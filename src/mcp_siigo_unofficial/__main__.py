"""Command-line entry point.

- ``--version``: print the version.
- ``--stdio``: MCP server over stdin/stdout (for clients that start the server
  themselves, such as Claude Desktop). Write actions follow the tray app's switch.
- ``--serve``: headless Streamable HTTP server on 127.0.0.1 (development and CI;
  the tray app in phase 3 runs the same server). Write actions stay off.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from collections.abc import Sequence
from typing import TYPE_CHECKING

import anyio

from mcp_siigo_unofficial import __version__

if TYPE_CHECKING:
    from mcp_siigo_unofficial.server.app import SiigoMCPServer
    from mcp_siigo_unofficial.vault import Vault

APP_NAME = "MCP Siigo Unofficial"
#: Development/CI override of the Siigo base URL (for the mock Siigo API).
BASE_URL_ENV = "MCP_SIIGO_UNOFFICIAL_SIIGO_BASE_URL"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcp-siigo-unofficial", description=APP_NAME)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--version", action="store_true", help="print the version and exit")
    mode.add_argument("--stdio", action="store_true", help="run the MCP server over stdio")
    mode.add_argument("--serve", action="store_true", help="run the MCP HTTP server headless")
    parser.add_argument("--port", type=int, default=None, help="HTTP port (with --serve)")
    return parser


def _open_runtime(*, follow_vault: bool) -> tuple[Vault, SiigoMCPServer]:
    from mcp_siigo_unofficial.paths import vault_path
    from mcp_siigo_unofficial.server.app import build_server
    from mcp_siigo_unofficial.server.write_gate import WriteSwitch
    from mcp_siigo_unofficial.siigo import DEFAULT_BASE_URL, SiigoClient
    from mcp_siigo_unofficial.vault import KeyringKeyStore, Vault

    vault = Vault.open(vault_path(), KeyringKeyStore())
    switch = WriteSwitch(vault, follow_vault=follow_vault)
    if not follow_vault:
        switch.reset_at_start()
    base_url = os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL
    siigo = SiigoClient(vault.load_siigo_credentials, base_url=base_url)
    return vault, build_server(siigo, switch, vault=vault)


def _serve(port: int | None) -> int:
    from mcp_siigo_unofficial.server.transport import (
        DEFAULT_PORT,
        SETTING_PORT,
        HttpServerThread,
        ensure_bearer_key,
    )

    vault, server = _open_runtime(follow_vault=False)
    chosen = port or int(vault.get_setting(SETTING_PORT, DEFAULT_PORT))
    http = HttpServerThread(server, ensure_bearer_key(vault), port=chosen)
    http.start()
    sys.stderr.write(f"{APP_NAME} {__version__}: MCP server at {http.url} (Ctrl+C to stop)\n")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        http.stop()
        vault.close()
    return 0


def _stdio() -> int:
    from mcp_siigo_unofficial.server.transport import run_stdio

    _vault, server = _open_runtime(follow_vault=True)
    anyio.run(run_stdio, server)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line. Without options, print the name and version."""
    args = _parser().parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    if args.stdio:
        return _stdio()
    if args.serve:
        return _serve(args.port)
    sys.stdout.write(f"{APP_NAME} {__version__}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
