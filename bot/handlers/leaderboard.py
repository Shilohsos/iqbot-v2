"""
Leaderboard handler — shows top traders.
"""
from telegram import Update
from telegram.ext import ContextTypes
from database.db import get_connection
from bot.middleware.approval_gate import require_approved


@require_approved
async def cmd_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn = get_connection()
    rows = conn.execute(
        """SELECT display_name, profit_amount, profit_currency, period
           FROM leaderboard
           ORDER BY rank ASC
           LIMIT 10"""
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("🏆 *Leaderboard*\n\nNo data yet.", parse_mode='Markdown')
        return

    from core.currency import format_amount
    text = "🏆 *Leaderboard*\n\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. {r['display_name']} — {format_amount(r['profit_amount'], r['profit_currency'])}\n"
    from bot.ui.messages import reply_safe
    from bot.ui.keyboards import back_to_menu_keyboard
    await reply_safe(update, text=text, parse_mode='Markdown',
                      reply_markup=back_to_menu_keyboard())


@require_approved
async def cb_show_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await cmd_leaderboard(update, ctx)
