"""
IQ Option User ID verification handler.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.models.users import (
    set_iq_id_verified, set_rejection, log_funnel_event,
    get_user, approve_user, set_iq_user_id, set_referrer_check_passed,
)
from bot.ui.images import send_image_with_caption
from utils.affiliate_check import verify_iq_user_id
from config import AFFILIATE_LINK


async def msg_iq_id_submission(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User typed their IQ ID."""
    if not ctx.user_data.get('awaiting_iq_id'):
        return

    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("That doesn't look like a valid User ID. Try again.")
        return

    iq_id = int(text)
    ctx.user_data['awaiting_iq_id'] = False
    tg_id = update.effective_user.id

    # ── SAVE IQ ID IMMEDIATELY — before any check ──
    set_iq_user_id(tg_id, iq_id)

    # Admin bypass — auto-approve
    user = get_user(tg_id)
    if user and user['tier'] == 'ADMIN':
        set_iq_id_verified(tg_id, iq_id)
        approve_user(user['id'], 'ADMIN')
        log_funnel_event(tg_id, 'VERIFIED_ADMIN')
        await update.message.reply_text(
            "✅ *Admin verified.*\n\n"
            "You have full access. Use /admin for controls.",
            parse_mode='Markdown'
        )
        return

    # Try affiliate check
    is_valid = await verify_iq_user_id(iq_id)

    if not is_valid:
        # Mark referrer check failed but proceed to manual review
        set_referrer_check_passed(tg_id, False)
        set_rejection(
            tg_id,
            'Awaiting manual admin approval — affiliate check pending.'
        )
        # Override status to PENDING for admin review
        from database.db import get_connection
        conn = get_connection()
        conn.execute(
            "UPDATE users SET approval_status='PENDING' WHERE telegram_id=?",
            (tg_id,)
        )
        conn.commit()
        conn.close()

        await update.message.reply_text(
            "⏳ *Manual review needed*\n\n"
            "Your account is pending admin approval. "
            "An admin will review your submission and activate your account.\n\n"
            "_This is temporary — automatic verification will be available soon._",
            parse_mode='Markdown'
        )
        # Notify admin
        from bot.admin.activation import notify_admin_pending_user
        await notify_admin_pending_user(ctx.bot, tg_id)
        return

    # Approved via affiliate check
    set_referrer_check_passed(tg_id, True)
    set_iq_id_verified(tg_id, iq_id)
    log_funnel_event(tg_id, 'VERIFIED')

    await send_image_with_caption(
        ctx.bot,
        chat_id=update.effective_chat.id,
        image_path='assets/verified.png',
        caption=(
            "✅ *Verified!*\n\n"
            "Your IQ Option account is confirmed.\n\n"
            "An admin will now assign you a *token* to activate trading. "
            "You'll be notified once your token is ready.\n\n"
            "_This usually takes a few minutes during business hours._"
        ),
        parse_mode='Markdown',
    )

    from bot.admin.activation import notify_admin_pending_user
    await notify_admin_pending_user(ctx.bot, tg_id)
