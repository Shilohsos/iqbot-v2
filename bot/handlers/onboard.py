"""
Onboarding handler — add IQ Option account credentials.
"""
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database.models.users import get_user
from database.models.accounts import add_account
from core.encryption import encrypt_credential
from bot.middleware.approval_gate import require_approved
from utils.logger import get_logger

logger = get_logger("onboard")

EMAIL, PASSWORD = range(2)


@require_approved
async def cmd_addaccount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or user['approval_status'] != 'APPROVED':
        await update.message.reply_text("🔒 Your account is not approved yet.")
        return ConversationHandler.END

    await update.message.reply_text(
        "📧 Send your *IQ Option email* (the one you log in with):",
        parse_mode='Markdown'
    )
    return EMAIL


async def receive_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if '@' not in email:
        await update.message.reply_text("That doesn't look like an email. Try again.")
        return EMAIL

    ctx.user_data['onboard_email'] = email
    await update.message.reply_text(
        "🔐 Now send your *IQ Option password*.\n"
        "_It will be encrypted before storage and never shared._",
        parse_mode='Markdown'
    )
    return PASSWORD


async def receive_password(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    email = ctx.user_data.get('onboard_email', '')

    # Delete the password message immediately
    try:
        await update.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete password message for user {update.effective_user.id}: {e}")

    user = get_user(update.effective_user.id)

    # Acquire SSID before saving
    from core.iq_login import acquire_ssid
    try:
        ssid, _ = await acquire_ssid(email, password)
    except RuntimeError as e:
        await update.message.reply_text(
            f"❌ Could not log in to IQ Option:\n\n_{e}_\n\nPlease verify your credentials and try again.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    # Encrypt credentials
    email_enc = encrypt_credential(email)
    pass_enc = encrypt_credential(password)

    add_account(
        user_id=user['id'],
        email_encrypted=email_enc,
        password_encrypted=pass_enc,
        ssid=ssid,
        platform_id=int(os.getenv('PLATFORM_ID', '0'))
    )

    from database.models.users import log_funnel_event
    log_funnel_event(update.effective_user.id, 'ADDED_ACCOUNT')

    await update.message.reply_text(
        "✅ *Account connected. Watcher is now starting up.*\n\n"
        "Use /trade when ready.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💹 Start Trading", callback_data='open_trade')],
        ])
    )

    return ConversationHandler.END


async def cancel_onboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Onboarding cancelled.")
    return ConversationHandler.END
