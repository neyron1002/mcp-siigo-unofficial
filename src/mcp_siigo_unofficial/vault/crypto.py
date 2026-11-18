"""AES-256-GCM field encryption (plan D6).

Blob layout: ``version (1 byte) || nonce (12 bytes) || ciphertext + tag``. The
associated data binds each blob to its field name, so a value cannot be moved to
another field without failing authentication.
"""

from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_SIZE = 32
NONCE_SIZE = 12
FORMAT_VERSION = 1
_AAD_PREFIX = b"mcp-siigo-unofficial/vault/v1/"


class VaultCryptoError(Exception):
    """A blob could not be decrypted: wrong key, wrong field, or tampered data."""


def generate_key() -> bytes:
    """Return a new random 256-bit key."""
    return AESGCM.generate_key(bit_length=KEY_SIZE * 8)


def _aad(field: str) -> bytes:
    return _AAD_PREFIX + field.encode("utf-8")


def _check_key(key: bytes) -> None:
    if len(key) != KEY_SIZE:
        raise ValueError("The vault key must be 32 bytes (AES-256).")


def encrypt(key: bytes, field: str, plaintext: bytes) -> bytes:
    """Encrypt ``plaintext`` for ``field`` with a fresh random nonce."""
    _check_key(key)
    nonce = os.urandom(NONCE_SIZE)
    return bytes([FORMAT_VERSION]) + nonce + AESGCM(key).encrypt(nonce, plaintext, _aad(field))


def decrypt(key: bytes, field: str, blob: bytes) -> bytes:
    """Decrypt a blob made by :func:`encrypt`; raise :class:`VaultCryptoError` on failure."""
    _check_key(key)
    if len(blob) < 1 + NONCE_SIZE + 16 or blob[0] != FORMAT_VERSION:
        raise VaultCryptoError("Unknown or damaged vault data format.")
    nonce, ciphertext = blob[1 : 1 + NONCE_SIZE], blob[1 + NONCE_SIZE :]
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, _aad(field))
    except InvalidTag as exc:
        raise VaultCryptoError("Vault data failed authentication (wrong key or tampered).") from exc
