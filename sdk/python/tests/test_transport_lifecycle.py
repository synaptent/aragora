"""Public SDK transport classification, cancellation and ownership contracts."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from aragora_sdk import AragoraAsyncClient, AragoraClient, AragoraError
from aragora_sdk import ConnectionError as SDKConnectionError
from aragora_sdk import TimeoutError as SDKTimeoutError

FAILURES = [
    (httpx.TimeoutException, SDKTimeoutError, "Request timed out"),
    (httpx.ConnectTimeout, SDKTimeoutError, "Request timed out"),
    (httpx.ReadTimeout, SDKTimeoutError, "Request timed out"),
    (httpx.WriteTimeout, SDKTimeoutError, "Request timed out"),
    (httpx.PoolTimeout, SDKTimeoutError, "Request timed out"),
    (httpx.ConnectError, SDKConnectionError, "Connection failed"),
]
REQUESTS = [
    ("POST", "/api/v1/debates"),
    ("POST", "/api/v1/code-review/review"),
    ("GET", "/api/v2/receipts/example"),
]


def assert_error(
    error: AragoraError, expected: type[AragoraError], message: str, cause: Exception
) -> None:
    assert type(error) is expected
    assert isinstance(error, AragoraError)
    assert error.message == message
    assert str(error) == f"AragoraError: {message}"
    assert error.__cause__ is cause
    assert error.status_code is None
    assert error.error_code is None
    assert error.trace_id is None
    assert error.response_body is None


@pytest.mark.parametrize("failure,expected,message", FAILURES)
@pytest.mark.parametrize("attempts", [1, 3])
def test_sync_exhaustion_preserves_type_cause_budget_and_cleanup(
    failure: type[httpx.TransportError], expected: type[AragoraError], message: str, attempts: int
) -> None:
    causes: list[httpx.TransportError] = []

    def handle(request: httpx.Request) -> httpx.Response:
        cause = failure("private transport detail", request=request)
        causes.append(cause)
        raise cause

    http = httpx.Client(transport=httpx.MockTransport(handle))
    with (
        patch("aragora_sdk.client.httpx.Client", return_value=http),
        patch("aragora_sdk.client.time.sleep") as sleep,
        pytest.raises(expected) as raised,
    ):
        with AragoraClient(max_retries=attempts, retry_delay=0.125) as client:
            client.request("POST", REQUESTS[0][1], json={"task": "local only"})
    assert_error(raised.value, expected, message, causes[-1])
    assert len(causes) == attempts
    assert [call.args[0] for call in sleep.call_args_list] == [
        0.125 * 2**i for i in range(attempts - 1)
    ]
    assert http.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,expected,message", FAILURES)
@pytest.mark.parametrize("attempts", [1, 3])
async def test_async_exhaustion_preserves_type_cause_budget_and_cleanup(
    failure: type[httpx.TransportError], expected: type[AragoraError], message: str, attempts: int
) -> None:
    causes: list[httpx.TransportError] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        cause = failure("private transport detail", request=request)
        causes.append(cause)
        raise cause

    http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with (
        patch("aragora_sdk.client.httpx.AsyncClient", return_value=http),
        patch("asyncio.sleep", new_callable=AsyncMock) as sleep,
        pytest.raises(expected) as raised,
    ):
        async with AragoraAsyncClient(max_retries=attempts, retry_delay=0.125) as client:
            await client.request("POST", REQUESTS[0][1], json={"task": "local only"})
    assert_error(raised.value, expected, message, causes[-1])
    assert len(causes) == attempts
    assert [call.args[0] for call in sleep.call_args_list] == [
        0.125 * 2**i for i in range(attempts - 1)
    ]
    assert http.is_closed


@pytest.mark.parametrize("failure", [None, httpx.ReadTimeout, httpx.ConnectError])
@pytest.mark.parametrize("method,path", REQUESTS)
def test_sync_success_and_recovery_keep_budget_and_cleanup(
    failure: type[httpx.TransportError] | None, method: str, path: str
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure and len(requests) < 3:
            raise failure("transient", request=request)
        return httpx.Response(200, json={"ok": True})

    http = httpx.Client(transport=httpx.MockTransport(handle))
    with (
        patch("aragora_sdk.client.httpx.Client", return_value=http),
        patch("aragora_sdk.client.time.sleep") as sleep,
    ):
        with AragoraClient(max_retries=3, retry_delay=0.125) as client:
            assert client.request(method, path) == {"ok": True}
    assert len(requests) == (3 if failure else 1)
    assert [call.args[0] for call in sleep.call_args_list] == ([0.125, 0.25] if failure else [])
    assert all((request.method, request.url.path) == (method, path) for request in requests)
    assert http.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, httpx.ReadTimeout, httpx.ConnectError])
@pytest.mark.parametrize("method,path", REQUESTS)
async def test_async_success_and_recovery_keep_budget_and_cleanup(
    failure: type[httpx.TransportError] | None, method: str, path: str
) -> None:
    requests: list[httpx.Request] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure and len(requests) < 3:
            raise failure("transient", request=request)
        return httpx.Response(200, json={"ok": True})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with (
        patch("aragora_sdk.client.httpx.AsyncClient", return_value=http),
        patch("asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        async with AragoraAsyncClient(max_retries=3, retry_delay=0.125) as client:
            assert await client.request(method, path) == {"ok": True}
    assert len(requests) == (3 if failure else 1)
    assert [call.args[0] for call in sleep.call_args_list] == ([0.125, 0.25] if failure else [])
    assert all((request.method, request.url.path) == (method, path) for request in requests)
    assert http.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["request", "timeout", "connection", "rate_limit"])
async def test_cancellation_propagates_without_retry_and_closes_owned_http(phase: str) -> None:
    entered = asyncio.Event()
    never = asyncio.Event()
    requests: list[httpx.Request] = []
    delays: list[float] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if phase == "request":
            entered.set()
            await never.wait()
        if phase == "timeout":
            raise httpx.ReadTimeout("transient", request=request)
        if phase == "connection":
            raise httpx.ConnectError("transient", request=request)
        return httpx.Response(429, headers={"Retry-After": "1"}, json={"error": "slow down"})

    async def backoff(delay: float) -> None:
        delays.append(delay)
        entered.set()
        await never.wait()

    http = httpx.AsyncClient(transport=httpx.MockTransport(handle))

    async def operation() -> object:
        async with AragoraAsyncClient(max_retries=3, retry_delay=0.125) as client:
            return await client.request("POST", REQUESTS[0][1], json={"task": "local only"})

    with (
        patch("aragora_sdk.client.httpx.AsyncClient", return_value=http),
        patch("asyncio.sleep", side_effect=backoff),
    ):
        task = asyncio.create_task(operation())
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            assert task.cancel("caller stopped")
            with pytest.raises(asyncio.CancelledError, match="caller stopped"):
                await asyncio.wait_for(task, timeout=2)
        finally:
            # Keep a broken implementation from leaking an in-flight fixture task.
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    assert len(requests) == 1
    expected_delays = [] if phase == "request" else [1 if phase == "rate_limit" else 0.125]
    assert delays == expected_delays
    assert http.is_closed


@pytest.mark.parametrize("failure", [httpx.ReadError, httpx.RemoteProtocolError, ValueError])
def test_other_sync_failures_are_not_newly_wrapped_or_retried(failure: type[Exception]) -> None:
    cause = failure("unchanged")
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise cause

    http = httpx.Client(transport=httpx.MockTransport(handle))
    with (
        patch("aragora_sdk.client.httpx.Client", return_value=http),
        patch("aragora_sdk.client.time.sleep") as sleep,
        pytest.raises(failure) as raised,
    ):
        with AragoraClient() as client:
            client.request("GET", REQUESTS[2][1])
    assert raised.value is cause
    assert len(calls) == 1
    sleep.assert_not_called()
    assert http.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [httpx.ReadError, httpx.RemoteProtocolError, ValueError])
async def test_other_async_failures_are_not_newly_wrapped_or_retried(
    failure: type[Exception],
) -> None:
    cause = failure("unchanged")
    calls: list[httpx.Request] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise cause

    http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with (
        patch("aragora_sdk.client.httpx.AsyncClient", return_value=http),
        patch("asyncio.sleep", new_callable=AsyncMock) as sleep,
        pytest.raises(failure) as raised,
    ):
        async with AragoraAsyncClient() as client:
            await client.request("GET", REQUESTS[2][1])
    assert raised.value is cause
    assert len(calls) == 1
    sleep.assert_not_called()
    assert http.is_closed
