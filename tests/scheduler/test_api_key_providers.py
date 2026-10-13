"""
Tests for API key provider rotation methods.

Tests Anthropic, Stripe, Cloudflare programmatic rotation
and xAI, DeepSeek, Stripe, Cloudflare validators.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.scheduler.rotation_handlers.api_key import APIKeyRotationHandler
from aragora.scheduler.rotation_handlers.base import RotationError, RotationStatus


class TestRotateAnthropic:
    """Test Anthropic Admin API key rotation."""

    @pytest.fixture
    def handler(self):
        return APIKeyRotationHandler()

    @pytest.mark.asyncio
    async def test_rotate_anthropic_success(self, handler):
        """Mock Admin API, verify key creation."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "id": "apikey-123",
            "api_key": "sk-ant-new-rotated-key",
        }

        mock_session = AsyncMock()
        mock_session.post = AsyncMock(return_value=mock_response)

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            new_key, meta = await handler._rotate_anthropic(
                "ANTHROPIC_API_KEY",
                {
                    "provider": "anthropic",
                    "admin_key": "admin-key-123",
                    "org_id": "org-test-123",
                },
            )

        assert new_key == "sk-ant-new-rotated-key"
        assert meta["key_id"] == "apikey-123"
        assert meta["rotation_method"] == "programmatic"

    @pytest.mark.asyncio
    async def test_rotate_anthropic_no_admin_key(self, handler):
        """Falls back to manual notification when no admin key."""
        handler._notify_manual_rotation = AsyncMock()

        with patch(
            "aragora.config.secrets.get_secret",
            side_effect=KeyError("not found"),
        ):
            with pytest.raises(RotationError, match="admin key required"):
                await handler._rotate_anthropic(
                    "ANTHROPIC_API_KEY",
                    {"provider": "anthropic"},
                )

        handler._notify_manual_rotation.assert_called_once()

    @pytest.mark.asyncio
    async def test_rotate_anthropic_no_org_id(self, handler):
        """Should fail when org_id is not available."""
        handler._notify_manual_rotation = AsyncMock()

        with pytest.raises(RotationError, match="org_id required"):
            await handler._rotate_anthropic(
                "ANTHROPIC_API_KEY",
                {"provider": "anthropic", "admin_key": "admin-123"},
            )

    @pytest.mark.asyncio
    async def test_rotate_anthropic_api_error(self, handler):
        """API errors should fall back to manual notification."""
        handler._notify_manual_rotation = AsyncMock()

        mock_session = AsyncMock()
        mock_session.post = AsyncMock(side_effect=ConnectionError("Network error"))

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            with pytest.raises(RotationError, match="programmatic rotation failed"):
                await handler._rotate_anthropic(
                    "ANTHROPIC_API_KEY",
                    {
                        "provider": "anthropic",
                        "admin_key": "admin-123",
                        "org_id": "org-123",
                    },
                )

        handler._notify_manual_rotation.assert_called_once()

    @pytest.mark.asyncio
    async def test_anthropic_full_rotation_lifecycle(self, handler):
        """Full rotation via handler.rotate() with Anthropic programmatic path."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "id": "apikey-456",
            "api_key": "sk-ant-lifecycle-key",
        }

        mock_session = AsyncMock()
        mock_session.post = AsyncMock(return_value=mock_response)

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        # Also mock validation to succeed
        handler._validate_anthropic = AsyncMock(return_value=True)

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            result = await handler.rotate(
                "ANTHROPIC_API_KEY",
                "old-key",
                {
                    "provider": "anthropic",
                    "admin_key": "admin-key",
                    "org_id": "org-123",
                },
            )

        assert result.status == RotationStatus.SUCCESS
        assert result.metadata["new_value"] == "sk-ant-lifecycle-key"


class TestRotateStripe:
    """Test Stripe rolling key rotation."""

    @pytest.fixture
    def handler(self):
        return APIKeyRotationHandler()

    @pytest.mark.asyncio
    async def test_rotate_stripe_success(self, handler):
        """Mock roll endpoint, verify 24h grace note."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "id": "sk_live_old",
            "secret": "sk_live_new_rolled_key",
            "expires": "2026-02-18T00:00:00Z",
        }

        mock_session = AsyncMock()
        mock_session.post = AsyncMock(return_value=mock_response)

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            new_key, meta = await handler._rotate_stripe(
                "STRIPE_SECRET_KEY",
                {"provider": "stripe", "current_key": "sk_live_current"},
            )

        assert new_key == "sk_live_new_rolled_key"
        assert meta["rotation_method"] == "programmatic"
        assert "grace_note" in meta

    @pytest.mark.asyncio
    async def test_rotate_stripe_no_current_key(self, handler):
        """Should fail when no current key is available."""
        handler._notify_manual_rotation = AsyncMock()

        with pytest.raises(RotationError, match="Current Stripe key required"):
            await handler._rotate_stripe(
                "STRIPE_SECRET_KEY",
                {"provider": "stripe"},
            )

    @pytest.mark.asyncio
    async def test_rotate_stripe_api_error(self, handler):
        """API errors should fall back to manual notification."""
        handler._notify_manual_rotation = AsyncMock()

        mock_session = AsyncMock()
        mock_session.post = AsyncMock(side_effect=TimeoutError("Timeout"))

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            with pytest.raises(RotationError, match="programmatic rotation failed"):
                await handler._rotate_stripe(
                    "STRIPE_SECRET_KEY",
                    {"provider": "stripe", "current_key": "sk_live_current"},
                )


class TestRotateCloudflare:
    """Test Cloudflare API token rotation."""

    @pytest.fixture
    def handler(self):
        return APIKeyRotationHandler()

    @pytest.mark.asyncio
    async def test_rotate_cloudflare_success(self, handler):
        """Mock token creation and old token deletion."""
        create_response = MagicMock()
        create_response.status_code = 200
        create_response.raise_for_status = MagicMock()
        create_response.json.return_value = {
            "success": True,
            "result": {
                "id": "new-token-id-456",
                "value": "cf_new_token_value",
            },
        }

        delete_response = MagicMock()
        delete_response.status_code = 200

        mock_session = AsyncMock()
        mock_session.post = AsyncMock(return_value=create_response)
        mock_session.delete = AsyncMock(return_value=delete_response)

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            new_token, meta = await handler._rotate_cloudflare(
                "CLOUDFLARE_API_TOKEN",
                {
                    "provider": "cloudflare",
                    "admin_token": "cf-admin-token",
                    "old_token_id": "old-token-id-123",
                },
            )

        assert new_token == "cf_new_token_value"
        assert meta["token_id"] == "new-token-id-456"
        assert meta["rotation_method"] == "programmatic"
        mock_session.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_rotate_cloudflare_no_admin_token(self, handler):
        """Should fail when no admin token available."""
        handler._notify_manual_rotation = AsyncMock()

        with pytest.raises(RotationError, match="admin token required"):
            await handler._rotate_cloudflare(
                "CLOUDFLARE_API_TOKEN",
                {"provider": "cloudflare"},
            )

    @pytest.mark.asyncio
    async def test_rotate_cloudflare_api_failure(self, handler):
        """API returning success=false should raise RotationError."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "success": False,
            "errors": [{"message": "Token limit reached"}],
        }

        mock_session = AsyncMock()
        mock_session.post = AsyncMock(return_value=mock_response)

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            with pytest.raises(RotationError, match="token creation failed"):
                await handler._rotate_cloudflare(
                    "CLOUDFLARE_API_TOKEN",
                    {"provider": "cloudflare", "admin_token": "cf-admin"},
                )


class TestValidateStripe:
    """Test Stripe key validation."""

    @pytest.fixture
    def handler(self):
        return APIKeyRotationHandler()

    @pytest.mark.asyncio
    async def test_validate_stripe_valid(self, handler):
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            result = await handler._validate_stripe("STRIPE_KEY", "sk_live_test", {})

        assert result is True

    @pytest.mark.asyncio
    async def test_validate_stripe_invalid(self, handler):
        mock_response = MagicMock()
        mock_response.status_code = 401

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            result = await handler._validate_stripe("STRIPE_KEY", "bad_key", {})

        assert result is False


class TestValidateCloudflare:
    """Test Cloudflare token validation."""

    @pytest.fixture
    def handler(self):
        return APIKeyRotationHandler()

    @pytest.mark.asyncio
    async def test_validate_cloudflare_valid(self, handler):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            result = await handler._validate_cloudflare("CF_TOKEN", "cf-token", {})

        assert result is True

    @pytest.mark.asyncio
    async def test_validate_cloudflare_invalid(self, handler):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": False}

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            result = await handler._validate_cloudflare("CF_TOKEN", "bad-token", {})

        assert result is False


class TestValidateXai:
    """Test xAI key validation."""

    @pytest.fixture
    def handler(self):
        return APIKeyRotationHandler()

    @pytest.mark.asyncio
    async def test_validate_xai_valid(self, handler):
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            result = await handler._validate_xai("XAI_KEY", "xai-test-key", {})

        assert result is True

    @pytest.mark.asyncio
    async def test_validate_xai_network_error(self, handler):
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(side_effect=ConnectionError("Network error"))

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            result = await handler._validate_xai("XAI_KEY", "xai-key", {})

        assert result is False


class TestValidateDeepseek:
    """Test DeepSeek key validation."""

    @pytest.fixture
    def handler(self):
        return APIKeyRotationHandler()

    @pytest.mark.asyncio
    async def test_validate_deepseek_valid(self, handler):
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            result = await handler._validate_deepseek("DS_KEY", "ds-test-key", {})

        assert result is True

    @pytest.mark.asyncio
    async def test_validate_deepseek_invalid(self, handler):
        mock_response = MagicMock()
        mock_response.status_code = 401

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            result = await handler._validate_deepseek("DS_KEY", "bad-key", {})

        assert result is False


class TestRevokeAnthropic:
    """Test Anthropic key revocation."""

    @pytest.fixture
    def handler(self):
        return APIKeyRotationHandler()

    @pytest.mark.asyncio
    async def test_revoke_anthropic_success(self, handler):
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_session = AsyncMock()
        mock_session.delete = AsyncMock(return_value=mock_response)

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            result = await handler._revoke_anthropic(
                "ANTHROPIC_API_KEY",
                "old-key-id",
                {
                    "admin_key": "admin-key",
                    "org_id": "org-123",
                },
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_revoke_anthropic_no_admin_key(self, handler):
        result = await handler._revoke_anthropic(
            "ANTHROPIC_API_KEY",
            "old-key-id",
            {},
        )
        assert result is False


class TestProviderDispatch:
    """Test that provider dispatch routes to correct rotation method."""

    @pytest.fixture
    def handler(self):
        return APIKeyRotationHandler()

    @pytest.mark.asyncio
    async def test_dispatch_anthropic(self, handler):
        handler._rotate_anthropic = AsyncMock(
            return_value=("new-key", {"rotation_method": "programmatic"})
        )
        handler._validate_anthropic = AsyncMock(return_value=True)

        result = await handler.rotate(
            "ANTHROPIC_KEY",
            "old",
            {"provider": "anthropic"},
        )
        handler._rotate_anthropic.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_stripe(self, handler):
        handler._rotate_stripe = AsyncMock(
            return_value=("new-key", {"rotation_method": "programmatic"})
        )
        handler._validate_stripe = AsyncMock(return_value=True)

        result = await handler.rotate(
            "STRIPE_KEY",
            "old",
            {"provider": "stripe"},
        )
        handler._rotate_stripe.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_cloudflare(self, handler):
        handler._rotate_cloudflare = AsyncMock(
            return_value=("new-key", {"rotation_method": "programmatic"})
        )
        handler._validate_cloudflare = AsyncMock(return_value=True)

        result = await handler.rotate(
            "CF_TOKEN",
            "old",
            {"provider": "cloudflare"},
        )
        handler._rotate_cloudflare.assert_called_once()

    @pytest.mark.asyncio
    async def test_validator_dispatch_xai(self, handler):
        """Verify xAI validator is called for xai provider."""
        handler._validate_xai = AsyncMock(return_value=True)

        result = await handler.validate_credentials("XAI_KEY", "key-value", {"provider": "xai"})

        assert result is True
        handler._validate_xai.assert_called_once()

    @pytest.mark.asyncio
    async def test_validator_dispatch_deepseek(self, handler):
        """Verify DeepSeek validator is called for deepseek provider."""
        handler._validate_deepseek = AsyncMock(return_value=True)

        result = await handler.validate_credentials("DS_KEY", "key-value", {"provider": "deepseek"})

        assert result is True
        handler._validate_deepseek.assert_called_once()

    @pytest.mark.asyncio
    async def test_validator_dispatch_stripe(self, handler):
        """Verify Stripe validator is called for stripe provider."""
        handler._validate_stripe = AsyncMock(return_value=True)

        result = await handler.validate_credentials(
            "STRIPE_KEY", "key-value", {"provider": "stripe"}
        )

        assert result is True
        handler._validate_stripe.assert_called_once()

    @pytest.mark.asyncio
    async def test_validator_dispatch_cloudflare(self, handler):
        """Verify Cloudflare validator is called for cloudflare provider."""
        handler._validate_cloudflare = AsyncMock(return_value=True)

        result = await handler.validate_credentials(
            "CF_TOKEN", "key-value", {"provider": "cloudflare"}
        )

        assert result is True
        handler._validate_cloudflare.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoke_dispatches_anthropic(self, handler):
        """Verify Anthropic revocation is dispatched correctly."""
        handler._revoke_anthropic = AsyncMock(return_value=True)

        result = await handler.revoke_old_credentials(
            "ANTHROPIC_KEY",
            "old-key",
            {"provider": "anthropic", "old_key_id": "key-123"},
        )

        assert result is True
        handler._revoke_anthropic.assert_called_once_with(
            "ANTHROPIC_KEY", "key-123", {"provider": "anthropic", "old_key_id": "key-123"}
        )
