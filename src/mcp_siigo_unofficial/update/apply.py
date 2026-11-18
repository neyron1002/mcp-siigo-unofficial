"""Hand a verified download over to the installer, then let the app quit (plan section 3).

- Windows and Linux: the downloaded file is a launcher with the new payload inside.
  It is started as ``<file> --update --wait-pid <app pid>``; it waits for this app
  to exit, installs the new version beside the old one, runs its self-test, and
  switches only if the self-test passes (rollback otherwise).
- macOS: the DMG is mounted and the new ``.app`` is copied to a staging folder,
  with the quarantine flag removed (the app downloaded it itself). The staged app
  is started as ``--apply-update --wait-pid <pid> --target <current .app>``: it
  waits, runs its own self-test, moves the current ``.app`` to
  ``<user data>/previous-app/``, and moves itself into place (rollback otherwise).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp_siigo_unofficial.launcher.core import (
    UPDATE_LOG_NAME,
    UPDATE_RESULT_NAME,
    run_selftest,
    wait_for_pid,
    write_update_result,
)
from mcp_siigo_unofficial.paths import data_dir
from mcp_siigo_unofficial.update.releases import UpdateError

MACOS = sys.platform == "darwin"
WINDOWS = sys.platform.startswith("win")


def downloads_dir() -> Path:
    return data_dir() / "downloads"


def can_self_update() -> bool:
    """Only an installed build can replace itself (not a development checkout)."""
    if not getattr(sys, "frozen", False):
        return False
    return current_bundle() is not None if MACOS else True


def current_bundle(executable: str = sys.executable) -> Path | None:
    """macOS: the running ``.app`` folder (``X.app/Contents/MacOS/exe``)."""
    bundle = Path(executable).resolve().parents[2]
    return bundle if bundle.suffix == ".app" else None


def _environment() -> dict[str, str]:
    env = dict(os.environ)
    # A frozen program started by another frozen program must not reuse its
    # parent's PyInstaller environment.
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def _spawn_detached(command: list[str]) -> None:
    common: dict[str, object] = {
        "env": _environment(),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if WINDOWS:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        subprocess.Popen(command, creationflags=flags, **common)  # type: ignore[call-overload]  # noqa: S603
    else:
        subprocess.Popen(command, start_new_session=True, **common)  # type: ignore[call-overload]  # noqa: S603


def start_update(downloaded: Path, *, pid: int, start_app: bool) -> None:
    """Start the installer for ``downloaded``; the caller must then quit the app."""
    extra = [] if start_app else ["--no-start"]
    if not MACOS:
        _spawn_detached([str(downloaded), "--update", "--wait-pid", str(pid), *extra])
        return
    bundle = current_bundle()
    if bundle is None:
        raise UpdateError("This copy of the app is not an installed .app; update it by hand.")
    staged = stage_macos_app(downloaded, data_dir() / "update-staging")
    exe = staged / "Contents" / "MacOS" / Path(sys.executable).name
    from mcp_siigo_unofficial import __version__

    command = [str(exe), "--apply-update", "--wait-pid", str(pid), "--target", str(bundle)]
    _spawn_detached([*command, "--from-version", __version__, *extra])


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise UpdateError(f"{command[0]} failed: {result.stderr.strip() or result.returncode}")


def stage_macos_app(dmg: Path, staging_root: Path) -> Path:
    """Copy the ``.app`` out of ``dmg`` into ``staging_root``; return the staged ``.app``."""
    shutil.rmtree(staging_root, ignore_errors=True)
    staging_root.mkdir(parents=True)
    mount = Path(tempfile.mkdtemp(prefix="mcp-siigo-dmg-"))
    _run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount), str(dmg)])
    try:
        apps = list(mount.glob("*.app"))
        if len(apps) != 1:
            raise UpdateError("The downloaded DMG does not hold exactly one app.")
        staged = staging_root / apps[0].name
        _run(["ditto", str(apps[0]), str(staged)])
    finally:
        subprocess.run(["hdiutil", "detach", str(mount)], capture_output=True, check=False)  # noqa: S603,S607
        shutil.rmtree(mount, ignore_errors=True)
    # The app downloaded this copy itself, so the quarantine flag is not needed.
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(staged)], check=False)  # noqa: S603,S607
    return staged


def apply_macos_update(
    staged: Path,
    target: Path,
    *,
    wait_pid: int | None,
    start: bool,
    old: str | None = None,
    root: Path | None = None,
) -> int:
    """``--apply-update`` (runs inside the staged app): self-test, swap, or roll back."""
    from mcp_siigo_unofficial import __version__

    root = root or data_dir()
    if wait_pid is not None and not wait_for_pid(wait_pid):
        write_update_result(
            root, old=old, new=__version__, ok=False, detail="old app still running"
        )
        return 1
    exe = staged / "Contents" / "MacOS" / Path(sys.executable).name
    if not exe.is_file():
        write_update_result(root, old=old, new=__version__, ok=False, detail=f"missing {exe}")
        return 1
    if not run_selftest(exe, _environment(), root / UPDATE_LOG_NAME):
        write_update_result(
            root, old=old, new=__version__, ok=False, detail=f"self-test failed ({UPDATE_LOG_NAME})"
        )
        if start:
            _open(target)
        return 1
    previous = root / "previous-app" / target.name
    shutil.rmtree(previous.parent, ignore_errors=True)
    previous.parent.mkdir(parents=True)
    shutil.move(str(target), str(previous))
    try:
        shutil.move(str(staged), str(target))
    except OSError as exc:
        shutil.move(str(previous), str(target))  # rollback: put the old app back
        write_update_result(root, old=old, new=__version__, ok=False, detail=str(exc))
        if start:
            _open(target)
        return 1
    write_update_result(root, old=old, new=__version__, ok=True, detail="self-test passed")
    if start:
        _open(target)
    return 0


def _open(bundle: Path) -> None:
    subprocess.run(["open", str(bundle)], check=False)  # noqa: S603,S607


def take_update_result(root: Path | None = None) -> dict[str, object] | None:
    """The outcome of the last update, once (the file is deleted when read)."""
    path = (root or data_dir()) / UPDATE_RESULT_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    path.unlink(missing_ok=True)
    return data if isinstance(data, dict) else None


def clean_downloads() -> None:
    """Remove downloads and staging left from an earlier update."""
    shutil.rmtree(downloads_dir(), ignore_errors=True)
    shutil.rmtree(data_dir() / "update-staging", ignore_errors=True)
