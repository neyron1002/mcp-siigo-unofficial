"""PyInstaller entry point for the app (tray, --stdio, --selftest, ...)."""

import sys

from mcp_siigo_unofficial.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
