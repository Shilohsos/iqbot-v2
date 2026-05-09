"""
Help command — shows available commands based on user tier.
"""
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from database.models.users import get_user


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id) if update.effective_user else None
    is_admin = user and user.get('tier') == 'ADMIN'

    text = (
        "*Available Commands*\n\n"
        "/start — Start or return to the main menu\n"
        "/trade — Open the trade screen\n"
        "/balance — View your IQ Option balance\n"
        "/history — View your trade history\n"
        "/settings — Adjust your preferences\n"
        "/help — Show this message\n"
    )
    if is_admin:
        text += (
            "\n*Admin Commands:*\n"
            "/admin — Open admin panel\n"
            "/find <query> — Find a user\n"
            "/assign\\_token @user TOKEN — Assign a token\n"
            "/broadcast — Compose a broadcast\n"
            "/audit — Generate audit report\n"
        )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
