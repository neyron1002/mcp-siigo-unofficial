"""Write safety (plan section 5.1): the "Write actions" switch.

The switch is **off by default** and off again after every restart (P9). Turning it
on requires an explicit acceptance of responsibility, which is recorded. Each write
also needs the user's approval (``server/approval.py``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable
from typing import Any

from mcp_siigo_unofficial import __version__
from mcp_siigo_unofficial.vault import Vault

log = logging.getLogger(__name__)

SETTING_WRITE_ENABLED = "write_actions.enabled"
EVENT_WRITE_ENABLED = "write_actions.enabled"
EVENT_WRITE_DISABLED = "write_actions.disabled"

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
        """Turn the switch off (called when the app starts and when it quits; plan P9).

        If writes were on, the change is recorded in the event log and the listeners
        are told, like any other change.
        """
        if self._follow_vault:
            return
        with self._lock:
            was_on = self._enabled
            self._enabled = False
            listeners = list(self._listeners)
        if self._vault is not None:
            stored_on = self._vault.get_setting(SETTING_WRITE_ENABLED, False) is True
            self._vault.set_setting(SETTING_WRITE_ENABLED, False)
            if was_on or stored_on:
                self._vault.add_event(
                    EVENT_WRITE_DISABLED, {"app_version": __version__, "reason": "app_restart"}
                )
        if was_on:
            log.warning("Write actions disabled (app start or quit)")
            self.notify(listeners, False)

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
    """Stable digest of a tool call (used to match an AI app's answer to its question)."""
    text = json.dumps([tool, arguments], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
