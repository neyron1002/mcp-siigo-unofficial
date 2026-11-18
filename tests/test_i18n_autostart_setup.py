"""Translations, start at login, and client setup snippets (no Qt needed)."""

from __future__ import annotations

import json
import plistlib
import re
import string
import sys
import tomllib
import uuid
from pathlib import Path

import pytest

from mcp_siigo_unofficial.app.client_setup import build_setups, stdio_command
from mcp_siigo_unofficial.autostart import (
    LinuxAutostart,
    MacAutostart,
    WindowsAutostart,
    for_platform,
    launch_command,
)
from mcp_siigo_unofficial.i18n import LANGUAGES, Translator, all_keys, system_language, text_for


def _fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


@pytest.mark.parametrize("key", all_keys())
def test_every_string_exists_in_both_languages_with_same_placeholders(key: str) -> None:
    texts = [text_for(key, lang) for lang in LANGUAGES]
    assert all(t.strip() for t in texts)
    assert _fields(texts[0]) == _fields(texts[1])


def test_about_text_matches_the_plan() -> None:
    en = text_for("about.body", "en")
    es = text_for("about.body", "es")
    assert "I built it for a friend's company" in en
    assert "the author is not responsible for AI decisions or executions" in en
    assert "Lo construí para la empresa de un amigo" in es
    assert "el autor no responde por las decisiones ni ejecuciones de la IA" in es


@pytest.mark.parametrize(
    ("value", "expected"),
    [("es_CO.UTF-8", "es"), ("es", "es"), ("en_US.UTF-8", "en"), ("fr_FR.UTF-8", "en")],
)
def test_system_language(monkeypatch: pytest.MonkeyPatch, value: str, expected: str) -> None:
    for name in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANG", value)
    assert system_language() == expected


def test_translator_formats_and_switches() -> None:
    tr = Translator("en")
    assert tr("tray.status.running", url="http://x") == "MCP server running at http://x"
    tr.set_language("es")
    assert tr("tray.quit") == "Salir"


def test_linux_autostart(tmp_path: Path) -> None:
    autostart = LinuxAutostart(tmp_path)
    assert not autostart.is_enabled()
    autostart.enable(["/opt/My App/mcp", "--run"])
    assert autostart.is_enabled()
    content = autostart.path.read_text(encoding="utf-8")
    assert "Exec='/opt/My App/mcp' --run" in content
    assert autostart.path == tmp_path / "autostart" / "mcp-siigo-unofficial.desktop"
    autostart.disable()
    autostart.disable()
    assert not autostart.is_enabled()


def test_macos_autostart(tmp_path: Path) -> None:
    autostart = MacAutostart(tmp_path)
    autostart.enable(["/Applications/MCP Siigo Unofficial.app/Contents/MacOS/app", "--run"])
    data = plistlib.loads(autostart.path.read_bytes())
    assert data["ProgramArguments"][-1] == "--run"
    assert data["RunAtLoad"] is True
    assert autostart.path.parent == tmp_path / "Library" / "LaunchAgents"
    autostart.disable()
    assert not autostart.is_enabled()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry")
def test_windows_autostart_registry() -> None:
    autostart = WindowsAutostart(value_name=f"MCPSiigoUnofficialTest{uuid.uuid4().hex[:8]}")
    try:
        autostart.enable([r"C:\Users\A B\AppData\Local\MCPSiigoUnofficial\launcher.exe", "--run"])
        assert autostart.is_enabled()
        assert autostart.command() == (
            r'"C:\Users\A B\AppData\Local\MCPSiigoUnofficial\launcher.exe" --run'
        )
    finally:
        autostart.disable()
    assert not autostart.is_enabled()
    autostart.disable()


def test_platform_selection() -> None:
    assert isinstance(for_platform("win32"), WindowsAutostart)
    assert isinstance(for_platform("darwin"), MacAutostart)
    assert isinstance(for_platform("linux"), LinuxAutostart)
    assert launch_command()[-1] == "mcp_siigo_unofficial"
    assert stdio_command()[-1] == "--stdio"


def test_client_setups() -> None:
    url = "http://127.0.0.1:39217/mcp"
    key = "k" * 43
    setups = {s.key: s for s in build_setups(url, key, ["/opt/app/mcp", "--stdio"])}
    assert set(setups) == {"claude_code", "claude_desktop", "codex", "copilot", "gemini"}
    assert url in setups["claude_code"].text
    assert f"Authorization: Bearer {key}" in setups["claude_code"].text
    desktop = json.loads(setups["claude_desktop"].text)
    assert desktop["mcpServers"]["siigo"] == {"command": "/opt/app/mcp", "args": ["--stdio"]}
    codex = tomllib.loads(setups["codex"].text)
    assert codex["mcp_servers"]["siigo"]["args"] == ["--stdio"]
    copilot = json.loads(setups["copilot"].text)["servers"]["siigo"]
    assert copilot == {"type": "http", "url": url, "headers": {"Authorization": f"Bearer {key}"}}
    gemini = json.loads(setups["gemini"].text)["mcpServers"]["siigo"]
    assert gemini["httpUrl"] == url
    assert re.search(r"Bearer k{43}", setups["gemini"].text)
