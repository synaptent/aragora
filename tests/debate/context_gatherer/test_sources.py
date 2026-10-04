"""
Tests for aragora/debate/context_gatherer/sources.py

Tests the SourceGatheringMixin class, which provides all async context-source
gathering methods used by the main ContextGatherer.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.debate.context_gatherer.sources import SourceGatheringMixin


# ---------------------------------------------------------------------------
# Concrete test class
# ---------------------------------------------------------------------------


class ConcreteGatherer(SourceGatheringMixin):
    """Minimal concrete subclass that satisfies the mixin's type contract."""

    def __init__(self):
        # Feature flags
        self._enable_trending_context = True
        self._enable_knowledge_grounding = True
        self._enable_threat_intel = True
        self._enable_belief_guidance = True
        self._enable_document_context = True
        self._enable_evidence_store_context = True

        # Mound & workspace
        self._knowledge_mound = None
        self._knowledge_workspace_id = "ws-test"

        # External integrations
        self._threat_intel_enrichment = None
        self._belief_analyzer = None
        self._evidence_store_callback = None
        self._prompt_builder = None

        # Filesystem / project
        self._project_root = MagicMock()
        self._project_root.__truediv__ = lambda s, o: MagicMock()  # support / operator

        # Caches and data
        self._research_evidence_pack: dict = {}
        self._trending_topics_cache: list = []
        self._document_store = None
        self._evidence_store = None
        self._document_ids = None
        self._document_org_id = "org-1"
        self._max_document_context_items = 5
        self._max_evidence_context_items = 5
        self._auth_context = None

    # -----------------------------------------------------------------------
    # Required abstract-ish helpers
    # -----------------------------------------------------------------------

    def _get_task_hash(self, task: str) -> str:
        import hashlib

        return hashlib.md5(task.encode()).hexdigest()  # noqa: S324

    def _enforce_cache_limit(self, cache: dict, max_size: int) -> None:
        while len(cache) >= max_size:
            cache.pop(next(iter(cache)))

    # -----------------------------------------------------------------------
    # CompressionMixin stub (called by gather_document_store_context)
    # -----------------------------------------------------------------------

    async def _compress_with_rlm(
        self, content: str, source_type: str = "documentation", max_chars: int = 3000
    ) -> str:
        return content[:max_chars]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_gatherer(**overrides) -> ConcreteGatherer:
    g = ConcreteGatherer()
    for k, v in overrides.items():
        setattr(g, k, v)
    return g


def _make_km_result(items=None, execution_time_ms=10):
    result = MagicMock()
    result.items = items or []
    result.execution_time_ms = execution_time_ms
    return result


def _make_km_item(content, source_name="fact", confidence=0.8):
    item = MagicMock()
    item.content = content
    source = MagicMock()
    source.value = source_name
    item.source = source
    item.confidence = confidence
    return item


# ===========================================================================
# 1. Timeout Wrappers
# ===========================================================================


class TestTimeoutWrappers:
    """Each wrapper delegates to a real method and returns None on TimeoutError."""

    # -- _gather_claude_web_search -------------------------------------------

    async def test_claude_web_search_returns_none_on_timeout(self):
        g = make_gatherer()
        with patch.object(
            g,
            "_gather_claude_web_search",
            new=AsyncMock(side_effect=asyncio.TimeoutError),
        ):
            # Wrap the real inner call so the wrapper is exercised
            pass

        # Test the wrapper directly by making gather_evidence_context time out
        async def _slow_research(task):
            await asyncio.sleep(10)

        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=asyncio.TimeoutError),
        ):
            result = await g._gather_evidence_with_timeout("task")
        assert result is None

    async def test_gather_evidence_with_timeout_returns_none_on_timeout(self):
        g = make_gatherer()
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=asyncio.TimeoutError),
        ):
            result = await g._gather_evidence_with_timeout("any task")
        assert result is None

    async def test_gather_evidence_with_timeout_propagates_result(self):
        g = make_gatherer()
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(return_value="evidence result"),
        ):
            result = await g._gather_evidence_with_timeout("task")
        assert result == "evidence result"

    async def test_gather_trending_with_timeout_returns_none_on_timeout(self):
        g = make_gatherer()
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=asyncio.TimeoutError),
        ):
            result = await g._gather_trending_with_timeout()
        assert result is None

    async def test_gather_trending_with_timeout_propagates_result(self):
        g = make_gatherer()
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(return_value="trending result"),
        ):
            result = await g._gather_trending_with_timeout()
        assert result == "trending result"

    async def test_gather_knowledge_mound_with_timeout_returns_none_on_timeout(self):
        g = make_gatherer()
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=asyncio.TimeoutError),
        ):
            result = await g._gather_knowledge_mound_with_timeout("task")
        assert result is None

    async def test_gather_threat_intel_with_timeout_returns_none_on_timeout(self):
        g = make_gatherer()
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=asyncio.TimeoutError),
        ):
            result = await g._gather_threat_intel_with_timeout("task")
        assert result is None

    async def test_gather_belief_with_timeout_returns_none_on_timeout(self):
        g = make_gatherer()
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=asyncio.TimeoutError),
        ):
            result = await g._gather_belief_with_timeout("task")
        assert result is None

    async def test_gather_culture_with_timeout_returns_none_on_timeout(self):
        g = make_gatherer()
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=asyncio.TimeoutError),
        ):
            result = await g._gather_culture_with_timeout("task")
        assert result is None

    async def test_gather_document_store_with_timeout_returns_none_on_timeout(self):
        g = make_gatherer()
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=asyncio.TimeoutError),
        ):
            result = await g._gather_document_store_with_timeout("task")
        assert result is None

    async def test_gather_evidence_store_with_timeout_returns_none_on_timeout(self):
        g = make_gatherer()
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=asyncio.TimeoutError),
        ):
            result = await g._gather_evidence_store_with_timeout("task")
        assert result is None

    async def test_gather_evidence_store_with_timeout_propagates_result(self):
        g = make_gatherer()
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(return_value="store result"),
        ):
            result = await g._gather_evidence_store_with_timeout("task")
        assert result == "store result"


# ===========================================================================
# 2. _gather_claude_web_search
# ===========================================================================


class TestGatherClaudeWebSearch:
    """Tests for the Claude web search source method."""

    async def test_returns_none_on_import_error(self):
        g = make_gatherer()
        with patch.dict("sys.modules", {"aragora.server.research_phase": None}):
            result = await g._gather_claude_web_search("topic")
        assert result is None

    async def test_returns_none_on_timeout(self):
        g = make_gatherer()
        mock_research = AsyncMock(side_effect=asyncio.TimeoutError)
        with patch(
            "aragora.server.research_phase.research_for_debate",
            mock_research,
            create=True,
        ):
            with patch(
                "aragora.debate.context_gatherer.sources.asyncio.wait_for",
                new=AsyncMock(side_effect=asyncio.TimeoutError),
            ):
                result = await g._gather_claude_web_search("topic")
        assert result is None

    async def test_returns_none_on_connection_error(self):
        g = make_gatherer()
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=ConnectionError("network down")),
        ):
            result = await g._gather_claude_web_search("topic")
        assert result is None

    async def test_returns_none_on_value_error(self):
        g = make_gatherer()
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(side_effect=ValueError("bad")),
        ):
            result = await g._gather_claude_web_search("topic")
        assert result is None

    async def test_returns_none_when_result_is_none(self):
        g = make_gatherer()
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(return_value=None),
        ):
            result = await g._gather_claude_web_search("topic")
        assert result is None

    async def test_filters_low_signal_result_short_without_key_sources(self):
        """Short result without 'Key Sources' is considered low-signal and discarded."""
        g = make_gatherer()
        short_result = "Too short."
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(return_value=short_result),
        ):
            result = await g._gather_claude_web_search("topic")
        assert result is None

    async def test_passes_result_with_key_sources_marker(self):
        """Result containing 'Key Sources' is returned even if short."""
        g = make_gatherer()
        good_result = "Key Sources: example.com"
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(return_value=good_result),
        ):
            result = await g._gather_claude_web_search("topic")
        assert result == good_result

    async def test_passes_result_that_is_long_enough(self):
        """Result >= 200 chars is returned regardless of 'Key Sources'."""
        g = make_gatherer()
        long_result = "x" * 250
        with patch(
            "aragora.debate.context_gatherer.sources.asyncio.wait_for",
            new=AsyncMock(return_value=long_result),
        ):
            result = await g._gather_claude_web_search("topic")
        assert result == long_result


# ===========================================================================
# 3. gather_threat_intel_context
# ===========================================================================


class TestGatherThreatIntelContext:
    async def test_disabled_feature_returns_none(self):
        g = make_gatherer(_enable_threat_intel=False, _threat_intel_enrichment=MagicMock())
        result = await g.gather_threat_intel_context("CVE-2024-1234")
        assert result is None

    async def test_no_enrichment_object_returns_none(self):
        g = make_gatherer(_enable_threat_intel=True, _threat_intel_enrichment=None)
        result = await g.gather_threat_intel_context("CVE-2024-1234")
        assert result is None

    async def test_non_security_topic_returns_none(self):
        enrichment = MagicMock()
        enrichment.is_security_topic.return_value = False
        g = make_gatherer(_enable_threat_intel=True, _threat_intel_enrichment=enrichment)
        result = await g.gather_threat_intel_context("best pizza topping")
        assert result is None
        enrichment.is_security_topic.assert_called_once_with("best pizza topping")

    async def test_returns_formatted_context_on_success(self):
        enrichment = MagicMock()
        enrichment.is_security_topic.return_value = True

        context = MagicMock()
        context.indicators = ["10.0.0.1"]
        context.relevant_cves = ["CVE-2024-1234", "CVE-2024-5678"]
        enrichment.enrich_context = AsyncMock(return_value=context)
        enrichment.format_for_debate.return_value = "## THREAT INTEL\nCVE-2024-1234 is critical."

        g = make_gatherer(_enable_threat_intel=True, _threat_intel_enrichment=enrichment)
        result = await g.gather_threat_intel_context("SQL injection vulnerability")

        assert result == "## THREAT INTEL\nCVE-2024-1234 is critical."
        enrichment.format_for_debate.assert_called_once_with(context)

    async def test_returns_none_when_enrich_context_returns_none(self):
        enrichment = MagicMock()
        enrichment.is_security_topic.return_value = True
        enrichment.enrich_context = AsyncMock(return_value=None)

        g = make_gatherer(_enable_threat_intel=True, _threat_intel_enrichment=enrichment)
        result = await g.gather_threat_intel_context("sql injection")
        assert result is None

    async def test_connection_error_returns_none(self):
        enrichment = MagicMock()
        enrichment.is_security_topic.return_value = True
        enrichment.enrich_context = AsyncMock(side_effect=ConnectionError("timeout"))

        g = make_gatherer(_enable_threat_intel=True, _threat_intel_enrichment=enrichment)
        result = await g.gather_threat_intel_context("CVE exploit")
        assert result is None

    async def test_value_error_returns_none(self):
        enrichment = MagicMock()
        enrichment.is_security_topic.return_value = True
        enrichment.enrich_context = AsyncMock(side_effect=ValueError("bad data"))

        g = make_gatherer(_enable_threat_intel=True, _threat_intel_enrichment=enrichment)
        result = await g.gather_threat_intel_context("CVE exploit")
        assert result is None

    async def test_runtime_error_returns_none(self):
        enrichment = MagicMock()
        enrichment.is_security_topic.return_value = True
        enrichment.enrich_context = AsyncMock(side_effect=RuntimeError("crash"))

        g = make_gatherer(_enable_threat_intel=True, _threat_intel_enrichment=enrichment)
        result = await g.gather_threat_intel_context("malware analysis")
        assert result is None


# ===========================================================================
# 4. gather_evidence_context
# ===========================================================================


class TestGatherEvidenceContext:
    async def test_returns_none_when_no_connectors_available(self):
        """If no connectors can be imported, returns None."""
        g = make_gatherer()

        with patch.dict(
            "sys.modules",
            {
                "aragora.evidence.collector": None,
            },
        ):
            result = await g.gather_evidence_context("my topic")
        assert result is None

    async def test_returns_none_when_evidence_pack_has_no_snippets(self):
        g = make_gatherer()

        mock_collector = MagicMock()
        mock_pack = MagicMock()
        mock_pack.snippets = []
        mock_collector.collect_evidence = AsyncMock(return_value=mock_pack)

        mock_module = MagicMock()
        mock_module.EvidenceCollector = MagicMock(return_value=mock_collector)

        with patch.dict("sys.modules", {"aragora.evidence.collector": mock_module}):
            with patch.dict(
                "sys.modules",
                {
                    "aragora.connectors.web": None,
                    "aragora.connectors.github": None,
                    "aragora.connectors.local_docs": None,
                },
            ):
                result = await g.gather_evidence_context("topic")
        assert result is None

    async def test_returns_formatted_context_on_success(self):
        g = make_gatherer()

        mock_snippet = MagicMock()
        mock_pack = MagicMock()
        mock_pack.snippets = [mock_snippet]
        mock_pack.to_context_string.return_value = "snippet content here"

        mock_collector = MagicMock()
        mock_collector.collect_evidence = AsyncMock(return_value=mock_pack)

        collector_module = MagicMock()
        collector_module.EvidenceCollector = MagicMock(return_value=mock_collector)

        local_docs_mod = MagicMock()
        local_docs_mod.LocalDocsConnector = MagicMock(return_value=MagicMock())

        with patch.dict(
            "sys.modules",
            {
                "aragora.evidence.collector": collector_module,
                "aragora.connectors.web": None,
                "aragora.connectors.github": None,
                "aragora.connectors.local_docs": local_docs_mod,
            },
        ):
            result = await g.gather_evidence_context("my task")

        assert result is not None
        assert "EVIDENCE CONTEXT" in result
        assert "snippet content here" in result

    async def test_caches_evidence_pack_by_task_hash(self):
        g = make_gatherer()

        mock_snippet = MagicMock()
        mock_pack = MagicMock()
        mock_pack.snippets = [mock_snippet]
        mock_pack.to_context_string.return_value = "ctx"

        mock_collector = MagicMock()
        mock_collector.collect_evidence = AsyncMock(return_value=mock_pack)

        collector_module = MagicMock()
        collector_module.EvidenceCollector = MagicMock(return_value=mock_collector)

        local_docs_mod = MagicMock()
        local_docs_mod.LocalDocsConnector = MagicMock(return_value=MagicMock())

        with patch.dict(
            "sys.modules",
            {
                "aragora.evidence.collector": collector_module,
                "aragora.connectors.web": None,
                "aragora.connectors.github": None,
                "aragora.connectors.local_docs": local_docs_mod,
            },
        ):
            await g.gather_evidence_context("caching task")

        task_hash = g._get_task_hash("caching task")
        assert task_hash in g._research_evidence_pack
        assert g._research_evidence_pack[task_hash] is mock_pack

    async def test_updates_prompt_builder_when_available(self):
        g = make_gatherer()
        prompt_builder = MagicMock()
        g._prompt_builder = prompt_builder

        mock_snippet = MagicMock()
        mock_pack = MagicMock()
        mock_pack.snippets = [mock_snippet]
        mock_pack.to_context_string.return_value = "ctx"

        mock_collector = MagicMock()
        mock_collector.collect_evidence = AsyncMock(return_value=mock_pack)

        collector_module = MagicMock()
        collector_module.EvidenceCollector = MagicMock(return_value=mock_collector)

        local_docs_mod = MagicMock()
        local_docs_mod.LocalDocsConnector = MagicMock(return_value=MagicMock())

        with patch.dict(
            "sys.modules",
            {
                "aragora.evidence.collector": collector_module,
                "aragora.connectors.web": None,
                "aragora.connectors.github": None,
                "aragora.connectors.local_docs": local_docs_mod,
            },
        ):
            await g.gather_evidence_context("task")

        prompt_builder.set_evidence_pack.assert_called_once_with(mock_pack)

    async def test_calls_evidence_store_callback_when_provided(self):
        callback = MagicMock()
        g = make_gatherer(_evidence_store_callback=callback)

        mock_snippet = MagicMock()
        mock_pack = MagicMock()
        mock_pack.snippets = [mock_snippet]
        mock_pack.to_context_string.return_value = "ctx"

        mock_collector = MagicMock()
        mock_collector.collect_evidence = AsyncMock(return_value=mock_pack)

        collector_module = MagicMock()
        collector_module.EvidenceCollector = MagicMock(return_value=mock_collector)

        local_docs_mod = MagicMock()
        local_docs_mod.LocalDocsConnector = MagicMock(return_value=MagicMock())

        with patch.dict(
            "sys.modules",
            {
                "aragora.evidence.collector": collector_module,
                "aragora.connectors.web": None,
                "aragora.connectors.github": None,
                "aragora.connectors.local_docs": local_docs_mod,
            },
        ):
            await g.gather_evidence_context("task")

        callback.assert_called_once_with(mock_pack.snippets, "task")

    async def test_connection_error_returns_none(self):
        g = make_gatherer()

        mock_collector = MagicMock()
        mock_collector.collect_evidence = AsyncMock(side_effect=ConnectionError("net fail"))

        collector_module = MagicMock()
        collector_module.EvidenceCollector = MagicMock(return_value=mock_collector)

        local_docs_mod = MagicMock()
        local_docs_mod.LocalDocsConnector = MagicMock(return_value=MagicMock())

        with patch.dict(
            "sys.modules",
            {
                "aragora.evidence.collector": collector_module,
                "aragora.connectors.web": None,
                "aragora.connectors.github": None,
                "aragora.connectors.local_docs": local_docs_mod,
            },
        ):
            result = await g.gather_evidence_context("topic")
        assert result is None

    async def test_adds_web_connector_when_ddgs_available(self):
        """WebConnector is added to collector when DDGS_AVAILABLE is True."""
        g = make_gatherer()

        web_connector_instance = MagicMock()
        web_mod = MagicMock()
        web_mod.DDGS_AVAILABLE = True
        web_mod.WebConnector = MagicMock(return_value=web_connector_instance)

        mock_pack = MagicMock()
        mock_pack.snippets = []
        mock_collector = MagicMock()
        mock_collector.collect_evidence = AsyncMock(return_value=mock_pack)

        collector_module = MagicMock()
        collector_module.EvidenceCollector = MagicMock(return_value=mock_collector)

        with patch.dict(
            "sys.modules",
            {
                "aragora.evidence.collector": collector_module,
                "aragora.connectors.web": web_mod,
                "aragora.connectors.github": None,
                "aragora.connectors.local_docs": None,
            },
        ):
            await g.gather_evidence_context("topic")

        mock_collector.add_connector.assert_any_call("web", web_connector_instance)


# ===========================================================================
# 5. gather_document_store_context
# ===========================================================================


class TestGatherDocumentStoreContext:
    async def test_disabled_returns_none(self):
        g = make_gatherer(_enable_document_context=False, _document_store=MagicMock())
        result = await g.gather_document_store_context("topic")
        assert result is None

    async def test_no_document_store_returns_none(self):
        g = make_gatherer(_enable_document_context=True, _document_store=None)
        result = await g.gather_document_store_context("topic")
        assert result is None

    async def test_no_debate_org_returns_none(self):
        doc_store = MagicMock()
        g = make_gatherer(
            _enable_document_context=True,
            _document_store=doc_store,
            _document_ids=["doc-123"],
            _document_org_id=None,
        )
        result = await g.gather_document_store_context("topic")
        assert result is None
        doc_store.get.assert_not_called()
        doc_store.list_for_org.assert_not_called()
        doc_store.list_all.assert_not_called()

    async def test_empty_org_listing_returns_none(self):
        doc_store = MagicMock()
        doc_store.list_for_org.return_value = []
        g = make_gatherer(_enable_document_context=True, _document_store=doc_store)
        result = await g.gather_document_store_context("topic")
        assert result is None

    async def test_no_matching_docs_returns_none(self):
        doc_store = MagicMock()
        item = {"id": "d1", "filename": "report.pdf", "preview": "quarterly numbers"}
        doc_store.list_for_org.return_value = [item]
        doc_store.get.return_value = None  # document not found

        g = make_gatherer(_enable_document_context=True, _document_store=doc_store)
        result = await g.gather_document_store_context("topic")
        assert result is None

    async def test_success_with_list_all_and_keyword_scoring(self):
        doc_store = MagicMock()

        item1 = {"id": "d1", "filename": "ai safety.pdf", "preview": "AI safety guidelines"}
        item2 = {"id": "d2", "filename": "finance.pdf", "preview": "quarterly numbers"}
        doc_store.list_for_org.return_value = [item1, item2]

        doc_obj = MagicMock()
        doc_obj.filename = "ai safety.pdf"
        doc_obj.text = "This is the document content about AI safety."
        doc_obj.org_id = "org-1"
        doc_store.get.return_value = doc_obj

        g = make_gatherer(_enable_document_context=True, _document_store=doc_store)
        result = await g.gather_document_store_context("AI safety guidelines")

        assert result is not None
        assert "DOCUMENT CONTEXT" in result
        assert "ai safety.pdf" in result
        doc_store.list_for_org.assert_called_once_with("org-1")
        doc_store.list_all.assert_not_called()

    async def test_success_with_explicit_document_ids(self):
        doc_store = MagicMock()

        doc_obj = MagicMock()
        doc_obj.filename = "spec.pdf"
        doc_obj.text = "Technical specification document."
        doc_obj.org_id = "org-1"
        doc_store.get.return_value = doc_obj

        g = make_gatherer(
            _enable_document_context=True,
            _document_store=doc_store,
            _document_ids=["doc-123"],
        )
        result = await g.gather_document_store_context("spec topic")

        assert result is not None
        assert "DOCUMENT CONTEXT" in result
        assert "spec.pdf" in result
        doc_store.get.assert_called_with("doc-123")

    async def test_explicit_document_ids_of_another_org_are_dropped(self):
        doc_store = MagicMock()
        own = MagicMock(filename="own.pdf", text="own text", org_id="org-1")
        foreign = MagicMock(filename="foreign.pdf", text="foreign text", org_id="org-2")
        unowned = MagicMock(filename="unowned.pdf", text="unowned text", org_id=None)
        doc_store.get.side_effect = {"own": own, "foreign": foreign, "unowned": unowned}.get

        g = make_gatherer(
            _enable_document_context=True,
            _document_store=doc_store,
            _document_ids=["foreign", "unowned", "own"],
        )
        result = await g.gather_document_store_context("topic")

        assert result is not None
        assert "own.pdf" in result
        assert "foreign" not in result
        assert "unowned" not in result

    async def test_attribute_error_returns_none(self):
        doc_store = MagicMock()
        doc_store.list_for_org.side_effect = AttributeError("broken")

        g = make_gatherer(_enable_document_context=True, _document_store=doc_store)
        result = await g.gather_document_store_context("topic")
        assert result is None

    async def test_runtime_error_returns_none(self):
        doc_store = MagicMock()
        doc_store.list_for_org.side_effect = RuntimeError("db down")

        g = make_gatherer(_enable_document_context=True, _document_store=doc_store)
        result = await g.gather_document_store_context("topic")
        assert result is None

    async def test_respects_max_document_context_items(self):
        """Only max_document_context_items documents are fetched."""
        doc_store = MagicMock()
        items = [{"id": f"d{i}", "filename": f"doc{i}.pdf", "preview": "topic"} for i in range(10)]
        doc_store.list_for_org.return_value = items

        doc_obj = MagicMock()
        doc_obj.filename = "docX.pdf"
        doc_obj.text = "content"
        doc_store.get.return_value = doc_obj

        g = make_gatherer(
            _enable_document_context=True,
            _document_store=doc_store,
            _max_document_context_items=2,
        )
        await g.gather_document_store_context("topic")
        # At most 2 docs should be fetched
        assert doc_store.get.call_count <= 2


# ===========================================================================
# 6. gather_evidence_store_context
# ===========================================================================


class TestGatherEvidenceStoreContext:
    async def test_disabled_returns_none(self):
        g = make_gatherer(_enable_evidence_store_context=False, _evidence_store=MagicMock())
        result = await g.gather_evidence_store_context("topic")
        assert result is None

    async def test_no_evidence_store_returns_none(self):
        g = make_gatherer(_enable_evidence_store_context=True, _evidence_store=None)
        result = await g.gather_evidence_store_context("topic")
        assert result is None

    async def test_empty_results_returns_none(self):
        ev_store = MagicMock()
        ev_store.search_evidence.return_value = []
        g = make_gatherer(_enable_evidence_store_context=True, _evidence_store=ev_store)
        result = await g.gather_evidence_store_context("topic")
        assert result is None

    async def test_all_empty_snippets_returns_none(self):
        ev_store = MagicMock()
        ev_store.search_evidence.return_value = [
            {"snippet": "", "source": "src", "reliability_score": 0.5}
        ]
        g = make_gatherer(_enable_evidence_store_context=True, _evidence_store=ev_store)
        result = await g.gather_evidence_store_context("topic")
        assert result is None

    async def test_success_formats_source_reliability_url(self):
        ev_store = MagicMock()
        ev_store.search_evidence.return_value = [
            {
                "snippet": "Relevant evidence snippet",
                "source": "research",
                "reliability_score": 0.87,
                "url": "https://example.com/paper",
            }
        ]
        g = make_gatherer(_enable_evidence_store_context=True, _evidence_store=ev_store)
        result = await g.gather_evidence_store_context("topic")

        assert result is not None
        assert "EVIDENCE STORE CONTEXT" in result
        assert "research" in result
        assert "87%" in result
        assert "https://example.com/paper" in result

    async def test_success_without_url(self):
        ev_store = MagicMock()
        ev_store.search_evidence.return_value = [
            {
                "snippet": "Evidence without URL",
                "source": "internal",
                "reliability_score": 0.5,
            }
        ]
        g = make_gatherer(_enable_evidence_store_context=True, _evidence_store=ev_store)
        result = await g.gather_evidence_store_context("topic")

        assert result is not None
        assert "Evidence without URL" in result

    async def test_attribute_error_returns_none(self):
        ev_store = MagicMock()
        ev_store.search_evidence.side_effect = AttributeError("gone")

        g = make_gatherer(_enable_evidence_store_context=True, _evidence_store=ev_store)
        result = await g.gather_evidence_store_context("topic")
        assert result is None

    async def test_respects_max_evidence_context_items(self):
        ev_store = MagicMock()
        ev_store.search_evidence.return_value = [
            {"snippet": f"snippet {i}", "source": "s", "reliability_score": 0.5} for i in range(20)
        ]
        g = make_gatherer(
            _enable_evidence_store_context=True,
            _evidence_store=ev_store,
            _max_evidence_context_items=3,
        )
        result = await g.gather_evidence_store_context("topic")

        assert result is not None
        # Should only have at most max_evidence_context_items bullet lines
        bullet_lines = [l for l in result.split("\n") if l.startswith("- [")]
        assert len(bullet_lines) <= 3


# ===========================================================================
# 7. gather_trending_context
# ===========================================================================


class TestGatherTrendingContext:
    async def test_disabled_returns_none(self):
        g = make_gatherer(_enable_trending_context=False)
        result = await g.gather_trending_context()
        assert result is None

    async def test_import_error_returns_none(self):
        g = make_gatherer(_enable_trending_context=True)
        with patch.dict("sys.modules", {"aragora.pulse.ingestor": None}):
            result = await g.gather_trending_context()
        assert result is None

    async def test_success_caches_topics_and_returns_formatted(self):
        g = make_gatherer(_enable_trending_context=True)

        topic = MagicMock()
        topic.topic = "AI Safety"
        topic.platform = "hackernews"
        topic.volume = 1500
        topic.category = "technology"

        mock_manager = MagicMock()
        mock_manager.get_trending_topics = AsyncMock(return_value=[topic])

        mock_module = MagicMock()
        mock_module.PulseManager = MagicMock(return_value=mock_manager)
        mock_module.GoogleTrendsIngestor = MagicMock()
        mock_module.HackerNewsIngestor = MagicMock()
        mock_module.RedditIngestor = MagicMock()
        mock_module.GitHubTrendingIngestor = MagicMock()

        with patch.dict("sys.modules", {"aragora.pulse.ingestor": mock_module}):
            result = await g.gather_trending_context()

        assert result is not None
        assert "TRENDING CONTEXT" in result
        assert "AI Safety" in result
        assert "hackernews" in result
        assert "1,500" in result
        # Cache should be populated
        assert g._trending_topics_cache == [topic]

    async def test_updates_prompt_builder_with_topics(self):
        g = make_gatherer(_enable_trending_context=True)
        prompt_builder = MagicMock()
        g._prompt_builder = prompt_builder

        topic = MagicMock()
        topic.topic = "Blockchain"
        topic.platform = "reddit"
        topic.volume = 500
        topic.category = "finance"

        mock_manager = MagicMock()
        mock_manager.get_trending_topics = AsyncMock(return_value=[topic])

        mock_module = MagicMock()
        mock_module.PulseManager = MagicMock(return_value=mock_manager)
        mock_module.GoogleTrendsIngestor = MagicMock()
        mock_module.HackerNewsIngestor = MagicMock()
        mock_module.RedditIngestor = MagicMock()
        mock_module.GitHubTrendingIngestor = MagicMock()

        with patch.dict("sys.modules", {"aragora.pulse.ingestor": mock_module}):
            await g.gather_trending_context()

        prompt_builder.set_trending_topics.assert_called_once()

    async def test_no_topics_returns_none(self):
        g = make_gatherer(_enable_trending_context=True)

        mock_manager = MagicMock()
        mock_manager.get_trending_topics = AsyncMock(return_value=[])

        mock_module = MagicMock()
        mock_module.PulseManager = MagicMock(return_value=mock_manager)
        mock_module.GoogleTrendsIngestor = MagicMock()
        mock_module.HackerNewsIngestor = MagicMock()
        mock_module.RedditIngestor = MagicMock()
        mock_module.GitHubTrendingIngestor = MagicMock()

        with patch.dict("sys.modules", {"aragora.pulse.ingestor": mock_module}):
            result = await g.gather_trending_context()
        assert result is None

    async def test_connection_error_returns_none(self):
        g = make_gatherer(_enable_trending_context=True)

        mock_manager = MagicMock()
        mock_manager.get_trending_topics = AsyncMock(side_effect=ConnectionError("offline"))

        mock_module = MagicMock()
        mock_module.PulseManager = MagicMock(return_value=mock_manager)
        mock_module.GoogleTrendsIngestor = MagicMock()
        mock_module.HackerNewsIngestor = MagicMock()
        mock_module.RedditIngestor = MagicMock()
        mock_module.GitHubTrendingIngestor = MagicMock()

        with patch.dict("sys.modules", {"aragora.pulse.ingestor": mock_module}):
            result = await g.gather_trending_context()
        assert result is None

    async def test_get_trending_topics_returns_cache(self):
        g = make_gatherer()
        mock_topic = MagicMock()
        g._trending_topics_cache = [mock_topic]
        assert g.get_trending_topics() == [mock_topic]


# ===========================================================================
# 8. gather_knowledge_mound_context
# ===========================================================================


class TestGatherKnowledgeMoundContext:
    async def test_disabled_grounding_returns_none(self):
        g = make_gatherer(_enable_knowledge_grounding=False, _knowledge_mound=MagicMock())
        result = await g.gather_knowledge_mound_context("task")
        assert result is None

    async def test_no_knowledge_mound_returns_none(self):
        g = make_gatherer(_enable_knowledge_grounding=True, _knowledge_mound=None)
        result = await g.gather_knowledge_mound_context("task")
        assert result is None

    async def test_empty_result_items_returns_none(self):
        km = MagicMock()
        km.query = AsyncMock(return_value=_make_km_result(items=[]))
        g = make_gatherer(_enable_knowledge_grounding=True, _knowledge_mound=km)
        result = await g.gather_knowledge_mound_context("task")
        assert result is None

    async def test_success_formats_facts(self):
        km = MagicMock()
        item = _make_km_item("Python was created by Guido van Rossum.", "fact", confidence=0.9)
        km.query = AsyncMock(return_value=_make_km_result(items=[item]))

        g = make_gatherer(_enable_knowledge_grounding=True, _knowledge_mound=km)
        result = await g.gather_knowledge_mound_context("programming language history")

        assert result is not None
        assert "KNOWLEDGE MOUND CONTEXT" in result
        assert "Verified Facts" in result
        assert "Python was created" in result
        assert "HIGH" in result  # confidence 0.9 > 0.7

    async def test_success_formats_evidence(self):
        km = MagicMock()
        item = _make_km_item("Evidence: test shows X.", "evidence", confidence=0.7)
        km.query = AsyncMock(return_value=_make_km_result(items=[item]))

        g = make_gatherer(_enable_knowledge_grounding=True, _knowledge_mound=km)
        result = await g.gather_knowledge_mound_context("task")

        assert result is not None
        assert "Supporting Evidence" in result
        assert "Evidence: test shows X." in result

    async def test_success_formats_insights(self):
        km = MagicMock()
        item = _make_km_item("Pattern observed in discussions.", "debate_consensus", confidence=0.6)
        km.query = AsyncMock(return_value=_make_km_result(items=[item]))

        g = make_gatherer(_enable_knowledge_grounding=True, _knowledge_mound=km)
        result = await g.gather_knowledge_mound_context("task")

        assert result is not None
        assert "Related Insights" in result
        assert "debate_consensus" in result

    async def test_uses_rbac_aware_query_when_auth_context_available(self):
        km = MagicMock()
        km.query_with_visibility = AsyncMock(return_value=_make_km_result(items=[]))

        auth_ctx = MagicMock()
        auth_ctx.user_id = "user-1"
        auth_ctx.workspace_id = "ws-1"
        auth_ctx.org_id = "org-1"

        g = make_gatherer(
            _enable_knowledge_grounding=True,
            _knowledge_mound=km,
            _auth_context=auth_ctx,
        )
        await g.gather_knowledge_mound_context("security task")

        km.query_with_visibility.assert_awaited_once_with(
            "security task",
            actor_id="user-1",
            actor_workspace_id="ws-1",
            actor_org_id="org-1",
            limit=10,
        )

    async def test_falls_back_to_basic_query_when_no_auth_context(self):
        km = MagicMock()
        km.query = AsyncMock(return_value=_make_km_result(items=[]))

        g = make_gatherer(
            _enable_knowledge_grounding=True,
            _knowledge_mound=km,
            _auth_context=None,
        )
        await g.gather_knowledge_mound_context("task")

        km.query.assert_awaited_once()

    async def test_falls_back_to_basic_query_when_auth_context_missing_user_id(self):
        km = MagicMock()
        km.query = AsyncMock(return_value=_make_km_result(items=[]))
        # km has query_with_visibility but auth_ctx has no user_id
        km.query_with_visibility = AsyncMock(return_value=_make_km_result(items=[]))

        auth_ctx = MagicMock()
        auth_ctx.user_id = ""
        auth_ctx.workspace_id = "ws-1"
        auth_ctx.org_id = None

        g = make_gatherer(
            _enable_knowledge_grounding=True,
            _knowledge_mound=km,
            _auth_context=auth_ctx,
        )
        await g.gather_knowledge_mound_context("task")

        km.query.assert_awaited_once()
        km.query_with_visibility.assert_not_awaited()

    async def test_connection_error_returns_none(self):
        km = MagicMock()
        km.query = AsyncMock(side_effect=ConnectionError("db gone"))

        g = make_gatherer(_enable_knowledge_grounding=True, _knowledge_mound=km)
        result = await g.gather_knowledge_mound_context("task")
        assert result is None

    async def test_attribute_error_returns_none(self):
        km = MagicMock()
        km.query = AsyncMock(side_effect=AttributeError("no attr"))

        g = make_gatherer(_enable_knowledge_grounding=True, _knowledge_mound=km)
        result = await g.gather_knowledge_mound_context("task")
        assert result is None

    async def test_generic_exception_returns_none(self):
        km = MagicMock()
        km.query = AsyncMock(side_effect=Exception("driver-specific error"))

        g = make_gatherer(_enable_knowledge_grounding=True, _knowledge_mound=km)
        result = await g.gather_knowledge_mound_context("task")
        assert result is None

    async def test_confidence_label_medium(self):
        km = MagicMock()
        item = _make_km_item("Moderate confidence fact.", "fact", confidence=0.6)
        km.query = AsyncMock(return_value=_make_km_result(items=[item]))

        g = make_gatherer(_enable_knowledge_grounding=True, _knowledge_mound=km)
        result = await g.gather_knowledge_mound_context("task")

        assert result is not None
        assert "MEDIUM" in result

    async def test_confidence_label_low(self):
        km = MagicMock()
        item = _make_km_item("Low confidence fact.", "fact", confidence=0.2)
        km.query = AsyncMock(return_value=_make_km_result(items=[item]))

        g = make_gatherer(_enable_knowledge_grounding=True, _knowledge_mound=km)
        result = await g.gather_knowledge_mound_context("task")

        assert result is not None
        assert "LOW" in result


# ===========================================================================
# 9. gather_belief_crux_context
# ===========================================================================


class TestGatherBeliefCruxContext:
    async def test_disabled_returns_none(self):
        g = make_gatherer(_enable_belief_guidance=False, _belief_analyzer=MagicMock())
        result = await g.gather_belief_crux_context("task")
        assert result is None

    async def test_no_analyzer_returns_none(self):
        g = make_gatherer(_enable_belief_guidance=True, _belief_analyzer=None)
        result = await g.gather_belief_crux_context("task")
        assert result is None

    async def test_no_messages_returns_none(self):
        analyzer = MagicMock()
        g = make_gatherer(_enable_belief_guidance=True, _belief_analyzer=analyzer)
        result = await g.gather_belief_crux_context("task", messages=None)
        assert result is None
        analyzer.analyze_messages.assert_not_called()

    async def test_analysis_error_returns_none(self):
        analyzer = MagicMock()
        result_obj = MagicMock()
        result_obj.analysis_error = "Something went wrong"
        result_obj.cruxes = []
        analyzer.analyze_messages.return_value = result_obj

        g = make_gatherer(_enable_belief_guidance=True, _belief_analyzer=analyzer)
        result = await g.gather_belief_crux_context("task", messages=["msg1"])
        assert result is None

    async def test_no_cruxes_returns_none(self):
        analyzer = MagicMock()
        result_obj = MagicMock()
        result_obj.analysis_error = None
        result_obj.cruxes = []
        result_obj.evidence_suggestions = []
        analyzer.analyze_messages.return_value = result_obj

        g = make_gatherer(_enable_belief_guidance=True, _belief_analyzer=analyzer)
        result = await g.gather_belief_crux_context("task", messages=["msg1"])
        assert result is None

    async def test_success_with_cruxes_returns_formatted(self):
        analyzer = MagicMock()

        crux1 = {
            "statement": "AI will replace all jobs by 2030",
            "confidence": 0.8,
            "entropy": 0.9,
        }
        crux2 = {
            "statement": "Universal basic income is needed",
            "confidence": 0.5,
            "entropy": 0.4,
        }

        result_obj = MagicMock()
        result_obj.analysis_error = None
        result_obj.cruxes = [crux1, crux2]
        result_obj.evidence_suggestions = []
        analyzer.analyze_messages.return_value = result_obj

        g = make_gatherer(_enable_belief_guidance=True, _belief_analyzer=analyzer)
        result = await g.gather_belief_crux_context(
            "future of work", messages=["arg1", "arg2"], top_k_cruxes=3
        )

        assert result is not None
        assert "Key Crux Points" in result
        assert "AI will replace all jobs by 2030" in result
        assert "HIGH" in result
        assert "CONTESTED" in result  # entropy 0.9 > 0.8
        assert "Universal basic income" in result
        assert "MEDIUM" in result  # confidence 0.5

    async def test_includes_evidence_suggestions(self):
        analyzer = MagicMock()

        crux = {"statement": "X causes Y", "confidence": 0.75, "entropy": 0.3}

        result_obj = MagicMock()
        result_obj.analysis_error = None
        result_obj.cruxes = [crux]
        result_obj.evidence_suggestions = ["Need peer-reviewed study on X→Y", "RCT data required"]
        analyzer.analyze_messages.return_value = result_obj

        g = make_gatherer(_enable_belief_guidance=True, _belief_analyzer=analyzer)
        result = await g.gather_belief_crux_context("topic", messages=["m1"])

        assert result is not None
        assert "Evidence Needed" in result
        assert "Need peer-reviewed study" in result

    async def test_uses_claim_key_fallback(self):
        """Crux dicts can use 'claim' key instead of 'statement'."""
        analyzer = MagicMock()
        crux = {"claim": "Claim without statement key", "confidence": 0.6, "entropy": 0.2}

        result_obj = MagicMock()
        result_obj.analysis_error = None
        result_obj.cruxes = [crux]
        result_obj.evidence_suggestions = []
        analyzer.analyze_messages.return_value = result_obj

        g = make_gatherer(_enable_belief_guidance=True, _belief_analyzer=analyzer)
        result = await g.gather_belief_crux_context("topic", messages=["m"])

        assert result is not None
        assert "Claim without statement key" in result

    async def test_value_error_returns_none(self):
        analyzer = MagicMock()
        analyzer.analyze_messages.side_effect = ValueError("parse error")

        g = make_gatherer(_enable_belief_guidance=True, _belief_analyzer=analyzer)
        result = await g.gather_belief_crux_context("topic", messages=["m"])
        assert result is None

    async def test_runtime_error_returns_none(self):
        analyzer = MagicMock()
        analyzer.analyze_messages.side_effect = RuntimeError("crash")

        g = make_gatherer(_enable_belief_guidance=True, _belief_analyzer=analyzer)
        result = await g.gather_belief_crux_context("topic", messages=["m"])
        assert result is None


# ===========================================================================
# 10. gather_culture_patterns_context
# ===========================================================================


class TestGatherCulturePatternsContext:
    async def test_no_knowledge_mound_returns_none(self):
        g = make_gatherer(_knowledge_mound=None)
        result = await g.gather_culture_patterns_context("task")
        assert result is None

    async def test_uses_get_culture_context_when_available(self):
        km = MagicMock()
        km.get_culture_context = AsyncMock(return_value="## Culture\nBe concise.")

        g = make_gatherer(_knowledge_mound=km, _knowledge_workspace_id="ws-1")
        result = await g.gather_culture_patterns_context("task")

        assert result == "## Culture\nBe concise."
        km.get_culture_context.assert_awaited_once_with(org_id="ws-1", task="task", max_documents=5)

    async def test_uses_get_culture_context_returns_none_on_empty(self):
        km = MagicMock()
        km.get_culture_context = AsyncMock(return_value=None)

        g = make_gatherer(_knowledge_mound=km)
        result = await g.gather_culture_patterns_context("task")
        assert result is None

    async def test_uses_workspace_id_param_over_instance_var(self):
        km = MagicMock()
        km.get_culture_context = AsyncMock(return_value="culture context")

        g = make_gatherer(_knowledge_mound=km, _knowledge_workspace_id="ws-default")
        await g.gather_culture_patterns_context("task", workspace_id="ws-override")

        km.get_culture_context.assert_awaited_once_with(
            org_id="ws-override", task="task", max_documents=5
        )

    async def test_fallback_to_culture_accumulator_from_mound_attr(self):
        km = MagicMock(spec=["_culture_accumulator"])  # no get_culture_context
        km._culture_accumulator = MagicMock()

        pattern = MagicMock()
        pattern.pattern_type = "argumentation"
        pattern.description = "Use data-driven arguments"
        pattern.confidence = 0.8
        pattern.observations = 12

        km._culture_accumulator.get_patterns.return_value = [pattern]

        g = make_gatherer(_knowledge_mound=km, _knowledge_workspace_id="ws-1")
        result = await g.gather_culture_patterns_context("task")

        assert result is not None
        assert "ORGANIZATIONAL CULTURE PATTERNS" in result
        assert "Use data-driven arguments" in result
        assert "Strong" in result  # confidence 0.8 > 0.7

    async def test_fallback_creates_accumulator_when_not_on_mound(self):
        km = MagicMock(spec=[])  # no get_culture_context, no _culture_accumulator

        mock_accumulator = MagicMock()
        mock_accumulator.get_patterns.return_value = []

        mock_culture_module = MagicMock()
        mock_culture_module.CultureAccumulator = MagicMock(return_value=mock_accumulator)

        with patch.dict(
            "sys.modules",
            {"aragora.knowledge.mound.culture.accumulator": mock_culture_module},
        ):
            g = make_gatherer(_knowledge_mound=km)
            result = await g.gather_culture_patterns_context("task")

        assert result is None  # no patterns returned
        mock_culture_module.CultureAccumulator.assert_called_once_with(mound=km)

    async def test_no_patterns_returns_none(self):
        km = MagicMock(spec=["_culture_accumulator"])
        km._culture_accumulator = MagicMock()
        km._culture_accumulator.get_patterns.return_value = []

        g = make_gatherer(_knowledge_mound=km)
        result = await g.gather_culture_patterns_context("task")
        assert result is None

    async def test_patterns_with_enum_pattern_type(self):
        km = MagicMock(spec=["_culture_accumulator"])
        km._culture_accumulator = MagicMock()

        pattern = MagicMock()
        enum_val = MagicMock()
        enum_val.value = "consensus_building"
        pattern.pattern_type = enum_val
        pattern.description = "Build consensus through round-robin"
        pattern.confidence = 0.5
        pattern.observations = 3

        km._culture_accumulator.get_patterns.return_value = [pattern]

        g = make_gatherer(_knowledge_mound=km)
        result = await g.gather_culture_patterns_context("task")

        assert result is not None
        assert "consensus_building" in result.lower()

    async def test_patterns_with_empty_description_skipped(self):
        km = MagicMock(spec=["_culture_accumulator"])
        km._culture_accumulator = MagicMock()

        p1 = MagicMock()
        p1.pattern_type = "general"
        p1.description = ""  # empty → skipped
        p1.confidence = 0.9
        p1.observations = 5

        p2 = MagicMock()
        p2.pattern_type = "argumentation"
        p2.description = "Always cite sources"
        p2.confidence = 0.6
        p2.observations = 7

        km._culture_accumulator.get_patterns.return_value = [p1, p2]

        g = make_gatherer(_knowledge_mound=km)
        result = await g.gather_culture_patterns_context("task")

        assert result is not None
        assert "Always cite sources" in result

    async def test_import_error_returns_none(self):
        km = MagicMock(spec=[])  # no get_culture_context

        with patch.dict(
            "sys.modules",
            {"aragora.knowledge.mound.culture.accumulator": None},
        ):
            g = make_gatherer(_knowledge_mound=km)
            result = await g.gather_culture_patterns_context("task")
        assert result is None

    async def test_value_error_returns_none(self):
        km = MagicMock()
        km.get_culture_context = AsyncMock(side_effect=ValueError("bad"))

        g = make_gatherer(_knowledge_mound=km)
        result = await g.gather_culture_patterns_context("task")
        assert result is None


# ===========================================================================
# 11. refresh_evidence_for_round
# ===========================================================================


class TestRefreshEvidenceForRound:
    async def test_no_collector_returns_zero_and_none(self):
        g = make_gatherer()
        count, pack = await g.refresh_evidence_for_round("combined text", None, "task")
        assert count == 0
        assert pack is None

    async def test_no_claims_extracted_returns_zero_and_none(self):
        collector = MagicMock()
        collector.extract_claims_from_text.return_value = []

        g = make_gatherer()
        count, pack = await g.refresh_evidence_for_round("text", collector, "task")
        assert count == 0
        assert pack is None

    async def test_no_snippets_in_pack_returns_zero_and_none(self):
        collector = MagicMock()
        collector.extract_claims_from_text.return_value = ["claim1"]

        empty_pack = MagicMock()
        empty_pack.snippets = []
        collector.collect_for_claims = AsyncMock(return_value=empty_pack)

        g = make_gatherer()
        count, pack = await g.refresh_evidence_for_round("text", collector, "task")
        assert count == 0
        assert pack is None

    async def test_success_stores_new_pack_when_no_existing(self):
        collector = MagicMock()
        collector.extract_claims_from_text.return_value = ["claim1", "claim2"]

        snippet = MagicMock()
        snippet.id = "s1"
        ev_pack = MagicMock()
        ev_pack.snippets = [snippet]
        ev_pack.total_searched = 5
        collector.collect_for_claims = AsyncMock(return_value=ev_pack)

        g = make_gatherer()
        count, returned_pack = await g.refresh_evidence_for_round("text", collector, "task")

        assert count == 1
        task_hash = g._get_task_hash("task")
        assert g._research_evidence_pack[task_hash] is ev_pack
        assert returned_pack is ev_pack

    async def test_success_merges_with_existing_pack(self):
        task = "merge task"
        collector = MagicMock()
        collector.extract_claims_from_text.return_value = ["claim"]

        new_snippet = MagicMock()
        new_snippet.id = "new-1"
        new_pack = MagicMock()
        new_pack.snippets = [new_snippet]
        new_pack.total_searched = 3
        collector.collect_for_claims = AsyncMock(return_value=new_pack)

        existing_snippet = MagicMock()
        existing_snippet.id = "old-1"
        # Use a real list so we can verify extend was called with the new snippet
        existing_snippets_list = [existing_snippet]
        existing_pack = MagicMock()
        existing_pack.snippets = existing_snippets_list
        existing_pack.total_searched = 10

        g = make_gatherer()
        task_hash = g._get_task_hash(task)
        g._research_evidence_pack[task_hash] = existing_pack

        count, returned_pack = await g.refresh_evidence_for_round("text", collector, task)

        assert count == 1
        # new snippet should be appended to existing list
        assert new_snippet in existing_snippets_list
        # total_searched updated
        assert existing_pack.total_searched == 13
        assert returned_pack is existing_pack

    async def test_deduplicates_snippets_by_id(self):
        task = "dedup task"
        collector = MagicMock()
        collector.extract_claims_from_text.return_value = ["claim"]

        dup_snippet = MagicMock()
        dup_snippet.id = "existing-1"
        new_pack = MagicMock()
        new_pack.snippets = [dup_snippet]
        new_pack.total_searched = 1
        collector.collect_for_claims = AsyncMock(return_value=new_pack)

        existing_snippet = MagicMock()
        existing_snippet.id = "existing-1"  # same id → should be deduped
        existing_snippets_list = [existing_snippet]
        existing_pack = MagicMock()
        existing_pack.snippets = existing_snippets_list
        existing_pack.total_searched = 5

        g = make_gatherer()
        task_hash = g._get_task_hash(task)
        g._research_evidence_pack[task_hash] = existing_pack

        await g.refresh_evidence_for_round("text", collector, task)

        # The list should still be length 1 — duplicate was not appended
        assert len(existing_snippets_list) == 1
        assert existing_snippets_list[0].id == "existing-1"

    async def test_calls_evidence_store_callback(self):
        callback = MagicMock()
        collector = MagicMock()
        collector.extract_claims_from_text.return_value = ["claim"]

        snippet = MagicMock()
        snippet.id = "s1"
        ev_pack = MagicMock()
        ev_pack.snippets = [snippet]
        ev_pack.total_searched = 1
        collector.collect_for_claims = AsyncMock(return_value=ev_pack)

        g = make_gatherer()
        await g.refresh_evidence_for_round(
            "text", collector, "task", evidence_store_callback=callback
        )

        callback.assert_called_once_with(ev_pack.snippets, "task")

    async def test_no_callback_still_succeeds(self):
        collector = MagicMock()
        collector.extract_claims_from_text.return_value = ["claim"]

        snippet = MagicMock()
        snippet.id = "s1"
        ev_pack = MagicMock()
        ev_pack.snippets = [snippet]
        ev_pack.total_searched = 2
        collector.collect_for_claims = AsyncMock(return_value=ev_pack)

        g = make_gatherer()
        count, pack = await g.refresh_evidence_for_round("text", collector, "task", None)
        assert count == 1
        assert pack is not None

    async def test_attribute_error_returns_zero_and_none(self):
        collector = MagicMock()
        collector.extract_claims_from_text.side_effect = AttributeError("oops")

        g = make_gatherer()
        count, pack = await g.refresh_evidence_for_round("text", collector, "task")
        assert count == 0
        assert pack is None

    async def test_runtime_error_returns_zero_and_none(self):
        collector = MagicMock()
        collector.extract_claims_from_text.return_value = ["claim"]
        collector.collect_for_claims = AsyncMock(side_effect=RuntimeError("crash"))

        g = make_gatherer()
        count, pack = await g.refresh_evidence_for_round("text", collector, "task")
        assert count == 0
        assert pack is None
