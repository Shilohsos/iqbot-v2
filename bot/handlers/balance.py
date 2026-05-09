"""
Balance handler — shows user's account balances.
"""
from telegram import Update
from telegram.ext import ContextTypes
from database.models.users import get_user
from database.models.accounts import get_user_account_summary
from bot.middleware.approval_gate import require_approved
from core.currency import format_amount


@require_approved
async def cmd_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    user = get_user(update.effective_user.id)
    summary = get_user_account_summary(user['id'])

    from bot.ui.messages import reply_safe
    from bot.ui.keyboards import back_to_menu_keyboard
    text = (
        "*Your Balances* 💰\n\n"
        f"🎮 *Practice:* {format_amount(summary['practice_balance'], summary['practice_currency'])}\n"
        f"💎 *Live:* {format_amount(summary['real_balance'], summary['real_currency'])}"
    )
    await reply_safe(update, text=text, parse_mode='Markdown',
                      reply_markup=back_to_menu_keyboard())


async def cb_show_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await cmd_balance(update, ctx)
