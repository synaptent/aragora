"""
Claude Code Harness Integration.

Integrates with Claude Code CLI for code analysis and review.

Usage:
    harness = ClaudeCodeHarness()
    result = await harness.analyze_repository(
        repo_path=Path("/path/to/repo"),
        analysis_type=AnalysisType.SECURITY,
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
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
    HarnessConfigError,
    HarnessError,
    HarnessResult,
    HarnessTimeoutError,
    SessionContext,
    SessionResult,
)

logger = logging.getLogger(__name__)


@dataclass
class ClaudeCodeConfig(HarnessConfig):
    """Configuration for Claude Code harness."""

    # Claude Code CLI settings
    claude_code_path: str = "claude"  # Path to claude CLI
    model: str = "claude-sonnet-4-20250514"  # Model to use

    # Analysis settings
    max_thinking_tokens: int = 10000
    include_file_contents: bool = True
    use_mcp_tools: bool = True

    # Output parsing
    parse_structured_output: bool = True
    extract_code_blocks: bool = True

    # System prompt injection for context-aware implementation
    append_system_prompt: str | None = None  # Appended to Claude Code's system prompt
    inject_claude_md: bool = True  # Auto-read CLAUDE.md from repo root
    inject_memory_md: bool = True  # Auto-read MEMORY.md from project memory dir

    # Prompts for different analysis types
    analysis_prompts: dict[str, str] = field(
        default_factory=lambda: {
            AnalysisType.SECURITY.value: """Analyze this codebase for security vulnerabilities.
Look for:
- Hardcoded credentials, API keys, secrets
- SQL injection vulnerabilities
- XSS vulnerabilities
- Command injection
- Path traversal
- Insecure deserialization
- Sensitive data exposure
- Authentication/authorization issues

For each finding, provide:
1. Title
2. Severity (critical/high/medium/low)
3. File and line number
4. Description of the vulnerability
5. Code snippet showing the issue
6. Recommended fix

Format findings as JSON array.""",
            AnalysisType.QUALITY.value: """Analyze this codebase for code quality issues.
Look for:
- Code duplication
- Complex or hard-to-understand code
- Missing error handling
- Unused variables/imports
- Inconsistent naming conventions
- Missing documentation
- Anti-patterns

Format findings as JSON array with severity, file, line, description, and recommendation.""",
            AnalysisType.ARCHITECTURE.value: """Analyze the architecture of this codebase.
Evaluate:
- Module organization
- Dependency structure
- Separation of concerns
- SOLID principles adherence
- Design patterns used
- Potential improvements

Provide architectural findings and recommendations.""",
            AnalysisType.DEPENDENCIES.value: """Analyze the dependencies in this codebase.
Look for:
- Outdated dependencies
- Known vulnerabilities in dependencies
- Unused dependencies
- Missing dependencies
- Version conflicts

Format findings as JSON array.""",
            AnalysisType.GENERAL.value: """Analyze this codebase and provide a comprehensive review.
Include:
- Overall code quality assessment
- Security concerns
- Performance considerations
- Architecture evaluation
- Recommendations for improvement

Format any specific findings as JSON array.""",
        }
    )


class ClaudeCodeHarness(CodeAnalysisHarness):
    """
    Harness for Claude Code CLI integration.

    Spawns Claude Code as a subprocess and parses its output
    to extract structured findings.
    """

    def __init__(self, config: ClaudeCodeConfig | None = None):
        super().__init__(config or ClaudeCodeConfig())
        self.config: ClaudeCodeConfig = self.config
        self._process: asyncio.subprocess.Process | None = None
        self._sessions: dict[str, SessionContext] = {}

    @property
    def name(self) -> str:
        return "claude-code"

    @property
    def supports_interactive(self) -> bool:
        """Claude Code supports interactive sessions."""
        return True

    @property
    def supported_analysis_types(self) -> list[AnalysisType]:
        return list(AnalysisType)

    async def initialize(self) -> bool:
        """Check if Claude Code CLI is available."""
        try:
            # Check if claude command exists
            claude_path = shutil.which(self.config.claude_code_path)
            if not claude_path:
                logger.warning("Claude Code CLI not found at: %s", self.config.claude_code_path)
                return False

            # Try to get version
            proc = await asyncio.create_subprocess_exec(
                self.config.claude_code_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                logger.warning("Claude Code CLI version check timed out")
                return False

            if proc.returncode == 0:
                version = stdout.decode().strip()
                logger.info("Claude Code CLI available: %s", version)
                self._initialized = True
                return True
            else:
                logger.warning("Claude Code CLI check failed: %s", stderr.decode())
                return False

        except (OSError, ValueError, RuntimeError) as e:
            logger.warning("Failed to initialize Claude Code harness: %s", e)
            return False

    async def analyze_repository(
        self,
        repo_path: Path,
        analysis_type: AnalysisType = AnalysisType.GENERAL,
        prompt: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> HarnessResult:
        """
        Analyze a repository using Claude Code.

        Args:
            repo_path: Path to the repository
            analysis_type: Type of analysis to perform
            prompt: Optional custom prompt (overrides default)
            options: Additional options

        Returns:
            Analysis result with findings
        """
        self._validate_path(repo_path)
        options = options or {}

        started_at = datetime.now(timezone.utc)
        findings: list[AnalysisFinding] = []
        raw_output = ""
        error_output = ""
        error_message = None
        success = False

        try:
            # Build the prompt
            analysis_prompt = prompt or self.config.analysis_prompts.get(
                analysis_type.value,
                self.config.analysis_prompts[AnalysisType.GENERAL.value],
            )

            # Build file list
            files_to_analyze = self._collect_files(repo_path)
            files_content = ""

            if self.config.include_file_contents:
                files_content = self._build_files_context(files_to_analyze)

            full_prompt = f"""{analysis_prompt}

Repository path: {repo_path}
Files to analyze: {len(files_to_analyze)}

{files_content}

Respond with a JSON array of findings. Each finding should have:
- id: unique identifier
- title: short title
- description: detailed description
- severity: critical/high/medium/low/info
- confidence: 0.0-1.0
- category: category of the issue
- file_path: relative file path
- line_start: starting line number (optional)
- line_end: ending line number (optional)
- code_snippet: relevant code (optional)
- recommendation: how to fix (optional)
"""

            # Run Claude Code
            raw_output, error_output = await self._run_claude_code(
                full_prompt,
                cwd=repo_path,
            )

            # Parse findings from output
            findings = self._parse_findings(raw_output, analysis_type)
            success = True

        except HarnessTimeoutError:
            error_message = f"Analysis timed out after {self.config.timeout_seconds}s"
            logger.error(error_message)
        except HarnessError as e:
            error_message = str(e)
            logger.error("Harness error: %s", e)
        except (OSError, ValueError, TypeError, RuntimeError) as e:
            error_message = f"Unexpected error: {e}"
            logger.exception("Unexpected error in analyze_repository")

        completed_at = datetime.now(timezone.utc)

        return HarnessResult(
            harness=self.name,
            analysis_type=analysis_type,
            success=success,
            findings=findings,
            started_at=started_at,
            completed_at=completed_at,
            files_analyzed=len(self._collect_files(repo_path)) if repo_path.exists() else 0,
            raw_output=raw_output,
            error_output=error_output,
            error_message=error_message,
            metadata={
                "repo_path": str(repo_path),
                "prompt_used": prompt is not None,
                "options": options,
            },
        )

    async def analyze_files(
        self,
        files: list[Path],
        analysis_type: AnalysisType = AnalysisType.GENERAL,
        prompt: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> HarnessResult:
        """Analyze specific files using Claude Code."""
        if not files:
            return HarnessResult(
                harness=self.name,
                analysis_type=analysis_type,
                success=False,
                findings=[],
                error_message="No files provided",
            )

        # Use parent of first file as working directory
        cwd = files[0].parent
        return await self.analyze_repository(
            repo_path=cwd,
            analysis_type=analysis_type,
            prompt=prompt,
            options={**(options or {}), "specific_files": [str(f) for f in files]},
        )

    async def stream_analysis(
        self,
        repo_path: Path,
        analysis_type: AnalysisType = AnalysisType.GENERAL,
        prompt: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream analysis output in real-time."""
        self._validate_path(repo_path)

        analysis_prompt = prompt or self.config.analysis_prompts.get(
            analysis_type.value,
            self.config.analysis_prompts[AnalysisType.GENERAL.value],
        )

        cmd = [
            self.config.claude_code_path,
            "--print",  # Print output to stdout
            "-p",
            analysis_prompt,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(repo_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            while True:
                if proc.stdout is None:
                    break

                line = await asyncio.wait_for(
                    proc.stdout.readline(),
                    timeout=self.config.timeout_seconds,
                )

                if not line:
                    break

                yield line.decode()

        except asyncio.TimeoutError:
            proc.kill()
            raise HarnessTimeoutError("Stream timed out", self.name)
        finally:
            await proc.wait()

    async def start_interactive_session(
        self,
        context: SessionContext,
    ) -> SessionResult:
        """Start an interactive Claude Code session."""
        session_id = context.session_id or str(uuid4())
        context.session_id = session_id

        self._sessions[session_id] = context

        # Initial prompt
        initial_prompt = f"""You are analyzing the repository at {context.repo_path}.
Files in context: {", ".join(context.files_in_context) if context.files_in_context else "all"}

I'll ask you questions about the codebase. Provide helpful, accurate answers."""

        raw_output, _ = await self._run_claude_code(
            initial_prompt,
            cwd=context.repo_path,
        )

        return SessionResult(
            session_id=session_id,
            response=raw_output,
            continue_conversation=True,
        )

    async def continue_session(
        self,
        context: SessionContext,
        user_input: str,
    ) -> SessionResult:
        """Continue an interactive session."""
        if context.session_id not in self._sessions:
            raise HarnessError("Session not found", self.name)

        # Add to conversation history
        context.conversation_history.append({"role": "user", "content": user_input})

        # Build context with history
        history = "\n".join(
            f"{msg['role']}: {msg['content']}" for msg in context.conversation_history[-5:]
        )

        raw_output, _ = await self._run_claude_code(
            f"{history}\n\nuser: {user_input}",
            cwd=context.repo_path,
        )

        context.conversation_history.append({"role": "assistant", "content": raw_output})

        # Parse any findings from the response
        findings = self._parse_findings(raw_output, AnalysisType.GENERAL)

        return SessionResult(
            session_id=context.session_id,
            response=raw_output,
            findings=findings,
            continue_conversation=True,
        )

    async def end_session(self, context: SessionContext) -> None:
        """End an interactive session."""
        if context.session_id in self._sessions:
            del self._sessions[context.session_id]

    @staticmethod
    def _get_allowed_tools() -> list[str]:
        """Return allowed tool list for scoped implementation sessions."""
        return [
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Grep",
            "Glob",
            "mcp__aragora__*",
        ]

    def _build_system_prompt_injection(self, repo_path: Path) -> str | None:
        """Build system prompt injection from CLAUDE.md and MEMORY.md.

        Reads project conventions and memory files, truncates to reasonable
        lengths, and combines with any custom append_system_prompt config.

        Args:
            repo_path: Path to the repository root.

        Returns:
            Combined system prompt string, or None if nothing to inject.
        """
        parts: list[str] = []

        # Read CLAUDE.md from repo root
        if self.config.inject_claude_md:
            claude_md_path = Path(repo_path) / "CLAUDE.md"
            try:
                content = claude_md_path.read_text(encoding="utf-8")
                # Extract key sections, truncate to 2000 chars
                truncated = content[:2000]
                if len(content) > 2000:
                    truncated += "\n... (truncated)"
                parts.append(f"## Project Conventions (CLAUDE.md)\n{truncated}")
            except (FileNotFoundError, OSError):
                pass

        # Read MEMORY.md from project memory dir
        if self.config.inject_memory_md:
            # Standard Claude Code memory dir pattern
            memory_dir = Path.home() / ".claude" / "projects"
            try:
                if memory_dir.is_dir():
                    for project_dir in memory_dir.iterdir():
                        memory_file = project_dir / "memory" / "MEMORY.md"
                        if memory_file.is_file():
                            content = memory_file.read_text(encoding="utf-8")
                            truncated = content[:1000]
                            if len(content) > 1000:
                                truncated += "\n... (truncated)"
                            parts.append(f"## Project Memory (MEMORY.md)\n{truncated}")
                            break  # Use first matching project
            except (OSError, PermissionError):
                pass

        # Append custom system prompt if configured
        if self.config.append_system_prompt:
            parts.append(self.config.append_system_prompt)

        if not parts:
            return None
        return "\n\n".join(parts)

    async def execute_implementation(
        self,
        repo_path: Path,
        prompt: str,
    ) -> tuple[str, str]:
        """Execute an implementation task using Claude Code in edit mode.

        Unlike analyze_repository (which uses --print for read-only analysis),
        this method runs Claude Code without --print, allowing it to edit files
        directly. Used by the Nomic Loop implementation phase.

        Args:
            repo_path: Path to the repository to modify
            prompt: Implementation instructions

        Returns:
            Tuple of (stdout, stderr) from Claude Code
        """
        self._validate_path(repo_path)

        cmd = [
            self.config.claude_code_path,
            "-p",  # Non-interactive mode (no --print, allows file edits)
            prompt,
            "--yes",  # Auto-approve file edits
        ]

        if self.config.model:
            cmd.extend(["--model", self.config.model])

        # Inject system prompt with project context
        system_prompt = self._build_system_prompt_injection(repo_path)
        if system_prompt:
            cmd.extend(["--append-system-prompt", system_prompt])

        # Wire MCP tools when enabled
        if self.config.use_mcp_tools:
            try:
                from aragora.mcp.impl_config import generate_impl_mcp_config

                mcp_config_path = generate_impl_mcp_config(repo_path)
                cmd.extend(["--mcp-config", str(mcp_config_path)])
            except (ImportError, OSError) as exc:
                logger.warning("MCP config generation failed: %s", exc)

            # Scope allowed tools
            allowed = self._get_allowed_tools()
            cmd.extend(["--allowedTools", ",".join(allowed)])

        env = os.environ.copy()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(repo_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.config.timeout_seconds,
            )

            logger.info(
                "Claude Code implementation completed (exit=%s, stdout=%d bytes)",
                proc.returncode,
                len(stdout),
            )
            return stdout.decode(), stderr.decode()

        except asyncio.TimeoutError:
            if proc:
                proc.kill()
            raise HarnessTimeoutError(
                f"Claude Code implementation timed out after {self.config.timeout_seconds}s",
                self.name,
            )
        except FileNotFoundError:
            raise HarnessConfigError(
                f"Claude Code CLI not found: {self.config.claude_code_path}",
                self.name,
            )

    async def _run_claude_code(
        self,
        prompt: str,
        cwd: Path | None = None,
    ) -> tuple[str, str]:
        """
        Run Claude Code CLI with a prompt (read-only analysis mode).

        Returns:
            Tuple of (stdout, stderr)
        """
        cmd = [
            self.config.claude_code_path,
            "--print",  # Print output (read-only, no file edits)
            "-p",
            prompt,
        ]

        if self.config.model:
            cmd.extend(["--model", self.config.model])

        env = os.environ.copy()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd) if cwd else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.config.timeout_seconds,
            )

            return stdout.decode(), stderr.decode()

        except asyncio.TimeoutError:
            if proc:
                proc.kill()
            raise HarnessTimeoutError(
                f"Claude Code timed out after {self.config.timeout_seconds}s",
                self.name,
            )
        except FileNotFoundError:
            raise HarnessConfigError(
                f"Claude Code CLI not found: {self.config.claude_code_path}",
                self.name,
            )

    def _collect_files(self, repo_path: Path) -> list[Path]:
        """Collect files to analyze based on patterns."""
        files = []
        try:
            for path in repo_path.rglob("*"):
                if path.is_file() and self._should_include_file(path):
                    # Check file size
                    if path.stat().st_size <= self.config.max_file_size_mb * 1024 * 1024:
                        files.append(path)

                        if len(files) >= self.config.max_files:
                            break
        except (OSError, PermissionError) as e:
            logger.warning("Error collecting files: %s", e)

        return files

    def _build_files_context(self, files: list[Path]) -> str:
        """Build context string with file contents."""
        context_parts = []
        total_size = 0
        max_size = self.config.max_output_size_mb * 1024 * 1024

        for file_path in files:
            try:
                content = file_path.read_text(errors="ignore")
                file_context = f"\n--- {file_path} ---\n{content}\n"

                if total_size + len(file_context) > max_size:
                    break

                context_parts.append(file_context)
                total_size += len(file_context)

            except (OSError, UnicodeDecodeError) as e:
                logger.debug("Could not read file %s: %s", file_path, e)

        return "\n".join(context_parts)

    def _parse_findings(
        self,
        output: str,
        analysis_type: AnalysisType,
    ) -> list[AnalysisFinding]:
        """Parse findings from Claude Code output."""
        findings = []

        # Try to extract JSON array from output
        json_match = re.search(r"\[[\s\S]*?\]", output)
        if json_match:
            try:
                json_data = json.loads(json_match.group())
                if isinstance(json_data, list):
                    for i, item in enumerate(json_data):
                        if isinstance(item, dict):
                            finding = AnalysisFinding(
                                id=item.get("id", f"finding_{i}"),
                                title=item.get("title", "Untitled Finding"),
                                description=item.get("description", ""),
                                severity=item.get("severity", "medium").lower(),
                                confidence=float(item.get("confidence", 0.75)),
                                category=item.get("category", analysis_type.value),
                                file_path=item.get("file_path", ""),
                                line_start=item.get("line_start"),
                                line_end=item.get("line_end"),
                                code_snippet=item.get("code_snippet", ""),
                                recommendation=item.get("recommendation", ""),
                            )
                            findings.append(finding)
            except json.JSONDecodeError:
                logger.debug("Could not parse JSON from output")

        # If no JSON found, try to parse structured text
        if not findings and self.config.parse_structured_output:
            findings = self._parse_structured_text(output, analysis_type)

        return findings

    def _parse_structured_text(
        self,
        output: str,
        analysis_type: AnalysisType,
    ) -> list[AnalysisFinding]:
        """Parse findings from structured text output."""
        findings = []

        # Pattern for common finding formats
        finding_pattern = re.compile(
            r"(?:Finding|Issue|Vulnerability|Problem)\s*(?:\d+)?[:\s]*"
            r"(?P<title>[^\n]+)\n"
            r"(?:.*?Severity[:\s]*(?P<severity>critical|high|medium|low|info))?"
            r"(?:.*?File[:\s]*(?P<file>[^\n]+))?"
            r"(?:.*?Line[:\s]*(?P<line>\d+))?",
            re.IGNORECASE | re.DOTALL,
        )

        for i, match in enumerate(finding_pattern.finditer(output)):
            finding = AnalysisFinding(
                id=f"finding_{i}",
                title=match.group("title").strip(),
                description="",
                severity=match.group("severity") or "medium",
                confidence=0.7,
                category=analysis_type.value,
                file_path=match.group("file") or "",
                line_start=int(match.group("line")) if match.group("line") else None,
            )
            findings.append(finding)

        return findings


__all__ = [
    "ClaudeCodeHarness",
    "ClaudeCodeConfig",
]
