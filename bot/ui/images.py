"""
Image sending helpers.
Uses static assets from /root/iqbot-v2/assets/.
"""
import os
from telegram import Bot

ASSETS_DIR = os.path.join(os.path.dirname(__file__), '..', '..')


async def send_image_with_caption(bot: Bot, chat_id: int, image_path: str,
                                    caption: str = None, parse_mode: str = None,
                                    reply_markup=None):
    """Send an image with optional caption and keyboard."""
    full_path = os.path.join(ASSETS_DIR, image_path) if not os.path.isabs(image_path) else image_path

    if not os.path.exists(full_path):
        # Fall back to text-only if image missing
        if caption:
            await bot.send_message(
                chat_id=chat_id, text=caption,
                parse_mode=parse_mode, reply_markup=reply_markup
            )
        return

    with open(full_path, 'rb') as f:
        await bot.send_photo(
            chat_id=chat_id, photo=f,
            caption=caption, parse_mode=parse_mode,
            reply_markup=reply_markup
        )


async def edit_message_smart(query, text: str, **kwargs):
    """
    Edits a message correctly whether it's a photo (caption) or text.
    Use on callback_query.message instead of edit_message_text/caption.
    """
    from telegram.error import BadRequest
    msg = query.message
    if msg and (msg.photo or msg.video or msg.animation):
        try:
            return await query.edit_message_caption(caption=text, **kwargs)
        except BadRequest:
            return await msg.reply_text(text=text, **kwargs)
    else:
        try:
            return await query.edit_message_text(text=text, **kwargs)
        except BadRequest:
            return await msg.reply_text(text=text, **kwargs)
