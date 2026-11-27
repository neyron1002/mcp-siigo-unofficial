"""Write approval (plan section 5.1, decisions W1-W10 of 2026-11-19).

Every write needs a person's approval, in the mode the user chose in Settings
(:class:`ApprovalMode`): the **Siigo approval window** (default), a notification that
opens it, or the AI app's own question (MCP elicitation) with the window as fallback.
The user can also start, in the app only, "approve similar writes for 10 minutes" or
automatic approval for 1 hour / until the end of today (max 100 writes). The pieces
here have no Qt:

- :class:`ApprovalRequest` describes one write: the tool, the request, a short
  summary for the window, and the AI app connection that asked.
- :class:`ApprovalBroker` lives in the tray process. It hands each request to the
  window (a callback set by the tray), waits up to 2 minutes for the answer, and
  keeps the "approve similar writes for 10 minutes" grants.
- :class:`LocalApprover` is used by the HTTP server inside the tray process.
  :class:`RemoteApprover` is used by ``--stdio`` servers: it asks the tray app
  through a private route on its local HTTP server (same bearer key).

If nobody can show the window (no tray app, no UI), the answer is
:attr:`Outcome.UNAVAILABLE` and nothing is sent to Siigo.

Risk levels (API coverage plan, decisions A2-A4 of 2026-11-27): only plain creates and
updates (:attr:`Risk.CHANGE`) can be approved by "similar writes" or automatic
approval. Writes that can't be undone (:attr:`Risk.PERMANENT`) and writes that send
data outside Siigo (:attr:`Risk.OUTBOUND`) are approved one by one. The tray app
takes the risk level from its own catalog, so a request can't lower it.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import enum
import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

import httpx2

from mcp_siigo_unofficial.server.catalog import Risk, risk_of

log = logging.getLogger(__name__)

APPROVAL_TIMEOUT_S = 120.0  # W6: the window waits 2 minutes
SIMILAR_GRANT_S = 600.0  # W4: approve similar writes for 10 minutes
AUTOMATIC_MAX_WRITES = 100  # W5
AUTOMATIC_CONFIRM_TEXT = "APPROVE ALL"  # W5: typed to turn automatic approval on
APPROVE_PATH = "/app/approve"
PREAPPROVED_PATH = "/app/preapproved"
SETTING_APPROVAL_MODE = "write_approval.mode"


class ApprovalMode(enum.StrEnum):
    """How each write is approved (Settings → Write approval; only the user changes it)."""

    SIIGO_WINDOW = "siigo_window"
    NOTIFICATION = "notification"
    AI_APP = "ai_app"

    @classmethod
    def parse(cls, value: object) -> ApprovalMode:
        try:
            return cls(str(value))
        except ValueError:
            return cls.SIIGO_WINDOW


class AutomaticSpan(enum.StrEnum):
    HOUR = "hour"
    TODAY = "today"


def automatic_seconds(span: AutomaticSpan, now: dt.datetime | None = None) -> float:
    """Length of an automatic approval: 1 hour, or until local midnight."""
    if span is AutomaticSpan.HOUR:
        return 3600.0
    current = now or dt.datetime.now().astimezone()
    midnight = (current + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60.0, (midnight - current).total_seconds())


_REMOTE_MARGIN_S = 15.0


class Outcome(enum.StrEnum):
    APPROVED = "approved"
    APPROVED_SIMILAR = "approved_similar"  # approved, and a 10-minute grant was started
    GRANTED = "granted"  # covered by an earlier "approve similar writes" grant
    REJECTED = "rejected"
    AUTOMATIC = "automatic"  # automatic approval for a limited time (W5)
    AI_APP = "ai_app"  # approved in the AI app's own question (elicitation)
    REJECTED_IN_APP = "rejected_in_app"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"

    @property
    def approved(self) -> bool:
        return self in (
            Outcome.APPROVED,
            Outcome.APPROVED_SIMILAR,
            Outcome.GRANTED,
            Outcome.AUTOMATIC,
            Outcome.AI_APP,
        )


class Decision(enum.StrEnum):
    """What the person clicked in the window."""

    APPROVE = "approve"
    APPROVE_SIMILAR = "approve_similar"
    REJECT = "reject"


@dataclass(frozen=True)
class ApprovalRequest:
    """One write waiting for approval. Holds no secrets (the body is the AI's input)."""

    tool: str
    title: str
    method: str
    url: str
    query: dict[str, Any]
    body: Any
    summary: list[tuple[str, str]]
    client: str
    connection: str
    timeout_s: float = APPROVAL_TIMEOUT_S
    id: str = field(default_factory=lambda: secrets.token_urlsafe(9))
    risk: Risk = Risk.CHANGE

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["summary"] = [list(pair) for pair in self.summary]
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ApprovalRequest:
        summary = [(str(k), str(v)) for k, v in data.get("summary", [])]
        tool = str(data["tool"])
        return cls(
            tool=tool,
            title=str(data["title"]),
            method=str(data["method"]),
            url=str(data["url"]),
            query=dict(data.get("query") or {}),
            body=data.get("body"),
            summary=summary,
            client=str(data.get("client") or "?"),
            connection=str(data.get("connection") or "?"),
            timeout_s=min(float(data.get("timeout_s", APPROVAL_TIMEOUT_S)), APPROVAL_TIMEOUT_S),
            id=str(data.get("id") or secrets.token_urlsafe(9)),
            # The tray's own catalog decides; a request can only make it stricter.
            risk=Risk.strictest(Risk.parse(data.get("risk", "change")), risk_of(tool)),
        )


class Approver(Protocol):
    async def approve(self, request: ApprovalRequest) -> Outcome: ...

    async def preapproved(self, request: ApprovalRequest) -> Outcome | None:
        """GRANTED or AUTOMATIC if no question is needed (consumes it), else None."""
        ...


#: The tray sets this: show the window for ``request`` and call ``answer`` with the
#: decision (from any thread). ``closed`` is called if the window must close (timeout).
AskCallback = Callable[[ApprovalRequest], None]
CloseCallback = Callable[[str], None]


@dataclass
class Grant:
    tool: str
    connection: str
    title: str
    expires_at: float


@dataclass
class Automatic:
    """Automatic approval of every write until ``expires_at`` or ``writes_left`` is 0."""

    span: AutomaticSpan
    expires_at: float
    writes_left: int
    writes_used: int = 0


EventSink = Callable[[str, dict[str, Any]], object]


class ApprovalBroker:
    """Shows approval requests in the tray app and collects the answers. Thread-safe."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Future[Decision]]] = {}
        self._grants: dict[tuple[str, str], Grant] = {}
        self._automatic: Automatic | None = None
        self.on_ask: AskCallback | None = None
        self.on_close: CloseCallback | None = None
        self.on_grants_changed: Callable[[], None] | None = None
        self.on_event: EventSink | None = None

    # ------------------------------------------------------------------ automatic
    def automatic(self) -> Automatic | None:
        """The active automatic approval, or None (an expired one ends here)."""
        with self._lock:
            auto = self._automatic
            if auto is None or auto.expires_at > self._clock():
                return auto
            self._automatic = None
        self._ended(auto, "time_limit")
        return None

    def start_automatic(self, span: AutomaticSpan, *, confirm_text: str) -> Automatic:
        """Turn on automatic approval. Only the app's own dialog calls this (W5, W8)."""
        if confirm_text != AUTOMATIC_CONFIRM_TEXT:
            raise ValueError(f"Type {AUTOMATIC_CONFIRM_TEXT} to confirm.")
        seconds = automatic_seconds(span)
        auto = Automatic(span, self._clock() + seconds, AUTOMATIC_MAX_WRITES)
        with self._lock:
            self._automatic = auto
        self._event(
            "write_approval.automatic_on",
            {"span": span.value, "seconds": int(seconds), "max_writes": AUTOMATIC_MAX_WRITES},
        )
        self._grants_changed()
        return auto

    def stop_automatic(self, reason: str = "stopped") -> None:
        with self._lock:
            auto, self._automatic = self._automatic, None
        if auto is not None:
            self._ended(auto, reason)

    def _ended(self, auto: Automatic, reason: str) -> None:
        self._event(
            "write_approval.automatic_off", {"reason": reason, "writes_used": auto.writes_used}
        )
        self._grants_changed()

    def _event(self, kind: str, detail: dict[str, Any]) -> None:
        sink = self.on_event
        if sink is not None:
            try:
                sink(kind, detail)
            except Exception:
                log.exception("Approval event could not be recorded")

    def preapproved(self, request: ApprovalRequest) -> Outcome | None:
        """AUTOMATIC (uses one of the writes left) or GRANTED, else None.

        Permanent and outbound writes are never pre-approved, and don't use up a write.
        """
        if not request.risk.allows_shortcuts:
            return None
        if self.automatic() is not None:
            ended: Automatic | None = None
            with self._lock:
                auto = self._automatic
                if auto is not None:
                    auto.writes_left -= 1
                    auto.writes_used += 1
                    if auto.writes_left <= 0:
                        ended, self._automatic = auto, None
            if auto is not None:
                if ended is not None:
                    self._ended(ended, "write_limit")
                return Outcome.AUTOMATIC
        if self._granted(request):
            return Outcome.GRANTED
        return None

    # ------------------------------------------------------------------ grants
    def grants(self) -> list[Grant]:
        """Active "approve similar writes" grants (expired ones are dropped)."""
        now = self._clock()
        with self._lock:
            for key in [k for k, g in self._grants.items() if g.expires_at <= now]:
                del self._grants[key]
            return sorted(self._grants.values(), key=lambda g: g.expires_at)

    def seconds_left(self, grant: Grant) -> float:
        return max(0.0, grant.expires_at - self._clock())

    def seconds_left_until(self, expires_at: float) -> float:
        return max(0.0, expires_at - self._clock())

    def _granted(self, request: ApprovalRequest) -> bool:
        return any(
            g.tool == request.tool and g.connection == request.connection for g in self.grants()
        )

    def _start_grant(self, request: ApprovalRequest) -> None:
        with self._lock:
            self._grants[(request.tool, request.connection)] = Grant(
                request.tool, request.connection, request.title, self._clock() + SIMILAR_GRANT_S
            )
        self._grants_changed()

    def stop_grants(self) -> None:
        """Stop now: end every grant (also called when write actions turn off)."""
        with self._lock:
            had = bool(self._grants)
            self._grants.clear()
        if had:
            self._grants_changed()

    def _grants_changed(self) -> None:
        callback = self.on_grants_changed
        if callback is not None:
            try:
                callback()
            except Exception:
                log.exception("Grant listener failed")

    # ------------------------------------------------------------------ requests
    async def request(self, request: ApprovalRequest) -> Outcome:
        """Ask the person. Returns when they answer, the time runs out, or no UI exists."""
        early = self.preapproved(request)
        if early is not None:
            return early
        ask = self.on_ask
        if ask is None:
            return Outcome.UNAVAILABLE
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Decision] = loop.create_future()
        with self._lock:
            self._pending[request.id] = (loop, future)
        try:
            ask(request)
        except Exception:
            log.exception("The approval window could not be shown")
            with self._lock:
                self._pending.pop(request.id, None)
            return Outcome.UNAVAILABLE
        try:
            decision = await asyncio.wait_for(future, timeout=request.timeout_s)
        except TimeoutError:
            self._close(request.id)
            return Outcome.TIMEOUT
        except asyncio.CancelledError:
            self._close(request.id)
            raise
        finally:
            with self._lock:
                self._pending.pop(request.id, None)
        if decision is Decision.APPROVE_SIMILAR and request.risk.allows_shortcuts:
            self._start_grant(request)
            return Outcome.APPROVED_SIMILAR
        if decision is Decision.APPROVE_SIMILAR:  # no grant for risky writes
            return Outcome.APPROVED
        if decision is Decision.APPROVE:
            return Outcome.APPROVED
        return Outcome.REJECTED

    def answer(self, request_id: str, decision: Decision) -> bool:
        """The window's answer (any thread). False if the request is gone (timed out)."""
        with self._lock:
            entry = self._pending.get(request_id)
        if entry is None:
            return False
        loop, future = entry

        def resolve() -> None:
            if not future.done():
                future.set_result(decision)

        loop.call_soon_threadsafe(resolve)
        return True

    def pending_ids(self) -> list[str]:
        with self._lock:
            return list(self._pending)

    def _close(self, request_id: str) -> None:
        callback = self.on_close
        if callback is not None:
            try:
                callback(request_id)
            except Exception:
                log.exception("The approval window could not be closed")


class LocalApprover:
    """Approver for the HTTP server inside the tray process."""

    def __init__(self, broker: ApprovalBroker) -> None:
        self.broker = broker

    async def approve(self, request: ApprovalRequest) -> Outcome:
        return await self.broker.request(request)

    async def preapproved(self, request: ApprovalRequest) -> Outcome | None:
        return self.broker.preapproved(request)


class UnavailableApprover:
    """No window can be shown (headless ``--serve``, tests): every write is refused."""

    async def approve(self, request: ApprovalRequest) -> Outcome:
        del request
        return Outcome.UNAVAILABLE

    async def preapproved(self, request: ApprovalRequest) -> Outcome | None:
        del request
        return None


class RemoteApprover:
    """Approver for ``--stdio`` servers: asks the running tray app over 127.0.0.1."""

    def __init__(self, base_url: Callable[[], str | None], bearer_key: Callable[[], str | None]):
        self._base_url = base_url
        self._bearer_key = bearer_key

    async def _post(self, path: str, request: ApprovalRequest, timeout: float) -> Any:
        base, key = self._base_url(), self._bearer_key()
        if not base or not key:
            return None
        try:
            async with httpx2.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{base}{path}",
                    json=request.to_json(),
                    headers={"Authorization": f"Bearer {key}"},
                )
        except httpx2.HTTPError as exc:
            log.warning("The Siigo app is not reachable for approval: %s", type(exc).__name__)
            return None
        if response.status_code != 200:
            log.warning("Approval route answered HTTP %s", response.status_code)
            return None
        try:
            return response.json()
        except ValueError:
            return None

    async def approve(self, request: ApprovalRequest) -> Outcome:
        data = await self._post(APPROVE_PATH, request, request.timeout_s + _REMOTE_MARGIN_S)
        try:
            return Outcome(data["outcome"])
        except (ValueError, KeyError, TypeError):
            return Outcome.UNAVAILABLE

    async def preapproved(self, request: ApprovalRequest) -> Outcome | None:
        data = await self._post(PREAPPROVED_PATH, request, _REMOTE_MARGIN_S)
        try:
            value = data["outcome"]
            return None if value is None else Outcome(value)
        except (ValueError, KeyError, TypeError):
            return None


def summarize(
    path_values: dict[str, str], body: Any, limit: int = 6, *, full: bool = False
) -> list[tuple[str, str]]:
    """Main fields for the window (W7): path ids, then simple body fields.

    ``full`` (writes that send data outside Siigo) keeps every simple field whole, so
    the person sees each email address and URL exactly.
    """
    pairs: list[tuple[str, str]] = [(k, v) for k, v in path_values.items() if v]
    if full:
        limit = max(limit, 12)
    if isinstance(body, dict):
        for key, value in body.items():
            if len(pairs) >= limit:
                break
            if isinstance(value, str | int | float | bool) and value != "":
                pairs.append((key, str(value) if full else _short(str(value))))
            elif isinstance(value, dict):
                ident = value.get("identification") or value.get("code") or value.get("id")
                if ident is not None:
                    pairs.append((key, _short(str(ident))))
            elif isinstance(value, list):
                pairs.append((key, f"{len(value)} item(s)"))
    return pairs[:limit]


def _short(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
