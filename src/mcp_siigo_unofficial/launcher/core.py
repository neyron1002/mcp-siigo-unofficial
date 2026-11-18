"""Single-file launcher: installer, runner, and uninstaller (plan section 3, D8 + D12).

The downloadable file (Windows and Linux) is a PyInstaller one-file program that
carries, as data:

- ``payload.tar.xz``: the full app (a PyInstaller one-folder build), LZMA-compressed;
- ``payload.json``: the manifest (version, SHA-256 of the payload, app executable);
- ``launcher-core[.exe]``: this same launcher without the payload.

Modes:

- default (double-click): install this version if needed, then start the app;
- ``--run``: start the current version with no extraction (start at login);
- ``--stdio``: run the current version as a stdio MCP server;
- ``--selftest``: run the current version's self-test;
- ``--uninstall [--purge-data]``: remove start at login and the installed versions
  (and, with ``--purge-data``, the vault and its keychain key).

Only the standard library and ``platformdirs`` are used here, so the small
installed launcher starts quickly. macOS ships a ``.app`` in a DMG instead
(plan P5), so this module is not used there.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path

from mcp_siigo_unofficial.autostart import LAUNCHER_ENV
from mcp_siigo_unofficial.paths import data_dir

PAYLOAD_NAME = "payload.tar.xz"
MANIFEST_NAME = "payload.json"
_WINDOWS = sys.platform.startswith("win")
EXE_SUFFIX = ".exe" if _WINDOWS else ""
CORE_NAME = f"launcher-core{EXE_SUFFIX}"
INSTALLED_LAUNCHER_NAME = f"launcher{EXE_SUFFIX}"


class LauncherError(Exception):
    """Install or start failed; the message is shown to the user."""


@dataclass(frozen=True)
class Manifest:
    version: str
    sha256: str
    app_exe: str  # path of the app executable inside the version folder (POSIX style)

    @classmethod
    def load(cls, path: Path) -> Manifest:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(str(data["version"]), str(data["sha256"]), str(data["app_exe"]))

    def dump(self, path: Path) -> None:
        payload = {"version": self.version, "sha256": self.sha256, "app_exe": self.app_exe}
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bundle_dir() -> Path | None:
    """Folder with the data files of a frozen one-file program, else None."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else None


class Layout:
    """Per-user install layout (no administrator rights)."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or data_dir()
        self.versions = self.root / "versions"
        self.current_file = self.root / "current"
        self.previous_file = self.root / "previous"
        self.launcher = self.root / INSTALLED_LAUNCHER_NAME

    def _read(self, path: Path) -> str | None:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        return value or None

    def current_version(self) -> str | None:
        return self._read(self.current_file)

    def previous_version(self) -> str | None:
        return self._read(self.previous_file)

    def version_dir(self, version: str) -> Path:
        return self.versions / version

    def is_installed(self, version: str) -> bool:
        return (self.version_dir(version) / MANIFEST_NAME).is_file()

    def app_exe(self, version: str) -> Path:
        manifest = Manifest.load(self.version_dir(version) / MANIFEST_NAME)
        return self.version_dir(version) / manifest.app_exe

    def _write_pointer(self, path: Path, value: str) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(value + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def set_current(self, version: str) -> None:
        old = self.current_version()
        if old and old != version:
            self._write_pointer(self.previous_file, old)
        self._write_pointer(self.current_file, version)

    def prune(self) -> list[str]:
        """Keep the current and previous versions; delete older ones."""
        keep = {v for v in (self.current_version(), self.previous_version()) if v}
        removed = []
        if self.versions.is_dir():
            for child in self.versions.iterdir():
                if child.name not in keep:
                    shutil.rmtree(child, ignore_errors=True)
                    removed.append(child.name)
        return removed


def install_payload(source: Path, layout: Layout, core_launcher: Path | None = None) -> str:
    """Verify and extract the payload in ``source``; make it the current version."""
    manifest = Manifest.load(source / MANIFEST_NAME)
    payload = source / PAYLOAD_NAME
    if sha256_file(payload) != manifest.sha256:
        raise LauncherError("The app payload is damaged (SHA-256 mismatch). Download it again.")
    layout.versions.mkdir(parents=True, exist_ok=True)
    target = layout.version_dir(manifest.version)
    if not layout.is_installed(manifest.version):
        partial = target.with_name(target.name + ".partial")
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        with tarfile.open(payload, "r:xz") as archive:
            archive.extractall(partial, filter="data")
        app_exe = partial / manifest.app_exe
        if not app_exe.is_file():
            raise LauncherError(f"The payload has no app executable at {manifest.app_exe}.")
        if not _WINDOWS:
            app_exe.chmod(app_exe.stat().st_mode | 0o755)
        manifest.dump(partial / MANIFEST_NAME)
        shutil.rmtree(target, ignore_errors=True)
        os.replace(partial, target)
    if core_launcher is not None and core_launcher.is_file():
        tmp = layout.launcher.with_name(layout.launcher.name + ".new")
        shutil.copy2(core_launcher, tmp)
        if not _WINDOWS:
            tmp.chmod(tmp.stat().st_mode | 0o755)
        try:
            os.replace(tmp, layout.launcher)
        except PermissionError:  # Windows: the installed launcher is running (--run)
            tmp.unlink(missing_ok=True)
    layout.set_current(manifest.version)
    layout.prune()
    return manifest.version


def child_environment(layout: Layout) -> dict[str, str]:
    env = dict(os.environ)
    env[LAUNCHER_ENV] = str(layout.launcher)
    # A frozen program started by another frozen program must not reuse its
    # parent's PyInstaller environment (PyInstaller >= 6.10).
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def _usable(stream: object) -> object | None:
    """``stream`` when it has a real file descriptor, else None (inherit the default)."""
    try:
        stream.fileno()  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError):
        return None
    return stream


def inherited_streams() -> dict[str, object | None]:
    """This process's stdin, stdout, and stderr, passed to the app explicitly.

    The launcher has no console on Windows (a GUI program), and Windows does not
    give a GUI child the parent's pipes unless they are passed explicitly. Without
    this, ``--stdio`` and ``--selftest`` would run with no stdin or stdout.
    """
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, OSError, ValueError):
            stream.flush()
    return {
        "stdin": _usable(sys.stdin),
        "stdout": _usable(sys.stdout),
        "stderr": _usable(sys.stderr),
    }


def run_app(layout: Layout, args: list[str], *, wait: bool) -> int:
    version = layout.current_version()
    if version is None or not layout.is_installed(version):
        raise LauncherError("MCP Siigo Unofficial is not installed. Run the downloaded file.")
    command = [str(layout.app_exe(version)), *args]
    env = child_environment(layout)
    if wait:
        streams = inherited_streams()
        completed = subprocess.run(  # noqa: S603
            command,
            env=env,
            check=False,
            stdin=streams["stdin"],  # type: ignore[arg-type]
            stdout=streams["stdout"],  # type: ignore[arg-type]
            stderr=streams["stderr"],  # type: ignore[arg-type]
        )
        return completed.returncode
    if _WINDOWS:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        subprocess.Popen(command, env=env, creationflags=flags, close_fds=True)  # noqa: S603
    else:
        subprocess.Popen(command, env=env, start_new_session=True, close_fds=True)  # noqa: S603
    return 0


def uninstall(layout: Layout, *, purge_data: bool) -> int:
    from mcp_siigo_unofficial.autostart import for_platform

    version = layout.current_version()
    if purge_data and version and layout.is_installed(version):
        run_app(layout, ["--purge-data"], wait=True)
    for_platform().disable()
    shutil.rmtree(layout.versions, ignore_errors=True)
    for path in (layout.current_file, layout.previous_file):
        path.unlink(missing_ok=True)
    # Windows: the running launcher cannot delete itself; it is left for the user.
    with contextlib.suppress(PermissionError):
        layout.launcher.unlink(missing_ok=True)
    return 0


def _report(message: str) -> None:
    """Show an error: stderr when there is one, else a native message box on Windows."""
    if sys.stderr is not None:
        sys.stderr.write(message + "\n")
        return
    if _WINDOWS:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "MCP Siigo Unofficial", 0x10)  # type: ignore[attr-defined,unused-ignore]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    layout = Layout()
    try:
        if "--uninstall" in args:
            return uninstall(layout, purge_data="--purge-data" in args)
        if "--version" in args:
            source = bundle_dir()
            manifest_path = source / MANIFEST_NAME if source else None
            if manifest_path is not None and manifest_path.is_file():
                version = Manifest.load(manifest_path).version
            else:
                version = layout.current_version() or "not installed"
            if sys.stdout is not None:
                sys.stdout.write(f"MCP Siigo Unofficial launcher {version}\n")
            return 0
        source = bundle_dir()
        if source is not None and (source / PAYLOAD_NAME).is_file():
            manifest = Manifest.load(source / MANIFEST_NAME)
            if layout.current_version() != manifest.version or not layout.is_installed(
                manifest.version
            ):
                install_payload(source, layout, source / CORE_NAME)
        if "--stdio" in args:
            return run_app(layout, ["--stdio"], wait=True)
        if "--selftest" in args:
            return run_app(layout, args, wait=True)
        return run_app(layout, ["--run"], wait=False)
    except (LauncherError, OSError, ValueError, KeyError) as exc:
        _report(f"MCP Siigo Unofficial: {exc}")
        return 1
