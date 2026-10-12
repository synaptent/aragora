"""
OpenAI Codex/GPT Harness.

Integration with OpenAI's API for code analysis tasks.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import AsyncIterator
from uuid import uuid4

from aragora.harnesses.base import (
    AnalysisFinding,
    AnalysisType,
    CodeAnalysisHarness,
    HarnessConfig,
    HarnessError,
    HarnessResult,
    SessionContext,
    SessionResult,
)
from aragora.config import get_api_key
from aragora.swarm.harness_health import (
    get_harness_health_registry,
    record_harness_result,
)

logger = logging.getLogger(__name__)


@dataclass
class CodexConfig(HarnessConfig):
    """Configuration for OpenAI Codex harness."""

    # Model settings
    model: str = "gpt-4o"  # or gpt-4-turbo, gpt-3.5-turbo
    temperature: float = 0.2
    max_tokens: int = 4096

    # API settings
    api_key: str | None = None  # Falls back to OPENAI_API_KEY env var

    # Analysis prompts per type
    analysis_prompts: dict[str, str] = field(
        default_factory=lambda: {
            AnalysisType.SECURITY.value: """Analyze this code for security vulnerabilities.
Look for:
- SQL injection, command injection, path traversal
- XSS vulnerabilities
- Authentication/authorization issues
- Sensitive data exposure
- Insecure cryptography
- SSRF vulnerabilities

For each issue found, provide:
1. Title (brief description)
2. Severity (critical/high/medium/low/info)
3. File path and line numbers
4. Description of the vulnerability
5. Recommended fix
6. Code snippet showing the issue

Format your response as JSON array of findings.""",
            AnalysisType.QUALITY.value: """Analyze this code for quality issues.
Look for:
- Code smells and anti-patterns
- Complex or confusing code
- Missing error handling
- Poor naming conventions
- Duplicated code
- Dead code
- Magic numbers/strings

For each issue found, provide structured feedback.""",
            AnalysisType.PERFORMANCE.value: """Analyze this code for performance issues.
Look for:
- N+1 queries
- Memory leaks
- Inefficient algorithms
- Missing caching opportunities
- Resource contention
- Blocking operations

Provide specific recommendations for improvement.""",
            AnalysisType.ARCHITECTURE.value: """Analyze this codebase's architecture.
Consider:
- SOLID principles adherence
- Separation of concerns
- Dependency management
- Module boundaries
- API design
- Error handling patterns

Provide architectural recommendations.""",
            AnalysisType.DEPENDENCIES.value: """Analyze dependencies for security issues.
Check:
- Known vulnerabilities (CVEs)
- Outdated packages
- License compatibility
- Unnecessary dependencies

List all issues found with severity.""",
            AnalysisType.DOCUMENTATION.value: """Analyze code documentation quality.
Check:
- Missing docstrings
- Outdated comments
- Unclear function signatures
- Missing type hints
- API documentation gaps

Provide specific recommendations.""",
            AnalysisType.TESTING.value: """Analyze test coverage and quality.
Look for:
- Missing test cases
- Inadequate assertions
- Test code smells
- Mocking issues
- Edge cases not covered

Provide testing recommendations.""",
            AnalysisType.GENERAL.value: """Perform a general code review.
Consider all aspects: security, quality, performance, and maintainability.
Provide prioritized findings and recommendations.""",
        }
    )


class CodexHarness(CodeAnalysisHarness):
    """
    OpenAI Codex/GPT harness for code analysis.

    Uses OpenAI's API to analyze code for various issues.
    Supports streaming responses and batch analysis.
    """

    config: CodexConfig  # Type override for subclass-specific config

    def __init__(self, config: CodexConfig | None = None):
        self.config = config or CodexConfig()
        self._client: Any = None

    @property
    def name(self) -> str:
        """Return the harness name."""
        return "codex"

    @property
    def supported_analysis_types(self) -> list[AnalysisType]:
        """Return list of supported analysis types."""
        return list(AnalysisType)

    def _get_client(self) -> Any:
        """Get or create OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError:
                raise HarnessError(
                    "openai package not installed. Install with: pip install openai",
                    harness="codex",
                )

            api_key = self.config.api_key or get_api_key("OPENAI_API_KEY", required=False)
            if not api_key:
                raise HarnessError(
                    "OPENAI_API_KEY environment variable not set",
                    harness="codex",
                )

            self._client = AsyncOpenAI(api_key=api_key)

        return self._client

    async def analyze_repository(
        self,
        repo_path: Path,
        analysis_type: AnalysisType = AnalysisType.GENERAL,
        prompt: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> HarnessResult:
        """
        Analyze a repository using OpenAI's API.

        Args:
            repo_path: Path to the repository
            analysis_type: Type of analysis to perform
            prompt: Optional custom prompt for the analysis
            options: Additional options (file_patterns, exclude_patterns, max_files)

        Returns:
            HarnessResult with findings
        """
        options = options or {}
        started_at = datetime.now(timezone.utc)

        get_harness_health_registry().record_attempt(self.name)

        try:
            # Gather code files
            file_patterns = options.get("file_patterns", ["**/*.py", "**/*.js", "**/*.ts"])
            exclude_patterns = options.get(
                "exclude_patterns", ["**/node_modules/**", "**/__pycache__/**", "**/venv/**"]
            )
            max_files = options.get("max_files", 50)

            files_content = await self._gather_files(
                repo_path, file_patterns, exclude_patterns, max_files
            )

            if not files_content:
                # No-op success — caller produced an empty work surface,
                # not a harness failure. Record success to keep the
                # health registry honest.
                record_harness_result(harness=self.name, success=True)
                return HarnessResult(
                    harness="codex",
                    analysis_type=analysis_type,
                    findings=[],
                    raw_output="No matching files found",
                    duration_seconds=0,
                    success=True,
                )

            # Build analysis prompt
            analysis_prompt = self._build_analysis_prompt(files_content, analysis_type, prompt)

            # Call OpenAI API
            raw_output = await self._call_openai(analysis_prompt)

            # Parse findings
            findings = self._parse_findings(raw_output, repo_path, analysis_type)

            duration = (datetime.now(timezone.utc) - started_at).total_seconds()

            record_harness_result(harness=self.name, success=True)

            return HarnessResult(
                harness="codex",
                analysis_type=analysis_type,
                findings=findings,
                raw_output=raw_output,
                duration_seconds=duration,
                success=True,
                metadata={
                    "model": self.config.model,
                    "files_analyzed": len(files_content),
                    "repo_path": str(repo_path),
                },
            )

        except (OSError, ValueError, TypeError, RuntimeError) as e:
            logger.exception("Codex analysis failed: %s", e)
            record_harness_result(
                harness=self.name,
                success=False,
                error_message=str(e),
            )
            return HarnessResult(
                harness="codex",
                analysis_type=analysis_type,
                findings=[],
                raw_output=str(e),
                duration_seconds=(datetime.now(timezone.utc) - started_at).total_seconds(),
                success=False,
                error_message=str(e),
            )

    async def analyze_files(
        self,
        files: list[Path],
        analysis_type: AnalysisType = AnalysisType.GENERAL,
        prompt: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> HarnessResult:
        """Analyze specific files."""
        options = options or {}
        started_at = datetime.now(timezone.utc)

        get_harness_health_registry().record_attempt(self.name)

        try:
            # Read file contents
            files_content: dict[str, str] = {}
            for file_path in files:
                if file_path.exists() and file_path.is_file():
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        files_content[str(file_path)] = content
                    except (OSError, UnicodeDecodeError) as e:
                        logger.warning("Failed to read %s: %s", file_path, e)

            if not files_content:
                # Empty work surface — not a harness failure.
                record_harness_result(harness=self.name, success=True)
                return HarnessResult(
                    harness="codex",
                    analysis_type=analysis_type,
                    findings=[],
                    raw_output="No files could be read",
                    duration_seconds=0,
                    success=True,
                )

            # Build and send prompt
            analysis_prompt = self._build_analysis_prompt(files_content, analysis_type, prompt)
            raw_output = await self._call_openai(analysis_prompt)
            findings = self._parse_findings(raw_output, files[0].parent, analysis_type)

            duration = (datetime.now(timezone.utc) - started_at).total_seconds()

            record_harness_result(harness=self.name, success=True)

            return HarnessResult(
                harness="codex",
                analysis_type=analysis_type,
                findings=findings,
                raw_output=raw_output,
                duration_seconds=duration,
                success=True,
                metadata={
                    "model": self.config.model,
                    "files_analyzed": len(files_content),
                },
            )

        except (OSError, ValueError, TypeError, RuntimeError) as e:
            logger.exception("Codex file analysis failed: %s", e)
            record_harness_result(
                harness=self.name,
                success=False,
                error_message=str(e),
            )
            return HarnessResult(
                harness="codex",
                analysis_type=analysis_type,
                findings=[],
                raw_output=str(e),
                duration_seconds=(datetime.now(timezone.utc) - started_at).total_seconds(),
                success=False,
                error_message=str(e),
            )

    async def stream_analysis(
        self,
        repo_path: Path,
        analysis_type: AnalysisType = AnalysisType.GENERAL,
        prompt: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Stream analysis results."""
        options = options or {}

        try:
            # Gather files
            file_patterns = options.get("file_patterns", ["**/*.py", "**/*.js", "**/*.ts"])
            exclude_patterns = options.get(
                "exclude_patterns", ["**/node_modules/**", "**/__pycache__/**"]
            )
            max_files = options.get("max_files", 50)

            files_content = await self._gather_files(
                repo_path, file_patterns, exclude_patterns, max_files
            )

            if not files_content:
                yield "No matching files found for analysis."
                return

            analysis_prompt = self._build_analysis_prompt(files_content, analysis_type, prompt)

            # Stream from OpenAI
            client = self._get_client()
            stream = await client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": "You are a code analysis expert."},
                    {"role": "user", "content": analysis_prompt},
                ],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                stream=True,
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except (OSError, ValueError, TypeError, RuntimeError) as e:
            logger.exception("Codex stream analysis failed: %s", e)
            yield f"Error: {e}"

    async def run_interactive_session(
        self,
        context: SessionContext,
        prompt: str,
    ) -> SessionResult:
        """Run an interactive analysis session."""
        _started_at = datetime.now(timezone.utc)

        try:
            # Build context from files
            files_content: dict[str, str] = {}
            for file_path in context.files_in_context:
                path = Path(file_path)
                if path.exists():
                    files_content[file_path] = path.read_text(encoding="utf-8", errors="ignore")

            # Build messages
            messages: list[dict[str, str]] = [
                {
                    "role": "system",
                    "content": "You are a code analysis expert. Help the user understand and improve their code.",
                },
            ]

            # Add context
            if files_content:
                context_text = "\n\n".join(
                    f"=== {path} ===\n{content}" for path, content in files_content.items()
                )
                messages.append(
                    {
                        "role": "user",
                        "content": f"Here is the code context:\n\n{context_text}",
                    }
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": "I've reviewed the code. What would you like me to help you with?",
                    }
                )

            # Add user prompt
            messages.append({"role": "user", "content": prompt})

            # Call OpenAI
            client = self._get_client()
            response = await client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )

            response_text = response.choices[0].message.content

            return SessionResult(
                session_id=context.session_id,
                response=response_text if response_text is not None else "",
            )

        except (OSError, ValueError, TypeError, RuntimeError) as e:
            logger.exception("Codex interactive session failed: %s", e)
            return SessionResult(
                session_id=context.session_id,
                response="Error: session execution failed",
            )

    async def _gather_files(
        self,
        repo_path: Path,
        patterns: list[str],
        exclude_patterns: list[str],
        max_files: int,
    ) -> dict[str, str]:
        """Gather file contents matching patterns."""
        import fnmatch

        files_content: dict[str, str] = {}
        files_found = 0

        for pattern in patterns:
            for file_path in repo_path.glob(pattern):
                if files_found >= max_files:
                    break

                # Check exclusions
                rel_path = str(file_path.relative_to(repo_path))
                if any(fnmatch.fnmatch(rel_path, exc) for exc in exclude_patterns):
                    continue

                if file_path.is_file():
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        # Skip very large files
                        if len(content) > 100000:
                            continue
                        files_content[rel_path] = content
                        files_found += 1
                    except (OSError, UnicodeDecodeError) as e:
                        logger.warning("Failed to read %s: %s", file_path, e)

            if files_found >= max_files:
                break

        return files_content

    def _build_analysis_prompt(
        self,
        files_content: dict[str, str],
        analysis_type: AnalysisType,
        custom_prompt: str | None = None,
    ) -> str:
        """Build the analysis prompt."""
        # Use custom prompt if provided, otherwise use default based on analysis type
        if custom_prompt:
            base_prompt = custom_prompt
        else:
            base_prompt = self.config.analysis_prompts.get(
                analysis_type.value,
                self.config.analysis_prompts[AnalysisType.GENERAL.value],
            )

        code_section = "\n\n".join(
            f"=== {path} ===\n```\n{content}\n```" for path, content in files_content.items()
        )

        return f"""{base_prompt}

Here is the code to analyze:

{code_section}

Respond with your analysis in JSON format with an array of findings.
Each finding should have: id, title, severity, file_path, line_start, line_end, description, recommendation, category, confidence (0-1)."""

    async def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API."""
        client = self._get_client()

        response = await client.chat.completions.create(
            model=self.config.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a code analysis expert. Always respond with valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

        content = response.choices[0].message.content
        return content if content is not None else ""

    def _parse_findings(
        self,
        raw_output: str,
        repo_path: Path,
        analysis_type: AnalysisType,
    ) -> list[AnalysisFinding]:
        """Parse findings from OpenAI response."""
        findings: list[AnalysisFinding] = []

        try:
            # Try to extract JSON from response
            json_match = re.search(r"\[[\s\S]*\]", raw_output)
            if json_match:
                findings_data = json.loads(json_match.group())
            else:
                # Try parsing entire response as JSON
                findings_data = json.loads(raw_output)

            if not isinstance(findings_data, list):
                findings_data = [findings_data]

            for idx, item in enumerate(findings_data):
                if not isinstance(item, dict):
                    continue

                finding = AnalysisFinding(
                    id=item.get("id", f"codex_{uuid4().hex[:8]}"),
                    title=item.get("title", "Finding"),
                    severity=item.get("severity", "medium").lower(),
                    file_path=item.get("file_path", "unknown"),
                    line_start=item.get("line_start") or item.get("line"),
                    line_end=item.get("line_end"),
                    description=item.get("description", ""),
                    recommendation=item.get("recommendation", item.get("fix", "")),
                    category=item.get("category", analysis_type.value),
                    confidence=float(item.get("confidence", 0.8)),
                    code_snippet=item.get("code_snippet", item.get("snippet", "")),
                    references=item.get("references", []),
                )
                findings.append(finding)

        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON from OpenAI response, extracting manually")
            # Fall back to text extraction
            findings = self._extract_findings_from_text(raw_output, analysis_type)

        return findings

    def _extract_findings_from_text(
        self,
        text: str,
        analysis_type: AnalysisType,
    ) -> list[AnalysisFinding]:
        """Extract findings from non-JSON text response."""
        findings: list[AnalysisFinding] = []

        # Simple heuristic: look for severity indicators
        severity_patterns = {
            "critical": r"(?:critical|Critical|CRITICAL)",
            "high": r"(?:high|High|HIGH)",
            "medium": r"(?:medium|Medium|MEDIUM|moderate|Moderate)",
            "low": r"(?:low|Low|LOW)",
        }

        # Split by common delimiters
        sections = re.split(r"\n\d+\.|###|---|\*\*\*", text)

        for idx, section in enumerate(sections):
            if len(section.strip()) < 20:
                continue

            # Determine severity
            severity = "medium"
            for level, pattern in severity_patterns.items():
                if re.search(pattern, section):
                    severity = level
                    break

            # Extract title (first line or first sentence)
            lines = section.strip().split("\n")
            title = lines[0].strip()[:100] if lines else "Finding"

            # Clean title
            title = re.sub(r"^[\*#\-\s]+", "", title)
            if not title:
                continue

            finding = AnalysisFinding(
                id=f"codex_text_{idx}",
                title=title,
                severity=severity,
                file_path="unknown",
                description=section.strip(),
                category=analysis_type.value,
                confidence=0.6,  # Lower confidence for text extraction
            )
            findings.append(finding)

        return findings


# Convenience function
def create_codex_harness(
    model: str = "gpt-4o",
    api_key: str | None = None,
) -> CodexHarness:
    """Create a CodexHarness with custom configuration."""
    config = CodexConfig(model=model, api_key=api_key)
    return CodexHarness(config)


__all__ = [
    "CodexHarness",
    "CodexConfig",
    "create_codex_harness",
]
