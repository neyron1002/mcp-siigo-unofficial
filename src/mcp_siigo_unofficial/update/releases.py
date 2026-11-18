"""Find a newer release on GitHub and download it with its signature checked (plan D11).

A release is used only when it has this system's file, ``SHA256SUMS``, and
``SHA256SUMS.sig``. The download is accepted only when the Ed25519 signature
matches the public key shipped inside the app, and the file matches its signed
SHA-256. Pre-releases are offered only to pre-release builds (``-rc.N``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2

from mcp_siigo_unofficial import __version__
from mcp_siigo_unofficial.update.assets import artifact_name
from mcp_siigo_unofficial.update.signature import (
    SIGNATURE_NAME,
    SUMS_NAME,
    SignatureError,
    verify_file,
)
from mcp_siigo_unofficial.update.versions import is_newer, is_prerelease, version_key

REPOSITORY = "neyron1002/mcp-siigo-unofficial"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
#: Optional GitHub token for the releases API (CI only: shared runners hit the
#: anonymous rate limit). It is sent only to api.github.com, never with downloads.
TOKEN_ENV = "MCP_SIIGO_UNOFFICIAL_GITHUB_TOKEN"  # noqa: S105 - a variable name
USER_AGENT = f"mcp-siigo-unofficial/{__version__}"


class UpdateError(Exception):
    """The update check, download, or verification failed (message for the user)."""


@dataclass(frozen=True)
class Release:
    tag: str
    version: str
    prerelease: bool
    page_url: str
    assets: dict[str, str]  # file name -> download URL

    @property
    def file_name(self) -> str:
        return artifact_name(self.version)


def _client() -> httpx2.Client:
    return httpx2.Client(
        timeout=httpx2.Timeout(30.0, read=120.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def parse_releases(data: Any) -> list[Release]:
    releases = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        tag = str(item.get("tag_name", ""))
        version = tag.removeprefix("v")
        try:
            version_key(version)
        except ValueError:
            continue
        assets = {
            str(a["name"]): str(a["browser_download_url"])
            for a in item.get("assets", [])
            if isinstance(a, dict) and "name" in a and "browser_download_url" in a
        }
        releases.append(
            Release(tag, version, bool(item.get("prerelease")), str(item.get("html_url")), assets)
        )
    return releases


def newest_update(releases: list[Release], current: str = __version__) -> Release | None:
    """The newest release above ``current`` that has this system's signed file."""
    include_pre = is_prerelease(current)
    candidates = [
        r
        for r in releases
        if (include_pre or not r.prerelease)
        and is_newer(r.version, current)
        and {r.file_name, SUMS_NAME, SIGNATURE_NAME} <= r.assets.keys()
    ]
    return max(candidates, key=lambda r: version_key(r.version), default=None)


def check_for_update(
    current: str = __version__, client: httpx2.Client | None = None
) -> Release | None:
    """Ask GitHub for the releases; return the update to offer, or None."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get(TOKEN_ENV)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    owned = client is None
    http = client or _client()
    try:
        response = http.get(RELEASES_API, headers=headers)
        response.raise_for_status()
        return newest_update(parse_releases(response.json()), current)
    except (httpx2.HTTPError, ValueError) as exc:
        raise UpdateError(f"Could not check for updates: {exc}") from exc
    finally:
        if owned:
            http.close()


def download_update(release: Release, folder: Path, client: httpx2.Client | None = None) -> Path:
    """Download this system's file into ``folder`` and verify it; return its path."""
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / release.file_name
    partial = folder / (release.file_name + ".partial")
    owned = client is None
    http = client or _client()
    try:
        sums = http.get(release.assets[SUMS_NAME]).raise_for_status().content
        signature = http.get(release.assets[SIGNATURE_NAME]).raise_for_status().content
        with (
            http.stream("GET", release.assets[release.file_name]) as response,
            partial.open("wb") as handle,
        ):
            response.raise_for_status()
            for chunk in response.iter_bytes(1024 * 1024):
                handle.write(chunk)
        verify_file(partial, sums, signature, name=release.file_name)
    except (httpx2.HTTPError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"Could not download the update: {exc}") from exc
    except SignatureError as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"The update failed its signature check: {exc}") from exc
    finally:
        if owned:
            http.close()
    os.replace(partial, final)
    if not final.name.endswith((".exe", ".dmg")):
        final.chmod(0o755)
    return final


__all__ = [
    "Release",
    "UpdateError",
    "check_for_update",
    "download_update",
    "newest_update",
    "parse_releases",
]
