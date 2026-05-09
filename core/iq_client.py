"""
IQOptionClient — WebSocket client for IQ Option / Stockity.
Maintains connection, handles auth, subscriptions, and trade placement.
"""
import asyncio
import json
import time
import websockets
from core.iq_protocol import (
    WS_URL, gen_request_id,
    msg_authenticate, msg_set_options, msg_get_profile,
    msg_get_initialization_data, msg_get_candles,
    msg_subscribe_candles, msg_open_binary_option,
    msg_subscribe_position_state, msg_subscribe_balance,
    msg_get_balances,
)
from utils.logger import get_logger

logger = get_logger("iq-client")


class IQOptionClient:
    def __init__(self, ssid: str, platform_id: int):
        self.ssid = ssid
        self.platform_id = platform_id
        self.ws = None
        self.connected = False
        self.authenticated = False

        # State
        self.profile = None
        self.balances = {}       # balance_id -> dict
        self.actives = {}        # active_id -> {'name': 'EURUSD', 'profit_percent': 80, ...}
        self.actives_by_name = {}  # 'EURUSD-OTC' -> active_id

        # Pending request tracking
        self._pending = {}       # request_id -> asyncio.Future
        self._pending_data = {}  # request_id -> bool (True = wait for data response, not ACK)

        # Subscription handlers
        self._candle_handlers = []
        self._position_handlers = []
        self._balance_handlers = []
        self._on_reconnect_cb = None

        self._stop_event = asyncio.Event()

        # Server time tracking
        self._server_time = None
        self._server_time_local = None
        self._connecting = False

    async def _request(self, msg_fn, *args, timeout: float = 10, expect_data: bool = True):
        """Send a request and wait for response. expect_data=True means wait for data (not just ACK)."""
        rid = gen_request_id()
        fut = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        self._pending_data[rid] = expect_data
        await self.ws.send(msg_fn(rid, *args) if args else msg_fn(rid))
        return await asyncio.wait_for(fut, timeout=timeout)

    async def connect(self):
        """Connect, authenticate, send setOptions, fetch initialization data."""
        self._connecting = True
        logger.info("Connecting to IQ Option WS...")

        headers = {
            "Cookie": f"ssid={self.ssid}; platform={self.platform_id}",
            "User-Agent": "iqbot-v2/1.0",
        }

        self.ws = await websockets.connect(WS_URL, additional_headers=headers, max_size=5 * 1024 * 1024)
        self.connected = True

        # Start receive loop
        asyncio.create_task(self._receive_loop())

        # 1. Authenticate
        auth_result = await self._request(
            lambda rid: msg_authenticate(self.ssid, rid),
            timeout=10, expect_data=False
        )
        if isinstance(auth_result, dict) and not auth_result.get("success", False):
            raise RuntimeError(f"Authentication failed: {auth_result}")
        self.authenticated = True
        logger.info("Authenticated successfully")

        # 2. CRITICAL: setOptions(sendResults=True)
        await self._request(msg_set_options, timeout=5, expect_data=False)
        logger.info("setOptions confirmed")

        # 3. Fetch profile
        self.profile = await self._request(msg_get_profile, timeout=5)
        logger.info(f"Profile: {self.profile.get('user_id', 'N/A')}")

        # 4. Fetch balances
        await self._refresh_balances()

        # 5. Fetch initialization data (assets + payout %)
        await self._refresh_initialization_data()

        logger.info(
            f"Client ready. {len(self.balances)} balances, {len(self.actives)} actives"
        )
        self._connecting = False

    async def _refresh_balances(self):
        result = await self._request(msg_get_balances, timeout=5)
        items = result if isinstance(result, list) else result.get('items', [])
        for bal in items:
            self.balances[bal['id']] = bal

    async def _refresh_initialization_data(self):
        init_data = await self._request(msg_get_initialization_data, timeout=10)

        # Parse actives — they're dicts keyed by string IDs
        for atype in ['turbo', 'binary', 'blitz']:
            section = init_data.get(atype, {})
            actives_dict = section.get('actives', {})
            if isinstance(actives_dict, dict):
                for aid_str, active in actives_dict.items():
                    aid = int(aid_str)
                    name = active.get('name', f'unknown_{aid}')
                    profit_pct = 100
                    opt = active.get('option', {})
                    prof = opt.get('profit', {})
                    comm = prof.get('commission', 0)
                    if comm:
                        profit_pct = 100 - comm
                    self.actives[aid] = {
                        'name': name,
                        'profit_percent': profit_pct,
                        'is_suspended': active.get('is_suspended', False),
                        'type': atype,
                    }
                    self.actives_by_name[name] = aid
                    # Also index without 'front.' prefix
                    if name.startswith('front.'):
                        short = name[6:]
                        if short not in self.actives_by_name:
                            self.actives_by_name[short] = aid

    async def _receive_loop(self):
        while self.connected:
            try:
                msg_raw = await self.ws.recv()
                if isinstance(msg_raw, bytes):
                    # Binary message (ping, etc.) — ignore
                    continue
                msg = json.loads(msg_raw)
                await self._handle_message(msg)
            except websockets.ConnectionClosed:
                logger.warning("WS closed, reconnecting...")
                self.connected = False
                if not self._connecting:
                    await self._reconnect()
                break
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON received: {e} | raw={str(msg_raw)[:100]}")
            except Exception as e:
                logger.error(f"Receive error: {type(e).__name__}: {e}")

    async def _handle_message(self, msg: dict):
        name = msg.get("name")
        request_id = msg.get("request_id")
        body = msg.get("msg", {})

        # Pending request response
        if request_id and request_id in self._pending:
            expects_data = self._pending_data.get(request_id, False)

            # If this is a result ACK (name="result", success=true),
            # skip it if we're waiting for the actual data response
            if name == "result" and expects_data:
                # Don't resolve yet — wait for the actual data response
                # (the next message with the same request_id and the endpoint name)
                return

            # If we get a data response (name != "result"), resolve
            # OR if this is an ACK and we DON'T expect data, resolve
            fut = self._pending.pop(request_id)
            self._pending_data.pop(request_id, None)
            if not fut.done():
                # Unwrap result if present
                if isinstance(body, dict) and 'result' in body:
                    fut.set_result(body['result'])
                else:
                    fut.set_result(body)
            return

        # Time sync
        if name == "timeSync":
            self._server_time = body
            self._server_time_local = time.time()
            return

        # Subscription events
        microservice = msg.get("microserviceName")
        if microservice == "quotes" and name == "candle-generated":
            await self._dispatch_candle(body)
        elif name == "position-changed":
            for h in self._position_handlers:
                asyncio.create_task(h(body))
        elif name == "balance-changed":
            for h in self._balance_handlers:
                asyncio.create_task(h(body))

    async def _dispatch_candle(self, body: dict):
        active_id = body.get('active_id')
        size = body.get('size')
        pair = self.actives.get(active_id, {}).get('name', f'unknown_{active_id}')
        for h in self._candle_handlers:
            asyncio.create_task(h(pair, size, body))

    def now(self) -> float:
        """Server-corrected timestamp for expiry calculations."""
        if self._server_time and self._server_time_local:
            return (self._server_time / 1000) + (time.time() - self._server_time_local)
        return time.time()

    async def subscribe_candles(self, pair: str, timeframe: int):
        active_id = self.actives_by_name.get(pair)
        if not active_id:
            logger.error(f"Unknown asset: {pair}")
            return False
        result = await self._request(
            lambda rid: msg_subscribe_candles(active_id, timeframe, rid),
            timeout=5, expect_data=False
        )
        if isinstance(result, dict) and result.get('success') is False:
            logger.warning(f"Candle subscription rejected for {pair}@{timeframe}: {result}")
            return False
        return True

    def on_candle_close(self, handler):
        """Decorator to register a candle close handler."""
        self._candle_handlers.append(handler)
        return handler

    def on_position_changed(self, handler):
        self._position_handlers.append(handler)
        return handler

    def on_balance_changed(self, handler):
        self._balance_handlers.append(handler)
        return handler

    async def get_candles(
        self, pair: str, timeframe: int, count: int = 50
    ) -> list:
        active_id = self.actives_by_name.get(pair)
        if not active_id:
            return []
        to_time = int(self.now())
        result = await self._request(
            lambda rid: msg_get_candles(active_id, timeframe, count, to_time, rid),
            timeout=15
        )
        return result.get('candles', []) if isinstance(result, dict) else []

    async def place_binary_option(
        self, pair: str, direction: str,
        duration_seconds: int, amount: float,
        balance_id: int
    ) -> dict:
        """
        direction: 'call' or 'put'
        duration_seconds: 60, 120, 180, 300, 600, etc.
        Uses option_type_id=3 (turbo) for ≤5min, 1 (binary) for >5min.
        """
        active = self.actives_by_name.get(pair)
        if not active:
            raise ValueError(f"Unknown pair: {pair}")

        active_data = self.actives[active]
        if active_data.get('is_suspended'):
            raise RuntimeError(f"{pair} is suspended")

        option_type_id = 3 if duration_seconds <= 300 else 1
        expired_at = int(self.now()) + duration_seconds

        # Round to next minute boundary for binary
        if option_type_id == 1:
            expired_at = ((expired_at // 60) + 1) * 60

        _active = active
        _direction = direction
        _expired_at = expired_at
        _amount = amount
        _balance_id = balance_id
        _profit_percent = active_data['profit_percent']
        _option_type_id = option_type_id

        result = await self._request(
            lambda rid: msg_open_binary_option(
                _active, _direction, _expired_at,
                _amount, _balance_id, _profit_percent,
                _option_type_id, rid
            ),
            timeout=10
        )
        return result

    async def _reconnect(self):
        """Exponential backoff reconnect."""
        delay = 1
        while not self.connected:
            await asyncio.sleep(delay)
            try:
                await self.connect()
                # Re-subscribe candles via callback
                if self._on_reconnect_cb:
                    await self._on_reconnect_cb()
                logger.info("Reconnected successfully")
                return
            except Exception as e:
                logger.error(f"Reconnect failed: {e}")
                delay = min(delay * 2, 60)

    def on_reconnect(self, handler):
        """Register a callback for post-reconnect re-subscriptions."""
        self._on_reconnect_cb = handler
        return handler

    async def run_forever(self):
        """Block until stop() is called."""
        await self._stop_event.wait()

    def stop(self):
        self._stop_event.set()
