"""Docs link check (plan phase 6): every relative link and ``#anchor`` in the Markdown
files must point to a file or heading that exists.

External links are not fetched (CI must not depend on other websites).

Usage::

    uv run python scripts/check_docs.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["README.md", "CLAUDE.md", "docs/*.md", ".devcontainer/README.md"]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)


def slug(heading: str) -> str:
    """GitHub's heading anchor: lower case, punctuation removed, spaces to hyphens."""
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    text = FENCE.sub("", path.read_text(encoding="utf-8"))
    found: set[str] = set()
    counts: dict[str, int] = {}
    for match in re.finditer(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.MULTILINE):
        base = slug(match.group(1))
        n = counts.get(base, 0)
        counts[base] = n + 1
        found.add(base if n == 0 else f"{base}-{n}")
    return found


def check(root: Path = ROOT) -> list[str]:
    errors = []
    files = sorted({p for pattern in FILES for p in root.glob(pattern)})
    for path in files:
        text = FENCE.sub("", path.read_text(encoding="utf-8"))
        for target in LINK.findall(text):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target):  # http:, https:, mailto:
                continue
            file_part, _, anchor = target.partition("#")
            dest = (path.parent / file_part).resolve() if file_part else path
            where = f"{path.relative_to(root)}: {target}"
            if not dest.exists():
                errors.append(f"{where} (missing file)")
            elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
                errors.append(f"{where} (missing heading #{anchor})")
    return errors


def main() -> int:
    errors = check()
    for error in errors:
        print(f"broken link: {error}", file=sys.stderr)
    if not errors:
        print("All documentation links are valid.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
