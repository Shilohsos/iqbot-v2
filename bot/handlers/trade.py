"""
Trade flow — the main event.
Multi-step: pair → timeframe → amount → confirm → execute → result.
"""
import asyncio
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core.redis_bus import publish, subscribe_once
from database.models.bias import get_top_pairs_by_confidence
from database.models.users import get_user
from database.models.accounts import get_user_account_summary
from bot.middleware.approval_gate import require_approved
from bot.ui.images import send_image_with_caption
from bot.ui.messages import format_bias_emoji, format_pnl, reply_safe
from core.currency import format_amount
from bot.ui.keyboards import (
    trade_pairs_keyboard, timeframe_keyboard,
    account_choice_keyboard, trade_result_keyboard,
)
from config import TIER_TRADE_LIMITS


# ── Step 1: Open trade menu ──────────────────────────────────
@require_approved
async def cmd_trade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry point — works from /trade command OR callback."""
    if update.callback_query:
        await update.callback_query.answer()
    user = get_user(update.effective_user.id)
    top_pairs = get_top_pairs_by_confidence(
        timeframe=300,
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
    await update.callback_query.edit_message_text(
        f"*{pair}* selected.\n\nNow pick the *timeframe*:",
        parse_mode='Markdown',
        reply_markup=timeframe_keyboard(),
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

    # Check sufficient balance before sending to watcher
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

    await update.callback_query.answer("Placing trade...")
    await update.callback_query.edit_message_text(
        "⏳ *Analyzing market...*\n\nReading bias and executing trade.",
        parse_mode='Markdown',
    )

    # Send to watcher via Redis
    request_token = uuid.uuid4().hex
    await publish(f'trade-requests:{user["id"]}', {
        'request_token': request_token,
        'pair': pair,
        'amount': amount,
        'duration_seconds': tf,
        'balance_type': balance_type,
    })

    # Wait for OPENED response (max 10s)
    try:
        result = await asyncio.wait_for(
            subscribe_once(
                f'trade-results:{user["id"]}',
                filter_fn=lambda m: m.get('request_token') == request_token,
                timeout=10
            ),
            timeout=10
        )
    except asyncio.TimeoutError:
        await update.callback_query.edit_message_text(
            "⚠️ Trade timed out. Please try again or contact admin."
        )
        return

    if result['status'] == 'NEUTRAL_BIAS':
        bias = result.get('bias', {})
        await update.callback_query.edit_message_text(
            f"⚪ *Market is neutral on {pair}*\n\n"
            f"Bullish: {bias.get('bullish_percent', 0):.1f}%\n"
            f"No clear direction — try another pair or wait.",
            parse_mode='Markdown',
        )
        return

    if result['status'] != 'OPENED':
        await update.callback_query.edit_message_text(
            f"❌ Trade failed: `{result.get('error', result['status'])}`",
            parse_mode='Markdown',
        )
        return

    # Trade opened
    direction = result['direction'].upper()
    bias = result['bias']
    emoji = '🟢' if direction == 'CALL' else '🔴'

    await send_image_with_caption(
        ctx.bot,
        chat_id=update.effective_chat.id,
        image_path=f'assets/trade_{direction.lower()}.png',
        caption=(
            f"{emoji} *TRADE OPENED*\n\n"
            f"Pair: `{pair}`\n"
            f"Direction: *{direction}*\n"
            f"Amount: `{amount}`\n"
            f"Bias: {bias['bullish_percent']:.1f}% bullish\n"
            f"Confidence: {bias['confidence']:.0f}%\n\n"
            f"⏳ _Result in {tf}s..._"
        ),
        parse_mode='Markdown',
    )

    # Wait for CLOSED event
    try:
        close = await asyncio.wait_for(
            subscribe_once(
                f'trade-results:{user["id"]}',
                filter_fn=lambda m: m.get('status') == 'CLOSED',
                timeout=tf + 30,
            ),
            timeout=tf + 30
        )
    except asyncio.TimeoutError:
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Trade result delayed. Check /history shortly.",
        )
        return

    # Show result
    res = close['result']
    pnl = close['pnl']
    if res == 'WIN':
        img = 'assets/trade_win.png'
        caption = f"💚 *WIN!* +{format_pnl(pnl)}"
    elif res == 'LOSS':
        img = 'assets/trade_loss.png'
        caption = f"💔 *LOSS* -{format_amount(abs(amount))}"
    else:
        img = 'assets/trade_tie.png'
        caption = "⚪ *TIE* (stake refunded)"

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
