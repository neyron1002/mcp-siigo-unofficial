"""Tray app tests (plan phase 3): runtime, dialogs, tray, and the self-test.

Qt runs with the ``offscreen`` platform, so no screen is needed.
"""

from __future__ import annotations

import os
import socket
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ.get("MCP_SIIGO_REQUIRE_QT") != "1":
    # Local runs without Qt skip; CI sets MCP_SIIGO_REQUIRE_QT=1 so a broken Qt fails.
    pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QDialog

from mcp_siigo_unofficial.app import dialogs as dialogs_module
from mcp_siigo_unofficial.app import tray as tray_module
from mcp_siigo_unofficial.app.dialogs import (
    AboutDialog,
    SettingsDialog,
    WriteActionsDialog,
)
from mcp_siigo_unofficial.app.main import configure_autostart_once
from mcp_siigo_unofficial.app.runtime import BASE_URL_ENV, AppRuntime
from mcp_siigo_unofficial.app.tray import TrayController
from mcp_siigo_unofficial.autostart import (
    SETTING_AUTOSTART_CONFIGURED,
    LinuxAutostart,
)
from mcp_siigo_unofficial.i18n import SETTING_LANGUAGE, Translator
from mcp_siigo_unofficial.selftest import run_selftest
from mcp_siigo_unofficial.server.transport import SETTING_PORT
from mcp_siigo_unofficial.siigo import SiigoCredentials
from mcp_siigo_unofficial.vault import MemoryKeyStore
from mock_siigo import TEST_ACCESS_KEY, TEST_USERNAME, MockSiigo


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


@pytest.fixture
def runtime(tmp_path: Path) -> Iterator[AppRuntime]:
    rt = AppRuntime.open(tmp_path / "vault.sqlite3", MemoryKeyStore())
    rt.port = free_port()
    try:
        yield rt
    finally:
        rt.shutdown()


@pytest.fixture
def tr() -> Translator:
    return Translator("en")


@pytest.fixture
def tray(
    qapp: QApplication, runtime: AppRuntime, tr: Translator, tmp_path: Path
) -> Iterator[TrayController]:
    controller = TrayController(runtime, tr, LinuxAutostart(tmp_path / "config"), qapp)
    yield controller
    controller.tray.hide()


def process_events(until: Any = None, timeout: float = 5.0) -> None:
    deadline = threading.Event()
    waited = 0.0
    while True:
        QCoreApplication.processEvents()
        if until is None or until() or waited >= timeout:
            return
        deadline.wait(0.02)
        waited += 0.02


def accept_dialog(monkeypatch: pytest.MonkeyPatch, module: Any, *, tick: bool) -> None:
    """Replace the modal exec() of the write warning with an automatic answer."""

    def fake_exec(self: WriteActionsDialog) -> int:
        self.accept_box.setChecked(tick)
        self.enable_button.click()
        if not tick:
            self.reject()
        return int(self.result())

    monkeypatch.setattr(module.WriteActionsDialog, "exec", fake_exec)


# ---------------------------------------------------------------------- runtime
def test_runtime_starts_off_and_serves(runtime: AppRuntime) -> None:
    assert runtime.write_switch.enabled is False
    assert runtime.start_server()
    assert runtime.server_running
    assert runtime.url.startswith("http://127.0.0.1:")
    assert {s.key for s in runtime.client_setups()} >= {"claude_code", "copilot"}


def test_second_instance_asks_the_first_to_show(tmp_path: Path, runtime: AppRuntime) -> None:
    shown = threading.Event()
    runtime.on_show_requested = shown.set
    assert runtime.start_server()
    other = AppRuntime(runtime.vault)  # same vault: same bearer key and port setting
    other.port = runtime.port
    assert not other.start_server()
    assert "already in use" in (other.server_error or "")
    assert other.ask_running_instance_to_show()
    assert shown.wait(5)


def test_ask_to_show_without_a_running_instance(runtime: AppRuntime) -> None:
    assert runtime.ask_running_instance_to_show() is False


def test_credentials_and_connection_test(
    runtime: AppRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = SiigoCredentials(TEST_USERNAME, TEST_ACCESS_KEY)
    bad = SiigoCredentials(TEST_USERNAME, "wrong")
    mock = MockSiigo()
    with mock.serve() as base_url:
        monkeypatch.setenv(BASE_URL_ENV, base_url)
        assert runtime.test_credentials(good) is None
        assert "Invalid username" in (runtime.test_credentials(bad) or "")
    runtime.save_credentials(good)
    assert runtime.credentials() == good
    runtime.clear_credentials()
    assert runtime.credentials() is None


def test_port_setting(runtime: AppRuntime) -> None:
    runtime.set_port(40001)
    assert runtime.vault.get_setting(SETTING_PORT) == 40001
    with pytest.raises(ValueError, match="1024"):
        runtime.set_port(80)


def test_shutdown_turns_writes_off(tmp_path: Path) -> None:
    keystore = MemoryKeyStore()
    rt = AppRuntime.open(tmp_path / "v.sqlite3", keystore)
    rt.write_switch.enable(accepted_responsibility=True)
    assert rt.vault.get_setting("write_actions.enabled") is True
    rt.shutdown()
    rt2 = AppRuntime.open(tmp_path / "v.sqlite3", keystore)
    try:
        assert rt2.vault.get_setting("write_actions.enabled") is False
        assert rt2.write_switch.enabled is False
        kinds = [e.kind for e in rt2.vault.events()]
        assert kinds == ["write_actions.enabled", "write_actions.disabled"]
    finally:
        rt2.shutdown()


def test_autostart_configured_once(runtime: AppRuntime, tmp_path: Path) -> None:
    autostart = LinuxAutostart(tmp_path / "cfg")
    configure_autostart_once(runtime, autostart)
    assert runtime.vault.get_setting(SETTING_AUTOSTART_CONFIGURED) is True
    assert not autostart.is_enabled()  # only installed (frozen) builds turn it on


# ---------------------------------------------------------------------- dialogs
def test_write_dialog_needs_the_acceptance_tick(qapp: QApplication, tr: Translator) -> None:
    dialog = WriteActionsDialog(tr)
    assert not dialog.enable_button.isEnabled()
    dialog.enable_button.click()
    assert dialog.result() != QDialog.DialogCode.Accepted
    dialog.accept_box.setChecked(True)
    assert dialog.enable_button.isEnabled()
    dialog.enable_button.click()
    assert dialog.accepted_responsibility


def test_write_dialog_cancel(qapp: QApplication, tr: Translator) -> None:
    dialog = WriteActionsDialog(tr)
    dialog.accept_box.setChecked(True)
    dialog.cancel_button.click()
    assert not dialog.accepted_responsibility


def test_settings_validation_and_save(
    qapp: QApplication, runtime: AppRuntime, tr: Translator
) -> None:
    dialog = SettingsDialog(runtime, tr)
    dialog.username.setText("user@example.com")
    dialog.save_button.click()
    assert "access key" in dialog.status.text()
    dialog.access_key.setText("secret-key")
    dialog.partner_id.setText("bad id")
    dialog.save_button.click()
    assert "Partner-Id" in dialog.status.text()
    assert runtime.credentials() is None
    dialog.partner_id.setText("MyPartner")
    dialog.save_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert runtime.credentials() == SiigoCredentials("user@example.com", "secret-key", "MyPartner")

    again = SettingsDialog(runtime, tr)
    assert again.access_key.text() == ""
    assert "Saved" in again.access_key.placeholderText()
    again.username.setText("other@example.com")
    again.save_button.click()
    saved = runtime.credentials()
    assert saved is not None
    assert saved.access_key == "secret-key"
    assert saved.username == "other@example.com"


def test_settings_language_and_clear(
    qapp: QApplication, runtime: AppRuntime, tr: Translator
) -> None:
    runtime.save_credentials(SiigoCredentials("u@example.com", "k"))
    dialog = SettingsDialog(runtime, tr)
    changed: list[bool] = []
    dialog.language_changed.connect(lambda: changed.append(True))
    dialog._clear()
    assert runtime.credentials() is None
    dialog.language.setCurrentIndex(dialog.language.findData("es"))
    dialog.save_button.click()
    assert runtime.vault.get_setting(SETTING_LANGUAGE) == "es"
    assert tr.language == "es"
    assert changed == [True]


@pytest.mark.parametrize("tick", [True, False])
def test_settings_write_switch(
    qapp: QApplication,
    runtime: AppRuntime,
    tr: Translator,
    monkeypatch: pytest.MonkeyPatch,
    tick: bool,
) -> None:
    accept_dialog(monkeypatch, dialogs_module, tick=tick)
    dialog = SettingsDialog(runtime, tr)
    dialog.write_box.click()
    assert runtime.write_switch.enabled is tick
    assert dialog.write_box.isChecked() is tick
    if tick:
        dialog.write_box.click()
        assert runtime.write_switch.enabled is False


def test_settings_connection_test_button(
    qapp: QApplication, runtime: AppRuntime, tr: Translator, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock = MockSiigo()
    with mock.serve() as base_url:
        monkeypatch.setenv(BASE_URL_ENV, base_url)
        dialog = SettingsDialog(runtime, tr)
        dialog.username.setText(TEST_USERNAME)
        dialog.access_key.setText(TEST_ACCESS_KEY)
        dialog.test_button.click()
        process_events(lambda: dialog.test_button.isEnabled())
    assert dialog.status.text() == "Connected to Siigo."
    assert mock.auth_calls == 1


def test_about_dialog(qapp: QApplication) -> None:
    dialog = AboutDialog(Translator("es"))
    assert dialog.linkedin_button.text() == "Contácteme por LinkedIn"
    assert dialog.windowTitle() == "Acerca de MCP Siigo Unofficial"


# ---------------------------------------------------------------------- tray
def test_tray_menu_and_status(tray: TrayController, runtime: AppRuntime) -> None:
    texts = [a.text() for a in tray.menu.actions() if a.text()]
    assert "Write actions: OFF" in texts
    assert "Quit" in texts
    assert tray.status_text().startswith("MCP server stopped")
    assert runtime.start_server()
    tray.refresh()
    assert tray.status_text() == "Siigo credentials missing: open Settings"
    runtime.save_credentials(SiigoCredentials("u@example.com", "k"))
    assert tray.status_text() == f"MCP server running at {runtime.url}"
    assert next(a.text() for a in tray.copy_menu.actions()) == "Claude Code"


@pytest.mark.parametrize("tick", [True, False])
def test_tray_write_toggle_changes_icon_and_tooltip(
    tray: TrayController, runtime: AppRuntime, monkeypatch: pytest.MonkeyPatch, tick: bool
) -> None:
    accept_dialog(monkeypatch, tray_module, tick=tick)
    normal_key = tray.tray.icon().cacheKey()
    tray.write_action.trigger()
    process_events()
    assert runtime.write_switch.enabled is tick
    if tick:
        assert tray.tray.toolTip() == "MCP Siigo Unofficial — WRITE ACTIONS ENABLED"
        assert tray.write_action.text() == "Write actions: ON"
        assert tray.tray.icon().cacheKey() != normal_key
        tray.write_action.trigger()
        process_events()
    assert runtime.write_switch.enabled is False
    assert tray.tray.toolTip() == "MCP Siigo Unofficial"


def test_switch_change_from_another_thread_updates_the_tray(
    tray: TrayController, runtime: AppRuntime
) -> None:
    worker = threading.Thread(
        target=lambda: runtime.write_switch.enable(accepted_responsibility=True)
    )
    worker.start()
    worker.join()
    process_events(lambda: tray.write_action.isChecked())
    assert tray.write_action.text() == "Write actions: ON"


def test_tray_copy_setup_and_autostart(tray: TrayController, runtime: AppRuntime) -> None:
    setup = runtime.client_setups()[0]
    tray.copy_setup(setup.label, setup.text)
    assert QGuiApplication.clipboard().text() == setup.text
    assert not tray.autostart.is_enabled()
    tray.toggle_autostart()
    assert tray.autostart.is_enabled()
    assert tray.autostart_action.isChecked()
    tray.toggle_autostart()
    assert not tray.autostart.is_enabled()


def test_tray_settings_window_and_retranslate(tray: TrayController, tr: Translator) -> None:
    tray.show_settings()
    first = tray.settings_dialog
    tray.show_settings()
    assert tray.settings_dialog is first
    assert first is not None
    first.close()
    tr.set_language("es")
    tray.retranslate()
    assert tray.quit_action.text() == "Salir"
    tray.show_about()
    assert tray.about_dialog is not None
    tray.about_dialog.close()


# ---------------------------------------------------------------------- self-test
def test_selftest_offline(qapp: QApplication, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_selftest(offline=True) == 0
    assert '"ok": true' in capsys.readouterr().out
