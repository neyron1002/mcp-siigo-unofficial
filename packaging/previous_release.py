"""Print ``from_tag=<tag>`` and ``expect=<version>`` for the update test (GitHub output).

Reads the GitHub releases JSON and picks the newest published release older than
the given tag. Prints ``from_tag=`` (empty) when there is none.

Usage::

    gh api repos/OWNER/REPO/releases > releases.json
    python packaging/previous_release.py releases.json v0.1.0-rc.2 >> "$GITHUB_OUTPUT"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcp_siigo_unofficial.update.versions import version_key


def previous_tag(releases: list[dict[str, object]], tag: str) -> str | None:
    current = version_key(tag)
    older = []
    for item in releases:
        name = str(item.get("tag_name", ""))
        if item.get("draft"):
            continue
        try:
            key = version_key(name)
        except ValueError:
            continue
        if key < current:
            older.append((key, name))
    return max(older)[1] if older else None


def main() -> int:
    releases = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    tag = sys.argv[2]
    found = previous_tag(releases, tag)
    print(f"from_tag={found or ''}")
    print(f"expect={tag.removeprefix('v')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
