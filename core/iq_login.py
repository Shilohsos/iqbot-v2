"""
Acquire and refresh SSIDs for IQ Option / Quadcode platform.

Preferred path (OAuth):
  If the account has a stored refresh_token (set during OAuth connect), we call
  POST /auth/oauth.v5/token with grant_type=refresh_token to get a new SSID
  silently — no password needed.

Fallback path (password):
  Legacy email/password login via the v2 REST endpoint.
  Used when no refresh_token is stored (password-onboarded users).
"""
import aiohttp
from utils.logger import get_logger

logger = get_logger("iq-login")

LOGIN_URL = "https://auth.iqoption.com/api/v2/login"


async def acquire_ssid(email: str, password: str) -> tuple:
    """
    POST credentials, return (ssid, '').
    Raises RuntimeError on failure with a meaningful message.
    """
    payload = {
        "identifier": email,
        "password": password,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            LOGIN_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                ssid = data.get('ssid') or data.get('data', {}).get('ssid')
                if not ssid:
                    raise RuntimeError(f"Login OK but no SSID in response: {str(data)[:200]}")
                return ssid, ''
            elif resp.status == 401:
                raise RuntimeError("Invalid email or password")
            elif resp.status == 403:
                try:
                    err = await resp.json()
                except Exception:
                    err = {}
                code = err.get('code', 'unknown')
                if 'captcha' in str(err).lower():
                    raise RuntimeError(
                        "IQ Option is requiring CAPTCHA verification. "
                        "Please log in via the IQ Option app once, then retry."
                    )
                raise RuntimeError(f"Login forbidden: {code}")
            else:
                text = await resp.text()
                raise RuntimeError(f"Login failed [{resp.status}]: {text[:200]}")


async def refresh_ssid_if_stale(account_id: int, max_age_days: int = 14) -> str | None:
    """
    Return a valid SSID for the account, refreshing it if stale.

    Priority:
      1. If SSID is still within its validity window → return as-is.
      2. If a refresh_token is stored → use OAuth refresh (no password needed).
      3. Fall back to email/password login for legacy password-onboarded accounts.
    """
    from database.models.accounts import get_account_by_id, update_ssid, store_oauth_tokens
    from core.encryption import decrypt_credential
    from datetime import datetime, timedelta
    import os

    account = get_account_by_id(account_id)
    if not account:
        return None

    # ── 1. Check whether the current SSID is still valid ─────────────────────
    if account.get('ssid'):
        # Use precise expiry from OAuth if available, otherwise 14-day heuristic
        if account.get('token_expires_at'):
            try:
                expires_at = datetime.fromisoformat(account['token_expires_at'])
                # Refresh 30 minutes before actual expiry
                if datetime.utcnow() < expires_at - timedelta(minutes=30):
                    return account['ssid']
            except (ValueError, TypeError):
                pass
        elif account.get('ssid_at'):
            try:
                ssid_at = datetime.fromisoformat(account['ssid_at'])
                if datetime.utcnow() - ssid_at < timedelta(days=max_age_days):
                    return account['ssid']
            except (ValueError, TypeError):
                pass

    # ── 2. Try OAuth refresh_token (preferred — no password required) ─────────
    stored_refresh = account.get('refresh_token')
    if stored_refresh:
        client_id_str = os.getenv('OAUTH_CLIENT_ID', '')
        client_secret = os.getenv('OAUTH_CLIENT_SECRET', '')
        if client_id_str and client_secret:
            try:
                from core.iq_oauth import refresh_token as oauth_refresh
                tokens = await oauth_refresh(
                    int(client_id_str), client_secret, stored_refresh
                )
                ssid = tokens['access_token']
                store_oauth_tokens(
                    account_id, ssid,
                    tokens.get('refresh_token', stored_refresh),
                    tokens.get('expires_in', 1209600),
                )
                logger.info(f"SSID refreshed via OAuth for account {account_id}")
                return ssid
            except RuntimeError as e:
                if 'refresh_token_expired' in str(e):
                    logger.warning(
                        f"OAuth refresh_token expired for account {account_id}; "
                        "falling back to password auth"
                    )
                else:
                    logger.error(f"OAuth refresh failed for account {account_id}: {e}")
        else:
            logger.warning(
                f"Account {account_id} has refresh_token but OAUTH_CLIENT_ID/"
                "OAUTH_CLIENT_SECRET not set — falling back to password auth"
            )

    # ── 3. Fall back to email/password login ──────────────────────────────────
    enc_email = account.get('email_encrypted', '')
    enc_pass = account.get('password_encrypted', '')
    if not enc_email or not enc_pass:
        logger.error(
            f"Account {account_id} has no usable credentials "
            "(no refresh_token and no email/password stored)"
        )
        return None

    try:
        email = decrypt_credential(enc_email)
        password = decrypt_credential(enc_pass)
    except Exception as e:
        logger.error(f"Failed to decrypt credentials for account {account_id}: {e}")
        return None

    try:
        ssid, _ = await acquire_ssid(email, password)
        update_ssid(account_id, ssid)
        logger.info(f"SSID refreshed via password for account {account_id}")
        return ssid
    except Exception as e:
        logger.error(f"Password SSID refresh failed for account {account_id}: {e}")
        return None
