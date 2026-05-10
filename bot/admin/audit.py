"""
Admin: /audit — generate audit report.
For v1: text report only. PDF generation is a v2.1 feature.
"""
from telegram import Update
from telegram.ext import ContextTypes
from bot.middleware.admin_gate import require_admin
from database.db import get_connection


@require_admin
async def cmd_audit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    conn = get_connection()

    # Recent admin actions
    actions = conn.execute(
        """SELECT * FROM admin_actions
           ORDER BY created_at DESC LIMIT 20"""
    ).fetchall()

    # Recent approvals/rejections
    users_recent = conn.execute(
        """SELECT telegram_username, approval_status, tier, created_at
           FROM users ORDER BY created_at DESC LIMIT 20"""
    ).fetchall()

    # Broadcast stats
    bc_count = conn.execute("SELECT COUNT(*) FROM broadcasts").fetchone()[0]

    conn.close()

    text = (
        f"📋 *Audit Report*\n\n"
        f"*Recent admin actions:* {len(actions)}\n"
    )
    for a in actions[:10]:
        text += f"  • {a['action']} — {a['created_at'][:16]}\n"

    text += f"\n*Recent users:* {len(users_recent)}\n"
    for u in users_recent[:10]:
        text += f"  • @{u['telegram_username']} — {u['approval_status']} ({u['tier']})\n"

    text += f"\n*Total broadcasts:* {bc_count}\n\n"
    text += "_PDF generation is a v2.1 feature._"

    from bot.ui.messages import reply_safe
    await reply_safe(update, text=text[:4000], parse_mode='Markdown')
