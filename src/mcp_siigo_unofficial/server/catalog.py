"""The shipped Siigo endpoint catalog (``catalog.json``, built by ``scripts/build_catalog.py``)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any, Literal

ParamType = Literal["string", "integer", "number", "boolean", "array", "object"]


@dataclass(frozen=True)
class Param:
    name: str
    location: Literal["path", "query"]
    type: ParamType
    required: bool
    description: str

    @property
    def python_name(self) -> str:
        """A valid Python identifier for the tool function signature."""
        return re.sub(r"\W", "_", self.name)


@dataclass(frozen=True)
class EndpointTool:
    """One MCP tool backed by one Siigo endpoint."""

    name: str
    title: str
    method: str
    path: str
    read_only: bool
    description: str
    params: tuple[Param, ...]
    fixed_query: dict[str, str] = field(default_factory=dict)
    body_schema: dict[str, Any] | None = None
    request_example: Any = None
    notes: tuple[str, ...] = ()

    @property
    def path_params(self) -> tuple[Param, ...]:
        return tuple(p for p in self.params if p.location == "path")

    @property
    def query_params(self) -> tuple[Param, ...]:
        return tuple(p for p in self.params if p.location == "query")

    def build_path(self, values: dict[str, Any]) -> str:
        path = self.path
        for param in self.path_params:
            value = values.get(param.python_name)
            if value is None or str(value).strip() == "":
                raise ValueError(f"The path parameter '{param.name}' is required.")
            text = str(value).strip()
            if not re.fullmatch(r"[A-Za-z0-9_\-]+", text):
                raise ValueError(f"The path parameter '{param.name}' has invalid characters.")
            path = path.replace("{" + param.name + "}", text)
        return path

    def build_query(self, values: dict[str, Any]) -> dict[str, Any]:
        query: dict[str, Any] = dict(self.fixed_query)
        for param in self.query_params:
            value = values.get(param.python_name)
            if value is not None:
                query[param.name] = value
        return query


@dataclass(frozen=True)
class Catalog:
    base_url: str
    source_version: str
    tools: tuple[EndpointTool, ...]

    @property
    def read_tools(self) -> tuple[EndpointTool, ...]:
        return tuple(t for t in self.tools if t.read_only)

    @property
    def write_tools(self) -> tuple[EndpointTool, ...]:
        return tuple(t for t in self.tools if not t.read_only)

    def get(self, name: str) -> EndpointTool:
        for tool in self.tools:
            if tool.name == name:
                return tool
        raise KeyError(name)


def _parse(data: dict[str, Any]) -> Catalog:
    tools = []
    for raw in data["tools"]:
        tools.append(
            EndpointTool(
                name=raw["name"],
                title=raw["title"],
                method=raw["method"],
                path=raw["path"],
                read_only=bool(raw["read_only"]),
                description=raw["description"],
                params=tuple(
                    Param(p["name"], p["in"], p["type"], bool(p["required"]), p["description"])
                    for p in raw["params"]
                ),
                fixed_query=dict(raw.get("fixed_query") or {}),
                body_schema=raw.get("body_schema"),
                request_example=raw.get("request_example"),
                notes=tuple(raw.get("notes") or ()),
            )
        )
    return Catalog(data["base_url"], data["source_version"], tuple(tools))


@cache
def load_catalog() -> Catalog:
    """Load the catalog shipped inside the package."""
    text = resources.files(__package__).joinpath("catalog.json").read_text(encoding="utf-8")
    return _parse(json.loads(text))
