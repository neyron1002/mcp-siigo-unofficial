"""End-to-end update test (plan phase 5): install an older release, update it from GitHub.

1. Install the ``--from`` release file into a clean temporary home (on macOS: copy
   the ``.app`` out of the DMG into a temporary Applications folder).
2. Run ``--update-now``: the app asks GitHub for the newest release, downloads it,
   verifies its Ed25519 signature and SHA-256, and starts the installer.
3. Wait for the version switch to ``--expect``; check the previous version was kept,
   the update result says the self-test passed, and the new version's self-test passes.

Usage (CI, after both releases are published)::

    uv run python packaging/update_test.py <from file> --expect 0.1.0-rc.2
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from smoke_test import check, run

WAIT_SECONDS = 600


def wait_for(condition, what: str) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if condition():
            check(True, what)
            return
        time.sleep(3)
    check(False, f"{what} (waited {WAIT_SECONDS} s)")


def read_json(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def update_launcher(artifact: Path, home: Path, env: dict[str, str], expect: str) -> None:
    if not sys.platform.startswith("win"):
        artifact.chmod(0o755)
    check(
        run([str(artifact), "--selftest", "--offline"], env).returncode == 0, "old release installs"
    )
    old = (home / "current").read_text(encoding="utf-8").strip()
    check(old != expect, f"old version {old} is installed")
    launcher = home / ("launcher.exe" if sys.platform.startswith("win") else "launcher")
    result = run([str(launcher), "--update-now"], env, timeout=WAIT_SECONDS)
    check(
        result.returncode == 0 and "signature verified" in result.stdout, "--update-now starts it"
    )
    current = home / "current"
    wait_for(
        lambda: (
            current.read_text(encoding="utf-8").strip() == expect
            and (home / "update-result.json").is_file()
        ),
        f"the current version switched to {expect}",
    )
    outcome = read_json(home / "update-result.json") or {}
    check(outcome.get("ok") is True and outcome.get("from") == old, f"update result: {outcome}")
    check((home / "previous").read_text(encoding="utf-8").strip() == old, "previous version kept")
    check((home / "versions" / old).is_dir(), "previous version files kept")
    result = run([str(launcher), "--selftest", "--offline"], env)
    check(result.returncode == 0 and f'"version": "{expect}"' in result.stdout, "new version runs")


def update_macos(
    artifact: Path, workdir: Path, home: Path, env: dict[str, str], expect: str
) -> None:
    mount = workdir / "mnt"
    mount.mkdir()
    check(
        run(
            [
                "hdiutil",
                "attach",
                "-nobrowse",
                "-readonly",
                "-mountpoint",
                str(mount),
                str(artifact),
            ],
            env,
        ).returncode
        == 0,
        "old DMG mounts",
    )
    try:
        app = next(mount.glob("*.app"))
        installed = workdir / "Applications" / app.name
        installed.parent.mkdir()
        run(["ditto", str(app), str(installed)], env)
    finally:
        run(["hdiutil", "detach", str(mount)], env)
    exe = installed / "Contents" / "MacOS" / "MCPSiigoUnofficial"
    result = run([str(exe), "--update-now"], env, timeout=WAIT_SECONDS)
    check(
        result.returncode == 0 and "signature verified" in result.stdout, "--update-now starts it"
    )

    def switched() -> bool:
        if not (home / "update-result.json").is_file():
            return False
        version = run([str(exe), "--version"], env, timeout=60)
        return version.returncode == 0 and version.stdout.strip().endswith(expect)

    wait_for(switched, f"the .app was replaced by {expect}")
    outcome = read_json(home / "update-result.json") or {}
    check(outcome.get("ok") is True, f"update result: {outcome}")
    check((home / "previous-app" / installed.name).is_dir(), "previous .app kept")
    check(run([str(exe), "--selftest", "--offline"], env).returncode == 0, "new version runs")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("artifact", type=Path, help="the older release file")
    parser.add_argument("--expect", required=True, help="the version the update must reach")
    args = parser.parse_args()
    workdir = Path(tempfile.mkdtemp(prefix="mcp-siigo-update-"))
    home = workdir / "home"
    env = {
        **os.environ,
        "MCP_SIIGO_UNOFFICIAL_HOME": str(home),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
    }
    try:
        if args.artifact.suffix == ".dmg":
            update_macos(args.artifact.resolve(), workdir, home, env, args.expect)
        else:
            update_launcher(args.artifact.resolve(), home, env, args.expect)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print("UPDATE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
