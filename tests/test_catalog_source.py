"""Decision A7: the catalog source is in the repository, and catalog.json matches it."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parents[1]
CATALOG_JSON = ROOT / "src/mcp_siigo_unofficial/server/catalog.json"


def load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_catalog", ROOT / "scripts" / "build_catalog.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_json_is_built_from_the_source() -> None:
    expected = load_builder().build()
    actual = CATALOG_JSON.read_text(encoding="utf-8")
    assert actual == expected, (
        "catalog.json is out of date: run `uv run python scripts/build_catalog.py`"
    )


def test_source_has_no_credentials() -> None:
    import yaml

    data = yaml.safe_load((ROOT / "scripts/catalog/endpoints.yaml").read_text(encoding="utf-8"))
    auth = next(e for e in data["endpoints"] if e["nombre"] == "generar_token")
    # The docs' example access key is replaced by a placeholder (CLAUDE.md rule 4).
    assert auth["cuerpo"]["properties"]["access_key"]["example"] == "[access key]"
