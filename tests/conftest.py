"""Shared fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from mcp_siigo_unofficial.siigo import SiigoClient, SiigoCredentials
from mcp_siigo_unofficial.vault import MemoryKeyStore, Vault
from mock_siigo import TEST_ACCESS_KEY, TEST_USERNAME, MockSiigo


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets its own data folder; the real user folder is never touched."""
    home = tmp_path / "app-home"
    monkeypatch.setenv("MCP_SIIGO_UNOFFICIAL_HOME", str(home))
    return home


@pytest.fixture
def credentials() -> SiigoCredentials:
    return SiigoCredentials(TEST_USERNAME, TEST_ACCESS_KEY)


@pytest.fixture
def mock_siigo() -> MockSiigo:
    return MockSiigo()


class FakeClock:
    """Monotonic clock that tests move forward by hand."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class FakeSleep:
    """Records the waits instead of sleeping."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_sleep() -> FakeSleep:
    return FakeSleep()


@pytest.fixture
async def client(
    mock_siigo: MockSiigo,
    credentials: SiigoCredentials,
    clock: FakeClock,
    fake_sleep: FakeSleep,
) -> AsyncIterator[SiigoClient]:
    async with SiigoClient(
        lambda: credentials,
        base_url="https://api.siigo.test",
        transport=mock_siigo.transport(),
        clock=clock,
        sleep=fake_sleep,
    ) as siigo_client:
        yield siigo_client


@pytest.fixture
def vault(tmp_path: Path) -> Iterator[Vault]:
    with Vault.open(tmp_path / "vault.sqlite3", MemoryKeyStore()) as opened:
        yield opened
