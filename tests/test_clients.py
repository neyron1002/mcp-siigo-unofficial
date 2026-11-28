"""One-click connect, phase 7: detection, connect, disconnect, repair (plan v3).

Every test uses a fake home folder and fake AI app commands; the real user's
settings are never touched.
"""

from __future__ import annotations

import json
import stat
import sys
import tomllib
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from mcp_siigo_unofficial.clients import (
    ALT_SERVER_NAME,
    SERVER_NAME,
    ConfigFileError,
    Entry,
    Environment,
    Installer,
    ServerSpec,
    app_by_id,
    configfiles,
    is_ours,
    matches,
)
from mcp_siigo_unofficial.clients import cli as clients_cli
from mcp_siigo_unofficial.clients.apps import CommandResult
from mcp_siigo_unofficial.clients.specs import Transport

LAUNCHER = ("/home/u/.local/share/mcp-siigo-unofficial/launcher", "--stdio")
MOVED_LAUNCHER = ("/opt/new-place/launcher", "--stdio")
HTTP_URL = "http://127.0.0.1:39217/mcp"
KEY = "test-bearer-key-not-real"
TODAY = date(2026, 11, 19)
OTHER_SERVER = {"command": "python", "args": ["/srv/mcp_siigo/server.py"]}


class FakeRunner:
    """Pretends to be ``claude``/``codex``/``gemini``/``code``.

    ``mode``: ``ok`` changes the settings like the real command, ``noop`` says it
    worked but changes nothing, ``fail`` returns an error.
    """

    def __init__(self, env_home: Path, mode: str = "ok") -> None:
        self.home = env_home
        self.mode = mode
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str], env: Mapping[str, str]) -> CommandResult:
        call = list(args)
        self.calls.append(call)
        if self.mode == "fail":
            return CommandResult(1, "error")
        if self.mode == "noop":
            return CommandResult(0)
        tool = Path(call[0]).stem
        if tool == "claude":
            self._json(self.home / ".claude.json", "mcpServers", call)
        elif tool == "gemini":
            self._json(self.home / ".gemini" / "settings.json", "mcpServers", call)
        elif tool == "codex":
            self._codex(call)
        elif tool == "code":
            payload = json.loads(call[2])
            path = self.home / ".config" / "Code" / "User" / "mcp.json"
            data = configfiles.read_json(path)
            name = payload.pop("name")
            data.setdefault("servers", {})[name] = payload
            configfiles.write_json(path, data)
        return CommandResult(0)

    def _json(self, path: Path, key: str, call: list[str]) -> None:
        data = configfiles.read_json(path)
        servers = data.setdefault(key, {})
        if call[2] == "add":
            name = call[5]
            rest = [a for a in call[6:] if a != "--"]
            servers[name] = {"command": rest[0], "args": rest[1:]}
            if Path(call[0]).stem == "claude":
                servers[name] = {"type": "stdio", **servers[name], "env": {}}
        else:
            servers.pop(call[-1], None)
        configfiles.write_json(path, data)

    def _codex(self, call: list[str]) -> None:
        path = self.home / ".codex" / "config.toml"
        if call[2] == "add":
            sep = call.index("--")
            command = call[sep + 1 :]
            configfiles.edit_toml_table(
                path, "mcp_servers", call[3], {"command": command[0], "args": command[1:]}
            )
        else:
            configfiles.edit_toml_table(path, "mcp_servers", call[3], None)


def norm(calls: list[list[str]]) -> list[list[str]]:
    """Command lines with the executable path in lower case (Windows returns ``.EXE``)."""
    return [[call[0].lower(), *call[1:]] for call in calls]


def make_exe(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name + ".exe" if sys.platform.startswith("win") else name)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


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


def make_env(home: Path, bin_dir: Path, runner: FakeRunner, platform: str = "linux") -> Environment:
    return Environment(home=home, platform=platform, env={}, search_path=[bin_dir], runner=runner)


def specs(transport: Transport) -> ServerSpec:
    return ServerSpec.stdio(LAUNCHER) if transport == "stdio" else ServerSpec.http(HTTP_URL, KEY)


def installer(env: Environment, **kwargs: Any) -> Installer:
    return Installer(env, specs, today=lambda: TODAY, **kwargs)


def claude_json(home: Path) -> dict[str, Any]:
    return json.loads((home / ".claude.json").read_text())


# ---------------------------------------------------------------- specs
@pytest.mark.parametrize(
    ("entry", "ours"),
    [
        (Entry("stdio", LAUNCHER), True),
        (
            Entry(
                "stdio", (r"C:\Users\u\AppData\Local\MCPSiigoUnofficial\launcher.exe", "--stdio")
            ),
            True,
        ),
        (
            Entry(
                "stdio",
                (
                    "/Applications/MCP Siigo Unofficial.app/Contents/MacOS/MCPSiigoUnofficial",
                    "--stdio",
                ),
            ),
            True,
        ),
        (Entry("stdio", ("/usr/bin/python3", "-m", "mcp_siigo_unofficial", "--stdio")), True),
        (Entry("stdio", ("python", "/srv/mcp_siigo/server.py")), False),
        (Entry("stdio", ("/x/launcher", "--serve")), False),
        (Entry("http", url="http://127.0.0.1:39217/mcp"), True),
        (Entry("http", url="http://localhost:40000/mcp/"), True),
        (Entry("http", url="https://mcp.example.com/mcp"), False),
        (Entry(None), False),
    ],
)
def test_is_ours(entry: Entry, ours: bool) -> None:
    assert is_ours(entry) is ours


def test_matches_and_repr_hide_the_key() -> None:
    spec = ServerSpec.http(HTTP_URL, KEY)
    assert matches(spec.as_entry(), spec)
    assert not matches(Entry("http", url=HTTP_URL, authorization="Bearer old"), spec)
    assert KEY not in repr(spec)
    assert KEY not in repr(spec.as_entry())
    with pytest.raises(ValueError, match="command"):
        ServerSpec.stdio([])


# ---------------------------------------------------------------- files
def test_backup_once_per_day(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"a": 1}')
    first = configfiles.backup_once(path, TODAY)
    path.write_text('{"a": 2}')
    again = configfiles.backup_once(path, TODAY)
    assert first == again == tmp_path / "settings.json.siigo-backup-2026-11-19"
    assert json.loads(first.read_text()) == {"a": 1}
    assert configfiles.backup_once(tmp_path / "missing.json", TODAY) is None


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX permissions")
def test_atomic_write_keeps_permissions_and_new_files_are_private(tmp_path: Path) -> None:
    existing = tmp_path / "a.json"
    existing.write_text("{}")
    existing.chmod(0o640)
    configfiles.write_json(existing, {"x": 1})
    assert stat.S_IMODE(existing.stat().st_mode) == 0o640
    new = tmp_path / "sub" / "b.json"
    configfiles.write_json(new, {})
    assert stat.S_IMODE(new.stat().st_mode) == 0o600
    assert not list(tmp_path.glob("**/*.tmp"))


def test_invalid_json_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{ not json")
    with pytest.raises(ConfigFileError, match="not valid JSON"):
        configfiles.read_json(path)
    path.write_text("[1, 2]")
    with pytest.raises(ConfigFileError, match="object"):
        configfiles.read_json(path)


CODEX_TEXT = """# my codex settings
model = "gpt-5"

[mcp_servers.other]
command = "node"
args = ["other.js"]

[mcp_servers.siigo]
command = "/old/launcher"
args = ["--stdio"]

[mcp_servers.siigo.env]
A = "1"

[profiles.fast]
model = "mini"
"""


def test_toml_edit_changes_only_our_table(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(CODEX_TEXT)
    configfiles.edit_toml_table(
        path, "mcp_servers", "siigo", {"command": "/new/launcher", "args": ["--stdio"]}
    )
    text = path.read_text()
    data = tomllib.loads(text)
    assert "# my codex settings" in text
    assert data["mcp_servers"]["siigo"] == {"command": "/new/launcher", "args": ["--stdio"]}
    assert data["mcp_servers"]["other"] == {"command": "node", "args": ["other.js"]}
    assert data["profiles"] == {"fast": {"model": "mini"}}
    configfiles.edit_toml_table(path, "mcp_servers", "siigo", None)
    data = tomllib.loads(path.read_text())
    assert "siigo" not in data["mcp_servers"]
    assert data["model"] == "gpt-5"


def test_toml_inline_definition_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    original = 'mcp_servers = { siigo = { command = "x" } }\n'
    path.write_text(original)
    with pytest.raises(ConfigFileError, match="can't be edited safely"):
        configfiles.edit_toml_table(path, "mcp_servers", "siigo", None)
    assert path.read_text() == original


def test_invalid_toml_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[mcp_servers\n")
    with pytest.raises(ConfigFileError, match="not valid TOML"):
        configfiles.edit_toml_table(path, "mcp_servers", "siigo", {"command": "x"})


# ---------------------------------------------------------------- detection and status
@pytest.mark.parametrize(
    ("platform", "relative"),
    [
        ("darwin", "Library/Application Support/Claude/claude_desktop_config.json"),
        ("win32", "AppData/Roaming/Claude/claude_desktop_config.json"),
    ],
)
def test_claude_desktop_paths(home: Path, bin_dir: Path, platform: str, relative: str) -> None:
    env = make_env(home, bin_dir, FakeRunner(home), platform)
    app = app_by_id("claude-desktop")
    assert app.config_path(env) == home / relative
    assert not app.is_installed(env)
    app.config_path(env).parent.mkdir(parents=True)
    assert app.is_installed(env)


MSIX_FAMILY = "Claude_pzs8sxrjxfjjc"
MSIX_PACKAGE = f"AppData/Local/Packages/{MSIX_FAMILY}"
MSIX_CACHE_DIR = f"{MSIX_PACKAGE}/LocalCache/Roaming/Claude"
MSIX_DATA_DIR = "AppData/Local/Claude-Data/claude_pzs8sxrjxfjjc"
DATA_LEFT = ".user-data-left.claude_pzs8sxrjxfjjc"


def make_windows_desktop(home: Path, install: str) -> Path:
    """Lay out one Windows install type of Claude Desktop; return its settings folder."""
    if install == "classic":
        (home / "AppData/Local/AnthropicClaude").mkdir(parents=True)
        return home / "AppData/Roaming/Claude"
    (home / MSIX_PACKAGE / "LocalState").mkdir(parents=True)
    if install == "msix":
        return home / MSIX_CACHE_DIR
    # msix-data: newer versions moved the settings and left a note in the old folders.
    for old in (home / MSIX_CACHE_DIR, home / "AppData/Roaming/Claude"):
        old.mkdir(parents=True)
        (old / DATA_LEFT).write_text("{}")
    data = home / MSIX_DATA_DIR
    data.mkdir(parents=True)
    return data


@pytest.mark.parametrize("install", ["classic", "msix", "msix-data"])
def test_claude_desktop_windows_install_types(home: Path, bin_dir: Path, install: str) -> None:
    env = make_env(home, bin_dir, FakeRunner(home), "win32")
    app = app_by_id("claude-desktop")
    assert not app.is_installed(env)
    settings_dir = make_windows_desktop(home, install)
    assert app.is_installed(env)
    assert app.config_path(env) == settings_dir / "claude_desktop_config.json"
    [state] = installer(env).status(["claude-desktop"])
    assert state.state == "not_connected"
    assert state.config_path == str(settings_dir / "claude_desktop_config.json")


@pytest.mark.parametrize("install", ["classic", "msix", "msix-data"])
def test_claude_desktop_windows_connect_and_disconnect_keep_other_servers(
    home: Path, bin_dir: Path, install: str
) -> None:
    env = make_env(home, bin_dir, FakeRunner(home), "win32")
    path = make_windows_desktop(home, install) / "claude_desktop_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"preferences": {"x": True}, "mcpServers": {"other": OTHER_SERVER}}))
    inst = installer(env)
    [result] = inst.connect(["claude-desktop"])
    assert result.outcome == "connected"
    data = json.loads(path.read_text())
    assert data["preferences"] == {"x": True}
    assert data["mcpServers"] == {
        "other": OTHER_SERVER,
        "siigo": {"command": LAUNCHER[0], "args": ["--stdio"]},
    }
    [result] = inst.disconnect(["claude-desktop"])
    assert result.outcome == "disconnected"
    data = json.loads(path.read_text())
    assert data == {"preferences": {"x": True}, "mcpServers": {"other": OTHER_SERVER}}
    # Only the file Claude Desktop reads was changed; the old folders keep just their note.
    if install == "msix-data":
        for old in (home / MSIX_CACHE_DIR, home / "AppData/Roaming/Claude"):
            assert [p.name for p in old.iterdir()] == [DATA_LEFT]


def test_claude_desktop_msix_first_connect_creates_the_settings(home: Path, bin_dir: Path) -> None:
    """A freshly installed MSIX package has no settings folder yet: it is created."""
    env = make_env(home, bin_dir, FakeRunner(home), "win32")
    make_windows_desktop(home, "msix")
    [result] = installer(env).connect(["claude-desktop"])
    assert result.outcome == "connected"
    written = json.loads((home / MSIX_CACHE_DIR / "claude_desktop_config.json").read_text())
    assert written["mcpServers"]["siigo"] == {"command": LAUNCHER[0], "args": ["--stdio"]}
    assert not (home / "AppData/Roaming/Claude").exists()


def test_claude_desktop_is_not_offered_on_linux(home: Path, bin_dir: Path) -> None:
    env = make_env(home, bin_dir, FakeRunner(home), "linux")
    (home / ".config" / "Claude").mkdir(parents=True)
    assert not app_by_id("claude-desktop").is_installed(env)


def test_status_of_every_state(home: Path, bin_dir: Path) -> None:
    env = make_env(home, bin_dir, FakeRunner(home))
    make_exe(bin_dir, "claude")
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text(
        '[mcp_servers.siigo]\ncommand = "/old/launcher"\nargs = ["--stdio"]\n'
    )
    (home / ".gemini").mkdir()
    (home / ".gemini" / "settings.json").write_text(
        json.dumps({"mcpServers": {"siigo": OTHER_SERVER}})
    )
    vscode = home / ".config" / "Code" / "User"
    vscode.mkdir(parents=True)
    (vscode / "mcp.json").write_text("{ broken")
    states = {s.id: s for s in installer(env).status()}
    assert states["claude-code"].state == "not_connected"
    assert states["claude-desktop"].state == "not_installed"
    assert states["codex"].state == "needs_repair"
    assert states["codex"].transport == "stdio"
    assert states["gemini"].state == "conflict"
    assert states["vscode"].state == "unreadable"
    assert "not valid JSON" in states["vscode"].detail


def test_hand_made_http_setup_is_recognized(home: Path, bin_dir: Path) -> None:
    """A setup pasted from Copy client setup in v0.1.0 shows as Connected · HTTP (Q2d)."""
    (home / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "siigo": {
                        "type": "http",
                        "url": HTTP_URL,
                        "headers": {"Authorization": f"Bearer {KEY}"},
                    }
                }
            }
        )
    )
    env = make_env(home, bin_dir, FakeRunner(home))
    status = installer(env).status(["claude-code"])[0]
    assert (status.state, status.transport, status.name) == ("connected", "http", "siigo")
    assert KEY not in json.dumps(status.to_dict())


# ---------------------------------------------------------------- connect
def test_connect_uses_the_apps_command_and_keeps_other_settings(home: Path, bin_dir: Path) -> None:
    original = {"theme": "dark", "mcpServers": {"other": {"command": "node", "args": ["x.js"]}}}
    (home / ".claude.json").write_text(json.dumps(original))
    runner = FakeRunner(home)
    exe = make_exe(bin_dir, "claude")
    env = make_env(home, bin_dir, runner)
    [result] = installer(env).connect(["claude-code"])
    assert (result.outcome, result.transport, result.name) == ("connected", "stdio", "siigo")
    assert norm(runner.calls) == [
        [str(exe).lower(), "mcp", "add", "--scope", "user", "siigo", "--", *LAUNCHER]
    ]
    data = claude_json(home)
    assert data["theme"] == "dark"
    assert data["mcpServers"]["other"] == original["mcpServers"]["other"]
    assert data["mcpServers"]["siigo"]["command"] == LAUNCHER[0]
    backup = home / ".claude.json.siigo-backup-2026-11-19"
    assert json.loads(backup.read_text()) == original


@pytest.mark.parametrize("mode", ["noop", "fail"])
def test_command_problems_fall_back_to_a_file_edit(home: Path, bin_dir: Path, mode: str) -> None:
    runner = FakeRunner(home, mode)
    make_exe(bin_dir, "claude")
    env = make_env(home, bin_dir, runner)
    [result] = installer(env).connect(["claude-code"])
    assert result.outcome == "connected"
    assert len(runner.calls) == 1
    assert claude_json(home)["mcpServers"]["siigo"] == {
        "type": "stdio",
        "command": LAUNCHER[0],
        "args": ["--stdio"],
        "env": {},
    }


def test_connect_twice_changes_nothing(home: Path, bin_dir: Path) -> None:
    runner = FakeRunner(home)
    make_exe(bin_dir, "claude")
    env = make_env(home, bin_dir, runner)
    installer(env).connect(["claude-code"])
    before = (home / ".claude.json").read_text()
    runner.calls.clear()
    [result] = installer(env).connect(["claude-code"])
    assert result.outcome == "already_connected"
    assert runner.calls == []
    assert (home / ".claude.json").read_text() == before


def test_not_installed_apps_are_skipped(home: Path, bin_dir: Path) -> None:
    env = make_env(home, bin_dir, FakeRunner(home))
    results = installer(env).connect()
    assert {r.outcome for r in results} == {"not_installed"}
    assert not (home / ".claude.json").exists()


def test_windows_batch_wrappers_are_not_run(
    home: Path, bin_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(home, bin_dir, FakeRunner(home), "win32")
    monkeypatch.setattr(env, "which", lambda name: Path(r"C:\npm\claude.cmd"))
    assert app_by_id("claude-code").cli(env) is None


@pytest.mark.parametrize(
    ("policy", "outcome", "name"),
    [
        ("ask", "conflict", "siigo"),
        ("keep-both", "connected", ALT_SERVER_NAME),
        ("replace", "connected", SERVER_NAME),
    ],
)
def test_name_conflict(home: Path, bin_dir: Path, policy: str, outcome: str, name: str) -> None:
    (home / ".gemini").mkdir()
    path = home / ".gemini" / "settings.json"
    path.write_text(json.dumps({"mcpServers": {"siigo": OTHER_SERVER}}))
    before = path.read_text()
    env = make_env(home, bin_dir, FakeRunner(home))
    [result] = installer(env).connect(["gemini"], on_conflict=policy)  # type: ignore[arg-type]
    assert (result.outcome, result.name) == (outcome, name)
    servers = json.loads(path.read_text())["mcpServers"]
    if policy == "ask":
        assert path.read_text() == before
    elif policy == "keep-both":
        assert servers["siigo"] == OTHER_SERVER
        assert servers[ALT_SERVER_NAME] == {"command": LAUNCHER[0], "args": ["--stdio"]}
    else:
        assert servers["siigo"] == {"command": LAUNCHER[0], "args": ["--stdio"]}


def test_broken_settings_are_not_touched(home: Path, bin_dir: Path) -> None:
    path = home / ".claude.json"
    path.write_text("{ broken")
    env = make_env(home, bin_dir, FakeRunner(home))
    [result] = installer(env).connect(["claude-code"])
    assert result.outcome == "failed"
    assert "not valid JSON" in result.detail
    assert path.read_text() == "{ broken"


def test_http_is_written_to_the_file_never_on_a_command_line(home: Path, bin_dir: Path) -> None:
    runner = FakeRunner(home)
    make_exe(bin_dir, "claude")
    make_exe(bin_dir, "gemini")
    (home / "Library" / "Application Support" / "Claude").mkdir(parents=True)
    env = make_env(home, bin_dir, runner, "darwin")
    results = {r.id: r for r in installer(env).connect(transport="http")}
    assert runner.calls == [] or all(KEY not in " ".join(c) for c in runner.calls)
    assert results["claude-code"].transport == "http"
    assert claude_json(home)["mcpServers"]["siigo"] == {
        "type": "http",
        "url": HTTP_URL,
        "headers": {"Authorization": f"Bearer {KEY}"},
    }
    gemini = json.loads((home / ".gemini" / "settings.json").read_text())["mcpServers"]["siigo"]
    assert gemini == {"httpUrl": HTTP_URL, "headers": {"Authorization": f"Bearer {KEY}"}}
    # Claude Desktop can't use HTTP: it gets stdio (plan Q2b).
    assert results["claude-desktop"].transport == "stdio"
    desktop = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    assert json.loads(desktop.read_text())["mcpServers"]["siigo"] == {
        "command": LAUNCHER[0],
        "args": ["--stdio"],
    }
    assert "Restart Claude Desktop" in results["claude-desktop"].detail


def test_switching_transport_rewrites_our_entry(home: Path, bin_dir: Path) -> None:
    env = make_env(home, bin_dir, FakeRunner(home))
    (home / ".claude").mkdir()
    inst = installer(env)
    inst.connect(["claude-code"], transport="http")
    [result] = inst.connect(["claude-code"], transport="stdio")
    assert result.outcome == "connected"
    assert claude_json(home)["mcpServers"]["siigo"]["command"] == LAUNCHER[0]


def test_codex_file_edit_and_command(home: Path, bin_dir: Path) -> None:
    (home / ".codex").mkdir()
    path = home / ".codex" / "config.toml"
    path.write_text('model = "gpt-5"\n')
    env = make_env(home, bin_dir, FakeRunner(home))
    [result] = installer(env).connect(["codex"])
    assert result.outcome == "connected"
    data = tomllib.loads(path.read_text())
    assert data == {
        "model": "gpt-5",
        "mcp_servers": {"siigo": {"command": LAUNCHER[0], "args": ["--stdio"]}},
    }
    installer(env).disconnect(["codex"])
    assert tomllib.loads(path.read_text()) == {"model": "gpt-5"}
    runner = FakeRunner(home)
    exe = make_exe(bin_dir, "codex")
    env = make_env(home, bin_dir, runner)
    installer(env).connect(["codex"])
    assert norm(runner.calls) == [[str(exe).lower(), "mcp", "add", "siigo", "--", *LAUNCHER]]
    [http] = installer(env).connect(["codex"], transport="http")
    assert http.outcome == "connected"
    assert tomllib.loads(path.read_text())["mcp_servers"]["siigo"] == {
        "url": HTTP_URL,
        "http_headers": {"Authorization": f"Bearer {KEY}"},
    }


def test_vscode_command_and_file(home: Path, bin_dir: Path) -> None:
    runner = FakeRunner(home)
    exe = make_exe(bin_dir, "code")
    env = make_env(home, bin_dir, runner)
    [result] = installer(env).connect(["vscode"])
    assert result.outcome == "connected"
    assert norm(runner.calls)[0][:2] == [str(exe).lower(), "--add-mcp"]
    path = home / ".config" / "Code" / "User" / "mcp.json"
    assert json.loads(path.read_text())["servers"]["siigo"] == {
        "type": "stdio",
        "command": LAUNCHER[0],
        "args": ["--stdio"],
    }
    [gone] = installer(env).disconnect(["vscode"])
    assert gone.outcome == "disconnected"
    assert json.loads(path.read_text())["servers"] == {}


# ---------------------------------------------------------------- disconnect and repair
def test_disconnect_restores_the_original_settings(home: Path, bin_dir: Path) -> None:
    original = {"theme": "dark", "mcpServers": {"other": {"command": "node", "args": ["x.js"]}}}
    (home / ".claude.json").write_text(json.dumps(original))
    make_exe(bin_dir, "claude")
    env = make_env(home, bin_dir, FakeRunner(home))
    installer(env).connect(["claude-code"])
    [result] = installer(env).disconnect(["claude-code"])
    assert result.outcome == "disconnected"
    assert claude_json(home) == original
    [again] = installer(env).disconnect(["claude-code"])
    assert again.outcome == "not_connected"


def test_disconnect_never_removes_another_programs_server(home: Path, bin_dir: Path) -> None:
    (home / ".gemini").mkdir()
    path = home / ".gemini" / "settings.json"
    path.write_text(json.dumps({"mcpServers": {"siigo": OTHER_SERVER}}))
    env = make_env(home, bin_dir, FakeRunner(home))
    [result] = installer(env).disconnect(["gemini"])
    assert result.outcome == "not_connected"
    assert json.loads(path.read_text())["mcpServers"]["siigo"] == OTHER_SERVER


def test_repair_after_the_app_moved(home: Path, bin_dir: Path) -> None:
    """Q14: our entry points to an old launcher path; repair fixes only our entry."""
    (home / ".gemini").mkdir()
    path = home / ".gemini" / "settings.json"
    old = {"command": MOVED_LAUNCHER[0], "args": ["--stdio"]}
    path.write_text(json.dumps({"mcpServers": {ALT_SERVER_NAME: old, "siigo": OTHER_SERVER}}))
    env = make_env(home, bin_dir, FakeRunner(home))
    [result] = installer(env).repair()
    assert (result.id, result.outcome, result.name) == ("gemini", "repaired", ALT_SERVER_NAME)
    servers = json.loads(path.read_text())["mcpServers"]
    assert servers[ALT_SERVER_NAME] == {"command": LAUNCHER[0], "args": ["--stdio"]}
    assert servers["siigo"] == OTHER_SERVER
    assert installer(env).repair() == []


# ---------------------------------------------------------------- command line
def test_command_line_list_and_connect(
    home: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(clients_cli, "stdio_spec", lambda: ServerSpec.stdio(LAUNCHER))
    (home / ".gemini").mkdir()
    env = make_env(home, bin_dir, FakeRunner(home))
    assert clients_cli.run("connect", clients=["gemini"], env=env) == clients_cli.EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["results"][0]["outcome"] == "connected"
    assert clients_cli.run("list", env=env) == clients_cli.EXIT_OK
    listed = {c["id"]: c["state"] for c in json.loads(capsys.readouterr().out)["clients"]}
    assert listed["gemini"] == "connected"
    (home / ".gemini" / "settings.json").write_text(
        json.dumps({"mcpServers": {"siigo": OTHER_SERVER}})
    )
    assert clients_cli.run("connect", clients=["gemini"], env=env) == clients_cli.EXIT_CONFLICT
    capsys.readouterr()
    assert clients_cli.run("connect", clients=["nope"], env=env) == 2


def test_main_parses_the_client_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_siigo_unofficial import __main__ as entry

    seen: dict[str, Any] = {}

    def fake_run(action: str, **kwargs: Any) -> int:
        seen.update(action=action, **kwargs)
        return 0

    monkeypatch.setattr(clients_cli, "run", fake_run)
    code = entry.main(
        [
            "--connect-clients",
            "--client",
            "codex",
            "--client",
            "gemini",
            "--transport",
            "http",
            "--on-conflict",
            "keep-both",
        ]
    )
    assert code == 0
    assert seen == {
        "action": "connect",
        "clients": ["codex", "gemini"],
        "transport": "http",
        "on_conflict": "keep-both",
    }


def test_environment_search_path_includes_usual_folders(home: Path) -> None:
    env = Environment(
        home=home, platform="darwin", env={"PATH": "/a", "MCP_SIIGO_UNOFFICIAL_NO_LOGIN_SHELL": "1"}
    )
    dirs = env.dirs()
    assert dirs[0] == Path("/a")
    assert home / ".local" / "bin" in dirs
    assert Path("/opt/homebrew/bin") in dirs
    assert env.command_env()["PATH"].split(":")[0] == "/a" or sys.platform.startswith("win")
