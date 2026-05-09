"""
Admin: /broadcast — send message to user segments.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.middleware.approval_gate import require_admin
from database.models.users import get_all_user_ids
from database.models.broadcasts import log_broadcast, update_broadcast_count
import asyncio


@require_admin
async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Initiate broadcast flow — pick segment."""
    if update.callback_query:
        await update.callback_query.answer()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 ALL users", callback_data='bc_seg:ALL')],
        [InlineKeyboardButton("🟢 Active (5h)", callback_data='bc_seg:ACTIVE')],
        [InlineKeyboardButton("🔴 Inactive (5h+)", callback_data='bc_seg:INACTIVE_5H')],
        [InlineKeyboardButton("🆕 NEWBIE only", callback_data='bc_seg:NEWBIE')],
        [InlineKeyboardButton("⭐ PRO only", callback_data='bc_seg:PRO')],
    ])

    from bot.ui.messages import reply_safe
    await reply_safe(update,
        text="*Broadcast — Pick segment:*",
        parse_mode='Markdown',
        reply_markup=keyboard,
    )
    ctx.user_data['composing_broadcast'] = True


async def cb_broadcast_segment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """After segment picked, ask for message."""
    await update.callback_query.answer()
    segment = update.callback_query.data.split(':', 1)[1] if ':' in update.callback_query.data else 'ALL'
    ctx.user_data['broadcast_segment'] = segment
    ctx.user_data['composing_broadcast'] = True
    from bot.ui.messages import reply_safe
    await reply_safe(
        update,
        text=(
            f"*Segment:* `{segment}`\n\n"
            f"Send the message text (Markdown supported).\n"
            f"Type /cancel to abort."
        ),
        parse_mode='Markdown',
    )


async def msg_broadcast_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Triggered when admin types broadcast message text — shows preview."""
    if not ctx.user_data.get('composing_broadcast'):
        return
    if update.message.text.strip().lower() in ('/cancel', 'cancel'):
        ctx.user_data['composing_broadcast'] = False
        ctx.user_data.pop('broadcast_segment', None)
        await update.message.reply_text("Broadcast cancelled.")
        return

    ctx.user_data['broadcast_text'] = update.message.text
    segment = ctx.user_data.get('broadcast_segment', 'ALL')
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Send", callback_data='bc_confirm'),
            InlineKeyboardButton("❌ Cancel", callback_data='bc_cancel'),
        ],
    ])
    preview = (
        f"*Preview*\n"
        f"Segment: `{segment}`\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{update.message.text}\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"Send to all matching users?"
    )
    await update.message.reply_text(
        preview, parse_mode='Markdown',
        reply_markup=keyboard,
    )


async def cb_broadcast_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Confirm and send the broadcast."""
    await update.callback_query.answer("Sending...")
    text = ctx.user_data.get('broadcast_text')
    segment = ctx.user_data.get('broadcast_segment', 'ALL')
    if not text:
        from bot.ui.messages import reply_safe
        await reply_safe(update, text="No message draft found.")
        return

    ctx.user_data['composing_broadcast'] = False
    ctx.user_data.pop('broadcast_text', None)
    ctx.user_data.pop('broadcast_segment', None)

    from database.models.users import get_users_by_segment
    targets = get_users_by_segment(segment)
    sent, failed = 0, 0
    for u in targets:
        try:
            await ctx.bot.send_message(
                chat_id=u['telegram_id'],
                text=text,
                parse_mode='Markdown',
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    from database.models.broadcasts import log_broadcast
    log_broadcast(
        admin_id=update.effective_user.id,
        target_segment=segment,
        message_text=text,
        sent_count=sent,
    )

    from bot.ui.messages import reply_safe
    from bot.ui.keyboards import back_to_admin_keyboard
    await reply_safe(
        update,
        text=(
            f"✅ *Broadcast complete*\n\n"
            f"Segment: `{segment}`\n"
            f"Sent: `{sent}`\n"
            f"Failed: `{failed}`"
        ),
        parse_mode='Markdown',
        reply_markup=back_to_admin_keyboard(),
    )


async def cb_broadcast_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Cancel the broadcast."""
    await update.callback_query.answer("Cancelled")
    ctx.user_data['composing_broadcast'] = False
    ctx.user_data.pop('broadcast_text', None)
    ctx.user_data.pop('broadcast_segment', None)
    from bot.ui.messages import reply_safe
    from bot.ui.keyboards import back_to_admin_keyboard
    await reply_safe(update, text="Broadcast cancelled.",
                      reply_markup=back_to_admin_keyboard())
