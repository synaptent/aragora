"""
Context initialization phase for debate orchestration.

This module extracts the context initialization logic (Phase 0) from the
Arena._run_inner() method, handling:
- Fork debate history injection
- Trending topic context
- Historical context fetching
- Pattern injection from InsightStore
- Memory pattern injection from CritiqueStore
- Pre-debate research
- DebateResult initialization
- Proposer selection
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import time
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.debate.context import DebateContext

logger = logging.getLogger(__name__)

# Knowledge query cache (TTL-based to reduce redundant semantic searches)
_knowledge_cache: dict[str, tuple[str, float]] = {}
_KNOWLEDGE_CACHE_TTL = 300.0  # 5 minutes

# Receipt conclusions cache (TTL-based, same pattern as knowledge cache)
_receipt_conclusions_cache: dict[str, tuple[str, float]] = {}
_RECEIPT_CONCLUSIONS_CACHE_TTL = 300.0  # 5 minutes

# Convergence history cache (TTL-based)
_convergence_history_cache: dict[str, tuple[dict, float]] = {}
_CONVERGENCE_HISTORY_CACHE_TTL = 600.0  # 10 minutes

# Check for RLM availability (prefer factory for TRUE RLM support)
# Declare types as unions to handle both import success and failure
_get_rlm: Callable[..., Any] | None = None
_RLMConfig: type[Any] | None = None
_RLMContextClass: type[Any] | None = None
HAS_RLM = False
HAS_OFFICIAL_RLM = False

try:
    from aragora.rlm import get_rlm, RLMConfig, RLMContext as RLMContextImport
    from aragora.rlm import HAS_OFFICIAL_RLM as _HAS_OFFICIAL_RLM_IMPORT

    _get_rlm = get_rlm
    _RLMConfig = RLMConfig
    _RLMContextClass = RLMContextImport
    HAS_RLM = True
    HAS_OFFICIAL_RLM = _HAS_OFFICIAL_RLM_IMPORT
except ImportError:
    pass


class ContextInitializer:
    """
    Initializes debate context before the proposal phase.

    This class encapsulates all the context preparation logic that was
    previously in the first ~130 lines of Arena._run_inner().

    Usage:
        initializer = ContextInitializer(
            initial_messages=arena.initial_messages,
            trending_topic=arena.trending_topic,
            recorder=arena.recorder,
            debate_embeddings=arena.debate_embeddings,
            insight_store=arena.insight_store,
            memory=arena.memory,
            protocol=arena.protocol,
        )
        await initializer.initialize(ctx)
    """

    def __init__(
        self,
        initial_messages: list | None = None,
        trending_topic: Any = None,
        recorder: Any = None,
        debate_embeddings: Any = None,
        insight_store: Any = None,
        memory: Any = None,
        protocol: Any = None,
        evidence_collector: Any = None,
        dissent_retriever: Any = None,  # DissentRetriever for historical minority views
        pulse_manager: Any = None,  # PulseManager for trending topics
        auto_fetch_trending: bool = True,  # Auto-fetch trending if no topic provided
        # Knowledge Mound integration
        knowledge_mound: Any = None,  # KnowledgeMound for unified knowledge queries
        enable_knowledge_retrieval: bool = True,  # Query mound before debates
        # Belief Network guidance
        enable_belief_guidance: bool = True,  # Inject historical cruxes from similar debates
        # Cross-debate memory for institutional knowledge
        cross_debate_memory: Any = None,  # CrossDebateMemory for institutional knowledge
        enable_cross_debate_memory: bool = True,  # Query cross-debate memory before debates
        # Outcome context: inject past decision outcomes into new debates
        enable_outcome_context: bool = True,  # Query OutcomeAdapter for similar past outcomes
        # Skills system for extensible evidence collection
        skill_registry: Any = None,  # SkillRegistry for debate-compatible skills
        enable_skills: bool = False,  # Invoke skills during evidence collection
        # RLM (Recursive Language Models) for context compression
        enable_rlm_compression: bool = True,  # Compress accumulated context hierarchically
        rlm_config: Any = None,  # RLMConfig for compression settings
        rlm_agent_call: Callable[[str, str], str] | None = None,  # Agent callback for compression
        # Codebase grounding (code-aware debates)
        codebase_path: str | None = None,  # Path to repo for code-grounded debates
        enable_codebase_grounding: bool = False,  # Inject codebase context
        codebase_persist_to_km: bool = False,  # Persist codebase to KM
        # Callbacks for orchestrator methods
        fetch_historical_context: Callable | None = None,
        format_patterns_for_prompt: Callable | None = None,
        get_successful_patterns_from_memory: Callable | None = None,
        perform_research: Callable | None = None,
        fetch_knowledge_context: Callable | None = None,  # Callback to fetch knowledge context
        inject_supermemory_context: Callable
        | None = None,  # Callback for external memory injection
    ):
        """
        Initialize the context initializer.

        Args:
            initial_messages: Fork debate history messages
            trending_topic: Optional trending topic to inject
            recorder: Optional ReplayRecorder
            debate_embeddings: Optional DebateEmbeddings for historical context
            insight_store: Optional InsightStore for pattern injection
            memory: Optional CritiqueStore for memory patterns
            protocol: DebateProtocol configuration
            evidence_collector: Optional EvidenceCollector for auto-collecting evidence
            dissent_retriever: Optional DissentRetriever for historical minority views
            pulse_manager: Optional PulseManager for fetching trending topics
            auto_fetch_trending: If True and no trending_topic provided, auto-fetch from Pulse
            knowledge_mound: Optional KnowledgeMound for unified knowledge queries
            enable_knowledge_retrieval: If True, query mound for relevant knowledge
            fetch_historical_context: Async callback to fetch historical context
            format_patterns_for_prompt: Callback to format patterns for prompts
            get_successful_patterns_from_memory: Callback to get memory patterns
            perform_research: Async callback to perform pre-debate research
            fetch_knowledge_context: Async callback to fetch knowledge from mound
            inject_supermemory_context: Async callback to inject external memory context
        """
        self.initial_messages = initial_messages or []
        self.trending_topic = trending_topic
        self.recorder = recorder
        self.debate_embeddings = debate_embeddings
        self.insight_store = insight_store
        self.memory = memory
        self.protocol = protocol
        self.evidence_collector = evidence_collector
        self.dissent_retriever = dissent_retriever
        self.pulse_manager = pulse_manager
        self.auto_fetch_trending = auto_fetch_trending
        self.knowledge_mound = knowledge_mound
        self.enable_knowledge_retrieval = enable_knowledge_retrieval
        self.enable_belief_guidance = enable_belief_guidance
        self.cross_debate_memory = cross_debate_memory
        self.enable_cross_debate_memory = enable_cross_debate_memory
        self.enable_outcome_context = enable_outcome_context

        # Skills system for extensible evidence collection
        self.skill_registry = skill_registry
        self.enable_skills = enable_skills

        # Codebase grounding
        self.codebase_path = codebase_path
        self.enable_codebase_grounding = enable_codebase_grounding
        self.codebase_persist_to_km = codebase_persist_to_km

        # RLM configuration - use factory for TRUE RLM support
        self.enable_rlm_compression = enable_rlm_compression and HAS_RLM
        self._rlm: Any | None = None
        if self.enable_rlm_compression and _get_rlm is not None:
            try:
                config = rlm_config if rlm_config else (_RLMConfig() if _RLMConfig else None)
                self._rlm = _get_rlm(config=config)
                if HAS_OFFICIAL_RLM:
                    logger.info(
                        "[rlm] TRUE RLM enabled for context initialization "
                        "(REPL-based, model writes code to examine context)"
                    )
                else:
                    logger.info(
                        "[rlm] RLM compression enabled for context initialization "
                        "(compression fallback - install rlm for TRUE RLM)"
                    )
            except (RuntimeError, AttributeError, ImportError) as e:  # noqa: BLE001 - phase isolation
                logger.warning("[rlm] Failed to initialize AragoraRLM: %s", e)

        # Callbacks
        self._fetch_historical_context = fetch_historical_context
        self._format_patterns_for_prompt = format_patterns_for_prompt
        self._get_successful_patterns_from_memory = get_successful_patterns_from_memory
        self._perform_research = perform_research
        self._fetch_knowledge_context = fetch_knowledge_context
        self._inject_supermemory_context_cb = inject_supermemory_context

    @staticmethod
    async def _safe_async(coro: Any, label: str) -> None:
        """Run an async coroutine with isolated error handling.

        Used by ``initialize()`` to gather independent context enrichment
        tasks concurrently without one failure aborting the others.

        Args:
            coro: The awaitable to run.
            label: Human-readable label for logging on failure.
        """
        try:
            await coro
        except asyncio.CancelledError:
            raise  # Never swallow cancellation
        except Exception as exc:  # noqa: BLE001 - phase isolation
            logger.debug("context_enrichment_failed label=%s error=%s", label, exc)

    async def initialize(self, ctx: DebateContext) -> None:
        """
        Initialize the debate context.

        This method performs context preparation with critical items first
        to enable parallel execution with the proposal phase:

        CRITICAL (must complete before proposals):
        1. Initialize DebateResult
        2. Select proposers

        FAST SYNC (run before background tasks):
        3. Inject fork debate history
        4. Start recorder
        5. Initialize context messages

        BACKGROUND (can run parallel with proposals):
        6. Auto-fetch trending topics from Pulse (if enabled)
        7. Inject trending topic context
        8. Fetch historical context
        9. Fetch knowledge mound context (unified knowledge queries)
        10. Inject learned patterns
        11. Inject memory patterns
        12. Inject historical dissents
        13. Perform pre-debate research
        14. Collect evidence (auto-collection)

        Args:
            ctx: The DebateContext to initialize
        """
        from aragora.core import DebateResult

        # === CRITICAL: Must complete before proposals can start ===

        # 1. Initialize DebateResult (needed for message recording)
        ctx.result = DebateResult(
            task=ctx.env.task,
            messages=[],
            critiques=[],
            votes=[],
            dissenting_views=[],
        )

        # 2. Select proposers (needed by proposal phase)
        self._select_proposers(ctx)
        logger.debug("proposers_selected count=%s", len(ctx.proposers))

        # === FAST SYNC: Quick operations that set up context ===

        # 3. Inject fork debate history
        self._inject_fork_history(ctx)

        # 4. Start recorder
        self._start_recorder()

        # 5. Initialize context messages for fork debates
        self._init_context_messages(ctx)

        # === BACKGROUND: Context enrichment (can run parallel with proposals) ===
        # These operations gather additional context but aren't blocking.
        # Results are injected before round 2 via await_background_context().
        #
        # Latency optimization (issue #268): independent async I/O operations
        # are gathered concurrently instead of running sequentially.  Sync
        # injections (memory patterns, dissents, belief cruxes, convergence
        # history) run after the concurrent batch because they are CPU-only
        # and depend on no I/O.

        # 6. Auto-fetch trending topics from Pulse if enabled
        if not self.trending_topic and self.auto_fetch_trending:
            await self._inject_pulse_context(ctx)

        # 7. Inject trending topic context (provided or auto-fetched)
        self._inject_trending_topic(ctx)

        # 8-9d. Gather independent async context enrichment tasks concurrently.
        # Each task is wrapped in _safe_async to isolate failures.
        # Perf: skip KM-dependent tasks when no knowledge_mound is configured
        # to avoid unnecessary coroutine overhead and timeout waits.
        _has_km = self.knowledge_mound is not None
        _concurrent_tasks: list[Any] = [
            self._safe_async(self._fetch_historical(ctx), "historical"),
            self._safe_async(self._inject_supermemory_context(ctx), "supermemory"),
            self._safe_async(self._inject_insight_patterns(ctx), "insight_patterns"),
        ]
        if _has_km:
            _concurrent_tasks.extend(
                [
                    self._safe_async(self._inject_knowledge_context(ctx), "knowledge_mound"),
                    self._safe_async(self._inject_receipt_conclusions(ctx), "receipt_conclusions"),
                    self._safe_async(self._inject_debate_knowledge(ctx), "debate_knowledge"),
                    self._safe_async(self._inject_cross_adapter_synthesis(ctx), "km_synthesis"),
                ]
            )
        if self.enable_cross_debate_memory:
            _concurrent_tasks.append(
                self._safe_async(self._inject_cross_debate_context(ctx), "cross_debate"),
            )
        if self.enable_outcome_context and _has_km:
            _concurrent_tasks.append(
                self._safe_async(self._inject_outcome_context(ctx), "outcome_context"),
            )

        _ctx_start = time.time()
        await asyncio.gather(*_concurrent_tasks)
        _ctx_elapsed_ms = (time.time() - _ctx_start) * 1000
        logger.debug(
            "context_enrichment_concurrent elapsed_ms=%.1f tasks=%d",
            _ctx_elapsed_ms,
            len(_concurrent_tasks),
        )

        # 11. Inject memory patterns from CritiqueStore (sync, no I/O)
        self._inject_memory_patterns(ctx)

        # 12. Inject historical dissents from ConsensusMemory (sync, no I/O)
        self._inject_historical_dissents(ctx)

        # 12b. Inject belief cruxes from similar past debates (sync, no I/O)
        if self.enable_belief_guidance:
            self._inject_belief_cruxes(ctx)

        # 12e. Inject convergence history (sync, no I/O)
        self._inject_convergence_history(ctx)

        # 13. Start research in background (non-blocking for fast startup)
        # Research runs in parallel with proposals, results injected before round 2
        if self.protocol and getattr(self.protocol, "enable_research", False):
            ctx.background_research_task = asyncio.create_task(
                self._perform_pre_debate_research(ctx)
            )
            logger.info("background_research_started")

        # 14. Start evidence collection in background (non-blocking)
        if (
            self.evidence_collector
            and self.protocol
            and getattr(self.protocol, "enable_evidence_collection", True)
        ):
            ctx.background_evidence_task = asyncio.create_task(self._collect_evidence(ctx))
            logger.info("background_evidence_started")

        # 15. Compress accumulated context with RLM (if enabled)
        # Uses TRUE RLM when available, compression fallback otherwise
        if self.enable_rlm_compression and self._rlm and ctx.env.context:
            await self._compress_context_with_rlm(ctx)

        # 16. Inject codebase context for code-grounded debates
        if self.enable_codebase_grounding and self.codebase_path:
            await self._inject_codebase_context(ctx)

    async def _inject_codebase_context(self, ctx: DebateContext) -> None:
        """Inject codebase structure context for code-grounded debates.

        Uses CodebaseContextProvider to build a cached codebase summary
        and sets it on the prompt builder as a dedicated section.
        Gracefully falls back to empty context on timeout or error.
        """
        try:
            from aragora.debate.codebase_context import (
                CodebaseContextConfig,
                CodebaseContextProvider,
            )

            config = CodebaseContextConfig(
                codebase_path=self.codebase_path,
                persist_to_km=self.codebase_persist_to_km,
                enable_rlm=getattr(self, "use_rlm_limiter", False),
            )
            provider = CodebaseContextProvider(config=config)

            # Reduced from 30s to 10s for interactive latency.
            context = await asyncio.wait_for(
                provider.build_context(ctx.env.task),
                timeout=10.0,
            )

            if context and hasattr(ctx, "_prompt_builder") and ctx._prompt_builder:
                summary = provider.get_summary(max_tokens=500)
                ctx._prompt_builder.set_codebase_context(summary)
                logger.info(
                    "codebase_context_injected",
                    extra={"path": self.codebase_path, "chars": len(summary)},
                )
        except asyncio.TimeoutError:
            logger.warning("Codebase context injection timed out after 30s")
        except (ImportError, RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Codebase context injection failed: %s", e)

    def _inject_fork_history(self, ctx: DebateContext) -> None:
        """Inject fork debate history into partial messages."""
        from aragora.core import Message

        if not self.initial_messages:
            return

        for msg in self.initial_messages:
            if isinstance(msg, Message):
                ctx.partial_messages.append(msg)
            elif isinstance(msg, dict):
                ctx.partial_messages.append(
                    Message(
                        role=msg.get("role", "user"),
                        agent=msg.get("agent", "fork_context"),
                        content=msg.get("content", ""),
                        round=msg.get("round", 0),
                    )
                )

    def _inject_trending_topic(self, ctx: DebateContext) -> None:
        """Inject trending topic context into environment."""
        if not self.trending_topic:
            return

        try:
            topic_context = (
                "## TRENDING TOPIC\nThis debate was initiated based on trending topic:\n"
            )
            topic_context += f"- **{self.trending_topic.topic}** ({self.trending_topic.platform})\n"

            if hasattr(self.trending_topic, "category") and self.trending_topic.category:
                topic_context += f"- Category: {self.trending_topic.category}\n"

            if hasattr(self.trending_topic, "volume") and self.trending_topic.volume:
                topic_context += f"- Engagement: {self.trending_topic.volume:,}\n"

            if hasattr(self.trending_topic, "to_debate_prompt"):
                topic_context += f"\n{self.trending_topic.to_debate_prompt()}"

            if ctx.env.context:
                ctx.env.context = topic_context + "\n\n" + ctx.env.context
            else:
                ctx.env.context = topic_context
        except (ValueError, KeyError, TypeError, AttributeError) as e:  # noqa: BLE001 - phase isolation
            logger.debug("Trending topic injection failed: %s", e)

    async def _inject_pulse_context(self, ctx: DebateContext) -> None:
        """Auto-fetch and inject trending topics from Pulse.

        Fetches trending topics from configured Pulse ingestors and
        selects the most suitable one for debate context enrichment.
        This runs only if auto_fetch_trending is True and no trending_topic
        was explicitly provided.
        """
        if not self.pulse_manager:
            return

        try:
            topics = await asyncio.wait_for(
                self.pulse_manager.get_trending_topics(limit_per_platform=3),
                timeout=5.0,  # Don't delay debate startup
            )

            if not topics:
                return

            # Select best topic for debate
            if hasattr(self.pulse_manager, "select_topic_for_debate"):
                selected = self.pulse_manager.select_topic_for_debate(topics)
            else:
                selected = topics[0] if topics else None

            if selected:
                # Store as trending_topic so _inject_trending_topic can use it
                self.trending_topic = selected
                logger.info(
                    "[pulse] Auto-selected trending topic: %s (%s)",
                    selected.topic,
                    selected.platform,
                )

        except asyncio.TimeoutError:
            logger.warning("[pulse] Trending topic fetch timed out")
        except (RuntimeError, AttributeError, ImportError) as e:  # noqa: BLE001 - phase isolation
            logger.debug("[pulse] Trending topic fetch failed: %s", e)

    def _start_recorder(self) -> None:
        """Start the replay recorder if provided."""
        if not self.recorder:
            return

        try:
            self.recorder.start()
            self.recorder.record_phase_change("debate_start")
        except (RuntimeError, AttributeError, ImportError) as e:  # noqa: BLE001 - phase isolation
            logger.warning("Recorder start error (non-fatal): %s", e)

    async def _fetch_historical(self, ctx: DebateContext) -> None:
        """Fetch historical context for institutional memory."""
        if not self.debate_embeddings or not self._fetch_historical_context:
            return

        try:
            # Reduced from 10s to 5s for interactive latency.
            ctx.historical_context_cache = await asyncio.wait_for(
                self._fetch_historical_context(ctx.env.task, limit=2), timeout=5.0
            )
        except asyncio.TimeoutError:
            logger.warning("Historical context fetch timed out")
            ctx.historical_context_cache = ""
        except (RuntimeError, AttributeError, ImportError) as e:  # noqa: BLE001 - phase isolation
            logger.debug("Historical context fetch error: %s", e)
            ctx.historical_context_cache = ""

    async def _inject_knowledge_context(self, ctx: DebateContext) -> None:
        """Fetch and inject knowledge from Knowledge Mound.

        Queries the unified knowledge superstructure for semantically related
        knowledge items that can inform the debate. This provides agents with
        organizational memory and previously learned conclusions.

        When a PromptBuilder is available (via ctx._prompt_builder), the knowledge
        context is set as a structured prompt section rather than appended to
        env.context. This gives agents a dedicated "Organizational Knowledge"
        section in their prompts. Falls back to env.context injection for
        backward compatibility.

        Uses TTL-based caching to reduce redundant semantic searches for
        similar tasks within a short time window.
        """
        global _knowledge_cache

        if not self.knowledge_mound or not self.enable_knowledge_retrieval:
            return

        if not self._fetch_knowledge_context:
            return

        try:
            # Generate cache key from task content (not for security)
            query_hash = hashlib.md5(ctx.env.task.encode(), usedforsecurity=False).hexdigest()

            # Check cache first
            cached = self._get_cached_knowledge(query_hash)
            if cached is not None:
                if cached:  # Non-empty cached result
                    self._set_knowledge_on_builder_or_env(ctx, cached)
                    logger.info(
                        "[knowledge_mound] Used cached knowledge context (%d chars)",
                        len(cached),
                    )
                return

            # Fetch fresh knowledge context
            # Reduced from 10s to 5s for interactive latency (issue #268 follow-up).
            # If KM is slow, we skip rather than block the debate start.
            knowledge_context = await asyncio.wait_for(
                self._fetch_knowledge_context(ctx.env.task, limit=10),
                timeout=5.0,
            )

            # Cache the result (even if empty, to avoid re-fetching)
            _knowledge_cache[query_hash] = (knowledge_context or "", time.time())

            if knowledge_context:
                # Track which KM items were used for outcome validation
                item_ids: list[str] = []
                km_ops = getattr(self._fetch_knowledge_context, "__self__", None)
                if km_ops and hasattr(km_ops, "_last_km_item_ids"):
                    km_ids = km_ops._last_km_item_ids
                    if km_ids:
                        item_ids = list(km_ids)
                        ctx._km_item_ids_used = km_ids  # type: ignore[attr-defined]

                self._set_knowledge_on_builder_or_env(ctx, knowledge_context, item_ids)
                logger.info(
                    "[knowledge_mound] Injected knowledge context into debate (%d chars)",
                    len(knowledge_context),
                )

        except asyncio.TimeoutError:
            logger.warning("[knowledge_mound] Knowledge context fetch timed out")
        except (RuntimeError, AttributeError, ImportError) as e:  # noqa: BLE001 - phase isolation
            logger.debug("[knowledge_mound] Knowledge context fetch error: %s", e)

    def _set_knowledge_on_builder_or_env(
        self,
        ctx: DebateContext,
        knowledge_context: str,
        item_ids: list[str] | None = None,
    ) -> None:
        """Set knowledge context on PromptBuilder if available, else env.context.

        Prefers the structured PromptBuilder injection path so that knowledge
        appears as a dedicated "Organizational Knowledge" section in agent
        prompts. Falls back to appending to env.context for backward
        compatibility when no PromptBuilder is wired in.

        Args:
            ctx: The debate context.
            knowledge_context: The knowledge context string to inject.
            item_ids: Optional list of KM item IDs used for outcome tracking.
        """
        prompt_builder = getattr(ctx, "_prompt_builder", None)
        if prompt_builder and hasattr(prompt_builder, "set_knowledge_context"):
            prompt_builder.set_knowledge_context(knowledge_context, item_ids)
        else:
            # Fallback: append to env.context (backward compatible)
            if ctx.env.context:
                ctx.env.context += "\n\n" + knowledge_context
            else:
                ctx.env.context = knowledge_context

    async def _inject_supermemory_context(self, ctx: DebateContext) -> None:
        """Inject external Supermemory context via orchestrator callback."""
        if not self._inject_supermemory_context_cb:
            return

        try:
            await self._inject_supermemory_context_cb(
                debate_id=getattr(ctx, "debate_id", None),
                debate_topic=ctx.env.task,
            )
        except (RuntimeError, AttributeError, ImportError) as e:  # noqa: BLE001 - phase isolation
            logger.debug("[supermemory] Context injection error: %s", e)

    async def _inject_debate_knowledge(self, ctx: DebateContext) -> None:
        """Inject past debate knowledge from KM via the knowledge injection flywheel.

        Uses DebateKnowledgeInjector to query for relevant past decision receipts
        and inject them into the environment context, completing the
        Receipt -> KM -> Next Debate feedback loop.
        """
        if not getattr(self.protocol, "enable_knowledge_injection", False):
            return

        if not self.knowledge_mound:
            return

        try:
            from aragora.debate.knowledge_injection import (
                DebateKnowledgeInjector,
                KnowledgeInjectionConfig,
            )
        except ImportError:
            return

        try:
            config = KnowledgeInjectionConfig(
                max_relevant_receipts=getattr(self.protocol, "knowledge_injection_max_receipts", 3),
            )
            injector = DebateKnowledgeInjector(config=config)
            task = ctx.env.task if ctx.env else ""
            domain = getattr(ctx, "domain", None)

            knowledge = await injector.query_relevant_knowledge(task, domain)
            if not knowledge:
                return

            formatted = injector.format_for_injection(knowledge)
            if formatted:
                ctx.env.context = (ctx.env.context or "") + "\n\n" + formatted
                logger.info(
                    "[knowledge_injection] Injected %d past debate receipts into context",
                    len(knowledge),
                )
        except (RuntimeError, ValueError, OSError, AttributeError, TypeError) as e:
            logger.debug("[knowledge_injection] Failed: %s", e)

    async def _inject_cross_adapter_synthesis(self, ctx: DebateContext) -> None:
        """Inject cross-adapter synthesized knowledge from KnowledgeBridgeHub.

        Queries multiple KM adapters (Consensus, Evidence, Performance, Pulse,
        Belief, Compliance) and injects a unified context block. This is the
        cross-adapter synthesis layer that turns 33 write-heavy adapters into
        a coherent read-back system for debate enrichment.
        """
        if not self.knowledge_mound:
            return

        try:
            from aragora.knowledge.bridges import KnowledgeBridgeHub

            hub = KnowledgeBridgeHub(self.knowledge_mound)
            topic = ctx.env.task if ctx.env else ""
            domain = getattr(ctx, "domain", "general") or "general"

            # Reduced from 8s to 5s for interactive latency.
            synthesis = await asyncio.wait_for(
                hub.synthesize_for_debate(topic, domain=domain, max_items=8),
                timeout=5.0,
            )

            if synthesis:
                if ctx.env.context:
                    ctx.env.context += "\n\n" + synthesis
                else:
                    ctx.env.context = synthesis
                logger.info(
                    "[km_synthesis] Injected cross-adapter synthesis (%d chars)",
                    len(synthesis),
                )
        except asyncio.TimeoutError:
            logger.warning("[km_synthesis] Cross-adapter synthesis timed out")
        except (ImportError, RuntimeError, AttributeError, TypeError, ValueError) as e:
            logger.debug("[km_synthesis] Cross-adapter synthesis failed: %s", e)

    def _get_cached_knowledge(self, query_hash: str) -> str | None:
        """Get cached knowledge context if still valid.

        Returns:
            Cached knowledge string if found and not expired, None otherwise.
        """
        if query_hash in _knowledge_cache:
            result, ts = _knowledge_cache[query_hash]
            if time.time() - ts < _KNOWLEDGE_CACHE_TTL:
                return result
            # Expired - remove from cache
            del _knowledge_cache[query_hash]
        return None

    async def _inject_receipt_conclusions(self, ctx: DebateContext) -> None:
        """Fetch and inject past decision conclusions from Knowledge Mound.

        Queries the Knowledge Mound for items tagged as receipt conclusions
        (ingested by the ReceiptAdapter) that are semantically relevant to the
        current debate topic. This closes the backward flow of the feedback
        loop: decisions made in past debates inform future ones.

        Uses the same TTL-based caching pattern as ``_inject_knowledge_context``
        to reduce redundant semantic searches.
        """
        global _receipt_conclusions_cache

        if not self.knowledge_mound or not self.enable_knowledge_retrieval:
            return

        try:
            task = ctx.env.task
            query_hash = hashlib.md5(
                f"receipt_conclusions:{task}".encode(), usedforsecurity=False
            ).hexdigest()

            # Check cache first
            if query_hash in _receipt_conclusions_cache:
                cached_text, cached_ts = _receipt_conclusions_cache[query_hash]
                if time.time() - cached_ts < _RECEIPT_CONCLUSIONS_CACHE_TTL:
                    if cached_text:
                        self._set_receipt_conclusions_on_context(ctx, cached_text)
                        logger.info(
                            "[receipt_feedback] Used cached receipt conclusions (%d chars)",
                            len(cached_text),
                        )
                    return

            # Query the KM for receipt-derived items relevant to this topic
            if not hasattr(self.knowledge_mound, "query"):
                return

            from aragora.knowledge.mound.types import QueryFilters

            filters = QueryFilters(tags=["decision_receipt"])

            # Reduced from 8s to 5s for interactive latency.
            results = await asyncio.wait_for(
                self.knowledge_mound.query(
                    query=task,
                    filters=filters,
                    limit=5,
                ),
                timeout=5.0,
            )

            items = results.items if hasattr(results, "items") else []
            if not items:
                _receipt_conclusions_cache[query_hash] = ("", time.time())
                return

            # Format the conclusions for injection
            lines: list[str] = [
                "## PAST DECISION CONCLUSIONS",
                "The following decisions were reached in previous debates on related topics.",
                "Consider them as institutional precedent but challenge if new evidence warrants:\n",
            ]
            for item in items:
                confidence_label = (
                    item.confidence.value
                    if hasattr(item.confidence, "value")
                    else str(item.confidence)
                )
                verdict = item.metadata.get("verdict", "")
                verdict_str = f" [{verdict}]" if verdict else ""
                content_preview = item.content[:400]
                lines.append(f"- **{confidence_label} confidence{verdict_str}**: {content_preview}")

            conclusions_text = "\n".join(lines)
            _receipt_conclusions_cache[query_hash] = (conclusions_text, time.time())

            self._set_receipt_conclusions_on_context(ctx, conclusions_text)
            logger.info(
                "[receipt_feedback] Injected %d past decision conclusions into debate context",
                len(items),
            )

        except asyncio.TimeoutError:
            logger.warning("[receipt_feedback] Receipt conclusions fetch timed out")
        except (RuntimeError, AttributeError, ImportError, TypeError, ValueError) as e:  # noqa: BLE001 - phase isolation
            logger.debug("[receipt_feedback] Receipt conclusions injection error: %s", e)

    def _set_receipt_conclusions_on_context(
        self,
        ctx: DebateContext,
        conclusions_text: str,
    ) -> None:
        """Set receipt conclusions on PromptBuilder or env.context.

        Args:
            ctx: The debate context.
            conclusions_text: The formatted receipt conclusions string.
        """
        prompt_builder = getattr(ctx, "_prompt_builder", None)
        if prompt_builder and hasattr(prompt_builder, "set_knowledge_context"):
            # Append to existing knowledge context rather than replacing it
            existing = getattr(prompt_builder, "_knowledge_context", "") or ""
            if existing:
                prompt_builder.set_knowledge_context(existing + "\n\n" + conclusions_text)
            else:
                prompt_builder.set_knowledge_context(conclusions_text)
        else:
            if ctx.env.context:
                ctx.env.context += "\n\n" + conclusions_text
            else:
                ctx.env.context = conclusions_text

    def _inject_convergence_history(self, ctx: DebateContext) -> None:
        """Inject past convergence metrics for similar topics.

        Queries the convergence history store for debates on similar topics
        and injects a suggested round count based on historical convergence
        speed. This helps the protocol set expectations and enables early
        termination when past data indicates quick convergence.

        Uses TTL-based caching to avoid repeated lookups.
        """
        global _convergence_history_cache

        try:
            from aragora.debate.convergence.history import get_convergence_history_store

            store = get_convergence_history_store()
            if store is None:
                return

            task = ctx.env.task
            query_hash = hashlib.md5(
                f"convergence_history:{task}".encode(), usedforsecurity=False
            ).hexdigest()

            # Check cache first
            if query_hash in _convergence_history_cache:
                cached_data, cached_ts = _convergence_history_cache[query_hash]
                if time.time() - cached_ts < _CONVERGENCE_HISTORY_CACHE_TTL:
                    if cached_data:
                        self._apply_convergence_hint(ctx, cached_data)
                    return

            # Query for similar topics
            similar_records = store.find_similar(task, limit=5)
            if not similar_records:
                _convergence_history_cache[query_hash] = ({}, time.time())
                return

            # Compute average convergence round from past debates
            total_convergence_round = 0
            total_rounds = 0
            total_final_similarity = 0.0
            count = len(similar_records)

            for record in similar_records:
                total_convergence_round += record.get("convergence_round", 0)
                total_rounds += record.get("total_rounds", 0)
                total_final_similarity += record.get("final_similarity", 0.0)

            summary = {
                "avg_convergence_round": total_convergence_round / count if count else 0,
                "avg_total_rounds": total_rounds / count if count else 0,
                "avg_final_similarity": total_final_similarity / count if count else 0.0,
                "sample_count": count,
            }

            _convergence_history_cache[query_hash] = (summary, time.time())
            self._apply_convergence_hint(ctx, summary)

            logger.info(
                "[convergence_history] Injected convergence hint: avg %.1f rounds to converge "
                "(from %d similar debates)",
                summary["avg_convergence_round"],
                count,
            )

        except ImportError:
            pass  # Convergence history store not available yet
        except (TypeError, ValueError, AttributeError, RuntimeError, KeyError) as e:  # noqa: BLE001 - phase isolation
            logger.debug("[convergence_history] Convergence history injection error: %s", e)

    def _apply_convergence_hint(self, ctx: DebateContext, summary: dict) -> None:
        """Apply convergence hint to debate context.

        Sets a ``_convergence_hint`` attribute on the context so the round
        controller can consider it when deciding whether to run additional
        rounds.  Also injects a brief note into ``env.context`` so agents
        are aware of historical convergence speed.

        Args:
            ctx: The debate context.
            summary: Dict with avg_convergence_round, avg_total_rounds,
                     avg_final_similarity, sample_count.
        """
        if not summary or summary.get("sample_count", 0) == 0:
            return

        ctx._convergence_hint = summary  # type: ignore[attr-defined]

        avg_rounds = summary["avg_convergence_round"]
        avg_sim = summary["avg_final_similarity"]
        sample_n = summary["sample_count"]

        hint_text = (
            f"\n\n## CONVERGENCE HINT (from {sample_n} similar past debates)\n"
            f"Similar topics typically converge in ~{avg_rounds:.1f} rounds "
            f"with {avg_sim:.0%} final similarity. "
            f"Focus arguments early to avoid diminishing returns in later rounds."
        )

        if ctx.env.context:
            ctx.env.context += hint_text
        else:
            ctx.env.context = hint_text.strip()

    async def _inject_insight_patterns(self, ctx: DebateContext) -> None:
        """Inject learned patterns and high-confidence insights from past debates.

        This method now uses the enhanced get_relevant_insights() to find
        domain-specific insights with high confidence scores, in addition to
        common patterns. Applied insight IDs are stored for usage tracking.
        """
        if not self.insight_store:
            return

        try:
            # 1. Inject common patterns (original behavior)
            patterns = await self.insight_store.get_common_patterns(min_occurrences=2, limit=5)
            if patterns and self._format_patterns_for_prompt:
                pattern_context = self._format_patterns_for_prompt(patterns)
                if ctx.env.context:
                    ctx.env.context += "\n\n" + pattern_context
                else:
                    ctx.env.context = pattern_context

            # 2. Inject high-confidence insights as "learned practices" (B2 enhancement)
            domain = getattr(ctx, "domain", None)
            if domain == "general":
                domain = None

            relevant_insights = await self.insight_store.get_relevant_insights(
                domain=domain,
                min_confidence=0.7,
                limit=3,
            )

            if relevant_insights:
                # Format insights as learned practices
                insight_context = "\n\n## LEARNED PRACTICES (from previous debates)\n"
                insight_context += (
                    "The following insights have proven valuable in similar debates:\n"
                )

                for insight in relevant_insights:
                    insight_context += (
                        f"\n• **{insight.title}** (confidence: {insight.confidence:.0%})\n"
                    )
                    if insight.description:
                        insight_context += f"  {insight.description[:200]}\n"

                    # Track applied insight IDs for usage feedback
                    ctx.applied_insight_ids.append(insight.id)

                if ctx.env.context:
                    ctx.env.context += insight_context
                else:
                    ctx.env.context = insight_context.strip()

                logger.info(
                    "[insight] Injected %d learned practices into debate context",
                    len(relevant_insights),
                )

        except (RuntimeError, AttributeError, ImportError) as e:  # noqa: BLE001 - phase isolation
            logger.debug("Pattern injection error: %s", e)

    def _inject_memory_patterns(self, ctx: DebateContext) -> None:
        """Inject successful critique patterns from CritiqueStore memory."""
        if not self.memory or not self._get_successful_patterns_from_memory:
            return

        try:
            memory_patterns = self._get_successful_patterns_from_memory(limit=3)
            if memory_patterns:
                if ctx.env.context:
                    ctx.env.context += "\n\n" + memory_patterns
                else:
                    ctx.env.context = memory_patterns
                logger.info("  [memory] Injected successful critique patterns into debate context")
        except (ValueError, KeyError, TypeError) as e:  # noqa: BLE001 - phase isolation
            logger.debug("Memory pattern injection error: %s", e)

    def _inject_historical_dissents(self, ctx: DebateContext) -> None:
        """Inject historical dissenting views from similar past debates.

        Uses DissentRetriever to find relevant contrarian perspectives
        from previous debates on similar topics. This helps prevent
        groupthink and surfaces minority viewpoints that may be valuable.

        Dissents are structured by type with confidence scores:
        - WARNINGS FROM PAST DEBATES (risk_warning, edge_case_concern)
        - ALTERNATIVE APPROACHES CONSIDERED (alternative_approach)
        - FUNDAMENTAL DISAGREEMENTS (fundamental_disagreement)
        """
        if not self.dissent_retriever:
            return

        try:
            topic = ctx.env.task
            domain = getattr(ctx, "domain", None)
            if domain == "general":
                domain = None

            # Try structured injection via retrieve_for_new_debate
            structured = self._build_structured_dissent_context(topic, domain)

            if structured and len(structured.strip()) >= 50:
                historical_section = f"\n\n{structured}"
                if ctx.env.context:
                    ctx.env.context += historical_section
                else:
                    ctx.env.context = historical_section.strip()

                logger.info(
                    "[consensus_memory] Injected structured dissent context "
                    "(%d chars) from similar debates",
                    len(structured),
                )
                return

            # Fallback: use the plain text preparation context
            historical = self.dissent_retriever.get_debate_preparation_context(
                topic=topic,
                domain=domain,
            )

            if not historical or len(historical.strip()) < 50:
                return

            historical_section = f"\n\n{historical}"
            if ctx.env.context:
                ctx.env.context += historical_section
            else:
                ctx.env.context = historical_section.strip()

            logger.info(
                "[consensus_memory] Injected historical dissent context "
                "(%d chars) from similar debates",
                len(historical),
            )

        except (ValueError, KeyError, TypeError, RuntimeError) as e:  # noqa: BLE001 - phase isolation
            logger.debug("Historical dissent injection error: %s", e)

        # Also inject epistemic graph priors (inherited beliefs from past debates)
        self._inject_epistemic_priors(ctx)

    def _inject_epistemic_priors(self, ctx: DebateContext) -> None:
        """Inject inherited beliefs from the cross-debate epistemic graph.

        Queries the EpistemicGraph for beliefs relevant to the debate topic,
        enabling belief inheritance: high-confidence conclusions from past
        debates seed new debates as prior knowledge.
        """
        try:
            from aragora.reasoning.epistemic_graph import get_epistemic_graph

            graph = get_epistemic_graph()
            topic = ctx.env.task
            domain = getattr(ctx, "domain", None) or ""

            priors = graph.inject_priors(topic=topic, domain=domain, limit=5)
            if not priors:
                return

            # Build context section
            lines = ["## INHERITED BELIEFS FROM PAST DEBATES"]
            lines.append(
                "These beliefs were established in prior debates on similar topics. "
                "Consider them as priors but challenge them if evidence warrants:"
            )
            for prior in priors:
                conf_pct = f"{prior.effective_confidence * 100:.0f}%"
                source = prior.source_type.upper()
                lines.append(f"- [{conf_pct} confidence, {source}] {prior.statement}")
                if prior.dissenting_agents:
                    lines.append(f"  (Dissent from: {', '.join(prior.dissenting_agents[:3])})")

            section = "\n\n" + "\n".join(lines)
            if ctx.env.context:
                ctx.env.context += section
            else:
                ctx.env.context = section.strip()

            # Store priors on context for feedback phase tracking
            ctx._epistemic_priors = priors  # type: ignore[attr-defined]

            logger.info(
                "[epistemic] Injected %d inherited beliefs as priors",
                len(priors),
            )
        except ImportError:
            pass  # EpistemicGraph not available
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("Epistemic prior injection error: %s", e)

    def _build_structured_dissent_context(
        self,
        topic: str,
        domain: str | None,
    ) -> str:
        """Build structured dissent context organized by dissent type.

        Separates dissents into three categories with confidence scores:
        1. WARNINGS FROM PAST DEBATES (risk_warning + edge_case_concern)
        2. ALTERNATIVE APPROACHES CONSIDERED (alternative_approach)
        3. FUNDAMENTAL DISAGREEMENTS (fundamental_disagreement)

        Returns:
            Formatted context string, or empty string if no structured
            data is available.
        """
        if not hasattr(self.dissent_retriever, "retrieve_for_new_debate"):
            return ""

        try:
            context_data = self.dissent_retriever.retrieve_for_new_debate(
                topic=topic,
                domain=domain,
            )
        except (ValueError, KeyError, TypeError, RuntimeError):
            return ""

        dissent_by_type = context_data.get("dissent_by_type", {})
        if not dissent_by_type:
            return ""

        sections: list[str] = []
        sections.append(f"# Historical Dissent Analysis for: {topic}\n")

        # Section 1: Warnings (risk_warning + edge_case_concern)
        warnings = dissent_by_type.get("risk_warning", []) + dissent_by_type.get(
            "edge_case_concern", []
        )
        if warnings:
            sections.append("## WARNINGS FROM PAST DEBATES")
            sections.append("These risks and edge cases were raised in similar past debates:")
            for d in warnings[:5]:
                confidence = d.get("confidence", 0.0)
                content = d.get("content", "")[:300]
                agent = d.get("agent_id", "unknown")
                sections.append(f"- [{confidence:.0%} confidence] {content} (raised by {agent})")
            sections.append("")

        # Section 2: Alternative approaches
        alternatives = dissent_by_type.get("alternative_approach", [])
        if alternatives:
            sections.append("## ALTERNATIVE APPROACHES CONSIDERED")
            sections.append("Previous debates explored these alternative approaches:")
            for d in alternatives[:5]:
                confidence = d.get("confidence", 0.0)
                content = d.get("content", "")[:300]
                agent = d.get("agent_id", "unknown")
                reasoning = d.get("reasoning", "")[:200]
                entry = f"- [{confidence:.0%} confidence] {content} (by {agent})"
                if reasoning:
                    entry += f"\n  Reasoning: {reasoning}"
                sections.append(entry)
            sections.append("")

        # Section 3: Fundamental disagreements
        disagreements = dissent_by_type.get("fundamental_disagreement", [])
        if disagreements:
            sections.append("## FUNDAMENTAL DISAGREEMENTS")
            sections.append("These core disagreements remain unresolved from past debates:")
            for d in disagreements[:5]:
                confidence = d.get("confidence", 0.0)
                content = d.get("content", "")[:300]
                agent = d.get("agent_id", "unknown")
                acknowledged = d.get("acknowledged", False)
                status = "addressed" if acknowledged else "UNRESOLVED"
                sections.append(f"- [{confidence:.0%} confidence, {status}] {content} (by {agent})")
            sections.append("")

        # Only return if we built at least one typed section
        if len(sections) <= 1:
            return ""

        sections.append("Consider addressing these points explicitly in your arguments.")

        return "\n".join(sections)

    def _inject_belief_cruxes(self, ctx: DebateContext) -> None:
        """Inject belief cruxes from similar past debates.

        Retrieves crux claims (key disagreement points) from past debates
        on similar topics and injects them as context. This helps agents
        focus on the most important points of contention early in the debate.

        Uses the DissentRetriever's underlying ConsensusMemory to find
        similar debates and extract their recorded belief_cruxes.
        """
        if not self.dissent_retriever:
            return

        try:
            # Get the underlying ConsensusMemory from DissentRetriever
            consensus_memory = getattr(self.dissent_retriever, "memory", None)
            if not consensus_memory:
                return

            topic = ctx.env.task
            domain = getattr(ctx, "domain", None)
            if domain == "general":
                domain = None

            # Find similar debates
            similar_debates = consensus_memory.find_similar_debates(
                topic=topic,
                domain=domain,
                min_confidence=0.5,
                limit=5,
            )

            if not similar_debates:
                return

            # Extract belief cruxes from similar debates
            all_cruxes: list[str] = []
            for similar in similar_debates:
                consensus = similar.consensus
                # Cruxes are stored in the metadata dict
                if hasattr(consensus, "metadata") and consensus.metadata:
                    cruxes = consensus.metadata.get("belief_cruxes", [])
                    all_cruxes.extend(cruxes[:3])  # Max 3 per debate

                # Also check key_claims as backup
                if hasattr(consensus, "key_claims") and consensus.key_claims:
                    # Add key claims if we don't have enough cruxes
                    if len(all_cruxes) < 5:
                        all_cruxes.extend(consensus.key_claims[:2])

            if not all_cruxes:
                return

            # Deduplicate and limit
            unique_cruxes = list(dict.fromkeys(all_cruxes))[:5]  # Max 5 cruxes

            # Format as context
            crux_context = "\n\n## HISTORICAL CRUXES (key points of debate from similar topics)\n"
            crux_context += (
                "Previous debates on similar topics identified these as critical decision points:\n"
            )
            for i, crux in enumerate(unique_cruxes, 1):
                # Truncate long cruxes
                crux_text = crux[:300] + "..." if len(crux) > 300 else crux
                crux_context += f"\n{i}. {crux_text}"

            crux_context += "\n\nConsider addressing these points explicitly in your arguments."

            # Inject into context
            if ctx.env.context:
                ctx.env.context += crux_context
            else:
                ctx.env.context = crux_context.strip()

            logger.info(
                "[belief_guidance] Injected %d historical cruxes from %d similar debates",
                len(unique_cruxes),
                len(similar_debates),
            )

        except (ValueError, KeyError, TypeError, AttributeError) as e:  # noqa: BLE001 - phase isolation
            logger.debug("[belief_guidance] Crux injection error: %s", e)

    async def _inject_cross_debate_context(self, ctx: DebateContext) -> None:
        """Inject institutional knowledge from CrossDebateMemory.

        Queries the cross-debate memory system for relevant context from past
        debates on similar topics. This provides agents with institutional
        knowledge - conclusions, insights, and patterns that the system has
        learned from previous debates.

        This is distinct from historical dissents (which focus on minority views)
        and belief cruxes (which focus on key disagreement points). Cross-debate
        memory provides a broader view of what the system has learned.
        """
        if not self.enable_cross_debate_memory:
            return

        try:
            topic = ctx.env.task
            context_source = self.cross_debate_memory
            if context_source is None and hasattr(self.memory, "get_relevant_context"):
                context_source = self.memory
            if not context_source:
                return

            # Query cross-debate memory for relevant context
            context_result = context_source.get_relevant_context(task=topic)
            if inspect.isawaitable(context_result):
                relevant_context = await asyncio.wait_for(
                    context_result,
                    timeout=5.0,  # Quick timeout to avoid blocking
                )
            else:
                relevant_context = context_result

            if not relevant_context or len(relevant_context.strip()) < 50:
                return

            # Never inject error placeholders as institutional knowledge
            # (issue #9304: a failed attempt's 'tripped over an edge case'
            # placeholder was re-fed to the next debate as a learned insight).
            from aragora.agents.failure_semantics import looks_like_agent_failure_response

            filtered_lines = [
                line
                for line in relevant_context.splitlines()
                if not (line.strip() and looks_like_agent_failure_response(line))
            ]
            relevant_context = "\n".join(filtered_lines)
            if len(relevant_context.strip()) < 50:
                return

            # Inject as institutional knowledge section
            institutional_section = "\n\n## INSTITUTIONAL KNOWLEDGE\n"
            institutional_section += (
                "The following insights are from previous debates on related topics:\n\n"
            )
            institutional_section += relevant_context

            if ctx.env.context:
                ctx.env.context += institutional_section
            else:
                ctx.env.context = institutional_section.strip()

            logger.info(
                "[cross_debate] Injected institutional knowledge (%d chars) from past debates",
                len(relevant_context),
            )

        except asyncio.TimeoutError:
            logger.debug("[cross_debate] Context fetch timed out")
        except (RuntimeError, AttributeError, ImportError, TypeError) as e:  # noqa: BLE001 - phase isolation
            logger.debug("[cross_debate] Context injection error: %s", e)

    async def _inject_outcome_context(self, ctx: DebateContext) -> None:
        """Inject past decision outcome data into the debate context.

        Queries the OutcomeAdapter for outcomes from similar past decisions
        and injects them as context so agents can learn from past successes
        and failures. This closes the outcome feedback loop: decisions made
        in past debates inform future ones via their measured outcomes.

        The context is set on the PromptBuilder as a dedicated section
        (``_outcome_context``) so it appears alongside other KM context
        in agent prompts. Falls back to env.context injection.
        """
        if not self.knowledge_mound:
            return

        try:
            from aragora.knowledge.mound.adapters.outcome_adapter import (
                OutcomeAdapter,
            )
        except ImportError:
            logger.debug("[outcome_context] OutcomeAdapter not available")
            return

        try:
            adapter = OutcomeAdapter(mound=self.knowledge_mound)
            topic = ctx.env.task if ctx.env else ""
            if not topic:
                return

            # Reduced from 8s to 5s for interactive latency.
            similar_outcomes = await asyncio.wait_for(
                adapter.find_similar_outcomes(query=topic, limit=5),
                timeout=5.0,
            )

            if not similar_outcomes:
                return

            # Format outcome items as context
            lines: list[str] = [
                "## PAST DECISION OUTCOMES",
                "The following outcomes were observed from similar past decisions.",
                "Use these to avoid past mistakes and build on past successes:\n",
            ]

            for item in similar_outcomes:
                meta = item.metadata or {}
                outcome_type = meta.get("outcome_type", "unknown")
                impact_score = meta.get("impact_score", 0.0)
                lessons = meta.get("lessons_learned", "")
                kpi_deltas = meta.get("kpi_deltas", {})

                # Map outcome type to label
                type_label = outcome_type.upper()
                impact_pct = (
                    f"{impact_score:.0%}" if isinstance(impact_score, (int, float)) else "N/A"
                )

                content_preview = item.content[:300]
                if len(item.content) > 300:
                    content_preview += "..."

                lines.append(f"- **[{type_label}, {impact_pct} impact]** {content_preview}")

                if lessons:
                    lesson_preview = lessons[:200]
                    if len(lessons) > 200:
                        lesson_preview += "..."
                    lines.append(f"  Lesson: {lesson_preview}")

                if kpi_deltas:
                    delta_strs = [
                        f"{k}: {v:+.2f}" if isinstance(v, float) else f"{k}: {v}"
                        for k, v in list(kpi_deltas.items())[:3]
                    ]
                    lines.append(f"  KPI changes: {', '.join(delta_strs)}")

            lines.append("\nConsider these outcomes when evaluating proposals.")

            outcome_text = "\n".join(lines)

            # Set on prompt builder or fall back to env.context
            prompt_builder = getattr(ctx, "_prompt_builder", None)
            if prompt_builder and hasattr(prompt_builder, "set_outcome_context"):
                prompt_builder.set_outcome_context(outcome_text)
            else:
                if ctx.env.context:
                    ctx.env.context += "\n\n" + outcome_text
                else:
                    ctx.env.context = outcome_text

            logger.info(
                "[outcome_context] Injected %d past decision outcomes into debate context",
                len(similar_outcomes),
            )

        except asyncio.TimeoutError:
            logger.warning("[outcome_context] Outcome context fetch timed out")
        except (RuntimeError, AttributeError, TypeError, ValueError, OSError) as e:
            logger.debug("[outcome_context] Outcome context injection failed: %s", e)

    async def _perform_pre_debate_research(self, ctx: DebateContext) -> None:
        """Perform pre-debate research if enabled."""
        if not self.protocol or not getattr(self.protocol, "enable_research", False):
            return

        if not self._perform_research:
            return

        try:
            logger.info("research_start phase=research")
            research_context = await self._perform_research(ctx.env.task)
            if research_context:
                logger.info("research_complete chars=%s", len(research_context))
                ctx.research_context = research_context
                if ctx.env.context:
                    ctx.env.context += "\n\n" + research_context
                else:
                    ctx.env.context = research_context
            else:
                logger.info("research_empty")
        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:  # noqa: BLE001 - phase isolation
            logger.warning("research_error error=%s", e)
            # Continue without research - don't break the debate
        except Exception as e:  # noqa: BLE001 - provider SDK exceptions (e.g. quota) should not fail debate
            logger.warning("research_error_unexpected error=%s", e)
            # Continue without research - don't break the debate

    async def _collect_evidence(self, ctx: DebateContext) -> None:
        """Collect evidence from configured connectors for debate grounding.

        This auto-collects citations and snippets from connectors like:
        - local_docs: Local documentation
        - github: Code and documentation from GitHub
        - web: Web search results

        Evidence is stored in ctx.evidence_pack and injected into env.context.
        """
        if not self.evidence_collector:
            return

        if not self.protocol or not getattr(self.protocol, "enable_evidence_collection", True):
            return

        try:
            logger.info("evidence_collection_start phase=evidence")
            # Reduced from 15s to 8s -- evidence collection runs as a background
            # task and the debate proceeds without it if slow.
            evidence_pack = await asyncio.wait_for(
                self.evidence_collector.collect_evidence(ctx.env.task),
                timeout=8.0,
            )

            if evidence_pack and evidence_pack.snippets:
                ctx.evidence_pack = evidence_pack
                evidence_context = evidence_pack.to_context_string()
                logger.info(
                    "evidence_collection_complete snippets=%s sources=%s",
                    len(evidence_pack.snippets),
                    evidence_pack.total_searched,
                )

                # Inject evidence into environment context
                if ctx.env.context:
                    ctx.env.context += "\n\n" + evidence_context
                else:
                    ctx.env.context = evidence_context
            else:
                logger.info("evidence_collection_empty")

            # Collect evidence from skills if enabled
            if self.enable_skills and self.skill_registry:
                skill_snippets = await self._collect_skill_evidence(ctx.env.task)
                if skill_snippets:
                    if ctx.evidence_pack is None:
                        # Create minimal evidence pack if none exists
                        from aragora.reasoning.evidence_collector import EvidencePack

                        ctx.evidence_pack = EvidencePack(snippets=[], total_searched=0)
                    ctx.evidence_pack.snippets.extend(skill_snippets)
                    logger.info("skill_evidence_collected snippets=%s", len(skill_snippets))

        except asyncio.TimeoutError:
            logger.warning("evidence_collection_timeout")
        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:  # noqa: BLE001 - phase isolation
            logger.warning("evidence_collection_error error=%s", e)
            # Continue without evidence - don't break the debate

    async def _collect_skill_evidence(self, task: str) -> list:
        """Collect evidence from debate-compatible skills.

        Invokes all skills tagged with 'debate' capability and converts
        their outputs to EvidenceSnippet format for injection into context.

        Args:
            task: The debate task/query to collect evidence for

        Returns:
            List of EvidenceSnippet objects from skill invocations
        """
        if not self.skill_registry or not self.enable_skills:
            return []

        snippets = []
        try:
            from aragora.reasoning.evidence_collector import EvidenceSnippet
            from aragora.skills import SkillCapability, SkillContext, SkillStatus

            # Create skill execution context
            skill_ctx = SkillContext(
                user_id="debate-system",
                permissions=["debate:evidence"],
                config={"source": "context_initializer", "task": task[:200]},
            )

            # Find skills tagged for debate evidence collection
            debate_skills = []
            for manifest in self.skill_registry.list_skills():
                # Check if skill has EXTERNAL_API capability and is debate-compatible
                if SkillCapability.EXTERNAL_API in manifest.capabilities:
                    # Check for debate tag in tags list
                    if "debate" in manifest.tags:
                        debate_skills.append(manifest)
                    # Or check if it's a web search skill (commonly useful for debates)
                    elif manifest.name in ("web_search", "search", "research"):
                        debate_skills.append(manifest)

            if not debate_skills:
                logger.debug("[skills] No debate-compatible skills found")
                return []

            # Invoke skills in parallel with timeout
            async def invoke_skill(skill_manifest):
                try:
                    result = await asyncio.wait_for(
                        self.skill_registry.invoke(
                            skill_manifest.name,
                            {"query": task},
                            skill_ctx,
                        ),
                        timeout=10.0,
                    )
                    if result.status == SkillStatus.SUCCESS and result.data:
                        exec_time_ms = (
                            int(result.duration_seconds * 1000) if result.duration_seconds else None
                        )
                        return EvidenceSnippet(
                            content=str(result.data)[:2000],  # Limit size
                            source=f"skill:{skill_manifest.name}",
                            relevance=0.7,  # Base relevance for skill evidence
                            metadata={
                                "skill": skill_manifest.name,
                                "skill_version": skill_manifest.version,
                                "execution_time_ms": exec_time_ms,
                            },
                        )
                except asyncio.TimeoutError:
                    logger.debug("[skills] Timeout invoking %s", skill_manifest.name)
                except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:  # noqa: BLE001 - phase isolation
                    logger.debug("[skills] Error invoking %s: %s", skill_manifest.name, e)
                return None

            results = await asyncio.gather(
                *[invoke_skill(s) for s in debate_skills],
                return_exceptions=True,
            )

            for result in results:
                if isinstance(result, EvidenceSnippet):
                    snippets.append(result)

            logger.info("[skills] Collected %s evidence snippets from skills", len(snippets))

        except ImportError as e:
            logger.debug("[skills] Evidence collection skipped (missing imports): %s", e)
        except (RuntimeError, AttributeError, ImportError) as e:  # noqa: BLE001 - phase isolation
            logger.warning("[skills] Evidence collection error: %s", e)

        return snippets

    async def await_background_context(self, ctx: DebateContext) -> None:
        """Await and cleanup background research/evidence tasks.

        Called before round 2 to ensure research context is available for critiques.
        This method is safe to call multiple times - completed tasks are cleaned up.
        """
        tasks = []
        task_names = []

        if ctx.background_research_task and not ctx.background_research_task.done():
            tasks.append(ctx.background_research_task)
            task_names.append("research")

        if ctx.background_evidence_task and not ctx.background_evidence_task.done():
            tasks.append(ctx.background_evidence_task)
            task_names.append("evidence")

        if not tasks:
            return

        logger.info("awaiting_background_context tasks=%s", task_names)

        try:
            # Wait for background tasks to complete before round 2.
            # Reduced from 30s to 10s to avoid stalling the debate.
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=10.0,
            )
            logger.info("background_context_complete")
        except asyncio.TimeoutError:
            logger.warning("background_context_timeout")
            # Cancel any still-running tasks
            for task in tasks:
                if not task.done():
                    task.cancel()

        # Clear task references
        ctx.background_research_task = None
        ctx.background_evidence_task = None

    def _init_context_messages(self, ctx: DebateContext) -> None:
        """Initialize context messages for fork debates."""
        from aragora.core import Message

        if not self.initial_messages:
            return

        for msg in self.initial_messages:
            if isinstance(msg, dict) and "content" in msg:
                ctx.context_messages.append(
                    Message(
                        agent=msg.get("agent", "previous"),
                        content=msg["content"],
                        role=msg.get("role", "assistant"),
                        round=-1,  # Mark as pre-debate context
                    )
                )

        if ctx.context_messages:
            logger.debug("fork_context loaded %s initial messages", len(ctx.context_messages))

    def _select_proposers(self, ctx: DebateContext) -> None:
        """Select proposers from agent list."""
        ctx.proposers = [a for a in ctx.agents if a.role == "proposer"]

        if not ctx.proposers and ctx.agents:
            # Default to first agent if no dedicated proposers
            ctx.proposers = [ctx.agents[0]]

    async def _compress_context_with_rlm(self, ctx: DebateContext) -> None:
        """
        Compress accumulated context using Recursive Language Models (RLM).

        Uses AragoraRLM which routes to TRUE RLM (REPL-based) when the official
        library is installed, falling back to compression-based approach otherwise.

        Based on the paper "Recursive Language Models" (arXiv:2512.24601),
        this enables agents to efficiently navigate long content by:
        - TRUE RLM: Model writes code to programmatically examine context
        - Fallback: Creates hierarchical summaries for context compression

        This is particularly valuable when context exceeds agent context windows,
        as it maintains semantic fidelity while enabling 100x longer content.
        """
        if not self._rlm:
            return

        try:
            context_content = ctx.env.context or ""
            if len(context_content) < 1000:
                # Skip compression for very short context
                logger.debug("[rlm] Context too short for compression, skipping")
                return

            # Estimate tokens
            estimated_tokens = len(context_content) // 4

            logger.info(
                "[rlm] Compressing context: %d chars (~%d tokens)",
                len(context_content),
                estimated_tokens,
            )

            # Determine source type from context content
            source_type = "text"
            if "## Round" in context_content or "Proposal" in context_content:
                source_type = "debate"
            elif "def " in context_content or "class " in context_content:
                source_type = "code"

            # Compress using AragoraRLM (routes to TRUE RLM if available)
            compression_result = await asyncio.wait_for(
                self._rlm.compress_and_query(
                    query="Create a comprehensive summary preserving key information",
                    content=context_content,
                    source_type=source_type,
                ),
                timeout=30.0,  # 30 second timeout for compression
            )

            # Store summary in context
            if compression_result and compression_result.answer:
                ctx.rlm_compressed_context = compression_result.answer

                # Wire RLM context into prompt builder for agent drill-down
                prompt_builder = getattr(ctx, "_prompt_builder", None)
                if (
                    prompt_builder
                    and hasattr(prompt_builder, "set_rlm_context")
                    and _RLMContextClass
                ):
                    try:
                        from aragora.rlm.types import AbstractionLevel, AbstractionNode

                        summary_node = AbstractionNode(
                            id="compression_summary",
                            level=AbstractionLevel.SUMMARY,
                            content=compression_result.answer,
                            token_count=len(compression_result.answer) // 4,
                        )
                        rlm_ctx = _RLMContextClass(
                            original_content=context_content,
                            original_tokens=estimated_tokens,
                            levels={AbstractionLevel.SUMMARY: [summary_node]},
                            nodes_by_id={"compression_summary": summary_node},
                            source_type=source_type,
                            compression_stats={
                                "used_true_rlm": getattr(
                                    compression_result, "used_true_rlm", False
                                ),
                                "used_compression_fallback": getattr(
                                    compression_result, "used_compression_fallback", False
                                ),
                            },
                        )
                        prompt_builder.set_rlm_context(rlm_ctx)
                        logger.info("[rlm] Set hierarchical RLM context on prompt builder")
                    except (ImportError, TypeError, AttributeError) as exc:
                        logger.debug("[rlm] Could not set RLM context on prompt builder: %s", exc)

                # Log which approach was used
                if compression_result.used_true_rlm:
                    logger.info(
                        "[rlm] Context compressed using TRUE RLM "
                        "(model wrote code to examine content)"
                    )
                elif compression_result.used_compression_fallback:
                    logger.info("[rlm] Context compressed using compression fallback")

                # Calculate compression stats
                compressed_tokens = len(compression_result.answer) // 4
                reduction = ((estimated_tokens - compressed_tokens) / estimated_tokens) * 100

                logger.info(
                    "[rlm] Context compressed: %d → %d tokens (%.0f%% reduction)",
                    estimated_tokens,
                    compressed_tokens,
                    reduction,
                )

                # Emit Prometheus metrics for RLM compression
                try:
                    from aragora.server.prometheus_rlm import record_rlm_compression

                    record_rlm_compression(
                        source_type=source_type,
                        original_tokens=estimated_tokens,
                        compressed_tokens=compressed_tokens,
                        levels=1,
                        success=True,
                    )
                except ImportError:
                    pass

                # Optionally replace context with summary for agents with small windows
                if hasattr(ctx, "use_compressed_context") and ctx.use_compressed_context:
                    if len(compression_result.answer) < len(context_content):
                        ctx.env.context = (
                            "## COMPRESSED CONTEXT (full context available on request)\n\n"
                            + compression_result.answer
                        )
                    logger.info("[rlm] Replaced context with summary level")

        except asyncio.TimeoutError:
            logger.warning("[rlm] Context compression timed out after 30s")
            try:
                from aragora.server.prometheus_rlm import record_rlm_compression

                record_rlm_compression(
                    source_type=source_type,
                    original_tokens=estimated_tokens,
                    compressed_tokens=0,
                    success=False,
                )
            except (ImportError, NameError):
                pass
        except Exception as e:  # noqa: BLE001 - provider SDK boundary (issue #8101)
            # Provider SDK errors (e.g. openai.AuthenticationError on a missing
            # key) are plain Exception subclasses, not RuntimeError. Context
            # compression is an optimization: degrade to uncompressed context
            # with a logged note — never fail the context-init phase.
            logger.warning(
                "[rlm] Context compression skipped (provider/SDK error); "
                "continuing with uncompressed context: %s",
                e,
            )
            try:
                from aragora.server.prometheus_rlm import record_rlm_compression

                record_rlm_compression(
                    source_type=source_type,
                    original_tokens=estimated_tokens,
                    compressed_tokens=0,
                    success=False,
                )
            except (ImportError, NameError):
                pass
            # Continue without compressed context - don't break the debate
