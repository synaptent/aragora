"""
Tests for aragora/server/handlers/base.py utilities.

Covers:
- BoundedTTLCache class
- ttl_cache decorator
- Parameter parsing utilities
- Validation functions
- Error handling decorators
- JSON response helpers
"""

import json
import time
import pytest
from unittest.mock import Mock, patch, MagicMock

from aragora.server.handlers.base import (
    BoundedTTLCache,
    ttl_cache,
    clear_cache,
    get_cache_stats,
    HandlerResult,
    json_response,
    error_response,
    generate_trace_id,
    handle_errors,
    with_error_recovery,
    parse_query_params,
    get_int_param,
    get_float_param,
    get_bool_param,
    get_string_param,
    get_clamped_int_param,
    get_bounded_float_param,
    get_bounded_string_param,
)
from aragora.server.middleware.exception_handler import map_exception_to_status
from aragora.server.validation import (
    ValidationResult,
    validate_against_schema,
    validate_path_segment,
    validate_agent_name,
    validate_debate_id,
)


# ============================================================================
# BoundedTTLCache Tests
# ============================================================================


class TestBoundedTTLCache:
    """Tests for BoundedTTLCache class."""

    def test_cache_set_and_get(self):
        """Should store and retrieve values."""
        cache = BoundedTTLCache(max_entries=10)
        cache.set("key1", "value1")

        hit, value = cache.get("key1", ttl_seconds=60)

        assert hit is True
        assert value == "value1"

    def test_cache_miss_returns_none(self):
        """Should return miss for non-existent keys."""
        cache = BoundedTTLCache(max_entries=10)

        hit, value = cache.get("nonexistent", ttl_seconds=60)

        assert hit is False
        assert value is None

    def test_cache_expires_after_ttl(self):
        """Should expire entries after TTL."""
        cache = BoundedTTLCache(max_entries=10)
        cache.set("key1", "value1")

        # Simulate time passing (cache module was extracted from base)
        with patch("aragora.server.handlers.cache.time.time") as mock_time:
            # Initial set was at time 0
            mock_time.return_value = 0
            cache.set("key2", "value2")

            # Get after TTL expired
            mock_time.return_value = 100
            hit, value = cache.get("key2", ttl_seconds=60)

            assert hit is False
            assert value is None

    def test_cache_evicts_oldest_when_full(self):
        """Should evict oldest entries when at capacity."""
        cache = BoundedTTLCache(max_entries=3, evict_percent=0.5)

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        # This should trigger eviction
        cache.set("key4", "value4")

        # Oldest should be evicted
        hit, _ = cache.get("key1", ttl_seconds=60)
        assert hit is False

        # Newest should exist
        hit, value = cache.get("key4", ttl_seconds=60)
        assert hit is True
        assert value == "value4"

    def test_cache_clear_all(self):
        """Should clear all entries."""
        cache = BoundedTTLCache(max_entries=10)
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        count = cache.clear()

        assert count == 2
        assert len(cache) == 0

    def test_cache_clear_by_prefix(self):
        """Should clear entries matching prefix."""
        cache = BoundedTTLCache(max_entries=10)
        cache.set("user:1", "alice")
        cache.set("user:2", "bob")
        cache.set("post:1", "hello")

        count = cache.clear("user:")

        assert count == 2
        assert len(cache) == 1
        hit, value = cache.get("post:1", ttl_seconds=60)
        assert hit is True

    def test_cache_stats(self):
        """Should track hits and misses."""
        cache = BoundedTTLCache(max_entries=10)
        cache.set("key1", "value1")

        # Hit
        cache.get("key1", ttl_seconds=60)
        # Miss
        cache.get("key2", ttl_seconds=60)

        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_cache_contains(self):
        """Should support 'in' operator."""
        cache = BoundedTTLCache(max_entries=10)
        cache.set("key1", "value1")

        assert "key1" in cache
        assert "key2" not in cache

    def test_cache_len(self):
        """Should return correct length."""
        cache = BoundedTTLCache(max_entries=10)
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        assert len(cache) == 2

    def test_cache_update_existing(self):
        """Should update existing entries."""
        cache = BoundedTTLCache(max_entries=10)
        cache.set("key1", "value1")
        cache.set("key1", "value2")

        hit, value = cache.get("key1", ttl_seconds=60)
        assert value == "value2"
        assert len(cache) == 1


# ============================================================================
# ttl_cache Decorator Tests
# ============================================================================


class TestTTLCacheDecorator:
    """Tests for ttl_cache decorator."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_cache()

    def test_caches_result(self):
        """Should cache function results."""
        call_count = 0

        @ttl_cache(ttl_seconds=60, key_prefix="test", skip_first=False)
        def expensive_func(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = expensive_func(5)
        result2 = expensive_func(5)

        assert result1 == 10
        assert result2 == 10
        assert call_count == 1  # Only called once

    def test_different_args_different_cache(self):
        """Should cache different args separately."""
        call_count = 0

        @ttl_cache(ttl_seconds=60, key_prefix="test", skip_first=False)
        def expensive_func(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        expensive_func(5)
        expensive_func(10)

        assert call_count == 2

    def test_skips_self_for_methods(self):
        """Should skip self when building cache key for methods."""
        call_count = 0

        class MyClass:
            @ttl_cache(ttl_seconds=60, key_prefix="test", skip_first=True)
            def method(self, x):
                nonlocal call_count
                call_count += 1
                return x * 2

        obj1 = MyClass()
        obj2 = MyClass()

        # Different instances, same args should hit same cache
        obj1.method(5)
        obj2.method(5)

        assert call_count == 1

    def test_clear_cache_by_prefix(self):
        """Should clear cache by prefix."""

        @ttl_cache(ttl_seconds=60, key_prefix="prefix1", skip_first=False)
        def func1(x):
            return x

        @ttl_cache(ttl_seconds=60, key_prefix="prefix2", skip_first=False)
        def func2(x):
            return x

        func1(1)
        func2(2)

        count = clear_cache("prefix1:")
        assert count >= 1


# ============================================================================
# Parameter Parsing Tests
# ============================================================================


class TestParameterParsing:
    """Tests for parameter parsing utilities."""

    def test_get_int_param_valid(self):
        """Should parse valid integer."""
        params = {"limit": "20"}
        assert get_int_param(params, "limit", 10) == 20

    def test_get_int_param_default(self):
        """Should return default for missing key."""
        params = {}
        assert get_int_param(params, "limit", 10) == 10

    def test_get_int_param_invalid(self):
        """Should return default for invalid value."""
        params = {"limit": "not_a_number"}
        assert get_int_param(params, "limit", 10) == 10

    def test_get_int_param_list_value(self):
        """Should handle list values from query strings."""
        params = {"limit": ["20", "30"]}
        assert get_int_param(params, "limit", 10) == 20

    def test_get_float_param_valid(self):
        """Should parse valid float."""
        params = {"threshold": "0.75"}
        assert get_float_param(params, "threshold", 0.5) == 0.75

    def test_get_float_param_default(self):
        """Should return default for missing key."""
        params = {}
        assert get_float_param(params, "threshold", 0.5) == 0.5

    def test_get_float_param_invalid(self):
        """Should return default for invalid value."""
        params = {"threshold": "invalid"}
        assert get_float_param(params, "threshold", 0.5) == 0.5

    def test_get_bool_param_true_values(self):
        """Should recognize various true values."""
        assert get_bool_param({"flag": "true"}, "flag") is True
        assert get_bool_param({"flag": "1"}, "flag") is True
        assert get_bool_param({"flag": "yes"}, "flag") is True
        assert get_bool_param({"flag": "on"}, "flag") is True
        assert get_bool_param({"flag": "TRUE"}, "flag") is True

    def test_get_bool_param_false_values(self):
        """Should recognize various false values."""
        assert get_bool_param({"flag": "false"}, "flag") is False
        assert get_bool_param({"flag": "0"}, "flag") is False
        assert get_bool_param({"flag": "no"}, "flag") is False

    def test_get_string_param_valid(self):
        """Should get string parameter."""
        params = {"name": "test"}
        assert get_string_param(params, "name") == "test"

    def test_get_string_param_default(self):
        """Should return default for missing key."""
        params = {}
        assert get_string_param(params, "name", "default") == "default"

    def test_get_string_param_list_value(self):
        """Should handle list values."""
        params = {"name": ["first", "second"]}
        assert get_string_param(params, "name") == "first"

    def test_get_clamped_int_param(self):
        """Should clamp integer to range."""
        params = {"limit": "200"}
        result = get_clamped_int_param(params, "limit", 10, 1, 100)
        assert result == 100

    def test_get_clamped_int_param_below_min(self):
        """Should clamp to minimum."""
        params = {"limit": "-5"}
        result = get_clamped_int_param(params, "limit", 10, 1, 100)
        assert result == 1

    def test_get_bounded_float_param(self):
        """Should bound float to range."""
        params = {"score": "1.5"}
        result = get_bounded_float_param(params, "score", 0.5, 0.0, 1.0)
        assert result == 1.0

    def test_get_bounded_string_param(self):
        """Should truncate string to max length."""
        params = {"text": "a" * 1000}
        result = get_bounded_string_param(params, "text", max_length=100)
        assert len(result) == 100


# ============================================================================
# Bounded Parameter Edge Case Tests
# ============================================================================


class TestClampedIntParamEdgeCases:
    """Comprehensive edge case tests for get_clamped_int_param."""

    def test_exact_min_value(self):
        """Should accept value exactly at minimum."""
        params = {"val": "1"}
        result = get_clamped_int_param(params, "val", 10, min_val=1, max_val=100)
        assert result == 1

    def test_exact_max_value(self):
        """Should accept value exactly at maximum."""
        params = {"val": "100"}
        result = get_clamped_int_param(params, "val", 10, min_val=1, max_val=100)
        assert result == 100

    def test_missing_key_uses_default_then_clamps(self):
        """Should use default and clamp it if outside range."""
        params = {}
        # Default 200 should be clamped to max of 100
        result = get_clamped_int_param(params, "val", 200, min_val=1, max_val=100)
        assert result == 100

    def test_missing_key_with_default_in_range(self):
        """Should use default when in valid range."""
        params = {}
        result = get_clamped_int_param(params, "val", 50, min_val=1, max_val=100)
        assert result == 50

    def test_invalid_string_falls_back_to_default(self):
        """Should use default for non-numeric string."""
        params = {"val": "not_a_number"}
        result = get_clamped_int_param(params, "val", 10, min_val=1, max_val=100)
        assert result == 10

    def test_list_value_uses_first(self):
        """Should handle list values from query string."""
        params = {"val": ["50", "100"]}
        result = get_clamped_int_param(params, "val", 10, min_val=1, max_val=100)
        assert result == 50

    def test_float_string_uses_default(self):
        """Should use default for float string (not valid int)."""
        params = {"val": "3.7"}
        result = get_clamped_int_param(params, "val", 10, min_val=1, max_val=100)
        # Float strings are not valid integers, so default is used
        assert result == 10

    def test_negative_range(self):
        """Should handle negative min/max values."""
        params = {"val": "-50"}
        result = get_clamped_int_param(params, "val", 0, min_val=-100, max_val=-10)
        assert result == -50

    def test_clamps_below_negative_min(self):
        """Should clamp to negative minimum."""
        params = {"val": "-200"}
        result = get_clamped_int_param(params, "val", 0, min_val=-100, max_val=-10)
        assert result == -100

    def test_large_value_clamps(self):
        """Should clamp very large values."""
        params = {"val": "999999999"}
        result = get_clamped_int_param(params, "val", 10, min_val=1, max_val=100)
        assert result == 100

    def test_min_equals_max(self):
        """Should always return min_val when min == max."""
        params = {"val": "999"}
        result = get_clamped_int_param(params, "val", 10, min_val=50, max_val=50)
        assert result == 50

    def test_zero_in_range(self):
        """Should accept zero when in range."""
        params = {"val": "0"}
        result = get_clamped_int_param(params, "val", 10, min_val=-10, max_val=10)
        assert result == 0

    def test_empty_string_uses_default(self):
        """Should use default for empty string."""
        params = {"val": ""}
        result = get_clamped_int_param(params, "val", 25, min_val=1, max_val=100)
        assert result == 25


class TestBoundedFloatParamEdgeCases:
    """Comprehensive edge case tests for get_bounded_float_param."""

    def test_exact_min_value(self):
        """Should accept value exactly at minimum."""
        params = {"val": "0.0"}
        result = get_bounded_float_param(params, "val", 0.5, min_val=0.0, max_val=1.0)
        assert result == 0.0

    def test_exact_max_value(self):
        """Should accept value exactly at maximum."""
        params = {"val": "1.0"}
        result = get_bounded_float_param(params, "val", 0.5, min_val=0.0, max_val=1.0)
        assert result == 1.0

    def test_scientific_notation(self):
        """Should parse scientific notation."""
        params = {"val": "1.5e-1"}
        result = get_bounded_float_param(params, "val", 0.5, min_val=0.0, max_val=1.0)
        assert result == 0.15

    def test_negative_range(self):
        """Should handle negative min/max values."""
        params = {"val": "-0.5"}
        result = get_bounded_float_param(params, "val", 0.0, min_val=-1.0, max_val=0.0)
        assert result == -0.5

    def test_very_small_value(self):
        """Should handle very small values."""
        params = {"val": "1e-10"}
        result = get_bounded_float_param(params, "val", 0.5, min_val=0.0, max_val=1.0)
        assert result == 1e-10

    def test_missing_key_uses_default(self):
        """Should use default for missing key."""
        params = {}
        result = get_bounded_float_param(params, "val", 0.5, min_val=0.0, max_val=1.0)
        assert result == 0.5

    def test_missing_key_clamps_default_above_max(self):
        """Should clamp default if above max."""
        params = {}
        result = get_bounded_float_param(params, "val", 2.0, min_val=0.0, max_val=1.0)
        assert result == 1.0

    def test_missing_key_clamps_default_below_min(self):
        """Should clamp default if below min."""
        params = {}
        result = get_bounded_float_param(params, "val", -0.5, min_val=0.0, max_val=1.0)
        assert result == 0.0

    def test_list_value_uses_first(self):
        """Should handle list values from query string."""
        params = {"val": ["0.75", "0.25"]}
        result = get_bounded_float_param(params, "val", 0.5, min_val=0.0, max_val=1.0)
        assert result == 0.75

    def test_invalid_string_uses_default(self):
        """Should use default for invalid string."""
        params = {"val": "invalid"}
        result = get_bounded_float_param(params, "val", 0.5, min_val=0.0, max_val=1.0)
        assert result == 0.5

    def test_integer_string(self):
        """Should accept integer string as float."""
        params = {"val": "1"}
        result = get_bounded_float_param(params, "val", 0.5, min_val=0.0, max_val=2.0)
        assert result == 1.0

    def test_min_equals_max(self):
        """Should always return min_val when min == max."""
        params = {"val": "999.0"}
        result = get_bounded_float_param(params, "val", 0.5, min_val=0.5, max_val=0.5)
        assert result == 0.5

    def test_infinity_clamps_to_max(self):
        """Should clamp infinity to max."""
        params = {"val": "inf"}
        result = get_bounded_float_param(params, "val", 0.5, min_val=0.0, max_val=1.0)
        assert result == 1.0

    def test_negative_infinity_clamps_to_min(self):
        """Should clamp negative infinity to min."""
        params = {"val": "-inf"}
        result = get_bounded_float_param(params, "val", 0.5, min_val=0.0, max_val=1.0)
        assert result == 0.0


class TestBoundedStringParamEdgeCases:
    """Comprehensive edge case tests for get_bounded_string_param."""

    def test_exact_max_length(self):
        """Should accept string at exactly max length."""
        params = {"val": "a" * 100}
        result = get_bounded_string_param(params, "val", max_length=100)
        assert result == "a" * 100
        assert len(result) == 100

    def test_unicode_characters(self):
        """Should handle unicode characters."""
        params = {"val": "héllo wörld 🌍"}
        result = get_bounded_string_param(params, "val", max_length=100)
        assert result == "héllo wörld 🌍"

    def test_unicode_truncation(self):
        """Should truncate unicode strings by character count."""
        params = {"val": "🌍" * 20}
        result = get_bounded_string_param(params, "val", max_length=10)
        assert len(result) == 10
        assert result == "🌍" * 10

    def test_empty_string(self):
        """Should return empty string."""
        params = {"val": ""}
        result = get_bounded_string_param(params, "val", max_length=100)
        assert result == ""

    def test_missing_key_returns_none(self):
        """Should return None for missing key with no default."""
        params = {}
        result = get_bounded_string_param(params, "val", max_length=100)
        assert result is None

    def test_missing_key_with_default(self):
        """Should return default for missing key."""
        params = {}
        result = get_bounded_string_param(params, "val", default="default", max_length=100)
        assert result == "default"

    def test_list_value_uses_first(self):
        """Should handle list values from query string."""
        params = {"val": ["first", "second"]}
        result = get_bounded_string_param(params, "val", max_length=100)
        assert result == "first"

    def test_newlines_preserved(self):
        """Should preserve newlines in string."""
        params = {"val": "line1\nline2\rline3"}
        result = get_bounded_string_param(params, "val", max_length=100)
        assert result == "line1\nline2\rline3"

    def test_whitespace_preserved(self):
        """Should preserve whitespace."""
        params = {"val": "  spaced  text  "}
        result = get_bounded_string_param(params, "val", max_length=100)
        assert result == "  spaced  text  "

    def test_special_characters(self):
        """Should handle special characters."""
        params = {"val": "a<script>b</script>c"}
        result = get_bounded_string_param(params, "val", max_length=100)
        assert result == "a<script>b</script>c"

    def test_sql_like_content_truncated(self):
        """Should truncate SQL-like content without interpretation."""
        params = {"val": "'; DROP TABLE users; --" * 10}
        result = get_bounded_string_param(params, "val", max_length=20)
        assert len(result) == 20
        assert result == "'; DROP TABLE users;"

    def test_zero_max_length(self):
        """Should return empty string for zero max length."""
        params = {"val": "test string"}
        result = get_bounded_string_param(params, "val", max_length=0)
        assert result == ""

    def test_default_truncated_if_too_long(self):
        """Should truncate default if exceeds max length."""
        params = {}
        result = get_bounded_string_param(params, "val", default="a" * 200, max_length=50)
        assert len(result) == 50

    def test_parse_query_params(self):
        """Should parse query string to dict."""
        result = parse_query_params("limit=20&domain=test")
        assert result == {"limit": "20", "domain": "test"}

    def test_parse_query_params_empty(self):
        """Should handle empty query string."""
        assert parse_query_params("") == {}
        assert parse_query_params(None) == {}


# ============================================================================
# Validation Tests
# ============================================================================


class TestValidation:
    """Tests for validation functions."""

    def test_validate_path_segment_valid(self):
        """Should accept valid segments."""
        is_valid, error = validate_path_segment("debate-123", "debate_id")
        assert is_valid is True
        assert error is None

    def test_validate_path_segment_empty(self):
        """Should reject empty segments."""
        is_valid, error = validate_path_segment("", "debate_id")
        assert is_valid is False
        assert "Missing" in error

    def test_validate_path_segment_traversal(self):
        """Should reject path traversal attempts."""
        is_valid, error = validate_path_segment("../etc/passwd", "file")
        assert is_valid is False
        assert "must match pattern" in error

    def test_validate_path_segment_slash(self):
        """Should reject paths with slashes."""
        is_valid, error = validate_path_segment("foo/bar", "segment")
        assert is_valid is False
        assert "must match pattern" in error

    def test_validate_agent_name_valid(self):
        """Should accept valid agent names."""
        is_valid, error = validate_agent_name("claude-3")
        assert is_valid is True

    def test_validate_agent_name_invalid(self):
        """Should reject invalid agent names."""
        is_valid, error = validate_agent_name("agent<script>")
        assert is_valid is False

    def test_validate_debate_id_valid(self):
        """Should accept valid debate IDs."""
        is_valid, error = validate_debate_id("debate-abc123")
        assert is_valid is True

    def test_validate_debate_id_traversal(self):
        """Should reject path traversal in debate IDs."""
        is_valid, error = validate_debate_id("../../secret")
        assert is_valid is False


class TestSchemaValidation:
    """Tests for schema-based validation."""

    def test_validates_required_param(self):
        """Should reject missing required params."""
        schema = {"name": {"required": True, "type": "string"}}
        result = validate_against_schema({}, schema)

        assert result.is_valid is False
        assert "Missing required" in result.error

    def test_validates_optional_field(self):
        """Should allow missing optional field."""
        schema = {"limit": {"type": "int", "required": False}}
        result = validate_against_schema({}, schema)

        assert result.is_valid is True

    def test_validates_int_type(self):
        """Should validate actual int type."""
        schema = {"limit": {"type": "int", "required": True}}
        result = validate_against_schema({"limit": 50}, schema)

        assert result.is_valid is True
        assert result.data["limit"] == 50

    def test_validates_int_min_max(self):
        """Should enforce min/max for ints."""
        schema = {"limit": {"type": "int", "min_value": 1, "max_value": 100}}
        result = validate_against_schema({"limit": 200}, schema)

        assert result.is_valid is False
        assert "at most" in result.error or "100" in result.error

    def test_validates_float_type(self):
        """Should validate actual float type."""
        schema = {"score": {"type": "float", "required": True}}
        result = validate_against_schema({"score": 0.75}, schema)

        assert result.is_valid is True
        assert result.data["score"] == 0.75

    def test_validates_enum_field(self):
        """Should enforce allowed enum values."""
        schema = {"status": {"type": "enum", "allowed_values": {"active", "inactive"}}}
        result = validate_against_schema({"status": "invalid"}, schema)

        assert result.is_valid is False
        assert "must be one of" in result.error or "active" in result.error


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling decorators."""

    def test_handle_errors_catches_exception(self):
        """Should catch exceptions and return error response."""

        @handle_errors("test operation")
        def failing_func():
            raise ValueError("Test error")

        result = failing_func()

        assert isinstance(result, HandlerResult)
        assert result.status_code == 400  # ValueError maps to 400

    def test_handle_errors_includes_trace_id(self):
        """Should include trace ID in response headers."""

        @handle_errors("test operation")
        def failing_func():
            raise ValueError("Test error")

        result = failing_func()

        assert "X-Trace-Id" in result.headers

    def test_handle_errors_logs_exception(self):
        """Should log the exception."""
        with patch("aragora.server.handlers.utils.decorators.logger") as mock_logger:

            @handle_errors("test operation")
            def failing_func():
                raise ValueError("Test error")

            failing_func()

            mock_logger.error.assert_called_once()

    def test_handle_errors_returns_success_on_no_error(self):
        """Should pass through successful results."""

        @handle_errors("test operation")
        def success_func():
            return json_response({"result": "ok"})

        result = success_func()

        assert result.status_code == 200

    def test_map_exception_to_status(self):
        """Should map exceptions to appropriate status codes."""
        assert map_exception_to_status(FileNotFoundError()) == 404
        assert map_exception_to_status(ValueError()) == 400
        assert map_exception_to_status(PermissionError()) == 403
        assert map_exception_to_status(TimeoutError()) == 504
        assert map_exception_to_status(Exception()) == 500  # Default


class TestErrorRecovery:
    """Tests for error recovery decorator."""

    def test_returns_fallback_on_error(self):
        """Should return fallback value on error."""

        @with_error_recovery(fallback_value=[])
        def failing_func():
            raise RuntimeError("Error")

        result = failing_func()
        assert result == []

    def test_returns_result_on_success(self):
        """Should return actual result on success."""

        @with_error_recovery(fallback_value=[])
        def success_func():
            return [1, 2, 3]

        result = success_func()
        assert result == [1, 2, 3]

    def test_logs_error_when_enabled(self):
        """Should log warnings when log_errors=True."""
        with patch("aragora.server.handlers.utils.decorators.logger") as mock_logger:

            @with_error_recovery(fallback_value=None, log_errors=True)
            def failing_func():
                raise RuntimeError("Error")

            failing_func()

            mock_logger.warning.assert_called_once()

    def test_no_log_when_disabled(self):
        """Should not log when log_errors=False."""
        with patch("aragora.server.handlers.utils.decorators.logger") as mock_logger:

            @with_error_recovery(fallback_value=None, log_errors=False)
            def failing_func():
                raise RuntimeError("Error")

            failing_func()

            mock_logger.error.assert_not_called()


# ============================================================================
# JSON Response Tests
# ============================================================================


class TestJSONResponse:
    """Tests for JSON response helpers."""

    def test_json_response_structure(self):
        """Should create proper HandlerResult."""
        result = json_response({"key": "value"})

        assert result.status_code == 200
        assert result.content_type == "application/json"
        assert b'"key"' in result.body

    def test_json_response_custom_status(self):
        """Should accept custom status code."""
        result = json_response({"key": "value"}, status=201)
        assert result.status_code == 201

    def test_json_response_serializes_dates(self):
        """Should serialize datetime objects."""
        from datetime import datetime

        data = {"timestamp": datetime(2024, 1, 1, 12, 0, 0)}

        result = json_response(data)

        assert b"2024-01-01" in result.body

    def test_json_response_custom_headers(self):
        """Should include custom headers."""
        result = json_response({"key": "value"}, headers={"X-Custom": "test"})
        assert result.headers["X-Custom"] == "test"

    def test_error_response_structure(self):
        """Should create error response with message."""
        result = error_response("Something went wrong", 400)

        assert result.status_code == 400
        body = json.loads(result.body)
        assert body["error"] == "Something went wrong"

    def test_error_response_default_status(self):
        """Should default to 400 status."""
        result = error_response("Error")
        assert result.status_code == 400


# ============================================================================
# Trace ID Tests
# ============================================================================


class TestTraceID:
    """Tests for trace ID generation."""

    def test_generates_trace_id(self):
        """Should generate valid trace ID."""
        trace_id = generate_trace_id()

        assert len(trace_id) == 8
        assert trace_id.isalnum()

    def test_generates_unique_ids(self):
        """Should generate unique IDs."""
        ids = {generate_trace_id() for _ in range(100)}
        assert len(ids) == 100


# ============================================================================
# HandlerResult Tests
# ============================================================================


class TestHandlerResult:
    """Tests for HandlerResult dataclass."""

    def test_default_headers(self):
        """Should initialize empty headers dict."""
        result = HandlerResult(status_code=200, content_type="text/plain", body=b"test")
        assert result.headers == {}

    def test_custom_headers(self):
        """Should accept custom headers."""
        result = HandlerResult(
            status_code=200, content_type="text/plain", body=b"test", headers={"X-Custom": "value"}
        )
        assert result.headers["X-Custom"] == "value"


# ============================================================================
# Cache Stats Tests
# ============================================================================


class TestCacheStats:
    """Tests for cache statistics."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_cache()

    def test_get_cache_stats(self):
        """Should return cache statistics."""
        stats = get_cache_stats()

        assert "entries" in stats
        assert "max_entries" in stats
        assert "hits" in stats
        assert "misses" in stats
        assert "hit_rate" in stats


# ============================================================================
# Exception Handling Edge Case Tests
# ============================================================================


class TestExceptionStatusMapping:
    """Edge case tests for exception to HTTP status mapping."""

    def test_file_not_found_maps_to_404(self):
        """FileNotFoundError should map to 404."""
        assert map_exception_to_status(FileNotFoundError("missing")) == 404

    def test_key_error_maps_to_404(self):
        """KeyError should map to 404."""
        assert map_exception_to_status(KeyError("key")) == 404

    def test_value_error_maps_to_400(self):
        """ValueError should map to 400."""
        assert map_exception_to_status(ValueError("bad value")) == 400

    def test_type_error_maps_to_400(self):
        """TypeError should map to 400."""
        assert map_exception_to_status(TypeError("bad type")) == 400

    def test_permission_error_maps_to_403(self):
        """PermissionError should map to 403."""
        assert map_exception_to_status(PermissionError("denied")) == 403

    def test_timeout_error_maps_to_504(self):
        """TimeoutError should map to 504."""
        assert map_exception_to_status(TimeoutError("timeout")) == 504

    def test_connection_error_maps_to_502(self):
        """ConnectionError should map to 502."""
        assert map_exception_to_status(ConnectionError("conn failed")) == 502

    def test_os_error_maps_to_500(self):
        """OSError should map to 500."""
        assert map_exception_to_status(OSError("os error")) == 500

    def test_generic_exception_maps_to_500(self):
        """Unknown exceptions should map to 500."""
        assert map_exception_to_status(Exception("generic")) == 500

    def test_runtime_error_maps_to_500(self):
        """RuntimeError should map to 500."""
        assert map_exception_to_status(RuntimeError("runtime")) == 500

    def test_custom_exception_maps_to_500(self):
        """Custom exceptions should map to 500."""

        class CustomError(Exception):
            pass

        assert map_exception_to_status(CustomError("custom")) == 500


class TestHandleErrorsDecorator:
    """Edge case tests for @handle_errors decorator."""

    def test_preserves_return_value_on_success(self):
        """Should return original value when no exception."""

        @handle_errors("test")
        def success_func():
            return json_response({"key": "value"})

        result = success_func()
        assert result.status_code == 200

    def test_maps_file_not_found_to_404(self):
        """Should return 404 for FileNotFoundError."""

        @handle_errors("test")
        def not_found_func():
            raise FileNotFoundError("missing file")

        result = not_found_func()
        assert result.status_code == 404

    def test_maps_key_error_to_404(self):
        """Should return 404 for KeyError."""

        @handle_errors("test")
        def key_error_func():
            raise KeyError("missing key")

        result = key_error_func()
        assert result.status_code == 404

    def test_maps_permission_error_to_403(self):
        """Should return 403 for PermissionError."""

        @handle_errors("test")
        def permission_func():
            raise PermissionError("access denied")

        result = permission_func()
        assert result.status_code == 403

    def test_maps_timeout_error_to_504(self):
        """Should return 504 for TimeoutError."""

        @handle_errors("test")
        def timeout_func():
            raise TimeoutError("timed out")

        result = timeout_func()
        assert result.status_code == 504

    def test_maps_connection_error_to_502(self):
        """Should return 502 for ConnectionError."""

        @handle_errors("test")
        def connection_func():
            raise ConnectionError("connection failed")

        result = connection_func()
        assert result.status_code == 502

    def test_uses_custom_default_status(self):
        """Should use custom default status when provided."""

        @handle_errors("test", default_status=503)
        def failing_func():
            raise RuntimeError("unknown error")

        result = failing_func()
        assert result.status_code == 503

    def test_includes_trace_id_in_headers(self):
        """Should include X-Trace-Id header on error."""

        @handle_errors("test")
        def failing_func():
            raise ValueError("error")

        result = failing_func()
        assert "X-Trace-Id" in result.headers
        assert len(result.headers["X-Trace-Id"]) == 8

    def test_error_body_contains_message(self):
        """Should include error message in response body."""

        @handle_errors("test")
        def failing_func():
            raise ValueError("test error message")

        result = failing_func()
        body = json.loads(result.body)
        assert "error" in body


class TestWithErrorRecoveryDecorator:
    """Edge case tests for @with_error_recovery decorator."""

    def test_returns_none_fallback(self):
        """Should return None as fallback value."""

        @with_error_recovery(fallback_value=None)
        def failing_func():
            raise RuntimeError("error")

        result = failing_func()
        assert result is None

    def test_returns_empty_dict_fallback(self):
        """Should return empty dict as fallback value."""

        @with_error_recovery(fallback_value={})
        def failing_func():
            raise RuntimeError("error")

        result = failing_func()
        assert result == {}

    def test_returns_empty_list_fallback(self):
        """Should return empty list as fallback value."""

        @with_error_recovery(fallback_value=[])
        def failing_func():
            raise RuntimeError("error")

        result = failing_func()
        assert result == []

    def test_returns_default_value_fallback(self):
        """Should return specific default value as fallback."""

        @with_error_recovery(fallback_value={"status": "degraded", "data": []})
        def failing_func():
            raise RuntimeError("error")

        result = failing_func()
        assert result == {"status": "degraded", "data": []}

    def test_returns_actual_result_on_success(self):
        """Should return actual result when no exception."""

        @with_error_recovery(fallback_value=[])
        def success_func():
            return [1, 2, 3]

        result = success_func()
        assert result == [1, 2, 3]

    def test_logs_error_when_enabled(self):
        """Should log warning when log_errors=True."""
        with patch("aragora.server.handlers.utils.decorators.logger") as mock_logger:

            @with_error_recovery(fallback_value=None, log_errors=True)
            def failing_func():
                raise ValueError("test error")

            failing_func()
            mock_logger.warning.assert_called()

    def test_does_not_log_when_disabled(self):
        """Should not log when log_errors=False."""
        with patch("aragora.server.handlers.utils.decorators.logger") as mock_logger:

            @with_error_recovery(fallback_value=None, log_errors=False)
            def failing_func():
                raise ValueError("test error")

            failing_func()
            mock_logger.error.assert_not_called()

    def test_handles_nested_exceptions(self):
        """Should handle exceptions raised during exception handling."""

        @with_error_recovery(fallback_value="safe_default")
        def complex_failing_func():
            try:
                raise ValueError("inner")
            except ValueError:
                raise RuntimeError("outer")

        result = complex_failing_func()
        assert result == "safe_default"


class TestTraceIdGeneration:
    """Edge case tests for trace ID generation."""

    def test_trace_id_is_8_chars(self):
        """Trace ID should be exactly 8 characters."""
        trace_id = generate_trace_id()
        assert len(trace_id) == 8

    def test_trace_id_is_alphanumeric(self):
        """Trace ID should be alphanumeric."""
        trace_id = generate_trace_id()
        assert trace_id.isalnum()

    def test_trace_ids_are_unique(self):
        """Generated trace IDs should be unique."""
        ids = {generate_trace_id() for _ in range(1000)}
        assert len(ids) == 1000

    def test_trace_id_is_lowercase(self):
        """Trace ID should be lowercase hex."""
        for _ in range(100):
            trace_id = generate_trace_id()
            assert trace_id == trace_id.lower()
