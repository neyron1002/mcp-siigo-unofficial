"""``--selftest``: prove that a build has everything it needs (plan sections 3.2 and 7).

Checks: Qt starts (headless when there is no display) and the tray, dialogs, and
icons can be built; the vault encrypts and decrypts; the MCP server answers
``tools/list``; and, unless ``offline``, HTTPS works (the certificate bundle is
included). It never touches the user's real vault or keychain, and it prints a JSON
report.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp_siigo_unofficial import __version__

HTTPS_PROBE_URL = "https://api.github.com/zen"


def _headless_if_needed() -> None:
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"


def check_qt(workdir: Path) -> dict[str, Any]:
    _headless_if_needed()
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from mcp_siigo_unofficial.app.connect_window import ConnectWindow
    from mcp_siigo_unofficial.app.dialogs import AboutDialog, SettingsDialog, WriteActionsDialog
    from mcp_siigo_unofficial.app.icons import app_icon
    from mcp_siigo_unofficial.app.runtime import AppRuntime
    from mcp_siigo_unofficial.app.tray import TrayController
    from mcp_siigo_unofficial.autostart import LinuxAutostart
    from mcp_siigo_unofficial.clients import Environment
    from mcp_siigo_unofficial.i18n import Translator
    from mcp_siigo_unofficial.vault import MemoryKeyStore

    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication([sys.argv[0]])
    icons_ok = not app_icon().isNull() and not app_icon(write_mode=True).isNull()
    runtime = AppRuntime.open(workdir / "qt-vault.sqlite3", MemoryKeyStore())
    # The Connect window looks at an empty, throwaway home folder: never the user's apps.
    clients_home = workdir / "clients-home"
    clients_home.mkdir(exist_ok=True)
    installer = runtime.client_installer(Environment(home=clients_home, env={}, search_path=[]))
    connect_rows = 0
    try:
        for language in ("en", "es"):
            tr = Translator(language)
            tray = TrayController(
                runtime, tr, LinuxAutostart(workdir / "autostart"), app, installer=installer
            )
            tray.refresh()
            tray._fill_clients_menu()
            window = ConnectWindow(installer, tr)
            window.adjustSize()
            connect_rows = len(window.rows)
            window.deleteLater()
            for dialog in (WriteActionsDialog(tr), SettingsDialog(runtime, tr), AboutDialog(tr)):
                dialog.adjustSize()
                dialog.deleteLater()
            tray.tray.hide()
    finally:
        runtime.shutdown()
    return {
        "platform": app.platformName(),
        "icons": icons_ok,
        "tray_available": QSystemTrayIcon.isSystemTrayAvailable(),
        "connect_window_apps": connect_rows,
    }


def check_vault(workdir: Path) -> dict[str, Any]:
    from mcp_siigo_unofficial.siigo import SiigoCredentials
    from mcp_siigo_unofficial.vault import MemoryKeyStore, Vault

    keystore = MemoryKeyStore()
    path = workdir / "vault.sqlite3"
    creds = SiigoCredentials("selftest@example.com", "selftest-access-key")
    with Vault.open(path, keystore) as vault:
        vault.save_siigo_credentials(creds)
    with Vault.open(path, keystore) as vault:
        ok = vault.load_siigo_credentials() == creds
    raw = path.read_bytes() + (
        Path(f"{path}-wal").read_bytes() if Path(f"{path}-wal").exists() else b""
    )
    return {"round_trip": ok, "encrypted": b"selftest-access-key" not in raw}


def check_mcp() -> dict[str, Any]:
    import anyio
    from mcp import Client

    from mcp_siigo_unofficial.server.app import build_server
    from mcp_siigo_unofficial.server.write_gate import WriteSwitch
    from mcp_siigo_unofficial.siigo import SiigoClient

    async def run() -> int:
        async with SiigoClient(lambda: None) as siigo:
            server = build_server(siigo, WriteSwitch())
            async with Client(server) as client:
                return len((await client.list_tools()).tools)

    return {"tools": anyio.run(run)}


def check_https(url: str = HTTPS_PROBE_URL) -> dict[str, Any]:
    import httpx2

    response = httpx2.get(
        url, timeout=20.0, headers={"User-Agent": f"mcp-siigo-unofficial/{__version__}"}
    )
    return {"url": url, "status": response.status_code}


def run_selftest(*, offline: bool = False) -> int:
    report: dict[str, Any] = {"version": __version__, "checks": {}}
    ok = True
    with tempfile.TemporaryDirectory(prefix="mcp-siigo-selftest-") as tmp:
        workdir = Path(tmp)
        os.environ["MCP_SIIGO_UNOFFICIAL_HOME"] = str(workdir / "home")
        checks: list[tuple[str, Callable[[], dict[str, Any]]]] = [
            ("vault", lambda: check_vault(workdir)),
            ("mcp", check_mcp),
            ("qt", lambda: check_qt(workdir)),
        ]
        if not offline:
            checks.append(("https", check_https))
        for name, check in checks:
            started = time.perf_counter()
            try:
                result = check()
                passed = _passed(name, result)
            except Exception as exc:
                result = {"error": f"{type(exc).__name__}: {exc}"}
                passed = False
            result["ok"] = passed
            result["seconds"] = round(time.perf_counter() - started, 3)
            report["checks"][name] = result
            ok = ok and passed
    report["ok"] = ok
    if sys.stdout is not None:  # a GUI build started with no stdout
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0 if ok else 1


def _passed(name: str, result: dict[str, Any]) -> bool:
    if name == "vault":
        return bool(result["round_trip"] and result["encrypted"])
    if name == "mcp":
        return int(result["tools"]) > 1
    if name == "qt":
        return bool(result["icons"])
    if name == "https":
        return int(result["status"]) < 500
    return False
