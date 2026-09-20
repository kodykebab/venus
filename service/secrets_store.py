"""Encrypts the API keys installations hand us.

An Anthropic key is a live billing credential belonging to someone else. Storing
it in plaintext would mean a read-only leak of the database - a stray backup, a
mounted volume, a SQL injection we haven't found - is immediately a leak of
every customer's key.

Encrypted at rest with a key the database does not contain, so reading the file
is not enough. This is not protection against an attacker who already has code
execution on the host: they have the encryption key too. It is protection
against the much more common case where data escapes and the process does not.

Not named `secrets.py`: that shadows the stdlib module store.py imports.
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


class EncryptionUnavailable(RuntimeError):
    """Raised when there is nowhere safe to put a key, rather than falling back
    to storing it in the clear."""


def _fernet() -> Fernet:
    configured = (
        os.environ.get("PARACHECK_ENCRYPTION_KEY")
        or os.environ.get("GITHUB_WEBHOOK_SECRET")
    )
    if not configured:
        raise EncryptionUnavailable(
            "Set PARACHECK_ENCRYPTION_KEY (or GITHUB_WEBHOOK_SECRET) before storing API keys."
        )
    # Domain-separated from the session signing key, which may be derived from
    # the same secret: the two must never produce the same bytes.
    material = hashlib.sha256(b"paracheck-key-encryption-v1" + configured.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def available() -> bool:
    try:
        _fernet()
    except EncryptionUnavailable:
        return False
    return True


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    """None rather than an exception when a stored key can't be read: rotating
    the encryption secret should degrade reviews to the plain renderer, not
    crash every job."""
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def hint(value: str) -> str:
    """What the dashboard shows instead of the key. Enough to recognise which
    key is installed, not enough to be worth stealing."""
    tail = value[-4:] if len(value) >= 4 else ""
    return f"...{tail}"
