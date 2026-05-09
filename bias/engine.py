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
        # Fetch the last 50 candles for this pair+tf
        candles = await client.get_candles(pair, timeframe, count=50)
        if not candles:
            logger.warning(f"No candles returned for {pair} @ {timeframe}s")
            return

        bias = calculate_bias(candles)
        if not bias:
            logger.warning(f"Bias calculation returned None for {pair} @ {timeframe}s")
            return

        # Persist
        upsert_bias(
            asset=pair,
            timeframe_seconds=timeframe,
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
