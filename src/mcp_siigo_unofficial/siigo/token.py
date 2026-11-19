"""A Siigo access token shared by the app's processes (one-click plan v3, Q2e).

With stdio, every AI session starts its own server process. Instead of each one
logging in to Siigo, the first process stores the token in the encrypted vault and
the others reuse it until it expires. The token is never returned by a tool,
printed, or logged (plan rule 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class SharedToken:
    token: str = field(repr=False)
    #: Wall-clock expiry (seconds since the epoch), comparable across processes.
    expires_at: float
    #: SHA-256 fingerprint of the credentials that produced the token (not a secret).
    owner: str


class TokenStore(Protocol):
    def load(self) -> SharedToken | None: ...

    def save(self, token: SharedToken) -> None: ...

    def clear(self) -> None: ...
