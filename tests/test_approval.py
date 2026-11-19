"""Write approval: the broker, grants, the stdio route to the tray app (plan section 5.1)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from conftest import FakeClock
from mcp_siigo_unofficial.app.runtime import AppRuntime
from mcp_siigo_unofficial.server.approval import (
    APPROVAL_TIMEOUT_S,
    SIMILAR_GRANT_S,
    ApprovalBroker,
    ApprovalRequest,
    Decision,
    Outcome,
    RemoteApprover,
    summarize,
)
from mcp_siigo_unofficial.server.transport import HOST, tray_approver
from mcp_siigo_unofficial.vault import MemoryKeyStore
from test_transport import free_port

pytestmark = pytest.mark.anyio


def make_request(
    tool: str = "siigo_create_product", connection: str = "c1", **kw: object
) -> ApprovalRequest:
    values: dict[str, object] = {
        "tool": tool,
        "title": "Create product",
        "method": "POST",
        "url": "https://api.siigo.test/v1/products",
        "query": {},
        "body": {"code": "P1"},
        "summary": [("code", "P1")],
        "client": "Claude Desktop",
        "connection": connection,
    }
    values.update(kw)
    return ApprovalRequest(**values)  # type: ignore[arg-type]


def answer_with(broker: ApprovalBroker, decision: Decision) -> list[ApprovalRequest]:
    """A fake window that answers from another thread, like the Qt main thread does."""
    shown: list[ApprovalRequest] = []

    def ask(request: ApprovalRequest) -> None:
        shown.append(request)
        threading.Timer(0.01, broker.answer, args=(request.id, decision)).start()

    broker.on_ask = ask
    return shown


# ---------------------------------------------------------------------- broker
async def test_no_window_means_unavailable() -> None:
    assert await ApprovalBroker().request(make_request()) is Outcome.UNAVAILABLE


@pytest.mark.parametrize(
    ("decision", "outcome"),
    [
        (Decision.APPROVE, Outcome.APPROVED),
        (Decision.REJECT, Outcome.REJECTED),
        (Decision.APPROVE_SIMILAR, Outcome.APPROVED_SIMILAR),
    ],
)
async def test_window_answers(decision: Decision, outcome: Outcome) -> None:
    broker = ApprovalBroker()
    shown = answer_with(broker, decision)
    assert await broker.request(make_request()) is outcome
    assert len(shown) == 1
    assert broker.pending_ids() == []


async def test_timeout_closes_the_window_and_sends_nothing() -> None:
    broker = ApprovalBroker()
    closed: list[str] = []
    broker.on_ask = lambda request: None  # nobody answers
    broker.on_close = closed.append
    request = make_request(timeout_s=0.05)
    assert await broker.request(request) is Outcome.TIMEOUT
    assert closed == [request.id]
    assert broker.answer(request.id, Decision.APPROVE) is False  # too late


async def test_a_failing_window_is_unavailable() -> None:
    broker = ApprovalBroker()

    def broken(request: ApprovalRequest) -> None:
        raise RuntimeError("no display")

    broker.on_ask = broken
    assert await broker.request(make_request()) is Outcome.UNAVAILABLE


async def test_similar_grant_covers_only_the_same_tool_and_connection(clock: FakeClock) -> None:
    broker = ApprovalBroker(clock=clock)
    changes: list[int] = []
    broker.on_grants_changed = lambda: changes.append(1)
    shown = answer_with(broker, Decision.APPROVE_SIMILAR)
    assert await broker.request(make_request()) is Outcome.APPROVED_SIMILAR
    assert await broker.request(make_request()) is Outcome.GRANTED
    assert len(shown) == 1
    answer_with(broker, Decision.REJECT)
    assert await broker.request(make_request(connection="c2")) is Outcome.REJECTED
    assert await broker.request(make_request(tool="siigo_create_invoice")) is Outcome.REJECTED
    assert len(broker.grants()) == 1
    assert broker.seconds_left(broker.grants()[0]) == SIMILAR_GRANT_S
    clock.now += SIMILAR_GRANT_S - 1
    assert await broker.request(make_request()) is Outcome.GRANTED
    clock.now += 2  # the 10 minutes are over
    assert broker.grants() == []
    assert await broker.request(make_request()) is Outcome.REJECTED
    assert changes == [1]


async def test_stop_grants_now() -> None:
    broker = ApprovalBroker()
    answer_with(broker, Decision.APPROVE_SIMILAR)
    await broker.request(make_request())
    broker.stop_grants()
    assert broker.grants() == []
    answer_with(broker, Decision.REJECT)
    assert await broker.request(make_request()) is Outcome.REJECTED


def test_request_json_round_trip_and_timeout_cap() -> None:
    request = make_request(body={"items": [1, 2]}, query={"a": "1"})
    again = ApprovalRequest.from_json(request.to_json())
    assert again == request
    longer = ApprovalRequest.from_json({**request.to_json(), "timeout_s": 9999})
    assert longer.timeout_s == APPROVAL_TIMEOUT_S


def test_summary_fields() -> None:
    body = {
        "document": {"id": 24446},
        "customer": {"identification": "13832081"},
        "date": "2026-11-19",
        "items": [{"code": "A"}, {"code": "B"}],
        "observations": "x" * 200,
    }
    pairs = dict(summarize({"id": "abc"}, body))
    assert pairs["id"] == "abc"
    assert pairs["document"] == "24446"
    assert pairs["customer"] == "13832081"
    assert pairs["items"] == "2 item(s)"
    assert len(pairs["observations"]) == 80


# ---------------------------------------------------------------------- stdio -> tray
@pytest.fixture
def running_runtime(tmp_path: Path) -> Iterator[AppRuntime]:
    rt = AppRuntime.open(tmp_path / "vault.sqlite3", MemoryKeyStore())
    rt.port = free_port()
    rt.vault.set_setting("mcp.port", rt.port)
    assert rt.start_server()
    try:
        yield rt
    finally:
        rt.shutdown()


async def test_stdio_server_asks_the_tray_window(running_runtime: AppRuntime) -> None:
    rt = running_runtime
    rt.write_switch.enable(accepted_responsibility=True)
    shown = answer_with(rt.approvals, Decision.APPROVE)
    approver = tray_approver(rt.vault)
    assert await approver.approve(make_request()) is Outcome.APPROVED
    assert shown[0].client == "Claude Desktop"
    answer_with(rt.approvals, Decision.REJECT)
    assert await approver.approve(make_request()) is Outcome.REJECTED


async def test_tray_route_refuses_while_writes_are_off(running_runtime: AppRuntime) -> None:
    shown = answer_with(running_runtime.approvals, Decision.APPROVE)
    assert await tray_approver(running_runtime.vault).approve(make_request()) is (
        Outcome.UNAVAILABLE
    )
    assert shown == []


async def test_tray_route_needs_the_bearer_key(running_runtime: AppRuntime) -> None:
    rt = running_runtime
    rt.write_switch.enable(accepted_responsibility=True)
    shown = answer_with(rt.approvals, Decision.APPROVE)
    wrong = RemoteApprover(lambda: f"http://{HOST}:{rt.port}", lambda: "x" * 32)
    assert await wrong.approve(make_request()) is Outcome.UNAVAILABLE
    assert shown == []


async def test_tray_not_running_is_unavailable(tmp_path: Path) -> None:
    rt = AppRuntime.open(tmp_path / "vault.sqlite3", MemoryKeyStore())
    try:
        rt.vault.set_setting("mcp.port", free_port())  # nothing listens there
        assert await tray_approver(rt.vault).approve(make_request()) is Outcome.UNAVAILABLE
    finally:
        rt.shutdown()


def test_grants_end_when_write_actions_turn_off(tmp_path: Path) -> None:
    rt = AppRuntime.open(tmp_path / "vault.sqlite3", MemoryKeyStore())
    try:
        rt.write_switch.enable(accepted_responsibility=True)
        rt.approvals._start_grant(make_request())
        assert rt.approvals.grants()
        rt.write_switch.disable()
        assert rt.approvals.grants() == []
    finally:
        rt.shutdown()
