"""
Currency formatting and detection.
Every user-visible amount uses their actual balance currency, never hardcoded USD.
"""
from typing import Optional

SUPPORTED_CURRENCIES = ['USD', 'EUR', 'GBP', 'NGN', 'KES', 'ZAR', 'BRL', 'INR']

CURRENCY_SYMBOLS = {
    'USD': '$', 'EUR': '€', 'GBP': '£', 'NGN': '₦',
    'KES': 'KSh', 'ZAR': 'R', 'BRL': 'R$', 'INR': '₹',
}


def format_amount(amount: float, currency: str = 'USD') -> str:
    """Format amount with correct currency symbol."""
    sym = CURRENCY_SYMBOLS.get(currency, currency + ' ')
    if amount >= 0:
        return f"{sym}{amount:,.2f}"
    return f"-{sym}{abs(amount):,.2f}"


def detect_currency(balance_data: dict) -> str:
    """
    Extract currency from balance-changed event or balance dict.
    Falls back to 'USD'.
    """
    currency = balance_data.get('currency', '')
    if currency and currency in SUPPORTED_CURRENCIES:
        return currency
    return 'USD'


def symbol_for(currency: str) -> str:
    """Get just the symbol."""
    return CURRENCY_SYMBOLS.get(currency, currency + ' ')
