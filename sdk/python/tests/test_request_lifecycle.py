"""Deterministic sync/async HTTP request-lifecycle contracts."""

from __future__ import annotations

from threading import TIMEOUT_MAX
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from aragora_sdk.client import AragoraAsyncClient, AragoraClient
from aragora_sdk.exceptions import RateLimitError

# 2026-09-11 12:00:00.25 UTC: future dates must round up, not truncate.
NOW = 1789128000.25
FUTURE = "Fri, 11 Sep 2026 12:00:02 GMT"
BODY = {"error": "Slow down", "code": "RATE_LIMITED", "trace_id": "trace-429"}
HINTS = [
    pytest.param(None, None, id="absent"),
    pytest.param("", None, id="empty"),
    pytest.param("0", 0, id="zero"),
    pytest.param("12", 12, id="integer"),
    pytest.param(" 0012\t", 12, id="whitespace-leading-zero"),
    pytest.param(FUTURE, 2, id="http-date-ceiling"),
    pytest.param("Friday, 11-Sep-26 12:00:02 GMT", 2, id="rfc850-date"),
    pytest.param("Fri Sep 11 12:00:02 2026", 2, id="asctime-utc"),
    pytest.param("Fri, 11 Sep 2026 12:00:00 GMT", 0, id="past-date"),
    pytest.param("nonsense", None, id="malformed"),
    pytest.param("Fri, 11 Sep 2026 12:00:00 BOGUS", None, id="unknown-zone"),
    pytest.param("Fri, 11 Sep 2026 12:00:00 GMT trailing", None, id="date-trailing-garbage"),
    pytest.param("Fri, 11 Sep 2026 12:00:00 GMT, 0", None, id="coalesced-integer"),
    pytest.param(
        "Fri, 11 Sep 2026 12:00:00 GMT, Fri, 11 Sep 2026 12:10:00 GMT",
        None,
        id="coalesced-dates",
    ),
    pytest.param("notaday, 11 Sep 2026 12:00:00 GMT", None, id="unknown-weekday"),
    pytest.param("11 Sep 2026 12:00:00 GMT", None, id="missing-weekday"),
    pytest.param("Fri, 11 Sep 2026 12:00:00", None, id="missing-zone"),
    pytest.param("\nFri, 11 Sep 2026 12:00:00 GMT", None, id="non-ows-prefix"),
    pytest.param("-1", None, id="negative"),
    pytest.param("+1", None, id="signed"),
    pytest.param("1.5", None, id="fraction"),
    pytest.param("1e2", None, id="exponent"),
    pytest.param("NaN", None, id="nan"),
    pytest.param("Infinity", None, id="infinite"),
    pytest.param("Fri, 32 Sep 2026 12:00:02 GMT", None, id="invalid-date"),
    pytest.param("Fri, 11 Sep 10000 12:00:02 GMT", None, id="unrepresentable-date"),
    pytest.param(str(int(TIMEOUT_MAX) + 1), None, id="timer-overflow"),
    pytest.param("9" * 5000, None, id="integer-overflow"),
]


def limited(header: str | None, *, json_body: bool = True) -> httpx.Response:
    headers = {} if header is None else {"Retry-After": header}
    if json_body:
        return httpx.Response(429, headers=headers, json=BODY)
    return httpx.Response(429, headers=headers, text="Slow down")


def assert_diagnostics(error: RateLimitError, hint: int | None) -> None:
    assert error.retry_after == hint
    assert hint is None or type(error.retry_after) is int
    assert error.status_code == 429
    assert error.error_code == BODY["code"]
    assert error.trace_id == BODY["trace_id"]
    assert error.response_body == BODY
    assert error.message == BODY["error"]


@pytest.mark.parametrize("header,hint", HINTS)
def test_sync_rate_limit_diagnostics(header: str | None, hint: int | None) -> None:
    with AragoraClient(max_retries=1) as client:
        with (
            patch.object(client._client, "request", return_value=limited(header)) as request,
            patch("aragora_sdk.client.time.time", return_value=NOW),
            patch("aragora_sdk.client.time.sleep") as sleep,
            pytest.raises(RateLimitError) as raised,
        ):
            client.request("POST", "/api/v1/debates", json={"task": "example"})
        assert_diagnostics(raised.value, hint)
        request.assert_called_once()
        sleep.assert_not_called()


@pytest.mark.parametrize("header,hint", HINTS)
async def test_async_rate_limit_diagnostics(header: str | None, hint: int | None) -> None:
    async with AragoraAsyncClient(max_retries=1) as client:
        with (
            patch.object(client._client, "request", return_value=limited(header)) as request,
            patch("aragora_sdk.client.time.time", return_value=NOW),
            patch("asyncio.sleep", new_callable=AsyncMock) as sleep,
            pytest.raises(RateLimitError) as raised,
        ):
            await client.request("POST", "/api/v1/debates", json={"task": "example"})
        assert_diagnostics(raised.value, hint)
        request.assert_awaited_once()
        sleep.assert_not_awaited()


@pytest.mark.parametrize("header,hint", HINTS)
@pytest.mark.parametrize("succeed", [False, True], ids=["budget-exhausted", "recovers"])
async def test_retry_policy_parity(header: str | None, hint: int | None, succeed: bool) -> None:
    """Both clients keep the attempt budget and use zero, dates or fallback identically."""
    for async_mode in (False, True):
        responses = [limited(header), limited(header), limited(header)]
        if succeed:
            responses[-1] = httpx.Response(200, json={"ok": True})
        sleeps = AsyncMock() if async_mode else Mock()
        client = (
            AragoraAsyncClient(max_retries=3, retry_delay=7)
            if async_mode
            else AragoraClient(max_retries=3, retry_delay=7)
        )
        try:
            with (
                patch.object(client._client, "request", side_effect=responses) as request,
                patch("aragora_sdk.client.time.time", return_value=NOW),
                patch("asyncio.sleep" if async_mode else "aragora_sdk.client.time.sleep", sleeps),
            ):

                async def run(c: AragoraClient | AragoraAsyncClient) -> dict[str, Any]:
                    if isinstance(c, AragoraAsyncClient):
                        return await c.request("GET", "/api/v1/debates")
                    return c.request("GET", "/api/v1/debates")

                if succeed:
                    assert await run(client) == {"ok": True}
                else:
                    with pytest.raises(RateLimitError) as raised:
                        await run(client)
                    assert_diagnostics(raised.value, hint)
                assert request.call_count == 3
                delays = [call.args[0] for call in sleeps.call_args_list]
                assert delays == ([hint, hint] if hint is not None else [7, 14])
        finally:
            if isinstance(client, AragoraAsyncClient):
                await client.close()
            else:
                client.close()


@pytest.mark.parametrize("client_type", [AragoraClient, AragoraAsyncClient])
def test_non_json_429_retains_status(client_type: type) -> None:
    # The error decoder is synchronous in both clients; demo avoids owning transport here.
    client = client_type(demo=True)
    with pytest.raises(RateLimitError) as raised:
        client._handle_error_response(limited("broken", json_body=False))
    assert raised.value.status_code == 429
    assert raised.value.message == "Slow down"
    assert raised.value.retry_after is None
    assert raised.value.response_body is None
    assert raised.value.error_code is None
    assert raised.value.trace_id is None
