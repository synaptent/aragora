"""Tests for aragora/debate/context/sources.py - SourceFetcher class."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.debate.context.sources import (
    BELIEF_CRUX_TIMEOUT,
    CLAUDE_SEARCH_TIMEOUT,
    EVIDENCE_TIMEOUT,
    KNOWLEDGE_MOUND_TIMEOUT,
    THREAT_INTEL_TIMEOUT,
    TRENDING_TIMEOUT,
    SourceFetcher,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


def make_fetcher(**kwargs) -> SourceFetcher:
    """Create a SourceFetcher with sensible defaults for tests."""
    defaults = dict(
        project_root=Path("/tmp/test_aragora"),
        knowledge_mound=None,
        knowledge_workspace_id="test_ws",
        threat_intel_enrichment=None,
        belief_analyzer=None,
        enable_trending_context=False,
    )
    defaults.update(kwargs)
    return SourceFetcher(**defaults)


# ===========================================================================
# TestSourceFetcherInit
# ===========================================================================


class TestSourceFetcherInit:
    """Tests for __init__ parameter wiring."""

    def test_default_init(self):
        fetcher = SourceFetcher()
        assert fetcher._knowledge_mound is None
        assert fetcher._threat_intel_enrichment is None
        assert fetcher._belief_analyzer is None
        assert fetcher._enable_trending_context is True  # default is True
        assert fetcher._knowledge_workspace_id == "debate"

    def test_custom_project_root(self, tmp_path):
        fetcher = SourceFetcher(project_root=tmp_path)
        assert fetcher._project_root == tmp_path

    def test_default_project_root_is_set(self):
        fetcher = SourceFetcher()
        assert fetcher._project_root is not None
        assert isinstance(fetcher._project_root, Path)

    def test_knowledge_mound_stored(self):
        mock_mound = MagicMock()
        fetcher = SourceFetcher(knowledge_mound=mock_mound)
        assert fetcher._knowledge_mound is mock_mound

    def test_knowledge_workspace_id_default(self):
        fetcher = SourceFetcher(knowledge_workspace_id=None)
        assert fetcher._knowledge_workspace_id == "debate"

    def test_knowledge_workspace_id_custom(self):
        fetcher = SourceFetcher(knowledge_workspace_id="my_ws")
        assert fetcher._knowledge_workspace_id == "my_ws"

    def test_threat_intel_stored(self):
        mock_ti = MagicMock()
        fetcher = SourceFetcher(threat_intel_enrichment=mock_ti)
        assert fetcher._threat_intel_enrichment is mock_ti

    def test_belief_analyzer_stored(self):
        mock_ba = MagicMock()
        fetcher = SourceFetcher(belief_analyzer=mock_ba)
        assert fetcher._belief_analyzer is mock_ba

    def test_enable_trending_false(self):
        fetcher = SourceFetcher(enable_trending_context=False)
        assert fetcher._enable_trending_context is False


# ===========================================================================
# TestGatherClaudeWebSearch
# ===========================================================================


class TestGatherClaudeWebSearch:
    """Tests for gather_claude_web_search."""

    def test_success_with_key_sources(self):
        """Returns result when it contains 'Key Sources' and is long enough."""
        long_result = "Key Sources\n" + "x" * 300
        fetcher = make_fetcher()
        with patch.dict(
            sys.modules,
            {
                "aragora.server.research_phase": MagicMock(
                    research_for_debate=AsyncMock(return_value=long_result)
                )
            },
        ):
            result = run(fetcher.gather_claude_web_search("test task"))
        assert result == long_result

    def test_success_long_result_without_key_sources(self):
        """Returns None when result lacks 'Key Sources' and is short."""
        short_result = "some summary text"
        fetcher = make_fetcher()
        with patch.dict(
            sys.modules,
            {
                "aragora.server.research_phase": MagicMock(
                    research_for_debate=AsyncMock(return_value=short_result)
                )
            },
        ):
            result = run(fetcher.gather_claude_web_search("test task"))
        assert result is None

    def test_empty_result_returns_none(self):
        """Returns None when research_for_debate returns empty string."""
        fetcher = make_fetcher()
        with patch.dict(
            sys.modules,
            {
                "aragora.server.research_phase": MagicMock(
                    research_for_debate=AsyncMock(return_value="")
                )
            },
        ):
            result = run(fetcher.gather_claude_web_search("test task"))
        assert result is None

    def test_none_result_returns_none(self):
        """Returns None when research_for_debate returns None."""
        fetcher = make_fetcher()
        with patch.dict(
            sys.modules,
            {
                "aragora.server.research_phase": MagicMock(
                    research_for_debate=AsyncMock(return_value=None)
                )
            },
        ):
            result = run(fetcher.gather_claude_web_search("test task"))
        assert result is None

    def test_import_error_returns_none(self):
        """Returns None gracefully when research_phase module is missing."""
        fetcher = make_fetcher()
        with patch.dict(sys.modules, {"aragora.server.research_phase": None}):
            result = run(fetcher.gather_claude_web_search("test task"))
        assert result is None

    def test_timeout_returns_none(self):
        """Returns None on asyncio.TimeoutError."""
        fetcher = make_fetcher()
        mock_module = MagicMock()
        mock_module.research_for_debate = AsyncMock(side_effect=asyncio.TimeoutError())
        with patch.dict(sys.modules, {"aragora.server.research_phase": mock_module}):
            with patch(
                "aragora.debate.context.sources.asyncio.wait_for",
                new=AsyncMock(side_effect=asyncio.TimeoutError()),
            ):
                result = run(fetcher.gather_claude_web_search("test task"))
        assert result is None

    def test_connection_error_returns_none(self):
        """Returns None on ConnectionError."""
        fetcher = make_fetcher()
        mock_module = MagicMock()
        mock_module.research_for_debate = AsyncMock(side_effect=ConnectionError("network down"))
        with patch.dict(sys.modules, {"aragora.server.research_phase": mock_module}):
            with patch(
                "aragora.debate.context.sources.asyncio.wait_for",
                new=AsyncMock(side_effect=ConnectionError("network down")),
            ):
                result = run(fetcher.gather_claude_web_search("test task"))
        assert result is None

    def test_value_error_returns_none(self):
        """Returns None on ValueError."""
        fetcher = make_fetcher()
        with patch(
            "aragora.debate.context.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=ValueError("bad value")),
        ):
            with patch.dict(sys.modules, {"aragora.server.research_phase": MagicMock()}):
                result = run(fetcher.gather_claude_web_search("test task"))
        assert result is None

    def test_attribute_error_returns_none(self):
        """Returns None on AttributeError."""
        fetcher = make_fetcher()
        with patch(
            "aragora.debate.context.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=AttributeError("no attr")),
        ):
            with patch.dict(sys.modules, {"aragora.server.research_phase": MagicMock()}):
                result = run(fetcher.gather_claude_web_search("test task"))
        assert result is None


# ===========================================================================
# TestGatherEvidenceContext
# ===========================================================================


class TestGatherEvidenceContext:
    """Tests for gather_evidence_context."""

    def _make_evidence_pack(self, snippets=None, context_str="Evidence here"):
        pack = MagicMock()
        pack.snippets = snippets if snippets is not None else [MagicMock()]
        pack.to_context_string.return_value = context_str
        return pack

    def test_no_connectors_returns_none(self, connector_factory):
        """Returns (None, None) when no connectors can be loaded."""
        fetcher = make_fetcher()
        with patch.dict(sys.modules, {"aragora.evidence.collector": None}):
            ctx, pack = run(fetcher.gather_evidence_context("test task"))
        assert ctx is None
        assert pack is None

    def test_import_error_returns_none(self):
        """Returns (None, None) when EvidenceCollector import fails."""
        fetcher = make_fetcher()
        with patch.dict(sys.modules, {"aragora.evidence.collector": None}):
            ctx, pack = run(fetcher.gather_evidence_context("test task"))
        assert ctx is None
        assert pack is None

    def test_success_with_web_connector(self, connector_factory):
        """Returns formatted context when web connector provides evidence."""
        evidence_pack = self._make_evidence_pack(context_str="web evidence")
        mock_collector = MagicMock()
        mock_collector.collect_evidence = AsyncMock(return_value=evidence_pack)

        mock_collector_class = MagicMock(return_value=mock_collector)
        mock_web_connector = MagicMock()

        mock_evidence_module = MagicMock()
        mock_evidence_module.EvidenceCollector = mock_collector_class

        connector_factory["web_search"] = mock_web_connector

        fetcher = make_fetcher()
        with patch.dict(sys.modules, {"aragora.evidence.collector": mock_evidence_module}):
            ctx, pack = run(fetcher.gather_evidence_context("test task"))

        assert ctx is not None
        assert "EVIDENCE CONTEXT" in ctx
        assert pack is evidence_pack
        mock_collector.add_connector.assert_called_once_with("web", mock_web_connector)

    def test_evidence_store_callback_called(self, connector_factory):
        """Calls evidence_store_callback when evidence is available."""
        evidence_pack = self._make_evidence_pack()
        mock_collector = MagicMock()
        mock_collector.collect_evidence = AsyncMock(return_value=evidence_pack)

        mock_collector_class = MagicMock(return_value=mock_collector)
        mock_evidence_module = MagicMock()
        mock_evidence_module.EvidenceCollector = mock_collector_class

        connector_factory["web_search"] = MagicMock()

        callback = MagicMock()
        fetcher = make_fetcher()
        with patch.dict(sys.modules, {"aragora.evidence.collector": mock_evidence_module}):
            run(fetcher.gather_evidence_context("task", evidence_store_callback=callback))

        callback.assert_called_once()

    def test_prompt_builder_receives_evidence_pack(self, connector_factory):
        """Calls prompt_builder.set_evidence_pack when evidence is available."""
        evidence_pack = self._make_evidence_pack()
        mock_collector = MagicMock()
        mock_collector.collect_evidence = AsyncMock(return_value=evidence_pack)

        mock_collector_class = MagicMock(return_value=mock_collector)
        mock_evidence_module = MagicMock()
        mock_evidence_module.EvidenceCollector = mock_collector_class

        connector_factory["web_search"] = MagicMock()

        prompt_builder = MagicMock()
        fetcher = make_fetcher()
        with patch.dict(sys.modules, {"aragora.evidence.collector": mock_evidence_module}):
            run(fetcher.gather_evidence_context("task", prompt_builder=prompt_builder))

        prompt_builder.set_evidence_pack.assert_called_once_with(evidence_pack)

    def test_empty_snippets_returns_none(self, connector_factory):
        """Returns (None, None) when evidence pack has no snippets."""
        evidence_pack = self._make_evidence_pack(snippets=[])
        mock_collector = MagicMock()
        mock_collector.collect_evidence = AsyncMock(return_value=evidence_pack)

        mock_collector_class = MagicMock(return_value=mock_collector)
        mock_evidence_module = MagicMock()
        mock_evidence_module.EvidenceCollector = mock_collector_class

        connector_factory["web_search"] = MagicMock()

        fetcher = make_fetcher()
        with patch.dict(sys.modules, {"aragora.evidence.collector": mock_evidence_module}):
            ctx, pack = run(fetcher.gather_evidence_context("task"))

        assert ctx is None
        assert pack is None

    def test_connection_error_returns_none(self, connector_factory):
        """Returns (None, None) on ConnectionError during collection."""
        mock_collector = MagicMock()
        mock_collector.collect_evidence = AsyncMock(side_effect=ConnectionError("net fail"))

        mock_collector_class = MagicMock(return_value=mock_collector)
        mock_evidence_module = MagicMock()
        mock_evidence_module.EvidenceCollector = mock_collector_class

        connector_factory["web_search"] = MagicMock()

        fetcher = make_fetcher()
        with patch.dict(sys.modules, {"aragora.evidence.collector": mock_evidence_module}):
            ctx, pack = run(fetcher.gather_evidence_context("task"))

        assert ctx is None
        assert pack is None

    def test_ddgs_unavailable_skips_web_connector(self, connector_factory):
        """Skips web connector when the web search kind builds nothing."""
        mock_evidence_module = MagicMock()
        mock_collector = MagicMock()
        mock_collector.collect_evidence = AsyncMock(return_value=MagicMock(snippets=[]))
        mock_evidence_module.EvidenceCollector = MagicMock(return_value=mock_collector)

        connector_factory["web_search"] = None

        fetcher = make_fetcher()
        with patch.dict(sys.modules, {"aragora.evidence.collector": mock_evidence_module}):
            ctx, pack = run(fetcher.gather_evidence_context("task"))

        # No connectors → (None, None)
        assert ctx is None
        assert pack is None
        mock_collector.add_connector.assert_not_called()


# ===========================================================================
# TestGatherTrendingContext
# ===========================================================================


class TestGatherTrendingContext:
    """Tests for gather_trending_context."""

    def _make_topic(self, name, platform="hackernews", volume=1000, category="tech"):
        t = MagicMock()
        t.topic = name
        t.platform = platform
        t.volume = volume
        t.category = category
        return t

    def test_disabled_returns_none(self):
        """Returns (None, []) immediately when enable_trending_context=False."""
        fetcher = make_fetcher(enable_trending_context=False)
        ctx, topics = run(fetcher.gather_trending_context())
        assert ctx is None
        assert topics == []

    def test_import_error_returns_none(self):
        """Returns (None, []) when pulse module is unavailable."""
        fetcher = make_fetcher(enable_trending_context=True)
        with patch.dict(sys.modules, {"aragora.pulse.ingestor": None}):
            ctx, topics = run(fetcher.gather_trending_context())
        assert ctx is None
        assert topics == []

    def test_success_returns_context_and_topics(self):
        """Returns formatted context and topics list on success."""
        mock_topics = [self._make_topic(f"topic{i}") for i in range(4)]

        mock_manager = MagicMock()
        mock_manager.get_trending_topics = AsyncMock(return_value=mock_topics)

        mock_pulse_module = MagicMock()
        mock_pulse_module.PulseManager = MagicMock(return_value=mock_manager)
        mock_pulse_module.HackerNewsIngestor = MagicMock()
        mock_pulse_module.RedditIngestor = MagicMock()
        mock_pulse_module.GitHubTrendingIngestor = MagicMock()
        mock_pulse_module.GoogleTrendsIngestor = MagicMock()

        fetcher = make_fetcher(enable_trending_context=True)
        with patch.dict(sys.modules, {"aragora.pulse.ingestor": mock_pulse_module}):
            ctx, topics = run(fetcher.gather_trending_context())

        assert ctx is not None
        assert "TRENDING CONTEXT" in ctx
        assert len(topics) == 4

    def test_empty_topics_returns_none(self):
        """Returns (None, []) when manager returns empty list."""
        mock_manager = MagicMock()
        mock_manager.get_trending_topics = AsyncMock(return_value=[])

        mock_pulse_module = MagicMock()
        mock_pulse_module.PulseManager = MagicMock(return_value=mock_manager)
        mock_pulse_module.HackerNewsIngestor = MagicMock()
        mock_pulse_module.RedditIngestor = MagicMock()
        mock_pulse_module.GitHubTrendingIngestor = MagicMock()
        mock_pulse_module.GoogleTrendsIngestor = MagicMock()

        fetcher = make_fetcher(enable_trending_context=True)
        with patch.dict(sys.modules, {"aragora.pulse.ingestor": mock_pulse_module}):
            ctx, topics = run(fetcher.gather_trending_context())

        assert ctx is None
        assert topics == []

    def test_prompt_builder_receives_topics(self):
        """Calls prompt_builder.set_trending_topics when topics are available."""
        mock_topics = [self._make_topic("ai")]
        mock_manager = MagicMock()
        mock_manager.get_trending_topics = AsyncMock(return_value=mock_topics)

        mock_pulse_module = MagicMock()
        mock_pulse_module.PulseManager = MagicMock(return_value=mock_manager)
        mock_pulse_module.HackerNewsIngestor = MagicMock()
        mock_pulse_module.RedditIngestor = MagicMock()
        mock_pulse_module.GitHubTrendingIngestor = MagicMock()
        mock_pulse_module.GoogleTrendsIngestor = MagicMock()

        prompt_builder = MagicMock()
        fetcher = make_fetcher(enable_trending_context=True)
        with patch.dict(sys.modules, {"aragora.pulse.ingestor": mock_pulse_module}):
            run(fetcher.gather_trending_context(prompt_builder=prompt_builder))

        prompt_builder.set_trending_topics.assert_called_once_with(mock_topics)

    def test_connection_error_returns_none(self):
        """Returns (None, []) on ConnectionError."""
        mock_manager = MagicMock()
        mock_manager.get_trending_topics = AsyncMock(side_effect=ConnectionError("net"))

        mock_pulse_module = MagicMock()
        mock_pulse_module.PulseManager = MagicMock(return_value=mock_manager)
        mock_pulse_module.HackerNewsIngestor = MagicMock()
        mock_pulse_module.RedditIngestor = MagicMock()
        mock_pulse_module.GitHubTrendingIngestor = MagicMock()
        mock_pulse_module.GoogleTrendsIngestor = MagicMock()

        fetcher = make_fetcher(enable_trending_context=True)
        with patch.dict(sys.modules, {"aragora.pulse.ingestor": mock_pulse_module}):
            ctx, topics = run(fetcher.gather_trending_context())

        assert ctx is None
        assert topics == []


# ===========================================================================
# TestGatherKnowledgeMoundContext
# ===========================================================================


class TestGatherKnowledgeMoundContext:
    """Tests for gather_knowledge_mound_context."""

    def _make_result(self, items=None, execution_time_ms=100):
        result = MagicMock()
        result.items = items if items is not None else []
        result.execution_time_ms = execution_time_ms
        return result

    def _make_item(self, content="Some knowledge", source="fact", confidence=0.9):
        item = MagicMock()
        item.content = content
        item.source = source
        item.confidence = confidence
        return item

    def test_no_mound_returns_none(self):
        """Returns None immediately when knowledge_mound is not configured."""
        fetcher = make_fetcher(knowledge_mound=None)
        result = run(fetcher.gather_knowledge_mound_context("test task"))
        assert result is None

    def test_empty_items_returns_none(self):
        """Returns None when mound returns no items."""
        mock_mound = MagicMock()
        mock_mound.query = AsyncMock(return_value=self._make_result(items=[]))
        fetcher = make_fetcher(knowledge_mound=mock_mound)
        result = run(fetcher.gather_knowledge_mound_context("test task"))
        assert result is None

    def test_success_with_facts(self):
        """Returns formatted context containing facts section."""
        item = self._make_item(content="Python is fast", source="fact", confidence=0.9)
        mock_mound = MagicMock()
        mock_mound.query = AsyncMock(return_value=self._make_result(items=[item]))
        fetcher = make_fetcher(knowledge_mound=mock_mound)
        result = run(fetcher.gather_knowledge_mound_context("test task"))
        assert result is not None
        assert "KNOWLEDGE MOUND CONTEXT" in result
        assert "Verified Facts" in result

    def test_success_with_evidence(self):
        """Returns formatted context containing evidence section."""
        item = self._make_item(content="Study shows X", source="evidence", confidence=0.8)
        mock_mound = MagicMock()
        mock_mound.query = AsyncMock(return_value=self._make_result(items=[item]))
        fetcher = make_fetcher(knowledge_mound=mock_mound)
        result = run(fetcher.gather_knowledge_mound_context("test task"))
        assert result is not None
        assert "Supporting Evidence" in result

    def test_success_with_insights(self):
        """Returns formatted context containing insights section."""
        item = self._make_item(content="Pattern observed", source="consensus", confidence=0.7)
        mock_mound = MagicMock()
        mock_mound.query = AsyncMock(return_value=self._make_result(items=[item]))
        fetcher = make_fetcher(knowledge_mound=mock_mound)
        result = run(fetcher.gather_knowledge_mound_context("test task"))
        assert result is not None
        assert "Related Insights" in result

    def test_connection_error_returns_none(self):
        """Returns None on ConnectionError."""
        mock_mound = MagicMock()
        mock_mound.query = AsyncMock(side_effect=ConnectionError("db down"))
        fetcher = make_fetcher(knowledge_mound=mock_mound)
        result = run(fetcher.gather_knowledge_mound_context("test task"))
        assert result is None

    def test_attribute_error_returns_none(self):
        """Returns None on AttributeError."""
        mock_mound = MagicMock()
        mock_mound.query = AsyncMock(side_effect=AttributeError("no attr"))
        fetcher = make_fetcher(knowledge_mound=mock_mound)
        result = run(fetcher.gather_knowledge_mound_context("test task"))
        assert result is None

    def test_runtime_error_returns_none(self):
        """Returns None on RuntimeError."""
        mock_mound = MagicMock()
        mock_mound.query = AsyncMock(side_effect=RuntimeError("unexpected"))
        fetcher = make_fetcher(knowledge_mound=mock_mound)
        result = run(fetcher.gather_knowledge_mound_context("test task"))
        assert result is None

    def test_confidence_as_string_high(self):
        """Handles string confidence values like 'high'."""
        item = MagicMock()
        item.content = "A fact"
        item.source = "fact"
        item.confidence = "high"
        mock_mound = MagicMock()
        mock_mound.query = AsyncMock(return_value=self._make_result(items=[item]))
        fetcher = make_fetcher(knowledge_mound=mock_mound)
        result = run(fetcher.gather_knowledge_mound_context("test"))
        assert result is not None
        assert "[HIGH]" in result

    def test_confidence_as_string_low(self):
        """Handles string confidence value 'low'."""
        item = MagicMock()
        item.content = "A low-conf fact"
        item.source = "fact"
        item.confidence = "low"
        mock_mound = MagicMock()
        mock_mound.query = AsyncMock(return_value=self._make_result(items=[item]))
        fetcher = make_fetcher(knowledge_mound=mock_mound)
        result = run(fetcher.gather_knowledge_mound_context("test"))
        assert result is not None
        assert "[LOW]" in result

    def test_content_truncated_to_500_chars(self):
        """Long content is truncated to 500 characters."""
        long_content = "x" * 1000
        item = self._make_item(content=long_content, source="fact", confidence=0.9)
        mock_mound = MagicMock()
        mock_mound.query = AsyncMock(return_value=self._make_result(items=[item]))
        fetcher = make_fetcher(knowledge_mound=mock_mound)
        result = run(fetcher.gather_knowledge_mound_context("test"))
        # Content is sliced to 500, so only 500 x's should appear in each line
        assert "x" * 501 not in result


# ===========================================================================
# TestGatherThreatIntelContext
# ===========================================================================


class TestGatherThreatIntelContext:
    """Tests for gather_threat_intel_context."""

    def test_no_enrichment_returns_none(self):
        """Returns None when threat_intel_enrichment is not configured."""
        fetcher = make_fetcher(threat_intel_enrichment=None)
        result = run(fetcher.gather_threat_intel_context("test task"))
        assert result is None

    def test_non_security_topic_returns_none(self):
        """Returns None when topic is not security-related."""
        mock_ti = MagicMock()
        mock_ti.is_security_topic.return_value = False
        fetcher = make_fetcher(threat_intel_enrichment=mock_ti)
        result = run(fetcher.gather_threat_intel_context("business strategy"))
        assert result is None
        mock_ti.is_security_topic.assert_called_once_with("business strategy")

    def test_success_returns_formatted_context(self):
        """Returns formatted threat intel context for security topics."""
        mock_context = MagicMock()
        mock_context.indicators = [MagicMock(), MagicMock()]
        mock_context.relevant_cves = [MagicMock()]

        mock_ti = MagicMock()
        mock_ti.is_security_topic.return_value = True
        mock_ti.enrich_context = AsyncMock(return_value=mock_context)
        mock_ti.format_for_debate.return_value = "## THREAT INTEL\nCVE-2024-1234"

        fetcher = make_fetcher(threat_intel_enrichment=mock_ti)
        result = run(fetcher.gather_threat_intel_context("CVE vulnerability analysis"))
        assert result == "## THREAT INTEL\nCVE-2024-1234"
        mock_ti.format_for_debate.assert_called_once_with(mock_context)

    def test_no_enrichment_data_returns_none(self):
        """Returns None when enrich_context returns falsy value."""
        mock_ti = MagicMock()
        mock_ti.is_security_topic.return_value = True
        mock_ti.enrich_context = AsyncMock(return_value=None)

        fetcher = make_fetcher(threat_intel_enrichment=mock_ti)
        result = run(fetcher.gather_threat_intel_context("security topic"))
        assert result is None

    def test_connection_error_returns_none(self):
        """Returns None on ConnectionError during enrichment."""
        mock_ti = MagicMock()
        mock_ti.is_security_topic.return_value = True
        mock_ti.enrich_context = AsyncMock(side_effect=ConnectionError("net fail"))

        fetcher = make_fetcher(threat_intel_enrichment=mock_ti)
        result = run(fetcher.gather_threat_intel_context("security topic"))
        assert result is None

    def test_value_error_returns_none(self):
        """Returns None on ValueError during enrichment."""
        mock_ti = MagicMock()
        mock_ti.is_security_topic.return_value = True
        mock_ti.enrich_context = AsyncMock(side_effect=ValueError("bad value"))

        fetcher = make_fetcher(threat_intel_enrichment=mock_ti)
        result = run(fetcher.gather_threat_intel_context("security topic"))
        assert result is None

    def test_runtime_error_returns_none(self):
        """Returns None on RuntimeError during enrichment."""
        mock_ti = MagicMock()
        mock_ti.is_security_topic.return_value = True
        mock_ti.enrich_context = AsyncMock(side_effect=RuntimeError("fail"))

        fetcher = make_fetcher(threat_intel_enrichment=mock_ti)
        result = run(fetcher.gather_threat_intel_context("security topic"))
        assert result is None


# ===========================================================================
# TestGatherBeliefCruxContext
# ===========================================================================


class TestGatherBeliefCruxContext:
    """Tests for gather_belief_crux_context."""

    def _make_crux(self, statement="X causes Y", confidence=0.8, entropy=0.3):
        return {"statement": statement, "confidence": confidence, "entropy": entropy}

    def _make_result(self, cruxes=None, evidence_suggestions=None, analysis_error=None):
        result = MagicMock()
        result.cruxes = cruxes if cruxes is not None else []
        result.evidence_suggestions = evidence_suggestions or []
        result.analysis_error = analysis_error
        return result

    def test_no_analyzer_returns_none(self):
        """Returns None when belief_analyzer is not configured."""
        fetcher = make_fetcher(belief_analyzer=None)
        result = run(fetcher.gather_belief_crux_context("task"))
        assert result is None

    def test_no_messages_returns_none(self):
        """Returns None when no messages are provided."""
        fetcher = make_fetcher(belief_analyzer=MagicMock())
        result = run(fetcher.gather_belief_crux_context("task", messages=None))
        assert result is None

    def test_empty_messages_returns_none(self):
        """Returns None when messages list is empty (falsy)."""
        fetcher = make_fetcher(belief_analyzer=MagicMock())
        result = run(fetcher.gather_belief_crux_context("task", messages=[]))
        assert result is None

    def test_analysis_error_returns_none(self):
        """Returns None when analyzer reports an analysis_error."""
        mock_ba = MagicMock()
        mock_ba.analyze_messages.return_value = self._make_result(analysis_error="Parse error")
        fetcher = make_fetcher(belief_analyzer=mock_ba)
        result = run(fetcher.gather_belief_crux_context("task", messages=["msg1"]))
        assert result is None

    def test_no_cruxes_returns_none(self):
        """Returns None when analyzer finds no cruxes."""
        mock_ba = MagicMock()
        mock_ba.analyze_messages.return_value = self._make_result(cruxes=[])
        fetcher = make_fetcher(belief_analyzer=mock_ba)
        result = run(fetcher.gather_belief_crux_context("task", messages=["msg1"]))
        assert result is None

    def test_success_returns_crux_context(self):
        """Returns formatted crux context with crux claims."""
        crux = self._make_crux("AI is transformative", confidence=0.85, entropy=0.2)
        mock_ba = MagicMock()
        mock_ba.analyze_messages.return_value = self._make_result(cruxes=[crux])
        fetcher = make_fetcher(belief_analyzer=mock_ba)
        result = run(fetcher.gather_belief_crux_context("task", messages=["msg1"]))
        assert result is not None
        assert "Key Crux Points" in result
        assert "AI is transformative" in result
        assert "[HIGH]" in result

    def test_contested_crux_label(self):
        """Marks cruxes with entropy > 0.8 as CONTESTED."""
        crux = self._make_crux("Disputed claim", confidence=0.6, entropy=0.9)
        mock_ba = MagicMock()
        mock_ba.analyze_messages.return_value = self._make_result(cruxes=[crux])
        fetcher = make_fetcher(belief_analyzer=mock_ba)
        result = run(fetcher.gather_belief_crux_context("task", messages=["msg1"]))
        assert "(CONTESTED)" in result

    def test_evidence_suggestions_included(self):
        """Includes evidence suggestions section when available."""
        crux = self._make_crux()
        mock_ba = MagicMock()
        mock_ba.analyze_messages.return_value = self._make_result(
            cruxes=[crux],
            evidence_suggestions=["Find study on X", "Check source Y"],
        )
        fetcher = make_fetcher(belief_analyzer=mock_ba)
        result = run(fetcher.gather_belief_crux_context("task", messages=["m1"]))
        assert "Evidence Needed" in result
        assert "Find study on X" in result

    def test_top_k_cruxes_respected(self):
        """Only includes top_k_cruxes cruxes in output."""
        cruxes = [self._make_crux(f"Claim {i}") for i in range(5)]
        mock_ba = MagicMock()
        mock_ba.analyze_messages.return_value = self._make_result(cruxes=cruxes)
        fetcher = make_fetcher(belief_analyzer=mock_ba)
        result = run(fetcher.gather_belief_crux_context("task", messages=["m"], top_k_cruxes=2))
        assert "Claim 0" in result
        assert "Claim 1" in result
        assert "Claim 2" not in result

    def test_value_error_returns_none(self):
        """Returns None on ValueError from analyzer."""
        mock_ba = MagicMock()
        mock_ba.analyze_messages.side_effect = ValueError("bad input")
        fetcher = make_fetcher(belief_analyzer=mock_ba)
        result = run(fetcher.gather_belief_crux_context("task", messages=["m"]))
        assert result is None

    def test_runtime_error_returns_none(self):
        """Returns None on RuntimeError from analyzer."""
        mock_ba = MagicMock()
        mock_ba.analyze_messages.side_effect = RuntimeError("crash")
        fetcher = make_fetcher(belief_analyzer=mock_ba)
        result = run(fetcher.gather_belief_crux_context("task", messages=["m"]))
        assert result is None


# ===========================================================================
# TestGatherCulturePatternsContext
# ===========================================================================


class TestGatherCulturePatternsContext:
    """Tests for gather_culture_patterns_context."""

    def _make_pattern(
        self,
        pattern_type="consensus",
        description="Build consensus early",
        confidence=0.75,
        observations=10,
    ):
        p = MagicMock()
        p.pattern_type = pattern_type
        p.description = description
        p.confidence = confidence
        p.observations = observations
        return p

    def test_no_mound_returns_none(self):
        """Returns None when knowledge_mound is not configured."""
        fetcher = make_fetcher(knowledge_mound=None)
        result = run(fetcher.gather_culture_patterns_context("task"))
        assert result is None

    def test_uses_get_culture_context_if_available(self):
        """Uses mound.get_culture_context() when the method is available."""
        mock_mound = MagicMock()
        mock_mound.get_culture_context = AsyncMock(return_value="## CULTURE\nPattern A")
        fetcher = make_fetcher(knowledge_mound=mock_mound)
        result = run(fetcher.gather_culture_patterns_context("task", workspace_id="ws1"))
        assert result == "## CULTURE\nPattern A"
        mock_mound.get_culture_context.assert_called_once_with(
            org_id="ws1", task="task", max_documents=5
        )

    def test_get_culture_context_returns_none(self):
        """Returns None when get_culture_context returns falsy."""
        mock_mound = MagicMock()
        mock_mound.get_culture_context = AsyncMock(return_value=None)
        fetcher = make_fetcher(knowledge_mound=mock_mound)
        result = run(fetcher.gather_culture_patterns_context("task"))
        assert result is None

    def test_fallback_to_culture_accumulator(self):
        """Falls back to CultureAccumulator when mound lacks get_culture_context."""
        pattern = self._make_pattern()

        mock_mound = MagicMock(spec=[])  # no get_culture_context attr
        mock_mound._culture_accumulator = None  # triggers CultureAccumulator creation

        mock_accumulator = MagicMock()
        mock_accumulator.get_patterns.return_value = [pattern]

        mock_accumulator_class = MagicMock(return_value=mock_accumulator)
        mock_culture_module = MagicMock()
        mock_culture_module.CultureAccumulator = mock_accumulator_class

        fetcher = make_fetcher(knowledge_mound=mock_mound)
        with patch.dict(
            sys.modules,
            {
                "aragora.knowledge.mound.culture.accumulator": mock_culture_module,
            },
        ):
            result = run(fetcher.gather_culture_patterns_context("task"))

        assert result is not None
        assert "ORGANIZATIONAL CULTURE PATTERNS" in result

    def test_no_patterns_returns_none(self):
        """Returns None when CultureAccumulator finds no patterns."""
        mock_mound = MagicMock(spec=[])
        mock_mound._culture_accumulator = None

        mock_accumulator = MagicMock()
        mock_accumulator.get_patterns.return_value = []

        mock_accumulator_class = MagicMock(return_value=mock_accumulator)
        mock_culture_module = MagicMock()
        mock_culture_module.CultureAccumulator = mock_accumulator_class

        fetcher = make_fetcher(knowledge_mound=mock_mound)
        with patch.dict(
            sys.modules,
            {
                "aragora.knowledge.mound.culture.accumulator": mock_culture_module,
            },
        ):
            result = run(fetcher.gather_culture_patterns_context("task"))

        assert result is None

    def test_import_error_returns_none(self):
        """Returns None when CultureAccumulator import fails."""
        mock_mound = MagicMock(spec=[])
        fetcher = make_fetcher(knowledge_mound=mock_mound)
        with patch.dict(
            sys.modules,
            {
                "aragora.knowledge.mound.culture.accumulator": None,
            },
        ):
            result = run(fetcher.gather_culture_patterns_context("task"))
        assert result is None

    def test_value_error_returns_none(self):
        """Returns None on ValueError."""
        mock_mound = MagicMock()
        mock_mound.get_culture_context = AsyncMock(side_effect=ValueError("fail"))
        fetcher = make_fetcher(knowledge_mound=mock_mound)
        result = run(fetcher.gather_culture_patterns_context("task"))
        assert result is None

    def test_workspace_id_fallback_to_instance_default(self):
        """Uses knowledge_workspace_id when workspace_id arg is None."""
        mock_mound = MagicMock()
        mock_mound.get_culture_context = AsyncMock(return_value="ctx")
        fetcher = make_fetcher(knowledge_mound=mock_mound, knowledge_workspace_id="my_ws")
        run(fetcher.gather_culture_patterns_context("task", workspace_id=None))
        mock_mound.get_culture_context.assert_called_once_with(
            org_id="my_ws", task="task", max_documents=5
        )


# ===========================================================================
# TestTimeoutWrappers
# ===========================================================================


class TestTimeoutWrappers:
    """Tests for timeout-wrapped versions of each gather method."""

    def test_gather_evidence_with_timeout_success(self):
        """Evidence timeout wrapper passes through result on success."""
        fetcher = make_fetcher()
        with patch.object(
            fetcher, "gather_evidence_context", new=AsyncMock(return_value=("ctx", "pack"))
        ):
            ctx, pack = run(fetcher.gather_evidence_with_timeout("task"))
        assert ctx == "ctx"
        assert pack == "pack"

    def test_gather_evidence_with_timeout_fires(self):
        """Evidence timeout wrapper returns (None, None) on TimeoutError."""
        fetcher = make_fetcher()
        with patch(
            "aragora.debate.context.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=asyncio.TimeoutError()),
        ):
            ctx, pack = run(fetcher.gather_evidence_with_timeout("task"))
        assert ctx is None
        assert pack is None

    def test_gather_trending_with_timeout_success(self):
        """Trending timeout wrapper passes through result on success."""
        fetcher = make_fetcher(enable_trending_context=True)
        with patch.object(
            fetcher, "gather_trending_context", new=AsyncMock(return_value=("ctx", ["t"]))
        ):
            ctx, topics = run(fetcher.gather_trending_with_timeout())
        assert ctx == "ctx"
        assert topics == ["t"]

    def test_gather_trending_with_timeout_fires(self):
        """Trending timeout wrapper returns (None, []) on TimeoutError."""
        fetcher = make_fetcher(enable_trending_context=True)
        with patch(
            "aragora.debate.context.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=asyncio.TimeoutError()),
        ):
            ctx, topics = run(fetcher.gather_trending_with_timeout())
        assert ctx is None
        assert topics == []

    def test_gather_knowledge_mound_with_timeout_success(self):
        """KM timeout wrapper passes through result on success."""
        fetcher = make_fetcher()
        with patch.object(
            fetcher, "gather_knowledge_mound_context", new=AsyncMock(return_value="km ctx")
        ):
            result = run(fetcher.gather_knowledge_mound_with_timeout("task"))
        assert result == "km ctx"

    def test_gather_knowledge_mound_with_timeout_fires(self):
        """KM timeout wrapper returns None on TimeoutError."""
        fetcher = make_fetcher()
        with patch(
            "aragora.debate.context.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=asyncio.TimeoutError()),
        ):
            result = run(fetcher.gather_knowledge_mound_with_timeout("task"))
        assert result is None

    def test_gather_threat_intel_with_timeout_success(self):
        """Threat intel timeout wrapper passes through result on success."""
        fetcher = make_fetcher()
        with patch.object(
            fetcher, "gather_threat_intel_context", new=AsyncMock(return_value="ti ctx")
        ):
            result = run(fetcher.gather_threat_intel_with_timeout("task"))
        assert result == "ti ctx"

    def test_gather_threat_intel_with_timeout_fires(self):
        """Threat intel timeout wrapper returns None on TimeoutError."""
        fetcher = make_fetcher()
        with patch(
            "aragora.debate.context.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=asyncio.TimeoutError()),
        ):
            result = run(fetcher.gather_threat_intel_with_timeout("task"))
        assert result is None

    def test_gather_belief_with_timeout_success(self):
        """Belief timeout wrapper passes through result on success."""
        fetcher = make_fetcher(belief_analyzer=MagicMock())
        with patch.object(
            fetcher, "gather_belief_crux_context", new=AsyncMock(return_value="belief ctx")
        ):
            result = run(fetcher.gather_belief_with_timeout("task", messages=["m"]))
        assert result == "belief ctx"

    def test_gather_belief_with_timeout_fires(self):
        """Belief timeout wrapper returns None on TimeoutError."""
        fetcher = make_fetcher()
        with patch(
            "aragora.debate.context.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=asyncio.TimeoutError()),
        ):
            result = run(fetcher.gather_belief_with_timeout("task"))
        assert result is None

    def test_gather_culture_with_timeout_success(self):
        """Culture timeout wrapper passes through result on success."""
        fetcher = make_fetcher()
        with patch.object(
            fetcher,
            "gather_culture_patterns_context",
            new=AsyncMock(return_value="culture ctx"),
        ):
            result = run(fetcher.gather_culture_with_timeout("task"))
        assert result == "culture ctx"

    def test_gather_culture_with_timeout_fires(self):
        """Culture timeout wrapper returns None on TimeoutError."""
        fetcher = make_fetcher()
        with patch(
            "aragora.debate.context.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=asyncio.TimeoutError()),
        ):
            result = run(fetcher.gather_culture_with_timeout("task"))
        assert result is None


# ===========================================================================
# TestModuleConstants
# ===========================================================================


class TestModuleConstants:
    """Verify that timeout constants are exported and have reasonable values."""

    def test_claude_search_timeout_positive(self):
        assert CLAUDE_SEARCH_TIMEOUT > 0

    def test_evidence_timeout_positive(self):
        assert EVIDENCE_TIMEOUT > 0

    def test_trending_timeout_positive(self):
        assert TRENDING_TIMEOUT > 0

    def test_knowledge_mound_timeout_positive(self):
        assert KNOWLEDGE_MOUND_TIMEOUT > 0

    def test_belief_crux_timeout_positive(self):
        assert BELIEF_CRUX_TIMEOUT > 0

    def test_threat_intel_timeout_positive(self):
        assert THREAT_INTEL_TIMEOUT > 0
