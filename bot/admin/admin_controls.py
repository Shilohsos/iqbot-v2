"""
Admin: /admin — admin control panel menu.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.middleware.admin_gate import require_admin
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


@require_admin
async def cb_admin_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle admin panel callback actions — both menu nav and user actions."""
    await update.callback_query.answer()
    data = update.callback_query.data

    def _extract_user_id(data: str) -> int | None:
        parts = data.split(':')
        if len(parts) < 3 or not parts[2].isdigit():
            return None
        return int(parts[2])

    def _log_admin_action(admin_id: int, action: str, target_user_id: int, details: str = ''):
        from database.db import get_connection
        from datetime import datetime, timezone
        conn = get_connection()
        conn.execute(
            "INSERT INTO admin_actions (admin_id, action, target_user_id, details, created_at) VALUES (?,?,?,?,?)",
            (admin_id, action, target_user_id, details, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()

    admin_tg_id = update.effective_user.id

    # ── User actions (tier, ban, delete) ──
    if data.startswith('adm:tier:'):
        user_id = _extract_user_id(data)
        if user_id is None:
            return
        from database.models.users import get_user_by_id
        user = get_user_by_id(user_id)
        new_tier = 'PRO' if user['tier'] != 'PRO' else 'NEWBIE'
        set_tier(user_id, new_tier)
        _log_admin_action(admin_tg_id, 'TIER_CHANGE', user_id, f"new_tier={new_tier}")
        await update.callback_query.edit_message_text(
            f"Tier changed to *{new_tier}* for user {user_id}",
            parse_mode='Markdown'
        )

    elif data.startswith('adm:ban:'):
        user_id = _extract_user_id(data)
        if user_id is None:
            return
        set_tier(user_id, 'BANNED')
        _log_admin_action(admin_tg_id, 'BAN', user_id)
        await update.callback_query.edit_message_text(
            f"🚫 User {user_id} banned."
        )

    elif data.startswith('adm:delete:'):
        user_id = _extract_user_id(data)
        if user_id is None:
            return
        _log_admin_action(admin_tg_id, 'DELETE_USER', user_id)
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
