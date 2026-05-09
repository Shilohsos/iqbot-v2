"""
Admin: /find — find user by IQ ID, @username, or telegram ID.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.middleware.approval_gate import require_admin
from database.models.users import find_user_full
from core.currency import format_amount


@require_admin
async def cmd_find(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await reply_safe(update,
            text=(
                "🔍 *Find User*\n\n"
                "Send the user's:\n"
                "• Telegram username (with or without `@`)\n"
                "• IQ Option User ID\n"
                "• Telegram ID\n\n"
                "Or use the command: `/find <query>`"
            ),
            parse_mode='Markdown',
        )
        return

    query = ctx.args[0].lstrip('@')
    user = find_user_full(query)

    if not user:
        await update.message.reply_text("User not found.")
        return

    text = (
        f"👤 *User Profile*\n\n"
        f"Telegram: @{user['telegram_username']} (`{user['telegram_id']}`)\n"
        f"IQ Option ID: `{user['iq_user_id']}`\n"
        f"Tier: `{user['tier']}`\n"
        f"Approval: `{user['approval_status']}`\n"
        f"Token: `{user['token'] or 'NONE'}`\n"
        f"Created: `{user['created_at']}`\n"
        f"Last active: `{user['last_active_at'] or 'never'}`\n"
        f"Last trade: `{user['last_trade_at'] or 'never'}`\n\n"
        f"*Stats:*\n"
        f"Total trades: `{user['total_trades']}`\n"
        f"Net P&L: `{user['total_pnl']:+,.2f}`\n"
        f"Win rate: `{user['win_rate']:.1f}%`\n"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔰 Change tier", callback_data=f"adm:tier:{user['id']}"),
            InlineKeyboardButton("🚫 Ban", callback_data=f"adm:ban:{user['id']}"),
        ],
        [InlineKeyboardButton("🗑 Delete", callback_data=f"adm:delete:{user['id']}")],
    ])

    from bot.ui.messages import reply_safe
    await reply_safe(update,
        text=text[:4000], parse_mode='Markdown',
        reply_markup=keyboard
    )


async def msg_find_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle text input when admin is searching for a user."""
    if not ctx.user_data.get('awaiting_find_query'):
        return
    ctx.user_data['awaiting_find_query'] = False
    ctx.args = [update.message.text.strip()]
    await cmd_find(update, ctx)
