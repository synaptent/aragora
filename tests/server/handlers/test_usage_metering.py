"""
Tests for Usage Metering API Handler.

Tests coverage for:
- GET /api/v1/billing/usage - Usage summary
- GET /api/v1/billing/usage/breakdown - Detailed breakdown
- GET /api/v1/billing/limits - Usage limits
- GET /api/v1/billing/usage/export - CSV export
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.server.handlers.conftest import parse_handler_response


@dataclass
class MockUsageSummary:
    """Mock usage summary response."""

    period_start: datetime = field(
        default_factory=lambda: datetime(2025, 1, 1, tzinfo=timezone.utc)
    )
    period_end: datetime = field(
        default_factory=lambda: datetime(2025, 1, 31, 23, 59, 59, tzinfo=timezone.utc)
    )
    period_type: str = "month"
    input_tokens: int = 500000
    output_tokens: int = 250000
    total_tokens: int = 750000
    cost: Decimal = field(default_factory=lambda: Decimal("12.50"))
    debates: int = 45
    api_calls: int = 1500

    def to_dict(self):
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "period_type": self.period_type,
            "tokens": {
                "input": self.input_tokens,
                "output": self.output_tokens,
                "total": self.total_tokens,
                "cost": str(self.cost),
            },
            "counts": {
                "debates": self.debates,
                "api_calls": self.api_calls,
            },
        }


@dataclass
class MockUsageBreakdown:
    """Mock usage breakdown response."""

    period_start: datetime = field(
        default_factory=lambda: datetime(2025, 1, 1, tzinfo=timezone.utc)
    )
    period_end: datetime = field(
        default_factory=lambda: datetime(2025, 1, 31, 23, 59, 59, tzinfo=timezone.utc)
    )
    total_cost: Decimal = field(default_factory=lambda: Decimal("125.50"))
    total_tokens: int = 5000000
    total_debates: int = 150
    total_api_calls: int = 5000
    by_model: list = field(default_factory=list)
    by_provider: list = field(default_factory=list)
    by_day: list = field(default_factory=list)
    by_user: list = field(default_factory=list)

    def __post_init__(self):
        if not self.by_model:
            self.by_model = [
                {
                    "model": "claude-3.5-sonnet",
                    "input_tokens": 2000000,
                    "output_tokens": 1000000,
                    "total_tokens": 3000000,
                    "cost": "75.00",
                    "requests": 1000,
                },
            ]
        if not self.by_provider:
            self.by_provider = [
                {
                    "provider": "anthropic",
                    "total_tokens": 3000000,
                    "cost": "75.00",
                    "requests": 1000,
                },
            ]
        if not self.by_day:
            self.by_day = [
                {
                    "day": "2025-01-15",
                    "total_tokens": 100000,
                    "cost": "2.50",
                    "debates": 5,
                    "api_calls": 100,
                },
            ]

    def to_dict(self):
        return {
            "totals": {
                "cost": str(self.total_cost),
                "tokens": self.total_tokens,
                "debates": self.total_debates,
                "api_calls": self.total_api_calls,
            },
            "by_model": self.by_model,
            "by_provider": self.by_provider,
            "by_day": self.by_day,
            "by_user": self.by_user,
        }


@dataclass
class MockUsageLimits:
    """Mock usage limits response."""

    tier: str = "enterprise"
    token_limit: int = 999999999
    debate_limit: int = 999999
    api_call_limit: int = 999999
    tokens_used: int = 750000
    debates_used: int = 45
    api_calls_used: int = 1500

    def to_dict(self):
        return {
            "tier": self.tier,
            "limits": {
                "tokens": self.token_limit,
                "debates": self.debate_limit,
                "api_calls": self.api_call_limit,
            },
            "used": {
                "tokens": self.tokens_used,
                "debates": self.debates_used,
                "api_calls": self.api_calls_used,
            },
            "percent": {
                "tokens": self.tokens_used / self.token_limit,
                "debates": self.debates_used / self.debate_limit,
                "api_calls": self.api_calls_used / self.api_call_limit,
            },
            "exceeded": {
                "tokens": self.tokens_used > self.token_limit,
                "debates": self.debates_used > self.debate_limit,
                "api_calls": self.api_calls_used > self.api_call_limit,
            },
        }


class TestUsageMeteringHandler:
    """Tests for UsageMeteringHandler."""

    @pytest.fixture
    def mock_usage_meter(self):
        """Create mock usage meter."""
        meter = MagicMock()
        meter.get_usage_summary = AsyncMock(return_value=MockUsageSummary())
        meter.get_usage_breakdown = AsyncMock(return_value=MockUsageBreakdown())
        meter.get_usage_limits = AsyncMock(return_value=MockUsageLimits())
        return meter

    @pytest.fixture
    def metering_handler(self, mock_server_context):
        """Create UsageMeteringHandler with mocked context."""
        from aragora.server.handlers.usage_metering import UsageMeteringHandler

        return UsageMeteringHandler(server_context=mock_server_context)

    def test_can_handle_valid_routes(self, metering_handler):
        """Handler recognizes valid routes."""
        assert metering_handler.can_handle("/api/v1/billing/usage") is True
        assert metering_handler.can_handle("/api/v1/billing/usage/breakdown") is True
        assert metering_handler.can_handle("/api/v1/billing/limits") is True
        assert metering_handler.can_handle("/api/v1/billing/usage/summary") is True
        assert metering_handler.can_handle("/api/v1/billing/usage/export") is True

    def test_can_handle_invalid_routes(self, metering_handler):
        """Handler rejects invalid routes."""
        assert metering_handler.can_handle("/api/v1/billing/invoices") is False
        assert metering_handler.can_handle("/api/v1/debates") is False
        assert metering_handler.can_handle("/billing/usage") is False

    def test_get_org_tier_returns_free_for_none(self, metering_handler):
        """_get_org_tier returns 'free' when org is None."""
        assert metering_handler._get_org_tier(None) == "free"

    def test_get_org_tier_handles_string_tier(self, metering_handler):
        """_get_org_tier handles string tier values."""
        org = MagicMock()
        org.tier = "professional"
        assert metering_handler._get_org_tier(org) == "professional"


class TestUsageMeteringRouting:
    """Tests for request routing."""

    @pytest.fixture
    def metering_handler(self, mock_server_context):
        """Create handler with mocked context."""
        from aragora.server.handlers.usage_metering import UsageMeteringHandler

        return UsageMeteringHandler(server_context=mock_server_context)

    @pytest.fixture
    def mock_http(self, mock_http_handler):
        """Create mock HTTP handler."""
        return mock_http_handler(method="GET")

    @pytest.mark.asyncio
    async def test_handle_routes_to_usage(self, metering_handler, mock_http):
        """handle() routes /api/v1/billing/usage to _get_usage."""
        with patch.object(
            metering_handler, "_get_usage", new=AsyncMock(return_value=MagicMock(status_code=200))
        ) as mock_get:
            with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
                mock_limiter.is_allowed.return_value = True
                await metering_handler.handle("/api/v1/billing/usage", {}, mock_http, "GET")
                mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_routes_to_breakdown(self, metering_handler, mock_http):
        """handle() routes /api/v1/billing/usage/breakdown to _get_usage_breakdown."""
        with patch.object(
            metering_handler,
            "_get_usage_breakdown",
            new=AsyncMock(return_value=MagicMock(status_code=200)),
        ) as mock_get:
            with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
                mock_limiter.is_allowed.return_value = True
                await metering_handler.handle(
                    "/api/v1/billing/usage/breakdown", {}, mock_http, "GET"
                )
                mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_routes_to_limits(self, metering_handler, mock_http):
        """handle() routes /api/v1/billing/limits to _get_limits."""
        with patch.object(
            metering_handler, "_get_limits", new=AsyncMock(return_value=MagicMock(status_code=200))
        ) as mock_get:
            with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
                mock_limiter.is_allowed.return_value = True
                await metering_handler.handle("/api/v1/billing/limits", {}, mock_http, "GET")
                mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_rate_limit_exceeded(self, metering_handler, mock_http):
        """handle() returns 429 when rate limit exceeded."""
        with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = False
            result = await metering_handler.handle("/api/v1/billing/usage", {}, mock_http, "GET")
            assert result.status_code == 429

    @pytest.mark.asyncio
    async def test_handle_method_not_allowed(self, metering_handler):
        """handle() returns 405 for unsupported method."""
        mock_http = MagicMock()
        mock_http.command = "DELETE"
        mock_http.client_address = ("127.0.0.1", 12345)
        mock_http.headers = {}

        with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = True
            result = await metering_handler.handle("/api/v1/billing/usage", {}, mock_http, "DELETE")
            assert result.status_code == 405


class TestQuotaIncreaseRequest:
    """Tests for POST /api/v1/quotas/request-increase and the literal-path guard.

    The 'request-increase' literal is an action endpoint (POST-only per both
    SDKs and the registered spec contract); it must never be served as a
    /api/v1/quotas/{resource} lookup.
    """

    REQUEST_INCREASE_PATH = "/api/v1/quotas/request-increase"

    @pytest.fixture
    def metering_handler(self, mock_server_context):
        """Create handler whose mocked user store resolves a user and an org."""
        from aragora.server.handlers.usage_metering import UsageMeteringHandler

        db_user = MagicMock()
        db_user.org_id = "org-001"
        org = MagicMock()
        org.id = "org-001"
        mock_server_context["user_store"].get_user_by_id.return_value = db_user
        mock_server_context["user_store"].get_organization_by_id.return_value = org
        return UsageMeteringHandler(server_context=mock_server_context)

    @pytest.mark.asyncio
    async def test_post_request_increase_returns_submission_receipt(
        self, metering_handler, mock_http_handler
    ):
        """POST on the literal dispatches to a real implementation (no 405)."""
        mock_http = mock_http_handler(
            method="POST",
            body={"resource": "debates", "requested_limit": 500, "reason": "scaling up"},
        )
        with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = True
            result = await metering_handler.handle(
                self.REQUEST_INCREASE_PATH, {}, mock_http, "POST"
            )
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert isinstance(body["request_id"], str)
        assert body["request_id"]
        assert body["status"] == "pending"
        assert body["resource"] == "debates"
        assert body["requested_limit"] == 500
        assert body["reason"] == "scaling up"

    @pytest.mark.asyncio
    async def test_post_request_increase_accepts_justification_alias(
        self, metering_handler, mock_http_handler
    ):
        """The python SDK sends 'justification'; it is accepted as the reason."""
        mock_http = mock_http_handler(
            method="POST",
            body={"resource": "tokens", "justification": "traffic spike"},
        )
        with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = True
            result = await metering_handler.handle(
                self.REQUEST_INCREASE_PATH, {}, mock_http, "POST"
            )
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert body["reason"] == "traffic spike"
        assert body["requested_limit"] is None

    @pytest.mark.asyncio
    async def test_post_request_increase_requires_resource(
        self, metering_handler, mock_http_handler
    ):
        """A body without 'resource' is a 400, not a submission."""
        mock_http = mock_http_handler(method="POST", body={"requested_limit": 100})
        with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = True
            result = await metering_handler.handle(
                self.REQUEST_INCREASE_PATH, {}, mock_http, "POST"
            )
        assert result.status_code == 400
        body = parse_handler_response(result)
        assert "resource" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_post_request_increase_rejects_invalid_json(self, metering_handler):
        """A malformed JSON body is a 400."""
        mock_http = MagicMock()
        mock_http.command = "POST"
        mock_http.client_address = ("127.0.0.1", 12345)
        mock_http.body = None
        mock_http.request = None
        raw = b"{not-json"
        mock_http.headers = {"Content-Length": str(len(raw))}
        mock_http.rfile.read.return_value = raw
        with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = True
            result = await metering_handler.handle(
                self.REQUEST_INCREASE_PATH, {}, mock_http, "POST"
            )
        assert result.status_code == 400

    @pytest.mark.parametrize(
        "bad_limit", ["lots", -5, 0, True, float("nan"), float("inf"), float("-inf")]
    )
    @pytest.mark.asyncio
    async def test_post_request_increase_rejects_invalid_requested_limit(
        self, metering_handler, mock_http_handler, bad_limit
    ):
        """requested_limit must be a positive finite number when provided."""
        mock_http = mock_http_handler(
            method="POST", body={"resource": "debates", "requested_limit": bad_limit}
        )
        with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = True
            result = await metering_handler.handle(
                self.REQUEST_INCREASE_PATH, {}, mock_http, "POST"
            )
        assert result.status_code == 400
        body = parse_handler_response(result)
        assert "requested_limit" in body.get("error", "")

    @pytest.mark.parametrize(
        "bad_resource",
        [
            "debates\nfake-entry",
            "tok\rens",
            "a\x00b",
            "a\u0085b",
            "a\u2028b",
            "a\u2029b",
            # C1 controls: not caught by an ord()<0x20/DEL check. U+009B is a
            # bare CSI, a terminal-escape vector when logs are viewed in
            # terminals.
            "a\x80b",
            "a\x9bb",
            "a\x9fb",
            # Cf format chars: bidi overrides and zero-width joiners are not
            # control chars but reorder or hide text, visually spoofing the
            # audit line.
            "a\u202eb",
            "a\u200db",
            "a\ufeffb",
            # Cs lone surrogates arrive over the wire as pure-ASCII JSON
            # \ud800 escapes (json.dumps ensure_ascii re-emits them here); a
            # utf-8 log handler cannot encode the decoded value.
            "a\ud800b",
            "a\udfffb",
        ],
    )
    @pytest.mark.asyncio
    async def test_post_request_increase_rejects_control_chars_in_resource(
        self, metering_handler, mock_http_handler, bad_resource
    ):
        """Control characters and line separators in 'resource' are rejected."""
        mock_http = mock_http_handler(method="POST", body={"resource": bad_resource})
        with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = True
            result = await metering_handler.handle(
                self.REQUEST_INCREASE_PATH, {}, mock_http, "POST"
            )
        assert result.status_code == 400
        body = parse_handler_response(result)
        assert "resource" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_post_request_increase_accepts_huge_integer_limit(
        self, metering_handler, mock_http_handler
    ):
        """Arbitrary-precision JSON ints are valid (ints are always finite, no 500)."""
        huge = 10**400
        mock_http = mock_http_handler(
            method="POST", body={"resource": "debates", "requested_limit": huge}
        )
        with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = True
            result = await metering_handler.handle(
                self.REQUEST_INCREASE_PATH, {}, mock_http, "POST"
            )
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert body["requested_limit"] == huge

    @pytest.mark.asyncio
    async def test_post_request_increase_rejects_overlong_resource(
        self, metering_handler, mock_http_handler
    ):
        """resource is length-bounded well below the body-size cap."""
        mock_http = mock_http_handler(method="POST", body={"resource": "r" * 257})
        with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = True
            result = await metering_handler.handle(
                self.REQUEST_INCREASE_PATH, {}, mock_http, "POST"
            )
        assert result.status_code == 400
        body = parse_handler_response(result)
        assert "resource" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_post_request_increase_overlong_resource_rejects_on_length_before_scan(
        self, metering_handler, mock_http_handler
    ):
        """An oversized resource of scan-rejected chars fails on the LENGTH
        message: the O(1) cap runs before the per-char category scan."""
        mock_http = mock_http_handler(method="POST", body={"resource": "\x9b" * 300})
        with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = True
            result = await metering_handler.handle(
                self.REQUEST_INCREASE_PATH, {}, mock_http, "POST"
            )
        assert result.status_code == 400
        body = parse_handler_response(result)
        assert "maximum length" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_post_request_increase_surrogate_escape_never_reaches_log_handler(
        self, metering_handler, tmp_path
    ):
        """A wire-level JSON \\ud800 escape (pure-ASCII bytes) is rejected
        before the audit log call: a utf-8 log handler cannot encode the
        decoded lone surrogate and would silently drop the audit line."""
        raw = b'{"resource": "a\\ud800b", "requested_limit": 5}'
        mock_http = MagicMock()
        mock_http.command = "POST"
        mock_http.client_address = ("127.0.0.1", 12345)
        mock_http.body = None
        mock_http.request = None
        mock_http.headers = {"Content-Length": str(len(raw))}
        mock_http.rfile.read.return_value = raw

        log_file = tmp_path / "audit.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        module_logger = logging.getLogger("aragora.server.handlers.usage_metering")
        previous_level = module_logger.level
        module_logger.addHandler(file_handler)
        module_logger.setLevel(logging.INFO)
        try:
            # emit() swallows UnicodeEncodeError into handleError; spying on
            # it makes the silent-drop failure mode observable.
            with (
                patch.object(file_handler, "handleError") as mock_handle_error,
                patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter,
            ):
                mock_limiter.is_allowed.return_value = True
                result = await metering_handler.handle(
                    self.REQUEST_INCREASE_PATH, {}, mock_http, "POST"
                )
        finally:
            module_logger.removeHandler(file_handler)
            module_logger.setLevel(previous_level)
            file_handler.close()

        assert result.status_code == 400
        body = parse_handler_response(result)
        assert "resource" in body.get("error", "").lower()
        mock_handle_error.assert_not_called()
        logged = log_file.read_text(encoding="utf-8")
        assert "Quota increase request" not in logged

    @pytest.mark.asyncio
    async def test_post_request_increase_rejects_overlong_reason(
        self, metering_handler, mock_http_handler
    ):
        """reason is length-bounded well below the body-size cap."""
        mock_http = mock_http_handler(
            method="POST", body={"resource": "debates", "reason": "r" * 2001}
        )
        with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = True
            result = await metering_handler.handle(
                self.REQUEST_INCREASE_PATH, {}, mock_http, "POST"
            )
        assert result.status_code == 400
        body = parse_handler_response(result)
        assert "reason" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_post_request_increase_without_user_store_returns_503(self, mock_http_handler):
        """Missing user store keeps the sibling endpoints' 503 ladder."""
        from aragora.server.handlers.usage_metering import UsageMeteringHandler

        handler = UsageMeteringHandler(server_context={})
        mock_http = mock_http_handler(method="POST", body={"resource": "debates"})
        with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = True
            result = await handler.handle(self.REQUEST_INCREASE_PATH, {}, mock_http, "POST")
        assert result.status_code == 503

    @pytest.mark.asyncio
    async def test_get_request_increase_literal_is_not_a_resource_lookup(
        self, metering_handler, mock_http_handler
    ):
        """GET on the literal returns 405 instead of a {resource} quota lookup."""
        mock_http = mock_http_handler(method="GET")
        with patch.object(
            metering_handler, "_get_quota_for_resource", new=AsyncMock()
        ) as mock_lookup:
            with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
                mock_limiter.is_allowed.return_value = True
                result = await metering_handler.handle(
                    self.REQUEST_INCREASE_PATH, {}, mock_http, "GET"
                )
        assert result.status_code == 405
        mock_lookup.assert_not_called()

    @pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
    @pytest.mark.asyncio
    async def test_other_methods_on_request_increase_literal_return_405(
        self, metering_handler, mock_http_handler, method
    ):
        """Non-POST methods on the literal stay 405."""
        mock_http = mock_http_handler(method=method)
        with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = True
            result = await metering_handler.handle(
                self.REQUEST_INCREASE_PATH, {}, mock_http, method
            )
        assert result.status_code == 405

    def test_can_handle_request_increase_literal(self, metering_handler):
        """The literal remains claimed by can_handle (4-segment quotas path)."""
        assert metering_handler.can_handle(self.REQUEST_INCREASE_PATH) is True

    @pytest.mark.asyncio
    async def test_dynamic_resource_lookup_still_dispatches(
        self, metering_handler, mock_http_handler
    ):
        """Real resources (e.g. /api/v1/quotas/debates) still hit the lookup."""
        mock_http = mock_http_handler(method="GET")
        with patch.object(
            metering_handler,
            "_get_quota_for_resource",
            new=AsyncMock(return_value=MagicMock(status_code=200)),
        ) as mock_lookup:
            with patch("aragora.server.handlers.usage_metering._usage_limiter") as mock_limiter:
                mock_limiter.is_allowed.return_value = True
                await metering_handler.handle("/api/v1/quotas/debates", {}, mock_http, "GET")
        mock_lookup.assert_called_once()
        assert mock_lookup.call_args.args[1] == "debates"
