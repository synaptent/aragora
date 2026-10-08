"""
Tests for JWT authentication module.

Covers:
- JWT token creation and encoding
- Token validation and decoding
- Access vs refresh token handling
- Token expiration
- User authentication context extraction
"""

import os
import pytest
import time
from unittest.mock import Mock, patch

from aragora.billing.jwt_auth import (
    JWTPayload,
    UserAuthContext,
    TokenPair,
    create_access_token,
    create_refresh_token,
    decode_jwt,
    validate_access_token,
    validate_refresh_token,
    extract_user_from_request,
    create_token_pair,
    _base64url_encode,
    _base64url_decode,
)
from aragora.billing.models import User
from aragora.server.handlers.auth import InMemoryUserStore


class TestBase64UrlEncoding:
    """Tests for base64 URL-safe encoding/decoding."""

    def test_encode_decode_roundtrip(self):
        """Encoding then decoding should return original."""
        original = b"hello world"
        encoded = _base64url_encode(original)
        decoded = _base64url_decode(encoded)
        assert decoded == original

    def test_no_padding_in_encoded(self):
        """Encoded string should not have padding."""
        encoded = _base64url_encode(b"test data")
        assert "=" not in encoded

    def test_url_safe_characters(self):
        """Encoded string should use URL-safe characters."""
        encoded = _base64url_encode(b"binary\x00\xff\xfe data")
        # Should not contain + or /
        assert "+" not in encoded
        assert "/" not in encoded


class TestJWTPayload:
    """Tests for JWTPayload dataclass."""

    def test_payload_creation(self):
        """Should create payload with all fields."""
        now = int(time.time())
        payload = JWTPayload(
            sub="user123",
            email="test@example.com",
            org_id="org456",
            role="admin",
            iat=now,
            exp=now + 3600,
        )

        assert payload.sub == "user123"
        assert payload.email == "test@example.com"
        assert payload.org_id == "org456"
        assert payload.role == "admin"
        assert payload.type == "access"

    def test_user_id_alias(self):
        """user_id should be alias for sub."""
        payload = JWTPayload(
            sub="user123",
            email="",
            org_id=None,
            role="member",
            iat=0,
            exp=0,
        )
        assert payload.user_id == payload.sub == "user123"

    def test_is_expired_false_for_future(self):
        """Token with future expiry should not be expired."""
        future = int(time.time()) + 3600
        payload = JWTPayload(
            sub="user",
            email="",
            org_id=None,
            role="",
            iat=0,
            exp=future,
        )
        assert payload.is_expired is False

    def test_is_expired_true_for_past(self):
        """Token with past expiry should be expired."""
        past = int(time.time()) - 3600
        payload = JWTPayload(
            sub="user",
            email="",
            org_id=None,
            role="",
            iat=0,
            exp=past,
        )
        assert payload.is_expired is True

    def test_to_dict(self):
        """Should convert to dictionary."""
        payload = JWTPayload(
            sub="user123",
            email="test@example.com",
            org_id="org456",
            role="admin",
            iat=1000,
            exp=2000,
            type="access",
        )
        data = payload.to_dict()

        assert data["sub"] == "user123"
        assert data["email"] == "test@example.com"
        assert data["org_id"] == "org456"
        assert data["role"] == "admin"
        assert data["iat"] == 1000
        assert data["exp"] == 2000
        assert data["type"] == "access"

    def test_from_dict(self):
        """Should create from dictionary."""
        data = {
            "sub": "user123",
            "email": "test@example.com",
            "org_id": "org456",
            "role": "admin",
            "iat": 1000,
            "exp": 2000,
            "type": "refresh",
        }
        payload = JWTPayload.from_dict(data)

        assert payload.sub == "user123"
        assert payload.email == "test@example.com"
        assert payload.type == "refresh"


class TestAccessTokenCreation:
    """Tests for access token creation."""

    def test_create_access_token_format(self):
        """Token should have three dot-separated parts."""
        token = create_access_token("user123", "test@example.com")
        parts = token.split(".")
        assert len(parts) == 3

    def test_create_access_token_decodable(self):
        """Created token should be decodable."""
        token = create_access_token(
            "user123",
            "test@example.com",
            org_id="org456",
            role="admin",
        )
        payload = decode_jwt(token)

        assert payload is not None
        assert payload.sub == "user123"
        assert payload.email == "test@example.com"
        assert payload.org_id == "org456"
        assert payload.role == "admin"
        assert payload.type == "access"

    def test_create_access_token_custom_expiry(self):
        """Should respect custom expiry hours."""
        token = create_access_token("user", "email", expiry_hours=1)
        payload = decode_jwt(token)

        # Should expire in about 1 hour
        expected_exp = int(time.time()) + 3600
        assert abs(payload.exp - expected_exp) < 5

    def test_access_token_not_expired_immediately(self):
        """Fresh token should not be expired."""
        token = create_access_token("user", "email")
        payload = decode_jwt(token)
        assert payload.is_expired is False


class TestRefreshTokenCreation:
    """Tests for refresh token creation."""

    def test_create_refresh_token_format(self):
        """Refresh token should have JWT format."""
        token = create_refresh_token("user123")
        parts = token.split(".")
        assert len(parts) == 3

    def test_create_refresh_token_type(self):
        """Refresh token should have type='refresh'."""
        token = create_refresh_token("user123")
        payload = decode_jwt(token)

        assert payload is not None
        assert payload.type == "refresh"
        assert payload.sub == "user123"

    def test_refresh_token_minimal_payload(self):
        """Refresh token should have minimal payload."""
        token = create_refresh_token("user123")
        payload = decode_jwt(token)

        assert payload.email == ""
        assert payload.org_id is None
        assert payload.role == ""


class TestTokenValidation:
    """Tests for token validation."""

    def test_validate_access_token_success(self):
        """Valid access token should validate."""
        token = create_access_token("user", "email")
        payload = validate_access_token(token)

        assert payload is not None
        assert payload.type == "access"

    def test_validate_access_token_rejects_refresh(self):
        """Should reject refresh token as access token."""
        token = create_refresh_token("user")
        payload = validate_access_token(token)
        assert payload is None

    def test_validate_refresh_token_success(self):
        """Valid refresh token should validate."""
        token = create_refresh_token("user")
        payload = validate_refresh_token(token)

        assert payload is not None
        assert payload.type == "refresh"

    def test_validate_refresh_token_rejects_access(self):
        """Should reject access token as refresh token."""
        token = create_access_token("user", "email")
        payload = validate_refresh_token(token)
        assert payload is None

    def test_decode_invalid_format(self):
        """Should reject malformed tokens."""
        assert decode_jwt("not.a.valid.token.at.all") is None
        assert decode_jwt("invalid") is None
        assert decode_jwt("") is None

    def test_decode_invalid_signature(self):
        """Should reject tokens with wrong signature."""
        token = create_access_token("user", "email")
        parts = token.split(".")
        # Tamper with signature
        tampered = f"{parts[0]}.{parts[1]}.invalidsignature"
        assert decode_jwt(tampered) is None

    def test_decode_expired_token(self):
        """Should reject expired tokens."""
        # Create token with minimum expiry
        token = create_access_token("user", "email", expiry_hours=1)

        # Fast-forward time to make token expired
        with patch("aragora.billing.auth.tokens.time") as mock_time:
            # Set time to 2 hours in the future (past the 1-hour expiry)
            mock_time.time.return_value = time.time() + 7200
            payload = decode_jwt(token)

        assert payload is None


class TestUserAuthContext:
    """Tests for UserAuthContext."""

    def test_default_values(self):
        """Should have secure defaults."""
        ctx = UserAuthContext()
        assert ctx.authenticated is False
        assert ctx.user_id is None
        assert ctx.token_type == "none"

    def test_is_authenticated_alias(self):
        """is_authenticated should alias authenticated."""
        ctx = UserAuthContext(authenticated=True)
        assert ctx.is_authenticated is True

    def test_is_owner(self):
        """Should detect owner role."""
        ctx = UserAuthContext(role="owner")
        assert ctx.is_owner is True
        assert ctx.is_admin is True

    def test_is_admin(self):
        """Should detect admin or owner as admin."""
        assert UserAuthContext(role="admin").is_admin is True
        assert UserAuthContext(role="owner").is_admin is True
        assert UserAuthContext(role="member").is_admin is False


class TestExtractUserFromRequest:
    """Tests for extracting auth from requests."""

    def test_no_handler_returns_unauthenticated(self):
        """None handler should return unauthenticated context."""
        ctx = extract_user_from_request(None)
        assert ctx.authenticated is False

    def test_no_auth_header_returns_unauthenticated(self):
        """Missing auth header should return unauthenticated."""
        handler = Mock()
        handler.headers = {}

        with patch("aragora.billing.auth.context.extract_client_ip", return_value="127.0.0.1"):
            ctx = extract_user_from_request(handler)

        assert ctx.authenticated is False
        assert ctx.client_ip == "127.0.0.1"

    def test_bearer_jwt_token_extracts_user(self):
        """Valid Bearer JWT should extract user info."""
        token = create_access_token(
            "user123",
            "test@example.com",
            org_id="org456",
            role="admin",
        )

        handler = Mock()
        handler.headers = {"Authorization": f"Bearer {token}"}

        with patch("aragora.billing.auth.context.extract_client_ip", return_value="127.0.0.1"):
            ctx = extract_user_from_request(handler)

        assert ctx.authenticated is True
        assert ctx.user_id == "user123"
        assert ctx.email == "test@example.com"
        assert ctx.org_id == "org456"
        assert ctx.role == "admin"
        assert ctx.token_type == "access"

    def test_bearer_api_key_validates_store(self):
        """Bearer with API key should validate against user store."""
        store = InMemoryUserStore()
        user = User(email="test@example.com")
        api_key = user.generate_api_key()
        store.save_user(user)

        handler = Mock()
        handler.headers = {"Authorization": f"Bearer {api_key}"}

        with patch("aragora.billing.auth.context.extract_client_ip", return_value="127.0.0.1"):
            ctx = extract_user_from_request(handler, store)

        assert ctx.authenticated is True
        assert ctx.user_id == user.id
        assert ctx.token_type == "api_key"

    def test_bearer_api_key_requires_store_by_default(self):
        """Bearer API key should require a user store unless explicitly allowed."""
        handler = Mock()
        handler.headers = {"Authorization": "Bearer ara_validapikeywithsufficient_length"}

        with patch.dict(os.environ, {"ARAGORA_ALLOW_FORMAT_ONLY_API_KEYS": "0"}):
            with patch("aragora.billing.auth.context.extract_client_ip", return_value="127.0.0.1"):
                ctx = extract_user_from_request(handler)

        assert ctx.authenticated is False

    def test_invalid_api_key_format_rejected(self):
        """Short or invalid API key should be rejected."""
        handler = Mock()
        handler.headers = {"Authorization": "Bearer ara_short"}

        with patch("aragora.billing.auth.context.extract_client_ip", return_value="127.0.0.1"):
            ctx = extract_user_from_request(handler)

        assert ctx.authenticated is False


class TestTokenPair:
    """Tests for TokenPair class."""

    def test_token_pair_creation(self):
        """Should create token pair with both tokens."""
        pair = TokenPair("access_token", "refresh_token")
        assert pair.access_token == "access_token"
        assert pair.refresh_token == "refresh_token"
        assert pair.token_type == "Bearer"

    def test_token_pair_to_dict(self):
        """Should serialize to dict for API response."""
        pair = TokenPair("access", "refresh")
        data = pair.to_dict()

        assert data["access_token"] == "access"
        assert data["refresh_token"] == "refresh"
        assert data["token_type"] == "Bearer"
        assert "expires_in" in data

    def test_create_token_pair_function(self):
        """create_token_pair should create valid pair."""
        pair = create_token_pair(
            "user123",
            "test@example.com",
            org_id="org456",
            role="admin",
        )

        # Both tokens should be valid
        access = validate_access_token(pair.access_token)
        refresh = validate_refresh_token(pair.refresh_token)

        assert access is not None
        assert access.sub == "user123"
        assert refresh is not None
        assert refresh.sub == "user123"
