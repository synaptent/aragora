"""
Tests for aragora.cli.knowledge module.

Tests knowledge base CLI commands: query, facts, search, jobs, process, stats.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.cli.knowledge import (
    cmd_facts,
    cmd_jobs,
    cmd_process,
    cmd_query,
    cmd_search,
    cmd_stats,
    create_knowledge_parser,
    main,
)

if TYPE_CHECKING:
    pass


# ===========================================================================
# Test Fixtures and Mock Classes
# ===========================================================================


@dataclass
class MockQueryResult:
    """Mock query result.

    Mirrors the real ``aragora.knowledge.types.QueryResult`` contract:
    supporting facts live on ``facts`` (not ``facts_used``) and chunk counts
    are reported via ``metadata["chunks_searched"]`` (there is no
    ``chunks_used`` attribute).
    """

    answer: str = "Test answer"
    confidence: float = 0.85
    facts: list = field(default_factory=list)
    metadata: dict = field(default_factory=lambda: {"chunks_searched": 0})


@dataclass
class MockFact:
    """Mock fact."""

    id: str = "fact-1"
    statement: str = "Test fact statement"
    confidence: float = 0.9
    validation_status: MagicMock = field(default_factory=lambda: MagicMock(value="unverified"))
    topics: list = field(default_factory=lambda: ["test", "knowledge"])
    evidence_ids: list = field(default_factory=list)
    source_documents: list = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class MockSearchResult:
    """Mock search result."""

    chunk_id: str = "chunk-1"
    document_id: str = "doc-1"
    score: float = 0.95
    content: str = "Test content for search result"


@dataclass
class MockProcessResult:
    """Mock document processing result."""

    success: bool = True
    document_id: str = "doc-123"
    chunk_count: int = 10
    fact_count: int = 5
    embedded_count: int = 10
    duration_ms: int = 1500
    error: str | None = None


# ===========================================================================
# Tests: create_knowledge_parser
# ===========================================================================


class TestCreateKnowledgeParser:
    """Tests for create_knowledge_parser function."""

    def test_creates_knowledge_subparser(self):
        """Test that knowledge parser is created with subcommands."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        create_knowledge_parser(subparsers)

        # Parse a simple knowledge query command
        args = parser.parse_args(["knowledge", "query", "test question"])
        assert args.question == "test question"
        assert args.workspace == "default"
        assert args.json is False
        assert args.debate is False

    def test_query_subcommand_options(self):
        """Test query subcommand with all options."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        create_knowledge_parser(subparsers)

        args = parser.parse_args(
            [
                "knowledge",
                "query",
                "What are payment terms?",
                "--workspace",
                "finance",
                "--debate",
                "--limit",
                "10",
                "--json",
            ]
        )
        assert args.question == "What are payment terms?"
        assert args.workspace == "finance"
        assert args.debate is True
        assert args.limit == 10
        assert args.json is True

    def test_facts_subcommand_options(self):
        """Test facts subcommand with filters."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        create_knowledge_parser(subparsers)

        args = parser.parse_args(
            [
                "knowledge",
                "facts",
                "list",
                "--workspace",
                "legal",
                "--topic",
                "contracts",
                "--status",
                "majority_agreed",
                "--min-confidence",
                "0.8",
                "--limit",
                "50",
            ]
        )
        assert args.action == "list"
        assert args.workspace == "legal"
        assert args.topic == "contracts"
        assert args.status == "majority_agreed"
        assert args.min_confidence == 0.8
        assert args.limit == 50

    def test_search_subcommand_modes(self):
        """Test search subcommand with different modes."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        create_knowledge_parser(subparsers)

        # Default mode
        args = parser.parse_args(["knowledge", "search", "contract expiration"])
        assert args.mode == "hybrid"

        # Vector mode
        args = parser.parse_args(["knowledge", "search", "contract", "--mode", "vector"])
        assert args.mode == "vector"

        # Keyword mode
        args = parser.parse_args(["knowledge", "search", "contract", "--mode", "keyword"])
        assert args.mode == "keyword"

    def test_jobs_subcommand_options(self):
        """Test jobs subcommand with filters."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        create_knowledge_parser(subparsers)

        args = parser.parse_args(
            [
                "knowledge",
                "jobs",
                "list",
                "--workspace",
                "main",
                "--status",
                "completed",
                "--limit",
                "100",
            ]
        )
        assert args.action == "list"
        assert args.workspace == "main"
        assert args.status == "completed"
        assert args.limit == 100

    def test_process_subcommand_options(self):
        """Test process subcommand with options."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        create_knowledge_parser(subparsers)

        args = parser.parse_args(
            [
                "knowledge",
                "process",
                "document.pdf",
                "--workspace",
                "docs",
                "--sync",
                "--no-facts",
                "--json",
            ]
        )
        assert args.file == "document.pdf"
        assert args.workspace == "docs"
        assert args.sync is True
        assert args.no_facts is True
        assert args.json is True

    def test_stats_subcommand_options(self):
        """Test stats subcommand options."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        create_knowledge_parser(subparsers)

        args = parser.parse_args(["knowledge", "stats", "--workspace", "analytics", "--json"])
        assert args.workspace == "analytics"
        assert args.json is True


# ===========================================================================
# Tests: cmd_query
# ===========================================================================


class TestCmdQuery:
    """Tests for cmd_query function."""

    @pytest.fixture
    def query_args(self):
        """Create base query args."""
        args = argparse.Namespace()
        args.question = "What are the payment terms?"
        args.workspace = "default"
        args.debate = False
        args.limit = 5
        args.json = False
        return args

    @patch("aragora.cli.knowledge.asyncio.run")
    def test_query_success_text_output(self, mock_run, query_args, capsys):
        """Test successful query with text output."""
        mock_result = MockQueryResult()
        mock_run.return_value = mock_result

        with patch.dict(
            "sys.modules",
            {
                "aragora.knowledge": MagicMock(
                    DatasetQueryEngine=MagicMock,
                    InMemoryEmbeddingService=MagicMock,
                    InMemoryFactStore=MagicMock,
                    QueryOptions=MagicMock,
                ),
            },
        ):
            result = cmd_query(query_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "ANSWER" in captured.out
        assert "Test answer" in captured.out
        assert "85.0%" in captured.out

    @patch("aragora.cli.knowledge.asyncio.run")
    def test_query_success_json_output(self, mock_run, query_args, capsys):
        """Test successful query with JSON output."""
        mock_result = MockQueryResult()
        mock_run.return_value = mock_result
        query_args.json = True

        with patch.dict(
            "sys.modules",
            {
                "aragora.knowledge": MagicMock(
                    DatasetQueryEngine=MagicMock,
                    InMemoryEmbeddingService=MagicMock,
                    InMemoryFactStore=MagicMock,
                    QueryOptions=MagicMock,
                ),
            },
        ):
            result = cmd_query(query_args)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["answer"] == "Test answer"
        assert output["confidence"] == 0.85
        assert output["facts_used"] == 0

    @patch("aragora.cli.knowledge.asyncio.run")
    def test_query_with_facts(self, mock_run, query_args, capsys):
        """Test query that returns supporting facts."""
        mock_result = MockQueryResult(
            facts=[MockFact(), MockFact(id="fact-2", statement="Second fact")]
        )
        mock_run.return_value = mock_result

        with patch.dict(
            "sys.modules",
            {
                "aragora.knowledge": MagicMock(
                    DatasetQueryEngine=MagicMock,
                    InMemoryEmbeddingService=MagicMock,
                    InMemoryFactStore=MagicMock,
                    QueryOptions=MagicMock,
                ),
            },
        ):
            result = cmd_query(query_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "SUPPORTING FACTS" in captured.out
        assert "Test fact statement" in captured.out

    def test_query_import_error(self, query_args, capsys):
        """Test query when knowledge module not available."""
        with patch.dict("sys.modules", {"aragora.knowledge": None}):
            # Force ImportError by patching import mechanism
            with patch(
                "builtins.__import__",
                side_effect=ImportError("No module named 'aragora.knowledge'"),
            ):
                result = cmd_query(query_args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Knowledge module not available" in captured.out

    # -- Regression tests for the QueryOptions/QueryResult contract --------
    #
    # The tests above replace QueryOptions/QueryResult with MagicMock, which
    # silently accepts any kwarg/attribute and therefore masked two real
    # crashes in cmd_query:
    #   1. QueryOptions(max_facts=...) -> TypeError (no such field)
    #   2. result.facts_used / result.chunks_used -> AttributeError
    # These tests exercise cmd_query against the REAL in-memory engine
    # (offline, no API key) so the actual dataclass contracts are checked.

    def test_query_options_has_no_max_facts_field(self):
        """The real QueryOptions must not accept a max_facts kwarg.

        cmd_query passes --limit through to QueryOptions; the only chunk/fact
        sizing field on the dataclass is max_chunks. Constructing with
        max_facts is the original defect and must remain a TypeError so we
        never regress to it.
        """
        import dataclasses

        from aragora.knowledge import QueryOptions

        field_names = {f.name for f in dataclasses.fields(QueryOptions)}
        assert "max_facts" not in field_names
        assert "max_chunks" in field_names

        # max_chunks is the correct mapping for --limit and must be accepted.
        opts = QueryOptions(max_chunks=7)
        assert opts.max_chunks == 7

        with pytest.raises(TypeError):
            QueryOptions(max_facts=7)  # type: ignore[call-arg]

    def test_query_result_uses_facts_not_facts_used(self):
        """QueryResult exposes `facts` and metadata, not facts_used/chunks_used."""
        import dataclasses

        from aragora.knowledge.types import QueryResult

        field_names = {f.name for f in dataclasses.fields(QueryResult)}
        assert "facts" in field_names
        assert "facts_used" not in field_names
        assert "chunks_used" not in field_names

    @pytest.mark.parametrize("flag", [None, "json", "debate"])
    def test_query_real_engine_fails_closed_without_org(self, query_args, capsys, flag):
        """The real engine searches no chunks: the CLI has no authenticated organization."""
        if flag:
            setattr(query_args, flag, True)

        assert cmd_query(query_args) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "require an organization" in captured.err


# ===========================================================================
# Tests: cmd_facts
# ===========================================================================


class TestCmdFacts:
    """Tests for cmd_facts function."""

    @pytest.fixture
    def facts_args(self):
        """Create base facts args."""
        args = argparse.Namespace()
        args.action = "list"
        args.fact_id = None
        args.workspace = "default"
        args.topic = None
        args.status = None
        args.min_confidence = 0.0
        args.limit = 20
        args.json = False
        return args

    def test_facts_list_text_output(self, facts_args, capsys):
        """Test listing facts with text output."""
        mock_fact = MockFact()
        mock_store = MagicMock()
        mock_store.list_facts.return_value = [mock_fact]

        mock_validation = MagicMock()
        mock_validation.value = "unverified"

        mock_knowledge = MagicMock()
        mock_knowledge.InMemoryFactStore.return_value = mock_store
        mock_knowledge.ValidationStatus = MagicMock(return_value=mock_validation)

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            with patch.dict("sys.modules", {"aragora.knowledge.types": MagicMock()}):
                result = cmd_facts(facts_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Facts in workspace 'default'" in captured.out
        assert "Total: 1 facts" in captured.out

    def test_facts_list_json_output(self, facts_args, capsys):
        """Test listing facts with JSON output."""
        mock_fact = MockFact()
        mock_store = MagicMock()
        mock_store.list_facts.return_value = [mock_fact]
        facts_args.json = True

        mock_knowledge = MagicMock()
        mock_knowledge.InMemoryFactStore.return_value = mock_store

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            with patch.dict("sys.modules", {"aragora.knowledge.types": MagicMock()}):
                result = cmd_facts(facts_args)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert len(output) == 1
        assert output[0]["id"] == "fact-1"

    def test_facts_list_empty(self, facts_args, capsys):
        """Test listing when no facts found."""
        mock_store = MagicMock()
        mock_store.list_facts.return_value = []

        mock_knowledge = MagicMock()
        mock_knowledge.InMemoryFactStore.return_value = mock_store

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            with patch.dict("sys.modules", {"aragora.knowledge.types": MagicMock()}):
                result = cmd_facts(facts_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "No facts found" in captured.out

    def test_facts_show_success(self, facts_args, capsys):
        """Test showing a specific fact."""
        facts_args.action = "show"
        facts_args.fact_id = "fact-123"

        mock_fact = MockFact(id="fact-123")
        mock_store = MagicMock()
        mock_store.get_fact.return_value = mock_fact

        mock_knowledge = MagicMock()
        mock_knowledge.InMemoryFactStore.return_value = mock_store

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            with patch.dict("sys.modules", {"aragora.knowledge.types": MagicMock()}):
                result = cmd_facts(facts_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Fact: fact-123" in captured.out
        assert "Test fact statement" in captured.out

    def test_facts_show_json(self, facts_args, capsys):
        """Test showing fact with JSON output."""
        facts_args.action = "show"
        facts_args.fact_id = "fact-123"
        facts_args.json = True

        mock_fact = MockFact(id="fact-123")
        mock_store = MagicMock()
        mock_store.get_fact.return_value = mock_fact

        mock_knowledge = MagicMock()
        mock_knowledge.InMemoryFactStore.return_value = mock_store

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            with patch.dict("sys.modules", {"aragora.knowledge.types": MagicMock()}):
                result = cmd_facts(facts_args)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["id"] == "fact-123"

    def test_facts_show_not_found(self, facts_args, capsys):
        """Test showing non-existent fact."""
        facts_args.action = "show"
        facts_args.fact_id = "missing-fact"

        mock_store = MagicMock()
        mock_store.get_fact.return_value = None

        mock_knowledge = MagicMock()
        mock_knowledge.InMemoryFactStore.return_value = mock_store

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            with patch.dict("sys.modules", {"aragora.knowledge.types": MagicMock()}):
                result = cmd_facts(facts_args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Fact not found" in captured.out

    def test_facts_show_missing_id(self, facts_args, capsys):
        """Test show action without fact_id."""
        facts_args.action = "show"
        facts_args.fact_id = None

        mock_knowledge = MagicMock()

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            with patch.dict("sys.modules", {"aragora.knowledge.types": MagicMock()}):
                result = cmd_facts(facts_args)

        assert result == 1
        captured = capsys.readouterr()
        assert "fact_id required" in captured.out

    def test_facts_verify_runs_verification(self, facts_args, capsys):
        """Test verify action attempts fact verification."""
        facts_args.action = "verify"
        facts_args.fact_id = "fact-123"

        mock_knowledge = MagicMock()
        mock_fact = MagicMock()
        mock_fact.statement = "Test statement"
        mock_fact.confidence = 0.85
        mock_fact.validation_status.value = "majority_agreed"
        mock_store = mock_knowledge.InMemoryFactStore.return_value
        mock_store.get_fact.return_value = mock_fact

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            with patch.dict("sys.modules", {"aragora.knowledge.types": MagicMock()}):
                # The verify action now tries to import KnowledgeQueryEngine;
                # if the import fails (mocked modules), it returns 1 with an error
                result = cmd_facts(facts_args)

        captured = capsys.readouterr()
        # Should show the "Verifying fact:" header since the fact was found
        assert "Verifying fact" in captured.out

    def test_facts_verify_missing_id(self, facts_args, capsys):
        """Test verify action without fact_id."""
        facts_args.action = "verify"
        facts_args.fact_id = None

        mock_knowledge = MagicMock()

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            with patch.dict("sys.modules", {"aragora.knowledge.types": MagicMock()}):
                result = cmd_facts(facts_args)

        assert result == 1
        captured = capsys.readouterr()
        assert "fact_id required" in captured.out


# ===========================================================================
# Tests: cmd_search
# ===========================================================================


class TestCmdSearch:
    """Tests for cmd_search function."""

    @pytest.fixture
    def search_args(self):
        """Create base search args."""
        args = argparse.Namespace()
        args.query = "contract expiration"
        args.workspace = "default"
        args.mode = "hybrid"
        args.limit = 10
        args.json = False
        return args

    @patch("aragora.cli.knowledge.asyncio.run")
    def test_search_hybrid_text_output(self, mock_run, search_args, capsys):
        """Test hybrid search with text output."""
        mock_results = [MockSearchResult(), MockSearchResult(chunk_id="chunk-2", score=0.88)]
        mock_run.return_value = mock_results

        mock_knowledge = MagicMock()
        mock_service = MagicMock()
        mock_service.hybrid_search = AsyncMock(return_value=mock_results)
        mock_knowledge.InMemoryEmbeddingService.return_value = mock_service

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_search(search_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Search results for: 'contract expiration'" in captured.out
        assert "Mode: hybrid" in captured.out

    @patch("aragora.cli.knowledge.asyncio.run")
    def test_search_hybrid_json_output(self, mock_run, search_args, capsys):
        """Test hybrid search with JSON output."""
        mock_results = [MockSearchResult()]
        mock_run.return_value = mock_results
        search_args.json = True

        mock_knowledge = MagicMock()

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_search(search_args)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert len(output) == 1
        assert output[0]["chunk_id"] == "chunk-1"
        assert output[0]["score"] == 0.95

    @patch("aragora.cli.knowledge.asyncio.run")
    def test_search_vector_mode(self, mock_run, search_args, capsys):
        """Test vector search mode."""
        mock_results = [MockSearchResult()]
        mock_run.return_value = mock_results
        search_args.mode = "vector"

        mock_knowledge = MagicMock()

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_search(search_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Mode: vector" in captured.out

    @patch("aragora.cli.knowledge.asyncio.run")
    def test_search_keyword_mode(self, mock_run, search_args, capsys):
        """Test keyword search mode."""
        mock_results = [MockSearchResult()]
        mock_run.return_value = mock_results
        search_args.mode = "keyword"

        mock_knowledge = MagicMock()

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_search(search_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Mode: keyword" in captured.out

    @patch("aragora.cli.knowledge.asyncio.run")
    def test_search_no_results(self, mock_run, search_args, capsys):
        """Test search with no results."""
        mock_run.return_value = []

        mock_knowledge = MagicMock()

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_search(search_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "No results found" in captured.out


# ===========================================================================
# Tests: cmd_jobs
# ===========================================================================


class TestCmdJobs:
    """Tests for cmd_jobs function."""

    @pytest.fixture
    def jobs_args(self):
        """Create base jobs args."""
        args = argparse.Namespace()
        args.action = "list"
        args.job_id = None
        args.workspace = None
        args.status = None
        args.limit = 20
        args.json = False
        return args

    def test_jobs_list_text_output(self, jobs_args, capsys):
        """Test listing jobs with text output."""
        mock_jobs = [
            {
                "job_id": "job-1",
                "filename": "document.pdf",
                "status": "completed",
                "result": {"chunk_count": 10, "fact_count": 5},
            },
            {"job_id": "job-2", "filename": "report.docx", "status": "processing"},
        ]

        mock_knowledge = MagicMock()
        mock_knowledge.get_all_jobs.return_value = mock_jobs

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_jobs(jobs_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Knowledge Processing Jobs" in captured.out
        assert "job-1" in captured.out
        assert "Total: 2 jobs" in captured.out

    def test_jobs_list_json_output(self, jobs_args, capsys):
        """Test listing jobs with JSON output."""
        mock_jobs = [{"job_id": "job-1", "filename": "document.pdf", "status": "completed"}]
        jobs_args.json = True

        mock_knowledge = MagicMock()
        mock_knowledge.get_all_jobs.return_value = mock_jobs

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_jobs(jobs_args)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert len(output) == 1
        assert output[0]["job_id"] == "job-1"

    def test_jobs_list_empty(self, jobs_args, capsys):
        """Test listing when no jobs found."""
        mock_knowledge = MagicMock()
        mock_knowledge.get_all_jobs.return_value = []

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_jobs(jobs_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "No jobs found" in captured.out

    def test_jobs_show_success(self, jobs_args, capsys):
        """Test showing a specific job."""
        jobs_args.action = "show"
        jobs_args.job_id = "job-123"

        mock_job = {
            "job_id": "job-123",
            "filename": "document.pdf",
            "workspace_id": "default",
            "status": "completed",
            "created_at": "2024-01-01T10:00:00",
            "completed_at": "2024-01-01T10:05:00",
            "result": {
                "chunk_count": 10,
                "fact_count": 5,
                "embedded_count": 10,
                "duration_ms": 3000,
            },
        }

        mock_knowledge = MagicMock()
        mock_knowledge.get_job_status.return_value = mock_job

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_jobs(jobs_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Job: job-123" in captured.out
        assert "document.pdf" in captured.out
        assert "Chunks: 10" in captured.out

    def test_jobs_show_with_error(self, jobs_args, capsys):
        """Test showing a failed job."""
        jobs_args.action = "show"
        jobs_args.job_id = "job-fail"

        mock_job = {
            "job_id": "job-fail",
            "filename": "bad.pdf",
            "workspace_id": "default",
            "status": "failed",
            "created_at": "2024-01-01T10:00:00",
            "completed_at": None,
            "error": "Processing failed: invalid format",
        }

        mock_knowledge = MagicMock()
        mock_knowledge.get_job_status.return_value = mock_job

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_jobs(jobs_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Error: Processing failed" in captured.out

    def test_jobs_show_not_found(self, jobs_args, capsys):
        """Test showing non-existent job."""
        jobs_args.action = "show"
        jobs_args.job_id = "missing-job"

        mock_knowledge = MagicMock()
        mock_knowledge.get_job_status.return_value = None

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_jobs(jobs_args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Job not found" in captured.out

    def test_jobs_show_missing_id(self, jobs_args, capsys):
        """Test show action without job_id."""
        jobs_args.action = "show"
        jobs_args.job_id = None

        mock_knowledge = MagicMock()

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_jobs(jobs_args)

        assert result == 1
        captured = capsys.readouterr()
        assert "job_id required" in captured.out


# ===========================================================================
# Tests: cmd_process
# ===========================================================================


class TestCmdProcess:
    """Tests for cmd_process function."""

    @pytest.fixture
    def process_args(self, tmp_path):
        """Create base process args with temp file."""
        test_file = tmp_path / "document.pdf"
        test_file.write_bytes(b"test content")

        args = argparse.Namespace()
        args.file = str(test_file)
        args.workspace = "default"
        args.sync = False
        args.no_facts = False
        args.json = False
        return args

    def test_process_async_success(self, process_args, capsys):
        """Test async document processing."""
        mock_knowledge = MagicMock()
        mock_knowledge.queue_document_processing.return_value = "job-123"

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_process(process_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Job queued: job-123" in captured.out
        assert "Check status with" in captured.out

    def test_process_async_json_output(self, process_args, capsys):
        """Test async processing with JSON output."""
        process_args.json = True

        mock_knowledge = MagicMock()
        mock_knowledge.queue_document_processing.return_value = "job-456"

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_process(process_args)

        assert result == 0
        captured = capsys.readouterr()
        out = captured.out
        # Output includes "Queuing ..." before JSON
        json_start = out.find("{")
        assert json_start != -1, f"No JSON found in output: {out}"
        output = json.loads(out[json_start:])
        assert output["job_id"] == "job-456"
        assert output["status"] == "queued"

    def test_process_sync_success(self, process_args, capsys):
        """Test synchronous document processing."""
        process_args.sync = True

        mock_result = MockProcessResult()
        mock_knowledge = MagicMock()
        mock_knowledge.process_document_sync.return_value = mock_result

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_process(process_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "SUCCESS" in captured.out
        assert "Document ID: doc-123" in captured.out
        assert "Chunks: 10" in captured.out

    def test_process_sync_json_output(self, process_args, capsys):
        """Test sync processing with JSON output."""
        process_args.sync = True
        process_args.json = True

        mock_result = MockProcessResult()
        mock_knowledge = MagicMock()
        mock_knowledge.process_document_sync.return_value = mock_result

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_process(process_args)

        assert result == 0
        captured = capsys.readouterr()
        out = captured.out
        # Output includes "Processing ..." before JSON
        json_start = out.find("{")
        assert json_start != -1, f"No JSON found in output: {out}"
        output = json.loads(out[json_start:])
        assert output["success"] is True
        assert output["document_id"] == "doc-123"
        assert output["chunk_count"] == 10

    def test_process_sync_failure(self, process_args, capsys):
        """Test synchronous processing failure."""
        process_args.sync = True

        mock_result = MockProcessResult(success=False, error="Invalid file format")
        mock_knowledge = MagicMock()
        mock_knowledge.process_document_sync.return_value = mock_result

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            result = cmd_process(process_args)

        assert result == 0  # Function returns 0 even on processing failure
        captured = capsys.readouterr()
        assert "FAILED" in captured.out
        assert "Invalid file format" in captured.out

    def test_process_file_not_found(self, capsys):
        """Test processing non-existent file."""
        args = argparse.Namespace()
        args.file = "/nonexistent/file.pdf"
        args.workspace = "default"
        args.sync = False
        args.no_facts = False
        args.json = False

        result = cmd_process(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "File not found" in captured.out


# ===========================================================================
# Tests: cmd_stats
# ===========================================================================


class TestCmdStats:
    """Tests for cmd_stats function."""

    @pytest.fixture
    def stats_args(self):
        """Create base stats args."""
        args = argparse.Namespace()
        args.workspace = None
        args.json = False
        return args

    def test_stats_text_output(self, stats_args, capsys, monkeypatch):
        """Test stats with text output."""
        monkeypatch.setenv("ARAGORA_WEAVIATE_ENABLED", "false")

        mock_store = MagicMock()
        mock_store.list_facts.return_value = [MockFact() for _ in range(25)]

        mock_knowledge = MagicMock()
        mock_knowledge.InMemoryFactStore.return_value = mock_store
        mock_knowledge.InMemoryEmbeddingService.return_value = MagicMock()

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            with patch.dict("sys.modules", {"aragora.knowledge.types": MagicMock()}):
                result = cmd_stats(stats_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Knowledge Base Statistics" in captured.out
        assert "Total Facts: 25" in captured.out
        assert "disabled (using in-memory)" in captured.out

    def test_stats_json_output(self, stats_args, capsys, monkeypatch):
        """Test stats with JSON output."""
        stats_args.json = True
        monkeypatch.setenv("ARAGORA_WEAVIATE_ENABLED", "true")

        mock_store = MagicMock()
        mock_store.list_facts.return_value = [MockFact() for _ in range(10)]

        mock_knowledge = MagicMock()
        mock_knowledge.InMemoryFactStore.return_value = mock_store
        mock_knowledge.InMemoryEmbeddingService.return_value = MagicMock()

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            with patch.dict("sys.modules", {"aragora.knowledge.types": MagicMock()}):
                result = cmd_stats(stats_args)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["facts"] == 10
        assert output["weaviate_enabled"] is True

    def test_stats_with_workspace(self, stats_args, capsys, monkeypatch):
        """Test stats filtered by workspace."""
        stats_args.workspace = "finance"
        monkeypatch.setenv("ARAGORA_WEAVIATE_ENABLED", "false")

        mock_store = MagicMock()
        mock_store.list_facts.return_value = []

        mock_knowledge = MagicMock()
        mock_knowledge.InMemoryFactStore.return_value = mock_store
        mock_knowledge.InMemoryEmbeddingService.return_value = MagicMock()

        with patch.dict("sys.modules", {"aragora.knowledge": mock_knowledge}):
            with patch.dict("sys.modules", {"aragora.knowledge.types": MagicMock()}):
                result = cmd_stats(stats_args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Workspace: finance" in captured.out


# ===========================================================================
# Tests: main
# ===========================================================================


class TestMain:
    """Tests for main function."""

    def test_main_with_func(self, capsys):
        """Test main delegates to command function."""
        mock_func = MagicMock(return_value=0)
        args = argparse.Namespace()
        args.func = mock_func

        result = main(args)

        assert result == 0
        mock_func.assert_called_once_with(args)

    def test_main_without_func(self, capsys):
        """Test main shows usage when no func set."""
        args = argparse.Namespace()
        # No func attribute

        result = main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Usage: aragora knowledge <command>" in captured.out

    def test_main_func_returns_error(self, capsys):
        """Test main propagates error codes."""
        mock_func = MagicMock(return_value=1)
        args = argparse.Namespace()
        args.func = mock_func

        result = main(args)

        assert result == 1
