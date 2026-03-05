"""
Pytest fixtures for Nomic loop tests.
"""

import asyncio
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, NonCallableMock, patch

import pytest

# Capture the original side_effect property descriptor before any test can
# corrupt it.  Some tests erroneously set MagicMock.side_effect on the CLASS
# rather than an instance, which destroys the property descriptor and breaks
# list-to-iterator conversion for all subsequent mocks.
_original_side_effect_descriptor = NonCallableMock.side_effect


@pytest.fixture(autouse=True)
def _restore_mock_side_effect_descriptor():
    """Restore NonCallableMock.side_effect if a test corrupted the descriptor."""
    yield
    if NonCallableMock.side_effect is not _original_side_effect_descriptor:
        NonCallableMock.side_effect = _original_side_effect_descriptor


@pytest.fixture(autouse=True)
def _disable_rlm_context(monkeypatch):
    """Disable RLM context gathering to avoid calling real LLM APIs in tests.

    Also enables the ENABLE_NOMIC_LOOP gate so tests can exercise execute_goal
    without fighting the production safety check.  The gate is an operator
    opt-in for production deployments, not a test-environment restriction.
    """
    monkeypatch.setenv("ARAGORA_NOMIC_CONTEXT_RLM", "false")
    monkeypatch.setenv("ENABLE_NOMIC_LOOP", "true")


@pytest.fixture(autouse=True)
def _isolate_nomic_databases(tmp_path, monkeypatch):
    """Isolate SQLite databases and prevent heavy I/O during nomic tests.

    The SelfImprovePipeline and related components open real SQLite
    databases via CalibrationTracker and other stores.  Pointing
    ARAGORA_DATA_DIR at a temporary directory prevents contention with
    production databases and avoids hangs on WAL locks.

    The CodebaseIndexer is also patched to return immediately.  Without
    this, ``_map_test_to_source`` would AST-parse every test file in the
    repo (3000+), which can block indefinitely on large codebases.
    """
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ARAGORA_CONVERGENCE_BACKEND", "jaccard")
    monkeypatch.setenv("ARAGORA_SIMILARITY_BACKEND", "jaccard")


@pytest.fixture(autouse=True)
def _mock_codebase_indexer(request, monkeypatch):
    """Prevent CodebaseIndexer from scanning real source files.

    The indexer's ``index()`` method walks the entire repo, AST-parsing
    every Python file (3000+ modules and 3000+ test files).  On large
    codebases this can take minutes and block the event loop, causing
    tests to hang.  Patching ``index()`` to return empty stats avoids
    this entirely while still exercising the pipeline logic that calls it.

    Skipped for test_codebase_indexer.py which tests the indexer itself.
    """
    if "test_codebase_indexer" in request.fspath.basename:
        return
    try:
        from aragora.nomic.codebase_indexer import CodebaseIndexer, IndexStats

        async def _fast_index(self) -> IndexStats:
            return IndexStats()

        async def _fast_query(self, search_text: str, limit: int = 10):
            return []

        monkeypatch.setattr(CodebaseIndexer, "index", _fast_index)
        monkeypatch.setattr(CodebaseIndexer, "query", _fast_query)
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _mock_scan_code_markers(request, monkeypatch):
    """Prevent scan_code_markers from walking the entire repo.

    The NextStepsRunner.scan() calls scan_code_markers() which does
    os.walk + read_text on up to 5000 files.  On a 3000+ module codebase
    this takes minutes and causes test timeouts in long suite runs.

    Skipped for tests that specifically test the scanner itself.
    """
    if "test_next_steps" in request.fspath.basename:
        return
    try:
        import aragora.compat.openclaw.next_steps_runner as nsr_mod

        monkeypatch.setattr(nsr_mod, "scan_code_markers", lambda repo_path: ([], 0))
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _mock_goal_proposer(request, monkeypatch):
    """Prevent GoalProposer from scanning the entire repo.

    ``GoalProposer._signal_coverage_gaps`` calls ``rglob`` on the source
    and test directories, which takes minutes on a 3000+ module codebase.
    Patching ``propose_goals`` to return an empty list avoids this entirely.

    Skipped for tests that specifically test goal proposer logic.
    """
    if "test_goal_proposer" in request.fspath.basename:
        return
    try:
        from aragora.nomic.goal_proposer import GoalProposer

        monkeypatch.setattr(GoalProposer, "propose_goals", lambda self: [])
    except (ImportError, AttributeError):
        pass


@pytest.fixture(autouse=True)
def _mock_km_operations(request, monkeypatch):
    """Prevent KnowledgeMound operations from blocking on real I/O.

    Several orchestrator methods (_record_orchestration_outcome,
    _detect_km_contradictions) import KM adapters and perform async
    database/filesystem operations.  Without mocking, these block
    indefinitely on large codebases.

    Skipped for tests that specifically test KM integration.
    """
    if "test_knowledge" in request.fspath.basename:
        return
    try:
        import aragora.knowledge.mound as km_mod

        monkeypatch.setattr(
            km_mod,
            "get_knowledge_mound",
            lambda **kwargs: MagicMock(),
        )
    except (ImportError, AttributeError):
        pass
    try:
        import aragora.knowledge.mound.adapters.nomic_cycle_adapter as nca_mod

        mock_adapter = MagicMock()
        mock_adapter.ingest_cycle_outcome = AsyncMock()
        # Various async adapter methods that get awaited during KM enrichment.
        mock_adapter.find_recurring_failures = AsyncMock(return_value=[])
        mock_adapter.find_high_roi_goal_types = AsyncMock(return_value=[])
        mock_adapter.find_similar_cycles = AsyncMock(return_value=[])
        mock_adapter.get_goal_history = AsyncMock(return_value=[])
        monkeypatch.setattr(
            nca_mod,
            "get_nomic_cycle_adapter",
            lambda: mock_adapter,
        )
    except (ImportError, AttributeError):
        pass
    try:
        import aragora.knowledge.mound.ops.contradiction as contra_mod

        mock_detector = MagicMock()
        mock_report = MagicMock()
        mock_report.contradictions_found = 0
        mock_detector.detect_contradictions = AsyncMock(return_value=mock_report)
        monkeypatch.setattr(
            contra_mod,
            "ContradictionDetector",
            lambda: mock_detector,
        )
    except (ImportError, AttributeError):
        pass


@pytest.fixture
def mock_aragora_path(tmp_path: Path) -> Path:
    """Create a mock aragora project structure."""
    # Create basic directory structure
    (tmp_path / "aragora").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs").mkdir()

    # Create a minimal pyproject.toml
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "aragora"
version = "1.0.0"
"""
    )

    # Create a sample Python file
    (tmp_path / "aragora" / "__init__.py").write_text('"""Aragora package."""')
    (tmp_path / "aragora" / "core.py").write_text(
        '''
"""Core module."""

def example_function():
    """Example function."""
    return "hello"
'''
    )

    return tmp_path


@pytest.fixture
def mock_claude_agent() -> MagicMock:
    """Create a mock Claude agent."""
    agent = MagicMock()
    agent.name = "claude"
    agent.generate = AsyncMock(return_value="Mock Claude response")
    return agent


@pytest.fixture
def mock_codex_agent() -> MagicMock:
    """Create a mock Codex agent."""
    agent = MagicMock()
    agent.name = "codex"
    agent.generate = AsyncMock(return_value="Mock Codex response")
    return agent


@pytest.fixture
def mock_log_fn() -> MagicMock:
    """Create a mock logging function that accepts any args/kwargs."""
    mock = MagicMock()
    # Ensure the mock accepts any positional and keyword arguments
    mock.side_effect = lambda *args, **kwargs: None
    return mock


@pytest.fixture
def mock_stream_emit_fn() -> MagicMock:
    """Create a mock stream emit function."""
    return MagicMock()


@pytest.fixture
def mock_harness() -> MagicMock:
    """Create a mock agent harness."""
    harness = MagicMock()
    harness.explore_codebase = AsyncMock(
        return_value={
            "files": ["aragora/core.py"],
            "summary": "Mock codebase exploration",
            "features": ["feature1", "feature2"],
        }
    )
    harness.run_tests = AsyncMock(
        return_value={
            "passed": True,
            "failures": [],
            "output": "All tests passed",
        }
    )
    harness.generate_code = AsyncMock(
        return_value={
            "code": "def new_feature(): pass",
            "files_modified": ["aragora/new.py"],
        }
    )
    return harness


@pytest.fixture
def mock_debate_result() -> dict[str, Any]:
    """Create a mock debate result."""
    return {
        "consensus": True,
        "confidence": 0.85,
        "final_claim": "We should implement feature X",
        "proposals": [
            {
                "agent": "claude",
                "proposal": "Add error handling",
                "votes": 3,
            },
            {
                "agent": "codex",
                "proposal": "Optimize performance",
                "votes": 2,
            },
        ],
        "votes": {
            "claude": "Add error handling",
            "codex": "Add error handling",
            "gemini": "Add error handling",
        },
    }


@pytest.fixture
def mock_design_result() -> dict[str, Any]:
    """Create a mock design result."""
    return {
        "approved": True,
        "design": {
            "components": ["ErrorHandler", "RetryLogic"],
            "files_to_modify": ["aragora/errors.py", "aragora/retry.py"],
            "tests_required": ["test_error_handling.py"],
        },
        "safety_review": {
            "safe": True,
            "concerns": [],
        },
    }


@pytest.fixture
def mock_implementation_result() -> dict[str, Any]:
    """Create a mock implementation result."""
    return {
        "success": True,
        "files_created": ["aragora/errors.py"],
        "files_modified": ["aragora/core.py"],
        "lines_added": 50,
        "lines_removed": 5,
        "code_changes": {
            "aragora/errors.py": "class ErrorHandler: pass",
        },
    }


@pytest.fixture
def mock_verification_result() -> dict[str, Any]:
    """Create a mock verification result."""
    return {
        "passed": True,
        "test_results": {
            "total": 10,
            "passed": 10,
            "failed": 0,
            "skipped": 0,
        },
        "coverage": 85.5,
        "mypy_clean": True,
        "lint_clean": True,
    }


class MockNomicState:
    """Mock nomic state for testing."""

    def __init__(self):
        self.cycle_count = 1
        self.phase = "context"
        self.context = {}
        self.proposals = []
        self.design = {}
        self.implementation = {}
        self.verification = {}
        self.errors = []
        self.checkpoints = []


@pytest.fixture
def mock_nomic_state() -> MockNomicState:
    """Create a mock nomic state."""
    return MockNomicState()
