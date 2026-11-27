"""Convert the Siigo endpoint catalog (YAML) into the shipped JSON catalog.

Source: ``scripts/catalog/endpoints.yaml``. It started as the catalog of the owner's own
earlier MCP server (authorship confirmed on 2026-11-18, MIT) and has been edited by hand in
this repository since 2026-11-27 (decision A7). It is a development file and is not shipped.

Plan D20: PyYAML is used only here and in the tests (dev dependency group); the app ships
JSON. ``tests/test_catalog_source.py`` fails when ``catalog.json`` is not rebuilt.

Usage (inside the dev container)::

    uv run python scripts/build_catalog.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "scripts/catalog/endpoints.yaml"
DEFAULT_OUTPUT = ROOT / "src/mcp_siigo_unofficial/server/catalog.json"

#: Read tools: every safe read endpoint of the source catalog.
READ_TOOLS: dict[str, str] = {
    "listar_productos": "list_products",
    "consultar_producto": "get_product",
    "listar_grupos_inventario": "list_account_groups",
    "listar_clientes": "list_customers",
    "consultar_cliente": "get_customer",
    "listar_tipos_factura": "list_invoice_types",
    "listar_facturas": "list_invoices",
    "consultar_factura": "get_invoice",
    "consultar_errores_dian_factura": "get_invoice_dian_errors",
    "obtener_pdf_factura": "get_invoice_pdf",
    "obtener_xml_factura": "get_invoice_xml",
    "listar_tipos_cotizacion": "list_quotation_types",
    "listar_cotizaciones": "list_quotations",
    "consultar_cotizacion": "get_quotation",
    "listar_tipos_nota_credito": "list_credit_note_types",
    "listar_notas_credito": "list_credit_notes",
    "consultar_nota_credito": "get_credit_note",
    "obtener_pdf_nota_credito": "get_credit_note_pdf",
    "listar_tipos_factura_compra": "list_purchase_types",
    "consultar_factura_compra": "get_purchase",
    "listar_tipos_documento_soporte": "list_support_document_types",
    "consultar_documento_soporte": "get_support_document",
    "listar_tipos_recibo_caja": "list_voucher_types",
    "listar_recibos_caja": "list_vouchers",
    "consultar_recibo_caja": "get_voucher",
    "listar_tipos_recibo_pago": "list_payment_receipt_types",
    "listar_recibos_pago": "list_payment_receipts",
    "consultar_recibo_pago": "get_payment_receipt",
    "listar_tipos_comprobante_contable": "list_journal_types",
    "listar_comprobantes_contables": "list_journals",
    "consultar_comprobante_contable": "get_journal",
    "generar_balance_prueba": "get_trial_balance_report",
    "generar_balance_prueba_por_tercero": "get_trial_balance_by_third_party_report",
    "consultar_cuentas_por_pagar": "list_accounts_payable",
    "listar_impuestos": "list_taxes",
    "listar_listas_precios": "list_price_lists",
    "listar_bodegas": "list_warehouses",
    "listar_usuarios": "list_users",
    "listar_tipos_documento": "list_document_types",
    "listar_formas_pago": "list_payment_types",
    "listar_centros_costo": "list_cost_centers",
    "listar_descuentos_recibo_caja": "list_expenses",
    "listar_otros_ingresos": "list_misc_incomes",
    "listar_activos_fijos": "list_fixed_assets",
    "listar_webhooks": "list_webhooks",
}

#: Write tools: only the scope of plan section 5 (create/update customers and
#: products; create invoices, credit notes, cash receipts, and journals).
WRITE_TOOLS: dict[str, str] = {
    "crear_cliente": "create_customer",
    "actualizar_cliente": "update_customer",
    "crear_producto": "create_product",
    "actualizar_producto": "update_product",
    "crear_factura": "create_invoice",
    "crear_nota_credito": "create_credit_note",
    "crear_recibo_caja": "create_voucher",
    "crear_recibo_caja_otros_ingresos": "create_voucher_misc_income",
    "crear_comprobante_contable": "create_journal",
}

#: Risk level of each write tool (API coverage plan, Part 3). Writes not listed here
#: are plain creates or updates ("change").
RISK: dict[str, str] = {}

#: Writes left out on purpose (deletes, annulments, emails, batches, and resources
#: outside plan section 5). Listed so that a new source endpoint is never missed.
EXCLUDED: frozenset[str] = frozenset(
    {
        "generar_token",
        "eliminar_producto",
        "crear_grupo_inventario",
        "actualizar_grupo_inventario",
        "actualizar_factura",
        "crear_lote_facturas",
        "eliminar_factura",
        "anular_factura",
        "enviar_factura_por_correo",
        "crear_cotizacion",
        "actualizar_cotizacion",
        "eliminar_cotizacion",
        "crear_factura_compra",
        "actualizar_factura_compra",
        "eliminar_factura_compra",
        "crear_documento_soporte",
        "actualizar_documento_soporte",
        "eliminar_documento_soporte",
        "crear_recibo_pago",
        "crear_recibo_pago_avanzado",
        "eliminar_recibo_pago",
        "crear_webhook",
        "actualizar_webhook",
        "eliminar_webhook",
    }
)


def _title(name: str) -> str:
    return name.replace("_", " ").capitalize().replace("Dian", "DIAN").replace("Pdf", "PDF")


def dedupe_required(node: Any) -> Any:
    """Remove repeated names from every JSON Schema ``required`` list (keeps the order).

    The Claude API rejects schemas whose ``required`` has duplicate items, and Claude
    Code then hides the whole tool.
    """
    if isinstance(node, dict):
        out = {k: dedupe_required(v) for k, v in node.items()}
        required = out.get("required")
        if isinstance(required, list):
            out["required"] = list(dict.fromkeys(required))
        return out
    if isinstance(node, list):
        return [dedupe_required(v) for v in node]
    return node


def convert(source: dict[str, Any]) -> dict[str, Any]:
    endpoints = source["endpoints"]
    names = {e["nombre"] for e in endpoints}
    mapped = set(READ_TOOLS) | set(WRITE_TOOLS) | EXCLUDED
    unknown = names - mapped
    missing = mapped - names
    if unknown or missing:
        raise SystemExit(f"Catalog mismatch. Unmapped: {sorted(unknown)}; gone: {sorted(missing)}")

    tools: list[dict[str, Any]] = []
    for e in endpoints:
        source_name = e["nombre"]
        if source_name in EXCLUDED:
            continue
        read_only = source_name in READ_TOOLS
        if read_only != bool(e["lectura"]):
            raise SystemExit(f"{source_name}: read/write flag does not match the source")
        name = READ_TOOLS.get(source_name) or WRITE_TOOLS[source_name]
        tool: dict[str, Any] = {
            "name": f"siigo_{name}",
            "title": _title(name),
            "method": e["metodo"],
            "path": e["ruta"],
            "read_only": read_only,
            "description": " ".join(str(e["descripcion"]).split()),
            "params": [
                {
                    "name": p["nombre"],
                    "in": p["en"],
                    "type": p.get("tipo", "string"),
                    "required": bool(p.get("obligatorio", False)),
                    "description": p.get("descripcion", ""),
                }
                for p in e.get("parametros", [])
            ],
            "fixed_query": e.get("query_fija") or {},
            "body_schema": dedupe_required(e.get("cuerpo")),
        }
        if not read_only:
            tool["request_example"] = e.get("ejemplo_peticion")
            tool["notes"] = e.get("notas") or []
            tool["risk"] = RISK.get(source_name, "change")
        tools.append(tool)
    return {
        "source": "owner's mcp_siigo catalog",
        "source_version": str(source.get("version", "")),
        "base_url": source.get("base_url", "https://api.siigo.com"),
        "tools": tools,
    }


def render(catalog: dict[str, Any]) -> str:
    """The exact text of ``catalog.json`` for a converted catalog."""
    return json.dumps(catalog, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"


def build(source: Path = DEFAULT_SOURCE) -> str:
    """Read the YAML source and return the ``catalog.json`` text."""
    return render(convert(yaml.safe_load(source.read_text(encoding="utf-8"))))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    data = yaml.safe_load(args.source.read_text(encoding="utf-8"))
    catalog = convert(data)
    text = render(catalog)
    args.output.write_text(text, encoding="utf-8")
    reads = sum(t["read_only"] for t in catalog["tools"])
    writes = len(catalog["tools"]) - reads
    sys.stdout.write(
        f"{args.output}: {reads} read tools, {writes} write tools, {len(text)} bytes\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
