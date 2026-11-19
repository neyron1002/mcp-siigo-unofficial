"""Transports (plan D4): Streamable HTTP on 127.0.0.1 with a bearer key, and stdio.

The HTTP server runs uvicorn on a background thread, so the Qt event loop can keep
the main thread (plan section 4). Requests without the right
``Authorization: Bearer <key>`` header get 401. The SDK's DNS-rebinding protection
is on, because the server binds to 127.0.0.1.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets
import socket
import threading
from typing import Any

import anyio
import uvicorn
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp_siigo_unofficial.server.app import SiigoMCPServer
from mcp_siigo_unofficial.server.approval import RemoteApprover
from mcp_siigo_unofficial.vault import Vault

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
DEFAULT_PORT = 39217
MCP_PATH = "/mcp"
SECRET_BEARER_KEY = "mcp.bearer_key"  # noqa: S105 - vault field name, not a secret
SETTING_PORT = "mcp.port"
STDIO_SWITCH_POLL_S = 2.0


def ensure_bearer_key(vault: Vault) -> str:
    """Return the MCP bearer key from the vault, creating a random one the first time."""
    key = vault.get_secret(SECRET_BEARER_KEY)
    if not key:
        key = secrets.token_urlsafe(32)
        vault.set_secret(SECRET_BEARER_KEY, key)
    return key


def tray_approver(vault: Vault) -> RemoteApprover:
    """Approver for a ``--stdio`` server: the tray app's window, over 127.0.0.1.

    Port and key are read at each write, so a port change in Settings is followed.
    The key is never created here: without it the tray app never ran, so the answer
    is "unavailable".
    """

    def base_url() -> str | None:
        return f"http://{HOST}:{int(vault.get_setting(SETTING_PORT, DEFAULT_PORT))}"

    return RemoteApprover(base_url, lambda: vault.get_secret(SECRET_BEARER_KEY))


class BearerAuthMiddleware:
    """ASGI middleware: every HTTP request needs ``Authorization: Bearer <key>``."""

    def __init__(self, app: ASGIApp, key: str) -> None:
        if len(key) < 16:
            raise ValueError("The bearer key is too short.")
        self.app = app
        self._expected = f"Bearer {key}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            supplied = b""
            for name, value in scope.get("headers", []):
                if name == b"authorization":
                    supplied = value
                    break
            if not hmac.compare_digest(supplied, self._expected):
                body = json.dumps(
                    {"error": "unauthorized", "message": "Missing or wrong bearer key."}
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"www-authenticate", b'Bearer realm="mcp-siigo-unofficial"'),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def build_http_app(server: SiigoMCPServer, bearer_key: str) -> ASGIApp:
    """The Streamable HTTP app at ``/mcp``, protected by the bearer key."""
    app = server.streamable_http_app(streamable_http_path=MCP_PATH, host=HOST)
    return BearerAuthMiddleware(app, bearer_key)


def port_is_free(port: int, host: str = HOST) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


class HttpServerThread:
    """Runs the MCP HTTP server on a background thread."""

    def __init__(
        self, server: SiigoMCPServer, bearer_key: str, *, port: int = DEFAULT_PORT
    ) -> None:
        self.port = port
        config = uvicorn.Config(
            build_http_app(server, bearer_key),
            host=HOST,
            port=port,
            log_level="warning",
            lifespan="on",
            access_log=False,
        )
        self._uvicorn = uvicorn.Server(config)
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}{MCP_PATH}"

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._uvicorn.started

    def _run(self) -> None:
        try:
            asyncio.run(self._uvicorn.serve())
        except BaseException as exc:  # reported by start()
            self._error = exc

    def start(self, timeout: float = 10.0) -> None:
        """Start the server and wait until it accepts connections."""
        if not port_is_free(self.port):
            raise OSError(f"Port {self.port} on {HOST} is already in use.")
        self._thread = threading.Thread(target=self._run, name="mcp-http", daemon=True)
        self._thread.start()
        deadline = threading.Event()
        waited = 0.0
        while not self._uvicorn.started:
            if self._error is not None or not self._thread.is_alive():
                raise RuntimeError(f"The MCP HTTP server did not start: {self._error!r}")
            if waited >= timeout:
                raise TimeoutError("The MCP HTTP server did not start in time.")
            deadline.wait(0.05)
            waited += 0.05
        log.info("MCP HTTP server listening on %s", self.url)

    def stop(self, timeout: float = 10.0) -> None:
        self._uvicorn.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None


async def _watch_vault_switch(server: SiigoMCPServer) -> None:
    """stdio mode: the tray owns the switch; notify the client when it changes."""
    last = server.write_switch.enabled
    while True:
        await anyio.sleep(STDIO_SWITCH_POLL_S)
        current = server.write_switch.enabled
        if current != last:
            last = current
            await server.broadcast_tools_changed()


async def run_stdio(server: SiigoMCPServer, *, watch_switch: bool = True) -> None:
    """Serve MCP over stdin/stdout until the client closes the stream."""
    async with anyio.create_task_group() as group:
        if watch_switch:
            group.start_soon(_watch_vault_switch, server)
        await server.run_stdio_async()
        group.cancel_scope.cancel()


def describe_endpoint(port: int) -> dict[str, Any]:
    """Non-secret connection facts (the bearer key is shown only by the tray UI)."""
    return {"url": f"http://{HOST}:{port}{MCP_PATH}", "transport": "streamable-http"}
