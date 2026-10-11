"""Subsystem setup helpers for Arena initialization.

Consolidated module containing:
- Fabric integration, debate strategy, post-debate workflow
- Knowledge operations, RLM limiter, agent hierarchy, grounded operations
- Agent channel management (setup/teardown)
- Lifecycle/cache management (DebateStateCache, LifecycleManager, EventEmitter, CheckpointOps)
- Domain classification (compute_domain_from_task)
- Output formatting and translation

Previously split across orchestrator_setup.py, orchestrator_lifecycle.py,
orchestrator_domains.py, and orchestrator_output.py. Consolidated for maintainability.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any

from aragora.debate.checkpoint_ops import CheckpointOperations
from aragora.debate.event_emission import EventEmitter
from aragora.debate.grounded_operations import GroundedOperations
from aragora.debate.hierarchy import HierarchyConfig
from aragora.debate.knowledge_manager import ArenaKnowledgeManager
from aragora.debate.lifecycle_manager import LifecycleManager
from aragora.debate.state_cache import DebateStateCache
from aragora.logging_config import get_logger as get_structured_logger
from aragora.utils.cache_registry import register_lru_cache

if TYPE_CHECKING:
    from aragora.core import Agent, DebateResult
    from aragora.debate.context import DebateContext
    from aragora.debate.cognitive_limiter_rlm import RLMCognitiveLoadLimiter
    from aragora.debate.orchestrator import Arena

logger = get_structured_logger(__name__)


def init_fabric_integration(
    arena: Arena,
    fabric: Any | None,
    fabric_config: Any | None,
    agents: list[Agent],
) -> list[Agent]:
    """Initialize fabric integration for agent pool management.

    Returns the agents list (possibly from fabric pool if configured).

    Args:
        arena: Arena instance.
        fabric: Optional fabric instance.
        fabric_config: Optional fabric configuration.
        agents: List of agents (may be empty if using fabric).

    Returns:
        List of agents to use for the debate.
    """
    if fabric is not None and fabric_config is not None:
        if agents:
            raise ValueError(
                "Cannot specify both 'agents' and 'fabric'/'fabric_config'. "
                "Use either direct agents or fabric-managed agents."
            )
        from aragora.debate.orchestrator_agents import (
            get_fabric_agents_sync as _agents_get_fabric_agents_sync,
        )

        agents = _agents_get_fabric_agents_sync(fabric, fabric_config)
        arena._fabric = fabric
        arena._fabric_config = fabric_config
        logger.info(
            "[fabric] Arena using fabric pool %s with %s agents", fabric_config.pool_id, len(agents)
        )
    else:
        arena._fabric = None
        arena._fabric_config = None
    return agents


def init_debate_strategy(
    arena: Arena,
    enable_adaptive_rounds: bool,
    debate_strategy: Any | None,
) -> Any | None:
    """Initialize debate strategy for adaptive rounds.

    Auto-creates DebateStrategy if adaptive rounds enabled but no strategy provided.

    Args:
        arena: Arena instance to configure.
        enable_adaptive_rounds: Whether adaptive rounds are enabled.
        debate_strategy: Optional pre-configured strategy.

    Returns:
        The debate strategy (may be auto-created or None).
    """
    arena.enable_adaptive_rounds = enable_adaptive_rounds
    arena.debate_strategy = debate_strategy

    if arena.enable_adaptive_rounds and arena.debate_strategy is None:
        try:
            from aragora.debate.strategy import DebateStrategy

            arena.debate_strategy = DebateStrategy(
                continuum_memory=arena.continuum_memory,
            )
            logger.info("debate_strategy auto-initialized for adaptive rounds")
        except ImportError:
            logger.debug("DebateStrategy not available")
            arena.debate_strategy = None
        except (TypeError, ValueError) as e:
            logger.warning("Failed to initialize DebateStrategy: %s", e)
            arena.debate_strategy = None
        except (RuntimeError, AttributeError, OSError) as e:
            logger.exception("Unexpected error initializing DebateStrategy: %s", e)
            arena.debate_strategy = None

    return arena.debate_strategy


def init_post_debate_workflow(
    arena: Arena,
    enable_post_debate_workflow: bool,
    post_debate_workflow: Any | None,
    post_debate_workflow_threshold: float,
) -> None:
    """Initialize post-debate workflow automation.

    Auto-creates default post-debate workflow if enabled but not provided.

    Args:
        arena: Arena instance to configure.
        enable_post_debate_workflow: Whether post-debate workflow is enabled.
        post_debate_workflow: Optional pre-configured workflow.
        post_debate_workflow_threshold: Confidence threshold for triggering.
    """
    if enable_post_debate_workflow and post_debate_workflow is None:
        try:
            from aragora.workflow.patterns.post_debate import get_default_post_debate_workflow

            post_debate_workflow = get_default_post_debate_workflow()
            logger.debug("[arena] Auto-created default post-debate workflow")
        except ImportError:
            logger.warning("[arena] Post-debate workflow enabled but pattern not available")

    arena.post_debate_workflow = post_debate_workflow
    arena.enable_post_debate_workflow = enable_post_debate_workflow
    arena.post_debate_workflow_threshold = post_debate_workflow_threshold


def init_knowledge_ops(arena: Arena) -> None:
    """Initialize ArenaKnowledgeManager for knowledge retrieval and ingestion.

    Sets up the knowledge mound, supermemory adapter, revalidation scheduler,
    and knowledge bridge hub on the Arena instance.

    Args:
        arena: Arena instance to configure.
    """
    arena._km_manager = ArenaKnowledgeManager(
        knowledge_mound=arena.knowledge_mound,
        enable_retrieval=arena.enable_knowledge_retrieval,
        enable_ingestion=arena.enable_knowledge_ingestion,
        enable_supermemory=arena.enable_supermemory,
        supermemory_adapter=arena.supermemory_adapter,
        supermemory_inject_on_start=arena.supermemory_inject_on_start,
        supermemory_max_context_items=arena.supermemory_max_context_items,
        supermemory_context_container_tag=arena.supermemory_context_container_tag,
        supermemory_sync_on_conclusion=arena.supermemory_sync_on_conclusion,
        supermemory_min_confidence_for_sync=arena.supermemory_min_confidence_for_sync,
        supermemory_outcome_container_tag=arena.supermemory_outcome_container_tag,
        supermemory_enable_privacy_filter=arena.supermemory_enable_privacy_filter,
        supermemory_enable_resilience=arena.supermemory_enable_resilience,
        supermemory_enable_km_adapter=arena.supermemory_enable_km_adapter,
        enable_auto_revalidation=arena.enable_auto_revalidation,
        revalidation_staleness_threshold=getattr(arena, "revalidation_staleness_threshold", 0.7),
        revalidation_check_interval_seconds=getattr(
            arena, "revalidation_check_interval_seconds", 3600
        ),
        notify_callback=lambda event_type, data: arena._notify_spectator(event_type, **data),
    )
    arena._km_manager.initialize(
        continuum_memory=arena.continuum_memory,
        consensus_memory=arena.consensus_memory,
        elo_system=arena.elo_system,
        cost_tracker=getattr(arena, "cost_tracker", None),
        insight_store=arena.insight_store,
        flip_detector=arena.flip_detector,
        evidence_store=getattr(arena, "evidence_store", None),
        pulse_manager=getattr(arena, "pulse_manager", None),
        memory=arena.memory,
    )
    # Propagate supermemory adapter/config (may be initialized in manager)
    arena.supermemory_adapter = arena._km_manager.supermemory_adapter
    arena.enable_supermemory = arena._km_manager.enable_supermemory
    arena._knowledge_ops = arena._km_manager._knowledge_ops
    arena.knowledge_bridge_hub = arena._km_manager.knowledge_bridge_hub
    if arena._km_manager.revalidation_scheduler is not None:
        arena.revalidation_scheduler = arena._km_manager.revalidation_scheduler
    arena._km_coordinator = arena._km_manager._km_coordinator
    arena._km_adapters = arena._km_manager._km_adapters
    arena._km_metadata_template = {
        "knowledge_mound_present": arena.knowledge_mound is not None,
        "supermemory_enabled": bool(arena.enable_supermemory),
        "context_handoff": {
            "status": "pending" if arena.knowledge_mound is not None else "not_configured",
            "non_blocking": True,
        },
        "retrieval": {
            "enabled": bool(arena.enable_knowledge_retrieval),
            "status": (
                "pending"
                if arena.enable_knowledge_retrieval and arena.knowledge_mound is not None
                else "disabled"
                if not arena.enable_knowledge_retrieval
                else "not_configured"
            ),
            "observed_context_chars": 0,
            "observed_item_count": 0,
        },
        "writeback": {
            "enabled": bool(arena.enable_knowledge_ingestion),
            "status": "pending" if arena.enable_knowledge_ingestion else "disabled",
            "attempts": 0,
        },
    }


def init_grounded_operations(arena: Arena) -> None:
    """Initialize GroundedOperations helper for verdict and relationship management.

    Args:
        arena: Arena instance to configure.
    """
    arena._grounded_ops = GroundedOperations(
        position_ledger=arena.position_ledger,
        elo_system=arena.elo_system,
        evidence_grounder=None,  # Set after _init_phases
    )


def init_agent_hierarchy(
    arena: Arena,
    enable_agent_hierarchy: bool,
    hierarchy_config: HierarchyConfig | None,
) -> None:
    """Initialize AgentHierarchy for Gastown pattern.

    Args:
        arena: Arena instance to configure.
        enable_agent_hierarchy: Whether hierarchy is enabled.
        hierarchy_config: Optional hierarchy configuration.
    """
    from aragora.debate.orchestrator_agents import (
        init_agent_hierarchy as _agents_init_agent_hierarchy,
    )

    arena.enable_agent_hierarchy = enable_agent_hierarchy
    arena._hierarchy = _agents_init_agent_hierarchy(enable_agent_hierarchy, hierarchy_config)


def init_rlm_limiter(
    arena: Arena,
    use_rlm_limiter: bool,
    rlm_limiter: RLMCognitiveLoadLimiter | None,
    rlm_compression_threshold: int,
    rlm_max_recent_messages: int,
    rlm_summary_level: str,
    rlm_compression_round_threshold: int,
) -> None:
    """Initialize the RLM cognitive load limiter for context compression.

    Args:
        arena: Arena instance to configure.
        use_rlm_limiter: Whether to use the limiter.
        rlm_limiter: Optional pre-configured limiter.
        rlm_compression_threshold: Token threshold for compression.
        rlm_max_recent_messages: Max recent messages to keep.
        rlm_summary_level: Summary level for compression.
        rlm_compression_round_threshold: Round threshold for compression.
    """
    from aragora.debate.orchestrator_memory import (
        init_rlm_limiter_state as _mem_init_rlm_limiter_state,
    )

    state = _mem_init_rlm_limiter_state(
        use_rlm_limiter=use_rlm_limiter,
        rlm_limiter=rlm_limiter,
        rlm_compression_threshold=rlm_compression_threshold,
        rlm_max_recent_messages=rlm_max_recent_messages,
        rlm_summary_level=rlm_summary_level,
    )
    arena.use_rlm_limiter = state["use_rlm_limiter"]
    arena.rlm_compression_threshold = state["rlm_compression_threshold"]
    arena.rlm_max_recent_messages = state["rlm_max_recent_messages"]
    arena.rlm_summary_level = state["rlm_summary_level"]
    arena.rlm_limiter = state["rlm_limiter"]
    arena.rlm_compression_round_threshold = rlm_compression_round_threshold


def init_selection_feedback(arena: Arena) -> None:
    """Initialize SelectionFeedbackLoop for performance-based agent selection.

    Reads ``enable_performance_feedback`` from the arena's config and
    auto-creates a SelectionFeedbackLoop if enabled.

    Args:
        arena: Arena instance to configure.
    """
    if not getattr(arena, "enable_performance_feedback", False):
        arena._selection_feedback_loop = None
        return

    try:
        from aragora.debate.selection_feedback import SelectionFeedbackLoop

        arena._selection_feedback_loop = SelectionFeedbackLoop()
        logger.info("[selection_feedback] SelectionFeedbackLoop initialized")
    except ImportError:
        logger.debug("SelectionFeedbackLoop not available")
        arena._selection_feedback_loop = None
    except (TypeError, ValueError) as e:
        logger.warning("Failed to initialize SelectionFeedbackLoop: %s", e)
        arena._selection_feedback_loop = None


def init_cost_tracking(arena: Arena) -> None:
    """Initialize CostTracker and register debate-level budget limits.

    Reads ``budget_limit_usd`` from the arena's budget sub-config and
    registers it with the global CostTracker instance.

    Args:
        arena: Arena instance to configure.
    """
    try:
        from aragora.billing.cost_tracker import get_cost_tracker

        tracker = get_cost_tracker()
        if tracker is None:
            arena._cost_tracker = None
            return

        arena._cost_tracker = tracker

        # Register per-debate budget limit if configured
        budget_limit = getattr(arena, "budget_limit_usd", None)
        if budget_limit and budget_limit > 0:
            try:
                from decimal import Decimal as _Decimal

                from aragora.billing.cost_tracker import Budget

                tracker.set_budget(Budget(per_debate_limit_usd=_Decimal(str(budget_limit))))
                logger.info("[cost_tracking] Budget limit set: $%.2f", budget_limit)
            except (AttributeError, TypeError, ImportError):
                pass  # Budget/set_budget may not exist yet

        logger.debug("[cost_tracking] CostTracker attached to arena")
    except ImportError:
        logger.debug("CostTracker not available")
        arena._cost_tracker = None
    except (TypeError, ValueError) as e:
        logger.warning("Failed to initialize CostTracker: %s", e)
        arena._cost_tracker = None


def init_health_registry(arena: Arena) -> None:
    """Initialize HealthRegistry and register health checkers for subsystems.

    Registers health checks for event_bus, knowledge_mound, memory, and
    cost_tracker so that startup and runtime health reports include them.

    Args:
        arena: Arena instance to configure.
    """
    try:
        from aragora.resilience.health import get_global_health_registry

        registry = get_global_health_registry()
        if registry is None:
            arena._health_registry = None
            return

        arena._health_registry = registry

        # Register health checks for key subsystems
        subsystem_checks = {
            "event_bus": arena.event_bus is not None,
            "knowledge_mound": getattr(arena, "knowledge_mound", None) is not None,
            "memory": getattr(arena, "memory", None) is not None,
            "cost_tracker": getattr(arena, "_cost_tracker", None) is not None,
        }

        for name, healthy in subsystem_checks.items():
            try:
                checker = registry.register(name)
                if healthy:
                    checker.record_success()
            except (AttributeError, TypeError):
                pass  # register/record_success may not exist

        logger.debug("[health] Registered %s subsystem health checks", len(subsystem_checks))
    except ImportError:
        logger.debug("HealthRegistry not available")
        arena._health_registry = None
    except (TypeError, ValueError) as e:
        logger.warning("Failed to initialize HealthRegistry: %s", e)
        arena._health_registry = None


async def setup_agent_channels(arena: Arena, ctx: DebateContext, debate_id: str) -> None:
    """Initialize agent-to-agent channels for the current debate.

    Args:
        arena: Arena instance.
        ctx: Current debate context.
        debate_id: Debate identifier.
    """
    if not getattr(arena.protocol, "enable_agent_channels", False):
        return
    try:
        from aragora.debate.channel_integration import create_channel_integration

        channel_integration = create_channel_integration(
            debate_id=debate_id,
            agents=arena.agents,
            protocol=arena.protocol,
        )
        if await channel_integration.setup():
            arena._channel_integration = channel_integration  # type: ignore[assignment]
            ctx.channel_integration = channel_integration
        else:
            arena._channel_integration = None
    except (ImportError, ConnectionError, OSError, ValueError, TypeError, AttributeError) as e:
        logger.debug("[channels] Channel setup failed (non-critical): %s", e)
        arena._channel_integration = None


async def teardown_agent_channels(arena: Arena) -> None:
    """Tear down agent channels after debate completion.

    Args:
        arena: Arena instance.
    """
    if not arena._channel_integration:
        return
    try:
        await arena._channel_integration.teardown()
    except (ConnectionError, OSError, RuntimeError) as e:
        logger.debug("[channels] Channel teardown failed (non-critical): %s", e)
    finally:
        arena._channel_integration = None


# ---------------------------------------------------------------------------
# Lifecycle / cache management (from orchestrator_lifecycle.py)
# ---------------------------------------------------------------------------


def init_caches(arena: Arena) -> None:
    """Initialize caches for computed values.

    Creates the DebateStateCache for caching debate state computations.

    Args:
        arena: Arena instance to initialize.
    """
    arena._cache = DebateStateCache()


def init_lifecycle_manager(arena: Arena) -> None:
    """Initialize LifecycleManager for cleanup and task cancellation.

    Creates the LifecycleManager with references to the cache, circuit breaker,
    and checkpoint manager for coordinated lifecycle operations.

    Args:
        arena: Arena instance to initialize.
    """
    arena._lifecycle = LifecycleManager(
        cache=arena._cache,
        circuit_breaker=arena.circuit_breaker,
        checkpoint_manager=arena.checkpoint_manager,
    )


def init_event_emitter(arena: Arena) -> None:
    """Initialize EventEmitter for spectator/websocket events.

    Creates the EventEmitter with connections to event bus, event bridge,
    hooks, and persona manager for broadcasting debate events.

    Args:
        arena: Arena instance to initialize.
    """
    arena._event_emitter = EventEmitter(
        event_bus=arena.event_bus,
        event_bridge=arena.event_bridge,
        hooks=arena.hooks,
        persona_manager=arena.persona_manager,
    )


def init_checkpoint_ops(arena: Arena) -> None:
    """Initialize CheckpointOperations for checkpoint and memory operations.

    Creates the CheckpointOperations helper. Note: memory_manager is set to None
    initially and should be updated after _init_phases when memory_manager exists.

    Args:
        arena: Arena instance to initialize.
    """
    arena._checkpoint_ops = CheckpointOperations(
        checkpoint_manager=arena.checkpoint_manager,
        memory_manager=None,  # Set after _init_phases when memory_manager exists
        cache=arena._cache,
    )


# ---------------------------------------------------------------------------
# Domain classification (from orchestrator_domains.py)
# ---------------------------------------------------------------------------


@register_lru_cache
@lru_cache(maxsize=1024)
def compute_domain_from_task(task_lower: str) -> str:
    """Compute domain from lowercased task string.

    Module-level cached helper to avoid O(n) string matching
    for repeated task strings across debate instances.

    Args:
        task_lower: Lowercased task description string

    Returns:
        Domain name: security, performance, testing, architecture,
        debugging, api, database, frontend, or general
    """
    if any(w in task_lower for w in ("security", "hack", "vulnerability", "auth", "encrypt")):
        return "security"
    if any(w in task_lower for w in ("performance", "speed", "optimize", "cache", "latency")):
        return "performance"
    if any(w in task_lower for w in ("test", "testing", "coverage", "regression")):
        return "testing"
    if any(w in task_lower for w in ("design", "architecture", "pattern", "structure")):
        return "architecture"
    if any(w in task_lower for w in ("bug", "error", "fix", "crash", "exception")):
        return "debugging"
    if any(w in task_lower for w in ("api", "endpoint", "rest", "graphql")):
        return "api"
    if any(w in task_lower for w in ("database", "sql", "query", "schema")):
        return "database"
    if any(w in task_lower for w in ("ui", "frontend", "react", "css", "layout")):
        return "frontend"
    return "general"


# Backward compatibility alias
_compute_domain_from_task = compute_domain_from_task


# ---------------------------------------------------------------------------
# Output formatting and translation (from orchestrator_output.py)
# ---------------------------------------------------------------------------


def format_conclusion(result: DebateResult) -> str:
    """Format debate conclusion. Delegates to ResultFormatter.

    Args:
        result: The completed debate result.

    Returns:
        A formatted conclusion string.
    """
    from aragora.debate.result_formatter import ResultFormatter

    return ResultFormatter().format_conclusion(result)


async def translate_conclusions(
    result: DebateResult,
    protocol: Any,
) -> None:
    """Translate debate conclusions to configured target languages.

    Uses the translation module to provide multi-language support.
    Translations are stored in ``result.translations`` dict.

    Args:
        result: The completed debate result (mutated in place).
        protocol: The debate protocol (checked for ``target_languages``,
            ``default_language``).
    """
    if not result.final_answer:
        return

    target_languages = getattr(protocol, "target_languages", [])
    if not target_languages:
        return

    try:
        from aragora.debate.translation import (
            Language,
            get_translation_service,
        )

        service = get_translation_service()
        default_lang = getattr(protocol, "default_language", "en")

        # Detect or use configured source language
        source_lang = Language.from_code(default_lang) or Language.ENGLISH

        for target_code in target_languages:
            target_lang = Language.from_code(target_code)
            if not target_lang or target_lang == source_lang:
                continue

            try:
                translation_result = await service.translate(
                    result.final_answer,
                    target_lang,
                    source_lang,
                )
                if translation_result.confidence > 0.5:
                    result.translations[target_code] = translation_result.translated_text
                    logger.debug(
                        "Translated conclusion to %s (confidence: %.2f)",
                        target_lang.name_english,
                        translation_result.confidence,
                    )
            except (ConnectionError, OSError, ValueError, TypeError) as e:
                logger.warning("Translation to %s failed: %s", target_code, e)

    except ImportError as e:
        logger.debug("Translation module not available: %s", e)
    except (AttributeError, RuntimeError) as e:
        logger.warning("Translation failed (non-critical): %s", e)
