"""Deterministic sync/async HTTP request-lifecycle contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime
from math import ceil
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
    pytest.param("59", 59, id="integer-below-wait-bound"),
    pytest.param("60", 60, id="integer-at-wait-bound"),
    pytest.param("61", 61, id="integer-above-wait-bound"),
    pytest.param(" 0012\t", 12, id="whitespace-leading-zero"),
    pytest.param(FUTURE, 2, id="http-date-ceiling"),
    pytest.param("Fri, 11 Sep 2026 12:00:59 GMT", 59, id="date-below-wait-bound"),
    pytest.param("Fri, 11 Sep 2026 12:01:00 GMT", 60, id="date-at-wait-bound"),
    pytest.param("Fri, 11 Sep 2026 12:01:01 GMT", 61, id="date-above-wait-bound"),
    pytest.param("Friday, 11-Sep-26 12:00:02 GMT", 2, id="rfc850-date"),
    pytest.param("Fri Sep 11 12:00:02 2026", 2, id="asctime-utc"),
    pytest.param("Fri, 11 Sep 2026 12:00:00 GMT", 0, id="past-date"),
    pytest.param("Mon, 11 Sep 2026 12:00:00 GMT", None, id="imf-wrong-weekday"),
    pytest.param("Monday, 11-Sep-26 12:00:00 GMT", None, id="rfc850-wrong-weekday"),
    pytest.param("Mon Sep 11 12:00:00 2026", None, id="asctime-wrong-weekday"),
    pytest.param("Fri, 11 Sep 0026 12:00:02 GMT", None, id="imf-low-year"),
    pytest.param("Fri Sep 11 12:00:02 0026", None, id="asctime-low-year"),
    pytest.param("Mon, 11 Sep 1899 12:00:02 GMT", None, id="year-before-1900"),
    pytest.param("Thursday, 11-Sep-70 12:00:02 GMT", 1388534402, id="rfc850-2070"),
    pytest.param("Thu, 11 Sep 2070 12:00:02 GMT", 1388534402, id="imf-2070"),
    pytest.param("Fri, 29 Feb 2100 12:00:02 GMT", None, id="non-leap-century"),
    pytest.param("Fri, 11 Sep 2026 24:00:02 GMT", None, id="invalid-hour"),
    pytest.param("Fri, 11 Sep 2026 12:60:02 GMT", None, id="invalid-minute"),
    pytest.param("Fri, 11 Sep 2026 12:00:61 GMT", None, id="invalid-second"),
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

                oversized = hint is not None and hint > 60
                if succeed and not oversized:
                    assert await run(client) == {"ok": True}
                else:
                    with pytest.raises(RateLimitError) as raised:
                        await run(client)
                    assert_diagnostics(raised.value, hint)
                assert request.call_count == (1 if oversized else 3)
                delays = [call.args[0] for call in sleeps.call_args_list]
                expected = [] if oversized else ([hint, hint] if hint is not None else [7, 14])
                assert delays == expected
        finally:
            if isinstance(client, AragoraAsyncClient):
                await client.close()
            else:
                client.close()


@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("prior_attempts", [0, 1], ids=["first-hint", "late-hint"])
@pytest.mark.parametrize(
    "header,now,hint",
    [
        ("61", NOW, 61),
        ("Thu, 11 Sep 2070 12:00:02 GMT", NOW, 1388534402),
        (FUTURE, 0.0, 1789128002),  # A severely skewed local clock.
    ],
)
async def test_oversized_hint_preserves_original_error_without_replay(
    async_mode: bool, prior_attempts: int, header: str, now: float, hint: int
) -> None:
    client = AragoraAsyncClient(max_retries=5) if async_mode else AragoraClient(max_retries=5)
    errors: list[RateLimitError] = []
    decode = client._handle_error_response

    def record_error(response: httpx.Response) -> None:
        try:
            decode(response)
        except RateLimitError as error:
            errors.append(error)
            raise

    responses = [limited("2")] * prior_attempts + [
        limited(header),
        httpx.Response(200, json={"must_not_be_requested": True}),
    ]
    sleep = AsyncMock() if async_mode else Mock()
    try:
        with (
            patch.object(client._client, "request", side_effect=responses) as request,
            patch.object(client, "_handle_error_response", side_effect=record_error),
            patch("aragora_sdk.client.time.time", return_value=now),
            patch("asyncio.sleep" if async_mode else "aragora_sdk.client.time.sleep", sleep),
            pytest.raises(RateLimitError) as raised,
        ):
            if isinstance(client, AragoraAsyncClient):
                await client.request("POST", "/api/v1/debates", json={"task": "example"})
            else:
                client.request("POST", "/api/v1/debates", json={"task": "example"})
        assert raised.value is errors[-1]
        assert_diagnostics(raised.value, hint)
        assert request.call_count == prior_attempts + 1
        assert [call.args[0] for call in sleep.call_args_list] == [2] * prior_attempts
    finally:
        if isinstance(client, AragoraAsyncClient):
            await client.close()
        else:
            client.close()


@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
async def test_large_configured_fallback_is_unchanged(async_mode: bool) -> None:
    client = (
        AragoraAsyncClient(max_retries=3, retry_delay=61)
        if async_mode
        else AragoraClient(max_retries=3, retry_delay=61)
    )
    sleep = AsyncMock() if async_mode else Mock()
    try:
        with (
            patch.object(client._client, "request", return_value=limited("broken")) as request,
            patch("asyncio.sleep" if async_mode else "aragora_sdk.client.time.sleep", sleep),
            pytest.raises(RateLimitError) as raised,
        ):
            if isinstance(client, AragoraAsyncClient):
                await client.request("GET", "/api/v1/debates")
            else:
                client.request("GET", "/api/v1/debates")
        assert_diagnostics(raised.value, None)
        assert request.call_count == 3
        assert [call.args[0] for call in sleep.call_args_list] == [61, 122]
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


@pytest.mark.parametrize("client_type", [AragoraClient, AragoraAsyncClient])
@pytest.mark.parametrize(
    "now,resolved",
    [
        ("2026-09-11T12:00:00", "2076-09-11T12:00:00"),  # Exactly fifty years.
        ("2026-09-11T12:00:00", "1976-09-11T12:00:01"),  # One second beyond.
        ("2026-09-11T12:00:00.250000", "2076-09-11T12:00:00"),
        ("2026-09-11T12:00:00.250000", "1976-09-11T12:00:01"),
        ("2099-12-31T23:59:59", "2100-01-01T00:00:00"),
        ("2099-12-31T23:59:59", "2099-01-01T00:00:00"),
        ("2049-03-01T00:00:00", "2000-02-29T00:00:00"),
        ("2024-02-29T12:00:00", "2074-02-28T12:00:00"),
        ("2024-02-29T12:00:00", "1974-03-01T00:00:00"),
        ("1900-01-01T00:00:00", "1900-01-01T00:00:00"),
    ],
)
def test_rfc850_rolling_boundary(client_type: type, now: str, resolved: str) -> None:
    current = datetime.fromisoformat(now).replace(tzinfo=timezone.utc)
    target = datetime.fromisoformat(resolved).replace(tzinfo=timezone.utc)
    canonical = format_datetime(target, usegmt=True)
    _, day, month, year, clock, _ = canonical.split()
    weekdays = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    obsolete = f"{weekdays[target.weekday()]}, {day}-{month}-{year[-2:]} {clock} GMT"
    client = client_type(demo=True)
    for header in (canonical, obsolete):
        with (
            patch("aragora_sdk.client.time.time", return_value=current.timestamp()) as clock_read,
            pytest.raises(RateLimitError) as raised,
        ):
            client._handle_error_response(limited(header))
        assert_diagnostics(raised.value, max(0, ceil((target - current).total_seconds())))
        clock_read.assert_called_once()


@pytest.mark.parametrize("client_type", [AragoraClient, AragoraAsyncClient])
@pytest.mark.parametrize(
    "header",
    [
        "Sat, 31 Dec 2016 23:59:60 GMT",
        "Saturday, 31-Dec-16 23:59:60 GMT",
        "Sat Dec 31 23:59:60 2016",
    ],
)
def test_http_leap_second_preserves_original_weekday(client_type: type, header: str) -> None:
    now = datetime(2016, 12, 31, 23, 59, 59, 250000, tzinfo=timezone.utc).timestamp()
    with (
        patch("aragora_sdk.client.time.time", return_value=now),
        pytest.raises(RateLimitError) as raised,
    ):
        client_type(demo=True)._handle_error_response(limited(header))
    assert_diagnostics(raised.value, 1)
