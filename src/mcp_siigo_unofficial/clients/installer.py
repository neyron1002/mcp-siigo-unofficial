"""Connect, disconnect, and repair the Siigo server in AI apps (one-click plan v3).

- **Connect** (Q2, Q2b, Q5, Q11): stdio by default, HTTP when asked (Claude Desktop
  is always stdio). The app's own command is used for stdio when found; the file is
  edited otherwise, and always for HTTP so the private key is never on a command line.
  Every result is checked by reading the settings back.
- **Disconnect** (Q13): removes only our entries.
- **Repair** (Q14): rewrites our own entries whose launcher path (or HTTP address or
  key) changed, keeping their name and connection type.
- Before the first change of the day, each settings file gets a backup.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

from mcp_siigo_unofficial.clients import configfiles
from mcp_siigo_unofficial.clients.apps import ALL_APPS, ClientApp, Environment
from mcp_siigo_unofficial.clients.specs import (
    ALT_SERVER_NAME,
    SERVER_NAME,
    Entry,
    ServerSpec,
    Transport,
    is_ours,
    matches,
)

State = Literal[
    "not_installed", "not_connected", "connected", "needs_repair", "conflict", "unreadable"
]
Outcome = Literal[
    "connected",
    "already_connected",
    "repaired",
    "disconnected",
    "not_connected",
    "not_installed",
    "conflict",
    "failed",
]
ConflictPolicy = Literal["ask", "keep-both", "replace"]
CONFLICT_POLICIES: tuple[ConflictPolicy, ...] = ("ask", "keep-both", "replace")


@dataclass(frozen=True)
class ClientStatus:
    """What the Connect window shows for one app (no secrets)."""

    id: str
    label: str
    installed: bool
    state: State
    transport: Transport | None = None
    name: str | None = None
    config_path: str = ""
    supports_http: bool = True
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ActionResult:
    id: str
    label: str
    outcome: Outcome
    transport: Transport | None = None
    name: str | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome not in ("failed", "conflict")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


SpecFactory = Callable[[Transport], ServerSpec | None]


class Installer:
    def __init__(
        self,
        env: Environment,
        spec_for: SpecFactory,
        *,
        apps: Iterable[ClientApp] = ALL_APPS,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.env = env
        self.spec_for = spec_for
        self.apps = tuple(apps)
        self.today = today

    # ---------------------------------------------------------------- reading
    def _select(self, ids: Iterable[str] | None) -> list[ClientApp]:
        if ids is None:
            return list(self.apps)
        wanted = list(ids)
        unknown = [i for i in wanted if i not in {a.id for a in self.apps}]
        if unknown:
            raise KeyError(", ".join(unknown))
        return [a for a in self.apps if a.id in wanted]

    @staticmethod
    def _ours(entries: dict[str, Entry]) -> tuple[str, Entry] | None:
        for name in (SERVER_NAME, ALT_SERVER_NAME):
            entry = entries.get(name)
            if entry is not None and is_ours(entry):
                return name, entry
        return None

    def status(self, ids: Iterable[str] | None = None) -> list[ClientStatus]:
        return [self._status(app) for app in self._select(ids)]

    def _status(self, app: ClientApp) -> ClientStatus:
        base = {
            "id": app.id,
            "label": app.label,
            "config_path": str(app.config_path(self.env)),
            "supports_http": app.supports_http,
        }
        if not app.is_installed(self.env):
            return ClientStatus(installed=False, state="not_installed", **base)  # type: ignore[arg-type]
        try:
            entries = app.read_entries(self.env)
        except configfiles.ConfigFileError as exc:
            return ClientStatus(installed=True, state="unreadable", detail=str(exc), **base)  # type: ignore[arg-type]
        ours = self._ours(entries)
        if ours is not None and ours[1].transport is not None:
            name, entry = ours
            spec = self.spec_for(entry.transport)  # type: ignore[arg-type]
            state: State = "connected" if spec is None or matches(entry, spec) else "needs_repair"
            return ClientStatus(
                installed=True,
                state=state,
                transport=entry.transport,
                name=name,
                **base,  # type: ignore[arg-type]
            )
        if SERVER_NAME in entries:
            return ClientStatus(
                installed=True,
                state="conflict",
                name=SERVER_NAME,
                detail=f'Another program already uses the name "{SERVER_NAME}".',
                **base,  # type: ignore[arg-type]
            )
        return ClientStatus(installed=True, state="not_connected", **base)  # type: ignore[arg-type]

    # ---------------------------------------------------------------- writing
    def _apply(self, app: ClientApp, name: str, spec: ServerSpec, *, replace: bool) -> None:
        """Write our entry under ``name``; raise ConfigFileError if it can't be verified."""
        configfiles.backup_once(app.config_path(self.env), self.today())
        exe = app.cli(self.env)
        add_args = app.cli_add_args(exe, name, spec) if exe is not None else None
        if exe is not None and add_args is not None:
            command_env = self.env.command_env()
            if replace:
                remove_args = app.cli_remove_args(exe, name)
                if remove_args is not None:
                    self.env.runner(remove_args, command_env)
            result = self.env.runner(add_args, command_env)
            if result.returncode == 0 and self._verify(app, name, spec):
                return
        app.write_entry(self.env, name, spec)
        if not self._verify(app, name, spec):
            raise configfiles.ConfigFileError(
                f"{app.label}: the Siigo entry could not be confirmed after writing it."
            )

    def _verify(self, app: ClientApp, name: str, spec: ServerSpec) -> bool:
        try:
            entry = app.read_entries(self.env).get(name)
        except configfiles.ConfigFileError:
            return False
        return entry is not None and matches(entry, spec)

    def _remove(self, app: ClientApp, name: str) -> None:
        configfiles.backup_once(app.config_path(self.env), self.today())
        exe = app.cli(self.env)
        remove_args = app.cli_remove_args(exe, name) if exe is not None else None
        if exe is not None and remove_args is not None:
            self.env.runner(remove_args, self.env.command_env())
            try:
                if name not in app.read_entries(self.env):
                    return
            except configfiles.ConfigFileError:
                pass
        app.remove_entry(self.env, name)

    def connect(
        self,
        ids: Iterable[str] | None = None,
        *,
        transport: Transport = "stdio",
        on_conflict: ConflictPolicy = "ask",
    ) -> list[ActionResult]:
        return [self._connect(app, transport, on_conflict) for app in self._select(ids)]

    def _connect(
        self, app: ClientApp, transport: Transport, on_conflict: ConflictPolicy
    ) -> ActionResult:
        if not app.is_installed(self.env):
            return ActionResult(app.id, app.label, "not_installed")
        effective: Transport = transport if app.supports_http else "stdio"
        spec = self.spec_for(effective)
        if spec is None:
            return ActionResult(
                app.id,
                app.label,
                "failed",
                effective,
                detail="The connection details are not available.",
            )
        try:
            entries = app.read_entries(self.env)
            ours = self._ours(entries)
            if ours is not None:
                name, entry = ours
                if matches(entry, spec):
                    return ActionResult(app.id, app.label, "already_connected", effective, name)
                self._apply(app, name, spec, replace=True)
                return ActionResult(app.id, app.label, "connected", effective, name)
            name, replace = SERVER_NAME, False
            if SERVER_NAME in entries:
                if on_conflict == "ask":
                    return ActionResult(
                        app.id,
                        app.label,
                        "conflict",
                        effective,
                        SERVER_NAME,
                        f'Another program already uses the name "{SERVER_NAME}".',
                    )
                if on_conflict == "keep-both":
                    if ALT_SERVER_NAME in entries:
                        return ActionResult(
                            app.id,
                            app.label,
                            "conflict",
                            effective,
                            ALT_SERVER_NAME,
                            f'Other programs already use "{SERVER_NAME}" and "{ALT_SERVER_NAME}".',
                        )
                    name = ALT_SERVER_NAME
                else:
                    replace = True
            self._apply(app, name, spec, replace=replace)
            detail = f"Restart {app.label} to see the Siigo tools." if app.needs_restart else ""
            return ActionResult(app.id, app.label, "connected", effective, name, detail)
        except (configfiles.ConfigFileError, OSError) as exc:
            return ActionResult(app.id, app.label, "failed", effective, detail=_error_text(exc))

    def disconnect(self, ids: Iterable[str] | None = None) -> list[ActionResult]:
        results = []
        for app in self._select(ids):
            if not app.is_installed(self.env):
                results.append(ActionResult(app.id, app.label, "not_installed"))
                continue
            try:
                entries = app.read_entries(self.env)
                names = [n for n, e in entries.items() if is_ours(e)]
                if not names:
                    results.append(ActionResult(app.id, app.label, "not_connected"))
                    continue
                for name in names:
                    self._remove(app, name)
                remaining = app.read_entries(self.env)
                if any(n in remaining and is_ours(remaining[n]) for n in names):
                    raise configfiles.ConfigFileError(
                        f"{app.label}: the Siigo entry is still there."
                    )
                results.append(ActionResult(app.id, app.label, "disconnected", name=names[0]))
            except (configfiles.ConfigFileError, OSError) as exc:
                results.append(ActionResult(app.id, app.label, "failed", detail=_error_text(exc)))
        return results

    def repair(self, ids: Iterable[str] | None = None) -> list[ActionResult]:
        """Rewrite our own entries that point to an old launcher, address, or key (Q14)."""
        results = []
        for status in self.status(ids):
            if status.state != "needs_repair" or status.transport is None or status.name is None:
                continue
            app = next(a for a in self.apps if a.id == status.id)
            spec = self.spec_for(status.transport)
            if spec is None:
                continue
            try:
                self._apply(app, status.name, spec, replace=True)
                results.append(
                    ActionResult(app.id, app.label, "repaired", status.transport, status.name)
                )
            except (configfiles.ConfigFileError, OSError) as exc:
                results.append(
                    ActionResult(
                        app.id, app.label, "failed", status.transport, detail=_error_text(exc)
                    )
                )
        return results


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, OSError):
        return f"{type(exc).__name__}: {exc.strerror or exc}"
    return str(exc)
