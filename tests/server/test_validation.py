"""
Tests for request validation middleware.
"""

import json
import re
import pytest

from aragora.server.validation import (
    ValidationResult,
    validate_json_body,
    validate_content_type,
    validate_required_fields,
    validate_string_field,
    validate_int_field,
    validate_float_field,
    validate_list_field,
    validate_enum_field,
    validate_against_schema,
    sanitize_string,
    sanitize_id,
    SAFE_ID_PATTERN,
    SAFE_SLUG_PATTERN,
    SAFE_AGENT_PATTERN,
    MAX_JSON_BODY_SIZE,
    DEBATE_START_SCHEMA,
    VERIFICATION_SCHEMA,
    PROBE_RUN_SCHEMA,
)


# ============================================================================
# ValidationResult Tests
# ============================================================================


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_valid_result(self):
        """Test creating a valid result."""
        result = ValidationResult(is_valid=True, data={"key": "value"})

        assert result.is_valid is True
        assert result.error is None
        assert result.data == {"key": "value"}

    def test_invalid_result(self):
        """Test creating an invalid result."""
        result = ValidationResult(is_valid=False, error="Something went wrong")

        assert result.is_valid is False
        assert result.error == "Something went wrong"
        assert result.data is None


# ============================================================================
# JSON Body Validation Tests
# ============================================================================


class TestValidateJsonBody:
    """Tests for validate_json_body function."""

    def test_valid_json(self):
        """Test parsing valid JSON."""
        body = b'{"key": "value", "number": 42}'
        result = validate_json_body(body)

        assert result.is_valid is True
        assert result.data == {"key": "value", "number": 42}

    def test_empty_body(self):
        """Test empty body fails."""
        result = validate_json_body(b"")

        assert result.is_valid is False
        assert "empty" in result.error.lower()

    def test_invalid_json(self):
        """Test invalid JSON fails."""
        result = validate_json_body(b'{"key": value}')  # Missing quotes

        assert result.is_valid is False
        assert "Invalid JSON" in result.error

    def test_body_too_large(self):
        """Test oversized body fails."""
        large_body = b'{"x": "' + b"a" * (MAX_JSON_BODY_SIZE + 100) + b'"}'
        result = validate_json_body(large_body, max_size=MAX_JSON_BODY_SIZE)

        assert result.is_valid is False
        assert "too large" in result.error.lower()

    def test_invalid_utf8(self):
        """Test invalid UTF-8 encoding fails."""
        result = validate_json_body(b'\xff\xfe{"key": "value"}')

        assert result.is_valid is False
        assert "UTF-8" in result.error

    def test_nested_json(self):
        """Test valid nested JSON."""
        body = b'{"outer": {"inner": {"deep": [1, 2, 3]}}}'
        result = validate_json_body(body)

        assert result.is_valid is True
        assert result.data["outer"]["inner"]["deep"] == [1, 2, 3]


# ============================================================================
# Content-Type Validation Tests
# ============================================================================


class TestValidateContentType:
    """Tests for validate_content_type function."""

    @pytest.mark.parametrize(
        "content_type,expected_valid",
        [
            ("application/json", True),
            ("application/json; charset=utf-8", True),
            ("text/html", False),
            ("", False),
        ],
    )
    def test_content_type_validation(self, content_type: str, expected_valid: bool):
        """Test content type validation for various inputs."""
        result = validate_content_type(content_type)
        assert result.is_valid is expected_valid

    def test_missing_content_type_error_message(self):
        """Test missing content type has correct error message."""
        result = validate_content_type("")
        assert "Missing" in result.error

    def test_wrong_content_type_error_message(self):
        """Test wrong content type has correct error message."""
        result = validate_content_type("text/html")
        assert "Invalid Content-Type" in result.error

    def test_custom_expected_type(self):
        """Test custom expected content type."""
        result = validate_content_type("multipart/form-data", expected="multipart/form-data")
        assert result.is_valid is True


# ============================================================================
# Required Fields Validation Tests
# ============================================================================


class TestValidateRequiredFields:
    """Tests for validate_required_fields function."""

    def test_all_fields_present(self):
        """Test all required fields present."""
        data = {"name": "test", "value": 42}
        result = validate_required_fields(data, ["name", "value"])

        assert result.is_valid is True

    def test_missing_field(self):
        """Test missing required field fails."""
        data = {"name": "test"}
        result = validate_required_fields(data, ["name", "value"])

        assert result.is_valid is False
        assert "value" in result.error

    def test_null_field_value(self):
        """Test null field value counts as missing."""
        data = {"name": "test", "value": None}
        result = validate_required_fields(data, ["name", "value"])

        assert result.is_valid is False
        assert "value" in result.error

    def test_empty_required_list(self):
        """Test empty required list passes."""
        result = validate_required_fields({}, [])

        assert result.is_valid is True


# ============================================================================
# String Field Validation Tests
# ============================================================================


class TestValidateStringField:
    """Tests for validate_string_field function."""

    def test_valid_string(self):
        """Test valid string field."""
        data = {"name": "test value"}
        result = validate_string_field(data, "name")

        assert result.is_valid is True

    def test_string_too_short(self):
        """Test string below minimum length fails."""
        data = {"name": "ab"}
        result = validate_string_field(data, "name", min_length=5)

        assert result.is_valid is False
        assert "at least 5" in result.error

    def test_string_too_long(self):
        """Test string above maximum length fails."""
        data = {"name": "a" * 101}
        result = validate_string_field(data, "name", max_length=100)

        assert result.is_valid is False
        assert "at most 100" in result.error

    def test_string_pattern_match(self):
        """Test string matching pattern passes."""
        data = {"id": "valid_id-123"}
        result = validate_string_field(data, "id", pattern=SAFE_ID_PATTERN)

        assert result.is_valid is True

    def test_string_pattern_mismatch(self):
        """Test string not matching pattern fails."""
        data = {"id": "invalid id!@#"}
        result = validate_string_field(data, "id", pattern=SAFE_ID_PATTERN)

        assert result.is_valid is False
        assert "invalid format" in result.error.lower()

    def test_missing_required_string(self):
        """Test missing required string fails."""
        data = {}
        result = validate_string_field(data, "name", required=True)

        assert result.is_valid is False

    def test_missing_optional_string(self):
        """Test missing optional string passes."""
        data = {}
        result = validate_string_field(data, "name", required=False)

        assert result.is_valid is True

    def test_non_string_value(self):
        """Test non-string value fails."""
        data = {"name": 123}
        result = validate_string_field(data, "name")

        assert result.is_valid is False
        assert "must be a string" in result.error


# ============================================================================
# Integer Field Validation Tests
# ============================================================================


class TestValidateIntField:
    """Tests for validate_int_field function."""

    def test_valid_int(self):
        """Test valid integer field."""
        data = {"count": 42}
        result = validate_int_field(data, "count")

        assert result.is_valid is True

    def test_int_below_min(self):
        """Test integer below minimum fails."""
        data = {"count": 0}
        result = validate_int_field(data, "count", min_value=1)

        assert result.is_valid is False
        assert "at least 1" in result.error

    def test_int_above_max(self):
        """Test integer above maximum fails."""
        data = {"count": 101}
        result = validate_int_field(data, "count", max_value=100)

        assert result.is_valid is False
        assert "at most 100" in result.error

    def test_float_as_int_fails(self):
        """Test float value for int field fails."""
        data = {"count": 42.5}
        result = validate_int_field(data, "count")

        assert result.is_valid is False
        assert "must be an integer" in result.error

    def test_bool_as_int_fails(self):
        """Test boolean value for int field fails."""
        data = {"count": True}
        result = validate_int_field(data, "count")

        assert result.is_valid is False

    def test_missing_optional_int(self):
        """Test missing optional int passes."""
        data = {}
        result = validate_int_field(data, "count", required=False)

        assert result.is_valid is True


# ============================================================================
# Float Field Validation Tests
# ============================================================================


class TestValidateFloatField:
    """Tests for validate_float_field function."""

    def test_valid_float(self):
        """Test valid float field."""
        data = {"ratio": 0.75}
        result = validate_float_field(data, "ratio")

        assert result.is_valid is True

    def test_int_as_float_valid(self):
        """Test integer value for float field passes."""
        data = {"ratio": 1}
        result = validate_float_field(data, "ratio")

        assert result.is_valid is True

    def test_float_below_min(self):
        """Test float below minimum fails."""
        data = {"ratio": -0.5}
        result = validate_float_field(data, "ratio", min_value=0.0)

        assert result.is_valid is False
        assert "at least 0" in result.error

    def test_float_above_max(self):
        """Test float above maximum fails."""
        data = {"ratio": 1.5}
        result = validate_float_field(data, "ratio", max_value=1.0)

        assert result.is_valid is False
        assert "at most 1" in result.error

    def test_string_as_float_fails(self):
        """Test string value for float field fails."""
        data = {"ratio": "0.5"}
        result = validate_float_field(data, "ratio")

        assert result.is_valid is False
        assert "must be a number" in result.error


# ============================================================================
# List Field Validation Tests
# ============================================================================


class TestValidateListField:
    """Tests for validate_list_field function."""

    def test_valid_list(self):
        """Test valid list field."""
        data = {"items": ["a", "b", "c"]}
        result = validate_list_field(data, "items")

        assert result.is_valid is True

    def test_list_too_short(self):
        """Test list below minimum length fails."""
        data = {"items": [1]}
        result = validate_list_field(data, "items", min_length=2)

        assert result.is_valid is False
        assert "at least 2" in result.error

    def test_list_too_long(self):
        """Test list above maximum length fails."""
        data = {"items": list(range(10))}
        result = validate_list_field(data, "items", max_length=5)

        assert result.is_valid is False
        assert "at most 5" in result.error

    def test_list_item_type_valid(self):
        """Test list with correct item types passes."""
        data = {"items": ["a", "b", "c"]}
        result = validate_list_field(data, "items", item_type=str)

        assert result.is_valid is True

    def test_list_item_type_invalid(self):
        """Test list with wrong item type fails."""
        data = {"items": ["a", 2, "c"]}
        result = validate_list_field(data, "items", item_type=str)

        assert result.is_valid is False
        assert "items[1]" in result.error

    def test_non_list_value(self):
        """Test non-list value fails."""
        data = {"items": "not a list"}
        result = validate_list_field(data, "items")

        assert result.is_valid is False
        assert "must be a list" in result.error


# ============================================================================
# Enum Field Validation Tests
# ============================================================================


class TestValidateEnumField:
    """Tests for validate_enum_field function."""

    def test_valid_enum_value(self):
        """Test valid enum value passes."""
        data = {"status": "active"}
        result = validate_enum_field(data, "status", {"active", "inactive", "pending"})

        assert result.is_valid is True

    def test_invalid_enum_value(self):
        """Test invalid enum value fails."""
        data = {"status": "unknown"}
        result = validate_enum_field(data, "status", {"active", "inactive"})

        assert result.is_valid is False
        assert "must be one of" in result.error
        assert "active" in result.error
        assert "inactive" in result.error

    def test_missing_optional_enum(self):
        """Test missing optional enum passes."""
        data = {}
        result = validate_enum_field(data, "status", {"active"}, required=False)

        assert result.is_valid is True


# ============================================================================
# Schema Validation Tests
# ============================================================================


class TestValidateAgainstSchema:
    """Tests for validate_against_schema function."""

    def test_debate_start_valid(self):
        """Test valid debate start payload."""
        data = {
            "task": "Discuss the pros and cons of AI regulation",
            "agents": ["claude", "gemini"],
            "rounds": 5,
        }
        result = validate_against_schema(data, DEBATE_START_SCHEMA)

        assert result.is_valid is True

    def test_debate_start_missing_task(self):
        """Test debate start without task is valid (task is optional)."""
        data = {"agents": ["claude", "gemini"]}
        result = validate_against_schema(data, DEBATE_START_SCHEMA)

        # task field is optional in the schema (required=False)
        assert result.is_valid is True

    def test_debate_start_task_too_long(self):
        """Test debate start with oversized task fails."""
        data = {"task": "x" * 2001}
        result = validate_against_schema(data, DEBATE_START_SCHEMA)

        assert result.is_valid is False
        assert "at most 2000" in result.error

    def test_debate_start_single_agent_valid(self):
        """Test debate start with 1 agent is valid (min_length=0 in schema)."""
        data = {"task": "Test task", "agents": ["claude"]}
        result = validate_against_schema(data, DEBATE_START_SCHEMA)

        # Schema allows 0+ agents (auto_select can fill remaining)
        assert result.is_valid is True

    def test_debate_start_comparison_config_valid(self):
        """Comparison config object should validate for debate start requests."""
        data = {
            "task": "Discuss the strongest model lineup for this implementation task",
            "comparison_config": {
                "agent_combinations": [
                    ["claude", "gemini"],
                    ["openai-api", "grok"],
                ]
            },
        }
        result = validate_against_schema(data, DEBATE_START_SCHEMA)

        assert result.is_valid is True

    def test_debate_start_agent_combinations_requires_list(self):
        """Top-level comparison aliases should still enforce list shape."""
        data = {
            "task": "Discuss the strongest model lineup for this implementation task",
            "agent_combinations": "claude,gemini",
        }
        result = validate_against_schema(data, DEBATE_START_SCHEMA)

        assert result.is_valid is False
        assert "must be a list" in result.error

    def test_verification_schema_valid(self):
        """Test valid verification payload."""
        data = {
            "claim": "The sky is blue.",
            "context": "A discussion about colors.",
        }
        result = validate_against_schema(data, VERIFICATION_SCHEMA)

        assert result.is_valid is True

    def test_verification_missing_claim(self):
        """Test verification without claim fails."""
        data = {"context": "Some context"}
        result = validate_against_schema(data, VERIFICATION_SCHEMA)

        assert result.is_valid is False
        assert "claim" in result.error.lower()

    def test_probe_run_valid(self):
        """Test valid probe run payload."""
        data = {
            "agent_name": "claude",
            "strategies": ["contradiction", "hallucination"],
            "num_probes": 10,
        }
        result = validate_against_schema(data, PROBE_RUN_SCHEMA)

        assert result.is_valid is True

    def test_probe_run_invalid_agent_pattern(self):
        """Test probe run with invalid agent name fails."""
        data = {"agent_name": "invalid agent name!@#"}
        result = validate_against_schema(data, PROBE_RUN_SCHEMA)

        assert result.is_valid is False
        assert "invalid format" in result.error.lower()


# ============================================================================
# Sanitization Tests
# ============================================================================


class TestSanitizeString:
    """Tests for sanitize_string function."""

    @pytest.mark.parametrize(
        "input_str,expected",
        [
            ("  hello world  ", "hello world"),
            ("no_whitespace", "no_whitespace"),
        ],
    )
    def test_strips_whitespace(self, input_str: str, expected: str):
        """Test whitespace is stripped."""
        result = sanitize_string(input_str)
        assert result == expected

    def test_truncates_long_string(self):
        """Test long strings are truncated."""
        result = sanitize_string("a" * 100, max_length=50)
        assert len(result) == 50
        assert result == "a" * 50

    @pytest.mark.parametrize("input_val", [123, None, [], {}])
    def test_non_string_returns_empty(self, input_val):
        """Test non-string input returns empty string."""
        result = sanitize_string(input_val)
        assert result == ""


class TestSanitizeId:
    """Tests for sanitize_id function."""

    @pytest.mark.parametrize(
        "input_id,expected",
        [
            ("valid_id-123", "valid_id-123"),
            ("  valid_id  ", "valid_id"),
        ],
    )
    def test_valid_id(self, input_id: str, expected: str):
        """Test valid ID passes through (with whitespace stripping)."""
        result = sanitize_id(input_id)
        assert result == expected

    @pytest.mark.parametrize(
        "invalid_id",
        [
            "invalid id with spaces!",
            123,
            "a" * 100,  # Pattern max is 64
        ],
    )
    def test_invalid_id_returns_none(self, invalid_id):
        """Test invalid IDs return None."""
        result = sanitize_id(invalid_id)
        assert result is None


# ============================================================================
# Pattern Tests
# ============================================================================


class TestPatterns:
    """Tests for validation regex patterns."""

    @pytest.mark.parametrize(
        "id_str",
        [
            "abc",
            "test_123",
            "my-id",
            "ABC123",
            "a" * 64,
        ],
    )
    def test_safe_id_pattern_valid(self, id_str: str):
        """Test valid IDs match pattern."""
        assert SAFE_ID_PATTERN.match(id_str), f"{id_str} should match"

    @pytest.mark.parametrize(
        "id_str",
        [
            "",
            "a" * 65,
            "has space",
            "special@char",
            "dot.id",
        ],
    )
    def test_safe_id_pattern_invalid(self, id_str: str):
        """Test invalid IDs don't match pattern."""
        assert not SAFE_ID_PATTERN.match(id_str), f"{id_str} should not match"

    @pytest.mark.parametrize(
        "slug",
        [
            "my-article-slug",
            "test_page_123",
            "a" * 128,
        ],
    )
    def test_safe_slug_pattern_valid(self, slug: str):
        """Test valid slugs match pattern."""
        assert SAFE_SLUG_PATTERN.match(slug), f"{slug} should match"

    @pytest.mark.parametrize(
        "agent",
        [
            "claude",
            "gemini-pro",
            "gpt_4",
            "agent123",
            # dotted frontier model ids (#9994)
            "gemini-3.1-pro-preview",
            "claude-fable-5.1",
            "qwen3.8-2.4t-a95b",
        ],
    )
    def test_safe_agent_pattern_valid(self, agent: str):
        """Test valid agent names match pattern."""
        assert SAFE_AGENT_PATTERN.match(agent), f"{agent} should match"

    @pytest.mark.parametrize(
        "agent",
        [
            "anthropic/claude-fable-5.1",  # provider-qualified slug: "/" is a path separator
            "x-ai/grok-4.6",
            ".hidden",  # leading dot
            ".",
            "..",
            "../etc",
            "claude fable",  # whitespace
            "",
        ],
    )
    def test_safe_agent_pattern_rejects_separators_and_leading_dot(self, agent: str):
        """Dots are allowed inside a name, never as a path token; slashes never."""
        assert not SAFE_AGENT_PATTERN.match(agent), f"{agent!r} should not match"

    @pytest.mark.parametrize(
        "agent,expected_match",
        [
            ("a" * 32, True),
            ("a" * 33, False),
        ],
    )
    def test_safe_agent_pattern_max_length(self, agent: str, expected_match: bool):
        """Test agent name max length is 32."""
        assert bool(SAFE_AGENT_PATTERN.match(agent)) is expected_match
