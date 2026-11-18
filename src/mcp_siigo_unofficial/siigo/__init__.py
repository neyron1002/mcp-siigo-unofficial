"""Siigo REST API client."""

from mcp_siigo_unofficial.siigo.client import DEFAULT_BASE_URL, SiigoClient
from mcp_siigo_unofficial.siigo.credentials import (
    DEFAULT_PARTNER_ID,
    SiigoCredentials,
    is_valid_partner_id,
)
from mcp_siigo_unofficial.siigo.errors import SiigoAuthError, SiigoError, SiigoNotConfiguredError

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_PARTNER_ID",
    "SiigoAuthError",
    "SiigoClient",
    "SiigoCredentials",
    "SiigoError",
    "SiigoNotConfiguredError",
    "is_valid_partner_id",
]
