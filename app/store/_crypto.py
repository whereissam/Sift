"""Encryption helpers for secrets at rest (API keys etc.).

Stored secrets carry a prefix to make their encoding visible:
- ``enc:`` — Fernet-encrypted (requires the ``cryptography`` package)
- ``b64:`` — plain base64 (fallback when ``cryptography`` is missing)
- no prefix — legacy plaintext, returned as-is by ``_decrypt_secret``

The key comes from ENCRYPTION_KEY when set. Otherwise a random key is
generated on first use and kept in ENCRYPTION_KEY_FILE (default
``~/.config/sift/secret.key``), outside the download directory that holds
the database, so a copy of jobs.db or a backup is not enough to decrypt it.

Older versions derived the key from DOWNLOAD_DIR when ENCRYPTION_KEY was
unset — a public constant (sha256("/app/output") on every Docker install).
Values under that key still decrypt, and ``rotate_secret`` re-encrypts them
under the current key.
"""

import base64
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Current schema version for migrations
SCHEMA_VERSION = 2

# Generated keys, by key-file path, so the file is read once per process.
_key_file_cache: dict[str, bytes] = {}
_fallback_key_warned = False


def _derive(secret: str) -> bytes:
    """A Fernet key derived from an arbitrary secret string."""
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


def _key_file_path(settings) -> Path:
    if settings.encryption_key_file:
        return Path(settings.encryption_key_file).expanduser()
    return Path.home() / ".config" / "sift" / "secret.key"


def _load_or_create_key_file(path: Path) -> bytes:
    """Read the generated key at ``path``, creating it (mode 0600) if absent."""
    cached = _key_file_cache.get(str(path))
    if cached:
        return cached
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = base64.urlsafe_b64encode(os.urandom(32))
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass  # another process created it first; read theirs
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(key)
            logger.info("Generated a secrets-at-rest key at %s", path)
    key = path.read_bytes().strip()
    if len(base64.urlsafe_b64decode(key)) != 32:
        raise ValueError(f"{path} does not hold a valid encryption key")
    _key_file_cache[str(path)] = key
    return key


def _legacy_key() -> bytes:
    """The old DOWNLOAD_DIR-derived key, kept only to read old values."""
    from ..config import get_settings

    return _derive(get_settings().download_dir)


def _get_encryption_key() -> bytes:
    """Get the Fernet-compatible key for secrets at rest."""
    global _fallback_key_warned
    from ..config import get_settings

    settings = get_settings()
    if settings.encryption_key:
        return _derive(settings.encryption_key)
    try:
        return _load_or_create_key_file(_key_file_path(settings))
    except (OSError, ValueError) as e:
        # No writable place for a key: keep working, but loudly.
        if not _fallback_key_warned:
            logger.warning(
                "Cannot use the encryption key file (%s); falling back to a key "
                "derived from DOWNLOAD_DIR, which is guessable. Set "
                "ENCRYPTION_KEY or ENCRYPTION_KEY_FILE.",
                e,
            )
            _fallback_key_warned = True
        return _legacy_key()


def _fernet():
    """MultiFernet that encrypts with the current key and reads old values."""
    from cryptography.fernet import Fernet, MultiFernet

    keys = [_get_encryption_key()]
    legacy = _legacy_key()
    if legacy not in keys:
        keys.append(legacy)
    return MultiFernet([Fernet(k) for k in keys])


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
            return _fernet().decrypt(value[4:].encode()).decode()
        except Exception:
            logger.warning("Failed to decrypt secret — returning empty")
            return ""
    elif value.startswith("b64:"):
        return base64.b64decode(value[4:].encode()).decode()
    # Plaintext (legacy, pre-encryption) — return as-is
    return value


def rotate_secret(value: Optional[str]) -> Optional[str]:
    """``value`` re-encrypted under the current key, or None if unchanged.

    Only ``enc:`` values that the current key cannot read (old
    DOWNLOAD_DIR-derived ones) are rewritten.
    """
    if not value or not value.startswith("enc:"):
        return None
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError:
        return None
    token = value[4:].encode()
    try:
        Fernet(_get_encryption_key()).decrypt(token)
        return None
    except InvalidToken:
        pass
    try:
        return "enc:" + _fernet().rotate(token).decode()
    except InvalidToken:
        return None  # unreadable under every known key; leave it alone
