"""Generate ``docs/tools.md`` from the shipped tool catalog (a test keeps it current).

Usage (inside the dev container)::

    uv run python scripts/build_tools_doc.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "src/mcp_siigo_unofficial/server/catalog.json"
OUTPUT = ROOT / "docs/tools.md"

HEADER = """# MCP tools

Generated from the tool catalog by `scripts/build_tools_doc.py`; do not edit it by hand.

The server always offers `siigo_status` and every read tool. The write tools are listed
only while the **Write actions** switch is on (see [Write actions](usage.md#write-actions)),
and every write still needs your approval.

"""


def render(catalog: dict[str, object]) -> str:
    tools = sorted(catalog["tools"], key=lambda t: t["name"])  # type: ignore[index]
    reads = [t for t in tools if t["read_only"]]
    writes = [t for t in tools if not t["read_only"]]
    lines = [HEADER.rstrip("\n"), ""]
    lines += [
        "## Status",
        "",
        "| Tool | What it does |",
        "|---|---|",
        "| `siigo_status` | The app version, whether Siigo credentials are set, and whether "
        "write actions are on. Never returns secrets. |",
        "",
    ]
    groups = ((f"Read tools ({len(reads)})", reads), (f"Write tools ({len(writes)})", writes))
    for title, group in groups:
        lines += [f"## {title}", "", "| Tool | Title | Siigo API |", "|---|---|---|"]
        lines += [f"| `{t['name']}` | {t['title']} | `{t['method']} {t['path']}` |" for t in group]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    text = render(json.loads(CATALOG.read_text(encoding="utf-8")))
    if "--check" in sys.argv:
        if OUTPUT.read_text(encoding="utf-8") != text:
            print(f"{OUTPUT} is out of date; run scripts/build_tools_doc.py", file=sys.stderr)
            return 1
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
