"""
Fernet-based credential encryption.
All IQ Option emails/passwords stored encrypted at rest.
"""
import os
from cryptography.fernet import Fernet

_KEY = None


def _get_fernet() -> Fernet:
    global _KEY
    if _KEY is None:
        key = os.getenv('FERNET_KEY')
        if not key:
            # Generate one on first use if env var not set
            key = Fernet.generate_key().decode()
            print(f"WARNING: FERNET_KEY not set. Generated: {key}")
            print("Save this in your .env file!")
        _KEY = Fernet(key.encode())
    return _KEY


def encrypt_credential(plaintext: str) -> str:
    """Encrypt a credential. Returns hex token."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_credential(token: str) -> str:
    """Decrypt a credential. Returns plaintext."""
    f = _get_fernet()
    return f.decrypt(token.encode()).decode()
