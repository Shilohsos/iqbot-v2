"""
Affiliate channel listener.
Uses Telethon (user account) to read the affiliate channel messages.
Each parsed message extracts IQ Option user ID and inserts into affiliate_events.

Run as: python3 utils/affiliate_listener.py
PM2: iqbot-v2-affiliate-listener
"""
import os
import re
import asyncio
from telethon import TelegramClient, events
from database.db import get_connection
from utils.logger import get_logger

logger = get_logger("affiliate-listener")

API_ID = int(os.getenv('TELETHON_API_ID', '0'))
API_HASH = os.getenv('TELETHON_API_HASH', '')
SESSION = os.getenv('TELETHON_SESSION', '/root/.hermes/telethon.session')

# Read session string from file if it exists
_session_path = SESSION
if os.path.exists(_session_path):
    with open(_session_path) as f:
        _content = f.read().strip()
        if _content and not _content.startswith('/'):
            SESSION = _content  # use as session string
else:
    SESSION = _session_path
CHANNEL_ID = os.getenv('AFFILIATE_CHANNEL_ID', '')


# Regex patterns for IQ Option user ID in affiliate notifications
# Adjust based on actual notification format
IQ_ID_PATTERNS = [
    re.compile(r'User\s*ID[:\s]+(\d{6,15})', re.IGNORECASE),
    re.compile(r'ID[:\s]+(\d{6,15})'),
    re.compile(r'user[_\s]?id[:\s]+(\d{6,15})', re.IGNORECASE),
    re.compile(r'(\d{6,15})\s+(?:registered|signed\s*up|joined)', re.IGNORECASE),
]


def extract_iq_user_id(text: str) -> int | None:
    """Try to extract IQ Option user ID from a message."""
    for pattern in IQ_ID_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group(1))
    return None


def store_affiliate_event(iq_user_id: int, raw_message: str):
    """Insert affiliate event into database."""
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO affiliate_events (iq_user_id, raw_message) VALUES (?, ?)",
        (iq_user_id, raw_message[:500])
    )
    conn.commit()
    conn.close()


async def main():
    if not API_ID or not API_HASH:
        logger.error("TELETHON_API_ID or TELETHON_API_HASH not set")
        return

    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()

    if not CHANNEL_ID:
        logger.error("AFFILIATE_CHANNEL_ID not set")
        return

    channel_id = int(CHANNEL_ID) if CHANNEL_ID.startswith('-') else int(f'-100{CHANNEL_ID}')

    logger.info(f"Listening for affiliate events in channel {channel_id}")

    # Process any existing messages on startup
    try:
        async for msg in client.iter_messages(channel_id, limit=100):
            if msg.text:
                iq_id = extract_iq_user_id(msg.text)
                if iq_id:
                    store_affiliate_event(iq_id, msg.text)
                    logger.info(f"Stored existing: IQ ID {iq_id}")
    except Exception as e:
        logger.error(f"Error processing existing messages: {e}")

    # Listen for new messages
    @client.on(events.NewMessage(chats=[channel_id]))
    async def handler(event):
        if event.message.text:
            iq_id = extract_iq_user_id(event.message.text)
            if iq_id:
                store_affiliate_event(iq_id, event.message.text)
                logger.info(f"New affiliate: IQ ID {iq_id}")

    logger.info("Affiliate listener running...")
    await client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
