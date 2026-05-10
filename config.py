"""
Static configuration for IQBot v2.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Bias Engine ─────────────────────
BIAS_PAIRS = [
    "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "AUDUSD-OTC",
    "EURJPY-OTC", "EURGBP-OTC", "USDCAD-OTC", "USDCHF-OTC",
    "NZDUSD-OTC", "GBPJPY-OTC", "AUDCAD-OTC", "AUDJPY-OTC",
]

BIAS_TIMEFRAMES = [60, 180, 300, 900]  # 1m, 3m, 5m, 15m

BIAS_API_CREDENTIALS = {
    'ssid': os.getenv('BIAS_ENGINE_SSID', ''),
    'platform_id': int(os.getenv('PLATFORM_ID', '0')),
}

# ── Telegram ────────────────────────
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
ADMIN_IDS = [
    int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()
]
AFFILIATE_CHANNEL_ID = os.getenv('AFFILIATE_CHANNEL_ID', '')

# ── Affiliate ───────────────────────
AFFILIATE_LINK = os.getenv('AFFILIATE_LINK', 'https://iqoption.com/?aff=YOUR_ID')

# ── Tiers ───────────────────────────
DEFAULT_TIER = 'PENDING'
TIER_TRADE_LIMITS = {
    'NEWBIE': {'min': 1, 'max': 50, 'max_pairs': 4, 'timeframes': [60, 180, 300, 900]},
    'PRO': {'min': 1, 'max': 500, 'max_pairs': 8, 'timeframes': [60, 180, 300, 900]},
}

# ── Database ────────────────────────
DATABASE_PATH = os.getenv('IQBOT_DB_PATH', '/root/iqbot-v2/iqbot.db')

# ── Funnel ──────────────────────────
LANDING_WEBHOOK_SECRET = os.getenv('LANDING_WEBHOOK_SECRET', '')

# ── Quadcode OAuth (optional — enables OAuth connect flow) ───────────────────
# Obtain client_id + client_secret by registering an OAuth application with
# the Quadcode / IQ Option partner portal.
# If not set, the bot falls back to the legacy email/password login flow.
OAUTH_CLIENT_ID = int(os.getenv('OAUTH_CLIENT_ID', '0')) or None
OAUTH_CLIENT_SECRET = os.getenv('OAUTH_CLIENT_SECRET', '') or None
OAUTH_REDIRECT_URI = os.getenv('OAUTH_REDIRECT_URI', '')
OAUTH_BASE_URL = os.getenv('OAUTH_BASE_URL', 'https://auth.iqoption.com')
