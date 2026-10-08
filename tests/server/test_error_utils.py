"""Tests for error sanitization utilities."""

import importlib
import sys

import pytest

from aragora.api_errors import safe_error_message
from aragora.utils.error_sanitizer import sanitize_error_text


def test_legacy_server_errors_path_warns_and_preserves_identity():
    """The old server path remains a warning compatibility shim."""
    sys.modules.pop("aragora.server.errors", None)
    with pytest.warns(DeprecationWarning, match=r"aragora\.server\.errors"):
        legacy = importlib.import_module("aragora.server.errors")

    assert legacy.safe_error_message is safe_error_message


class TestSanitizeErrorText:
    """Tests for sanitize_error_text function."""

    def test_redacts_openai_api_key(self):
        """Test OpenAI API key patterns are redacted."""
        text = "Error with key sk-TESTKEY123456789012345678901234"
        result = sanitize_error_text(text)
        assert "sk-" not in result
        assert "<REDACTED_KEY>" in result

    def test_redacts_google_api_key(self):
        """Test Google API key patterns are redacted."""
        text = "Error with key AIzaTESTKEYEXAMPLE1234567890123456789AB8"
        result = sanitize_error_text(text)
        assert "AIza" not in result
        assert "<REDACTED_KEY>" in result

    def test_redacts_api_key_assignment(self):
        """Test api_key=value patterns are redacted."""
        text = "Config: api_key=secret123 failed"
        result = sanitize_error_text(text)
        assert "secret123" not in result
        assert "<REDACTED>" in result

    def test_redacts_bearer_token(self):
        """Test authorization Bearer tokens are redacted."""
        text = 'Header: authorization="Bearer eyJ123.xyz"'
        result = sanitize_error_text(text)
        assert "eyJ123" not in result
        assert "<REDACTED>" in result

    def test_redacts_token_assignment(self):
        """Test token=value patterns are redacted."""
        text = 'token="my-secret-token-123"'
        result = sanitize_error_text(text)
        assert "my-secret-token-123" not in result
        assert "<REDACTED>" in result

    def test_redacts_secret_assignment(self):
        """Test secret=value patterns are redacted."""
        text = "Config: secret=my_secret_value"
        result = sanitize_error_text(text)
        assert "my_secret_value" not in result
        assert "<REDACTED>" in result

    def test_redacts_x_api_key_header(self):
        """Test x-api-key header values are redacted."""
        text = "Header: x-api-key: abc123def456"
        result = sanitize_error_text(text)
        assert "abc123def456" not in result
        assert "<REDACTED>" in result

    def test_preserves_non_sensitive_text(self):
        """Test non-sensitive text is preserved."""
        text = "Error 500: Database connection failed"
        result = sanitize_error_text(text)
        assert result == text

    def test_truncates_long_messages(self):
        """Test long messages are truncated."""
        text = "A" * 1000
        result = sanitize_error_text(text, max_length=100)
        assert len(result) < 150
        assert "[truncated]" in result

    def test_default_max_length_is_500(self):
        """Test default truncation at 500 chars."""
        text = "A" * 1000
        result = sanitize_error_text(text)
        assert len(result) < 600
        assert "[truncated]" in result

    def test_handles_empty_string(self):
        """Test empty string input."""
        result = sanitize_error_text("")
        assert result == ""

    def test_case_insensitive_redaction(self):
        """Test redaction is case insensitive."""
        text = "API_KEY=secret123"
        result = sanitize_error_text(text)
        assert "secret123" not in result

    def test_multiple_patterns_in_one_message(self):
        """Test multiple sensitive patterns in one message."""
        text = 'api_key=key1 token="tok123" secret=sec456'
        result = sanitize_error_text(text)
        assert "key1" not in result
        assert "tok123" not in result
        assert "sec456" not in result


class TestSafeErrorMessage:
    """Tests for safe_error_message function."""

    def test_file_not_found_returns_generic(self):
        """Test FileNotFoundError returns generic message."""
        e = FileNotFoundError("/secret/path/to/file.txt")
        result = safe_error_message(e, "test context")
        assert result == "Resource not found"
        assert "/secret" not in result

    def test_os_error_returns_generic(self):
        """Test OSError returns generic message."""
        e = OSError("Permission denied: /etc/passwd")
        result = safe_error_message(e, "test context")
        assert result == "Resource not found"
        assert "/etc" not in result

    def test_value_error_returns_invalid_format(self):
        """Test ValueError returns invalid format message."""
        e = ValueError("Invalid JSON at position 42")
        result = safe_error_message(e, "test context")
        assert result == "Invalid data format"

    def test_permission_error_returns_access_denied(self):
        """Test PermissionError returns access denied."""
        e = PermissionError("Cannot write to /var/log")
        result = safe_error_message(e, "test context")
        assert result == "Access denied"
        assert "/var" not in result

    def test_timeout_error_returns_timeout(self):
        """Test TimeoutError returns timeout message."""
        e = TimeoutError("Connection timed out after 30s")
        result = safe_error_message(e, "test context")
        assert result == "Operation timed out"

    def test_unknown_error_returns_generic(self):
        """Test unknown exceptions return generic message."""
        e = RuntimeError("Internal server details exposed here")
        result = safe_error_message(e, "test context")
        assert result == "An error occurred"
        assert "Internal" not in result

    def test_does_not_leak_exception_details(self):
        """Test that exception message is not in result."""
        secret_path = "/home/user/.ssh/id_rsa"
        e = FileNotFoundError(f"Cannot find {secret_path}")
        result = safe_error_message(e, "test context")
        assert secret_path not in result
        assert ".ssh" not in result

    def test_key_error_returns_generic(self):
        """Test KeyError returns generic message."""
        e = KeyError("secret_config_key")
        result = safe_error_message(e, "test context")
        assert result == "An error occurred"
        assert "secret" not in result


class TestIntegration:
    """Integration tests for error handling."""

    def test_sanitize_then_safe_message(self):
        """Test using both functions together."""
        # Simulate a complex error with sensitive data
        raw_error = "API call failed: api_key=sk-secret123 at /internal/path"
        sanitized = sanitize_error_text(raw_error)

        # Verify intermediate sanitization
        assert "sk-secret" not in sanitized
        assert "/internal/path" in sanitized  # Path preserved by sanitize

        # Create exception with sanitized text
        e = RuntimeError(sanitized)
        safe = safe_error_message(e, "api call")

        # Final message should be generic
        assert safe == "An error occurred"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
