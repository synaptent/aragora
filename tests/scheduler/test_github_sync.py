"""
Tests for GitHub Secrets sync backend.

Tests the GitHubSecretsSyncBackend that pushes rotated secrets to GitHub.
"""

import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.scheduler.rotation_handlers.github_sync import GitHubSecretsSyncBackend


class TestGitHubSecretsSyncBackend:
    """Test GitHubSecretsSyncBackend."""

    @pytest.fixture
    def backend(self):
        return GitHubSecretsSyncBackend(
            repo="aragora-ai/aragora",
            token="ghp_test_token_123",
        )

    def test_init(self, backend):
        assert backend.repo == "aragora-ai/aragora"
        assert backend.token == "ghp_test_token_123"

    def test_token_from_env(self):
        with patch.dict("os.environ", {"GITHUB_ROTATION_TOKEN": "ghp_env_token"}):
            backend = GitHubSecretsSyncBackend(repo="owner/repo")
            assert backend.token == "ghp_env_token"

    def test_no_token_available(self):
        with patch.dict("os.environ", {}, clear=True):
            backend = GitHubSecretsSyncBackend(repo="owner/repo")
            # No token set, no env var, no app credentials
            assert backend.token is None

    @pytest.mark.asyncio
    async def test_sync_secret_success(self, backend):
        """Mock HTTP calls and verify sealed-box encryption + PUT call."""
        mock_public_key = base64.b64encode(b"\x00" * 32).decode()

        mock_get_response = MagicMock()
        mock_get_response.status_code = 200
        mock_get_response.raise_for_status = MagicMock()
        mock_get_response.json.return_value = {
            "key_id": "key-id-123",
            "key": mock_public_key,
        }

        mock_put_response = MagicMock()
        mock_put_response.status_code = 204

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_get_response)
        mock_session.put = AsyncMock(return_value=mock_put_response)

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with (
            patch(
                "aragora.observability.http_client_pool.get_http_pool",
                return_value=mock_pool,
            ),
            patch.object(
                backend,
                "_encrypt_secret",
                return_value="encrypted_value_b64",
            ),
        ):
            result = await backend.sync_secret("ANTHROPIC_API_KEY", "sk-ant-new-key")

        assert result is True
        mock_session.put.assert_called_once()
        call_args = mock_session.put.call_args
        assert "ANTHROPIC_API_KEY" in call_args[0][0]
        assert call_args[1]["json"]["encrypted_value"] == "encrypted_value_b64"
        assert call_args[1]["json"]["key_id"] == "key-id-123"

    @pytest.mark.asyncio
    async def test_sync_secret_auth_failure(self, backend):
        """401 on public key fetch should return False."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        # raise_for_status raises on 4xx status
        mock_response.raise_for_status = MagicMock(side_effect=RuntimeError("401 Unauthorized"))

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
            result = await backend.sync_secret("TEST_KEY", "value")

        assert result is False

    @pytest.mark.asyncio
    async def test_sync_secret_no_token(self):
        """Should skip gracefully when no token is configured."""
        with patch.dict("os.environ", {}, clear=True):
            backend = GitHubSecretsSyncBackend(repo="owner/repo")
            result = await backend.sync_secret("TEST_KEY", "value")

        assert result is False

    @pytest.mark.asyncio
    async def test_sync_secret_network_error(self, backend):
        """Network errors should return False."""
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(side_effect=ConnectionError("Network unreachable"))

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
            result = await backend.sync_secret("TEST_KEY", "value")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_public_key(self, backend):
        """Test public key retrieval."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "key_id": "kid-456",
            "key": "base64pubkey==",
        }

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
            key_id, key = await backend.get_public_key()

        assert key_id == "kid-456"
        assert key == "base64pubkey=="

    @pytest.mark.asyncio
    async def test_get_public_key_no_token(self):
        """Should raise RuntimeError when no token available."""
        with patch.dict("os.environ", {}, clear=True):
            backend = GitHubSecretsSyncBackend(repo="owner/repo")
            with pytest.raises(RuntimeError, match="No GitHub token"):
                await backend.get_public_key()

    def test_encrypt_secret(self, backend):
        """Test that _encrypt_secret produces valid base64 output."""
        from nacl.public import PrivateKey

        # Generate a test keypair
        private_key = PrivateKey.generate()
        public_key_b64 = base64.b64encode(bytes(private_key.public_key)).decode()

        encrypted = backend._encrypt_secret(public_key_b64, "test-secret-value")

        # Should be valid base64
        decoded = base64.b64decode(encrypted)
        assert len(decoded) > 0
        # Encrypted value should be different from plaintext
        assert decoded != b"test-secret-value"

    def test_github_app_token_no_credentials(self):
        """Should return None when app credentials are not set."""
        with patch.dict("os.environ", {}, clear=True):
            backend = GitHubSecretsSyncBackend(repo="owner/repo")
            result = backend._get_app_installation_token()
            assert result is None


class TestGitHubSyncIntegration:
    """Integration-style tests for GitHub sync in rotation flow."""

    @pytest.mark.asyncio
    async def test_sync_after_rotation(self):
        """Integration test: rotate -> store_new_secret -> sync_to_github."""
        from aragora.scheduler.run_rotation import sync_to_github

        mock_backend_instance = MagicMock()
        mock_backend_instance.sync_secret = AsyncMock(return_value=True)

        with (
            patch.dict("os.environ", {"GITHUB_REPO": "aragora-ai/aragora"}),
            patch(
                "aragora.scheduler.rotation_handlers.github_sync.GitHubSecretsSyncBackend",
                return_value=mock_backend_instance,
            ),
        ):
            result = await sync_to_github(
                "ANTHROPIC_API_KEY",
                "sk-ant-new-rotated-key",
                {"github_sync": {"repo": "aragora-ai/aragora"}},
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_sync_skipped_when_no_repo(self):
        """Should return False when no GitHub repo is configured."""
        from aragora.scheduler.run_rotation import sync_to_github

        with patch.dict("os.environ", {}, clear=True):
            result = await sync_to_github(
                "TEST_KEY",
                "test-value",
                {},  # No github_sync config
            )

        assert result is False
