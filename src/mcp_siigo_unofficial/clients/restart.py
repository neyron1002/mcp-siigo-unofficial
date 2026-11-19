"""Restart Claude Desktop so it reads its new settings (one-click plan v3, Q6).

Only when the user clicks "Restart Claude Desktop". Claude Desktop is asked to quit
normally (never killed), then opened again. If it can't be done, the caller tells
the user to quit and reopen it by hand.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from mcp_siigo_unofficial.clients.apps import CommandResult, Environment

Launcher = Callable[[Sequence[str]], None]
QUIT_TIMEOUT_S = 15.0


def _launch_detached(args: Sequence[str]) -> None:
    subprocess.Popen(  # noqa: S603 - fixed program paths, no shell
        list(args),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def windows_executable(env: Environment) -> Path | None:
    """Claude Desktop's per-user install on Windows, if present."""
    candidates = [
        env.localappdata() / "AnthropicClaude" / "claude.exe",
        env.localappdata() / "AnthropicClaude" / "Claude.exe",
        env.localappdata() / "Programs" / "Claude" / "Claude.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


def restart_claude_desktop(
    env: Environment,
    *,
    launch: Launcher = _launch_detached,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = QUIT_TIMEOUT_S,
) -> bool:
    """Quit Claude Desktop normally and open it again. True if both steps worked."""
    if env.macos:
        return _restart_macos(env, launch, sleep, timeout)
    if env.windows:
        return _restart_windows(env, launch, sleep, timeout)
    return False  # there is no official Claude Desktop for Linux


def _running(env: Environment, check: Sequence[str]) -> bool:
    result: CommandResult = env.runner(check, env.command_env())
    return result.returncode == 0 and bool(result.output.strip())


def _wait_until_closed(
    env: Environment, check: Sequence[str], sleep: Callable[[float], None], timeout: float
) -> bool:
    waited = 0.0
    while _running(env, check):
        if waited >= timeout:
            return False
        sleep(0.5)
        waited += 0.5
    return True


def _restart_macos(
    env: Environment, launch: Launcher, sleep: Callable[[float], None], timeout: float
) -> bool:
    check = ["pgrep", "-x", "Claude"]
    if _running(env, check):
        env.runner(["osascript", "-e", 'tell application "Claude" to quit'], env.command_env())
        if not _wait_until_closed(env, check, sleep, timeout):
            return False
    try:
        launch(["open", "-a", "Claude"])
    except OSError:
        return False
    return True


def _restart_windows(
    env: Environment, launch: Launcher, sleep: Callable[[float], None], timeout: float
) -> bool:
    exe = windows_executable(env)
    if exe is None:
        return False
    check = ["tasklist", "/FI", "IMAGENAME eq claude.exe", "/NH", "/FO", "CSV"]
    if _windows_running(env, check):
        env.runner(["taskkill", "/IM", "claude.exe"], env.command_env())  # asks it to close
        waited = 0.0
        while _windows_running(env, check):
            if waited >= timeout:
                return False
            sleep(0.5)
            waited += 0.5
    try:
        launch([str(exe)])
    except OSError:
        return False
    return True


def _windows_running(env: Environment, check: Sequence[str]) -> bool:
    result = env.runner(check, env.command_env())
    return result.returncode == 0 and "claude.exe" in result.output.lower()
