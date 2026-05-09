"""
Simple admin authorization decorator.
Checks against ADMIN_IDS env var — no DB query needed.
"""
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
import os


ADMIN_IDS = set(
    int(x.strip())
    for x in os.getenv('ADMIN_IDS', '').split(',')
    if x.strip()
)


def require_admin(handler):
    @wraps(handler)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else None
        if user_id not in ADMIN_IDS:
            if update.callback_query:
                await update.callback_query.answer("Not authorized.", show_alert=True)
            return
        return await handler(update, ctx, *args, **kwargs)
    return wrapper
