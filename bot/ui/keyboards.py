"""
Inline keyboard builders.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def trade_pairs_keyboard(pairs: list, include_cancel: bool = True) -> InlineKeyboardMarkup:
    """Build keyboard showing top pairs with bias %."""
    keyboard = []
    for p in pairs:
        pair = p['asset']
        bullish = p['bullish_percent']
        emoji = '🟢' if bullish >= 55 else ('🔴' if bullish <= 45 else '⚪')
        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} {pair} ({bullish:.0f}%)",
                callback_data=f"select_pair:{pair}"
            )
        ])
    if include_cancel:
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_trade')])
    return InlineKeyboardMarkup(keyboard)


_TF_LABELS = {30: "30s", 60: "1m", 300: "5m", 600: "10m"}

def timeframe_keyboard(allowed: list = None, include_cancel: bool = True) -> InlineKeyboardMarkup:
    all_tfs = [30, 60, 300, 600]
    tfs = [tf for tf in all_tfs if allowed is None or tf in allowed]
    row = [InlineKeyboardButton(_TF_LABELS[tf], callback_data=f'select_tf:{tf}') for tf in tfs]
    keyboard = [row]
    if include_cancel:
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_trade')])
    return InlineKeyboardMarkup(keyboard)


def account_choice_keyboard(practice_bal: float, practice_curr: str,
                             real_bal: float, real_curr: str) -> InlineKeyboardMarkup:
    from core.currency import format_amount
    keyboard = [
        [InlineKeyboardButton(
            f"🎮 PRACTICE ({format_amount(practice_bal, practice_curr)})",
            callback_data='confirm_trade:PRACTICE'
        )],
        [InlineKeyboardButton(
            f"💎 LIVE ({format_amount(real_bal, real_curr)})",
            callback_data='confirm_trade:REAL'
        )],
        [InlineKeyboardButton("❌ Cancel", callback_data='cancel_trade')],
    ]
    return InlineKeyboardMarkup(keyboard)


def welcome_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I have an IQ Option account", callback_data='have_account')],
        [InlineKeyboardButton("🆕 I need to create one", callback_data='need_account')],
    ])


def trade_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Trade Again", callback_data='new_trade')],
        [InlineKeyboardButton("📊 History", callback_data='show_history')],
    ])


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💹 Trade", callback_data='open_trade')],
        [InlineKeyboardButton("💰 Balance", callback_data='show_balance')],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data='show_leaderboard')],
        [InlineKeyboardButton("⚙️ Settings", callback_data='show_settings')],
    ])


# ── Back-button helpers ──────────────────────────────────────

def back_to_menu_keyboard():
    """Single 'Back to menu' button for user-side screens."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to menu", callback_data='back_to_user_menu')]
    ])


def back_to_admin_keyboard():
    """Single 'Back to admin panel' button."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data='back_to_admin')]
    ])


def with_back_to_menu(rows):
    """Wrap an existing keyboard with a 'Back to menu' row."""
    return InlineKeyboardMarkup(
        rows + [[InlineKeyboardButton("🔙 Back to menu", callback_data='back_to_user_menu')]]
    )


def with_back_to_admin(rows):
    """Wrap an existing keyboard with a 'Back' row."""
    return InlineKeyboardMarkup(
        rows + [[InlineKeyboardButton("🔙 Back", callback_data='back_to_admin')]]
    )
