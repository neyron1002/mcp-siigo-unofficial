"""Asynchronous Siigo REST client (httpx2).

- ``POST /auth`` with the username and access key. The token is cached in memory
  and renewed 5 minutes before it expires (Siigo tokens last 24 hours, plan D7).
- Every call sends ``Authorization: Bearer <token>`` and ``Partner-Id``.
- On 401 it authenticates again and retries once. On 429 it waits for
  ``Retry-After`` (capped) and retries. Read calls (GET) also retry once on a
  network error or a 502/503/504. Writes are never retried after a server error,
  because the record may already exist.
- Only relative ``/v1/...`` paths are accepted, so the token is never sent to
  another host.
- The token and the access key are never returned, printed, or logged.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, Self

import httpx2

from mcp_siigo_unofficial import __version__
from mcp_siigo_unofficial.siigo.credentials import SiigoCredentials
from mcp_siigo_unofficial.siigo.errors import (
    SiigoAuthError,
    SiigoError,
    SiigoNotConfiguredError,
)

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.siigo.com"
#: Siigo recommends waiting up to 120 seconds for heavy requests.
DEFAULT_TIMEOUT_S = 120.0
#: Renew the token this many seconds before it expires.
TOKEN_RENEW_MARGIN_S = 300.0
DEFAULT_TOKEN_LIFETIME_S = 86_400.0
MAX_RETRY_AFTER_S = 60.0
DEFAULT_RETRY_AFTER_S = 5.0
MAX_RATE_LIMIT_RETRIES = 2
_RETRYABLE_READ_STATUS = frozenset({502, 503, 504})
_PATH_PATTERN = re.compile(r"^/v1/[A-Za-z0-9._~\-/{}%]*$")

CredentialsProvider = Callable[[], SiigoCredentials | None]
Sleep = Callable[[float], Awaitable[None]]


def _fingerprint(credentials: SiigoCredentials) -> str:
    raw = "\x00".join((credentials.username, credentials.access_key, credentials.partner_id))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validate_path(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    if not _PATH_PATTERN.fullmatch(path) or "/../" in path + "/" or "//" in path:
        raise SiigoError(
            "Only Siigo API paths that start with /v1/ are allowed.",
            code="invalid_path",
            path=path,
        )
    return path


def _retry_after_seconds(response: httpx2.Response) -> float:
    value = response.headers.get("Retry-After")
    try:
        seconds = float(value) if value else DEFAULT_RETRY_AFTER_S
    except ValueError:
        seconds = DEFAULT_RETRY_AFTER_S
    return max(0.0, min(seconds, MAX_RETRY_AFTER_S))


def _decode(response: httpx2.Response) -> Any:
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return {
            "content_type": response.headers.get("Content-Type"),
            "text": response.text,
        }


class SiigoClient:
    """Siigo API client. Use it as ``async with SiigoClient(...)`` or call :meth:`aclose`.

    ``credentials`` is a function, so a change in Settings is picked up on the next
    call (and causes a new authentication).
    """

    def __init__(
        self,
        credentials: CredentialsProvider,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_S,
        transport: httpx2.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._clock = clock
        self._sleep = sleep
        self._http = httpx2.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={
                "Accept": "application/json",
                "User-Agent": f"mcp-siigo-unofficial/{__version__}",
            },
            follow_redirects=False,
        )
        self._token: str | None = None
        self._token_expires_at: float | None = None
        self._token_owner: str | None = None
        self._auth_lock = asyncio.Lock()
        self.request_count = 0

    def __repr__(self) -> str:
        state = "present" if self._token else "absent"
        return f"SiigoClient(base_url={self.base_url!r}, token={state})"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ token
    def _require_credentials(self) -> SiigoCredentials:
        credentials = self._credentials()
        if credentials is None:
            raise SiigoNotConfiguredError(
                "Siigo credentials are not set. Enter them in the app's Settings dialog.",
                code="not_configured",
            )
        return credentials

    def _token_is_fresh(self, credentials: SiigoCredentials) -> bool:
        if self._token is None or self._token_owner != _fingerprint(credentials):
            return False
        if self._token_expires_at is None:
            return True
        return self._clock() < self._token_expires_at - TOKEN_RENEW_MARGIN_S

    def is_configured(self) -> bool:
        """True if Siigo credentials are available."""
        return self._credentials() is not None

    def invalidate_token(self) -> None:
        """Forget the cached token (for example, after the credentials change)."""
        self._token = None
        self._token_expires_at = None
        self._token_owner = None

    @property
    def token_seconds_left(self) -> float | None:
        """Seconds until the cached token expires, or None if there is no token."""
        if self._token is None or self._token_expires_at is None:
            return None
        return max(0.0, self._token_expires_at - self._clock())

    async def authenticate(self, *, force: bool = False) -> None:
        """Get a token with ``POST /auth`` unless a fresh one is cached."""
        async with self._auth_lock:
            credentials = self._require_credentials()
            if not force and self._token_is_fresh(credentials):
                return
            log.info("Authenticating with Siigo (POST /auth)")
            try:
                response = await self._http.post(
                    "/auth",
                    json={"username": credentials.username, "access_key": credentials.access_key},
                    headers={"Partner-Id": credentials.partner_id},
                )
            except httpx2.HTTPError as exc:
                raise SiigoError(
                    f"Network error while authenticating: {type(exc).__name__}",
                    code="network_error",
                    method="POST",
                    path="/auth",
                ) from exc
            if response.status_code >= 400:
                error = SiigoError.from_response(response, "POST", "/auth")
                raise SiigoAuthError(
                    error.message,
                    status=error.status,
                    code=error.code,
                    errors=error.errors,
                    method="POST",
                    path="/auth",
                )
            data = _decode(response)
            token = data.get("access_token") if isinstance(data, dict) else None
            if not isinstance(token, str) or not token:
                raise SiigoAuthError(
                    "Siigo did not return an access token.",
                    status=response.status_code,
                    method="POST",
                    path="/auth",
                )
            lifetime = DEFAULT_TOKEN_LIFETIME_S
            raw_lifetime = data.get("expires_in") if isinstance(data, dict) else None
            if isinstance(raw_lifetime, int | float) and raw_lifetime > 0:
                lifetime = float(raw_lifetime)
                # The docs say milliseconds, but the documented value (86400) is seconds.
                if lifetime > 1_000_000:
                    lifetime /= 1000.0
            self._token = token
            self._token_expires_at = self._clock() + lifetime
            self._token_owner = _fingerprint(credentials)
            log.info("Siigo token received; it expires in %.0f s", lifetime)

    # ------------------------------------------------------------------ requests
    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Call the Siigo API and return the decoded JSON body (None for 204)."""
        method = method.upper()
        path = _validate_path(path)
        query = {k: v for k, v in (params or {}).items() if v is not None}
        is_read = method == "GET"

        credentials = self._require_credentials()
        if not self._token_is_fresh(credentials):
            await self.authenticate()

        retried_401 = False
        retried_read = False
        rate_limit_retries = 0
        while True:
            try:
                response = await self._send(method, path, query, json, headers)
            except httpx2.HTTPError as exc:
                if is_read and not retried_read:
                    retried_read = True
                    log.warning("Network error on %s %s; retrying once", method, path)
                    await self._sleep(1.0)
                    continue
                if isinstance(exc, httpx2.TimeoutException):
                    raise SiigoError(
                        f"Siigo did not answer within {self.timeout:.0f} s ({method} {path}).",
                        status=408,
                        code="request_timeout",
                        method=method,
                        path=path,
                    ) from exc
                raise SiigoError(
                    f"Network error on {method} {path}: {type(exc).__name__}",
                    code="network_error",
                    method=method,
                    path=path,
                ) from exc

            status = response.status_code
            if status == 401 and not retried_401:
                retried_401 = True
                log.warning("401 on %s %s; authenticating again once", method, path)
                await self.authenticate(force=True)
                continue
            if status == 429 and rate_limit_retries < MAX_RATE_LIMIT_RETRIES:
                rate_limit_retries += 1
                wait = _retry_after_seconds(response)
                log.warning("429 on %s %s; waiting %.1f s", method, path, wait)
                await self._sleep(wait)
                continue
            if status in _RETRYABLE_READ_STATUS and is_read and not retried_read:
                retried_read = True
                log.warning("%s on %s %s; retrying once", status, method, path)
                await self._sleep(1.0)
                continue
            break

        if response.status_code >= 400:
            raise SiigoError.from_response(response, method, path)
        return _decode(response)

    async def _send(
        self,
        method: str,
        path: str,
        params: dict[str, Any],
        body: Any,
        extra_headers: dict[str, str] | None,
    ) -> httpx2.Response:
        credentials = self._require_credentials()
        request_headers = dict(extra_headers or {})
        request_headers["Partner-Id"] = credentials.partner_id
        request_headers["Authorization"] = f"Bearer {self._token}"
        response = await self._http.request(
            method,
            path,
            params=params or None,
            json=body if method in {"POST", "PUT", "PATCH"} else None,
            headers=request_headers,
        )
        self.request_count += 1
        log.info("%s %s -> %s", method, path, response.status_code)
        return response

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json: Any, headers: dict[str, str] | None = None) -> Any:
        return await self.request("POST", path, json=json, headers=headers)

    async def put(self, path: str, json: Any) -> Any:
        return await self.request("PUT", path, json=json)

    async def delete(self, path: str) -> Any:
        return await self.request("DELETE", path)
