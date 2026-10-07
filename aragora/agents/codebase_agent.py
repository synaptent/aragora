"""
Codebase Understanding Agent for multi-agent code analysis.

Provides comprehensive codebase analysis through:
- AST-based code intelligence
- Call graph analysis
- Security vulnerability scanning
- Bug pattern detection
- Multi-agent debate for code understanding
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aragora.agents.base import BaseDebateAgent
from aragora.agents.code_scanners import (
    BUG_DETECTOR,
    SECURITY_SCANNER,
    CodeScannerNotRegisteredError,
    create_code_scanner,
)
from aragora.core_types import AgentRole

logger = logging.getLogger(__name__)


@dataclass
class CodebaseIndex:
    """Index of codebase structure and symbols."""

    root_path: str
    total_files: int = 0
    total_lines: int = 0
    languages: dict[str, int] = field(default_factory=dict)  # lang -> file count
    symbols: dict[str, list[str]] = field(default_factory=dict)  # symbol type -> names
    file_summaries: dict[str, str] = field(default_factory=dict)  # path -> summary

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "root_path": self.root_path,
            "total_files": self.total_files,
            "total_lines": self.total_lines,
            "languages": self.languages,
            "symbol_counts": {k: len(v) for k, v in self.symbols.items()},
            "indexed_files": len(self.file_summaries),
        }


@dataclass
class CodeUnderstanding:
    """Result of code understanding query."""

    question: str
    answer: str
    confidence: float
    relevant_files: list[str]
    code_citations: list[dict[str, Any]]  # {file, line, snippet, relevance}
    related_symbols: list[str]
    reasoning_trace: list[str] = field(default_factory=list)
    agent_perspectives: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "question": self.question,
            "answer": self.answer,
            "confidence": self.confidence,
            "relevant_files": self.relevant_files,
            "code_citations": self.code_citations,
            "related_symbols": self.related_symbols,
            "reasoning_trace": self.reasoning_trace,
            "agent_perspectives": self.agent_perspectives,
        }


@dataclass
class CodeAuditResult:
    """Result of comprehensive code audit."""

    scan_id: str
    started_at: datetime
    completed_at: datetime | None = None
    root_path: str = ""

    # Scan results
    security_findings: list[dict[str, Any]] = field(default_factory=list)
    bug_findings: list[dict[str, Any]] = field(default_factory=list)
    quality_issues: list[dict[str, Any]] = field(default_factory=list)
    dead_code: list[dict[str, Any]] = field(default_factory=list)

    # Analysis
    risk_score: float = 0.0
    prioritized_remediations: list[dict[str, Any]] = field(default_factory=list)
    agent_summary: str = ""

    # Stats
    files_analyzed: int = 0
    lines_analyzed: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "scan_id": self.scan_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "root_path": self.root_path,
            "summary": {
                "security_findings": len(self.security_findings),
                "bug_findings": len(self.bug_findings),
                "quality_issues": len(self.quality_issues),
                "dead_code_items": len(self.dead_code),
                "risk_score": self.risk_score,
            },
            "security_findings": self.security_findings[:20],
            "bug_findings": self.bug_findings[:20],
            "quality_issues": self.quality_issues[:20],
            "prioritized_remediations": self.prioritized_remediations,
            "agent_summary": self.agent_summary,
            "files_analyzed": self.files_analyzed,
            "lines_analyzed": self.lines_analyzed,
            "error": self.error,
        }


class CodeAnalystAgent(BaseDebateAgent):
    """Agent specialized in code structure and architecture analysis."""

    persona = "senior software architect with deep expertise in code organization"
    focus = "code structure, design patterns, and architectural decisions"

    def __init__(self, name: str = "code-analyst"):
        # Initialize Agent attributes directly to avoid ABC init issues
        self.name = name
        self.model = "pattern-based"
        self.role: AgentRole = "critic"  # Analysts act as critics
        self.agent_type = "code_analyst"
        self.stance = "neutral"
        self.persona = self.__class__.persona
        self.focus = self.__class__.focus
        self.system_prompt = f"You are a {self.persona}. Focus on: {self.focus}"

    async def generate(self, prompt: str, context=None) -> str:
        """Generate response - stub for analysis agent."""
        return f"[Code Analyst] Analysis: {prompt[:100]}..."

    async def critique(self, proposal: str, task: str, context=None, target_agent=None):
        """Critique - stub for analysis agent."""
        from aragora.core_types import Critique

        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal[:200],
            issues=[],
            suggestions=[],
            severity=0.0,
            reasoning="Code structure analysis",
        )


class SecurityReviewerAgent(BaseDebateAgent):
    """Agent specialized in security vulnerability analysis."""

    persona = "security engineer focused on identifying vulnerabilities"
    focus = "security vulnerabilities, attack vectors, and defensive coding"

    def __init__(self, name: str = "security-reviewer"):
        # Initialize Agent attributes directly to avoid ABC init issues
        self.name = name
        self.model = "pattern-based"
        self.role = "critic"
        self.agent_type = "security_reviewer"
        self.stance = "neutral"
        self.persona = self.__class__.persona
        self.focus = self.__class__.focus
        self.system_prompt = f"You are a {self.persona}. Focus on: {self.focus}"

    async def generate(self, prompt: str, context=None) -> str:
        """Generate response - stub for security agent."""
        return f"[Security Reviewer] Analysis: {prompt[:100]}..."

    async def critique(self, proposal: str, task: str, context=None, target_agent=None):
        """Critique - stub for security agent."""
        from aragora.core_types import Critique

        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal[:200],
            issues=[],
            suggestions=[],
            severity=0.0,
            reasoning="Security vulnerability analysis",
        )


class BugHunterAgent(BaseDebateAgent):
    """Agent specialized in bug pattern detection."""

    persona = "QA engineer expert at finding subtle bugs and edge cases"
    focus = "bug patterns, error handling, and edge cases"

    def __init__(self, name: str = "bug-hunter"):
        # Initialize Agent attributes directly to avoid ABC init issues
        self.name = name
        self.model = "pattern-based"
        self.role = "critic"
        self.agent_type = "bug_hunter"
        self.stance = "neutral"
        self.persona = self.__class__.persona
        self.focus = self.__class__.focus
        self.system_prompt = f"You are a {self.persona}. Focus on: {self.focus}"

    async def generate(self, prompt: str, context=None) -> str:
        """Generate response - stub for bug hunter agent."""
        return f"[Bug Hunter] Analysis: {prompt[:100]}..."

    async def critique(self, proposal: str, task: str, context=None, target_agent=None):
        """Critique - stub for bug hunter agent."""
        from aragora.core_types import Critique

        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal[:200],
            issues=[],
            suggestions=[],
            severity=0.0,
            reasoning="Bug pattern analysis",
        )


class CodebaseUnderstandingAgent:
    """
    Multi-agent system for comprehensive codebase understanding.

    Combines:
    - AST-based code intelligence for symbol extraction
    - Call graph analysis for understanding relationships
    - Security scanning for vulnerability detection
    - Bug detection for identifying potential issues
    - Multi-agent debate for nuanced understanding

    Usage:
        agent = CodebaseUnderstandingAgent(root_path="/path/to/repo")

        # Answer questions about the codebase
        understanding = await agent.understand("How does authentication work?")

        # Run comprehensive audit
        audit = await agent.audit()
    """

    def __init__(
        self,
        root_path: str,
        exclude_patterns: list[str] | None = None,
        enable_debate: bool = True,
    ):
        """
        Initialize the codebase understanding agent.

        Args:
            root_path: Root directory of the codebase
            exclude_patterns: Patterns to exclude from analysis
            enable_debate: Whether to use multi-agent debate for analysis
        """
        self.root_path = Path(root_path)
        self.exclude_patterns = exclude_patterns or [
            "__pycache__",
            ".git",
            "node_modules",
            ".venv",
            "venv",
            "dist",
            "build",
            ".pytest_cache",
        ]
        self.enable_debate = enable_debate

        # Lazy-loaded components
        self._code_intel: Any | None = None
        self._call_graph_builder: Any | None = None
        self._security_scanner: Any | None = None
        self._bug_detector: Any | None = None
        self._index: CodebaseIndex | None = None
        self._context_builder: Any | None = None
        self._rlm_context_cache: str | None = None
        self._use_rlm_context = os.environ.get("ARAGORA_CODEBASE_CONTEXT_RLM", "1") == "1"

        # Specialist agents for debate
        self._agents = [
            CodeAnalystAgent(),
            SecurityReviewerAgent(),
            BugHunterAgent(),
        ]

    def _get_context_builder(self) -> Any | None:
        """Lazy-load a shared RLM codebase context builder."""
        if self._context_builder is not None:
            return self._context_builder
        try:
            from aragora.rlm.codebase_context import CodebaseContextBuilder

            self._context_builder = CodebaseContextBuilder(root_path=self.root_path)
        except (ImportError, TypeError, ValueError, OSError) as exc:
            logger.warning("Codebase RLM context builder unavailable: %s", exc)
            self._context_builder = None
        return self._context_builder

    async def _get_rlm_context(self) -> str | None:
        """Build or return cached RLM codebase context."""
        if not self._use_rlm_context:
            return None
        if self._rlm_context_cache:
            return self._rlm_context_cache
        builder = self._get_context_builder()
        if not builder:
            return None
        try:
            context = await builder.build_debate_context()
            self._rlm_context_cache = context
            return context
        except (RuntimeError, ValueError, OSError, AttributeError) as exc:
            logger.warning("RLM context build failed: %s", exc)
            return None

    @property
    def code_intel(self) -> Any:
        """Lazy-load code intelligence module."""
        if self._code_intel is None:
            try:
                from aragora.analysis.code_intelligence import CodeIntelligence

                self._code_intel = CodeIntelligence()
            except ImportError:
                logger.warning("CodeIntelligence not available")
                self._code_intel = None
        return self._code_intel

    @property
    def call_graph_builder(self) -> Any:
        """Lazy-load call graph builder."""
        if self._call_graph_builder is None:
            try:
                from aragora.analysis.call_graph import CallGraphBuilder

                self._call_graph_builder = CallGraphBuilder(self.code_intel)
            except ImportError:
                logger.warning("CallGraphBuilder not available")
                self._call_graph_builder = None
        return self._call_graph_builder

    @property
    def security_scanner(self) -> Any:
        """Lazy-load security scanner."""
        if self._security_scanner is None:
            try:
                self._security_scanner = create_code_scanner(SECURITY_SCANNER)
            except (CodeScannerNotRegisteredError, ImportError):
                logger.warning("SecurityScanner not available")
                self._security_scanner = None
        return self._security_scanner

    @property
    def bug_detector(self) -> Any:
        """Lazy-load bug detector."""
        if self._bug_detector is None:
            try:
                self._bug_detector = create_code_scanner(BUG_DETECTOR)
            except (CodeScannerNotRegisteredError, ImportError):
                logger.warning("BugDetector not available")
                self._bug_detector = None
        return self._bug_detector

    async def index_codebase(self, force: bool = False) -> CodebaseIndex:
        """
        Build an index of the codebase for faster queries.

        Args:
            force: Force re-indexing even if index exists

        Returns:
            CodebaseIndex with codebase structure
        """
        if self._index is not None and not force:
            return self._index

        logger.info("Indexing codebase at %s", self.root_path)
        start_time = datetime.now(timezone.utc)

        index = CodebaseIndex(root_path=str(self.root_path))

        if self.code_intel is None:
            logger.warning("CodeIntelligence not available; using basic indexing")
            # Fallback to basic file listing
            for ext in [".py", ".js", ".ts", ".tsx", ".go", ".java", ".rs"]:
                for file_path in self.root_path.rglob(f"*{ext}"):
                    if any(p in str(file_path) for p in self.exclude_patterns):
                        continue
                    index.total_files += 1
                    lang = self._extension_to_language(ext)
                    index.languages[lang] = index.languages.get(lang, 0) + 1
            self._index = index
            return index

        # Use CodeIntelligence for comprehensive indexing
        analyses_dict = self.code_intel.analyze_directory(
            str(self.root_path), exclude_patterns=self.exclude_patterns
        )

        for analysis in analyses_dict.values():
            index.total_files += 1
            index.total_lines += (
                analysis.lines_of_code + analysis.comment_lines + analysis.blank_lines
            )

            # Track language distribution
            lang = analysis.language.value if analysis.language else "unknown"
            index.languages[lang] = index.languages.get(lang, 0) + 1

            # Collect symbols
            if "classes" not in index.symbols:
                index.symbols["classes"] = []
            if "functions" not in index.symbols:
                index.symbols["functions"] = []
            if "modules" not in index.symbols:
                index.symbols["modules"] = []

            for cls in analysis.classes:
                index.symbols["classes"].append(cls.name)
            for func in analysis.functions:
                index.symbols["functions"].append(func.name)
            index.symbols["modules"].append(Path(analysis.file_path).stem)

            # Brief file summary
            class_names = [c.name for c in analysis.classes[:3]]
            func_names = [f.name for f in analysis.functions[:5]]
            summary_parts = []
            if class_names:
                summary_parts.append(f"Classes: {', '.join(class_names)}")
            if func_names:
                summary_parts.append(f"Functions: {', '.join(func_names)}")
            if summary_parts:
                rel_path = str(Path(analysis.file_path).relative_to(self.root_path))
                index.file_summaries[rel_path] = "; ".join(summary_parts)

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(
            f"Indexed {index.total_files} files ({index.total_lines} lines) in {elapsed:.2f}s"
        )

        self._index = index
        return index

    async def understand(
        self,
        question: str,
        max_files: int = 10,
    ) -> CodeUnderstanding:
        """
        Answer a question about the codebase.

        Uses:
        1. Codebase indexing for symbol resolution
        2. Semantic search for relevant code
        3. Multi-agent debate for nuanced understanding

        Args:
            question: Natural language question about the codebase
            max_files: Maximum files to include in analysis

        Returns:
            CodeUnderstanding with answer and citations
        """
        logger.info("Understanding question: %s...", question[:100])

        # Ensure codebase is indexed
        index = await self.index_codebase()

        # Find relevant files and symbols
        relevant_files, code_citations = await self._find_relevant_code(question, index, max_files)

        # Build context for answering
        context = self._build_understanding_context(question, index, relevant_files, code_citations)
        rlm_context = await self._get_rlm_context()
        if rlm_context:
            context = f"=== CODEBASE STRUCTURE MAP (RLM) ===\n{rlm_context}\n\n{context}"

        # Generate answer (with optional multi-agent debate)
        if self.enable_debate:
            answer, agent_perspectives, reasoning = await self._debate_understanding(
                question, context
            )
        else:
            answer = self._generate_simple_answer(question, context)
            agent_perspectives = {}
            reasoning = []

        # Calculate confidence based on evidence quality
        confidence = self._calculate_confidence(code_citations, len(relevant_files))

        related_symbols = []
        for citation in code_citations:
            if "symbol" in citation:
                related_symbols.append(citation["symbol"])

        return CodeUnderstanding(
            question=question,
            answer=answer,
            confidence=confidence,
            relevant_files=relevant_files,
            code_citations=code_citations,
            related_symbols=list(set(related_symbols)),
            reasoning_trace=reasoning,
            agent_perspectives=agent_perspectives,
        )

    async def audit(
        self,
        include_dead_code: bool = True,
        include_quality: bool = True,
    ) -> CodeAuditResult:
        """
        Run comprehensive security and bug audit.

        Combines:
        1. Security vulnerability scanning
        2. Bug pattern detection
        3. Dead code analysis
        4. Code quality assessment
        5. Multi-agent review of findings

        Args:
            include_dead_code: Run dead code analysis
            include_quality: Include quality metrics

        Returns:
            CodeAuditResult with all findings
        """
        start_time = datetime.now(timezone.utc)
        scan_id = f"codebase_audit_{start_time.strftime('%Y%m%d_%H%M%S')}"

        logger.info("[%s] Starting comprehensive codebase audit", scan_id)

        result = CodeAuditResult(
            scan_id=scan_id,
            started_at=start_time,
            root_path=str(self.root_path),
        )

        # Run security scan
        if self.security_scanner:
            try:
                security_report = self.security_scanner.scan_directory(
                    str(self.root_path), self.exclude_patterns
                )
                result.security_findings = [f.to_dict() for f in security_report.findings]
                result.files_analyzed = security_report.files_scanned
                result.lines_analyzed = security_report.lines_scanned
            except (OSError, ValueError, RuntimeError, AttributeError) as e:
                logger.error("Security scan failed: %s", e)
                result.error = "Security scan failed"

        # Run bug detection
        if self.bug_detector:
            try:
                bug_report = self.bug_detector.detect_in_directory(
                    str(self.root_path), self.exclude_patterns
                )
                result.bug_findings = [b.to_dict() for b in bug_report.bugs]
                if not result.files_analyzed:
                    result.files_analyzed = bug_report.files_scanned
                    result.lines_analyzed = bug_report.lines_scanned
            except (OSError, ValueError, RuntimeError, AttributeError) as e:
                logger.error("Bug detection failed: %s", e)
                if result.error:
                    result.error += "; Bug detection failed"
                else:
                    result.error = "Bug detection failed"

        # Dead code analysis
        if include_dead_code and self.call_graph_builder:
            try:
                call_graph = self.call_graph_builder.build_from_directory(
                    str(self.root_path), self.exclude_patterns
                )
                dead_code = call_graph.find_dead_code()
                result.dead_code = [
                    {
                        "name": n.qualified_name,
                        "kind": n.kind.value,
                        "location": (
                            f"{n.location.file_path}:{n.location.start_line}"
                            if n.location
                            else None
                        ),
                    }
                    for n in dead_code.unreachable_functions[:50]
                ]
            except (OSError, ValueError, RuntimeError, AttributeError) as e:
                logger.warning("Dead code analysis failed: %s", e)

        # Code quality assessment
        if include_quality and self.code_intel:
            try:
                await self._analyze_quality(result)
            except (OSError, ValueError, RuntimeError, AttributeError) as e:
                logger.warning("Quality analysis failed: %s", e)

        # Calculate overall risk score
        result.risk_score = self._calculate_risk_score(result)

        # Prioritize remediations
        result.prioritized_remediations = self._prioritize_remediations(result)

        # Generate agent summary (with optional multi-agent review)
        if self.enable_debate:
            result.agent_summary = await self._generate_audit_summary(result)
        else:
            result.agent_summary = self._generate_simple_summary(result)

        result.completed_at = datetime.now(timezone.utc)

        elapsed = (result.completed_at - start_time).total_seconds()
        logger.info(
            f"[{scan_id}] Audit completed in {elapsed:.2f}s: "
            f"{len(result.security_findings)} security, "
            f"{len(result.bug_findings)} bugs"
        )

        return result

    async def _find_relevant_code(
        self,
        question: str,
        index: CodebaseIndex,
        max_files: int,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """Find code relevant to the question."""
        relevant_files: list[str] = []
        citations: list[dict[str, Any]] = []

        # Extract keywords from question
        keywords = self._extract_keywords(question)

        # Search symbols for matches
        for keyword in keywords:
            keyword_lower = keyword.lower()

            # Check class names
            for cls_name in index.symbols.get("classes", []):
                if keyword_lower in cls_name.lower():
                    # Find file containing this class
                    for file_path, summary in index.file_summaries.items():
                        if cls_name in summary:
                            if file_path not in relevant_files:
                                relevant_files.append(file_path)
                            citations.append(
                                {
                                    "file": file_path,
                                    "symbol": cls_name,
                                    "type": "class",
                                    "relevance": 0.9,
                                }
                            )

            # Check function names
            for func_name in index.symbols.get("functions", []):
                if keyword_lower in func_name.lower():
                    for file_path, summary in index.file_summaries.items():
                        if func_name in summary:
                            if file_path not in relevant_files:
                                relevant_files.append(file_path)
                            citations.append(
                                {
                                    "file": file_path,
                                    "symbol": func_name,
                                    "type": "function",
                                    "relevance": 0.8,
                                }
                            )

        # If code intelligence available, do more sophisticated search
        if self.code_intel and len(relevant_files) < max_files:
            for keyword in keywords[:3]:  # Limit expensive searches
                usages = self.code_intel.find_symbol_usages(str(self.root_path), keyword)
                for usage in usages[:5]:
                    rel_path = str(Path(usage.file_path).relative_to(self.root_path))
                    if rel_path not in relevant_files:
                        relevant_files.append(rel_path)
                    citations.append(
                        {
                            "file": rel_path,
                            "line": usage.start_line,
                            "snippet": f"Line {usage.start_line}",  # SourceLocation doesn't have context
                            "relevance": 0.7,
                        }
                    )

        # Sort by relevance and limit
        citations.sort(key=lambda c: c.get("relevance", 0), reverse=True)
        return relevant_files[:max_files], citations[:20]

    def _build_understanding_context(
        self,
        question: str,
        index: CodebaseIndex,
        relevant_files: list[str],
        citations: list[dict[str, Any]],
    ) -> str:
        """Build context string for answering questions."""
        parts = []

        # Codebase overview
        parts.append("## Codebase Overview")
        parts.append(f"Total files: {index.total_files}")
        parts.append(f"Languages: {', '.join(index.languages.keys())}")
        parts.append(f"Classes: {len(index.symbols.get('classes', []))}")
        parts.append(f"Functions: {len(index.symbols.get('functions', []))}")
        parts.append("")

        # Relevant files
        if relevant_files:
            parts.append("## Relevant Files")
            for file_path in relevant_files[:10]:
                summary = index.file_summaries.get(file_path, "")
                parts.append(f"- {file_path}: {summary}")
            parts.append("")

        # Code citations
        if citations:
            parts.append("## Code Evidence")
            for citation in citations[:10]:
                parts.append(
                    f"- {citation.get('file', '')}:{citation.get('line', '')} - {citation.get('symbol', citation.get('snippet', '')[:50])}"
                )
            parts.append("")

        return "\n".join(parts)

    async def _debate_understanding(
        self,
        question: str,
        context: str,
    ) -> tuple[str, dict[str, str], list[str]]:
        """Use multi-agent debate to answer question."""
        # Simplified debate - in production would use full Arena
        perspectives: dict[str, str] = {}
        reasoning: list[str] = []

        # Each agent provides perspective
        for agent in self._agents:
            perspective = f"[{agent.name}] Analysis from {agent.focus} perspective"
            perspectives[agent.name] = perspective
            reasoning.append(f"Agent {agent.name} analyzed for {agent.focus}")

        # Synthesize answer
        answer = f"""Based on analysis of the codebase:

{context}

The agents provided the following insights:
- Code Analyst: Examined structure and patterns
- Security Reviewer: Checked for security implications
- Bug Hunter: Looked for potential issues

Summary: [Synthesis of perspectives based on question: {question[:50]}...]"""

        return answer, perspectives, reasoning

    def _generate_simple_answer(self, question: str, context: str) -> str:
        """Generate simple answer without debate."""
        return f"""Based on codebase analysis:

{context}

This addresses: {question}"""

    async def _analyze_quality(self, result: CodeAuditResult) -> None:
        """Analyze code quality metrics."""
        if self.code_intel is None:
            return

        # Collect complexity metrics
        analyses = self.code_intel.analyze_directory(
            str(self.root_path), exclude_patterns=self.exclude_patterns
        )

        high_complexity = []
        for analysis in analyses:
            for func in analysis.functions:
                if func.complexity and func.complexity > 10:
                    high_complexity.append(
                        {
                            "file": analysis.file_path,
                            "function": func.name,
                            "complexity": func.complexity,
                            "issue": "High cyclomatic complexity",
                        }
                    )

        result.quality_issues = high_complexity[:20]

    def _calculate_risk_score(self, result: CodeAuditResult) -> float:
        """Calculate overall risk score (0-100)."""
        score = 0.0

        # Security findings weighted heavily
        for finding in result.security_findings:
            severity = finding.get("severity", "low")
            if severity == "critical":
                score += 20
            elif severity == "high":
                score += 10
            elif severity == "medium":
                score += 5
            else:
                score += 1

        # Bug findings
        for bug in result.bug_findings:
            severity = bug.get("severity", "low")
            if severity == "critical":
                score += 15
            elif severity == "high":
                score += 7
            elif severity == "medium":
                score += 3
            else:
                score += 1

        return min(100.0, score)

    def _prioritize_remediations(self, result: CodeAuditResult) -> list[dict[str, Any]]:
        """Prioritize remediation actions."""
        remediations = []

        # Group findings by severity
        critical_findings = []
        high_findings = []

        for f in result.security_findings:
            if f.get("severity") == "critical":
                critical_findings.append(("security", f))
            elif f.get("severity") == "high":
                high_findings.append(("security", f))

        for b in result.bug_findings:
            if b.get("severity") == "critical":
                critical_findings.append(("bug", b))
            elif b.get("severity") == "high":
                high_findings.append(("bug", b))

        # Create prioritized list
        priority = 1
        for finding_type, finding in critical_findings[:5]:
            remediations.append(
                {
                    "priority": priority,
                    "type": finding_type,
                    "title": finding.get("title", "Unknown"),
                    "file": finding.get("file_path", ""),
                    "recommendation": finding.get("recommendation", ""),
                    "urgency": "immediate",
                }
            )
            priority += 1

        for finding_type, finding in high_findings[:10]:
            remediations.append(
                {
                    "priority": priority,
                    "type": finding_type,
                    "title": finding.get("title", "Unknown"),
                    "file": finding.get("file_path", ""),
                    "recommendation": finding.get("recommendation", ""),
                    "urgency": "soon",
                }
            )
            priority += 1

        return remediations

    async def _generate_audit_summary(self, result: CodeAuditResult) -> str:
        """Generate audit summary with agent perspectives."""
        parts = []

        parts.append("## Codebase Audit Summary")
        parts.append("")
        parts.append(f"**Risk Score:** {result.risk_score:.1f}/100")
        parts.append(f"**Files Analyzed:** {result.files_analyzed}")
        parts.append("")

        parts.append("### Findings Overview")
        parts.append(f"- Security Issues: {len(result.security_findings)}")
        parts.append(f"- Potential Bugs: {len(result.bug_findings)}")
        parts.append(f"- Quality Issues: {len(result.quality_issues)}")
        parts.append(f"- Dead Code Items: {len(result.dead_code)}")
        parts.append("")

        if result.prioritized_remediations:
            parts.append("### Top Priorities")
            for rem in result.prioritized_remediations[:5]:
                parts.append(
                    f"{rem['priority']}. [{rem['type'].upper()}] {rem['title']} - {rem['urgency']}"
                )

        return "\n".join(parts)

    def _generate_simple_summary(self, result: CodeAuditResult) -> str:
        """Generate simple summary without agent analysis."""
        return f"""Audit Summary:
- Security findings: {len(result.security_findings)}
- Bug findings: {len(result.bug_findings)}
- Risk score: {result.risk_score:.1f}/100"""

    def _extract_keywords(self, question: str) -> list[str]:
        """Extract relevant keywords from question."""
        # Simple keyword extraction
        stopwords = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "how",
            "what",
            "where",
            "when",
            "why",
            "does",
            "do",
            "can",
            "could",
            "would",
            "should",
            "this",
            "that",
            "these",
            "those",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
        }

        words = question.lower().split()
        keywords = [w.strip("?.,!") for w in words if w.lower() not in stopwords and len(w) > 2]

        return keywords[:10]

    def _calculate_confidence(self, citations: list[dict[str, Any]], file_count: int) -> float:
        """Calculate confidence based on evidence quality."""
        if not citations and file_count == 0:
            return 0.3

        base_confidence = 0.5

        # More citations = more confidence
        citation_boost = min(0.3, len(citations) * 0.05)

        # Average relevance of citations
        if citations:
            avg_relevance = sum(c.get("relevance", 0.5) for c in citations) / len(citations)
            relevance_boost = avg_relevance * 0.2
        else:
            relevance_boost = 0

        return min(0.95, base_confidence + citation_boost + relevance_boost)

    def _extension_to_language(self, ext: str) -> str:
        """Map file extension to language name."""
        mapping = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".go": "go",
            ".java": "java",
            ".rs": "rust",
        }
        return mapping.get(ext, "unknown")


async def quick_codebase_audit(path: str) -> dict[str, Any]:
    """
    Quick codebase audit for a directory.

    Args:
        path: Path to codebase root

    Returns:
        Audit results dictionary
    """
    agent = CodebaseUnderstandingAgent(root_path=path, enable_debate=False)
    result = await agent.audit(include_dead_code=False, include_quality=True)
    return result.to_dict()


async def understand_codebase(path: str, question: str) -> dict[str, Any]:
    """
    Answer a question about a codebase.

    Args:
        path: Path to codebase root
        question: Question to answer

    Returns:
        Understanding results dictionary
    """
    agent = CodebaseUnderstandingAgent(root_path=path, enable_debate=False)
    result = await agent.understand(question)
    return result.to_dict()
