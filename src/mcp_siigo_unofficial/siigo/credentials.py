"""Siigo API credentials (plan D7) and the Partner-Id rule."""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Default ``Partner-Id`` header value (plan P6). Editable in Settings.
DEFAULT_PARTNER_ID = "MCPSiigoUnofficial"

#: Siigo accepts 3 to 100 alphanumeric characters, with no spaces or symbols.
PARTNER_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{3,100}$")


def is_valid_partner_id(value: str) -> bool:
    """Return True if Siigo accepts ``value`` as a ``Partner-Id`` header."""
    return PARTNER_ID_PATTERN.fullmatch(value) is not None


@dataclass(frozen=True, repr=False)
class SiigoCredentials:
    """API username, access key, and Partner-Id. ``repr`` never shows the key."""

    username: str
    access_key: str
    partner_id: str = DEFAULT_PARTNER_ID

    def __post_init__(self) -> None:
        if not self.username.strip():
            raise ValueError("The Siigo API username is empty.")
        if not self.access_key.strip():
            raise ValueError("The Siigo access key is empty.")
        if not is_valid_partner_id(self.partner_id):
            raise ValueError("Partner-Id must be 3 to 100 letters or digits, with no spaces.")

    def __repr__(self) -> str:
        return (
            f"SiigoCredentials(username={self.username!r}, access_key='***', "
            f"partner_id={self.partner_id!r})"
        )

    __str__ = __repr__
