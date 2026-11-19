"""The tray icon and its menu (plan section 4 and 5.1)."""

from __future__ import annotations

import math
import os
import threading
import time

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from mcp_siigo_unofficial import __version__
from mcp_siigo_unofficial.app.approval_window import ApprovalWindow
from mcp_siigo_unofficial.app.connect_window import ConnectWindow, state_text
from mcp_siigo_unofficial.app.dialogs import (
    AboutDialog,
    AutomaticApprovalDialog,
    SettingsDialog,
    WriteActionsDialog,
)
from mcp_siigo_unofficial.app.icons import app_icon
from mcp_siigo_unofficial.app.runtime import AppRuntime
from mcp_siigo_unofficial.autostart import Autostart, launch_command
from mcp_siigo_unofficial.clients import ActionResult, ClientStatus, Installer
from mcp_siigo_unofficial.clients.restart import restart_claude_desktop
from mcp_siigo_unofficial.i18n import RELEASES_URL, Translator
from mcp_siigo_unofficial.server.approval import (
    ApprovalMode,
    ApprovalRequest,
    AutomaticSpan,
    Decision,
)

NOTIFICATION_OPENS_WINDOW_S = 15.0  # W3
#: One-click plan v3: the Connect window was shown once (Q12), and the AI apps seen so far (Q4).
SETTING_CONNECT_OFFERED = "clients.connect_offered"
SETTING_KNOWN_APPS = "clients.known_apps"
CLIENT_CHECK_FIRST_MS = 30_000
CLIENT_CHECK_EVERY_MS = 4 * 60 * 60 * 1000


def _minutes_left(seconds: float) -> int:
    """Whole minutes, rounded up: 600 s is "10 min", 599 s is "10 min", 1 s is "1 min"."""
    return max(1, math.ceil(seconds / 60))


class _Bridge(QObject):
    """Moves callbacks from other threads onto the Qt main thread."""

    write_changed = Signal(bool)
    show_requested = Signal()
    update_checked = Signal(object, object, bool)  # release or None, error or None, interactive
    update_downloaded = Signal(object, object)  # path or None, error or None
    approval_requested = Signal(object)  # ApprovalRequest
    approval_closed = Signal(str)  # request id (timed out)
    grants_changed = Signal()
    clients_checked = Signal(object, object)  # statuses, repair results
    clients_disconnected = Signal(object)  # results


class TrayController(QObject):
    """Owns the tray icon, its menu, and the dialogs."""

    def __init__(
        self,
        runtime: AppRuntime,
        tr: Translator,
        autostart: Autostart,
        app: QApplication,
        installer: Installer | None = None,
    ) -> None:
        super().__init__()
        self._installer = installer
        self.connect_window: ConnectWindow | None = None
        self._last_notice = ""
        self._client_lock = threading.Lock()
        self.runtime = runtime
        self.tr_ = tr
        self.autostart = autostart
        self.app = app
        self._icon_normal = app_icon(write_mode=False)
        self._icon_write = app_icon(write_mode=True)
        self._icon_auto = app_icon(write_mode=True, automatic=True)
        self._auto_was_on = False
        self._bridge = _Bridge()
        self._bridge.write_changed.connect(self._on_write_changed)
        self._bridge.show_requested.connect(self.show_settings)
        self._bridge.update_checked.connect(self._on_update_checked)
        self._bridge.update_downloaded.connect(self._on_update_downloaded)
        self._update_busy = False
        runtime.write_switch.add_listener(self._bridge.write_changed.emit)
        runtime.on_show_requested = self._bridge.show_requested.emit
        self._bridge.approval_requested.connect(self.show_approval)
        self._bridge.approval_closed.connect(self._close_approval)
        self._bridge.grants_changed.connect(self.refresh)
        runtime.approvals.on_ask = self._bridge.approval_requested.emit
        runtime.approvals.on_close = self._bridge.approval_closed.emit
        runtime.approvals.on_grants_changed = self._bridge.grants_changed.emit
        self.approval_windows: dict[str, ApprovalWindow] = {}
        self.waiting_approvals: dict[str, tuple[ApprovalRequest, float]] = {}
        self._grant_timer = QTimer(self)
        self._grant_timer.setInterval(15_000)
        self._grant_timer.timeout.connect(self.refresh)
        self._bridge.clients_checked.connect(self._on_clients_checked)
        self._bridge.clients_disconnected.connect(self._on_clients_disconnected)
        self._client_timer = QTimer(self)
        self._client_timer.setInterval(CLIENT_CHECK_EVERY_MS)
        self._client_timer.timeout.connect(self.check_clients)

        self.tray = QSystemTrayIcon(self._icon_normal)
        self.menu = QMenu()
        self.status_action = QAction()
        self.status_action.setEnabled(False)
        self.write_action = QAction()
        self.write_action.setCheckable(True)
        self.write_action.triggered.connect(self.toggle_write_actions)
        self.grants_action = QAction()
        self.grants_action.setEnabled(False)
        self.stop_grants_action = QAction()
        self.stop_grants_action.triggered.connect(self.stop_grants)
        self.auto_menu = QMenu()
        self.auto_hour_action = self.auto_menu.addAction("")
        self.auto_hour_action.triggered.connect(lambda: self.start_automatic(AutomaticSpan.HOUR))
        self.auto_today_action = self.auto_menu.addAction("")
        self.auto_today_action.triggered.connect(lambda: self.start_automatic(AutomaticSpan.TODAY))
        self.auto_status_action = QAction()
        self.auto_status_action.setEnabled(False)
        self.stop_auto_action = QAction()
        self.stop_auto_action.triggered.connect(self.stop_automatic)
        self.copy_menu = QMenu()
        self.clients_menu = QMenu()
        self.clients_menu.aboutToShow.connect(self._fill_clients_menu)
        self.settings_action = QAction()
        self.settings_action.triggered.connect(self.show_settings)
        self.autostart_action = QAction()
        self.autostart_action.setCheckable(True)
        self.autostart_action.triggered.connect(self.toggle_autostart)
        self.updates_action = QAction()
        self.updates_action.triggered.connect(lambda: self.check_for_updates(interactive=True))
        self.about_action = QAction()
        self.about_action.triggered.connect(self.show_about)
        self.quit_action = QAction()
        self.quit_action.triggered.connect(self.app.quit)

        self.menu.addAction(self.status_action)
        self.menu.addSeparator()
        self.menu.addAction(self.write_action)
        self.menu.addAction(self.grants_action)
        self.menu.addAction(self.stop_grants_action)
        self.menu.addMenu(self.auto_menu)
        self.menu.addAction(self.auto_status_action)
        self.menu.addAction(self.stop_auto_action)
        self.menu.addMenu(self.clients_menu)
        self.menu.addMenu(self.copy_menu)
        self.menu.addAction(self.settings_action)
        self.menu.addAction(self.autostart_action)
        self.menu.addAction(self.updates_action)
        self.menu.addAction(self.about_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.menu.aboutToShow.connect(self.refresh)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.messageClicked.connect(self._on_message_clicked)
        self.settings_dialog: SettingsDialog | None = None
        self.about_dialog: AboutDialog | None = None
        self.retranslate()

    # ------------------------------------------------------------------ state
    def retranslate(self) -> None:
        tr = self.tr_
        self.copy_menu.setTitle(tr("tray.copy_setup"))
        self.clients_menu.setTitle(tr("tray.clients"))
        self.settings_action.setText(tr("tray.settings"))
        self.autostart_action.setText(tr("tray.autostart"))
        self.updates_action.setText(tr("tray.updates"))
        self.about_action.setText(tr("tray.about"))
        self.quit_action.setText(tr("tray.quit"))
        self.stop_grants_action.setText(tr("tray.grants.stop"))
        self.auto_menu.setTitle(tr("tray.auto"))
        self.auto_hour_action.setText(tr("tray.auto.hour"))
        self.auto_today_action.setText(tr("tray.auto.today"))
        self.stop_auto_action.setText(tr("tray.auto.stop"))
        self.copy_menu.clear()
        for setup in self.runtime.client_setups():
            action = self.copy_menu.addAction(setup.label)
            action.triggered.connect(lambda _=False, s=setup: self.copy_setup(s.label, s.text))
        self.refresh()

    def status_text(self) -> str:
        tr = self.tr_
        if not self.runtime.server_running:
            return tr("tray.status.stopped", error=self.runtime.server_error or "-")
        if self.runtime.credentials() is None:
            return tr("tray.status.no_credentials")
        return tr("tray.status.running", url=self.runtime.url)

    def refresh(self) -> None:
        tr = self.tr_
        enabled = self.runtime.write_switch.enabled
        self.status_action.setText(self.status_text())
        self.write_action.setChecked(enabled)
        self.write_action.setText(tr("tray.write.on") if enabled else tr("tray.write.off"))
        self.copy_menu.setEnabled(self.runtime.server_running)
        self.autostart_action.setChecked(self.autostart.is_enabled())
        approvals = self.runtime.approvals
        grants = approvals.grants()
        auto = approvals.automatic()
        if grants:
            first = grants[0]
            minutes = _minutes_left(approvals.seconds_left_until(first.expires_at))
            self.grants_action.setText(tr("tray.grants", title=first.title, minutes=minutes))
        if auto is not None:
            minutes = _minutes_left(approvals.seconds_left_until(auto.expires_at))
            self.auto_status_action.setText(
                tr("tray.auto.active", minutes=minutes, writes=auto.writes_left)
            )
        if grants or auto is not None:
            if not self._grant_timer.isActive():
                self._grant_timer.start()
        elif self._grant_timer.isActive():
            self._grant_timer.stop()
        if self._auto_was_on and auto is None:
            self.notify(tr("notify.auto.off.title"), tr("notify.auto.off.body"))
        self._auto_was_on = auto is not None
        self.grants_action.setVisible(bool(grants))
        self.stop_grants_action.setVisible(bool(grants))
        self.auto_menu.menuAction().setVisible(enabled and auto is None)
        self.auto_status_action.setVisible(auto is not None)
        self.stop_auto_action.setVisible(auto is not None)
        if auto is not None:
            self.tray.setIcon(self._icon_auto)
            self.tray.setToolTip(tr("tray.tooltip.auto"))
        else:
            self.tray.setIcon(self._icon_write if enabled else self._icon_normal)
            self.tray.setToolTip(tr("tray.tooltip.write") if enabled else tr("tray.tooltip"))
        self.app.setWindowIcon(self.tray.icon())

    def show(self) -> None:
        self.tray.show()

    # ------------------------------------------------------------------ actions
    def toggle_write_actions(self) -> None:
        switch = self.runtime.write_switch
        if switch.enabled:
            switch.disable()
        else:
            dialog = WriteActionsDialog(self.tr_)
            dialog.exec()
            if dialog.accepted_responsibility:
                switch.enable(accepted_responsibility=True)
        self.refresh()

    def _on_write_changed(self, enabled: bool) -> None:
        tr = self.tr_
        if not enabled:  # writes off: open approval windows become rejections
            for request_id, window in list(self.approval_windows.items()):
                self.runtime.approvals.answer(request_id, Decision.REJECT)
                window.close_without_answer()
            self.approval_windows.clear()
            for request_id in list(self.waiting_approvals):
                self.runtime.approvals.answer(request_id, Decision.REJECT)
            self.waiting_approvals.clear()
        self.refresh()
        if enabled:
            self.notify(tr("notify.write.on.title"), tr("notify.write.on.body"), warning=True)
        else:
            self.notify(tr("notify.write.off.title"), tr("notify.write.off.body"))

    # ------------------------------------------------------------------ approvals
    def show_approval(self, request: object) -> None:
        """A write needs approval (main thread): the window, or a notification first."""
        if not isinstance(request, ApprovalRequest):
            return
        self.notify(
            self.tr_("notify.approval.title"),
            self.tr_("notify.approval.body", client=request.client, title=request.title),
            warning=True,
        )
        notification_first = (
            self.runtime.approval_mode() is ApprovalMode.NOTIFICATION
            and QSystemTrayIcon.isSystemTrayAvailable()
            and self.tray.isVisible()
        )
        if not notification_first:
            self._open_approval(request, request.timeout_s)
            return
        self.waiting_approvals[request.id] = (request, time.monotonic())
        QTimer.singleShot(
            int(NOTIFICATION_OPENS_WINDOW_S * 1000),
            lambda rid=request.id: self._open_waiting_approval(rid),
        )

    def _open_waiting_approval(self, request_id: str) -> None:
        waiting = self.waiting_approvals.pop(request_id, None)
        if waiting is not None:
            request, received = waiting
            self._open_approval(request, request.timeout_s - (time.monotonic() - received))

    def _on_message_clicked(self) -> None:
        """A click on our notification: waiting approvals first, else the Connect window."""
        if self.waiting_approvals:
            self._open_waiting_approvals()
        elif self._last_notice == "clients":
            self.show_connect()

    def _open_waiting_approvals(self) -> None:
        """The user clicked the notification: open every waiting approval now."""
        for request_id in list(self.waiting_approvals):
            self._open_waiting_approval(request_id)

    def _open_approval(self, request: ApprovalRequest, seconds_left: float) -> None:
        window = ApprovalWindow(
            request, self.tr_, self._approval_answered, seconds_left=seconds_left
        )
        window.finished.connect(lambda _=0, rid=request.id: self.approval_windows.pop(rid, None))
        self.approval_windows[request.id] = window
        window.bring_to_front()

    def _approval_answered(self, request_id: str, decision: Decision) -> None:
        window = self.approval_windows.pop(request_id, None)
        self.runtime.approvals.answer(request_id, decision)
        if decision is Decision.APPROVE_SIMILAR and window is not None:
            title = window.request.title
            self.notify(self.tr_("notify.grant.title"), self.tr_("notify.grant.body", title=title))

    def _close_approval(self, request_id: str) -> None:
        self.waiting_approvals.pop(request_id, None)
        window = self.approval_windows.pop(request_id, None)
        if window is not None:
            window.close_without_answer()

    def stop_grants(self) -> None:
        self.runtime.approvals.stop_grants()
        self.refresh()

    def start_automatic(self, span: AutomaticSpan) -> None:
        """W5: only after the warning dialog where the user types APPROVE ALL."""
        if not self.runtime.write_switch.enabled:
            return
        dialog = AutomaticApprovalDialog(self.tr_, span)
        if dialog.exec() != AutomaticApprovalDialog.DialogCode.Accepted:
            return
        try:
            self.runtime.approvals.start_automatic(span, confirm_text=dialog.typed)
        except ValueError:
            return
        self.refresh()
        tr = self.tr_
        self.notify(
            tr("notify.auto.on.title"),
            tr("notify.auto.on.body", span=tr(f"auto.span.{span.value}")),
            warning=True,
        )

    def stop_automatic(self) -> None:
        self.runtime.approvals.stop_automatic("stopped")
        self.refresh()

    def toggle_autostart(self) -> None:
        if self.autostart.is_enabled():
            self.autostart.disable()
        else:
            self.autostart.enable(launch_command())
        self.refresh()

    def copy_setup(self, label: str, text: str) -> None:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text)
        self.notify(self.tr_("notify.copied.title"), self.tr_("notify.copied.body", client=label))

    def notify(self, title: str, message: str, *, warning: bool = False, kind: str = "") -> None:
        self._last_notice = kind
        if QSystemTrayIcon.isSystemTrayAvailable() and self.tray.isVisible():
            icon = (
                QSystemTrayIcon.MessageIcon.Warning
                if warning
                else QSystemTrayIcon.MessageIcon.Information
            )
            self.tray.showMessage(title, message, icon, 8000)

    def show_settings(self) -> None:
        if self.settings_dialog is not None and self.settings_dialog.isVisible():
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
        self.settings_dialog = SettingsDialog(self.runtime, self.tr_)
        self.settings_dialog.language_changed.connect(self.retranslate)
        self.settings_dialog.finished.connect(lambda _: self.refresh())
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def show_about(self) -> None:
        self.about_dialog = AboutDialog(self.tr_)
        self.about_dialog.show()
        self.about_dialog.raise_()

    # ------------------------------------------------------------------ AI apps
    @property
    def installer(self) -> Installer:
        """Built on first use: finding the AI apps may ask the login shell (macOS)."""
        if self._installer is None:
            self._installer = self.runtime.client_installer()
        return self._installer

    def show_connect(self) -> None:
        if self.connect_window is not None and self.connect_window.isVisible():
            self.connect_window.raise_()
            self.connect_window.activateWindow()
            return
        installer = self.installer
        self.connect_window = ConnectWindow(
            installer, self.tr_, lambda: restart_claude_desktop(installer.env)
        )
        self.connect_window.finished.connect(lambda _=0: self._remember_known_apps())
        self.connect_window.show()
        self.connect_window.raise_()
        self.connect_window.activateWindow()

    def offer_connect_once(self) -> bool:
        """Q12: show the Connect window once, on the first start or after an update from
        0.1.x, when an AI app is installed. True if it was shown."""
        vault = self.runtime.vault
        if vault.get_setting(SETTING_CONNECT_OFFERED):
            return False
        with self._client_lock:
            statuses = self.installer.status()
        if not any(s.installed for s in statuses):
            return False
        vault.set_setting(SETTING_CONNECT_OFFERED, True)
        self.show_connect()
        return True

    def start_client_checks(self) -> None:
        """Repair our entries and look for new AI apps soon after start, then every 4 hours."""
        QTimer.singleShot(CLIENT_CHECK_FIRST_MS, self.check_clients)
        self._client_timer.start()

    def check_clients(self) -> None:
        """Q14 repair and Q4 detection on a worker thread (AI app commands can be slow)."""

        def work() -> None:
            try:
                with self._client_lock:
                    repaired = self.installer.repair()
                    statuses = self.installer.status()
            except Exception:  # a check must never crash the tray
                return
            self._bridge.clients_checked.emit(statuses, repaired)

        threading.Thread(target=work, name="ai-apps-check", daemon=True).start()

    def _on_clients_checked(self, statuses: object, repaired: object) -> None:
        tr = self.tr_
        results = repaired if isinstance(repaired, list) else []
        fixed = [
            r.label for r in results if isinstance(r, ActionResult) and r.outcome == "repaired"
        ]
        if fixed:
            self.notify(
                tr("notify.clients.repaired.title"),
                tr("notify.clients.repaired.body", apps=", ".join(fixed)),
            )
        if not isinstance(statuses, list):
            return
        items = [s for s in statuses if isinstance(s, ClientStatus)]
        new = self.new_apps(items)
        self._remember_known_apps(items)
        if new and not (self.connect_window is not None and self.connect_window.isVisible()):
            self.notify(
                tr("notify.clients.found.title"),
                tr("notify.clients.found.body", apps=", ".join(s.label for s in new)),
                kind="clients",
            )

    def new_apps(self, statuses: list[ClientStatus]) -> list[ClientStatus]:
        """Installed, not connected, and never seen before (Q4: only ask, never change)."""
        vault = self.runtime.vault
        known = vault.get_setting(SETTING_KNOWN_APPS)
        if not vault.get_setting(SETTING_CONNECT_OFFERED) or not isinstance(known, list):
            return []
        return [
            s
            for s in statuses
            if s.installed and s.state in ("not_connected", "conflict") and s.id not in known
        ]

    def _remember_known_apps(self, statuses: list[ClientStatus] | None = None) -> None:
        if statuses is None:
            try:
                with self._client_lock:
                    statuses = self.installer.status()
            except Exception:
                return
        vault = self.runtime.vault
        known = vault.get_setting(SETTING_KNOWN_APPS)
        ids = set(known) if isinstance(known, list) else set()
        ids.update(s.id for s in statuses if s.installed)
        vault.set_setting(SETTING_KNOWN_APPS, sorted(ids))

    def _fill_clients_menu(self) -> None:
        tr = self.tr_
        self.clients_menu.clear()
        try:
            with self._client_lock:
                statuses = [s for s in self.installer.status() if s.installed]
        except Exception:
            statuses = []
        if not statuses:
            self.clients_menu.addAction(tr("tray.clients.none")).setEnabled(False)
        for status in statuses:
            line = tr("tray.clients.line", app=status.label, state=state_text(tr, status))
            self.clients_menu.addAction(line).setEnabled(False)
        self.clients_menu.addSeparator()
        self.clients_menu.addAction(tr("tray.clients.connect")).triggered.connect(self.show_connect)
        disconnect = self.clients_menu.addAction(tr("tray.clients.disconnect_all"))
        disconnect.setEnabled(any(s.state in ("connected", "needs_repair") for s in statuses))
        disconnect.triggered.connect(self.ask_disconnect_all)

    def ask_disconnect_all(self) -> None:
        box = QMessageBox(
            QMessageBox.Icon.Question,
            self.tr_("app.name"),
            self.tr_("tray.clients.confirm_disconnect"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.disconnect_all_clients()

    def disconnect_all_clients(self) -> None:
        def work() -> None:
            try:
                with self._client_lock:
                    results = self.installer.disconnect()
            except Exception as exc:
                results = [ActionResult("-", "-", "failed", detail=str(exc))]
            self._bridge.clients_disconnected.emit(results)

        threading.Thread(target=work, name="ai-apps-disconnect", daemon=True).start()

    def _on_clients_disconnected(self, results: object) -> None:
        items = (
            [r for r in results if isinstance(r, ActionResult)] if isinstance(results, list) else []
        )
        done = [r.label for r in items if r.outcome == "disconnected"]
        if done:
            self.notify(
                self.tr_("notify.clients.disconnected.title"),
                self.tr_("notify.clients.disconnected.body", apps=", ".join(done)),
            )

    # ------------------------------------------------------------------ updates
    def check_for_updates(self, *, interactive: bool) -> None:
        """Ask GitHub on a worker thread; the answer comes back on the main thread."""
        if self._update_busy:
            return
        self._update_busy = True

        def work() -> None:
            from mcp_siigo_unofficial.update.releases import UpdateError, check_for_update

            try:
                self._bridge.update_checked.emit(check_for_update(), None, interactive)
            except UpdateError as exc:
                self._bridge.update_checked.emit(None, str(exc), interactive)

        threading.Thread(target=work, name="update-check", daemon=True).start()

    def _message(self, text: str, *, icon: QMessageBox.Icon = QMessageBox.Icon.Information) -> None:
        QMessageBox(icon, self.tr_("app.name"), text).exec()

    def _on_update_checked(self, release: object, error: object, interactive: bool) -> None:
        from mcp_siigo_unofficial.update.apply import can_self_update
        from mcp_siigo_unofficial.update.releases import Release

        self._update_busy = False
        tr = self.tr_
        if error is not None:
            if interactive:
                self._message(tr("update.error", error=error), icon=QMessageBox.Icon.Warning)
            return
        if not isinstance(release, Release):
            if interactive:
                self._message(tr("update.latest", version=__version__))
            return
        if not interactive:
            self.notify(
                tr("update.available.title"), tr("update.available.body", version=release.version)
            )
            return
        if not can_self_update():
            self._message(tr("update.manual", version=release.version))
            QDesktopServices.openUrl(QUrl(release.page_url or RELEASES_URL))
            return
        box = QMessageBox(
            QMessageBox.Icon.Question,
            tr("app.name"),
            tr("update.ask", version=release.version, current=__version__),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self._update_busy = True
        self.notify(tr("update.available.title"), tr("update.downloading", version=release.version))

        def work() -> None:
            from mcp_siigo_unofficial.update.apply import clean_downloads, downloads_dir
            from mcp_siigo_unofficial.update.releases import UpdateError, download_update

            try:
                clean_downloads()
                self._bridge.update_downloaded.emit(download_update(release, downloads_dir()), None)
            except UpdateError as exc:
                self._bridge.update_downloaded.emit(None, str(exc))

        threading.Thread(target=work, name="update-download", daemon=True).start()

    def _on_update_downloaded(self, path: object, error: object) -> None:
        from pathlib import Path

        from mcp_siigo_unofficial.update.apply import start_update
        from mcp_siigo_unofficial.update.releases import UpdateError

        self._update_busy = False
        if error is not None or not isinstance(path, Path):
            self._message(self.tr_("update.error", error=error), icon=QMessageBox.Icon.Warning)
            return
        try:
            start_update(path, pid=os.getpid(), start_app=True)
        except (UpdateError, OSError) as exc:
            self._message(self.tr_("update.error", error=exc), icon=QMessageBox.Icon.Warning)
            return
        self.app.quit()  # the installer waits for this process to exit

    def show_update_result(self, result: dict[str, object] | None) -> None:
        """Show the outcome of the update that ran before this start (once)."""
        if not result:
            return
        old, new = result.get("from") or "-", result.get("to") or "-"
        if result.get("ok"):
            self.notify(
                self.tr_("update.done.title"), self.tr_("update.done.body", old=old, new=new)
            )
        else:
            self.notify(
                self.tr_("update.rollback.title"),
                self.tr_("update.rollback.body", old=old, new=new),
                warning=True,
            )

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_settings()
