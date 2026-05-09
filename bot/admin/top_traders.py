"""
Admin: /top_traders — leaderboard and top performers.
"""
from bot.middleware.admin_gate import require_admin
from bot.ui.messages import reply_safe
from bot.ui.keyboards import back_to_admin_keyboard
from database.models.leaderboard import get_leaderboard, get_top_real_traders


@require_admin
async def cmd_top_traders(update, ctx):
    if update.callback_query:
        await update.callback_query.answer()
    published = get_leaderboard(period='ALL_TIME', limit=10)
    real_top = get_top_real_traders(limit=10)
    text = "🏆 *Top Traders*\n\n"
    text += "*Currently published leaderboard:*\n"
    if not published:
        text += "_No leaderboard published yet._\n"
    else:
        for entry in published:
            text += (f"  {entry['rank']}. {entry['display_name']} — "
                      f"{entry['profit_amount']:+.2f} {entry['profit_currency']}\n")
    text += "\n*Real top traders (by net P&L):*\n"
    if not real_top:
        text += "_No trader activity yet._\n"
    else:
        for i, t in enumerate(real_top, 1):
            text += (f"  {i}. @{t['telegram_username'] or 'anon'} — "
                      f"{t['pnl']:+.2f} ({t['count']} trades)\n")
    text += (
        "\n*Commands:*\n"
        "`/publish_leaderboard` — push real top to public leaderboard\n"
        "`/clear_leaderboard` — remove published entries\n"
        "`/add_leaderboard <rank> <name> <profit>` — manual entry\n"
    )
    await reply_safe(update, text=text, parse_mode='Markdown',
                      reply_markup=back_to_admin_keyboard())
