"""PyInstaller entry point for the launcher (Windows and Linux)."""

import sys

from mcp_siigo_unofficial.launcher.core import main

if __name__ == "__main__":
    sys.exit(main())
