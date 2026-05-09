"""
Admin: /tokens — token management dashboard.
"""
from bot.middleware.admin_gate import require_admin
from bot.ui.messages import reply_safe
from bot.ui.keyboards import back_to_admin_keyboard
from database.models.users import get_pending_token_users, get_active_token_users


@require_admin
async def cmd_tokens(update, ctx):
    if update.callback_query:
        await update.callback_query.answer()
    pending = get_pending_token_users()
    active = get_active_token_users()
    text = "🎫 *Token Management*\n\n"
    text += f"Pending token assignment: `{len(pending)}`\n"
    text += f"Active tokens: `{len(active)}`\n\n"
    if pending:
        text += "*Awaiting tokens:*\n"
        for u in pending[:10]:
            text += f"  • @{u['telegram_username']} (IQ: `{u['iq_user_id']}`)\n"
        text += "\n"
    text += (
        "*Commands:*\n"
        "`/assign_token @username TOKEN`\n"
        "`/revoke_token @username`\n"
    )
    await reply_safe(update, text=text, parse_mode='Markdown',
                      reply_markup=back_to_admin_keyboard())


@require_admin
async def cmd_assign_token(update, ctx):
    """Assign a token to a user."""
    args = ctx.args if ctx.args else []
    if len(args) < 2:
        from bot.ui.messages import reply_safe
        await reply_safe(update,
            text="Usage: `/assign_token @username TOKEN`",
            parse_mode='Markdown')
        return

    target_str = args[0].lstrip('@')
    token = args[1]

    from database.models.users import find_user_by_username_or_iq_id, set_token
    user = find_user_by_username_or_iq_id(target_str)
    if not user:
        from bot.ui.messages import reply_safe
        await reply_safe(update, text=f"User `{target_str}` not found.")
        return

    set_token(user['id'], token)

    from bot.ui.messages import reply_safe
    await reply_safe(update,
        text=f"✅ Token `{token}` assigned to @{user['telegram_username']} "
             f"(IQ ID: {user['iq_user_id']})",
        parse_mode='Markdown')

    # Notify the user
    await ctx.bot.send_message(
        chat_id=user['telegram_id'],
        text=(
            "✅ *Your account is activated!*\n\n"
            "You can now connect your IQ Option credentials and start trading.\n\n"
            "Type /addaccount to begin."
        ),
        parse_mode='Markdown',
    )
