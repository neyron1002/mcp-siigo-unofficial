"""Command-line entry point. In phase 0 it only prints the version."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from mcp_siigo_unofficial import __version__

APP_NAME = "MCP Siigo Unofficial"


def main(argv: Sequence[str] | None = None) -> int:
    """Print the application name and version, then exit with code 0."""
    del argv  # Command-line options arrive in later phases.
    sys.stdout.write(f"{APP_NAME} {__version__}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
