"""
Message templates and formatting helpers for the bot UI.
"""
from core.currency import format_amount
from utils.logger import get_logger

_log = get_logger("ui")


WELCOME_TEXT = """\
💜 *Hart Trading Bot*

This is the most sophisticated automated trading assistant you'll ever use.

Powered by real-time market bias analysis and direct integration with IQ Option.

Choose an option to begin:\
"""


def md_escape(text: str) -> str:
    """Escape Telegram MarkdownV1 metacharacters in untrusted text."""
    if text is None:
        return ''
    return (
        str(text)
        .replace('\\', '\\\\')
        .replace('_', '\\_')
        .replace('*', '\\*')
        .replace('`', '\\`')
        .replace('[', '\\[')
    )


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
        except Exception as e:
            _log.debug(f"reply_safe: edit failed, falling back to reply_text: {e}")
        if update.callback_query.message:
            return await update.callback_query.message.reply_text(text=text, **kwargs)
        return None
    elif update.message:
        return await update.message.reply_text(text=text, **kwargs)
    return None
