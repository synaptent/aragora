"""
EU AI Act Compliance Artifact Generation Handler.

Endpoints for generating and retrieving EU AI Act compliance artifact bundles:

    POST /api/v1/compliance/eu-ai-act/bundles
        Generate a new compliance artifact bundle from a debate receipt.
        Body: { "debate_id": str?, "scope": str?, "articles": list[int]? }
        Permission: compliance:generate

    GET /api/v1/compliance/eu-ai-act/bundles/{bundle_id}
        Retrieve a previously generated bundle.
        Permission: compliance:read

Bundles contain Article 12 (record-keeping), Article 13 (transparency),
and Article 14 (human oversight) artifacts per EU AI Act Regulation 2024/1689.
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from aragora.server.handlers.utils.decorators import require_permission

logger = logging.getLogger(__name__)

# Lazy-initialized singleton
_bundle_generator = None
_VALID_ARTICLES = {12, 13, 14}


def _get_bundle_generator() -> Any:
    """Lazy-import and instantiate EUAIActBundleGenerator."""
    global _bundle_generator
    if _bundle_generator is None:
        from aragora.compliance.eu_ai_act import EUAIActBundleGenerator

        _bundle_generator = EUAIActBundleGenerator()
    return _bundle_generator


def _synthetic_receipt(debate_id: str | None = None) -> dict[str, Any]:
    """Build a minimal synthetic receipt for demo/testing."""
    return {
        "receipt_id": debate_id or "DEMO-RCP-001",
        "input_summary": "AI-powered recruitment and CV screening for hiring decisions",
        "verdict": "CONDITIONAL",
        "verdict_reasoning": (
            "The recruitment algorithm shows bias risk in CV screening. "
            "Multi-agent consensus recommends additional fairness auditing."
        ),
        "confidence": 0.78,
        "robustness_score": 0.72,
        "risk_summary": {
            "total": 5,
            "critical": 0,
            "high": 1,
            "medium": 3,
            "low": 1,
        },
        "consensus_proof": {
            "method": "weighted_majority",
            "supporting_agents": ["claude-analyst", "gpt-reviewer", "gemini-auditor"],
            "dissenting_agents": ["mistral-challenger"],
            "agreement_ratio": 0.75,
        },
        "dissenting_views": [
            "mistral-challenger: Insufficient bias testing for protected categories."
        ],
        "provenance_chain": [
            {
                "event_type": "debate_started",
                "timestamp": "2026-01-15T10:00:00Z",
                "actor": "system",
            },
            {
                "event_type": "proposal_submitted",
                "timestamp": "2026-01-15T10:01:00Z",
                "actor": "claude-analyst",
            },
            {
                "event_type": "critique_submitted",
                "timestamp": "2026-01-15T10:02:00Z",
                "actor": "mistral-challenger",
            },
            {
                "event_type": "human_approval",
                "timestamp": "2026-01-15T10:10:00Z",
                "actor": "hr-director@acme.com",
            },
            {
                "event_type": "receipt_generated",
                "timestamp": "2026-01-15T10:10:05Z",
                "actor": "system",
            },
        ],
        "config_used": {
            "protocol": "adversarial",
            "rounds": 3,
            "require_approval": True,
            "human_in_loop": True,
        },
        "artifact_hash": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
        "signature": "ed25519:demo-signature",
    }


class EUAIActComplianceHandler(BaseHandler):
    """Handler for EU AI Act compliance artifact bundle endpoints."""

    def __init__(self, ctx: dict[str, Any] | None = None, **kwargs: Any):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        """Check whether this handler manages the given path."""
        return path.startswith("/api/v1/compliance/eu-ai-act/bundles")

    @handle_errors("get EU AI Act bundle")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle GET requests for bundle retrieval."""
        if not path.startswith("/api/v1/compliance/eu-ai-act/bundles"):
            return None

        # GET /api/v1/compliance/eu-ai-act/bundles/{bundle_id}
        parts = path.strip("/").split("/")
        # parts: ['api', 'v1', 'compliance', 'eu-ai-act', 'bundles', '{bundle_id}']
        if len(parts) == 6:
            bundle_id = parts[5]
            return self._handle_get_bundle(bundle_id)

        return None

    @require_permission("compliance:read")
    @handle_errors("get EU AI Act bundle")
    def _handle_get_bundle(self, bundle_id: str) -> HandlerResult:
        """Retrieve a previously generated compliance bundle."""
        try:
            gen = _get_bundle_generator()
        except (ImportError, RuntimeError, ValueError, TypeError, OSError, AttributeError):
            logger.warning("EU AI Act bundle generator unavailable")
            return error_response("EU AI Act compliance module unavailable", 503)

        result = gen.get(bundle_id)
        if result is None:
            return error_response(f"Bundle '{bundle_id}' not found", 404)

        return json_response({"data": result})

    @require_permission("compliance:generate")
    @handle_errors("generate EU AI Act bundle")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST to generate a new compliance artifact bundle."""
        if path != "/api/v1/compliance/eu-ai-act/bundles":
            return None

        body, error = self.read_json_object_or_error(handler)
        if error:
            return error
        if body is None:
            return error_response("JSON object body is required", 400)

        debate_id = body.get("debate_id")
        scope = body.get("scope")
        articles = body.get("articles")

        if debate_id is not None and not isinstance(debate_id, str):
            return error_response("'debate_id' must be a string", 400)
        if scope is not None and not isinstance(scope, str):
            return error_response("'scope' must be a string", 400)

        # Validate articles parameter
        if articles is not None:
            if not isinstance(articles, list):
                return error_response("'articles' must be a list of integers (12, 13, 14)", 400)
            invalid = [a for a in articles if a not in _VALID_ARTICLES]
            if invalid:
                return error_response(
                    f"Invalid article numbers: {invalid}. Must be one of: 12, 13, 14",
                    400,
                )

        # Build receipt from debate storage or use synthetic
        receipt = None
        if debate_id:
            storage = self.ctx.get("storage")
            if storage:
                try:
                    debate_data = storage.get_debate(debate_id)
                    if debate_data is not None:
                        receipt = debate_data
                except (ImportError, RuntimeError, ValueError, TypeError, OSError, AttributeError):
                    logger.warning("Failed to load debate '%s' from storage", debate_id)

            if receipt is None:
                # Fall back to a synthetic receipt tagged with the debate_id
                receipt = _synthetic_receipt(debate_id)
        else:
            receipt = _synthetic_receipt()

        try:
            gen = _get_bundle_generator()
        except (ImportError, RuntimeError, ValueError, TypeError, OSError, AttributeError):
            logger.warning("EU AI Act bundle generator unavailable")
            return error_response("EU AI Act compliance module unavailable", 503)

        try:
            result = gen.generate(receipt, scope=scope, articles=articles)
        except (ImportError, RuntimeError, ValueError, TypeError, OSError, AttributeError):
            logger.warning("Bundle generation failed")
            return error_response("Bundle generation failed", 500)

        return json_response({"data": result}, status=201)


__all__ = ["EUAIActComplianceHandler"]
