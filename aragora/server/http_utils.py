"""
HTTP utility functions for request handling.

Provides validation, type conversion, and async execution utilities
used across the unified server.
"""

import logging

# Import run_async from central utils for re-export
from aragora.utils.async_utils import run_async

logger = logging.getLogger(__name__)


# Query parameter whitelist (security: reject unknown params to prevent injection)
# Maps param name -> validation rule:
#   - None: numeric/short params (no length limit, validated elsewhere)
#   - set: restricted to specific values
#   - int: max length for string params (DoS protection)
ALLOWED_QUERY_PARAMS = {
    # Pagination (numeric, validated by int parsing)
    "limit": None,
    "offset": None,
    "count": None,
    "min_debates": None,
    "since": None,
    # Filtering (string, need length limits)
    "domain": 100,
    "loop_id": 100,
    "topic": 500,
    "query": 1000,
    "q": 1000,
    "task": 1000,
    "use_case": 100,
    "category": 100,
    "metric": 100,
    "format": 50,
    "status": 50,
    "range": 50,
    "period": 50,
    "time_range": 50,
    "granularity": 50,
    "host": 200,
    "email": 254,
    "direction": 10,
    "prioritized": 10,
    "scopes": 500,
    "debate_id": 100,
    "pipeline_id": 100,
    "org_id": 100,
    "organization_id": 100,
    "user_id": 100,
    "workspace_id": 100,
    "agents": 500,
    "source": 100,
    "sources": 500,
    # Analytics/time windows
    "days": None,
    # Depth/graph
    "depth": None,
    "max_depth": None,
    "include_cruxes": 10,
    # Export
    "table": {"summary", "debates", "proposals", "votes", "critiques", "messages"},
    # Validated against the ODR profile list by the export handler, which owns
    # the supported-version error message.
    "odr_version": 10,
    # Agent queries
    "agent": 100,
    "agent_a": 100,
    "agent_b": 100,
    "sections": {"identity", "performance", "relationships", "all"},
    # Calibration
    "buckets": None,
    # Memory
    "tiers": 100,
    "min_importance": None,
    # Thresholds
    "min_confidence": None,
    "min_success": None,
    "min_success_rate": None,
    "min_confidence_diff": None,
    # Genesis
    "event_type": {"mutation", "crossover", "selection", "extinction", "speciation"},
    # Logs
    "lines": None,
    # Belief network
    "top_k": None,
    # Codebase context (RLM)
    "refresh": 10,
    "rlm": 10,
    "include_tests": 10,
    "full_corpus": 10,
    "max_bytes": None,
    # Cost estimation
    "num_agents": None,
    "num_rounds": None,
    "model_types": 500,
    # OAuth
    "redirect_url": 500,  # Where to redirect after OAuth
    "code": 500,  # OAuth authorization code
    "state": 500,  # OAuth state parameter
    "error": 200,  # OAuth error
    "error_description": 500,  # OAuth error description
    # OAuth callback parameters (returned by Google/GitHub OAuth)
    "scope": 500,  # OAuth scope returned in callback
    "authuser": 10,  # Google authuser parameter
    "prompt": 50,  # OAuth prompt parameter
    "hd": 100,  # Google hosted domain
    "session_state": 100,  # Session state from some OAuth providers
}


def validate_query_params(query: dict) -> tuple[bool, str]:
    """Validate query parameters against whitelist.

    Returns (is_valid, error_message).

    Validation rules:
    - None: no length validation (for numeric params)
    - set: value must be in the set
    - int: max length for string params
    """
    for param, values in query.items():
        if param not in ALLOWED_QUERY_PARAMS:
            return False, f"Unknown query parameter: {param}"

        allowed = ALLOWED_QUERY_PARAMS[param]
        if allowed is None:
            # No validation needed (numeric params validated elsewhere)
            continue

        if isinstance(allowed, set):
            # Check if value is in the allowed set
            for val in values:
                if val not in allowed:
                    return False, f"Invalid value for {param}: {val}"
        elif isinstance(allowed, int):
            # Check length limit
            for val in values:
                if len(val) > allowed:
                    return False, f"Parameter {param} exceeds max length ({allowed})"

    return True, ""


def safe_float(value, default: float = 0.0) -> float:
    """Safely convert value to float, returning default on failure."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value, default: int = 0) -> int:
    """Safely convert value to int, returning default on failure."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


# run_async is imported from aragora.utils.async_utils (see top of file)

# Backward compatibility aliases (prefixed with underscore)
_validate_query_params = validate_query_params
_safe_float = safe_float
_safe_int = safe_int
_run_async = run_async


__all__ = [
    "ALLOWED_QUERY_PARAMS",
    "validate_query_params",
    "safe_float",
    "safe_int",
    "run_async",
    # Backward compatibility
    "_validate_query_params",
    "_safe_float",
    "_safe_int",
    "_run_async",
]
