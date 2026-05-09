"""
Admin: /today — aggregated dashboard.
"""
from telegram import Update
from telegram.ext import ContextTypes
from bot.middleware.approval_gate import require_admin
from database.models.trades import get_daily_summary, get_per_user_today
from core.currency import format_amount


@require_admin
async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    summary = get_daily_summary()
    per_user = get_per_user_today()

    text = (
        f"📊 *Today's Performance*\n\n"
        f"Trades: `{summary['count']}`\n"
        f"Volume: `${summary['volume']:,.2f}`\n"
        f"Net P&L: *{summary['pnl']:+,.2f}*\n"
        f"Win rate: `{summary['win_rate']:.1f}%`\n"
        f"Active traders: `{summary['active_traders']}`\n\n"
        f"*Top traders:*\n"
    )

    for u in per_user[:20]:
        text += (
            f"  • @{u['username'] or 'anon'} (ID: `{u['iq_user_id']}`)"
            f" — {u['pnl']:+.2f} ({u['count']} trades)\n"
        )

    from bot.ui.messages import reply_safe
    await reply_safe(update, text=text[:4000], parse_mode='Markdown')
