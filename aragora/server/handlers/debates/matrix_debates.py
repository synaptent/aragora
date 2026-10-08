"""
Matrix debates endpoint handlers.

Endpoints:
- POST /api/debates/matrix - Run parallel scenario debates
- POST /api/debates/matrix with agent_combinations/model_combinations - Compare model/team combinations
- GET /api/debates/matrix/{id} - Get matrix debate results
- GET /api/debates/matrix/{id}/scenarios - Get all scenario results
- GET /api/debates/matrix/{id}/conclusions - Get universal/conditional conclusions
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import OrderedDict
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from aragora.config import DEFAULT_ROUNDS
from aragora.server.versioning.compat import strip_version_prefix

if TYPE_CHECKING:
    from typing import TypeAlias

    # Type alias for agent instances (from base.py)
    AgentInstance: TypeAlias = Any  # Could be APIAgent | CLIAgent


@runtime_checkable
class ScenarioConfigProtocol(Protocol):
    """Protocol for scenario configuration objects."""

    name: str
    parameters: dict[str, Any]
    constraints: list[str]
    is_baseline: bool


@runtime_checkable
class MatrixResultProtocol(Protocol):
    """Protocol for matrix debate result objects."""

    @property
    def scenario_results(self) -> list[Any]: ...

    @property
    def universal_conclusions(self) -> list[str]: ...

    @property
    def conditional_conclusions(self) -> dict[str, list[str]]: ...

    @property
    def comparison_matrix(self) -> dict[str, Any]: ...


@runtime_checkable
class MatrixRunnerProtocol(Protocol):
    """Protocol for matrix debate runner objects."""

    @property
    def scenarios(self) -> list[Any]: ...

    def add_scenario(self, config: Any) -> None: ...

    async def run_all(self, max_rounds: int = DEFAULT_ROUNDS) -> MatrixResultProtocol: ...


from ..base import (
    HandlerResult,
    MaybeAsyncHandlerResult,
    error_response,
    handle_errors,
    json_response,
    safe_error_message,
)
from ..openapi_decorator import api_endpoint
from ..secure import SecureHandler, ForbiddenError, UnauthorizedError
from ..utils.rate_limit import RateLimiter, get_client_ip
from aragora.resilience import with_timeout
from aragora.tenancy.record_scope import (
    OrgScope,
    record_not_found,
    record_visible,
    require_org_scope,
)

logger = logging.getLogger(__name__)

# RBAC permissions for matrix debates
DEBATES_READ_PERMISSION = "debates:read"
DEBATES_CREATE_PERMISSION = "debates:create"
MAX_AGENT_COMBINATIONS = 10
DEFAULT_SELECTION_STRATEGY = "consensus_confidence_completion"

# Rate limiter for matrix debates (5 requests per minute - parallel debates are expensive)
_matrix_limiter = RateLimiter(requests_per_minute=5)

# No store persists matrix runs, so the GET routes read the runs this process
# created (with their org) from here; they are lost on restart.
_MATRIX_DEBATE_CACHE_LIMIT = 100
_matrix_debate_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()


def _matrix_response(payload: dict[str, Any]) -> HandlerResult:
    """Remember a finished matrix run for the GET routes and return it."""
    _matrix_debate_cache[payload["matrix_id"]] = deepcopy(payload)
    _matrix_debate_cache.move_to_end(payload["matrix_id"])
    while len(_matrix_debate_cache) > _MATRIX_DEBATE_CACHE_LIMIT:
        _matrix_debate_cache.popitem(last=False)
    return json_response(payload)


class MatrixDebatesHandler(SecureHandler):
    """Handler for matrix debate endpoints (parallel scenario exploration).

    RBAC Protected:
    - debates:read - required for GET endpoints
    - debates:create - required for POST endpoints
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/debates/matrix",
        "/api/v1/debates/matrix/",
        "/api/v1/matrix-debates",
        "/api/v1/matrix-debates/",
        "/api/v1/matrix-debates/*",
    ]

    AUTH_REQUIRED_ENDPOINTS = [
        "/api/v1/debates/matrix",
        "/api/v1/matrix-debates",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        return normalized.startswith("/api/debates/matrix") or normalized.startswith(
            "/api/matrix-debates"
        )

    def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> MaybeAsyncHandlerResult:
        """Route GET requests through the async handler."""
        return self.handle_get(handler, path, query_params)

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/matrix/{matrix_id}",
        summary="Get matrix debate",
        description="Get the results of a matrix debate with parallel scenario exploration.",
        tags=["Debates", "Matrix Debates"],
        parameters=[
            {"name": "matrix_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        responses={
            "200": {"description": "Matrix debate results"},
            "401": {"description": "Authentication required"},
            "403": {"description": "Permission denied"},
            "404": {"description": "Matrix debate not found"},
        },
        operation_id="get_matrix_debate",
    )
    @handle_errors("matrix debates GET")
    async def handle_get(
        self, handler: Any, path: str, query_params: dict[str, Any]
    ) -> HandlerResult:
        """Handle GET requests for matrix debates with RBAC."""
        scope, scope_error = require_org_scope(handler)
        if scope is None:
            return scope_error

        # RBAC: Require authentication and debates:read permission
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, DEBATES_READ_PERMISSION)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Matrix debates GET access denied: %s", e)
            return error_response("Permission denied", 403)

        normalized = strip_version_prefix(path)
        if normalized.startswith("/api/matrix-debates"):
            normalized = normalized.replace("/api/matrix-debates", "/api/debates/matrix", 1)
        segments = normalized.strip("/").split("/")

        # GET /api/debates/matrix/{id}
        # Path structure: ['api', 'debates', 'matrix', '{id}', ...]
        if len(segments) >= 4 and segments[2] == "matrix":
            matrix_id = segments[3]

            # GET /api/debates/matrix/{id}/scenarios
            if len(segments) >= 5 and segments[4] == "scenarios":
                return await self._get_scenarios(handler, matrix_id, scope)

            # GET /api/debates/matrix/{id}/conclusions
            if len(segments) >= 5 and segments[4] == "conclusions":
                return await self._get_conclusions(handler, matrix_id, scope)

            return await self._get_matrix_debate(handler, matrix_id, scope)

        return error_response("Not found", 404)

    @api_endpoint(
        method="POST",
        path="/api/v1/debates/matrix",
        summary="Create matrix debate",
        description="Run parallel scenario debates to explore a topic under different conditions.",
        tags=["Debates", "Matrix Debates"],
        operation_id="create_matrix_debate",
        responses={
            "200": {"description": "Matrix debate created and executed"},
            "400": {"description": "Invalid request body"},
            "401": {"description": "Authentication required"},
            "403": {"description": "Permission denied"},
            "429": {"description": "Rate limit exceeded"},
            "500": {"description": "Matrix debate failed"},
        },
    )
    @handle_errors("matrix debates POST")
    async def handle_post(self, *args: Any, **kwargs: Any) -> HandlerResult:
        """Handle POST requests for matrix debates with RBAC.

        POST /api/debates/matrix - Run parallel scenario debates
        """
        handler = None
        path = ""
        data: dict[str, Any] = {}
        read_body = False

        if len(args) >= 3:
            if isinstance(args[0], str):
                path = args[0]
                handler = args[2]
                read_body = True
            else:
                handler = args[0]
                path = args[1]
                data = args[2] or {}
        else:
            handler = kwargs.get("handler")
            path = kwargs.get("path", "")
            data = kwargs.get("data") or kwargs.get("body") or {}
            if handler is None:
                return error_response("Invalid request", 400)
            read_body = not data

        scope, scope_error = require_org_scope(handler)
        if scope is None:
            return scope_error

        if read_body:
            data, error = self.read_json_body_validated(handler)
            if error:
                return error

        normalized = strip_version_prefix(path)
        if normalized.startswith("/api/matrix-debates"):
            normalized = normalized.replace("/api/matrix-debates", "/api/debates/matrix", 1)
        if not normalized.rstrip("/").endswith("/debates/matrix"):
            return error_response("Not found", 404)

        # RBAC: Require authentication and debates:create permission
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, DEBATES_CREATE_PERMISSION)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Matrix debates POST access denied: %s", e)
            return error_response("Permission denied", 403)

        # Rate limit check (5/min - expensive parallel operations)
        client_ip = get_client_ip(handler)
        if not _matrix_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for matrix debates: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        logger.debug("POST /api/debates/matrix - running matrix debate")
        return await self._run_matrix_debate(handler, data, scope)

    @with_timeout(180.0)
    async def _run_matrix_debate(
        self, handler: Any, data: dict[str, Any], scope: OrgScope
    ) -> HandlerResult:
        """Run parallel scenario debates.

        Request body:
            task: str - Base debate topic/question (10-5000 chars)
            agents: list[str] - Agent names to participate (2-10 agents)
            agent_combinations/model_combinations: list[dict] - Explicit agent/model combinations
                to compare
            scenarios: list[dict] - List of scenario configurations (1-10 scenarios)
                - name: str - Scenario name (max 100 chars)
                - parameters: dict - Scenario-specific parameters
                - constraints: list[str] - Additional constraints
                - is_baseline: bool - Whether this is the baseline scenario
            max_rounds: int - Maximum rounds per scenario (1-10, default: global debate default)
            select_best_result: bool - Include the strongest result in the response
        """
        # Validate task (accept "question" as alias for frontend compatibility)
        task = data.get("task") or data.get("question")
        if not task:
            return error_response("task is required", 400)
        if not isinstance(task, str):
            return error_response("task must be a string", 400)
        task = task.strip()
        if len(task) < 10:
            return error_response("task must be at least 10 characters", 400)
        if len(task) > 5000:
            return error_response("task must be at most 5000 characters", 400)

        # Validate scenarios
        scenarios = data.get("scenarios", [])
        if not isinstance(scenarios, list):
            return error_response("scenarios must be an array", 400)
        if len(scenarios) > 10:
            return error_response("Maximum 10 scenarios allowed", 400)

        raw_model_combinations = (
            data.get("model_combinations") if "model_combinations" in data else None
        )
        if raw_model_combinations is not None and not isinstance(raw_model_combinations, list):
            return error_response("model_combinations must be an array", 400)

        # Validate explicit agent/model combinations
        agent_combinations, combo_error = self._get_agent_combinations_payload(data)
        if combo_error is not None:
            return combo_error
        if not isinstance(agent_combinations, list):
            return error_response("agent_combinations must be an array", 400)
        if len(agent_combinations) > MAX_AGENT_COMBINATIONS:
            return error_response(
                f"Maximum {MAX_AGENT_COMBINATIONS} agent combinations allowed",
                400,
            )
        uses_model_combinations = (
            raw_model_combinations is not None and "agent_combinations" not in data
        )

        if uses_model_combinations and scenarios and agent_combinations:
            return error_response(
                "scenarios and model_combinations cannot be combined in one request",
                400,
            )

        if scenarios and agent_combinations:
            return error_response(
                "Use either scenarios or agent_combinations, not both",
                400,
            )

        if not scenarios and not agent_combinations:
            return error_response(
                "At least one scenario or agent combination is required",
                400,
            )

        # Validate each scenario
        for i, scenario in enumerate(scenarios):
            if not isinstance(scenario, dict):
                return error_response(f"scenarios[{i}] must be an object", 400)
            name = scenario.get("name", "")
            if name and len(name) > 100:
                return error_response(f"scenarios[{i}].name too long (max 100 chars)", 400)
            if "parameters" in scenario and not isinstance(scenario["parameters"], dict):
                return error_response(f"scenarios[{i}].parameters must be an object", 400)
            if "constraints" in scenario:
                if not isinstance(scenario["constraints"], list):
                    return error_response(f"scenarios[{i}].constraints must be an array", 400)
                if len(scenario["constraints"]) > 10:
                    return error_response(f"scenarios[{i}].constraints too many (max 10)", 400)

        normalized_model_combinations: list[dict[str, Any]] = []
        if uses_model_combinations:
            normalized_model_combinations, combo_error = self._normalize_model_combinations(
                agent_combinations
            )
            if combo_error is not None:
                return combo_error

        normalized_combinations: list[dict[str, Any]] = []
        if not uses_model_combinations:
            normalized_combinations, combo_error = self._normalize_agent_combinations(
                agent_combinations
            )
            if combo_error is not None:
                return combo_error

        # Validate agents
        agent_names = data.get("agents", [])
        if not isinstance(agent_names, list):
            return error_response("agents must be an array", 400)
        if uses_model_combinations and agent_names:
            return error_response("agents and model_combinations cannot be used together", 400)
        if normalized_combinations and agent_names:
            return error_response(
                "Use either agents or agent_combinations, not both",
                400,
            )
        if len(agent_names) > 10:
            return error_response("Maximum 10 agents allowed", 400)
        for i, name in enumerate(agent_names):
            if not isinstance(name, str):
                return error_response(f"agents[{i}] must be a string", 400)
            if len(name) > 50:
                return error_response(f"agents[{i}] name too long (max 50 chars)", 400)

        # Validate max_rounds
        max_rounds = data.get("max_rounds", DEFAULT_ROUNDS)
        if not isinstance(max_rounds, int):
            try:
                max_rounds = int(max_rounds)
            except (ValueError, TypeError):
                return error_response("max_rounds must be an integer", 400)
        if max_rounds < 1:
            return error_response("max_rounds must be at least 1", 400)
        if max_rounds > 10:
            return error_response("max_rounds must be at most 10", 400)

        select_best_result = data.get("select_best_result", True)
        if not isinstance(select_best_result, bool):
            return error_response("select_best_result must be a boolean", 400)

        if uses_model_combinations and normalized_model_combinations:
            data = dict(data)
            data["model_combinations"] = normalized_model_combinations
            data["select_best_result"] = select_best_result
            return await self._run_matrix_debate_fallback(handler, data, scope)

        if normalized_combinations:
            data = dict(data)
            data["agent_combinations"] = normalized_combinations
            data["select_best_result"] = select_best_result
            return await self._run_matrix_debate_fallback(handler, data, scope)

        try:
            # Dynamic import of scenario module classes
            # These classes may have a different API than our Protocol definitions,
            # so we use cast() and handle ImportError gracefully with fallback
            from typing import cast

            scenarios_module = __import__(
                "aragora.debate.scenarios", fromlist=["MatrixDebateRunner", "ScenarioConfig"]
            )

            # Check if the expected API exists - if not, fall back to our implementation
            if not hasattr(scenarios_module, "ScenarioConfig") or not hasattr(
                scenarios_module, "MatrixDebateRunner"
            ):
                raise ImportError("Required scenario classes not found")

            ScenarioConfig = scenarios_module.ScenarioConfig
            MatrixDebateRunner = scenarios_module.MatrixDebateRunner

            # Load agents
            agents = await self._load_agents(agent_names)
            if not agents:
                return error_response("No valid agents found", 400)

            # Create matrix runner - cast to our Protocol for type checking
            runner = cast(
                MatrixRunnerProtocol,
                MatrixDebateRunner(
                    base_task=task,
                    agents=agents,
                ),
            )

            # Add scenarios
            for scenario_data in scenarios:
                config = ScenarioConfig(
                    name=scenario_data.get("name", f"Scenario {len(runner.scenarios) + 1}"),
                    parameters=scenario_data.get("parameters", {}),
                    constraints=scenario_data.get("constraints", []),
                    is_baseline=scenario_data.get("is_baseline", False),
                )
                runner.add_scenario(config)

            # Generate matrix ID
            matrix_id = str(uuid.uuid4())

            # Run all scenarios in parallel
            results = await runner.run_all(max_rounds=max_rounds)

            # Build response
            return _matrix_response(
                {
                    "matrix_id": matrix_id,
                    "task": task,
                    "scenario_count": len(results.scenario_results),
                    "results": [r.to_dict() for r in results.scenario_results],
                    "universal_conclusions": results.universal_conclusions,
                    "conditional_conclusions": results.conditional_conclusions,
                    "comparison_matrix": results.comparison_matrix,
                    "org_id": scope.org_id,
                    "created_by": scope.user_id,
                }
            )

        except ImportError as e:
            logger.warning("Matrix debate module not available, using fallback: %s", e)
            return await self._run_matrix_debate_fallback(handler, data, scope)
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
            logger.exception("Matrix debate failed: %s", e)
            return error_response(safe_error_message(e, "matrix debate"), 500)

    def _normalize_agent_combinations(
        self,
        combinations: list[Any],
    ) -> tuple[list[dict[str, Any]], HandlerResult | None]:
        """Validate and normalize explicit agent/model combinations."""
        if not combinations:
            return [], None

        try:
            from aragora.agents.spec import AgentSpec
        except ImportError as exc:
            logger.warning("Agent combination parsing unavailable: %s", exc)
            return [], error_response("Agent specification support is unavailable", 500)

        normalized: list[dict[str, Any]] = []
        for index, combo in enumerate(combinations):
            if not isinstance(combo, dict):
                return [], error_response(
                    f"agent_combinations[{index}] must be an object",
                    400,
                )

            raw_name = combo.get("name")
            if raw_name is not None and not isinstance(raw_name, str):
                return [], error_response(
                    f"agent_combinations[{index}].name must be a string",
                    400,
                )
            combo_name = (raw_name or "").strip() or f"Combination {index + 1}"
            if len(combo_name) > 100:
                return [], error_response(
                    f"agent_combinations[{index}].name too long (max 100 chars)",
                    400,
                )

            if "agents" not in combo:
                return [], error_response(
                    f"agent_combinations[{index}].agents is required",
                    400,
                )

            try:
                specs = AgentSpec.coerce_list(combo.get("agents"), warn=False)
            except ValueError as exc:
                return [], error_response(
                    f"agent_combinations[{index}].agents invalid: {exc}",
                    400,
                )

            if len(specs) < 2:
                return [], error_response(
                    f"agent_combinations[{index}] must include at least 2 agents",
                    400,
                )
            if len(specs) > 10:
                return [], error_response(
                    f"agent_combinations[{index}] exceeds 10 agents",
                    400,
                )

            normalized.append({"name": combo_name, "agents": specs})

        return normalized, None

    def _normalize_model_combinations(
        self,
        combinations: list[Any],
    ) -> tuple[list[dict[str, Any]], HandlerResult | None]:
        """Validate and normalize lightweight model combinations."""
        normalized: list[dict[str, Any]] = []
        for index, combo in enumerate(combinations):
            if not isinstance(combo, dict):
                return [], error_response(
                    f"model_combinations[{index}] must be an object",
                    400,
                )

            raw_name = combo.get("name")
            if raw_name is not None and not isinstance(raw_name, str):
                return [], error_response(
                    f"model_combinations[{index}].name must be a string",
                    400,
                )
            combo_name = (raw_name or "").strip() or f"Combination {index + 1}"
            if len(combo_name) > 100:
                return [], error_response(
                    f"model_combinations[{index}].name too long (max 100 chars)",
                    400,
                )

            combo_agents = combo.get("agents")
            if not isinstance(combo_agents, list) or not combo_agents:
                return [], error_response(
                    f"model_combinations[{index}].agents must be a non-empty array",
                    400,
                )
            if len(combo_agents) > 10:
                return [], error_response(
                    f"model_combinations[{index}].agents too many (max 10)",
                    400,
                )

            normalized_agents: list[Any] = []
            for agent_index, agent in enumerate(combo_agents):
                if isinstance(agent, str):
                    if len(agent) > 50:
                        return [], error_response(
                            f"model_combinations[{index}].agents[{agent_index}] name too long (max 50 chars)",
                            400,
                        )
                    normalized_agents.append(agent)
                    continue
                if isinstance(agent, dict):
                    normalized_agents.append(agent)
                    continue
                return [], error_response(
                    f"model_combinations[{index}].agents[{agent_index}] must be a string or object",
                    400,
                )

            normalized.append({"name": combo_name, "agents": normalized_agents})

        return normalized, None

    def _get_agent_combinations_payload(
        self,
        data: dict[str, Any],
    ) -> tuple[list[Any] | Any, HandlerResult | None]:
        """Return the active combination payload, supporting a model_combinations alias."""
        has_agent = bool(data.get("agent_combinations"))
        has_model = bool(data.get("model_combinations"))

        if has_agent and has_model:
            return [], error_response(
                "Use either agent_combinations or model_combinations, not both",
                400,
            )

        if "agent_combinations" in data:
            return data.get("agent_combinations", []), None
        if "model_combinations" in data:
            return data.get("model_combinations", []), None
        return [], None

    def _serialize_agent_specs(self, agent_specs: Any) -> list[dict[str, Any]]:
        """Render agent specs into a JSON-safe response shape."""
        try:
            from aragora.agents.spec import AgentSpec

            specs = AgentSpec.coerce_list(agent_specs, warn=False)
        except (ImportError, ValueError, TypeError):
            return []

        return [
            {
                "provider": spec.provider,
                "model": spec.model,
                "persona": spec.persona,
                "role": spec.role,
                "name": spec.name,
            }
            for spec in specs
        ]

    async def _load_agents_from_specs(self, agent_specs: Any, min_agents: int = 2) -> list[Any]:
        """Create fresh agent instances from flexible agent specifications."""
        try:
            from aragora.agents.spec import AgentSpec
            from aragora.server.debate_factory import DebateFactory

            specs = AgentSpec.coerce_list(agent_specs, warn=False)
            if len(specs) < min_agents:
                return []

            factory = DebateFactory()
            result = factory.create_agents(specs)
            return result.agents
        except (ImportError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.warning("Failed to load agents from specs: %s", e)
            return []

    def _score_matrix_entry(self, result: dict[str, Any], max_rounds: int) -> dict[str, Any]:
        """Score a matrix result deterministically for best-result selection."""
        confidence = result.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)):
            confidence = 0.0
        confidence = max(0.0, min(float(confidence), 1.0))

        rounds_used = result.get("rounds_used", 0)
        if not isinstance(rounds_used, int):
            try:
                rounds_used = int(rounds_used)
            except (ValueError, TypeError):
                rounds_used = 0

        consensus_component = 2.0 if result.get("consensus_reached") else 0.0
        confidence_component = confidence * 1.5
        answer_component = 0.5 if str(result.get("final_answer") or "").strip() else 0.0
        round_efficiency = 1.0
        if max_rounds > 0:
            round_efficiency = max(0.0, 1.0 - min(rounds_used / max_rounds, 1.0))
        round_component = round_efficiency * 0.25

        breakdown = {
            "consensus": round(consensus_component, 4),
            "confidence": round(confidence_component, 4),
            "answer_completion": round(answer_component, 4),
            "round_efficiency": round(round_component, 4),
        }
        score = round(sum(breakdown.values()), 4)
        return {
            "selection_score": score,
            "selection_strategy": DEFAULT_SELECTION_STRATEGY,
            "selection_breakdown": breakdown,
        }

    def _select_best_result(self, results: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Pick the strongest matrix result using the precomputed score."""
        if not results:
            return None

        return max(
            results,
            key=lambda item: (
                float(item.get("selection_score", 0.0) or 0.0),
                int(bool(item.get("consensus_reached"))),
                float(item.get("confidence", 0.0) or 0.0),
                -int(item.get("rounds_used", 0) or 0),
                len(str(item.get("final_answer") or "")),
            ),
        )

    async def _run_matrix_debate_fallback(
        self, handler: Any, data: dict[str, Any], scope: OrgScope
    ) -> HandlerResult:
        """Fallback implementation using Arena directly for each scenario."""
        from aragora.core import DebateProtocol, Environment
        from aragora.debate.orchestrator import Arena

        task = data.get("task") or data.get("question")
        scenarios = data.get("scenarios", [])
        agent_names = data.get("agents", [])
        agent_combinations = data.get("agent_combinations", [])
        model_combinations = data.get("model_combinations", [])
        max_rounds = data.get("max_rounds", DEFAULT_ROUNDS)
        select_best_result = data.get("select_best_result", True)

        try:
            matrix_id = str(uuid.uuid4())
            use_agent_combinations = bool(agent_combinations)
            use_model_combinations = bool(model_combinations)
            run_items: list[dict[str, Any]] = []
            ctx = getattr(self, "ctx", {}) or {}
            document_store = ctx.get("document_store")
            evidence_store = ctx.get("evidence_store")

            if use_model_combinations:
                for combo in model_combinations:
                    if not await self._load_agents_from_specs(
                        combo.get("agents", []), min_agents=1
                    ):
                        return error_response(
                            f"No valid agents found for {combo.get('name', 'model combination')}",
                            400,
                        )
                    combo_name = str(combo.get("name", "Unnamed Combination"))
                    run_items.append(
                        {
                            "scenario_name": combo_name,
                            "parameters": {},
                            "constraints": [],
                            "is_baseline": False,
                            "variant_type": "model_combination",
                            "agent_specs": combo.get("agents", []),
                            "combination_name": combo_name,
                        }
                    )
            elif use_agent_combinations:
                for combo in agent_combinations:
                    if not await self._load_agents_from_specs(combo.get("agents", [])):
                        return error_response(
                            f"No valid agents found for {combo.get('name', 'agent combination')}",
                            400,
                        )
                    run_items.append(
                        {
                            "scenario_name": combo.get("name", "Unnamed Combination"),
                            "parameters": {},
                            "constraints": [],
                            "is_baseline": False,
                            "variant_type": "agent_combination",
                            "agent_specs": combo.get("agents", []),
                        }
                    )
            else:
                if not await self._load_agents(agent_names):
                    return error_response("No valid agents found", 400)
                run_items = [
                    {
                        "scenario_name": scenario.get("name", "Unnamed"),
                        "parameters": scenario.get("parameters", {}),
                        "constraints": scenario.get("constraints", []),
                        "is_baseline": scenario.get("is_baseline", False),
                        "variant_type": "scenario",
                        "agent_specs": agent_names,
                    }
                    for scenario in scenarios
                ]

            # Run scenarios or combinations in parallel
            async def run_variant(run_item: dict[str, Any]) -> dict[str, Any]:
                name = run_item["scenario_name"]
                parameters = run_item.get("parameters", {})
                constraints = run_item.get("constraints", [])

                # Build variant task with parameters and constraints
                scenario_task = f"{task}"
                if parameters:
                    param_str = ", ".join(f"{k}={v}" for k, v in parameters.items())
                    scenario_task += f"\n\nParameters: {param_str}"
                if constraints:
                    scenario_task += f"\n\nConstraints: {', '.join(constraints)}"

                min_agents = 1 if run_item.get("variant_type") == "model_combination" else 2
                agents = await self._load_agents_from_specs(
                    run_item.get("agent_specs", []), min_agents=min_agents
                )
                if not agents:
                    raise ValueError(f"No valid agents found for {name}")

                # Run debate
                env = Environment(task=scenario_task)
                protocol = DebateProtocol(
                    rounds=max_rounds,
                    convergence_detection=False,
                    early_stopping=False,
                )
                arena = Arena(
                    env,
                    agents,
                    protocol,
                    document_store=document_store,
                    evidence_store=evidence_store,
                    receipt_org_id=scope.org_id,
                    receipt_created_by=scope.user_id,
                )

                result = await arena.run()

                response = {
                    "scenario_name": name,
                    "parameters": parameters,
                    "constraints": constraints,
                    "is_baseline": run_item.get("is_baseline", False),
                    "variant_type": run_item.get("variant_type", "scenario"),
                    "combination_name": run_item.get("combination_name"),
                    "agent_specs": self._serialize_agent_specs(run_item.get("agent_specs", [])),
                    "winner": result.winner,
                    "final_answer": result.final_answer,
                    "confidence": result.confidence,
                    "consensus_reached": result.consensus_reached,
                    "rounds_used": result.rounds_used,
                }
                response.update(self._score_matrix_entry(response, max_rounds))
                return response

            # Run all scenarios concurrently
            scenario_tasks = [run_variant(item) for item in run_items]
            gather_results = await asyncio.gather(*scenario_tasks, return_exceptions=True)

            # Process results
            valid_results: list[dict[str, Any]] = []
            for r in gather_results:
                if isinstance(r, BaseException):
                    logger.error("Scenario failed: %s", r)
                else:
                    valid_results.append(r)

            best_result = self._select_best_result(valid_results) if select_best_result else None
            if best_result is not None:
                for result in valid_results:
                    result["is_best"] = result is best_result

            # Find universal conclusions (conclusions that appear in all scenarios)
            universal_conclusions = self._find_universal_conclusions(valid_results)

            # Find conditional conclusions (conclusions specific to scenarios)
            conditional_conclusions = self._find_conditional_conclusions(valid_results)

            comparison_matrix = self._build_comparison_matrix(
                valid_results,
                include_best_result=select_best_result,
            )

            return _matrix_response(
                {
                    "matrix_id": matrix_id,
                    "task": task,
                    "scenario_count": len(valid_results),
                    "combination_count": len(valid_results)
                    if use_agent_combinations or use_model_combinations
                    else 0,
                    "results": valid_results,
                    "best_result": best_result,
                    "selection_strategy": DEFAULT_SELECTION_STRATEGY if best_result else None,
                    "universal_conclusions": universal_conclusions,
                    "conditional_conclusions": conditional_conclusions,
                    "comparison_matrix": comparison_matrix,
                    "org_id": scope.org_id,
                    "created_by": scope.user_id,
                }
            )

        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
            logger.exception("Matrix debate fallback failed: %s", e)
            return error_response(safe_error_message(e, "matrix debate"), 500)

    def _find_universal_conclusions(self, results: list[dict]) -> list[str]:
        """Find conclusions that are consistent across all scenarios."""
        if not results:
            return []

        # Simple heuristic: if all scenarios reached consensus, that's universal
        consensus_results = [r for r in results if r.get("consensus_reached")]
        if len(consensus_results) == len(results):
            return ["All scenarios reached consensus"]

        return []

    def _find_conditional_conclusions(self, results: list[dict]) -> list[dict]:
        """Find conclusions that depend on specific scenarios."""
        conditional = []
        for r in results:
            if r.get("final_answer"):
                conditional.append(
                    {
                        "condition": f"When {r['scenario_name']}",
                        "parameters": r.get("parameters", {}),
                        "conclusion": r["final_answer"],
                        "confidence": r.get("confidence", 0),
                    }
                )
        return conditional

    def _build_comparison_matrix(
        self, results: list[dict], include_best_result: bool = True
    ) -> dict:
        """Build a comparison matrix of scenarios."""
        best_result = self._select_best_result(results) if include_best_result else None
        comparison = {
            "scenarios": [r["scenario_name"] for r in results],
            "consensus_rate": sum(1 for r in results if r.get("consensus_reached"))
            / max(len(results), 1),
            "avg_confidence": sum(r.get("confidence", 0) for r in results) / max(len(results), 1),
            "avg_rounds": sum(r.get("rounds_used", 0) for r in results) / max(len(results), 1),
        }
        if best_result is not None:
            comparison["best_result_name"] = best_result.get("scenario_name")
            comparison["best_result_score"] = best_result.get("selection_score")
            comparison["selection_strategy"] = best_result.get(
                "selection_strategy",
                DEFAULT_SELECTION_STRATEGY,
            )
        return comparison

    async def _load_agents(self, agent_names: list[str]) -> list[Any]:
        """Load agents by name."""
        names = agent_names or ["claude", "openai"]
        return await self._load_agents_from_specs(names)

    async def _load_visible_matrix(
        self, handler: Any, matrix_id: str, scope: OrgScope
    ) -> tuple[Any, HandlerResult | None]:
        """Load a matrix debate of the caller's org: ``(matrix, None)`` or ``(None, error)``.

        Reads storage when it has a matrix getter, else the runs this process created.
        """
        matrix: Any = None
        getter = getattr(getattr(handler, "storage", None), "get_matrix_debate", None)
        if callable(getter):
            try:
                matrix = await getter(matrix_id)
            except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
                logger.error("Failed to get matrix debate %s: %s", matrix_id, e)
                return None, error_response("Failed to retrieve matrix debate", 500)
        if not matrix and matrix_id in _matrix_debate_cache:
            matrix = deepcopy(_matrix_debate_cache[matrix_id])

        if isinstance(matrix, dict):
            org_id = matrix.get("org_id")
        else:
            org_id = getattr(matrix, "org_id", None)
        if not matrix or not record_visible(org_id, scope):
            return None, record_not_found("Matrix debate")
        return matrix, None

    async def _get_matrix_debate(
        self, handler: Any, matrix_id: str, scope: OrgScope
    ) -> HandlerResult:
        """Get a matrix debate by ID."""
        matrix, error = await self._load_visible_matrix(handler, matrix_id, scope)
        if error is not None:
            return error
        return json_response(matrix)

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/matrix/{matrix_id}/scenarios",
        summary="Get matrix debate scenarios",
        description="Get all scenario results from a matrix debate.",
        tags=["Debates", "Matrix Debates"],
        parameters=[
            {"name": "matrix_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        responses={
            "200": {"description": "List of scenario results"},
            "401": {"description": "Authentication required"},
            "503": {"description": "Storage not configured"},
        },
    )
    async def _get_scenarios(self, handler: Any, matrix_id: str, scope: OrgScope) -> HandlerResult:
        """Get all scenario results for a matrix debate."""
        matrix, error = await self._load_visible_matrix(handler, matrix_id, scope)
        if error is not None:
            return error

        getter = getattr(getattr(handler, "storage", None), "get_matrix_scenarios", None)
        try:
            if callable(getter):
                scenarios = await getter(matrix_id)
            else:
                scenarios = matrix.get("results", [])
            return json_response({"matrix_id": matrix_id, "scenarios": scenarios})
        except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
            logger.error("Failed to get scenarios for %s: %s", matrix_id, e)
            return error_response("Failed to retrieve scenarios", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/matrix/{matrix_id}/conclusions",
        summary="Get matrix debate conclusions",
        description="Get universal and conditional conclusions from a matrix debate.",
        tags=["Debates", "Matrix Debates"],
        parameters=[
            {"name": "matrix_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        responses={
            "200": {"description": "Universal and conditional conclusions"},
            "401": {"description": "Authentication required"},
            "503": {"description": "Storage not configured"},
        },
    )
    async def _get_conclusions(
        self, handler: Any, matrix_id: str, scope: OrgScope
    ) -> HandlerResult:
        """Get conclusions for a matrix debate."""
        matrix, error = await self._load_visible_matrix(handler, matrix_id, scope)
        if error is not None:
            return error

        getter = getattr(getattr(handler, "storage", None), "get_matrix_conclusions", None)
        try:
            if callable(getter):
                conclusions = await getter(matrix_id)
            else:
                conclusions = {
                    "universal": matrix.get("universal_conclusions", []),
                    "conditional": matrix.get("conditional_conclusions", []),
                }
            return json_response(
                {
                    "matrix_id": matrix_id,
                    "universal_conclusions": conclusions.get("universal", []),
                    "conditional_conclusions": conclusions.get("conditional", []),
                }
            )
        except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
            logger.error("Failed to get conclusions for %s: %s", matrix_id, e)
            return error_response("Failed to retrieve conclusions", 500)
