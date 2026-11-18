"""MCP server tests with an in-process MCP client against the mock Siigo API (plan phase 2)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import anyio
import anyio.to_thread
import pytest
from mcp import Client
from mcp.types import ElicitResult

from conftest import FakeClock
from mcp_siigo_unofficial.server.app import STATUS_TOOL, SiigoMCPServer, build_server
from mcp_siigo_unofficial.server.catalog import load_catalog
from mcp_siigo_unofficial.server.write_gate import (
    EVENT_WRITE_ENABLED,
    ConfirmationStore,
    WriteSwitch,
)
from mcp_siigo_unofficial.siigo import SiigoClient, SiigoCredentials
from mcp_siigo_unofficial.vault import MemoryKeyStore, Vault
from mock_siigo import MockSiigo

pytestmark = pytest.mark.anyio

CATALOG = load_catalog()
WRITE_NAMES = {t.name for t in CATALOG.write_tools}
READ_NAMES = {t.name for t in CATALOG.read_tools}
MODES = ["auto", "legacy"]
INVOICE = {"document": {"id": 24446}, "customer": {"identification": "13832081"}}


@pytest.fixture
def vault(tmp_path: Path) -> Iterator[Vault]:
    with Vault.open(tmp_path / "vault.sqlite3", MemoryKeyStore()) as opened:
        yield opened


@pytest.fixture
def switch(vault: Vault) -> WriteSwitch:
    write_switch = WriteSwitch(vault)
    write_switch.reset_at_start()
    return write_switch


@pytest.fixture
async def server(
    mock_siigo: MockSiigo,
    credentials: SiigoCredentials,
    switch: WriteSwitch,
    vault: Vault,
    clock: FakeClock,
) -> AsyncIterator[SiigoMCPServer]:
    siigo = SiigoClient(
        lambda: credentials, base_url="https://api.siigo.test", transport=mock_siigo.transport()
    )
    async with siigo:
        yield build_server(siigo, switch, vault=vault, confirmations=ConfirmationStore(clock=clock))


def text(result: Any) -> str:
    return str(result.content[0].text)


def payload(result: Any) -> Any:
    """JSON of a tool result (error texts carry an SDK prefix before the JSON)."""
    raw = text(result)
    return json.loads(raw[raw.index("{") :] if result.is_error else raw)


async def accept(context: Any, params: Any) -> ElicitResult:
    return ElicitResult(action="accept", content={"approve": True})


async def reject(context: Any, params: Any) -> ElicitResult:
    return ElicitResult(action="accept", content={"approve": False})


async def decline(context: Any, params: Any) -> ElicitResult:
    return ElicitResult(action="decline")


def posts(mock: MockSiigo) -> list[str]:
    return [str(r.url.path) for r in mock.requests if r.method in {"POST", "PUT"}][1:]


# ---------------------------------------------------------------------- catalog and listing
def test_catalog_scope() -> None:
    assert len(READ_NAMES) == 45
    assert {
        "siigo_create_customer",
        "siigo_update_customer",
        "siigo_create_product",
        "siigo_update_product",
        "siigo_create_invoice",
        "siigo_create_credit_note",
        "siigo_create_voucher",
        "siigo_create_voucher_misc_income",
        "siigo_create_journal",
    } == WRITE_NAMES
    assert not any(t.method == "DELETE" for t in CATALOG.tools)
    assert all(t.path.startswith("/v1/") for t in CATALOG.tools)


@pytest.mark.parametrize("mode", MODES)
async def test_write_tools_hidden_while_switch_is_off(server: SiigoMCPServer, mode: str) -> None:
    async with Client(server, mode=mode) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        status = payload(await client.call_tool(STATUS_TOOL, {}))
    assert names == READ_NAMES | {STATUS_TOOL}
    assert status["write_actions_enabled"] is False
    assert status["siigo_configured"] is True
    assert status["write_tools"] == 0


async def test_annotations_and_write_warnings(server: SiigoMCPServer, switch: WriteSwitch) -> None:
    switch.enable(accepted_responsibility=True)
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == READ_NAMES | WRITE_NAMES | {STATUS_TOOL}
    for name in READ_NAMES:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is True
        assert annotations.destructive_hint is False
    for name in WRITE_NAMES:
        tool = tools[name]
        assert tool.annotations is not None
        assert tool.annotations.destructive_hint is True
        assert tool.annotations.read_only_hint is False
        assert (tool.description or "").startswith("⚠ WRITE ACTION — REAL DATA IN SIIGO")
        assert "confirmation_id" in tool.input_schema["properties"]
        assert "approval" not in tool.input_schema["properties"]
        assert "body" in tool.input_schema["required"]


async def test_instructions_carry_the_liability_statement(server: SiigoMCPServer) -> None:
    assert "the author is not responsible for AI decisions" in (server.instructions or "")
    assert "only they can enable them from the tray" in (server.instructions or "")


# ---------------------------------------------------------------------- reads
async def test_read_tools_call_siigo(server: SiigoMCPServer, mock_siigo: MockSiigo) -> None:
    created = mock_siigo.seed("customers", 3)
    async with Client(server) as client:
        listed = payload(
            await client.call_tool("siigo_list_customers", {"page": 1, "page_size": 2})
        )
        one = payload(await client.call_tool("siigo_get_customer", {"id": created[0]["id"]}))
        types = await client.call_tool("siigo_list_invoice_types", {})
        taxes = payload(await client.call_tool("siigo_list_taxes", {}))
    assert listed["pagination"]["total_results"] == 3
    assert len(listed["results"]) == 2
    assert one["id"] == created[0]["id"]
    assert not types.is_error
    assert taxes[0]["name"] == "IVA 19%"
    doc_types = [r for r in mock_siigo.requests if r.url.path == "/v1/document-types"]
    assert doc_types[0].url.params["type"] == "FV"


async def test_siigo_errors_become_tool_errors(server: SiigoMCPServer) -> None:
    async with Client(server) as client:
        result = await client.call_tool("siigo_get_customer", {"id": "missing-id"})
    assert result.is_error
    error = payload(result)["error"]
    assert error["status"] == 404
    assert error["code"] == "not_found"


async def test_invalid_path_ids_are_rejected(server: SiigoMCPServer, mock_siigo: MockSiigo) -> None:
    async with Client(server) as client:
        result = await client.call_tool("siigo_get_customer", {"id": "../auth"})
    assert result.is_error
    assert "invalid characters" in text(result)
    assert mock_siigo.requests == []


async def test_not_configured(switch: WriteSwitch) -> None:
    async with SiigoClient(lambda: None) as siigo:
        server = build_server(siigo, switch)
        async with Client(server) as client:
            status = payload(await client.call_tool(STATUS_TOOL, {}))
            result = await client.call_tool("siigo_list_taxes", {})
    assert status["siigo_configured"] is False
    assert result.is_error
    assert "not_configured" in text(result)


# ---------------------------------------------------------------------- write gate
@pytest.mark.parametrize("mode", MODES)
async def test_write_rejected_while_switch_is_off(
    server: SiigoMCPServer, mock_siigo: MockSiigo, mode: str
) -> None:
    async with Client(server, mode=mode, elicitation_callback=accept) as client:
        result = await client.call_tool("siigo_create_invoice", {"body": INVOICE})
    assert result.is_error
    assert "write_actions_disabled" in text(result)
    assert mock_siigo.data["invoices"] == {}
    assert mock_siigo.requests == []


def test_switch_needs_acceptance(switch: WriteSwitch, vault: Vault) -> None:
    with pytest.raises(Exception, match="acceptance"):
        switch.enable(accepted_responsibility=False)
    assert switch.enabled is False
    switch.enable(accepted_responsibility=True)
    events = vault.events(EVENT_WRITE_ENABLED)
    assert len(events) == 1
    assert events[0].detail["accepted_responsibility"] is True
    assert vault.get_setting("write_actions.enabled") is True
    switch.reset_at_start()
    assert switch.enabled is False
    assert vault.get_setting("write_actions.enabled") is False


@pytest.mark.parametrize("mode", MODES)
async def test_two_step_confirmation_without_elicitation(
    server: SiigoMCPServer,
    switch: WriteSwitch,
    mock_siigo: MockSiigo,
    vault: Vault,
    mode: str,
) -> None:
    switch.enable(accepted_responsibility=True)
    async with Client(server, mode=mode) as client:
        preview = payload(await client.call_tool("siigo_create_invoice", {"body": INVOICE}))
        assert preview["status"] == "confirmation_required"
        assert preview["sent_to_siigo"] is False
        assert preview["preview"]["method"] == "POST"
        assert preview["preview"]["body"] == INVOICE
        assert mock_siigo.data["invoices"] == {}

        cid = preview["confirmation_id"]
        done = payload(
            await client.call_tool(
                "siigo_create_invoice", {"body": INVOICE, "confirmation_id": cid}
            )
        )
        assert done["name"] == "FV-1-1"
        assert len(mock_siigo.data["invoices"]) == 1

        reused = await client.call_tool(
            "siigo_create_invoice", {"body": INVOICE, "confirmation_id": cid}
        )
        assert reused.is_error
        assert "invalid_confirmation" in text(reused)
    assert len(mock_siigo.data["invoices"]) == 1
    executed = vault.events("write.executed")
    assert [e.detail["approved_via"] for e in executed] == ["confirmation_id"]


async def test_write_without_valid_confirmation_is_rejected(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo, clock: FakeClock
) -> None:
    switch.enable(accepted_responsibility=True)
    async with Client(server) as client:
        made_up = await client.call_tool(
            "siigo_create_invoice", {"body": INVOICE, "confirmation_id": "made-up"}
        )
        first = payload(await client.call_tool("siigo_create_invoice", {"body": INVOICE}))
        changed = await client.call_tool(
            "siigo_create_invoice",
            {"body": {**INVOICE, "observations": "x"}, "confirmation_id": first["confirmation_id"]},
        )
        second = payload(await client.call_tool("siigo_create_invoice", {"body": INVOICE}))
        clock.now += 301
        expired = await client.call_tool(
            "siigo_create_invoice", {"body": INVOICE, "confirmation_id": second["confirmation_id"]}
        )
        third = payload(await client.call_tool("siigo_create_customer", {"body": {"a": 1}}))
        other_tool = await client.call_tool(
            "siigo_create_product", {"body": {"a": 1}, "confirmation_id": third["confirmation_id"]}
        )
    for result in (made_up, changed, expired, other_tool):
        assert result.is_error
        assert "invalid_confirmation" in text(result)
    assert mock_siigo.data["invoices"] == {}
    assert mock_siigo.data["customers"] == {}
    assert mock_siigo.data["products"] == {}


@pytest.mark.parametrize("mode", MODES)
async def test_elicitation_approve_executes(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo, vault: Vault, mode: str
) -> None:
    switch.enable(accepted_responsibility=True)
    seen: list[str] = []

    async def approve_and_record(context: Any, params: Any) -> ElicitResult:
        seen.append(params.message)
        return ElicitResult(action="accept", content={"approve": True})

    async with Client(server, mode=mode, elicitation_callback=approve_and_record) as client:
        created = payload(
            await client.call_tool("siigo_create_customer", {"body": {"name": ["Ana", "Ruiz"]}})
        )
        updated = payload(
            await client.call_tool(
                "siigo_update_customer",
                {"id": created["id"], "body": {"name": ["Ana", "Pérez"]}},
            )
        )
    assert updated["name"] == ["Ana", "Pérez"]
    assert "WRITE ACTION" in seen[0]
    assert "POST https://api.siigo.test/v1/customers" in seen[0]
    assert f"PUT https://api.siigo.test/v1/customers/{created['id']}" in seen[1]
    assert [e.detail["approved_via"] for e in vault.events("write.executed")] == [
        "elicitation",
        "elicitation",
    ]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("callback", [reject, decline])
async def test_elicitation_reject_or_decline_sends_nothing(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo, mode: str, callback: Any
) -> None:
    switch.enable(accepted_responsibility=True)
    async with Client(server, mode=mode, elicitation_callback=callback) as client:
        result = payload(await client.call_tool("siigo_create_invoice", {"body": INVOICE}))
    assert result["status"] == "rejected_by_user"
    assert mock_siigo.data["invoices"] == {}
    assert posts(mock_siigo) == []


async def test_elicitation_ignores_a_confirmation_id(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo
) -> None:
    """With elicitation available, the user is always asked; a confirmation_id is not enough."""
    switch.enable(accepted_responsibility=True)
    async with Client(server, elicitation_callback=decline) as client:
        result = payload(
            await client.call_tool(
                "siigo_create_invoice", {"body": INVOICE, "confirmation_id": "anything"}
            )
        )
    assert result["status"] == "rejected_by_user"
    assert mock_siigo.data["invoices"] == {}


async def test_switch_turned_off_between_preview_and_confirmation(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo
) -> None:
    switch.enable(accepted_responsibility=True)
    async with Client(server) as client:
        first = payload(await client.call_tool("siigo_create_invoice", {"body": INVOICE}))
        switch.disable()
        result = await client.call_tool(
            "siigo_create_invoice", {"body": INVOICE, "confirmation_id": first["confirmation_id"]}
        )
    assert result.is_error
    assert "write_actions_disabled" in text(result)
    assert mock_siigo.data["invoices"] == {}


# ---------------------------------------------------------------------- notifications
async def test_switch_change_sends_tools_list_changed(
    server: SiigoMCPServer, switch: WriteSwitch
) -> None:
    received = anyio.Event()
    methods: list[str] = []

    async def on_message(message: Any) -> None:
        method = getattr(getattr(message, "root", message), "method", None)
        if method is not None:
            methods.append(str(method))
            if method == "notifications/tools/list_changed":
                received.set()

    async with Client(server, mode="legacy", message_handler=on_message) as client:
        await client.list_tools()
        # The tray changes the switch from the Qt thread, not from the server loop.
        await anyio.to_thread.run_sync(lambda: switch.enable(accepted_responsibility=True))
        with anyio.fail_after(5):
            await received.wait()
        names = {t.name for t in (await client.list_tools()).tools}
    assert names >= WRITE_NAMES
    assert "notifications/tools/list_changed" in methods


def test_follow_vault_switch_reads_the_tray_state(vault: Vault, switch: WriteSwitch) -> None:
    follower = WriteSwitch(vault, follow_vault=True)
    assert follower.enabled is False
    switch.enable(accepted_responsibility=True)
    assert follower.enabled is True
    with pytest.raises(Exception, match="tray"):
        follower.disable()
