"""
Tier gating middleware — blocks features based on user tier.
Tiers: PENDING, NEWBIE, PRO, BANNED, ADMIN
"""
from functools import wraps
from database.models.users import get_user


def require_tier(min_tier: str):
    """Decorator — handler runs only if user's tier meets minimum."""
    def decorator(handler):
        @wraps(handler)
        async def wrapper(update, ctx, *args, **kwargs):
            user = get_user(update.effective_user.id)
            if not user:
                await _reply(update, "Please /start the bot first.")
                return

            tier = user['tier']

            if tier == 'PENDING' or tier == 'BANNED':
                await _reply(update, "🔒 Your account isn't activated yet.")
                return

            if tier == 'ADMIN':
                return await handler(update, ctx, *args, **kwargs)

            # Tier comparison
            TIER_ORDER = {'PENDING': 0, 'NEWBIE': 1, 'PRO': 2, 'ADMIN': 99}
            if TIER_ORDER.get(tier, 0) < TIER_ORDER.get(min_tier, 1):
                await _reply(
                    update,
                    "⚡ This feature is for *Live Pro* accounts only.\n\n"
                    "Contact admin to upgrade.",
                    parse_mode='Markdown'
                )
                return

            return await handler(update, ctx, *args, **kwargs)
        return wrapper
    return decorator


async def _reply(update, text, **kwargs):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, **kwargs)
    else:
        await update.message.reply_text(text, **kwargs)
