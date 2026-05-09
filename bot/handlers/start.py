"""
/start handler — welcome flow with state-based routing.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.models.users import upsert_user, log_funnel_event, get_user
from bot.ui.images import send_image_with_caption
from bot.ui.keyboards import welcome_keyboard
from bot.ui.messages import WELCOME_TEXT


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    user = upsert_user(
        telegram_id=tg_user.id,
        telegram_username=tg_user.username or '',
    )
    log_funnel_event(tg_user.id, 'STARTED')

    # ── State-based routing ──
    tier = user.get('tier', 'PENDING')
    status = user.get('approval_status', 'PENDING')

    # 1. Admin
    if tier == 'ADMIN':
        await show_admin_panel(update, ctx)
        return

    # 2. Banned
    if tier == 'BANNED':
        await update.message.reply_text(
            "🚫 *Access Revoked*\n\n"
            "Your account has been suspended. Contact support if you believe this is in error.",
            parse_mode='Markdown'
        )
        return

    # 3. Approved + has token → main menu
    if status == 'APPROVED' and user.get('token'):
        await show_user_menu(update, ctx)
        return

    # 4. Approved but no token → waiting
    if status == 'APPROVED' and not user.get('token'):
        await update.message.reply_text(
            "⏳ *Token pending*\n\n"
            "Your account is approved but awaiting token assignment. "
            "An admin will assign your token shortly.\n\n"
            "You'll be notified the moment your token is ready.",
            parse_mode='Markdown'
        )
        return

    # 5. Rejected
    if status == 'REJECTED':
        reason = user.get('rejection_reason') or 'Not specified'
        await update.message.reply_text(
            f"❌ Your application was not approved.\n\n"
            f"*Reason:* _{reason}_\n\n"
            f"If you believe this is in error, contact support.",
            parse_mode='Markdown'
        )
        return

    # 6. Pending with IQ ID → under review
    if user.get('iq_user_id') and status == 'PENDING':
        await update.message.reply_text(
            "⏳ Your application is under review. We'll notify you once approved."
        )
        return

    # 7. New user → welcome flow
    await show_welcome_flow(update, ctx)


async def show_welcome_flow(update, ctx):
    """The original new-user welcome — extracted into its own function."""
    await send_image_with_caption(
        ctx.bot,
        chat_id=update.effective_chat.id,
        image_path='assets/welcome.png',
        caption=WELCOME_TEXT,
        parse_mode='Markdown',
        reply_markup=welcome_keyboard(),
    )


async def show_user_menu(update, ctx):
    """Main menu for approved + tokened users."""
    user = get_user(update.effective_user.id)
    keyboard = [
        [InlineKeyboardButton("💹 Trade", callback_data='open_trade')],
        [InlineKeyboardButton("💰 Balance", callback_data='show_balance')],
        [InlineKeyboardButton("📊 History", callback_data='show_history')],
    ]
    if user.get('tier') == 'PRO':
        keyboard.append([InlineKeyboardButton("🏆 Leaderboard", callback_data='show_leaderboard')])
    keyboard.append([InlineKeyboardButton("⚙️ Settings", callback_data='show_settings')])
    keyboard.append([InlineKeyboardButton("ℹ️ About", callback_data='show_about')])

    await update.message.reply_text(
        f"💜 Welcome back, *@{update.effective_user.username or 'trader'}*\n\n"
        f"Your tier: *{user.get('tier', 'NEWBIE')}*\n\n"
        f"What would you like to do?",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_admin_panel(update, ctx):
    """Admin menu shown when admin types /start."""
    keyboard = [
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
    ]
    from bot.ui.messages import reply_safe
    await reply_safe(update,
        text="⚡ *Admin Panel*\n\nSelect an option:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Callback handlers for welcome buttons ────────────────────

async def cb_have_account(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User clicked 'I have an account' → ask for User ID."""
    query = update.callback_query
    await query.answer()
    caption = (
        "Please send me your *IQ Option User ID*.\n\n"
        "📋 *How to find it:*\n"
        "1. Open IQ Option app or website\n"
        "2. Go to Profile → Settings\n"
        "3. Your user ID appears at the top\n\n"
        "Send the number now (e.g., `123456789`)."
    )
    from bot.ui.images import edit_message_smart
    await edit_message_smart(query, caption, parse_mode='Markdown')
    ctx.user_data['awaiting_iq_id'] = True


async def cb_need_account(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User clicked 'Need to create' → show affiliate link."""
    from config import AFFILIATE_LINK
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    query = update.callback_query
    await query.answer()
    caption = (
        "*Create your IQ Option account* 💜\n\n"
        "Sign up via my affiliate link. This is REQUIRED — only accounts "
        "created through this link can use the bot.\n\n"
        "After signing up, send /start again and click 'I have an account' "
        "to submit your User ID."
    )
    from bot.ui.images import edit_message_smart
    await edit_message_smart(
        query, caption, parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Sign up on IQ Option", url=AFFILIATE_LINK)],
        ])
    )


# ── Back navigation handlers ─────────────────────────────────

async def cb_back_to_user_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Return to user main menu."""
    if update.callback_query:
        await update.callback_query.answer()
    elif update.message:
        pass  # /menu command
    
    user = get_user(update.effective_user.id)
    if not user or user.get('tier') == 'ADMIN':
        await show_admin_panel(update, ctx)
        return
    
    from bot.ui.messages import reply_safe
    keyboard = [
        [InlineKeyboardButton("💹 Trade", callback_data='open_trade')],
        [InlineKeyboardButton("💰 Balance", callback_data='show_balance')],
        [InlineKeyboardButton("📊 History", callback_data='show_history')],
    ]
    if user.get('tier') == 'PRO':
        keyboard.append([InlineKeyboardButton("🏆 Leaderboard", callback_data='show_leaderboard')])
    keyboard.append([InlineKeyboardButton("⚙️ Settings", callback_data='show_settings')])
    keyboard.append([InlineKeyboardButton("ℹ️ About", callback_data='show_about')])
    
    await reply_safe(
        update,
        text=(
            f"💜 *@{update.effective_user.username or 'trader'}*\n\n"
            f"Tier: *{user.get('tier', 'NEWBIE')}*\n\n"
            f"What would you like to do?"
        ),
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cb_back_to_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Return to admin panel."""
    if update.callback_query:
        await update.callback_query.answer()
    
    from bot.ui.messages import reply_safe
    keyboard = [
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
    ]
    await reply_safe(update,
        text="⚡ *Admin Panel*\n\nSelect an option:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
