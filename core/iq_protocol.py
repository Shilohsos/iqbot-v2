"""
Official Quadcode WebSocket protocol for IQ Option / Stockity.
Reference: @quadcode-tech/client-sdk-js v1.3.21
"""
import json
import time
import uuid

# Endpoint identifiers
WS_URL = "wss://iqoption.com/echo/websocket"


def gen_request_id() -> str:
    return uuid.uuid4().hex[:16]


def msg_authenticate(ssid: str, request_id: str) -> str:
    """Initial auth handshake."""
    return json.dumps({
        "name": "authenticate",
        "request_id": request_id,
        "msg": {
            "ssid": ssid,
            "protocol": 3,
            "session_id": "",
            "client_session_id": "",
        }
    })


def msg_set_options(request_id: str) -> str:
    """
    CRITICAL: Must be sent immediately after auth succeeds.
    Without this, socket-option-opened/closed events are NOT sent.
    """
    return json.dumps({
        "name": "setOptions",
        "request_id": request_id,
        "msg": {"sendResults": True}
    })


def msg_get_profile(request_id: str) -> str:
    """Fetch user profile data."""
    return json.dumps({
        "name": "sendMessage",
        "request_id": request_id,
        "msg": {
            "name": "core.get-profile",
            "version": "1.0",
            "body": {}
        }
    })


def msg_get_initialization_data(request_id: str) -> str:
    """
    Fetches all binary/turbo/blitz active definitions including current
    profit_percent per asset. Cache the response, refresh every 5 min.
    """
    return json.dumps({
        "name": "sendMessage",
        "request_id": request_id,
        "msg": {
            "name": "binary-options.get-initialization-data",
            "version": "3.0",
            "body": {}
        }
    })


def msg_get_candles(
    active_id: int, size_seconds: int, count: int,
    to_time: int, request_id: str
) -> str:
    """
    CORRECTED endpoint name: 'quotes-history.get-candles' (not 'get-candles').
    """
    return json.dumps({
        "name": "sendMessage",
        "request_id": request_id,
        "msg": {
            "name": "quotes-history.get-candles",
            "version": "2.0",
            "body": {
                "active_id": active_id,
                "size": size_seconds,
                "to": to_time,
                "count": count,
                "only_closed": True,
                "kind": "candles",
                "split_normalization": True,
            }
        }
    })


def msg_subscribe_candles(
    active_id: int, size_seconds: int, request_id: str
) -> str:
    """Subscribes to live candle-generated events."""
    return json.dumps({
        "name": "subscribeMessage",
        "request_id": request_id,
        "msg": {
            "name": "candle-generated",
            "version": "1.0",
            "params": {
                "routingFilters": {
                    "active_id": active_id,
                    "size": size_seconds,
                }
            }
        }
    })


def msg_open_binary_option(
    active_id: int, direction: str, expired_at: int,
    price: float, balance_id: int, profit_percent: float,
    option_type_id: int, request_id: str
) -> str:
    """
    Open a binary/turbo/blitz option.

    option_type_id values:
      1  = Binary  (uses 'expired')
      3  = Turbo   (uses 'expired')
      12 = Blitz   (uses 'expiration_size' instead of 'expired')

    direction: 'call' or 'put'
    """
    body = {
        "active_id": active_id,
        "direction": direction,
        "expired": expired_at,
        "option_type_id": option_type_id,
        "price": price,
        "user_balance_id": balance_id,
        "profit_percent": profit_percent,
    }
    return json.dumps({
        "name": "sendMessage",
        "request_id": request_id,
        "msg": {
            "name": "binary-options.open-option",
            "version": "2.0",  # CORRECTED — was 1.0
            "body": body,
        }
    })


def msg_subscribe_position_state(request_id: str) -> str:
    """Subscribe to position updates (open/closed/changed)."""
    return json.dumps({
        "name": "sendMessage",
        "request_id": request_id,
        "msg": {
            "name": "portfolio.subscribe-positions",
            "version": "1.0",
            "body": {
                "frequency": "realtime",
                "ids": []
            }
        }
    })


def msg_subscribe_balance(balance_id: int, request_id: str) -> str:
    """Subscribe to balance change events."""
    return json.dumps({
        "name": "sendMessage",
        "request_id": request_id,
        "msg": {
            "name": "marginal-portfolio.subscribe-balance-changed",
            "version": "1.0",
            "body": {}
        }
    })


def msg_get_balances(request_id: str) -> str:
    """Get all available balances (demo, real, tournament)."""
    return json.dumps({
        "name": "sendMessage",
        "request_id": request_id,
        "msg": {
            "name": "balances.get-available-balances",
            "version": "1.0",
            "body": {"types_ids": [1, 4]}  # 1=Real, 4=Practice
        }
    })
