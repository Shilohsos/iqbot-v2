"""
One-shot trade executor: connect → authenticate → place → wait for result → disconnect.
No persistent state, no reconnect loops. Every trade is a self-contained WS cycle.
"""
import asyncio
import json
import time
import websockets
from core.iq_protocol import (
    WS_URL, gen_request_id,
    msg_authenticate, msg_set_options,
    msg_get_balances, msg_get_initialization_data,
    msg_subscribe_position_state, msg_open_binary_option,
)
from utils.logger import get_logger

logger = get_logger("trade-executor")


async def execute_trade(
    ssid: str,
    platform_id: int,
    pair: str,
    direction: str,
    amount: float,
    duration_seconds: int,
    balance_type: str,
    timeout_result: int = None,
) -> dict:
    """
    Connect to IQ Option, place a binary option, wait for result, disconnect.

    Returns one of:
        {"status": "WIN",     "pnl": float, "trade_id": str, "pair": ..., ...}
        {"status": "LOSS",    "pnl": float, "trade_id": str, ...}
        {"status": "TIE",     "pnl": 0.0,   "trade_id": str, ...}
        {"status": "TIMEOUT", "error": str, "trade_id": str}
        {"status": "ERROR",   "error": str}

    Never raises.
    """
    if timeout_result is None:
        timeout_result = duration_seconds + 60

    ws = None
    try:
        # 1. Connect
        headers = {
            "Cookie": f"ssid={ssid}; platform={platform_id}",
            "User-Agent": "iqbot-v2/1.0",
        }
        ws = await asyncio.wait_for(
            websockets.connect(WS_URL, additional_headers=headers, max_size=5 * 1024 * 1024),
            timeout=10,
        )

        # 2. Authenticate
        rid = gen_request_id()
        await ws.send(msg_authenticate(ssid, rid))
        auth_resp = await _wait_for(ws, rid, timeout=10, expect_data=False)
        # IQ Option auth response: msg is True (bool) on success, False on failure
        if isinstance(auth_resp, bool):
            if not auth_resp:
                return {"status": "ERROR", "error": "Authentication failed — invalid SSID"}
        elif not auth_resp.get("success", False):
            return {"status": "ERROR", "error": f"Authentication failed: {auth_resp}"}

        # 3. setOptions — critical: enables socket-option-closed result events
        rid = gen_request_id()
        await ws.send(msg_set_options(rid))
        await _wait_for(ws, rid, timeout=5, expect_data=False)

        # 4. Get balances → pick the right balance_id
        rid = gen_request_id()
        await ws.send(msg_get_balances(rid))
        balances_data = await _wait_for(ws, rid, timeout=5, expect_data=True)
        balance_id = _pick_balance_id(balances_data, balance_type)
        if not balance_id:
            return {"status": "ERROR", "error": f"No {balance_type} balance found"}

        # 5. Get initialization data → resolve pair name to active_id + profit %
        rid = gen_request_id()
        await ws.send(msg_get_initialization_data(rid))
        init_data = await _wait_for(ws, rid, timeout=10, expect_data=True)
        active_id = _resolve_active_id(init_data, pair)
        if not active_id:
            return {"status": "ERROR", "error": f"Unknown pair: {pair}"}

        # 6. Subscribe to position updates (needed to receive position-changed events)
        rid = gen_request_id()
        await ws.send(msg_subscribe_position_state(rid))

        # 7. Place trade
        rid = gen_request_id()
        option_type_id = 3 if duration_seconds <= 300 else 1  # 3=turbo, 1=binary
        expired_at = int(time.time()) + duration_seconds
        if option_type_id == 1:  # binary: align to next minute boundary
            expired_at = ((expired_at // 60) + 1) * 60
        profit_percent = _get_profit_percent(init_data, active_id)

        await ws.send(msg_open_binary_option(
            active_id, direction, expired_at, amount,
            balance_id, profit_percent, option_type_id, rid,
        ))
        place_result = await _wait_for(ws, rid, timeout=10, expect_data=True)
        trade_iq_id = place_result.get("id") if isinstance(place_result, dict) else None
        if not trade_iq_id:
            error_msg = (
                place_result.get("message", "Trade rejected")
                if isinstance(place_result, dict)
                else "No trade ID returned"
            )
            return {"status": "ERROR", "error": error_msg}

        logger.info(f"Trade placed id={trade_iq_id} pair={pair} dir={direction} amount={amount}")

        # 8. Wait for position result (position-changed or socket-option-closed)
        deadline = time.time() + timeout_result
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 10))
            except asyncio.TimeoutError:
                continue

            if isinstance(raw, bytes):
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_name = msg.get("name", "")
            body = msg.get("msg", {})

            if msg_name in ("position-changed", "portfolio.position-changed"):
                if body.get("external_id") == trade_iq_id and body.get("status") == "closed":
                    return _build_result(body, trade_iq_id, pair, direction, amount)

            elif msg_name == "socket-option-closed":
                if body.get("id") == trade_iq_id:
                    win_str = body.get("win", "loose")
                    pnl = body.get("profit_amount", 0) if win_str == "win" else 0
                    status = "WIN" if win_str == "win" else ("TIE" if win_str == "equal" else "LOSS")
                    return {
                        "status": status, "pnl": pnl,
                        "trade_id": str(trade_iq_id),
                        "pair": pair, "direction": direction, "amount": amount,
                    }

        return {
            "status": "TIMEOUT",
            "error": f"Trade result not received within {timeout_result}s",
            "trade_id": str(trade_iq_id),
        }

    except asyncio.TimeoutError:
        return {"status": "ERROR", "error": "IQ Option request timed out"}
    except websockets.ConnectionClosed as e:
        return {"status": "ERROR", "error": f"Connection closed unexpectedly: {e}"}
    except Exception as e:
        logger.exception(f"execute_trade error: {e}")
        return {"status": "ERROR", "error": str(e)}
    finally:
        if ws:
            try:
                await ws.close()
            except Exception:
                pass


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _wait_for(ws, request_id: str, timeout: float = 10, expect_data: bool = True) -> dict:
    """
    Read WS messages until one matches request_id.
    expect_data=True: skip the "result" ACK and return the actual data response.
    expect_data=False: return on the first matching message (used for auth/setOptions).
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 2))
        except asyncio.TimeoutError:
            continue
        if isinstance(raw, bytes):
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if msg.get("request_id") != request_id:
            continue
        if msg.get("name") == "result" and expect_data:
            continue  # this is just the ACK; wait for the actual data response
        body = msg.get("msg", {})
        if isinstance(body, dict) and "result" in body:
            return body["result"]
        return body
    raise asyncio.TimeoutError(f"No response for request {request_id[:8]}")


def _pick_balance_id(balances_data, balance_type: str):
    """Return the balance id matching REAL (type=1) or PRACTICE (type=4)."""
    target_type = 1 if balance_type == "REAL" else 4
    items = balances_data if isinstance(balances_data, list) else balances_data.get("items", [])
    for item in items:
        if item.get("type") == target_type:
            return item["id"]
    return None


def _resolve_active_id(init_data: dict, pair: str):
    """Find active_id for a pair name (handles both 'EURUSD-OTC' and 'front.EURUSD-OTC')."""
    for atype in ("turbo", "binary", "blitz"):
        actives = init_data.get(atype, {}).get("actives", {})
        if not isinstance(actives, dict):
            continue
        for aid_str, active in actives.items():
            name = active.get("name", "")
            if name == pair or name == f"front.{pair}":
                return int(aid_str)
    return None


def _get_profit_percent(init_data: dict, active_id: int) -> float:
    """Return the profit % for an active. Defaults to 80% if not found."""
    for atype in ("turbo", "binary", "blitz"):
        active = init_data.get(atype, {}).get("actives", {}).get(str(active_id), {})
        comm = active.get("option", {}).get("profit", {}).get("commission", 0)
        if comm:
            return 100 - comm
    return 80.0


def _build_result(body: dict, trade_iq_id, pair: str, direction: str, amount: float) -> dict:
    """Construct the result dict from a position-changed event body."""
    pnl = body.get("close_profit", 0)
    close_reason = body.get("close_reason", "")
    status = "WIN" if close_reason == "win" else ("TIE" if close_reason == "equal" else "LOSS")
    return {
        "status": status, "pnl": pnl,
        "trade_id": str(trade_iq_id),
        "pair": pair, "direction": direction, "amount": amount,
    }
