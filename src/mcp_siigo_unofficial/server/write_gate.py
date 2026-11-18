"""Write safety (plan section 5.1): the "Write actions" switch and one-time confirmations.

- The switch is **off by default** and off again after every restart (P9). Turning
  it on requires an explicit acceptance of responsibility, which is recorded.
- When a client cannot ask the user directly (no MCP elicitation), a write needs a
  one-time ``confirmation_id`` that the server issued for exactly the same tool and
  arguments, and that expires after 5 minutes (P10).
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp_siigo_unofficial import __version__
from mcp_siigo_unofficial.vault import Vault

log = logging.getLogger(__name__)

SETTING_WRITE_ENABLED = "write_actions.enabled"
EVENT_WRITE_ENABLED = "write_actions.enabled"
EVENT_WRITE_DISABLED = "write_actions.disabled"
CONFIRMATION_TTL_S = 300.0

Listener = Callable[[bool], None]


class WriteSwitchError(Exception):
    """The switch cannot be turned on without an acceptance of responsibility."""


class WriteSwitch:
    """The "Write actions" switch. Thread-safe.

    ``follow_vault=True`` is for the ``--stdio`` process: it does not own the switch,
    it reads the state that the tray app stored in the vault.
    """

    def __init__(self, vault: Vault | None = None, *, follow_vault: bool = False) -> None:
        self._vault = vault
        self._follow_vault = follow_vault and vault is not None
        self._lock = threading.Lock()
        self._enabled = False
        self._listeners: list[Listener] = []

    @property
    def enabled(self) -> bool:
        if self._follow_vault and self._vault is not None:
            return self._vault.get_setting(SETTING_WRITE_ENABLED, False) is True
        with self._lock:
            return self._enabled

    def reset_at_start(self) -> None:
        """Turn the switch off (called when the app starts and when it quits)."""
        with self._lock:
            self._enabled = False
        if self._vault is not None and not self._follow_vault:
            self._vault.set_setting(SETTING_WRITE_ENABLED, False)

    def add_listener(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def enable(self, *, accepted_responsibility: bool) -> None:
        """Turn writes on. The user must have accepted the warning dialog."""
        if not accepted_responsibility:
            raise WriteSwitchError("Write actions need an explicit acceptance of responsibility.")
        self._set(True)

    def disable(self) -> None:
        self._set(False)

    def _set(self, value: bool) -> None:
        if self._follow_vault:
            raise WriteSwitchError("Only the tray app can change the Write actions switch.")
        with self._lock:
            changed = self._enabled != value
            self._enabled = value
            listeners = list(self._listeners)
        if self._vault is not None:
            self._vault.set_setting(SETTING_WRITE_ENABLED, value)
            if changed:
                kind = EVENT_WRITE_ENABLED if value else EVENT_WRITE_DISABLED
                detail: dict[str, Any] = {"app_version": __version__}
                if value:
                    detail["accepted_responsibility"] = True
                self._vault.add_event(kind, detail)
        if changed:
            log.warning("Write actions %s", "ENABLED" if value else "disabled")
            self.notify(listeners, value)

    def notify(self, listeners: list[Listener] | None = None, value: bool | None = None) -> None:
        """Call the listeners (also used by the stdio watcher after a vault change)."""
        state = self.enabled if value is None else value
        if listeners is None:
            with self._lock:
                listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(state)
            except Exception:
                log.exception("A write-switch listener failed")


def arguments_digest(tool: str, arguments: dict[str, Any]) -> str:
    """Stable digest of a tool call (the confirmation id is not part of it)."""
    payload = {k: v for k, v in arguments.items() if k != "confirmation_id"}
    text = json.dumps([tool, payload], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _Pending:
    tool: str
    digest: str
    expires_at: float


class ConfirmationStore:
    """One-time confirmation ids for the two-step write flow."""

    def __init__(
        self, ttl: float = CONFIRMATION_TTL_S, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}

    def issue(self, tool: str, arguments: dict[str, Any]) -> str:
        confirmation_id = secrets.token_urlsafe(18)
        with self._lock:
            self._purge()
            self._pending[confirmation_id] = _Pending(
                tool, arguments_digest(tool, arguments), self._clock() + self.ttl
            )
        return confirmation_id

    def redeem(self, confirmation_id: str, tool: str, arguments: dict[str, Any]) -> bool:
        """Consume the id. True only for the same tool and arguments, before expiry."""
        with self._lock:
            pending = self._pending.pop(confirmation_id, None)
            self._purge()
        if pending is None or self._clock() > pending.expires_at:
            return False
        return secrets.compare_digest(
            pending.digest, arguments_digest(tool, arguments)
        ) and secrets.compare_digest(pending.tool, tool)

    def _purge(self) -> None:
        now = self._clock()
        for key in [k for k, p in self._pending.items() if now > p.expires_at]:
            del self._pending[key]

    def __len__(self) -> int:
        with self._lock:
            return len(self._pending)
