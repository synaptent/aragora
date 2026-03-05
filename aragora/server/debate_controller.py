"""
Controller for ad-hoc debate execution.

Handles debate lifecycle orchestration using DebateFactory for creation
and debate_utils for state management. Extracted from unified_server.py
for better modularity and testability.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.config import (
    DEBATE_TIMEOUT_SECONDS,
    DEFAULT_AGENTS,
    DEFAULT_CONSENSUS,
    DEFAULT_ROUNDS,
    MAX_CONCURRENT_DEBATES,
    MAX_ROUNDS,
)
from aragora.server.debate_factory import (
    DEFAULT_ENABLE_VERTICALS,
    DebateConfig,
    DebateFactory,
)
from aragora.server.debate_utils import (
    _active_debates,
    _active_debates_lock,
    cleanup_stale_debates,
    update_debate_status,
)
from aragora.server.errors import safe_error_message
from aragora.server.http_utils import run_async
from aragora.server.state import get_state_manager
from aragora.server.stream import (
    StreamEvent,
    StreamEventType,
    create_arena_hooks,
    wrap_agent_for_streaming,
)

# Default classification when Haiku call fails or times out
_DEFAULT_CLASSIFICATION = {
    "type": "general",
    "domain": "other",
    "complexity": "moderate",
    "aspects": [],
    "approach": "Agents will analyze this topic from multiple perspectives.",
}

_EPISTEMIC_HYGIENE_MODE = "epistemic_hygiene"
_EPISTEMIC_HYGIENE_PROMPT = (
    "Epistemic hygiene protocol:\n"
    "1) Separate observations from assumptions and inferences.\n"
    "2) Include at least one strong alternative explanation and disconfirming evidence.\n"
    "3) State confidence bounds and key uncertainty drivers.\n"
    "4) End with a concrete falsifier and measurable settlement metric."
)
_PRODUCTION_LIKE_ENVS = {"production", "prod", "live", "staging", "stage"}
_REQUIRED_PRODUCTION_SETTLEMENT_FIELDS = (
    "falsifier",
    "metric",
    "review_horizon_days",
    "resolver_type",
)
_DEFAULT_SETTLEMENT_FALSIFIER = "Define an objective falsifier for the primary claim."
_DEFAULT_SETTLEMENT_METRIC = "Define a measurable metric for decision settlement."
_DEFAULT_SETTLEMENT_CLAIM = "Define the primary claim under debate."
_DEFAULT_SETTLEMENT_RESOLVER_TYPE = "human"
_ALLOWED_SETTLEMENT_RESOLVER_TYPES = {"human", "deterministic", "oracle"}

if TYPE_CHECKING:
    from aragora.server.stream import SyncEventEmitter

logger = logging.getLogger(__name__)


def _parse_budget_limit(value: Any) -> float | None:
    """Parse budget_limit_usd from request body, clamping to safe range."""
    if value is None:
        return None
    try:
        limit = float(value)
        if limit <= 0:
            return None
        return min(limit, 100.0)  # Cap at $100 for safety
    except (ValueError, TypeError):
        return None


def _resolve_template(name: str):
    """Resolve a deliberation template by name.

    Returns:
        DeliberationTemplate or None if not found
    """
    try:
        from aragora.deliberation.templates.registry import get_template

        return get_template(name)
    except (ImportError, RuntimeError):
        return None


def _normalize_documents(value: Any, max_items: int = 50) -> list[str]:
    """Normalize document ID input to a clean list of strings."""
    if not value:
        return []
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, list):
        candidates = value
    else:
        return []

    seen: set[str] = set()
    normalized: list[str] = []
    for item in candidates:
        if not isinstance(item, str):
            continue
        doc_id = item.strip()
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        normalized.append(doc_id)
        if len(normalized) >= max_items:
            break
    return normalized


def _normalize_agent_names(agents_value: Any) -> list[str]:
    """Normalize agent specs into a list of display names/providers."""
    if not agents_value:
        return []
    if isinstance(agents_value, str):
        return [a.strip() for a in agents_value.split(",") if a.strip()]

    names: list[str] = []
    if isinstance(agents_value, list):
        for item in agents_value:
            if isinstance(item, str):
                name = item.strip()
            elif isinstance(item, dict):
                name = (
                    item.get("name")
                    or item.get("provider")
                    or item.get("agent_type")
                    or item.get("id")
                )
            else:
                name = getattr(item, "name", None) or getattr(item, "provider", None)
            if name:
                names.append(str(name))
        return names

    return []


def _is_truthy_flag(value: Any) -> bool:
    """Interpret flexible boolean request flags."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _normalize_mode(raw_mode: Any) -> str | None:
    """Normalize optional debate mode into a stable token."""
    if raw_mode is None:
        return None
    mode = str(raw_mode).strip().lower().replace("-", "_").replace(" ", "_")
    if not mode or mode in {"default", "standard"}:
        return None
    if mode in {"epistemic", "hygiene", "epistemic_hygiene"}:
        return _EPISTEMIC_HYGIENE_MODE
    return mode


def _append_epistemic_hygiene_prompt(context: Any) -> str:
    """Append epistemic hygiene guidance to user context once."""
    base_context = str(context).strip() if isinstance(context, str) else ""
    if _EPISTEMIC_HYGIENE_PROMPT in base_context:
        return base_context or _EPISTEMIC_HYGIENE_PROMPT
    if not base_context:
        return _EPISTEMIC_HYGIENE_PROMPT
    return f"{base_context}\n\n{_EPISTEMIC_HYGIENE_PROMPT}"


def _is_production_like_env() -> bool:
    """True when running in production-like environments."""
    return os.environ.get("ARAGORA_ENV", "development").strip().lower() in _PRODUCTION_LIKE_ENVS


def _coerce_positive_int(value: Any, *, default: int) -> int:
    """Best-effort conversion for positive integer fields."""
    try:
        parsed = int(value)
    except (ValueError, TypeError):
        return default
    return parsed if parsed > 0 else default


def _normalize_resolver_type(
    value: Any, *, default: str = _DEFAULT_SETTLEMENT_RESOLVER_TYPE
) -> str:
    """Normalize resolver types into stable canonical values."""
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    if raw in {"deterministic", "ci", "test", "tests", "auto"}:
        return "deterministic"
    if raw in {"oracle", "onchain", "blockchain", "feed"}:
        return "oracle"
    if raw in {"human", "manual", "reviewer", "analyst"}:
        return "human"
    return raw


def _normalize_settlement_metadata(
    settlement: Any,
    *,
    claim_fallback: str | None = None,
) -> dict[str, Any]:
    """Normalize settlement metadata into a stable shape."""
    raw = settlement if isinstance(settlement, dict) else {}
    claim = str(raw.get("claim") or claim_fallback or _DEFAULT_SETTLEMENT_CLAIM).strip()
    resolver_hint = _normalize_resolver_type(
        raw.get("resolver_type") or raw.get("resolution_tier") or raw.get("verification_mode")
    )
    normalized: dict[str, Any] = {
        "status": str(raw.get("status") or "needs_definition").strip() or "needs_definition",
        "falsifier": (str(raw.get("falsifier") or _DEFAULT_SETTLEMENT_FALSIFIER).strip()),
        "metric": str(raw.get("metric") or _DEFAULT_SETTLEMENT_METRIC).strip(),
        "review_horizon_days": _coerce_positive_int(raw.get("review_horizon_days"), default=30),
        "claim": claim,
        "resolver_type": resolver_hint,
    }
    return normalized


def _validate_production_settlement_metadata(metadata: dict[str, Any]) -> None:
    """Require explicit settlement fields for epistemic hygiene debates in production."""
    settlement = metadata.get("settlement")
    if not isinstance(settlement, dict):
        raise ValueError("epistemic_hygiene mode requires metadata.settlement in production")

    missing: list[str] = []
    if (
        not isinstance(settlement.get("falsifier"), str)
        or not settlement.get("falsifier", "").strip()
    ):
        missing.append("falsifier")
    elif str(settlement.get("falsifier")).strip() == _DEFAULT_SETTLEMENT_FALSIFIER:
        missing.append("falsifier")
    if not isinstance(settlement.get("metric"), str) or not settlement.get("metric", "").strip():
        missing.append("metric")
    elif str(settlement.get("metric")).strip() == _DEFAULT_SETTLEMENT_METRIC:
        missing.append("metric")
    horizon = settlement.get("review_horizon_days")
    try:
        if int(horizon) <= 0:
            missing.append("review_horizon_days")
    except (ValueError, TypeError):
        missing.append("review_horizon_days")
    resolver_hint = settlement.get("resolver_type")
    if resolver_hint is None:
        resolver_hint = settlement.get("resolution_tier")
    if resolver_hint is None:
        resolver_hint = settlement.get("verification_mode")
    normalized_resolver = _normalize_resolver_type(
        resolver_hint,
        default="",
    )
    if normalized_resolver not in _ALLOWED_SETTLEMENT_RESOLVER_TYPES:
        missing.append("resolver_type")

    if missing:
        fields = ", ".join(_REQUIRED_PRODUCTION_SETTLEMENT_FIELDS)
        raise ValueError(
            f"epistemic_hygiene mode requires settlement fields in production: {fields} "
            f"(missing/invalid: {', '.join(missing)})"
        )


def _ensure_epistemic_hygiene_metadata(
    metadata: dict[str, Any],
    *,
    question: str | None = None,
) -> None:
    """Attach default settlement scaffolding for hygiene-mode debates."""
    metadata["mode"] = _EPISTEMIC_HYGIENE_MODE
    metadata["epistemic_hygiene"] = True
    metadata["settlement"] = _normalize_settlement_metadata(
        metadata.get("settlement"),
        claim_fallback=question,
    )


@dataclass
class DebateRequest:
    """Parsed debate request from HTTP body."""

    question: str
    agents_str: Any = DEFAULT_AGENTS
    rounds: int = DEFAULT_ROUNDS  # 9-round format (0-8), default for all debates
    consensus: str = DEFAULT_CONSENSUS  # Default consensus configuration
    debate_format: str = "full"  # "light" (~5 min) or "full" (~30 min)
    auto_select: bool = False
    auto_select_config: dict | None = None
    use_trending: bool = False
    trending_category: str | None = None
    metadata: dict | None = None  # Custom metadata (e.g., is_onboarding)
    documents: list[str] = field(default_factory=list)
    enable_verticals: bool = DEFAULT_ENABLE_VERTICALS
    vertical_id: str | None = None
    context: str | None = None  # Optional context for the debate
    mode: str | None = None  # Optional request mode (e.g., epistemic_hygiene)
    template_name: str | None = None  # Optional deliberation template name
    budget_limit_usd: float | None = None  # Per-debate budget cap
    enable_cartographer: bool | None = None  # Enable argument cartography
    enable_introspection: bool | None = None  # Enable agent introspection
    enable_auto_execution: bool | None = None  # Enable post-debate auto-execution
    enable_settlement_tracking: bool | None = None  # Enable settlement claim extraction
    enable_interventions: bool | None = None  # Enable intervention queue
    quality_pipeline: dict | None = None  # Post-consensus quality pipeline config

    def __post_init__(self):
        if self.auto_select_config is None:
            self.auto_select_config = {}
        if self.metadata is None:
            self.metadata = {}
        if self.documents is None:
            self.documents = []
        # Normalize debate_format
        if self.debate_format not in ("light", "full"):
            self.debate_format = "full"

    @classmethod
    def from_dict(cls, data: dict) -> DebateRequest:
        """Create request from parsed JSON data.

        Args:
            data: Parsed JSON dictionary

        Returns:
            DebateRequest instance

        Raises:
            ValueError: If required fields are missing or invalid
        """
        question = data.get("question") or data.get("task") or ""
        question = str(question).strip()
        if not question:
            raise ValueError("question or task field is required")
        if len(question) > 10000:
            raise ValueError("question must be under 10,000 characters")

        try:
            rounds = min(max(int(data.get("rounds", DEFAULT_ROUNDS)), 1), MAX_ROUNDS)
        except (ValueError, TypeError):
            rounds = DEFAULT_ROUNDS

        metadata_raw = data.get("metadata")
        metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}
        auto_select = bool(data.get("auto_select", False))
        auto_select_config = data.get("auto_select_config") or {}
        if not isinstance(auto_select_config, dict):
            auto_select_config = {}

        mode_raw = data.get("mode", metadata.get("mode"))
        if _is_truthy_flag(data.get("epistemic_hygiene")) or _is_truthy_flag(
            metadata.get("epistemic_hygiene")
        ):
            mode_raw = _EPISTEMIC_HYGIENE_MODE
        mode = _normalize_mode(mode_raw)

        raw_agents = data.get("agents", None)
        if raw_agents is None:
            agents_value: Any = [] if auto_select else DEFAULT_AGENTS
        else:
            agents_value = raw_agents

        enable_verticals = data.get("enable_verticals", metadata.get("enable_verticals", None))
        if enable_verticals is None:
            enable_verticals = DEFAULT_ENABLE_VERTICALS
        else:
            enable_verticals = bool(enable_verticals)
        vertical_id = data.get("vertical_id") or data.get("vertical") or metadata.get("vertical_id")

        # Template support: apply template defaults as fallbacks
        template_name = data.get("template")
        if template_name:
            template = _resolve_template(template_name)
            if template is None:
                raise ValueError(f"Unknown template: {template_name}")
            # Apply template defaults where user hasn't specified values
            if raw_agents is None and not auto_select and template.default_agents:
                agents_value = template.default_agents
            if "rounds" not in data:
                rounds = template.max_rounds
            if "consensus" not in data:
                consensus_val = str(template.consensus_threshold)
            else:
                consensus_val = data.get("consensus", DEFAULT_CONSENSUS)
            # Store template in metadata
            metadata["template_name"] = template_name
        else:
            consensus_val = data.get("consensus", DEFAULT_CONSENSUS)

        context = data.get("context")
        if mode == _EPISTEMIC_HYGIENE_MODE:
            if _is_production_like_env():
                _validate_production_settlement_metadata(metadata)
            _ensure_epistemic_hygiene_metadata(metadata, question=question)
            context = _append_epistemic_hygiene_prompt(context)
        elif mode is not None:
            metadata["mode"] = mode

        return cls(
            question=question,
            agents_str=agents_value,
            rounds=rounds,
            consensus=consensus_val,
            debate_format=data.get("debate_format", "full"),
            auto_select=auto_select,
            auto_select_config=auto_select_config,
            use_trending=data.get("use_trending", False),
            trending_category=data.get("trending_category"),
            metadata=metadata,
            documents=_normalize_documents(data.get("documents") or data.get("document_ids") or []),
            enable_verticals=enable_verticals,
            vertical_id=vertical_id,
            context=context,
            mode=mode,
            template_name=template_name,
            budget_limit_usd=_parse_budget_limit(data.get("budget_limit_usd")),
            enable_cartographer=data.get("enable_cartographer"),
            enable_introspection=data.get("enable_introspection"),
            enable_auto_execution=data.get("enable_auto_execution"),
            enable_settlement_tracking=data.get("enable_settlement_tracking"),
            enable_interventions=data.get("enable_interventions"),
            quality_pipeline=data.get("quality_pipeline"),
        )


@dataclass
class DebateResponse:
    """Response from debate controller."""

    success: bool
    debate_id: str | None = None
    status: str | None = None
    task: str | None = None
    error: str | None = None
    status_code: int = 200
    use_playground: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result: dict[str, Any] = {"success": self.success}
        if self.debate_id:
            result["debate_id"] = str(self.debate_id)
        if self.status:
            result["status"] = str(self.status)
        if self.task:
            result["task"] = str(self.task)
        if self.error:
            result["error"] = str(self.error)
        if self.use_playground:
            result["use_playground"] = True
        return result


class DebateController:
    """
    Controls debate execution lifecycle.

    Responsibilities:
    - Validates and processes debate requests
    - Coordinates with StateManager for thread pool access
    - Coordinates with DebateFactory for arena creation
    - Handles trending topic integration
    - Manages debate state through debate_utils

    Thread Safety:
        The thread pool is managed by StateManager which handles
        its own locking. All debate state is also managed through
        StateManager.

    Usage:
        controller = DebateController(
            factory=debate_factory,
            emitter=stream_emitter,
            elo_system=elo_system,
        )

        request = DebateRequest.from_dict(json_data)
        response = controller.start_debate(request)
    """

    def __init__(
        self,
        factory: DebateFactory,
        emitter: SyncEventEmitter,
        elo_system: Any | None = None,
        auto_select_fn: Callable[..., str] | None = None,
        storage: Any | None = None,
    ):
        """Initialize the debate controller.

        Args:
            factory: DebateFactory for creating arenas
            emitter: Event emitter for streaming
            elo_system: Optional ELO system for leaderboard updates
            auto_select_fn: Optional function for auto-selecting agents
            storage: Optional DebateStorage instance for persisting debates
        """
        self.factory = factory
        self.emitter = emitter
        self.elo_system = elo_system
        self.auto_select_fn = auto_select_fn
        self.storage = storage

    def _preflight_agents(self, agents_str: Any) -> str | None:
        """Validate agent availability before starting a debate.

        Returns:
            Error message if agents are missing/unavailable, otherwise None.
        """
        try:
            from aragora.agents import filter_available_agents
            from aragora.agents.spec import AgentSpec
        except ImportError:
            logger.debug("Agent preflight skipped: credential validator unavailable")
            return None

        try:
            specs = AgentSpec.coerce_list(agents_str, warn=False)
        except (ValueError, TypeError) as e:
            # ValueError: invalid agent spec format
            # TypeError: unexpected type in agent spec
            return f"Invalid agent specification: {e}"

        try:
            requested_count = len(specs)
            available_specs, filtered = filter_available_agents(
                specs,
                log_filtered=False,
                min_agents=requested_count,
            )
        except (ValueError, RuntimeError, OSError) as e:
            # ValueError: invalid agent configuration
            # RuntimeError: agent initialization failure
            # OSError: credential file/network access issues
            logger.warning("Agent credential validation failed: %s", e)
            # Check if ALL agents are missing credentials (no API keys configured at all)
            if (
                filtered_count := len(specs)
                if "0 agents have valid credentials" in str(e) or "none" in str(e).lower()
                else 0
            ):
                return (
                    f"No AI model API keys are configured on this server. "
                    f"None of the {filtered_count} requested agents have valid credentials. "
                    "Please configure at least one API key "
                    "(ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.) "
                    "or use playground mode for demo debates."
                )
            return (
                "Some AI model API keys are missing. "
                "Please check your API key configuration "
                "or use playground mode for demo debates."
            )

        if filtered:
            missing_detail = "; ".join(f"{agent}: {reason}" for agent, reason in filtered)
            available_names = ", ".join(s.provider for s in available_specs) or "none"
            return (
                "Missing credentials for requested agents. "
                f"Missing: {missing_detail}. Available: {available_names}. "
                "Configure API keys or use the playground mode for demo debates."
            )

        if requested_count < 2:
            return "At least 2 agents are required to start a debate."

        if len(available_specs) < requested_count:
            available_names = ", ".join(s.provider for s in available_specs) or "none"
            requested_names = ", ".join(s.provider for s in specs) or "none"
            return (
                f"Only {len(available_specs)}/{requested_count} requested agents are available. "
                f"Requested: {requested_names}. Available: {available_names}."
            )

        return None

    async def _quick_classify_async(self, question: str) -> dict:
        """Fast Haiku classification of question type and domain.

        This provides immediate context to users while the debate initializes.
        Uses Claude 3.5 Haiku for speed (~100-200ms typical latency).

        Args:
            question: The debate question to classify

        Returns:
            Dict with type, domain, complexity, aspects, and approach
        """
        import asyncio
        import json
        import os

        # Check for API key first
        if not os.getenv("ANTHROPIC_API_KEY"):
            logger.error("[quick_classify] ANTHROPIC_API_KEY not set - skipping classification")
            return _DEFAULT_CLASSIFICATION

        logger.info("[quick_classify] Starting Haiku classification")

        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic()
            # Wrap API call with 5 second timeout
            response = await asyncio.wait_for(
                client.messages.create(
                    model="claude-3-5-haiku-20241022",
                    max_tokens=300,
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                "Classify this debate question."
                                " Return ONLY valid JSON, no"
                                " other text.\n\n"
                                f"Question: {question[:500]}\n\n"
                                "Return JSON with these exact fields:\n"
                                "- type: one of [factual, ethical, technical,"
                                " creative, policy, comparative]\n"
                                "- domain: one of [science, technology,"
                                " philosophy, politics, society,"
                                " economics, other]\n"
                                "- complexity: one of [simple, moderate, complex]\n"
                                "- aspects: array of 3-4 key focus areas as short phrases\n"
                                "- approach: one sentence on how AI agents will analyze this"
                            ),
                        }
                    ],
                ),
                timeout=5.0,
            )
            # Parse JSON from response
            content_block = response.content[0]
            content = str(getattr(content_block, "text", "")).strip()
            # Handle potential markdown code blocks
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            result = json.loads(content)
            logger.info(
                "[quick_classify] Success: type=%s, domain=%s",
                result.get("type"),
                result.get("domain"),
            )
            return result
        except asyncio.TimeoutError:
            logger.error("[quick_classify] Haiku API timeout after 5s")
            return _DEFAULT_CLASSIFICATION
        except json.JSONDecodeError as e:
            logger.error("[quick_classify] JSON parse error: %s", e)
            return _DEFAULT_CLASSIFICATION
        except (ImportError, AttributeError, KeyError, RuntimeError, OSError) as e:
            # ImportError: anthropic SDK not installed
            # AttributeError: unexpected response structure
            # KeyError: missing response fields
            # RuntimeError: API client errors
            # OSError: network connectivity issues
            logger.error("[quick_classify] Failed: %s: %s", type(e).__name__, e)
            return _DEFAULT_CLASSIFICATION

    def _quick_classify(self, question: str, debate_id: str) -> None:
        """Run quick classification and emit event (sync wrapper).

        Also recommends relevant templates based on the question and
        classification domain, including them in the stream event.
        """
        try:
            classification = run_async(self._quick_classify_async(question))

            # Auto-recommend templates based on question + domain
            suggested_templates: list[dict[str, str]] = []
            try:
                from aragora.deliberation.templates.registry import _global_registry

                _global_registry._ensure_initialized()
                domain = classification.get("domain")
                recommended = _global_registry.recommend(question=question, domain=domain, limit=3)
                suggested_templates = [
                    {"name": t.name, "description": t.description} for t in recommended
                ]
            except (ImportError, RuntimeError, AttributeError) as e:
                logger.debug("Template recommendation failed (non-fatal): %s", e)

            self.emitter.emit(
                StreamEvent(
                    type=StreamEventType.QUICK_CLASSIFICATION,
                    data={
                        "question_type": classification.get("type", "general"),
                        "domain": classification.get("domain", "other"),
                        "complexity": classification.get("complexity", "moderate"),
                        "key_aspects": classification.get("aspects", []),
                        "suggested_approach": classification.get("approach", ""),
                        "suggested_templates": suggested_templates,
                    },
                    loop_id=debate_id,
                )
            )
        except (RuntimeError, OSError, KeyError, TypeError) as e:
            # RuntimeError: async execution issues
            # OSError: network/system errors
            # KeyError/TypeError: unexpected classification response format
            logger.warning("Failed to emit quick classification: %s", e)

    def start_debate(self, request: DebateRequest) -> DebateResponse:
        """Start a new debate asynchronously.

        Args:
            request: Validated debate request

        Returns:
            DebateResponse with debate_id on success
        """
        # Validate storage is available for persistence
        if not self.storage:
            logger.error("[debate] Cannot start debate: storage not configured")
            return DebateResponse(
                success=False,
                error="Server storage not configured. Debates cannot be persisted.",
                status_code=503,
            )

        # Generate debate ID
        debate_id = f"adhoc_{uuid.uuid4().hex[:8]}"

        # Resolve agents (auto-select if requested and no explicit agents provided)
        agents_str = request.agents_str
        if request.auto_select and self.auto_select_fn:
            should_autoselect = False
            if agents_str is None:
                should_autoselect = True
            elif isinstance(agents_str, str):
                should_autoselect = not agents_str.strip()
            else:
                try:
                    should_autoselect = len(agents_str) == 0
                except TypeError:
                    should_autoselect = False

            if should_autoselect:
                try:
                    agents_str = self.auto_select_fn(request.question, request.auto_select_config)
                except (ValueError, TypeError, RuntimeError, OSError) as e:
                    # ValueError/TypeError: invalid auto-select config or response
                    # RuntimeError: auto-select execution failure
                    # OSError: network/system errors during selection
                    logger.warning("Auto-select failed, using defaults: %s", e)

        preflight_error = self._preflight_agents(agents_str)
        if preflight_error:
            logger.warning("[debate] Agent preflight failed: %s", preflight_error)
            # Suggest playground fallback for credential-related errors
            is_credential_error = any(
                phrase in preflight_error.lower()
                for phrase in ("credentials", "api key", "playground")
            )
            return DebateResponse(
                success=False,
                error=preflight_error,
                status_code=400,
                use_playground=is_credential_error,
            )

        mode_meta = request.mode or (
            request.metadata.get("mode") if isinstance(request.metadata, dict) else None
        )
        settlement_meta = (
            request.metadata.get("settlement") if isinstance(request.metadata, dict) else None
        )
        settlement_snapshot = (
            _normalize_settlement_metadata(
                settlement_meta,
                claim_fallback=request.question,
            )
            if (mode_meta == _EPISTEMIC_HYGIENE_MODE or isinstance(settlement_meta, dict))
            else None
        )

        # Track debate state (use "task" not "question" for StateManager compatibility)
        with _active_debates_lock:
            _active_debates[debate_id] = {
                "id": debate_id,
                "task": request.question,
                "status": "starting",
                "agents": agents_str,
                "rounds": request.rounds,
                "total_rounds": request.rounds,
                "documents": list(request.documents or []),
                "mode": mode_meta,
                "settlement": settlement_snapshot,
            }

        # Periodic cleanup
        cleanup_stale_debates()

        # Set loop_id on emitter
        self.emitter.set_loop_id(debate_id)

        # Parse agent names for immediate event (handle string, list of dicts, or specs)
        agent_names = _normalize_agent_names(agents_str)

        # Emit immediate DEBATE_START event so clients see progress within seconds
        # (The debate phases will emit more detailed events as they execute)
        self.emitter.emit(
            StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={
                    "task": request.question,
                    "agents": agent_names,
                    "mode": mode_meta,
                    "settlement": settlement_snapshot,
                },
                loop_id=debate_id,
            )
        )

        # Quick classification with Haiku (~100-200ms) - shows immediately in UI
        # This runs while the rest of initialization continues
        self._quick_classify(request.question, debate_id)

        # Emit PHASE_PROGRESS to show research is starting
        # This gives users immediate feedback that something is happening
        self.emitter.emit(
            StreamEvent(
                type=StreamEventType.PHASE_PROGRESS,
                data={
                    "phase": "research",
                    "status": "starting",
                    "message": "Gathering context and researching topic...",
                },
                loop_id=debate_id,
            )
        )

        # Fetch trending topic if requested
        trending_topic = None
        if request.use_trending:
            trending_topic = self._fetch_trending_topic(request.trending_category)

        # Create config for factory
        config = DebateConfig(
            question=request.question,
            context=request.context,
            mode=request.mode,
            agents_str=agents_str,
            rounds=request.rounds,
            consensus=request.consensus,
            debate_format=request.debate_format,
            debate_id=debate_id,
            trending_topic=trending_topic,
            metadata=request.metadata,
            documents=list(request.documents or []),
            enable_verticals=request.enable_verticals,
            vertical_id=request.vertical_id,
            budget_limit_usd=request.budget_limit_usd,
            enable_cartographer=request.enable_cartographer,
            enable_introspection=request.enable_introspection,
            enable_auto_execution=request.enable_auto_execution,
            enable_settlement_tracking=request.enable_settlement_tracking,
            enable_interventions=request.enable_interventions,
            quality_pipeline=request.quality_pipeline,
        )

        # Submit to thread pool
        try:
            executor = self._get_executor()
            executor.submit(self._run_debate, config, debate_id)
        except RuntimeError as e:
            logger.warning("Cannot submit debate: %s", e)
            return DebateResponse(
                success=False,
                error="Server at capacity. Please try again later.",
                status_code=503,
            )

        return DebateResponse(
            success=True,
            debate_id=debate_id,
            status="created",
            task=request.question,
            status_code=200,
        )

    def _get_executor(self) -> ThreadPoolExecutor:
        """Get the shared thread pool executor from StateManager."""
        return get_state_manager().get_executor(max_workers=MAX_CONCURRENT_DEBATES)

    def _run_debate(self, config: DebateConfig, debate_id: str) -> None:
        """Execute debate in background thread.

        Args:
            config: Debate configuration
            debate_id: Unique debate identifier
        """
        import time

        start_time = time.time()
        try:
            # Update status to initializing immediately to prevent stuck "starting" state
            update_debate_status(debate_id, "initializing")

            # Create event hooks for streaming with explicit loop_id
            # (prevents race condition when multiple debates run concurrently)
            hooks = create_arena_hooks(self.emitter, loop_id=debate_id)

            # Create arena using factory with streaming wrapper
            arena = self.factory.create_arena(
                config,
                event_hooks=hooks,
                stream_wrapper=wrap_agent_for_streaming,
            )

            # Reset circuit breakers for fresh start
            self.factory.reset_circuit_breakers(arena)

            # Run debate with timeout
            # Use protocol timeout if configured, otherwise use global default
            protocol_timeout = getattr(arena.protocol, "timeout_seconds", 0)
            timeout = (
                protocol_timeout
                if isinstance(protocol_timeout, (int, float)) and protocol_timeout > 0
                else DEBATE_TIMEOUT_SECONDS
            )
            update_debate_status(debate_id, "running")

            async def run_with_timeout():
                return await asyncio.wait_for(arena.run(), timeout=timeout)

            result = run_async(run_with_timeout())

            # Post-consensus quality pipeline (deterministic, opt-in)
            quality_meta: dict[str, Any] | None = None
            if isinstance(config.quality_pipeline, dict) and config.quality_pipeline.get(
                "enabled", True
            ):
                try:
                    from aragora.debate.quality_pipeline import (
                        QualityPipelineConfig,
                        apply_post_consensus_quality,
                    )

                    qp_config = QualityPipelineConfig.from_dict(config.quality_pipeline)
                    qp_result = apply_post_consensus_quality(
                        answer=result.final_answer or "",
                        task=config.question,
                        config=qp_config,
                    )
                    result.final_answer = qp_result.answer
                    quality_meta = qp_result.to_dict()
                    logger.info(
                        "[debate] Quality pipeline for %s: passes_gate=%s repaired=%s",
                        debate_id,
                        qp_result.passes_gate,
                        qp_result.repaired,
                    )
                except (ImportError, ValueError, TypeError, OSError) as qp_err:
                    logger.warning(
                        "[debate] Quality pipeline failed for %s (non-fatal): %s",
                        debate_id,
                        qp_err,
                    )

            # Extract explanation summary if available
            explanation_text = ""
            explanation_obj = getattr(result, "explanation", None)
            if explanation_obj:
                if isinstance(explanation_obj, str):
                    explanation_text = explanation_obj
                elif hasattr(explanation_obj, "summary"):
                    explanation_text = str(getattr(explanation_obj, "summary", ""))
                elif hasattr(explanation_obj, "text"):
                    explanation_text = str(getattr(explanation_obj, "text", ""))
                else:
                    explanation_text = str(explanation_obj)

            # Collect calibration snapshots for participating agents
            agent_calibration = self._collect_agent_calibration(result.participants or [])
            settlement_meta = (
                config.metadata.get("settlement") if isinstance(config.metadata, dict) else None
            )
            mode_meta = config.mode or (
                config.metadata.get("mode") if isinstance(config.metadata, dict) else None
            )
            settlement_snapshot = (
                _normalize_settlement_metadata(
                    settlement_meta,
                    claim_fallback=config.question,
                )
                if (mode_meta == _EPISTEMIC_HYGIENE_MODE or isinstance(settlement_meta, dict))
                else None
            )

            # Update status with result
            update_debate_status(
                debate_id,
                "completed",
                result={
                    "final_answer": result.final_answer,
                    "consensus_reached": result.consensus_reached,
                    "confidence": result.confidence,
                    "status": result.status,
                    "agent_failures": result.agent_failures,
                    "participants": result.participants,
                    "grounded_verdict": (
                        result.grounded_verdict.to_dict() if result.grounded_verdict else None
                    ),
                    "total_cost_usd": getattr(result, "total_cost_usd", None) or 0.0,
                    "per_agent_cost": getattr(result, "per_agent_cost", None) or {},
                    "explanation_summary": explanation_text[:500] if explanation_text else "",
                    "has_plan": getattr(result, "plan", None) is not None,
                    "agent_calibration": agent_calibration,
                    "mode": mode_meta,
                    "settlement": settlement_snapshot,
                    "quality_pipeline": quality_meta,
                },
            )

            # Persist debate to SQLite storage
            try:
                if self.storage:
                    # Parse agents string to list
                    agents_list = (
                        config.agents_str.split(",")
                        if isinstance(config.agents_str, str)
                        else config.agents_str
                    )
                    # Serialize messages from result
                    messages_data = []
                    if hasattr(result, "messages") and result.messages:
                        for msg in result.messages:
                            messages_data.append(
                                {
                                    "role": msg.role,
                                    "agent": msg.agent,
                                    "content": msg.content,
                                    "round": msg.round,
                                    "timestamp": (
                                        msg.timestamp.isoformat()
                                        if hasattr(msg.timestamp, "isoformat")
                                        else str(msg.timestamp)
                                    ),
                                }
                            )

                    debate_data = {
                        "id": debate_id,
                        "task": config.question,
                        "agents": agents_list,
                        "rounds": config.rounds,
                        "final_answer": result.final_answer,
                        "consensus_reached": result.consensus_reached,
                        "confidence": result.confidence,
                        "grounded_verdict": (
                            result.grounded_verdict.to_dict() if result.grounded_verdict else None
                        ),
                        "messages": messages_data,
                    }
                    self.storage.save_dict(debate_data)
                    logger.info("[debate] Persisted debate %s to storage", debate_id)
            except (OSError, ValueError, TypeError, AttributeError) as e:
                # OSError: database/file access errors
                # ValueError: serialization errors
                # TypeError: unexpected data types during serialization
                # AttributeError: missing attributes on result object
                logger.error("[debate] Failed to persist debate %s: %s", debate_id, e)

            # Emit leaderboard update
            self._emit_leaderboard_update(debate_id)

            # Auto-generate receipt for ALL completed debates
            self._generate_debate_receipt(
                debate_id=debate_id,
                config=config,
                result=result,
                duration_seconds=time.time() - start_time,
            )

        except ValueError as e:
            # Validation errors (not enough agents, etc.)
            logger.warning("[debate] Validation error in %s: %s", debate_id, e)
            safe_msg = "Debate validation failed. Check agent configuration and parameters."
            update_debate_status(debate_id, "error", error=safe_msg)
            self.emitter.emit(
                StreamEvent(
                    type=StreamEventType.ERROR,
                    data={"error": safe_msg, "debate_id": debate_id},
                )
            )
            # Emit DEBATE_END so frontend knows debate is finished
            self.emitter.emit(
                StreamEvent(
                    type=StreamEventType.DEBATE_END,
                    data={
                        "debate_id": debate_id,
                        "duration": time.time() - start_time,
                        "rounds": 0,
                        "error": safe_msg,
                    },
                    loop_id=debate_id,
                )
            )

        except Exception as e:  # noqa: BLE001 - Intentional catch-all: debate execution must handle any error to emit proper error events and cleanup
            import traceback

            safe_msg = safe_error_message(e, "debate_execution")
            error_trace = traceback.format_exc()
            update_debate_status(debate_id, "error", error=safe_msg)
            logger.error("[debate] Thread error in %s: %s\n%s", debate_id, e, error_trace)
            self.emitter.emit(
                StreamEvent(
                    type=StreamEventType.ERROR,
                    data={"error": safe_msg, "debate_id": debate_id},
                )
            )
            # Emit DEBATE_END so frontend knows debate is finished
            self.emitter.emit(
                StreamEvent(
                    type=StreamEventType.DEBATE_END,
                    data={
                        "debate_id": debate_id,
                        "duration": time.time() - start_time,
                        "rounds": 0,
                        "error": safe_msg,
                    },
                    loop_id=debate_id,
                )
            )

    def _collect_agent_calibration(self, participants: list[str]) -> dict[str, dict[str, Any]]:
        """Collect calibration snapshots for participating agents.

        Args:
            participants: List of agent names

        Returns:
            Dict mapping agent name to calibration data
        """
        if not participants:
            return {}
        try:
            from aragora.agents.calibration import CalibrationTracker
            from aragora.server.handlers.base import _compute_trust_tier

            tracker = CalibrationTracker()
            calibration_map: dict[str, dict[str, Any]] = {}
            for agent_name in participants:
                try:
                    summary = tracker.get_calibration_summary(str(agent_name))
                    if summary.total_predictions > 0:
                        calibration_map[str(agent_name)] = {
                            "brier_score": round(summary.brier_score, 4),
                            "ece": round(summary.ece, 4),
                            "trust_tier": _compute_trust_tier(
                                summary.brier_score, summary.total_predictions
                            ),
                            "prediction_count": summary.total_predictions,
                        }
                except (AttributeError, TypeError, ValueError, OSError):
                    continue
            try:
                if calibration_map:
                    from aragora.debate.epistemic_outcomes import get_epistemic_outcome_store
                    from aragora.debate.reliability_scheduler import ReliabilityScheduler

                    scheduler = ReliabilityScheduler()
                    settled_outcomes = get_epistemic_outcome_store().list_outcomes(
                        status="resolved",
                        limit=500,
                    )
                    settlement_deltas = scheduler.build_settlement_deltas(settled_outcomes)
                    budget_shares = scheduler.allocate_budget(
                        participants,
                        calibration_map,
                        settlement_deltas,
                    )
                    for agent_name, share in budget_shares.items():
                        if agent_name in calibration_map:
                            calibration_map[agent_name]["budget_share"] = round(float(share), 4)
            except (ImportError, TypeError, ValueError, OSError) as e:
                logger.debug("Reliability budget share computation skipped: %s", e)
            return calibration_map
        except ImportError:
            return {}

    def _fetch_trending_topic(self, category: str | None) -> Any | None:
        """Fetch a trending topic for the debate.

        Args:
            category: Optional category filter

        Returns:
            TrendingTopic or None
        """
        try:
            from aragora.pulse.ingestor import (
                HackerNewsIngestor,
                PulseManager,
                RedditIngestor,
                TwitterIngestor,
            )

            async def _fetch():
                manager = PulseManager()
                manager.add_ingestor("twitter", TwitterIngestor())
                manager.add_ingestor("hackernews", HackerNewsIngestor())
                manager.add_ingestor("reddit", RedditIngestor())

                filters = {}
                if category:
                    filters["categories"] = [category]

                topics = await manager.get_trending_topics(
                    limit_per_platform=3, filters=filters if filters else None
                )
                return manager.select_topic_for_debate(topics)

            loop = asyncio.new_event_loop()
            try:
                topic = loop.run_until_complete(_fetch())
                if topic:
                    logger.info("Selected trending topic: %s", topic.topic)
                return topic
            finally:
                loop.close()

        except (ImportError, RuntimeError, OSError, asyncio.TimeoutError) as e:
            # ImportError: pulse module not available
            # RuntimeError: async execution errors
            # OSError: network connectivity issues
            # TimeoutError: API request timeout
            logger.warning("Trending topic fetch failed (non-fatal): %s", e)
            return None

    def _emit_leaderboard_update(self, debate_id: str) -> None:
        """Emit leaderboard update event after debate completion."""
        if not self.elo_system:
            return

        try:
            top_agents = self.elo_system.get_leaderboard(limit=10)
            self.emitter.emit(
                StreamEvent(
                    type=StreamEventType.LEADERBOARD_UPDATE,
                    data={
                        "debate_id": debate_id,
                        "leaderboard": [
                            {
                                "agent": a.agent_name,
                                "elo": a.elo_rating,
                                "wins": a.wins,
                                "debates": a.total_debates,
                            }
                            for a in top_agents
                        ],
                    },
                )
            )
        except (AttributeError, KeyError, TypeError, RuntimeError, ValueError, OSError) as e:
            # AttributeError: missing method on elo_system
            # KeyError: missing fields in agent data
            # TypeError: unexpected data format
            # RuntimeError: emission failure
            # ValueError/OSError: data conversion or system errors
            logger.debug("Leaderboard emission failed: %s", e)

    def _generate_debate_receipt(
        self,
        debate_id: str,
        config: DebateConfig,
        result: Any,
        duration_seconds: float,
    ) -> None:
        """Generate and save a receipt for a completed debate.

        Args:
            debate_id: Unique debate identifier
            config: Debate configuration
            result: Debate result with final_answer, consensus, etc.
            duration_seconds: Total debate duration
        """
        import hashlib
        import uuid
        from datetime import datetime, timezone

        try:
            from aragora.storage.receipt_store import get_receipt_store

            receipt_store = get_receipt_store()

            # Parse agents
            agents_list = (
                config.agents_str.split(",")
                if isinstance(config.agents_str, str)
                else config.agents_str
            )

            # Build receipt dict
            receipt_id = str(uuid.uuid4())
            timestamp = datetime.now(timezone.utc).isoformat()

            # Determine verdict based on consensus
            if result.consensus_reached and result.confidence >= 0.7:
                verdict = "APPROVED"
                risk_level = "LOW"
            elif result.consensus_reached:
                verdict = "APPROVED_WITH_CONDITIONS"
                risk_level = "MEDIUM"
            else:
                verdict = "NEEDS_REVIEW"
                risk_level = "MEDIUM"

            # Calculate input hash
            input_content = f"{config.question}|{config.agents_str}|{config.rounds}"
            input_hash = hashlib.sha256(input_content.encode()).hexdigest()

            mode_meta = config.mode or (
                config.metadata.get("mode") if isinstance(config.metadata, dict) else None
            )
            settlement_meta = (
                config.metadata.get("settlement") if isinstance(config.metadata, dict) else None
            )
            settlement_snapshot = (
                _normalize_settlement_metadata(
                    settlement_meta,
                    claim_fallback=config.question,
                )
                if (mode_meta == _EPISTEMIC_HYGIENE_MODE or isinstance(settlement_meta, dict))
                else None
            )
            is_onboarding = bool(config.metadata and config.metadata.get("is_onboarding"))

            receipt_dict = {
                "receipt_id": receipt_id,
                "gauntlet_id": f"debate-{debate_id}",
                "debate_id": debate_id,
                "timestamp": timestamp,
                "input_summary": config.question[:200],
                "input_hash": input_hash,
                "verdict": verdict,
                "confidence": result.confidence if hasattr(result, "confidence") else 0.5,
                "risk_level": risk_level,
                "risk_score": 1.0 - (result.confidence if hasattr(result, "confidence") else 0.5),
                "robustness_score": result.confidence if hasattr(result, "confidence") else 0.5,
                "agents_involved": agents_list,
                "rounds_completed": config.rounds,
                "duration_seconds": duration_seconds,
                "final_answer": result.final_answer if hasattr(result, "final_answer") else "",
                "consensus_reached": (
                    result.consensus_reached if hasattr(result, "consensus_reached") else False
                ),
                "is_onboarding": is_onboarding,
                "agent_calibration": self._collect_agent_calibration(agents_list),
            }
            if mode_meta:
                receipt_dict["mode"] = mode_meta
            if settlement_snapshot:
                receipt_dict["settlement"] = settlement_snapshot

            # Calculate checksum
            checksum_content = f"{receipt_id}|{debate_id}|{input_hash}|{verdict}"
            receipt_dict["checksum"] = hashlib.sha256(checksum_content.encode()).hexdigest()

            # Save receipt
            receipt_store.save(receipt_dict)
            logger.info("[debate] Generated receipt %s for debate %s", receipt_id, debate_id)
            self._record_epistemic_outcome(
                debate_id=debate_id,
                claim_settlement=settlement_snapshot,
                confidence=float(receipt_dict.get("confidence", 0.5)),  # type: ignore[arg-type]
                mode=mode_meta,
                receipt_id=receipt_id,
                participants=agents_list,
            )

            # Add receipt_id to the debate status
            update_debate_status(debate_id, "completed", result={"receipt_id": receipt_id})

            # Emit RECEIPT_GENERATED stream event
            self.emitter.emit(
                StreamEvent(
                    type=StreamEventType.RECEIPT_GENERATED,
                    data={
                        "debate_id": debate_id,
                        "receipt_id": receipt_id,
                        "verdict": verdict,
                        "confidence": receipt_dict["confidence"],
                    },
                    loop_id=debate_id,
                )
            )

            # Update onboarding flow with receipt ID if this is an onboarding debate
            if is_onboarding:
                user_id = config.metadata.get("user_id") if config.metadata else None
                org_id = config.metadata.get("organization_id") if config.metadata else None
                flow_id = config.metadata.get("flow_id") if config.metadata else None
                if user_id:
                    try:
                        from aragora.storage.repositories.onboarding import (
                            get_onboarding_repository,
                        )

                        repo = get_onboarding_repository()
                        flow = repo.get_flow(user_id, org_id)
                        if flow:
                            flow_id = flow.get("id") or flow_id
                            repo.update_flow(
                                flow["id"],
                                {
                                    "metadata": {
                                        **flow.get("metadata", {}),
                                        "receipt_id": receipt_id,
                                    }
                                },
                            )
                        try:
                            from aragora.server.handlers.onboarding import _track_event

                            _track_event(
                                "first_receipt_generated",
                                str(user_id),
                                str(org_id) if org_id is not None else None,
                                {
                                    "flow_id": flow_id,
                                    "debate_id": debate_id,
                                    "receipt_id": receipt_id,
                                },
                            )
                        except (ImportError, AttributeError, TypeError, ValueError) as e:
                            logger.debug("Could not track onboarding receipt event: %s", e)
                    except (ImportError, KeyError, TypeError, OSError) as e:
                        # ImportError: onboarding repository not available
                        # KeyError: missing flow data
                        # TypeError: unexpected flow structure
                        # OSError: database access errors
                        logger.debug("Could not update onboarding flow with receipt: %s", e)

        except (ImportError, ValueError, TypeError, OSError, KeyError) as e:
            # ImportError: receipt store module not available
            # ValueError: invalid receipt data
            # TypeError: unexpected data types
            # OSError: storage access errors
            # KeyError: missing required fields
            logger.warning("[debate] Failed to generate receipt for %s: %s", debate_id, e)

    def _record_epistemic_outcome(
        self,
        *,
        debate_id: str,
        claim_settlement: dict[str, Any] | None,
        confidence: float,
        mode: str | None,
        receipt_id: str,
        participants: list[str],
    ) -> None:
        """Record a debate claim in the epistemic outcome ledger.

        This is best-effort and never blocks receipt generation.
        """
        if not isinstance(claim_settlement, dict):
            return
        resolution_tier, initial_status, auto_settle_eligible = self._select_resolution_tier(
            claim_settlement
        )
        try:
            from aragora.debate.epistemic_outcomes import (
                EpistemicOutcome,
                get_epistemic_outcome_store,
            )

            store = get_epistemic_outcome_store()
            store.record_outcome(
                EpistemicOutcome(
                    debate_id=debate_id,
                    claim=str(claim_settlement.get("claim") or "").strip()
                    or _DEFAULT_SETTLEMENT_CLAIM,
                    falsifier=str(claim_settlement.get("falsifier") or "").strip()
                    or _DEFAULT_SETTLEMENT_FALSIFIER,
                    metric=str(claim_settlement.get("metric") or "").strip()
                    or _DEFAULT_SETTLEMENT_METRIC,
                    review_horizon_days=max(
                        1,
                        int(claim_settlement.get("review_horizon_days", 30)),
                    ),
                    status=initial_status,
                    resolver_type=resolution_tier,
                    initial_confidence=float(confidence),
                    metadata={
                        "mode": mode or "",
                        "receipt_id": receipt_id,
                        "participants": participants,
                        "resolution_tier": resolution_tier,
                        "auto_settle_eligible": auto_settle_eligible,
                    },
                )
            )
        except (ImportError, TypeError, ValueError, OSError) as e:
            logger.debug("Epistemic outcome ledger skipped for %s: %s", debate_id, e)

    @staticmethod
    def _select_resolution_tier(claim_settlement: dict[str, Any]) -> tuple[str, str, bool]:
        """Map settlement metadata to deterministic/oracle/human resolution tiers."""
        tier_hint = _normalize_resolver_type(
            claim_settlement.get("resolver_type")
            or claim_settlement.get("resolution_tier")
            or claim_settlement.get("verification_mode")
        )

        if tier_hint == "deterministic":
            return ("deterministic", "pending_deterministic", True)
        if tier_hint == "oracle":
            return ("oracle", "pending_oracle", True)
        return ("human", "open", False)

    @classmethod
    def shutdown(cls) -> None:
        """Shutdown the thread pool executor via StateManager."""
        get_state_manager().shutdown_executor()

    def start_playground_debate(
        self,
        question: str,
        agent_count: int = 3,
        max_rounds: int = 2,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """Run a simplified synchronous debate for the playground.

        Skips storage/auth. Runs in a separate ThreadPoolExecutor.
        Sets ``public_spectate: true`` in metadata for spectator URLs.

        Args:
            question: The debate question
            agent_count: Number of agents (2-5)
            max_rounds: Maximum debate rounds (1-2)
            timeout: Timeout in seconds (default 60)

        Returns:
            Dict with debate result fields (final_answer, consensus, etc.)
        """
        import time as _time

        debate_id = f"playground_{uuid.uuid4().hex[:8]}"
        start_time = _time.time()

        config = DebateConfig(
            question=question,
            agents_str=DEFAULT_AGENTS,
            rounds=max_rounds,
            debate_format="light",
            debate_id=debate_id,
            metadata={"public_spectate": True, "is_playground": True},
        )

        arena = self.factory.create_arena(config)

        async def _run_arena():
            return await asyncio.wait_for(arena.run(), timeout=timeout)

        result = run_async(_run_arena())
        duration = _time.time() - start_time

        return {
            "debate_id": debate_id,
            "status": result.status,
            "rounds_used": getattr(result, "rounds_used", max_rounds),
            "consensus_reached": result.consensus_reached,
            "confidence": result.confidence,
            "final_answer": result.final_answer,
            "participants": result.participants,
            "duration_seconds": round(duration, 3),
        }
