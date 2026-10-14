"""Memory coordination, RLM compression, and persistence helpers for Arena.

Extracted from orchestrator.py to reduce its size. These functions handle
cross-debate memory, belief network setup, RLM cognitive load limiting,
Supabase sync, and memory outcome storage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from aragora.logging_config import get_logger as get_structured_logger

if TYPE_CHECKING:
    from aragora.core import DebateResult
    from aragora.debate.context import DebateContext

logger = get_structured_logger(__name__)


def queue_for_supabase_sync(ctx: DebateContext, result: DebateResult) -> None:
    """Queue debate result for background Supabase sync.

    This is a non-blocking operation. If sync is disabled or fails,
    the debate still completes successfully (SQLite remains primary).

    Args:
        ctx: Debate context with metadata.
        result: Completed debate result.
    """
    try:
        from aragora.persistence.sync_service import get_sync_service

        sync = get_sync_service()
        if not sync.enabled:
            return

        debate_data = {
            "id": result.id,
            "debate_id": result.debate_id or ctx.debate_id,
            "loop_id": getattr(ctx, "loop_id", "default"),
            "cycle_number": getattr(ctx, "cycle_number", 0),
            "phase": "debate",
            "task": result.task,
            "agents": [a.name for a in ctx.agents] if ctx.agents else [],
            "transcript": "\n".join(str(m) for m in result.messages[:50]),
            "consensus_reached": result.consensus_reached,
            "confidence": result.confidence,
            "winning_proposal": result.final_answer[:1000] if result.final_answer else None,
            "vote_tally": {v.choice: 1 for v in result.votes} if result.votes else None,
        }

        sync.queue_debate(debate_data)
        logger.debug("Queued debate %s for Supabase sync", result.id)

    except ImportError:
        logger.debug("Supabase sync not available")
    except (ConnectionError, TimeoutError) as e:
        logger.debug("Supabase sync queue failed (non-fatal): %s", e)
    except (RuntimeError, OSError, ValueError) as e:
        logger.warning("Unexpected Supabase sync error (non-fatal): %s", e)


def setup_belief_network(
    debate_id: str,
    topic: str,
    seed_from_km: bool = True,
) -> Any:
    """Initialize BeliefNetwork and seed with prior beliefs from KM.

    This implements the KM -> BeliefNetwork reverse flow for cross-session
    learning. When a new debate starts, we seed the belief network with
    historical cruxes and beliefs related to the topic.

    Args:
        debate_id: Unique ID for this debate.
        topic: The debate topic/question.
        seed_from_km: Whether to seed from Knowledge Mound.

    Returns:
        BeliefNetwork instance or ``None`` if initialization fails.
    """
    try:
        from aragora.reasoning.belief import BeliefNetwork

        km_adapter = None
        try:
            from aragora.knowledge.mound.adapters.belief_adapter import BeliefAdapter

            km_adapter = BeliefAdapter()
        except ImportError:
            logger.debug("[arena] BeliefAdapter not available")

        network = BeliefNetwork(
            debate_id=debate_id,
            km_adapter=cast(Any, km_adapter),  # BeliefAdapter implements _BeliefAdapterProtocol
        )

        if seed_from_km and km_adapter and topic:
            seeded = network.seed_from_km(topic, min_confidence=0.7)
            if seeded > 0:
                logger.info("[arena] Seeded belief network with %s prior beliefs from KM", seeded)

        return network

    except ImportError:
        logger.debug("[arena] BeliefNetwork not available")
        return None
    except (ValueError, TypeError, AttributeError, KeyError) as e:
        logger.debug("[arena] Failed to setup belief network: %s", e)
        return None


def init_rlm_limiter_state(
    use_rlm_limiter: bool,
    rlm_limiter: Any,
    rlm_compression_threshold: int,
    rlm_max_recent_messages: int,
    rlm_summary_level: str,
) -> dict[str, Any]:
    """Compute RLM cognitive load limiter state for the Arena.

    Returns a dict of attribute values to set on the Arena instance:
    ``use_rlm_limiter``, ``rlm_compression_threshold``,
    ``rlm_max_recent_messages``, ``rlm_summary_level``, ``rlm_limiter``.
    """
    state: dict[str, Any] = {
        "use_rlm_limiter": use_rlm_limiter,
        "rlm_compression_threshold": rlm_compression_threshold,
        "rlm_max_recent_messages": rlm_max_recent_messages,
        "rlm_summary_level": rlm_summary_level,
        "rlm_limiter": None,
    }

    if rlm_limiter is not None:
        state["rlm_limiter"] = rlm_limiter
    elif use_rlm_limiter:
        try:
            from aragora.debate.cognitive_limiter_rlm import (
                RLMCognitiveBudget,
                RLMCognitiveLoadLimiter,
            )

            budget = RLMCognitiveBudget(
                enable_rlm_compression=True,
                compression_threshold=rlm_compression_threshold,
                max_recent_full_messages=rlm_max_recent_messages,
                summary_level=rlm_summary_level,
            )
            state["rlm_limiter"] = RLMCognitiveLoadLimiter(budget=budget)
            logger.info(
                "[arena] RLM limiter enabled: threshold=%s, recent=%s, level=%s",
                rlm_compression_threshold,
                rlm_max_recent_messages,
                rlm_summary_level,
            )
        except ImportError:
            logger.warning("[arena] RLM module not available, disabling limiter")
            state["rlm_limiter"] = None
            state["use_rlm_limiter"] = False

    return state


def init_checkpoint_bridge(
    protocol: Any,
    checkpoint_manager: Any,
) -> tuple[Any, Any]:
    """Initialize optional checkpoint bridge for molecule-aware recovery.

    Args:
        protocol: Debate protocol (checked for enable_molecule_tracking).
        checkpoint_manager: Optional CheckpointManager.

    Returns:
        Tuple of (molecule_orchestrator, checkpoint_bridge), either may be ``None``.
    """
    molecule_orchestrator = None
    checkpoint_bridge = None

    if getattr(protocol, "enable_molecule_tracking", False):
        try:
            from aragora.debate.molecule_orchestrator import get_molecule_orchestrator

            molecule_orchestrator = get_molecule_orchestrator(protocol)
        except ImportError:
            logger.debug("[molecules] Molecule orchestrator not available")
        except (ValueError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning("[molecules] Failed to initialize orchestrator: %s", e)

    if checkpoint_manager or molecule_orchestrator:
        try:
            from aragora.debate.checkpoint_bridge import create_checkpoint_bridge

            checkpoint_bridge = create_checkpoint_bridge(
                molecule_orchestrator=molecule_orchestrator,
                checkpoint_manager=checkpoint_manager,
            )
        except ImportError:
            logger.debug("[checkpoint_bridge] Checkpoint bridge not available")
        except (ValueError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning("[checkpoint_bridge] Initialization failed: %s", e)

    return molecule_orchestrator, checkpoint_bridge


def auto_create_knowledge_mound(
    knowledge_mound: Any,
    auto_create: bool,
    enable_retrieval: bool,
    enable_ingestion: bool,
    org_id: str,
) -> Any:
    """Auto-create a KnowledgeMound if not provided.

    Args:
        knowledge_mound: Existing mound instance (returned as-is if not ``None``).
        auto_create: Whether auto-creation is enabled.
        enable_retrieval: Whether knowledge retrieval is enabled.
        enable_ingestion: Whether knowledge ingestion is enabled.
        org_id: Organization ID for workspace scoping.

    Returns:
        A KnowledgeMound instance or ``None``.
    """

    def _is_valid_knowledge_mound(obj: Any) -> bool:
        """Return True when object exposes at least one KM capability method."""
        return any(
            hasattr(obj, method)
            for method in ("query_semantic", "query_with_visibility", "store", "initialize")
        )

    if knowledge_mound is not None:
        if _is_valid_knowledge_mound(knowledge_mound):
            return knowledge_mound
        logger.warning(
            "[knowledge_mound] Ignoring invalid KM object of type %s (missing query/store methods)",
            type(knowledge_mound).__name__,
        )
        knowledge_mound = None

    if not auto_create:
        if enable_retrieval or enable_ingestion:
            logger.warning(
                "[knowledge_mound] KM not provided and auto_create_knowledge_mound=False. "
                "Knowledge retrieval/ingestion features will be disabled."
            )
        return None

    if not (enable_retrieval or enable_ingestion):
        return None

    try:
        from aragora.knowledge.mound import get_knowledge_mound

        km = get_knowledge_mound(
            workspace_id=org_id or "default",
            auto_initialize=True,
        )
        logger.info(
            "[knowledge_mound] Auto-created KM instance for debate (enable_retrieval=%s, enable_ingestion=%s)",
            enable_retrieval,
            enable_ingestion,
        )
        return km
    except ImportError as e:
        logger.warning(
            "[knowledge_mound] Could not auto-create: %s. Debates will run without knowledge grounding.",
            e,
        )
    except (RuntimeError, ConnectionError, OSError) as e:
        logger.warning(
            "[knowledge_mound] Initialization failed (infrastructure): %s. Debates will run without knowledge grounding.",
            e,
        )
    except (ValueError, TypeError, AttributeError) as e:
        logger.warning(
            "[knowledge_mound] Initialization failed (config): %s. Debates will run without knowledge grounding.",
            e,
        )
    except (KeyError, ImportError) as e:
        logger.exception(
            "[knowledge_mound] Unexpected initialization error: %s. Debates will run without knowledge grounding.",
            e,
        )
    return None


def init_cross_subscriber_bridge(event_bus: Any) -> Any:
    """Initialize cross-subscriber bridge for event cross-pollination.

    Connects the Arena's EventBus to the CrossSubscriberManager,
    enabling cross-subsystem event handling during debates.

    Runs at Arena construction time, before ``initialize_debate_context``'s
    own bootstrap call - so this bridges to a bootstrapped manager directly
    (via ``bootstrap_debate_event_subscribers``) rather than relying on the
    bare ``get_cross_subscriber_manager()`` accessor that
    ``ArenaEventBridge`` otherwise falls back to. The manager is a
    process-wide singleton that a later bootstrap call would mutate in
    place either way, but constructing the bridge against an
    already-wired manager removes that ordering assumption (P4a E8
    SCOPE #1 hardening; no confirmed production gap, since phase
    execution - where this bridge actually dispatches - already runs
    after that later bootstrap call within the same debate).

    Args:
        event_bus: The Arena's EventBus instance (may be ``None``).

    Returns:
        ArenaEventBridge instance or ``None``.
    """
    if event_bus is None:
        return None

    try:
        from aragora.debate.arena_bridge import ArenaEventBridge
        from aragora.debate.event_subscribers import bootstrap_debate_event_subscribers

        manager = bootstrap_debate_event_subscribers()
        bridge = ArenaEventBridge(event_bus, cross_manager=manager)
        bridge.connect_to_cross_subscribers()
        logger.debug("[arena] Cross-subscriber bridge connected")
        return bridge
    except ImportError:
        logger.debug("[arena] Cross-subscriber bridge not available")
        return None
    except (AttributeError, ValueError, TypeError, RuntimeError) as e:
        logger.warning("[arena] Failed to initialize cross-subscriber bridge: %s", e)
        return None


async def compress_debate_messages(
    messages: list,
    critiques: list | None,
    use_rlm_limiter: bool,
    rlm_limiter: Any,
) -> tuple[list, list | None]:
    """Compress debate messages using RLM cognitive load limiter.

    Uses hierarchical compression to reduce context size while preserving
    semantic content. Older messages are summarized, recent messages kept
    at full detail.

    Args:
        messages: List of debate messages to compress.
        critiques: Optional list of critiques to compress.
        use_rlm_limiter: Whether the RLM limiter is enabled.
        rlm_limiter: The limiter instance (or ``None``).

    Returns:
        Tuple of (compressed_messages, compressed_critiques).
    """
    if not use_rlm_limiter or not rlm_limiter:
        return messages, critiques

    try:
        result = await rlm_limiter.compress_context_async(
            messages=messages,
            critiques=critiques,
        )

        if result.compression_applied:
            logger.info(
                "[arena] Compressed debate context: %s -> %s chars (%.0f%% of original)",
                result.original_chars,
                result.compressed_chars,
                result.compression_ratio * 100,
            )

        return result.messages, result.critiques
    except (ValueError, TypeError, AttributeError) as e:
        logger.warning("[arena] RLM compression failed with data error, using original: %s", e)
        return messages, critiques
    except (RuntimeError, OSError, ImportError) as e:
        logger.exception("[arena] Unexpected RLM compression error, using original: %s", e)
        return messages, critiques
