"""Install PyInstaller with a bootloader compiled from source (plan section 3).

A locally compiled bootloader reduces antivirus false positives compared with the
prebuilt one. CI only: it clones the PyInstaller release tag that matches the
locked version, builds the bootloader with ``waf``, and installs that tree into the
project environment.

    uv run --group build python packaging/build_bootloader.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import PyInstaller


def run(command: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True, cwd=cwd)  # noqa: S603


def main() -> int:
    version = PyInstaller.__version__
    with tempfile.TemporaryDirectory(prefix="pyinstaller-src-") as tmp:
        source = Path(tmp) / "pyinstaller"
        run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                f"v{version}",
                "https://github.com/pyinstaller/pyinstaller.git",
                str(source),
            ]
        )
        run([sys.executable, "./waf", "all"], cwd=source / "bootloader")
        run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                sys.executable,
                "--reinstall",
                "--no-deps",
                str(source),
            ]
        )
    print(f"PyInstaller {version} installed with a bootloader built from source.")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
