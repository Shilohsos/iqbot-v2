"""
Admin: /admin — admin control panel menu.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.middleware.approval_gate import require_admin
from bot.middleware.admin_gate import require_admin as require_admin_simple
from database.models.users import set_tier


@require_admin
async def cmd_admin_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Today", callback_data='adm:today')],
        [InlineKeyboardButton("👥 Activation", callback_data='adm:activation')],
        [InlineKeyboardButton("🔍 Find Users", callback_data='adm:find_user_prompt')],
        [InlineKeyboardButton("🎫 Tokens", callback_data='adm:tokens')],
        [InlineKeyboardButton("🖥 System", callback_data='adm:system')],
        [InlineKeyboardButton("📢 Broadcast", callback_data='adm:broadcast')],
        [InlineKeyboardButton("🏆 Top Traders", callback_data='adm:top_traders')],
        [InlineKeyboardButton("📈 Funnel", callback_data='adm:funnel')],
        [InlineKeyboardButton("📋 Audit", callback_data='adm:audit')],
        [InlineKeyboardButton("⚙️ Admin Controls", callback_data='adm:admin_controls')],
    ])

    from bot.ui.messages import reply_safe
    await reply_safe(update,
        text="⚙️ *ADMIN PANEL*",
        parse_mode='Markdown',
        reply_markup=keyboard,
    )


@require_admin_simple
async def cb_admin_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle admin panel callback actions — both menu nav and user actions."""
    await update.callback_query.answer()
    data = update.callback_query.data

    # ── User actions (tier, ban, delete) ──
    if data.startswith('adm:tier:'):
        user_id = int(data.split(':')[2])
        from database.models.users import get_user_by_id
        user = get_user_by_id(user_id)
        new_tier = 'PRO' if user['tier'] != 'PRO' else 'NEWBIE'
        set_tier(user_id, new_tier)
        await update.callback_query.edit_message_text(
            f"Tier changed to *{new_tier}* for user {user_id}",
            parse_mode='Markdown'
        )

    elif data.startswith('adm:ban:'):
        user_id = int(data.split(':')[2])
        set_tier(user_id, 'BANNED')
        await update.callback_query.edit_message_text(
            f"🚫 User {user_id} banned."
        )

    elif data.startswith('adm:delete:'):
        user_id = int(data.split(':')[2])
        from database.db import get_connection
        conn = get_connection()
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
        conn.close()
        await update.callback_query.edit_message_text(
            f"🗑 User {user_id} deleted."
        )

    # ── Menu navigation (complete routing dict) ──
    else:
        action = data.split(':', 1)[1] if ':' in data else data

        from bot.admin.today import cmd_today
        from bot.admin.activation import cmd_activation
        from bot.admin.find_users import cmd_find
        from bot.admin.tokens import cmd_tokens
        from bot.admin.system import cmd_system
        from bot.admin.broadcast import cmd_broadcast
        from bot.admin.top_traders import cmd_top_traders
        from bot.admin.funnel import cmd_funnel
        from bot.admin.audit import cmd_audit

        handlers = {
            'today': cmd_today,
            'activation': cmd_activation,
            'find_user_prompt': cmd_find,
            'tokens': cmd_tokens,
            'system': cmd_system,
            'broadcast': cmd_broadcast,
            'top_traders': cmd_top_traders,
            'funnel': cmd_funnel,
            'audit': cmd_audit,
            'admin_controls': cmd_admin_menu,
        }
        handler = handlers.get(action)
        if handler:
            await handler(update, ctx)
        else:
            from bot.ui.messages import reply_safe
            await reply_safe(update, text=f"Unknown action: `{action}`", parse_mode='Markdown')
