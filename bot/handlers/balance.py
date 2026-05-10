"""
Balance handler — shows user's account balances.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.models.users import get_user
from database.models.accounts import (
    get_user_account_summary, get_account_credentials, update_balance,
)
from bot.middleware.approval_gate import require_approved
from core.currency import format_amount
from utils.logger import get_logger

logger = get_logger("balance")


def _balance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data='refresh_balance')],
        [InlineKeyboardButton("🔙 Back to menu", callback_data='back_to_user_menu')],
    ])


def _format_balance_text(summary: dict) -> str:
    return (
        "*Your Balances* 💰\n\n"
        f"🎮 *Practice:* {format_amount(summary['practice_balance'], summary['practice_currency'])}\n"
        f"💎 *Live:* {format_amount(summary['real_balance'], summary['real_currency'])}"
    )


@require_approved
async def cmd_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    user = get_user(update.effective_user.id)
    summary = get_user_account_summary(user['id'])

    from bot.ui.messages import reply_safe
    await reply_safe(update, text=_format_balance_text(summary), parse_mode='Markdown',
                      reply_markup=_balance_keyboard())


async def cb_show_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await cmd_balance(update, ctx)


async def cb_refresh_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Live-fetch balance from IQ Option, write to DB, redraw."""
    await update.callback_query.answer("Refreshing...")
    user = get_user(update.effective_user.id)
    account = get_account_credentials(user['id'])
    if not account:
        await update.callback_query.edit_message_text(
            "❌ No IQ Option account linked. Use /addaccount.",
        )
        return

    from core.iq_login import refresh_ssid_if_stale
    from core.trade_executor import fetch_balances

    fresh_ssid = await refresh_ssid_if_stale(account['id'])
    if not fresh_ssid:
        await update.callback_query.edit_message_text(
            "❌ Session expired — IQ Option could not authenticate.\n\n"
            "Your credentials may have changed or the session has lapsed.\n"
            "Use /addaccount to re-link your account.",
        )
        return

    balances = await fetch_balances(fresh_ssid, account['platform_id'])
    if not balances:
        await update.callback_query.edit_message_text(
            "❌ Connected to IQ Option but balance fetch returned nothing.\n\n"
            "Try again in a moment, or use /addaccount to re-link.",
        )
        return

    for bal in balances:
        try:
            update_balance(
                user['id'],
                bal.get('type', 4),
                bal.get('amount', 0),
                bal.get('currency', 'USD'),
            )
        except Exception:
            pass

    summary = get_user_account_summary(user['id'])
    await update.callback_query.edit_message_text(
        text=_format_balance_text(summary),
        parse_mode='Markdown',
        reply_markup=_balance_keyboard(),
    )
