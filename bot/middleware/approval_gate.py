"""
Approval gate — blocks unapproved users from accessing any trade features.
"""
from functools import wraps
from database.models.users import get_user


def require_approved(handler):
    """Decorator — handler runs only if user is approved."""
    @wraps(handler)
    async def wrapper(update, ctx, *args, **kwargs):
        user = get_user(update.effective_user.id)

        if not user:
            await _reply(update, "Please /start the bot first.")
            return

        if user['tier'] == 'ADMIN':
            return await handler(update, ctx, *args, **kwargs)

        if user['approval_status'] != 'APPROVED':
            reason = user.get('rejection_reason', 'Not yet approved.')
            await _reply(
                update,
                f"🔒 *Access restricted*\n\n{reason}",
                parse_mode='Markdown'
            )
            return

        if not user.get('token'):
            await _reply(
                update,
                "🔒 *Token required*\n\nAn admin must assign you a token before trading.",
                parse_mode='Markdown'
            )
            return

        return await handler(update, ctx, *args, **kwargs)
    return wrapper


def require_admin(handler):
    """Decorator — handler runs only if user is ADMIN."""
    @wraps(handler)
    async def wrapper(update, ctx, *args, **kwargs):
        user = get_user(update.effective_user.id)
        if not user or user['tier'] != 'ADMIN':
            await _reply(update, "🔒 Admin only.")
            return
        return await handler(update, ctx, *args, **kwargs)
    return wrapper


async def _reply(update, text, **kwargs):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, **kwargs)
    else:
        await update.message.reply_text(text, **kwargs)
