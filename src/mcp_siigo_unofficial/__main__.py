"""Command-line entry point.

- (no option) or ``--run``: start the tray app.
- ``--version``: print the version.
- ``--selftest``: check that this build works (``--offline`` skips the HTTPS check).
- ``--stdio``: MCP server over stdin/stdout (for clients that start the server
  themselves, such as Claude Desktop). Write actions follow the tray app's switch.
- ``--update-now``: check GitHub for a newer release, download it, verify its
  signature, and start the installer (no tray; used by CI and by scripts).
- ``--list-clients``, ``--connect-clients``, ``--disconnect-clients``,
  ``--repair-clients``: connect the Siigo server to AI apps (one-click plan v3);
  ``--client NAME`` (repeatable), ``--transport stdio|http``, ``--on-conflict``.
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
from types import TracebackType
from typing import TYPE_CHECKING

import anyio

from mcp_siigo_unofficial import __version__

if TYPE_CHECKING:
    from mcp_siigo_unofficial.server.app import SiigoMCPServer
    from mcp_siigo_unofficial.vault import Vault

APP_NAME = "MCP Siigo Unofficial"
#: Development/CI override of the Siigo base URL (for the mock Siigo API).
BASE_URL_ENV = "MCP_SIIGO_UNOFFICIAL_SIIGO_BASE_URL"
#: Size limit of the log file of a build with no console (one older file is kept).
LOG_MAX_BYTES = 1_000_000
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging() -> None:
    """Send warnings to stderr, or to a log file when the app has no console.

    A Windows window build (PyInstaller ``console=False``) opened from Explorer or
    at login has ``sys.stdout`` and ``sys.stderr`` set to ``None``. Code that prints
    or checks for a terminal then fails, so the missing streams point to
    ``os.devnull``, and logs and uncaught errors go to a small file in the data folder.
    """
    no_console = sys.stderr is None
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            # Kept open for the life of the process.
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115
    if not no_console:
        logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
        return

    from logging.handlers import RotatingFileHandler

    from mcp_siigo_unofficial.paths import log_path

    path = log_path()
    handler: logging.Handler
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=LOG_MAX_BYTES, backupCount=1, encoding="utf-8", delay=True
        )
    except OSError:
        handler = logging.StreamHandler(sys.stderr)  # os.devnull: nowhere to write
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)

    previous = sys.excepthook

    def log_uncaught(
        kind: type[BaseException], value: BaseException, tb: TracebackType | None
    ) -> None:
        logging.getLogger("mcp_siigo_unofficial").critical(
            "Uncaught error", exc_info=(kind, value, tb)
        )
        previous(kind, value, tb)

    sys.excepthook = log_uncaught


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcp-siigo-unofficial", description=APP_NAME)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--version", action="store_true", help="print the version and exit")
    mode.add_argument("--stdio", action="store_true", help="run the MCP server over stdio")
    mode.add_argument("--serve", action="store_true", help="run the MCP HTTP server headless")
    mode.add_argument("--run", action="store_true", help="start the tray app (used at login)")
    mode.add_argument("--selftest", action="store_true", help="check that this build works")
    parser.add_argument("--offline", action="store_true", help="--selftest without HTTPS")
    mode.add_argument("--purge-data", action="store_true", help=argparse.SUPPRESS)
    mode.add_argument(
        "--update-now", action="store_true", help="download and install a newer release"
    )
    # macOS updater internals (the staged new .app replaces the old one).
    mode.add_argument("--apply-update", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--wait-pid", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--target", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--from-version", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--no-start", action="store_true", help=argparse.SUPPRESS)
    clients = parser.add_argument_group("AI apps (one-click connect)")
    mode.add_argument(
        "--list-clients", action="store_true", help="show the AI apps and their state"
    )
    mode.add_argument(
        "--connect-clients", action="store_true", help="add the Siigo server to AI apps"
    )
    mode.add_argument(
        "--disconnect-clients", action="store_true", help="remove the Siigo server from AI apps"
    )
    mode.add_argument(
        "--repair-clients", action="store_true", help="fix our entries after the app moved"
    )
    clients.add_argument(
        "--client",
        action="append",
        default=None,
        metavar="NAME",
        help="claude-code, claude-desktop, codex, gemini, or vscode (default: all)",
    )
    clients.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    clients.add_argument(
        "--on-conflict",
        choices=("ask", "keep-both", "replace"),
        default="ask",
        help='what to do when another program already uses the name "siigo"',
    )
    parser.add_argument("--port", type=int, default=None, help="HTTP port (with --serve)")
    return parser


def _open_runtime(*, follow_vault: bool) -> tuple[Vault, SiigoMCPServer]:
    from mcp_siigo_unofficial.paths import vault_path
    from mcp_siigo_unofficial.server.app import build_server
    from mcp_siigo_unofficial.server.write_gate import WriteSwitch
    from mcp_siigo_unofficial.siigo import DEFAULT_BASE_URL, SiigoClient
    from mcp_siigo_unofficial.vault import KeyringKeyStore, Vault, VaultTokenStore

    vault = Vault.open(vault_path(), KeyringKeyStore())
    switch = WriteSwitch(vault, follow_vault=follow_vault)
    if not follow_vault:
        switch.reset_at_start()
    base_url = os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL
    siigo = SiigoClient(
        vault.load_siigo_credentials, base_url=base_url, token_store=VaultTokenStore(vault)
    )
    # stdio: approvals are shown by the running tray app. --serve (headless): no
    # window exists, and the switch is always off there anyway.
    from mcp_siigo_unofficial.server.approval import SETTING_APPROVAL_MODE, ApprovalMode

    approver = None
    if follow_vault:
        from mcp_siigo_unofficial.server.transport import tray_approver

        approver = tray_approver(vault)
    return vault, build_server(
        siigo,
        switch,
        vault=vault,
        approver=approver,
        approval_mode=lambda: ApprovalMode.parse(vault.get_setting(SETTING_APPROVAL_MODE)),
    )


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


def _purge_data() -> int:
    """Delete the vault and its keychain key (used by ``launcher --uninstall --purge-data``)."""
    from pathlib import Path

    from mcp_siigo_unofficial.paths import vault_path
    from mcp_siigo_unofficial.vault import KeyringKeyStore, KeyStoreError

    path = vault_path()
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    try:
        KeyringKeyStore().delete()
    except KeyStoreError as exc:
        sys.stderr.write(f"Could not delete the keychain key: {exc}\n")
        return 1
    return 0


def _update_now() -> int:
    """Headless update: check, download, verify, and hand over to the installer."""
    from mcp_siigo_unofficial.update.apply import (
        can_self_update,
        clean_downloads,
        downloads_dir,
        start_update,
    )
    from mcp_siigo_unofficial.update.releases import (
        UpdateError,
        check_for_update,
        download_update,
    )

    try:
        release = check_for_update()
        if release is None:
            sys.stdout.write(f"{APP_NAME} {__version__} is up to date.\n")
            return 0
        if not can_self_update():
            sys.stderr.write(f"{release.version} is available: {release.page_url}\n")
            return 1
        clean_downloads()
        path = download_update(release, downloads_dir())
        start_update(path, pid=os.getpid(), start_app=False)
    except UpdateError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    sys.stdout.write(f"Updating {__version__} -> {release.version} (signature verified).\n")
    return 0


def _apply_update(args: argparse.Namespace) -> int:
    from pathlib import Path

    from mcp_siigo_unofficial.update.apply import apply_macos_update, current_bundle

    staged = current_bundle()
    if staged is None or not args.target:
        sys.stderr.write("--apply-update runs only inside a staged macOS app.\n")
        return 2
    return apply_macos_update(
        staged,
        Path(args.target),
        wait_pid=args.wait_pid,
        start=not args.no_start,
        old=args.from_version,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line. Without options, start the tray app."""
    args = _parser().parse_args(list(argv) if argv is not None else None)
    setup_logging()
    if args.stdio:
        return _stdio()
    if args.serve:
        return _serve(args.port)
    if args.selftest:
        from mcp_siigo_unofficial.selftest import run_selftest

        return run_selftest(offline=args.offline)
    if args.purge_data:
        return _purge_data()
    if args.update_now:
        return _update_now()
    if args.apply_update:
        return _apply_update(args)
    for action in ("list", "connect", "disconnect", "repair"):
        if getattr(args, f"{action}_clients"):
            from mcp_siigo_unofficial.clients.cli import run as run_clients

            return run_clients(
                action,
                clients=args.client,
                transport=args.transport,
                on_conflict=args.on_conflict,
            )
    if args.version:
        sys.stdout.write(f"{APP_NAME} {__version__}\n")
        return 0
    from mcp_siigo_unofficial.app.main import run_app

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
