"""
Acquire SSID from email/password via IQ Option's REST login endpoint.
Reference: Quadcode SDK uses this same endpoint internally for SsidAuthMethod.
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
    """Returns fresh SSID if cache is stale. Returns existing SSID otherwise."""
    from database.models.accounts import get_account_by_id, update_ssid
    from core.encryption import decrypt_credential
    from datetime import datetime, timedelta

    account = get_account_by_id(account_id)
    if not account:
        return None

    if account.get('ssid') and account.get('ssid_at'):
        try:
            ssid_at = datetime.fromisoformat(account['ssid_at'])
            if datetime.utcnow() - ssid_at < timedelta(days=max_age_days):
                return account['ssid']
        except (ValueError, TypeError):
            pass

    # Refresh
    try:
        email = decrypt_credential(account['email_encrypted'])
        password = decrypt_credential(account['password_encrypted'])
    except Exception as e:
        logger.error(f"Failed to decrypt credentials: {e}")
        return None

    try:
        ssid, _ = await acquire_ssid(email, password)
        update_ssid(account_id, ssid)
        return ssid
    except Exception as e:
        logger.error(f"SSID refresh failed: {e}")
        return None
