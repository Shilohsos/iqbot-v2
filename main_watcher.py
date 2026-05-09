"""
PILLAR 2 entry point: Account Watcher.
Run: python3 main_watcher.py <user_id>
PM2: iqbot-v2-watcher-{user_id}
"""
import sys
import asyncio
from database.db import init_db
from watcher.connection import UserWatcher
from utils.logger import get_logger

logger = get_logger("main-watcher")


async def main(user_id: int):
    init_db()
    logger.info(f"Watcher starting for user {user_id}...")
    watcher = UserWatcher(user_id=user_id)
    await watcher.start()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 main_watcher.py <user_id>")
        sys.exit(1)
    try:
        user_id = int(sys.argv[1])
    except ValueError:
        print(f"Error: user_id must be an integer, got: {sys.argv[1]!r}")
        sys.exit(1)
    asyncio.run(main(user_id))
