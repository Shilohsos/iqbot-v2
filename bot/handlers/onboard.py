"""
Onboarding handler — connect an IQ Option account.

Two flows depending on server configuration:
  OAuth (preferred): If OAUTH_CLIENT_ID is set, users authorise via a browser
    link — no password ever enters Telegram. Bot receives the token via the
    /oauth/callback aiohttp endpoint in main_bot.py.
  Password (fallback): Legacy email/password conversation when OAuth is not
    configured. Credentials are encrypted before storage.
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

    from config import OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, OAUTH_REDIRECT_URI
    if OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET and OAUTH_REDIRECT_URI:
        return await _start_oauth_flow(update, ctx, user)

    # Fallback: email/password conversation
    await update.message.reply_text(
        "📧 Send your *IQ Option email* (the one you log in with):",
        parse_mode='Markdown'
    )
    return EMAIL


async def _start_oauth_flow(update, ctx, user):
    """Generate PKCE state + send the IQ Option authorization URL to the user."""
    from config import OAUTH_CLIENT_ID, OAUTH_REDIRECT_URI
    from core.iq_oauth import register_pending, build_authorize_url

    state, verifier = register_pending(update.effective_user.id)
    # verifier is stored inside iq_oauth._pending keyed by state — we don't
    # need to hold it here; the callback handler will look it up.
    auth_url = build_authorize_url(
        client_id=OAUTH_CLIENT_ID,
        redirect_uri=OAUTH_REDIRECT_URI,
        state=state,
        verifier=verifier,
    )

    await update.message.reply_text(
        "🔗 *Connect your IQ Option account*\n\n"
        "Click the button below to authorise securely via IQ Option.\n"
        "Your password never enters Telegram.\n\n"
        "_The link expires in 10 minutes._",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 Authorise on IQ Option", url=auth_url)],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel_oauth')],
        ])
    )
    return ConversationHandler.END


# ── Password flow ──────────────────────────────────────────────────────────────

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
        logger.warning(
            f"Could not delete password message for user {update.effective_user.id}: {e}"
        )

    user = get_user(update.effective_user.id)

    # Acquire SSID before saving
    from core.iq_login import acquire_ssid
    try:
        ssid, _ = await acquire_ssid(email, password)
    except RuntimeError as e:
        await update.message.reply_text(
            f"❌ Could not log in to IQ Option:\n\n_{e}_\n\n"
            "Please verify your credentials and try again.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    email_enc = encrypt_credential(email)
    pass_enc = encrypt_credential(password)

    add_account(
        user_id=user['id'],
        email_encrypted=email_enc,
        password_encrypted=pass_enc,
        ssid=ssid,
        platform_id=int(os.getenv('PLATFORM_ID', '0'))
    )

    _post_connect(user['id'], update.effective_user.id)

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


# ── Shared post-connect logic ──────────────────────────────────────────────────

def _post_connect(db_user_id: int, telegram_id: int):
    """Log funnel event and spawn the watcher after any successful connect."""
    from database.models.funnel import log_funnel_event
    log_funnel_event(telegram_id, 'ADDED_ACCOUNT')
    try:
        from utils.pm2_manager import spawn_watcher
        if not spawn_watcher(db_user_id):
            logger.error(f"Failed to spawn watcher for user_id={db_user_id}")
    except Exception as e:
        logger.error(f"spawn_watcher raised for user_id={db_user_id}: {e}")
