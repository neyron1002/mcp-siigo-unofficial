"""The tray icon and its menu (plan section 4 and 5.1)."""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from mcp_siigo_unofficial import __version__
from mcp_siigo_unofficial.app.approval_window import ApprovalWindow
from mcp_siigo_unofficial.app.dialogs import AboutDialog, SettingsDialog, WriteActionsDialog
from mcp_siigo_unofficial.app.icons import app_icon
from mcp_siigo_unofficial.app.runtime import AppRuntime
from mcp_siigo_unofficial.autostart import Autostart, launch_command
from mcp_siigo_unofficial.i18n import RELEASES_URL, Translator
from mcp_siigo_unofficial.server.approval import ApprovalRequest, Decision


class _Bridge(QObject):
    """Moves callbacks from other threads onto the Qt main thread."""

    write_changed = Signal(bool)
    show_requested = Signal()
    update_checked = Signal(object, object, bool)  # release or None, error or None, interactive
    update_downloaded = Signal(object, object)  # path or None, error or None
    approval_requested = Signal(object)  # ApprovalRequest
    approval_closed = Signal(str)  # request id (timed out)
    grants_changed = Signal()


class TrayController(QObject):
    """Owns the tray icon, its menu, and the dialogs."""

    def __init__(
        self, runtime: AppRuntime, tr: Translator, autostart: Autostart, app: QApplication
    ) -> None:
        super().__init__()
        self.runtime = runtime
        self.tr_ = tr
        self.autostart = autostart
        self.app = app
        self._icon_normal = app_icon(write_mode=False)
        self._icon_write = app_icon(write_mode=True)
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
        self._grant_timer = QTimer(self)
        self._grant_timer.setInterval(15_000)
        self._grant_timer.timeout.connect(self.refresh)

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
        self.copy_menu = QMenu()
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
        self.settings_dialog: SettingsDialog | None = None
        self.about_dialog: AboutDialog | None = None
        self.retranslate()

    # ------------------------------------------------------------------ state
    def retranslate(self) -> None:
        tr = self.tr_
        self.copy_menu.setTitle(tr("tray.copy_setup"))
        self.settings_action.setText(tr("tray.settings"))
        self.autostart_action.setText(tr("tray.autostart"))
        self.updates_action.setText(tr("tray.updates"))
        self.about_action.setText(tr("tray.about"))
        self.quit_action.setText(tr("tray.quit"))
        self.stop_grants_action.setText(tr("tray.grants.stop"))
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
        grants = self.runtime.approvals.grants()
        if grants:
            first = grants[0]
            minutes = int(self.runtime.approvals.seconds_left(first) // 60) + 1
            self.grants_action.setText(tr("tray.grants", title=first.title, minutes=minutes))
            if not self._grant_timer.isActive():
                self._grant_timer.start()
        elif self._grant_timer.isActive():
            self._grant_timer.stop()
        self.grants_action.setVisible(bool(grants))
        self.stop_grants_action.setVisible(bool(grants))
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
        self.refresh()
        if enabled:
            self.notify(tr("notify.write.on.title"), tr("notify.write.on.body"), warning=True)
        else:
            self.notify(tr("notify.write.off.title"), tr("notify.write.off.body"))

    # ------------------------------------------------------------------ approvals
    def show_approval(self, request: object) -> None:
        """Show the approval window for one write (main thread)."""
        if not isinstance(request, ApprovalRequest):
            return
        window = ApprovalWindow(request, self.tr_, self._approval_answered)
        window.finished.connect(lambda _=0, rid=request.id: self.approval_windows.pop(rid, None))
        self.approval_windows[request.id] = window
        window.bring_to_front()
        self.notify(
            self.tr_("notify.approval.title"),
            self.tr_("notify.approval.body", client=request.client, title=request.title),
            warning=True,
        )

    def _approval_answered(self, request_id: str, decision: Decision) -> None:
        window = self.approval_windows.pop(request_id, None)
        self.runtime.approvals.answer(request_id, decision)
        if decision is Decision.APPROVE_SIMILAR and window is not None:
            title = window.request.title
            self.notify(self.tr_("notify.grant.title"), self.tr_("notify.grant.body", title=title))

    def _close_approval(self, request_id: str) -> None:
        window = self.approval_windows.pop(request_id, None)
        if window is not None:
            window.close_without_answer()

    def stop_grants(self) -> None:
        self.runtime.approvals.stop_grants()
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

    def notify(self, title: str, message: str, *, warning: bool = False) -> None:
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
