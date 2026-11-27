"""Mock Siigo API for tests (plan phase 1). It never talks to the real Siigo.

It implements the parts of the API the client needs: ``POST /auth``, the
``Partner-Id`` rule, Bearer tokens, paginated lists, catalogs (plain arrays),
get/create/update/delete for customers, products, and invoices, Siigo-style error
bodies, and fault injection (expired tokens, 429 with ``Retry-After``, 5xx).

Use it in-process with :meth:`MockSiigo.transport` (an ``httpx2.MockTransport``),
or over real HTTP on 127.0.0.1 with :meth:`MockSiigo.serve`.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx2

PARTNER_ID = re.compile(r"^[A-Za-z0-9]{3,100}$")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9]{1,30}$")
TEST_USERNAME = "sandbox@example.com"
TEST_ACCESS_KEY = "dGVzdC1hY2Nlc3Mta2V5LW5vdC1yZWFs"

RESOURCES = (
    "customers",
    "products",
    "invoices",
    "quotations",
    "purchases",
    "purchase-support-documents",
    "payment-receipts",
    "account-groups",
    "webhooks",
)
CATALOGS: dict[str, list[dict[str, Any]]] = {
    "taxes": [{"id": 13156, "name": "IVA 19%", "type": "IVA", "percentage": 19, "active": True}],
    "payment-types": [{"id": 5636, "name": "Contado", "type": "ElectronicInvoice"}],
    "document-types": [{"id": 24446, "code": "1", "name": "Factura", "type": "FV"}],
    "warehouses": [{"id": 1270, "name": "Bodega principal", "active": True}],
    "users": [{"id": 629, "username": "seller@example.com", "first_name": "Ana"}],
    "cost-centers": [{"id": 13156, "code": "1", "name": "General", "active": True}],
    "price-lists": [{"id": 1, "name": "Precio de venta 1", "active": True, "position": 1}],
    "account-groups": [{"id": 1253, "name": "Productos", "active": True}],
}


@dataclass
class Fault:
    """A canned response returned instead of the normal one."""

    status: int
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)


def siigo_error(status: int, code: str, message: str, *params: str) -> httpx2.Response:
    body = {"Errors": [{"Code": code, "Message": message, "Params": list(params)}]}
    return httpx2.Response(status, json=body)


class MockSiigo:
    """In-memory Siigo API."""

    def __init__(
        self,
        username: str = TEST_USERNAME,
        access_key: str = TEST_ACCESS_KEY,
        token_lifetime: int = 86_400,
    ) -> None:
        self.username = username
        self.access_key = access_key
        self.token_lifetime = token_lifetime
        self.tokens: set[str] = set()
        self.auth_calls = 0
        self.requests: list[httpx2.Request] = []
        self.faults: list[Fault] = []
        self.data: dict[str, dict[str, dict[str, Any]]] = {r: {} for r in RESOURCES}
        self._lock = threading.Lock()
        self._invoice_number = 0
        self.idempotency: dict[tuple[str, str], str] = {}
        self.mails: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ test helpers
    def expire_tokens(self) -> None:
        """Make every issued token invalid (the next call gets 401)."""
        with self._lock:
            self.tokens.clear()

    def add_fault(
        self, status: int, body: Any = None, headers: dict[str, str] | None = None
    ) -> None:
        """Queue one canned response for the next ``/v1`` request."""
        self.faults.append(Fault(status, body, headers or {}))

    def seed(self, resource: str, count: int) -> list[dict[str, Any]]:
        created = [self._create(resource, {"name": f"{resource} {i}"}) for i in range(count)]
        return created

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    # ------------------------------------------------------------------ dispatch
    def handle(self, request: httpx2.Request) -> httpx2.Response:
        with self._lock:
            self.requests.append(request)
            return self._dispatch(request)

    def _dispatch(self, request: httpx2.Request) -> httpx2.Response:
        partner_id = request.headers.get("Partner-Id")
        if not partner_id:
            return siigo_error(400, "header_required", "The Partner-Id header is required.")
        if not PARTNER_ID.fullmatch(partner_id):
            return siigo_error(400, "invalid_partner_id", "The Partner-Id is invalid.")

        path = request.url.path
        if path == "/auth" and request.method == "POST":
            return self._auth(request)
        if not path.startswith("/v1/"):
            return siigo_error(404, "not_found", "Resource not found.")

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth.removeprefix("Bearer ") not in self.tokens:
            return siigo_error(401, "unauthorized", "Invalid or expired token.")

        if self.faults:
            fault = self.faults.pop(0)
            if fault.body is None:
                return httpx2.Response(fault.status, headers=fault.headers)
            return httpx2.Response(fault.status, json=fault.body, headers=fault.headers)

        parts = path.removeprefix("/v1/").strip("/").split("/")
        resource = parts[0]
        if resource in CATALOGS and len(parts) == 1 and request.method == "GET":
            return httpx2.Response(200, json=CATALOGS[resource])
        if resource == "invoices" and len(parts) == 3 and parts[2] == "mail":
            if request.method != "POST" or parts[1] not in self.data["invoices"]:
                return self._not_found(parts[1])
            self.mails.append({"invoice": parts[1], **json.loads(request.content or b"{}")})
            return httpx2.Response(201, json={"status": "sent", "observations": ""})
        if resource == "webhooks" and len(parts) == 1 and request.method == "PUT":
            body = json.loads(request.content or b"{}")
            for item in self.data["webhooks"].values():
                if item.get("topic") == body.get("topic"):  # the docs send no id
                    item.update(body)
                    return httpx2.Response(201, json=item)
            return self._not_found(body.get("topic"))
        if resource == "invoices" and len(parts) == 3 and parts[2] == "annul":
            invoice = self.data["invoices"].get(parts[1])
            if request.method != "POST" or invoice is None:
                return self._not_found(parts[1])
            invoice["annulled"] = True
            return httpx2.Response(200, json={"id": parts[1], "Annul": True})
        if resource not in RESOURCES or len(parts) > 2:
            return siigo_error(404, "not_found", "Resource not found.")
        item_id = parts[1] if len(parts) == 2 else None
        return self._crud(request, resource, item_id)

    def _auth(self, request: httpx2.Request) -> httpx2.Response:
        self.auth_calls += 1
        try:
            body = json.loads(request.content or b"{}")
        except ValueError:
            return siigo_error(400, "invalid_json", "The body is not valid JSON.")
        if body.get("username") != self.username or body.get("access_key") != self.access_key:
            return siigo_error(401, "unauthorized", "Invalid username or access key.")
        token = "mock-" + secrets.token_urlsafe(24)
        self.tokens.add(token)
        return httpx2.Response(
            201,
            json={
                "access_token": token,
                "expires_in": self.token_lifetime,
                "token_type": "Bearer",
                "scope": "SiigoAPI",
            },
        )

    def _crud(self, request: httpx2.Request, resource: str, item_id: str | None) -> httpx2.Response:
        store = self.data[resource]
        method = request.method
        if method == "GET" and item_id is None:
            return self._list(request, resource)
        if method == "GET":
            item = store.get(item_id or "")
            return httpx2.Response(200, json=item) if item else self._not_found(item_id)
        if method == "POST" and item_id is None:
            body = json.loads(request.content or b"{}")
            if not isinstance(body, dict) or not body:
                return siigo_error(400, "invalid_type", "The request body is required.")
            key = request.headers.get("Idempotency-Key")
            if key is not None:
                if not IDEMPOTENCY_KEY.fullmatch(key):
                    return siigo_error(
                        400, "invalid_idempotency-key", "The Idempotency-Key is invalid."
                    )
                earlier = self.idempotency.get((resource, key))
                if earlier is not None:  # Siigo returns the document created before
                    return httpx2.Response(200, json=store[earlier])
            item = self._create(resource, body)
            if key is not None:
                self.idempotency[(resource, key)] = item["id"]
            return httpx2.Response(201, json=item)
        if method == "PUT" and item_id is not None:
            if item_id not in store:
                return self._not_found(item_id)
            body = json.loads(request.content or b"{}")
            store[item_id] = {**body, "id": item_id}
            return httpx2.Response(200, json=store[item_id])
        if method == "DELETE" and item_id is not None:
            if store.pop(item_id, None) is None:
                return self._not_found(item_id)
            return httpx2.Response(200, json={"id": item_id, "deleted": True})
        return siigo_error(405, "method_not_allowed", "Method not allowed.")

    def _list(self, request: httpx2.Request, resource: str) -> httpx2.Response:
        try:
            page = max(1, int(request.url.params.get("page", "1")))
            page_size = min(100, max(1, int(request.url.params.get("page_size", "25"))))
        except ValueError:
            return siigo_error(400, "invalid_type", "page and page_size must be integers.")
        items = list(reversed(self.data[resource].values()))  # newest first
        start = (page - 1) * page_size
        return httpx2.Response(
            200,
            json={
                "pagination": {"page": page, "page_size": page_size, "total_results": len(items)},
                "results": items[start : start + page_size],
                "_links": {"self": {"href": str(request.url)}},
            },
        )

    def _create(self, resource: str, body: dict[str, Any]) -> dict[str, Any]:
        item_id = str(uuid.uuid4())
        item = {**body, "id": item_id}
        if resource == "invoices":
            self._invoice_number += 1
            item["name"] = f"FV-1-{self._invoice_number}"
        self.data[resource][item_id] = item
        return item

    @staticmethod
    def _not_found(item_id: str | None) -> httpx2.Response:
        return siigo_error(404, "not_found", "The record does not exist.", str(item_id))

    # ------------------------------------------------------------------ real HTTP
    @contextmanager
    def serve(self) -> Iterator[str]:
        """Serve over HTTP on 127.0.0.1 (random port); yield the base URL."""
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                content = self.rfile.read(length) if length else b""
                url = f"http://{self.headers.get('Host', '127.0.0.1')}{self.path}"
                request = httpx2.Request(
                    self.command, url, headers=dict(self.headers.items()), content=content
                )
                response = mock.handle(request)
                payload = response.content
                self.send_response(response.status_code)
                for name, value in response.headers.items():
                    if name.lower() not in {"content-length", "transfer-encoding"}:
                        self.send_header(name, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = do_DELETE = _handle

            def log_message(self, format: str, *args: Any) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            server.server_close()
