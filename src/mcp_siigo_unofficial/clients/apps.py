"""The AI apps the installer knows: where they keep settings, and how to find them.

Each app is described by a small adapter: how to tell that it is installed, where
its user-level settings file is, how a server entry looks in that file, and (when
the app has one) the command that adds or removes a server (plan Q5: the app's own
command first, a careful file edit otherwise).

Verified on 2026-11-19: ``claude mcp add/remove`` (Claude Code 2.1.327). The
commands of Codex, Gemini CLI, and VS Code follow their documentation; every
command's result is checked by reading the file back, and a file edit is used when
the check fails, so a changed command format can't leave a wrong entry.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp_siigo_unofficial.clients import configfiles
from mcp_siigo_unofficial.clients.specs import SERVER_NAMES, Entry, ServerSpec

CLI_TIMEOUT_S = 60.0
LOGIN_SHELL_TIMEOUT_S = 5.0
#: Set to skip asking the login shell for its PATH (tests and CI).
NO_LOGIN_SHELL_ENV = "MCP_SIIGO_UNOFFICIAL_NO_LOGIN_SHELL"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str = ""


Runner = Callable[[Sequence[str], Mapping[str, str]], CommandResult]


def run_command(args: Sequence[str], env: Mapping[str, str]) -> CommandResult:
    """Run an AI app's command line with a time limit. Output is kept for messages only."""
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argument lists, no shell
            list(args),
            env=dict(env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return CommandResult(127, f"{type(exc).__name__}")
    return CommandResult(completed.returncode, (completed.stdout + completed.stderr)[-2000:])


def _login_shell_path(env: Mapping[str, str]) -> list[str]:
    """The PATH of the user's login shell (macOS apps don't get the terminal's PATH)."""
    shell = env.get("SHELL") or "/bin/zsh"
    try:
        completed = subprocess.run(  # noqa: S603 - the user's own shell, fixed command
            [shell, "-ilc", 'printf "%s" "$PATH"'],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=LOGIN_SHELL_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    return [p for p in completed.stdout.strip().split(":") if p]


@dataclass
class Environment:
    """Where to look: the user's home folder, the system, and how to run commands."""

    home: Path
    platform: str = sys.platform
    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    #: Folders searched for commands; ``None`` builds the list (PATH + usual folders).
    search_path: list[Path] | None = None
    runner: Runner = run_command

    @classmethod
    def current(cls) -> Environment:
        return cls(home=Path.home())

    @property
    def windows(self) -> bool:
        return self.platform.startswith("win")

    @property
    def macos(self) -> bool:
        return self.platform == "darwin"

    def appdata(self) -> Path:
        return Path(self.env.get("APPDATA") or self.home / "AppData" / "Roaming")

    def localappdata(self) -> Path:
        return Path(self.env.get("LOCALAPPDATA") or self.home / "AppData" / "Local")

    def xdg_config(self) -> Path:
        return Path(self.env.get("XDG_CONFIG_HOME") or self.home / ".config")

    def app_support(self) -> Path:
        return self.home / "Library" / "Application Support"

    def dirs(self) -> list[Path]:
        if self.search_path is None:
            self.search_path = self._build_search_path()
        return self.search_path

    def _build_search_path(self) -> list[Path]:
        raw = [p for p in self.env.get("PATH", "").split(os.pathsep) if p]
        if self.macos and not self.env.get(NO_LOGIN_SHELL_ENV):
            raw += _login_shell_path(self.env)
        extra = [
            self.home / ".local" / "bin",
            self.home / ".claude" / "local",
            self.home / ".npm-global" / "bin",
            self.home / ".volta" / "bin",
            self.home / ".bun" / "bin",
        ]
        if self.windows:
            extra += [
                self.appdata() / "npm",
                self.localappdata() / "Programs" / "Microsoft VS Code" / "bin",
            ]
        else:
            extra += [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/usr/bin")]
        if self.macos:
            extra.append(Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin"))
        seen: set[str] = set()
        result: list[Path] = []
        for item in [Path(p) for p in raw] + extra:
            key = str(item)
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    def which(self, name: str) -> Path | None:
        found = shutil.which(name, path=os.pathsep.join(str(d) for d in self.dirs()))
        return Path(found) if found else None

    def command_env(self) -> dict[str, str]:
        """Environment for an AI app's command: the full search path (npm CLIs need node)."""
        env = dict(self.env)
        env["PATH"] = os.pathsep.join(str(d) for d in self.dirs())
        return env


class ClientApp:
    """One AI app. Subclasses fill in the details."""

    id: str = ""
    label: str = ""
    cli_name: str | None = None
    supports_http: bool = True
    #: The app reads its settings only at start, so it must be restarted after a change.
    needs_restart: bool = False

    def config_path(self, env: Environment) -> Path:
        raise NotImplementedError

    def install_markers(self, env: Environment) -> list[Path]:
        """Folders or files whose presence shows that the app is installed."""
        return []

    def is_available(self, env: Environment) -> bool:
        """False on systems where the app doesn't exist (Claude Desktop on Linux)."""
        return True

    def cli(self, env: Environment) -> Path | None:
        """The app's command line, if found and safe to run with arguments."""
        if not self.cli_name:
            return None
        found = env.which(self.cli_name)
        # Windows batch wrappers (.cmd/.bat) re-parse arguments; edit the file instead.
        if found is None or found.suffix.lower() in {".cmd", ".bat"}:
            return None
        return found

    def is_installed(self, env: Environment) -> bool:
        if not self.is_available(env):
            return False
        if self.cli_name and env.which(self.cli_name) is not None:
            return True
        return any(marker.exists() for marker in self.install_markers(env))

    # -- settings file -------------------------------------------------------------
    def read_entries(self, env: Environment) -> dict[str, Entry]:
        """Our candidate entries (``siigo``, ``siigo-unofficial``) found in the settings."""
        raise NotImplementedError

    def write_entry(self, env: Environment, name: str, spec: ServerSpec) -> None:
        raise NotImplementedError

    def remove_entry(self, env: Environment, name: str) -> None:
        raise NotImplementedError

    # -- command line (stdio only: an HTTP key never goes on a command line) --------
    def cli_add_args(self, exe: Path, name: str, spec: ServerSpec) -> list[str] | None:
        return None

    def cli_remove_args(self, exe: Path, name: str) -> list[str] | None:
        return None


class JsonClientApp(ClientApp):
    """An app whose settings are a JSON object with a servers object inside."""

    section = "mcpServers"

    def stdio_json(self, spec: ServerSpec) -> dict[str, Any]:
        return {"command": spec.command[0], "args": list(spec.command[1:])}

    def http_json(self, spec: ServerSpec) -> dict[str, Any]:
        return {"type": "http", "url": spec.url, "headers": {"Authorization": spec.authorization}}

    def url_key(self, raw: Mapping[str, Any]) -> str:
        return str(raw.get("url") or "")

    def to_entry(self, raw: Any) -> Entry:
        if not isinstance(raw, Mapping):
            return Entry(None)
        command = raw.get("command")
        if isinstance(command, str) and command:
            args = raw.get("args") or []
            if not isinstance(args, list):
                return Entry(None)
            return Entry("stdio", (command, *(str(a) for a in args)))
        url = self.url_key(raw)
        if url:
            headers = raw.get("headers") or {}
            auth = ""
            if isinstance(headers, Mapping):
                for key, value in headers.items():
                    if str(key).lower() == "authorization":
                        auth = str(value)
            return Entry("http", url=url, authorization=auth)
        return Entry(None)

    def _load(self, env: Environment) -> tuple[Path, dict[str, Any], dict[str, Any]]:
        path = self.config_path(env)
        data = configfiles.read_json(path)
        return path, data, configfiles.json_section(data, self.section, path)

    def read_entries(self, env: Environment) -> dict[str, Entry]:
        _path, _data, servers = self._load(env)
        return {name: self.to_entry(servers[name]) for name in SERVER_NAMES if name in servers}

    def write_entry(self, env: Environment, name: str, spec: ServerSpec) -> None:
        path, data, servers = self._load(env)
        servers = dict(servers)
        servers[name] = self.stdio_json(spec) if spec.transport == "stdio" else self.http_json(spec)
        data[self.section] = servers
        configfiles.write_json(path, data)

    def remove_entry(self, env: Environment, name: str) -> None:
        path, data, servers = self._load(env)
        if name not in servers:
            return
        servers = dict(servers)
        del servers[name]
        data[self.section] = servers
        configfiles.write_json(path, data)


class ClaudeCode(JsonClientApp):
    """Claude Code: terminal, IDE extensions, and Claude Desktop's local Code sessions."""

    id = "claude-code"
    label = "Claude Code"
    cli_name = "claude"

    def config_path(self, env: Environment) -> Path:
        custom = env.env.get("CLAUDE_CONFIG_DIR")
        return Path(custom) / ".claude.json" if custom else env.home / ".claude.json"

    def install_markers(self, env: Environment) -> list[Path]:
        return [env.home / ".claude", self.config_path(env)]

    def stdio_json(self, spec: ServerSpec) -> dict[str, Any]:
        return {"type": "stdio", **super().stdio_json(spec), "env": {}}

    def cli_add_args(self, exe: Path, name: str, spec: ServerSpec) -> list[str] | None:
        if spec.transport != "stdio":
            return None
        return [str(exe), "mcp", "add", "--scope", "user", name, "--", *spec.command]

    def cli_remove_args(self, exe: Path, name: str) -> list[str] | None:
        return [str(exe), "mcp", "remove", "--scope", "user", name]


class ClaudeDesktop(JsonClientApp):
    """Claude Desktop chat. It starts servers itself: stdio only (plan Q2b)."""

    id = "claude-desktop"
    label = "Claude Desktop"
    supports_http = False
    needs_restart = True

    def is_available(self, env: Environment) -> bool:
        return env.windows or env.macos

    def config_dir(self, env: Environment) -> Path:
        if env.windows:
            return env.appdata() / "Claude"
        if env.macos:
            return env.app_support() / "Claude"
        return env.xdg_config() / "Claude"

    def config_path(self, env: Environment) -> Path:
        return self.config_dir(env) / "claude_desktop_config.json"

    def install_markers(self, env: Environment) -> list[Path]:
        markers = [self.config_dir(env)]
        if env.macos:
            markers += [Path("/Applications/Claude.app"), env.home / "Applications" / "Claude.app"]
        if env.windows:
            markers.append(env.localappdata() / "AnthropicClaude")
        return markers


class GeminiCli(JsonClientApp):
    id = "gemini"
    label = "Gemini CLI"
    cli_name = "gemini"

    def config_path(self, env: Environment) -> Path:
        return env.home / ".gemini" / "settings.json"

    def install_markers(self, env: Environment) -> list[Path]:
        return [env.home / ".gemini"]

    def http_json(self, spec: ServerSpec) -> dict[str, Any]:
        return {"httpUrl": spec.url, "headers": {"Authorization": spec.authorization}}

    def url_key(self, raw: Mapping[str, Any]) -> str:
        return str(raw.get("httpUrl") or raw.get("url") or "")

    def cli_add_args(self, exe: Path, name: str, spec: ServerSpec) -> list[str] | None:
        if spec.transport != "stdio":
            return None
        return [
            str(exe),
            "mcp",
            "add",
            "--scope",
            "user",
            name,
            spec.command[0],
            "--",
            *spec.command[1:],
        ]

    def cli_remove_args(self, exe: Path, name: str) -> list[str] | None:
        return [str(exe), "mcp", "remove", "--scope", "user", name]


class VsCode(JsonClientApp):
    """GitHub Copilot in VS Code (user profile ``mcp.json``)."""

    id = "vscode"
    label = "VS Code (GitHub Copilot)"
    cli_name = "code"
    section = "servers"

    def user_dir(self, env: Environment) -> Path:
        if env.windows:
            return env.appdata() / "Code" / "User"
        if env.macos:
            return env.app_support() / "Code" / "User"
        return env.xdg_config() / "Code" / "User"

    def config_path(self, env: Environment) -> Path:
        return self.user_dir(env) / "mcp.json"

    def install_markers(self, env: Environment) -> list[Path]:
        return [self.user_dir(env)]

    def stdio_json(self, spec: ServerSpec) -> dict[str, Any]:
        return {"type": "stdio", **super().stdio_json(spec)}

    def cli_add_args(self, exe: Path, name: str, spec: ServerSpec) -> list[str] | None:
        if spec.transport != "stdio":
            return None
        payload = {"name": name, **self.stdio_json(spec)}
        return [str(exe), "--add-mcp", json.dumps(payload)]


class Codex(ClientApp):
    """Codex CLI and IDE extension (``config.toml``)."""

    id = "codex"
    label = "Codex"
    cli_name = "codex"
    table = "mcp_servers"

    def home_dir(self, env: Environment) -> Path:
        custom = env.env.get("CODEX_HOME")
        return Path(custom) if custom else env.home / ".codex"

    def config_path(self, env: Environment) -> Path:
        return self.home_dir(env) / "config.toml"

    def install_markers(self, env: Environment) -> list[Path]:
        return [self.home_dir(env)]

    def to_entry(self, raw: Any) -> Entry:
        if not isinstance(raw, Mapping):
            return Entry(None)
        command = raw.get("command")
        if isinstance(command, str) and command:
            args = raw.get("args") or []
            if not isinstance(args, list):
                return Entry(None)
            return Entry("stdio", (command, *(str(a) for a in args)))
        url = raw.get("url")
        if isinstance(url, str) and url:
            headers = raw.get("http_headers") or {}
            auth = ""
            if isinstance(headers, Mapping):
                for key, value in headers.items():
                    if str(key).lower() == "authorization":
                        auth = str(value)
            return Entry("http", url=url, authorization=auth)
        return Entry(None)

    def read_entries(self, env: Environment) -> dict[str, Entry]:
        path = self.config_path(env)
        _text, data = configfiles.read_toml(path)
        section = data.get(self.table, {})
        if not isinstance(section, dict):
            raise configfiles.ConfigFileError(f'"{self.table}" in {path} is not a table.')
        return {name: self.to_entry(section[name]) for name in SERVER_NAMES if name in section}

    def write_entry(self, env: Environment, name: str, spec: ServerSpec) -> None:
        if spec.transport == "stdio":
            values: dict[str, Any] = {"command": spec.command[0], "args": list(spec.command[1:])}
        else:
            values = {"url": spec.url, "http_headers": {"Authorization": spec.authorization}}
        configfiles.edit_toml_table(self.config_path(env), self.table, name, values)

    def remove_entry(self, env: Environment, name: str) -> None:
        configfiles.edit_toml_table(self.config_path(env), self.table, name, None)

    def cli_add_args(self, exe: Path, name: str, spec: ServerSpec) -> list[str] | None:
        if spec.transport != "stdio":
            return None
        return [str(exe), "mcp", "add", name, "--", *spec.command]

    def cli_remove_args(self, exe: Path, name: str) -> list[str] | None:
        return [str(exe), "mcp", "remove", name]


ALL_APPS: tuple[ClientApp, ...] = (ClaudeCode(), ClaudeDesktop(), Codex(), GeminiCli(), VsCode())
APP_IDS = tuple(app.id for app in ALL_APPS)


def app_by_id(app_id: str) -> ClientApp:
    for app in ALL_APPS:
        if app.id == app_id:
            return app
    raise KeyError(app_id)
