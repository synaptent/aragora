"""
Vertical specialist endpoint handlers.

Stability: STABLE

Exposes the vertical specialist system for domain-specific AI agents.

Endpoints:
- GET /api/verticals - List available verticals
- GET /api/verticals/:id - Get vertical config
- PUT /api/verticals/:id/config - Update vertical configuration
- GET /api/verticals/:id/tools - Get vertical tools
- GET /api/verticals/:id/compliance - Get compliance frameworks
- POST /api/verticals/:id/debate - Create vertical-specific debate
- POST /api/verticals/:id/agent - Create specialist agent instance
- GET /api/verticals/suggest - Suggest vertical for a task

Features:
- Circuit breaker pattern for registry access resilience
- Rate limiting (60 requests/minute)
- RBAC permission checks (verticals:read, verticals:update)
- Comprehensive input validation with safe ID patterns
- Error isolation (registry failures handled gracefully)
"""

from __future__ import annotations

import logging
import threading
from typing import Any, cast

from aragora.config import DEFAULT_ROUNDS
from aragora.server.validation import validate_path_segment, SAFE_ID_PATTERN
from aragora.server.versioning.compat import strip_version_prefix


from ..base import (
    HandlerResult,
    error_response,
    get_string_param,
    json_response,
    safe_error_message,
)
from ..secure import SecureHandler
from ..utils.auth import ForbiddenError, UnauthorizedError
from ..utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)


# =============================================================================
# Circuit Breaker for Vertical Registry Access
# =============================================================================

from aragora.resilience.simple_circuit_breaker import (
    SimpleCircuitBreaker as VerticalsCircuitBreaker,
)

# Global circuit breaker instance for the vertical registry
_circuit_breaker = VerticalsCircuitBreaker("verticals", failure_threshold=3, half_open_max_calls=2)
_circuit_breaker_lock = threading.Lock()


def get_verticals_circuit_breaker() -> VerticalsCircuitBreaker:
    """Get the global circuit breaker for verticals registry."""
    return _circuit_breaker


def reset_verticals_circuit_breaker() -> None:
    """Reset the global circuit breaker (for testing)."""
    with _circuit_breaker_lock:
        _circuit_breaker.reset()


class VerticalsHandler(SecureHandler):
    """Handler for vertical specialist endpoints with RBAC protection.

    Stability: STABLE

    Features:
    - Circuit breaker pattern for registry access resilience
    - Rate limiting (60 requests/minute)
    - RBAC permission checks (verticals.read, verticals.update)
    - Comprehensive input validation with safe ID patterns
    """

    # Input validation constants
    MAX_TOPIC_LENGTH = 100_000
    MAX_AGENT_NAME_LENGTH = 100
    MAX_ADDITIONAL_AGENTS = 10
    MAX_TOOLS_COUNT = 50
    MAX_FRAMEWORKS_COUNT = 20
    MAX_KEYWORD_LENGTH = 200
    MAX_TASK_LENGTH = 100_000

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}
        self._circuit_breaker = get_verticals_circuit_breaker()

    RESOURCE_TYPE = "verticals"

    ROUTES = [
        "/api/verticals",
        "/api/verticals/suggest",
        "/api/verticals/*",
        "/api/verticals/*/config",
        "/api/verticals/*/tools",
        "/api/verticals/*/compliance",
        "/api/verticals/*/debate",
        "/api/verticals/*/agent",
        "/api/v1/verticals",
        "/api/v1/verticals/suggest",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can handle the request."""
        path = strip_version_prefix(path)
        if path == "/api/verticals":
            return True
        if path == "/api/verticals/suggest":
            return True
        if path.startswith("/api/verticals/"):
            return True
        return False

    def get_circuit_breaker_status(self) -> dict[str, Any]:
        """Get the current status of the circuit breaker."""
        return self._circuit_breaker.get_status()

    @rate_limit(requests_per_minute=60)
    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any = None
    ) -> HandlerResult | None:
        """Route request to appropriate handler method."""
        path = strip_version_prefix(path)
        # Get HTTP method from handler
        method = getattr(handler, "command", "GET") if handler else "GET"

        # RBAC check - skip auth for GET (public read-only dashboard data)
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            try:
                auth_context = await self.get_auth_context(handler, require_auth=True)
                self.check_permission(auth_context, "verticals.update")
            except UnauthorizedError:
                return error_response("Authentication required", 401)
            except ForbiddenError as e:
                logger.warning("Handler error: %s", e)
                return error_response("Permission denied", 403)

        # Check circuit breaker before proceeding
        if not self._circuit_breaker.can_proceed():
            logger.warning("Verticals circuit breaker is open, rejecting request")
            return error_response("Service temporarily unavailable. Please try again later.", 503)

        # GET /api/verticals - List all verticals
        if path == "/api/verticals" and method == "GET":
            return self._list_verticals(query_params)

        # GET /api/verticals/suggest - Suggest vertical for task
        if path == "/api/verticals/suggest" and method == "GET":
            return self._suggest_vertical(query_params)

        # Handle specific vertical endpoints
        if path.startswith("/api/verticals/"):
            parts = path.split("/")

            # GET /api/verticals/:id/tools
            if len(parts) == 5 and parts[4] == "tools" and method == "GET":
                vertical_id = parts[3]
                is_valid, err = validate_path_segment(vertical_id, "vertical_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return self._get_tools(vertical_id)

            # GET /api/verticals/:id/compliance
            if len(parts) == 5 and parts[4] == "compliance" and method == "GET":
                vertical_id = parts[3]
                is_valid, err = validate_path_segment(vertical_id, "vertical_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return self._get_compliance(vertical_id, query_params)

            # PUT /api/verticals/:id/config
            if len(parts) == 5 and parts[4] == "config" and method == "PUT":
                vertical_id = parts[3]
                is_valid, err = validate_path_segment(vertical_id, "vertical_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return self._update_config(vertical_id, handler)

            # POST /api/verticals/:id/debate
            if len(parts) == 5 and parts[4] == "debate" and method == "POST":
                vertical_id = parts[3]
                is_valid, err = validate_path_segment(vertical_id, "vertical_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return await self._create_debate(vertical_id, handler)

            # POST /api/verticals/:id/agent
            if len(parts) == 5 and parts[4] == "agent" and method == "POST":
                vertical_id = parts[3]
                is_valid, err = validate_path_segment(vertical_id, "vertical_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return self._create_agent(vertical_id, handler)

            # GET /api/verticals/:id
            if len(parts) == 4 and method == "GET":
                vertical_id = parts[3]
                is_valid, err = validate_path_segment(vertical_id, "vertical_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return self._get_vertical(vertical_id)

        return None

    def _get_registry_with_circuit_breaker(self) -> Any | None:
        """Get the VerticalRegistry with circuit breaker tracking."""
        try:
            from aragora.verticals import VerticalRegistry

            self._circuit_breaker.record_success()
            return VerticalRegistry
        except ImportError:
            self._circuit_breaker.record_failure()
            logger.warning("Verticals module not available")
            return None
        except (RuntimeError, OSError, AttributeError, TypeError) as e:
            self._circuit_breaker.record_failure()
            logger.error("Error loading verticals registry: %s", e)
            return None

    def _get_registry(self) -> Any | None:
        """Get the VerticalRegistry, handling import errors."""
        return self._get_registry_with_circuit_breaker()

    def _validate_keyword(self, keyword: str | None) -> tuple[bool, str]:
        """Validate keyword parameter.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if keyword is None:
            return True, ""
        if len(keyword) > self.MAX_KEYWORD_LENGTH:
            return False, f"keyword exceeds maximum length of {self.MAX_KEYWORD_LENGTH}"
        return True, ""

    def _validate_task(self, task: str | None) -> tuple[bool, str]:
        """Validate task parameter.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if task is None:
            return False, "Missing required parameter: task"
        if not task.strip():
            return False, "task cannot be empty"
        if len(task) > self.MAX_TASK_LENGTH:
            return False, f"task exceeds maximum length of {self.MAX_TASK_LENGTH}"
        return True, ""

    def _validate_topic(self, topic: str | None) -> tuple[bool, str]:
        """Validate topic parameter.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if topic is None:
            return False, "Missing required field: topic"
        if not topic.strip():
            return False, "topic cannot be empty"
        if len(topic) > self.MAX_TOPIC_LENGTH:
            return False, f"topic exceeds maximum length of {self.MAX_TOPIC_LENGTH}"
        return True, ""

    def _validate_agent_name(self, name: str | None) -> tuple[bool, str]:
        """Validate agent name parameter.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if name is None:
            return True, ""  # Name is optional
        if len(name) > self.MAX_AGENT_NAME_LENGTH:
            return False, f"agent name exceeds maximum length of {self.MAX_AGENT_NAME_LENGTH}"
        # Validate safe characters
        is_valid, err = validate_path_segment(name, "agent_name", SAFE_ID_PATTERN)
        return is_valid, err

    def _validate_additional_agents(self, agents: list | None) -> tuple[bool, str]:
        """Validate additional agents list.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if agents is None:
            return True, ""
        if not isinstance(agents, list):
            return False, "additional_agents must be a list"
        if len(agents) > self.MAX_ADDITIONAL_AGENTS:
            return (
                False,
                f"additional_agents exceeds maximum count of {self.MAX_ADDITIONAL_AGENTS}",
            )
        return True, ""

    def _list_verticals(self, query_params: dict[str, Any]) -> HandlerResult:
        """List all available verticals."""
        registry = self._get_registry()
        if registry is None:
            return json_response(
                {
                    "verticals": [],
                    "total": 0,
                    "message": "Verticals module not available",
                },
                status=503,
            )

        try:
            # Get optional keyword filter with validation
            keyword = get_string_param(query_params, "keyword", None)
            is_valid, err = self._validate_keyword(keyword)
            if not is_valid:
                return error_response(err, 400)

            if keyword:
                # Filter by keyword
                matching_ids = registry.get_by_keyword(keyword)
                all_verticals = registry.list_all()
                verticals = {
                    vid: all_verticals[vid] for vid in matching_ids if vid in all_verticals
                }
            else:
                verticals = registry.list_all()

            self._circuit_breaker.record_success()
            return json_response(
                {
                    "verticals": [
                        {
                            "vertical_id": vid,
                            **data,
                        }
                        for vid, data in verticals.items()
                    ],
                    "total": len(verticals),
                }
            )

        except (KeyError, ValueError, TypeError) as e:
            self._circuit_breaker.record_failure()
            logger.warning("Data error listing verticals: %s", e)
            return error_response(safe_error_message(e, "list verticals"), 400)
        except (RuntimeError, OSError, AttributeError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Unexpected error listing verticals: %s", e)
            return error_response(safe_error_message(e, "list verticals"), 500)

    def _get_vertical(self, vertical_id: str) -> HandlerResult:
        """Get a specific vertical's configuration."""
        registry = self._get_registry()
        if registry is None:
            return error_response("Verticals module not available", 503)

        try:
            spec = registry.get(vertical_id)
            if spec is None:
                available = registry.get_registered_ids()
                return error_response(
                    f"Vertical not found: {vertical_id}. Available: {', '.join(available)}",
                    404,
                )

            config = spec.config

            self._circuit_breaker.record_success()
            return json_response(
                {
                    "vertical_id": vertical_id,
                    "display_name": config.display_name,
                    "description": spec.description,
                    "domain_keywords": config.domain_keywords,
                    "expertise_areas": config.expertise_areas,
                    "tools": [t.to_dict() for t in config.tools],
                    "compliance_frameworks": [c.to_dict() for c in config.compliance_frameworks],
                    "model_config": config.model_config.to_dict(),
                    "version": config.version,
                    "author": config.author,
                    "tags": config.tags,
                }
            )

        except (KeyError, AttributeError, TypeError) as e:
            self._circuit_breaker.record_failure()
            logger.warning("Data error getting vertical %s: %s", vertical_id, e)
            return error_response(safe_error_message(e, "get vertical"), 400)
        except (RuntimeError, OSError, ValueError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Unexpected error getting vertical %s: %s", vertical_id, e)
            return error_response(safe_error_message(e, "get vertical"), 500)

    def _get_tools(self, vertical_id: str) -> HandlerResult:
        """Get tools available for a vertical."""
        registry = self._get_registry()
        if registry is None:
            return error_response("Verticals module not available", 503)

        try:
            config = registry.get_config(vertical_id)
            if config is None:
                return error_response(f"Vertical not found: {vertical_id}", 404)

            tools = config.tools
            enabled_tools = config.get_enabled_tools()

            self._circuit_breaker.record_success()
            return json_response(
                {
                    "vertical_id": vertical_id,
                    "tools": [t.to_dict() for t in tools],
                    "enabled_count": len(enabled_tools),
                    "total_count": len(tools),
                }
            )

        except (KeyError, AttributeError, TypeError) as e:
            self._circuit_breaker.record_failure()
            logger.warning("Data error getting tools for %s: %s", vertical_id, e)
            return error_response(safe_error_message(e, "get vertical tools"), 400)
        except (RuntimeError, OSError, ValueError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Unexpected error getting tools for %s: %s", vertical_id, e)
            return error_response(safe_error_message(e, "get vertical tools"), 500)

    def _get_compliance(self, vertical_id: str, query_params: dict[str, Any]) -> HandlerResult:
        """Get compliance frameworks for a vertical."""
        registry = self._get_registry()
        if registry is None:
            return error_response("Verticals module not available", 503)

        try:
            from aragora.verticals.config import ComplianceLevel

            config = registry.get_config(vertical_id)
            if config is None:
                return error_response(f"Vertical not found: {vertical_id}", 404)

            # Optional filter by level
            level_filter = get_string_param(query_params, "level", None)
            level_enum = None
            if level_filter:
                try:
                    level_enum = ComplianceLevel(level_filter)
                except ValueError:
                    return error_response(
                        f"Invalid level: {level_filter}. "
                        f"Valid values: {[lvl.value for lvl in ComplianceLevel]}",
                        400,
                    )

            frameworks = config.get_compliance_frameworks(level=level_enum)

            self._circuit_breaker.record_success()
            return json_response(
                {
                    "vertical_id": vertical_id,
                    "compliance_frameworks": [f.to_dict() for f in frameworks],
                    "total": len(frameworks),
                }
            )

        except ImportError:
            self._circuit_breaker.record_failure()
            return error_response("Compliance module not available", 503)
        except (KeyError, AttributeError, TypeError) as e:
            self._circuit_breaker.record_failure()
            logger.warning("Data error getting compliance for %s: %s", vertical_id, e)
            return error_response(safe_error_message(e, "get vertical compliance"), 400)
        except (RuntimeError, OSError, ValueError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Unexpected error getting compliance for %s: %s", vertical_id, e)
            return error_response(safe_error_message(e, "get vertical compliance"), 500)

    def _suggest_vertical(self, query_params: dict[str, Any]) -> HandlerResult:
        """Suggest the best vertical for a task description."""
        registry = self._get_registry()
        if registry is None:
            return error_response("Verticals module not available", 503)

        task = get_string_param(query_params, "task", None)
        is_valid, err = self._validate_task(task)
        if not is_valid:
            return error_response(err, 400)

        try:
            suggested = registry.get_for_task(task)

            if suggested is None:
                return json_response(
                    {
                        "suggestion": None,
                        "message": "No vertical matches the given task",
                        "available_verticals": registry.get_registered_ids(),
                    }
                )

            spec = registry.get(suggested)
            config = spec.config if spec else None

            self._circuit_breaker.record_success()
            return json_response(
                {
                    "suggestion": {
                        "vertical_id": suggested,
                        "display_name": config.display_name if config else suggested,
                        "description": spec.description if spec else "",
                        "expertise_areas": config.expertise_areas if config else [],
                    },
                    "task": task,
                }
            )

        except (KeyError, AttributeError, TypeError) as e:
            self._circuit_breaker.record_failure()
            logger.warning("Data error suggesting vertical: %s", e)
            return error_response(safe_error_message(e, "suggest vertical"), 400)
        except (RuntimeError, OSError, ValueError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Unexpected error suggesting vertical: %s", e)
            return error_response(safe_error_message(e, "suggest vertical"), 500)

    async def _create_debate(self, vertical_id: str, handler: Any) -> HandlerResult:
        """Create a debate using a vertical specialist."""
        registry = self._get_registry()
        if registry is None:
            return error_response("Verticals module not available", 503)

        # Validate vertical exists
        if not registry.is_registered(vertical_id):
            return error_response(f"Vertical not found: {vertical_id}", 404)

        # Parse request body
        data = self.read_json_body(handler)
        if data is None:
            return error_response("Invalid or too large request body", 400)

        # Validate topic
        topic = data.get("topic")
        is_valid, err = self._validate_topic(topic)
        if not is_valid:
            return error_response(err, 400)

        # Validate agent name if provided
        agent_name = data.get("agent_name")
        is_valid, err = self._validate_agent_name(agent_name)
        if not is_valid:
            return error_response(err, 400)

        # Validate additional agents if provided
        additional_agents = data.get("additional_agents", [])
        is_valid, err = self._validate_additional_agents(additional_agents)
        if not is_valid:
            return error_response(err, 400)

        # Validate rounds
        rounds = data.get("rounds", DEFAULT_ROUNDS)
        if not isinstance(rounds, int) or rounds < 1 or rounds > 20:
            return error_response("rounds must be an integer between 1 and 20", 400)

        try:
            # Import debate infrastructure
            from aragora.core import DebateProtocol, Environment
            from aragora.debate.orchestrator import Arena

            # Create specialist agent
            if agent_name is None:
                agent_name = f"{vertical_id}-specialist"
            model = data.get("model")
            role = data.get("role", "specialist")

            specialist = registry.create_specialist(
                vertical_id=vertical_id,
                name=agent_name,
                model=model,
                role=role,
            )

            # Get additional agents if specified
            agents = [specialist]

            if additional_agents:
                from aragora.agents.base import AgentType, create_agent

                for agent_spec in additional_agents:
                    if isinstance(agent_spec, str):
                        agents.append(create_agent(cast(AgentType, agent_spec)))
                    elif isinstance(agent_spec, dict):
                        agents.append(
                            create_agent(
                                cast(AgentType, agent_spec.get("type", "anthropic-api")),
                                name=agent_spec.get("name"),
                                role=agent_spec.get("role"),
                            )
                        )

            # Create environment and protocol
            env = Environment(task=topic)
            protocol = DebateProtocol(
                rounds=rounds,
                consensus=data.get("consensus", "weighted"),
            )

            # Run debate
            ctx = getattr(self, "ctx", {}) or {}
            arena = Arena(
                env,
                agents=agents,
                protocol=protocol,
                document_store=ctx.get("document_store"),
                evidence_store=ctx.get("evidence_store"),
            )
            result = await arena.run()

            self._circuit_breaker.record_success()
            return json_response(
                {
                    "debate_id": (result.debate_id if hasattr(result, "debate_id") else None),
                    "vertical_id": vertical_id,
                    "topic": topic,
                    "consensus_reached": (
                        result.consensus_reached if hasattr(result, "consensus_reached") else False
                    ),
                    "final_answer": (
                        result.final_answer if hasattr(result, "final_answer") else None
                    ),
                    "confidence": (result.confidence if hasattr(result, "confidence") else 0.0),
                    "participants": [a.name for a in agents],
                }
            )

        except ImportError as e:
            self._circuit_breaker.record_failure()
            logger.error("Debate infrastructure not available: %s", e)
            return error_response("Debate infrastructure not available", 503)
        except (ValueError, KeyError, TypeError) as e:
            self._circuit_breaker.record_failure()
            logger.warning("Invalid data for debate creation in %s: %s", vertical_id, e)
            return error_response(safe_error_message(e, "create vertical debate"), 400)
        except (RuntimeError, OSError, AttributeError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Unexpected error creating debate for %s: %s", vertical_id, e)
            return error_response(safe_error_message(e, "create vertical debate"), 500)

    def _create_agent(self, vertical_id: str, handler: Any) -> HandlerResult:
        """Create a specialist agent instance."""
        registry = self._get_registry()
        if registry is None:
            return error_response("Verticals module not available", 503)

        # Validate vertical exists
        if not registry.is_registered(vertical_id):
            return error_response(f"Vertical not found: {vertical_id}", 404)

        # Parse request body
        data = self.read_json_body(handler)
        if data is None:
            return error_response("Invalid or too large request body", 400)

        # Validate agent name if provided
        name = data.get("name")
        is_valid, err = self._validate_agent_name(name)
        if not is_valid:
            return error_response(err, 400)

        try:
            # Create specialist with provided config
            if name is None:
                name = f"{vertical_id}-agent"
            model = data.get("model")
            role = data.get("role", "specialist")

            specialist = registry.create_specialist(
                vertical_id=vertical_id,
                name=name,
                model=model,
                role=role,
            )

            self._circuit_breaker.record_success()
            return json_response(
                {
                    "agent": specialist.to_dict(),
                    "vertical_id": vertical_id,
                    "name": specialist.name,
                    "model": specialist.model,
                    "role": specialist.role,
                    "expertise_areas": specialist.expertise_areas,
                    "tools": [t.name for t in specialist.get_enabled_tools()],
                    "message": "Specialist agent created successfully",
                }
            )

        except ValueError as e:
            self._circuit_breaker.record_failure()
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)
        except (KeyError, TypeError, AttributeError) as e:
            self._circuit_breaker.record_failure()
            logger.warning("Data error creating agent for %s: %s", vertical_id, e)
            return error_response(safe_error_message(e, "create vertical agent"), 400)
        except (RuntimeError, OSError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Unexpected error creating agent for %s: %s", vertical_id, e)
            return error_response(safe_error_message(e, "create vertical agent"), 500)

    def _update_config(self, vertical_id: str, handler: Any) -> HandlerResult:
        """Update configuration for a vertical.

        Accepts partial updates for:
        - tools: List of tool configurations with enabled states
        - compliance_frameworks: List of compliance framework updates
        - model_config: Model configuration overrides
        """
        registry = self._get_registry()
        if registry is None:
            return error_response("Verticals module not available", 503)

        # Validate vertical exists
        if not registry.is_registered(vertical_id):
            return error_response(f"Vertical not found: {vertical_id}", 404)

        # Parse request body
        data = self.read_json_body(handler)
        if data is None:
            return error_response("Invalid or too large request body", 400)

        try:
            from aragora.verticals.config import (
                ComplianceConfig,
                ComplianceLevel,
                ModelConfig,
                ToolConfig,
            )

            spec = registry.get(vertical_id)
            if spec is None:
                return error_response(f"Vertical not found: {vertical_id}", 404)

            config = spec.config
            updates_applied = []

            # Update tools if provided
            if "tools" in data:
                tools_data = data["tools"]
                if not isinstance(tools_data, list):
                    return error_response("tools must be a list", 400)
                if len(tools_data) > self.MAX_TOOLS_COUNT:
                    return error_response(
                        f"tools exceeds maximum count of {self.MAX_TOOLS_COUNT}", 400
                    )

                new_tools = []
                for tool_data in tools_data:
                    if isinstance(tool_data, dict):
                        # Validate tool name
                        tool_name = tool_data.get("name", "")
                        if tool_name and len(tool_name) > self.MAX_AGENT_NAME_LENGTH:
                            return error_response(
                                f"Tool name exceeds maximum length of {self.MAX_AGENT_NAME_LENGTH}",
                                400,
                            )
                        # Create new tool from data
                        tool = ToolConfig(
                            name=tool_name,
                            description=tool_data.get("description", ""),
                            enabled=tool_data.get("enabled", True),
                            connector_type=tool_data.get("connector_type"),
                            parameters=tool_data.get("parameters", {}),
                        )
                        new_tools.append(tool)
                config.tools = new_tools
                updates_applied.append("tools")

            # Update compliance frameworks if provided
            if "compliance_frameworks" in data:
                frameworks_data = data["compliance_frameworks"]
                if not isinstance(frameworks_data, list):
                    return error_response("compliance_frameworks must be a list", 400)
                if len(frameworks_data) > self.MAX_FRAMEWORKS_COUNT:
                    return error_response(
                        f"compliance_frameworks exceeds maximum count of "
                        f"{self.MAX_FRAMEWORKS_COUNT}",
                        400,
                    )

                new_frameworks = []
                for fw_data in frameworks_data:
                    if isinstance(fw_data, dict):
                        level_str = fw_data.get("level", "warning")
                        try:
                            level = ComplianceLevel(level_str)
                        except ValueError:
                            level = ComplianceLevel.WARNING
                        framework = ComplianceConfig(
                            framework=fw_data.get("framework", fw_data.get("name", "")),
                            version=fw_data.get("version", "latest"),
                            level=level,
                            rules=fw_data.get("rules", []),
                            exemptions=fw_data.get("exemptions", []),
                        )
                        new_frameworks.append(framework)
                config.compliance_frameworks = new_frameworks
                updates_applied.append("compliance_frameworks")

            # Update model config if provided
            if "model_config" in data:
                model_data = data["model_config"]
                if not isinstance(model_data, dict):
                    return error_response("model_config must be an object", 400)

                # Validate temperature
                temperature = model_data.get("temperature", config.model_config.temperature)
                if not isinstance(temperature, (int, float)) or temperature < 0 or temperature > 2:
                    return error_response("temperature must be a number between 0 and 2", 400)

                # Validate max_tokens
                max_tokens = model_data.get("max_tokens", config.model_config.max_tokens)
                if not isinstance(max_tokens, int) or max_tokens < 1 or max_tokens > 200000:
                    return error_response("max_tokens must be an integer between 1 and 200000", 400)

                model_config = ModelConfig(
                    primary_model=model_data.get(
                        "primary_model", config.model_config.primary_model
                    ),
                    primary_provider=model_data.get(
                        "primary_provider", config.model_config.primary_provider
                    ),
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                config.model_config = model_config
                updates_applied.append("model_config")

            if not updates_applied:
                return error_response(
                    "No valid fields to update. Provide: tools, compliance_frameworks, "
                    "or model_config",
                    400,
                )

            # Log the update
            logger.info("Updated vertical %s config: %s", vertical_id, updates_applied)

            # Persist to database so changes survive restarts
            try:
                from aragora.storage.repositories.verticals import (
                    get_verticals_config_repository,
                )

                repo = get_verticals_config_repository()
                repo.save_config(
                    vertical_id,
                    {
                        "tools": [t.to_dict() for t in config.tools],
                        "compliance_frameworks": [
                            c.to_dict() for c in config.compliance_frameworks
                        ],
                        "model_config": config.model_config.to_dict(),
                    },
                )
            except Exception as persist_err:  # noqa: BLE001
                logger.warning(
                    "Config updated in-memory but persistence failed for %s: %s",
                    vertical_id,
                    persist_err,
                )

            self._circuit_breaker.record_success()
            return json_response(
                {
                    "vertical_id": vertical_id,
                    "updated_fields": updates_applied,
                    "message": f"Configuration updated successfully for {vertical_id}",
                    "current_config": {
                        "tools": [t.to_dict() for t in config.tools],
                        "compliance_frameworks": [
                            c.to_dict() for c in config.compliance_frameworks
                        ],
                        "model_config": config.model_config.to_dict(),
                    },
                }
            )

        except ImportError as e:
            self._circuit_breaker.record_failure()
            logger.error("Verticals config module not available: %s", e)
            return error_response("Verticals config module not available", 503)
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            self._circuit_breaker.record_failure()
            logger.warning("Data error updating config for %s: %s", vertical_id, e)
            return error_response(safe_error_message(e, "update vertical config"), 400)
        except (RuntimeError, OSError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Unexpected error updating config for %s: %s", vertical_id, e)
            return error_response(safe_error_message(e, "update vertical config"), 500)
