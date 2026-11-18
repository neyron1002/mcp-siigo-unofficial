"""Vault round trip with the real operating-system keychain (plan phase 1).

Runs only when ``MCP_SIIGO_TEST_REAL_KEYRING=1`` (set in CI for Windows, macOS, and
the Linux dev container job with a temporary Secret Service). It uses its own
service name, and it removes the key at the end.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import keyring
import keyring.errors
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import fail

from mcp_siigo_unofficial.siigo import SiigoCredentials
from mcp_siigo_unofficial.vault import KeyringKeyStore, KeyStoreError, Vault

real_keyring = pytest.mark.skipif(
    os.environ.get("MCP_SIIGO_TEST_REAL_KEYRING") != "1",
    reason="set MCP_SIIGO_TEST_REAL_KEYRING=1 to use the real OS keychain",
)


@pytest.mark.real_keyring
@real_keyring
def test_vault_round_trip_with_os_keychain(tmp_path: Path) -> None:
    keystore = KeyringKeyStore(service=f"mcp-siigo-unofficial-test-{uuid.uuid4().hex[:12]}")
    path = tmp_path / "vault.sqlite3"
    creds = SiigoCredentials("user@example.com", "fake-access-key", "MCPSiigoUnofficial")
    try:
        with Vault.open(path, keystore) as vault:
            vault.save_siigo_credentials(creds)
        key = keystore.load()
        assert key is not None
        assert len(key) == 32
        with Vault.open(path, keystore) as vault:
            assert vault.load_siigo_credentials() == creds
    finally:
        keystore.delete()
    assert keystore.load() is None


class FakeBackend(KeyringBackend):
    """In-memory keyring backend (exercises KeyringKeyStore without an OS keychain)."""

    priority = 1  # type: ignore[assignment]

    def __init__(self, error: type[Exception] | None = None) -> None:
        super().__init__()
        self.values: dict[tuple[str, str], str] = {}
        self.error = error

    def _maybe_fail(self) -> None:
        if self.error is not None:
            raise self.error("backend failure")

    def get_password(self, service: str, username: str) -> str | None:
        self._maybe_fail()
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._maybe_fail()
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._maybe_fail()
        if self.values.pop((service, username), None) is None:
            raise keyring.errors.PasswordDeleteError("missing")


def test_keyring_keystore_with_fake_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = FakeBackend()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    store = KeyringKeyStore()
    assert store.load() is None
    store.save(b"\x00" * 32)
    assert backend.values[("mcp-siigo-unofficial", "vault-master-key")] == "A" * 43 + "="
    assert store.load() == b"\x00" * 32
    store.delete()
    store.delete()  # deleting twice is fine
    assert store.load() is None


def test_damaged_key_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = FakeBackend()
    backend.values[("mcp-siigo-unofficial", "vault-master-key")] = "not base64!"
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    with pytest.raises(KeyStoreError, match="damaged"):
        KeyringKeyStore().load()


@pytest.mark.parametrize("operation", ["load", "save", "delete"])
def test_backend_errors_become_keystore_errors(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    backend = FakeBackend(error=keyring.errors.KeyringError)
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    store = KeyringKeyStore()
    calls = {"load": store.load, "save": lambda: store.save(b"k" * 32), "delete": store.delete}
    with pytest.raises(KeyStoreError, match="vault key"):
        calls[operation]()


def test_unavailable_keychain_raises_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())
    with pytest.raises(KeyStoreError, match="keychain"):
        KeyringKeyStore().load()
