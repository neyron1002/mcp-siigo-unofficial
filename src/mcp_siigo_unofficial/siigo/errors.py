"""Readable errors for Siigo API failures."""

from __future__ import annotations

from typing import Any

import httpx2


class SiigoError(Exception):
    """A Siigo API error (HTTP status, Siigo error code, and details) or a network error."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        errors: list[dict[str, Any]] | None = None,
        method: str | None = None,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.errors = errors or []
        self.method = method
        self.path = path

    def to_dict(self) -> dict[str, Any]:
        """Compact, secret-free representation for MCP tool results."""
        return {
            "message": self.message,
            "status": self.status,
            "code": self.code,
            "errors": self.errors,
            "method": self.method,
            "path": self.path,
        }

    @classmethod
    def from_response(cls, response: httpx2.Response, method: str, path: str) -> SiigoError:
        """Build an error from a Siigo response body (``{"Errors": [{"Code", ...}]}``)."""
        errors: list[dict[str, Any]] = []
        message = f"Siigo answered HTTP {response.status_code} to {method} {path}"
        try:
            data: Any = response.json()
        except ValueError:
            data = None
        if isinstance(data, dict):
            raw = data.get("Errors") or data.get("errors") or []
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        errors.append(
                            {
                                "code": item.get("Code") or item.get("code"),
                                "message": item.get("Message") or item.get("message"),
                                "params": item.get("Params") or item.get("params") or [],
                                "detail": item.get("Detail") or item.get("detail"),
                            }
                        )
            texts = [f"{e['code']}: {e['message']}" for e in errors if e.get("message")]
            if texts:
                message += ": " + "; ".join(texts)
            elif data.get("Message") or data.get("message"):
                message += ": " + str(data.get("Message") or data.get("message"))
        elif response.text:
            message += ": " + response.text[:300]
        error_class = SiigoAuthError if response.status_code == 401 else cls
        return error_class(
            message,
            status=response.status_code,
            code=errors[0]["code"] if errors else None,
            errors=errors,
            method=method,
            path=path,
        )


class SiigoAuthError(SiigoError):
    """Authentication failed (wrong credentials or a rejected token)."""


class SiigoNotConfiguredError(SiigoError):
    """No Siigo credentials are stored yet."""
