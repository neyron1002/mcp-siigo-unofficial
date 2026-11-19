"""Careful edits of AI apps' settings files (one-click plan v3, section 4 of plan v2).

- A backup next to the file before the first change of the day:
  ``<file>.siigo-backup-<YYYY-MM-DD>``.
- Atomic writes: a temporary file in the same folder, then a rename. The file's
  permissions are kept; new files are private to the user (0600).
- A file that is not valid JSON or TOML is never overwritten.
- TOML (Codex) is read with the standard library's ``tomllib`` and edited as text:
  only our ``[mcp_servers.<name>]`` table is removed or appended, and the result is
  parsed again to prove that nothing else changed (no new dependency, plan rule 2).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import stat
import tempfile
import tomllib
from datetime import date
from pathlib import Path
from typing import Any


class ConfigFileError(Exception):
    """A settings file cannot be read or edited safely. Nothing was changed."""


# ---------------------------------------------------------------------- files
def backup_once(path: Path, today: date) -> Path | None:
    """Copy ``path`` to ``<path>.siigo-backup-<today>`` unless that backup exists."""
    if not path.is_file():
        return None
    backup = path.with_name(f"{path.name}.siigo-backup-{today.isoformat()}")
    if not backup.exists():
        shutil.copy2(path, backup)
    return backup


def atomic_write_text(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` in one rename, keeping its permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):  # Windows has no POSIX modes
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------- JSON
def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object; a missing or empty file is an empty object."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigFileError(f"{path} cannot be read: {exc.strerror}") from exc
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigFileError(
            f"{path} is not valid JSON (line {exc.lineno}). Fix it, then try again."
        ) from exc
    if not isinstance(data, dict):
        raise ConfigFileError(f"{path} does not hold a JSON object.")
    return data


def json_section(data: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    """The servers object inside a settings file (empty when absent)."""
    section = data.get(key, {})
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ConfigFileError(f'"{key}" in {path} is not an object.')
    return section


def write_json(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------- TOML
def read_toml(path: Path) -> tuple[str, dict[str, Any]]:
    """Return the text and the parsed data of a TOML file (missing file: empty)."""
    if not path.exists():
        return "", {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigFileError(f"{path} cannot be read: {exc.strerror}") from exc
    try:
        return text, tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigFileError(f"{path} is not valid TOML ({exc}). Fix it, then try again.") from exc


def toml_string(value: str) -> str:
    """A TOML basic string (JSON string escaping is valid TOML)."""
    return json.dumps(value, ensure_ascii=False)


def _table_key(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else toml_string(name)


def _header_pattern(table: str, name: str) -> re.Pattern[str]:
    quoted = re.escape(name)
    return re.compile(
        rf'^\s*\[\s*{re.escape(table)}\s*\.\s*(?:{quoted}|"{quoted}"|\'{quoted}\')\s*(?:\]|\.)'
    )


def _any_header(line: str) -> bool:
    return bool(re.match(r"^\s*\[", line))


def remove_toml_table(text: str, table: str, name: str) -> str:
    """Remove ``[table.name]`` and its sub-tables (``[table.name.env]``) from the text."""
    pattern = _header_pattern(table, name)
    out: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        if _any_header(line):
            skipping = bool(pattern.match(line))
        if not skipping:
            out.append(line)
    return "".join(out)


def render_toml_table(table: str, name: str, values: dict[str, Any]) -> str:
    lines = [f"[{table}.{_table_key(name)}]"]
    for key, value in values.items():
        lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        return toml_string(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        inner = ", ".join(f"{toml_string(str(k))} = {_toml_value(v)}" for k, v in value.items())
        return "{ " + inner + " }"
    raise TypeError(f"Unsupported TOML value: {type(value).__name__}")


def edit_toml_table(
    path: Path,
    table: str,
    name: str,
    values: dict[str, Any] | None,
) -> None:
    """Set (``values``) or remove (``None``) ``[table.name]``, changing nothing else."""
    text, data = read_toml(path)
    section = data.get(table, {})
    if not isinstance(section, dict):
        raise ConfigFileError(f'"{table}" in {path} is not a table.')
    pattern = _header_pattern(table, name)
    has_header = any(pattern.match(line) for line in text.splitlines())
    if name in section and not has_header:
        raise ConfigFileError(
            f"{path} defines {table}.{name} in a form that can't be edited safely. "
            "Edit it by hand, then try again."
        )
    new_text = remove_toml_table(text, table, name)
    if values is not None:
        if new_text and not new_text.endswith("\n"):
            new_text += "\n"
        if new_text.strip():
            new_text += "\n"
        new_text += render_toml_table(table, name, values)
    try:
        new_data = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as exc:  # pragma: no cover - defensive
        raise ConfigFileError(f"Editing {path} would break it; nothing was changed.") from exc
    _check_only_our_table_changed(path, data, new_data, table, name, values)
    atomic_write_text(path, new_text)


def _check_only_our_table_changed(
    path: Path,
    before: dict[str, Any],
    after: dict[str, Any],
    table: str,
    name: str,
    values: dict[str, Any] | None,
) -> None:
    def without_ours(data: dict[str, Any]) -> dict[str, Any]:
        copy = dict(data)
        section = dict(copy.get(table, {}))
        section.pop(name, None)
        if section:
            copy[table] = section
        else:
            copy.pop(table, None)
        return copy

    ours_after = after.get(table, {}).get(name)
    expected = None if values is None else {k: _plain(v) for k, v in values.items()}
    if without_ours(before) != without_ours(after) or ours_after != expected:
        raise ConfigFileError(f"Editing {path} would change other settings; nothing was changed.")


def _plain(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return value
