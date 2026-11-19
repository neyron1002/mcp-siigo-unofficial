"""Command-line access to the installer (CI, scripts, and the launcher's uninstall).

``--list-clients`` prints each AI app's state; ``--connect-clients``,
``--disconnect-clients``, and ``--repair-clients`` change only our own entries. The
output is JSON and never contains the private key.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

from mcp_siigo_unofficial.clients.apps import Environment
from mcp_siigo_unofficial.clients.installer import ConflictPolicy, Installer
from mcp_siigo_unofficial.clients.specs import ServerSpec, Transport

if TYPE_CHECKING:
    from mcp_siigo_unofficial.vault import Vault

#: Exit codes: everything done, something failed, an existing "siigo" entry needs the user.
EXIT_OK, EXIT_FAILED, EXIT_CONFLICT = 0, 1, 3


def stdio_spec() -> ServerSpec:
    from mcp_siigo_unofficial.app.client_setup import stdio_command

    return ServerSpec.stdio(stdio_command())


def http_spec(vault: Vault) -> ServerSpec:
    from mcp_siigo_unofficial.server.transport import (
        DEFAULT_PORT,
        MCP_PATH,
        SETTING_PORT,
        ensure_bearer_key,
    )

    port = int(vault.get_setting(SETTING_PORT, DEFAULT_PORT))
    return ServerSpec.http(f"http://127.0.0.1:{port}{MCP_PATH}", ensure_bearer_key(vault))


class _LazySpecs:
    """Builds specs on demand; the vault is opened only when HTTP is involved."""

    def __init__(self) -> None:
        self._vault: Vault | None = None
        self._vault_failed = False

    def __call__(self, transport: Transport) -> ServerSpec | None:
        if transport == "stdio":
            return stdio_spec()
        vault = self._open_vault()
        return http_spec(vault) if vault is not None else None

    def _open_vault(self) -> Vault | None:
        if self._vault is None and not self._vault_failed:
            from mcp_siigo_unofficial.paths import vault_path
            from mcp_siigo_unofficial.vault import KeyringKeyStore, Vault

            try:
                self._vault = Vault.open(vault_path(), KeyringKeyStore())
            except Exception:
                self._vault_failed = True
        return self._vault

    def close(self) -> None:
        if self._vault is not None:
            self._vault.close()


def run(
    action: str,
    *,
    clients: Sequence[str] | None = None,
    transport: Transport = "stdio",
    on_conflict: ConflictPolicy = "ask",
    env: Environment | None = None,
) -> int:
    specs = _LazySpecs()
    installer = Installer(env or Environment.current(), specs)
    try:
        if action == "list":
            payload: dict[str, object] = {
                "clients": [s.to_dict() for s in installer.status(clients or None)]
            }
            code = EXIT_OK
        else:
            if action == "connect":
                results = installer.connect(
                    clients or None, transport=transport, on_conflict=on_conflict
                )
            elif action == "disconnect":
                results = installer.disconnect(clients or None)
            elif action == "repair":
                results = installer.repair(clients or None)
            else:
                raise ValueError(action)
            payload = {"action": action, "results": [r.to_dict() for r in results]}
            if any(r.outcome == "failed" for r in results):
                code = EXIT_FAILED
            elif any(r.outcome == "conflict" for r in results):
                code = EXIT_CONFLICT
            else:
                code = EXIT_OK
    except KeyError as exc:
        sys.stderr.write(f"Unknown AI app: {exc.args[0]}\n")
        return 2
    finally:
        specs.close()
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return code
