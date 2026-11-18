"""Where the vault master key lives: the operating-system keychain (plan D6)."""

from __future__ import annotations

import base64
import binascii
from typing import Protocol

import keyring
import keyring.errors
from keyring.backends import fail

SERVICE_NAME = "mcp-siigo-unofficial"
ACCOUNT_NAME = "vault-master-key"


class KeyStoreError(Exception):
    """The keychain is not available, or it refused the operation."""


class KeyStore(Protocol):
    """Stores one secret: the vault master key."""

    def load(self) -> bytes | None: ...

    def save(self, key: bytes) -> None: ...

    def delete(self) -> None: ...


class KeyringKeyStore:
    """Master key in the OS keychain: Windows Credential Manager, macOS Keychain,
    or the Secret Service on Linux. The key is stored base64-encoded."""

    def __init__(self, service: str = SERVICE_NAME, account: str = ACCOUNT_NAME) -> None:
        self.service = service
        self.account = account

    def _backend(self) -> keyring.backend.KeyringBackend:
        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring):
            raise KeyStoreError("No operating-system keychain is available to store the vault key.")
        return backend

    def load(self) -> bytes | None:
        try:
            value = self._backend().get_password(self.service, self.account)
        except keyring.errors.KeyringError as exc:
            raise KeyStoreError(f"Could not read the vault key: {type(exc).__name__}") from exc
        if value is None:
            return None
        try:
            return base64.b64decode(value.encode("ascii"), validate=True)
        except (binascii.Error, UnicodeEncodeError) as exc:
            raise KeyStoreError("The stored vault key is damaged.") from exc

    def save(self, key: bytes) -> None:
        encoded = base64.b64encode(key).decode("ascii")
        try:
            self._backend().set_password(self.service, self.account, encoded)
        except keyring.errors.KeyringError as exc:
            raise KeyStoreError(f"Could not save the vault key: {type(exc).__name__}") from exc

    def delete(self) -> None:
        try:
            self._backend().delete_password(self.service, self.account)
        except keyring.errors.PasswordDeleteError:
            return
        except keyring.errors.KeyringError as exc:
            raise KeyStoreError(f"Could not delete the vault key: {type(exc).__name__}") from exc


class MemoryKeyStore:
    """In-memory key store for tests and the self-test. Not persistent."""

    def __init__(self, key: bytes | None = None) -> None:
        self._key = key

    def load(self) -> bytes | None:
        return self._key

    def save(self, key: bytes) -> None:
        self._key = key

    def delete(self) -> None:
        self._key = None
