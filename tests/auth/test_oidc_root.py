"""
Tests for OIDC authentication provider.

Tests cover:
- Configuration validation
- PKCE code generation
- Authorization URL generation
- Token exchange (mocked)
- User info extraction
- Claim mapping
- Token refresh
- Logout URL generation
- Error handling
"""

import base64
import hashlib
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

from aragora.auth.oidc import (
    OIDCConfig,
    OIDCProvider,
    OIDCError,
    HAS_HTTPX,
    HAS_JWT,
)
from aragora.auth.sso import (
    SSOProviderType,
    SSOUser,
    SSOAuthenticationError,
    SSOConfigurationError,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def valid_config() -> OIDCConfig:
    """Create a valid OIDC configuration."""
    return OIDCConfig(
        provider_type=SSOProviderType.OIDC,
        entity_id="test-entity-id",  # Required by base SSOConfig
        client_id="test-client-id",
        client_secret="test-client-secret",
        issuer_url="https://example.okta.com",
        callback_url="https://aragora.example.com/auth/callback",
    )


@pytest.fixture
def provider(valid_config: OIDCConfig) -> OIDCProvider:
    """Create an OIDC provider with valid config."""
    return OIDCProvider(valid_config)


@pytest.fixture
def mock_discovery_response() -> dict:
    """Mock OIDC discovery document."""
    return {
        "issuer": "https://example.okta.com",
        "authorization_endpoint": "https://example.okta.com/oauth2/v1/authorize",
        "token_endpoint": "https://example.okta.com/oauth2/v1/token",
        "userinfo_endpoint": "https://example.okta.com/oauth2/v1/userinfo",
        "jwks_uri": "https://example.okta.com/oauth2/v1/keys",
        "end_session_endpoint": "https://example.okta.com/oauth2/v1/logout",
    }


@pytest.fixture
def mock_token_response() -> dict:
    """Mock token exchange response."""
    return {
        "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test_access",
        "refresh_token": "test_refresh_token",
        "id_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test_id",
        "token_type": "Bearer",
        "expires_in": 3600,
    }


@pytest.fixture
def mock_userinfo_response() -> dict:
    """Mock userinfo endpoint response."""
    return {
        "sub": "user-123",
        "email": "test@example.com",
        "name": "Test User",
        "given_name": "Test",
        "family_name": "User",
        "preferred_username": "testuser",
        "groups": ["admin", "developers"],
        "roles": ["owner"],
    }


# =============================================================================
# Configuration Tests
# =============================================================================


class TestOIDCConfig:
    """Tests for OIDC configuration."""

    def test_valid_config_with_issuer(self):
        """Valid config with issuer URL passes validation."""
        config = OIDCConfig(
            provider_type=SSOProviderType.OIDC,
            entity_id="test-entity",
            client_id="client-id",
            client_secret="client-secret",
            issuer_url="https://example.com",
            callback_url="https://app.example.com/callback",
        )
        errors = config.validate()
        assert errors == []

    def test_valid_config_with_explicit_endpoints(self):
        """Valid config with explicit endpoints passes validation."""
        config = OIDCConfig(
            provider_type=SSOProviderType.OIDC,
            entity_id="test-entity",
            client_id="client-id",
            client_secret="client-secret",
            authorization_endpoint="https://example.com/authorize",
            token_endpoint="https://example.com/token",
            callback_url="https://app.example.com/callback",
        )
        errors = config.validate()
        assert errors == []

    def test_missing_client_id(self):
        """Missing client_id fails validation."""
        config = OIDCConfig(
            provider_type=SSOProviderType.OIDC,
            entity_id="test-entity",
            client_secret="client-secret",
            issuer_url="https://example.com",
            callback_url="https://app.example.com/callback",
        )
        errors = config.validate()
        assert "client_id is required" in errors

    def test_missing_client_secret(self):
        """Missing client_secret fails validation."""
        config = OIDCConfig(
            provider_type=SSOProviderType.OIDC,
            entity_id="test-entity",
            client_id="client-id",
            issuer_url="https://example.com",
            callback_url="https://app.example.com/callback",
        )
        errors = config.validate()
        assert "client_secret is required" in errors

    def test_missing_issuer_and_endpoints(self):
        """Missing both issuer and endpoints fails validation."""
        config = OIDCConfig(
            provider_type=SSOProviderType.OIDC,
            entity_id="test-entity",
            client_id="client-id",
            client_secret="client-secret",
            callback_url="https://app.example.com/callback",
        )
        errors = config.validate()
        assert any("issuer_url or explicit endpoints" in e for e in errors)

    def test_default_scopes(self):
        """Default scopes include openid, email, profile."""
        config = OIDCConfig(
            provider_type=SSOProviderType.OIDC,
            entity_id="test-entity",
            client_id="client-id",
            client_secret="client-secret",
            issuer_url="https://example.com",
        )
        assert "openid" in config.scopes
        assert "email" in config.scopes
        assert "profile" in config.scopes

    def test_custom_scopes(self):
        """Custom scopes override defaults."""
        config = OIDCConfig(
            provider_type=SSOProviderType.OIDC,
            entity_id="test-entity",
            client_id="client-id",
            client_secret="client-secret",
            issuer_url="https://example.com",
            scopes=["openid", "custom-scope"],
        )
        assert config.scopes == ["openid", "custom-scope"]

    def test_pkce_enabled_by_default(self):
        """PKCE is enabled by default."""
        config = OIDCConfig(
            provider_type=SSOProviderType.OIDC,
            entity_id="test-entity",
            client_id="client-id",
            client_secret="client-secret",
            issuer_url="https://example.com",
        )
        assert config.use_pkce is True

    def test_provider_type_is_set(self):
        """Provider type is correctly set."""
        config = OIDCConfig(
            provider_type=SSOProviderType.OIDC,
            entity_id="test-entity",
            client_id="client-id",
            client_secret="client-secret",
            issuer_url="https://example.com",
        )
        assert config.provider_type == SSOProviderType.OIDC


class TestOIDCProviderInit:
    """Tests for OIDC provider initialization."""

    def test_create_with_valid_config(self, valid_config: OIDCConfig):
        """Provider creates successfully with valid config."""
        provider = OIDCProvider(valid_config)
        assert provider.config == valid_config

    def test_create_with_invalid_config_raises(self):
        """Provider raises error with invalid config."""
        # Missing client_id and client_secret
        invalid_config = OIDCConfig(
            provider_type=SSOProviderType.OIDC,
            entity_id="test-entity",
            callback_url="https://example.com/callback",
            issuer_url="https://example.com",
        )
        with pytest.raises(SSOConfigurationError) as exc_info:
            OIDCProvider(invalid_config)
        assert "Invalid OIDC configuration" in str(exc_info.value)


# =============================================================================
# PKCE Tests
# =============================================================================


class TestPKCE:
    """Tests for PKCE code generation."""

    def test_generate_pkce_returns_verifier_and_challenge(self, provider: OIDCProvider):
        """PKCE generation returns both verifier and challenge."""
        verifier, challenge = provider._generate_pkce()
        assert verifier
        assert challenge
        assert len(verifier) >= 43  # Minimum PKCE verifier length

    def test_pkce_challenge_is_sha256_of_verifier(self, provider: OIDCProvider):
        """Challenge is base64url(SHA256(verifier))."""
        verifier, challenge = provider._generate_pkce()

        # Verify the challenge matches SHA256 of verifier
        expected_digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected_challenge = base64.urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")
        assert challenge == expected_challenge

    def test_pkce_generates_unique_values(self, provider: OIDCProvider):
        """Each PKCE call generates unique values."""
        v1, c1 = provider._generate_pkce()
        v2, c2 = provider._generate_pkce()
        assert v1 != v2
        assert c1 != c2


# =============================================================================
# Authorization URL Tests
# =============================================================================


class TestAuthorizationURL:
    """Tests for authorization URL generation."""

    @pytest.mark.asyncio
    async def test_authorization_url_includes_required_params(self, provider: OIDCProvider):
        """Authorization URL includes all required OIDC parameters."""
        # Mock discovery
        provider._discovery_cache = {"authorization_endpoint": "https://example.com/authorize"}
        provider._discovery_cached_at = 9999999999  # Future timestamp

        url = await provider.get_authorization_url(state="test-state")
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        assert parsed.netloc == "example.com"
        assert parsed.path == "/authorize"
        assert params["client_id"][0] == "test-client-id"
        assert params["response_type"][0] == "code"
        assert params["state"][0] == "test-state"
        assert "redirect_uri" in params
        assert "scope" in params
        assert "nonce" in params

    @pytest.mark.asyncio
    async def test_authorization_url_includes_pkce_params(self, provider: OIDCProvider):
        """Authorization URL includes PKCE parameters when enabled."""
        provider._discovery_cache = {"authorization_endpoint": "https://example.com/authorize"}
        provider._discovery_cached_at = 9999999999

        url = await provider.get_authorization_url(state="test-state")
        params = parse_qs(urlparse(url).query)

        assert "code_challenge" in params
        assert params["code_challenge_method"][0] == "S256"

    @pytest.mark.asyncio
    async def test_authorization_url_without_pkce(self, valid_config: OIDCConfig):
        """Authorization URL without PKCE when disabled."""
        valid_config.use_pkce = False
        provider = OIDCProvider(valid_config)
        provider._discovery_cache = {"authorization_endpoint": "https://example.com/authorize"}
        provider._discovery_cached_at = 9999999999

        url = await provider.get_authorization_url(state="test-state")
        params = parse_qs(urlparse(url).query)

        assert "code_challenge" not in params
        assert "code_challenge_method" not in params

    @pytest.mark.asyncio
    async def test_authorization_url_custom_scopes(self, provider: OIDCProvider):
        """Authorization URL uses custom scopes when provided."""
        provider._discovery_cache = {"authorization_endpoint": "https://example.com/authorize"}
        provider._discovery_cached_at = 9999999999

        url = await provider.get_authorization_url(state="test-state", scopes=["openid", "custom"])
        params = parse_qs(urlparse(url).query)

        assert params["scope"][0] == "openid custom"

    @pytest.mark.asyncio
    async def test_authorization_url_generates_state_if_not_provided(self, provider: OIDCProvider):
        """Authorization URL generates state if not provided."""
        provider._discovery_cache = {"authorization_endpoint": "https://example.com/authorize"}
        provider._discovery_cached_at = 9999999999

        url = await provider.get_authorization_url()
        params = parse_qs(urlparse(url).query)

        assert "state" in params
        assert len(params["state"][0]) > 0

    @pytest.mark.asyncio
    async def test_authorization_url_stores_pkce_verifier(self, provider: OIDCProvider):
        """PKCE verifier is stored for later retrieval."""
        provider._discovery_cache = {"authorization_endpoint": "https://example.com/authorize"}
        provider._discovery_cached_at = 9999999999

        await provider.get_authorization_url(state="test-state")

        assert "test-state" in provider._pkce_store
        # _pkce_store stores (verifier, timestamp) tuples
        stored = provider._pkce_store["test-state"]
        verifier = stored[0] if isinstance(stored, tuple) else stored
        assert len(verifier) >= 43


# =============================================================================
# Authentication Tests
# =============================================================================


class TestAuthentication:
    """Tests for authentication flow."""

    @pytest.mark.asyncio
    async def test_authenticate_without_code_raises(self, provider: OIDCProvider):
        """Authentication without code raises error."""
        with pytest.raises(SSOAuthenticationError) as exc_info:
            await provider.authenticate(code=None)
        assert "No authorization code" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_authenticate_with_invalid_state_raises(self, provider: OIDCProvider):
        """Authentication with invalid state raises error."""
        with pytest.raises(SSOAuthenticationError) as exc_info:
            await provider.authenticate(code="test-code", state="invalid-state")
        assert "Invalid or expired state" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_authenticate_domain_restriction(
        self,
        valid_config: OIDCConfig,
        mock_token_response: dict,
        mock_userinfo_response: dict,
    ):
        """Authentication fails if email domain not allowed."""
        valid_config.allowed_domains = ["allowed.com"]
        provider = OIDCProvider(valid_config)

        # Store valid state
        state = provider.generate_state()

        # Mock discovery and HTTP calls
        provider._discovery_cache = {
            "token_endpoint": "https://example.com/token",
            "userinfo_endpoint": "https://example.com/userinfo",
        }
        provider._discovery_cached_at = 9999999999

        with patch.object(provider, "_exchange_code", new_callable=AsyncMock) as mock_exchange:
            mock_exchange.return_value = mock_token_response
            with (
                patch.object(
                    provider, "_validate_id_token", new_callable=AsyncMock
                ) as mock_validate,
                patch.object(provider, "_fetch_userinfo", new_callable=AsyncMock) as mock_userinfo,
            ):
                mock_validate.return_value = {}
                # Return user with non-allowed domain
                mock_userinfo.return_value = {"sub": "123", "email": "user@notallowed.com"}

                with pytest.raises(SSOAuthenticationError) as exc_info:
                    await provider.authenticate(code="test-code", state=state)
                assert "domain not allowed" in str(exc_info.value).lower()


# =============================================================================
# Token Exchange Tests
# =============================================================================


class TestTokenExchange:
    """Tests for token exchange."""

    @pytest.mark.asyncio
    async def test_exchange_code_without_endpoint_raises(self, provider: OIDCProvider):
        """Token exchange without endpoint raises error."""
        # Use a non-empty cache without token_endpoint (empty dict is falsy and triggers discovery)
        provider._discovery_cache = {"issuer": "https://example.com"}
        provider._discovery_cached_at = 9999999999

        with pytest.raises(SSOConfigurationError) as exc_info:
            await provider._exchange_code("test-code", None)
        assert "No token_endpoint" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_exchange_code_includes_pkce_verifier(self, provider: OIDCProvider):
        """Token exchange includes PKCE verifier when available."""
        provider._discovery_cache = {"token_endpoint": "https://example.com/token"}
        provider._discovery_cached_at = 9999999999

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.json.return_value = {"access_token": "test"}
            mock_response.raise_for_status = MagicMock()

            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()  # http_client_pool awaits this
            mock_client_class.return_value = mock_client

            await provider._exchange_code("test-code", "test-verifier")

            # Verify code_verifier was included in the request
            call_kwargs = mock_client.post.call_args
            assert "code_verifier" in call_kwargs.kwargs.get("data", {})
            assert call_kwargs.kwargs["data"]["code_verifier"] == "test-verifier"


# =============================================================================
# User Info Tests
# =============================================================================


class TestUserInfo:
    """Tests for user info extraction."""

    def test_claims_to_user_basic_fields(self, provider: OIDCProvider):
        """Claims are correctly mapped to user fields."""
        claims = {
            "sub": "user-123",
            "email": "test@example.com",
            "name": "Test User",
            "given_name": "Test",
            "family_name": "User",
            "preferred_username": "testuser",
        }
        tokens = {"access_token": "test_access", "expires_in": 3600}

        user = provider._claims_to_user(claims, tokens)

        assert user.id == "user-123"
        assert user.email == "test@example.com"
        assert user.name == "Test User"
        assert user.first_name == "Test"
        assert user.last_name == "User"
        assert user.username == "testuser"
        assert user.access_token == "test_access"

    def test_claims_to_user_with_roles_and_groups(self, provider: OIDCProvider):
        """Roles and groups are correctly extracted."""
        claims = {
            "sub": "user-123",
            "email": "test@example.com",
            "roles": ["admin", "developer"],
            "groups": ["team-a", "team-b"],
        }
        tokens = {"access_token": "test_access", "expires_in": 3600}

        user = provider._claims_to_user(claims, tokens)

        assert "admin" in user.roles
        assert "developer" in user.roles
        assert "team-a" in user.groups
        assert "team-b" in user.groups

    def test_claims_to_user_with_azure_wids(self, provider: OIDCProvider):
        """Azure AD wids claim is mapped to roles."""
        claims = {
            "sub": "user-123",
            "email": "test@example.com",
            "wids": ["admin-role-id", "reader-role-id"],
        }
        tokens = {"access_token": "test_access", "expires_in": 3600}

        user = provider._claims_to_user(claims, tokens)

        assert "admin-role-id" in user.roles
        assert "reader-role-id" in user.roles

    def test_claims_to_user_with_custom_mapping(self, valid_config: OIDCConfig):
        """Custom claim mapping is respected."""
        # Mapping format: {custom_claim_name: standard_target_name}
        # The code looks for entries where value matches the standard target
        valid_config.claim_mapping = {
            "user_id": "sub",  # user_id claim maps to "sub" target (user.id)
            "mail": "email",  # mail claim maps to "email" target
            "display": "name",  # display claim maps to "name" target
        }
        provider = OIDCProvider(valid_config)

        claims = {
            "user_id": "custom-123",
            "mail": "custom@example.com",
            "display": "Custom Name",
        }
        tokens = {"access_token": "test_access", "expires_in": 3600}

        user = provider._claims_to_user(claims, tokens)

        assert user.id == "custom-123"
        assert user.email == "custom@example.com"
        assert user.name == "Custom Name"

    def test_extract_list_claim_from_list(self, provider: OIDCProvider):
        """List claims are correctly extracted."""
        claims = {"roles": ["admin", "user"]}
        result = provider._extract_list_claim(claims, "roles", provider.config.claim_mapping)
        assert result == ["admin", "user"]

    def test_extract_list_claim_from_string(self, provider: OIDCProvider):
        """String claims are wrapped in list."""
        claims = {"roles": "admin"}
        result = provider._extract_list_claim(claims, "roles", provider.config.claim_mapping)
        assert result == ["admin"]

    def test_extract_list_claim_missing(self, provider: OIDCProvider):
        """Missing claims return empty list."""
        claims = {}
        result = provider._extract_list_claim(claims, "roles", provider.config.claim_mapping)
        assert result == []


# =============================================================================
# Token Refresh Tests
# =============================================================================


class TestTokenRefresh:
    """Tests for token refresh."""

    @pytest.mark.asyncio
    async def test_refresh_without_refresh_token_returns_none(self, provider: OIDCProvider):
        """Refresh without refresh token returns None."""
        user = SSOUser(id="123", email="test@example.com", refresh_token=None)
        result = await provider.refresh_token(user)
        assert result is None

    @pytest.mark.asyncio
    async def test_refresh_without_endpoint_returns_none(self, provider: OIDCProvider):
        """Refresh without token endpoint returns None."""
        # Use non-empty cache without token_endpoint (empty dict triggers discovery)
        provider._discovery_cache = {"issuer": "https://example.com"}
        provider._discovery_cached_at = 9999999999

        user = SSOUser(id="123", email="test@example.com", refresh_token="test_refresh")
        result = await provider.refresh_token(user)
        assert result is None


# =============================================================================
# Logout Tests
# =============================================================================


class TestLogout:
    """Tests for logout URL generation."""

    @pytest.mark.asyncio
    async def test_logout_without_endpoint_returns_fallback(self, valid_config: OIDCConfig):
        """Logout without endpoint returns fallback URL."""
        valid_config.logout_url = "https://example.com/logged-out"
        provider = OIDCProvider(valid_config)
        # Use non-empty cache without end_session_endpoint (empty dict triggers discovery)
        provider._discovery_cache = {"issuer": "https://example.com"}
        provider._discovery_cached_at = 9999999999

        user = SSOUser(id="123", email="test@example.com")
        result = await provider.logout(user)

        assert result == "https://example.com/logged-out"

    @pytest.mark.asyncio
    async def test_logout_with_endpoint_includes_id_token_hint(self, provider: OIDCProvider):
        """Logout URL includes id_token_hint when available."""
        provider._discovery_cache = {"end_session_endpoint": "https://example.com/logout"}
        provider._discovery_cached_at = 9999999999

        user = SSOUser(id="123", email="test@example.com", id_token="test_id_token")
        result = await provider.logout(user)

        assert "id_token_hint=test_id_token" in result

    @pytest.mark.asyncio
    async def test_logout_with_post_logout_redirect(self, valid_config: OIDCConfig):
        """Logout URL includes post_logout_redirect_uri."""
        valid_config.post_logout_redirect_url = "https://app.example.com/logged-out"
        provider = OIDCProvider(valid_config)
        provider._discovery_cache = {"end_session_endpoint": "https://example.com/logout"}
        provider._discovery_cached_at = 9999999999

        user = SSOUser(id="123", email="test@example.com")
        result = await provider.logout(user)

        assert "post_logout_redirect_uri" in result


# =============================================================================
# Discovery Tests
# =============================================================================


class TestDiscovery:
    """Tests for OIDC discovery."""

    @pytest.mark.asyncio
    async def test_discovery_caches_results(self, provider: OIDCProvider):
        """Discovery results are cached."""
        # Set up a cached result
        provider._discovery_cache = {"test": "cached"}
        provider._discovery_cached_at = 9999999999  # Far future

        result = await provider._discover_endpoints()

        assert result == {"test": "cached"}

    @pytest.mark.asyncio
    async def test_get_endpoint_prefers_config(self, provider: OIDCProvider):
        """Endpoint getter prefers config over discovery."""
        provider.config.token_endpoint = "https://config.example.com/token"
        provider._discovery_cache = {"token_endpoint": "https://discovery.example.com/token"}
        provider._discovery_cached_at = 9999999999

        result = await provider._get_endpoint("token_endpoint")

        assert result == "https://config.example.com/token"


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    def test_oidc_error_has_correct_code(self):
        """OIDCError has correct error code."""
        error = OIDCError("Test error", {"detail": "value"})
        assert error.code == "OIDC_ERROR"
        assert error.details == {"detail": "value"}

    def test_authentication_error_inheritance(self):
        """SSOAuthenticationError inherits from SSOError."""
        error = SSOAuthenticationError("Auth failed")
        assert error.code == "SSO_AUTH_FAILED"

    def test_configuration_error_inheritance(self):
        """SSOConfigurationError inherits from SSOError."""
        error = SSOConfigurationError("Config invalid")
        assert error.code == "SSO_CONFIG_ERROR"
