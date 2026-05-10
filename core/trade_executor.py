"""
V4 Hybrid: delegates trade execution to the iq-trader Node.js microservice,
which uses the official @quadcode-tech/client-sdk-js SDK.

The Node service maintains persistent per-SSID SDK connections, places the
trade, waits for the position-closed event, and returns the full result in
one HTTP response.  Python only needs to POST and parse JSON.
"""
import aiohttp
from utils.logger import get_logger

logger = get_logger("trade-executor")

TRADER_URL = "http://localhost:3001"


async def execute_trade(
    ssid: str,
    platform_id: int,
    pair: str,
    direction: str,
    amount: float,
    duration_seconds: int,
    balance_type: str = 'PRACTICE',
) -> dict:
    """
    Returns a dict with at least:
      { 'status': 'OPENED', 'tradeId': <int>,
        'result': 'WIN'|'LOSS'|'TIE'|'TIMEOUT',
        'pnl': <float> }
    or on error:
      { 'status': 'ERROR', 'error': '<message>' }
    """
    # Give the HTTP call plenty of time: trade duration + 120 s buffer
    timeout = aiohttp.ClientTimeout(total=duration_seconds + 120)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f'{TRADER_URL}/trade',
                json={
                    'ssid':            ssid,
                    'platformId':      platform_id,
                    'pair':            pair,
                    'direction':       direction,
                    'amount':          amount,
                    'durationSeconds': duration_seconds,
                    'balanceType':     balance_type,
                },
            ) as resp:
                data = await resp.json()
                logger.info(f"iq-trader response: {data}")
                return data
    except aiohttp.ClientConnectorError:
        logger.error("iq-trader unreachable on :3001 — is the iq-trader PM2 process running?")
        return {'status': 'ERROR', 'error': 'Trade service offline. Try again shortly.'}
    except Exception as e:
        logger.exception(f"execute_trade error: {e}")
        return {'status': 'ERROR', 'error': str(e)}


async def fetch_balances(ssid: str, platform_id: int) -> dict:
    """
    Returns { 'real': {'amount': X, 'currency': 'USD'}, 'demo': {...} }
    or {} on error.
    """
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f'{TRADER_URL}/balance',
                json={'ssid': ssid, 'platformId': platform_id},
            ) as resp:
                return await resp.json()
    except Exception as e:
        logger.error(f"fetch_balances error: {e}")
        return {}
