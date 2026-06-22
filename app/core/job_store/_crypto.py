"""Encryption helpers for secrets at rest (API keys etc.).

Stored secrets carry a prefix to make their encoding visible:
- ``enc:`` — Fernet-encrypted (requires the ``cryptography`` package)
- ``b64:`` — plain base64 (fallback when ``cryptography`` is missing)
- no prefix — legacy plaintext, returned as-is by ``_decrypt_secret``
"""

import base64
import hashlib
import logging

logger = logging.getLogger(__name__)

# Current schema version for migrations
SCHEMA_VERSION = 2

# Guard so the insecure-fallback warning is only emitted once per process.
_fallback_key_warned = False


def _get_encryption_key() -> bytes:
    """Get or derive a Fernet-compatible encryption key for secrets at rest."""
    global _fallback_key_warned
    from ...config import get_settings

    settings = get_settings()
    if settings.encryption_key:
        # Derive a 32-byte key from the user-provided key
        key_bytes = hashlib.sha256(settings.encryption_key.encode()).digest()
    else:
        # Derive a machine-specific key from the download directory path.
        # This is a guessable fallback kept only for backward compatibility
        # with already-stored secrets — production must set ENCRYPTION_KEY.
        if not _fallback_key_warned:
            logger.warning(
                "ENCRYPTION_KEY is not set — deriving the secrets-at-rest key "
                "from DOWNLOAD_DIR, which is guessable. Set ENCRYPTION_KEY for "
                "production to securely encrypt stored API keys."
            )
            _fallback_key_warned = True
        key_bytes = hashlib.sha256(settings.download_dir.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)


def _encrypt_secret(value: str) -> str:
    """Encrypt a secret value for storage."""
    try:
        from cryptography.fernet import Fernet

        f = Fernet(_get_encryption_key())
        return "enc:" + f.encrypt(value.encode()).decode()
    except ImportError:
        logger.warning(
            "cryptography package not installed — storing secret with basic obfuscation"
        )
        encoded = base64.b64encode(value.encode()).decode()
        return "b64:" + encoded


def _decrypt_secret(value: str) -> str:
    """Decrypt a stored secret value."""
    if not value:
        return value
    if value.startswith("enc:"):
        try:
            from cryptography.fernet import Fernet

            f = Fernet(_get_encryption_key())
            return f.decrypt(value[4:].encode()).decode()
        except Exception:
            logger.warning("Failed to decrypt secret — returning empty")
            return ""
    elif value.startswith("b64:"):
        return base64.b64decode(value[4:].encode()).decode()
    # Plaintext (legacy, pre-encryption) — return as-is
    return value
