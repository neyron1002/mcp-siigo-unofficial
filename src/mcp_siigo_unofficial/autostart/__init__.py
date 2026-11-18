"""Start at login (plan D16), per user, with no administrator rights.

- Windows: ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``.
- macOS: ``~/Library/LaunchAgents/<label>.plist`` (loaded by launchd at login).
- Linux: ``$XDG_CONFIG_HOME/autostart/mcp-siigo-unofficial.desktop``.
"""

from __future__ import annotations

import importlib
import os
import plistlib
import shlex
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

APP_ID = "mcp-siigo-unofficial"
WINDOWS_VALUE = "MCPSiigoUnofficial"
MACOS_LABEL = "com.neyron1002.mcp-siigo-unofficial"
SETTING_AUTOSTART_CONFIGURED = "autostart.configured"


class Autostart(Protocol):
    def is_enabled(self) -> bool: ...

    def enable(self, command: Sequence[str]) -> None: ...

    def disable(self) -> None: ...


def _winreg() -> Any:
    """The Windows registry module (imported lazily: it exists only on Windows)."""
    return importlib.import_module("winreg")


def _windows_command_line(command: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(command))


class WindowsAutostart:
    """Run key value in the current user's registry hive."""

    KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def __init__(self, value_name: str = WINDOWS_VALUE) -> None:
        self.value_name = value_name

    def is_enabled(self) -> bool:
        winreg = _winreg()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY) as key:
                winreg.QueryValueEx(key, self.value_name)
        except OSError:
            return False
        return True

    def command(self) -> str | None:
        winreg = _winreg()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY) as key:
                value, _ = winreg.QueryValueEx(key, self.value_name)
        except OSError:
            return None
        return str(value)

    def enable(self, command: Sequence[str]) -> None:
        winreg = _winreg()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.KEY) as key:
            winreg.SetValueEx(
                key, self.value_name, 0, winreg.REG_SZ, _windows_command_line(command)
            )

    def disable(self) -> None:
        winreg = _winreg()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, self.value_name)
        except FileNotFoundError:
            return


class MacAutostart:
    """A per-user LaunchAgent."""

    def __init__(self, home: Path | None = None, label: str = MACOS_LABEL) -> None:
        self.label = label
        self.path = (home or Path.home()) / "Library" / "LaunchAgents" / f"{label}.plist"

    def is_enabled(self) -> bool:
        return self.path.exists()

    def enable(self, command: Sequence[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        plist = {
            "Label": self.label,
            "ProgramArguments": list(command),
            "RunAtLoad": True,
            "ProcessType": "Interactive",
        }
        self.path.write_bytes(plistlib.dumps(plist))

    def disable(self) -> None:
        self.path.unlink(missing_ok=True)


class LinuxAutostart:
    """An XDG autostart desktop entry."""

    def __init__(self, config_home: Path | None = None, app_id: str = APP_ID) -> None:
        base = config_home or Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        self.path = base / "autostart" / f"{app_id}.desktop"

    def is_enabled(self) -> bool:
        return self.path.exists()

    def enable(self, command: Sequence[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exec_line = " ".join(shlex.quote(part) for part in command)
        self.path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=MCP Siigo Unofficial\n"
            "Comment=Unofficial MCP server for the Siigo API\n"
            f"Exec={exec_line}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )

    def disable(self) -> None:
        self.path.unlink(missing_ok=True)


def for_platform(platform: str = sys.platform) -> Autostart:
    if platform.startswith("win"):
        return WindowsAutostart()
    if platform == "darwin":
        return MacAutostart()
    return LinuxAutostart()


def launch_command() -> list[str]:
    """The command that starts the tray app at login.

    A frozen build runs itself with ``--run`` (phase 4 points this to the installed
    launcher). From source, it runs the package with the current interpreter.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run"]
    return [sys.executable, "-m", "mcp_siigo_unofficial"]
