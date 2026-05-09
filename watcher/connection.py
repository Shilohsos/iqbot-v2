"""
Account Watcher — one process per user.
Maintains IQ Option WS connection for a specific user.
Listens for trade commands via Redis, executes trades,
syncs balance and position changes back via Redis.
"""
import asyncio
from core.iq_client import IQOptionClient
from core.iq_protocol import gen_request_id, msg_subscribe_position_state, msg_subscribe_balance
from core.redis_bus import subscribe, publish
from database.models.accounts import get_account_credentials, update_balance
from database.models.bias import get_current_bias
from database.models.trades import log_trade, update_trade_result
from utils.logger import get_logger

logger = get_logger("watcher")


class UserWatcher:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.client: IQOptionClient | None = None
        self.account = None
        self._trade_listener_task: asyncio.Task | None = None

    async def start(self):
        self.account = get_account_credentials(self.user_id)
        if not self.account:
            logger.error(f"No account for user {self.user_id}")
            return

        # Refresh SSID if stale
        from core.iq_login import refresh_ssid_if_stale
        fresh_ssid = await refresh_ssid_if_stale(self.account['id'])
        if not fresh_ssid:
            logger.error(f"Could not get SSID for user {self.user_id}")
            return

        self.client = IQOptionClient(
            ssid=fresh_ssid,
            platform_id=self.account['platform_id'],
        )
        await self.client.connect()

        # Sync initial balance to DB
        for bal_id, bal in self.client.balances.items():
            update_balance(
                self.user_id, bal_id,
                bal.get('amount', 0),
                bal.get('currency', 'USD')
            )

        # Subscribe to position + balance changes (fire-and-forget; confirmations
        # arrive as normal WebSocket messages and are logged by the client)
        req_id = gen_request_id()
        await self.client.ws.send(msg_subscribe_position_state(req_id))
        logger.info(f"Sent position-state subscription (req_id={req_id}) for user {self.user_id}")
        for bal_id in self.client.balances:
            req_id = gen_request_id()
            await self.client.ws.send(msg_subscribe_balance(bal_id, req_id))
            logger.info(f"Sent balance subscription bal_id={bal_id} (req_id={req_id}) for user {self.user_id}")

        @self.client.on_position_changed
        async def handle_position(data):
            await self._handle_position(data)

        @self.client.on_balance_changed
        async def handle_balance(data):
            await self._handle_balance(data)

        # Listen for trade requests on Redis
        self._trade_listener_task = asyncio.create_task(self._listen_trade_requests())
        self._trade_listener_task.add_done_callback(
            lambda t: logger.error(f"Trade listener exited for user {self.user_id}: {t.exception()}")
            if not t.cancelled() and t.exception() else None
        )

        await self.client.run_forever()

    async def _listen_trade_requests(self):
        async for msg in subscribe(f'trade-requests:{self.user_id}'):
            try:
                await self._execute_trade(msg)
            except Exception as e:
                logger.exception(f"Trade execution error: {e}")
                await publish(f'trade-results:{self.user_id}', {
                    'request_token': msg.get('request_token'),
                    'status': 'ERROR',
                    'error': str(e),
                })

    async def _execute_trade(self, req: dict):
        """
        req = {
          'request_token': '<uuid>',
          'pair': 'EURUSD-OTC',
          'amount': 10,
          'duration_seconds': 60,
          'balance_type': 'REAL' | 'PRACTICE',
        }
        """
        pair = req['pair']
        amount = req['amount']
        duration = req['duration_seconds']

        # Read current bias from DB
        bias = get_current_bias(pair, duration)
        if not bias:
            await publish(f'trade-results:{self.user_id}', {
                'request_token': req['request_token'],
                'status': 'NO_BIAS',
                'message': f'No bias data available for {pair}@{duration}s',
            })
            return

        # Determine direction
        if bias['bullish_percent'] >= 55:
            direction = 'call'
        elif bias['bullish_percent'] <= 45:
            direction = 'put'
        else:
            await publish(f'trade-results:{self.user_id}', {
                'request_token': req['request_token'],
                'status': 'NEUTRAL_BIAS',
                'message': 'Market is neutral. No clear direction.',
                'bias': bias,
            })
            return

        # Pick balance
        balance = self._pick_balance(req.get('balance_type', 'PRACTICE'))
        if not balance:
            await publish(f'trade-results:{self.user_id}', {
                'request_token': req['request_token'],
                'status': 'NO_BALANCE',
            })
            return

        # Place trade
        result = await self.client.place_binary_option(
            pair=pair,
            direction=direction,
            duration_seconds=duration,
            amount=amount,
            balance_id=balance['id'],
        )

        # Log to DB
        trade_id = log_trade(
            user_id=self.user_id,
            pair=pair,
            direction=direction,
            amount=amount,
            duration_seconds=duration,
            iq_option_id=result.get('id'),
            bias_at_entry=bias['bullish_percent'],
            confidence_at_entry=bias['confidence'],
        )

        # Notify bot — trade opened
        await publish(f'trade-results:{self.user_id}', {
            'request_token': req['request_token'],
            'status': 'OPENED',
            'trade_id': trade_id,
            'direction': direction,
            'pair': pair,
            'amount': amount,
            'duration': duration,
            'bias': bias,
        })

    async def _handle_position(self, data):
        """Position closed event → update DB → notify bot."""
        if data.get('status') != 'closed':
            return
        iq_option_id = data.get('external_id')
        pnl = data.get('close_profit', 0)
        close_reason = data.get('close_reason')  # 'win' | 'loose' | 'equal'
        result = 'WIN' if close_reason == 'win' else (
            'TIE' if close_reason == 'equal' else 'LOSS'
        )
        update_trade_result(iq_option_id, result, pnl)
        await publish(f'trade-results:{self.user_id}', {
            'status': 'CLOSED',
            'iq_option_id': iq_option_id,
            'result': result,
            'pnl': pnl,
        })

    async def _handle_balance(self, data):
        update_balance(
            self.user_id,
            data['user_balance_id'],
            data['amount'],
            data.get('currency', 'USD'),
        )
        await publish(f'balance-updates:{self.user_id}', data)

    def _pick_balance(self, balance_type: str):
        target = 1 if balance_type == 'REAL' else 4  # 1=Real, 4=Practice
        for bal in self.client.balances.values():
            if bal['type'] == target:
                return bal
        return None
