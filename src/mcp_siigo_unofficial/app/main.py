"""Start the tray app (the default mode, and ``--run`` at login)."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Sequence

from PySide6.QtCore import QLibraryInfo, QLocale, QTimer, QTranslator
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from mcp_siigo_unofficial import __version__
from mcp_siigo_unofficial.app.icons import app_icon
from mcp_siigo_unofficial.app.runtime import AppRuntime
from mcp_siigo_unofficial.app.tray import TrayController
from mcp_siigo_unofficial.autostart import (
    SETTING_AUTOSTART_CONFIGURED,
    Autostart,
    for_platform,
    launch_command,
)
from mcp_siigo_unofficial.i18n import SETTING_LANGUAGE, Translator
from mcp_siigo_unofficial.paths import vault_path
from mcp_siigo_unofficial.vault import (
    KeyringKeyStore,
    KeyStoreError,
    Vault,
    VaultKeyMismatchError,
    VaultKeyMissingError,
)

log = logging.getLogger(__name__)
#: Set to 1 to turn off the quiet update check at start (tests, offline use).
NO_UPDATE_CHECK_ENV = "MCP_SIIGO_UNOFFICIAL_NO_UPDATE_CHECK"
UPDATE_CHECK_DELAY_MS = 20_000


def _install_qt_translations(app: QApplication, language: str) -> None:
    """Spanish strings for Qt's own buttons and dialogs (plan D20: es and en only)."""
    if language != "es":
        return
    translator = QTranslator(app)
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale("es"), "qtbase", "_", path):
        app.installTranslator(translator)


def _open_runtime(tr: Translator) -> AppRuntime | None:
    """Open the vault. If its key is missing or wrong, offer to reset it."""
    keystore = KeyringKeyStore()
    try:
        return AppRuntime.open(vault_path(), keystore)
    except KeyStoreError as exc:
        QMessageBox(QMessageBox.Icon.Critical, tr("app.name"), str(exc)).exec()
        return None
    except (VaultKeyMissingError, VaultKeyMismatchError) as exc:
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            tr("app.name"),
            f"{exc}\n\nReset the vault? / ¿Restablecer el almacén?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if box.exec() != QMessageBox.StandardButton.Yes:
            return None
        Vault.reset(vault_path(), keystore).close()
        return AppRuntime.open(vault_path(), keystore)


def configure_autostart_once(runtime: AppRuntime, autostart: Autostart) -> None:
    """Plan D16: start at login is on after the first run (installed builds only)."""
    if runtime.vault.get_setting(SETTING_AUTOSTART_CONFIGURED):
        return
    if getattr(sys, "frozen", False):
        autostart.enable(launch_command())
    runtime.vault.set_setting(SETTING_AUTOSTART_CONFIGURED, True)


def running_from_disk_image(executable: str = sys.executable) -> bool:
    """macOS: True when the app runs from a mounted DMG instead of Applications."""
    return (
        sys.platform == "darwin"
        and getattr(sys, "frozen", False)
        and executable.startswith("/Volumes/")
    )


def run_app(argv: Sequence[str] | None = None) -> int:
    app = QApplication(list(argv) if argv is not None else sys.argv[:1])
    app.setApplicationName("MCP Siigo Unofficial")
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())

    tr = Translator()
    if running_from_disk_image():
        # Start at login needs a stable path (plan section 3).
        QMessageBox(QMessageBox.Icon.Information, tr("app.name"), tr("mac.move_to_apps")).exec()
        return 1
    runtime = _open_runtime(tr)
    if runtime is None:
        return 1
    tr.set_language(runtime.vault.get_setting(SETTING_LANGUAGE))
    _install_qt_translations(app, tr.language)

    if not runtime.start_server() and runtime.ask_running_instance_to_show():
        log.info("Another instance is running; it was asked to show itself.")
        runtime.vault.close()
        return 0

    autostart = for_platform()
    configure_autostart_once(runtime, autostart)
    tray = TrayController(runtime, tr, autostart, app)
    tray.show()
    has_tray = QSystemTrayIcon.isSystemTrayAvailable()
    # Without a tray area, the Settings window is the app: closing it quits.
    app.setQuitOnLastWindowClosed(not has_tray)
    if not has_tray or runtime.credentials() is None:
        tray.show_settings()

    from mcp_siigo_unofficial.update.apply import take_update_result

    tray.show_update_result(take_update_result())
    # One-click plan v3: the Connect window once (Q12), then repair (Q14) and new apps (Q4).
    tray.offer_connect_once()
    tray.start_client_checks()
    if os.environ.get(NO_UPDATE_CHECK_ENV) != "1":
        QTimer.singleShot(UPDATE_CHECK_DELAY_MS, lambda: tray.check_for_updates(interactive=False))

    app.aboutToQuit.connect(runtime.shutdown)
    return app.exec()
