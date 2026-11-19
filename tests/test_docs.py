"""Phase 6: the docs link check passes and the generated tool list is current."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parents[1]


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docs_links_are_valid() -> None:
    assert load("check_docs").check() == []


def test_link_checker_finds_broken_links(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text(
        "# Title\n\n## Good part\n\n[ok](#good-part) [ok](docs/a.md#a-b) [web](https://x.invalid)\n"
        "[bad](docs/missing.md) [bad anchor](#nope)\n\n```\n[ignored](in-code.md)\n```\n"
    )
    (tmp_path / "docs" / "a.md").write_text("# A b\n")
    errors = load("check_docs").check(tmp_path)
    assert errors == [
        "README.md: docs/missing.md (missing file)",
        "README.md: #nope (missing heading #nope)",
    ]


def test_tools_doc_is_current() -> None:
    module = load("build_tools_doc")
    catalog = json.loads(module.CATALOG.read_text(encoding="utf-8"))
    assert (ROOT / "docs" / "tools.md").read_text(encoding="utf-8") == module.render(catalog)
