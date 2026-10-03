"""
Reconnection Token System.

Provides cryptographic token generation and validation for:
- Voice session reconnection
- Device push token management
- Session migration across nodes

The token system uses:
- Cryptographically secure random tokens
- Redis-backed storage for distributed validation
- Configurable TTL with refresh support
- HMAC-based token signing for integrity

Usage:
    from aragora.server.tokens import TokenManager, TokenConfig

    config = TokenConfig(ttl_seconds=300, secret_key="...")
    manager = TokenManager(config)

    # Generate a reconnection token
    token = await manager.generate_token(
        session_id="sess-123",
        user_id="user-456",
        token_type=TokenType.VOICE_RECONNECT,
    )

    # Validate and retrieve token data
    data = await manager.validate_token(token.token)
    if data:
        print(f"Valid token for session: {data.session_id}")

    # Refresh token TTL
    await manager.refresh_token(token.token)

    # Revoke token
    await manager.revoke_token(token.token)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, cast

logger = logging.getLogger(__name__)


class TokenType(Enum):
    """Types of reconnection tokens."""

    VOICE_RECONNECT = "voice_reconnect"
    DEVICE_PUSH = "device_push"
    SESSION_MIGRATE = "session_migrate"
    WEBSOCKET_RECONNECT = "websocket_reconnect"


@dataclass
class TokenConfig:
    """Configuration for token management."""

    # Default TTL for tokens (5 minutes)
    ttl_seconds: float = 300.0

    # Secret key for HMAC signing (auto-generated if not provided)
    secret_key: str | None = None

    # Token length in bytes (before hex encoding)
    token_bytes: int = 32

    # Maximum tokens per session
    max_tokens_per_session: int = 5

    # Redis key prefix
    key_prefix: str = "aragora:tokens:"

    # Enable Redis storage (falls back to in-memory if unavailable)
    use_redis: bool = True

    def __post_init__(self) -> None:
        """Generate secret key if not provided."""
        if self.secret_key is None:
            self.secret_key = secrets.token_hex(32)


@dataclass
class TokenData:
    """Data associated with a token."""

    token: str
    session_id: str
    user_id: str
    token_type: TokenType
    created_at: datetime
    expires_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if token has expired."""
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def ttl_remaining(self) -> float:
        """Get remaining TTL in seconds."""
        delta = self.expires_at - datetime.now(timezone.utc)
        return max(0, delta.total_seconds())

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "token": self.token,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "token_type": self.token_type.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenData:
        """Deserialize from dictionary."""
        return cls(
            token=data["token"],
            session_id=data["session_id"],
            user_id=data["user_id"],
            token_type=TokenType(data["token_type"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            metadata=data.get("metadata", {}),
        )


class TokenManager:
    """
    Manages reconnection tokens with Redis-backed or in-memory storage.

    Provides:
    - Cryptographically secure token generation
    - HMAC-based token signing for integrity
    - TTL-based expiration with refresh support
    - Distributed validation via Redis
    """

    def __init__(self, config: TokenConfig | None = None):
        """
        Initialize the token manager.

        Args:
            config: Token configuration (uses defaults if not provided)
        """
        self.config = config or TokenConfig()
        self._redis: Any | None = None
        self._redis_available = False
        self._local_store: dict[str, TokenData] = {}
        self._lock = asyncio.Lock()

    async def _get_redis(self) -> Any | None:
        """Get Redis connection if available."""
        if not self.config.use_redis:
            return None

        if self._redis is not None:
            return self._redis if self._redis_available else None

        try:
            import redis.asyncio as redis

            self._redis = redis.from_url(
                "redis://localhost:6379",
                decode_responses=True,
            )
            # Test connection
            await cast(Any, self._redis.ping())
            self._redis_available = True
            logger.debug("Token manager connected to Redis")
            return self._redis
        except ImportError:
            logger.debug("Redis not available, using in-memory storage")
            self._redis_available = False
            return None
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.debug("Redis connection failed: %s, using in-memory storage", e)
            self._redis_available = False
            return None

    def _generate_token_string(self) -> str:
        """Generate a cryptographically secure token string."""
        return secrets.token_hex(self.config.token_bytes)

    def _sign_token(self, token: str, session_id: str, user_id: str) -> str:
        """Sign a token with HMAC for integrity verification."""
        message = f"{token}:{session_id}:{user_id}"
        signature = hmac.new(
            self.config.secret_key.encode() if self.config.secret_key else b"",
            message.encode(),
            hashlib.sha256,
        ).hexdigest()  # Full 256-bit signature for proper collision resistance
        return f"{token}.{signature}"

    def _verify_signature(self, signed_token: str, session_id: str, user_id: str) -> bool:
        """Verify token signature."""
        if "." not in signed_token:
            return False

        token, signature = signed_token.rsplit(".", 1)
        expected = self._sign_token(token, session_id, user_id)
        expected_sig = expected.rsplit(".", 1)[1]

        return hmac.compare_digest(signature, expected_sig)

    async def generate_token(
        self,
        session_id: str,
        user_id: str,
        token_type: TokenType,
        ttl_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TokenData:
        """
        Generate a new reconnection token.

        Args:
            session_id: Associated session ID
            user_id: Associated user ID
            token_type: Type of token
            ttl_seconds: Custom TTL (uses config default if not provided)
            metadata: Additional data to store with token

        Returns:
            TokenData with the generated token
        """
        ttl = ttl_seconds or self.config.ttl_seconds
        now = datetime.now(timezone.utc)

        # Generate and sign token
        raw_token = self._generate_token_string()
        signed_token = self._sign_token(raw_token, session_id, user_id)

        token_data = TokenData(
            token=signed_token,
            session_id=session_id,
            user_id=user_id,
            token_type=token_type,
            created_at=now,
            expires_at=datetime.fromtimestamp(now.timestamp() + ttl, tz=timezone.utc),
            metadata=metadata or {},
        )

        # Store token
        redis_client = await self._get_redis()
        if redis_client:
            key = f"{self.config.key_prefix}{signed_token}"
            import json

            await redis_client.setex(
                key,
                int(ttl),
                json.dumps(token_data.to_dict()),
            )
        else:
            async with self._lock:
                self._local_store[signed_token] = token_data
                # Cleanup expired tokens
                self._cleanup_expired()

        logger.debug(
            "Generated %s token for session %s, expires in %ss", token_type.value, session_id, ttl
        )

        return token_data

    async def validate_token(
        self,
        token: str,
        expected_type: TokenType | None = None,
    ) -> TokenData | None:
        """
        Validate a token and return its data.

        Args:
            token: The token to validate
            expected_type: Optional expected token type

        Returns:
            TokenData if valid, None otherwise
        """
        redis_client = await self._get_redis()
        token_data: TokenData | None

        if redis_client:
            key = f"{self.config.key_prefix}{token}"
            import json

            data_str = await redis_client.get(key)
            if not data_str:
                return None

            try:
                token_data = TokenData.from_dict(json.loads(data_str))
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning("Invalid token data: %s", e)
                return None
        else:
            async with self._lock:
                token_data = self._local_store.get(token)
                if token_data is None:
                    return None

        # Check expiration
        if token_data.is_expired:
            await self.revoke_token(token)
            return None

        # Verify signature
        if not self._verify_signature(token, token_data.session_id, token_data.user_id):
            logger.warning("Token signature verification failed")
            return None

        # Check type if specified
        if expected_type and token_data.token_type != expected_type:
            logger.debug(
                "Token type mismatch: expected %s, got %s",
                expected_type.value,
                token_data.token_type.value,
            )
            return None

        return token_data

    async def refresh_token(
        self,
        token: str,
        ttl_seconds: float | None = None,
    ) -> bool:
        """
        Refresh a token's TTL.

        Args:
            token: The token to refresh
            ttl_seconds: New TTL (uses config default if not provided)

        Returns:
            True if refreshed, False if token not found or expired
        """
        token_data = await self.validate_token(token)
        if not token_data:
            return False

        ttl = ttl_seconds or self.config.ttl_seconds
        new_expires = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + ttl,
            tz=timezone.utc,
        )

        token_data.expires_at = new_expires

        redis_client = await self._get_redis()
        if redis_client:
            key = f"{self.config.key_prefix}{token}"
            import json

            await redis_client.setex(
                key,
                int(ttl),
                json.dumps(token_data.to_dict()),
            )
        else:
            async with self._lock:
                self._local_store[token] = token_data

        logger.debug("Refreshed token, new TTL: %ss", ttl)
        return True

    async def revoke_token(self, token: str) -> bool:
        """
        Revoke a token.

        Args:
            token: The token to revoke

        Returns:
            True if revoked, False if not found
        """
        redis_client = await self._get_redis()

        if redis_client:
            key = f"{self.config.key_prefix}{token}"
            result = await redis_client.delete(key)
            return result > 0
        else:
            async with self._lock:
                if token in self._local_store:
                    del self._local_store[token]
                    return True
                return False

    async def revoke_session_tokens(
        self,
        session_id: str,
        token_type: TokenType | None = None,
    ) -> int:
        """
        Revoke all tokens for a session.

        Args:
            session_id: Session ID to revoke tokens for
            token_type: Optional type filter

        Returns:
            Number of tokens revoked
        """
        revoked = 0
        redis_client = await self._get_redis()

        if redis_client:
            # Scan for tokens (less efficient but necessary for pattern matching)
            cursor = 0
            pattern = f"{self.config.key_prefix}*"
            import json

            while True:
                cursor, keys = await redis_client.scan(cursor, match=pattern, count=100)

                for key in keys:
                    data_str = await redis_client.get(key)
                    if data_str:
                        try:
                            data = json.loads(data_str)
                            if data.get("session_id") == session_id:
                                if token_type is None or data.get("token_type") == token_type.value:
                                    await redis_client.delete(key)
                                    revoked += 1
                        except (json.JSONDecodeError, KeyError):
                            pass

                if cursor == 0:
                    break
        else:
            async with self._lock:
                to_revoke = [
                    token
                    for token, data in self._local_store.items()
                    if data.session_id == session_id
                    and (token_type is None or data.token_type == token_type)
                ]
                for token in to_revoke:
                    del self._local_store[token]
                revoked = len(to_revoke)

        logger.debug("Revoked %s tokens for session %s", revoked, session_id)
        return revoked

    def _cleanup_expired(self) -> None:
        """Cleanup expired tokens from local store."""
        now = datetime.now(timezone.utc)
        expired = [token for token, data in self._local_store.items() if data.expires_at < now]
        for token in expired:
            del self._local_store[token]

        if expired:
            logger.debug("Cleaned up %s expired tokens", len(expired))

    async def get_session_tokens(
        self,
        session_id: str,
        token_type: TokenType | None = None,
    ) -> list[TokenData]:
        """
        Get all valid tokens for a session.

        Args:
            session_id: Session ID to get tokens for
            token_type: Optional type filter

        Returns:
            List of TokenData for the session
        """
        tokens = []
        redis_client = await self._get_redis()

        if redis_client:
            cursor = 0
            pattern = f"{self.config.key_prefix}*"
            import json

            while True:
                cursor, keys = await redis_client.scan(cursor, match=pattern, count=100)

                for key in keys:
                    data_str = await redis_client.get(key)
                    if data_str:
                        try:
                            data = TokenData.from_dict(json.loads(data_str))
                            if data.session_id == session_id and not data.is_expired:
                                if token_type is None or data.token_type == token_type:
                                    tokens.append(data)
                        except (json.JSONDecodeError, KeyError, ValueError):
                            pass

                if cursor == 0:
                    break
        else:
            async with self._lock:
                self._cleanup_expired()
                tokens = [
                    data
                    for data in self._local_store.values()
                    if data.session_id == session_id
                    and (token_type is None or data.token_type == token_type)
                ]

        return tokens


# Global token manager instance
_token_manager: TokenManager | None = None


def get_token_manager() -> TokenManager:
    """Get or create the global token manager instance."""
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager()
    return _token_manager


async def init_token_manager(config: TokenConfig | None = None) -> TokenManager:
    """
    Initialize the global token manager with custom config.

    Args:
        config: Optional token configuration

    Returns:
        The initialized TokenManager
    """
    global _token_manager
    _token_manager = TokenManager(config)
    # Test Redis connection
    await _token_manager._get_redis()
    return _token_manager
