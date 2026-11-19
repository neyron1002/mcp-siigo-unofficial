"""One-click connection of the Siigo server to AI apps (one-click plan v3, phase 7)."""

from mcp_siigo_unofficial.clients.apps import ALL_APPS, APP_IDS, ClientApp, Environment, app_by_id
from mcp_siigo_unofficial.clients.configfiles import ConfigFileError
from mcp_siigo_unofficial.clients.installer import (
    CONFLICT_POLICIES,
    ActionResult,
    ClientStatus,
    Installer,
)
from mcp_siigo_unofficial.clients.specs import (
    ALT_SERVER_NAME,
    SERVER_NAME,
    TRANSPORTS,
    Entry,
    ServerSpec,
    is_ours,
    matches,
)

__all__ = [
    "ALL_APPS",
    "ALT_SERVER_NAME",
    "APP_IDS",
    "CONFLICT_POLICIES",
    "SERVER_NAME",
    "TRANSPORTS",
    "ActionResult",
    "ClientApp",
    "ClientStatus",
    "ConfigFileError",
    "Entry",
    "Environment",
    "Installer",
    "ServerSpec",
    "app_by_id",
    "is_ours",
    "matches",
]
