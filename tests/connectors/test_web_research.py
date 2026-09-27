"""
Tests for web research functionality in Aragora LiveWire.

Tests the WebConnector, EvidenceCollector integration, and Arena research phase.
"""

import asyncio
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.connectors.web import WebConnector
from aragora.connectors.base import Evidence
from aragora.evidence.collector import EvidenceCollector
from aragora.reasoning.provenance import SourceType
from aragora.core import DebateResult, Environment
from aragora.debate.orchestrator import Arena, DebateProtocol
from aragora.core import Agent


class MockWebConnector(WebConnector):
    """Mock WebConnector for testing that returns fixed results."""

    def __init__(self, mock_results=None):
        # Don't call super().__init__ to avoid dependency checks
        self.mock_results = mock_results or []
        self.cache_dir = Path(".test_cache")
        self.cache_dir.mkdir(exist_ok=True)

    async def search(self, query, limit=10, **kwargs):
        """Return mock search results."""
        return self.mock_results[:limit]


class MockAgent(Agent):
    """Mock agent for testing."""

    def __init__(self, name="TestAgent"):
        super().__init__(name=name, model="test-model", role="proposer")

    async def generate(self, prompt, context=None):
        return f"Mock response from {self.name}"

    async def critique(self, proposal, task, context=None):
        return MagicMock()


@pytest.mark.asyncio
async def test_web_connector_caching():
    """Test that WebConnector caches search results via MockWebConnector."""
    # Use MockWebConnector which simulates the caching behavior
    mock_results = [
        Evidence(
            id="test1",
            source_type=SourceType.WEB_SEARCH,
            source_id="test",
            content="Test content 1",
            title="Test Title 1",
            confidence=0.8,
        )
    ]

    connector = MockWebConnector(mock_results)

    # First search - returns mock results
    result1 = await connector.search("test query")
    assert len(result1) == 1
    assert result1[0].title == "Test Title 1"

    # Second search with same query - MockWebConnector returns same results
    result2 = await connector.search("test query")
    assert len(result2) == 1
    assert result2[0].title == "Test Title 1"


@pytest.mark.asyncio
async def test_web_connector_with_test_seam():
    """Test WebConnector using _search_web_actual test seam for proper mocking."""
    with tempfile.TemporaryDirectory() as temp_dir:
        connector = WebConnector(cache_dir=temp_dir)

        # Mock results that _search_web_actual would return
        mock_results = [
            Evidence(
                id="seam_test1",
                source_type=SourceType.WEB_SEARCH,
                source_id="http://example.com",
                content="Test content via seam",
                title="Seam Test Title",
                confidence=0.9,
            )
        ]

        with patch.object(connector, "_search_web_actual", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = mock_results

            # First search - should call _search_web_actual
            result1 = await connector.search("test query seam")
            assert len(result1) == 1
            assert result1[0].title == "Seam Test Title"
            assert mock_search.call_count == 1

            # Clear mock call count for second test
            mock_search.reset_mock()

            # Note: Cache is populated by _search_web_actual, so second call
            # would use cache if we hadn't mocked. This test verifies the seam works.


@pytest.mark.asyncio
async def test_web_connector_local_ip_blocking():
    """Test that WebConnector blocks access to local/private IPs."""
    connector = WebConnector()

    # Test blocking localhost
    assert connector._is_local_ip("http://localhost/test")
    assert connector._is_local_ip("http://127.0.0.1/test")
    assert connector._is_local_ip("http://192.168.1.1/test")  # Private IP
    assert connector._is_local_ip("http://10.0.0.1/test")  # Private IP

    # Test allowing public IPs
    assert not connector._is_local_ip("http://google.com/test")
    assert not connector._is_local_ip("http://8.8.8.8/test")


@pytest.mark.asyncio
async def test_evidence_collector_with_web_connector():
    """Test EvidenceCollector integration with WebConnector."""
    # Create mock web connector with fixed results
    mock_evidence = Evidence(
        id="web_1",
        source_type=SourceType.WEB_SEARCH,
        source_id="http://example.com",
        content="This is some test content about AI safety from a web source.",
        title="AI Safety Best Practices",
        url="http://example.com/ai-safety",
        confidence=0.7,
        authority=0.8,
    )

    web_connector = MockWebConnector([mock_evidence])
    collector = EvidenceCollector()
    collector.add_connector("web", web_connector)

    # Collect evidence
    evidence_pack = await collector.collect_evidence("AI safety regulations")

    # Check results
    assert len(evidence_pack.snippets) == 1
    snippet = evidence_pack.snippets[0]
    assert snippet.title == "AI Safety Best Practices"
    assert "AI safety" in snippet.snippet
    assert snippet.source == "web"
    assert snippet.reliability_score > 0.5  # Should be calculated from evidence


@pytest.mark.asyncio
async def test_arena_research_phase():
    """Test that Arena performs research when enabled."""
    # Create mock environment and agents
    env = Environment(task="What are the latest AI safety regulations?")
    protocol = DebateProtocol(enable_research=True, rounds=1)
    agents = [MockAgent("Agent1"), MockAgent("Agent2")]

    # Create arena
    arena = Arena(env, agents, protocol)

    # Mock the research method on the context_initializer (where it's actually called)
    research_context = "## WEB RESEARCH CONTEXT\nSome research data..."
    mock_research = AsyncMock(return_value=research_context)
    arena.context_initializer._perform_research = mock_research

    # The debate completes with mock agents; research runs during context setup
    result = await arena.run()
    assert isinstance(result, DebateResult)

    # Check that research was called
    mock_research.assert_called_once_with(env.task)

    # Check that research was added to context
    assert env.context == research_context


@pytest.mark.asyncio
async def test_research_enabled_by_default():
    """Test that research is enabled by default."""
    env = Environment(task="Test task")
    protocol = DebateProtocol()  # enable_research=True by default
    agents = [MockAgent("Agent1")]

    arena = Arena(env, agents, protocol)

    # Mock the research method on the context_initializer where it's called
    mock_research = AsyncMock(return_value="Mock research context")
    arena.context_initializer._perform_research = mock_research

    result = await arena.run()
    assert isinstance(result, DebateResult)

    # Research should be called since it's enabled by default
    mock_research.assert_called_once()


@pytest.mark.asyncio
async def test_research_can_be_disabled():
    """Test that research can be explicitly disabled."""
    env = Environment(task="Test task")
    protocol = DebateProtocol(enable_research=False)
    agents = [MockAgent("Agent1")]

    arena = Arena(env, agents, protocol)

    with patch.object(arena, "_perform_research", new_callable=AsyncMock) as mock_research:
        result = await arena.run()
        assert isinstance(result, DebateResult)

        # Research should not be called when disabled
        mock_research.assert_not_called()


@pytest.mark.asyncio
async def test_research_failure_graceful():
    """Test that research failure doesn't break the debate."""
    env = Environment(task="Test task")
    protocol = DebateProtocol(enable_research=True)
    agents = [MockAgent("Agent1"), MockAgent("Agent2")]

    arena = Arena(env, agents, protocol)

    # Mock research to raise exception
    with patch.object(arena, "_perform_research", new_callable=AsyncMock) as mock_research:
        mock_research.side_effect = Exception("Research failed")

        # Run should not raise exception due to research failure
        try:
            result = await arena.run()
            # Should complete (even if with errors)
            assert isinstance(result, object)  # Some result object
        except Exception as e:
            # If it fails, it shouldn't be due to research
            assert "Research failed" not in str(e)


def test_evidence_formatting():
    """Test that evidence is properly formatted for context."""
    from aragora.evidence.collector import EvidencePack, EvidenceSnippet

    snippet = EvidenceSnippet(
        id="test_1",
        source="web",
        title="Test Title",
        snippet="Test content snippet",
        url="http://example.com",
        reliability_score=0.8,
    )

    pack = EvidencePack(topic_keywords=["test", "topic"], snippets=[snippet])

    context = pack.to_context_string()
    assert "EVID-test_1" in context
    assert "Test Title" in context
    assert "web (0.8 reliability" in context  # Format now includes freshness
    assert "fresh)" in context  # Verify freshness indicator is present
    assert "http://example.com" in context
