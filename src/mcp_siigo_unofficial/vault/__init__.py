"""Encrypted local vault (SQLite + AES-256-GCM + OS keychain master key)."""

from mcp_siigo_unofficial.vault.crypto import VaultCryptoError
from mcp_siigo_unofficial.vault.keystore import (
    KeyringKeyStore,
    KeyStore,
    KeyStoreError,
    MemoryKeyStore,
)
from mcp_siigo_unofficial.vault.store import (
    Vault,
    VaultError,
    VaultEvent,
    VaultKeyMismatchError,
    VaultKeyMissingError,
)
from mcp_siigo_unofficial.vault.token_store import VaultTokenStore

__all__ = [
    "KeyStore",
    "KeyStoreError",
    "KeyringKeyStore",
    "MemoryKeyStore",
    "Vault",
    "VaultCryptoError",
    "VaultError",
    "VaultEvent",
    "VaultKeyMismatchError",
    "VaultKeyMissingError",
    "VaultTokenStore",
]
