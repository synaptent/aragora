"""
Base Harness Abstraction.

Defines the interface for external code analysis tools.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class AnalysisType(str, Enum):
    """Types of code analysis."""

    SECURITY = "security"
    QUALITY = "quality"
    PERFORMANCE = "performance"
    ARCHITECTURE = "architecture"
    DEPENDENCIES = "dependencies"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    GENERAL = "general"


class HarnessError(Exception):
    """Base exception for harness errors."""

    def __init__(self, message: str, harness: str = "", details: dict | None = None):
        super().__init__(message)
        self.harness = harness
        self.details = details or {}


class HarnessTimeoutError(HarnessError):
    """Raised when harness operation times out."""

    pass


class HarnessConfigError(HarnessError):
    """Raised when harness configuration is invalid."""

    pass


@dataclass
class HarnessConfig:
    """Base configuration for code analysis harnesses."""

    # Execution settings
    timeout_seconds: int = 300
    max_retries: int = 2
    retry_delay_seconds: float = 1.0

    # Output settings
    verbose: bool = False
    stream_output: bool = True
    capture_stderr: bool = True

    # Resource limits
    max_file_size_mb: int = 10
    max_files: int = 1000
    max_output_size_mb: int = 50

    # Analysis settings
    include_patterns: list[str] = field(default_factory=lambda: ["**/*"])
    exclude_patterns: list[str] = field(
        default_factory=lambda: [
            "**/.git/**",
            "**/node_modules/**",
            "**/__pycache__/**",
            "**/venv/**",
            "**/.venv/**",
            "**/dist/**",
            "**/build/**",
        ]
    )


@dataclass
class AnalysisFinding:
    """A single finding from code analysis."""

    id: str
    title: str
    description: str
    severity: str  # critical, high, medium, low, info
    confidence: float
    category: str
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    code_snippet: str = ""
    recommendation: str = ""
    references: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HarnessResult:
    """Result from a harness analysis operation."""

    harness: str
    analysis_type: AnalysisType
    success: bool
    findings: list[AnalysisFinding]

    # Execution metadata
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    duration_seconds: float = 0.0

    # Stats
    files_analyzed: int = 0
    lines_analyzed: int = 0
    findings_by_severity: dict[str, int] = field(default_factory=dict)

    # Output
    raw_output: str = ""
    error_output: str = ""
    error_message: str | None = None

    # Additional context
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Calculate derived fields."""
        if self.completed_at and self.started_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()

        # Calculate severity counts
        for finding in self.findings:
            sev = finding.severity.lower()
            self.findings_by_severity[sev] = self.findings_by_severity.get(sev, 0) + 1


@dataclass
class SessionContext:
    """Context for an interactive analysis session."""

    session_id: str
    repo_path: Path
    files_in_context: list[str] = field(default_factory=list)
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionResult:
    """Result from an interactive session."""

    session_id: str
    response: str
    findings: list[AnalysisFinding] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    continue_conversation: bool = True


class CodeAnalysisHarness(ABC):
    """
    Abstract interface for code analysis harnesses.

    Implementations integrate with external tools like Claude Code,
    Codex, or other code analysis systems.
    """

    def __init__(self, config: HarnessConfig | None = None):
        self.config = config or HarnessConfig()
        self._initialized = False

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the harness name."""
        ...

    @property
    def supports_interactive(self) -> bool:
        """Return whether this harness supports interactive sessions.

        Override in subclasses that implement start_interactive_session
        and continue_session without raising NotImplementedError.
        """
        return False

    @property
    @abstractmethod
    def supported_analysis_types(self) -> list[AnalysisType]:
        """Return list of supported analysis types."""
        ...

    async def initialize(self) -> bool:
        """
        Initialize the harness.

        Returns:
            True if initialization succeeded
        """
        self._initialized = True
        return True

    @abstractmethod
    async def analyze_repository(
        self,
        repo_path: Path,
        analysis_type: AnalysisType = AnalysisType.GENERAL,
        prompt: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> HarnessResult:
        """
        Analyze a repository or directory.

        Args:
            repo_path: Path to the repository or directory
            analysis_type: Type of analysis to perform
            prompt: Optional custom prompt for the analysis
            options: Additional options for the harness

        Returns:
            Analysis result with findings
        """
        ...

    @abstractmethod
    async def analyze_files(
        self,
        files: list[Path],
        analysis_type: AnalysisType = AnalysisType.GENERAL,
        prompt: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> HarnessResult:
        """
        Analyze specific files.

        Args:
            files: List of file paths to analyze
            analysis_type: Type of analysis to perform
            prompt: Optional custom prompt for the analysis
            options: Additional options for the harness

        Returns:
            Analysis result with findings
        """
        ...

    async def stream_analysis(
        self,
        repo_path: Path,
        analysis_type: AnalysisType = AnalysisType.GENERAL,
        prompt: str | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream analysis output in real-time.

        Args:
            repo_path: Path to analyze
            analysis_type: Type of analysis
            prompt: Optional custom prompt

        Yields:
            Output chunks as they become available
        """
        # Default implementation runs non-streaming analysis
        result = await self.analyze_repository(repo_path, analysis_type, prompt)
        yield result.raw_output

    async def start_interactive_session(
        self,
        context: SessionContext,
    ) -> SessionResult:
        """
        Start an interactive analysis session.

        Args:
            context: Session context with repo and file info

        Returns:
            Initial session result
        """
        raise NotImplementedError(f"{self.name} does not support interactive sessions")

    async def continue_session(
        self,
        context: SessionContext,
        user_input: str,
    ) -> SessionResult:
        """
        Continue an interactive session with user input.

        Args:
            context: Session context
            user_input: User's message/query

        Returns:
            Session response
        """
        raise NotImplementedError(f"{self.name} does not support interactive sessions")

    async def end_session(self, context: SessionContext) -> None:
        """End an interactive session and clean up resources."""
        pass

    def _validate_path(self, path: Path | str) -> None:
        """Validate a path before analysis."""
        path = Path(path) if isinstance(path, str) else path
        if not path.exists():
            raise HarnessConfigError(f"Path does not exist: {path}", self.name)

    def _should_include_file(self, file_path: Path) -> bool:
        """Check if a file should be included based on patterns."""
        import fnmatch

        path_str = str(file_path)

        # Check exclude patterns first
        for pattern in self.config.exclude_patterns:
            if fnmatch.fnmatch(path_str, pattern):
                return False

        # Check include patterns
        for pattern in self.config.include_patterns:
            if fnmatch.fnmatch(path_str, pattern):
                return True

        return True


__all__ = [
    "CodeAnalysisHarness",
    "HarnessConfig",
    "HarnessResult",
    "HarnessError",
    "HarnessTimeoutError",
    "HarnessConfigError",
    "AnalysisType",
    "AnalysisFinding",
    "SessionContext",
    "SessionResult",
]
