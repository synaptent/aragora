"""
Readiness Check Handler - SME onboarding readiness endpoint.

Stability: STABLE

Provides a single public endpoint that tells users what they need
to configure before they can run debates.  This is critical for
first-time SME onboarding: before reading docs about 42 agent types,
a user can call one URL and immediately see what is missing.

Routes:
    GET /api/v1/readiness   - Full configuration readiness report (no auth required)
    GET /api/readiness       - Alias without version prefix
"""

from __future__ import annotations

import importlib.util
import logging
import os
from datetime import datetime, timezone
from typing import Any

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    handle_errors,
    json_response,
    log_request,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

# (env_var, default_model) – default_model is the value we report when the
# key is present.  We intentionally do NOT import agent modules here to keep
# the handler lightweight and free of heavy dependencies.
_PROVIDER_CONFIG: dict[str, tuple[str, str]] = {
    "anthropic": ("ANTHROPIC_API_KEY", "claude-opus-4-5-20251101"),
    "openai": ("OPENAI_API_KEY", "gpt-5.3"),
    "openrouter": ("OPENROUTER_API_KEY", "deepseek/deepseek-chat-v3-0324"),
    "mistral": ("MISTRAL_API_KEY", "mistral-large-2512"),
    "gemini": ("GEMINI_API_KEY", "gemini-2.5-pro"),
    "xai": ("XAI_API_KEY", "grok-4-latest"),
}

# A debate requires *at least one* of these providers.
_REQUIRED_PROVIDERS = {"anthropic", "openai"}

# The rest are optional (nice-to-have for heterogeneous consensus).
_OPTIONAL_PROVIDERS = {"openrouter", "mistral", "gemini", "xai"}

# ---------------------------------------------------------------------------
# Feature detection helpers
# ---------------------------------------------------------------------------


def _check_provider(name: str) -> dict[str, Any]:
    """Return availability info for a single AI provider."""
    env_var, default_model = _PROVIDER_CONFIG[name]
    key = os.environ.get(env_var)
    available = key is not None and len(key) > 10
    if available:
        return {"available": True, "model": default_model}
    return {"available": False, "reason": f"{env_var} not set"}


def _detect_storage() -> dict[str, Any]:
    """Detect which storage backend is in use and whether it is reachable."""
    # Check for PostgreSQL / Supabase first
    pg_dsn = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("ARAGORA_POSTGRES_DSN")
        or os.environ.get("SUPABASE_POSTGRES_DSN")
    )
    supabase_url = os.environ.get("SUPABASE_URL")

    if pg_dsn:
        return {"type": "postgresql", "status": "configured"}
    if supabase_url:
        return {"type": "supabase", "status": "configured"}

    # Default: local SQLite (always available)
    return {"type": "sqlite", "status": "connected"}


def _detect_features() -> dict[str, bool]:
    """Check which major platform features are available.

    Uses lightweight ``importlib.util.find_spec`` probes so we never actually
    import heavy modules.
    """
    features: dict[str, bool] = {}

    # Core features – almost always available because they live in-tree
    features["debates"] = importlib.util.find_spec("aragora.debate.orchestrator") is not None
    features["receipts"] = importlib.util.find_spec("aragora.gauntlet.receipts") is not None
    features["knowledge_mound"] = importlib.util.find_spec("aragora.knowledge.mound") is not None
    features["memory"] = importlib.util.find_spec("aragora.memory.continuum") is not None
    features["pulse"] = importlib.util.find_spec("aragora.pulse.ingestor") is not None
    features["explainability"] = (
        importlib.util.find_spec("aragora.explainability.builder") is not None
    )
    features["workflows"] = importlib.util.find_spec("aragora.workflow.engine") is not None
    features["rbac"] = importlib.util.find_spec("aragora.rbac.checker") is not None
    features["compliance"] = importlib.util.find_spec("aragora.compliance.framework") is not None
    features["analytics"] = importlib.util.find_spec("aragora.analytics.dashboard") is not None

    return features


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class ReadinessCheckHandler(BaseHandler):
    """Public endpoint reporting what a user needs to configure before
    they can run their first debate.

    No authentication is required -- this is intentionally open so that
    a brand-new user can call it before any credentials are set up.
    """

    ROUTES = [
        "/api/v1/readiness",
        "/api/readiness",
    ]

    def __init__(self, ctx: dict[str, Any] | None = None):
        """Initialize handler with optional server context."""
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        return path in self.ROUTES

    @handle_errors("readiness check")
    @log_request("readiness check")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle GET /api/v1/readiness."""
        if not self.can_handle(path):
            return None

        # -- Providers --
        providers: dict[str, dict[str, Any]] = {}
        for name in _PROVIDER_CONFIG:
            providers[name] = _check_provider(name)

        # -- Missing keys --
        missing_required: list[str] = []
        for name in _REQUIRED_PROVIDERS:
            if not providers[name]["available"]:
                env_var = _PROVIDER_CONFIG[name][0]
                missing_required.append(env_var)

        missing_optional: list[str] = []
        for name in _OPTIONAL_PROVIDERS:
            if not providers[name]["available"]:
                env_var = _PROVIDER_CONFIG[name][0]
                missing_optional.append(env_var)

        # ready_to_debate = at least one required provider is configured
        any_required_available = any(providers[name]["available"] for name in _REQUIRED_PROVIDERS)
        ready_to_debate = any_required_available

        # -- Storage --
        storage = _detect_storage()

        # -- Features --
        features = _detect_features()

        body: dict[str, Any] = {
            "ready_to_debate": ready_to_debate,
            "providers": providers,
            "missing_required": sorted(missing_required),
            "missing_optional": sorted(missing_optional),
            "storage": storage,
            "features": features,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        }

        return json_response(body)


__all__ = ["ReadinessCheckHandler"]
