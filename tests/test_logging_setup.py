"""Logging when the app has no console (Windows window build, v0.2.0 bug)."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from mcp_siigo_unofficial.__main__ import setup_logging
from mcp_siigo_unofficial.paths import HOME_ENV, log_path


@pytest.fixture
def clean_root() -> Iterator[logging.Logger]:
    """Restore the root logger and the uncaught-error hook after the test."""
    root = logging.getLogger()
    handlers, level, hook = list(root.handlers), root.level, sys.excepthook
    yield root
    for handler in root.handlers:
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)
    sys.excepthook = hook


def test_no_console_logs_to_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_root: logging.Logger
) -> None:
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    setup_logging()
    try:
        # Code that prints no longer fails.
        assert sys.stdout is not None
        assert sys.stderr is not None
        print("ignored")
        logging.getLogger("mcp_siigo_unofficial.test").warning("server did not start")
        for handler in clean_root.handlers:
            handler.flush()
        assert "server did not start" in log_path().read_text(encoding="utf-8")
    finally:
        sys.stdout.close()
        sys.stderr.close()


def test_console_keeps_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_root: logging.Logger
) -> None:
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    stdout, stderr = sys.stdout, sys.stderr
    setup_logging()
    assert sys.stdout is stdout
    assert sys.stderr is stderr
    assert not log_path().exists()
