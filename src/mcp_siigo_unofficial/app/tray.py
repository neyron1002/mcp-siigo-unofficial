"""The tray icon and its menu (plan section 4 and 5.1)."""

from __future__ import annotations

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from mcp_siigo_unofficial.app.dialogs import AboutDialog, SettingsDialog, WriteActionsDialog
from mcp_siigo_unofficial.app.icons import app_icon
from mcp_siigo_unofficial.app.runtime import AppRuntime
from mcp_siigo_unofficial.autostart import Autostart, launch_command
from mcp_siigo_unofficial.i18n import RELEASES_URL, Translator


class _Bridge(QObject):
    """Moves callbacks from other threads onto the Qt main thread."""

    write_changed = Signal(bool)
    show_requested = Signal()


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
        runtime.write_switch.add_listener(self._bridge.write_changed.emit)
        runtime.on_show_requested = self._bridge.show_requested.emit

        self.tray = QSystemTrayIcon(self._icon_normal)
        self.menu = QMenu()
        self.status_action = QAction()
        self.status_action.setEnabled(False)
        self.write_action = QAction()
        self.write_action.setCheckable(True)
        self.write_action.triggered.connect(self.toggle_write_actions)
        self.copy_menu = QMenu()
        self.settings_action = QAction()
        self.settings_action.triggered.connect(self.show_settings)
        self.autostart_action = QAction()
        self.autostart_action.setCheckable(True)
        self.autostart_action.triggered.connect(self.toggle_autostart)
        self.updates_action = QAction()
        self.updates_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        self.about_action = QAction()
        self.about_action.triggered.connect(self.show_about)
        self.quit_action = QAction()
        self.quit_action.triggered.connect(self.app.quit)

        self.menu.addAction(self.status_action)
        self.menu.addSeparator()
        self.menu.addAction(self.write_action)
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
        self.refresh()
        if enabled:
            self.notify(tr("notify.write.on.title"), tr("notify.write.on.body"), warning=True)
        else:
            self.notify(tr("notify.write.off.title"), tr("notify.write.off.body"))

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

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_settings()
