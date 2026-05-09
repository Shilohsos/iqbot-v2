"""
Quadcode OAuth 2.0 PKCE implementation.
Reference: Quadcode OAuth API docs — auth/oauth.v5
  GET  {OAUTH_BASE}/auth/oauth.v5/authorize  → browser redirect for user login
  POST {OAUTH_BASE}/auth/oauth.v5/token      → exchange code or refresh token for SSID

The access_token returned by the token endpoint IS the SSID used for WS auth.
The refresh_token lets us get new SSIDs without ever re-prompting for a password.
"""
import base64
import hashlib
import os
import secrets
import time
from typing import Optional

import aiohttp

from utils.logger import get_logger

logger = get_logger("iq-oauth")

OAUTH_BASE = os.getenv('OAUTH_BASE_URL', 'https://auth.iqoption.com')
_AUTHORIZE_PATH = '/auth/oauth.v5/authorize'
_TOKEN_PATH = '/auth/oauth.v5/token'

# ── In-memory pending state (state_token → {telegram_id, code_verifier, expires}) ──
# Keyed by the opaque `state` param sent to the authorization server.
# A pending entry expires after 10 minutes — after that the user must restart.
_PENDING_TTL = 600
_pending: dict[str, dict] = {}


# ── PKCE helpers ─────────────────────────────────────────────────────────────

def _code_verifier() -> str:
    """Cryptographically random 96-char URL-safe string (within 43-128 allowed)."""
    return secrets.token_urlsafe(72)[:96]


def _code_challenge(verifier: str) -> str:
    """BASE64URL(SHA256(verifier)) — RFC 7636 S256 method."""
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


# ── Pending state management ──────────────────────────────────────────────────

def register_pending(telegram_id: int) -> tuple[str, str]:
    """
    Create and store a pending OAuth state.
    Returns (state_token, code_verifier).
    The caller should pass state_token to build_authorize_url() and
    keep nothing — the verifier is stored here keyed by state.
    """
    _expire_old()
    state = secrets.token_urlsafe(32)
    verifier = _code_verifier()
    _pending[state] = {
        'telegram_id': telegram_id,
        'code_verifier': verifier,
        'expires': time.monotonic() + _PENDING_TTL,
    }
    return state, verifier


def pop_pending(state: str) -> Optional[dict]:
    """Retrieve and remove a pending entry; returns None if missing or expired."""
    _expire_old()
    entry = _pending.pop(state, None)
    if entry and time.monotonic() > entry['expires']:
        return None
    return entry


def _expire_old():
    now = time.monotonic()
    expired = [k for k, v in _pending.items() if now > v['expires']]
    for k in expired:
        _pending.pop(k, None)


# ── URL builder ───────────────────────────────────────────────────────────────

def build_authorize_url(
    client_id: int,
    redirect_uri: str,
    state: str,
    verifier: str,
    scope: str = 'full offline_access',
    aff: Optional[int] = None,
) -> str:
    """
    Build the GET /auth/oauth.v5/authorize URL.
    The `state` and `verifier` come from register_pending().
    """
    challenge = _code_challenge(verifier)
    params = [
        ('response_type', 'code'),
        ('client_id', str(client_id)),
        ('redirect_uri', redirect_uri),
        ('scope', scope),
        ('state', state),
        ('code_challenge', challenge),
        ('code_challenge_method', 'S256'),
    ]
    if aff is not None:
        params.append(('aff', str(aff)))

    qs = '&'.join(f'{k}={v}' for k, v in params)
    return f"{OAUTH_BASE}{_AUTHORIZE_PATH}?{qs}"


# ── Token exchange ────────────────────────────────────────────────────────────

async def exchange_code(
    client_id: int,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict:
    """
    POST /auth/oauth.v5/token with grant_type=authorization_code.
    Returns the full token response dict:
      access_token (= SSID), token_type, expires_in, refresh_token, scope.
    Raises RuntimeError with a descriptive message on any failure.
    """
    return await _post_token({
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
        'client_id': client_id,
        'code_verifier': code_verifier,
    })


async def refresh_token(
    client_id: int,
    client_secret: str,
    refresh_tok: str,
) -> dict:
    """
    POST /auth/oauth.v5/token with grant_type=refresh_token.
    Returns the full token response dict with a new access_token (SSID).
    Raises RuntimeError('refresh_token_expired') when the refresh token has expired
    so callers can handle re-auth gracefully.
    """
    return await _post_token({
        'grant_type': 'refresh_token',
        'refresh_token': refresh_tok,
        'client_id': client_id,
        'client_secret': client_secret,
    })


async def _post_token(payload: dict) -> dict:
    url = f"{OAUTH_BASE}{_TOKEN_PATH}"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data: dict = {}
            try:
                data = await resp.json(content_type=None)
            except Exception:
                pass

            if resp.status == 200:
                ssid = data.get('access_token')
                if not ssid:
                    raise RuntimeError(f"Token endpoint 200 but no access_token: {data}")
                return data

            err_code = data.get('code', 'unknown')
            err_msg = data.get('message', str(data)[:200])

            if resp.status == 400:
                if err_code == 'token_expired':
                    raise RuntimeError('refresh_token_expired')
                raise RuntimeError(f"Bad token request [{err_code}]: {err_msg}")
            elif resp.status == 403:
                if err_code == 'blocked':
                    raise RuntimeError("IQ Option account is blocked")
                raise RuntimeError(f"Token forbidden [{err_code}]: {err_msg}")
            elif resp.status == 429:
                ttl = data.get('ttl', '?')
                raise RuntimeError(f"Rate limited — retry in {ttl}s")
            else:
                raise RuntimeError(
                    f"Token endpoint {resp.status} [{err_code}]: {err_msg}"
                )
