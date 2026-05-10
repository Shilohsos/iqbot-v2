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
    msg_authenticate, msg_set_options, msg_get_profile,
    msg_get_balances, msg_get_initialization_data,
    msg_subscribe_position_state, msg_open_binary_option,
)
from utils.logger import get_logger

logger = get_logger("trade-executor")

# Fallback purchase buffer when server-provided deadtime is unavailable.
# IQ Option's actual deadtime per active comes from initialization data.
PURCHASE_BUFFER_SECONDS = 30


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
        {"status": "WIN",     "pnl": float, "trade_id": str, "balances": [...], ...}
        {"status": "LOSS",    "pnl": float, "trade_id": str, ...}
        {"status": "TIE",     "pnl": 0.0,   "trade_id": str, ...}
        {"status": "TIMEOUT", "error": str, "trade_id": str}
        {"status": "ERROR",   "error": str}

    "balances" key (when present) is the latest balances list as returned by
    IQ Option, so callers can refresh the cached DB balance without reopening
    a second WS connection.

    Never raises.
    """
    if timeout_result is None:
        timeout_result = duration_seconds + 60

    ws = None
    captured_balances = None
    try:
        # 1. Connect
        ws = await _connect_and_init(ssid, platform_id)

        # 2. Get balances → pick the right balance_id (and capture for caller)
        rid = gen_request_id()
        await ws.send(msg_get_balances(rid))
        balances_data = await _wait_for(ws, rid, timeout=5, expect_data=True)
        captured_balances = _normalize_balances(balances_data)
        balance_id = _pick_balance_id(captured_balances, balance_type)
        if not balance_id:
            return {"status": "ERROR", "error": f"No {balance_type} balance found"}

        # 3. Get initialization data → resolve pair name to active_id + profit %
        rid = gen_request_id()
        await ws.send(msg_get_initialization_data(rid))
        init_data = await _wait_for(ws, rid, timeout=10, expect_data=True)
        if not isinstance(init_data, dict):
            return {"status": "ERROR", "error": "Unexpected initialization data format"}
        active_id = _resolve_active_id(init_data, pair)
        if not active_id:
            return {"status": "ERROR", "error": f"Unknown pair: {pair}"}

        # Extract server-provided deadtime and check trading session
        option_type_id = 3 if duration_seconds <= 300 else 1  # 3=turbo, 1=binary
        active_meta = _get_active_meta(init_data, active_id, option_type_id)
        if not _can_trade_now(active_meta):
            return {"status": "ERROR", "error": f"{pair} is currently suspended or outside trading hours"}
        deadtime = active_meta["deadtime"]

        # 4. Subscribe to position updates (needed to receive position-changed events)
        rid = gen_request_id()
        await ws.send(msg_subscribe_position_state(rid))

        # 5. Place trade — retry once if IQ Option rejects for timing
        profit_percent = _get_profit_percent(init_data, active_id, option_type_id)
        trade_iq_id = None
        last_error = "Trade rejected"

        for attempt in range(2):
            expired_at = _aligned_expiry(int(time.time()), duration_seconds, option_type_id, deadtime)
            rid = gen_request_id()
            logger.info(
                f"Placing trade (attempt {attempt + 1}): pair={pair} active_id={active_id} "
                f"dir={direction} amount={amount} dur={duration_seconds}s "
                f"type={option_type_id} expired={expired_at} "
                f"(in {expired_at - int(time.time())}s) profit={profit_percent} bal_id={balance_id}"
            )
            await ws.send(msg_open_binary_option(
                active_id, direction, expired_at, amount,
                balance_id, profit_percent, option_type_id, rid,
            ))
            place_result = await _wait_for(ws, rid, timeout=10, expect_data=True)
            trade_iq_id = place_result.get("id") if isinstance(place_result, dict) else None
            if trade_iq_id:
                break
            last_error = (
                place_result.get("message", "Trade rejected")
                if isinstance(place_result, dict)
                else "No trade ID returned"
            )
            if attempt == 0 and "time for purchasing" in last_error.lower():
                # Wait just past the rejected boundary so _aligned_expiry picks the next one
                wait_secs = max(1, expired_at - int(time.time()) + 2)
                logger.warning(f"Timing rejection, waiting {wait_secs}s before retry")
                await asyncio.sleep(wait_secs)
            else:
                break

        if not trade_iq_id:
            return {"status": "ERROR", "error": last_error, "balances": captured_balances}

        logger.info(f"Trade placed id={trade_iq_id} pair={pair} dir={direction} amount={amount}")

        # 6. Wait for position result (handles both direct and wrapped message formats)
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
            if not isinstance(msg, dict):
                continue

            msg_name = msg.get("name", "")
            raw_body = msg.get("msg")
            body = raw_body if isinstance(raw_body, dict) else {}

            # IQ Option pushes portfolio events wrapped inside a "message" envelope:
            # {"name":"message","msg":{"name":"portfolio.position-changed","body":{...}}}
            if msg_name == "message" and body:
                inner_name = body.get("name", "")
                # inner body may be under "body" key or directly in msg
                inner_body = body.get("body") if isinstance(body.get("body"), dict) else body

                if inner_name in ("portfolio.position-changed", "position-changed"):
                    ext_id = inner_body.get("external_id") or inner_body.get("externalId")
                    if str(ext_id) == str(trade_iq_id) and inner_body.get("status") == "closed":
                        result = _build_result(inner_body, trade_iq_id, pair, direction, amount)
                        result["balances"] = await _try_refresh_balances(ws) or captured_balances
                        return result

                elif inner_name == "socket-option-closed":
                    opt_id = inner_body.get("id")
                    if str(opt_id) == str(trade_iq_id):
                        win_str = inner_body.get("win", "loose")
                        pnl = inner_body.get("profit_amount", 0) if win_str == "win" else 0
                        status = "WIN" if win_str == "win" else ("TIE" if win_str == "equal" else "LOSS")
                        result = {"status": status, "pnl": pnl, "trade_id": str(trade_iq_id),
                                  "pair": pair, "direction": direction, "amount": amount}
                        result["balances"] = await _try_refresh_balances(ws) or captured_balances
                        return result

            # Direct top-level position event (fallback / legacy format)
            elif msg_name in ("position-changed", "portfolio.position-changed"):
                ext_id = body.get("external_id") or body.get("externalId")
                if str(ext_id) == str(trade_iq_id) and body.get("status") == "closed":
                    result = _build_result(body, trade_iq_id, pair, direction, amount)
                    result["balances"] = await _try_refresh_balances(ws) or captured_balances
                    return result

            # Direct socket-option-closed (from setOptions sendResults=True)
            elif msg_name == "socket-option-closed":
                opt_id = body.get("id")
                if str(opt_id) == str(trade_iq_id):
                    win_str = body.get("win", "loose")
                    pnl = body.get("profit_amount", 0) if win_str == "win" else 0
                    status = "WIN" if win_str == "win" else ("TIE" if win_str == "equal" else "LOSS")
                    result = {"status": status, "pnl": pnl, "trade_id": str(trade_iq_id),
                              "pair": pair, "direction": direction, "amount": amount}
                    result["balances"] = await _try_refresh_balances(ws) or captured_balances
                    return result

            else:
                logger.debug(f"Result loop unmatched: name={msg_name}")

        return {
            "status": "TIMEOUT",
            "error": f"Trade result not received within {timeout_result}s",
            "trade_id": str(trade_iq_id),
            "balances": captured_balances,
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


async def fetch_balances(ssid: str, platform_id: int) -> list | None:
    """
    One-shot connection that just fetches balances and disconnects.
    Returns a list of balance dicts (each with id, type, amount, currency)
    or None if anything failed. Never raises.
    """
    ws = None
    try:
        ws = await _connect_and_init(ssid, platform_id)
        rid = gen_request_id()
        await ws.send(msg_get_balances(rid))
        balances_data = await _wait_for(ws, rid, timeout=5, expect_data=True)
        return _normalize_balances(balances_data)
    except Exception as e:
        logger.warning(f"fetch_balances failed: {e}")
        return None
    finally:
        if ws:
            try:
                await ws.close()
            except Exception:
                pass


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _connect_and_init(ssid: str, platform_id: int):
    """Connect, authenticate, setOptions, fetch profile. Returns the open WS."""
    headers = {
        "Cookie": f"ssid={ssid}; platform={platform_id}",
        "User-Agent": "iqbot-v2/1.0",
    }
    ws = await asyncio.wait_for(
        websockets.connect(WS_URL, additional_headers=headers, max_size=5 * 1024 * 1024),
        timeout=10,
    )

    # Authenticate
    rid = gen_request_id()
    await ws.send(msg_authenticate(ssid, rid))
    auth_resp = await _wait_for(ws, rid, timeout=10, expect_data=False)
    if not auth_resp.get("success", False):
        try:
            await ws.close()
        except Exception:
            pass
        raise RuntimeError(f"Authentication failed: {auth_resp}")

    # setOptions(sendResults=True) — enables socket-option-closed result events
    rid = gen_request_id()
    await ws.send(msg_set_options(rid))
    await _wait_for(ws, rid, timeout=5, expect_data=False)

    # Profile fetch — required to fully initialize the session for trading
    rid = gen_request_id()
    await ws.send(msg_get_profile(rid))
    await _wait_for(ws, rid, timeout=5, expect_data=True)

    return ws


async def _try_refresh_balances(ws):
    """After trade close, fetch fresh balances. Returns list or None."""
    try:
        rid = gen_request_id()
        await ws.send(msg_get_balances(rid))
        balances_data = await _wait_for(ws, rid, timeout=5, expect_data=True)
        return _normalize_balances(balances_data)
    except Exception:
        return None


def _get_active_meta(init_data: dict, active_id: int, option_type_id: int) -> dict:
    """Extract deadtime, isSuspended, and schedule for an active from init_data."""
    section = {3: "turbo", 1: "binary"}.get(option_type_id, "turbo")
    active = init_data.get(section, {}).get("actives", {}).get(str(active_id), {})
    # Server uses camelCase keys matching the TypeScript SDK DTO fields
    deadtime = active.get("deadtime", active.get("dead_time", PURCHASE_BUFFER_SECONDS))
    is_suspended = active.get("isSuspended", active.get("is_suspended", False))
    schedule = active.get("schedule", [])
    return {"deadtime": int(deadtime), "is_suspended": bool(is_suspended), "schedule": schedule}


def _can_trade_now(active_meta: dict) -> bool:
    """Return False if the active is suspended or outside its trading session."""
    if active_meta.get("is_suspended"):
        return False
    schedule = active_meta.get("schedule", [])
    if not schedule:
        return True  # no schedule = 24/7 (typical for OTC assets)
    now_ms = int(time.time() * 1000)
    for session in schedule:
        if isinstance(session, list) and len(session) >= 2:
            from_ts, to_ts = int(session[0]) * 1000, int(session[1]) * 1000
        elif isinstance(session, dict):
            from_ts = int(session.get("from", 0)) * 1000
            to_ts = int(session.get("to", 0)) * 1000
        else:
            continue
        if from_ts <= now_ms <= to_ts:
            return True
    return False


def _aligned_expiry(now: int, duration_seconds: int, option_type_id: int, deadtime: int = PURCHASE_BUFFER_SECONDS) -> int:
    """
    Compute the next valid expiry timestamp.

    Turbo (type=3): must be a multiple of duration_seconds. The SDK generates
        expiries as: now + size - (now % size). If the resulting boundary is
        within deadtime seconds, skip to the next one (server rejects purchases
        inside the deadtime window). The deadtime is active-specific and comes
        from initialization data.

    Binary (type=1): must align to a minute boundary at least duration_seconds away.
    """
    if option_type_id == 3:
        next_boundary = ((now // duration_seconds) + 1) * duration_seconds
        if next_boundary - now <= deadtime:
            next_boundary += duration_seconds
        return next_boundary
    else:
        # Add duration first, then round up to next minute boundary
        return (((now + duration_seconds) // 60) + 1) * 60


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
        if not isinstance(msg, dict):
            continue
        if msg.get("request_id") != request_id:
            continue
        if msg.get("name") == "result" and expect_data:
            continue  # this is just the ACK; wait for the actual data response
        body = msg.get("msg", {})
        if isinstance(body, bool):
            return {"success": body}
        if isinstance(body, dict) and "result" in body:
            return body["result"]
        return body  # may be list (balances) or dict; callers handle both
    raise asyncio.TimeoutError(f"No response for request {request_id[:8]}")


def _normalize_balances(balances_data) -> list:
    """Normalize a balances response into a flat list of balance dicts."""
    if isinstance(balances_data, list):
        return balances_data
    if isinstance(balances_data, dict):
        return balances_data.get("items", [])
    return []


def _pick_balance_id(balances: list, balance_type: str):
    """Return the balance id matching REAL (type=1) or PRACTICE (type=4)."""
    target_type = 1 if balance_type == "REAL" else 4
    for item in balances:
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
            if name == pair or name == f"front.{pair}" or name.replace("front.", "") == pair:
                return int(aid_str)
    return None


def _get_profit_percent(init_data: dict, active_id: int, option_type_id: int) -> float:
    """
    Return the profit % for an active for the specific option type.
    Falls back to other types only if the requested type is missing.
    """
    type_section = {3: "turbo", 1: "binary", 12: "blitz"}.get(option_type_id, "turbo")

    def _read(section: str):
        active = init_data.get(section, {}).get("actives", {}).get(str(active_id), {})
        comm = active.get("option", {}).get("profit", {}).get("commission", 0)
        if comm:
            return 100 - comm
        return None

    primary = _read(type_section)
    if primary is not None:
        return primary
    for atype in ("turbo", "binary", "blitz"):
        if atype == type_section:
            continue
        v = _read(atype)
        if v is not None:
            return v
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
