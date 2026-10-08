"""
Unit tests for OpenClaw Gateway credential management components.

Tests cover:
1. CredentialRotationRateLimiter - rate limiting for credential rotations
2. Credential handler mixin behavior
"""

from __future__ import annotations

import time
from threading import Thread
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.openclaw.credentials import (
    CREDENTIAL_ROTATION_WINDOW_SECONDS,
    MAX_CREDENTIAL_ROTATIONS_PER_HOUR,
    CredentialRotationRateLimiter,
    _get_credential_rotation_limiter,
)


# =============================================================================
# CredentialRotationRateLimiter Tests
# =============================================================================


class TestCredentialRotationRateLimiter:
    """Test the CredentialRotationRateLimiter class."""

    def test_default_constructor(self):
        """Test default constructor uses module constants."""
        limiter = CredentialRotationRateLimiter()
        assert limiter._max_rotations == MAX_CREDENTIAL_ROTATIONS_PER_HOUR
        assert limiter._window_seconds == CREDENTIAL_ROTATION_WINDOW_SECONDS

    def test_custom_constructor(self):
        """Test custom constructor parameters."""
        limiter = CredentialRotationRateLimiter(max_rotations=5, window_seconds=60)
        assert limiter._max_rotations == 5
        assert limiter._window_seconds == 60

    def test_first_rotation_allowed(self):
        """Test that the first rotation is always allowed."""
        limiter = CredentialRotationRateLimiter(max_rotations=3, window_seconds=60)
        assert limiter.is_allowed("user-001") is True

    def test_rotation_within_limit_allowed(self):
        """Test that rotations within limit are allowed."""
        limiter = CredentialRotationRateLimiter(max_rotations=3, window_seconds=60)

        assert limiter.is_allowed("user-001") is True  # 1st
        assert limiter.is_allowed("user-001") is True  # 2nd
        assert limiter.is_allowed("user-001") is True  # 3rd

    def test_rotation_exceeding_limit_denied(self):
        """Test that rotations exceeding limit are denied."""
        limiter = CredentialRotationRateLimiter(max_rotations=3, window_seconds=60)

        limiter.is_allowed("user-001")  # 1st
        limiter.is_allowed("user-001")  # 2nd
        limiter.is_allowed("user-001")  # 3rd
        assert limiter.is_allowed("user-001") is False  # 4th - denied

    def test_different_users_tracked_separately(self):
        """Test that different users have separate rate limits."""
        limiter = CredentialRotationRateLimiter(max_rotations=2, window_seconds=60)

        # User 1 uses their limit
        limiter.is_allowed("user-001")
        limiter.is_allowed("user-001")
        assert limiter.is_allowed("user-001") is False

        # User 2 still has their full limit
        assert limiter.is_allowed("user-002") is True
        assert limiter.is_allowed("user-002") is True
        assert limiter.is_allowed("user-002") is False

    def test_get_remaining_full_limit(self):
        """Test get_remaining returns full limit for new user."""
        limiter = CredentialRotationRateLimiter(max_rotations=5, window_seconds=60)
        assert limiter.get_remaining("user-001") == 5

    def test_get_remaining_after_rotations(self):
        """Test get_remaining decreases after rotations."""
        limiter = CredentialRotationRateLimiter(max_rotations=5, window_seconds=60)

        limiter.is_allowed("user-001")
        assert limiter.get_remaining("user-001") == 4

        limiter.is_allowed("user-001")
        assert limiter.get_remaining("user-001") == 3

    def test_get_remaining_at_zero(self):
        """Test get_remaining returns zero when exhausted."""
        limiter = CredentialRotationRateLimiter(max_rotations=2, window_seconds=60)

        limiter.is_allowed("user-001")
        limiter.is_allowed("user-001")
        assert limiter.get_remaining("user-001") == 0

    def test_get_retry_after_when_not_rate_limited(self):
        """Test get_retry_after returns 0 when not rate limited."""
        limiter = CredentialRotationRateLimiter(max_rotations=3, window_seconds=60)

        limiter.is_allowed("user-001")
        assert limiter.get_retry_after("user-001") == 0

    def test_get_retry_after_when_rate_limited(self):
        """Test get_retry_after returns positive value when rate limited."""
        limiter = CredentialRotationRateLimiter(max_rotations=2, window_seconds=60)

        limiter.is_allowed("user-001")
        limiter.is_allowed("user-001")

        retry_after = limiter.get_retry_after("user-001")
        assert retry_after > 0
        assert retry_after <= 60

    def test_window_expiration_allows_new_rotations(self):
        """Test that rotations are allowed again after window expires."""
        limiter = CredentialRotationRateLimiter(max_rotations=2, window_seconds=0.1)

        limiter.is_allowed("user-001")
        limiter.is_allowed("user-001")
        assert limiter.is_allowed("user-001") is False

        # Wait for window to expire
        time.sleep(0.15)

        assert limiter.is_allowed("user-001") is True

    def test_sliding_window_cleanup(self):
        """Test that old entries are cleaned up on check."""
        limiter = CredentialRotationRateLimiter(max_rotations=2, window_seconds=0.2)

        limiter.is_allowed("user-001")  # 1st - allowed
        time.sleep(0.05)
        limiter.is_allowed("user-001")  # 2nd - allowed

        # At limit now
        assert limiter.is_allowed("user-001") is False

        # Wait for window to fully expire
        time.sleep(0.2)

        # Both entries should have expired, allowing new rotation
        assert limiter.is_allowed("user-001") is True

    def test_thread_safety(self):
        """Test that rate limiter is thread-safe."""
        limiter = CredentialRotationRateLimiter(max_rotations=100, window_seconds=60)
        results = []

        def check_limit():
            for _ in range(10):
                results.append(limiter.is_allowed("user-001"))

        threads = [Thread(target=check_limit) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have exactly 100 True results
        true_count = sum(1 for r in results if r)
        assert true_count == 100, f"Expected 100 allowed, got {true_count}"

    def test_get_remaining_thread_safety(self):
        """Test that get_remaining is thread-safe."""
        limiter = CredentialRotationRateLimiter(max_rotations=50, window_seconds=60)
        results = []

        def check_remaining():
            for _ in range(10):
                limiter.is_allowed("user-001")
                results.append(limiter.get_remaining("user-001"))

        threads = [Thread(target=check_remaining) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All remaining counts should be non-negative
        assert all(r >= 0 for r in results)

    def test_multiple_users_concurrent(self):
        """Test concurrent access from multiple users."""
        limiter = CredentialRotationRateLimiter(max_rotations=10, window_seconds=60)

        def rotate_for_user(user_id):
            for _ in range(10):
                limiter.is_allowed(user_id)

        threads = [Thread(target=rotate_for_user, args=(f"user-{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each user should have exhausted their limit
        for i in range(5):
            assert limiter.get_remaining(f"user-{i}") == 0


# =============================================================================
# Global Limiter Instance Tests
# =============================================================================


class TestGlobalCredentialRotationLimiter:
    """Test the global credential rotation limiter instance management."""

    def test_get_limiter_returns_instance(self):
        """Test that _get_credential_rotation_limiter returns an instance."""
        # Reset global state first
        import aragora.server.handlers.openclaw.credentials as creds_module

        creds_module._credential_rotation_limiter = None

        limiter = _get_credential_rotation_limiter()
        assert isinstance(limiter, CredentialRotationRateLimiter)

    def test_get_limiter_returns_singleton(self):
        """Test that _get_credential_rotation_limiter returns same instance."""
        # Reset global state first
        import aragora.server.handlers.openclaw.credentials as creds_module

        creds_module._credential_rotation_limiter = None

        limiter1 = _get_credential_rotation_limiter()
        limiter2 = _get_credential_rotation_limiter()
        assert limiter1 is limiter2

    def test_limiter_override_via_shim_module(self):
        """Test that the limiter can be overridden via the shim module."""
        import sys
        import aragora.server.handlers.openclaw.credentials as creds_module

        # Create a mock limiter
        mock_limiter = CredentialRotationRateLimiter(max_rotations=999, window_seconds=1)

        def mock_get_limiter():
            return mock_limiter

        # Create mock shim module
        mock_shim = MagicMock()
        mock_shim._get_credential_rotation_limiter = mock_get_limiter

        # Reset global state
        creds_module._credential_rotation_limiter = None

        # Inject mock shim
        original_modules = sys.modules.copy()
        sys.modules["aragora.server.handlers.openclaw.openclaw_gateway"] = mock_shim

        try:
            limiter = _get_credential_rotation_limiter()
            assert limiter._max_rotations == 999
        finally:
            # Restore original modules
            sys.modules.clear()
            sys.modules.update(original_modules)
            creds_module._credential_rotation_limiter = None


# =============================================================================
# Constants Tests
# =============================================================================


class TestCredentialConstants:
    """Test credential-related constants."""

    def test_rotation_window_is_positive(self):
        """Test that rotation window is a positive value."""
        assert CREDENTIAL_ROTATION_WINDOW_SECONDS > 0

    def test_max_rotations_is_positive(self):
        """Test that max rotations is a positive value."""
        assert MAX_CREDENTIAL_ROTATIONS_PER_HOUR > 0

    def test_rotation_window_is_one_hour(self):
        """Test that rotation window is 1 hour (3600 seconds)."""
        assert CREDENTIAL_ROTATION_WINDOW_SECONDS == 3600

    def test_max_rotations_is_reasonable(self):
        """Test that max rotations is a reasonable value."""
        # 10 rotations per hour is the default
        assert MAX_CREDENTIAL_ROTATIONS_PER_HOUR == 10


# =============================================================================
# Edge Cases
# =============================================================================


class TestCredentialEdgeCases:
    """Test edge cases for credential management."""

    def test_empty_user_id(self):
        """Test rate limiting with empty user ID."""
        limiter = CredentialRotationRateLimiter(max_rotations=2, window_seconds=60)

        assert limiter.is_allowed("") is True
        assert limiter.is_allowed("") is True
        assert limiter.is_allowed("") is False

    def test_special_chars_in_user_id(self):
        """Test rate limiting with special chars in user ID."""
        limiter = CredentialRotationRateLimiter(max_rotations=2, window_seconds=60)

        special_id = "user@domain.com!#$%"
        assert limiter.is_allowed(special_id) is True
        assert limiter.is_allowed(special_id) is True
        assert limiter.is_allowed(special_id) is False

    def test_very_long_user_id(self):
        """Test rate limiting with very long user ID."""
        limiter = CredentialRotationRateLimiter(max_rotations=2, window_seconds=60)

        long_id = "u" * 10000
        assert limiter.is_allowed(long_id) is True
        assert limiter.is_allowed(long_id) is True
        assert limiter.is_allowed(long_id) is False

    def test_zero_max_rotations(self):
        """Test with zero max rotations (nothing allowed)."""
        limiter = CredentialRotationRateLimiter(max_rotations=0, window_seconds=60)
        assert limiter.is_allowed("user-001") is False

    def test_very_small_window(self):
        """Test with very small window."""
        limiter = CredentialRotationRateLimiter(max_rotations=1, window_seconds=0.001)

        limiter.is_allowed("user-001")
        assert limiter.is_allowed("user-001") is False

        time.sleep(0.01)
        assert limiter.is_allowed("user-001") is True

    def test_large_max_rotations(self):
        """Test with large max rotations value."""
        limiter = CredentialRotationRateLimiter(max_rotations=1000000, window_seconds=60)

        for _ in range(100):
            assert limiter.is_allowed("user-001") is True

        assert limiter.get_remaining("user-001") == 999900


__all__ = [
    "TestCredentialRotationRateLimiter",
    "TestGlobalCredentialRotationLimiter",
    "TestCredentialConstants",
    "TestCredentialEdgeCases",
]
