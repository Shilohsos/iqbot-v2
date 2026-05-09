"""
Bias engine main loop.
Single long-lived connection to IQ Option.
Subscribes to candles for all configured pairs and timeframes.
On candle close: recompute bias → write DB → publish Redis.
"""
import asyncio
from core.iq_client import IQOptionClient
from core.redis_bus import publish
from database.models.bias import upsert_bias
from bias.bias_calculator import calculate_bias
from config import BIAS_PAIRS, BIAS_TIMEFRAMES, BIAS_API_CREDENTIALS
from utils.logger import get_logger

logger = get_logger("bias-engine")


async def run_bias_engine():
    """
    Single long-lived connection. Subscribes to candles for every (pair, timeframe) combo.
    On each candle close → recompute bias → write to DB → publish on Redis.
    """
    ssid = BIAS_API_CREDENTIALS['ssid']
    platform_id = BIAS_API_CREDENTIALS['platform_id']

    if not ssid:
        logger.error("BIAS_ENGINE_SSID not set in .env — bias engine cannot start")
        return

    client = IQOptionClient(ssid=ssid, platform_id=platform_id)
    await client.connect()

    # Limit concurrent get_candles calls to avoid flooding the API
    _candle_semaphore = asyncio.Semaphore(4)

    # Resubscribe helper
    async def subscribe_all():
        for pair in BIAS_PAIRS:
            for tf in BIAS_TIMEFRAMES:
                ok = await client.subscribe_candles(pair, tf)
                if ok:
                    logger.info(f"Subscribed: {pair} @ {tf}s")
                else:
                    logger.warning(f"Failed to subscribe: {pair} @ {tf}s")

    # Register reconnect handler
    @client.on_reconnect
    async def on_reconnect():
        logger.info("Re-subscribing candles after reconnect...")
        await subscribe_all()

    # Initial subscription
    await subscribe_all()

    # Register candle close handler
    @client.on_candle_close
    async def handle_candle(pair: str, timeframe: int, candle: dict):
        logger.info(f"CANDLE EVENT: {pair} @ {timeframe}s phase={candle.get('phase','?')} close={candle.get('close')}")
        # Fetch the last 50 candles — throttled to avoid concurrent API floods
        async with _candle_semaphore:
            candles = await client.get_candles(pair, timeframe, count=50)
        if not candles:
            logger.warning(f"No candles returned for {pair} @ {timeframe}s")
            return

        bias = calculate_bias(candles)
        if not bias:
            logger.warning(f"Bias calculation returned None for {pair} @ {timeframe}s")
            return

        # Persist (pass live suspension status so the trade keyboard filters it out)
        active_id = client.actives_by_name.get(pair)
        is_suspended = client.actives.get(active_id, {}).get('is_suspended', False) if active_id else False
        upsert_bias(
            asset=pair,
            timeframe_seconds=timeframe,
            is_suspended=is_suspended,
            **bias,
        )

        # Notify watchers
        await publish('bias-updates', {
            'asset': pair,
            'timeframe': timeframe,
            **bias,
        })

        logger.info(
            f"[{pair}@{timeframe}s] bias={bias['bullish_percent']}% "
            f"conf={bias['confidence']}%"
        )

    # Keep alive
    await client.run_forever()


if __name__ == '__main__':
    asyncio.run(run_bias_engine())
