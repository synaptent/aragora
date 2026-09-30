"""Characterization contracts for the spend analytics handler (VAL-TYPEADMIN-008).

Every case runs the real ``SpendAnalyticsHandler`` against a real
``SpendAnalytics`` over an empty local ``CostTracker`` under the typing harness
network guard. Only pass-through observers are injected: a loop observer that
wraps ``asyncio.new_event_loop`` for the handler module, a counting wrapper
around the module's ``_get_analytics`` seam, and spies on the analytics
instance methods that record forwarded arguments.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
from typing import Any

import pytest

from aragora.billing import spend_analytics as spend_service
from aragora.billing.cost_tracker import CostTracker
from aragora.server.handlers import spend_analytics as spend_module
from aragora.server.handlers.utils import decorators as handler_decorators

_ip_counter = itertools.count(1)


class Request:
    """Request shim: the handler reads ``command``, ``query``, ``headers``, ``client_address``."""

    def __init__(
        self,
        *,
        method: str | None = "GET",
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        # The module-level limiter is keyed by client IP; each request gets its own.
        index = next(_ip_counter)
        self.client_address = (f"10.{(index >> 8) & 255}.{index & 255}.7", 41000)
        self.headers = dict(headers or {})
        self.query = dict(query or {})
        if method is not None:
            self.command = method


class Spy:
    def __init__(self, target: Any) -> None:
        self.target = target
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        return self.target(*args, **kwargs)

    @property
    def count(self) -> int:
        return len(self.calls)


class LoopObserver:
    """Pass-through ``asyncio`` namespace recording loops created by the handler module."""

    def __init__(self) -> None:
        self.loops: list[asyncio.AbstractEventLoop] = []

    def new_event_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.new_event_loop()
        self.loops.append(loop)
        return loop

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)

    @property
    def closed(self) -> list[bool]:
        return [loop.is_closed() for loop in self.loops]


def payload(result: Any) -> Any:
    body = getattr(result, "body", b"")
    return json.loads(body) if body else None


def summarize(result: Any) -> Any:
    if result is None:
        return None
    headers = dict(getattr(result, "headers", {}) or {})
    if "X-Trace-Id" in headers:
        headers["X-Trace-Id"] = "<trace>"
    return {"status": result.status_code, "body": payload(result), "headers": headers}


def observe(record_property: Any, observation: Any) -> None:
    record_property("observation", json.dumps(observation, sort_keys=True, default=str))


@pytest.fixture
def spend(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    tracker = CostTracker()
    analytics = spend_service.SpendAnalytics(cost_tracker=tracker)
    monkeypatch.setattr(spend_service, "_spend_analytics", analytics)
    seam = Spy(spend_module._get_analytics)
    monkeypatch.setattr(spend_module, "_get_analytics", seam)
    loops = LoopObserver()
    monkeypatch.setattr(spend_module, "asyncio", loops)
    return {"tracker": tracker, "analytics": analytics, "seam": seam, "loops": loops}


@pytest.fixture
def handler() -> Any:
    return spend_module.SpendAnalyticsHandler({})


def _tracker_state(tracker: CostTracker) -> dict[str, Any]:
    return {"buffered_usage": len(tracker._usage_buffer)}


WORKSPACE_CASES: dict[str, tuple[dict[str, Any], Any]] = {
    "absent": ({}, "default"),
    "none": ({"workspace_id": None}, "default"),
    "empty_list": ({"workspace_id": []}, "default"),
    "empty_string": ({"workspace_id": ""}, ""),
    "scalar": ({"workspace_id": "ws-scalar"}, "ws-scalar"),
    "list": ({"workspace_id": ["ws-first", "ws-second"]}, "ws-first"),
    "list_none": ({"workspace_id": [None]}, None),
}


@pytest.mark.parametrize("case", sorted(WORKSPACE_CASES))
def test_TYPEADMIN_008_workspace_resolution(case: str, spend, handler, record_property) -> None:
    query, expected = WORKSPACE_CASES[case]
    analytics = spend["analytics"]
    provider_spy = Spy(analytics.get_spend_by_provider)
    analytics.get_spend_by_provider = provider_spy
    before = _tracker_state(spend["tracker"])

    request = Request(query=query)
    result = handler.handle("/api/v1/spend/analytics/provider", {}, request)

    assert result.status_code == 200, payload(result)
    assert payload(result) == {"data": {"by_provider": {}}}
    assert provider_spy.count == 1
    forwarded = provider_spy.calls[0][0][0]
    assert forwarded == expected
    assert type(forwarded) is type(expected)
    assert handler._resolve_workspace_id(request) == expected
    assert spend["loops"].closed == [True]
    assert _tracker_state(spend["tracker"]) == before == {"buffered_usage": 0}
    observe(
        record_property,
        {
            "case": case,
            "query": query,
            "forwarded_workspace_id": forwarded,
            "forwarded_type": type(forwarded).__name__,
            "result": summarize(result),
            "loops_closed": spend["loops"].closed,
            "tracker": _tracker_state(spend["tracker"]),
        },
    )


DAYS_CASES: dict[str, tuple[dict[str, Any], int | None]] = {
    "absent": ({}, 30),
    "none": ({"days": None}, 30),
    "empty_list": ({"days": []}, 30),
    "empty_string": ({"days": ""}, 30),
    "invalid": ({"days": "abc"}, 30),
    "zero": ({"days": "0"}, 0),
    "negative": ({"days": "-2"}, -2),
    "list": ({"days": ["7", "9"]}, 7),
    "list_none": ({"days": [None]}, None),
}


@pytest.mark.parametrize("case", sorted(DAYS_CASES))
def test_TYPEADMIN_008_forecast_days(
    case: str, spend, handler, caplog: pytest.LogCaptureFixture, record_property
) -> None:
    query, expected_days = DAYS_CASES[case]
    analytics = spend["analytics"]
    forecast_spy = Spy(analytics.get_cost_forecast)
    analytics.get_cost_forecast = forecast_spy
    before = _tracker_state(spend["tracker"])
    observation: dict[str, Any] = {"case": case, "query": query}

    with caplog.at_level(logging.ERROR, logger="aragora.server.handlers.utils.decorators"):
        result = handler.handle("/api/v1/spend/analytics/forecast", {}, Request(query=query))

    if expected_days is None:
        assert result.status_code == 400
        body = payload(result)
        assert body["error"] == "An error occurred"
        assert body["error_code"] == "INVALID_REQUEST"
        assert "X-Trace-Id" in result.headers
        assert forecast_spy.count == 0
        assert spend["seam"].count == 0
        assert spend["loops"].loops == []
        records = [
            r
            for r in caplog.records
            if r.name == "aragora.server.handlers.utils.decorators"
            and r.exc_info
            and r.exc_info[1] is not None
        ]
        assert len(records) == 1
        exc = records[0].exc_info[1]
        assert type(exc) is TypeError
        assert str(exc) == (
            "int() argument must be a string, a bytes-like object or a real number, not 'NoneType'"
        )
        observation["exception"] = {"type": type(exc).__name__, "message": str(exc)}
        observation["decorator_operation"] = (
            records[0].getMessage().split("] Error in ", 1)[1].split(":", 1)[0]
        )
    else:
        assert result.status_code == 200, payload(result)
        assert forecast_spy.count == 1
        args, kwargs = forecast_spy.calls[0]
        assert args == ("default",)
        assert kwargs == {"days": expected_days}
        assert type(kwargs["days"]) is int
        assert payload(result)["data"]["forecast_days"] == expected_days
        assert payload(result)["data"]["workspace_id"] == "default"
        assert spend["seam"].count == 1
        assert spend["loops"].closed == [True]
        observation["forwarded_days"] = expected_days

    assert _tracker_state(spend["tracker"]) == before == {"buffered_usage": 0}
    observation["result"] = summarize(result)
    observation["forecast_calls"] = forecast_spy.count
    observation["analytics_seam_calls"] = spend["seam"].count
    observation["loops_created"] = len(spend["loops"].loops)
    observation["loops_closed"] = spend["loops"].closed
    observe(record_property, observation)


ROUTES = {
    "full": "/api/v1/spend/analytics",
    "trend": "/api/v1/spend/analytics/trend",
    "provider": "/api/v1/spend/analytics/provider",
    "agent": "/api/v1/spend/analytics/agent",
    "forecast": "/api/v1/spend/analytics/forecast",
    "anomalies": "/api/v1/spend/analytics/anomalies",
}


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_TYPEADMIN_008_routes_close_loops(route: str, spend, handler, record_property) -> None:
    before = _tracker_state(spend["tracker"])
    result = handler.handle(ROUTES[route], {}, Request(query={"workspace_id": "ws-route"}))
    body = payload(result)
    assert result.status_code == 200, body
    assert set(body) == {"data"}
    assert spend["seam"].count == 1
    assert spend["loops"].closed == [True]
    if route in {"full", "forecast"}:
        forecast = body["data"]["forecast"] if route == "full" else body["data"]
        assert forecast["workspace_id"] == "ws-route"
        assert forecast["forecast_days"] == 30
    if route in {"full", "trend"}:
        trend = body["data"]["trend"] if route == "full" else body["data"]
        assert trend["workspace_id"] == "ws-route"
    assert _tracker_state(spend["tracker"]) == before == {"buffered_usage": 0}
    observe(
        record_property,
        {
            "route": ROUTES[route],
            "result": summarize(result),
            "loops_closed": spend["loops"].closed,
            "analytics_seam_calls": spend["seam"].count,
            "tracker": _tracker_state(spend["tracker"]),
        },
    )


@pytest.mark.parametrize(
    "case", ["command_over_method", "query_over_route_params", "unknown_route", "post_method"]
)
def test_TYPEADMIN_008_precedence_and_dispatch(case: str, spend, handler, record_property) -> None:
    analytics = spend["analytics"]
    provider_spy = Spy(analytics.get_spend_by_provider)
    analytics.get_spend_by_provider = provider_spy
    observation: dict[str, Any] = {"case": case}

    if case == "command_over_method":
        result = handler.handle(
            ROUTES["provider"], {}, Request(method="POST", query={}), method="GET"
        )
        assert result.status_code == 405
        assert payload(result)["error"] == "Method not allowed"
        assert provider_spy.count == 0
    elif case == "query_over_route_params":
        result = handler.handle(
            ROUTES["provider"],
            {"workspace_id": "from-route"},
            Request(query={"workspace_id": "from-request"}),
        )
        assert result.status_code == 200
        assert provider_spy.calls == [(("from-request",), {})]
        observation["forwarded_workspace_id"] = "from-request"
    elif case == "unknown_route":
        result = handler.handle("/api/v1/spend/analytics/nope", {}, Request())
        assert result.status_code == 405
        assert payload(result)["error"] == "Method not allowed"
        assert provider_spy.count == 0
    else:
        result = handler.handle(ROUTES["provider"], {}, Request(method="POST"))
        assert result.status_code == 405
        assert provider_spy.count == 0

    observation["result"] = summarize(result)
    observation["provider_calls"] = provider_spy.count
    observation["loops_created"] = len(spend["loops"].loops)
    observe(record_property, observation)


def test_TYPEADMIN_008_service_error_closes_loop(spend, handler, record_property) -> None:
    analytics = spend["analytics"]

    async def failing_trend(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("readiness-injected service failure")

    analytics.get_spend_trend = failing_trend
    result = handler.handle(ROUTES["trend"], {}, Request())
    body = payload(result)
    assert result.status_code == 500
    assert body["error"] == "An error occurred"
    assert "X-Trace-Id" in result.headers
    assert spend["loops"].closed == [True]
    observe(
        record_property,
        {
            "result": summarize(result),
            "loops_closed": spend["loops"].closed,
            "tracker": _tracker_state(spend["tracker"]),
        },
    )


@pytest.mark.no_auto_auth
@pytest.mark.parametrize("case", ["admin_jwt_denied", "owner_jwt_denied", "anonymous"])
def test_TYPEADMIN_008_real_credentials(
    case: str, spend, handler, monkeypatch: pytest.MonkeyPatch, record_property
) -> None:
    from aragora.billing.jwt_auth import create_access_token

    assert handler_decorators._test_user_context_override is None
    analytics = spend["analytics"]
    provider_spy = Spy(analytics.get_spend_by_provider)
    analytics.get_spend_by_provider = provider_spy

    if case == "anonymous":
        request = Request()
    else:
        role = "admin" if case == "admin_jwt_denied" else "owner"
        token = create_access_token("readiness-fixture", "fixture@example.invalid", role=role)
        request = Request(headers={"Authorization": f"Bearer {token}"})

    result = handler.handle(ROUTES["provider"], {}, request)
    body = payload(result)
    if case == "anonymous":
        assert result.status_code == 401
        assert body["error"] == "Authentication required"
    else:
        assert result.status_code == 403
        assert body["error"] == "Permission denied"
    assert provider_spy.count == 0
    assert spend["seam"].count == 0
    assert spend["loops"].loops == []
    observe(
        record_property,
        {
            "case": case,
            "result": summarize(result),
            "provider_calls": provider_spy.count,
            "analytics_seam_calls": spend["seam"].count,
            "loops_created": len(spend["loops"].loops),
            "tracker": _tracker_state(spend["tracker"]),
        },
    )
