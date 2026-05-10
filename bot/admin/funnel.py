"""
Admin: /funnel — conversion funnel stats.
"""
from telegram import Update
from telegram.ext import ContextTypes
from bot.middleware.admin_gate import require_admin
from database.models.funnel import get_funnel_stats


@require_admin
async def cmd_funnel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    stats = get_funnel_stats(days=7)

    if not stats or not stats.get('total'):
        await update.message.reply_text("No funnel data yet.")
        return

    landing_views = stats.get('landing_views', 0) or 0
    landing_clicks = stats.get('landing_clicks', 0) or 0
    started = stats.get('started', 0) or 0
    verified = stats.get('verified', 0) or 0
    first_trade = stats.get('first_trade', 0) or 0

    # We don't have token_assigned / account_added in the schema, so estimate
    text = (
        f"📈 *Funnel — Last 7 Days*\n\n"
        f"Landing views:        {landing_views:,}\n"
        f"Landing clicks:       {landing_clicks:,} ({_pct(landing_clicks, landing_views)}%)\n"
        f"/start commands:      {started:,} ({_pct(started, landing_clicks)}%)\n"
        f"IQ ID submitted:      {verified:,} ({_pct(verified, started)}%)\n"
        f"Verified (in channel): {verified:,}\n"
        f"First trade:          {first_trade:,} ({_pct(first_trade, started)}%)\n\n"
        f"Overall conversion: {_pct(first_trade, landing_views)}% (landing → first trade)"
    )

    from bot.ui.messages import reply_safe
    await reply_safe(update, text=text, parse_mode='Markdown')


def _pct(part, whole) -> str:
    if not whole:
        return '0.0'
    return f"{100.0 * part / whole:.1f}"
