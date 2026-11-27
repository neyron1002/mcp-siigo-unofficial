"""Transports: Streamable HTTP on 127.0.0.1 with a bearer key, and stdio (plan D4)."""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

from mcp_siigo_unofficial.server.app import STATUS_TOOL, build_server
from mcp_siigo_unofficial.server.transport import (
    HOST,
    SECRET_BEARER_KEY,
    BearerAuthMiddleware,
    HttpServerThread,
    ensure_bearer_key,
    port_is_free,
)
from mcp_siigo_unofficial.server.write_gate import WriteSwitch
from mcp_siigo_unofficial.siigo import SiigoClient, SiigoCredentials
from mcp_siigo_unofficial.vault import MemoryKeyStore, Vault
from mock_siigo import MockSiigo

pytestmark = pytest.mark.anyio

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def vault(tmp_path: Path) -> Iterator[Vault]:
    with Vault.open(tmp_path / "vault.sqlite3", MemoryKeyStore()) as opened:
        yield opened


@pytest.fixture
def http_server(
    vault: Vault, mock_siigo: MockSiigo, credentials: SiigoCredentials
) -> Iterator[tuple[str, str]]:
    siigo = SiigoClient(lambda: credentials, transport=mock_siigo.transport())
    server = build_server(siigo, WriteSwitch(vault), vault=vault)
    key = ensure_bearer_key(vault)
    thread = HttpServerThread(server, key, port=free_port())
    thread.start()
    try:
        yield thread.url, key
    finally:
        thread.stop()


def test_bearer_key_is_created_once(vault: Vault) -> None:
    key = ensure_bearer_key(vault)
    assert len(key) >= 40
    assert ensure_bearer_key(vault) == key
    assert vault.get_secret(SECRET_BEARER_KEY) == key


def test_short_bearer_key_is_refused() -> None:
    async def app(scope: object, receive: object, send: object) -> None:
        return None

    with pytest.raises(ValueError, match="too short"):
        BearerAuthMiddleware(app, "short")  # type: ignore[arg-type]


@pytest.mark.parametrize("auth", [None, "Bearer wrong-key-wrong-key-wrong", "Basic abc"])
async def test_http_requires_the_bearer_key(http_server: tuple[str, str], auth: str | None) -> None:
    url, _key = http_server
    headers = dict(MCP_HEADERS)
    if auth is not None:
        headers["Authorization"] = auth
    async with httpx2.AsyncClient() as client:
        response = await client.post(url, json=INITIALIZE, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


async def test_http_rejects_foreign_host_headers(http_server: tuple[str, str]) -> None:
    url, key = http_server
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {key}", "Host": "evil.example"}
    async with httpx2.AsyncClient() as client:
        response = await client.post(url, json=INITIALIZE, headers=headers)
    assert response.status_code in {400, 403, 421}


async def test_http_end_to_end_with_mcp_client(
    http_server: tuple[str, str], mock_siigo: MockSiigo
) -> None:
    url, key = http_server
    async with (
        httpx2.AsyncClient(headers={"Authorization": f"Bearer {key}"}) as http,
        Client(streamable_http_client(url, http_client=http)) as client,
    ):
        names = {t.name for t in (await client.list_tools()).tools}
        taxes = await client.call_tool("siigo_list_taxes", {})
    assert STATUS_TOOL in names
    assert "siigo_create_invoice" not in names
    assert not taxes.is_error
    assert mock_siigo.auth_calls == 1


def test_http_server_binds_only_to_loopback(vault: Vault) -> None:
    server = build_server(SiigoClient(lambda: None), WriteSwitch(vault))
    port = free_port()
    thread = HttpServerThread(server, ensure_bearer_key(vault), port=port)
    thread.start()
    try:
        assert thread.running
        assert not port_is_free(port)
        with pytest.raises(OSError, match="already in use"):
            HttpServerThread(server, ensure_bearer_key(vault), port=port).start()
    finally:
        thread.stop()
    assert port_is_free(port)


def test_http_server_starts_without_console(vault: Vault, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Windows window build opened from Explorer has no stdout or stderr (v0.2.0 bug)."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    server = build_server(SiigoClient(lambda: None), WriteSwitch(vault))
    thread = HttpServerThread(server, ensure_bearer_key(vault), port=free_port())
    thread.start()
    try:
        assert thread.running
    finally:
        thread.stop()


async def test_stdio_end_to_end(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "MCP_SIIGO_UNOFFICIAL_HOME": str(tmp_path / "stdio-home"),
        # No OS keychain in this test: a throwaway, non-persistent backend.
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "mcp_siigo_unofficial", "--stdio"], env=env
    )
    async with Client(params) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        status = await client.call_tool(STATUS_TOOL, {})
    assert len(names) == 46
    assert '"siigo_configured":false' in str(status.content[0].text)
    assert '"write_actions_enabled":false' in str(status.content[0].text)
