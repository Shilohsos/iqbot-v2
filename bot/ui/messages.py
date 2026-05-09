"""
Message templates and formatting helpers for the bot UI.
"""
from core.currency import format_amount


WELCOME_TEXT = """\
💜 *Hart Trading Bot*

This is the most sophisticated automated trading assistant you'll ever use.

Powered by real-time market bias analysis and direct integration with IQ Option.

Choose an option to begin:\
"""


def format_bias_emoji(bullish: float) -> str:
    if bullish >= 55:
        return '🟢'
    elif bullish <= 45:
        return '🔴'
    return '⚪'


def format_pnl(amount: float, currency: str = 'USD') -> str:
    """Format PNL with sign and currency."""
    formatted = format_amount(abs(amount), currency)
    if amount >= 0:
        return f"+{formatted}"
    return f"-{formatted}"


def format_trade_result(direction: str, pair: str, amount: float,
                         duration: int, bias: dict) -> str:
    emoji = '🟢' if direction.upper() == 'CALL' else '🔴'
    return (
        f"{emoji} *TRADE OPENED*\n\n"
        f"Pair: `{pair}`\n"
        f"Direction: *{direction.upper()}*\n"
        f"Amount: `{amount}`\n"
        f"Duration: `{duration}s`\n\n"
        f"Bias: {bias['bullish_percent']:.1f}% bullish\n"
        f"Confidence: {bias['confidence']:.0f}%\n\n"
        f"⏳ _Result in {duration}s..._"
    )


async def reply_safe(update, text=None, **kwargs):
    """
    Reply correctly whether triggered by message or callback query.
    For callbacks: edits message in place (or sends new if not editable).
    For messages: sends new reply.
    """
    if update.callback_query:
        try:
            if update.callback_query.message and update.callback_query.message.text:
                return await update.callback_query.edit_message_text(text=text, **kwargs)
            elif update.callback_query.message:
                return await update.callback_query.edit_message_caption(caption=text, **kwargs)
        except Exception:
            pass
        if update.callback_query.message:
            return await update.callback_query.message.reply_text(text=text, **kwargs)
        return None
    elif update.message:
        return await update.message.reply_text(text=text, **kwargs)
    elif update.effective_chat:
        bot = update.get_bot()
        return await bot.send_message(chat_id=update.effective_chat.id, text=text, **kwargs)
    return None
