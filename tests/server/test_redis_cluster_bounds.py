"""
Tests for Redis cluster configuration bounds validation.

Validates that ClusterConfig properly enforces bounds on:
- max_connections_per_node: [1, 500]
- socket_timeout: [1.0, 300.0]
- socket_connect_timeout: [1.0, 60.0]
- health_check_interval: [5.0, 300.0]
"""

import logging
import os
import pytest
from unittest.mock import patch

from aragora.storage.redis_cluster import ClusterConfig, get_cluster_config


class TestMaxConnectionsBounds:
    """Tests for max_connections_per_node bounds validation."""

    def test_max_connections_within_bounds(self):
        """Test that valid max_connections values are accepted."""
        config = ClusterConfig(max_connections_per_node=32)
        assert config.max_connections_per_node == 32

        config = ClusterConfig(max_connections_per_node=1)
        assert config.max_connections_per_node == 1

        config = ClusterConfig(max_connections_per_node=500)
        assert config.max_connections_per_node == 500

    def test_max_connections_below_minimum_clamped(self):
        """Test that max_connections below minimum is clamped to 1."""
        config = ClusterConfig(max_connections_per_node=0)
        assert config.max_connections_per_node == 1

        config = ClusterConfig(max_connections_per_node=-10)
        assert config.max_connections_per_node == 1

    def test_max_connections_above_maximum_clamped(self):
        """Test that max_connections above maximum is clamped to 500."""
        config = ClusterConfig(max_connections_per_node=501)
        assert config.max_connections_per_node == 500

        config = ClusterConfig(max_connections_per_node=1000)
        assert config.max_connections_per_node == 500

    def test_max_connections_logs_warning_when_out_of_bounds(self, caplog):
        """Test that out-of-bounds max_connections logs a warning."""
        with caplog.at_level(logging.WARNING):
            ClusterConfig(max_connections_per_node=0)

        assert "max_connections_per_node=0 out of bounds" in caplog.text

        caplog.clear()
        with caplog.at_level(logging.WARNING):
            ClusterConfig(max_connections_per_node=1000)

        assert "max_connections_per_node=1000 out of bounds" in caplog.text


class TestSocketTimeoutBounds:
    """Tests for socket_timeout bounds validation."""

    def test_socket_timeout_within_bounds(self):
        """Test that valid socket_timeout values are accepted."""
        config = ClusterConfig(socket_timeout=5.0)
        assert config.socket_timeout == 5.0

        config = ClusterConfig(socket_timeout=1.0)
        assert config.socket_timeout == 1.0

        config = ClusterConfig(socket_timeout=300.0)
        assert config.socket_timeout == 300.0

    def test_socket_timeout_below_minimum_clamped(self):
        """Test that socket_timeout below minimum is clamped to 1.0."""
        config = ClusterConfig(socket_timeout=0.5)
        assert config.socket_timeout == 1.0

        config = ClusterConfig(socket_timeout=0.0)
        assert config.socket_timeout == 1.0

        config = ClusterConfig(socket_timeout=-1.0)
        assert config.socket_timeout == 1.0

    def test_socket_timeout_above_maximum_clamped(self):
        """Test that socket_timeout above maximum is clamped to 300.0."""
        config = ClusterConfig(socket_timeout=301.0)
        assert config.socket_timeout == 300.0

        config = ClusterConfig(socket_timeout=1000.0)
        assert config.socket_timeout == 300.0

    def test_socket_timeout_logs_warning_when_out_of_bounds(self, caplog):
        """Test that out-of-bounds socket_timeout logs a warning."""
        with caplog.at_level(logging.WARNING):
            ClusterConfig(socket_timeout=0.5)

        assert "socket_timeout=0.5 out of bounds" in caplog.text

        caplog.clear()
        with caplog.at_level(logging.WARNING):
            ClusterConfig(socket_timeout=500.0)

        assert "socket_timeout=500.0 out of bounds" in caplog.text


class TestSocketConnectTimeoutBounds:
    """Tests for socket_connect_timeout bounds validation."""

    def test_socket_connect_timeout_within_bounds(self):
        """Test that valid socket_connect_timeout values are accepted."""
        config = ClusterConfig(socket_connect_timeout=5.0)
        assert config.socket_connect_timeout == 5.0

        config = ClusterConfig(socket_connect_timeout=1.0)
        assert config.socket_connect_timeout == 1.0

        config = ClusterConfig(socket_connect_timeout=60.0)
        assert config.socket_connect_timeout == 60.0

    def test_socket_connect_timeout_below_minimum_clamped(self):
        """Test that socket_connect_timeout below minimum is clamped to 1.0."""
        config = ClusterConfig(socket_connect_timeout=0.5)
        assert config.socket_connect_timeout == 1.0

        config = ClusterConfig(socket_connect_timeout=0.0)
        assert config.socket_connect_timeout == 1.0

    def test_socket_connect_timeout_above_maximum_clamped(self):
        """Test that socket_connect_timeout above maximum is clamped to 60.0."""
        config = ClusterConfig(socket_connect_timeout=61.0)
        assert config.socket_connect_timeout == 60.0

        config = ClusterConfig(socket_connect_timeout=100.0)
        assert config.socket_connect_timeout == 60.0

    def test_socket_connect_timeout_logs_warning_when_out_of_bounds(self, caplog):
        """Test that out-of-bounds socket_connect_timeout logs a warning."""
        with caplog.at_level(logging.WARNING):
            ClusterConfig(socket_connect_timeout=0.1)

        assert "socket_connect_timeout=0.1 out of bounds" in caplog.text

        caplog.clear()
        with caplog.at_level(logging.WARNING):
            ClusterConfig(socket_connect_timeout=120.0)

        assert "socket_connect_timeout=120.0 out of bounds" in caplog.text


class TestHealthCheckIntervalBounds:
    """Tests for health_check_interval bounds validation."""

    def test_health_check_interval_within_bounds(self):
        """Test that valid health_check_interval values are accepted."""
        config = ClusterConfig(health_check_interval=30.0)
        assert config.health_check_interval == 30.0

        config = ClusterConfig(health_check_interval=5.0)
        assert config.health_check_interval == 5.0

        config = ClusterConfig(health_check_interval=300.0)
        assert config.health_check_interval == 300.0

    def test_health_check_interval_below_minimum_clamped(self):
        """Test that health_check_interval below minimum is clamped to 5.0."""
        config = ClusterConfig(health_check_interval=4.0)
        assert config.health_check_interval == 5.0

        config = ClusterConfig(health_check_interval=1.0)
        assert config.health_check_interval == 5.0

        config = ClusterConfig(health_check_interval=0.0)
        assert config.health_check_interval == 5.0

    def test_health_check_interval_above_maximum_clamped(self):
        """Test that health_check_interval above maximum is clamped to 300.0."""
        config = ClusterConfig(health_check_interval=301.0)
        assert config.health_check_interval == 300.0

        config = ClusterConfig(health_check_interval=600.0)
        assert config.health_check_interval == 300.0

    def test_health_check_interval_logs_warning_when_out_of_bounds(self, caplog):
        """Test that out-of-bounds health_check_interval logs a warning."""
        with caplog.at_level(logging.WARNING):
            ClusterConfig(health_check_interval=1.0)

        assert "health_check_interval=1.0 out of bounds" in caplog.text

        caplog.clear()
        with caplog.at_level(logging.WARNING):
            ClusterConfig(health_check_interval=500.0)

        assert "health_check_interval=500.0 out of bounds" in caplog.text


class TestGetClusterConfigBounds:
    """Tests for get_cluster_config() bounds validation from environment variables."""

    def test_get_cluster_config_clamps_max_connections(self, caplog):
        """Test that get_cluster_config clamps out-of-bounds max_connections."""
        with patch.dict(
            os.environ,
            {"ARAGORA_REDIS_CLUSTER_MAX_CONNECTIONS": "1000"},
            clear=False,
        ):
            with caplog.at_level(logging.WARNING):
                config = get_cluster_config()
            assert config.max_connections_per_node == 500
            assert "max_connections_per_node=1000 out of bounds" in caplog.text

    def test_get_cluster_config_clamps_socket_timeout(self, caplog):
        """Test that get_cluster_config clamps out-of-bounds socket_timeout."""
        with patch.dict(
            os.environ,
            {"ARAGORA_REDIS_SOCKET_TIMEOUT": "0.1"},
            clear=False,
        ):
            with caplog.at_level(logging.WARNING):
                config = get_cluster_config()
            assert config.socket_timeout == 1.0
            assert "socket_timeout=0.1 out of bounds" in caplog.text

    def test_get_cluster_config_clamps_socket_connect_timeout(self, caplog):
        """Test that get_cluster_config clamps out-of-bounds socket_connect_timeout."""
        with patch.dict(
            os.environ,
            {"ARAGORA_REDIS_SOCKET_CONNECT_TIMEOUT": "100.0"},
            clear=False,
        ):
            with caplog.at_level(logging.WARNING):
                config = get_cluster_config()
            assert config.socket_connect_timeout == 60.0
            assert "socket_connect_timeout=100.0 out of bounds" in caplog.text

    def test_get_cluster_config_clamps_health_check_interval(self, caplog):
        """Test that get_cluster_config clamps out-of-bounds health_check_interval."""
        with patch.dict(
            os.environ,
            {"ARAGORA_REDIS_HEALTH_CHECK_INTERVAL": "1.0"},
            clear=False,
        ):
            with caplog.at_level(logging.WARNING):
                config = get_cluster_config()
            assert config.health_check_interval == 5.0
            assert "health_check_interval=1.0 out of bounds" in caplog.text

    def test_get_cluster_config_valid_env_values_no_warnings(self, caplog):
        """Test that valid env values do not produce warnings."""
        with patch.dict(
            os.environ,
            {
                "ARAGORA_REDIS_CLUSTER_MAX_CONNECTIONS": "64",
                "ARAGORA_REDIS_SOCKET_TIMEOUT": "10.0",
                "ARAGORA_REDIS_SOCKET_CONNECT_TIMEOUT": "5.0",
                "ARAGORA_REDIS_HEALTH_CHECK_INTERVAL": "30.0",
            },
            clear=False,
        ):
            with caplog.at_level(logging.WARNING):
                config = get_cluster_config()

            assert config.max_connections_per_node == 64
            assert config.socket_timeout == 10.0
            assert config.socket_connect_timeout == 5.0
            assert config.health_check_interval == 30.0
            # No bounds warnings should be logged
            assert "out of bounds" not in caplog.text


class TestMultipleBoundsViolations:
    """Tests for multiple simultaneous bounds violations."""

    def test_multiple_violations_all_clamped(self, caplog):
        """Test that multiple out-of-bounds values are all clamped correctly."""
        with caplog.at_level(logging.WARNING):
            config = ClusterConfig(
                max_connections_per_node=0,
                socket_timeout=0.1,
                socket_connect_timeout=0.1,
                health_check_interval=1.0,
            )

        # All values should be clamped to their minimums
        assert config.max_connections_per_node == 1
        assert config.socket_timeout == 1.0
        assert config.socket_connect_timeout == 1.0
        assert config.health_check_interval == 5.0

        # All warnings should be logged
        assert "max_connections_per_node=0 out of bounds" in caplog.text
        assert "socket_timeout=0.1 out of bounds" in caplog.text
        assert "socket_connect_timeout=0.1 out of bounds" in caplog.text
        assert "health_check_interval=1.0 out of bounds" in caplog.text

    def test_multiple_violations_from_env(self, caplog):
        """Test that multiple out-of-bounds env values are all clamped."""
        with patch.dict(
            os.environ,
            {
                "ARAGORA_REDIS_CLUSTER_MAX_CONNECTIONS": "0",
                "ARAGORA_REDIS_SOCKET_TIMEOUT": "500.0",
                "ARAGORA_REDIS_SOCKET_CONNECT_TIMEOUT": "100.0",
                "ARAGORA_REDIS_HEALTH_CHECK_INTERVAL": "1000.0",
            },
            clear=False,
        ):
            with caplog.at_level(logging.WARNING):
                config = get_cluster_config()

            # All values should be clamped appropriately
            assert config.max_connections_per_node == 1
            assert config.socket_timeout == 300.0
            assert config.socket_connect_timeout == 60.0
            assert config.health_check_interval == 300.0


class TestBoundsEdgeCases:
    """Tests for edge cases in bounds validation."""

    def test_exact_boundary_values_accepted(self):
        """Test that exact boundary values are accepted without warnings."""
        # Test all minimum boundaries
        config_min = ClusterConfig(
            max_connections_per_node=1,
            socket_timeout=1.0,
            socket_connect_timeout=1.0,
            health_check_interval=5.0,
        )
        assert config_min.max_connections_per_node == 1
        assert config_min.socket_timeout == 1.0
        assert config_min.socket_connect_timeout == 1.0
        assert config_min.health_check_interval == 5.0

        # Test all maximum boundaries
        config_max = ClusterConfig(
            max_connections_per_node=500,
            socket_timeout=300.0,
            socket_connect_timeout=60.0,
            health_check_interval=300.0,
        )
        assert config_max.max_connections_per_node == 500
        assert config_max.socket_timeout == 300.0
        assert config_max.socket_connect_timeout == 60.0
        assert config_max.health_check_interval == 300.0

    def test_exact_boundary_values_no_warnings(self, caplog):
        """Test that exact boundary values do not produce warnings."""
        with caplog.at_level(logging.WARNING):
            ClusterConfig(
                max_connections_per_node=1,
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
                health_check_interval=5.0,
            )
            ClusterConfig(
                max_connections_per_node=500,
                socket_timeout=300.0,
                socket_connect_timeout=60.0,
                health_check_interval=300.0,
            )

        assert "out of bounds" not in caplog.text

    def test_negative_values_clamped_to_minimum(self):
        """Test that negative values are clamped to minimum."""
        config = ClusterConfig(
            max_connections_per_node=-100,
            socket_timeout=-10.0,
            socket_connect_timeout=-5.0,
            health_check_interval=-50.0,
        )
        assert config.max_connections_per_node == 1
        assert config.socket_timeout == 1.0
        assert config.socket_connect_timeout == 1.0
        assert config.health_check_interval == 5.0
