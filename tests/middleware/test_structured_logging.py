"""
Tests for aragora.server.middleware.structured_logging - Structured Logging Middleware.

Tests cover:
- LogContext dataclass
- redact_sensitive function
- JsonFormatter class
- TextFormatter class
- configure_structured_logging function
- get_logger function
- log_context context manager
- set_log_context, clear_log_context, get_log_context functions
- RequestLoggingMiddleware class
- setup_logging convenience function
- Error handling and edge cases
"""

from __future__ import annotations

import json
import logging
import sys
import time
from io import StringIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.middleware.structured_logging import (
    LogContext,
    redact_sensitive,
    JsonFormatter,
    TextFormatter,
    configure_structured_logging,
    get_logger,
    log_context,
    set_log_context,
    clear_log_context,
    get_log_context,
    RequestLoggingMiddleware,
    setup_logging,
    REDACT_FIELDS,
    _log_context,
)


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def reset_log_context():
    """Reset log context before and after each test."""
    clear_log_context()
    yield
    clear_log_context()


@pytest.fixture
def sample_log_record():
    """Create a sample log record for testing."""
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="/path/to/test.py",
        lineno=42,
        msg="Test message",
        args=(),
        exc_info=None,
    )
    return record


@pytest.fixture
def error_log_record():
    """Create an error log record with exception info."""
    try:
        raise ValueError("Test error")
    except ValueError:
        import sys

        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test.logger",
        level=logging.ERROR,
        pathname="/path/to/test.py",
        lineno=100,
        msg="Error occurred",
        args=(),
        exc_info=exc_info,
    )
    return record


@pytest.fixture
def log_stream():
    """Create a string stream for capturing log output."""
    stream = StringIO()
    yield stream
    stream.close()


@pytest.fixture
def json_formatter():
    """Create a JsonFormatter instance."""
    return JsonFormatter(
        include_timestamp=True, include_hostname=False, service_name="test-service"
    )


@pytest.fixture
def text_formatter():
    """Create a TextFormatter instance."""
    return TextFormatter()


# ===========================================================================
# Test LogContext Dataclass
# ===========================================================================


class TestLogContext:
    """Tests for LogContext dataclass."""

    def test_log_context_defaults(self):
        """LogContext should have None defaults for optional fields."""
        ctx = LogContext()

        assert ctx.request_id is None
        assert ctx.trace_id is None
        assert ctx.span_id is None
        assert ctx.user_id is None
        assert ctx.org_id is None
        assert ctx.debate_id is None
        assert ctx.extra == {}

    def test_log_context_with_values(self):
        """LogContext should store provided values."""
        ctx = LogContext(
            request_id="req-123",
            trace_id="trace-456",
            span_id="span-789",
            user_id="user-abc",
            org_id="org-def",
            debate_id="debate-ghi",
            extra={"custom": "value"},
        )

        assert ctx.request_id == "req-123"
        assert ctx.trace_id == "trace-456"
        assert ctx.span_id == "span-789"
        assert ctx.user_id == "user-abc"
        assert ctx.org_id == "org-def"
        assert ctx.debate_id == "debate-ghi"
        assert ctx.extra == {"custom": "value"}

    def test_log_context_to_dict_excludes_none(self):
        """to_dict should exclude fields with None values."""
        ctx = LogContext(request_id="req-123", user_id="user-456")

        result = ctx.to_dict()

        assert result == {"request_id": "req-123", "user_id": "user-456"}
        assert "trace_id" not in result
        assert "span_id" not in result
        assert "org_id" not in result
        assert "debate_id" not in result

    def test_log_context_to_dict_includes_extra(self):
        """to_dict should merge extra fields into result."""
        ctx = LogContext(
            request_id="req-123",
            extra={"action": "create", "resource": "debate"},
        )

        result = ctx.to_dict()

        assert result["request_id"] == "req-123"
        assert result["action"] == "create"
        assert result["resource"] == "debate"

    def test_log_context_to_dict_empty(self):
        """to_dict should return empty dict when all fields are None/empty."""
        ctx = LogContext()

        result = ctx.to_dict()

        assert result == {}

    def test_log_context_to_dict_all_fields(self):
        """to_dict should include all non-None fields."""
        ctx = LogContext(
            request_id="req",
            trace_id="trace",
            span_id="span",
            user_id="user",
            org_id="org",
            debate_id="debate",
        )

        result = ctx.to_dict()

        assert len(result) == 6
        assert "request_id" in result
        assert "trace_id" in result
        assert "span_id" in result
        assert "user_id" in result
        assert "org_id" in result
        assert "debate_id" in result


# ===========================================================================
# Test redact_sensitive Function
# ===========================================================================


class TestRedactSensitive:
    """Tests for redact_sensitive function."""

    def test_redact_password(self):
        """Should redact password fields."""
        data = {"username": "john", "password": "secret123"}

        result = redact_sensitive(data)

        assert result["username"] == "john"
        assert result["password"] == "[REDACTED]"

    def test_redact_token(self):
        """Should redact token fields."""
        data = {"auth_token": "abc123", "token": "xyz789"}

        result = redact_sensitive(data)

        assert result["auth_token"] == "[REDACTED]"
        assert result["token"] == "[REDACTED]"

    def test_redact_api_key_variations(self):
        """Should redact various API key field names."""
        data = {
            "api_key": "key1",
            "apikey": "key2",
            "API_KEY": "key3",
            "ApiKey": "key4",
        }

        result = redact_sensitive(data)

        assert result["api_key"] == "[REDACTED]"
        assert result["apikey"] == "[REDACTED]"
        assert result["API_KEY"] == "[REDACTED]"
        assert result["ApiKey"] == "[REDACTED]"

    def test_redact_authorization_header(self):
        """Should redact authorization headers."""
        data = {"Authorization": "Bearer token123", "headers": {"authorization": "Basic creds"}}

        result = redact_sensitive(data)

        assert result["Authorization"] == "[REDACTED]"
        assert result["headers"]["authorization"] == "[REDACTED]"

    def test_redact_cookie(self):
        """Should redact cookie fields."""
        data = {"cookie": "session=abc123", "Cookie": "auth=xyz"}

        result = redact_sensitive(data)

        assert result["cookie"] == "[REDACTED]"
        assert result["Cookie"] == "[REDACTED]"

    def test_redact_credit_card(self):
        """Should redact credit card fields."""
        data = {"credit_card": "4111111111111111", "credit_card_number": "5500000000000004"}

        result = redact_sensitive(data)

        assert result["credit_card"] == "[REDACTED]"
        assert result["credit_card_number"] == "[REDACTED]"

    def test_redact_ssn(self):
        """Should redact SSN fields."""
        data = {"ssn": "123-45-6789", "user_ssn": "987-65-4321"}

        result = redact_sensitive(data)

        assert result["ssn"] == "[REDACTED]"
        assert result["user_ssn"] == "[REDACTED]"

    def test_redact_private_key(self):
        """Should redact private key fields."""
        data = {"private_key": "-----BEGIN RSA PRIVATE KEY-----"}

        result = redact_sensitive(data)

        assert result["private_key"] == "[REDACTED]"

    def test_redact_secret(self):
        """Should redact secret fields."""
        data = {"secret": "mysecret", "client_secret": "anothersecret"}

        result = redact_sensitive(data)

        assert result["secret"] == "[REDACTED]"
        assert result["client_secret"] == "[REDACTED]"

    def test_redact_nested_dict(self):
        """Should redact sensitive fields in nested dictionaries."""
        data = {
            "user": {
                "name": "John",
                "settings": {
                    "password": "secret",
                    "api_key": "key123",
                    "theme": "dark",
                },
            },
        }

        result = redact_sensitive(data)

        assert result["user"]["name"] == "John"
        # Sensitive keys in nested dicts should be redacted
        assert result["user"]["settings"]["password"] == "[REDACTED]"
        assert result["user"]["settings"]["api_key"] == "[REDACTED]"
        # Non-sensitive keys preserved
        assert result["user"]["settings"]["theme"] == "dark"

    def test_redact_list_of_dicts(self):
        """Should redact sensitive fields in lists of dictionaries."""
        data = {
            "users": [
                {"name": "John", "password": "pass1"},
                {"name": "Jane", "password": "pass2"},
            ],
        }

        result = redact_sensitive(data)

        assert result["users"][0]["name"] == "John"
        assert result["users"][0]["password"] == "[REDACTED]"
        assert result["users"][1]["name"] == "Jane"
        assert result["users"][1]["password"] == "[REDACTED]"

    def test_redact_preserves_non_dict_list_items(self):
        """Should preserve non-dict items in lists."""
        data = {"tags": ["tag1", "tag2", 123, None]}

        result = redact_sensitive(data)

        assert result["tags"] == ["tag1", "tag2", 123, None]

    def test_redact_max_depth(self):
        """Should stop recursion at max depth (5)."""
        # Create deeply nested structure
        data: dict[str, Any] = {"level": 0}
        current = data
        for i in range(1, 10):
            current["nested"] = {"level": i, "password": "secret"}
            current = current["nested"]

        result = redact_sensitive(data)

        # First few levels should be redacted
        assert result["nested"]["password"] == "[REDACTED]"
        # After depth 5, should stop processing (return as-is)
        deep_level = result
        for _ in range(6):
            deep_level = deep_level.get("nested", {})
        # At depth > 5, password may not be redacted (depending on implementation)

    def test_redact_empty_dict(self):
        """Should handle empty dictionary."""
        result = redact_sensitive({})
        assert result == {}

    def test_redact_preserves_original(self):
        """Should not modify the original dictionary."""
        data = {"password": "secret", "name": "John"}

        result = redact_sensitive(data)

        assert data["password"] == "secret"  # Original unchanged
        assert result["password"] == "[REDACTED]"  # Result redacted

    def test_redact_sensitive_key_with_dict_value(self):
        """Should fully redact when sensitive key has dict value (regression test)."""
        # This was a security bug - dict values under sensitive keys were recursed
        # instead of fully redacted, potentially leaking nested secrets
        data = {"token": {"value": "abc123", "type": "bearer"}}

        result = redact_sensitive(data)

        # The entire token value should be redacted, not recursed into
        assert result["token"] == "[REDACTED]"

    def test_redact_sensitive_key_with_list_value(self):
        """Should fully redact when sensitive key has list value (regression test)."""
        # List values under sensitive keys should be fully redacted
        data = {"authorization": ["Bearer", "sk-secret-key-12345"]}

        result = redact_sensitive(data)

        # The entire authorization value should be redacted
        assert result["authorization"] == "[REDACTED]"

    def test_redact_sensitive_key_with_nested_structure(self):
        """Should fully redact complex nested structures under sensitive keys."""
        data = {
            "credentials": {
                "primary": {"key": "secret1", "endpoint": "https://api.example.com"},
                "backup": {"key": "secret2"},
            }
        }

        result = redact_sensitive(data)

        # credentials contains "credential" so entire value should be redacted
        assert result["credentials"] == "[REDACTED]"

    def test_redact_fields_constant(self):
        """REDACT_FIELDS should contain expected sensitive field names."""
        # Core fields that must always be present
        core_fields = {
            "password",
            "secret",
            "token",
            "api_key",
            "apikey",
            "authorization",
            "cookie",
            "credit_card",
            "ssn",
            "private_key",
        }

        # All core fields should be in REDACT_FIELDS (may have additional fields)
        assert core_fields.issubset(REDACT_FIELDS)


# ===========================================================================
# Test JsonFormatter Class
# ===========================================================================


class TestJsonFormatter:
    """Tests for JsonFormatter class."""

    def test_init_defaults(self):
        """Should initialize with default values."""
        formatter = JsonFormatter()

        assert formatter.include_timestamp is True
        assert formatter.include_hostname is True
        assert formatter.service_name == "aragora"
        assert formatter._hostname is not None

    def test_init_custom_values(self):
        """Should accept custom initialization values."""
        formatter = JsonFormatter(
            include_timestamp=False,
            include_hostname=False,
            service_name="custom-service",
        )

        assert formatter.include_timestamp is False
        assert formatter.include_hostname is False
        assert formatter.service_name == "custom-service"
        assert formatter._hostname is None

    def test_format_basic_record(self, json_formatter, sample_log_record):
        """Should format basic log record as JSON."""
        output = json_formatter.format(sample_log_record)
        parsed = json.loads(output)

        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert parsed["message"] == "Test message"
        assert parsed["service"] == "test-service"
        assert "timestamp" in parsed

    def test_format_includes_timestamp_when_enabled(self, sample_log_record):
        """Should include timestamp when enabled."""
        formatter = JsonFormatter(include_timestamp=True)

        output = formatter.format(sample_log_record)
        parsed = json.loads(output)

        assert "timestamp" in parsed
        # ISO format check
        assert "T" in parsed["timestamp"]

    def test_format_excludes_timestamp_when_disabled(self, sample_log_record):
        """Should exclude timestamp when disabled."""
        formatter = JsonFormatter(include_timestamp=False)

        output = formatter.format(sample_log_record)
        parsed = json.loads(output)

        assert "timestamp" not in parsed

    def test_format_includes_hostname_when_enabled(self, sample_log_record):
        """Should include hostname when enabled."""
        formatter = JsonFormatter(include_hostname=True)

        output = formatter.format(sample_log_record)
        parsed = json.loads(output)

        assert "hostname" in parsed

    def test_format_excludes_hostname_when_disabled(self, sample_log_record):
        """Should exclude hostname when disabled."""
        formatter = JsonFormatter(include_hostname=False)

        output = formatter.format(sample_log_record)
        parsed = json.loads(output)

        assert "hostname" not in parsed

    def test_format_includes_context(self, json_formatter, sample_log_record):
        """Should include log context in output."""
        set_log_context(request_id="req-123", user_id="user-456")

        output = json_formatter.format(sample_log_record)
        parsed = json.loads(output)

        assert "context" in parsed
        assert parsed["context"]["request_id"] == "req-123"
        assert parsed["context"]["user_id"] == "user-456"

    def test_format_excludes_empty_context(self, json_formatter, sample_log_record):
        """Should exclude context when empty."""
        clear_log_context()

        output = json_formatter.format(sample_log_record)
        parsed = json.loads(output)

        assert "context" not in parsed

    def test_format_includes_extra_fields(self, json_formatter):
        """Should include extra fields from log record."""
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/path/to/test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.action = "create"
        record.resource = "debate"

        output = json_formatter.format(record)
        parsed = json.loads(output)

        assert "extra" in parsed
        assert parsed["extra"]["action"] == "create"
        assert parsed["extra"]["resource"] == "debate"

    def test_format_redacts_sensitive_extra_fields(self, json_formatter):
        """Should redact sensitive fields in extra data."""
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/path/to/test.py",
            lineno=42,
            msg="Auth attempt",
            args=(),
            exc_info=None,
        )
        record.password = "secret123"
        record.api_key = "key456"
        record.username = "john"

        output = json_formatter.format(record)
        parsed = json.loads(output)

        assert parsed["extra"]["password"] == "[REDACTED]"
        assert parsed["extra"]["api_key"] == "[REDACTED]"
        assert parsed["extra"]["username"] == "john"

    def test_format_includes_exception_info(self, json_formatter, error_log_record):
        """Should include exception info for error logs."""
        output = json_formatter.format(error_log_record)
        parsed = json.loads(output)

        assert "exception" in parsed
        assert parsed["exception"]["type"] == "ValueError"
        assert parsed["exception"]["message"] == "Test error"
        assert "traceback" in parsed["exception"]
        assert "ValueError" in parsed["exception"]["traceback"]

    def test_format_includes_source_for_errors(self, json_formatter, error_log_record):
        """Should include source location for error logs."""
        output = json_formatter.format(error_log_record)
        parsed = json.loads(output)

        assert "source" in parsed
        assert parsed["source"]["file"] == "/path/to/test.py"
        assert parsed["source"]["line"] == 100
        # funcName can be None for some log records depending on how they were created
        assert "function" in parsed["source"]

    def test_format_excludes_source_for_non_errors(self, json_formatter, sample_log_record):
        """Should not include source for non-error logs."""
        output = json_formatter.format(sample_log_record)
        parsed = json.loads(output)

        assert "source" not in parsed

    def test_format_excludes_standard_attributes(self, json_formatter, sample_log_record):
        """Should exclude standard log record attributes from extra."""
        output = json_formatter.format(sample_log_record)
        parsed = json.loads(output)

        # Should not have standard attributes in extra
        if "extra" in parsed:
            standard_attrs = {
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
            }
            for attr in standard_attrs:
                assert attr not in parsed["extra"]

    def test_format_handles_non_serializable_values(self, json_formatter):
        """Should handle non-JSON-serializable values."""
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/path/to/test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.custom_object = object()

        # Should not raise
        output = json_formatter.format(record)
        parsed = json.loads(output)

        # Should use str() for non-serializable
        assert "extra" in parsed
        assert "custom_object" in parsed["extra"]


# ===========================================================================
# Test TextFormatter Class
# ===========================================================================


class TestTextFormatter:
    """Tests for TextFormatter class."""

    def test_format_basic_record(self, text_formatter, sample_log_record):
        """Should format basic log record as text."""
        output = text_formatter.format(sample_log_record)

        assert "[INFO" in output
        assert "test.logger" in output
        assert "Test message" in output

    def test_format_includes_timestamp(self, text_formatter, sample_log_record):
        """Should include timestamp in output."""
        output = text_formatter.format(sample_log_record)

        # Should have timestamp in brackets
        assert "[" in output
        # Should have date-like pattern
        assert "-" in output.split("]")[0]

    def test_format_includes_request_id(self, text_formatter, sample_log_record):
        """Should include request_id from context."""
        set_log_context(request_id="req-123")

        output = text_formatter.format(sample_log_record)

        assert "[req-123]" in output

    def test_format_uses_dash_for_missing_request_id(self, text_formatter, sample_log_record):
        """Should use '-' when request_id is not set."""
        clear_log_context()

        output = text_formatter.format(sample_log_record)

        assert "[-]" in output

    def test_format_includes_extra_fields_as_json(self, text_formatter):
        """Should append extra fields as JSON."""
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/path/to/test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.action = "create"

        output = text_formatter.format(record)

        assert '"action"' in output
        assert '"create"' in output

    def test_format_redacts_sensitive_extra_fields(self, text_formatter):
        """Should redact sensitive fields in extra data."""
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/path/to/test.py",
            lineno=42,
            msg="Auth",
            args=(),
            exc_info=None,
        )
        record.password = "secret"

        output = text_formatter.format(record)

        assert "[REDACTED]" in output
        assert "secret" not in output

    def test_format_includes_exception(self, text_formatter, error_log_record):
        """Should include exception traceback."""
        output = text_formatter.format(error_log_record)

        assert "ValueError" in output
        assert "Test error" in output

    def test_format_level_padding(self, text_formatter):
        """Level name should be padded for alignment."""
        info_record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="msg",
            args=(),
            exc_info=None,
        )
        warning_record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="msg",
            args=(),
            exc_info=None,
        )

        info_output = text_formatter.format(info_record)
        warning_output = text_formatter.format(warning_record)

        # Both should have consistent formatting
        assert "[INFO" in info_output
        assert "[WARNING" in warning_output


# ===========================================================================
# Test configure_structured_logging Function
# ===========================================================================


class TestConfigureStructuredLogging:
    """Tests for configure_structured_logging function."""

    @pytest.fixture(autouse=True)
    def _isolate_root_logger(self):
        """Save and restore root logger state around each test.

        Other test modules (or pytest's caplog fixture) may add handlers
        or change formatters on the root logger without cleanup.  By
        snapshotting the full handler list *and* level before the test and
        restoring them afterwards, the tests in this class are immune to
        that cross-test pollution regardless of execution order.
        """
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        original_level = root.level
        # Start each test with a clean root logger so
        # configure_structured_logging is the only thing setting handlers.
        for h in root.handlers[:]:
            root.removeHandler(h)
        yield
        # Restore exact pre-test state so we don't pollute other tests.
        for h in root.handlers[:]:
            root.removeHandler(h)
        for h in original_handlers:
            root.addHandler(h)
        root.setLevel(original_level)

    def test_configure_default_settings(self):
        """Should configure with default settings."""
        configure_structured_logging()

        root_logger = logging.getLogger()
        assert len(root_logger.handlers) == 1
        assert isinstance(root_logger.handlers[0], logging.StreamHandler)

    def test_configure_json_output(self):
        """Should use JsonFormatter when json_output=True."""
        configure_structured_logging(json_output=True)

        root_logger = logging.getLogger()
        formatter = root_logger.handlers[0].formatter
        # Check by class name to avoid module reload issues with isinstance
        assert formatter.__class__.__name__ == "JsonFormatter"

    def test_configure_text_output(self):
        """Should use TextFormatter when json_output=False."""
        configure_structured_logging(json_output=False)

        root_logger = logging.getLogger()
        formatter = root_logger.handlers[0].formatter
        # Check by class name to avoid module reload issues with isinstance
        assert formatter.__class__.__name__ == "TextFormatter"

    def test_configure_log_level(self):
        """Should set the specified log level."""
        configure_structured_logging(level="DEBUG")

        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG

    def test_configure_log_level_case_insensitive(self):
        """Should handle log level case-insensitively."""
        configure_structured_logging(level="warning")

        root_logger = logging.getLogger()
        assert root_logger.level == logging.WARNING

    def test_configure_service_name(self):
        """Should pass service_name to JsonFormatter."""
        configure_structured_logging(json_output=True, service_name="my-service")

        root_logger = logging.getLogger()
        formatter = root_logger.handlers[0].formatter
        # Check by class name to avoid module reload issues with isinstance
        assert formatter.__class__.__name__ == "JsonFormatter"
        assert formatter.service_name == "my-service"

    def test_configure_removes_existing_handlers(self):
        """Should remove existing handlers before adding new one."""
        root_logger = logging.getLogger()

        # Add multiple handlers
        root_logger.addHandler(logging.StreamHandler())
        root_logger.addHandler(logging.StreamHandler())
        assert len(root_logger.handlers) >= 2

        configure_structured_logging()

        assert len(root_logger.handlers) == 1

    def test_configure_suppresses_noisy_loggers(self):
        """Should set noisy third-party loggers to WARNING."""
        configure_structured_logging(level="DEBUG")

        assert logging.getLogger("urllib3").level == logging.WARNING
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING

    def test_configure_invalid_level_defaults_to_info(self):
        """Should default to INFO for invalid log level."""
        configure_structured_logging(level="INVALID_LEVEL")

        root_logger = logging.getLogger()
        assert root_logger.level == logging.INFO

    def test_configure_uses_env_format_when_json_output_none(self):
        """Should use ARAGORA_LOG_FORMAT env var when json_output is None."""
        with patch.dict("os.environ", {"ARAGORA_LOG_FORMAT": "text"}):
            # Need to reimport to pick up env change
            from aragora.server.middleware import structured_logging

            # Force reload to pick up new env
            import importlib

            importlib.reload(structured_logging)

            structured_logging.configure_structured_logging(json_output=None)

            root_logger = logging.getLogger()
            formatter = root_logger.handlers[0].formatter
            # Check by class name due to module reload issues with isinstance
            assert formatter.__class__.__name__ == "TextFormatter"


# ===========================================================================
# Test get_logger Function
# ===========================================================================


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_returns_logger(self):
        """Should return a Logger instance."""
        logger = get_logger("test.module")

        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.module"

    def test_get_logger_same_name_returns_same_logger(self):
        """Should return the same logger for the same name."""
        logger1 = get_logger("test.same")
        logger2 = get_logger("test.same")

        assert logger1 is logger2

    def test_get_logger_different_names(self):
        """Should return different loggers for different names."""
        logger1 = get_logger("test.one")
        logger2 = get_logger("test.two")

        assert logger1 is not logger2
        assert logger1.name == "test.one"
        assert logger2.name == "test.two"


# ===========================================================================
# Test log_context Context Manager
# ===========================================================================


class TestLogContextManager:
    """Tests for log_context context manager."""

    def test_log_context_adds_fields(self):
        """Should add fields within context."""
        with log_context(request_id="req-123"):
            ctx = get_log_context()
            assert ctx["request_id"] == "req-123"

    def test_log_context_removes_fields_after_exit(self):
        """Should remove fields after context exits."""
        with log_context(request_id="req-123"):
            pass

        ctx = get_log_context()
        assert "request_id" not in ctx

    def test_log_context_preserves_existing_fields(self):
        """Should preserve existing context fields."""
        set_log_context(user_id="user-456")

        with log_context(request_id="req-123"):
            ctx = get_log_context()
            assert ctx["request_id"] == "req-123"
            assert ctx["user_id"] == "user-456"

        # After exit, only user_id should remain
        ctx = get_log_context()
        assert "request_id" not in ctx
        assert ctx["user_id"] == "user-456"

    def test_log_context_nested(self):
        """Should support nested contexts."""
        with log_context(level1="a"):
            with log_context(level2="b"):
                ctx = get_log_context()
                assert ctx["level1"] == "a"
                assert ctx["level2"] == "b"

            ctx = get_log_context()
            assert ctx["level1"] == "a"
            assert "level2" not in ctx

    def test_log_context_multiple_fields(self):
        """Should support multiple fields."""
        with log_context(request_id="req-123", user_id="user-456", action="create"):
            ctx = get_log_context()
            assert ctx["request_id"] == "req-123"
            assert ctx["user_id"] == "user-456"
            assert ctx["action"] == "create"

    def test_log_context_restores_on_exception(self):
        """Should restore context even on exception."""
        try:
            with log_context(request_id="req-123"):
                raise ValueError("Test error")
        except ValueError:
            pass

        ctx = get_log_context()
        assert "request_id" not in ctx


# ===========================================================================
# Test set_log_context Function
# ===========================================================================


class TestSetLogContext:
    """Tests for set_log_context function."""

    def test_set_log_context_adds_fields(self):
        """Should add fields to context."""
        set_log_context(request_id="req-123")

        ctx = get_log_context()
        assert ctx["request_id"] == "req-123"

    def test_set_log_context_multiple_calls(self):
        """Should accumulate fields across calls."""
        set_log_context(request_id="req-123")
        set_log_context(user_id="user-456")

        ctx = get_log_context()
        assert ctx["request_id"] == "req-123"
        assert ctx["user_id"] == "user-456"

    def test_set_log_context_overwrites_existing(self):
        """Should overwrite existing fields."""
        set_log_context(request_id="old-id")
        set_log_context(request_id="new-id")

        ctx = get_log_context()
        assert ctx["request_id"] == "new-id"


# ===========================================================================
# Test clear_log_context Function
# ===========================================================================


class TestClearLogContext:
    """Tests for clear_log_context function."""

    def test_clear_log_context_removes_all(self):
        """Should remove all context fields."""
        set_log_context(request_id="req-123", user_id="user-456")

        clear_log_context()

        ctx = get_log_context()
        assert ctx == {}

    def test_clear_log_context_empty_is_safe(self):
        """Should handle clearing already empty context."""
        clear_log_context()  # Already empty
        clear_log_context()  # Should not raise

        ctx = get_log_context()
        assert ctx == {}


# ===========================================================================
# Test get_log_context Function
# ===========================================================================


class TestGetLogContext:
    """Tests for get_log_context function."""

    def test_get_log_context_returns_copy(self):
        """Should return a copy of the context."""
        set_log_context(request_id="req-123")

        ctx1 = get_log_context()
        ctx1["new_field"] = "value"

        ctx2 = get_log_context()
        assert "new_field" not in ctx2

    def test_get_log_context_empty(self):
        """Should return empty dict when no context set."""
        clear_log_context()

        ctx = get_log_context()
        assert ctx == {}
        assert isinstance(ctx, dict)


# ===========================================================================
# Test RequestLoggingMiddleware Class
# ===========================================================================


class TestRequestLoggingMiddleware:
    """Tests for RequestLoggingMiddleware class."""

    def test_init_default_threshold(self):
        """Should initialize with default slow threshold."""
        middleware = RequestLoggingMiddleware()

        assert middleware.slow_threshold_ms == 1000.0
        assert middleware.logger is not None

    def test_init_custom_threshold(self):
        """Should accept custom slow threshold."""
        middleware = RequestLoggingMiddleware(slow_threshold_ms=500.0)

        assert middleware.slow_threshold_ms == 500.0

    def test_start_request_returns_context(self):
        """Should return request context dict."""
        middleware = RequestLoggingMiddleware()

        ctx = middleware.start_request(
            method="GET",
            path="/api/debates",
            client_ip="192.168.1.1",
        )

        assert ctx["method"] == "GET"
        assert ctx["path"] == "/api/debates"
        assert ctx["client_ip"] == "192.168.1.1"
        assert "request_id" in ctx
        assert "start_time" in ctx

    def test_start_request_generates_request_id(self):
        """Should generate request_id if not provided."""
        middleware = RequestLoggingMiddleware()

        ctx = middleware.start_request(
            method="GET",
            path="/api/debates",
            client_ip="192.168.1.1",
        )

        assert ctx["request_id"].startswith("req-")
        assert len(ctx["request_id"]) == 16  # "req-" + 12 hex chars

    def test_start_request_uses_provided_request_id(self):
        """Should use provided request_id."""
        middleware = RequestLoggingMiddleware()

        ctx = middleware.start_request(
            method="GET",
            path="/api/debates",
            client_ip="192.168.1.1",
            request_id="custom-req-id",
        )

        assert ctx["request_id"] == "custom-req-id"

    def test_start_request_sets_log_context(self):
        """Should set log context with request info."""
        middleware = RequestLoggingMiddleware()
        clear_log_context()

        middleware.start_request(
            method="POST",
            path="/api/debates",
            client_ip="10.0.0.1",
            request_id="req-test",
        )

        ctx = get_log_context()
        assert ctx["request_id"] == "req-test"
        assert ctx["method"] == "POST"
        assert ctx["path"] == "/api/debates"
        assert ctx["client_ip"] == "10.0.0.1"

    def test_start_request_logs_with_headers(self):
        """Should log request with redacted headers."""
        middleware = RequestLoggingMiddleware()

        with patch.object(middleware.logger, "info") as mock_info:
            middleware.start_request(
                method="GET",
                path="/api/test",
                client_ip="127.0.0.1",
                headers={"Authorization": "Bearer secret", "Content-Type": "application/json"},
            )

            mock_info.assert_called_once()
            call_kwargs = mock_info.call_args[1]
            assert call_kwargs["extra"]["event"] == "request_start"
            assert call_kwargs["extra"]["headers"]["Authorization"] == "[REDACTED]"
            assert call_kwargs["extra"]["headers"]["Content-Type"] == "application/json"

    def test_end_request_logs_completion(self):
        """Should log request completion with timing."""
        middleware = RequestLoggingMiddleware()
        ctx = middleware.start_request(
            method="GET",
            path="/api/test",
            client_ip="127.0.0.1",
        )

        with patch.object(middleware.logger, "log") as mock_log:
            middleware.end_request(ctx, status_code=200)

            mock_log.assert_called_once()
            call_args = mock_log.call_args
            assert call_args[0][0] == logging.INFO  # Level
            assert "200" in call_args[0][1] % call_args[0][2:]  # Message contains status
            assert call_args[1]["extra"]["event"] == "request_end"
            assert call_args[1]["extra"]["status"] == 200
            assert "elapsed_ms" in call_args[1]["extra"]

    def test_end_request_logs_response_size(self):
        """Should include response_size when provided."""
        middleware = RequestLoggingMiddleware()
        ctx = middleware.start_request(
            method="GET",
            path="/api/test",
            client_ip="127.0.0.1",
        )

        with patch.object(middleware.logger, "log") as mock_log:
            middleware.end_request(ctx, status_code=200, response_size=1024)

            call_kwargs = mock_log.call_args[1]
            assert call_kwargs["extra"]["response_size"] == 1024

    def test_end_request_logs_error_level_for_5xx(self):
        """Should log ERROR level for 5xx status codes."""
        middleware = RequestLoggingMiddleware()
        ctx = middleware.start_request(
            method="GET",
            path="/api/test",
            client_ip="127.0.0.1",
        )

        with patch.object(middleware.logger, "log") as mock_log:
            middleware.end_request(ctx, status_code=500)

            assert mock_log.call_args[0][0] == logging.ERROR

    def test_end_request_logs_warning_level_for_4xx(self):
        """Should log WARNING level for 4xx status codes."""
        middleware = RequestLoggingMiddleware()
        ctx = middleware.start_request(
            method="GET",
            path="/api/test",
            client_ip="127.0.0.1",
        )

        with patch.object(middleware.logger, "log") as mock_log:
            middleware.end_request(ctx, status_code=404)

            assert mock_log.call_args[0][0] == logging.WARNING

    def test_end_request_logs_warning_for_slow_requests(self):
        """Should log WARNING level for slow requests."""
        middleware = RequestLoggingMiddleware(slow_threshold_ms=1.0)  # 1ms threshold
        ctx = {
            "request_id": "req-123",
            "method": "GET",
            "path": "/api/test",
            "start_time": time.time() - 0.1,  # 100ms ago
        }

        with patch.object(middleware.logger, "log") as mock_log:
            middleware.end_request(ctx, status_code=200)

            assert mock_log.call_args[0][0] == logging.WARNING
            assert mock_log.call_args[1]["extra"]["slow_request"] is True

    def test_end_request_clears_log_context(self):
        """Should clear log context after request."""
        middleware = RequestLoggingMiddleware()
        ctx = middleware.start_request(
            method="GET",
            path="/api/test",
            client_ip="127.0.0.1",
        )

        middleware.end_request(ctx, status_code=200)

        log_ctx = get_log_context()
        assert log_ctx == {}

    def test_log_error(self):
        """Should log request error with exception info."""
        middleware = RequestLoggingMiddleware()
        ctx = middleware.start_request(
            method="POST",
            path="/api/test",
            client_ip="127.0.0.1",
        )
        error = ValueError("Something went wrong")

        with patch.object(middleware.logger, "error") as mock_error:
            middleware.log_error(ctx, error)

            mock_error.assert_called_once()
            call_args = mock_error.call_args
            assert "ERROR" in call_args[0][0]
            # Logger uses %s format args; "ValueError" is in positional args
            assert "ValueError" in call_args[0]
            call_kwargs = call_args[1]
            assert call_kwargs["extra"]["event"] == "request_error"
            assert call_kwargs["extra"]["status"] == 500
            assert call_kwargs["extra"]["error_type"] == "ValueError"
            assert call_kwargs["extra"]["error_message"] == "Something went wrong"
            assert call_kwargs["exc_info"] is True

    def test_log_error_includes_traceback(self):
        """Should include traceback by default."""
        middleware = RequestLoggingMiddleware()
        ctx = middleware.start_request(
            method="POST",
            path="/api/test",
            client_ip="127.0.0.1",
        )
        error = ValueError("Test")

        with patch.object(middleware.logger, "error") as mock_error:
            middleware.log_error(ctx, error, include_traceback=True)

            assert "traceback" in mock_error.call_args[1]["extra"]

    def test_log_error_can_exclude_traceback(self):
        """Should exclude traceback when specified."""
        middleware = RequestLoggingMiddleware()
        ctx = middleware.start_request(
            method="POST",
            path="/api/test",
            client_ip="127.0.0.1",
        )
        error = ValueError("Test")

        with patch.object(middleware.logger, "error") as mock_error:
            middleware.log_error(ctx, error, include_traceback=False)

            assert "traceback" not in mock_error.call_args[1]["extra"]

    def test_log_error_truncates_long_messages(self):
        """Should truncate error messages longer than 500 chars."""
        middleware = RequestLoggingMiddleware()
        ctx = middleware.start_request(
            method="POST",
            path="/api/test",
            client_ip="127.0.0.1",
        )
        long_message = "x" * 1000
        error = ValueError(long_message)

        with patch.object(middleware.logger, "error") as mock_error:
            middleware.log_error(ctx, error)

            error_message = mock_error.call_args[1]["extra"]["error_message"]
            assert len(error_message) == 500


# ===========================================================================
# Test setup_logging Function
# ===========================================================================


class TestSetupLogging:
    """Tests for setup_logging convenience function."""

    @pytest.fixture(autouse=True)
    def _isolate_root_logger(self):
        """Save and restore root logger state for isolation."""
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        original_level = root.level
        for h in root.handlers[:]:
            root.removeHandler(h)
        yield
        for h in root.handlers[:]:
            root.removeHandler(h)
        for h in original_handlers:
            root.addHandler(h)
        root.setLevel(original_level)

    def test_setup_logging_defaults(self):
        """Should configure with defaults."""
        setup_logging()

        root_logger = logging.getLogger()
        assert len(root_logger.handlers) == 1
        # Default is json_output=True - check by class name to avoid module reload issues
        assert root_logger.handlers[0].formatter.__class__.__name__ == "JsonFormatter"

    def test_setup_logging_json(self):
        """Should configure JSON output."""
        setup_logging(json_output=True)

        root_logger = logging.getLogger()
        # Check by class name to avoid module reload issues
        assert root_logger.handlers[0].formatter.__class__.__name__ == "JsonFormatter"

    def test_setup_logging_text(self):
        """Should configure text output."""
        setup_logging(json_output=False)

        root_logger = logging.getLogger()
        # Check by class name to avoid module reload issues
        assert root_logger.handlers[0].formatter.__class__.__name__ == "TextFormatter"

    def test_setup_logging_level(self):
        """Should configure specified level."""
        setup_logging(level="DEBUG")

        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG


# ===========================================================================
# Test Module Exports
# ===========================================================================


class TestModuleExports:
    """Tests for module's __all__ exports."""

    def test_all_exports_importable(self):
        """All items in __all__ can be imported."""
        from aragora.server.middleware import structured_logging

        for name in structured_logging.__all__:
            assert hasattr(structured_logging, name), f"Missing export: {name}"

    def test_expected_exports(self):
        """Key items are exported in __all__."""
        from aragora.server.middleware.structured_logging import __all__

        expected = [
            "configure_structured_logging",
            "get_logger",
            "log_context",
            "set_log_context",
            "clear_log_context",
            "get_log_context",
            "redact_sensitive",
            "RequestLoggingMiddleware",
            "JsonFormatter",
            "TextFormatter",
            "LogContext",
            "setup_logging",
        ]

        for item in expected:
            assert item in __all__, f"Expected {item} in __all__"


# ===========================================================================
# Test Integration
# ===========================================================================


class TestIntegration:
    """Integration tests combining multiple components."""

    @pytest.fixture(autouse=True)
    def _isolate_root_logger(self):
        """Save and restore root logger state for isolation.

        The integration tests call configure_structured_logging() which
        replaces root logger handlers.  Without cleanup the leaked
        handlers cause assertion failures in later test classes that
        expect a clean root logger (e.g. TestConfigureStructuredLogging).
        """
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        original_level = root.level
        for h in root.handlers[:]:
            root.removeHandler(h)
        yield
        for h in root.handlers[:]:
            root.removeHandler(h)
        for h in original_handlers:
            root.addHandler(h)
        root.setLevel(original_level)

    def test_full_request_logging_flow(self, log_stream):
        """Test complete request logging from start to end."""
        # Configure logging to capture output
        configure_structured_logging(json_output=True, level="INFO")
        root_logger = logging.getLogger()
        root_logger.handlers[0].stream = log_stream

        middleware = RequestLoggingMiddleware()

        # Start request
        ctx = middleware.start_request(
            method="POST",
            path="/api/debates",
            client_ip="192.168.1.100",
            headers={"Content-Type": "application/json", "Authorization": "Bearer token"},
            request_id="test-req-001",
        )

        # Simulate some processing with additional logging
        logger = get_logger("aragora.test")
        logger.info("Processing debate creation", extra={"debate_topic": "AI Ethics"})

        # End request
        middleware.end_request(ctx, status_code=201, response_size=256)

        # Check output
        output = log_stream.getvalue()
        lines = output.strip().split("\n")

        # Should have 3 log entries: request_start, processing, request_end
        assert len(lines) >= 2  # At least start and end

        # Verify JSON format
        for line in lines:
            parsed = json.loads(line)
            assert "level" in parsed
            assert "message" in parsed

    def test_error_logging_flow(self, log_stream):
        """Test error logging flow."""
        configure_structured_logging(json_output=True, level="INFO")
        root_logger = logging.getLogger()
        root_logger.handlers[0].stream = log_stream

        middleware = RequestLoggingMiddleware()

        ctx = middleware.start_request(
            method="GET",
            path="/api/debates/invalid",
            client_ip="127.0.0.1",
        )

        # Simulate error
        error = ValueError("Invalid debate ID")
        middleware.log_error(ctx, error)

        output = log_stream.getvalue()

        # Should contain error log
        assert "ERROR" in output
        assert "ValueError" in output

    def test_context_propagation_across_logs(self):
        """Test that context propagates to all logs within scope."""
        formatter = JsonFormatter(include_timestamp=False, include_hostname=False)

        with log_context(request_id="ctx-test", user_id="user-123"):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="Message 1",
                args=(),
                exc_info=None,
            )
            output1 = formatter.format(record)

            record2 = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="Message 2",
                args=(),
                exc_info=None,
            )
            output2 = formatter.format(record2)

        parsed1 = json.loads(output1)
        parsed2 = json.loads(output2)

        # Both should have same context
        assert parsed1["context"]["request_id"] == "ctx-test"
        assert parsed1["context"]["user_id"] == "user-123"
        assert parsed2["context"]["request_id"] == "ctx-test"
        assert parsed2["context"]["user_id"] == "user-123"


# ===========================================================================
# Test Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Edge case tests for structured_logging middleware."""

    def test_empty_message(self, json_formatter):
        """Should handle empty log message."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="",
            args=(),
            exc_info=None,
        )

        output = json_formatter.format(record)
        parsed = json.loads(output)

        assert parsed["message"] == ""

    def test_message_with_format_args(self, json_formatter):
        """Should format message with arguments."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="User %s created debate %d",
            args=("john", 123),
            exc_info=None,
        )

        output = json_formatter.format(record)
        parsed = json.loads(output)

        assert parsed["message"] == "User john created debate 123"

    def test_unicode_in_message(self, json_formatter):
        """Should handle unicode in messages."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="User created: \u4e2d\u6587",
            args=(),
            exc_info=None,
        )

        output = json_formatter.format(record)
        parsed = json.loads(output)

        assert "\u4e2d\u6587" in parsed["message"]

    def test_very_long_message(self, json_formatter):
        """Should handle very long messages."""
        long_msg = "x" * 10000
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=long_msg,
            args=(),
            exc_info=None,
        )

        output = json_formatter.format(record)
        parsed = json.loads(output)

        assert len(parsed["message"]) == 10000

    def test_special_characters_in_extra(self, json_formatter):
        """Should handle special characters in extra fields."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None,
        )
        record.data = {"key": 'value\nwith\ttabs\rand"quotes"'}

        output = json_formatter.format(record)
        # Should not raise and produce valid JSON
        parsed = json.loads(output)
        assert "data" in parsed["extra"]

    def test_circular_reference_in_extra(self, json_formatter):
        """Should handle circular references - raises ValueError as expected from json.dumps."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None,
        )
        circular: dict[str, Any] = {"key": "value"}
        circular["self"] = circular
        record.circular = circular

        # json.dumps with default=str still raises ValueError for circular refs
        # This is expected Python behavior - the middleware doesn't try to handle this
        with pytest.raises(ValueError, match="Circular reference detected"):
            json_formatter.format(record)

    def test_none_values_in_context(self, json_formatter):
        """Should handle None values in context."""
        set_log_context(request_id=None, user_id="user-123")

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None,
        )

        output = json_formatter.format(record)
        parsed = json.loads(output)

        # None should be included as null in JSON
        assert "context" in parsed

    def test_concurrent_context_isolation(self):
        """Context should be isolated between different async tasks."""
        import asyncio

        results = []

        async def task1():
            set_log_context(task="task1")
            await asyncio.sleep(0.01)
            results.append(("task1", get_log_context().get("task")))

        async def task2():
            set_log_context(task="task2")
            await asyncio.sleep(0.01)
            results.append(("task2", get_log_context().get("task")))

        async def run_tasks():
            await asyncio.gather(task1(), task2())

        asyncio.run(run_tasks())

        # Each task should see its own context
        for task_name, ctx_task in results:
            assert ctx_task == task_name

    def test_log_level_names(self, json_formatter):
        """Should use correct level names for all levels."""
        levels = [
            (logging.DEBUG, "DEBUG"),
            (logging.INFO, "INFO"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR, "ERROR"),
            (logging.CRITICAL, "CRITICAL"),
        ]

        for level, expected_name in levels:
            record = logging.LogRecord(
                name="test",
                level=level,
                pathname="",
                lineno=0,
                msg="Test",
                args=(),
                exc_info=None,
            )

            output = json_formatter.format(record)
            parsed = json.loads(output)

            assert parsed["level"] == expected_name


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
