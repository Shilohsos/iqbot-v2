"""
PILLAR 1 entry point: Bias Engine.
Run: python3 main_bias.py
PM2: iqbot-v2-bias-engine
"""
import asyncio
from bias.engine import run_bias_engine
from database.db import init_db
from utils.logger import get_logger

logger = get_logger("main-bias")


async def main():
    init_db()
    logger.info("Bias engine starting...")
    await run_bias_engine()


if __name__ == '__main__':
    asyncio.run(main())
