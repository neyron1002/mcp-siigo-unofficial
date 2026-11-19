"""The app core without Qt: vault, write switch, Siigo client, and the MCP HTTP server.

The tray (``app/tray.py``) drives it from the Qt main thread; the MCP server runs on
its own thread (plan section 4).
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from pathlib import Path

import httpx2
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp_siigo_unofficial.app.client_setup import ClientSetup, build_setups
from mcp_siigo_unofficial.paths import vault_path
from mcp_siigo_unofficial.server.app import SiigoMCPServer, build_server
from mcp_siigo_unofficial.server.approval import (
    APPROVE_PATH,
    PREAPPROVED_PATH,
    SETTING_APPROVAL_MODE,
    ApprovalBroker,
    ApprovalMode,
    ApprovalRequest,
    LocalApprover,
    Outcome,
)
from mcp_siigo_unofficial.server.transport import (
    DEFAULT_PORT,
    HOST,
    SETTING_PORT,
    HttpServerThread,
    ensure_bearer_key,
    port_is_free,
)
from mcp_siigo_unofficial.server.write_gate import WriteSwitch
from mcp_siigo_unofficial.siigo import DEFAULT_BASE_URL, SiigoClient, SiigoCredentials, SiigoError
from mcp_siigo_unofficial.vault import KeyringKeyStore, KeyStore, Vault

log = logging.getLogger(__name__)

#: Development/CI override of the Siigo base URL (for the mock Siigo API).
BASE_URL_ENV = "MCP_SIIGO_UNOFFICIAL_SIIGO_BASE_URL"
SHOW_PATH = "/app/show"


def siigo_base_url() -> str:
    return os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL


class AppRuntime:
    """Owns the long-lived objects of the tray app."""

    def __init__(self, vault: Vault) -> None:
        self.vault = vault
        self.write_switch = WriteSwitch(vault)
        self.write_switch.reset_at_start()  # plan P9: off at every start
        self.siigo = SiigoClient(vault.load_siigo_credentials, base_url=siigo_base_url())
        self.approvals = ApprovalBroker()
        self.approvals.on_event = vault.add_event
        self.write_switch.add_listener(self._on_write_switch)
        self.server: SiigoMCPServer = build_server(
            self.siigo,
            self.write_switch,
            vault=vault,
            approver=LocalApprover(self.approvals),
            approval_mode=self.approval_mode,
        )
        self.bearer_key = ensure_bearer_key(vault)
        self.port = int(vault.get_setting(SETTING_PORT, DEFAULT_PORT))
        self.http: HttpServerThread | None = None
        self.server_error: str | None = None
        self.on_show_requested: Callable[[], None] | None = None
        self._register_show_route()
        self._register_approve_route()

    @classmethod
    def open(cls, path: Path | None = None, keystore: KeyStore | None = None) -> AppRuntime:
        return cls(Vault.open(path or vault_path(), keystore or KeyringKeyStore()))

    # ------------------------------------------------------------------ MCP server
    def _register_show_route(self) -> None:
        runtime = self

        @self.server.custom_route(SHOW_PATH, methods=["POST"])  # type: ignore[untyped-decorator]
        async def show(request: Request) -> Response:
            callback = runtime.on_show_requested
            if callback is not None:
                callback()
            return JSONResponse({"shown": callback is not None})

    def _register_approve_route(self) -> None:
        """Private route for ``--stdio`` servers: show the approval window here.

        Protected by the bearer key like ``/mcp``. The answer is the outcome only.
        """
        runtime = self

        @self.server.custom_route(APPROVE_PATH, methods=["POST"])  # type: ignore[untyped-decorator]
        async def approve(request: Request) -> Response:
            try:
                approval = ApprovalRequest.from_json(await request.json())
            except (ValueError, KeyError, TypeError):
                return JSONResponse({"error": "bad_request"}, status_code=400)
            if not runtime.write_switch.enabled:
                return JSONResponse({"outcome": Outcome.UNAVAILABLE.value})
            outcome = await runtime.approvals.request(approval)
            return JSONResponse({"outcome": outcome.value})

        @self.server.custom_route(PREAPPROVED_PATH, methods=["POST"])  # type: ignore[untyped-decorator]
        async def preapproved(request: Request) -> Response:
            try:
                approval = ApprovalRequest.from_json(await request.json())
            except (ValueError, KeyError, TypeError):
                return JSONResponse({"error": "bad_request"}, status_code=400)
            if not runtime.write_switch.enabled:
                return JSONResponse({"outcome": None})
            early = runtime.approvals.preapproved(approval)
            return JSONResponse({"outcome": None if early is None else early.value})

    def _on_write_switch(self, enabled: bool) -> None:
        if not enabled:  # grants and automatic approval end when write actions turn off
            self.approvals.stop_grants()
            self.approvals.stop_automatic("write_actions_off")

    # ------------------------------------------------------------------ approval mode
    def approval_mode(self) -> ApprovalMode:
        return ApprovalMode.parse(self.vault.get_setting(SETTING_APPROVAL_MODE))

    def set_approval_mode(self, mode: ApprovalMode) -> None:
        """Only the Settings dialog calls this (W8: never an MCP tool)."""
        if mode is self.approval_mode():
            return
        self.vault.set_setting(SETTING_APPROVAL_MODE, mode.value)
        self.vault.add_event("write_approval.mode_changed", {"mode": mode.value})

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}/mcp"

    @property
    def server_running(self) -> bool:
        return self.http is not None and self.http.running

    def start_server(self) -> bool:
        """Start the MCP HTTP server. False (with ``server_error``) if it cannot start."""
        if self.server_running:
            return True
        self.http = HttpServerThread(self.server, self.bearer_key, port=self.port)
        try:
            self.http.start()
        except (OSError, RuntimeError, TimeoutError) as exc:
            self.server_error = str(exc)
            self.http = None
            log.error("MCP server did not start: %s", exc)
            return False
        self.server_error = None
        return True

    def ask_running_instance_to_show(self, timeout: float = 3.0) -> bool:
        """If another copy of this app owns the port, ask it to show itself."""
        if port_is_free(self.port):
            return False
        try:
            response = httpx2.post(
                f"http://{HOST}:{self.port}{SHOW_PATH}",
                headers={"Authorization": f"Bearer {self.bearer_key}"},
                timeout=timeout,
            )
        except httpx2.HTTPError:
            return False
        return response.status_code == 200

    def set_port(self, port: int) -> None:
        if not 1024 <= port <= 65535:
            raise ValueError("The port must be between 1024 and 65535.")
        self.vault.set_setting(SETTING_PORT, port)

    # ------------------------------------------------------------------ Siigo
    def credentials(self) -> SiigoCredentials | None:
        return self.vault.load_siigo_credentials()

    def save_credentials(self, credentials: SiigoCredentials) -> None:
        self.vault.save_siigo_credentials(credentials)
        self.siigo.invalidate_token()

    def clear_credentials(self) -> None:
        self.vault.clear_siigo_credentials()
        self.siigo.invalidate_token()

    def test_credentials(self, credentials: SiigoCredentials) -> str | None:
        """Authenticate with Siigo using ``credentials``. None on success, else an error.

        Blocking: call it from a worker thread.
        """

        async def attempt() -> None:
            async with SiigoClient(lambda: credentials, base_url=siigo_base_url()) as client:
                await client.authenticate()

        try:
            asyncio.run(attempt())
        except SiigoError as exc:
            return exc.message
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
        return None

    def client_setups(self) -> list[ClientSetup]:
        return build_setups(self.url, self.bearer_key)

    # ------------------------------------------------------------------ shutdown
    def shutdown(self) -> None:
        """Turn writes off (P9), stop the server, and close the vault."""
        try:
            self.approvals.stop_automatic("app_quit")
            self.write_switch.reset_at_start()
        finally:
            if self.http is not None:
                self.http.stop()
                self.http = None
            self.vault.close()
