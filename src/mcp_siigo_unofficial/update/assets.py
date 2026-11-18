"""Release file names per operating system (shared by the build and the updater)."""

from __future__ import annotations

import platform
import sys

from mcp_siigo_unofficial import __version__


def target(system: str = sys.platform, machine: str | None = None) -> str:
    """Release target name, for example ``windows-x64`` or ``macos-arm64``."""
    name = "windows" if system.startswith("win") else "macos" if system == "darwin" else "linux"
    raw = (machine if machine is not None else platform.machine()).lower()
    arch = "x64" if raw in {"x86_64", "amd64"} else "arm64" if raw in {"arm64", "aarch64"} else raw
    return f"{name}-{arch}"


def artifact_name(
    version: str = __version__, system: str = sys.platform, machine: str | None = None
) -> str:
    """The downloadable file for ``version`` on this (or the given) system."""
    t = target(system, machine)
    if system.startswith("win"):
        return f"MCPSiigoUnofficial-{version}-{t}.exe"
    if system == "darwin":
        return f"MCPSiigoUnofficial-{version}-{t}.dmg"
    return f"mcp-siigo-unofficial-{version}-{t}"
