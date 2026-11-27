"""Idempotency-Key for document creation (decision A6, 2026-11-27).

Siigo accepts an ``Idempotency-Key`` header on ``POST`` for sales invoices, credit
notes, journals, and cash receipts. When a key arrives again, Siigo returns the
document it created the first time instead of creating a second one.

The key is made from the request content (path and body), so when an AI app sends
the same document again (for example after a timeout), Siigo does not create a
duplicate. To create an identical document on purpose, the user changes something
small, such as the observations.

Siigo's rules for the key: alphanumeric, no spaces or special characters, at most
30 characters. A hexadecimal SHA-256 prefix meets them.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

HEADER = "Idempotency-Key"
KEY_LENGTH = 30

#: The Siigo paths that accept the header on POST.
PATHS: frozenset[str] = frozenset(
    {"/v1/invoices", "/v1/credit-notes", "/v1/journals", "/v1/vouchers"}
)

#: Added to the description of every tool the key applies to.
NOTE = (
    "Duplicate protection: the app sends an Idempotency-Key made from the request "
    "content. If a document with exactly the same content was already sent, Siigo "
    "returns that document instead of creating a new one. To create an identical "
    "document on purpose, change something small, such as the observations."
)


def applies(method: str, path: str) -> bool:
    """True when Siigo accepts the key for this call."""
    return method.upper() == "POST" and path in PATHS


def key_for(path: str, body: Any) -> str:
    """The key for a request body: the same content always gives the same key."""
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"POST {path}\n{canonical}".encode()).hexdigest()
    return digest[:KEY_LENGTH]


def headers_for(method: str, path: str, body: Any) -> dict[str, str]:
    """The extra headers for a call: the key when it applies, otherwise none."""
    if body is None or not applies(method, path):
        return {}
    return {HEADER: key_for(path, body)}
