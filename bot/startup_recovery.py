"""
Startup recovery: notify users of any trades that were placed but whose results
were never received (bot crashed during the wait loop).
"""
import time
from utils.logger import get_logger

logger = get_logger("startup-recovery")


async def recover_pending_trades(bot) -> None:
    """
    Called once at bot startup. Finds stale pending_results (option already
    expired + 2-minute grace) and notifies each affected user. The trade
    stays in /history as it was logged at placement; we just notify.
    """
    from database.models.pending_results import get_stale_pending, delete_pending

    stale = get_stale_pending(grace_seconds=120)
    if not stale:
        return

    logger.info(f"Startup recovery: found {len(stale)} unresolved pending trade(s)")

    notified_users = set()
    for trade in stale:
        user_id = trade['user_id']
        iq_id = trade['iq_option_id']
        pair = trade['pair']
        amount = trade['amount']

        logger.info(f"Recovering pending trade iq_id={iq_id} user_id={user_id} pair={pair}")

        # Notify the user once (not once per trade if they had multiple pending)
        if user_id not in notified_users:
            try:
                from database.models.users import get_user_by_id
                user = get_user_by_id(user_id)
                if user:
                    await bot.send_message(
                        chat_id=user['telegram_id'],
                        text=(
                            "⚠️ *Bot restarted during an active trade*\n\n"
                            f"Trade on `{pair}` (${amount:.2f}) was placed but the result "
                            "could not be confirmed — the bot restarted while waiting.\n\n"
                            "Check /history or your IQ Option account for the outcome."
                        ),
                        parse_mode='Markdown',
                    )
                    notified_users.add(user_id)
            except Exception as e:
                logger.warning(f"Could not notify user_id={user_id}: {e}")

        delete_pending(iq_id)

    logger.info(f"Startup recovery complete — cleared {len(stale)} pending trade(s)")
