"""SemVer 2.0 parsing and ordering (release tags are ``vX.Y.Z`` or ``vX.Y.Z-rc.N``)."""

from __future__ import annotations

import re

_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$")

VersionKey = tuple[int, int, int, tuple[int, tuple[tuple[int, int | str], ...]]]


def version_key(version: str) -> VersionKey:
    """A sort key that follows SemVer precedence. Raises ValueError if not SemVer."""
    match = _SEMVER.match(version.strip())
    if match is None:
        raise ValueError(f"Not a SemVer version: {version!r}")
    major, minor, patch, pre = match.groups()
    if pre is None:
        pre_key: tuple[int, tuple[tuple[int, int | str], ...]] = (1, ())
    else:
        # Numeric identifiers sort before alphanumeric ones, and numerically.
        ids = tuple((0, int(p)) if p.isdigit() else (1, p) for p in pre.split("."))
        pre_key = (0, ids)
    return int(major), int(minor), int(patch), pre_key


def is_prerelease(version: str) -> bool:
    return version_key(version)[3][0] == 0


def is_newer(candidate: str, current: str) -> bool:
    return version_key(candidate) > version_key(current)
