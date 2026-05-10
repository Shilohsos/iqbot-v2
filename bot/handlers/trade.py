"""
Trade flow — the main event.
Multi-step: pair → timeframe → amount → confirm → execute → result.
"""
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.models.bias import get_top_pairs_by_confidence, get_current_bias
from database.models.users import get_user
from database.models.accounts import get_user_account_summary, get_account_credentials, update_balance
from database.models.trades import log_trade, update_trade_result
from bot.middleware.approval_gate import require_approved
from bot.ui.images import send_image_with_caption
from bot.ui.messages import format_bias_emoji, format_pnl, reply_safe
from core.currency import format_amount
from bot.ui.keyboards import (
    trade_pairs_keyboard, timeframe_keyboard,
    account_choice_keyboard, trade_result_keyboard,
)
from config import TIER_TRADE_LIMITS


def _apply_balances(user_id: int, balances: list | None):
    """Persist a refreshed balances list into the accounts table."""
    if not balances:
        return
    for bal in balances:
        try:
            update_balance(
                user_id,
                bal.get('type', 4),
                bal.get('amount', 0),
                bal.get('currency', 'USD'),
            )
        except Exception:
            pass


# ── Step 1: Open trade menu ──────────────────────────────────
@require_approved
async def cmd_trade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry point — works from /trade command OR callback."""
    if update.callback_query:
        await update.callback_query.answer()
    user = get_user(update.effective_user.id)
    top_pairs = get_top_pairs_by_confidence(
        timeframe=60,
        limit=8 if user['tier'] == 'PRO' else 4
    )

    if not top_pairs:
        await reply_safe(
            update,
            text="⚠️ No bias data available yet. The engine may be starting up. Try again shortly."
        )
        return

    keyboard = []
    for pair_info in top_pairs:
        pair = pair_info['asset']
        bullish = pair_info['bullish_percent']
        emoji = format_bias_emoji(bullish)
        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} {pair} ({bullish:.0f}%)",
                callback_data=f"select_pair:{pair}"
            )
        ])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_trade')])

    await reply_safe(
        update,
        text=(
            "*Live Market Bias* 💜\n\n"
            "These pairs are trending strongest right now:\n"
            "🟢 = bullish bias  |  🔴 = bearish bias\n\n"
            "Pick a pair to trade:"
        ),
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Step 2: User picks a pair ────────────────────────────────
async def cb_select_pair(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pair = update.callback_query.data.split(':', 1)[1]
    ctx.user_data['trade_pair'] = pair
    await update.callback_query.answer()
    user = get_user(update.effective_user.id)
    tier = user.get('tier', 'NEWBIE') if user else 'NEWBIE'
    allowed_tfs = TIER_TRADE_LIMITS.get(tier, TIER_TRADE_LIMITS.get('NEWBIE', {})).get('timeframes', [60, 180, 300, 900])
    await update.callback_query.edit_message_text(
        f"*{pair}* selected.\n\nNow pick the *timeframe*:",
        parse_mode='Markdown',
        reply_markup=timeframe_keyboard(allowed=allowed_tfs),
    )


# ── Step 3: User picks a timeframe ───────────────────────────
async def cb_select_timeframe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tf = int(update.callback_query.data.split(':', 1)[1])
    ctx.user_data['trade_timeframe'] = tf
    pair = ctx.user_data['trade_pair']
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        f"*{pair}* @ *{tf}s*\n\n"
        f"How much do you want to trade? (in your account's currency)\n\n"
        f"Send the amount as a number (e.g., `10` or `25.50`):",
        parse_mode='Markdown',
    )
    ctx.user_data['awaiting_amount'] = True


# ── Step 4: User types amount ────────────────────────────────
async def msg_trade_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get('awaiting_amount'):
        return
    if not update.message or not update.message.text:
        return

    raw = update.message.text.strip()
    try:
        # Reject scientific notation (e.g. 1e10) before float conversion
        if 'e' in raw.lower():
            raise ValueError("scientific notation not allowed")
        amount = float(raw)
    except ValueError:
        await update.message.reply_text("Invalid amount. Send a plain number (e.g. 10 or 25.50).")
        return

    if amount <= 0:
        await update.message.reply_text("Amount must be positive.")
        return

    user = get_user(update.effective_user.id)
    limits = TIER_TRADE_LIMITS.get(user['tier'] if user else '', {})
    min_amount = limits.get('min', 1)
    max_amount = limits.get('max', 50)
    if amount < min_amount or amount > max_amount:
        await update.message.reply_text(
            f"Amount must be between {min_amount} and {max_amount} for your tier."
        )
        return

    ctx.user_data['awaiting_amount'] = False
    ctx.user_data['trade_amount'] = amount

    summary = get_user_account_summary(user['id'])
    pair = ctx.user_data['trade_pair']
    tf = ctx.user_data['trade_timeframe']

    await update.message.reply_text(
        f"*Trade Confirmation* 💜\n\n"
        f"Pair: `{pair}`\n"
        f"Duration: `{tf}s`\n"
        f"Amount: `{amount}`\n\n"
        f"_Direction will be set automatically based on current market bias._\n\n"
        f"Choose your account:",
        parse_mode='Markdown',
        reply_markup=account_choice_keyboard(
            summary['practice_balance'], summary['practice_currency'],
            summary['real_balance'], summary['real_currency'],
        ),
    )


# ── Step 5: User confirms — fire the trade ───────────────────
async def cb_confirm_trade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    balance_type = update.callback_query.data.split(':', 1)[1]
    user = get_user(update.effective_user.id)
    pair = ctx.user_data['trade_pair']
    tf = ctx.user_data['trade_timeframe']
    amount = ctx.user_data['trade_amount']

    # Block trade if user has no linked IQ Option account
    account = get_account_credentials(user['id'])
    if not account:
        await update.callback_query.answer("No account linked.", show_alert=True)
        await update.callback_query.edit_message_text(
            "❌ *No IQ Option account linked.*\n\n"
            "Use /addaccount to connect your account before trading.",
            parse_mode='Markdown',
        )
        return

    # Read bias from DB and determine direction before connecting
    bias = get_current_bias(pair, tf)
    if not bias:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            f"⏳ *No market data yet for {pair}*\n\n"
            f"The bias engine hasn't computed this pair/timeframe yet. "
            f"Try again in 30–60 seconds or select a different timeframe.",
            parse_mode='Markdown',
        )
        return

    if bias['bullish_percent'] >= 55:
        direction = 'call'
    elif bias['bullish_percent'] <= 45:
        direction = 'put'
    else:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            f"⚪ *Market is neutral on {pair}*\n\n"
            f"Bullish: {bias['bullish_percent']:.1f}%\n"
            f"No clear direction — try another pair or wait.",
            parse_mode='Markdown',
        )
        return

    # Check sufficient balance (uses DB cache)
    summary = get_user_account_summary(user['id'])
    available = (
        summary['practice_balance'] if balance_type == 'PRACTICE'
        else summary['real_balance']
    )
    if available < amount:
        await update.callback_query.answer("Insufficient balance.", show_alert=True)
        await update.callback_query.edit_message_text(
            f"❌ Insufficient balance. Available: `{available:.2f}`, needed: `{amount}`.",
            parse_mode='Markdown',
        )
        return

    dir_emoji = '🟢' if direction == 'call' else '🔴'
    await update.callback_query.answer("Placing trade...")
    await update.callback_query.edit_message_text(
        f"⏳ *Placing trade...*\n\n"
        f"Pair: `{pair}`\n"
        f"Direction: {dir_emoji} *{direction.upper()}*\n"
        f"Amount: `{amount}`\n"
        f"Bias: {bias['bullish_percent']:.1f}% bullish\n\n"
        f"_Connecting to IQ Option..._",
        parse_mode='Markdown',
    )

    from core.trade_executor import execute_trade
    from core.iq_login import refresh_ssid_if_stale

    fresh_ssid = await refresh_ssid_if_stale(account['id'])
    if not fresh_ssid:
        await update.callback_query.edit_message_text(
            "❌ Could not refresh session. Please re-link your account with /addaccount.",
        )
        return

    result = await execute_trade(
        ssid=fresh_ssid,
        platform_id=account['platform_id'],
        pair=pair,
        direction=direction,
        amount=amount,
        duration_seconds=tf,
        balance_type=balance_type,
    )

    # Always persist any refreshed balances we got back, regardless of status
    _apply_balances(user['id'], result.get('balances'))

    if result['status'] == 'ERROR':
        await update.callback_query.edit_message_text(
            f"❌ Trade failed: {result['error']}",
            parse_mode='Markdown',
        )
        return

    iq_id = int(result['trade_id']) if result.get('trade_id') else None

    if result['status'] == 'TIMEOUT':
        log_trade(
            user_id=user['id'], pair=pair, direction=direction,
            amount=amount, duration_seconds=tf, iq_option_id=iq_id,
            bias_at_entry=bias['bullish_percent'],
            confidence_at_entry=bias['confidence'],
            balance_type=balance_type,
        )
        await update.callback_query.edit_message_text(
            "⚠️ Trade placed but result unknown. Check /history shortly.",
        )
        return

    # WIN / LOSS / TIE
    log_trade(
        user_id=user['id'], pair=pair, direction=direction,
        amount=amount, duration_seconds=tf, iq_option_id=iq_id,
        bias_at_entry=bias['bullish_percent'],
        confidence_at_entry=bias['confidence'],
        balance_type=balance_type,
    )
    if iq_id:
        update_trade_result(iq_id, result['status'], result['pnl'])

    pnl = result['pnl']
    res = result['status']
    if res == 'WIN':
        img = 'assets/trade_win.png'
        caption = (
            f"💚 *WIN!* {format_pnl(pnl)}\n\n"
            f"Pair: `{pair}`  Direction: *{direction.upper()}*  Amount: `{amount}`"
        )
    elif res == 'LOSS':
        img = 'assets/trade_loss.png'
        caption = (
            f"💔 *LOSS* -{format_amount(abs(amount))}\n\n"
            f"Pair: `{pair}`  Direction: *{direction.upper()}*  Amount: `{amount}`"
        )
    else:
        img = 'assets/trade_tie.png'
        caption = (
            f"⚪ *TIE* (stake refunded)\n\n"
            f"Pair: `{pair}`  Direction: *{direction.upper()}*"
        )

    await send_image_with_caption(
        ctx.bot,
        chat_id=update.effective_chat.id,
        image_path=img,
        caption=caption,
        parse_mode='Markdown',
        reply_markup=trade_result_keyboard(),
    )


# ── Cancel / New trade ───────────────────────────────────────
async def cb_cancel_trade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Trade cancelled.")
    # Clear trade state
    for key in ['trade_pair', 'trade_timeframe', 'trade_amount', 'awaiting_amount']:
        ctx.user_data.pop(key, None)


async def cb_new_trade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await cmd_trade(update, ctx)
