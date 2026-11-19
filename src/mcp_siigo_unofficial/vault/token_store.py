"""Keeps the shared Siigo token in the encrypted vault (one-click plan v3, Q2e)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp_siigo_unofficial.siigo.token import SharedToken
from mcp_siigo_unofficial.vault.store import FIELD_SIIGO_SHARED_TOKEN

if TYPE_CHECKING:
    from mcp_siigo_unofficial.vault.store import Vault


class VaultTokenStore:
    """A ``TokenStore`` backed by an encrypted vault secret."""

    def __init__(self, vault: Vault) -> None:
        self._vault = vault

    def __repr__(self) -> str:
        return "VaultTokenStore()"

    def load(self) -> SharedToken | None:
        raw = self._vault.get_secret(FIELD_SIIGO_SHARED_TOKEN)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return SharedToken(str(data["token"]), float(data["expires_at"]), str(data["owner"]))
        except (ValueError, KeyError, TypeError):
            return None

    def save(self, token: SharedToken) -> None:
        payload = {"token": token.token, "expires_at": token.expires_at, "owner": token.owner}
        self._vault.set_secret(FIELD_SIIGO_SHARED_TOKEN, json.dumps(payload))

    def clear(self) -> None:
        self._vault.delete_secret(FIELD_SIIGO_SHARED_TOKEN)
