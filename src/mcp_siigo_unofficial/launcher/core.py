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
- ``--update --wait-pid <pid> [--no-start]``: used by the app's updater. Wait for the
  old app to exit, extract this version beside the old one, run its ``--selftest``,
  and only then make it current and start it. If the self-test fails, delete the new
  version and keep the old one (rollback);
- ``--update-now``: passed to the app (check, download, verify, and update; for CI);
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
import time
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
UPDATE_RESULT_NAME = "update-result.json"
UPDATE_LOG_NAME = "update.log"
SELFTEST_TIMEOUT = 300.0


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


def extract_version(source: Path, layout: Layout) -> Manifest:
    """Verify the payload in ``source`` and extract it into ``versions/<version>``.

    The current version does not change. Extraction goes to a ``.partial`` folder
    that is renamed at the end, so a crash never leaves a half-installed version.
    """
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
            shutil.rmtree(partial, ignore_errors=True)
            raise LauncherError(f"The payload has no app executable at {manifest.app_exe}.")
        if not _WINDOWS:
            app_exe.chmod(app_exe.stat().st_mode | 0o755)
        manifest.dump(partial / MANIFEST_NAME)
        shutil.rmtree(target, ignore_errors=True)
        os.replace(partial, target)
    return manifest


def install_core_launcher(core_launcher: Path | None, layout: Layout, attempts: int = 20) -> None:
    """Copy the small launcher to its installed place (retry while it is still running)."""
    if core_launcher is None or not core_launcher.is_file():
        return
    tmp = layout.launcher.with_name(layout.launcher.name + ".new")
    shutil.copy2(core_launcher, tmp)
    if not _WINDOWS:
        tmp.chmod(tmp.stat().st_mode | 0o755)
    for attempt in range(attempts):
        try:
            os.replace(tmp, layout.launcher)
            return
        except PermissionError:  # Windows: the installed launcher is still running
            if attempt + 1 < attempts:
                time.sleep(0.5)
    tmp.unlink(missing_ok=True)


def activate(version: str, layout: Layout, core_launcher: Path | None) -> None:
    install_core_launcher(core_launcher, layout)
    layout.set_current(version)
    layout.prune()


def install_payload(source: Path, layout: Layout, core_launcher: Path | None = None) -> str:
    """Verify and extract the payload in ``source``; make it the current version."""
    manifest = extract_version(source, layout)
    activate(manifest.version, layout, core_launcher)
    return manifest.version


def wait_for_pid(pid: int, timeout: float = 120.0) -> bool:
    """Wait until process ``pid`` has exited. True if it did within ``timeout``."""
    deadline = time.monotonic() + timeout
    if _WINDOWS:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
        synchronize = 0x00100000
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return True  # no such process (already gone)
        try:
            wait_object_0 = 0
            result = kernel32.WaitForSingleObject(handle, int(timeout * 1000))
            return bool(result == wait_object_0)
        finally:
            kernel32.CloseHandle(handle)
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass  # exists, owned by someone else
        time.sleep(0.2)
    return False


def write_update_result(root: Path, *, old: str | None, new: str, ok: bool, detail: str) -> None:
    """Leave the outcome for the app, which shows it once on its next start."""
    root.mkdir(parents=True, exist_ok=True)
    data = {"from": old, "to": new, "ok": ok, "detail": detail, "time": int(time.time())}
    (root / UPDATE_RESULT_NAME).write_text(json.dumps(data) + "\n", encoding="utf-8")


def run_selftest(exe: Path, env: dict[str, str], log: Path) -> bool:
    """Run ``exe --selftest --offline`` and append its output to ``log``."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"\n== {time.strftime('%Y-%m-%d %H:%M:%S')} self-test of {exe}\n")
        handle.flush()
        try:
            result = subprocess.run(  # noqa: S603
                [str(exe), "--selftest", "--offline"],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=handle,
                timeout=SELFTEST_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            handle.write(f"self-test could not run: {exc}\n")
            return False
        handle.write(f"exit code {result.returncode}\n")
        return result.returncode == 0


def update(layout: Layout, source: Path, *, wait_pid: int | None, start: bool) -> int:
    """``--update``: install the payload in ``source`` with a self-test and rollback."""
    manifest = Manifest.load(source / MANIFEST_NAME)
    old = layout.current_version()
    if wait_pid is not None and not wait_for_pid(wait_pid):
        raise LauncherError(f"The running app (process {wait_pid}) did not exit; update stopped.")
    new_was_installed = layout.is_installed(manifest.version)
    try:
        extract_version(source, layout)
        passed = run_selftest(
            layout.app_exe(manifest.version),
            child_environment(layout),
            layout.root / UPDATE_LOG_NAME,
        )
    except (LauncherError, OSError, tarfile.TarError) as exc:
        passed, detail = False, str(exc)
    else:
        detail = "self-test passed" if passed else f"self-test failed (see {UPDATE_LOG_NAME})"
    if not passed:
        # Rollback: the old version stays current; remove what this update added.
        if not new_was_installed and manifest.version != old:
            shutil.rmtree(layout.version_dir(manifest.version), ignore_errors=True)
        write_update_result(layout.root, old=old, new=manifest.version, ok=False, detail=detail)
        if start and old and layout.is_installed(old):
            run_app(layout, ["--run"], wait=False)
        return 1
    activate(manifest.version, layout, source / CORE_NAME)
    write_update_result(layout.root, old=old, new=manifest.version, ok=True, detail=detail)
    if start:
        run_app(layout, ["--run"], wait=False)
    return 0


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


def _option_value(args: list[str], name: str) -> str | None:
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    layout = Layout()
    try:
        if "--update" in args:
            source = bundle_dir()
            if source is None or not (source / PAYLOAD_NAME).is_file():
                raise LauncherError("--update needs the downloaded file, which has the payload.")
            pid = _option_value(args, "--wait-pid")
            return update(
                layout,
                source,
                wait_pid=int(pid) if pid is not None else None,
                start="--no-start" not in args,
            )
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
        if "--update-now" in args:
            return run_app(layout, ["--update-now"], wait=True)
        return run_app(layout, ["--run"], wait=False)
    except (LauncherError, OSError, ValueError, KeyError) as exc:
        _report(f"MCP Siigo Unofficial: {exc}")
        return 1
