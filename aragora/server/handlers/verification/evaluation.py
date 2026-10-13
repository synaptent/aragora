"""
Evaluation API Handlers.

Provides endpoints for LLM-as-Judge evaluation:
- POST /api/evaluate - Evaluate a response
- POST /api/evaluate/compare - Compare two responses
- GET /api/evaluate/dimensions - List evaluation dimensions
- GET /api/evaluate/profiles - List weight profiles
"""

from __future__ import annotations

__all__ = [
    "EvaluationHandler",
]

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from aragora.utils.optional_imports import try_import

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from aragora.rbac.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for evaluation endpoints (30 requests per minute - LLM calls are expensive)
_evaluation_limiter = RateLimiter(requests_per_minute=30)

# Lazy imports for LLM Judge
_judge_imports, JUDGE_AVAILABLE = try_import(
    "aragora.evaluation.llm_judge",
    "LLMJudge",
    "JudgeConfig",
    "EvaluationDimension",
    "DEFAULT_RUBRICS",
    "WEIGHT_PROFILES",
    "DEFAULT_WEIGHTS",
)
LLMJudge = _judge_imports.get("LLMJudge")
JudgeConfig = _judge_imports.get("JudgeConfig")
EvaluationDimension = _judge_imports.get("EvaluationDimension")
DEFAULT_RUBRICS = _judge_imports.get("DEFAULT_RUBRICS")
WEIGHT_PROFILES = _judge_imports.get("WEIGHT_PROFILES")
DEFAULT_WEIGHTS = _judge_imports.get("DEFAULT_WEIGHTS")


class EvaluationHandler(BaseHandler):
    """Handler for LLM-as-Judge evaluation endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/evaluate",
        "/api/v1/evaluate/compare",
        "/api/v1/evaluate/dimensions",
        "/api/v1/evaluate/profiles",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return path in self.ROUTES

    @require_permission("evaluation:read")
    def handle(
        self, path: str, query_params: dict[str, Any], handler: Any = None
    ) -> HandlerResult | None:
        """Route GET requests to appropriate methods."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _evaluation_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for evaluation endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if path == "/api/v1/evaluate/dimensions":
            return self._list_dimensions()
        if path == "/api/v1/evaluate/profiles":
            return self._list_profiles()
        return None

    @handle_errors("evaluation creation")
    @require_permission("evaluation:create")
    async def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route POST requests to appropriate methods."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _evaluation_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for evaluation endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if path == "/api/v1/evaluate":
            return await self._evaluate_response(handler)
        if path == "/api/v1/evaluate/compare":
            return await self._compare_responses(handler)
        return None

    @handle_errors("list dimensions")
    def _list_dimensions(self) -> HandlerResult:
        """List available evaluation dimensions.

        GET /api/evaluate/dimensions

        Returns list of dimensions with descriptions and rubrics.
        """
        if not JUDGE_AVAILABLE or not EvaluationDimension:
            return error_response("LLM Judge not available", 503)

        dimensions = []
        for dim in EvaluationDimension:
            rubric = DEFAULT_RUBRICS.get(dim) if DEFAULT_RUBRICS else None
            dimensions.append(
                {
                    "id": dim.value,
                    "name": dim.name.replace("_", " ").title(),
                    "description": rubric.description if rubric else "",
                    "rubric": {
                        "score_1": rubric.score_1 if rubric else "",
                        "score_2": rubric.score_2 if rubric else "",
                        "score_3": rubric.score_3 if rubric else "",
                        "score_4": rubric.score_4 if rubric else "",
                        "score_5": rubric.score_5 if rubric else "",
                    },
                }
            )

        return json_response({"dimensions": dimensions})

    @handle_errors("list profiles")
    def _list_profiles(self) -> HandlerResult:
        """List available evaluation weight profiles.

        GET /api/evaluate/profiles

        Returns list of use-case profiles with dimension weights.
        """
        if not JUDGE_AVAILABLE or not WEIGHT_PROFILES:
            return error_response("LLM Judge not available", 503)

        profiles = [
            {
                "id": "default",
                "name": "Default",
                "description": "Balanced evaluation across all dimensions",
                "weights": (
                    {k.value: v for k, v in DEFAULT_WEIGHTS.items()} if DEFAULT_WEIGHTS else {}
                ),
            }
        ]

        profile_descriptions = {
            "factual_qa": "Factual Q&A - emphasizes accuracy",
            "creative_writing": "Creative Writing - emphasizes creativity and clarity",
            "code_generation": "Code Generation - emphasizes accuracy and completeness",
            "debate": "Debate - emphasizes reasoning and evidence",
            "safety_critical": "Safety Critical - emphasizes accuracy and safety",
        }

        for profile_id, weights in WEIGHT_PROFILES.items():
            profiles.append(
                {
                    "id": profile_id,
                    "name": profile_id.replace("_", " ").title(),
                    "description": profile_descriptions.get(profile_id, ""),
                    "weights": {k.value: v for k, v in weights.items()},
                }
            )

        return json_response({"profiles": profiles})

    @handle_errors("evaluate response")
    async def _evaluate_response(self, handler: Any) -> HandlerResult:
        """Evaluate a response using LLM-as-Judge.

        POST /api/evaluate

        Request body:
        {
            "query": "The original question/prompt",
            "response": "The response to evaluate",
            "context": "Optional additional context",
            "reference": "Optional reference/ground truth answer",
            "use_case": "Optional use case profile",
            "dimensions": ["Optional list of dimensions"],
            "threshold": 3.5
        }

        Returns evaluation result with scores.
        """
        if not JUDGE_AVAILABLE or not LLMJudge or not JudgeConfig:
            return error_response("LLM Judge not available", 503)

        # Read request body
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body or body too large", 400)

        query = body.get("query")
        response = body.get("response")

        if not query:
            return error_response("'query' is required", 400)
        if not response:
            return error_response("'response' is required", 400)

        # Build config
        use_case = body.get("use_case", "default")
        threshold = float(body.get("threshold", 3.5))

        # Parse dimensions if provided
        dimensions = None
        if body.get("dimensions") and EvaluationDimension:
            try:
                dimensions = [EvaluationDimension(d) for d in body["dimensions"]]
            except ValueError as e:
                logger.warning("Handler error: %s", e)
                return error_response("Invalid dimension specified", 400)

        config = JudgeConfig(
            use_case=use_case,
            pass_threshold=threshold,
            dimensions=dimensions,
        )
        judge = LLMJudge(config)

        result = await judge.evaluate(
            query=query,
            response=response,
            context=body.get("context"),
            reference=body.get("reference"),
        )

        return json_response(result.to_dict())

    @handle_errors("compare responses")
    async def _compare_responses(self, handler: Any) -> HandlerResult:
        """Compare two responses using pairwise evaluation.

        POST /api/evaluate/compare

        Request body:
        {
            "query": "The original question/prompt",
            "response_a": "First response",
            "response_b": "Second response",
            "context": "Optional context",
            "use_case": "Optional use case profile"
        }

        Returns comparison result.
        """
        if not JUDGE_AVAILABLE or not LLMJudge or not JudgeConfig:
            return error_response("LLM Judge not available", 503)

        # Read request body
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body or body too large", 400)

        query = body.get("query")
        response_a = body.get("response_a")
        response_b = body.get("response_b")

        if not query:
            return error_response("'query' is required", 400)
        if not response_a:
            return error_response("'response_a' is required", 400)
        if not response_b:
            return error_response("'response_b' is required", 400)

        use_case = body.get("use_case", "default")
        config = JudgeConfig(use_case=use_case)
        judge = LLMJudge(config)

        result = await judge.compare(
            query=query,
            response_a=response_a,
            response_b=response_b,
            context=body.get("context"),
            response_a_id=body.get("response_a_id", "A"),
            response_b_id=body.get("response_b_id", "B"),
        )

        return json_response(result.to_dict())
