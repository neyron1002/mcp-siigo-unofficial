"""The "Connect your AI apps" window (one-click plan v3, phase 8).

One row per AI app: a checkbox, its state, and (under Advanced) the connection type.
Connect adds the Siigo server to the checked apps; Disconnect removes only our
entries. Work runs on a worker thread, so a slow AI app command never freezes the
window. Nothing changes until the user clicks (Q4).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mcp_siigo_unofficial.app.icons import app_icon
from mcp_siigo_unofficial.clients import ActionResult, ClientStatus, Installer
from mcp_siigo_unofficial.clients.installer import ConflictPolicy
from mcp_siigo_unofficial.clients.specs import Transport
from mcp_siigo_unofficial.i18n import Translator

#: States whose checkbox starts ticked.
_TICKED = ("not_connected", "needs_repair", "conflict")
Restarter = Callable[[], bool]


def state_text(tr: Translator, status: ClientStatus) -> str:
    """Short state shown in the window and the tray menu."""
    if status.state == "connected":
        return tr("connect.state.connected", transport=_transport_label(tr, status.transport))
    return tr(f"connect.state.{status.state}")


def _transport_label(tr: Translator, transport: str | None) -> str:
    return tr("connect.transport.http") if transport == "http" else tr("connect.transport.stdio")


@dataclass
class _Row:
    status: ClientStatus
    box: QCheckBox
    state: QLabel
    transport: QComboBox
    button: QPushButton


class _Bridge(QObject):
    finished = Signal(object, object)  # results, follow-up callback


class ConnectWindow(QDialog):
    """Connect, switch, and disconnect the Siigo server in AI apps."""

    def __init__(
        self,
        installer: Installer,
        tr: Translator,
        restart_claude_desktop: Restarter | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.installer = installer
        self._tr = tr
        self._restart = restart_claude_desktop
        self._bridge = _Bridge()
        self._bridge.finished.connect(self._on_finished)
        self._lock = threading.Lock()
        self.busy = False
        self.rows: dict[str, _Row] = {}
        self.last_results: list[ActionResult] = []
        #: Answers for "a server called siigo already exists"; tests replace it.
        self.ask_conflict: Callable[[str], ConflictPolicy | None] = self._ask_conflict

        self.setWindowTitle(tr("connect.title"))
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(560)

        intro = QLabel(tr("connect.intro"))
        intro.setWordWrap(True)
        self.grid = QGridLayout()
        self.grid.setColumnStretch(0, 1)
        self.advanced_box = QCheckBox(tr("connect.advanced"))
        self.advanced_box.toggled.connect(self._show_advanced)
        self.advanced_note = QLabel(tr("connect.advanced.note"))
        self.advanced_note.setWordWrap(True)
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.restart_button = QPushButton(tr("connect.restart_desktop"))
        self.restart_button.clicked.connect(self.restart_desktop)
        self.restart_button.setVisible(False)
        self.disconnect_button = QPushButton(tr("connect.disconnect_all"))
        self.disconnect_button.clicked.connect(self.disconnect_all)
        self.close_button = QPushButton(tr("connect.not_now"))
        self.close_button.clicked.connect(self.reject)
        self.connect_button = QPushButton(tr("connect.connect"))
        self.connect_button.setDefault(True)
        self.connect_button.clicked.connect(self.connect_selected)

        buttons = QHBoxLayout()
        buttons.addWidget(self.restart_button)
        buttons.addWidget(self.disconnect_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.connect_button)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(self.grid)
        layout.addWidget(self.advanced_box)
        layout.addWidget(self.advanced_note)
        layout.addWidget(self.result_label)
        layout.addLayout(buttons)
        self.reload()
        self._show_advanced(False)

    # ------------------------------------------------------------------ rows
    def reload(self) -> None:
        """Read every app's state again and rebuild the rows."""
        for row in self.rows.values():
            for widget in (row.box, row.state, row.transport, row.button):
                self.grid.removeWidget(widget)
                widget.deleteLater()
        self.rows.clear()
        with self._lock:
            statuses = self.installer.status()
        tr = self._tr
        for index, status in enumerate(statuses):
            box = QCheckBox(status.label)
            usable = status.installed and status.state != "unreadable"
            box.setEnabled(usable)
            box.setChecked(usable and status.state in _TICKED)
            state = QLabel(state_text(tr, status))
            if status.detail and status.state in ("unreadable", "conflict"):
                state.setToolTip(status.detail)
            transport = QComboBox()
            transport.addItem(tr("connect.transport.stdio"), "stdio")
            if status.supports_http:
                transport.addItem(tr("connect.transport.http"), "http")
            transport.setCurrentIndex(1 if status.transport == "http" else 0)
            transport.setEnabled(usable and status.supports_http)
            button = QPushButton()
            self._setup_row_button(button, status)
            cells: tuple[QWidget, ...] = (box, state, transport, button)
            for column, cell in enumerate(cells):
                self.grid.addWidget(cell, index, column)
            self.rows[status.id] = _Row(status, box, state, transport, button)
        self._show_advanced(self.advanced_box.isChecked())
        any_connected = any(
            r.status.state in ("connected", "needs_repair") for r in self.rows.values()
        )
        self.disconnect_button.setEnabled(any_connected and not self.busy)
        self.connect_button.setEnabled(
            any(r.box.isEnabled() for r in self.rows.values()) and not self.busy
        )

    def _setup_row_button(self, button: QPushButton, status: ClientStatus) -> None:
        tr = self._tr
        if status.state == "connected" and status.transport == "http":
            button.setText(tr("connect.switch_stdio"))
            button.clicked.connect(lambda _=False, i=status.id: self.switch_to_stdio(i))
            button.setVisible(True)
        elif status.state in ("connected", "needs_repair"):
            button.setText(tr("connect.disconnect"))
            button.clicked.connect(lambda _=False, i=status.id: self.disconnect_apps([i]))
            button.setVisible(True)
        else:
            button.setVisible(False)

    def _show_advanced(self, shown: bool) -> None:
        self.advanced_note.setVisible(shown)
        for row in self.rows.values():
            row.transport.setVisible(shown)

    def selected(self) -> list[tuple[str, Transport]]:
        chosen: list[tuple[str, Transport]] = []
        for app_id, row in self.rows.items():
            if row.box.isEnabled() and row.box.isChecked():
                value = row.transport.currentData()
                chosen.append((app_id, "http" if value == "http" else "stdio"))
        return chosen

    # ------------------------------------------------------------------ work
    def _run(
        self,
        job: Callable[[], list[ActionResult]],
        then: Callable[[list[ActionResult]], None] | None = None,
    ) -> None:
        self.busy = True
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self.result_label.setText(self._tr("connect.working"))

        def work() -> None:
            try:
                with self._lock:
                    results = job()
            except Exception as exc:  # never leave the window busy
                results = [ActionResult("-", "-", "failed", detail=f"{type(exc).__name__}: {exc}")]
            self._bridge.finished.emit(results, then)

        threading.Thread(target=work, name="connect-ai-apps", daemon=True).start()

    def _on_finished(self, results: object, then: object) -> None:
        self.busy = False
        items = (
            [r for r in results if isinstance(r, ActionResult)] if isinstance(results, list) else []
        )
        self.last_results = items
        if callable(then):
            then(items)
            return
        self._show_results(items)

    def connect_selected(self) -> None:
        chosen = self.selected()
        if not chosen or self.busy:
            return

        def job() -> list[ActionResult]:
            results: list[ActionResult] = []
            for app_id, transport in chosen:
                results += self.installer.connect([app_id], transport=transport)
            return results

        self._run(job, self._after_connect(dict(chosen)))

    def _after_connect(
        self, transports: dict[str, Transport]
    ) -> Callable[[list[ActionResult]], None]:
        def then(results: list[ActionResult]) -> None:
            retry: list[tuple[str, Transport, ConflictPolicy]] = []
            for result in results:
                if result.outcome == "conflict" and result.name != "siigo-unofficial":
                    policy = self.ask_conflict(result.label)
                    if policy is not None:
                        retry.append((result.id, transports.get(result.id, "stdio"), policy))
            if not retry:
                self._show_results(results)
                return
            kept = [r for r in results if r.id not in {item[0] for item in retry}]

            def job() -> list[ActionResult]:
                again: list[ActionResult] = []
                for app_id, transport, policy in retry:
                    again += self.installer.connect(
                        [app_id], transport=transport, on_conflict=policy
                    )
                return kept + again

            self._run(job)

        return then

    def switch_to_stdio(self, app_id: str) -> None:
        if not self.busy:
            self._run(lambda: self.installer.connect([app_id], transport="stdio"))

    def disconnect_apps(self, ids: Sequence[str]) -> None:
        if not self.busy:
            chosen = list(ids)
            self._run(lambda: self.installer.disconnect(chosen))

    def disconnect_all(self) -> None:
        ids = [i for i, r in self.rows.items() if r.status.state in ("connected", "needs_repair")]
        if ids:
            self.disconnect_apps(ids)

    def restart_desktop(self) -> None:
        if self._restart is None:
            return
        restart = self._restart
        self.restart_button.setEnabled(False)
        self.result_label.setText(self._tr("connect.restarting"))

        def job() -> list[ActionResult]:
            ok = restart()
            if ok:
                return [ActionResult("claude-desktop", "Claude Desktop", "connected")]
            return [ActionResult("claude-desktop", "Claude Desktop", "failed")]

        self._run(job, self._after_restart)

    def _after_restart(self, results: list[ActionResult]) -> None:
        self.restart_button.setEnabled(True)
        ok = bool(results) and results[0].ok
        self.result_label.setText(
            self._tr("connect.restarted") if ok else self._tr("connect.restart_failed")
        )
        self.reload()

    # ------------------------------------------------------------------ results
    def _show_results(self, results: list[ActionResult]) -> None:
        tr = self._tr
        lines = [self.result_line(r) for r in results]
        lines = [line for line in lines if line]
        needs_restart = any(
            r.id == "claude-desktop" and r.outcome in ("connected", "disconnected") for r in results
        )
        if needs_restart:
            lines.append(tr("connect.restart_hint"))
        if any(r.outcome in ("connected", "already_connected") for r in results):
            lines.append(tr("connect.new_session_hint"))
        self.result_label.setText("\n".join(lines) or tr("connect.nothing"))
        self.restart_button.setVisible(needs_restart and self._restart is not None)
        self.close_button.setText(tr("connect.close"))
        self.reload()

    def result_line(self, result: ActionResult) -> str:
        tr = self._tr
        if result.outcome in ("not_installed", "not_connected"):
            return ""
        key = f"connect.result.{result.outcome}"
        line = tr(key, app=result.label, name=result.name or "siigo")
        if result.outcome == "failed" and result.detail:
            line += f" {result.detail}"
        return line

    def _ask_conflict(self, label: str) -> ConflictPolicy | None:
        tr = self._tr
        box = QMessageBox(
            QMessageBox.Icon.Question, tr("connect.title"), tr("connect.conflict", app=label)
        )
        replace = box.addButton(
            tr("connect.conflict.replace"), QMessageBox.ButtonRole.DestructiveRole
        )
        keep = box.addButton(tr("connect.conflict.keep_both"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("connect.conflict.skip"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is replace:
            return "replace"
        if clicked is keep:
            return "keep-both"
        return None
