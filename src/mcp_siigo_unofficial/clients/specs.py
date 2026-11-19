"""The Siigo server entry that the installer writes into AI apps (one-click plan v3, Q2).

A *spec* is what we want to write; an *entry* is what an AI app's settings hold.
An entry is **ours** when it starts our launcher with ``--stdio``, or when it points
at the tray app's local HTTP endpoint (``http://127.0.0.1:<port>/mcp``). Only our
entries are ever changed or removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

SERVER_NAME = "siigo"
#: Name used for our entry when another program already uses ``siigo`` (Q11 "keep both").
ALT_SERVER_NAME = "siigo-unofficial"
SERVER_NAMES = (SERVER_NAME, ALT_SERVER_NAME)

Transport = Literal["stdio", "http"]
TRANSPORTS: tuple[Transport, ...] = ("stdio", "http")

#: File names (without extension, lower case) of our launcher and app executables.
_LAUNCHER_STEMS = frozenset({"launcher", "mcpsiigounofficial", "mcp-siigo-unofficial"})
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})


@dataclass(frozen=True)
class ServerSpec:
    """What one AI app should run to reach the Siigo server."""

    transport: Transport
    command: tuple[str, ...] = ()
    url: str = ""
    bearer_key: str = field(default="", repr=False)

    @classmethod
    def stdio(cls, command: tuple[str, ...] | list[str]) -> ServerSpec:
        if not command:
            raise ValueError("A stdio server needs a command.")
        return cls("stdio", command=tuple(command))

    @classmethod
    def http(cls, url: str, bearer_key: str) -> ServerSpec:
        if not url or not bearer_key:
            raise ValueError("An HTTP server needs a URL and a bearer key.")
        return cls("http", url=url, bearer_key=bearer_key)

    @property
    def authorization(self) -> str:
        return f"Bearer {self.bearer_key}" if self.bearer_key else ""

    def as_entry(self) -> Entry:
        return Entry(self.transport, self.command, self.url, self.authorization)


@dataclass(frozen=True)
class Entry:
    """A normalized view of one server entry in an AI app's settings."""

    transport: Transport | None
    command: tuple[str, ...] = ()
    url: str = ""
    authorization: str = field(default="", repr=False)


def _executable_stem(path: str) -> str:
    name = re.split(r"[\\/]", path)[-1].lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def is_ours(entry: Entry) -> bool:
    """True when the entry runs or reaches this app (never another program's server)."""
    if entry.transport == "stdio" and entry.command:
        if entry.command[-1] != "--stdio":
            return False
        if _executable_stem(entry.command[0]) in _LAUNCHER_STEMS:
            return True
        return "mcp_siigo_unofficial" in entry.command
    if entry.transport == "http" and entry.url:
        parts = urlsplit(entry.url)
        return (
            parts.scheme == "http"
            and parts.hostname in _LOCAL_HOSTS
            and parts.path.rstrip("/") == "/mcp"
        )
    return False


def matches(entry: Entry, spec: ServerSpec) -> bool:
    """True when the entry already does exactly what the spec asks."""
    if entry.transport != spec.transport:
        return False
    if spec.transport == "stdio":
        return entry.command == spec.command
    return entry.url == spec.url and entry.authorization == spec.authorization
