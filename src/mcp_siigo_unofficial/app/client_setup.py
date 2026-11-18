""" "Copy client setup" snippets for each AI client (plan section 4).

HTTP clients get the local URL and the bearer key. Clients that start the server
themselves get the ``--stdio`` command. The texts are only put on the clipboard
when the user asks; they are never logged.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from mcp_siigo_unofficial.autostart import LAUNCHER_ENV

SERVER_ID = "siigo"


@dataclass(frozen=True)
class ClientSetup:
    key: str
    label: str
    text: str


def stdio_command() -> list[str]:
    """Command that starts the MCP server over stdio."""
    launcher = os.environ.get(LAUNCHER_ENV)
    if launcher:
        return [launcher, "--stdio"]
    if getattr(sys, "frozen", False):
        return [sys.executable, "--stdio"]
    return [sys.executable, "-m", "mcp_siigo_unofficial", "--stdio"]


def _shell_join(parts: Sequence[str], platform: str = sys.platform) -> str:
    """Quote a command for the user's shell (cmd.exe on Windows, POSIX elsewhere)."""
    if platform.startswith("win"):
        return subprocess.list2cmdline(list(parts))
    return " ".join(shlex.quote(p) for p in parts)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_setups(
    url: str, bearer_key: str, command: Sequence[str] | None = None
) -> list[ClientSetup]:
    cmd = list(command or stdio_command())
    auth = f"Bearer {bearer_key}"
    claude_code = _shell_join(
        [
            "claude",
            "mcp",
            "add",
            "--transport",
            "http",
            SERVER_ID,
            url,
            "--header",
            f"Authorization: {auth}",
        ]
    )
    claude_desktop = json.dumps(
        {"mcpServers": {SERVER_ID: {"command": cmd[0], "args": cmd[1:]}}}, indent=2
    )
    codex = "\n".join(
        [
            f"[mcp_servers.{SERVER_ID}]",
            f"command = {_toml_string(cmd[0])}",
            "args = [" + ", ".join(_toml_string(a) for a in cmd[1:]) + "]",
        ]
    )
    copilot = json.dumps(
        {"servers": {SERVER_ID: {"type": "http", "url": url, "headers": {"Authorization": auth}}}},
        indent=2,
    )
    gemini = json.dumps(
        {"mcpServers": {SERVER_ID: {"httpUrl": url, "headers": {"Authorization": auth}}}},
        indent=2,
    )
    return [
        ClientSetup("claude_code", "Claude Code", claude_code),
        ClientSetup(
            "claude_desktop", "Claude Desktop (claude_desktop_config.json)", claude_desktop
        ),
        ClientSetup("codex", "Codex (~/.codex/config.toml)", codex),
        ClientSetup("copilot", "GitHub Copilot in VS Code (.vscode/mcp.json)", copilot),
        ClientSetup("gemini", "Gemini CLI (~/.gemini/settings.json)", gemini),
    ]
