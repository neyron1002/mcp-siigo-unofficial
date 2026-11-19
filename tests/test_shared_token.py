"""One Siigo login shared by the app's processes (one-click plan v3, Q2e)."""

from __future__ import annotations

import logging

import pytest

from mcp_siigo_unofficial.siigo import SiigoClient, SiigoCredentials
from mcp_siigo_unofficial.siigo.token import SharedToken
from mcp_siigo_unofficial.vault import Vault, VaultTokenStore
from mock_siigo import MockSiigo

pytestmark = pytest.mark.anyio


class Wall:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def make_client(
    mock_siigo: MockSiigo, credentials: SiigoCredentials, vault: Vault, wall: Wall
) -> SiigoClient:
    return SiigoClient(
        lambda: credentials,
        base_url="https://api.siigo.test",
        transport=mock_siigo.transport(),
        token_store=VaultTokenStore(vault),
        wall_clock=wall,
    )


async def test_second_process_reuses_the_token(
    mock_siigo: MockSiigo, credentials: SiigoCredentials, vault: Vault
) -> None:
    wall = Wall()
    async with make_client(mock_siigo, credentials, vault, wall) as first:
        await first.get("/v1/taxes")
    async with make_client(mock_siigo, credentials, vault, wall) as second:
        await second.get("/v1/taxes")
    assert mock_siigo.auth_calls == 1


async def test_expired_or_foreign_token_is_not_used(
    mock_siigo: MockSiigo, credentials: SiigoCredentials, vault: Vault
) -> None:
    wall = Wall()
    async with make_client(mock_siigo, credentials, vault, wall) as first:
        await first.get("/v1/taxes")
    wall.now += 86_400 - 60  # inside the renewal margin
    async with make_client(mock_siigo, credentials, vault, wall) as second:
        await second.get("/v1/taxes")
    assert mock_siigo.auth_calls == 2
    other = SiigoCredentials(credentials.username, credentials.access_key, "OtherPartner")
    async with make_client(mock_siigo, other, vault, wall) as third:
        await third.get("/v1/taxes")
    assert mock_siigo.auth_calls == 3


async def test_401_gets_a_new_shared_token(
    mock_siigo: MockSiigo, credentials: SiigoCredentials, vault: Vault
) -> None:
    wall = Wall()
    store = VaultTokenStore(vault)
    async with make_client(mock_siigo, credentials, vault, wall) as first:
        await first.get("/v1/taxes")
        old = store.load()
        mock_siigo.expire_tokens()
        await first.get("/v1/taxes")
    new = store.load()
    assert old is not None
    assert new is not None
    assert old.token != new.token
    assert mock_siigo.auth_calls == 2


async def test_invalidate_clears_the_shared_token(
    mock_siigo: MockSiigo, credentials: SiigoCredentials, vault: Vault
) -> None:
    async with make_client(mock_siigo, credentials, vault, Wall()) as first:
        await first.get("/v1/taxes")
        first.invalidate_token()
    assert VaultTokenStore(vault).load() is None


async def test_the_token_is_never_logged_or_shown(
    mock_siigo: MockSiigo,
    credentials: SiigoCredentials,
    vault: Vault,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    wall = Wall()
    async with make_client(mock_siigo, credentials, vault, wall) as first:
        await first.get("/v1/taxes")
    async with make_client(mock_siigo, credentials, vault, wall) as second:
        await second.get("/v1/taxes")
        shared = VaultTokenStore(vault).load()
        assert shared is not None
        assert shared.token not in repr(second)
        assert shared.token not in repr(shared)
    assert shared.token not in caplog.text
    assert shared.token.encode() not in vault.path.read_bytes()


def test_new_or_cleared_credentials_drop_the_shared_token(
    vault: Vault, credentials: SiigoCredentials
) -> None:
    store = VaultTokenStore(vault)
    store.save(SharedToken("t1", 2e9, "owner"))
    vault.save_siigo_credentials(credentials)
    assert store.load() is None
    store.save(SharedToken("t2", 2e9, "owner"))
    vault.clear_siigo_credentials()
    assert store.load() is None


def test_a_damaged_shared_token_is_ignored(vault: Vault) -> None:
    vault.set_secret("siigo.shared_token", "{not json")
    assert VaultTokenStore(vault).load() is None
