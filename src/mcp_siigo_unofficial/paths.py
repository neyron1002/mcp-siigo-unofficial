"""Per-user folders (plan D9). No administrator rights are needed."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import platformdirs

#: Environment variable that overrides the data folder (tests, self-test, CI).
HOME_ENV = "MCP_SIIGO_UNOFFICIAL_HOME"


def app_dir_name(platform: str = sys.platform) -> str:
    """Folder name: ``MCPSiigoUnofficial`` on Windows and macOS, kebab-case on Linux."""
    if platform.startswith(("win", "darwin")):
        return "MCPSiigoUnofficial"
    return "mcp-siigo-unofficial"


def data_dir() -> Path:
    """Return the per-user data folder, creating nothing.

    Windows ``%LOCALAPPDATA%\\MCPSiigoUnofficial``, macOS
    ``~/Library/Application Support/MCPSiigoUnofficial``, Ubuntu
    ``~/.local/share/mcp-siigo-unofficial``.
    """
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return Path(platformdirs.user_data_dir(app_dir_name(), appauthor=False, roaming=False))


def vault_path() -> Path:
    """Location of the encrypted vault database."""
    return data_dir() / "vault.sqlite3"


def log_path() -> Path:
    """Log file of a build with no console (never holds secrets)."""
    return data_dir() / "logs" / "app.log"
