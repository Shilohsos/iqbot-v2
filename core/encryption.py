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
            raise RuntimeError(
                "FERNET_KEY environment variable is not set. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
                "and add it to your .env file."
            )
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
