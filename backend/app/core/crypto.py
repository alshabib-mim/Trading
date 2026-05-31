import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LEN = 12


class EncryptionKeyError(RuntimeError):
    """Raised when ENCRYPTION_KEY is missing or not a base64-encoded 32-byte key."""


def _load_key() -> bytes:
    raw = os.getenv("ENCRYPTION_KEY")
    if not raw:
        raise EncryptionKeyError("ENCRYPTION_KEY is not set")
    try:
        key = base64.b64decode(raw)
    except Exception as exc:
        raise EncryptionKeyError("ENCRYPTION_KEY is not valid base64") from exc
    if len(key) != 32:
        raise EncryptionKeyError(
            f"ENCRYPTION_KEY must decode to 32 bytes (AES-256), got {len(key)}"
        )
    return key


def validate_encryption_key() -> None:
    """Fail fast at startup if the key is missing or malformed — never run with no encryption."""
    _load_key()


def encrypt(plaintext: str) -> str:
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(_load_key()).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt(token: str) -> str:
    raw = base64.b64decode(token)
    nonce, ciphertext = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    return AESGCM(_load_key()).decrypt(nonce, ciphertext, None).decode()
