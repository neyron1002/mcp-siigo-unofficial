"""Per-user folders and Siigo credential rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_siigo_unofficial import paths
from mcp_siigo_unofficial.siigo import DEFAULT_PARTNER_ID, SiigoCredentials, is_valid_partner_id


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("win32", "MCPSiigoUnofficial"),
        ("darwin", "MCPSiigoUnofficial"),
        ("linux", "mcp-siigo-unofficial"),
    ],
)
def test_app_dir_name(platform: str, expected: str) -> None:
    assert paths.app_dir_name(platform) == expected


def test_home_override(isolated_home: Path) -> None:
    assert paths.data_dir() == isolated_home.resolve()
    assert paths.vault_path() == isolated_home.resolve() / "vault.sqlite3"


def test_default_data_dir_ends_with_app_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(paths.HOME_ENV)
    assert paths.data_dir().name == paths.app_dir_name()


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        (DEFAULT_PARTNER_ID, True),
        ("abc", True),
        ("A" * 100, True),
        ("ab", False),
        ("A" * 101, False),
        ("has space", False),
        ("under_score", False),
        ("guión", False),
    ],
)
def test_partner_id_rule(value: str, valid: bool) -> None:
    assert is_valid_partner_id(value) is valid


def test_credentials_validation_and_repr() -> None:
    creds = SiigoCredentials("user@example.com", "TOP-SECRET-KEY")
    assert creds.partner_id == DEFAULT_PARTNER_ID
    assert "TOP-SECRET-KEY" not in repr(creds)
    assert "TOP-SECRET-KEY" not in str(creds)
    with pytest.raises(ValueError, match="username"):
        SiigoCredentials(" ", "k")
    with pytest.raises(ValueError, match="access key"):
        SiigoCredentials("u", "")
    with pytest.raises(ValueError, match="Partner-Id"):
        SiigoCredentials("u", "k", "bad id")
