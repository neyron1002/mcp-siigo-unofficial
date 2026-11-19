"""Encrypted local vault: SQLite (WAL mode) with AES-256-GCM fields (plan D6, D7).

Tables:

- ``meta``: schema version and a key-check blob that proves the master key matches.
- ``secrets``: encrypted values (Siigo credentials, the MCP bearer key, ...).
- ``settings``: plain JSON values that are not secret (language, start at login, ...).
- ``events``: an append-only log (for example, acceptance of the write-actions warning).

The connection is shared between the Qt thread and the server thread, so every
operation holds a lock.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from mcp_siigo_unofficial.siigo.credentials import DEFAULT_PARTNER_ID, SiigoCredentials
from mcp_siigo_unofficial.vault import crypto
from mcp_siigo_unofficial.vault.keystore import KeyStore

SCHEMA_VERSION = 1
_KEY_CHECK_FIELD = "__key_check__"
_KEY_CHECK_PLAINTEXT = b"mcp-siigo-unofficial vault key check"

FIELD_SIIGO_USERNAME = "siigo.username"
FIELD_SIIGO_ACCESS_KEY = "siigo.access_key"
FIELD_SIIGO_PARTNER_ID = "siigo.partner_id"
#: The Siigo token shared by the app's processes (Q2e; see vault/token_store.py).
FIELD_SIIGO_SHARED_TOKEN = "siigo.shared_token"  # noqa: S105 - vault field name

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    name TEXT PRIMARY KEY,
    value BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS secrets (
    name TEXT PRIMARY KEY,
    value BLOB NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""


class VaultError(Exception):
    """Base class for vault errors."""


class VaultKeyMissingError(VaultError):
    """The vault holds data, but its master key is not in the keychain."""


class VaultKeyMismatchError(VaultError):
    """The master key in the keychain does not open this vault."""


@dataclass(frozen=True)
class VaultEvent:
    """One entry of the vault event log."""

    id: int
    at: str
    kind: str
    detail: dict[str, Any]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _restrict_permissions(path: Path) -> None:
    """Make the file readable only by its owner (no effect on Windows ACLs)."""
    if os.name == "posix" and path.exists():
        path.chmod(0o600)


class Vault:
    """Encrypted key-value store. Create it with :meth:`open`."""

    def __init__(self, path: Path, conn: sqlite3.Connection, key: bytes) -> None:
        self.path = path
        self._conn = conn
        self._key = key
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ lifecycle
    @classmethod
    def open(cls, path: Path, keystore: KeyStore) -> Self:
        """Open (or create) the vault at ``path`` with the master key from ``keystore``.

        A new key is created only when the vault holds no secrets yet. If the vault
        holds data and the key is missing or wrong, an error is raised instead of
        silently replacing the key; :meth:`reset` is the explicit way out.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(_SCHEMA)
            _restrict_permissions(path)
            key = cls._resolve_key(conn, keystore)
        except BaseException:
            conn.close()
            raise
        return cls(path, conn, key)

    @staticmethod
    def _resolve_key(conn: sqlite3.Connection, keystore: KeyStore) -> bytes:
        row = conn.execute("SELECT value FROM meta WHERE name = ?", ("key_check",)).fetchone()
        key = keystore.load()
        if row is None:
            (secret_count,) = conn.execute("SELECT COUNT(*) FROM secrets").fetchone()
            if secret_count:
                raise VaultKeyMissingError("The vault has secrets but no key check record.")
            if key is None:
                key = crypto.generate_key()
                keystore.save(key)
            check = crypto.encrypt(key, _KEY_CHECK_FIELD, _KEY_CHECK_PLAINTEXT)
            conn.executemany(
                "INSERT OR REPLACE INTO meta (name, value) VALUES (?, ?)",
                [("key_check", check), ("schema_version", str(SCHEMA_VERSION).encode())],
            )
            return key
        if key is None:
            raise VaultKeyMissingError(
                "The vault master key is missing from the keychain. "
                "Reset the vault and enter the Siigo credentials again."
            )
        try:
            plaintext = crypto.decrypt(key, _KEY_CHECK_FIELD, bytes(row[0]))
        except crypto.VaultCryptoError as exc:
            raise VaultKeyMismatchError("The keychain key does not open this vault.") from exc
        if plaintext != _KEY_CHECK_PLAINTEXT:
            raise VaultKeyMismatchError("The keychain key does not open this vault.")
        return key

    @classmethod
    def reset(cls, path: Path, keystore: KeyStore) -> Self:
        """Delete the vault files and its key, then create an empty vault."""
        for suffix in ("", "-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
        keystore.delete()
        return cls.open(path, keystore)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"Vault(path={str(self.path)!r})"

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    # ------------------------------------------------------------------ secrets
    def set_secret(self, name: str, value: str) -> None:
        blob = crypto.encrypt(self._key, name, value.encode("utf-8"))
        with self._transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO secrets (name, value, updated_at) VALUES (?, ?, ?)",
                (name, blob, _now()),
            )

    def get_secret(self, name: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM secrets WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return crypto.decrypt(self._key, name, bytes(row[0])).decode("utf-8")

    def delete_secret(self, name: str) -> None:
        with self._transaction() as conn:
            conn.execute("DELETE FROM secrets WHERE name = ?", (name,))

    def secret_names(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT name FROM secrets ORDER BY name").fetchall()
        return [str(r[0]) for r in rows]

    # ------------------------------------------------------------------ settings
    def set_setting(self, name: str, value: Any) -> None:
        """Store a JSON-serializable, non-secret value."""
        encoded = json.dumps(value)
        with self._transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (name, value, updated_at) VALUES (?, ?, ?)",
                (name, encoded, _now()),
            )

    def get_setting(self, name: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE name = ?", (name,)
            ).fetchone()
        return default if row is None else json.loads(row[0])

    # ------------------------------------------------------------------ events
    def add_event(self, kind: str, detail: dict[str, Any]) -> VaultEvent:
        """Append an event (never put secrets in ``detail``)."""
        at = _now()
        encoded = json.dumps(detail, sort_keys=True)
        with self._transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO events (at, kind, detail) VALUES (?, ?, ?)", (at, kind, encoded)
            )
            event_id = cursor.lastrowid
        if event_id is None:
            raise VaultError("The event was not stored.")
        return VaultEvent(event_id, at, kind, detail)

    def events(self, kind: str | None = None) -> list[VaultEvent]:
        query = "SELECT id, at, kind, detail FROM events"
        params: tuple[str, ...] = ()
        if kind is not None:
            query += " WHERE kind = ?"
            params = (kind,)
        with self._lock:
            rows = self._conn.execute(query + " ORDER BY id", params).fetchall()
        return [VaultEvent(int(r[0]), str(r[1]), str(r[2]), json.loads(r[3])) for r in rows]

    # ------------------------------------------------------------------ Siigo credentials
    def save_siigo_credentials(self, credentials: SiigoCredentials) -> None:
        with self._lock:
            self.delete_secret(FIELD_SIIGO_SHARED_TOKEN)
            self.set_secret(FIELD_SIIGO_USERNAME, credentials.username)
            self.set_secret(FIELD_SIIGO_ACCESS_KEY, credentials.access_key)
            self.set_secret(FIELD_SIIGO_PARTNER_ID, credentials.partner_id)

    def load_siigo_credentials(self) -> SiigoCredentials | None:
        with self._lock:
            username = self.get_secret(FIELD_SIIGO_USERNAME)
            access_key = self.get_secret(FIELD_SIIGO_ACCESS_KEY)
            partner_id = self.get_secret(FIELD_SIIGO_PARTNER_ID) or DEFAULT_PARTNER_ID
        if not username or not access_key:
            return None
        return SiigoCredentials(username, access_key, partner_id)

    def clear_siigo_credentials(self) -> None:
        for name in (
            FIELD_SIIGO_USERNAME,
            FIELD_SIIGO_ACCESS_KEY,
            FIELD_SIIGO_PARTNER_ID,
            FIELD_SIIGO_SHARED_TOKEN,
        ):
            self.delete_secret(name)
