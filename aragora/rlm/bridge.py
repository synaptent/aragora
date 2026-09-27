"""
Bridge layer between official RLM library and Aragora.

This module provides Aragora-specific adapters that work with
the official RLM library (github.com/alexzhang13/rlm).

## TRUE RLM vs COMPRESSION

This module prioritizes TRUE RLM (REPL-based recursive decomposition) over
compression-based approaches. Per the official RLM methodology:

**True RLM** (primary, when `rlm` package is installed):
- Model recursively calls itself via REPL
- Context stored as Python variables (NOT stuffed in prompt)
- Model WRITES CODE to query/grep/partition context
- Model has ACTIVE AGENCY in context management

**Compression** (fallback only, when `rlm` package unavailable):
- Pre-processing hierarchical summarization
- HierarchicalCompressor creates 5-level summaries
- Used ONLY when official RLM is not installed

The official library handles:
- REPL environment isolation (Docker, Modal, local)
- Backend abstraction (OpenAI, Anthropic, vLLM, etc.)
- Trajectory logging and visualization

Aragora adapters handle:
- Debate history formatting for programmatic access
- Knowledge Mound integration
- Aragora agent wrapping

Usage:
    from aragora.rlm.bridge import AragoraRLM, DebateContextAdapter

    # Create RLM with Aragora integration
    rlm = AragoraRLM(backend="openai", model="gpt-4")

    # Process long debate history
    adapter = DebateContextAdapter()
    context = adapter.format_for_rlm(debate_result)

    # Query with RLM (uses TRUE RLM if available, compression as fallback)
    answer = await rlm.query("What consensus was reached?", context)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from collections.abc import Callable

from aragora.config.secrets import get_secret_presence

logger = logging.getLogger(__name__)

# Credential env vars per RLM backend (issue #8101: never hard-require an
# OpenAI key — route to a configured provider or skip TRUE RLM init).
_BACKEND_CREDENTIAL_ENVS: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}


def _secret_configured(name: str) -> bool:
    """Presence-only check honoring strict-secrets mode (no value exposure)."""
    return get_secret_presence(name).source in {"aws", "env"}


# Check if official RLM is available.
# import_rlm_guarded: importing rlm triggers a load_dotenv() side effect that
# can inject a repository .env into os.environ process-wide (#8277); the
# helper serializes the one real import so no concurrent caller can
# interleave environ snapshots/restores.
from aragora.utils.env import import_rlm_guarded

try:
    OfficialRLM = import_rlm_guarded().RLM
    HAS_OFFICIAL_RLM = True
except (ImportError, AttributeError):
    HAS_OFFICIAL_RLM = False
    OfficialRLM = None

from .types import (
    AbstractionLevel,
    RLMConfig,
    RLMContext,
    RLMResult,
)
from .compressor import HierarchicalCompressor

# Debate-optimized system prompt for TRUE RLM
DEBATE_RLM_SYSTEM_PROMPT = """You are analyzing a multi-agent debate transcript using TRUE RLM.
The debate context is stored as Python variables in your REPL environment.

## Available Functions

### Core RLM Functions
- `llm_query(prompt)` - Recursively call yourself on a sub-problem
- `llm_query_batched([prompt1, prompt2, ...])` - Batch multiple queries for efficiency
- `FINAL(answer)` - Signal your final answer
- `FINAL_VAR(variable)` - Signal a variable as the final answer

### Debate Navigation
- `load_debate_context(result)` - Load debate into indexed structure
- `get_round(ctx, n)` - Get messages from round n
- `get_proposals_by_agent(ctx, name)` - Get agent's messages
- `search_debate(ctx, pattern)` - Grep debate content
- `partition_debate(ctx, by)` - Partition by "round" or "agent"

### Knowledge Navigation
- `load_knowledge_context(mound, ws_id)` - Load knowledge mound
- `get_facts(ctx, query)` - Query facts
- `search_knowledge(ctx, pattern)` - Search knowledge items

### Memory Navigation
- `load_memory_context(continuum)` - Load memory tiers
- `search_memory(ctx, pattern)` - Search across memory tiers
- `filter_by_importance(entries, threshold)` - Filter by importance

### Unified Memory Navigation (cross-system)
- `search_all(query, limit, sources)` - Search across ALL memory systems
- `build_context_hierarchy(topic, max_items)` - Build navigable context from all systems
- `drill_into(source, item_id)` - Get detailed view of a specific item
- `get_by_surprise(min_surprise)` - Get high-surprise items (Titans/MIRAS insight)
- `filter_by_source(items, source)` - Filter by source system
- `filter_by_confidence(items, threshold)` - Filter by confidence score
- `sort_by_confidence(items)` - Sort by confidence
- `sort_by_surprise(items)` - Sort by surprise score

## Strategy Guidance

For debate analysis, use batched queries to process rounds in parallel:
```python
rounds = partition_debate(debate, "round")
summaries = llm_query_batched([
    f"Summarize round {r}: {[m['content'][:200] for m in msgs]}"
    for r, msgs in rounds.items()
])
FINAL("\\n".join(summaries))
```

For agent comparison:
```python
agents = debate.agent_names
comparisons = llm_query_batched([
    f"What was {agent}'s main argument? Messages: {[m['content'][:200] for m in debate.by_agent.get(agent, [])]}"
    for agent in agents
])
FINAL("\\n".join(f"{a}: {c}" for a, c in zip(agents, comparisons)))
```
"""

# Import extracted adapter classes for backwards compatibility
from .debate_adapter import DebateContextAdapter
from .knowledge_adapter import KnowledgeMoundAdapter
from .hierarchy_cache import RLMHierarchyCache
from .streaming_mixin import RLMStreamingMixin


@dataclass
class RLMBackendConfig:
    """Configuration for RLM backend."""

    backend: str = "openai"  # openai, anthropic, openrouter, litellm
    model_name: str = "gpt-4o"
    sub_model_name: str = "gpt-4o-mini"
    fallback_backend: str | None = None
    fallback_model_name: str | None = None

    # Multi-backend routing: cheaper sub-model for recursive sub-queries
    sub_backend: str | None = None  # Backend for sub-LM calls
    sub_backend_model: str | None = None  # Model for sub-LM calls

    # Environment configuration (REPL sandbox type)
    environment_type: str = "local"  # local, docker, modal
    environment_timeout: int = 120
    max_depth: int = 1  # Maximum recursion depth
    max_iterations: int = 30  # Maximum iterations per execution

    # Official RLM kwargs
    verbose: bool = False
    persistent: bool = False  # Keep environment alive between calls

    # Deep integration
    trajectory_log_dir: str | None = None  # Directory for trajectory JSONL logs
    custom_system_prompt: str | None = None  # Custom system prompt for RLM


class AragoraRLM(RLMStreamingMixin):
    """
    Aragora-integrated RLM interface.

    Prioritizes TRUE RLM (REPL-based recursive decomposition) over compression:

    1. TRUE RLM (primary): Model writes code to query context via REPL
       - Used when official `rlm` package is installed
       - Model has agency in deciding how to process context
       - Context stored as variables, not stuffed in prompt

    2. COMPRESSION (fallback only): HierarchicalCompressor summarization
       - Used ONLY when official `rlm` package is NOT installed
       - Pre-processing that creates 5-level summaries

    Also provides:
    - Debate history formatting
    - Knowledge Mound integration
    - Aragora agent wrapping
    """

    def __init__(
        self,
        backend_config: RLMBackendConfig | None = None,
        aragora_config: RLMConfig | None = None,
        agent_registry: Any | None = None,
        hierarchy_cache: RLMHierarchyCache | None = None,
        knowledge_mound: Any | None = None,  # For auto-creating cache
        enable_caching: bool = True,  # Enable compression caching
        belief_network: Any | None = None,  # For belief-augmented reasoning
        supermemory_backend: Any | None = None,  # Supermemory fallback store
    ):
        """
        Initialize Aragora RLM.

        Args:
            backend_config: Configuration for RLM backend
            aragora_config: Aragora-specific RLM configuration
            agent_registry: Aragora agent registry for fallback
            hierarchy_cache: Optional pre-configured RLMHierarchyCache
            knowledge_mound: Optional KnowledgeMound for persistent caching
            enable_caching: Whether to cache compression hierarchies
            belief_network: Optional BeliefNetwork for belief-augmented reasoning
        """
        self.backend_config = backend_config or RLMBackendConfig()
        self.aragora_config = aragora_config or RLMConfig()
        self.agent_registry = agent_registry
        self.enable_caching = enable_caching
        self._supermemory_backend = supermemory_backend

        # Belief network integration (Phase 2: RLM-Belief Bridge)
        self._belief_network = belief_network
        self._belief_context_adapter: Any | None = None
        if belief_network:
            try:
                from .belief_context_adapter import BeliefContextAdapter

                self._belief_context_adapter = BeliefContextAdapter(belief_network=belief_network)
            except ImportError:
                logger.debug("BeliefContextAdapter not available")

        self._official_rlm: Any | None = None
        self._fallback_rlm: Any | None = None
        self._apply_backend_env_overrides()
        # Compressor is ONLY used as fallback when official RLM unavailable
        self._compressor = HierarchicalCompressor(
            config=self.aragora_config,
            agent_call=self._agent_call,
        )

        # Initialize hierarchy cache for compression result reuse
        self._hierarchy_cache: RLMHierarchyCache | None = hierarchy_cache
        if self.enable_caching and self._hierarchy_cache is None:
            # Auto-create cache if knowledge_mound provided
            self._hierarchy_cache = RLMHierarchyCache(knowledge_mound=knowledge_mound)

        # Trajectory logging directory
        self._trajectory_log_dir: str | None = self.backend_config.trajectory_log_dir

        # Track which approach was used (for debugging/telemetry)
        self._last_query_used_true_rlm: bool = False
        self._last_query_used_compression_fallback: bool = False

        if HAS_OFFICIAL_RLM:
            if self._backend_has_usable_credential():
                self._init_official_rlm()
            else:
                # Issue #8101: constructing an OpenAI-keyed RLM without a key
                # raises AuthenticationError mid-debate (context_initializer).
                # Skip TRUE RLM with a logged note and degrade gracefully.
                logger.warning(
                    "[AragoraRLM] No usable credential for RLM backend '%s'; "
                    "skipping TRUE RLM init and using compression fallback",
                    self.backend_config.backend,
                )
        else:
            logger.warning(
                "[AragoraRLM] Official RLM library not installed. "
                "Will use compression-based FALLBACK for all queries. "
                "For TRUE RLM (REPL-based), install with: pip install rlm"
            )

    def _backend_has_usable_credential(self) -> bool:
        """Whether the selected backend has a configured credential.

        Unknown backends (e.g. litellm, custom) are never blocked — we cannot
        prove they lack credentials.
        """
        keys = _BACKEND_CREDENTIAL_ENVS.get(self.backend_config.backend)
        if not keys:
            return True
        return any(_secret_configured(key) for key in keys)

    def _apply_backend_env_overrides(self) -> None:
        """Apply environment overrides for RLM backend selection."""
        env_backend = os.environ.get("ARAGORA_RLM_BACKEND") or os.environ.get(
            "ARAGORA_RLM_PROVIDER"
        )
        env_model = os.environ.get("ARAGORA_RLM_MODEL") or os.environ.get("ARAGORA_RLM_MODEL_NAME")
        env_fallback_backend = os.environ.get("ARAGORA_RLM_FALLBACK_BACKEND")
        env_fallback_model = os.environ.get("ARAGORA_RLM_FALLBACK_MODEL")
        if env_backend:
            self.backend_config.backend = env_backend.strip()
        if env_model:
            self.backend_config.model_name = env_model.strip()
        if env_fallback_backend:
            self.backend_config.fallback_backend = env_fallback_backend.strip()
        if env_fallback_model:
            self.backend_config.fallback_model_name = env_fallback_model.strip()

        # Issue #8101: the default "openai" backend must not hard-require an
        # OpenAI key. If OpenAI is unconfigured (or blocked by strict-secrets
        # mode) and the backend was not explicitly requested, route the
        # primary backend to a configured provider instead.
        if (
            not env_backend
            and self.backend_config.backend == "openai"
            and not _secret_configured("OPENAI_API_KEY")
        ):
            if _secret_configured("OPENROUTER_API_KEY"):
                self.backend_config.backend = "openrouter"
                logger.info(
                    "[AragoraRLM] OPENAI_API_KEY not configured; routing RLM backend to openrouter"
                )
            elif _secret_configured("ANTHROPIC_API_KEY"):
                self.backend_config.backend = "anthropic"
                if not env_model:
                    # Default openai model names are meaningless on the
                    # anthropic backend; use the repo's canonical default
                    # (see aragora/agents/api_agents/anthropic.py).
                    self.backend_config.model_name = os.environ.get(
                        "ARAGORA_RLM_ANTHROPIC_MODEL", "claude-opus-5"
                    )
                logger.info(
                    "[AragoraRLM] OPENAI_API_KEY not configured; routing RLM backend to anthropic"
                )

        if (
            self.backend_config.fallback_backend is None
            and self.backend_config.backend == "openai"
            and get_secret_presence("OPENROUTER_API_KEY").source in {"aws", "env"}
        ):
            self.backend_config.fallback_backend = "openrouter"

        if self.backend_config.backend == "openrouter":
            self.backend_config.model_name = self._normalize_openrouter_model(
                self.backend_config.model_name
            )
        if self.backend_config.fallback_backend == "openrouter":
            fallback_model = (
                self.backend_config.fallback_model_name or self.backend_config.model_name
            )
            self.backend_config.fallback_model_name = self._normalize_openrouter_model(
                fallback_model
            )

    @staticmethod
    def _normalize_openrouter_model(model_name: str) -> str:
        """Ensure OpenRouter model names include a provider prefix."""
        if "/" in model_name:
            return model_name
        return f"openai/{model_name}"

    def set_belief_network(self, belief_network: Any) -> None:
        """Set or update the belief network for belief-augmented reasoning.

        Args:
            belief_network: BeliefNetwork instance to use for belief context
        """
        self._belief_network = belief_network
        if belief_network:
            try:
                from .belief_context_adapter import BeliefContextAdapter

                if self._belief_context_adapter:
                    self._belief_context_adapter.set_belief_network(belief_network)
                else:
                    self._belief_context_adapter = BeliefContextAdapter(
                        belief_network=belief_network
                    )
            except ImportError:
                logger.debug("BeliefContextAdapter not available")

    def get_belief_context_summary(self, topic: str) -> str:
        """Get a text summary of belief context for a topic.

        Args:
            topic: The topic to build belief context for

        Returns:
            Formatted text summary of relevant beliefs and cruxes
        """
        if self._belief_context_adapter:
            return self._belief_context_adapter.build_belief_context_summary(topic)
        return ""

    def _extract_topic_from_query(self, query: str) -> str:
        """Extract a topic string from a query for belief context lookup.

        Args:
            query: The query string

        Returns:
            Extracted topic (first 100 chars, trimmed to last word boundary)
        """
        # Simple extraction: take first 100 chars, trim to word boundary
        topic = query[:100]
        if len(query) > 100:
            # Find last space to avoid cutting words
            last_space = topic.rfind(" ")
            if last_space > 50:
                topic = topic[:last_space]
        return topic.strip()

    async def build_context(
        self,
        content: str,
        source_type: str = "text",
        source_path: str | None = None,
        source_root: str | None = None,
        source_manifest: str | None = None,
    ) -> RLMContext:
        """
        Build an RLMContext for querying.

        If TRUE RLM is available, return a lightweight context with
        optional externalized content for REPL access. If TRUE RLM is
        not available, fall back to hierarchical compression.
        """
        from aragora.rlm.exceptions import RLMContextOverflowError

        content_bytes = len(content.encode("utf-8"))
        if content_bytes > self.aragora_config.max_content_bytes:
            raise RLMContextOverflowError(
                f"Context size {content_bytes} exceeds max_content_bytes="
                f"{self.aragora_config.max_content_bytes}",
                content_size=content_bytes,
                max_size=self.aragora_config.max_content_bytes,
            )

        inline_content = content
        externalized_path = source_path
        if content_bytes > self.aragora_config.externalize_content_bytes:
            if externalized_path is None:
                externalized_path = self._externalize_content(content)
            inline_limit = self.aragora_config.externalize_content_bytes
            inline_content = content[:inline_limit]

        metadata = {
            "externalized": externalized_path is not None,
            "content_path": externalized_path,
            "manifest_path": source_manifest,
            "source_root": source_root,
        }

        if self._official_rlm:
            return RLMContext(
                original_content=inline_content,
                original_tokens=max(1, content_bytes // 4),
                source_type=source_type,
                source_path=externalized_path,
                source_root=source_root,
                source_manifest=source_manifest,
                metadata=metadata,
            )

        compression = await self._compressor.compress(inline_content, source_type)
        context = compression.context
        context.source_type = source_type
        context.source_path = externalized_path
        context.source_root = source_root
        context.source_manifest = source_manifest
        context.metadata.update(metadata)
        return context

    def _externalize_content(self, content: str) -> str:
        """Persist large context to a temp file for TRUE RLM REPL access."""
        fd, path = tempfile.mkstemp(prefix="aragora_rlm_", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        logger.info("[AragoraRLM] Externalized context to %s", path)
        return path

    def _init_official_rlm(self) -> None:
        """Initialize the official RLM library with deep integration features."""
        try:
            # Build environment kwargs if timeout specified
            env_kwargs = None
            if self.backend_config.environment_timeout != 120:
                env_kwargs = {"timeout": self.backend_config.environment_timeout}

            # Trajectory logging setup
            rlm_logger = None
            if self._trajectory_log_dir:
                try:
                    from rlm.logger import RLMLogger

                    Path(self._trajectory_log_dir).mkdir(parents=True, exist_ok=True)
                    rlm_logger = RLMLogger(log_dir=self._trajectory_log_dir)
                    logger.info(
                        "[AragoraRLM] Trajectory logging enabled: %s",
                        self._trajectory_log_dir,
                    )
                except ImportError:
                    logger.debug("RLMLogger not available, trajectory logging disabled")

            # Multi-backend routing: sub-backend for recursive sub-queries
            other_backends = None
            other_backend_kwargs = None
            sub_backend = self.backend_config.sub_backend
            sub_model = (
                self.backend_config.sub_backend_model
                or os.environ.get("ARAGORA_RLM_SUB_MODEL")
                or self.backend_config.sub_model_name
            )
            if sub_backend:
                other_backends = [sub_backend]
                other_backend_kwargs = [{"model_name": sub_model}]

            # Custom system prompt (config > env var > None)
            system_prompt = (
                self.backend_config.custom_system_prompt
                or os.environ.get("ARAGORA_RLM_SYSTEM_PROMPT")
                or None
            )

            # Build init kwargs
            init_kwargs: dict[str, Any] = {
                "backend": self.backend_config.backend,
                "backend_kwargs": {"model_name": self.backend_config.model_name},
                "environment": self.backend_config.environment_type,
                "environment_kwargs": env_kwargs,
                "max_depth": self.backend_config.max_depth,
                "max_iterations": self.backend_config.max_iterations,
                "verbose": self.backend_config.verbose,
                "persistent": self.backend_config.persistent,
            }
            if rlm_logger is not None:
                init_kwargs["logger"] = rlm_logger
            if other_backends is not None:
                init_kwargs["other_backends"] = other_backends
                init_kwargs["other_backend_kwargs"] = other_backend_kwargs
            if system_prompt is not None:
                init_kwargs["system_prompt"] = system_prompt

            self._official_rlm = OfficialRLM(**init_kwargs)
            logger.info(
                "[AragoraRLM] Initialized TRUE RLM with backend=%s, model=%s, environment=%s",
                self.backend_config.backend,
                self.backend_config.model_name,
                self.backend_config.environment_type,
            )
            if self.backend_config.fallback_backend:
                fallback_kwargs: dict[str, Any] = {
                    "backend": self.backend_config.fallback_backend,
                    "backend_kwargs": {
                        "model_name": self.backend_config.fallback_model_name
                        or self.backend_config.model_name,
                    },
                    "environment": self.backend_config.environment_type,
                    "environment_kwargs": env_kwargs,
                    "max_depth": self.backend_config.max_depth,
                    "max_iterations": self.backend_config.max_iterations,
                    "verbose": self.backend_config.verbose,
                    "persistent": self.backend_config.persistent,
                }
                if rlm_logger is not None:
                    fallback_kwargs["logger"] = rlm_logger
                self._fallback_rlm = OfficialRLM(**fallback_kwargs)
                logger.info(
                    "[AragoraRLM] Initialized TRUE RLM fallback backend=%s, model=%s",
                    self.backend_config.fallback_backend,
                    self.backend_config.fallback_model_name or self.backend_config.model_name,
                )
        except (RuntimeError, ValueError, ImportError, OSError, TypeError) as e:
            logger.error("[AragoraRLM] Failed to initialize official RLM: %s", e)
            self._official_rlm = None
            self._fallback_rlm = None

    def _agent_call(self, prompt: str, model: str) -> str:
        """Call agent for compression/summarization."""
        if self._official_rlm:
            # Use official RLM for simple completions
            try:
                completion = self._official_rlm.completion(prompt)
                return completion.response
            except (RuntimeError, ValueError, ConnectionError, TimeoutError, OSError) as e:
                logger.warning("Official RLM call failed: %s", e)
                if self._fallback_rlm:
                    try:
                        completion = self._fallback_rlm.completion(prompt)
                        return completion.response
                    except (
                        RuntimeError,
                        ValueError,
                        ConnectionError,
                        TimeoutError,
                        OSError,
                    ) as fallback_exc:
                        logger.warning("Fallback RLM call failed: %s", fallback_exc)

        # Fallback to Aragora agent registry
        if self.agent_registry:
            try:
                agent = self.agent_registry.get_agent(model)
                return agent.complete(prompt)
            except (RuntimeError, ValueError, ConnectionError, TimeoutError, OSError) as e:
                logger.warning("Aragora agent call failed: %s", e)

        raise RuntimeError("No backend available for agent calls")

    async def query(
        self,
        query: str,
        context: RLMContext,
        strategy: str = "auto",
        inject_belief_context: bool = True,
    ) -> RLMResult:
        """
        Query using RLM over hierarchical context.

        Prioritizes TRUE RLM (REPL-based) when official library is available.
        Falls back to compression-based approach only when unavailable.

        Args:
            query: The query to answer
            context: Pre-compressed hierarchical context
            strategy: Decomposition strategy (auto, peek, grep, partition_map, etc.)
            inject_belief_context: Whether to inject belief network context

        Returns:
            RLMResult with answer and provenance. Check `used_true_rlm` and
            `used_compression_fallback` fields to see which approach was used.
        """
        # Reset tracking flags
        self._last_query_used_true_rlm = False
        self._last_query_used_compression_fallback = False

        # Reset belief context tracking
        belief_context_used = False
        if self._belief_context_adapter:
            self._belief_context_adapter.reset_tracking()

        # Build belief-augmented query if belief network available
        augmented_query = query
        if inject_belief_context and self._belief_context_adapter:
            try:
                # Extract topic from query for belief context
                topic = self._extract_topic_from_query(query)
                belief_summary = self._belief_context_adapter.build_belief_context_summary(topic)
                if belief_summary.strip():
                    augmented_query = f"{belief_summary}\n\n## Query\n{query}"
                    belief_context_used = True
                    logger.debug("Injected belief context for topic: %s", topic)
            except (RuntimeError, ValueError, AttributeError, TypeError) as e:
                logger.debug("Belief context injection skipped: %s", e)

        if self._official_rlm:
            # PRIMARY: Use TRUE RLM (REPL-based recursive decomposition)
            logger.info(
                "[AragoraRLM] Using TRUE RLM (REPL-based) for query - "
                "model will write code to examine context"
            )
            result = await self._true_rlm_query(augmented_query, context, strategy)
            result.used_true_rlm = self._last_query_used_true_rlm
            result.used_compression_fallback = self._last_query_used_compression_fallback
        else:
            # FALLBACK: Use compression-based approach
            logger.warning(
                "[AragoraRLM] Using COMPRESSION FALLBACK (official RLM not available) - "
                "context will be pre-summarized rather than model-driven"
            )
            self._last_query_used_compression_fallback = True
            result = await self._compression_fallback(augmented_query, context, strategy)
            result.used_true_rlm = False
            result.used_compression_fallback = True

        # Add belief context tracking to result
        result.belief_context_used = belief_context_used
        if self._belief_context_adapter:
            result.beliefs_consulted = self._belief_context_adapter.get_consulted_beliefs()
            result.cruxes_addressed = self._belief_context_adapter.get_consulted_cruxes()

        return result

    async def _true_rlm_query(
        self,
        query: str,
        context: RLMContext,
        strategy: str,
    ) -> RLMResult:
        """
        Query using TRUE RLM (REPL-based recursive decomposition).

        This is the CORRECT approach per official RLM methodology:
        - Model has access to context via REPL environment
        - Model WRITES CODE to query/grep/partition context
        - Model can recursively call itself on subsets
        - Model has ACTIVE AGENCY in deciding how to process context

        Falls back to compression ONLY if TRUE RLM fails.
        """
        import time as time_module

        # Format context for RLM REPL
        formatted = self._format_context_for_repl(context)

        # Get context at different abstraction levels
        summary_content = context.get_at_level(AbstractionLevel.SUMMARY) or ""
        abstract_content = context.get_at_level(AbstractionLevel.ABSTRACT) or ""

        # Externalize large context to a file to avoid prompt stuffing.
        # TRUE RLM expects context to live in the environment, not the prompt.
        use_external = self._should_externalize_context(context)
        context_file = self._ensure_context_file(context) if use_external else None

        # Build RLM prompt
        # The official RLM handles REPL interaction internally - model writes code
        # to decompose and query this context recursively.
        if context_file:
            metadata = getattr(context, "metadata", {}) or {}
            manifest_path = context.source_manifest or metadata.get("manifest_path", "")
            source_root = context.source_root or metadata.get("source_root", "")
            manifest_line = f"\nManifest: {manifest_path}" if manifest_path else ""
            root_line = f"\nRepo root: {source_root}" if source_root else ""
            rlm_prompt = f"""You are analyzing a hierarchical document context. Use Python code in the REPL to examine, grep, filter, and recursively process the context.

## Context Structure
{formatted["structure"]}

## Context Data

### Abstract Level
{abstract_content if abstract_content else "[No abstract available]"}

### Summary Level
{summary_content if summary_content else "[No summary available]"}

### Full Content (external file)
Context file: {context_file}{manifest_line}{root_line}

Use Python to read the file in chunks (do NOT load the entire file into memory).
Starter helpers you can paste into the REPL:

```
CONTEXT_FILE = r"{context_file}"

def read_chunk(offset=0, size=20000):
    with open(CONTEXT_FILE, "r", errors="ignore") as f:
        f.seek(offset)
        return f.read(size)

def grep_in_file(pattern, max_hits=50):
    import re
    hits = []
    with open(CONTEXT_FILE, "r", errors="ignore") as f:
        for line in f:
            if re.search(pattern, line):
                hits.append(line.strip())
                if len(hits) >= max_hits:
                    break
    return hits
```

## Instructions
1. Use Python code to programmatically examine the context
2. Use chunked reads or line-by-line scans; avoid loading full content
3. Use llm_query(prompt) to recursively call yourself on subsets
4. Call FINAL(answer) when you have the answer

## Task
Answer this question: {query}

Write Python code to analyze the context and call FINAL(answer) with your answer.
"""
        else:
            metadata = getattr(context, "metadata", {}) or {}
            manifest_path = context.source_manifest or metadata.get("manifest_path", "")
            source_root = context.source_root or metadata.get("source_root", "")
            extra_access = ""
            if manifest_path or source_root:
                extra_access = "\n\nExternal context:\n"
                if source_root:
                    extra_access += f"Repo root: {source_root}\n"
                if manifest_path:
                    extra_access += f"Manifest: {manifest_path}\n"
            rlm_prompt = f"""You are analyzing a hierarchical document context. Use Python code in the REPL to examine, grep, filter, and recursively process the context.

## Context Structure
{formatted["structure"]}

## Context Data

### Abstract Level
{abstract_content if abstract_content else "[No abstract available]"}

### Summary Level
{summary_content if summary_content else "[No summary available]"}

### Full Content ({context.original_tokens} tokens)
{context.original_content}

{extra_access}

## Instructions
1. Use Python code to programmatically examine the context
2. You can grep for patterns, filter sections, and partition data
3. Use llm_query(prompt) to recursively call yourself on subsets
4. Call FINAL(answer) when you have the answer

## Task
Answer this question: {query}

Write Python code to analyze the context and call FINAL(answer) with your answer.
"""

        start_time = time_module.perf_counter()
        try:
            official_rlm = self._official_rlm
            if official_rlm is None:
                raise RuntimeError("Official RLM is not initialized")
            # Run RLM completion (handles REPL internally)
            # The model writes code to examine context recursively
            completion = official_rlm.completion(
                rlm_prompt,
                root_prompt=query,  # Small prompt visible to root LM
            )

            time_module.perf_counter() - start_time

            # TRUE RLM succeeded
            self._last_query_used_true_rlm = True
            logger.info(
                f"[AragoraRLM] TRUE RLM query completed successfully "
                f"in {completion.execution_time:.2f}s"
            )

            # Extract trajectory data from RLM instance logger
            trajectory_log_path = None
            rlm_iterations = 0
            code_blocks_executed = 0
            if hasattr(official_rlm, "logger") and official_rlm.logger:
                rlm_log = official_rlm.logger
                trajectory_log_path = getattr(rlm_log, "log_path", None)
                if hasattr(rlm_log, "get_stats"):
                    stats = rlm_log.get_stats()
                    rlm_iterations = stats.get("iterations", 0)
                    code_blocks_executed = stats.get("code_blocks", 0)

            return RLMResult(
                answer=completion.response,
                nodes_examined=[],
                levels_traversed=[],
                citations=[],
                tokens_processed=context.original_tokens,
                sub_calls_made=0,
                time_seconds=completion.execution_time,
                confidence=0.8,
                uncertainty_sources=[],
                trajectory_log_path=trajectory_log_path,
                rlm_iterations=rlm_iterations,
                code_blocks_executed=code_blocks_executed,
            )

        except (RuntimeError, ValueError, ConnectionError, TimeoutError, OSError) as e:
            logger.error("[AragoraRLM] TRUE RLM query failed: %s", e)
            if self._fallback_rlm:
                try:
                    completion = self._fallback_rlm.completion(
                        rlm_prompt,
                        root_prompt=query,
                    )
                    self._last_query_used_true_rlm = True
                    logger.info("[AragoraRLM] TRUE RLM query succeeded via fallback backend")
                    return RLMResult(
                        answer=completion.response,
                        nodes_examined=[],
                        levels_traversed=[],
                        citations=[],
                        tokens_processed=context.original_tokens,
                        sub_calls_made=0,
                        time_seconds=completion.execution_time,
                        confidence=0.8,
                        uncertainty_sources=[],
                    )
                except (
                    RuntimeError,
                    ValueError,
                    ConnectionError,
                    TimeoutError,
                    OSError,
                ) as fallback_exc:
                    logger.warning("[AragoraRLM] Fallback TRUE RLM query failed: %s", fallback_exc)
            logger.warning(
                "[AragoraRLM] Falling back to COMPRESSION approach "
                "(this is suboptimal - TRUE RLM gives model agency)"
            )
            # Fall back to compression-based approach
            self._last_query_used_compression_fallback = True
            return await self._compression_fallback(query, context, strategy)

    def _should_externalize_context(self, context: RLMContext) -> bool:
        """Decide if context should be externalized to a file for TRUE RLM."""
        metadata = getattr(context, "metadata", {}) or {}
        if context.source_path or metadata.get("content_path"):
            return True
        try:
            content_bytes = len(context.original_content.encode("utf-8", errors="ignore"))
        except (UnicodeError, MemoryError, ValueError) as e:
            logger.debug("Failed to compute content bytes: %s: %s", type(e).__name__, e)
            content_bytes = 0
        threshold = getattr(self.aragora_config, "externalize_content_bytes", 0) or 0
        return threshold > 0 and content_bytes >= threshold

    def _ensure_context_file(self, context: RLMContext) -> str | None:
        """Ensure context is written to disk and return its path."""
        metadata = getattr(context, "metadata", {}) or {}
        content_path = context.source_path or metadata.get("content_path")
        if content_path:
            try:
                if Path(content_path).exists():
                    return content_path
            except (OSError, ValueError) as e:
                logger.debug("Failed to check context file path %s: %s", content_path, e)

        # No existing file; write if we have content
        if not context.original_content:
            return None

        # Choose directory
        context_dir = metadata.get("context_dir") or os.environ.get("ARAGORA_RLM_CONTEXT_DIR", "")
        if context_dir:
            base_dir = Path(context_dir)
        else:
            base_dir = Path(tempfile.gettempdir()) / "aragora_rlm"
        base_dir.mkdir(parents=True, exist_ok=True)

        # Content hash to dedupe
        content_hash = hashlib.sha256(
            context.original_content.encode("utf-8", errors="ignore")
        ).hexdigest()[:12]
        file_path = base_dir / f"rlm_context_{content_hash}.txt"

        if not file_path.exists():
            try:
                file_path.write_text(context.original_content)
            except OSError as e:
                logger.warning("[AragoraRLM] Failed to write context file: %s", e)
                return None

        metadata["content_path"] = str(file_path)
        context.metadata = metadata
        return str(file_path)

    async def _store_pre_compression(self, content: str, source_type: str) -> None:
        """Store pre-compression content in supermemory as fallback."""
        if not self._supermemory_backend:
            return
        try:
            if hasattr(self._supermemory_backend, "store"):
                store_fn = getattr(self._supermemory_backend, "store")
                if asyncio.iscoroutinefunction(store_fn):
                    await store_fn(
                        content=content,
                        metadata={"source_type": source_type, "role": "pre_compression_fallback"},
                    )
                else:
                    store_fn(
                        content=content,
                        metadata={"source_type": source_type, "role": "pre_compression_fallback"},
                    )
        except (RuntimeError, ValueError, OSError, AttributeError, TypeError) as exc:
            logger.warning("Supermemory pre-compression store failed: %s", exc)

    async def _check_supermemory_cache(self, query: str) -> str | None:
        """Check supermemory for pre-compression cached content."""
        if not self._supermemory_backend:
            return None
        try:
            if hasattr(self._supermemory_backend, "search"):
                search_fn = getattr(self._supermemory_backend, "search")
                if asyncio.iscoroutinefunction(search_fn):
                    results = await search_fn(query, limit=3)
                else:
                    results = search_fn(query, limit=3)
                for r in results or []:
                    meta = (
                        r.get("metadata", {}) if isinstance(r, dict) else getattr(r, "metadata", {})
                    )
                    if meta.get("role") == "pre_compression_fallback":
                        return (
                            r.get("content", "")
                            if isinstance(r, dict)
                            else getattr(r, "content", "")
                        )
        except (RuntimeError, ValueError, OSError, AttributeError, TypeError) as exc:
            logger.warning("Supermemory cache check failed: %s", exc)
        return None

    async def _compression_fallback(
        self,
        query: str,
        context: RLMContext,
        strategy: str,
    ) -> RLMResult:
        """
        FALLBACK: Query using compression-based approach.

        This is NOT true RLM - it pre-processes context via HierarchicalCompressor
        rather than giving the model agency to examine context programmatically.

        Used ONLY when:
        1. Official RLM library is not installed
        2. TRUE RLM query fails for some reason

        For true RLM behavior, install: pip install rlm
        """
        logger.debug(
            "[AragoraRLM] Executing COMPRESSION FALLBACK - "
            "context is pre-summarized, model doesn't write code to examine it"
        )

        # Check supermemory for pre-compression cached content
        cached = await self._check_supermemory_cache(query)
        if cached:
            logger.debug("[AragoraRLM] Found pre-compression content in supermemory cache")
            return RLMResult(
                answer=cached,
                nodes_examined=[],
                levels_traversed=[],
                citations=[],
                tokens_processed=len(cached) // 4,
                sub_calls_made=0,
                time_seconds=0.0,
                confidence=0.7,
                uncertainty_sources=[],
            )

        # Store pre-compression content in supermemory before compression
        if context.original_content:
            await self._store_pre_compression(context.original_content, context.source_type)

        from .types import DecompositionStrategy, RLMQuery
        from .strategies import get_strategy

        # Parse strategy
        try:
            strategy_enum = DecompositionStrategy(strategy)
        except ValueError:
            strategy_enum = DecompositionStrategy.AUTO

        # Create query
        rlm_query = RLMQuery(
            query=query,
            preferred_strategy=strategy_enum,
        )

        # Get and execute strategy (compression-based)
        strategy_impl = get_strategy(
            strategy_enum,
            self.aragora_config,
            self._agent_call_async,
        )

        result = await strategy_impl.execute(rlm_query, context)

        return RLMResult(
            answer=result.answer,
            nodes_examined=result.nodes_used,
            levels_traversed=[],
            citations=[],
            tokens_processed=result.tokens_examined,
            sub_calls_made=result.sub_calls,
            time_seconds=0.0,
            confidence=result.confidence,
            uncertainty_sources=[],
        )

    def _agent_call_async(self, prompt: str, model: str, context: str) -> str:
        """Async-compatible agent call."""
        full_prompt = f"{prompt}\n\nContext:\n{context}" if context else prompt
        return self._agent_call(full_prompt, model)

    def _format_context_for_repl(self, context: RLMContext) -> dict[str, str]:
        """Format context structure for REPL documentation."""
        structure_parts = []

        for level in [
            AbstractionLevel.ABSTRACT,
            AbstractionLevel.SUMMARY,
            AbstractionLevel.DETAILED,
            AbstractionLevel.FULL,
        ]:
            if level in context.levels:
                nodes = context.levels[level]
                structure_parts.append(
                    f"- {level.name}: {len(nodes)} nodes, "
                    f"~{sum(n.token_count for n in nodes)} tokens"
                )

        return {
            "structure": "\n".join(structure_parts) if structure_parts else "Flat content only",
        }

    def _get_node_dict(self, context: RLMContext, node_id: str) -> dict | None:
        """Get node as dictionary for REPL access."""
        node = context.get_node(node_id)
        if not node:
            return None
        return {
            "id": node.id,
            "level": node.level.name,
            "content": node.content,
            "token_count": node.token_count,
            "key_topics": node.key_topics,
            "child_ids": node.child_ids,
        }

    def _drill_down_dicts(self, context: RLMContext, node_id: str) -> list[dict]:
        """Drill down and return children as dictionaries."""
        children = context.drill_down(node_id)
        return [
            {
                "id": c.id,
                "level": c.level.name,
                "content": c.content[:500] + "..." if len(c.content) > 500 else c.content,
                "token_count": c.token_count,
            }
            for c in children
        ]

    async def compress_and_query(
        self,
        query: str,
        content: str,
        source_type: str = "text",
        use_cache: bool = True,
    ) -> RLMResult:
        """
        Convenience method: compress content and query in one step.

        Uses hierarchy cache to avoid recompressing similar content.

        Args:
            query: The query to answer
            content: Raw content to compress
            source_type: Type of content (text, debate, code)
            use_cache: Whether to use cached compression if available

        Returns:
            RLMResult with answer
        """
        compression = None

        # Try cache first if enabled
        if use_cache and self._hierarchy_cache:
            compression = await self._hierarchy_cache.get_cached(content, source_type)
            if compression:
                logger.debug(
                    "[AragoraRLM] Using cached compression (cache_stats=%s)",
                    self._hierarchy_cache.stats,
                )

        # Compress if not cached
        if compression is None:
            compression = await self._compressor.compress(content, source_type)

            # Store in cache for future use
            if use_cache and self._hierarchy_cache:
                await self._hierarchy_cache.store(content, source_type, compression)

        # Then query
        return await self.query(query, compression.context)

    async def query_with_refinement(
        self,
        query: str,
        context: RLMContext,
        strategy: str = "auto",
        max_iterations: int = 3,
        feedback_generator: Callable[[RLMResult], str] | None = None,
        start_level: str = "SUMMARY",
    ) -> RLMResult:
        """
        Query with iterative refinement (Prime Intellect alignment).

        Implements the iterative refinement protocol where the LLM can
        signal incomplete answers via ready=False, triggering additional
        refinement iterations with feedback.

        Args:
            query: The query to answer
            context: Pre-compressed hierarchical context
            strategy: Decomposition strategy (auto, peek, grep, partition_map, etc.)
            max_iterations: Maximum refinement iterations
            feedback_generator: Optional function to generate feedback from
                              incomplete result. If None, uses default feedback.
            start_level: Initial abstraction level (FULL, DETAILED, SUMMARY,
                        ABSTRACT, METADATA). Default is SUMMARY.

        Returns:
            RLMResult with final answer and refinement history
        """
        # Store start level in context for strategies to access
        if not context.compression_stats:
            context.compression_stats = {}
        context.compression_stats["start_level"] = start_level

        refinement_history: list[str] = []
        iteration = 0
        result: RLMResult | None = None

        while iteration < max_iterations:
            # Generate feedback for iterations > 0
            feedback: str | None = None
            if iteration > 0 and result:
                if feedback_generator:
                    feedback = feedback_generator(result)
                else:
                    feedback = self._default_feedback(result, query)

            # Execute query iteration
            result = await self._query_iteration(
                query=query,
                context=context,
                strategy=strategy,
                iteration=iteration,
                feedback=feedback,
            )

            # Track iteration
            result.iteration = iteration
            if iteration > 0:
                refinement_history.append(result.answer)

            logger.info(
                f"RLM refinement iteration={iteration} ready={result.ready} "
                f"confidence={result.confidence:.2f}"
            )

            # Check if answer is ready
            if result.ready:
                break

            iteration += 1

        # Finalize result
        if result:
            result.refinement_history = refinement_history
            result.iteration = iteration

        return result or RLMResult(
            answer="[Failed to generate answer after max iterations]",
            ready=True,
            iteration=max_iterations,
            refinement_history=refinement_history,
        )

    async def _query_iteration(
        self,
        query: str,
        context: RLMContext,
        strategy: str,
        iteration: int,
        feedback: str | None,
    ) -> RLMResult:
        """Execute a single query iteration with optional feedback."""
        # Modify query to include feedback context
        effective_query = query
        if feedback and iteration > 0:
            effective_query = f"""Previous answer was incomplete. Feedback:
{feedback}

Original question: {query}

Please provide an improved answer based on the feedback."""

        # Execute query
        result = await self.query(effective_query, context, strategy)

        # If using built-in REPL, set iteration context
        # (The official RLM would handle this internally)
        result.iteration = iteration

        return result

    def _default_feedback(self, result: RLMResult, original_query: str) -> str:
        """Generate default feedback for incomplete answers."""
        feedback_parts = ["Your previous answer was marked as incomplete."]

        if result.uncertainty_sources:
            feedback_parts.append(
                f"Uncertainty sources identified: {', '.join(result.uncertainty_sources)}"
            )

        if result.confidence < 0.5:
            feedback_parts.append(
                "Confidence was low. Try drilling down into more specific context sections."
            )

        if result.sub_calls_made == 0:
            feedback_parts.append("Consider using llm_query() to delegate complex sub-queries.")

        feedback_parts.append(f"Focus on answering: {original_query[:200]}")

        return "\n".join(feedback_parts)

    # --- Lifecycle methods ---

    def close(self) -> None:
        """Clean up persistent RLM sessions."""
        if self._official_rlm and hasattr(self._official_rlm, "close"):
            try:
                self._official_rlm.close()
            except (RuntimeError, OSError) as e:
                logger.debug("Error closing official RLM: %s", e)
        if self._fallback_rlm and hasattr(self._fallback_rlm, "close"):
            try:
                self._fallback_rlm.close()
            except (RuntimeError, OSError) as e:
                logger.debug("Error closing fallback RLM: %s", e)

    def __enter__(self) -> "AragoraRLM":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Literal[False]:
        self.close()
        return False

    def get_trajectory_log_path(self) -> str | None:
        """Get the trajectory log directory path."""
        return self._trajectory_log_dir

    # --- Tier 2: Audit, Memory, Knowledge integration ---

    def log_to_audit(
        self,
        result: RLMResult,
        *,
        query: str = "",
        debate_id: str | None = None,
    ) -> None:
        """Log an RLM query result to the audit trail.

        Args:
            result: The RLM result to audit
            query: The original query
            debate_id: Optional debate ID for context
        """
        try:
            from aragora.audit.log import AuditCategory, AuditEvent, get_audit_log

            audit = get_audit_log()
            audit.log(
                AuditEvent(
                    category=AuditCategory.SYSTEM,
                    action="rlm_query",
                    actor_id="system:rlm",
                    resource_type="rlm",
                    resource_id=debate_id or "",
                    details={
                        "query": query[:500],
                        "answer_preview": result.answer[:200],
                        "used_true_rlm": result.used_true_rlm,
                        "confidence": result.confidence,
                        "tokens_processed": result.tokens_processed,
                        "trajectory_log_path": result.trajectory_log_path,
                        "rlm_iterations": result.rlm_iterations,
                        "code_blocks_executed": result.code_blocks_executed,
                        "debate_id": debate_id,
                    },
                )
            )
        except (ImportError, RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.debug("Audit logging skipped: %s", e)

    def inject_memory_helpers(
        self,
        continuum: Any,
        *,
        query: str | None = None,
    ) -> dict[str, Any]:
        """Inject ContinuumMemory helpers into RLM REPL context.

        Args:
            continuum: ContinuumMemory instance
            query: Optional query to pre-filter memory

        Returns:
            Dictionary of injected helpers and loaded context
        """
        try:
            from .memory_helpers import load_memory_context, get_memory_helpers

            ctx = load_memory_context(continuum, query=query)
            helpers = get_memory_helpers()
            return {"context": ctx, "helpers": helpers}
        except (ImportError, RuntimeError, ValueError, AttributeError) as e:
            logger.debug("Memory helper injection failed: %s", e)
            return {"context": None, "helpers": {}}

    def inject_unified_memory_helpers(
        self,
        gateway: Any,
        retention_gate: Any = None,
    ) -> dict[str, Any]:
        """Inject unified memory navigation helpers into RLM REPL context.

        Provides cross-system search, drill-down, and surprise-based
        filtering across all 5 memory systems.

        Args:
            gateway: MemoryGateway instance
            retention_gate: Optional RetentionGate for enrichment

        Returns:
            Dictionary of injected helpers
        """
        try:
            from .memory_navigator import RLMMemoryNavigator

            navigator = RLMMemoryNavigator(
                gateway=gateway,
                retention_gate=retention_gate,
            )
            return {"helpers": navigator.get_repl_helpers()}
        except (ImportError, RuntimeError, ValueError, AttributeError) as e:
            logger.debug("Unified memory helper injection failed: %s", e)
            return {"helpers": {}}

    def inject_knowledge_helpers(
        self,
        mound: Any,
        workspace_id: str,
    ) -> dict[str, Any]:
        """Inject KnowledgeMound helpers into RLM REPL context.

        Args:
            mound: KnowledgeMound instance
            workspace_id: Workspace to load knowledge from

        Returns:
            Dictionary of injected helpers and loaded context
        """
        try:
            from .knowledge_helpers import load_knowledge_context, get_knowledge_helpers

            ctx = load_knowledge_context(mound, workspace_id)
            helpers = get_knowledge_helpers(mound)
            return {"context": ctx, "helpers": helpers}
        except (ImportError, RuntimeError, ValueError, AttributeError) as e:
            logger.debug("Knowledge helper injection failed: %s", e)
            return {"context": None, "helpers": {}}

    # Streaming methods are provided by RLMStreamingMixin:
    # - query_stream()
    # - query_with_refinement_stream()
    # - compress_stream()


# Convenience function
def create_aragora_rlm(
    backend: str = "openai",
    model: str = "gpt-4o",
    verbose: bool = False,
    knowledge_mound: Any | None = None,
    enable_caching: bool = True,
    sub_backend: str | None = None,
    sub_model: str | None = None,
    trajectory_log_dir: str | None = None,
    persistent: bool = False,
    debate_mode: bool = False,
) -> AragoraRLM:
    """
    Create an AragoraRLM instance with sensible defaults.

    Args:
        backend: LLM backend (openai, anthropic, openrouter)
        model: Model name
        verbose: Enable verbose logging
        knowledge_mound: Optional KnowledgeMound for persistent hierarchy caching
        enable_caching: Whether to enable compression caching (default True)
        sub_backend: Optional sub-backend for cheaper recursive calls
        sub_model: Optional sub-model for recursive calls
        trajectory_log_dir: Optional directory for trajectory JSONL logs
        persistent: Keep RLM environment alive between calls
        debate_mode: Use debate-optimized system prompt

    Returns:
        Configured AragoraRLM instance
    """
    return AragoraRLM(
        backend_config=RLMBackendConfig(
            backend=backend,
            model_name=model,
            verbose=verbose,
            sub_backend=sub_backend,
            sub_backend_model=sub_model,
            trajectory_log_dir=trajectory_log_dir,
            persistent=persistent,
            custom_system_prompt=DEBATE_RLM_SYSTEM_PROMPT if debate_mode else None,
        ),
        knowledge_mound=knowledge_mound,
        enable_caching=enable_caching,
    )


# Re-export extracted classes for backwards compatibility
__all__ = [
    "AragoraRLM",
    "DEBATE_RLM_SYSTEM_PROMPT",
    "RLMBackendConfig",
    "DebateContextAdapter",
    "KnowledgeMoundAdapter",
    "RLMHierarchyCache",
    "create_aragora_rlm",
    "HAS_OFFICIAL_RLM",
]
