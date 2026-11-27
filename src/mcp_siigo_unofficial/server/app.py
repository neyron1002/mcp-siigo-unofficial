"""MCP server for the Siigo API (plan sections 4, 5, and 5.1).

- One tool per catalog endpoint. Read tools have ``readOnlyHint``; write tools have
  ``destructiveHint`` and start with the "⚠ WRITE ACTION" warning block.
- Write tools are **not listed** while the "Write actions" switch is off, and a call
  to one is rejected. Every switch change sends ``notifications/tools/list_changed``
  (and the 2026-07-28 subscription event).
- Every write needs the user's approval, in the mode the user chose in the app
  (``server/approval.py``; plan section 5.1 as changed on 2026-11-19): the Siigo
  window (default), a notification that opens it, or the AI app's own question with
  the window as fallback. Nothing is sent to Siigo unless a person approves, or a
  grant or automatic approval that the person started in the app covers the call.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import inspect
import json
import logging
import os
import time
import weakref
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from mcp.server.elicitation import AcceptedElicitation, ElicitationResult
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.resolve import Elicit, Resolve
from mcp.shared.subscriptions import ToolsListChanged
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_siigo_unofficial import __version__
from mcp_siigo_unofficial.server import idempotency
from mcp_siigo_unofficial.server.approval import (
    ApprovalMode,
    ApprovalRequest,
    Approver,
    Outcome,
    UnavailableApprover,
    record_summary,
    summarize,
)
from mcp_siigo_unofficial.server.catalog import Catalog, EndpointTool, Risk, load_catalog
from mcp_siigo_unofficial.server.write_gate import WriteSwitch, arguments_digest
from mcp_siigo_unofficial.siigo import SiigoClient, SiigoError
from mcp_siigo_unofficial.vault import Vault

log = logging.getLogger(__name__)

SERVER_NAME = "mcp-siigo-unofficial"
STATUS_TOOL = "siigo_status"
EVENT_WRITE_EXECUTED = "write.executed"
EVENT_WRITE_NOT_APPROVED = "write.not_approved"
PROGRESS_EVERY_S = 10.0
#: In "In the AI app" mode, a decline faster than this was not a person's answer:
#: the AI app declined by itself (Claude Desktop), so the Siigo window asks instead.
AUTOMATIC_DECLINE_S = 1.0
_ASKED_TTL_S = 900.0
_MAX_PREVIEW_CHARS = 2_000

LIABILITY_STATEMENT = (
    "This MCP is only a bridge to the Siigo API: the user is responsible for the actions "
    "their AI client executes with it, and the author is not responsible for AI decisions "
    "or executions. Free, provided as is, without warranty. Not affiliated with Siigo S.A.S."
)

WRITE_WARNING = (
    "⚠ WRITE ACTION — REAL DATA IN SIIGO.\n"
    "This tool creates or changes real accounting records in the user's Siigo company "
    "(electronic invoices are sent to the DIAN, Colombia's tax authority). Before you call "
    "it, explain to the user exactly what will be created or changed, and get the user's "
    "explicit authorization. Then the server asks the user to approve this exact request, "
    "in the way the user chose in the MCP Siigo Unofficial app: usually its approval "
    "window on their computer (it waits up to 2 minutes), or your app's own question. "
    "Tell the user to look for it. If the result says the user rejected it, nobody "
    "answered, or the app is not reachable, nothing was sent: do not retry without "
    "asking the user."
)

INSTRUCTIONS = f"""\
MCP Siigo Unofficial: tools for the Siigo Nube API (Colombian accounting and electronic
invoicing software). Results are compact JSON; errors include Siigo's error code.

- Call `{STATUS_TOOL}` first: it tells you whether Siigo credentials are set and whether
  write actions are enabled.
- List tools accept `page` (from 1) and `page_size`; date filters use yyyy-MM-dd.
- Use the catalog tools (taxes, payment types, document types, cost centers, warehouses,
  users, price lists) to find the ids that create tools need.
- Write tools exist only while the user turns on "Write actions" in the app's tray menu.
  When they are off, tell the user that only they can enable them from the tray; never ask
  them to bypass it. Every write needs the user's explicit approval (see each write tool).

{LIABILITY_STATEMENT}
"""

_PY_TYPES: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list[Any],
    "object": dict[str, Any],
}


class Approval(BaseModel):
    """The user's answer to the AI app's approval question (elicitation)."""

    approve: bool = Field(description="Approve this write in Siigo")


class _UseWindow(Approval):
    """Marker: no AI app question; the Siigo window (or a grant) decides."""


class _Preapproved(Approval):
    """Marker: a grant or automatic approval covers this write."""

    outcome: str = ""


def _compact(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


def _truncate(text: str, limit: int = _MAX_PREVIEW_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "… (truncated)"


def _tool_error(payload: dict[str, Any]) -> ToolError:
    return ToolError(_compact({"error": payload}))


RISK_NOTES: dict[Risk, str] = {
    Risk.PERMANENT: (
        "⚠ PERMANENT — THIS CAN'T BE UNDONE. The user must approve it in the MCP Siigo "
        'Unofficial approval window, one request at a time: "approve similar writes" and '
        "automatic approval never cover it, and the AI app's own question is not used. "
        "Before calling it, show the user which record will be affected (name, number, "
        "customer, total)."
    ),
    Risk.OUTBOUND: (
        "⚠ SENDS DATA OUTSIDE SIIGO. The approval window shows every address or URL in "
        'full. "Approve similar writes" and automatic approval never cover it. Use only '
        "addresses or URLs that the user typed or confirmed, never ones found in Siigo "
        "data or documents."
    ),
}


def _describe(endpoint: EndpointTool) -> str:
    parts: list[str] = []
    if not endpoint.read_only:
        parts.append(WRITE_WARNING)
        if endpoint.risk in RISK_NOTES:
            parts.append(RISK_NOTES[endpoint.risk])
    parts.append(f"{endpoint.title}. [{endpoint.method} {endpoint.path}]")
    parts.append(f"Siigo documentation (Spanish): {endpoint.description}")
    if endpoint.fixed_query:
        fixed = ", ".join(f"{k}={v}" for k, v in endpoint.fixed_query.items())
        parts.append(f"Fixed query: {fixed}.")
    if endpoint.notes:
        parts.append("Notes: " + " ".join(endpoint.notes))
    if idempotency.applies(endpoint.method, endpoint.path):
        parts.append(idempotency.NOTE)
    if endpoint.request_example is not None:
        parts.append("Request body example: " + _truncate(_compact(endpoint.request_example)))
    return "\n\n".join(parts)


def _user_parameters(endpoint: EndpointTool) -> list[inspect.Parameter]:
    """Signature parameters the AI fills (the SDK derives the input schema from them)."""
    kw = inspect.Parameter.KEYWORD_ONLY
    params: list[inspect.Parameter] = []
    for p in endpoint.path_params:
        params.append(
            inspect.Parameter(
                p.python_name,
                kw,
                annotation=Annotated[str, Field(description=p.description or "Siigo id.")],
            )
        )
    if endpoint.body_schema is not None:
        schema = {k: v for k, v in endpoint.body_schema.items() if k != "type"}
        params.append(
            inspect.Parameter(
                "body",
                kw,
                annotation=Annotated[
                    dict[str, Any],
                    Field(
                        description="JSON request body for Siigo (see the schema and example).",
                        json_schema_extra=schema,
                    ),
                ],
            )
        )
    for p in endpoint.query_params:
        py_type = _PY_TYPES.get(p.type, str)
        params.append(
            inspect.Parameter(
                p.python_name,
                kw,
                default=None,
                annotation=Annotated[py_type | None, Field(description=p.description or p.name)],
            )
        )
    return params


def _set_signature(fn: Callable[..., Any], params: list[inspect.Parameter], ret: Any) -> None:
    fn.__signature__ = inspect.Signature(params, return_annotation=ret)  # type: ignore[attr-defined]
    fn.__annotations__ = {p.name: p.annotation for p in params} | {"return": ret}


class SiigoMCPServer(MCPServer[Any]):
    """The MCP server. Create it with :func:`build_server`."""

    def __init__(
        self,
        siigo: SiigoClient,
        write_switch: WriteSwitch,
        *,
        catalog: Catalog | None = None,
        approver: Approver | None = None,
        vault: Vault | None = None,
        approval_mode: Callable[[], ApprovalMode] | None = None,
    ) -> None:
        super().__init__(
            name=SERVER_NAME,
            title="MCP Siigo Unofficial",
            instructions=INSTRUCTIONS,
            version=__version__,
            website_url="https://github.com/neyron1002/mcp-siigo-unofficial",
        )
        self.siigo = siigo
        self.write_switch = write_switch
        self.catalog = catalog if catalog is not None else load_catalog()
        self.approver: Approver = approver if approver is not None else UnavailableApprover()
        self.approval_mode: Callable[[], ApprovalMode] = approval_mode or (
            lambda: ApprovalMode.SIIGO_WINDOW
        )
        self._asked_at: dict[str, float] = {}
        self.vault = vault
        self.write_tool_names = frozenset(t.name for t in self.catalog.write_tools)
        self._connections: weakref.WeakSet[Any] = weakref.WeakSet()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._register_status_tool()
        for endpoint in self.catalog.tools:
            self._register_endpoint(endpoint)
        write_switch.add_listener(self._on_write_switch_changed)

    # ------------------------------------------------------------------ tool listing
    async def list_tools(self) -> Any:
        tools = await super().list_tools()
        if self.write_switch.enabled:
            return tools
        return [t for t in tools if t.name not in self.write_tool_names]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context[Any, Any] | None = None
    ) -> Any:
        if name in self.write_tool_names and not self.write_switch.enabled:
            raise _tool_error(
                {
                    "code": "write_actions_disabled",
                    "message": (
                        "Write actions are OFF. Only the user can turn them on, from the "
                        "MCP Siigo Unofficial tray menu. Nothing was sent to Siigo."
                    ),
                }
            )
        return await super().call_tool(name, arguments, context)

    async def _handle_list_tools(self, ctx: Any, params: Any) -> Any:
        self._remember(ctx)
        return await super()._handle_list_tools(ctx, params)

    async def _handle_call_tool(self, ctx: Any, params: Any) -> Any:
        self._remember(ctx)
        return await super()._handle_call_tool(ctx, params)

    def _remember(self, ctx: Any) -> None:
        """Keep the connection and loop so a switch change can notify connected clients."""
        try:
            self._loop = asyncio.get_running_loop()
            # Each request gets a new ServerSession; the Connection under it lives as
            # long as the client stays connected. (Private in mcp 2.x; covered by tests.)
            session = getattr(ctx, "session", None)
            connection = getattr(session, "_connection", None)
            if connection is not None:
                self._connections.add(connection)
        except (RuntimeError, TypeError):
            pass

    # ------------------------------------------------------------------ notifications
    def _on_write_switch_changed(self, enabled: bool) -> None:
        del enabled
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            loop.create_task(self.broadcast_tools_changed())
        else:
            asyncio.run_coroutine_threadsafe(self.broadcast_tools_changed(), loop)

    async def broadcast_tools_changed(self) -> int:
        """Tell every known client that the tool list changed. Returns the connections reached."""
        try:
            await self._subscriptions.publish(ToolsListChanged())
        except Exception:
            log.debug("Subscription publish failed", exc_info=True)
        reached = 0
        for connection in list(self._connections):
            try:
                await connection.send_tool_list_changed()
                reached += 1
            except Exception:
                self._connections.discard(connection)
        return reached

    # ------------------------------------------------------------------ tools
    def _register_status_tool(self) -> None:
        server = self

        async def siigo_status() -> str:
            """Status of the MCP Siigo Unofficial server: whether Siigo credentials are set,
            whether write actions are enabled, and the app version. Never returns secrets."""
            enabled = server.write_switch.enabled
            return _compact(
                {
                    "app_version": __version__,
                    "siigo_configured": server.siigo.is_configured(),
                    "siigo_base_url": server.siigo.base_url,
                    "write_actions_enabled": enabled,
                    "write_approval": server.approval_mode().value,
                    "read_tools": len(server.catalog.read_tools),
                    "write_tools": len(server.catalog.write_tools) if enabled else 0,
                    "how_to_enable_writes": (
                        None if enabled else "Only the user can enable them from the tray menu."
                    ),
                    "liability": LIABILITY_STATEMENT,
                }
            )

        self.add_tool(
            siigo_status,
            name=STATUS_TOOL,
            title="Server status",
            annotations=ToolAnnotations(
                title="Server status", read_only_hint=True, open_world_hint=False
            ),
            structured_output=False,
        )

    def _register_endpoint(self, endpoint: EndpointTool) -> None:
        user_params = _user_parameters(endpoint)
        if endpoint.read_only:
            fn = self._make_read_tool(endpoint)
            _set_signature(fn, user_params, str)
        else:
            fn = self._make_write_tool(endpoint)
            resolver = self._make_approval_resolver(endpoint, user_params)
            approval = inspect.Parameter(
                "approval",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=Annotated[ElicitationResult[Approval], Resolve(resolver)],
            )
            ctx_param = inspect.Parameter(
                "ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context[Any, Any]
            )
            _set_signature(fn, [*user_params, approval, ctx_param], str)
        fn.__name__ = endpoint.name
        fn.__qualname__ = endpoint.name
        fn.__doc__ = _describe(endpoint)
        self.add_tool(
            fn,
            name=endpoint.name,
            title=endpoint.title,
            description=_describe(endpoint),
            annotations=ToolAnnotations(
                title=endpoint.title,
                read_only_hint=endpoint.read_only,
                destructive_hint=not endpoint.read_only,
                idempotent_hint=endpoint.read_only or endpoint.method == "PUT",
                open_world_hint=True,
            ),
            structured_output=False,
        )

    def _make_read_tool(self, endpoint: EndpointTool) -> Callable[..., Awaitable[str]]:
        async def read_tool(**kwargs: Any) -> str:
            return await self._execute(endpoint, kwargs)

        return read_tool

    def _asked_key(self, endpoint: EndpointTool, kwargs: dict[str, Any], ctx: Any) -> str:
        return arguments_digest(f"{endpoint.name}|{_connection_key(ctx)}", kwargs)

    def _make_approval_resolver(
        self, endpoint: EndpointTool, user_params: list[inspect.Parameter]
    ) -> Callable[..., Awaitable[Elicit[Approval] | Approval]]:
        """Runs before the tool: asks the AI app only in "In the AI app" mode."""

        async def resolver(ctx: Context[Any, Any], **kwargs: Any) -> Elicit[Approval] | Approval:
            if self.approval_mode() is not ApprovalMode.AI_APP or endpoint.risk.needs_window:
                return _UseWindow(approve=False)
            capabilities = ctx.client_capabilities
            if capabilities is None or capabilities.elicitation is None:
                return _UseWindow(approve=False)
            request = self._approval_request(endpoint, kwargs, ctx)
            early = await self.approver.preapproved(request)
            if early is not None:
                return _Preapproved(approve=True, outcome=early.value)
            now = time.monotonic()
            for key in [k for k, t in self._asked_at.items() if now - t > _ASKED_TTL_S]:
                del self._asked_at[key]
            self._asked_at.setdefault(self._asked_key(endpoint, kwargs, ctx), now)
            return Elicit(self._approval_message(endpoint, kwargs), Approval)

        ctx_param = inspect.Parameter(
            "ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context[Any, Any]
        )
        _set_signature(resolver, [ctx_param, *user_params], Elicit[Approval] | Approval)
        resolver.__name__ = f"approve_{endpoint.name}"
        resolver.__qualname__ = resolver.__name__
        return resolver

    def _make_write_tool(self, endpoint: EndpointTool) -> Callable[..., Awaitable[str]]:
        async def write_tool(
            approval: ElicitationResult[Approval], ctx: Context[Any, Any], **kwargs: Any
        ) -> str:
            request = self._approval_request(endpoint, kwargs, ctx)
            if endpoint.risk is Risk.PERMANENT:  # show the record as Siigo has it now
                summary = await self._record_summary(endpoint, kwargs)
                request = dataclasses.replace(request, summary=summary)
            asked_at = self._asked_at.pop(self._asked_key(endpoint, kwargs, ctx), None)
            if isinstance(approval, AcceptedElicitation):
                data = approval.data
                if isinstance(data, _Preapproved):
                    outcome = Outcome(data.outcome)
                elif isinstance(data, _UseWindow):
                    outcome = await self._wait_for_approval(request, ctx)
                else:
                    outcome = Outcome.AI_APP if data.approve else Outcome.REJECTED_IN_APP
            else:
                waited = time.monotonic() - asked_at if asked_at is not None else 0.0
                if waited < AUTOMATIC_DECLINE_S:
                    log.warning(
                        "The AI app declined %s in %.3f s without asking: using the Siigo window",
                        endpoint.name,
                        waited,
                    )
                    outcome = await self._wait_for_approval(request, ctx)
                else:
                    outcome = Outcome.REJECTED_IN_APP
            if not self.write_switch.enabled:  # the switch may change during approval
                raise _tool_error(
                    {"code": "write_actions_disabled", "message": "Write actions are OFF."}
                )
            if not outcome.approved:
                return self._not_approved(endpoint, request, outcome)
            return await self._execute(endpoint, kwargs, approved_via=outcome.value)

        return write_tool

    async def _record_summary(
        self, endpoint: EndpointTool, kwargs: dict[str, Any]
    ) -> list[tuple[str, str]]:
        """Read the record a delete or annul will affect, for the approval window.

        If it can't be read, nothing is asked and nothing is sent.
        """
        try:
            path = endpoint.build_path(kwargs)
        except ValueError as exc:
            raise _tool_error({"code": "invalid_arguments", "message": str(exc)}) from exc
        record_path = path.removesuffix("/annul")
        record_id = record_path.rsplit("/", 1)[-1]
        try:
            if record_path.startswith("/v1/webhooks/"):  # no GET by id: find it in the list
                data = await self.siigo.request("GET", "/v1/webhooks")
                items = data.get("results", []) if isinstance(data, dict) else data
                record = next(
                    (
                        item
                        for item in items or []
                        if isinstance(item, dict) and str(item.get("id")) == record_id
                    ),
                    None,
                )
                if record is None:
                    raise SiigoError(
                        f"The webhook subscription {record_id} does not exist.",
                        status=404,
                        code="not_found",
                        method="GET",
                        path="/v1/webhooks",
                    )
            else:
                record = await self.siigo.request("GET", record_path)
        except SiigoError as exc:
            raise _tool_error(
                {
                    "code": "record_not_readable",
                    "message": (
                        f"Could not read {record_path} to show it to the user before "
                        f"{endpoint.name}. Nothing was asked and nothing was sent."
                    ),
                    "siigo": exc.to_dict(),
                }
            ) from exc
        return record_summary(record_id, record)

    def _approval_request(
        self, endpoint: EndpointTool, kwargs: dict[str, Any], ctx: Context[Any, Any]
    ) -> ApprovalRequest:
        preview = self._request_preview(endpoint, kwargs)
        path_values = {p.name: str(kwargs.get(p.python_name) or "") for p in endpoint.path_params}
        return ApprovalRequest(
            tool=endpoint.name,
            title=endpoint.title,
            method=preview["method"],
            url=preview["url"],
            query=preview["query"],
            body=preview["body"],
            summary=summarize(path_values, preview["body"], full=endpoint.risk is Risk.OUTBOUND),
            client=_client_name(ctx),
            connection=_connection_key(ctx),
            risk=endpoint.risk,
        )

    async def _wait_for_approval(self, request: ApprovalRequest, ctx: Context[Any, Any]) -> Outcome:
        """Ask the approver; meanwhile send progress so the AI app keeps waiting."""

        async def keepalive() -> None:
            waited = 0.0
            while True:
                await asyncio.sleep(PROGRESS_EVERY_S)
                waited += PROGRESS_EVERY_S
                with contextlib.suppress(Exception):
                    await ctx.report_progress(
                        waited, request.timeout_s, "Waiting for approval in the Siigo window"
                    )

        task = asyncio.create_task(keepalive())
        try:
            return await self.approver.approve(request)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def _not_approved(
        self, endpoint: EndpointTool, request: ApprovalRequest, outcome: Outcome
    ) -> str:
        if self.vault is not None:
            self.vault.add_event(
                EVENT_WRITE_NOT_APPROVED,
                {"tool": endpoint.name, "method": request.method, "outcome": outcome.value},
            )
        if outcome is Outcome.UNAVAILABLE:
            raise _tool_error(
                {
                    "code": "approval_unavailable",
                    "message": (
                        "The MCP Siigo Unofficial app is not reachable, so the approval "
                        "window could not be shown. Ask the user to open the app (tray "
                        "icon) and try again. Nothing was sent to Siigo."
                    ),
                }
            )
        if outcome is Outcome.TIMEOUT:
            return _compact(
                {
                    "status": "approval_timeout",
                    "sent_to_siigo": False,
                    "message": (
                        f"Nobody answered the approval window for {endpoint.name} in "
                        f"{int(request.timeout_s)} seconds. Nothing was sent. Ask the user "
                        "before trying again."
                    ),
                }
            )
        where = (
            "your app's approval question"
            if outcome is Outcome.REJECTED_IN_APP
            else "the Siigo approval window"
        )
        return _compact(
            {
                "status": "rejected_by_user",
                "sent_to_siigo": False,
                "message": f"The user rejected {endpoint.name} in {where}. Nothing was sent.",
            }
        )

    def _approval_message(self, endpoint: EndpointTool, kwargs: dict[str, Any]) -> str:
        preview = self._request_preview(endpoint, kwargs)
        outbound = endpoint.risk is Risk.OUTBOUND
        body = _compact(preview["body"])
        lines = [
            f"⚠ MCP Siigo Unofficial — WRITE ACTION ({endpoint.title})",
            f"{preview['method']} {preview['url']}",
            f"Body: {body if outbound else _truncate(body)}",
            "",
        ]
        if outbound:
            lines.append(
                "This SENDS DATA OUTSIDE SIIGO to the addresses or URL above. Check each one."
            )
        lines.append(
            "This creates or changes REAL data in your Siigo company (invoices go to the "
            "DIAN). You are responsible for this action. Approve it?"
        )
        return "\n".join(lines)

    def _request_preview(self, endpoint: EndpointTool, kwargs: dict[str, Any]) -> dict[str, Any]:
        try:
            path = endpoint.build_path(kwargs)
        except ValueError as exc:
            raise _tool_error({"code": "invalid_arguments", "message": str(exc)}) from exc
        return {
            "tool": endpoint.name,
            "method": endpoint.method,
            "url": f"{self.siigo.base_url}{path}",
            "query": endpoint.build_query(kwargs),
            "body": kwargs.get("body"),
        }

    async def _execute(
        self, endpoint: EndpointTool, kwargs: dict[str, Any], *, approved_via: str | None = None
    ) -> str:
        try:
            path = endpoint.build_path(kwargs)
        except ValueError as exc:
            raise _tool_error({"code": "invalid_arguments", "message": str(exc)}) from exc
        query = endpoint.build_query(kwargs)
        body = kwargs.get("body") if endpoint.body_schema is not None else None
        headers = idempotency.headers_for(endpoint.method, path, body)
        try:
            data = await self.siigo.request(
                endpoint.method, path, params=query, json=body, headers=headers or None
            )
        except SiigoError as exc:
            raise _tool_error(exc.to_dict()) from exc
        if approved_via is not None:
            log.warning("Write executed: %s %s (%s)", endpoint.method, path, approved_via)
            if self.vault is not None:
                self.vault.add_event(
                    EVENT_WRITE_EXECUTED,
                    {
                        "tool": endpoint.name,
                        "method": endpoint.method,
                        "path": path,
                        "approved_via": approved_via,
                        **({"idempotency_key": headers[idempotency.HEADER]} if headers else {}),
                    },
                )
        return _compact(data)


def build_server(
    siigo: SiigoClient,
    write_switch: WriteSwitch,
    *,
    vault: Vault | None = None,
    approver: Approver | None = None,
    approval_mode: Callable[[], ApprovalMode] | None = None,
) -> SiigoMCPServer:
    """Create the MCP server with the shipped catalog."""
    return SiigoMCPServer(
        siigo, write_switch, vault=vault, approver=approver, approval_mode=approval_mode
    )


def _client_name(ctx: Context[Any, Any]) -> str:
    """The AI app's name from the MCP handshake (for the window), or "AI app"."""
    try:
        params = ctx.session.client_params
        info = getattr(params, "client_info", None) or getattr(params, "clientInfo", None)
        name = getattr(info, "title", None) or getattr(info, "name", None)
    except Exception:
        name = None
    return str(name)[:60] if name else "AI app"


def _connection_key(ctx: Context[Any, Any]) -> str:
    """Identifies one AI app connection, for "approve similar writes" grants.

    - A stdio server serves one AI app session: the process id is part of every key.
    - Streamable HTTP with a session: the MCP session id.
    - The stateless protocol (2026-07-28) has no lasting connection: the AI app's
      name and version stand for it.
    - Otherwise (in-process legacy sessions): the connection object.
    """
    prefix = str(os.getpid())
    try:
        connection = getattr(ctx.session, "_connection", None)
        session_id = getattr(connection, "session_id", None)
        if session_id:
            return f"{prefix}-session-{session_id}"
        version = str(getattr(connection, "protocol_version", "") or "")
        if version >= "2026-07-28":
            params = ctx.session.client_params
            info = getattr(params, "client_info", None)
            name = getattr(info, "name", "?")
            client_version = getattr(info, "version", "?")
            return f"{prefix}-client-{name}-{client_version}"
    except Exception:
        connection = None
    marker = id(connection) if connection is not None else 0
    return f"{prefix}-{marker}"
