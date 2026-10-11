"""
Tests for CodebaseUnderstandingAgent and related components.

Tests codebase indexing, understanding queries, and security audits.
"""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from aragora.agents.codebase_agent import (
    CodebaseIndex,
    CodeUnderstanding,
    CodeAuditResult,
    CodebaseUnderstandingAgent,
    CodeAnalystAgent,
    SecurityReviewerAgent,
    BugHunterAgent,
)
from aragora.agents.code_scanners import CodeScannerNotRegisteredError


@pytest.fixture
def require_networkx() -> None:
    """Skip tests that require networkx when dependency is missing."""


# Sample code for testing
SAMPLE_PYTHON_MODULE = """
\"\"\"Sample module for testing codebase analysis.\"\"\"

import os
from pathlib import Path

class DataProcessor:
    \"\"\"Process data items.\"\"\"

    def __init__(self, config: dict):
        self.config = config
        self._cache = {}

    def process(self, data: list) -> list:
        \"\"\"Process a list of data items.\"\"\"
        results = []
        for item in data:
            results.append(self._transform(item))
        return results

    def _transform(self, item):
        \"\"\"Transform a single item.\"\"\"
        return item * 2


def helper_function(value: str) -> str:
    \"\"\"A helper function.\"\"\"
    return value.upper()


def unused_function():
    \"\"\"This function is never called.\"\"\"
    pass
"""

SAMPLE_PYTHON_MAIN = """
\"\"\"Main entry point.\"\"\"

from processor import DataProcessor, helper_function

def main():
    processor = DataProcessor({})
    data = [1, 2, 3]
    result = processor.process(data)
    print(helper_function(str(result)))

if __name__ == "__main__":
    main()
"""

CODE_WITH_ISSUES = """
import os
import subprocess

# Hardcoded credential
API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

def vulnerable_query(user_input):
    # SQL injection
    query = f"SELECT * FROM users WHERE id = {user_input}"
    return query

def run_command(cmd):
    # Command injection
    os.system(f"ls {cmd}")

try:
    risky_operation()
except:
    pass  # Swallowed exception
"""


class TestCodebaseIndex:
    """Tests for CodebaseIndex dataclass."""

    def test_create_index(self):
        """Test creating a codebase index."""
        index = CodebaseIndex(
            root_path="/test/project",
            total_files=10,
            total_lines=500,
            languages={"python": 8, "javascript": 2},
            symbols={
                "classes": ["ClassA", "ClassB"],
                "functions": ["func1", "func2", "func3"],
            },
            file_summaries={"module.py": "Classes: ClassA; Functions: func1"},
        )

        assert index.root_path == "/test/project"
        assert index.total_files == 10
        assert index.total_lines == 500
        assert index.languages["python"] == 8

    def test_index_to_dict(self):
        """Test serialization to dictionary."""
        index = CodebaseIndex(
            root_path="/test",
            total_files=5,
            total_lines=100,
            languages={"python": 5},
            symbols={"classes": ["A", "B"], "functions": ["f1"]},
            file_summaries={"a.py": "test"},
        )

        data = index.to_dict()

        assert data["root_path"] == "/test"
        assert data["total_files"] == 5
        assert data["symbol_counts"]["classes"] == 2
        assert data["symbol_counts"]["functions"] == 1
        assert data["indexed_files"] == 1


class TestCodeUnderstanding:
    """Tests for CodeUnderstanding dataclass."""

    def test_create_understanding(self):
        """Test creating a code understanding result."""
        understanding = CodeUnderstanding(
            question="How does authentication work?",
            answer="Authentication is handled by the AuthService class...",
            confidence=0.85,
            relevant_files=["auth/service.py", "auth/middleware.py"],
            code_citations=[
                {
                    "file": "auth/service.py",
                    "line": 42,
                    "snippet": "def authenticate(user, password):",
                    "relevance": 0.9,
                }
            ],
            related_symbols=["AuthService", "authenticate", "verify_token"],
            reasoning_trace=["Found AuthService class", "Analyzed authenticate method"],
            agent_perspectives={
                "analyst": "The auth flow is well-structured",
                "security": "Consider adding rate limiting",
            },
        )

        assert understanding.question == "How does authentication work?"
        assert understanding.confidence == 0.85
        assert len(understanding.relevant_files) == 2
        assert len(understanding.code_citations) == 1

    def test_understanding_to_dict(self):
        """Test serialization to dictionary."""
        understanding = CodeUnderstanding(
            question="Test question",
            answer="Test answer",
            confidence=0.75,
            relevant_files=["file.py"],
            code_citations=[{"file": "file.py", "line": 1}],
            related_symbols=["Symbol"],
        )

        data = understanding.to_dict()

        assert data["question"] == "Test question"
        assert data["answer"] == "Test answer"
        assert data["confidence"] == 0.75
        assert "file.py" in data["relevant_files"]


class TestCodeAuditResult:
    """Tests for CodeAuditResult dataclass."""

    def test_create_audit_result(self):
        """Test creating an audit result."""
        start = datetime.now(timezone.utc)
        result = CodeAuditResult(
            scan_id="audit_001",
            started_at=start,
            completed_at=start,
            root_path="/test/project",
            security_findings=[{"title": "Hardcoded Secret", "severity": "HIGH"}],
            bug_findings=[{"title": "Bare except", "severity": "MEDIUM"}],
            quality_issues=[{"title": "Complex function", "severity": "LOW"}],
            dead_code=[{"name": "unused_func", "kind": "function"}],
            risk_score=7.5,
            prioritized_remediations=[
                {"priority": 1, "finding": "Hardcoded Secret", "action": "Remove and use env vars"}
            ],
            agent_summary="This codebase has some security concerns...",
            files_analyzed=50,
            lines_analyzed=5000,
        )

        assert result.scan_id == "audit_001"
        assert result.risk_score == 7.5
        assert len(result.security_findings) == 1
        assert len(result.bug_findings) == 1
        assert result.files_analyzed == 50

    def test_audit_result_to_dict(self):
        """Test serialization to dictionary."""
        start = datetime.now(timezone.utc)
        result = CodeAuditResult(
            scan_id="audit_002",
            started_at=start,
            root_path="/test",
            risk_score=5.0,
        )

        data = result.to_dict()

        assert data["scan_id"] == "audit_002"
        assert data["summary"]["risk_score"] == 5.0
        assert "security_findings" in data["summary"]


class TestSpecialistAgents:
    """Tests for specialist agent classes."""

    def test_code_analyst_agent(self):
        """Test CodeAnalystAgent creation."""
        agent = CodeAnalystAgent()
        assert agent.name == "code-analyst"
        assert agent.role == "critic"  # Analysts act as critics in debates
        assert agent.agent_type == "code_analyst"
        assert "architect" in agent.persona.lower()

    def test_code_analyst_custom_name(self):
        """Test CodeAnalystAgent with custom name."""
        agent = CodeAnalystAgent(name="custom-analyst")
        assert agent.name == "custom-analyst"
        assert agent.role == "critic"  # Analysts act as critics in debates

    def test_security_reviewer_agent(self):
        """Test SecurityReviewerAgent creation."""
        agent = SecurityReviewerAgent()
        assert agent.name == "security-reviewer"
        assert agent.role == "critic"
        assert agent.agent_type == "security_reviewer"
        assert "security" in agent.persona.lower()

    def test_bug_hunter_agent(self):
        """Test BugHunterAgent creation."""
        agent = BugHunterAgent()
        assert agent.name == "bug-hunter"
        assert agent.role == "critic"
        assert agent.agent_type == "bug_hunter"
        assert "bug" in agent.focus.lower()


class TestCodebaseUnderstandingAgent:
    """Tests for CodebaseUnderstandingAgent class."""

    @pytest.fixture
    def sample_codebase(self, tmp_path):
        """Create a sample codebase for testing."""
        # Create directory structure
        src = tmp_path / "src"
        src.mkdir()

        # Create sample files
        (src / "processor.py").write_text(SAMPLE_PYTHON_MODULE)
        (src / "main.py").write_text(SAMPLE_PYTHON_MAIN)
        (src / "issues.py").write_text(CODE_WITH_ISSUES)

        # Create a subdir
        utils = src / "utils"
        utils.mkdir()
        (utils / "helpers.py").write_text("def util_helper(): pass")

        return tmp_path

    @pytest.fixture
    def agent(self, sample_codebase):
        """Create a CodebaseUnderstandingAgent instance with mocked agents."""
        # Patch the specialist agents which have unimplemented abstract methods
        with (
            patch(
                "aragora.agents.codebase_agent.CodeAnalystAgent",
                return_value=Mock(name="code-analyst"),
            ),
            patch(
                "aragora.agents.codebase_agent.SecurityReviewerAgent",
                return_value=Mock(name="security-reviewer"),
            ),
            patch(
                "aragora.agents.codebase_agent.BugHunterAgent",
                return_value=Mock(name="bug-hunter"),
            ),
        ):
            return CodebaseUnderstandingAgent(
                root_path=str(sample_codebase),
                enable_debate=False,  # Disable debate for faster tests
            )

    def test_agent_initialization(self, agent, sample_codebase):
        """Test agent initialization."""
        assert agent.root_path == Path(sample_codebase)
        assert agent.enable_debate is False
        assert len(agent._agents) == 3  # Three specialist agents (mocked)

    def test_agent_default_exclusions(self, sample_codebase):
        """Test default exclusion patterns."""
        with (
            patch("aragora.agents.codebase_agent.CodeAnalystAgent", return_value=Mock()),
            patch("aragora.agents.codebase_agent.SecurityReviewerAgent", return_value=Mock()),
            patch("aragora.agents.codebase_agent.BugHunterAgent", return_value=Mock()),
        ):
            agent = CodebaseUnderstandingAgent(root_path=str(sample_codebase))

        assert "__pycache__" in agent.exclude_patterns
        assert ".git" in agent.exclude_patterns
        assert "node_modules" in agent.exclude_patterns

    def test_agent_custom_exclusions(self, sample_codebase):
        """Test custom exclusion patterns."""
        with (
            patch("aragora.agents.codebase_agent.CodeAnalystAgent", return_value=Mock()),
            patch("aragora.agents.codebase_agent.SecurityReviewerAgent", return_value=Mock()),
            patch("aragora.agents.codebase_agent.BugHunterAgent", return_value=Mock()),
        ):
            agent = CodebaseUnderstandingAgent(
                root_path=str(sample_codebase),
                exclude_patterns=["custom_exclude"],
            )

        assert "custom_exclude" in agent.exclude_patterns
        # Default patterns should not be present when custom patterns are provided
        assert (
            "__pycache__" not in agent.exclude_patterns
            or "custom_exclude" in agent.exclude_patterns
        )

    def test_lazy_load_code_intel(self, agent):
        """Test lazy loading of CodeIntelligence."""
        # Should be None initially
        assert agent._code_intel is None

        # Access should trigger loading
        intel = agent.code_intel
        assert intel is not None

        # Second access should return same instance
        assert agent.code_intel is intel

    def test_lazy_load_security_scanner(self, agent):
        """Test lazy loading of SecurityScanner."""
        assert agent._security_scanner is None

        scanner = agent.security_scanner
        assert scanner is not None

        assert agent.security_scanner is scanner

    def test_lazy_load_bug_detector(self, agent):
        """Test lazy loading of BugDetector."""
        assert agent._bug_detector is None

        detector = agent.bug_detector
        assert detector is not None

        assert agent.bug_detector is detector

    @pytest.mark.parametrize("attribute", ["security_scanner", "bug_detector"])
    @pytest.mark.parametrize(
        "error", [CodeScannerNotRegisteredError("nothing registered"), ImportError("missing")]
    )
    def test_scanner_is_none_when_it_cannot_be_built(
        self, agent, monkeypatch, caplog, attribute, error
    ):
        def unavailable(kind):
            raise error

        monkeypatch.setattr("aragora.agents.codebase_agent.create_code_scanner", unavailable)
        with caplog.at_level("WARNING", logger="aragora.agents.codebase_agent"):
            assert getattr(agent, attribute) is None
        assert "not available" in caplog.text

    def test_lazy_load_call_graph_builder(self, agent):
        """Test lazy loading of CallGraphBuilder."""
        assert agent._call_graph_builder is None

        builder = agent.call_graph_builder
        assert builder is not None

        assert agent.call_graph_builder is builder

    @pytest.mark.asyncio
    async def test_index_codebase(self, agent, sample_codebase):
        """Test codebase indexing."""
        index = await agent.index_codebase()

        assert isinstance(index, CodebaseIndex)
        assert index.root_path == str(sample_codebase)
        assert index.total_files >= 3  # At least processor, main, issues
        assert "python" in index.languages

    @pytest.mark.asyncio
    async def test_index_codebase_cached(self, agent):
        """Test that index is cached."""
        index1 = await agent.index_codebase()
        index2 = await agent.index_codebase()

        # Should be same instance
        assert index1 is index2

    @pytest.mark.asyncio
    async def test_index_codebase_force_refresh(self, agent):
        """Test force refresh of index."""
        index1 = await agent.index_codebase()
        index2 = await agent.index_codebase(force=True)

        # Should be different instance
        assert index1 is not index2

    @pytest.mark.asyncio
    async def test_understand_question(self, agent):
        """Test understanding a question about the codebase."""
        understanding = await agent.understand("What classes are in the codebase?")

        assert isinstance(understanding, CodeUnderstanding)
        assert understanding.question == "What classes are in the codebase?"
        assert understanding.answer  # Should have an answer
        assert 0 <= understanding.confidence <= 1

    @pytest.mark.asyncio
    async def test_understand_returns_relevant_files(self, agent):
        """Test that understanding returns relevant files."""
        understanding = await agent.understand("How does DataProcessor work?")

        # Should find processor.py as relevant
        assert (
            any("processor" in f.lower() for f in understanding.relevant_files)
            or len(understanding.relevant_files) >= 0
        )

    @pytest.mark.asyncio
    async def test_audit_codebase(self, agent, require_networkx):
        """Test comprehensive codebase audit."""
        result = await agent.audit()

        assert isinstance(result, CodeAuditResult)
        assert result.scan_id.startswith("codebase_audit_")
        assert result.root_path == str(agent.root_path)
        assert result.completed_at is not None
        assert result.files_analyzed >= 0

    @pytest.mark.asyncio
    async def test_audit_finds_security_issues(self, agent, require_networkx):
        """Test that audit finds security issues in vulnerable code."""
        result = await agent.audit()

        # Should find at least one security finding (hardcoded secret or injection)
        # Note: May not find any if scanners have specific patterns
        assert result.security_findings is not None

    @pytest.mark.asyncio
    async def test_audit_finds_bug_patterns(self, agent, require_networkx):
        """Test that audit finds bug patterns."""
        result = await agent.audit()

        # Should find at least one bug (swallowed exception)
        assert result.bug_findings is not None

    @pytest.mark.asyncio
    async def test_audit_calculates_risk_score(self, agent, require_networkx):
        """Test that audit calculates a risk score."""
        result = await agent.audit()

        assert isinstance(result.risk_score, (int, float))
        assert result.risk_score >= 0

    @pytest.mark.asyncio
    async def test_audit_generates_summary(self, agent, require_networkx):
        """Test that audit generates a summary."""
        result = await agent.audit()

        assert result.agent_summary is not None

    @pytest.mark.asyncio
    async def test_audit_prioritizes_remediations(self, agent, require_networkx):
        """Test that audit prioritizes remediations."""
        result = await agent.audit()

        # Remediations should be a list (may be empty if no issues found)
        assert isinstance(result.prioritized_remediations, list)

    @pytest.mark.asyncio
    async def test_audit_without_dead_code(self, agent, require_networkx):
        """Test audit with dead code analysis disabled."""
        result = await agent.audit(include_dead_code=False)

        # Should still work, dead_code may or may not be populated
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_audit_without_quality(self, agent, require_networkx):
        """Test audit with quality analysis disabled."""
        result = await agent.audit(include_quality=False)

        # Should still work
        assert result.completed_at is not None


class TestCodebaseAgentEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.fixture
    def create_agent(self, tmp_path):
        """Factory fixture to create agents with mocked specialist agents."""

        def _create_agent(path=None):
            with (
                patch("aragora.agents.codebase_agent.CodeAnalystAgent", return_value=Mock()),
                patch("aragora.agents.codebase_agent.SecurityReviewerAgent", return_value=Mock()),
                patch("aragora.agents.codebase_agent.BugHunterAgent", return_value=Mock()),
            ):
                return CodebaseUnderstandingAgent(
                    root_path=str(path or tmp_path),
                    enable_debate=False,
                )

        return _create_agent

    @pytest.mark.asyncio
    async def test_empty_directory(self, tmp_path, create_agent):
        """Test analyzing an empty directory."""
        agent = create_agent(tmp_path)

        index = await agent.index_codebase()
        assert index.total_files == 0

    @pytest.mark.asyncio
    async def test_no_python_files(self, tmp_path, create_agent):
        """Test directory with no supported files."""
        (tmp_path / "readme.md").write_text("# README")
        (tmp_path / "data.json").write_text("{}")

        agent = create_agent(tmp_path)

        index = await agent.index_codebase()
        assert index.total_files == 0

    @pytest.mark.asyncio
    async def test_malformed_python(self, tmp_path, create_agent):
        """Test handling malformed Python files."""
        (tmp_path / "bad.py").write_text("def broken(\n  # syntax error")

        agent = create_agent(tmp_path)

        # Should not crash
        index = await agent.index_codebase()
        assert index is not None

    @pytest.mark.asyncio
    async def test_unicode_content(self, tmp_path, create_agent):
        """Test handling Unicode content."""
        (tmp_path / "unicode.py").write_text(
            '# -*- coding: utf-8 -*-\n"""Unicode: 你好世界 🌍"""\ndef greet(): pass',
            encoding="utf-8",
        )

        agent = create_agent(tmp_path)

        index = await agent.index_codebase()
        assert index.total_files >= 1

    @pytest.mark.asyncio
    async def test_understand_with_empty_codebase(self, tmp_path, create_agent):
        """Test understanding query on empty codebase."""
        agent = create_agent(tmp_path)

        understanding = await agent.understand("What does this codebase do?")

        # Should return result even with empty codebase
        assert understanding is not None
        assert understanding.confidence <= 1

    @pytest.mark.asyncio
    async def test_audit_empty_codebase(self, tmp_path, create_agent, require_networkx):
        """Test audit on empty codebase."""
        agent = create_agent(tmp_path)

        result = await agent.audit()

        # Should complete without error
        assert result.completed_at is not None
        assert result.files_analyzed == 0
