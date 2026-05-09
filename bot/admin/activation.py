"""
Admin: /activation — approve/reject pending users.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.middleware.approval_gate import require_admin
from database.models.users import get_pending_users, get_user_by_id, approve_user, set_rejection, set_token


@require_admin
async def cmd_activation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    pending = get_pending_users()
    if not pending:
        from bot.ui.messages import reply_safe
        await reply_safe(update, text="No pending users.")
        return

    for user in pending:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve NEWBIE", callback_data=f"adm:approve:{user['id']}:NEWBIE"),
                InlineKeyboardButton("⭐ Approve PRO", callback_data=f"adm:approve:{user['id']}:PRO"),
            ],
            [InlineKeyboardButton("❌ Reject", callback_data=f"adm:reject:{user['id']}")],
        ])
        from bot.ui.messages import reply_safe
        await reply_safe(update,
            text=(
                f"🆕 *New user pending activation*\n\n"
                f"Username: @{user['telegram_username']}\n"
                f"Telegram ID: `{user['telegram_id']}`\n"
                f"IQ Option ID: `{user['iq_user_id']}`\n"
                f"Verified: ✅ (found in affiliate channel)"
            ),
            parse_mode='Markdown',
            reply_markup=keyboard,
        )


async def cb_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import secrets
    _, _, user_id, tier = update.callback_query.data.split(':')
    user_id = int(user_id)
    approve_user(user_id, tier)
    # Auto-generate token
    token = f"10x-{secrets.token_hex(6).upper()}"
    set_token(user_id, token)
    user = get_user_by_id(user_id)
    await update.callback_query.answer(f"Approved as {tier}")
    await update.callback_query.edit_message_text(
        f"✅ Approved @{user['telegram_username']} as *{tier}*\nToken: `{token}`",
        parse_mode='Markdown'
    )
    # Notify user with token
    await ctx.bot.send_message(
        chat_id=user['telegram_id'],
        text=(
            "✅ *Your account is activated!*\n\n"
            f"Tier: *{tier}*\n"
            f"Token: `{token}`\n\n"
            "You can now connect your IQ Option credentials and start trading.\n\n"
            "Type /addaccount to begin."
        ),
        parse_mode='Markdown',
    )


async def cb_reject(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    _, _, user_id = update.callback_query.data.split(':')
    user_id = int(user_id)
    set_rejection(user_id, 'Rejected by admin.')
    user = get_user_by_id(user_id)
    await update.callback_query.answer("Rejected")
    await update.callback_query.edit_message_text(
        f"❌ Rejected @{user['telegram_username']}",
    )
    await ctx.bot.send_message(
        chat_id=user['telegram_id'],
        text="❌ Your account was not approved. Contact admin for details.",
    )


async def notify_admin_pending_user(bot, telegram_id: int):
    """Notify admin of a new pending user."""
    from config import ADMIN_IDS
    from database.models.users import get_user
    user = get_user(telegram_id)
    if not user:
        return
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve NEWBIE", callback_data=f"adm:approve:{user['id']}:NEWBIE"),
            InlineKeyboardButton("⭐ Approve PRO", callback_data=f"adm:approve:{user['id']}:PRO"),
        ],
        [InlineKeyboardButton("❌ Reject", callback_data=f"adm:reject:{user['id']}")],
    ])
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=(
                    f"🆕 *New user pending activation*\n\n"
                    f"Username: @{user['telegram_username']}\n"
                    f"Telegram ID: `{user['telegram_id']}`\n"
                    f"IQ Option ID: `{user['iq_user_id']}`\n"
                    f"Verified: ✅ (found in affiliate channel)"
                ),
                parse_mode='Markdown',
                reply_markup=keyboard,
            )
        except Exception:
            pass
