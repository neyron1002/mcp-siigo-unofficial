"""Siigo client against the mock Siigo API."""

from __future__ import annotations

import logging

import httpx
import pytest

from conftest import FakeClock, FakeSleep
from mcp_siigo_unofficial.siigo import (
    SiigoAuthError,
    SiigoClient,
    SiigoCredentials,
    SiigoError,
    SiigoNotConfiguredError,
)
from mcp_siigo_unofficial.siigo.client import MAX_RETRY_AFTER_S, TOKEN_RENEW_MARGIN_S
from mock_siigo import TEST_ACCESS_KEY, MockSiigo

pytestmark = pytest.mark.anyio


async def test_authenticates_once_and_sends_headers(
    client: SiigoClient, mock_siigo: MockSiigo
) -> None:
    mock_siigo.seed("customers", 3)
    first = await client.get("/v1/customers", {"page": 1, "page_size": 2, "name": None})
    await client.get("/v1/taxes")
    assert mock_siigo.auth_calls == 1
    assert first["pagination"] == {"page": 1, "page_size": 2, "total_results": 3}
    assert len(first["results"]) == 2
    request = mock_siigo.requests[-1]
    assert request.headers["Partner-Id"] == "MCPSiigoUnofficial"
    assert request.headers["Authorization"].startswith("Bearer mock-")
    assert "name" not in mock_siigo.requests[1].url.params
    assert client.request_count == 2


async def test_create_update_get_delete(client: SiigoClient) -> None:
    created = await client.post("/v1/customers", {"name": ["Ana", "Pérez"]})
    customer_id = created["id"]
    updated = await client.put(f"/v1/customers/{customer_id}", {"name": ["Ana", "Ruiz"]})
    assert updated["name"] == ["Ana", "Ruiz"]
    assert (await client.get(f"/v1/customers/{customer_id}"))["id"] == customer_id
    assert (await client.delete(f"/v1/customers/{customer_id}"))["deleted"] is True


async def test_token_is_renewed_before_it_expires(
    client: SiigoClient, mock_siigo: MockSiigo, clock: FakeClock
) -> None:
    await client.get("/v1/taxes")
    assert client.token_seconds_left == 86_400
    clock.now += 86_400 - TOKEN_RENEW_MARGIN_S - 1
    await client.get("/v1/taxes")
    assert mock_siigo.auth_calls == 1
    clock.now += 2
    await client.get("/v1/taxes")
    assert mock_siigo.auth_calls == 2


async def test_401_authenticates_again_once(client: SiigoClient, mock_siigo: MockSiigo) -> None:
    await client.get("/v1/taxes")
    mock_siigo.expire_tokens()
    assert await client.get("/v1/taxes")
    assert mock_siigo.auth_calls == 2


async def test_401_twice_raises_auth_error(client: SiigoClient, mock_siigo: MockSiigo) -> None:
    await client.get("/v1/taxes")
    mock_siigo.add_fault(401, {"Errors": [{"Code": "unauthorized", "Message": "No"}]})
    mock_siigo.add_fault(401, {"Errors": [{"Code": "unauthorized", "Message": "No"}]})
    with pytest.raises(SiigoAuthError) as info:
        await client.get("/v1/taxes")
    assert info.value.status == 401
    assert info.value.code == "unauthorized"


async def test_429_waits_for_retry_after(
    client: SiigoClient, mock_siigo: MockSiigo, fake_sleep: FakeSleep
) -> None:
    mock_siigo.add_fault(429, {"Errors": [{"Code": "requests_limit"}]}, {"Retry-After": "7"})
    mock_siigo.add_fault(429, None, {"Retry-After": "999"})
    assert await client.get("/v1/taxes")
    assert fake_sleep.calls == [7.0, MAX_RETRY_AFTER_S]


async def test_429_gives_up_after_the_retry_limit(
    client: SiigoClient, mock_siigo: MockSiigo
) -> None:
    for _ in range(3):
        mock_siigo.add_fault(429, {"Errors": [{"Code": "requests_limit", "Message": "Slow"}]})
    with pytest.raises(SiigoError) as info:
        await client.get("/v1/taxes")
    assert info.value.status == 429
    assert info.value.code == "requests_limit"


async def test_reads_retry_once_on_503_but_writes_do_not(
    client: SiigoClient, mock_siigo: MockSiigo
) -> None:
    mock_siigo.add_fault(503)
    assert await client.get("/v1/taxes")
    mock_siigo.add_fault(503)
    with pytest.raises(SiigoError) as info:
        await client.post("/v1/invoices", {"document": {"id": 1}})
    assert info.value.status == 503
    assert mock_siigo.data["invoices"] == {}


async def test_siigo_errors_are_readable(client: SiigoClient) -> None:
    with pytest.raises(SiigoError) as info:
        await client.get("/v1/customers/does-not-exist")
    error = info.value.to_dict()
    assert error["status"] == 404
    assert error["code"] == "not_found"
    assert error["errors"][0]["params"] == ["does-not-exist"]
    assert "not_found: The record does not exist." in error["message"]


async def test_wrong_credentials(mock_siigo: MockSiigo) -> None:
    bad = SiigoCredentials("someone@example.com", "wrong")
    async with SiigoClient(lambda: bad, transport=mock_siigo.transport()) as siigo:
        with pytest.raises(SiigoAuthError, match="Invalid username"):
            await siigo.get("/v1/taxes")


async def test_no_credentials() -> None:
    async with SiigoClient(lambda: None) as siigo:
        with pytest.raises(SiigoNotConfiguredError):
            await siigo.get("/v1/taxes")


async def test_changed_credentials_trigger_new_authentication(mock_siigo: MockSiigo) -> None:
    current = {"creds": SiigoCredentials(mock_siigo.username, TEST_ACCESS_KEY)}
    async with SiigoClient(lambda: current["creds"], transport=mock_siigo.transport()) as siigo:
        await siigo.get("/v1/taxes")
        current["creds"] = SiigoCredentials(mock_siigo.username, TEST_ACCESS_KEY, "OtherPartner")
        await siigo.get("/v1/taxes")
    assert mock_siigo.auth_calls == 2
    assert mock_siigo.requests[-1].headers["Partner-Id"] == "OtherPartner"


@pytest.mark.parametrize(
    "path",
    ["/auth", "https://evil.example/v1/x", "/v2/customers", "/v1/../auth", "/v1//x", "//evil/v1"],
)
async def test_only_v1_paths_are_allowed(
    client: SiigoClient, mock_siigo: MockSiigo, path: str
) -> None:
    with pytest.raises(SiigoError, match="/v1/"):
        await client.get(path)
    assert mock_siigo.requests == []


async def test_expires_in_in_milliseconds_is_understood(credentials: SiigoCredentials) -> None:
    mock = MockSiigo(token_lifetime=86_400_000)
    async with SiigoClient(lambda: credentials, transport=mock.transport()) as siigo:
        await siigo.authenticate()
        left = siigo.token_seconds_left
        assert left is not None
        assert 86_000 < left <= 86_400


async def test_network_errors(credentials: SiigoCredentials, fake_sleep: FakeSleep) -> None:
    mock = MockSiigo()
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v1/"):
            calls["n"] += 1
            raise httpx.ConnectError("down", request=request)
        return mock.handle(request)

    async with SiigoClient(
        lambda: credentials, transport=httpx.MockTransport(flaky), sleep=fake_sleep
    ) as siigo:
        with pytest.raises(SiigoError, match="Network error") as info:
            await siigo.get("/v1/taxes")
        assert info.value.code == "network_error"
        assert calls["n"] == 2  # one retry for reads

        calls["n"] = 0
        with pytest.raises(SiigoError):
            await siigo.post("/v1/invoices", {"a": 1})
        assert calls["n"] == 1  # no retry for writes


async def test_timeout_is_reported(credentials: SiigoCredentials) -> None:
    mock = MockSiigo()

    def slow(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v1/"):
            raise httpx.ReadTimeout("slow", request=request)
        return mock.handle(request)

    async with SiigoClient(lambda: credentials, transport=httpx.MockTransport(slow)) as siigo:
        with pytest.raises(SiigoError) as info:
            await siigo.post("/v1/invoices", {"a": 1})
    assert info.value.code == "request_timeout"
    assert info.value.status == 408


async def test_secrets_never_appear_in_logs_or_repr(
    client: SiigoClient, mock_siigo: MockSiigo, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    mock_siigo.expire_tokens()
    await client.get("/v1/taxes")
    mock_siigo.expire_tokens()
    await client.get("/v1/taxes")
    tokens = [
        r.headers.get("Authorization", "").removeprefix("Bearer ") for r in mock_siigo.requests
    ]
    text = caplog.text + repr(client)
    assert TEST_ACCESS_KEY not in text
    issued = [t for t in tokens if t.startswith("mock-")]
    assert issued
    for token in issued:
        assert token not in text


async def test_mock_server_over_real_http(credentials: SiigoCredentials) -> None:
    mock = MockSiigo()
    with mock.serve() as base_url:
        async with SiigoClient(lambda: credentials, base_url=base_url) as siigo:
            created = await siigo.post("/v1/invoices", {"document": {"id": 24446}})
            assert created["name"] == "FV-1-1"
            listed = await siigo.get("/v1/invoices")
            assert listed["results"][0]["id"] == created["id"]
    assert mock.auth_calls == 1
