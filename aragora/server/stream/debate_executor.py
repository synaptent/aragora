"""
Debate execution logic for the streaming server.

This module handles the background execution of ad-hoc debates started via the
HTTP API. It runs debates in a ThreadPoolExecutor to avoid blocking the event loop.

Key components:
- _parse_debate_request: Validate and parse debate request JSON
- _fetch_trending_topic_async: Fetch trending topics for debate seeding
- _execute_debate_thread: Run a debate in a background thread
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from typing import Literal

    from aragora.agents.base import AgentType
    from aragora.core import Agent
    from aragora.debate.orchestrator import Arena as ArenaClass
    from aragora.debate.protocol import DebateProtocol as DebateProtocolClass
    from aragora.core import Environment as EnvironmentClass
    from aragora.server.stream.emitter import SyncEventEmitter
    from aragora.types.protocols import EventEmitterProtocol

    # Consensus type from DebateProtocol
    ConsensusType = Literal[
        "majority", "unanimous", "judge", "none", "weighted", "supermajority", "any", "byzantine"
    ]

from aragora.config import (
    DEBATE_TIMEOUT_SECONDS,
    DEFAULT_AGENTS,
    DEFAULT_CONSENSUS,
    DEFAULT_ROUNDS,
    MAX_AGENTS_PER_DEBATE,
    MAX_ROUNDS,
)
from aragora.server.errors import safe_error_message as _safe_error_message
from aragora.server.stream.arena_hooks import (
    create_arena_hooks,
    wrap_agent_for_streaming,
)
from aragora.agents.personas import apply_persona_to_agent
from aragora.agents.registry import AgentRegistry
from aragora.agents.spec import AgentSpec
from aragora.billing.usage import UsageTracker
from aragora.config import get_api_key
from aragora.config.secrets import get_secret
from aragora.pulse.ingestor import (
    HackerNewsIngestor,
    PulseManager,
    RedditIngestor,
    TwitterIngestor,
)
from aragora.server.stream.events import StreamEvent, StreamEventType
from aragora.server.stream.state_manager import (
    get_active_debates,
    get_active_debates_lock,
)

logger = logging.getLogger(__name__)

# Backward compatibility aliases
_active_debates = get_active_debates()
_active_debates_lock = get_active_debates_lock()

_ENV_VAR_RE = re.compile(r"[A-Z][A-Z0-9_]+")
_OPENROUTER_FALLBACK_MODELS = {
    "anthropic-api": "anthropic/claude-sonnet-4.6",
    "openai-api": "openai/gpt-5.3",
    "gemini": "google/gemini-3-flash-preview",
    "grok": "x-ai/grok-4.1-fast",
    "mistral-api": "mistralai/mistral-large-2512",
}
_OPENROUTER_GENERIC_FALLBACK_MODEL = "openai/gpt-5.3-chat"


def _missing_required_env_vars(env_vars: str) -> list[str]:
    """Return missing required env vars for a provider spec."""
    if not env_vars:
        return []
    if "optional" in env_vars.lower():
        return []
    candidates = _ENV_VAR_RE.findall(env_vars)
    if not candidates:
        return []
    try:
        if get_api_key(*candidates, required=False):
            return []
    except (ImportError, AttributeError, TypeError):
        if any(os.getenv(var) for var in candidates):
            return []
    return candidates


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


def _openrouter_key_available() -> bool:
    """Return True if OpenRouter key is configured via secrets or env."""
    try:
        value = get_secret("OPENROUTER_API_KEY")
        if value and value.strip():
            return True
    except (ImportError, AttributeError, KeyError, OSError) as e:
        logger.debug("Secrets module unavailable, falling back to env: %s", e)
    env_value = os.getenv("OPENROUTER_API_KEY")
    return bool(env_value and env_value.strip())


# Check if debate orchestrator is available
# Type aliases for optional debate components
_ArenaType = type["ArenaClass"] | None
_DebateProtocolType = type["DebateProtocolClass"] | None
_EnvironmentType = type["EnvironmentClass"] | None
_CreateAgentType = Any | None  # Callable type is complex, use Any

try:
    from aragora.agents.base import create_agent as _create_agent
    from aragora.core import Environment as _Environment
    from aragora.debate.orchestrator import Arena as _Arena, DebateProtocol as _DebateProtocol

    DEBATE_AVAILABLE = True
    Arena: _ArenaType = _Arena
    DebateProtocol: _DebateProtocolType = _DebateProtocol
    create_agent: _CreateAgentType = _create_agent
    Environment: _EnvironmentType = _Environment
except ImportError:
    DEBATE_AVAILABLE = False
    Arena = None
    DebateProtocol = None
    create_agent = None
    Environment = None


def parse_debate_request(data: dict) -> tuple[dict | None, str | None]:
    """Parse and validate debate request data.

    Args:
        data: JSON request body from the HTTP API

    Returns:
        Tuple of (parsed_config, error_message). If error_message is set,
        parsed_config will be None.
    """
    # Validate required fields with length limits
    question = str(data.get("question") or data.get("task") or "").strip()
    if not question:
        return None, "question field is required"
    if len(question) > 10000:
        return None, "question must be under 10,000 characters"

    # Parse optional fields with validation
    agents_value = data.get("agents", DEFAULT_AGENTS)
    # Validate agent providers early to avoid starting invalid debates
    try:
        specs = AgentSpec.coerce_list(agents_value, warn=False)
        if not specs:
            specs = AgentSpec.coerce_list(DEFAULT_AGENTS, warn=False)
    except (ValueError, TypeError, ImportError) as e:
        logger.warning("Agent spec parsing failed: %s", e)
        return None, "Invalid agent configuration"

    agent_count = len(specs)
    agents_str = ",".join(spec.to_string() for spec in specs)
    if agent_count < 2:
        return None, "At least 2 agents required for a debate"
    if agent_count > MAX_AGENTS_PER_DEBATE:
        return None, f"Too many agents. Maximum: {MAX_AGENTS_PER_DEBATE}"
    try:
        rounds = min(max(int(data.get("rounds", DEFAULT_ROUNDS)), 1), MAX_ROUNDS)
    except (ValueError, TypeError):
        rounds = DEFAULT_ROUNDS
    consensus = data.get("consensus", DEFAULT_CONSENSUS)
    context = data.get("context", "")
    documents = _normalize_documents(data.get("documents") or data.get("document_ids") or [])

    return {
        "question": question,
        "context": context,
        "agents_str": agents_str,
        "rounds": rounds,
        "consensus": consensus,
        "use_trending": data.get("use_trending", False),
        "trending_category": data.get("trending_category", None),
        "documents": documents,
        "enable_knowledge_retrieval": data.get("enable_knowledge_retrieval"),
        "enable_knowledge_ingestion": data.get("enable_knowledge_ingestion"),
        "enable_cross_debate_memory": data.get("enable_cross_debate_memory"),
        "enable_supermemory": data.get("enable_supermemory"),
        "supermemory_context_container_tag": data.get("supermemory_context_container_tag"),
        "supermemory_max_context_items": data.get("supermemory_max_context_items"),
        "enable_belief_guidance": data.get("enable_belief_guidance"),
    }, None


async def fetch_trending_topic_async(category: str | None = None) -> Any | None:
    """Fetch a trending topic for the debate.

    Args:
        category: Optional category to filter trending topics

    Returns:
        A TrendingTopic object or None if unavailable.
    """
    try:
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
        topic = manager.select_topic_for_debate(topics)

        if topic:
            logger.info("Selected trending topic: %s", topic.topic)
        return topic
    except (ImportError, AttributeError, OSError, RuntimeError, ValueError) as e:
        logger.warning("Trending topic fetch failed (non-fatal): %s", e)
        return None


def _set_debate_error(
    debate_id: str,
    error_msg: str,
    emitter: SyncEventEmitter | None = None,
) -> None:
    """Record an error state for a debate and optionally emit an error event."""
    with _active_debates_lock:
        _active_debates[debate_id]["status"] = "error"
        _active_debates[debate_id]["error"] = error_msg
        _active_debates[debate_id]["completed_at"] = time.time()
    if emitter is not None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.ERROR,
                data={"error": error_msg, "debate_id": debate_id},
                loop_id=debate_id,
            )
        )


def _filter_agent_specs_with_fallback(
    agent_specs: list[Any],
    emitter: SyncEventEmitter,
    debate_id: str,
) -> tuple[list[Any], list[str], list[str]]:
    """Filter agent specs, applying OpenRouter fallback for missing API keys.

    Returns:
        Tuple of (filtered_specs, actual_agent_names, missing_agent_names).
    """
    requested_agents = [spec.name or spec.provider for spec in agent_specs]
    filtered_specs = []
    missing_agents: list[str] = []
    openrouter_available = _openrouter_key_available()

    for spec in agent_specs:
        registry_spec = AgentRegistry.get_spec(spec.provider)
        missing_env = []
        if registry_spec and registry_spec.env_vars:
            missing_env = _missing_required_env_vars(registry_spec.env_vars)
        if missing_env:
            fallback_model = _OPENROUTER_FALLBACK_MODELS.get(
                spec.provider, _OPENROUTER_GENERIC_FALLBACK_MODEL
            )
            if openrouter_available and fallback_model:
                fallback_spec = AgentSpec(
                    provider="openrouter",
                    model=fallback_model,
                    persona=spec.persona,
                    role=spec.role,
                    name=spec.name or spec.provider,
                )
                emitter.emit(
                    StreamEvent(
                        type=StreamEventType.AGENT_ERROR,
                        data={
                            "error_type": "missing_env_fallback",
                            "message": (
                                f"Missing {spec.provider} key(s); using OpenRouter model "
                                f"{fallback_model}"
                            ),
                            "recoverable": True,
                            "phase": "setup",
                        },
                        agent=spec.name or spec.provider,
                        loop_id=debate_id,
                    )
                )
                logger.warning(
                    f"[debate] {debate_id}: {spec.provider} missing key(s), "
                    f"fallback to openrouter:{fallback_model}"
                )
                filtered_specs.append(fallback_spec)
                continue
            message = f"Missing required API key(s) for {spec.provider}: {', '.join(missing_env)}"
            emitter.emit(
                StreamEvent(
                    type=StreamEventType.AGENT_ERROR,
                    data={
                        "error_type": "missing_env",
                        "message": message,
                        "recoverable": False,
                        "phase": "setup",
                    },
                    agent=spec.name or spec.provider,
                    loop_id=debate_id,
                )
            )
            logger.warning("[debate] %s: %s", debate_id, message)
            missing_agents.append(spec.name or spec.provider)
            continue
        filtered_specs.append(spec)

    actual_agents = [spec.name or spec.provider for spec in filtered_specs]
    try:
        from aragora.server.state import get_state_manager

        get_state_manager().update_debate_agents(debate_id, actual_agents)
    except (ImportError, AttributeError, KeyError, RuntimeError) as e:
        logger.debug(
            "[debate] %s: unable to update active agent list: %s",
            debate_id,
            e,
        )

    return filtered_specs, requested_agents, missing_agents


def _create_debate_agents(
    agent_specs: list[Any],
    emitter: SyncEventEmitter,
    debate_id: str,
) -> list[Agent]:
    """Create and wrap agents from filtered specs, assigning roles by position."""
    agents: list[Agent] = []
    for i, spec in enumerate(agent_specs):
        role = spec.role
        if role is None:
            if i == 0:
                role = "proposer"
            elif i == len(agent_specs) - 1 and len(agent_specs) > 1:
                role = "synthesizer"
            else:
                role = "critic"
        try:
            agent = create_agent(
                model_type=cast("AgentType", spec.provider),
                name=spec.name,
                role=role,
                model=spec.model,
            )
        except (ValueError, TypeError, RuntimeError, ImportError, OSError) as e:
            msg = _safe_error_message(e, "agent_init")
            emitter.emit(
                StreamEvent(
                    type=StreamEventType.AGENT_ERROR,
                    data={
                        "error_type": "init",
                        "message": f"{spec.provider} init failed: {msg}",
                        "recoverable": False,
                        "phase": "setup",
                    },
                    agent=spec.name or spec.provider,
                    loop_id=debate_id,
                )
            )
            logger.warning("[debate] %s: %s init failed: %s", debate_id, spec.provider, e)
            continue

        if spec.persona:
            try:
                apply_persona_to_agent(agent, spec.persona)
            except (ImportError, TypeError):
                pass

        agent = wrap_agent_for_streaming(agent, emitter, debate_id)
        agents.append(agent)
    return agents


def execute_debate_thread(
    debate_id: str,
    question: str,
    agents_str: str,
    rounds: int,
    consensus: str,
    trending_topic: Any | None,
    emitter: SyncEventEmitter,
    user_id: str = "",
    org_id: str = "",
    on_arena_created: Any | None = None,
    on_arena_finished: Any | None = None,
) -> None:
    """Execute a debate in a background thread.

    This method is run in a ThreadPoolExecutor to avoid blocking the event loop.

    Args:
        debate_id: Unique identifier for this debate
        question: The debate topic/question
        agents_str: Comma-separated list of agent types
        rounds: Number of debate rounds
        consensus: Consensus method to use
        trending_topic: Optional trending topic to seed the debate
        emitter: Event emitter for streaming updates
        user_id: Optional user ID for usage tracking
        org_id: Optional organization ID for usage tracking
        on_arena_created: Optional callback ``(arena) -> None`` invoked after
            the Arena is constructed but before ``arena.run()`` begins.  Used
            by the server to wire the TTS event bridge.
        on_arena_finished: Optional callback ``(arena) -> None`` invoked after
            the debate completes (success or failure) for cleanup.
    """
    import asyncio as _asyncio

    logger.info(
        f"[debate] Thread started for {debate_id}: "
        f"question={question[:50]}..., agents={agents_str}, rounds={rounds}"
    )
    thread_start_time = time.time()

    try:
        # Parse agents with bounds check
        agent_specs = AgentSpec.coerce_list(agents_str, warn=False)
        if len(agent_specs) > MAX_AGENTS_PER_DEBATE:
            _set_debate_error(debate_id, f"Too many agents. Maximum: {MAX_AGENTS_PER_DEBATE}")
            return
        if len(agent_specs) < 2:
            _set_debate_error(debate_id, "At least 2 agents required for a debate")
            return

        # Filter specs with OpenRouter fallback for missing keys
        agent_specs, requested_agents, missing_agents = _filter_agent_specs_with_fallback(
            agent_specs,
            emitter,
            debate_id,
        )
        actual_agents = [spec.name or spec.provider for spec in agent_specs]

        if len(agent_specs) < 2:
            _set_debate_error(
                debate_id,
                "Not enough configured agents available to start the debate",
                emitter,
            )
            return

        filtered = len(agent_specs) != len(requested_agents)
        emitter.emit(
            StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={
                    "task": question,
                    "agents": actual_agents,
                    "filtered": filtered,
                    "missing_agents": missing_agents,
                    "requested_agents": requested_agents,
                },
                loop_id=debate_id,
            )
        )

        # Create agents with streaming support
        agents = _create_debate_agents(agent_specs, emitter, debate_id)
        if len(agents) < 2:
            _set_debate_error(
                debate_id,
                "Not enough agents could be initialized to start the debate",
                emitter,
            )
            return

        agent_names = [a.name for a in agents]
        logger.info("[debate] %s: Created %s agents: %s", debate_id, len(agents), agent_names)

        # Create environment and protocol
        env = Environment(task=question, context="", max_rounds=rounds)
        protocol = DebateProtocol(
            rounds=rounds,
            consensus=cast("ConsensusType", consensus),
            proposer_count=len(agents),
            topology="all-to-all",
            early_stopping=False,
            convergence_detection=False,
            min_rounds_before_early_stop=rounds,
        )

        # Create arena with hooks
        hooks = create_arena_hooks(emitter, loop_id=debate_id)

        usage_tracker = None
        if user_id or org_id:
            try:
                usage_tracker = UsageTracker()
            except (ImportError, TypeError):
                pass

        arena = Arena(
            env,
            agents,
            protocol,
            event_hooks=hooks,
            event_emitter=cast("EventEmitterProtocol", emitter),
            loop_id=debate_id,
            trending_topic=trending_topic,
            user_id=user_id,
            org_id=org_id,
            usage_tracker=usage_tracker,
        )

        setup_time = time.time() - thread_start_time
        logger.info(
            f"[debate] {debate_id}: Arena created in {setup_time:.2f}s, starting execution..."
        )

        # Notify caller that the arena is ready (e.g. to wire TTS bridge)
        if on_arena_created is not None:
            try:
                on_arena_created(arena)
            except (RuntimeError, TypeError, ValueError, OSError) as cb_err:
                logger.warning("[debate] on_arena_created callback failed: %s", cb_err)

        # Run debate with timeout protection
        protocol_timeout = getattr(arena.protocol, "timeout_seconds", 0)
        timeout = (
            protocol_timeout
            if isinstance(protocol_timeout, (int, float)) and protocol_timeout > 0
            else DEBATE_TIMEOUT_SECONDS
        )
        with _active_debates_lock:
            _active_debates[debate_id]["status"] = "running"

        async def run_with_timeout():
            return await _asyncio.wait_for(arena.run(), timeout=timeout)

        try:
            result = _asyncio.run(run_with_timeout())
        finally:
            # Always notify caller for cleanup (e.g. stop TTS bridge)
            if on_arena_finished is not None:
                try:
                    on_arena_finished(arena)
                except (RuntimeError, TypeError, ValueError, OSError) as cb_err:
                    logger.warning("[debate] on_arena_finished callback failed: %s", cb_err)

        total_time = time.time() - thread_start_time
        logger.info(
            f"[debate] {debate_id}: Completed in {total_time:.2f}s, "
            f"consensus={result.consensus_reached}, confidence={result.confidence:.2f}"
        )

        with _active_debates_lock:
            _active_debates[debate_id]["status"] = "completed"
            _active_debates[debate_id]["completed_at"] = time.time()
            _active_debates[debate_id]["result"] = {
                "final_answer": result.final_answer,
                "consensus_reached": result.consensus_reached,
                "confidence": result.confidence,
            }

    except (
        ValueError,
        TypeError,
        RuntimeError,
        OSError,
        asyncio.TimeoutError,
        KeyError,
        AttributeError,
    ) as e:
        import traceback

        safe_msg = _safe_error_message(e, "debate_execution")
        error_trace = traceback.format_exc()
        _set_debate_error(debate_id, safe_msg)
        logger.error("[debate] Thread error in %s: %s\n%s", debate_id, str(e), error_trace)
        emitter.emit(
            StreamEvent(
                type=StreamEventType.ERROR,
                data={"error": safe_msg, "debate_id": debate_id},
            )
        )


__all__ = [
    "DEBATE_AVAILABLE",
    "execute_debate_thread",
    "fetch_trending_topic_async",
    "parse_debate_request",
]
