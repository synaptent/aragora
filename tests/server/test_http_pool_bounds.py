"""Tests for HTTP pool and rate limit configuration bounds validation."""

import pytest

from aragora.observability.http_client_pool import HTTPPoolConfig
from aragora.server.rate_limit_redis import RedisConfig


class TestHTTPPoolConfigBounds:
    """Test HTTPPoolConfig bounds validation."""

    def test_pool_size_valid_min(self):
        """Test pool_size accepts minimum valid value."""
        config = HTTPPoolConfig(pool_size=1)
        assert config.pool_size == 1

    def test_pool_size_valid_max(self):
        """Test pool_size accepts maximum valid value."""
        config = HTTPPoolConfig(pool_size=1000)
        assert config.pool_size == 1000

    def test_pool_size_below_min(self):
        """Test pool_size rejects value below minimum."""
        with pytest.raises(ValueError, match="pool_size must be between 1 and 1000"):
            HTTPPoolConfig(pool_size=0)

    def test_pool_size_above_max(self):
        """Test pool_size rejects value above maximum."""
        with pytest.raises(ValueError, match="pool_size must be between 1 and 1000"):
            HTTPPoolConfig(pool_size=1001)

    def test_connect_timeout_valid_min(self):
        """Test connect_timeout accepts minimum valid value."""
        config = HTTPPoolConfig(connect_timeout=1.0)
        assert config.connect_timeout == 1.0

    def test_connect_timeout_valid_max(self):
        """Test connect_timeout accepts maximum valid value."""
        config = HTTPPoolConfig(connect_timeout=60.0)
        assert config.connect_timeout == 60.0

    def test_connect_timeout_below_min(self):
        """Test connect_timeout rejects value below minimum."""
        with pytest.raises(ValueError, match="connect_timeout must be between 1.0 and 60.0"):
            HTTPPoolConfig(connect_timeout=0.5)

    def test_connect_timeout_above_max(self):
        """Test connect_timeout rejects value above maximum."""
        with pytest.raises(ValueError, match="connect_timeout must be between 1.0 and 60.0"):
            HTTPPoolConfig(connect_timeout=61.0)

    def test_read_timeout_valid_min(self):
        """Test read_timeout accepts minimum valid value."""
        config = HTTPPoolConfig(read_timeout=1.0)
        assert config.read_timeout == 1.0

    def test_read_timeout_valid_max(self):
        """Test read_timeout accepts maximum valid value."""
        config = HTTPPoolConfig(read_timeout=300.0)
        assert config.read_timeout == 300.0

    def test_read_timeout_below_min(self):
        """Test read_timeout rejects value below minimum."""
        with pytest.raises(ValueError, match="read_timeout must be between 1.0 and 300.0"):
            HTTPPoolConfig(read_timeout=0.5)

    def test_read_timeout_above_max(self):
        """Test read_timeout rejects value above maximum."""
        with pytest.raises(ValueError, match="read_timeout must be between 1.0 and 300.0"):
            HTTPPoolConfig(read_timeout=301.0)

    def test_keepalive_timeout_valid_min(self):
        """Test keepalive_timeout accepts minimum valid value."""
        config = HTTPPoolConfig(keepalive_timeout=1.0)
        assert config.keepalive_timeout == 1.0

    def test_keepalive_timeout_valid_max(self):
        """Test keepalive_timeout accepts maximum valid value."""
        config = HTTPPoolConfig(keepalive_timeout=120.0)
        assert config.keepalive_timeout == 120.0

    def test_keepalive_timeout_below_min(self):
        """Test keepalive_timeout rejects value below minimum."""
        with pytest.raises(ValueError, match="keepalive_timeout must be between 1.0 and 120.0"):
            HTTPPoolConfig(keepalive_timeout=0.5)

    def test_keepalive_timeout_above_max(self):
        """Test keepalive_timeout rejects value above maximum."""
        with pytest.raises(ValueError, match="keepalive_timeout must be between 1.0 and 120.0"):
            HTTPPoolConfig(keepalive_timeout=121.0)

    def test_max_retries_valid_min(self):
        """Test max_retries accepts minimum valid value."""
        config = HTTPPoolConfig(max_retries=0)
        assert config.max_retries == 0

    def test_max_retries_valid_max(self):
        """Test max_retries accepts maximum valid value."""
        config = HTTPPoolConfig(max_retries=10)
        assert config.max_retries == 10

    def test_max_retries_below_min(self):
        """Test max_retries rejects value below minimum."""
        with pytest.raises(ValueError, match="max_retries must be between 0 and 10"):
            HTTPPoolConfig(max_retries=-1)

    def test_max_retries_above_max(self):
        """Test max_retries rejects value above maximum."""
        with pytest.raises(ValueError, match="max_retries must be between 0 and 10"):
            HTTPPoolConfig(max_retries=11)

    def test_default_config_valid(self):
        """Test default configuration passes validation."""
        config = HTTPPoolConfig()
        assert config.pool_size == 20
        assert config.connect_timeout == 10.0
        assert config.read_timeout == 60.0
        assert config.keepalive_timeout == 30.0
        assert config.max_retries == 3


class TestRedisConfigBounds:
    """Test RedisConfig bounds validation."""

    def test_default_limit_valid_min(self):
        """Test default_limit accepts minimum valid value."""
        config = RedisConfig(default_limit=1)
        assert config.default_limit == 1

    def test_default_limit_valid_max(self):
        """Test default_limit accepts maximum valid value."""
        config = RedisConfig(default_limit=100000)
        assert config.default_limit == 100000

    def test_default_limit_below_min(self):
        """Test default_limit rejects value below minimum."""
        with pytest.raises(ValueError, match="default_limit must be between 1 and 100000"):
            RedisConfig(default_limit=0)

    def test_default_limit_above_max(self):
        """Test default_limit rejects value above maximum."""
        with pytest.raises(ValueError, match="default_limit must be between 1 and 100000"):
            RedisConfig(default_limit=100001)

    def test_ip_limit_valid_min(self):
        """Test ip_limit accepts minimum valid value."""
        config = RedisConfig(ip_limit=1)
        assert config.ip_limit == 1

    def test_ip_limit_valid_max(self):
        """Test ip_limit accepts maximum valid value."""
        config = RedisConfig(ip_limit=100000)
        assert config.ip_limit == 100000

    def test_ip_limit_below_min(self):
        """Test ip_limit rejects value below minimum."""
        with pytest.raises(ValueError, match="ip_limit must be between 1 and 100000"):
            RedisConfig(ip_limit=0)

    def test_ip_limit_above_max(self):
        """Test ip_limit rejects value above maximum."""
        with pytest.raises(ValueError, match="ip_limit must be between 1 and 100000"):
            RedisConfig(ip_limit=100001)

    def test_burst_multiplier_valid_min(self):
        """Test burst_multiplier accepts minimum valid value."""
        config = RedisConfig(burst_multiplier=1.0)
        assert config.burst_multiplier == 1.0

    def test_burst_multiplier_valid_max(self):
        """Test burst_multiplier accepts maximum valid value."""
        config = RedisConfig(burst_multiplier=10.0)
        assert config.burst_multiplier == 10.0

    def test_burst_multiplier_below_min(self):
        """Test burst_multiplier rejects value below minimum."""
        with pytest.raises(ValueError, match="burst_multiplier must be between 1.0 and 10.0"):
            RedisConfig(burst_multiplier=0.5)

    def test_burst_multiplier_above_max(self):
        """Test burst_multiplier rejects value above maximum."""
        with pytest.raises(ValueError, match="burst_multiplier must be between 1.0 and 10.0"):
            RedisConfig(burst_multiplier=11.0)

    def test_default_config_valid(self):
        """Test default configuration passes validation."""
        config = RedisConfig()
        # Default values should be within bounds
        assert 1 <= config.default_limit <= 100000
        assert 1 <= config.ip_limit <= 100000
        assert 1.0 <= config.burst_multiplier <= 10.0
