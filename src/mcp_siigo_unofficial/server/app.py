"""MCP server for the Siigo API (plan sections 4, 5, and 5.1).

- One tool per catalog endpoint. Read tools have ``readOnlyHint``; write tools have
  ``destructiveHint`` and start with the "⚠ WRITE ACTION" warning block.
- Write tools are **not listed** while the "Write actions" switch is off, and a call
  to one is rejected. Every switch change sends ``notifications/tools/list_changed``
  (and the 2026-07-28 subscription event).
- Every write needs the user's approval: MCP elicitation when the client supports
  it, otherwise a one-time ``confirmation_id`` issued with a preview.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
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
from mcp_siigo_unofficial.server.catalog import Catalog, EndpointTool, load_catalog
from mcp_siigo_unofficial.server.write_gate import ConfirmationStore, WriteSwitch
from mcp_siigo_unofficial.siigo import SiigoClient, SiigoError
from mcp_siigo_unofficial.vault import Vault

log = logging.getLogger(__name__)

SERVER_NAME = "mcp-siigo-unofficial"
STATUS_TOOL = "siigo_status"
EVENT_WRITE_EXECUTED = "write.executed"
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
    "explicit authorization. The server also asks the user to approve: either the client "
    "shows an Approve/Reject question, or the first call returns a preview and a one-time "
    "`confirmation_id`. In that case, show the preview to the user, and call again with the "
    "same arguments plus `confirmation_id` only after the user approves. Never invent or "
    "reuse a confirmation_id."
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
    """The user's answer to the write approval question."""

    approve: bool = Field(description="Approve this write in Siigo")


class _ElicitationUnavailable(Approval):
    """Marker: the client cannot ask the user, so the two-step flow applies."""


def _compact(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


def _truncate(text: str, limit: int = _MAX_PREVIEW_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "… (truncated)"


def _tool_error(payload: dict[str, Any]) -> ToolError:
    return ToolError(_compact({"error": payload}))


def _describe(endpoint: EndpointTool) -> str:
    parts: list[str] = []
    if not endpoint.read_only:
        parts.append(WRITE_WARNING)
    parts.append(f"{endpoint.title}. [{endpoint.method} {endpoint.path}]")
    parts.append(f"Siigo documentation (Spanish): {endpoint.description}")
    if endpoint.fixed_query:
        fixed = ", ".join(f"{k}={v}" for k, v in endpoint.fixed_query.items())
        parts.append(f"Fixed query: {fixed}.")
    if endpoint.notes:
        parts.append("Notes: " + " ".join(endpoint.notes))
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
    if not endpoint.read_only:
        params.append(
            inspect.Parameter(
                "confirmation_id",
                kw,
                default=None,
                annotation=Annotated[
                    str | None,
                    Field(
                        description=(
                            "One-time id from this tool's preview. Send it only after the "
                            "user approved that exact preview."
                        )
                    ),
                ],
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
        confirmations: ConfirmationStore | None = None,
        vault: Vault | None = None,
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
        self.confirmations = confirmations if confirmations is not None else ConfirmationStore()
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
            _set_signature(fn, [*user_params, approval], str)
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

    def _make_approval_resolver(
        self, endpoint: EndpointTool, user_params: list[inspect.Parameter]
    ) -> Callable[..., Elicit[Approval] | Approval]:
        def resolver(ctx: Context[Any, Any], **kwargs: Any) -> Elicit[Approval] | Approval:
            capabilities = ctx.client_capabilities
            if capabilities is None or capabilities.elicitation is None:
                return _ElicitationUnavailable(approve=False)
            return Elicit(self._approval_message(endpoint, kwargs), Approval)

        ctx_param = inspect.Parameter(
            "ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context[Any, Any]
        )
        _set_signature(resolver, [ctx_param, *user_params], Elicit[Approval] | Approval)
        resolver.__name__ = f"approve_{endpoint.name}"
        resolver.__qualname__ = resolver.__name__
        return resolver

    def _make_write_tool(self, endpoint: EndpointTool) -> Callable[..., Awaitable[str]]:
        async def write_tool(approval: ElicitationResult[Approval], **kwargs: Any) -> str:
            if not self.write_switch.enabled:  # the switch may change during approval
                raise _tool_error(
                    {"code": "write_actions_disabled", "message": "Write actions are OFF."}
                )
            if not isinstance(approval, AcceptedElicitation):
                return _compact(
                    {
                        "status": "rejected_by_user",
                        "message": f"The user did not approve {endpoint.name}. Nothing was sent.",
                    }
                )
            if isinstance(approval.data, _ElicitationUnavailable):
                return await self._two_step(endpoint, kwargs)
            if not approval.data.approve:
                return _compact(
                    {
                        "status": "rejected_by_user",
                        "message": f"The user rejected {endpoint.name}. Nothing was sent.",
                    }
                )
            return await self._execute(endpoint, kwargs, approved_via="elicitation")

        return write_tool

    async def _two_step(self, endpoint: EndpointTool, kwargs: dict[str, Any]) -> str:
        arguments = {k: v for k, v in kwargs.items() if v is not None}
        confirmation_id = arguments.get("confirmation_id")
        if not confirmation_id:
            preview = self._request_preview(endpoint, kwargs)
            new_id = self.confirmations.issue(endpoint.name, arguments)
            return _compact(
                {
                    "status": "confirmation_required",
                    "sent_to_siigo": False,
                    "warning": WRITE_WARNING.splitlines()[0],
                    "preview": preview,
                    "confirmation_id": new_id,
                    "expires_in_seconds": int(self.confirmations.ttl),
                    "next_step": (
                        "Show this preview to the user. Only if the user approves, call "
                        f"{endpoint.name} again with the same arguments plus this "
                        "confirmation_id."
                    ),
                }
            )
        if not self.confirmations.redeem(str(confirmation_id), endpoint.name, arguments):
            raise _tool_error(
                {
                    "code": "invalid_confirmation",
                    "message": (
                        "The confirmation_id is invalid, expired, already used, or the "
                        "arguments changed. Nothing was sent. Call again without "
                        "confirmation_id to get a new preview for the user."
                    ),
                }
            )
        return await self._execute(endpoint, kwargs, approved_via="confirmation_id")

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

    def _approval_message(self, endpoint: EndpointTool, kwargs: dict[str, Any]) -> str:
        preview = self._request_preview(endpoint, kwargs)
        return (
            f"⚠ MCP Siigo Unofficial — WRITE ACTION ({endpoint.title})\n"
            f"{preview['method']} {preview['url']}\n"
            f"Body: {_truncate(_compact(preview['body']))}\n\n"
            "This creates or changes REAL data in your Siigo company (invoices go to the "
            "DIAN). You are responsible for this action. Approve it?"
        )

    async def _execute(
        self, endpoint: EndpointTool, kwargs: dict[str, Any], *, approved_via: str | None = None
    ) -> str:
        try:
            path = endpoint.build_path(kwargs)
        except ValueError as exc:
            raise _tool_error({"code": "invalid_arguments", "message": str(exc)}) from exc
        query = endpoint.build_query(kwargs)
        body = kwargs.get("body") if endpoint.body_schema is not None else None
        try:
            data = await self.siigo.request(endpoint.method, path, params=query, json=body)
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
                    },
                )
        return _compact(data)


def build_server(
    siigo: SiigoClient,
    write_switch: WriteSwitch,
    *,
    vault: Vault | None = None,
    confirmations: ConfirmationStore | None = None,
) -> SiigoMCPServer:
    """Create the MCP server with the shipped catalog."""
    return SiigoMCPServer(siigo, write_switch, vault=vault, confirmations=confirmations)
