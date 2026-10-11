"""Knowledge-domain event-subscriber home (P4a EventBus inversion, Batch E2).

Bidirectional Knowledge Mound cross-subsystem reactions, relocated here from
infrastructure ``aragora.events.cross_subscribers.handlers.knowledge_mound`` so the
knowledge-coupled reactions live in their DOMAIN home. The module self-registers via
the domain-free registry (``aragora.events.cross_subscribers.register_subscriber`` -
domain -> infrastructure, downward = legal); the layered bootstraps import it so
``CrossSubscriberManager.apply_registered_subscribers`` wires these reactions in.

Per the relocate-UP no-shim exemption (AGENTS.md "P4a Contracts-Thread Shared Rules"
and docs/architecture/P4A_EVENTS_QUEUE_INVERSION.md §8) there is NO re-export shim at
the old path; every consumer is repointed instead.

Handles bidirectional data flow between subsystems and Knowledge Mound:
- Memory ↔ KM: Sync high-importance memories
- Belief ↔ KM: Store converged beliefs, initialize priors
- RLM ↔ KM: Store compression patterns, update priorities
- ELO ↔ KM: Store agent expertise, query domain experts
- Insight → KM: Store high-confidence insights
- Flip → KM: Store flip events for meta-learning
- Trickster ← KM: Query flip history
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from aragora.events.cross_subscribers import get_registered_subscribers, register_subscriber
from aragora.events.types import StreamEventType

if TYPE_CHECKING:
    import asyncio

    from aragora.config.settings import Settings
    from aragora.events.cross_subscribers import CrossSubscriberManager
    from aragora.events.types import StreamEvent
    from aragora.knowledge.mound.facade import KnowledgeMound

# Import metrics stubs - will be overwritten if metrics available
try:
    from aragora.observability.prometheus_cross_pollination import (
        record_km_inbound_event,
        record_km_outbound_event,
    )
except ImportError:

    def record_km_inbound_event(source: str, event_type: str) -> None:
        pass

    def record_km_outbound_event(target: str, event_type: str) -> None:
        pass


# Feature-flag settings (mirrors the manager helper so the subscriber needs no
# manager state at construction time).
try:
    from aragora.config.settings import get_settings as _get_settings

    _SETTINGS_AVAILABLE = True

    def get_settings() -> "Settings | None":
        return _get_settings()

except ImportError:
    _SETTINGS_AVAILABLE = False

    def get_settings() -> "Settings | None":
        return None


logger = logging.getLogger(__name__)

KNOWLEDGE_EVENT_SUBSCRIBER_HANDLER_NAMES = frozenset(
    {
        "memory_to_mound",
        "mound_to_memory_retrieval",
        "belief_to_mound",
        "mound_to_belief",
        "rlm_to_mound",
        "mound_to_rlm",
        "elo_to_mound",
        "mound_to_team_selection",
        "insight_to_mound",
        "flip_to_mound",
        "mound_to_trickster",
        "provenance_to_mound",
        "mound_to_provenance",
        "consensus_to_mound",
        "km_validation_feedback",
        "mound_to_culture",
        "debate_outcome_to_knowledge",
        "workflow_complete_to_supermemory",
        "workflow_failed_to_supermemory",
        "tier_demotion_to_revalidation",
        "tier_promotion_to_knowledge",
        "approval_to_km_reinforcement",
    }
)


class KnowledgeEventSubscriber:
    """Knowledge-domain cross-subscriber: KM ingest/mound reactions.

    Owns its reactions and wires them into the manager via :meth:`register` (invoked
    by ``CrossSubscriberManager.apply_registered_subscribers`` at bootstrap). Feature
    flags are read via :meth:`_is_km_handler_enabled`, a self-contained copy of the
    manager helper.
    """

    def __init__(self) -> None:
        self._settings = get_settings() if _SETTINGS_AVAILABLE else None
        # Per-debate culture protocol hints, populated by _store_debate_culture
        # and read back via get_debate_culture_hints (relocated from
        # CrossSubscriberManager._debate_cultures, P4a Batch E2c).
        self._debate_cultures: dict[str, dict[str, Any]] = {}
        # In-flight KM culture-profile retrieval task per debate, scheduled by
        # _handle_mound_to_culture and consumed (popped) via
        # get_pending_culture_task so a caller can await it before reading
        # _debate_cultures back - otherwise the fire-and-forget task never
        # gets a turn before the read (P4a E8 Problem #2).
        self._pending_culture_tasks: dict[str, asyncio.Task[Any]] = {}

    def _is_km_handler_enabled(self, handler_name: str) -> bool:
        """Check whether a KM handler is enabled via feature flags (default on)."""
        if self._settings is None:
            return True
        try:
            integration = self._settings.integration
            return integration.is_km_handler_enabled(handler_name)
        except (AttributeError, TypeError):
            return True

    def _handle_memory_to_mound(self, event: "StreamEvent") -> None:
        """
        Memory stored → Knowledge Mound.

        Sync high-importance memories to Knowledge Mound for cross-debate access.
        Only syncs memories with importance ≥ 0.7 to avoid noise.
        """
        if not self._is_km_handler_enabled("memory_to_mound"):
            return

        data = event.data
        importance = data.get("importance", 0.0)
        content = data.get("content", "")
        tier = data.get("tier", "unknown")

        # Only sync significant memories
        if importance < 0.7:
            return

        logger.debug(
            "Syncing high-importance memory to KM: importance=%.2f, tier=%s", importance, tier
        )

        # Record KM inbound metric
        record_km_inbound_event("memory", event.type.value)

        try:
            from aragora.knowledge.mound import get_knowledge_mound

            # Get or create mound instance
            mound: KnowledgeMound | None = get_knowledge_mound()
            if mound is None:
                return

            # Use mound's store method directly since ContinuumAdapter
            # requires a ContinuumMemory instance that we don't have here.
            # The mound handles storage internally.
            from aragora.knowledge.mound.types import IngestionRequest, KnowledgeSource

            request = IngestionRequest(
                content=content,
                workspace_id=data.get("workspace_id", "default"),
                source_type=KnowledgeSource.CONTINUUM,
                confidence=importance,
                metadata=data.get("metadata", {}),
            )
            # Note: This is a sync handler, so we schedule the async store
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(mound.store(request))
            except RuntimeError:
                pass  # No event loop available
            logger.info("Synced memory to Knowledge Mound (importance=%.2f)", importance)

        except ImportError:
            pass  # KnowledgeMound not available
        except Exception as e:  # noqa: BLE001 - Intentional catch-all after specific exceptions
            logger.debug("Memory→KM sync failed: %s", e)

    def _handle_mound_to_memory_retrieval(self, event: "StreamEvent") -> None:
        """
        Knowledge Mound queried → Memory pre-warm.

        When KM is queried, check for related memories and pre-warm the cache.
        """
        if not self._is_km_handler_enabled("mound_to_memory"):
            return

        data = event.data
        query = data.get("query", "")
        results_count = data.get("results_count", 0)
        workspace_id = data.get("workspace_id", "")

        if not query or results_count == 0:
            return

        logger.debug("KM queried, pre-warming memory cache: query='%s...'", query[:50])

        # Record KM outbound metric
        record_km_outbound_event("memory", event.type.value)

        try:
            from aragora.memory import get_continuum_memory

            memory = get_continuum_memory()
            if memory and hasattr(memory, "prewarm_for_query"):
                memory.prewarm_for_query(query, workspace_id=workspace_id)
        except (ImportError, AttributeError):
            pass
        except Exception as e:  # noqa: BLE001 - Intentional catch-all after specific exceptions
            logger.debug("KM→Memory pre-warm failed: %s", e)

    def _handle_belief_to_mound(self, event: "StreamEvent") -> None:
        """
        Belief network converged → Knowledge Mound.

        Store high-confidence beliefs and cruxes in KM for cross-debate learning.
        """
        if not self._is_km_handler_enabled("belief_to_mound"):
            return

        data = event.data
        debate_id = data.get("debate_id", "")
        beliefs_count = data.get("beliefs_count", 0)
        cruxes = data.get("cruxes", [])

        logger.debug("Belief network converged: %s beliefs, %s cruxes", beliefs_count, len(cruxes))

        # Record KM inbound metric
        record_km_inbound_event("belief", event.type.value)

        try:
            from aragora.knowledge.mound.adapters.belief_adapter import BeliefAdapter

            adapter = BeliefAdapter()

            # Store converged beliefs
            for belief_data in data.get("beliefs", []):
                if belief_data.get("confidence", 0) >= 0.8:
                    adapter.store_converged_belief(
                        node=belief_data,
                        debate_id=debate_id,
                    )

            # Store cruxes
            for crux_data in cruxes:
                adapter.store_crux(
                    crux=crux_data,
                    debate_id=debate_id,
                    topics=crux_data.get("topics", []),
                )

            logger.info("Stored beliefs/cruxes from debate %s", debate_id)

        except ImportError:
            pass  # BeliefAdapter not available
        except Exception as e:  # noqa: BLE001 - Intentional catch-all after specific exceptions
            logger.debug("Belief→KM storage failed: %s", e)

    def _handle_mound_to_belief(self, event: "StreamEvent") -> None:
        """
        Debate start → Initialize belief priors from KM.

        Retrieve historical cruxes and beliefs to initialize priors for new debate.
        """
        if not self._is_km_handler_enabled("mound_to_belief"):
            return

        data = event.data
        debate_id = data.get("debate_id", "")
        question = data.get("question", "")

        if not question:
            return

        logger.debug("Initializing belief priors from KM for debate %s", debate_id)

        # Record KM outbound metric
        record_km_outbound_event("belief", event.type.value)

        try:
            from aragora.knowledge.mound.adapters.belief_adapter import BeliefAdapter

            adapter = BeliefAdapter()

            # Search for similar historical cruxes
            similar_cruxes = adapter.search_similar_cruxes(
                query=question,
                limit=10,
                min_score=0.3,
            )

            if similar_cruxes:
                logger.info(
                    "Found %s historical cruxes relevant to debate %s",
                    len(similar_cruxes),
                    debate_id,
                )
                # Store in event data for debate to pick up
                # (Actual initialization happens in debate orchestrator)

        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001 - Intentional catch-all after specific exceptions
            logger.debug("KM→Belief initialization failed: %s", e)

    def _handle_rlm_to_mound(self, event: "StreamEvent") -> None:
        """
        RLM compression complete → Knowledge Mound.

        Store compression patterns that worked well for future retrieval optimization.
        """
        if not self._is_km_handler_enabled("rlm_to_mound"):
            return

        data = event.data
        compression_ratio = data.get("compression_ratio", 0.0)
        value_score = data.get("value_score", 0.0)
        content_markers = data.get("content_markers", [])

        # Only store high-value compression patterns
        if value_score < 0.7:
            return

        logger.debug(
            "Storing RLM compression pattern: ratio=%.2f, value=%.2f",
            compression_ratio,
            value_score,
        )

        # Record KM inbound metric
        record_km_inbound_event("rlm", event.type.value)

        try:
            from aragora.knowledge.mound.adapters.rlm_adapter import RlmAdapter

            adapter = RlmAdapter()
            adapter.store_compression_pattern(
                compression_ratio=compression_ratio,
                value_score=value_score,
                content_markers=content_markers,
                metadata=data.get("metadata", {}),
            )

        except ImportError:
            pass  # RlmAdapter not available yet
        except Exception as e:  # noqa: BLE001 - Intentional catch-all after specific exceptions
            logger.debug("RLM→KM storage failed: %s", e)

    def _handle_mound_to_rlm(self, event: "StreamEvent") -> None:
        """
        Knowledge Mound queried → RLM priority update.

        Inform RLM about access patterns to optimize compression priorities.
        """
        if not self._is_km_handler_enabled("mound_to_rlm"):
            return

        data = event.data
        query = data.get("query", "")
        results_count = data.get("results_count", 0)
        node_ids = data.get("node_ids", [])

        if not node_ids:
            return

        logger.debug("Updating RLM priorities based on KM query: %s results", results_count)

        # Record KM outbound metric
        record_km_outbound_event("rlm", event.type.value)

        try:
            from aragora.rlm.compressor import HierarchicalCompressor

            # HierarchicalCompressor doesn't have a singleton getter,
            # and update_priority_hints is not a method on it.
            # This handler documents intent but RLM priority updates
            # would need to be implemented at a higher level.
            compressor: HierarchicalCompressor | None = None
            if compressor and hasattr(compressor, "update_priority_hints"):
                getattr(compressor, "update_priority_hints")(
                    accessed_ids=node_ids,
                    query=query,
                )
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001 - Intentional catch-all after specific exceptions
            logger.debug("KM→RLM priority update failed: %s", e)

    def _handle_elo_to_mound(self, event: "StreamEvent") -> None:
        """
        ELO updated → Knowledge Mound.

        Store agent expertise profiles for cross-debate team selection.
        Only stores significant ELO changes (|delta| > 25).
        """
        if not self._is_km_handler_enabled("elo_to_mound"):
            return

        data = event.data
        agent_name = data.get("agent", "")
        new_elo = data.get("elo", 1500)
        delta = data.get("delta", 0)
        debate_id = data.get("debate_id", "")
        domain = data.get("domain", "general")

        # Only store significant changes
        if abs(delta) < 25:
            return

        logger.debug(
            "Storing agent expertise: %s -> %s (Δ%+.0f) in %s", agent_name, new_elo, delta, domain
        )

        # Record KM inbound metric
        record_km_inbound_event("ranking", event.type.value)

        try:
            from aragora.knowledge.mound.adapters import RankingAdapter

            # RankingAdapter is an alias for PerformanceAdapter which implements
            # all abstract methods via mixins; the type checker cannot verify this.
            adapter = cast(Any, RankingAdapter)()
            adapter.store_agent_expertise(
                agent_name=agent_name,
                domain=domain,
                elo=new_elo,
                delta=delta,
                debate_id=debate_id,
            )

        except ImportError:
            pass  # RankingAdapter not available yet
        except Exception as e:  # noqa: BLE001 - Intentional catch-all after specific exceptions
            logger.debug("ELO→KM storage failed: %s", e)

    def _handle_mound_to_team_selection(self, event: "StreamEvent") -> None:
        """
        Debate start → Query KM for domain experts.

        Retrieve agent expertise profiles to inform team selection.
        """
        if not self._is_km_handler_enabled("mound_to_team"):
            return

        data = event.data
        debate_id = data.get("debate_id", "")
        question = data.get("question", "")

        if not question:
            return

        logger.debug("Querying KM for domain experts for debate %s", debate_id)

        # Record KM outbound metric
        record_km_outbound_event("team_selection", event.type.value)

        try:
            from aragora.knowledge.mound.adapters import RankingAdapter

            # RankingAdapter is an alias for PerformanceAdapter which implements
            # all abstract methods via mixins; the type checker cannot verify this.
            adapter = cast(Any, RankingAdapter)()
            # Detect domain from question
            domain = adapter.detect_domain(question)
            experts = adapter.get_domain_experts(domain=domain, limit=10)

            if experts:
                logger.info("Found %s domain experts for '%s'", len(experts), domain)

        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001 - Intentional catch-all after specific exceptions
            logger.debug("KM→Team selection query failed: %s", e)

    def _handle_insight_to_mound(self, event: "StreamEvent") -> None:
        """
        Insight extracted → Knowledge Mound.

        Store high-confidence insights (≥0.7) for organizational learning.
        """
        if not self._is_km_handler_enabled("insight_to_mound"):
            return

        data = event.data
        confidence = data.get("confidence", 0.0)
        insight_type = data.get("type", "")
        data.get("debate_id", "")

        # Only store high-confidence insights
        if confidence < 0.7:
            return

        logger.debug("Storing insight: type=%s, confidence=%.2f", insight_type, confidence)

        # Record KM inbound metric
        record_km_inbound_event("insights", event.type.value)

        try:
            from aragora.knowledge.mound.adapters.insights_adapter import InsightsAdapter

            adapter = InsightsAdapter()
            # InsightsAdapter.store_insight expects an Insight object.
            # Since we have event.data as a dict, we store it via the
            # adapter's in-memory storage directly for insight-like data.
            insight_data: dict[str, Any] = {
                "id": data.get("id", ""),
                "type": data.get("type", ""),
                "title": data.get("title", ""),
                "description": data.get("description", ""),
                "confidence": data.get("confidence", 0.0),
                "debate_id": data.get("debate_id", ""),
                "agents_involved": data.get("agents_involved", []),
                "evidence": data.get("evidence", []),
                "created_at": data.get("created_at", ""),
                "metadata": data.get("metadata", {}),
            }
            # Store directly in adapter's internal storage
            insight_id = f"{adapter.INSIGHT_PREFIX}{insight_data.get('id', '')}"
            adapter._insights[insight_id] = insight_data

        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001 - Intentional catch-all after specific exceptions
            logger.debug("Insight→KM storage failed: %s", e)

    def _handle_flip_to_mound(self, event: "StreamEvent") -> None:
        """
        Flip detected → Knowledge Mound.

        Store ALL flip events for meta-learning and consistency tracking.
        """
        if not self._is_km_handler_enabled("flip_to_mound"):
            return

        data = event.data
        agent_name = data.get("agent_name", "")
        flip_type = data.get("flip_type", "")

        logger.debug("Storing flip event: agent=%s, type=%s", agent_name, flip_type)

        # Record KM inbound metric
        record_km_inbound_event("trickster", event.type.value)

        try:
            from aragora.knowledge.mound.adapters.insights_adapter import InsightsAdapter

            adapter = InsightsAdapter()
            # InsightsAdapter.store_flip expects a FlipEvent object.
            # Since we have event.data as a dict, we store it directly
            # in the adapter's in-memory storage for flip-like data.
            flip_data: dict[str, Any] = {
                "id": f"{adapter.FLIP_PREFIX}{data.get('id', '')}",
                "original_id": data.get("id", ""),
                "agent_name": data.get("agent_name", ""),
                "original_claim": data.get("original_claim", ""),
                "new_claim": data.get("new_claim", ""),
                "original_confidence": data.get("original_confidence", 0.0),
                "new_confidence": data.get("new_confidence", 0.0),
                "original_debate_id": data.get("original_debate_id", ""),
                "new_debate_id": data.get("new_debate_id", ""),
                "original_position_id": data.get("original_position_id", ""),
                "new_position_id": data.get("new_position_id", ""),
                "similarity_score": data.get("similarity_score", 0.0),
                "flip_type": data.get("flip_type", ""),
                "domain": data.get("domain", ""),
                "detected_at": data.get("detected_at", ""),
            }
            flip_id = flip_data["id"]
            adapter._flips[flip_id] = flip_data

            # Update indices
            agent_name = data.get("agent_name", "")
            if agent_name:
                if agent_name not in adapter._agent_flips:
                    adapter._agent_flips[agent_name] = []
                adapter._agent_flips[agent_name].append(flip_id)

            domain = data.get("domain")
            if domain:
                if domain not in adapter._domain_flips:
                    adapter._domain_flips[domain] = []
                adapter._domain_flips[domain].append(flip_id)

        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001 - Intentional catch-all after specific exceptions
            logger.debug("Flip→KM storage failed: %s", e)

    def _handle_mound_to_trickster(self, event: "StreamEvent") -> None:
        """
        Debate start → Query KM for flip history.

        Retrieve agent flip history for consistency prediction.
        """
        if not self._is_km_handler_enabled("mound_to_trickster"):
            return

        data = event.data
        data.get("debate_id", "")
        agents = data.get("agents", [])

        if not agents:
            return

        logger.debug("Querying KM for flip history: %s agents", len(agents))

        # Record KM outbound metric
        record_km_outbound_event("trickster", event.type.value)

        try:
            from aragora.knowledge.mound.adapters.insights_adapter import InsightsAdapter

            adapter = InsightsAdapter()

            for agent_name in agents:
                flip_history = adapter.get_agent_flip_history(
                    agent_name=agent_name,
                    limit=20,
                )
                if flip_history:
                    logger.debug("Found %s historical flips for %s", len(flip_history), agent_name)

        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001 - Intentional catch-all after specific exceptions
            logger.debug("KM→Trickster query failed: %s", e)

    # ------------------------------------------------------------------
    # Consensus / provenance / validation reactions (relocated from
    # events.cross_subscribers.handlers.validation, P4a Batch E2b).
    # ------------------------------------------------------------------
    def _handle_provenance_to_mound(self, event: "StreamEvent") -> None:
        """
        Consensus reached → Store verified provenance chains.

        After debate consensus, store verified provenance chains in KM.
        """
        if not self._is_km_handler_enabled("provenance_to_mound"):
            return

        data = event.data
        debate_id = data.get("debate_id", "")
        consensus_reached = data.get("consensus_reached", False)

        if not consensus_reached:
            return

        logger.debug("Storing provenance chains from consensus in debate %s", debate_id)

        # Record KM inbound metric
        record_km_inbound_event("provenance", event.type.value)

        try:
            from aragora.knowledge.mound.adapters.belief_adapter import BeliefAdapter

            adapter = BeliefAdapter()

            # Store verified provenance chains
            chains = data.get("provenance_chains", [])
            for chain in chains:
                if chain.get("verified", False):
                    adapter.store_provenance(
                        chain_id=chain.get("id", ""),
                        source_id=chain.get("source_id", ""),
                        claim_ids=chain.get("claim_ids", []),
                        verified=True,
                        verification_method=chain.get("method", "consensus"),
                        debate_id=debate_id,
                    )

        except ImportError:
            pass
        except (RuntimeError, TypeError, AttributeError, ValueError, OSError) as e:
            logger.debug("Provenance→KM storage failed: %s", e)

    def _handle_mound_to_provenance(self, event: "StreamEvent") -> None:
        """
        Claim verification → Query KM for verification history.

        When verifying claims, check KM for related verified chains.
        """
        if not self._is_km_handler_enabled("mound_to_provenance"):
            return

        data = event.data
        claim_id = data.get("claim_id", "")
        claim_text = data.get("claim", "")

        if not claim_text:
            return

        logger.debug("Querying KM for verification history: claim %s", claim_id)

        # Record KM outbound metric
        record_km_outbound_event("provenance", event.type.value)

        try:
            from aragora.knowledge.mound.adapters.belief_adapter import BeliefAdapter

            adapter = BeliefAdapter()

            # Search for related verified claims
            related = adapter.search_similar_cruxes(
                query=claim_text,
                limit=5,
            )

            if related:
                logger.debug("Found %s related verified claims", len(related))

        except ImportError:
            pass
        except (RuntimeError, TypeError, AttributeError, ValueError, OSError) as e:
            logger.debug("KM→Provenance query failed: %s", e)

    def _handle_consensus_to_mound(self, event: "StreamEvent") -> None:
        """
        Consensus reached → Ingest consensus content to Knowledge Mound.

        After debate consensus, store the consensus conclusion, key claims,
        and dissenting views as knowledge nodes for organizational learning.

        Enhanced features:
        - Dissent tracking: Store dissenting views as separate nodes linked to consensus
        - Evolution tracking: Detect similar prior consensus and create supersedes links
        - Linking: Connect consensus to claims, evidence, and related knowledge
        """
        if not self._is_km_handler_enabled("consensus_to_mound"):
            return

        data = event.data
        debate_id = data.get("debate_id", "")
        consensus_reached = data.get("consensus_reached", False)

        if not consensus_reached:
            return

        topic = data.get("topic", "")
        conclusion = data.get("conclusion", "")
        confidence = data.get("confidence", 0.5)
        strength = data.get("strength", "moderate")
        key_claims = data.get("key_claims", [])
        supporting_evidence = data.get("supporting_evidence", [])
        domain = data.get("domain", "general")
        tags = data.get("tags", [])

        # Dissent data
        dissents = data.get("dissents", [])
        dissenting_agents = data.get("dissenting_agents", [])
        _dissent_ids = data.get("dissent_ids", [])  # Preserved for future linking

        # Evolution data
        supersedes = data.get("supersedes", None)
        agreeing_agents = data.get("agreeing_agents", [])
        participating_agents = data.get("participating_agents", [])

        if not topic and not conclusion:
            return

        logger.info(
            "Ingesting consensus from debate %s to Knowledge Mound (dissents=%s, evolution=%s)",
            debate_id,
            len(dissents),
            supersedes is not None,
        )

        # Record KM inbound metric
        record_km_inbound_event("consensus", event.type.value)

        try:
            from aragora.knowledge.mound import get_knowledge_mound
            from aragora.knowledge.mound.types import IngestionRequest, KnowledgeSource

            mound = get_knowledge_mound()
            if not mound:
                logger.debug("Knowledge Mound not available for consensus ingestion")
                return

            # Check if mound is initialized
            if not mound.is_initialized:
                logger.debug("Knowledge Mound not initialized, skipping consensus ingestion")
                return

            # Build content from topic and conclusion
            content = f"{topic}: {conclusion}" if conclusion else topic

            # Map strength to tier
            strength_to_tier = {
                "unanimous": "glacial",  # Highly stable
                "strong": "slow",
                "moderate": "slow",
                "weak": "medium",
                "split": "medium",
                "contested": "fast",  # May change
            }
            tier = strength_to_tier.get(strength, "slow")

            # Calculate agreement ratio
            agreement_ratio = (
                len(agreeing_agents) / len(participating_agents) if participating_agents else 0.0
            )

            import asyncio

            # Type check for the mound after null check
            if mound is None:
                raise RuntimeError(
                    "KnowledgeMound not initialized - verified above with `if not mound: return`"
                )

            async def ingest_consensus_with_enhancements(
                km: "KnowledgeMound",
            ) -> None:
                # ============================================================
                # EVOLUTION TRACKING: Check for similar prior consensus
                # ============================================================
                supersedes_node_id: str | None = None
                if supersedes:
                    # Direct supersedes reference provided
                    supersedes_node_id = f"cs_{supersedes}"
                else:
                    # Search for similar prior consensus on same topic
                    try:
                        # Use query_semantic for similarity-based search
                        similar_results = await km.query_semantic(
                            text=topic,
                            limit=3,
                            min_confidence=0.85,  # High threshold for "same topic"
                        )
                        # Filter to consensus node types
                        consensus_results = [
                            r
                            for r in similar_results
                            if (r.metadata or {}).get("node_type") == "consensus"
                        ]
                        if consensus_results:
                            # Found similar prior consensus - this new one supersedes it
                            prior = consensus_results[0]
                            prior_debate_id = (prior.metadata or {}).get("debate_id", "")
                            if prior_debate_id != debate_id:
                                supersedes_node_id = prior.id
                                logger.info(
                                    "Consensus %s supersedes prior consensus %s on topic '%s...'",
                                    debate_id,
                                    prior_debate_id,
                                    topic[:50],
                                )
                    except (RuntimeError, TypeError, AttributeError, ValueError, OSError) as e:
                        logger.debug("Evolution tracking search failed: %s", e)

                # ============================================================
                # MAIN CONSENSUS INGESTION
                # ============================================================
                # Build metadata dict with supersedes info included
                consensus_metadata: dict[str, Any] = {
                    "debate_id": debate_id,
                    "strength": strength,
                    "topic": topic,
                    "conclusion": conclusion,
                    "domain": domain,
                    "tags": tags,
                    "key_claims_count": len(key_claims),
                    "dissent_count": len(dissents),
                    "agreement_ratio": agreement_ratio,
                    "agreeing_agents": agreeing_agents,
                    "dissenting_agents": dissenting_agents,
                    "participating_agents": participating_agents,
                    "has_dissent": len(dissents) > 0 or len(dissenting_agents) > 0,
                    "ingested_at": datetime.now().isoformat(),
                }
                # Store supersedes relationship in metadata for tracking
                if supersedes_node_id:
                    consensus_metadata["supersedes"] = supersedes_node_id

                request = IngestionRequest(
                    content=content,
                    workspace_id=km.workspace_id,
                    source_type=KnowledgeSource.CONSENSUS,
                    debate_id=debate_id,
                    node_type="consensus",
                    confidence=confidence,
                    tier=tier,
                    metadata=consensus_metadata,
                )

                result = await km.store(request)
                consensus_node_id = result.node_id

                logger.debug(
                    "Ingested consensus %s: node_id=%s, deduplicated=%s, supersedes=%s",
                    debate_id,
                    consensus_node_id,
                    result.deduplicated,
                    supersedes_node_id,
                )

                # ============================================================
                # DISSENT TRACKING: Store dissenting views
                # ============================================================
                dissent_node_ids = []
                for i, dissent in enumerate(dissents[:10]):  # Limit to 10 dissents
                    if isinstance(dissent, dict):
                        dissent_content = dissent.get("content", "")
                        dissent_type = dissent.get(
                            "type", dissent.get("dissent_type", "alternative_approach")
                        )
                        dissent_agent = dissent.get("agent_id", dissent.get("agent", "unknown"))
                        dissent_reasoning = dissent.get("reasoning", "")
                        dissent_confidence = dissent.get("confidence", 0.5)
                        acknowledged = dissent.get("acknowledged", False)
                        rebuttal = dissent.get("rebuttal", "")
                    elif isinstance(dissent, str):
                        dissent_content = dissent
                        dissent_type = "alternative_approach"
                        dissent_agent = (
                            dissenting_agents[i] if i < len(dissenting_agents) else "unknown"
                        )
                        dissent_reasoning = ""
                        dissent_confidence = 0.5
                        acknowledged = False
                        rebuttal = ""
                    else:
                        continue

                    if not dissent_content.strip():
                        continue

                    # Determine dissent importance based on type
                    dissent_importance = 0.5
                    if dissent_type == "risk_warning":
                        dissent_importance = 0.7  # Risk warnings are valuable
                    elif dissent_type == "fundamental_disagreement":
                        dissent_importance = 0.6  # Strong dissent worth preserving
                    elif dissent_type == "edge_case_concern":
                        dissent_importance = 0.55  # Edge cases inform future debates

                    dissent_request = IngestionRequest(
                        content=f"[DISSENT from {dissent_agent}] {dissent_content}",
                        workspace_id=km.workspace_id,
                        source_type=KnowledgeSource.CONSENSUS,
                        debate_id=debate_id,
                        node_type="dissent",
                        confidence=dissent_confidence,
                        tier="medium",  # Dissents may be reconsidered
                        derived_from=[consensus_node_id] if consensus_node_id else [],
                        metadata={
                            "debate_id": debate_id,
                            "dissent_type": dissent_type,
                            "agent_id": dissent_agent,
                            "reasoning": dissent_reasoning,
                            "acknowledged": acknowledged,
                            "rebuttal": rebuttal,
                            "parent_consensus_id": consensus_node_id,
                            "dissent_index": i,
                            "topic": topic,
                            "is_risk_warning": dissent_type == "risk_warning",
                            "importance": dissent_importance,
                        },
                    )

                    dissent_result = await km.store(dissent_request)
                    if dissent_result.node_id:
                        dissent_node_ids.append(dissent_result.node_id)
                        logger.debug(
                            "Stored dissent from %s: type=%s, node_id=%s",
                            dissent_agent,
                            dissent_type,
                            dissent_result.node_id,
                        )

                if dissent_node_ids:
                    logger.info(
                        "Stored %s dissenting views for consensus %s",
                        len(dissent_node_ids),
                        debate_id,
                    )

                # ============================================================
                # CLAIM LINKING: Store key claims linked to consensus
                # ============================================================
                claim_node_ids = []
                for i, claim in enumerate(key_claims[:10]):  # Limit to 10 claims
                    if isinstance(claim, str) and claim.strip():
                        claim_request = IngestionRequest(
                            content=claim,
                            workspace_id=km.workspace_id,
                            source_type=KnowledgeSource.CONSENSUS,
                            debate_id=debate_id,
                            node_type="claim",
                            confidence=confidence * 0.9,  # Slightly lower than main consensus
                            tier=tier,
                            derived_from=[consensus_node_id] if consensus_node_id else [],
                            metadata={
                                "debate_id": debate_id,
                                "claim_index": i,
                                "parent_consensus_id": consensus_node_id,
                                "domain": domain,
                            },
                        )
                        claim_result = await km.store(claim_request)
                        if claim_result.node_id:
                            claim_node_ids.append(claim_result.node_id)

                # ============================================================
                # EVIDENCE LINKING: Store supporting evidence references
                # ============================================================
                for i, evidence in enumerate(supporting_evidence[:5]):  # Limit evidence
                    if isinstance(evidence, str) and evidence.strip():
                        evidence_request = IngestionRequest(
                            content=evidence,
                            workspace_id=km.workspace_id,
                            source_type=KnowledgeSource.CONSENSUS,
                            debate_id=debate_id,
                            node_type="evidence",
                            confidence=confidence * 0.85,
                            tier=tier,
                            derived_from=[consensus_node_id] if consensus_node_id else [],
                            metadata={
                                "debate_id": debate_id,
                                "evidence_index": i,
                                "parent_consensus_id": consensus_node_id,
                                "supports_conclusion": True,
                            },
                        )
                        await km.store(evidence_request)

                # ============================================================
                # UPDATE SUPERSEDED NODE (if applicable)
                # ============================================================
                if supersedes_node_id and hasattr(km, "update"):
                    try:
                        await km.update(
                            node_id=supersedes_node_id,
                            updates={"metadata": {"superseded_by": consensus_node_id}},
                        )
                        logger.debug(
                            "Marked %s as superseded by %s", supersedes_node_id, consensus_node_id
                        )
                    except (RuntimeError, TypeError, AttributeError, ValueError, OSError) as e:
                        logger.debug("Failed to update superseded node: %s", e)

                # Log summary
                logger.info(
                    "Consensus ingestion complete for debate %s: "
                    "consensus=%s, claims=%s, "
                    "dissents=%s, "
                    "supersedes=%s",
                    debate_id,
                    consensus_node_id,
                    len(claim_node_ids),
                    len(dissent_node_ids),
                    "yes" if supersedes_node_id else "no",
                )

            # Run async ingestion
            try:
                asyncio.get_running_loop()
                task = asyncio.create_task(ingest_consensus_with_enhancements(mound))
                task.add_done_callback(
                    lambda t: logger.warning(
                        "Consensus→KM async ingestion failed: %s", t.exception()
                    )
                    if not t.cancelled() and t.exception()
                    else None
                )
            except RuntimeError:
                # No event loop, create one
                asyncio.run(ingest_consensus_with_enhancements(mound))

        except ImportError as e:
            logger.debug("Consensus→KM ingestion import failed: %s", e)
        except (RuntimeError, TypeError, AttributeError, ValueError, OSError, KeyError) as e:
            logger.warning("Consensus→KM ingestion failed: %s", e)

    def _handle_km_validation_feedback(self, event: "StreamEvent") -> None:
        """
        KM Validation Feedback: Improve source system quality based on debate outcomes.

        When consensus is reached, this handler:
        1. Queries KM for items that may have contributed to the debate
        2. For items from ContinuumMemory or ConsensusMemory that match the topic:
           - If consensus was reached with high confidence → positive validation
           - If consensus contradicts prior knowledge → negative validation
        3. Feeds validation back to source adapters to improve quality scores

        This creates a learning loop where KM data that proves useful in debates
        gets promoted (higher tiers, higher importance), while contradicted data
        gets demoted or flagged for review.
        """
        if not self._is_km_handler_enabled("km_validation_feedback"):
            return

        data = event.data
        debate_id = data.get("debate_id", "")
        consensus_reached = data.get("consensus_reached", False)
        confidence = data.get("confidence", 0.5)
        topic = data.get("topic", "")

        # Only process debates with clear outcomes
        if not consensus_reached or confidence < 0.5 or not topic:
            return

        logger.debug(
            "Processing KM validation feedback for debate %s: confidence=%.2f, topic=%s...",
            debate_id,
            confidence,
            topic[:50],
        )

        try:
            import asyncio

            from aragora.knowledge.mound import get_knowledge_mound
            from aragora.knowledge.mound.adapters.continuum_adapter import (
                ContinuumAdapter,
                KMValidationResult,
            )
            from aragora.knowledge.mound.adapters.consensus_adapter import (  # noqa: F401
                ConsensusAdapter,
            )

            mound = get_knowledge_mound()
            if not mound:
                logger.debug("Knowledge Mound not available for validation feedback")
                return

            # Check if mound is initialized
            if not mound.is_initialized:
                logger.debug("Knowledge Mound not initialized, skipping validation feedback")
                return

            async def process_validation_feedback():
                # Query KM for items that may have contributed to this debate
                try:
                    # Search for related knowledge by topic
                    results = await mound.search(
                        query=topic,
                        limit=20,
                        min_score=0.6,  # Moderate threshold for potential contributors
                    )

                    if not results:
                        logger.debug("No KM items found for validation feedback: %s", topic[:50])
                        return

                    continuum_validations = 0
                    consensus_validations = 0

                    for result in results:
                        node_id = (
                            result.node_id
                            if hasattr(result, "node_id")
                            else result.get("node_id", "")
                        )
                        score = (
                            result.score if hasattr(result, "score") else result.get("score", 0.0)
                        )
                        source = (
                            result.source if hasattr(result, "source") else result.get("source", "")
                        )

                        # Determine validation recommendation based on outcome
                        # High confidence + high similarity = item was useful
                        cross_debate_utility = score * confidence

                        if confidence >= 0.8 and score >= 0.7:
                            recommendation = "promote"
                        elif confidence >= 0.6 and score >= 0.5:
                            recommendation = "keep"
                        elif confidence < 0.5:
                            recommendation = "review"
                        else:
                            recommendation = "keep"

                        # Create validation result
                        validation = KMValidationResult(
                            memory_id=node_id,
                            km_confidence=confidence,
                            cross_debate_utility=cross_debate_utility,
                            validation_count=1,
                            was_supported=consensus_reached and confidence >= 0.7,
                            was_contradicted=False,  # Would need contradiction detection
                            recommendation=recommendation,
                            metadata={
                                "debate_id": debate_id,
                                "topic": topic[:100],
                                "similarity_score": score,
                                "source_type": source,
                            },
                        )

                        # Route validation to appropriate adapter
                        if node_id.startswith("cm_"):
                            # ContinuumMemory item
                            try:
                                from aragora.memory.continuum import get_continuum_memory

                                continuum = get_continuum_memory()
                                if continuum and hasattr(continuum, "_km_adapter"):
                                    adapter = continuum._km_adapter
                                    if adapter and isinstance(adapter, ContinuumAdapter):
                                        updated = await adapter.update_continuum_from_km(
                                            memory_id=node_id,
                                            km_validation=validation,
                                        )
                                        if updated:
                                            continuum_validations += 1
                            except ImportError:
                                pass
                            except (
                                RuntimeError,
                                TypeError,
                                AttributeError,
                                ValueError,
                                OSError,
                            ) as e:
                                logger.debug("Continuum validation failed: %s", e)

                        elif node_id.startswith("cs_"):
                            # Consensus item - track but consensus records are immutable
                            # Instead, update the confidence tracking for the adapter
                            consensus_validations += 1

                    if continuum_validations > 0 or consensus_validations > 0:
                        logger.info(
                            "KM validation feedback for debate %s: continuum=%s, consensus=%s",
                            debate_id,
                            continuum_validations,
                            consensus_validations,
                        )

                        # Emit validation event for dashboard
                        try:
                            from aragora.events.types import (
                                StreamEvent,
                                StreamEventType,
                            )

                            validation_event = StreamEvent(
                                type=StreamEventType.KM_ADAPTER_VALIDATION,
                                data={
                                    "debate_id": debate_id,
                                    "topic_preview": topic[:50],
                                    "confidence": confidence,
                                    "continuum_validations": continuum_validations,
                                    "consensus_validations": consensus_validations,
                                    "total_items_reviewed": len(results),
                                },
                            )
                            # Don't dispatch to avoid recursion - just log for now
                            logger.debug("Validation event: %s", validation_event.data)
                        except (ImportError, TypeError, AttributeError, ValueError) as e:
                            logger.debug("Failed to create validation event: %s", e)

                except (RuntimeError, TypeError, AttributeError, ValueError, OSError) as e:
                    logger.warning("KM validation feedback query failed: %s", e)

            # Run async validation
            try:
                asyncio.get_running_loop()
                task = asyncio.create_task(process_validation_feedback())
                task.add_done_callback(
                    lambda t: logger.warning(
                        "KM validation feedback processing failed: %s", t.exception()
                    )
                    if not t.cancelled() and t.exception()
                    else None
                )
            except RuntimeError:
                asyncio.run(process_validation_feedback())

        except ImportError as e:
            logger.debug("KM validation feedback import failed: %s", e)
        except (RuntimeError, TypeError, AttributeError, ValueError, OSError) as e:
            logger.warning("KM validation feedback failed: %s", e)

    # ------------------------------------------------------------------
    # Culture / debate-outcome / workflow / tier / approval reactions
    # (relocated from events.cross_subscribers.handlers.{basic,culture,
    # strategic}, P4a Batch E2c). Each mixin's other-domain reactions stay
    # in place there for E3-E6 to relocate to their own domain homes.
    # ------------------------------------------------------------------
    def _handle_mound_to_culture(self, event: "StreamEvent") -> None:
        """
        Debate start → Load culture patterns from KM.

        Retrieve relevant culture patterns when a debate starts to inform
        protocol selection and agent behavior. Patterns include:
        - Decision style preferences (consensus vs majority)
        - Risk tolerance (conservative vs aggressive)
        - Domain expertise distribution
        - Debate dynamics (rounds to consensus, critique patterns)
        """
        if not self._is_km_handler_enabled("mound_to_culture"):
            return

        data = event.data
        debate_id = data.get("debate_id", "")
        domain = data.get("domain", "")
        data.get("protocol", {})

        logger.debug("Loading culture patterns for debate %s, domain=%s", debate_id, domain)

        # Record KM outbound metric
        record_km_outbound_event("culture", event.type.value)

        try:
            from aragora.knowledge.mound import get_knowledge_mound

            mound = get_knowledge_mound()
            if not mound:
                logger.debug("Knowledge Mound not available for culture retrieval")
                return

            # Check if mound is initialized
            if not mound.is_initialized:
                logger.debug("Knowledge Mound not initialized, skipping culture retrieval")
                return

            # Retrieve culture profile from mound
            import asyncio

            async def retrieve_culture():
                if hasattr(mound, "get_culture_profile"):
                    profile = await mound.get_culture_profile()
                    return profile
                return None

            def _on_culture_retrieved(task: "asyncio.Task[Any]") -> None:
                self._pending_culture_tasks.pop(debate_id, None)
                if task.cancelled():
                    return
                exc = task.exception()
                if exc is not None:
                    logger.warning("Culture profile retrieval failed: %s", exc)
                    return
                profile = task.result()
                if profile:
                    self._store_debate_culture(debate_id, profile, domain)

            # Run async retrieval
            try:
                asyncio.get_running_loop()
                task = asyncio.create_task(retrieve_culture())
                # Stashed so a caller (ArenaKnowledgeManager.init_context) can
                # await this specific task before reading culture hints back;
                # see get_pending_culture_task.
                self._pending_culture_tasks[debate_id] = task
                task.add_done_callback(_on_culture_retrieved)
            except RuntimeError:
                profile = asyncio.run(retrieve_culture())
                if profile:
                    self._store_debate_culture(debate_id, profile, domain)

        except ImportError as e:
            logger.debug("Culture retrieval import failed: %s", e)
        except (RuntimeError, TypeError, AttributeError, ValueError, OSError) as e:
            logger.debug("Culture→Debate retrieval failed: %s", e)

    def _store_debate_culture(
        self,
        debate_id: str,
        profile: Any,
        domain: str,
    ) -> None:
        """Store culture profile for a debate to inform protocol behavior.

        Args:
            debate_id: Debate identifier
            profile: CultureProfile from Knowledge Mound
            domain: Detected debate domain
        """
        try:
            # Extract relevant protocol hints from culture
            protocol_hints = {}

            if hasattr(profile, "dominant_pattern"):
                dominant = profile.dominant_pattern
                if dominant:
                    # Map decision style to protocol recommendations
                    if hasattr(dominant, "pattern_type"):
                        if str(dominant.pattern_type) == "decision_style":
                            protocol_hints["recommended_consensus"] = dominant.value

                    # Map risk tolerance to critique depth
                    if hasattr(dominant, "pattern_type"):
                        if str(dominant.pattern_type) == "risk_tolerance":
                            if dominant.value == "conservative":
                                protocol_hints["extra_critique_rounds"] = 1
                            elif dominant.value == "aggressive":
                                protocol_hints["early_consensus_threshold"] = 0.7

            # Extract domain-specific patterns
            if hasattr(profile, "patterns"):
                domain_patterns = [
                    p for p in profile.patterns if hasattr(p, "domain") and p.domain == domain
                ]
                if domain_patterns:
                    protocol_hints["domain_patterns"] = [
                        {
                            "type": str(p.pattern_type),
                            "value": p.value,
                            "confidence": p.confidence,
                        }
                        for p in domain_patterns
                    ]

            self._debate_cultures[debate_id] = {
                "profile": profile,
                "protocol_hints": protocol_hints,
                "domain": domain,
            }

            logger.info(
                "Stored culture context for debate %s: %s hints", debate_id, len(protocol_hints)
            )

        except (TypeError, AttributeError, ValueError, KeyError) as e:
            logger.debug("Failed to store debate culture: %s", e)

    def get_debate_culture_hints(self, debate_id: str) -> dict:
        """Get protocol hints from culture for a debate.

        Args:
            debate_id: Debate identifier

        Returns:
            Dict of protocol hints derived from organizational culture
        """
        culture_ctx = self._debate_cultures.get(debate_id, {})
        return culture_ctx.get("protocol_hints", {})

    def get_pending_culture_task(self, debate_id: str) -> "asyncio.Task[Any] | None":
        """Return and clear the in-flight culture-profile retrieval task for ``debate_id``.

        ``_handle_mound_to_culture`` schedules retrieval as a fire-and-forget
        task (it runs inside a synchronous event-dispatch call, so it cannot
        be awaited there). A caller that needs fresh hints - rather than
        whatever ``get_debate_culture_hints`` happens to already have stored -
        should await the returned task first. Pops rather than peeks so a
        retried debate-context init sees ``None`` instead of re-awaiting an
        already-consumed task.

        Args:
            debate_id: Debate identifier

        Returns:
            The pending retrieval task, or ``None`` if none was scheduled
            (no Knowledge Mound, culture handler disabled, or already
            consumed/completed).
        """
        return self._pending_culture_tasks.pop(debate_id, None)

    def _handle_debate_outcome_to_knowledge(self, event: "StreamEvent") -> None:
        """Debate end → Knowledge Mound outcome persistence.

        When a debate ends, persist the outcome (winning position,
        key arguments, consensus strength) into the Knowledge Mound
        for future debate context enrichment.
        """
        data = event.data
        debate_id = data.get("debate_id", "")
        consensus = data.get("consensus_reached", False)
        confidence = data.get("confidence", 0.0)
        task = data.get("task", "")

        if not consensus or confidence < 0.6:
            return  # Only persist high-confidence outcomes

        try:
            from aragora.knowledge.mound import get_knowledge_mound

            mound = get_knowledge_mound()
            if mound is None:
                return

            outcome_content = {
                "debate_id": debate_id,
                "task": task[:500] if task else "",
                "consensus_reached": consensus,
                "confidence": confidence,
                "winning_position": data.get("winning_position", ""),
                "key_arguments": data.get("key_arguments", [])[:10],
            }

            import asyncio

            item = {
                "content": str(outcome_content),
                "source": f"debate:{debate_id}",
                "node_type": "debate_outcome",
                "metadata": outcome_content,
            }
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(mound.ingest(item))
            except RuntimeError:
                asyncio.run(mound.ingest(item))
            logger.debug("Persisted debate outcome to KM: %s", debate_id)
        except ImportError:
            pass  # Knowledge Mound not available
        except (RuntimeError, TypeError, AttributeError, ValueError, OSError) as e:
            logger.debug("KM outcome persistence failed: %s", e)

    def _handle_workflow_outcome_to_supermemory(self, event: "StreamEvent") -> None:
        """Workflow completion/failure → Supermemory persistence.

        When a workflow completes or fails, store the outcome in supermemory
        for cross-workflow learning. This creates institutional memory of
        what worked and what didn't, enabling future workflows to benefit
        from past experience.
        """
        data = event.data
        workflow_id = data.get("workflow_id", "")
        definition_id = data.get("definition_id", "")
        success = data.get("success", False)

        if not workflow_id:
            return

        logger.info(
            "Storing workflow outcome in supermemory: workflow=%s success=%s",
            workflow_id,
            success,
        )

        try:
            from aragora.knowledge.mound import get_knowledge_mound

            mound = get_knowledge_mound()
            if mound is None:
                return

            outcome = {
                "workflow_id": workflow_id,
                "definition_id": definition_id,
                "success": success,
                "duration_ms": data.get("duration_ms", 0),
                "steps_executed": data.get("steps_executed", 0),
                "error": data.get("error", ""),
            }

            status = "completed successfully" if success else "failed"
            content = (
                f"Workflow {definition_id or workflow_id} {status}. "
                f"Steps: {outcome['steps_executed']}, "
                f"Duration: {outcome['duration_ms']}ms"
            )
            if not success and outcome["error"]:
                content += f". Error: {outcome['error'][:200]}"

            import asyncio

            wf_item = {
                "content": content,
                "source": f"workflow:{workflow_id}",
                "node_type": "workflow_outcome",
                "metadata": outcome,
            }
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(mound.ingest(wf_item))
            except RuntimeError:
                asyncio.run(mound.ingest(wf_item))
            logger.debug("Workflow outcome stored in KM: %s", workflow_id)
        except ImportError:
            pass  # Knowledge Mound not available
        except (RuntimeError, TypeError, AttributeError, ValueError, OSError) as e:
            logger.debug("KM workflow storage failed: %s", e)

    def _handle_tier_demotion_to_revalidation(self, event: "StreamEvent") -> None:
        """Memory tier demotion → Re-validation trigger.

        When a memory entry is demoted to slow or glacial tier, trigger
        re-validation to ensure the content is still accurate before
        it becomes harder to access. This prevents stale or incorrect
        knowledge from persisting in lower tiers without review.
        """
        data = event.data
        memory_id = data.get("memory_id", "")
        to_tier = data.get("to_tier", "")
        from_tier = data.get("from_tier", "")

        if not memory_id:
            return

        # Only re-validate on demotion to slow or glacial tiers
        if to_tier not in ("slow", "glacial"):
            return

        logger.info(
            "Tier demotion re-validation: memory=%s from=%s to=%s",
            memory_id,
            from_tier,
            to_tier,
        )

        try:
            from aragora.knowledge.mound import get_knowledge_mound

            mound = get_knowledge_mound()
            if mound is None:
                return

            # Mark for re-validation in KM
            if hasattr(mound, "mark_for_revalidation"):
                mound.mark_for_revalidation(
                    source=f"continuum:{memory_id}",
                    reason=f"tier_demotion:{from_tier}->{to_tier}",
                )
                logger.debug(
                    "Marked memory %s for KM re-validation after demotion",
                    memory_id,
                )
        except ImportError:
            pass  # Knowledge Mound not available
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            logger.debug("KM re-validation trigger failed: %s", e)

    def _handle_tier_promotion_to_knowledge(self, event: "StreamEvent") -> None:
        """Memory tier promotion → Knowledge Mound notification.

        When a memory entry is promoted to a faster tier, notify KM
        so it can prioritize that knowledge for retrieval and ensure
        the entry's importance is reflected in search rankings.
        """
        data = event.data
        memory_id = data.get("memory_id", "")
        to_tier = data.get("to_tier", "")
        surprise_score = data.get("surprise_score", 0.0)

        if not memory_id:
            return

        logger.debug(
            "Tier promotion notification: memory=%s to=%s surprise=%.3f",
            memory_id,
            to_tier,
            surprise_score,
        )

        try:
            from aragora.knowledge.mound import get_knowledge_mound

            mound = get_knowledge_mound()
            if mound is None:
                return

            # Boost importance in KM based on promotion
            if hasattr(mound, "boost_importance"):
                mound.boost_importance(
                    source=f"continuum:{memory_id}",
                    factor=1.0 + surprise_score,
                )
        except ImportError:
            pass  # Knowledge Mound not available
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            logger.debug("KM importance boost failed: %s", e)

    def _handle_approval_to_km_reinforcement(self, event: "StreamEvent") -> None:
        """Human approval → KM confidence reinforcement.

        When a human approves a decision (via the approval flow),
        boost the confidence of related knowledge in the Knowledge Mound.
        This creates a feedback loop where human judgment improves
        the quality of future AI-driven decisions.
        """
        data = event.data
        decision_id = data.get("decision_id", data.get("request_id", ""))
        debate_id = data.get("debate_id", "")
        topic = data.get("topic", data.get("description", ""))

        if not topic:
            return

        logger.debug(
            "Approval → KM reinforcement: decision=%s debate=%s",
            decision_id,
            debate_id,
        )

        try:
            from aragora.knowledge.mound import get_knowledge_mound

            mound = get_knowledge_mound()
            if mound is None:
                return

            # Boost importance of knowledge related to the approved decision
            if hasattr(mound, "boost_importance"):
                source = f"debate:{debate_id}" if debate_id else f"decision:{decision_id}"
                mound.boost_importance(
                    source=source,
                    factor=1.15,  # 15% confidence boost from human approval
                )
                logger.info(
                    "Boosted KM confidence for approved decision %s",
                    decision_id or debate_id,
                )
        except ImportError:
            pass  # Knowledge Mound not available
        except (RuntimeError, TypeError, AttributeError, ValueError, OSError) as e:
            logger.debug("KM reinforcement from approval failed: %s", e)

    def register(self, manager: "CrossSubscriberManager") -> None:
        """Wire the knowledge-domain reactions into ``manager`` (keyed/idempotent)."""
        manager.register(
            "memory_to_mound",
            StreamEventType.MEMORY_STORED,
            self._handle_memory_to_mound,
        )
        manager.register(
            "mound_to_memory_retrieval",
            StreamEventType.KNOWLEDGE_QUERIED,
            self._handle_mound_to_memory_retrieval,
        )
        manager.register(
            "belief_to_mound",
            StreamEventType.BELIEF_CONVERGED,
            self._handle_belief_to_mound,
        )
        manager.register(
            "mound_to_belief",
            StreamEventType.DEBATE_START,
            self._handle_mound_to_belief,
        )
        manager.register(
            "rlm_to_mound",
            StreamEventType.RLM_COMPRESSION_COMPLETE,
            self._handle_rlm_to_mound,
        )
        manager.register(
            "mound_to_rlm",
            StreamEventType.KNOWLEDGE_QUERIED,
            self._handle_mound_to_rlm,
        )
        manager.register(
            "elo_to_mound",
            StreamEventType.AGENT_ELO_UPDATED,
            self._handle_elo_to_mound,
        )
        manager.register(
            "mound_to_team_selection",
            StreamEventType.DEBATE_START,
            self._handle_mound_to_team_selection,
        )
        manager.register(
            "insight_to_mound",
            StreamEventType.INSIGHT_EXTRACTED,
            self._handle_insight_to_mound,
        )
        manager.register(
            "flip_to_mound",
            StreamEventType.FLIP_DETECTED,
            self._handle_flip_to_mound,
        )
        manager.register(
            "mound_to_trickster",
            StreamEventType.DEBATE_START,
            self._handle_mound_to_trickster,
        )
        manager.register(
            "provenance_to_mound",
            StreamEventType.CONSENSUS,
            self._handle_provenance_to_mound,
        )
        manager.register(
            "mound_to_provenance",
            StreamEventType.CLAIM_VERIFICATION_RESULT,
            self._handle_mound_to_provenance,
        )
        manager.register(
            "consensus_to_mound",
            StreamEventType.CONSENSUS,
            self._handle_consensus_to_mound,
        )
        manager.register(
            "km_validation_feedback",
            StreamEventType.CONSENSUS,
            self._handle_km_validation_feedback,
        )
        manager.register(
            "mound_to_culture",
            StreamEventType.DEBATE_START,
            self._handle_mound_to_culture,
        )
        manager.register(
            "debate_outcome_to_knowledge",
            StreamEventType.DEBATE_END,
            self._handle_debate_outcome_to_knowledge,
        )
        manager.register(
            "workflow_complete_to_supermemory",
            StreamEventType.WORKFLOW_COMPLETE,
            self._handle_workflow_outcome_to_supermemory,
        )
        manager.register(
            "workflow_failed_to_supermemory",
            StreamEventType.WORKFLOW_FAILED,
            self._handle_workflow_outcome_to_supermemory,
        )
        manager.register(
            "tier_demotion_to_revalidation",
            StreamEventType.MEMORY_TIER_DEMOTION,
            self._handle_tier_demotion_to_revalidation,
        )
        manager.register(
            "tier_promotion_to_knowledge",
            StreamEventType.MEMORY_TIER_PROMOTION,
            self._handle_tier_promotion_to_knowledge,
        )
        manager.register(
            "approval_to_km_reinforcement",
            StreamEventType.APPROVAL_APPROVED,
            self._handle_approval_to_km_reinforcement,
        )


def get_knowledge_event_subscriber() -> KnowledgeEventSubscriber:
    """Return the ``KnowledgeEventSubscriber`` currently wired into the registry.

    Domain callers that need subscriber-local state - e.g.
    ``aragora.debate.knowledge_manager`` reading per-debate culture hints - use
    this instead of routing through ``CrossSubscriberManager``, which no longer
    carries that state (P4a Batch E2c). Registers a fresh instance first if none
    is present yet, reusing the existing one otherwise so accumulated state
    (e.g. ``_debate_cultures``) survives repeat calls.
    """
    subscriber = get_registered_subscribers().get("knowledge")
    if not isinstance(subscriber, KnowledgeEventSubscriber):
        subscriber = KnowledgeEventSubscriber()
        register_subscriber("knowledge", subscriber)
    return subscriber


def register() -> None:
    """(Re-)register this home's subscriber into the domain-free registry.

    Delegates to :func:`get_knowledge_event_subscriber`'s get-or-create so
    repeated calls reuse the existing instance instead of replacing it.
    ``CrossSubscriberManager.apply_registered_subscribers`` wires a given name
    into a manager at most once (per manager instance), so a naive
    unconditional re-register here would silently split the registry entry
    from what the manager already dispatches to: production calls
    ``bootstrap_debate_event_subscribers()`` from both
    ``Arena.init_context`` (stores culture state) and ``get_culture_hints``
    (reads it back) without resetting the manager in between, so the second
    call must resolve to the SAME instance the first call populated. A fresh
    subscriber is still created on first call or after ``reset_registry`` in
    tests, so registration survives a cached re-import.
    """
    get_knowledge_event_subscriber()


register()
