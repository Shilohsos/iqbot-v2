"""
Redis pub/sub helpers for inter-pillar communication.
Channels:
  bias-updates          → Pillar 1 publishes, anyone can subscribe
  trade-requests:{uid}  → Pillar 3 publishes, Pillar 2 subscribes
  trade-results:{uid}   → Pillar 2 publishes, Pillar 3 subscribes
  balance-updates:{uid} → Pillar 2 publishes, Pillar 3 subscribes
"""
import asyncio
import json
import os
import redis.asyncio as aioredis
from typing import Optional, Callable, Any

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')

_pool: Optional[aioredis.ConnectionPool] = None
_pubsub: Optional[aioredis.client.PubSub] = None


async def _get_redis():
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(REDIS_URL)
    return aioredis.Redis(connection_pool=_pool)


async def publish(channel: str, data: dict) -> int:
    """Publish a JSON-serialized message to a channel."""
    r = await _get_redis()
    return await r.publish(channel, json.dumps(data))


async def subscribe(channel: str):
    """
    Async generator that yields messages from a channel.
    Usage: async for msg in subscribe('trade-requests:123'):
    """
    r = await _get_redis()
    ps = r.pubsub()
    await ps.subscribe(channel)
    try:
        async for message in ps.listen():
            if message['type'] == 'message':
                try:
                    yield json.loads(message['data'])
                except json.JSONDecodeError:
                    yield message['data']
    finally:
        await ps.unsubscribe(channel)


async def subscribe_once(
    channel: str,
    filter_fn: Optional[Callable[[dict], bool]] = None,
    timeout: float = 10.0
) -> Optional[dict]:
    """
    Wait for a single message matching filter_fn on a channel.
    Returns the first match or raises TimeoutError.
    """
    async def _listen():
        r = await _get_redis()
        ps = r.pubsub()
        await ps.subscribe(channel)
        try:
            async for message in ps.listen():
                if message['type'] != 'message':
                    continue
                try:
                    data = json.loads(message['data'])
                except json.JSONDecodeError:
                    data = message['data']
                if filter_fn is None or filter_fn(data):
                    return data
        finally:
            await ps.unsubscribe(channel)

    return await asyncio.wait_for(_listen(), timeout=timeout)


async def close():
    """Close Redis connection pool."""
    global _pool
    if _pool:
        await _pool.disconnect()
        _pool = None
