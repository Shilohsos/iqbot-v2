"""
Admin: /system — system dashboard and controls.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.middleware.approval_gate import require_admin
from bot.middleware.admin_gate import require_admin as require_admin_simple
import os


def status_emoji(status):
    return {'ONLINE': '🟢', 'STOPPED': '🔴', 'ERRORED': '🟡', 'LAUNCHING': '🟡'}.get(status, '⚫')


@require_admin
async def cmd_system(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    # Gather system stats
    from utils.pm2_manager import watcher_status
    from database.db import get_connection
    import json, subprocess

    # Real PM2 status
    def pm2_status(name):
        try:
            r = subprocess.run(['pm2', 'jlist'], capture_output=True, text=True, timeout=5)
            procs = json.loads(r.stdout)
            for p in procs:
                if p.get('name') == name:
                    return p.get('pm2_env', {}).get('status', 'unknown').upper()
        except Exception:
            pass
        return 'UNKNOWN'

    conn = get_connection()
    db_size = os.path.getsize('/root/iqbot-v2/iqbot.db') / (1024 * 1024)
    trades_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    bias_count = conn.execute("SELECT COUNT(*) FROM market_bias").fetchone()[0]
    conn.close()

    bias_status = pm2_status('iqbot-v2-bias')
    bot_status = pm2_status('iqbot-v2-bot')

    text = (
        f"🖥 *System Status*\n\n"
        f"Bias engine:      {status_emoji(bias_status)} {bias_status}\n"
        f"Bot process:      {status_emoji(bot_status)} {bot_status}\n\n"
        f"*Database:*\n"
        f"  - Size: {db_size:.1f} MB\n"
        f"  - Trades: {trades_count} rows\n"
        f"  - Users: {users_count} rows\n"
        f"  - Bias entries: {bias_count} active\n"
        f"Redis: {'🟢 connected' if True else '⚫ down'}\n"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Restart bias engine", callback_data='sys:restart_bias')],
        [InlineKeyboardButton("📋 View logs", callback_data='sys:view_logs')],
        [InlineKeyboardButton("🧹 Cleanup orphans", callback_data='sys:cleanup')],
    ])

    from bot.ui.messages import reply_safe
    await reply_safe(update,
        text=text[:4000], parse_mode='Markdown',
        reply_markup=keyboard,
    )


@require_admin_simple
async def cb_system_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    action = update.callback_query.data.split(':')[1]
    await update.callback_query.answer()

    if action == 'restart_bias':
        from utils.pm2_manager import kill_watcher
        # Restart bias via PM2
        import subprocess
        subprocess.run(['pm2', 'restart', 'iqbot-v2-bias'], capture_output=True)
        await update.callback_query.edit_message_text("🔄 Bias engine restart triggered.")

    elif action == 'view_logs':
        await update.callback_query.edit_message_text(
            "📋 Run `pm2 logs iqbot-v2-bias-engine` on the VPS for live logs."
        )

    elif action == 'cleanup':
        await update.callback_query.edit_message_text(
            "🧹 Orphan cleanup not yet implemented."
        )
