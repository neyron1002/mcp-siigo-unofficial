"""Phase 0 smoke tests: the package imports and the entry point prints the version."""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

import mcp_siigo_unofficial
from mcp_siigo_unofficial.__main__ import APP_NAME, main

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def test_version_is_semver() -> None:
    assert SEMVER.match(mcp_siigo_unofficial.__version__)


def test_main_prints_name_and_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out == f"{APP_NAME} {mcp_siigo_unofficial.__version__}\n"


def test_module_runs_as_script() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mcp_siigo_unofficial", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"{APP_NAME} {mcp_siigo_unofficial.__version__}"


def test_pyproject_version_matches_the_package() -> None:
    """The release tag is checked against __version__ (SemVer); pyproject uses PEP 440."""
    import tomllib
    from pathlib import Path

    data = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text("utf-8"))
    semver = mcp_siigo_unofficial.__version__
    pep440 = re.sub(r"-(a|b|rc)\.(\d+)$", r"\1\2", semver)
    assert data["project"]["version"] == pep440
