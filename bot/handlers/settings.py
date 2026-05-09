"""
Settings handler — user preferences.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.middleware.approval_gate import require_approved


@require_approved
async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from bot.ui.messages import reply_safe
    from bot.ui.keyboards import back_to_menu_keyboard
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Trade History", callback_data='show_history')],
        [InlineKeyboardButton("ℹ️ About", callback_data='show_about')],
        [InlineKeyboardButton("🔙 Back to menu", callback_data='back_to_user_menu')],
    ])
    await reply_safe(update,
        text="⚙️ *Settings*\n\nWhat would you like to do?",
        parse_mode='Markdown',
        reply_markup=keyboard,
    )


@require_approved
async def cb_show_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await cmd_settings(update, ctx)


@require_approved
async def cb_show_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show last 10 trades for this user."""
    from database.db import get_connection
    from core.currency import format_amount

    user_id = update.effective_user.id
    conn = get_connection()
    row = conn.execute("SELECT id FROM users WHERE telegram_id=?", (user_id,)).fetchone()
    if not row:
        await update.callback_query.edit_message_text("Account not found.")
        conn.close()
        return

    trades = conn.execute(
        """SELECT pair, direction, amount, result, pnl, balance_type, opened_at
           FROM trades WHERE user_id=?
           ORDER BY opened_at DESC LIMIT 10""",
        (row['id'],)
    ).fetchall()
    conn.close()

    if not trades:
        await update.callback_query.edit_message_text("No trades yet.")
        return

    text = "📊 *Trade History*\n\n"
    for t in trades:
        emoji = {'WIN': '✅', 'LOSS': '❌', 'TIE': '⚪', 'PENDING': '⏳'}.get(t['result'], '❓')
        text += (
            f"{emoji} {t['pair']} — {t['direction'].upper()}\n"
            f"   {t['amount']} — {t['result'] or 'PENDING'}\n\n"
        )

    await update.callback_query.edit_message_text(text[:4000], parse_mode='Markdown')


@require_approved
async def cb_show_about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "💜 *Hart Trading Bot v2*\n\n"
        "Automated trading assistant powered by real-time market bias analysis.\n\n"
        "Built by Master Ferdinand Shiloh Hart.",
        parse_mode='Markdown',
    )
