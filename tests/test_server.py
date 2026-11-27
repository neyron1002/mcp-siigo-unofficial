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
        # Phase 12 (API coverage plan)
        "siigo_create_account_group",
        "siigo_update_account_group",
        "siigo_update_invoice",
        "siigo_create_quotation",
        "siigo_update_quotation",
        "siigo_create_purchase",
        "siigo_update_purchase",
        "siigo_create_support_document",
        "siigo_update_support_document",
        "siigo_create_payment_receipt",
        "siigo_create_payment_receipt_detailed",
        # Phase 13: delete and annul
        "siigo_delete_product",
        "siigo_delete_invoice",
        "siigo_annul_invoice",
        "siigo_delete_quotation",
        "siigo_delete_purchase",
        "siigo_delete_support_document",
        "siigo_delete_payment_receipt",
        # Phase 14: email and webhooks
        "siigo_send_invoice_email",
        "siigo_create_webhook",
        "siigo_update_webhook",
        "siigo_delete_webhook",
    } == WRITE_NAMES
    permanent = {t.name for t in CATALOG.write_tools if t.risk.value == "permanent"}
    assert permanent == {t.name for t in CATALOG.tools if t.method == "DELETE"} | {
        "siigo_annul_invoice"
    }
    outbound = {t.name for t in CATALOG.write_tools if t.risk.value == "outbound"}
    assert outbound == {"siigo_send_invoice_email", "siigo_create_webhook", "siigo_update_webhook"}
    assert len(WRITE_NAMES) == 31
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
        if CATALOG.get(name).body_schema is not None:
            assert "body" in tool.input_schema["required"]
        else:  # delete and annul take only the record id
            assert "body" not in tool.input_schema["properties"]
            assert tool.input_schema["required"] == ["id"]


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


# ---------------------------------------------------------------------- risk levels (A2-A4)


def risky_catalog() -> Any:
    """The shipped catalog plus one permanent and one outbound tool (phase 11 has none yet)."""
    import dataclasses

    from mcp_siigo_unofficial.server.catalog import EndpointTool, Param, Risk

    shipped = load_catalog()
    id_param = Param("id", "path", "string", True, "Record id.")
    delete = EndpointTool(
        name="siigo_delete_product",
        title="Delete product",
        method="DELETE",
        path="/v1/products/{id}",
        read_only=False,
        description="Borrar un producto.",
        params=(id_param,),
        risk=Risk.PERMANENT,
    )
    mail = EndpointTool(
        name="siigo_send_invoice_email",
        title="Send invoice email",
        method="POST",
        path="/v1/invoices/{id}/mail",
        read_only=False,
        description="Enviar factura por correo.",
        params=(id_param,),
        body_schema={"type": "object", "properties": {"mail_to": {"type": "string"}}},
        risk=Risk.OUTBOUND,
    )
    return dataclasses.replace(shipped, tools=(*shipped.tools, delete, mail))


@pytest.fixture
async def risky_server(
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
        yield SiigoMCPServer(
            siigo,
            switch,
            catalog=risky_catalog(),
            vault=vault,
            approver=approver,
            approval_mode=mode_setting,
        )


async def test_permanent_writes_skip_the_ai_app_question(
    risky_server: SiigoMCPServer,
    switch: WriteSwitch,
    mock_siigo: MockSiigo,
    approver: ScriptedApprover,
    mode_setting: Mode,
) -> None:
    from mcp_siigo_unofficial.server.catalog import Risk

    switch.enable(accepted_responsibility=True)
    mode_setting.value = ApprovalMode.AI_APP
    (product,) = mock_siigo.seed("products", 1)
    asked: list[Any] = []

    async def would_accept(context: Any, params: Any) -> ElicitResult:
        asked.append(params)
        return ElicitResult(action="accept", content={"approve": True})

    async with Client(risky_server, elicitation_callback=would_accept) as client:
        result = payload(await client.call_tool("siigo_delete_product", {"id": product["id"]}))
    assert asked == []  # the AI app is never asked
    assert [r.risk for r in approver.requests] == [Risk.PERMANENT]  # the Siigo window is
    assert approver.early_checks == 0  # no shortcut is even checked here
    assert result == {"id": product["id"], "deleted": True}


async def test_outbound_writes_still_use_the_ai_app_mode(
    risky_server: SiigoMCPServer,
    switch: WriteSwitch,
    mode_setting: Mode,
    approver: ScriptedApprover,
) -> None:
    switch.enable(accepted_responsibility=True)
    mode_setting.value = ApprovalMode.AI_APP
    asked: list[Any] = []

    async def reject(context: Any, params: Any) -> ElicitResult:
        asked.append(params)
        return ElicitResult(action="accept", content={"approve": False})

    address = "customer-with-a-long-name@" + "x" * 90 + ".example.com"
    async with Client(risky_server, elicitation_callback=reject) as client:
        result = payload(
            await client.call_tool(
                "siigo_send_invoice_email", {"id": "F1", "body": {"mail_to": address}}
            )
        )
    assert result["status"] == "rejected_by_user"
    assert len(asked) == 1
    assert address in asked[0].message  # shown whole
    assert "OUTSIDE SIIGO" in asked[0].message
    assert approver.requests == []


async def test_risky_requests_carry_level_and_full_summary(
    risky_server: SiigoMCPServer, switch: WriteSwitch, approver: ScriptedApprover
) -> None:
    from mcp_siigo_unofficial.server.catalog import Risk

    switch.enable(accepted_responsibility=True)
    approver.outcome = Outcome.REJECTED
    address = "a@" + "y" * 120 + ".example.com"
    async with Client(risky_server) as client:
        await client.call_tool(
            "siigo_send_invoice_email", {"id": "F1", "body": {"mail_to": address}}
        )
        await client.call_tool("siigo_create_invoice", {"body": INVOICE})
    mail, invoice = approver.requests
    assert mail.risk is Risk.OUTBOUND
    assert ("mail_to", address) in mail.summary
    assert invoice.risk is Risk.CHANGE


async def test_risky_tool_descriptions(risky_server: SiigoMCPServer, switch: WriteSwitch) -> None:
    switch.enable(accepted_responsibility=True)
    async with Client(risky_server) as client:
        tools = {t.name: t.description or "" for t in (await client.list_tools()).tools}
    assert "CAN'T BE UNDONE" in tools["siigo_delete_product"]
    assert "OUTSIDE SIIGO" in tools["siigo_send_invoice_email"]
    assert "CAN'T BE UNDONE" not in tools["siigo_create_invoice"]
    assert "OUTSIDE SIIGO" not in tools["siigo_create_invoice"]


# ---------------------------------------------------------------------- phase 12 tools


@pytest.mark.parametrize(
    ("tool", "resource", "update"),
    [
        ("account_group", "account-groups", True),
        ("quotation", "quotations", True),
        ("purchase", "purchases", True),
        ("support_document", "purchase-support-documents", True),
        ("payment_receipt", "payment-receipts", False),
        ("payment_receipt_detailed", "payment-receipts", False),
    ],
)
async def test_new_create_and_update_tools_reach_siigo(
    server: SiigoMCPServer,
    switch: WriteSwitch,
    mock_siigo: MockSiigo,
    approver: ScriptedApprover,
    tool: str,
    resource: str,
    update: bool,
) -> None:
    switch.enable(accepted_responsibility=True)
    async with Client(server) as client:
        created = payload(await client.call_tool(f"siigo_create_{tool}", {"body": {"x": 1}}))
        if update:
            changed = payload(
                await client.call_tool(
                    f"siigo_update_{tool}", {"id": created["id"], "body": {"x": 2}}
                )
            )
            assert changed == {"x": 2, "id": created["id"]}
    assert created["x"] == 1
    assert posts(mock_siigo)[0] == f"/v1/{resource}"
    assert len(approver.requests) == (2 if update else 1)  # every write was approved


async def test_update_invoice_reaches_siigo(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo
) -> None:
    switch.enable(accepted_responsibility=True)
    (invoice,) = mock_siigo.seed("invoices", 1)
    async with Client(server) as client:
        result = payload(
            await client.call_tool(
                "siigo_update_invoice", {"id": invoice["id"], "body": {"observations": "new"}}
            )
        )
    assert result == {"observations": "new", "id": invoice["id"]}
    request = mock_siigo.requests[-1]
    assert request.method == "PUT"
    assert "Idempotency-Key" not in request.headers  # only POST creations carry it


# ---------------------------------------------------------------------- phase 13: delete, annul


@pytest.mark.parametrize(
    ("tool", "resource"),
    [
        ("siigo_delete_product", "products"),
        ("siigo_delete_invoice", "invoices"),
        ("siigo_delete_quotation", "quotations"),
        ("siigo_delete_purchase", "purchases"),
        ("siigo_delete_support_document", "purchase-support-documents"),
        ("siigo_delete_payment_receipt", "payment-receipts"),
    ],
)
async def test_delete_shows_the_record_then_deletes(
    server: SiigoMCPServer,
    switch: WriteSwitch,
    mock_siigo: MockSiigo,
    approver: ScriptedApprover,
    tool: str,
    resource: str,
) -> None:
    from mcp_siigo_unofficial.server.catalog import Risk

    switch.enable(accepted_responsibility=True)
    record = mock_siigo._create(resource, {"name": "FV-1-7", "total": 119000, "date": "2026-11-27"})
    async with Client(server) as client:
        result = payload(await client.call_tool(tool, {"id": record["id"]}))
    assert result == {"id": record["id"], "deleted": True}
    assert record["id"] not in mock_siigo.data[resource]
    (request,) = approver.requests
    assert request.risk is Risk.PERMANENT
    assert request.summary == [
        ("id", record["id"]),
        ("name", record["name"]),  # the mock names invoices itself
        ("date", "2026-11-27"),
        ("total", "119000"),
    ]


async def test_annul_invoice(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo, approver: ScriptedApprover
) -> None:
    switch.enable(accepted_responsibility=True)
    invoice = mock_siigo._create(
        "invoices", {"customer": {"identification": "13832081", "name": ["Ana", "Ruiz"]}}
    )
    async with Client(server) as client:
        result = payload(await client.call_tool("siigo_annul_invoice", {"id": invoice["id"]}))
    assert result == {"id": invoice["id"], "Annul": True}
    assert mock_siigo.data["invoices"][invoice["id"]]["annulled"] is True
    assert ("customer", "Ana Ruiz · 13832081") in approver.requests[0].summary
    annul = mock_siigo.requests[-1]
    assert annul.url.path.endswith("/annul")
    assert "Idempotency-Key" not in annul.headers


async def test_missing_record_is_never_deleted_or_asked(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo, approver: ScriptedApprover
) -> None:
    switch.enable(accepted_responsibility=True)
    async with Client(server) as client:
        result = await client.call_tool("siigo_delete_product", {"id": "missing-id"})
    assert result.is_error
    assert payload(result)["error"]["code"] == "record_not_readable"
    assert approver.requests == []
    assert not any(r.method == "DELETE" for r in mock_siigo.requests)


async def test_rejected_delete_sends_nothing(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo, approver: ScriptedApprover
) -> None:
    switch.enable(accepted_responsibility=True)
    approver.outcome = Outcome.REJECTED
    (product,) = mock_siigo.seed("products", 1)
    async with Client(server) as client:
        result = payload(await client.call_tool("siigo_delete_product", {"id": product["id"]}))
    assert result["status"] == "rejected_by_user"
    assert product["id"] in mock_siigo.data["products"]
    assert not any(r.method == "DELETE" for r in mock_siigo.requests)


# ---------------------------------------------------------------------- phase 14: email, webhooks


async def test_send_invoice_email(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo, approver: ScriptedApprover
) -> None:
    from mcp_siigo_unofficial.server.catalog import Risk

    switch.enable(accepted_responsibility=True)
    (invoice,) = mock_siigo.seed("invoices", 1)
    copies = "contabilidad@example.com;gerencia-con-un-nombre-largo@" + "x" * 70 + ".example.com"
    body = {"mail_to": "cliente@example.com", "copy_to": copies}
    async with Client(server) as client:
        result = payload(
            await client.call_tool("siigo_send_invoice_email", {"id": invoice["id"], "body": body})
        )
    assert result == {"status": "sent", "observations": ""}
    assert mock_siigo.mails == [{"invoice": invoice["id"], **body}]
    (request,) = approver.requests
    assert request.risk is Risk.OUTBOUND
    assert ("copy_to", copies) in request.summary  # every address, whole


async def test_invoice_email_to_more_than_five_addresses_is_refused(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo, approver: ScriptedApprover
) -> None:
    switch.enable(accepted_responsibility=True)
    body = {"mail_to": "a@example.com", "copy_to": ";".join(f"c{i}@example.com" for i in range(5))}
    async with Client(server) as client:
        result = await client.call_tool("siigo_send_invoice_email", {"id": "F1", "body": body})
    assert result.is_error
    assert "at most 5 addresses" in payload(result)["error"]["message"]
    assert approver.requests == []
    assert mock_siigo.mails == []


async def test_webhook_life_cycle(
    server: SiigoMCPServer, switch: WriteSwitch, mock_siigo: MockSiigo, approver: ScriptedApprover
) -> None:
    from mcp_siigo_unofficial.server.catalog import Risk

    switch.enable(accepted_responsibility=True)
    hook = {
        "application_id": "MyShop",
        "topic": "public.siigoapi.products.create",
        "url": "https://shop.example.com/siigo",
    }
    async with Client(server) as client:
        created = payload(await client.call_tool("siigo_create_webhook", {"body": hook}))
        updated = payload(
            await client.call_tool(
                "siigo_update_webhook", {"body": {**hook, "url": "https://shop.example.com/v2"}}
            )
        )
        deleted = payload(await client.call_tool("siigo_delete_webhook", {"id": created["id"]}))
    assert updated["url"] == "https://shop.example.com/v2"
    assert deleted == {"id": created["id"], "deleted": True}
    assert mock_siigo.data["webhooks"] == {}
    create, update, delete = approver.requests
    assert (create.risk, update.risk, delete.risk) == (
        Risk.OUTBOUND,
        Risk.OUTBOUND,
        Risk.PERMANENT,
    )
    assert ("url", "https://shop.example.com/siigo") in create.summary
    # The delete window shows the subscription, found in the webhook list.
    assert ("topic", "public.siigoapi.products.create") in delete.summary
    assert ("url", "https://shop.example.com/v2") in delete.summary


@pytest.mark.parametrize("url", ["http://shop.example.com/siigo", "ftp://x", "shop.example.com"])
async def test_webhook_url_must_be_https(
    server: SiigoMCPServer, switch: WriteSwitch, approver: ScriptedApprover, url: str
) -> None:
    switch.enable(accepted_responsibility=True)
    body = {"application_id": "A", "topic": "public.siigoapi.products.create", "url": url}
    async with Client(server) as client:
        result = await client.call_tool("siigo_create_webhook", {"body": body})
    assert result.is_error
    assert approver.requests == []


def test_invoice_batch_stays_out() -> None:
    assert not any(t.path == "/v1/invoices/batch" for t in CATALOG.tools)  # decision A5
