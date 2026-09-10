"""Test utilities for the Aragora test suite.

This module provides fundamental primitives for test infrastructure:

- managed_fixture: Universal cleanup for fixtures with resources
- run_with_timeout: Async operations with timeout and clear errors
- gather_with_timeout: Multiple async operations with shared timeout

These utilities solve common test infrastructure issues:
1. Resource leaks from fixtures without cleanup
2. Tests hanging indefinitely on async operations
3. Unclear error messages on timeouts
"""

from tests.utils.aiohttp_mocks import (
    make_async_context_manager,
    make_mock_client_session,
    make_mock_response,
)
from tests.utils.async_helpers import (
    DEFAULT_TIMEOUT,
    AsyncTestContext,
    close_coroutine_then,
    gather_with_timeout,
    run_with_cancellation,
    run_with_timeout,
)
from tests.utils.managed_resources import (
    managed_async_fixture,
    managed_fixture,
)
from tests.utils.state_reset import (
    clear_all_auth_rate_limiters,
    invalidate_legacy_config_module,
    reset_permission_checker_override,
    restore_legacy_config_module,
    restore_rbac_context_extractor,
    unset_env_vars,
)

__all__ = [
    # Resource management
    "managed_fixture",
    "managed_async_fixture",
    # Async helpers
    "DEFAULT_TIMEOUT",
    "run_with_timeout",
    "run_with_cancellation",
    "gather_with_timeout",
    "AsyncTestContext",
    "close_coroutine_then",
    # aiohttp mock builders (see aiohttp_mocks.py for the __aexit__ gotcha)
    "make_async_context_manager",
    "make_mock_client_session",
    "make_mock_response",
    # State reset helpers
    "unset_env_vars",
    "invalidate_legacy_config_module",
    "restore_legacy_config_module",
    "clear_all_auth_rate_limiters",
    "reset_permission_checker_override",
    "restore_rbac_context_extractor",
]
