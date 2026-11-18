"""Encrypted vault: SQLite (WAL) + AES-256-GCM + key store."""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

import pytest

from mcp_siigo_unofficial.siigo import SiigoCredentials
from mcp_siigo_unofficial.vault import (
    MemoryKeyStore,
    Vault,
    VaultKeyMismatchError,
    VaultKeyMissingError,
)
from mcp_siigo_unofficial.vault.crypto import generate_key


def test_secret_round_trip_survives_reopen(tmp_path: Path) -> None:
    keystore = MemoryKeyStore()
    path = tmp_path / "nested" / "vault.sqlite3"
    with Vault.open(path, keystore) as vault:
        vault.set_secret("token", "value-1")
        vault.set_secret("token", "value-2")
    with Vault.open(path, keystore) as vault:
        assert vault.get_secret("token") == "value-2"
        assert vault.get_secret("missing") is None
        assert vault.secret_names() == ["token"]
        vault.delete_secret("token")
        assert vault.get_secret("token") is None


def test_secrets_are_not_stored_in_plain_text(tmp_path: Path) -> None:
    path = tmp_path / "vault.sqlite3"
    with Vault.open(path, MemoryKeyStore()) as vault:
        vault.set_secret("siigo.access_key", "PLAINTEXT-MARKER-123")
    raw = b"".join(
        Path(f"{path}{suffix}").read_bytes()
        for suffix in ("", "-wal")
        if Path(f"{path}{suffix}").exists()
    )
    assert b"PLAINTEXT-MARKER-123" not in raw


def test_wal_mode_and_permissions(tmp_path: Path) -> None:
    path = tmp_path / "vault.sqlite3"
    with Vault.open(path, MemoryKeyStore()):
        mode = sqlite3.connect(path).execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_wrong_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "vault.sqlite3"
    Vault.open(path, MemoryKeyStore()).close()
    with pytest.raises(VaultKeyMismatchError):
        Vault.open(path, MemoryKeyStore(generate_key()))


def test_missing_key_is_not_silently_replaced(tmp_path: Path) -> None:
    path = tmp_path / "vault.sqlite3"
    with Vault.open(path, MemoryKeyStore()) as vault:
        vault.set_secret("a", "b")
    empty = MemoryKeyStore()
    with pytest.raises(VaultKeyMissingError):
        Vault.open(path, empty)
    assert empty.load() is None


def test_reset_creates_a_fresh_vault(tmp_path: Path) -> None:
    path = tmp_path / "vault.sqlite3"
    keystore = MemoryKeyStore()
    with Vault.open(path, keystore) as vault:
        vault.set_secret("a", "b")
    old_key = keystore.load()
    keystore.save(generate_key())  # the keychain lost the original key
    with Vault.reset(path, keystore) as vault:
        assert vault.secret_names() == []
    assert keystore.load() not in (None, old_key)


def test_existing_key_in_keystore_is_reused_for_a_new_vault(tmp_path: Path) -> None:
    key = generate_key()
    keystore = MemoryKeyStore(key)
    Vault.open(tmp_path / "vault.sqlite3", keystore).close()
    assert keystore.load() == key


def test_settings_are_json(vault: Vault) -> None:
    assert vault.get_setting("language", "en") == "en"
    vault.set_setting("language", "es")
    vault.set_setting("start_at_login", True)
    vault.set_setting("window", {"x": 1, "y": [2, 3]})
    assert vault.get_setting("language") == "es"
    assert vault.get_setting("start_at_login") is True
    assert vault.get_setting("window") == {"x": 1, "y": [2, 3]}


def test_events_are_appended_in_order(vault: Vault) -> None:
    first = vault.add_event("write_actions.accepted", {"version": "0.0.1"})
    vault.add_event("other", {})
    vault.add_event("write_actions.accepted", {"version": "0.0.2"})
    accepted = vault.events("write_actions.accepted")
    assert [e.detail["version"] for e in accepted] == ["0.0.1", "0.0.2"]
    assert accepted[0] == first
    assert len(vault.events()) == 3


def test_siigo_credentials_round_trip(vault: Vault) -> None:
    assert vault.load_siigo_credentials() is None
    creds = SiigoCredentials("user@example.com", "key-123", "MyPartner01")
    vault.save_siigo_credentials(creds)
    assert vault.load_siigo_credentials() == creds
    vault.clear_siigo_credentials()
    assert vault.load_siigo_credentials() is None


def test_concurrent_writes_from_threads(vault: Vault) -> None:
    def worker(n: int) -> None:
        for i in range(20):
            vault.set_secret(f"t{n}-{i}", str(i))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(vault.secret_names()) == 80
    assert vault.get_secret("t3-19") == "19"


def test_repr_has_no_secrets(vault: Vault) -> None:
    vault.set_secret("x", "SECRET-VALUE")
    assert "SECRET-VALUE" not in repr(vault)
