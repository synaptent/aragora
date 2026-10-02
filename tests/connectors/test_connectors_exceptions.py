"""
Tests for connector exception hierarchy.

Tests cover all exception types, their attributes, retryability,
and utility functions for error handling.
"""

import pytest

from aragora.connectors.exceptions import (
    ConnectorError,
    ConnectorAuthError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
    ConnectorNetworkError,
    ConnectorAPIError,
    ConnectorValidationError,
    ConnectorNotFoundError,
    ConnectorQuotaError,
    ConnectorParseError,
    is_retryable_error,
    get_retry_delay,
)


class TestConnectorError:
    """Tests for base ConnectorError."""

    def test_basic_creation(self):
        """ConnectorError should store message; str() appends the details dict."""
        error = ConnectorError("Something went wrong")
        assert error.message == "Something went wrong"
        assert str(error).startswith("Something went wrong (")
        assert "details={'connector_name': 'unknown', 'is_retryable': False}" in str(error)
        assert error.connector_name == "unknown"
        assert error.retry_after is None
        assert error.is_retryable is False

    def test_with_connector_name(self):
        """ConnectorError should include connector name in str."""
        error = ConnectorError("Failed", connector_name="github")
        assert "[github]" in str(error)
        assert "Failed" in str(error)
        assert error.connector_name == "github"

    def test_with_retry_after(self):
        """ConnectorError should store retry_after."""
        error = ConnectorError("Wait", retry_after=30.0)
        assert error.retry_after == 30.0

    def test_is_retryable_flag(self):
        """ConnectorError should store is_retryable."""
        error = ConnectorError("Retry me", is_retryable=True)
        assert error.is_retryable is True


class TestConnectorAuthError:
    """Tests for authentication errors."""

    def test_auth_error_not_retryable(self):
        """Auth errors should not be retryable."""
        error = ConnectorAuthError("Invalid API key", connector_name="twitter")
        assert error.is_retryable is False
        assert "[twitter]" in str(error)

    def test_auth_error_with_retry_after(self):
        """Auth errors can have retry_after for token refresh."""
        error = ConnectorAuthError("Token expired", retry_after=0.0)
        assert error.retry_after == 0.0
        assert error.is_retryable is False  # Still not retryable


class TestConnectorRateLimitError:
    """Tests for rate limit errors."""

    def test_rate_limit_is_retryable(self):
        """Rate limit errors should be retryable."""
        error = ConnectorRateLimitError("Too many requests", connector_name="youtube")
        assert error.is_retryable is True
        assert "[youtube]" in str(error)

    def test_rate_limit_default_retry_after(self):
        """Rate limit should default to 60 seconds retry."""
        error = ConnectorRateLimitError("Rate limited")
        assert error.retry_after == 60.0

    def test_rate_limit_custom_retry_after(self):
        """Rate limit should use provided retry_after."""
        error = ConnectorRateLimitError("Rate limited", retry_after=120.0)
        assert error.retry_after == 120.0


class TestConnectorTimeoutError:
    """Tests for timeout errors."""

    def test_timeout_is_retryable(self):
        """Timeout errors should be retryable."""
        error = ConnectorTimeoutError("Request timed out")
        assert error.is_retryable is True

    def test_timeout_short_retry(self):
        """Timeout errors should have short retry delay."""
        error = ConnectorTimeoutError("Timed out")
        assert error.retry_after == 5.0

    def test_timeout_with_seconds(self):
        """Timeout should store timeout_seconds."""
        error = ConnectorTimeoutError("Timed out", timeout_seconds=30.0)
        assert error.timeout_seconds == 30.0


class TestConnectorNetworkError:
    """Tests for network errors."""

    def test_network_error_is_retryable(self):
        """Network errors should be retryable."""
        error = ConnectorNetworkError("Connection refused")
        assert error.is_retryable is True

    def test_network_error_short_retry(self):
        """Network errors should have short retry delay."""
        error = ConnectorNetworkError("DNS failed")
        assert error.retry_after == 5.0


class TestConnectorAPIError:
    """Tests for API errors."""

    def test_api_error_5xx_is_retryable(self):
        """5xx API errors should be retryable."""
        error = ConnectorAPIError("Server error", status_code=503)
        assert error.is_retryable is True
        assert error.status_code == 503

    def test_api_error_4xx_not_retryable(self):
        """4xx API errors should not be retryable."""
        error = ConnectorAPIError("Bad request", status_code=400)
        assert error.is_retryable is False
        assert error.status_code == 400

    def test_api_error_no_status_not_retryable(self):
        """API error without status should not be retryable."""
        error = ConnectorAPIError("Unknown error")
        assert error.is_retryable is False
        assert error.status_code is None

    def test_api_error_with_retry_after(self):
        """API error can have retry_after."""
        error = ConnectorAPIError("Overloaded", status_code=503, retry_after=10.0)
        assert error.retry_after == 10.0


class TestConnectorValidationError:
    """Tests for validation errors."""

    def test_validation_not_retryable(self):
        """Validation errors should not be retryable."""
        error = ConnectorValidationError("Invalid URL format")
        assert error.is_retryable is False

    def test_validation_with_field(self):
        """Validation error should store field name."""
        error = ConnectorValidationError("Too long", field="title")
        assert error.field == "title"


class TestConnectorNotFoundError:
    """Tests for not found errors."""

    def test_not_found_not_retryable(self):
        """Not found errors should not be retryable."""
        error = ConnectorNotFoundError("Resource not found")
        assert error.is_retryable is False

    def test_not_found_with_resource_id(self):
        """Not found should store resource_id."""
        error = ConnectorNotFoundError("Video not found", resource_id="abc123")
        assert error.resource_id == "abc123"


class TestConnectorQuotaError:
    """Tests for quota errors."""

    def test_quota_not_retryable(self):
        """Quota errors should not be retryable."""
        error = ConnectorQuotaError("Daily quota exceeded")
        assert error.is_retryable is False

    def test_quota_with_reset_time(self):
        """Quota error should store reset time."""
        error = ConnectorQuotaError("Quota exceeded", quota_reset=3600.0)
        assert error.quota_reset == 3600.0
        assert error.retry_after == 3600.0


class TestConnectorParseError:
    """Tests for parse errors."""

    def test_parse_not_retryable(self):
        """Parse errors should not be retryable."""
        error = ConnectorParseError("Invalid JSON")
        assert error.is_retryable is False

    def test_parse_with_content_type(self):
        """Parse error should store content_type."""
        error = ConnectorParseError("Failed to parse", content_type="application/xml")
        assert error.content_type == "application/xml"


class TestIsRetryableError:
    """Tests for is_retryable_error utility function."""

    def test_connector_error_retryable(self):
        """Should check ConnectorError.is_retryable."""
        retryable = ConnectorRateLimitError("Rate limited")
        not_retryable = ConnectorAuthError("Bad auth")

        assert is_retryable_error(retryable) is True
        assert is_retryable_error(not_retryable) is False

    def test_timeout_in_type_name(self):
        """Errors with 'timeout' in type should be retryable."""

        class CustomTimeoutError(Exception):
            pass

        error = CustomTimeoutError("Timed out")
        assert is_retryable_error(error) is True

    def test_timeout_in_message(self):
        """Errors with 'timeout' in message should be retryable."""
        error = Exception("Request timeout occurred")
        assert is_retryable_error(error) is True

    def test_connection_in_type_name(self):
        """Errors with 'connection' in type should be retryable."""

        class ConnectionResetError(Exception):
            pass

        error = ConnectionResetError("Connection reset")
        assert is_retryable_error(error) is True

    def test_429_in_message(self):
        """Errors with '429' in message should be retryable."""
        error = Exception("HTTP 429 Too Many Requests")
        assert is_retryable_error(error) is True

    def test_rate_in_message(self):
        """Errors with 'rate' in message should be retryable."""
        error = Exception("Rate limit exceeded")
        assert is_retryable_error(error) is True

    def test_generic_error_not_retryable(self):
        """Generic errors should not be retryable."""
        error = Exception("Something failed")
        assert is_retryable_error(error) is False


class TestGetRetryDelay:
    """Tests for get_retry_delay utility function."""

    def test_connector_error_with_retry_after(self):
        """Should use ConnectorError.retry_after."""
        error = ConnectorRateLimitError("Rate limited", retry_after=120.0)
        assert get_retry_delay(error) == 120.0

    def test_connector_error_no_retry_after(self):
        """Should use default for ConnectorError without retry_after."""
        error = ConnectorAuthError("Bad auth")
        assert get_retry_delay(error, default=10.0) == 10.0

    def test_rate_limit_error_returns_60(self):
        """Rate limit errors should return 60 seconds."""
        error = ConnectorRateLimitError("Rate limited")
        assert get_retry_delay(error) == 60.0

    def test_generic_error_uses_default(self):
        """Generic errors should use default delay."""
        error = Exception("Unknown error")
        assert get_retry_delay(error) == 5.0
        assert get_retry_delay(error, default=15.0) == 15.0


class TestExceptionInheritance:
    """Tests for exception inheritance hierarchy."""

    def test_all_inherit_from_connector_error(self):
        """All exceptions should inherit from ConnectorError."""
        exceptions = [
            ConnectorAuthError("auth"),
            ConnectorRateLimitError("rate"),
            ConnectorTimeoutError("timeout"),
            ConnectorNetworkError("network"),
            ConnectorAPIError("api"),
            ConnectorValidationError("validation"),
            ConnectorNotFoundError("not found"),
            ConnectorQuotaError("quota"),
            ConnectorParseError("parse"),
        ]

        for exc in exceptions:
            assert isinstance(exc, ConnectorError)
            assert isinstance(exc, Exception)

    def test_can_catch_with_base_class(self):
        """Should be able to catch all with ConnectorError."""
        caught = []

        for exc_class in [
            ConnectorAuthError,
            ConnectorRateLimitError,
            ConnectorTimeoutError,
        ]:
            try:
                raise exc_class("test")
            except ConnectorError as e:
                caught.append(type(e).__name__)

        assert len(caught) == 3
        assert "ConnectorAuthError" in caught
        assert "ConnectorRateLimitError" in caught
        assert "ConnectorTimeoutError" in caught


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
