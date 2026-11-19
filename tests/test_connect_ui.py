"""One-click connect, phase 8: the Connect window, the tray's AI apps menu, the
once-only offer (Q12), new-app notifications (Q4), repair at start (Q14), and the
Claude Desktop restart (Q6).

Qt runs offscreen; every AI app lives in a fake home folder with fake commands.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ.get("MCP_SIIGO_REQUIRE_QT") != "1":
    pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from mcp_siigo_unofficial.app import tray as tray_module
from mcp_siigo_unofficial.app.connect_window import ConnectWindow, state_text
from mcp_siigo_unofficial.app.runtime import AppRuntime
from mcp_siigo_unofficial.app.tray import (
    SETTING_CONNECT_OFFERED,
    SETTING_KNOWN_APPS,
    TrayController,
)
from mcp_siigo_unofficial.autostart import LinuxAutostart
from mcp_siigo_unofficial.clients import Environment, Installer, ServerSpec
from mcp_siigo_unofficial.clients.apps import CommandResult
from mcp_siigo_unofficial.clients.restart import restart_claude_desktop
from mcp_siigo_unofficial.i18n import Translator
from mcp_siigo_unofficial.vault import MemoryKeyStore
from test_clients import (
    HTTP_URL,
    KEY,
    LAUNCHER,
    MOVED_LAUNCHER,
    OTHER_SERVER,
    FakeRunner,
    claude_json,
    installer,
    make_env,
    make_exe,
)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


@pytest.fixture
def tr() -> Translator:
    return Translator("en")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    path = tmp_path / "bin"
    path.mkdir()
    return path


def wait_for(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    pause = threading.Event()
    waited = 0.0
    while not condition():
        QCoreApplication.processEvents()
        if waited >= timeout:
            raise AssertionError("timed out")
        pause.wait(0.02)
        waited += 0.02
    QCoreApplication.processEvents()


def wait_idle(window: ConnectWindow) -> None:
    wait_for(lambda: not window.busy)


def desktop_env(home: Path, bin_dir: Path, runner: Any) -> Environment:
    """macOS with Claude Desktop installed (its settings folder exists)."""
    (home / "Library" / "Application Support" / "Claude").mkdir(parents=True)
    return make_env(home, bin_dir, runner, platform="darwin")


# ---------------------------------------------------------------- window
def test_window_rows_ticks_and_advanced(
    qapp: QApplication, tr: Translator, home: Path, bin_dir: Path
) -> None:
    make_exe(bin_dir, "claude")
    env = desktop_env(home, bin_dir, FakeRunner(home))
    window = ConnectWindow(installer(env), tr)
    rows = window.rows
    assert set(rows) == {"claude-code", "claude-desktop", "codex", "gemini", "vscode"}
    assert rows["claude-code"].box.isChecked()
    assert rows["claude-desktop"].box.isChecked()
    assert not rows["codex"].box.isEnabled()  # not installed
    assert rows["codex"].state.text() == "Not installed"
    assert rows["claude-code"].state.text() == "Found"
    # Advanced is hidden at first; Claude Desktop offers stdio only (Q2b).
    assert not window.advanced_note.isVisibleTo(window)
    assert not rows["claude-code"].transport.isVisibleTo(window)
    window.advanced_box.setChecked(True)
    assert rows["claude-code"].transport.isVisibleTo(window)
    assert rows["claude-desktop"].transport.count() == 1
    assert rows["claude-code"].transport.count() == 2
    assert window.selected() == [("claude-code", "stdio"), ("claude-desktop", "stdio")]


def test_connect_writes_settings_and_shows_restart(
    qapp: QApplication, tr: Translator, home: Path, bin_dir: Path
) -> None:
    make_exe(bin_dir, "claude")
    env = desktop_env(home, bin_dir, FakeRunner(home))
    restarted: list[bool] = []
    window = ConnectWindow(installer(env), tr, lambda: restarted.append(True) or True)
    window.connect_selected()
    wait_idle(window)
    assert claude_json(home)["mcpServers"]["siigo"]["command"] == LAUNCHER[0]
    desktop = json.loads(
        (home / "Library/Application Support/Claude/claude_desktop_config.json").read_text()
    )
    assert desktop["mcpServers"]["siigo"]["args"] == ["--stdio"]
    text = window.result_label.text()
    assert 'Claude Code: connected as "siigo".' in text
    assert "Restart Claude Desktop to see the change." in text
    assert window.restart_button.isVisibleTo(window)
    assert window.rows["claude-code"].state.text() == "Connected · stdio (recommended)"
    assert window.close_button.text() == "Close"
    window.restart_desktop()
    wait_idle(window)
    assert restarted == [True]
    assert window.result_label.text() == "Claude Desktop was restarted."


def test_http_choice_and_switch_to_stdio(
    qapp: QApplication, tr: Translator, home: Path, bin_dir: Path
) -> None:
    (home / ".gemini").mkdir()
    env = make_env(home, bin_dir, FakeRunner(home))
    window = ConnectWindow(installer(env), tr)
    row = window.rows["gemini"]
    window.advanced_box.setChecked(True)
    row.transport.setCurrentIndex(1)
    window.connect_selected()
    wait_idle(window)
    settings = json.loads((home / ".gemini" / "settings.json").read_text())
    assert settings["mcpServers"]["siigo"]["httpUrl"] == HTTP_URL
    assert KEY not in window.result_label.text()
    row = window.rows["gemini"]
    assert row.state.text() == "Connected · HTTP"
    assert row.button.isVisibleTo(window)
    assert row.button.text() == "Switch to stdio"
    row.button.click()
    wait_idle(window)
    settings = json.loads((home / ".gemini" / "settings.json").read_text())
    assert settings["mcpServers"]["siigo"]["command"] == LAUNCHER[0]
    assert window.rows["gemini"].button.text() == "Disconnect"


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("keep-both", "siigo-unofficial"), ("replace", "siigo"), (None, None)],
)
def test_conflict_question(
    qapp: QApplication,
    tr: Translator,
    home: Path,
    bin_dir: Path,
    answer: Any,
    expected: str | None,
) -> None:
    (home / ".gemini").mkdir()
    (home / ".gemini" / "settings.json").write_text(
        json.dumps({"mcpServers": {"siigo": OTHER_SERVER}})
    )
    env = make_env(home, bin_dir, FakeRunner(home))
    window = ConnectWindow(installer(env), tr)
    asked: list[str] = []
    window.ask_conflict = lambda label: asked.append(label) or answer
    assert window.rows["gemini"].state.text() == 'Another program uses "siigo"'
    window.connect_selected()
    wait_idle(window)
    assert asked == ["Gemini CLI"]
    servers = json.loads((home / ".gemini" / "settings.json").read_text())["mcpServers"]
    if expected is None:
        assert servers == {"siigo": OTHER_SERVER}
        assert "skipped" in window.result_label.text()
    else:
        assert servers[expected]["command"] == LAUNCHER[0]
        if expected == "siigo-unofficial":
            assert servers["siigo"] == OTHER_SERVER


def test_disconnect_all_restores_settings(
    qapp: QApplication, tr: Translator, home: Path, bin_dir: Path
) -> None:
    original = {"theme": "dark", "mcpServers": {"other": {"command": "node", "args": ["x.js"]}}}
    (home / ".claude.json").write_text(json.dumps(original))
    env = make_env(home, bin_dir, FakeRunner(home))
    window = ConnectWindow(installer(env), tr)
    window.connect_selected()
    wait_idle(window)
    assert "siigo" in claude_json(home)["mcpServers"]
    assert window.disconnect_button.isEnabled()
    window.disconnect_all()
    wait_idle(window)
    assert claude_json(home) == original
    assert "Claude Code: disconnected." in window.result_label.text()


def test_unreadable_settings_are_shown_and_left_alone(
    qapp: QApplication, tr: Translator, home: Path, bin_dir: Path
) -> None:
    (home / ".claude.json").write_text("{ broken")
    env = make_env(home, bin_dir, FakeRunner(home))
    window = ConnectWindow(installer(env), tr)
    row = window.rows["claude-code"]
    assert not row.box.isEnabled()
    assert row.state.text() == "Settings file can't be read"
    assert "not valid JSON" in row.state.toolTip()
    assert not window.connect_button.isEnabled()


def test_spanish_texts(qapp: QApplication, home: Path, bin_dir: Path) -> None:
    (home / ".codex").mkdir()
    env = make_env(home, bin_dir, FakeRunner(home))
    window = ConnectWindow(installer(env), Translator("es"))
    assert window.windowTitle() == "Conectar sus apps de IA"
    assert window.rows["codex"].state.text() == "Encontrada"
    assert window.connect_button.text() == "Conectar"


def test_state_text_for_every_state(tr: Translator, home: Path, bin_dir: Path) -> None:
    env = make_env(home, bin_dir, FakeRunner(home))
    for status in installer(env).status():
        assert state_text(tr, status)


# ---------------------------------------------------------------- tray
@pytest.fixture
def runtime(tmp_path: Path) -> Iterator[AppRuntime]:
    rt = AppRuntime.open(tmp_path / "vault.sqlite3", MemoryKeyStore())
    try:
        yield rt
    finally:
        rt.shutdown()


def make_tray(
    qapp: QApplication, runtime: AppRuntime, tr: Translator, tmp_path: Path, inst: Installer
) -> TrayController:
    return TrayController(runtime, tr, LinuxAutostart(tmp_path / "config"), qapp, installer=inst)


def test_runtime_specs_and_shared_token(runtime: AppRuntime) -> None:
    http = runtime.client_spec("http")
    assert (http.transport, http.url) == ("http", runtime.url)
    assert runtime.client_spec("stdio").transport == "stdio"
    assert type(runtime.siigo._token_store).__name__ == "VaultTokenStore"


def test_offer_connect_once(
    qapp: QApplication,
    runtime: AppRuntime,
    tr: Translator,
    tmp_path: Path,
    home: Path,
    bin_dir: Path,
) -> None:
    env = make_env(home, bin_dir, FakeRunner(home))
    tray = make_tray(qapp, runtime, tr, tmp_path, installer(env))
    try:
        assert tray.offer_connect_once() is False  # no AI app yet: nothing shown, not marked
        assert not runtime.vault.get_setting(SETTING_CONNECT_OFFERED)
        (home / ".codex").mkdir()
        assert tray.offer_connect_once() is True
        assert tray.connect_window is not None
        assert tray.connect_window.isVisible()
        tray.connect_window.reject()
        QCoreApplication.processEvents()
        assert runtime.vault.get_setting(SETTING_KNOWN_APPS) == ["codex"]
        assert tray.offer_connect_once() is False  # only once (Q12)
    finally:
        tray.tray.hide()


def test_new_app_notification_and_click(
    qapp: QApplication,
    runtime: AppRuntime,
    tr: Translator,
    tmp_path: Path,
    home: Path,
    bin_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = make_env(home, bin_dir, FakeRunner(home))
    tray = make_tray(qapp, runtime, tr, tmp_path, installer(env))
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(tray, "notify", lambda t, m, **k: shown.append((t, m)) or None)
    try:
        runtime.vault.set_setting(SETTING_CONNECT_OFFERED, True)
        runtime.vault.set_setting(SETTING_KNOWN_APPS, ["codex"])
        (home / ".codex").mkdir()
        (home / ".gemini").mkdir()
        tray.check_clients()
        wait_for(lambda: bool(shown))
        assert shown == [("AI app found", "Gemini CLI found. Click to connect it to Siigo.")]
        assert runtime.vault.get_setting(SETTING_KNOWN_APPS) == ["codex", "gemini"]
        # Nothing was changed without a click (Q4).
        assert not (home / ".gemini" / "settings.json").exists()
        # A second check does not ask again.
        shown.clear()
        tray.check_clients()
        wait_for(lambda: runtime.vault.get_setting(SETTING_KNOWN_APPS) == ["codex", "gemini"])
        threading.Event().wait(0.3)
        QCoreApplication.processEvents()
        assert shown == []
    finally:
        tray.tray.hide()


def test_message_click_opens_the_connect_window(
    qapp: QApplication,
    runtime: AppRuntime,
    tr: Translator,
    tmp_path: Path,
    home: Path,
    bin_dir: Path,
) -> None:
    env = make_env(home, bin_dir, FakeRunner(home))
    tray = make_tray(qapp, runtime, tr, tmp_path, installer(env))
    try:
        tray.notify("t", "m", kind="clients")
        tray._on_message_clicked()
        assert tray.connect_window is not None
        assert tray.connect_window.isVisible()
        tray.connect_window.reject()
        tray.notify("t", "m")
        tray.connect_window = None
        tray._on_message_clicked()
        assert tray.connect_window is None
    finally:
        tray.tray.hide()


def test_repair_at_start_notifies(
    qapp: QApplication,
    runtime: AppRuntime,
    tr: Translator,
    tmp_path: Path,
    home: Path,
    bin_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"siigo": {"command": MOVED_LAUNCHER[0], "args": ["--stdio"]}}})
    )
    env = make_env(home, bin_dir, FakeRunner(home))
    tray = make_tray(qapp, runtime, tr, tmp_path, installer(env))
    shown: list[str] = []
    monkeypatch.setattr(tray, "notify", lambda t, m, **k: shown.append(t) or None)
    try:
        tray.check_clients()
        wait_for(lambda: bool(shown))
        assert shown == ["AI app setup updated"]
        assert claude_json(home)["mcpServers"]["siigo"]["command"] == LAUNCHER[0]
    finally:
        tray.tray.hide()


def test_tray_ai_apps_menu_and_disconnect_all(
    qapp: QApplication,
    runtime: AppRuntime,
    tr: Translator,
    tmp_path: Path,
    home: Path,
    bin_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (home / ".codex").mkdir()
    env = make_env(home, bin_dir, FakeRunner(home))
    inst = installer(env)
    inst.connect(["codex"])
    tray = make_tray(qapp, runtime, tr, tmp_path, inst)
    shown: list[str] = []
    monkeypatch.setattr(tray, "notify", lambda t, m, **k: shown.append(m) or None)
    try:
        assert tray.clients_menu.title() == "AI apps"
        tray._fill_clients_menu()
        texts = [a.text() for a in tray.clients_menu.actions()]
        assert "Codex: Connected · stdio (recommended)" in texts
        assert "Connect AI apps…" in texts
        assert "Disconnect all AI apps" in texts
        monkeypatch.setattr(
            tray_module.QMessageBox, "exec", lambda self: tray_module.QMessageBox.StandardButton.Yes
        )
        tray.ask_disconnect_all()
        wait_for(lambda: bool(shown))
        assert shown == ["The Siigo tools were removed from: Codex."]
        assert inst.status(["codex"])[0].state == "not_connected"
    finally:
        tray.tray.hide()


def test_tray_menu_without_apps(
    qapp: QApplication,
    runtime: AppRuntime,
    tr: Translator,
    tmp_path: Path,
    home: Path,
    bin_dir: Path,
) -> None:
    env = make_env(home, bin_dir, FakeRunner(home))
    tray = make_tray(qapp, runtime, tr, tmp_path, installer(env))
    try:
        tray._fill_clients_menu()
        actions = tray.clients_menu.actions()
        assert actions[0].text() == "No AI apps found"
        assert not actions[0].isEnabled()
        assert not next(a for a in actions if a.text() == "Disconnect all AI apps").isEnabled()
    finally:
        tray.tray.hide()


# ---------------------------------------------------------------- restart (Q6)
class ScriptedRunner:
    """Answers "is Claude running?" from a list; records every command."""

    def __init__(self, running: list[bool], windows: bool = False) -> None:
        self.running = running
        self.windows = windows
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str], env: Mapping[str, str]) -> CommandResult:
        call = list(args)
        self.calls.append(call)
        if call[0] in ("pgrep", "tasklist"):
            on = self.running.pop(0) if self.running else False
            if self.windows:
                return CommandResult(0, '"claude.exe","123"' if on else "INFO: no tasks")
            return CommandResult(0 if on else 1, "123" if on else "")
        return CommandResult(0)


def test_restart_on_macos(home: Path) -> None:
    runner = ScriptedRunner([True, True, False])
    env = Environment(home=home, platform="darwin", env={}, search_path=[], runner=runner)
    launched: list[list[str]] = []
    ok = restart_claude_desktop(
        env, launch=lambda a: launched.append(list(a)), sleep=lambda s: None
    )
    assert ok
    assert ["osascript", "-e", 'tell application "Claude" to quit'] in runner.calls
    assert launched == [["open", "-a", "Claude"]]


def test_restart_gives_up_if_it_does_not_quit(home: Path) -> None:
    runner = ScriptedRunner([True] * 100)
    env = Environment(home=home, platform="darwin", env={}, search_path=[], runner=runner)
    launched: list[list[str]] = []
    ok = restart_claude_desktop(
        env, launch=lambda a: launched.append(list(a)), sleep=lambda s: None, timeout=2
    )
    assert not ok
    assert launched == []


def test_restart_on_windows(home: Path, tmp_path: Path) -> None:
    local = tmp_path / "local"
    exe = local / "AnthropicClaude" / "claude.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    runner = ScriptedRunner([True, False], windows=True)
    env = Environment(
        home=home, platform="win32", env={"LOCALAPPDATA": str(local)}, search_path=[], runner=runner
    )
    launched: list[list[str]] = []
    assert restart_claude_desktop(
        env, launch=lambda a: launched.append(list(a)), sleep=lambda s: None
    )
    assert ["taskkill", "/IM", "claude.exe"] in runner.calls  # a normal close, never /F
    assert launched == [[str(exe)]]


def test_restart_not_possible(home: Path) -> None:
    linux = Environment(home=home, platform="linux", env={}, search_path=[])
    assert restart_claude_desktop(linux) is False
    windows = Environment(home=home, platform="win32", env={"LOCALAPPDATA": str(home)})
    assert restart_claude_desktop(windows) is False  # Claude Desktop not found


def test_http_spec_never_in_results(home: Path, bin_dir: Path) -> None:
    (home / ".gemini").mkdir()
    env = make_env(home, bin_dir, FakeRunner(home))
    inst = Installer(env, lambda t: ServerSpec.http(HTTP_URL, KEY))
    results = inst.connect(["gemini"], transport="http")
    assert KEY not in json.dumps([r.to_dict() for r in results])
