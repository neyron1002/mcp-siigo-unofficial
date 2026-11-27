"""Write approval: the broker, grants, the stdio route to the tray app (plan section 5.1)."""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from conftest import FakeClock
from mcp_siigo_unofficial.app.runtime import AppRuntime
from mcp_siigo_unofficial.server.approval import (
    APPROVAL_TIMEOUT_S,
    AUTOMATIC_CONFIRM_TEXT,
    AUTOMATIC_MAX_WRITES,
    SIMILAR_GRANT_S,
    ApprovalBroker,
    ApprovalMode,
    ApprovalRequest,
    AutomaticSpan,
    Decision,
    Outcome,
    RemoteApprover,
    automatic_seconds,
    summarize,
)
from mcp_siigo_unofficial.server.catalog import Risk
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


# ---------------------------------------------------------------------- v0.1.2: modes
def test_mode_parse_defaults_to_the_window() -> None:
    assert ApprovalMode.parse("ai_app") is ApprovalMode.AI_APP
    assert ApprovalMode.parse(None) is ApprovalMode.SIIGO_WINDOW
    assert ApprovalMode.parse("anything") is ApprovalMode.SIIGO_WINDOW


def test_automatic_spans() -> None:
    assert automatic_seconds(AutomaticSpan.HOUR) == 3600
    evening = dt.datetime(2026, 11, 19, 22, 30, tzinfo=dt.UTC)
    assert automatic_seconds(AutomaticSpan.TODAY, evening) == 90 * 60
    almost = dt.datetime(2026, 11, 19, 23, 59, 50, tzinfo=dt.UTC)
    assert automatic_seconds(AutomaticSpan.TODAY, almost) == 60  # at least a minute


async def test_automatic_needs_the_exact_text() -> None:
    broker = ApprovalBroker()
    for wrong in ("", "approve all", "APPROVE  ALL", "APROBAR TODO"):
        with pytest.raises(ValueError, match="APPROVE ALL"):
            broker.start_automatic(AutomaticSpan.HOUR, confirm_text=wrong)
    assert broker.automatic() is None


async def test_automatic_approval_limits_and_log(clock: FakeClock) -> None:
    broker = ApprovalBroker(clock=clock)
    events: list[tuple[str, dict[str, object]]] = []
    broker.on_event = lambda kind, detail: events.append((kind, detail))
    shown = answer_with(broker, Decision.REJECT)
    broker.start_automatic(AutomaticSpan.HOUR, confirm_text=AUTOMATIC_CONFIRM_TEXT)
    for _ in range(AUTOMATIC_MAX_WRITES):
        assert await broker.request(make_request(tool="any", connection="any")) is (
            Outcome.AUTOMATIC
        )
    assert broker.automatic() is None  # the 100-write limit
    assert await broker.request(make_request()) is Outcome.REJECTED
    assert len(shown) == 1
    broker.start_automatic(AutomaticSpan.HOUR, confirm_text=AUTOMATIC_CONFIRM_TEXT)
    clock.now += 3601  # the time limit
    assert broker.preapproved(make_request()) is None
    broker.start_automatic(AutomaticSpan.TODAY, confirm_text=AUTOMATIC_CONFIRM_TEXT)
    broker.stop_automatic()
    assert [(k, d.get("reason")) for k, d in events] == [
        ("write_approval.automatic_on", None),
        ("write_approval.automatic_off", "write_limit"),
        ("write_approval.automatic_on", None),
        ("write_approval.automatic_off", "time_limit"),
        ("write_approval.automatic_on", None),
        ("write_approval.automatic_off", "stopped"),
    ]
    assert events[1][1]["writes_used"] == AUTOMATIC_MAX_WRITES


async def test_preapproved_route_for_stdio(running_runtime: AppRuntime) -> None:
    rt = running_runtime
    approver = tray_approver(rt.vault)
    assert await approver.preapproved(make_request()) is None  # writes off
    rt.write_switch.enable(accepted_responsibility=True)
    assert await approver.preapproved(make_request()) is None
    rt.approvals.start_automatic(AutomaticSpan.HOUR, confirm_text=AUTOMATIC_CONFIRM_TEXT)
    assert await approver.preapproved(make_request()) is Outcome.AUTOMATIC
    automatic = rt.approvals.automatic()
    assert automatic is not None
    assert automatic.writes_used == 1


def test_runtime_mode_setting_and_writes_off(tmp_path: Path) -> None:
    rt = AppRuntime.open(tmp_path / "vault.sqlite3", MemoryKeyStore())
    try:
        assert rt.approval_mode() is ApprovalMode.SIIGO_WINDOW
        rt.set_approval_mode(ApprovalMode.NOTIFICATION)
        rt.set_approval_mode(ApprovalMode.NOTIFICATION)  # no change, no event
        assert rt.approval_mode() is ApprovalMode.NOTIFICATION
        assert [e.detail["mode"] for e in rt.vault.events("write_approval.mode_changed")] == [
            "notification"
        ]
        rt.write_switch.enable(accepted_responsibility=True)
        rt.approvals.start_automatic(AutomaticSpan.HOUR, confirm_text=AUTOMATIC_CONFIRM_TEXT)
        rt.write_switch.disable()
        assert rt.approvals.automatic() is None
        off = rt.vault.events("write_approval.automatic_off")
        assert off[-1].detail["reason"] == "write_actions_off"
    finally:
        rt.shutdown()


def test_automatic_approval_never_survives_a_restart(tmp_path: Path) -> None:
    keystore = MemoryKeyStore()
    rt = AppRuntime.open(tmp_path / "vault.sqlite3", keystore)
    rt.write_switch.enable(accepted_responsibility=True)
    rt.approvals.start_automatic(AutomaticSpan.TODAY, confirm_text=AUTOMATIC_CONFIRM_TEXT)
    rt.shutdown()
    again = AppRuntime.open(tmp_path / "vault.sqlite3", keystore)
    try:
        assert again.approvals.automatic() is None
        assert again.write_switch.enabled is False
    finally:
        again.shutdown()


# ---------------------------------------------------------------------- risk levels (A2-A4)


@pytest.mark.parametrize("risk", [Risk.PERMANENT, Risk.OUTBOUND])
async def test_risky_writes_are_never_preapproved(clock: FakeClock, risk: Risk) -> None:
    broker = ApprovalBroker(clock=clock)
    shown = answer_with(broker, Decision.APPROVE_SIMILAR)
    broker.start_automatic(AutomaticSpan.HOUR, confirm_text=AUTOMATIC_CONFIRM_TEXT)
    risky = make_request(tool="siigo_delete_product", risk=risk)
    assert broker.preapproved(risky) is None
    auto = broker.automatic()
    assert auto is not None
    assert auto.writes_used == 0  # a refused shortcut doesn't use up a write
    # "Approve similar" in the window approves this one request and starts no grant.
    assert await broker.request(risky) is Outcome.APPROVED
    assert broker.grants() == []
    assert len(shown) == 1
    # A plain change still uses automatic approval.
    assert broker.preapproved(make_request()) is Outcome.AUTOMATIC


async def test_a_grant_never_covers_a_risky_write(clock: FakeClock) -> None:
    broker = ApprovalBroker(clock=clock)
    answer_with(broker, Decision.APPROVE_SIMILAR)
    assert await broker.request(make_request()) is Outcome.APPROVED_SIMILAR
    same_tool_but_risky = make_request(risk=Risk.PERMANENT)
    assert broker.preapproved(same_tool_but_risky) is None


def test_the_tray_takes_the_risk_from_its_own_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_siigo_unofficial.server import approval

    levels = {"siigo_delete_product": Risk.PERMANENT, "siigo_create_product": Risk.CHANGE}
    monkeypatch.setattr(approval, "risk_of", lambda tool: levels.get(tool, Risk.PERMANENT))
    lowered = make_request(tool="siigo_delete_product").to_json()
    lowered["risk"] = "change"  # a request can't lower the level
    assert ApprovalRequest.from_json(lowered).risk is Risk.PERMANENT
    raised = make_request(risk=Risk.OUTBOUND).to_json()
    assert ApprovalRequest.from_json(raised).risk is Risk.OUTBOUND  # it can raise it
    unknown = make_request(tool="siigo_something_new").to_json()
    assert ApprovalRequest.from_json(unknown).risk is Risk.PERMANENT
    assert ApprovalRequest.from_json(make_request().to_json()).risk is Risk.CHANGE


def test_outbound_summary_keeps_addresses_whole() -> None:
    long = "a-very-long-mailbox-name-for-a-test@" + "x" * 80 + ".example.com"
    body = {"mail_to": long, "copy_to": "b@example.com;c@example.com"}
    assert summarize({"id": "F1"}, body, full=True) == [
        ("id", "F1"),
        ("mail_to", long),
        ("copy_to", "b@example.com;c@example.com"),
    ]
    assert summarize({}, body)[0][1].endswith("…")
