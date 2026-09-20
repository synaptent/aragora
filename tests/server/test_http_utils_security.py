"""
Security tests for HTTP utility functions.

Tests cover:
1. Query parameter validation edge cases
2. Type conversion security (safe_float, safe_int)
3. Async execution safety (run_async)
4. DoS protection via length limits
"""

import pytest
import asyncio
from unittest.mock import Mock, patch

from aragora.server.http_utils import (
    ALLOWED_QUERY_PARAMS,
    validate_query_params,
    safe_float,
    safe_int,
    run_async,
)


class TestQueryParamValidation:
    """Security tests for query parameter validation."""

    def test_unknown_param_rejected(self):
        """Unknown parameters should be rejected."""
        valid, error = validate_query_params({"malicious": ["payload"]})
        assert valid is False
        assert "Unknown query parameter" in error

    def test_sql_injection_param_rejected(self):
        """SQL injection attempts via param names should be rejected."""
        injection_attempts = [
            {"'; DROP TABLE users;--": ["value"]},
            {"union select": ["*"]},
            {"1=1 OR": ["true"]},
        ]

        for params in injection_attempts:
            valid, error = validate_query_params(params)
            assert valid is False, f"Should reject: {params}"

    def test_path_traversal_param_rejected(self):
        """Path traversal attempts should be rejected."""
        traversal_attempts = [
            {"../../../etc/passwd": ["read"]},
            {"..%2f..%2f": ["value"]},
        ]

        for params in traversal_attempts:
            valid, error = validate_query_params(params)
            assert valid is False, f"Should reject: {params}"

    def test_length_limit_enforced(self):
        """String params should enforce length limits."""
        # domain has max length 100
        valid, error = validate_query_params({"domain": ["a" * 101]})
        assert valid is False
        assert "exceeds max length" in error

    def test_length_at_boundary(self):
        """Length at exact boundary should pass."""
        # domain has max length 100
        valid, error = validate_query_params({"domain": ["a" * 100]})
        assert valid is True

    def test_enum_validation(self):
        """Enum params should only accept allowed values."""
        # table only allows specific values
        valid, error = validate_query_params({"table": ["debates"]})
        assert valid is True

        valid, error = validate_query_params({"table": ["malicious"]})
        assert valid is False
        assert "Invalid value" in error

    def test_empty_params_valid(self):
        """Empty params dict should be valid."""
        valid, error = validate_query_params({})
        assert valid is True

    def test_numeric_params_no_length_limit(self):
        """Numeric params (None rule) should not have length limits."""
        # limit is None - no length validation
        valid, error = validate_query_params({"limit": ["99999999999"]})
        assert valid is True

    def test_since_param_is_allowed_for_event_polling(self):
        """Debate event polling cursor should pass the global whitelist."""
        valid, error = validate_query_params({"since": ["0"]})
        assert valid is True

    def test_odr_version_param_is_allowed_for_receipt_export(self):
        """The ODR export profile selector must reach the handler, which validates it."""
        for value in ("0.1", "0.2", "0.3"):
            valid, error = validate_query_params({"odr_version": [value]})
            assert valid is True, error

    def test_multiple_values_all_validated(self):
        """All values in a multi-value param should be validated."""
        # Mixed valid and invalid
        valid, error = validate_query_params({"table": ["debates", "invalid"]})
        assert valid is False

    def test_xss_in_value_not_blocked_by_validator(self):
        """XSS in values isn't blocked here (should be sanitized elsewhere)."""
        # This validator only checks whitelist and length, not content
        # XSS protection should happen at output encoding
        valid, error = validate_query_params({"query": ["<script>alert(1)</script>"]})
        assert valid is True  # Validation passes, but output should be escaped

    def test_all_allowed_params_documented(self):
        """All allowed params should be in ALLOWED_QUERY_PARAMS."""
        expected_params = {
            "limit",
            "offset",
            "count",
            "domain",
            "loop_id",
            "topic",
            "query",
            "table",
            "agent",
            "agent_a",
            "agent_b",
            "debate_id",
            "pipeline_id",
            "sections",
            "buckets",
            "tiers",
            "min_importance",
            "event_type",
            "lines",
        }
        assert expected_params.issubset(set(ALLOWED_QUERY_PARAMS.keys()))


class TestSafeFloat:
    """Security tests for safe_float conversion."""

    def test_valid_float_conversion(self):
        """Valid float strings should convert."""
        assert safe_float("3.14") == 3.14
        assert safe_float("0") == 0.0
        assert safe_float("-1.5") == -1.5

    def test_integer_converts_to_float(self):
        """Integers should convert to float."""
        assert safe_float(42) == 42.0
        assert safe_float("42") == 42.0

    def test_invalid_returns_default(self):
        """Invalid inputs should return default."""
        assert safe_float("not a number") == 0.0
        assert safe_float("abc123") == 0.0
        assert safe_float("") == 0.0

    def test_none_returns_default(self):
        """None should return default."""
        assert safe_float(None) == 0.0

    def test_custom_default(self):
        """Custom default should be used."""
        assert safe_float("invalid", default=-1.0) == -1.0

    def test_infinity_handling(self):
        """Infinity should convert."""
        assert safe_float("inf") == float("inf")
        assert safe_float("-inf") == float("-inf")

    def test_nan_handling(self):
        """NaN should convert (but be NaN)."""
        import math

        result = safe_float("nan")
        assert math.isnan(result)

    def test_scientific_notation(self):
        """Scientific notation should convert."""
        assert safe_float("1e10") == 1e10
        assert safe_float("1.5e-3") == 0.0015

    def test_whitespace_handling(self):
        """Whitespace around number should work."""
        assert safe_float("  3.14  ") == 3.14

    def test_overflow_protection(self):
        """Very large numbers should handle without crash."""
        result = safe_float("1e309")  # Beyond float max
        assert result == float("inf")

    def test_list_returns_default(self):
        """List input should return default."""
        assert safe_float([1, 2, 3]) == 0.0

    def test_dict_returns_default(self):
        """Dict input should return default."""
        assert safe_float({"value": 3.14}) == 0.0


class TestSafeInt:
    """Security tests for safe_int conversion."""

    def test_valid_int_conversion(self):
        """Valid int strings should convert."""
        assert safe_int("42") == 42
        assert safe_int("0") == 0
        assert safe_int("-100") == -100

    def test_float_string_returns_default(self):
        """Float strings should return default (not truncate)."""
        assert safe_int("3.14") == 0
        assert safe_int("3.0") == 0

    def test_float_value_converts(self):
        """Float value should convert (truncates)."""
        assert safe_int(3.14) == 3
        assert safe_int(3.9) == 3

    def test_invalid_returns_default(self):
        """Invalid inputs should return default."""
        assert safe_int("not a number") == 0
        assert safe_int("abc") == 0
        assert safe_int("") == 0

    def test_none_returns_default(self):
        """None should return default."""
        assert safe_int(None) == 0

    def test_custom_default(self):
        """Custom default should be used."""
        assert safe_int("invalid", default=-1) == -1

    def test_hex_string_returns_default(self):
        """Hex strings should return default (strict parsing)."""
        assert safe_int("0xff") == 0

    def test_binary_string_returns_default(self):
        """Binary strings should return default."""
        assert safe_int("0b101") == 0

    def test_large_number(self):
        """Very large integers should work (Python has arbitrary precision)."""
        big_num = "123456789012345678901234567890"
        result = safe_int(big_num)
        assert result == 123456789012345678901234567890

    def test_whitespace_handling(self):
        """Whitespace around number should work."""
        assert safe_int("  42  ") == 42

    def test_list_returns_default(self):
        """List input should return default."""
        assert safe_int([1, 2, 3]) == 0

    def test_dict_returns_default(self):
        """Dict input should return default."""
        assert safe_int({"value": 42}) == 0


class TestRunAsync:
    """Security tests for run_async execution."""

    def test_simple_coroutine(self):
        """Simple coroutine should execute."""

        async def simple():
            return 42

        result = run_async(simple())
        assert result == 42

    def test_coroutine_with_sleep(self):
        """Coroutine with async operations should work."""

        async def with_sleep():
            await asyncio.sleep(0.01)
            return "done"

        result = run_async(with_sleep())
        assert result == "done"

    def test_exception_propagates(self):
        """Exceptions in coroutine should propagate."""

        async def raises():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            run_async(raises())

    def test_timeout_behavior(self):
        """Long-running coroutines should respect timeout."""

        async def slow():
            await asyncio.sleep(0.1)
            return "done"

        # Should complete within timeout
        result = run_async(slow())
        assert result == "done"

    def test_nested_async_calls(self):
        """Nested async calls should work."""

        async def inner():
            return 1

        async def outer():
            result = await inner()
            return result + 1

        result = run_async(outer())
        assert result == 2

    def test_returns_none_when_coroutine_returns_none(self):
        """Should return None when coroutine returns None."""

        async def returns_none():
            return None

        result = run_async(returns_none())
        assert result is None


class TestRunAsyncInEventLoop:
    """Tests for run_async when called from within an event loop."""

    @pytest.mark.asyncio
    async def test_from_async_context(self):
        """run_async should support nested calls from the current event loop."""

        async def inner():
            return "from_thread"

        assert run_async(inner()) == "from_thread"

    @pytest.mark.asyncio
    async def test_concurrent_run_async(self):
        """Repeated async-context calls should succeed consistently."""

        async def task(n):
            await asyncio.sleep(0.01)
            return n * 2

        results = []
        for i in range(3):
            results.append(run_async(task(i)))

        assert results == [0, 2, 4]


class TestQueryParamWhitelistCompleteness:
    """Tests to ensure all routes' params are whitelisted."""

    def test_pagination_params_allowed(self):
        """Pagination params should be allowed."""
        assert "limit" in ALLOWED_QUERY_PARAMS
        assert "offset" in ALLOWED_QUERY_PARAMS
        assert "count" in ALLOWED_QUERY_PARAMS
        assert "since" in ALLOWED_QUERY_PARAMS

    def test_spectate_params_allowed(self):
        """Public spectate polling params should be allowed."""
        assert "debate_id" in ALLOWED_QUERY_PARAMS
        assert "pipeline_id" in ALLOWED_QUERY_PARAMS

    def test_search_params_allowed(self):
        """Search params should be allowed."""
        assert "query" in ALLOWED_QUERY_PARAMS
        assert "topic" in ALLOWED_QUERY_PARAMS

    def test_agent_params_allowed(self):
        """Agent-related params should be allowed."""
        assert "agent" in ALLOWED_QUERY_PARAMS
        assert "agent_a" in ALLOWED_QUERY_PARAMS
        assert "agent_b" in ALLOWED_QUERY_PARAMS

    def test_table_enum_complete(self):
        """Table enum should include all exportable tables."""
        table_allowed = ALLOWED_QUERY_PARAMS["table"]
        expected = {"summary", "debates", "proposals", "votes", "critiques", "messages"}
        assert expected == table_allowed

    def test_sections_enum_complete(self):
        """Sections enum should include all valid sections."""
        sections_allowed = ALLOWED_QUERY_PARAMS["sections"]
        assert "all" in sections_allowed
        assert "identity" in sections_allowed
        assert "performance" in sections_allowed
        assert "relationships" in sections_allowed

    def test_event_type_enum_complete(self):
        """Event type enum should include all genesis events."""
        event_types = ALLOWED_QUERY_PARAMS["event_type"]
        expected = {"mutation", "crossover", "selection", "extinction", "speciation"}
        assert expected == event_types


class TestLengthLimitConfiguration:
    """Tests for length limit configuration."""

    def test_domain_has_reasonable_limit(self):
        """Domain should have reasonable length limit."""
        limit = ALLOWED_QUERY_PARAMS["domain"]
        assert isinstance(limit, int)
        assert 50 <= limit <= 255  # DNS max is 253

    def test_query_has_adequate_limit(self):
        """Query param should have adequate limit for search."""
        limit = ALLOWED_QUERY_PARAMS["query"]
        assert isinstance(limit, int)
        assert limit >= 100  # Should allow meaningful queries

    def test_topic_has_adequate_limit(self):
        """Topic param should have adequate limit."""
        limit = ALLOWED_QUERY_PARAMS["topic"]
        assert isinstance(limit, int)
        assert limit >= 100  # Should allow full topic names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
