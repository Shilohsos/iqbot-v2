"""
Leaderboard handler — shows top traders.
"""
from telegram import Update
from telegram.ext import ContextTypes
from database.models.leaderboard import get_top_real_traders
from bot.middleware.approval_gate import require_approved
from bot.ui.messages import reply_safe
from bot.ui.keyboards import back_to_menu_keyboard


@require_approved
async def cmd_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = get_top_real_traders(limit=10)

    if not rows:
        await reply_safe(
            update,
            text="🏆 *Leaderboard*\n\nNo completed trades yet.",
            parse_mode='Markdown',
            reply_markup=back_to_menu_keyboard(),
        )
        return

    text = "🏆 *Top Traders*\n\n"
    for i, r in enumerate(rows, 1):
        name = f"@{r['telegram_username']}" if r['telegram_username'] else f"Trader#{r['iq_user_id']}"
        pnl = r['pnl']
        sign = '+' if pnl >= 0 else ''
        text += f"{i}. {name} — {sign}{pnl:,.2f} USD\n"
    await reply_safe(update, text=text, parse_mode='Markdown',
                     reply_markup=back_to_menu_keyboard())


@require_approved
async def cb_show_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await cmd_leaderboard(update, ctx)
