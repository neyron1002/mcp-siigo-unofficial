"""Single-file launcher: install, versions, run, and uninstall (plan section 3)."""

from __future__ import annotations

import io
import json
import lzma
import os
import sys
import tarfile
from pathlib import Path

import pytest

from mcp_siigo_unofficial.autostart import LAUNCHER_ENV, launch_command
from mcp_siigo_unofficial.launcher import core
from mcp_siigo_unofficial.launcher.core import (
    CORE_NAME,
    MANIFEST_NAME,
    PAYLOAD_NAME,
    LauncherError,
    Layout,
    Manifest,
    install_payload,
    sha256_file,
)

POSIX_ONLY = pytest.mark.skipif(sys.platform.startswith("win"), reason="shell script app")
APP_SCRIPT = (
    "#!/bin/sh\n"
    'printf "%s|%s|%s\\n" "$*" "$MCP_SIIGO_UNOFFICIAL_LAUNCHER" "$PYINSTALLER_RESET_ENVIRONMENT"'
    ' > "$(dirname "$0")/ran.txt"\n'
)


def make_payload(tmp: Path, version: str, *, extra: dict[str, bytes] | None = None) -> Path:
    """A fake release payload: a tiny 'app' script plus files, in a tar.xz."""
    source = tmp / f"source-{version}"
    source.mkdir(parents=True)
    members = {"app": APP_SCRIPT.encode(), "_internal/data.txt": b"data", **(extra or {})}
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o755 if name == "app" else 0o644
            archive.addfile(info, io.BytesIO(content))
    (source / PAYLOAD_NAME).write_bytes(lzma.compress(raw.getvalue()))
    Manifest(version, sha256_file(source / PAYLOAD_NAME), "app").dump(source / MANIFEST_NAME)
    (source / CORE_NAME).write_bytes(b"core launcher " + version.encode())
    return source


@pytest.fixture
def layout(tmp_path: Path) -> Layout:
    return Layout(tmp_path / "home")


def test_install_creates_the_layout(tmp_path: Path, layout: Layout) -> None:
    source = make_payload(tmp_path, "1.0.0")
    assert install_payload(source, layout, source / CORE_NAME) == "1.0.0"
    assert layout.current_version() == "1.0.0"
    assert layout.previous_version() is None
    assert layout.is_installed("1.0.0")
    assert (layout.version_dir("1.0.0") / "_internal" / "data.txt").read_bytes() == b"data"
    assert layout.launcher.read_bytes() == b"core launcher 1.0.0"
    assert layout.app_exe("1.0.0") == layout.version_dir("1.0.0") / "app"
    if not sys.platform.startswith("win"):
        assert os.access(layout.app_exe("1.0.0"), os.X_OK)
        assert os.access(layout.launcher, os.X_OK)
    # Installing the same version again changes nothing.
    assert install_payload(source, layout) == "1.0.0"
    assert layout.previous_version() is None


def test_versions_keep_current_and_previous(tmp_path: Path, layout: Layout) -> None:
    for version in ("1.0.0", "1.1.0", "1.2.0"):
        install_payload(make_payload(tmp_path, version), layout)
    assert layout.current_version() == "1.2.0"
    assert layout.previous_version() == "1.1.0"
    assert sorted(p.name for p in layout.versions.iterdir()) == ["1.1.0", "1.2.0"]


def test_damaged_payload_is_rejected(tmp_path: Path, layout: Layout) -> None:
    source = make_payload(tmp_path, "1.0.0")
    with (source / PAYLOAD_NAME).open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(LauncherError, match="SHA-256"):
        install_payload(source, layout)
    assert layout.current_version() is None


def test_path_traversal_in_payload_is_blocked(tmp_path: Path, layout: Layout) -> None:
    source = make_payload(tmp_path, "1.0.0", extra={"../escape.txt": b"x"})
    with pytest.raises(tarfile.OutsideDestinationError):
        install_payload(source, layout)
    assert not (layout.versions / "escape.txt").exists()
    assert layout.current_version() is None


def test_missing_app_executable(tmp_path: Path, layout: Layout) -> None:
    source = make_payload(tmp_path, "1.0.0")
    Manifest("1.0.0", sha256_file(source / PAYLOAD_NAME), "nope").dump(source / MANIFEST_NAME)
    with pytest.raises(LauncherError, match="no app executable"):
        install_payload(source, layout)


def test_run_without_install(layout: Layout) -> None:
    with pytest.raises(LauncherError, match="not installed"):
        core.run_app(layout, ["--run"], wait=True)


@POSIX_ONLY
def test_run_app_passes_the_launcher_path(tmp_path: Path, layout: Layout) -> None:
    install_payload(make_payload(tmp_path, "1.0.0"), layout)
    assert core.run_app(layout, ["--stdio"], wait=True) == 0
    ran = (layout.version_dir("1.0.0") / "ran.txt").read_text().strip()
    assert ran == f"--stdio|{layout.launcher}|1"


@POSIX_ONLY
def test_main_installs_from_the_bundle_and_runs(
    tmp_path: Path, layout: Layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_payload(tmp_path, "2.0.0")
    monkeypatch.setattr(core, "bundle_dir", lambda: source)
    monkeypatch.setattr(core, "Layout", lambda: layout)
    assert core.main(["--selftest", "--offline"]) == 0
    assert layout.current_version() == "2.0.0"
    ran = (layout.version_dir("2.0.0") / "ran.txt").read_text()
    assert ran.startswith("--selftest --offline|")


def test_main_version_and_errors(
    tmp_path: Path,
    layout: Layout,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(core, "Layout", lambda: layout)
    monkeypatch.setattr(core, "bundle_dir", lambda: None)
    assert core.main(["--version"]) == 0
    assert "not installed" in capsys.readouterr().out
    assert core.main(["--run"]) == 1
    assert "not installed" in capsys.readouterr().err
    monkeypatch.setattr(core, "bundle_dir", lambda: make_payload(tmp_path, "3.0.0"))
    assert core.main(["--version"]) == 0
    assert "3.0.0" in capsys.readouterr().out


def test_uninstall(tmp_path: Path, layout: Layout, monkeypatch: pytest.MonkeyPatch) -> None:
    install_payload(make_payload(tmp_path, "1.0.0"), layout, tmp_path / "source-1.0.0" / CORE_NAME)
    disabled: list[bool] = []

    class FakeAutostart:
        def disable(self) -> None:
            disabled.append(True)

    monkeypatch.setattr("mcp_siigo_unofficial.autostart.for_platform", lambda: FakeAutostart())
    assert core.uninstall(layout, purge_data=False) == 0
    assert disabled == [True]
    assert not layout.versions.exists()
    assert not layout.launcher.exists()
    assert layout.current_version() is None


def test_manifest_round_trip(tmp_path: Path) -> None:
    manifest = Manifest("1.2.3-rc.1", "ab" * 32, "MCPSiigoUnofficial.exe")
    manifest.dump(tmp_path / "m.json")
    assert Manifest.load(tmp_path / "m.json") == manifest
    assert json.loads((tmp_path / "m.json").read_text())["version"] == "1.2.3-rc.1"


def test_launch_and_stdio_commands_use_the_installed_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_siigo_unofficial.app.client_setup import stdio_command

    monkeypatch.setenv(LAUNCHER_ENV, "/home/u/.local/share/mcp-siigo-unofficial/launcher")
    assert launch_command() == ["/home/u/.local/share/mcp-siigo-unofficial/launcher", "--run"]
    assert stdio_command() == ["/home/u/.local/share/mcp-siigo-unofficial/launcher", "--stdio"]


def test_run_app_passes_its_own_streams(
    tmp_path: Path, layout: Layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GUI launcher on Windows must hand its pipes to the app explicitly."""
    install_payload(make_payload(tmp_path, "1.0.0"), layout)
    seen: dict[str, object] = {}

    class Done:
        returncode = 0

    def fake_run(command: list[str], **kwargs: object) -> Done:
        seen.update(kwargs)
        return Done()

    stdin = open(os.devnull, encoding="utf-8")  # noqa: SIM115 - closed below
    try:
        monkeypatch.setattr(sys, "stdin", stdin)
        monkeypatch.setattr(sys, "stdout", None)  # no stdout at all: inherit the default
        monkeypatch.setattr(core.subprocess, "run", fake_run)
        assert core.run_app(layout, ["--stdio"], wait=True) == 0
    finally:
        stdin.close()
    assert seen["stdin"] is stdin
    assert seen["stdout"] is None
    assert "stderr" in seen
