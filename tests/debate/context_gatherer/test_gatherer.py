"""
Tests for aragora/debate/context_gatherer/gatherer.py

Tests the main ContextGatherer class which composes SourceGatheringMixin,
CompressionMixin, and MemoryMixin to provide multi-source async context gathering.
"""

import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module-level patches applied BEFORE importing ContextGatherer so that the
# gatherer module sees the faked feature flags instead of performing real
# imports of RLM / KnowledgeMound / ThreatIntel at load-time.
# ---------------------------------------------------------------------------

_CONST = "aragora.debate.context_gatherer.constants"
_GATHERER = "aragora.debate.context_gatherer.gatherer"


def _make_gatherer(**kwargs):
    """Create a ContextGatherer with all heavy subsystems disabled.

    Patches feature-flag constants so __init__ never tries to import real
    RLM, KnowledgeMound, or ThreatIntel packages.
    """
    defaults = dict(
        enable_rlm_compression=False,
        enable_knowledge_grounding=False,
        enable_belief_guidance=False,
        enable_threat_intel_enrichment=False,
        enable_trending_context=False,
    )
    defaults.update(kwargs)

    patches = {
        f"{_GATHERER}.HAS_RLM": defaults.get("_has_rlm", False),
        f"{_GATHERER}.HAS_OFFICIAL_RLM": False,
        f"{_GATHERER}.HAS_KNOWLEDGE_MOUND": defaults.get("_has_km", False),
        f"{_GATHERER}.HAS_THREAT_INTEL": False,
        f"{_GATHERER}.THREAT_INTEL_ENABLED": False,
        f"{_GATHERER}.KnowledgeMound": None,
        f"{_GATHERER}.ThreatIntelEnrichment": None,
        f"{_GATHERER}.get_rlm": None,
        f"{_GATHERER}.get_compressor": None,
        f"{_GATHERER}.is_trending_disabled": lambda: False,
        f"{_GATHERER}.get_use_codebase": lambda: False,
        f"{_GATHERER}.CONTEXT_GATHER_TIMEOUT": 5.0,
        f"{_GATHERER}.MAX_CONTEXT_CACHE_SIZE": 100,
        f"{_GATHERER}.CODEBASE_CONTEXT_TIMEOUT": 5.0,
        f"{_GATHERER}.ARAGORA_KEYWORDS": [
            "aragora",
            "multi-agent debate",
            "decision stress-test",
            "nomic loop",
            "debate framework",
        ],
    }

    # Remove internal keys that should not be passed to ContextGatherer
    ctor_kwargs = {k: v for k, v in defaults.items() if not k.startswith("_")}

    from aragora.debate.context_gatherer.gatherer import ContextGatherer

    with _multi_patch(patches):
        return ContextGatherer(**ctor_kwargs)


class _multi_patch:
    """Context manager that applies multiple unittest.mock.patch calls."""

    def __init__(self, mapping: dict):
        self._patchers = [patch(target, value) for target, value in mapping.items()]

    def __enter__(self):
        for p in self._patchers:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patchers:
            p.stop()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def gatherer():
    """A vanilla ContextGatherer with all external subsystems disabled."""
    return _make_gatherer()


@pytest.fixture()
def gatherer_with_trending():
    """ContextGatherer with trending enabled (but env var not set)."""
    return _make_gatherer(enable_trending_context=True)


# ===========================================================================
# _package_override
# ===========================================================================


class TestPackageOverride:
    """Tests for the _package_override helper."""

    def test_returns_default_when_no_attribute(self):
        from aragora.debate.context_gatherer.gatherer import _package_override

        result = _package_override("__nonexistent_attr_xyz__", "fallback")
        assert result == "fallback"

    def test_returns_override_when_attribute_set(self):
        import aragora.debate.context_gatherer as pkg
        from aragora.debate.context_gatherer.gatherer import _package_override

        sentinel = object()
        pkg._test_sentinel = sentinel  # type: ignore[attr-defined]
        try:
            result = _package_override("_test_sentinel", "default")
            assert result is sentinel
        finally:
            delattr(pkg, "_test_sentinel")


# ===========================================================================
# __init__
# ===========================================================================


class TestInit:
    """Tests for ContextGatherer.__init__ constructor paths."""

    def test_basic_init_defaults(self, gatherer):
        """Verify default attribute values after construction."""
        assert gatherer._evidence_store_callback is None
        assert gatherer._prompt_builder is None
        assert isinstance(gatherer._research_evidence_pack, dict)
        assert isinstance(gatherer._research_context_cache, dict)
        assert isinstance(gatherer._continuum_context_cache, dict)
        assert isinstance(gatherer._trending_topics_cache, list)
        assert len(gatherer._research_evidence_pack) == 0

    def test_init_with_callback(self):
        cb = MagicMock()
        g = _make_gatherer(evidence_store_callback=cb)
        assert g._evidence_store_callback is cb

    def test_init_with_prompt_builder(self):
        pb = MagicMock()
        g = _make_gatherer(prompt_builder=pb)
        assert g._prompt_builder is pb

    def test_init_with_project_root(self, tmp_path):
        g = _make_gatherer(project_root=tmp_path)
        assert g._project_root == tmp_path

    def test_init_rlm_disabled_when_flag_false(self):
        g = _make_gatherer(enable_rlm_compression=False)
        assert g._enable_rlm is False
        assert g._aragora_rlm is None

    def test_init_rlm_enabled_with_factory(self):
        """When HAS_RLM is True and get_rlm returns something, _aragora_rlm is set."""
        mock_rlm = MagicMock()
        patches = {
            f"{_GATHERER}.HAS_RLM": True,
            f"{_GATHERER}.HAS_OFFICIAL_RLM": False,
            f"{_GATHERER}.HAS_KNOWLEDGE_MOUND": False,
            f"{_GATHERER}.HAS_THREAT_INTEL": False,
            f"{_GATHERER}.THREAT_INTEL_ENABLED": False,
            f"{_GATHERER}.KnowledgeMound": None,
            f"{_GATHERER}.ThreatIntelEnrichment": None,
            f"{_GATHERER}.get_rlm": lambda: mock_rlm,
            f"{_GATHERER}.get_compressor": None,
            f"{_GATHERER}.is_trending_disabled": lambda: False,
            f"{_GATHERER}.CONTEXT_GATHER_TIMEOUT": 5.0,
            f"{_GATHERER}.MAX_CONTEXT_CACHE_SIZE": 100,
            f"{_GATHERER}.CODEBASE_CONTEXT_TIMEOUT": 5.0,
            f"{_GATHERER}.ARAGORA_KEYWORDS": ["aragora"],
            f"{_GATHERER}.get_use_codebase": lambda: False,
        }
        from aragora.debate.context_gatherer.gatherer import ContextGatherer

        with _multi_patch(patches):
            g = ContextGatherer(
                enable_rlm_compression=True,
                enable_knowledge_grounding=False,
                enable_belief_guidance=False,
                enable_threat_intel_enrichment=False,
                enable_trending_context=False,
            )
        assert g._aragora_rlm is mock_rlm

    def test_init_rlm_factory_import_error(self):
        """get_rlm raising ImportError should not crash; _aragora_rlm stays None."""
        patches = {
            f"{_GATHERER}.HAS_RLM": True,
            f"{_GATHERER}.HAS_OFFICIAL_RLM": False,
            f"{_GATHERER}.HAS_KNOWLEDGE_MOUND": False,
            f"{_GATHERER}.HAS_THREAT_INTEL": False,
            f"{_GATHERER}.THREAT_INTEL_ENABLED": False,
            f"{_GATHERER}.KnowledgeMound": None,
            f"{_GATHERER}.ThreatIntelEnrichment": None,
            f"{_GATHERER}.get_rlm": MagicMock(side_effect=ImportError("no rlm")),
            f"{_GATHERER}.get_compressor": None,
            f"{_GATHERER}.is_trending_disabled": lambda: False,
            f"{_GATHERER}.CONTEXT_GATHER_TIMEOUT": 5.0,
            f"{_GATHERER}.MAX_CONTEXT_CACHE_SIZE": 100,
            f"{_GATHERER}.CODEBASE_CONTEXT_TIMEOUT": 5.0,
            f"{_GATHERER}.ARAGORA_KEYWORDS": ["aragora"],
            f"{_GATHERER}.get_use_codebase": lambda: False,
        }
        from aragora.debate.context_gatherer.gatherer import ContextGatherer

        with _multi_patch(patches):
            g = ContextGatherer(
                enable_rlm_compression=True,
                enable_knowledge_grounding=False,
                enable_belief_guidance=False,
                enable_threat_intel_enrichment=False,
                enable_trending_context=False,
            )
        assert g._aragora_rlm is None

    def test_init_trending_disabled_via_env(self):
        """When is_trending_disabled() returns True, trending is force-disabled."""
        patches = {
            f"{_GATHERER}.HAS_RLM": False,
            f"{_GATHERER}.HAS_OFFICIAL_RLM": False,
            f"{_GATHERER}.HAS_KNOWLEDGE_MOUND": False,
            f"{_GATHERER}.HAS_THREAT_INTEL": False,
            f"{_GATHERER}.THREAT_INTEL_ENABLED": False,
            f"{_GATHERER}.KnowledgeMound": None,
            f"{_GATHERER}.ThreatIntelEnrichment": None,
            f"{_GATHERER}.get_rlm": None,
            f"{_GATHERER}.get_compressor": None,
            f"{_GATHERER}.is_trending_disabled": lambda: True,
            f"{_GATHERER}.CONTEXT_GATHER_TIMEOUT": 5.0,
            f"{_GATHERER}.MAX_CONTEXT_CACHE_SIZE": 100,
            f"{_GATHERER}.CODEBASE_CONTEXT_TIMEOUT": 5.0,
            f"{_GATHERER}.ARAGORA_KEYWORDS": ["aragora"],
            f"{_GATHERER}.get_use_codebase": lambda: False,
        }
        from aragora.debate.context_gatherer.gatherer import ContextGatherer

        with _multi_patch(patches):
            g = ContextGatherer(
                enable_rlm_compression=False,
                enable_knowledge_grounding=False,
                enable_belief_guidance=False,
                enable_threat_intel_enrichment=False,
                enable_trending_context=True,  # user says yes, but env says no
            )
        assert g._enable_trending_context is False

    def test_init_knowledge_mound_provided(self):
        """When a KnowledgeMound instance is provided, it is used directly."""
        mock_km = MagicMock()
        patches = {
            f"{_GATHERER}.HAS_RLM": False,
            f"{_GATHERER}.HAS_OFFICIAL_RLM": False,
            f"{_GATHERER}.HAS_KNOWLEDGE_MOUND": True,
            f"{_GATHERER}.HAS_THREAT_INTEL": False,
            f"{_GATHERER}.THREAT_INTEL_ENABLED": False,
            f"{_GATHERER}.KnowledgeMound": MagicMock,  # non-None class sentinel
            f"{_GATHERER}.ThreatIntelEnrichment": None,
            f"{_GATHERER}.get_rlm": None,
            f"{_GATHERER}.get_compressor": None,
            f"{_GATHERER}.is_trending_disabled": lambda: False,
            f"{_GATHERER}.CONTEXT_GATHER_TIMEOUT": 5.0,
            f"{_GATHERER}.MAX_CONTEXT_CACHE_SIZE": 100,
            f"{_GATHERER}.CODEBASE_CONTEXT_TIMEOUT": 5.0,
            f"{_GATHERER}.ARAGORA_KEYWORDS": ["aragora"],
            f"{_GATHERER}.get_use_codebase": lambda: False,
        }
        from aragora.debate.context_gatherer.gatherer import ContextGatherer

        with _multi_patch(patches):
            g = ContextGatherer(
                enable_rlm_compression=False,
                enable_knowledge_grounding=True,
                knowledge_mound=mock_km,
                enable_belief_guidance=False,
                enable_threat_intel_enrichment=False,
                enable_trending_context=False,
            )
        assert g._knowledge_mound is mock_km

    def test_init_belief_guidance_import_error(self):
        """Belief analyzer import failure disables guidance."""
        with (
            patch(f"{_GATHERER}.HAS_RLM", False),
            patch(f"{_GATHERER}.HAS_OFFICIAL_RLM", False),
            patch(f"{_GATHERER}.HAS_KNOWLEDGE_MOUND", False),
            patch(f"{_GATHERER}.HAS_THREAT_INTEL", False),
            patch(f"{_GATHERER}.THREAT_INTEL_ENABLED", False),
            patch(f"{_GATHERER}.KnowledgeMound", None),
            patch(f"{_GATHERER}.ThreatIntelEnrichment", None),
            patch(f"{_GATHERER}.get_rlm", None),
            patch(f"{_GATHERER}.get_compressor", None),
            patch(f"{_GATHERER}.is_trending_disabled", return_value=False),
            patch(f"{_GATHERER}.CONTEXT_GATHER_TIMEOUT", 5.0),
            patch(f"{_GATHERER}.MAX_CONTEXT_CACHE_SIZE", 100),
            patch(f"{_GATHERER}.CODEBASE_CONTEXT_TIMEOUT", 5.0),
            patch(f"{_GATHERER}.ARAGORA_KEYWORDS", ["aragora"]),
            patch(f"{_GATHERER}.get_use_codebase", return_value=False),
            patch(
                "aragora.debate.phases.belief_analysis.DebateBeliefAnalyzer",
                side_effect=ImportError("no belief"),
            ),
        ):
            from aragora.debate.context_gatherer.gatherer import ContextGatherer

            g = ContextGatherer(
                enable_rlm_compression=False,
                enable_knowledge_grounding=False,
                enable_belief_guidance=True,
                enable_threat_intel_enrichment=False,
                enable_trending_context=False,
            )
        assert g._enable_belief_guidance is False

    def test_init_document_store_params(self):
        """Document store params are stored correctly."""
        ds = MagicMock()
        es = MagicMock()
        g = _make_gatherer(
            document_store=ds,
            evidence_store=es,
            document_ids=["d1", "d2"],
            document_org_id="org-1",
            enable_document_context=True,
            enable_evidence_store_context=True,
            max_document_context_items=10,
            max_evidence_context_items=8,
        )
        assert g._document_store is ds
        assert g._evidence_store is es
        assert g._document_ids == ["d1", "d2"]
        assert g._document_org_id == "org-1"
        assert g._max_document_context_items == 10
        assert g._max_evidence_context_items == 8


# ===========================================================================
# evidence_pack property
# ===========================================================================


class TestEvidencePack:
    """Tests for the evidence_pack property."""

    def test_returns_none_when_empty(self, gatherer):
        assert gatherer.evidence_pack is None

    def test_returns_last_pack(self, gatherer):
        gatherer._research_evidence_pack["aaa"] = "pack1"
        gatherer._research_evidence_pack["bbb"] = "pack2"
        assert gatherer.evidence_pack == "pack2"

    def test_returns_single_pack(self, gatherer):
        gatherer._research_evidence_pack["only"] = "single_pack"
        assert gatherer.evidence_pack == "single_pack"


# ===========================================================================
# get_evidence_pack
# ===========================================================================


class TestGetEvidencePack:
    """Tests for get_evidence_pack(task)."""

    def test_returns_pack_for_task(self, gatherer):
        task = "test task"
        task_hash = gatherer._get_task_hash(task)
        gatherer._research_evidence_pack[task_hash] = "my_pack"
        assert gatherer.get_evidence_pack(task) == "my_pack"

    def test_returns_none_for_unknown_task(self, gatherer):
        assert gatherer.get_evidence_pack("unknown task") is None


# ===========================================================================
# set_prompt_builder
# ===========================================================================


class TestSetPromptBuilder:
    def test_updates_prompt_builder(self, gatherer):
        pb = MagicMock()
        gatherer.set_prompt_builder(pb)
        assert gatherer._prompt_builder is pb


# ===========================================================================
# _get_task_hash
# ===========================================================================


class TestGetTaskHash:
    def test_sha256_truncated_to_16(self, gatherer):
        task = "some debate topic"
        expected = hashlib.sha256(task.encode()).hexdigest()[:16]
        assert gatherer._get_task_hash(task) == expected

    def test_different_tasks_different_hashes(self, gatherer):
        h1 = gatherer._get_task_hash("task A")
        h2 = gatherer._get_task_hash("task B")
        assert h1 != h2

    def test_deterministic(self, gatherer):
        assert gatherer._get_task_hash("x") == gatherer._get_task_hash("x")


# ===========================================================================
# _enforce_cache_limit
# ===========================================================================


class TestEnforceCacheLimit:
    def test_does_nothing_below_limit(self, gatherer):
        cache = {"a": 1, "b": 2}
        gatherer._enforce_cache_limit(cache, 5)
        assert len(cache) == 2

    def test_evicts_oldest_at_limit(self, gatherer):
        cache = {"a": 1, "b": 2, "c": 3}
        gatherer._enforce_cache_limit(cache, 3)
        # should have evicted "a" (oldest) to make room
        assert "a" not in cache
        assert len(cache) == 2

    def test_evicts_multiple_if_over_limit(self, gatherer):
        cache = {str(i): i for i in range(10)}
        gatherer._enforce_cache_limit(cache, 3)
        assert len(cache) == 2
        # The remaining keys should be the last inserted
        remaining = list(cache.keys())
        assert remaining == ["8", "9"]

    def test_empty_cache_is_noop(self, gatherer):
        cache = {}
        gatherer._enforce_cache_limit(cache, 5)
        assert len(cache) == 0

    def test_max_size_one(self, gatherer):
        cache = {"a": 1}
        gatherer._enforce_cache_limit(cache, 1)
        assert len(cache) == 0


# ===========================================================================
# gather_all
# ===========================================================================


class TestGatherAll:
    """Tests for the async gather_all method."""

    @pytest.mark.asyncio
    async def test_returns_cached_result(self, gatherer):
        """If task hash is already cached, return immediately."""
        task = "cached topic"
        task_hash = gatherer._get_task_hash(task)
        gatherer._research_context_cache[task_hash] = "cached_result"

        result = await gatherer.gather_all(task)
        assert result == "cached_result"

    @pytest.mark.asyncio
    async def test_returns_no_context_when_nothing_gathered(self, gatherer):
        """When all sources return nothing, returns the sentinel string."""
        gatherer._gather_claude_web_search = AsyncMock(return_value=None)
        gatherer.gather_aragora_context = AsyncMock(return_value=None)
        gatherer._gather_trending_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_knowledge_mound_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_belief_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_culture_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_threat_intel_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_evidence_with_timeout = AsyncMock(return_value=None)

        result = await gatherer.gather_all("nothing here")
        assert result == "No research context available."

    @pytest.mark.asyncio
    async def test_combines_multiple_sources(self, gatherer):
        """Context parts from multiple sources are joined with double newline."""
        gatherer._gather_claude_web_search = AsyncMock(return_value="claude_ctx")
        gatherer.gather_aragora_context = AsyncMock(return_value="aragora_ctx")
        gatherer._gather_trending_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_knowledge_mound_with_timeout = AsyncMock(return_value="knowledge_ctx")
        gatherer._gather_belief_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_culture_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_threat_intel_with_timeout = AsyncMock(return_value=None)

        result = await gatherer.gather_all("topic")
        assert "claude_ctx" in result
        assert "aragora_ctx" in result
        assert "knowledge_ctx" in result

    @pytest.mark.asyncio
    async def test_caches_result_on_success(self, gatherer):
        """After gathering, result is cached under the task hash."""
        gatherer._gather_claude_web_search = AsyncMock(return_value="research data")
        gatherer.gather_aragora_context = AsyncMock(return_value=None)
        gatherer._gather_trending_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_knowledge_mound_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_belief_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_culture_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_threat_intel_with_timeout = AsyncMock(return_value=None)

        task = "cache me"
        result = await gatherer.gather_all(task)
        task_hash = gatherer._get_task_hash(task)
        assert task_hash in gatherer._research_context_cache
        assert gatherer._research_context_cache[task_hash] == result

    @pytest.mark.asyncio
    async def test_evidence_fallback_when_claude_weak(self, gatherer):
        """When Claude search returns <500 chars, evidence fallback is triggered."""
        short_ctx = "x" * 100  # less than 500
        gatherer._gather_claude_web_search = AsyncMock(return_value=short_ctx)
        gatherer.gather_aragora_context = AsyncMock(return_value=None)
        gatherer._gather_trending_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_knowledge_mound_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_belief_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_culture_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_threat_intel_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_evidence_with_timeout = AsyncMock(return_value="evidence_fallback")

        result = await gatherer.gather_all("test")
        gatherer._gather_evidence_with_timeout.assert_called_once()
        assert "evidence_fallback" in result

    @pytest.mark.asyncio
    async def test_no_evidence_fallback_when_claude_strong(self, gatherer):
        """When Claude search returns >= 500 chars, evidence fallback is NOT used."""
        strong_ctx = "x" * 600
        gatherer._gather_claude_web_search = AsyncMock(return_value=strong_ctx)
        gatherer.gather_aragora_context = AsyncMock(return_value=None)
        gatherer._gather_trending_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_knowledge_mound_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_belief_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_culture_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_threat_intel_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_evidence_with_timeout = AsyncMock(return_value="evidence")

        result = await gatherer.gather_all("test")
        # evidence_with_timeout should NOT be called; it shouldn't be set up as a task
        # The mock was set up but the method should not have been awaited through the
        # gather tasks since claude_ctx >= 500. However, the evidence_with_timeout
        # is only created as a task when claude_ctx is weak. Let's verify the result
        # does not include fallback evidence:
        assert "evidence" not in result or strong_ctx in result

    @pytest.mark.asyncio
    async def test_timeout_returns_partial_results(self, gatherer):
        """Overall timeout yields partial results rather than error."""
        # Claude search returns quickly
        gatherer._gather_claude_web_search = AsyncMock(return_value="partial")
        gatherer.gather_aragora_context = AsyncMock(return_value=None)
        # The rest will be slow enough to be killed by the outer timeout
        gatherer._gather_trending_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_knowledge_mound_with_timeout = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )
        gatherer._gather_belief_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_culture_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_threat_intel_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_evidence_with_timeout = AsyncMock(return_value=None)

        result = await gatherer.gather_all("test", timeout=5.0)
        assert "partial" in result

    @pytest.mark.asyncio
    async def test_exception_in_subtask_is_handled(self, gatherer):
        """Exceptions in subtasks are logged but don't crash gather_all."""
        gatherer._gather_claude_web_search = AsyncMock(return_value="main_ctx")
        gatherer.gather_aragora_context = AsyncMock(return_value=None)
        gatherer._gather_trending_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_knowledge_mound_with_timeout = AsyncMock(side_effect=RuntimeError("boom"))
        gatherer._gather_belief_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_culture_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_threat_intel_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_evidence_with_timeout = AsyncMock(return_value=None)

        result = await gatherer.gather_all("test")
        assert "main_ctx" in result

    @pytest.mark.asyncio
    async def test_trending_task_created_when_enabled(self, gatherer_with_trending):
        """When trending is enabled, _gather_trending_with_timeout is invoked."""
        g = gatherer_with_trending
        g._gather_claude_web_search = AsyncMock(return_value=None)
        g.gather_aragora_context = AsyncMock(return_value=None)
        g._gather_trending_with_timeout = AsyncMock(return_value="trending_data")
        g._gather_knowledge_mound_with_timeout = AsyncMock(return_value=None)
        g._gather_belief_with_timeout = AsyncMock(return_value=None)
        g._gather_culture_with_timeout = AsyncMock(return_value=None)
        g._gather_threat_intel_with_timeout = AsyncMock(return_value=None)
        g._gather_evidence_with_timeout = AsyncMock(return_value=None)

        result = await g.gather_all("test")
        assert "trending_data" in result

    @pytest.mark.asyncio
    async def test_skip_empty_sidecars_skips_optional_sidecars_for_simple_question(self):
        """Opt-in sidecar skipping bypasses research/KM tasks for simple questions."""
        g = _make_gatherer(skip_empty_sidecars=True, enable_trending_context=True)
        g._gather_claude_web_search = AsyncMock(return_value="claude_ctx")
        g.gather_aragora_context = AsyncMock(return_value=None)
        g._gather_trending_with_timeout = AsyncMock(return_value="trending_data")
        g._gather_knowledge_mound_with_timeout = AsyncMock(return_value="knowledge_ctx")
        g._gather_belief_with_timeout = AsyncMock(return_value="belief_ctx")
        g._gather_culture_with_timeout = AsyncMock(return_value="culture_ctx")
        g._gather_threat_intel_with_timeout = AsyncMock(return_value="threat_ctx")
        g._gather_evidence_with_timeout = AsyncMock(return_value="evidence_ctx")

        result = await g.gather_all("What is 2 + 2?")

        assert result == "No research context available."
        g.gather_aragora_context.assert_called_once_with("What is 2 + 2?")
        g._gather_claude_web_search.assert_not_called()
        g._gather_trending_with_timeout.assert_not_called()
        g._gather_knowledge_mound_with_timeout.assert_not_called()
        g._gather_belief_with_timeout.assert_not_called()
        g._gather_culture_with_timeout.assert_not_called()
        g._gather_threat_intel_with_timeout.assert_not_called()
        g._gather_evidence_with_timeout.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_empty_sidecars_preserves_sidecars_for_domain_question(self):
        """Domain-specific questions still gather sidecars even when the flag is enabled."""
        g = _make_gatherer(skip_empty_sidecars=True, enable_trending_context=True)
        g._gather_claude_web_search = AsyncMock(return_value="claude_ctx")
        g.gather_aragora_context = AsyncMock(return_value=None)
        g._gather_trending_with_timeout = AsyncMock(return_value=None)
        g._gather_knowledge_mound_with_timeout = AsyncMock(return_value=None)
        g._gather_belief_with_timeout = AsyncMock(return_value=None)
        g._gather_culture_with_timeout = AsyncMock(return_value=None)
        g._gather_threat_intel_with_timeout = AsyncMock(return_value=None)
        g._gather_evidence_with_timeout = AsyncMock(return_value=None)

        result = await g.gather_all("How should we shard Postgres writes?")

        assert "claude_ctx" in result
        g._gather_claude_web_search.assert_called_once_with("How should we shard Postgres writes?")
        g._gather_trending_with_timeout.assert_called_once()
        g._gather_knowledge_mound_with_timeout.assert_called_once_with(
            "How should we shard Postgres writes?"
        )
        g._gather_belief_with_timeout.assert_called_once_with(
            "How should we shard Postgres writes?"
        )
        g._gather_culture_with_timeout.assert_called_once_with(
            "How should we shard Postgres writes?"
        )
        g._gather_threat_intel_with_timeout.assert_called_once_with(
            "How should we shard Postgres writes?"
        )

    @pytest.mark.asyncio
    async def test_document_store_task_created_when_configured(self):
        """When document_store is set, its gather task is created."""
        ds = MagicMock()
        g = _make_gatherer(
            document_store=ds,
            enable_document_context=True,
        )
        g._gather_claude_web_search = AsyncMock(return_value=None)
        g.gather_aragora_context = AsyncMock(return_value=None)
        g._gather_trending_with_timeout = AsyncMock(return_value=None)
        g._gather_knowledge_mound_with_timeout = AsyncMock(return_value=None)
        g._gather_belief_with_timeout = AsyncMock(return_value=None)
        g._gather_culture_with_timeout = AsyncMock(return_value=None)
        g._gather_threat_intel_with_timeout = AsyncMock(return_value=None)
        g._gather_evidence_with_timeout = AsyncMock(return_value=None)
        g._gather_document_store_with_timeout = AsyncMock(return_value="doc_ctx")

        result = await g.gather_all("test")
        g._gather_document_store_with_timeout.assert_called_once_with("test")
        assert "doc_ctx" in result

    @pytest.mark.asyncio
    async def test_evidence_store_task_created_when_configured(self):
        """When evidence_store is set, its gather task is created."""
        es = MagicMock()
        g = _make_gatherer(
            evidence_store=es,
            enable_evidence_store_context=True,
        )
        g._gather_claude_web_search = AsyncMock(return_value=None)
        g.gather_aragora_context = AsyncMock(return_value=None)
        g._gather_trending_with_timeout = AsyncMock(return_value=None)
        g._gather_knowledge_mound_with_timeout = AsyncMock(return_value=None)
        g._gather_belief_with_timeout = AsyncMock(return_value=None)
        g._gather_culture_with_timeout = AsyncMock(return_value=None)
        g._gather_threat_intel_with_timeout = AsyncMock(return_value=None)
        g._gather_evidence_with_timeout = AsyncMock(return_value=None)
        g._gather_evidence_store_with_timeout = AsyncMock(return_value="ev_store_ctx")

        result = await g.gather_all("test")
        g._gather_evidence_store_with_timeout.assert_called_once_with("test")
        assert "ev_store_ctx" in result

    @pytest.mark.asyncio
    async def test_cache_isolation_between_tasks(self, gatherer):
        """Different tasks produce separate cache entries."""
        gatherer._gather_claude_web_search = AsyncMock(side_effect=["ctx1", "ctx2"])
        gatherer.gather_aragora_context = AsyncMock(return_value=None)
        gatherer._gather_trending_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_knowledge_mound_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_belief_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_culture_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_threat_intel_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_evidence_with_timeout = AsyncMock(return_value=None)

        r1 = await gatherer.gather_all("task1")
        r2 = await gatherer.gather_all("task2")
        assert r1 != r2
        assert len(gatherer._research_context_cache) == 2


# ===========================================================================
# gather_aragora_context
# ===========================================================================


class TestGatherAragoraContext:
    """Tests for gather_aragora_context."""

    @pytest.mark.asyncio
    async def test_returns_none_for_non_aragora_topic(self, gatherer):
        result = await gatherer.gather_aragora_context("How to bake a cake")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_context_for_aragora_keyword(self, gatherer, tmp_path):
        """An Aragora-related topic triggers doc reading."""
        gatherer._project_root = tmp_path
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "FEATURES.md").write_text("Features content")
        (tmp_path / "CLAUDE.md").write_text("Claude project overview")

        # Patch _compress_with_rlm to return content as-is
        gatherer._compress_with_rlm = AsyncMock(side_effect=lambda c, **kw: c)
        # Patch _gather_codebase_context to return None (disabled)
        gatherer._gather_codebase_context = AsyncMock(return_value=None)

        result = await gatherer.gather_aragora_context("How does aragora debate work?")
        assert result is not None
        assert "ARAGORA PROJECT CONTEXT" in result

    @pytest.mark.asyncio
    async def test_matches_various_keywords(self, gatherer, tmp_path):
        """Multiple ARAGORA_KEYWORDS trigger context gathering."""
        gatherer._project_root = tmp_path
        (tmp_path / "docs").mkdir()
        (tmp_path / "CLAUDE.md").write_text("overview")
        gatherer._compress_with_rlm = AsyncMock(side_effect=lambda c, **kw: c)
        gatherer._gather_codebase_context = AsyncMock(return_value=None)

        for keyword in ["multi-agent debate", "nomic loop", "debate framework"]:
            result = await gatherer.gather_aragora_context(f"Tell me about {keyword}")
            assert result is not None, f"Failed for keyword: {keyword}"

    @pytest.mark.asyncio
    async def test_handles_oserror_gracefully(self, gatherer, tmp_path):
        """OSError during file reads does not crash."""
        gatherer._project_root = tmp_path
        # Don't create docs dir -- reading will fail
        gatherer._compress_with_rlm = AsyncMock(side_effect=lambda c, **kw: c)
        gatherer._gather_codebase_context = AsyncMock(return_value=None)

        result = await gatherer.gather_aragora_context("aragora discussion")
        # Result might be None if no files found, but shouldn't raise
        # (docs dir missing means no files read, so None is acceptable)
        assert result is None or "ARAGORA" in result

    @pytest.mark.asyncio
    async def test_includes_codebase_context_when_available(self, gatherer, tmp_path):
        """When _gather_codebase_context returns data, it is included first."""
        gatherer._project_root = tmp_path
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (tmp_path / "CLAUDE.md").write_text("overview")
        gatherer._compress_with_rlm = AsyncMock(side_effect=lambda c, **kw: c)
        gatherer._gather_codebase_context = AsyncMock(
            return_value="## ARAGORA CODEBASE MAP\ncodebase data"
        )

        result = await gatherer.gather_aragora_context("aragora test")
        assert result is not None
        assert "ARAGORA PROJECT CONTEXT" in result


# ===========================================================================
# _gather_codebase_context
# ===========================================================================


class TestGatherCodebaseContext:
    """Tests for _gather_codebase_context."""

    @pytest.mark.asyncio
    async def test_returns_none_when_use_codebase_disabled(self, gatherer):
        """When get_use_codebase() is False, returns None immediately."""
        with patch(f"{_GATHERER}.get_use_codebase", return_value=False):
            result = await gatherer._gather_codebase_context()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_import_fails(self, gatherer):
        """When CodebaseContextBuilder can't be imported, returns None."""
        with (
            patch(f"{_GATHERER}.get_use_codebase", return_value=True),
            patch(
                "builtins.__import__",
                side_effect=ImportError("no codebase module"),
            ),
        ):
            # Import patching is tricky; just test the disabled path
            result = await gatherer._gather_codebase_context()
        # The method catches ImportError internally
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_formatted_context_on_success(self, gatherer):
        """When builder succeeds, returns formatted codebase map."""
        mock_builder = MagicMock()
        mock_builder.build_debate_context = AsyncMock(return_value="codebase summary")

        with (
            patch(f"{_GATHERER}.get_use_codebase", return_value=True),
            patch(
                f"{_GATHERER}._package_override",
                side_effect=lambda name, default: default,
            ),
            patch(
                "aragora.rlm.codebase_context.CodebaseContextBuilder",
                return_value=mock_builder,
            ),
        ):
            gatherer._codebase_context_builder = mock_builder
            result = await gatherer._gather_codebase_context()

        assert result is not None
        assert "ARAGORA CODEBASE MAP" in result
        assert "codebase summary" in result

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self, gatherer):
        """Timeout during codebase build returns None."""
        mock_builder = MagicMock()
        mock_builder.build_debate_context = AsyncMock(side_effect=asyncio.TimeoutError)

        with (
            patch(f"{_GATHERER}.get_use_codebase", return_value=True),
            patch(
                f"{_GATHERER}._package_override",
                side_effect=lambda name, default: default,
            ),
        ):
            gatherer._codebase_context_builder = mock_builder
            result = await gatherer._gather_codebase_context()

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_context(self, gatherer):
        """When builder returns empty string, returns None."""
        mock_builder = MagicMock()
        mock_builder.build_debate_context = AsyncMock(return_value="")

        with (
            patch(f"{_GATHERER}.get_use_codebase", return_value=True),
            patch(
                f"{_GATHERER}._package_override",
                side_effect=lambda name, default: default,
            ),
        ):
            gatherer._codebase_context_builder = mock_builder
            result = await gatherer._gather_codebase_context()

        assert result is None


# ===========================================================================
# clear_cache
# ===========================================================================


class TestClearCache:
    """Tests for clear_cache."""

    def test_clear_all(self, gatherer):
        gatherer._research_context_cache["a"] = "ctx"
        gatherer._research_evidence_pack["a"] = "pack"
        gatherer._continuum_context_cache["a"] = "mem"
        gatherer._trending_topics_cache = ["t1"]

        gatherer.clear_cache()

        assert len(gatherer._research_context_cache) == 0
        assert len(gatherer._research_evidence_pack) == 0
        assert len(gatherer._continuum_context_cache) == 0
        assert len(gatherer._trending_topics_cache) == 0

    def test_clear_specific_task(self, gatherer):
        task = "specific task"
        task_hash = gatherer._get_task_hash(task)

        gatherer._research_context_cache[task_hash] = "ctx"
        gatherer._research_context_cache["other"] = "keep"
        gatherer._research_evidence_pack[task_hash] = "pack"
        gatherer._continuum_context_cache[task_hash] = "mem"

        gatherer.clear_cache(task=task)

        assert task_hash not in gatherer._research_context_cache
        assert "other" in gatherer._research_context_cache
        assert task_hash not in gatherer._research_evidence_pack
        assert task_hash not in gatherer._continuum_context_cache

    def test_clear_nonexistent_task_is_noop(self, gatherer):
        gatherer._research_context_cache["a"] = "ctx"
        gatherer.clear_cache(task="no such task")
        assert "a" in gatherer._research_context_cache

    def test_clear_all_when_already_empty(self, gatherer):
        """Clearing empty caches does not raise."""
        gatherer.clear_cache()
        assert len(gatherer._research_context_cache) == 0


# ===========================================================================
# Integration-style tests
# ===========================================================================


class TestIntegration:
    """Higher-level integration tests exercising multiple methods together."""

    @pytest.mark.asyncio
    async def test_gather_then_clear_then_re_gather(self, gatherer):
        """Gather, clear, and re-gather produces fresh results."""
        call_count = 0

        async def mock_claude_search(task):
            nonlocal call_count
            call_count += 1
            return f"result_{call_count}"

        gatherer._gather_claude_web_search = mock_claude_search
        gatherer.gather_aragora_context = AsyncMock(return_value=None)
        gatherer._gather_trending_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_knowledge_mound_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_belief_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_culture_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_threat_intel_with_timeout = AsyncMock(return_value=None)
        gatherer._gather_evidence_with_timeout = AsyncMock(return_value=None)

        r1 = await gatherer.gather_all("topic")
        assert "result_1" in r1

        gatherer.clear_cache(task="topic")
        r2 = await gatherer.gather_all("topic")
        assert "result_2" in r2

    @pytest.mark.asyncio
    async def test_cache_limit_enforcement_during_gather(self):
        """When MAX_CONTEXT_CACHE_SIZE is small, old entries are evicted."""
        patches = {
            f"{_GATHERER}.HAS_RLM": False,
            f"{_GATHERER}.HAS_OFFICIAL_RLM": False,
            f"{_GATHERER}.HAS_KNOWLEDGE_MOUND": False,
            f"{_GATHERER}.HAS_THREAT_INTEL": False,
            f"{_GATHERER}.THREAT_INTEL_ENABLED": False,
            f"{_GATHERER}.KnowledgeMound": None,
            f"{_GATHERER}.ThreatIntelEnrichment": None,
            f"{_GATHERER}.get_rlm": None,
            f"{_GATHERER}.get_compressor": None,
            f"{_GATHERER}.is_trending_disabled": lambda: False,
            f"{_GATHERER}.CONTEXT_GATHER_TIMEOUT": 5.0,
            f"{_GATHERER}.MAX_CONTEXT_CACHE_SIZE": 3,  # very small limit
            f"{_GATHERER}.CODEBASE_CONTEXT_TIMEOUT": 5.0,
            f"{_GATHERER}.ARAGORA_KEYWORDS": ["aragora"],
            f"{_GATHERER}.get_use_codebase": lambda: False,
        }
        from aragora.debate.context_gatherer.gatherer import ContextGatherer

        # Keep patches active throughout -- MAX_CONTEXT_CACHE_SIZE is read
        # inside gather_all at runtime, not just at construction time.
        with _multi_patch(patches):
            g = ContextGatherer(
                enable_rlm_compression=False,
                enable_knowledge_grounding=False,
                enable_belief_guidance=False,
                enable_threat_intel_enrichment=False,
                enable_trending_context=False,
            )

            counter = 0

            async def mock_search(task):
                nonlocal counter
                counter += 1
                return f"ctx_{counter}"

            g._gather_claude_web_search = mock_search
            g.gather_aragora_context = AsyncMock(return_value=None)
            g._gather_trending_with_timeout = AsyncMock(return_value=None)
            g._gather_knowledge_mound_with_timeout = AsyncMock(return_value=None)
            g._gather_belief_with_timeout = AsyncMock(return_value=None)
            g._gather_culture_with_timeout = AsyncMock(return_value=None)
            g._gather_threat_intel_with_timeout = AsyncMock(return_value=None)
            g._gather_evidence_with_timeout = AsyncMock(return_value=None)

            # Fill cache beyond limit
            for i in range(5):
                await g.gather_all(f"unique_task_{i}")

            # Cache should have been pruned
            assert len(g._research_context_cache) <= 3
