"""Write approval (plan section 5.1, decisions W1-W10 of 2026-11-19).

Every write waits for a person's answer in the **Siigo approval window**, which the
tray app shows. The pieces here have no Qt:

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
"""

from __future__ import annotations

import asyncio
import enum
import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

import httpx2

log = logging.getLogger(__name__)

APPROVAL_TIMEOUT_S = 120.0  # W6: the window waits 2 minutes
SIMILAR_GRANT_S = 600.0  # W4: approve similar writes for 10 minutes
APPROVE_PATH = "/app/approve"
_REMOTE_MARGIN_S = 15.0


class Outcome(enum.StrEnum):
    APPROVED = "approved"
    APPROVED_SIMILAR = "approved_similar"  # approved, and a 10-minute grant was started
    GRANTED = "granted"  # covered by an earlier "approve similar writes" grant
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"

    @property
    def approved(self) -> bool:
        return self in (Outcome.APPROVED, Outcome.APPROVED_SIMILAR, Outcome.GRANTED)


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

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["summary"] = [list(pair) for pair in self.summary]
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ApprovalRequest:
        summary = [(str(k), str(v)) for k, v in data.get("summary", [])]
        return cls(
            tool=str(data["tool"]),
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
        )


class Approver(Protocol):
    async def approve(self, request: ApprovalRequest) -> Outcome: ...


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


class ApprovalBroker:
    """Shows approval requests in the tray app and collects the answers. Thread-safe."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Future[Decision]]] = {}
        self._grants: dict[tuple[str, str], Grant] = {}
        self.on_ask: AskCallback | None = None
        self.on_close: CloseCallback | None = None
        self.on_grants_changed: Callable[[], None] | None = None

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
        if self._granted(request):
            return Outcome.GRANTED
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
        if decision is Decision.APPROVE_SIMILAR:
            self._start_grant(request)
            return Outcome.APPROVED_SIMILAR
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


class UnavailableApprover:
    """No window can be shown (headless ``--serve``, tests): every write is refused."""

    async def approve(self, request: ApprovalRequest) -> Outcome:
        del request
        return Outcome.UNAVAILABLE


class RemoteApprover:
    """Approver for ``--stdio`` servers: asks the running tray app over 127.0.0.1."""

    def __init__(self, base_url: Callable[[], str | None], bearer_key: Callable[[], str | None]):
        self._base_url = base_url
        self._bearer_key = bearer_key

    async def approve(self, request: ApprovalRequest) -> Outcome:
        base, key = self._base_url(), self._bearer_key()
        if not base or not key:
            return Outcome.UNAVAILABLE
        try:
            async with httpx2.AsyncClient(timeout=request.timeout_s + _REMOTE_MARGIN_S) as client:
                response = await client.post(
                    f"{base}{APPROVE_PATH}",
                    json=request.to_json(),
                    headers={"Authorization": f"Bearer {key}"},
                )
        except httpx2.HTTPError as exc:
            log.warning("The Siigo app is not reachable for approval: %s", type(exc).__name__)
            return Outcome.UNAVAILABLE
        if response.status_code != 200:
            log.warning("Approval route answered HTTP %s", response.status_code)
            return Outcome.UNAVAILABLE
        try:
            return Outcome(response.json()["outcome"])
        except (ValueError, KeyError, TypeError):
            return Outcome.UNAVAILABLE


def summarize(path_values: dict[str, str], body: Any, limit: int = 6) -> list[tuple[str, str]]:
    """Main fields for the window (W7): path ids, then simple body fields."""
    pairs: list[tuple[str, str]] = [(k, v) for k, v in path_values.items() if v]
    if isinstance(body, dict):
        for key, value in body.items():
            if len(pairs) >= limit:
                break
            if isinstance(value, str | int | float | bool) and value != "":
                pairs.append((key, _short(str(value))))
            elif isinstance(value, dict):
                ident = value.get("identification") or value.get("code") or value.get("id")
                if ident is not None:
                    pairs.append((key, _short(str(ident))))
            elif isinstance(value, list):
                pairs.append((key, f"{len(value)} item(s)"))
    return pairs[:limit]


def _short(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
