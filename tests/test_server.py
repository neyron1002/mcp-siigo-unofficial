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

from mcp_siigo_unofficial.server import app as app_module
from mcp_siigo_unofficial.server.app import STATUS_TOOL, SiigoMCPServer, build_server
from mcp_siigo_unofficial.server.approval import (
    ApprovalBroker,
    ApprovalMode,
    ApprovalRequest,
    Decision,
    LocalApprover,
    Outcome,
)
from mcp_siigo_unofficial.server.catalog import load_catalog
from mcp_siigo_unofficial.server.write_gate import EVENT_WRITE_ENABLED, WriteSwitch
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


class ScriptedApprover:
    """Stands in for the Siigo approval window: answers with ``outcome`` and records."""

    def __init__(self, outcome: Outcome = Outcome.APPROVED) -> None:
        self.outcome = outcome
        self.requests: list[ApprovalRequest] = []
        self.before_answer: Any = None
        self.early: Outcome | None = None
        self.early_checks = 0

    async def preapproved(self, request: ApprovalRequest) -> Outcome | None:
        self.early_checks += 1
        return self.early

    async def approve(self, request: ApprovalRequest) -> Outcome:
        self.requests.append(request)
        if self.before_answer is not None:
            self.before_answer()
        return self.outcome


@pytest.fixture
def approver() -> ScriptedApprover:
    return ScriptedApprover()


class Mode:
    value = ApprovalMode.SIIGO_WINDOW

    def __call__(self) -> ApprovalMode:
        return self.value


@pytest.fixture
def mode_setting() -> Mode:
    return Mode()


@pytest.fixture
async def server(
    mock_siigo: MockSiigo,
    credentials: SiigoCredentials,
    switch: WriteSwitch,
    vault: Vault,
    approver: ScriptedApprover,
    mode_setting: Mode,
) -> AsyncIterator[SiigoMCPServer]:
    siigo = SiigoClient(
        lambda: credentials, base_url="https://api.siigo.test", transport=mock_siigo.transport()
    )
    async with siigo:
        yield build_server(
            siigo, switch, vault=vault, approver=approver, approval_mode=mode_setting
        )


def text(result: Any) -> str:
    return str(result.content[0].text)


def payload(result: Any) -> Any:
    """JSON of a tool result (error texts carry an SDK prefix before the JSON)."""
    raw = text(result)
    return json.loads(raw[raw.index("{") :] if result.is_error else raw)


async def accept(context: Any, params: Any) -> ElicitResult:
    return ElicitResult(action="accept", content={"approve": True})


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
        assert "confirmation_id" not in tool.input_schema["properties"]
        assert "ctx" not in tool.input_schema["properties"]
        assert "approval" not in tool.input_schema["properties"]
        assert "approval window" in (tool.description or "")
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
async def test_window_approval_executes(
    server: SiigoMCPServer,
    switch: WriteSwitch,
    vault: Vault,
    approver: ScriptedApprover,
    mode: str,
) -> None:
    switch.enable(accepted_responsibility=True)
    async with Client(server, mode=mode) as client:
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
    first, second = approver.requests
    assert (first.tool, first.method, first.url) == (
        "siigo_create_customer",
        "POST",
        "https://api.siigo.test/v1/customers",
    )
    assert second.url == f"https://api.siigo.test/v1/customers/{created['id']}"
    assert ("id", created["id"]) in second.summary
    assert first.body == {"name": ["Ana", "Ruiz"]}
    assert first.connection == second.connection  # same AI app connection
    assert first.client != ""
    assert [e.detail["approved_via"] for e in vault.events("write.executed")] == [
        "approved",
        "approved",
    ]


@pytest.mark.parametrize(
    ("outcome", "status"),
    [(Outcome.REJECTED, "rejected_by_user"), (Outcome.TIMEOUT, "approval_timeout")],
)
async def test_rejected_or_unanswered_sends_nothing(
    server: SiigoMCPServer,
    switch: WriteSwitch,
    mock_siigo: MockSiigo,
    vault: Vault,
    approver: ScriptedApprover,
    outcome: Outcome,
    status: str,
) -> None:
    switch.enable(accepted_responsibility=True)
    approver.outcome = outcome
    async with Client(server) as client:
        result = payload(await client.call_tool("siigo_create_invoice", {"body": INVOICE}))
    assert result["status"] == status
    assert result["sent_to_siigo"] is False
    assert mock_siigo.data["invoices"] == {}
    assert posts(mock_siigo) == []
    assert [e.detail["outcome"] for e in vault.events("write.not_approved")] == [outcome.value]


async def test_unreachable_window_is_an_error_and_sends_nothing(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo, approver: ScriptedApprover
) -> None:
    switch.enable(accepted_responsibility=True)
    approver.outcome = Outcome.UNAVAILABLE
    async with Client(server) as client:
        result = await client.call_tool("siigo_create_invoice", {"body": INVOICE})
    assert result.is_error
    assert "approval_unavailable" in text(result)
    assert mock_siigo.data["invoices"] == {}


@pytest.mark.parametrize("mode", MODES)
async def test_ai_app_automatic_decline_is_not_used(
    server: SiigoMCPServer,
    switch: WriteSwitch,
    mock_siigo: MockSiigo,
    approver: ScriptedApprover,
    mode: str,
) -> None:
    """The v0.1.0 bug: Claude Desktop declines MCP elicitation without asking anyone.

    The server no longer asks the AI app; only the Siigo window decides.
    """
    switch.enable(accepted_responsibility=True)
    asked: list[Any] = []

    async def auto_decline(context: Any, params: Any) -> ElicitResult:
        asked.append(params)
        return ElicitResult(action="decline")

    async with Client(server, mode=mode, elicitation_callback=auto_decline) as client:
        approver.outcome = Outcome.APPROVED
        approved = await client.call_tool("siigo_create_invoice", {"body": INVOICE})
        approver.outcome = Outcome.REJECTED
        rejected = payload(await client.call_tool("siigo_create_invoice", {"body": INVOICE}))
    assert not approved.is_error
    assert rejected["status"] == "rejected_by_user"
    assert asked == []
    assert len(mock_siigo.data["invoices"]) == 1


async def test_switch_turned_off_during_approval(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo, approver: ScriptedApprover
) -> None:
    switch.enable(accepted_responsibility=True)
    approver.before_answer = switch.disable
    async with Client(server) as client:
        result = await client.call_tool("siigo_create_invoice", {"body": INVOICE})
    assert result.is_error
    assert "write_actions_disabled" in text(result)
    assert mock_siigo.data["invoices"] == {}


async def test_status_shows_the_approval_mode(server: SiigoMCPServer, mode_setting: Mode) -> None:
    async with Client(server) as client:
        status = payload(await client.call_tool(STATUS_TOOL, {}))
        mode_setting.value = ApprovalMode.AI_APP
        later = payload(await client.call_tool(STATUS_TOOL, {}))
    assert status["write_approval"] == "siigo_window"
    assert later["write_approval"] == "ai_app"


# ---------------------------------------------------------------------- "In the AI app" mode
def answering(action: str, approve: bool = True, delay: float = 0.0) -> Any:
    asked: list[str] = []

    async def callback(context: Any, params: Any) -> ElicitResult:
        asked.append(params.message)
        if delay:
            await anyio.sleep(delay)
        if action == "accept":
            return ElicitResult(action="accept", content={"approve": approve})
        return ElicitResult(action=action)  # type: ignore[arg-type]

    callback.asked = asked  # type: ignore[attr-defined]
    return callback


@pytest.mark.parametrize("mode", MODES)
async def test_ai_app_mode_approves_in_the_ai_app(
    server: SiigoMCPServer,
    switch: WriteSwitch,
    vault: Vault,
    approver: ScriptedApprover,
    mode_setting: Mode,
    mode: str,
) -> None:
    switch.enable(accepted_responsibility=True)
    mode_setting.value = ApprovalMode.AI_APP
    callback = answering("accept", approve=True)
    async with Client(server, mode=mode, elicitation_callback=callback) as client:
        result = await client.call_tool("siigo_create_invoice", {"body": INVOICE})
    assert not result.is_error
    assert "WRITE ACTION" in callback.asked[0]
    assert approver.requests == []  # no Siigo window
    assert [e.detail["approved_via"] for e in vault.events("write.executed")] == ["ai_app"]


@pytest.mark.parametrize("mode", MODES)
async def test_ai_app_mode_rejected_in_the_ai_app(
    server: SiigoMCPServer,
    switch: WriteSwitch,
    mock_siigo: MockSiigo,
    approver: ScriptedApprover,
    mode_setting: Mode,
    mode: str,
) -> None:
    switch.enable(accepted_responsibility=True)
    mode_setting.value = ApprovalMode.AI_APP
    callback = answering("accept", approve=False)
    async with Client(server, mode=mode, elicitation_callback=callback) as client:
        result = payload(await client.call_tool("siigo_create_invoice", {"body": INVOICE}))
    assert result["status"] == "rejected_by_user"
    assert "your app's approval question" in result["message"]
    assert approver.requests == []
    assert mock_siigo.data["invoices"] == {}


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("action", ["decline", "cancel"])
async def test_ai_app_mode_fast_decline_falls_back_to_the_window(
    server: SiigoMCPServer,
    switch: WriteSwitch,
    mock_siigo: MockSiigo,
    approver: ScriptedApprover,
    mode_setting: Mode,
    mode: str,
    action: str,
) -> None:
    """Claude Desktop declines in about 1 ms: the Siigo window asks instead (W2)."""
    switch.enable(accepted_responsibility=True)
    mode_setting.value = ApprovalMode.AI_APP
    callback = answering(action)
    async with Client(server, mode=mode, elicitation_callback=callback) as client:
        approver.outcome = Outcome.APPROVED
        approved = await client.call_tool("siigo_create_invoice", {"body": INVOICE})
        approver.outcome = Outcome.REJECTED
        rejected = payload(await client.call_tool("siigo_create_invoice", {"body": INVOICE}))
    assert not approved.is_error
    assert rejected["status"] == "rejected_by_user"
    assert len(callback.asked) == 2
    assert len(approver.requests) == 2  # both went to the window
    assert len(mock_siigo.data["invoices"]) == 1


async def test_ai_app_mode_slow_decline_is_the_users_no(
    server: SiigoMCPServer,
    switch: WriteSwitch,
    mock_siigo: MockSiigo,
    approver: ScriptedApprover,
    mode_setting: Mode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch.enable(accepted_responsibility=True)
    mode_setting.value = ApprovalMode.AI_APP
    monkeypatch.setattr(app_module, "AUTOMATIC_DECLINE_S", 0.05)
    callback = answering("decline", delay=0.1)
    async with Client(server, mode="legacy", elicitation_callback=callback) as client:
        result = payload(await client.call_tool("siigo_create_invoice", {"body": INVOICE}))
    assert result["status"] == "rejected_by_user"
    assert approver.requests == []
    assert mock_siigo.data["invoices"] == {}


async def test_ai_app_mode_without_elicitation_uses_the_window(
    server: SiigoMCPServer, switch: WriteSwitch, approver: ScriptedApprover, mode_setting: Mode
) -> None:
    switch.enable(accepted_responsibility=True)
    mode_setting.value = ApprovalMode.AI_APP
    async with Client(server) as client:  # no elicitation callback: no capability
        result = await client.call_tool("siigo_create_invoice", {"body": INVOICE})
    assert not result.is_error
    assert len(approver.requests) == 1


@pytest.mark.parametrize("early", [Outcome.AUTOMATIC, Outcome.GRANTED])
async def test_ai_app_mode_skips_the_question_when_preapproved(
    server: SiigoMCPServer,
    switch: WriteSwitch,
    vault: Vault,
    approver: ScriptedApprover,
    mode_setting: Mode,
    early: Outcome,
) -> None:
    switch.enable(accepted_responsibility=True)
    mode_setting.value = ApprovalMode.AI_APP
    approver.early = early
    callback = answering("accept", approve=False)
    async with Client(server, elicitation_callback=callback) as client:
        result = await client.call_tool("siigo_create_invoice", {"body": INVOICE})
    assert not result.is_error
    assert callback.asked == []
    assert approver.requests == []
    assert [e.detail["approved_via"] for e in vault.events("write.executed")] == [early.value]


@pytest.mark.parametrize("mode_value", [ApprovalMode.SIIGO_WINDOW, ApprovalMode.NOTIFICATION])
async def test_window_modes_never_ask_the_ai_app(
    server: SiigoMCPServer,
    switch: WriteSwitch,
    approver: ScriptedApprover,
    mode_setting: Mode,
    mode_value: ApprovalMode,
) -> None:
    switch.enable(accepted_responsibility=True)
    mode_setting.value = mode_value
    callback = answering("accept", approve=True)
    async with Client(server, elicitation_callback=callback) as client:
        await client.call_tool("siigo_create_invoice", {"body": INVOICE})
    assert callback.asked == []
    assert len(approver.requests) == 1
    assert approver.early_checks == 0


def test_no_schema_repeats_a_required_name() -> None:
    """The Claude API rejects such schemas, and Claude Code then hides the tool."""

    def walk(node: Any) -> Iterator[list[Any]]:
        if isinstance(node, dict):
            required = node.get("required")
            if isinstance(required, list):
                yield required
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    for tool in CATALOG.tools:
        for required in walk(tool.body_schema):
            assert len(required) == len(set(required)), tool.name


async def test_similar_writes_grant_through_the_broker(
    mock_siigo: MockSiigo, credentials: SiigoCredentials, switch: WriteSwitch, vault: Vault
) -> None:
    """Approve similar writes: the same tool from the same connection runs without asking."""
    broker = ApprovalBroker()
    shown: list[ApprovalRequest] = []

    def window(request: ApprovalRequest) -> None:
        shown.append(request)
        decision = Decision.APPROVE_SIMILAR if len(shown) == 1 else Decision.APPROVE
        broker.answer(request.id, decision)

    broker.on_ask = window
    switch.enable(accepted_responsibility=True)
    siigo = SiigoClient(
        lambda: credentials, base_url="https://api.siigo.test", transport=mock_siigo.transport()
    )
    async with siigo:
        server = build_server(siigo, switch, vault=vault, approver=LocalApprover(broker))
        async with Client(server, mode="legacy") as client:
            for code in ("P1", "P2", "P3"):
                body = {"code": code, "name": code, "account_group": 1}
                assert not (await client.call_tool("siigo_create_product", {"body": body})).is_error
            await client.call_tool("siigo_create_customer", {"body": {"name": ["A", "B"]}})
            async with Client(server, mode="legacy") as other:  # another connection: asked
                body = {"code": "P4", "name": "P4", "account_group": 1}
                await other.call_tool("siigo_create_product", {"body": body})
    assert [r.tool for r in shown] == [
        "siigo_create_product",
        "siigo_create_customer",
        "siigo_create_product",
    ]
    assert [e.detail["approved_via"] for e in vault.events("write.executed")] == [
        "approved_similar",
        "granted",
        "granted",
        "approved",
        "approved",
    ]


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


# ---------------------------------------------------------------------- Idempotency-Key (A6)


def idempotency_keys(mock: MockSiigo) -> list[str | None]:
    return [
        r.headers.get("Idempotency-Key")
        for r in mock.requests
        if r.method == "POST" and r.url.path.startswith("/v1/")
    ]


async def test_same_invoice_twice_creates_one_document(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo, vault: Vault
) -> None:
    switch.enable(accepted_responsibility=True)
    async with Client(server) as client:
        first = payload(await client.call_tool("siigo_create_invoice", {"body": INVOICE}))
        again = payload(await client.call_tool("siigo_create_invoice", {"body": INVOICE}))
        other = payload(
            await client.call_tool(
                "siigo_create_invoice", {"body": {**INVOICE, "observations": "second one"}}
            )
        )
    assert again["id"] == first["id"]
    assert other["id"] != first["id"]
    assert len(mock_siigo.data["invoices"]) == 2
    keys = idempotency_keys(mock_siigo)
    assert len(keys) == 3
    assert keys[0] == keys[1] != keys[2]
    assert all(k is not None and k.isalnum() and len(k) == 30 for k in keys)
    logged = [e.detail.get("idempotency_key") for e in vault.events("write.executed")]
    assert logged == keys


async def test_no_idempotency_key_where_siigo_does_not_accept_it(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo
) -> None:
    switch.enable(accepted_responsibility=True)
    async with Client(server) as client:
        await client.call_tool("siigo_create_customer", {"body": {"identification": "1"}})
    assert idempotency_keys(mock_siigo) == [None]


async def test_idempotent_tools_explain_duplicate_protection(server: SiigoMCPServer) -> None:
    from mcp_siigo_unofficial.server import idempotency

    with_note = {
        t.name for t in load_catalog().write_tools if idempotency.applies(t.method, t.path)
    }
    assert with_note == {
        "siigo_create_invoice",
        "siigo_create_credit_note",
        "siigo_create_journal",
        "siigo_create_voucher",
        "siigo_create_voucher_misc_income",
    }
    for tool in load_catalog().write_tools:
        description = app_module._describe(tool)
        assert (idempotency.NOTE in description) == (tool.name in with_note)


def test_idempotency_key_ignores_field_order() -> None:
    from mcp_siigo_unofficial.server import idempotency

    a = idempotency.key_for("/v1/invoices", {"date": "2026-11-27", "seller": 1})
    b = idempotency.key_for("/v1/invoices", {"seller": 1, "date": "2026-11-27"})
    assert a == b
    assert a != idempotency.key_for("/v1/credit-notes", {"date": "2026-11-27", "seller": 1})
    assert idempotency.headers_for("PUT", "/v1/invoices", {"x": 1}) == {}
