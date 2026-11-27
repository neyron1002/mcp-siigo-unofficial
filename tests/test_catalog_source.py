"""Decision A7: the catalog source is in the repository, and catalog.json matches it."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from mcp_siigo_unofficial.server.catalog import load_catalog

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


# Phase 10: the schemas follow the Siigo docs of 2026-11-27 (U1-U6, U8).


def _body(name: str) -> dict[str, Any]:
    schema = load_catalog().get(name).body_schema
    assert schema is not None
    return schema


def test_misc_income_voucher_uses_the_misc_income_type() -> None:  # U1
    body = _body("siigo_create_voucher_misc_income")
    assert body["properties"]["type"]["enum"] == ["MiscIncome"]
    assert {"income", "payment"} <= set(body["required"])
    assert "items" not in body["properties"]  # the removed "Detailed" layout


def test_voucher_has_no_detailed_type() -> None:  # U2
    body = _body("siigo_create_voucher")
    assert body["properties"]["type"]["enum"] == ["DebtPayment", "AdvancePayment"]
    assert "cost_center" in body["properties"]


def test_health_sector_fields() -> None:  # U3, U4
    for name in ("siigo_create_invoice", "siigo_create_credit_note"):
        health = _body(name)["properties"]["healthcare_company"]
        assert health["required"] == ["operation_type"]
        assert health["properties"]["operation_type"]["enum"] == [
            "SS-CUFE",
            "SS-SinAporte",
            "SS-Recaudo",
        ]
        plans = health["properties"]["service_plan"]["enum"]
        assert "01" not in plans
        assert {"16", "17"} <= set(plans)
        assert "nonContractInvoiceReason" in health["properties"]
    assert {"retentions", "advance_payment"} <= set(_body("siigo_create_invoice")["properties"])
    assert {"customer", "seller", "invoice_data"} <= set(
        _body("siigo_create_credit_note")["properties"]
    )


def test_customers_accept_cucon() -> None:  # U5
    for name in ("siigo_create_customer", "siigo_update_customer"):
        extra = _body(name)["properties"]["additional_fields"]
        assert "CUCON" in extra["properties"]


def test_products_accept_combos() -> None:  # U6
    for name in ("siigo_create_product", "siigo_update_product"):
        props = _body(name)["properties"]
        assert "Combo" in props["type"]["enum"]
        assert props["components"]["items"]["required"] == ["code", "quantity"]


def test_document_type_tools_have_no_fake_filters() -> None:  # U8
    for tool in load_catalog().tools:
        if tool.path == "/v1/document-types" and tool.fixed_query:
            assert tool.params == (), tool.name


def test_every_write_tool_has_a_risk_level() -> None:
    import json

    data = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    for tool in data["tools"]:
        if not tool["read_only"]:
            assert tool["risk"] in {"change", "outbound", "permanent"}, tool["name"]
