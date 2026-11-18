"""Functional proof of a built release file (plan 3.2, item 8).

Installs the file into a clean temporary user folder and checks:

1. the first run installs it (versions/<ver>, the small launcher, ``current``)
   and ``--selftest`` passes there (Qt headless, vault, MCP ``tools/list``, HTTPS);
2. the installed launcher starts the current version with no extraction;
3. ``--stdio`` answers ``tools/list`` to a real MCP client;
4. ``--uninstall`` removes the installed versions.

On macOS it checks the ``.app`` inside the DMG instead.

Usage::

    uv run python packaging/smoke_test.py dist-release/<file> [--offline]
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters

EXPECTED_TOOLS = 46  # 45 read tools + siigo_status, while write actions are off


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"SMOKE TEST FAILED: {message}")
    print(f"ok  {message}", flush=True)


def kill_tree(process: subprocess.Popen[str]) -> None:
    if sys.platform.startswith("win"):
        subprocess.run(  # noqa: S603
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],  # noqa: S607
            capture_output=True,
            check=False,
        )
    else:
        import signal

        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.kill()


def run(
    command: list[str], env: dict[str, str], timeout: float = 300
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    process = subprocess.Popen(  # noqa: S603
        command,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=not sys.platform.startswith("win"),
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Kill the whole tree: the app is a grandchild that holds the pipes open.
        kill_tree(process)
        stdout, stderr = process.communicate(timeout=30)
        stderr += f"\nTIMEOUT after {timeout} s"
    result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    if result.stdout:
        print(result.stdout[-4000:])
    if result.stderr:
        print(result.stderr[-4000:], file=sys.stderr)
    return result


async def list_tools_over_stdio(command: str, args: list[str], env: dict[str, str]) -> int:
    params = StdioServerParameters(command=command, args=args, env=env)
    with anyio.fail_after(120):
        async with Client(params) as client:
            return len((await client.list_tools()).tools)


def smoke_launcher(artifact: Path, home: Path, env: dict[str, str], offline: bool) -> None:
    extra = ["--offline"] if offline else []
    if not sys.platform.startswith("win"):
        artifact.chmod(0o755)
    result = run([str(artifact), "--selftest", *extra], env)
    check(result.returncode == 0, "first run installs the app and --selftest passes")
    current = (home / "current").read_text(encoding="utf-8").strip()
    check((home / "versions" / current / "payload.json").is_file(), f"version {current} installed")
    launcher = home / ("launcher.exe" if sys.platform.startswith("win") else "launcher")
    check(launcher.is_file(), "the small launcher was installed")
    check(
        launcher.stat().st_size < artifact.stat().st_size / 2,
        "the installed launcher does not carry the payload",
    )
    result = run([str(launcher), "--selftest", "--offline"], env)
    check(result.returncode == 0, "the installed launcher runs the current version")
    tools = anyio.run(list_tools_over_stdio, str(launcher), ["--stdio"], env)
    check(tools == EXPECTED_TOOLS, f"--stdio lists {EXPECTED_TOOLS} tools (got {tools})")
    result = run([str(launcher), "--uninstall"], env)
    check(result.returncode == 0, "--uninstall exits cleanly")
    check(not (home / "versions").exists(), "--uninstall removed the versions")


def smoke_macos(artifact: Path, workdir: Path, env: dict[str, str], offline: bool) -> None:
    mount = workdir / "mnt"
    mount.mkdir()
    attached = run(
        ["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount), str(artifact)],
        env,
    )
    check(attached.returncode == 0, "the DMG mounts")
    try:
        apps = list(mount.glob("*.app"))
        check(len(apps) == 1, "the DMG holds one .app")
        check((mount / "Applications").is_symlink(), "the DMG has an Applications shortcut")
        installed = workdir / "Applications" / apps[0].name
        installed.parent.mkdir()
        run(["ditto", str(apps[0]), str(installed)], env)
    finally:
        run(["hdiutil", "detach", str(mount)], env)
    exe = installed / "Contents" / "MacOS" / "MCPSiigoUnofficial"
    extra = ["--offline"] if offline else []
    result = run([str(exe), "--selftest", *extra], env)
    check(result.returncode == 0, "--selftest passes in the copied .app")
    tools = anyio.run(list_tools_over_stdio, str(exe), ["--stdio"], env)
    check(tools == EXPECTED_TOOLS, f"--stdio lists {EXPECTED_TOOLS} tools (got {tools})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--offline", action="store_true", help="skip the HTTPS check")
    args = parser.parse_args()
    artifact: Path = args.artifact.resolve()
    workdir = Path(tempfile.mkdtemp(prefix="mcp-siigo-smoke-"))
    home = workdir / "home"
    env = {
        **os.environ,
        "MCP_SIIGO_UNOFFICIAL_HOME": str(home),
        # The smoke test never touches the runner's real keychain.
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
    }
    try:
        if artifact.suffix == ".dmg":
            smoke_macos(artifact, workdir, env, args.offline)
        else:
            smoke_launcher(artifact, home, env, args.offline)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
