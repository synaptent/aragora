"""
Heuristic-based bug detection for codebase analysis.

Detects common bug patterns:
- Null/None reference risks
- Resource leaks (unclosed files/connections)
- Race conditions (shared mutable state)
- Off-by-one errors in loops
- Type confusion patterns
- Exception swallowing
- Infinite loop risks
- Integer overflow possibilities
- Logic errors
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from re import Pattern

logger = logging.getLogger(__name__)


class BugSeverity(str, Enum):
    """Severity level of potential bugs."""

    CRITICAL = "critical"  # Likely crash or data corruption
    HIGH = "high"  # Significant functionality issue
    MEDIUM = "medium"  # Moderate risk
    LOW = "low"  # Minor issue
    INFO = "info"  # Code smell, potential improvement


class BugCategory(str, Enum):
    """Category of potential bug."""

    NULL_REFERENCE = "null_reference"
    RESOURCE_LEAK = "resource_leak"
    RACE_CONDITION = "race_condition"
    OFF_BY_ONE = "off_by_one"
    TYPE_ERROR = "type_error"
    EXCEPTION_HANDLING = "exception_handling"
    INFINITE_LOOP = "infinite_loop"
    INTEGER_OVERFLOW = "integer_overflow"
    LOGIC_ERROR = "logic_error"
    MEMORY_ERROR = "memory_error"
    CONCURRENCY = "concurrency"
    API_MISUSE = "api_misuse"
    CODE_SMELL = "code_smell"


@dataclass
class BugPattern:
    """A pattern for detecting potential bugs."""

    name: str
    pattern: Pattern[str]
    category: BugCategory
    severity: BugSeverity
    description: str
    explanation: str
    fix_suggestion: str
    languages: list[str] | None = None
    false_positive_hints: list[str] = field(default_factory=list)


@dataclass
class PotentialBug:
    """A potential bug finding."""

    id: str
    title: str
    description: str
    category: BugCategory
    severity: BugSeverity
    confidence: float  # 0.0 - 1.0

    # Location
    file_path: str
    line_number: int
    column: int = 0
    end_line: int | None = None
    code_snippet: str = ""

    # Context
    function_name: str | None = None
    class_name: str | None = None

    # Analysis
    pattern_name: str | None = None
    explanation: str = ""
    fix_suggestion: str = ""
    related_lines: list[int] = field(default_factory=list)

    # Validation
    is_false_positive: bool = False
    false_positive_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "column": self.column,
            "end_line": self.end_line,
            "code_snippet": self.code_snippet,
            "function_name": self.function_name,
            "class_name": self.class_name,
            "pattern_name": self.pattern_name,
            "explanation": self.explanation,
            "fix_suggestion": self.fix_suggestion,
            "related_lines": self.related_lines,
            "is_false_positive": self.is_false_positive,
        }


@dataclass
class BugReport:
    """Complete bug detection report."""

    scan_id: str
    repository: str
    started_at: datetime
    completed_at: datetime | None = None
    files_scanned: int = 0
    lines_scanned: int = 0
    bugs: list[PotentialBug] = field(default_factory=list)
    error: str | None = None

    # Summary
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0

    def calculate_summary(self) -> None:
        """Calculate summary statistics."""
        self.critical_count = sum(1 for b in self.bugs if b.severity == BugSeverity.CRITICAL)
        self.high_count = sum(1 for b in self.bugs if b.severity == BugSeverity.HIGH)
        self.medium_count = sum(1 for b in self.bugs if b.severity == BugSeverity.MEDIUM)
        self.low_count = sum(1 for b in self.bugs if b.severity == BugSeverity.LOW)

    @property
    def total_bugs(self) -> int:
        return len(self.bugs)

    @property
    def bugs_by_category(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for bug in self.bugs:
            cat = bug.category.value
            counts[cat] = counts.get(cat, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "scan_id": self.scan_id,
            "repository": self.repository,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "files_scanned": self.files_scanned,
            "lines_scanned": self.lines_scanned,
            "total_bugs": self.total_bugs,
            "summary": {
                "critical": self.critical_count,
                "high": self.high_count,
                "medium": self.medium_count,
                "low": self.low_count,
            },
            "by_category": self.bugs_by_category,
            "bugs": [b.to_dict() for b in self.bugs],
            "error": self.error,
        }


class BugDetector:
    """
    Heuristic-based bug detection.

    Uses pattern matching and static analysis heuristics to
    identify potential bugs in source code.
    """

    # =====================================================================
    # NULL/NONE REFERENCE PATTERNS
    # =====================================================================
    NULL_PATTERNS = [
        BugPattern(
            name="None Check After Use",
            pattern=re.compile(
                r"(\w+)\.(\w+)\([^)]*\)[^\n]*\n[^\n]*if\s+\1\s+is\s+(?:None|not\s+None)",
                re.MULTILINE,
            ),
            category=BugCategory.NULL_REFERENCE,
            severity=BugSeverity.HIGH,
            description="Object used before None check",
            explanation="The object is dereferenced before checking if it's None, which can cause AttributeError",
            fix_suggestion="Move the None check before using the object",
            languages=["python"],
        ),
        BugPattern(
            name="Optional Without Check",
            pattern=re.compile(
                r":\s*Optional\[.+\]\s*(?:=\s*None)?[^)]*\)[^:]*:[^\n]*\n(?:[^\n]*\n)*?[^\n]*self\.\w+\s*=\s*\w+\.",
            ),
            category=BugCategory.NULL_REFERENCE,
            severity=BugSeverity.MEDIUM,
            description="Optional parameter used without None check",
            explanation="Optional parameter may be None but is used without verification",
            fix_suggestion="Add explicit None check before using Optional values",
            languages=["python"],
        ),
        BugPattern(
            name="Null Dereference Risk (JS)",
            pattern=re.compile(
                r"(\w+)\?\.(\w+)[^\n]*\n[^\n]*\1\.(?!\?)",
            ),
            category=BugCategory.NULL_REFERENCE,
            severity=BugSeverity.MEDIUM,
            description="Mixed optional chaining and direct access",
            explanation="Using ?. suggests nullable, but later direct access may fail",
            fix_suggestion="Use optional chaining consistently or add explicit null check",
            languages=["javascript", "typescript"],
        ),
    ]

    # =====================================================================
    # RESOURCE LEAK PATTERNS
    # =====================================================================
    RESOURCE_PATTERNS = [
        BugPattern(
            name="File Opened Without Context Manager",
            pattern=re.compile(
                r"(\w+)\s*=\s*open\s*\([^)]+\)(?!\s*\))",
            ),
            category=BugCategory.RESOURCE_LEAK,
            severity=BugSeverity.MEDIUM,
            description="File opened without 'with' statement",
            explanation="File may not be closed if an exception occurs before close() is called",
            fix_suggestion="Use 'with open(...) as f:' context manager",
            languages=["python"],
            false_positive_hints=["mock", "test", "close()"],
        ),
        BugPattern(
            name="Database Connection Without Close",
            pattern=re.compile(
                r"(\w+)\s*=\s*(?:sqlite3\.connect|psycopg2\.connect|mysql\.connector\.connect)\s*\([^)]+\)(?!.*\1\.close)",
                re.DOTALL,
            ),
            category=BugCategory.RESOURCE_LEAK,
            severity=BugSeverity.HIGH,
            description="Database connection opened without explicit close",
            explanation="Database connections should be closed to prevent resource exhaustion",
            fix_suggestion="Use context manager or ensure close() is called in finally block",
            languages=["python"],
        ),
        BugPattern(
            name="Socket Without Close",
            pattern=re.compile(
                r"socket\.socket\s*\([^)]*\)(?!.*\.close\(\))",
                re.DOTALL,
            ),
            category=BugCategory.RESOURCE_LEAK,
            severity=BugSeverity.MEDIUM,
            description="Socket created without close()",
            explanation="Sockets should be explicitly closed to free resources",
            fix_suggestion="Use context manager or call close() in finally block",
            languages=["python"],
        ),
        BugPattern(
            name="Thread/Process Without Join",
            pattern=re.compile(
                r"(\w+)\s*=\s*(?:threading\.Thread|multiprocessing\.Process)\s*\([^)]+\)\s*\n\s*\1\.start\s*\(\)(?!.*\1\.join)",
                re.DOTALL,
            ),
            category=BugCategory.RESOURCE_LEAK,
            severity=BugSeverity.LOW,
            description="Thread/Process started without join()",
            explanation="Threads should typically be joined to ensure completion",
            fix_suggestion="Call join() when thread completion is required",
            languages=["python"],
        ),
    ]

    # =====================================================================
    # RACE CONDITION PATTERNS
    # =====================================================================
    RACE_PATTERNS = [
        BugPattern(
            name="Global Variable in Thread",
            pattern=re.compile(
                r"def\s+\w+\s*\([^)]*\)[^:]*:[^\n]*\n(?:[^\n]*\n)*?\s+global\s+\w+",
                re.MULTILINE,
            ),
            category=BugCategory.RACE_CONDITION,
            severity=BugSeverity.MEDIUM,
            description="Global variable modified in function (potential thread safety issue)",
            explanation="Modifying global state without synchronization can cause race conditions",
            fix_suggestion="Use thread-local storage or explicit locking",
            languages=["python"],
        ),
        BugPattern(
            name="Check-Then-Act Pattern",
            pattern=re.compile(
                r"if\s+(?:os\.path\.exists|Path\([^)]+\)\.exists)\s*\([^)]+\)[^:]*:[^\n]*\n[^\n]*(?:open|write|remove|unlink)",
            ),
            category=BugCategory.RACE_CONDITION,
            severity=BugSeverity.MEDIUM,
            description="File existence check followed by file operation (TOCTOU)",
            explanation="Time-of-check to time-of-use race condition; file state may change between check and use",
            fix_suggestion="Use atomic operations or handle FileNotFoundError/FileExistsError",
            languages=["python"],
        ),
        BugPattern(
            name="Mutable Default Argument",
            pattern=re.compile(
                r"def\s+\w+\s*\([^)]*(?:\[\]|\{\}|list\(\)|dict\(\)|set\(\))\s*[,)]",
            ),
            category=BugCategory.RACE_CONDITION,
            severity=BugSeverity.HIGH,
            description="Mutable default argument in function definition",
            explanation="Mutable defaults are shared across calls, causing unexpected state sharing",
            fix_suggestion="Use None as default and create new object in function body",
            languages=["python"],
        ),
    ]

    # =====================================================================
    # OFF-BY-ONE PATTERNS
    # =====================================================================
    OFF_BY_ONE_PATTERNS = [
        BugPattern(
            name="Range Fence Post Error",
            pattern=re.compile(
                r"for\s+\w+\s+in\s+range\s*\(\s*len\s*\(\s*\w+\s*\)\s*\+\s*1\s*\)",
            ),
            category=BugCategory.OFF_BY_ONE,
            severity=BugSeverity.MEDIUM,
            description="range(len(x) + 1) may cause IndexError",
            explanation="Adding 1 to len() in range often indicates off-by-one error",
            fix_suggestion="Verify loop bounds; usually range(len(x)) is correct",
            languages=["python"],
        ),
        BugPattern(
            name="Array Access After Length",
            pattern=re.compile(
                r"\[\s*len\s*\(\s*\w+\s*\)\s*\]",
            ),
            category=BugCategory.OFF_BY_ONE,
            severity=BugSeverity.HIGH,
            description="Accessing array at index len(array)",
            explanation="Array indices go from 0 to len-1; accessing len causes IndexError",
            fix_suggestion="Use len(array) - 1 for last element, or array[-1]",
            languages=["python"],
        ),
        BugPattern(
            name="Inclusive Range Error",
            pattern=re.compile(
                r"for\s*\(\s*(?:let|var|const)?\s*\w+\s*=\s*0\s*;\s*\w+\s*<=\s*\w+\.length\s*;",
            ),
            category=BugCategory.OFF_BY_ONE,
            severity=BugSeverity.HIGH,
            description="Loop condition uses <= length (should be <)",
            explanation="Using <= with length causes out-of-bounds access",
            fix_suggestion="Change <= to < for array iteration",
            languages=["javascript", "typescript"],
        ),
    ]

    # =====================================================================
    # TYPE ERROR PATTERNS
    # =====================================================================
    TYPE_PATTERNS = [
        BugPattern(
            name="String/Number Confusion",
            pattern=re.compile(
                r"['\"][0-9]+['\"]\s*[<>=!]+\s*[0-9]+(?!\s*['\"])",
            ),
            category=BugCategory.TYPE_ERROR,
            severity=BugSeverity.MEDIUM,
            description="Comparing string to number",
            explanation="String comparison with number may give unexpected results",
            fix_suggestion="Ensure consistent types in comparison",
            languages=["python", "javascript"],
        ),
        BugPattern(
            name="Boolean Trap",
            pattern=re.compile(
                r"def\s+\w+\s*\([^)]*,\s*\w+\s*:\s*bool\s*=\s*(?:True|False)\s*,\s*\w+\s*:\s*bool\s*=",
            ),
            category=BugCategory.TYPE_ERROR,
            severity=BugSeverity.LOW,
            description="Multiple consecutive boolean parameters",
            explanation="Multiple boolean args make call sites confusing (foo(True, False, True))",
            fix_suggestion="Consider using enum or dataclass for configuration",
            languages=["python"],
        ),
        BugPattern(
            name="Implicit String Concatenation",
            pattern=re.compile(
                r"\(\s*['\"][^'\"]*['\"]\s+['\"][^'\"]*['\"]\s*\)",
            ),
            category=BugCategory.TYPE_ERROR,
            severity=BugSeverity.LOW,
            description="Implicit string concatenation (missing comma?)",
            explanation="Adjacent strings are concatenated, which may be unintentional",
            fix_suggestion="Add comma if tuple was intended, or use explicit + for concatenation",
            languages=["python"],
        ),
    ]

    # =====================================================================
    # EXCEPTION HANDLING PATTERNS
    # =====================================================================
    EXCEPTION_PATTERNS = [
        BugPattern(
            name="Bare Except",
            pattern=re.compile(
                r"except\s*:",
                re.MULTILINE,
            ),
            category=BugCategory.EXCEPTION_HANDLING,
            severity=BugSeverity.MEDIUM,
            description="Bare except clause catches all exceptions",
            explanation="Catches SystemExit, KeyboardInterrupt, and GeneratorExit unexpectedly",
            fix_suggestion="Use specific exception types instead of a catch-all handler",
            languages=["python"],
        ),
        BugPattern(
            name="Exception Swallowed",
            pattern=re.compile(
                r"except[^:]*:\s*\n\s*pass\s*$",
                re.MULTILINE,
            ),
            category=BugCategory.EXCEPTION_HANDLING,
            severity=BugSeverity.HIGH,
            description="Exception caught and silently ignored",
            explanation="Swallowing exceptions hides bugs and makes debugging difficult",
            fix_suggestion="At minimum, log the exception; better to handle or re-raise",
            languages=["python"],
        ),
        BugPattern(
            name="Catch and Ignore (JS)",
            pattern=re.compile(
                r"catch\s*\(\s*\w*\s*\)\s*\{\s*\}",
            ),
            category=BugCategory.EXCEPTION_HANDLING,
            severity=BugSeverity.HIGH,
            description="Exception caught with empty handler",
            explanation="Empty catch blocks hide errors",
            fix_suggestion="Log the error or handle it appropriately",
            languages=["javascript", "typescript"],
        ),
        BugPattern(
            name="Exception in Finally",
            pattern=re.compile(
                r"finally\s*:[^\n]*\n(?:[^\n]*\n)*?\s+raise\s+",
            ),
            category=BugCategory.EXCEPTION_HANDLING,
            severity=BugSeverity.MEDIUM,
            description="Exception raised in finally block",
            explanation="Raising in finally can mask the original exception",
            fix_suggestion="Avoid raising new exceptions in finally blocks",
            languages=["python"],
        ),
        BugPattern(
            name="Return in Finally",
            pattern=re.compile(
                r"finally\s*:[^\n]*\n(?:[^\n]*\n)*?\s+return\s+",
            ),
            category=BugCategory.EXCEPTION_HANDLING,
            severity=BugSeverity.MEDIUM,
            description="Return statement in finally block",
            explanation="Return in finally silences any exception that was being propagated",
            fix_suggestion="Avoid return in finally; use return after try-except",
            languages=["python"],
        ),
    ]

    # =====================================================================
    # INFINITE LOOP PATTERNS
    # =====================================================================
    LOOP_PATTERNS = [
        BugPattern(
            name="While True Without Break",
            pattern=re.compile(
                r"while\s+True\s*:[^\n]*\n(?:(?!\s*break|\s*return|\s*raise|\s*yield)[^\n]*\n){20,}",
            ),
            category=BugCategory.INFINITE_LOOP,
            severity=BugSeverity.LOW,
            description="while True loop with no obvious exit",
            explanation="Long while True loop without visible break may be infinite",
            fix_suggestion="Ensure there's a clear exit condition",
            languages=["python"],
        ),
        BugPattern(
            name="Unmodified Loop Variable",
            pattern=re.compile(
                r"while\s+(\w+)\s*[<>!=]+[^:]+:[^\n]*\n(?:(?!\1\s*[+\-*/%]?=)[^\n]*\n){5,}",
            ),
            category=BugCategory.INFINITE_LOOP,
            severity=BugSeverity.MEDIUM,
            description="Loop variable not modified in loop body",
            explanation="If the condition variable isn't updated, loop may be infinite",
            fix_suggestion="Ensure loop variable is modified within the loop",
            languages=["python"],
        ),
        BugPattern(
            name="Iterator Not Advanced",
            pattern=re.compile(
                r"while\s+\w+\.hasNext\s*\(\s*\)\s*:[^\n]*\n(?:(?!\.next\s*\(\s*\))[^\n]*\n){3,}",
            ),
            category=BugCategory.INFINITE_LOOP,
            severity=BugSeverity.HIGH,
            description="Iterator hasNext() checked but next() not called",
            explanation="Iterator must be advanced or loop will be infinite",
            fix_suggestion="Call next() to advance the iterator",
            languages=["python", "java"],
        ),
    ]

    # =====================================================================
    # INTEGER OVERFLOW PATTERNS
    # =====================================================================
    OVERFLOW_PATTERNS = [
        BugPattern(
            name="Unchecked Integer Multiplication",
            pattern=re.compile(
                r"(?:int|size_t|uint)\s+\w+\s*=\s*\w+\s*\*\s*\w+\s*;",
            ),
            category=BugCategory.INTEGER_OVERFLOW,
            severity=BugSeverity.MEDIUM,
            description="Integer multiplication without overflow check",
            explanation="Multiplying large integers can overflow",
            fix_suggestion="Check for overflow before multiplication or use safe math",
            languages=["c", "cpp", "java"],
        ),
        BugPattern(
            name="Array Size from User Input",
            pattern=re.compile(
                r"(?:malloc|calloc|new)\s*\([^)]*(?:atoi|strtol|parseInt|int\()[^)]*\)",
            ),
            category=BugCategory.INTEGER_OVERFLOW,
            severity=BugSeverity.HIGH,
            description="Array/buffer size derived from user input",
            explanation="User-controlled size can cause integer overflow or huge allocations",
            fix_suggestion="Validate size bounds before allocation",
            languages=["c", "cpp"],
        ),
    ]

    # =====================================================================
    # LOGIC ERROR PATTERNS
    # =====================================================================
    LOGIC_PATTERNS = [
        BugPattern(
            name="Comparison to Self",
            pattern=re.compile(
                r"(\w+)\s*(?:==|!=|<|>|<=|>=)\s*\1(?!\[)",
            ),
            category=BugCategory.LOGIC_ERROR,
            severity=BugSeverity.MEDIUM,
            description="Variable compared to itself",
            explanation="Comparing a variable to itself is usually a typo",
            fix_suggestion="Check if different variables should be compared",
        ),
        BugPattern(
            name="Assignment in Condition",
            pattern=re.compile(
                r"if\s*\(\s*\w+\s*=\s*[^=]",
            ),
            category=BugCategory.LOGIC_ERROR,
            severity=BugSeverity.MEDIUM,
            description="Assignment in if condition (likely meant ==)",
            explanation="Single = in condition assigns rather than compares",
            fix_suggestion="Use == for comparison, or clarify intent with extra parentheses",
            languages=["javascript", "c", "cpp", "java"],
        ),
        BugPattern(
            name="Unreachable Code After Return",
            pattern=re.compile(
                r"^\s+return\s+[^\n]+\n\s+(?!except|finally|elif|else)[a-zA-Z]",
                re.MULTILINE,
            ),
            category=BugCategory.LOGIC_ERROR,
            severity=BugSeverity.LOW,
            description="Code after return statement (unreachable)",
            explanation="Code after return will never execute",
            fix_suggestion="Remove unreachable code or fix control flow",
            languages=["python"],
        ),
        BugPattern(
            name="Constant Condition",
            pattern=re.compile(
                r"if\s+(?:True|False|0|1)\s*:",
            ),
            category=BugCategory.LOGIC_ERROR,
            severity=BugSeverity.LOW,
            description="Condition is constant (always true/false)",
            explanation="Constant condition indicates dead code or debugging remnant",
            fix_suggestion="Remove condition or replace with actual check",
            languages=["python"],
        ),
        BugPattern(
            name="Duplicate Dictionary Key",
            pattern=re.compile(
                r"\{[^}]*['\"](\w+)['\"]\s*:[^}]*['\"](\1)['\"]\s*:",
            ),
            category=BugCategory.LOGIC_ERROR,
            severity=BugSeverity.HIGH,
            description="Duplicate key in dictionary literal",
            explanation="Later value overwrites earlier one; probably a typo",
            fix_suggestion="Remove duplicate key or rename",
            languages=["python", "javascript"],
        ),
        BugPattern(
            name="Double Negation",
            pattern=re.compile(
                r"not\s+not\s+",
            ),
            category=BugCategory.LOGIC_ERROR,
            severity=BugSeverity.LOW,
            description="Double negation (not not x)",
            explanation="Double negation is confusing; use bool() if casting",
            fix_suggestion="Use bool(x) instead of not not x",
            languages=["python"],
        ),
    ]

    # =====================================================================
    # API MISUSE PATTERNS
    # =====================================================================
    API_PATTERNS = [
        BugPattern(
            name="String Format Without Arguments",
            pattern=re.compile(
                r'["\'][^"\']*\{[^}]*\}[^"\']*["\'](?!\s*\.format)',
            ),
            category=BugCategory.API_MISUSE,
            severity=BugSeverity.LOW,
            description="Format string without .format() call",
            explanation="String has {} placeholders but .format() not called",
            fix_suggestion="Add .format() or use f-string",
            languages=["python"],
            false_positive_hints=["{{", "}}"],
        ),
        BugPattern(
            name="async Function Without Await",
            pattern=re.compile(
                r"async\s+def\s+\w+\s*\([^)]*\)[^:]*:\s*\n(?:(?!\s*await)[^\n]*\n){10,}(?=\n\s*(?:async\s+)?def|\Z)",
            ),
            category=BugCategory.API_MISUSE,
            severity=BugSeverity.LOW,
            description="async function with no await statements",
            explanation="async function that never awaits could just be regular function",
            fix_suggestion="Add await or remove async keyword",
            languages=["python"],
        ),
        BugPattern(
            name="Missing Await",
            pattern=re.compile(
                r"(?<!await\s)(?:async_\w+|fetch|asyncio\.\w+)\s*\([^)]*\)(?!\s*\.then)",
            ),
            category=BugCategory.API_MISUSE,
            severity=BugSeverity.HIGH,
            description="Async call without await (returns coroutine/promise)",
            explanation="Forgetting await means the async operation result is lost",
            fix_suggestion="Add await before async function calls",
            languages=["python", "javascript"],
        ),
        BugPattern(
            name="re.match vs re.search Confusion",
            pattern=re.compile(
                r"re\.match\s*\([^)]*\$[^)]*\)",
            ),
            category=BugCategory.API_MISUSE,
            severity=BugSeverity.MEDIUM,
            description="re.match with $ anchor (may not work as expected)",
            explanation="re.match only matches at start; $ at end won't match full string",
            fix_suggestion="Use re.fullmatch() for full string matching, or re.search()",
            languages=["python"],
        ),
    ]

    # =====================================================================
    # CODE SMELL PATTERNS
    # =====================================================================
    SMELL_PATTERNS = [
        BugPattern(
            name="Magic Number",
            pattern=re.compile(
                r"(?:if|while|for|==|!=|<|>|<=|>=)\s+[0-9]{2,}(?!\s*[,\]])",
            ),
            category=BugCategory.CODE_SMELL,
            severity=BugSeverity.INFO,
            description="Magic number in comparison",
            explanation="Unexplained numeric literals make code hard to understand",
            fix_suggestion="Extract to named constant",
        ),
        BugPattern(
            name="Too Many Arguments",
            pattern=re.compile(
                r"def\s+\w+\s*\(\s*(?:\w+\s*[,:][^)]*){7,}\)",
            ),
            category=BugCategory.CODE_SMELL,
            severity=BugSeverity.LOW,
            description="Function with many parameters",
            explanation="Functions with >6 parameters are hard to use correctly",
            fix_suggestion="Group related parameters into dataclass or dict",
            languages=["python"],
        ),
        BugPattern(
            name="Deeply Nested Code",
            pattern=re.compile(
                r"^(?:\s{4}|\t){5,}(?:if|for|while|try)",
                re.MULTILINE,
            ),
            category=BugCategory.CODE_SMELL,
            severity=BugSeverity.LOW,
            description="Deeply nested control structure",
            explanation="Deep nesting makes code hard to follow",
            fix_suggestion="Extract nested logic into separate functions",
        ),
        BugPattern(
            name="Long Method",
            pattern=re.compile(
                r"def\s+\w+\s*\([^)]*\)[^:]*:\s*\n(?:[^\n]*\n){100,}(?=\n\s*(?:async\s+)?def|\n\s*class|\Z)",
            ),
            category=BugCategory.CODE_SMELL,
            severity=BugSeverity.LOW,
            description="Very long method (>100 lines)",
            explanation="Long methods are hard to understand and test",
            fix_suggestion="Break into smaller, focused methods",
            languages=["python"],
        ),
    ]

    def __init__(
        self,
        include_low_severity: bool = True,
        include_info: bool = False,
        include_smells: bool = True,
        custom_patterns: list[BugPattern] | None = None,
    ):
        """
        Initialize the bug detector.

        Args:
            include_low_severity: Include LOW severity findings
            include_info: Include INFO severity findings
            include_smells: Include code smell patterns
            custom_patterns: Additional patterns to check
        """
        self.include_low_severity = include_low_severity
        self.include_info = include_info

        # Combine patterns
        self.patterns: list[BugPattern] = []
        self.patterns.extend(self.NULL_PATTERNS)
        self.patterns.extend(self.RESOURCE_PATTERNS)
        self.patterns.extend(self.RACE_PATTERNS)
        self.patterns.extend(self.OFF_BY_ONE_PATTERNS)
        self.patterns.extend(self.TYPE_PATTERNS)
        self.patterns.extend(self.EXCEPTION_PATTERNS)
        self.patterns.extend(self.LOOP_PATTERNS)
        self.patterns.extend(self.OVERFLOW_PATTERNS)
        self.patterns.extend(self.LOGIC_PATTERNS)
        self.patterns.extend(self.API_PATTERNS)

        if include_smells:
            self.patterns.extend(self.SMELL_PATTERNS)

        if custom_patterns:
            self.patterns.extend(custom_patterns)

        self._finding_counter = 0

    def detect_in_file(self, file_path: str) -> list[PotentialBug]:
        """
        Detect potential bugs in a single file.

        Args:
            file_path: Path to the file to analyze

        Returns:
            List of potential bugs
        """
        bugs: list[PotentialBug] = []

        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
                lines = content.split("\n")
        except OSError as e:
            logger.warning("Failed to read %s: %s", file_path, e)
            return bugs

        # Detect language
        ext = Path(file_path).suffix.lower()
        language = self._extension_to_language(ext)

        for pattern in self.patterns:
            # Filter by language
            if pattern.languages and language not in pattern.languages:
                continue

            # Filter by severity
            if pattern.severity == BugSeverity.LOW and not self.include_low_severity:
                continue
            if pattern.severity == BugSeverity.INFO and not self.include_info:
                continue

            # Find matches
            for match in pattern.pattern.finditer(content):
                # Check false positive hints
                match_text = match.group()
                is_false_positive = False
                for hint in pattern.false_positive_hints:
                    if hint.lower() in match_text.lower():
                        is_false_positive = True
                        break

                # Calculate line number
                line_num = content[: match.start()].count("\n") + 1

                # Get code snippet
                snippet_start = max(0, line_num - 2)
                snippet_end = min(len(lines), line_num + 3)
                snippet = "\n".join(lines[snippet_start:snippet_end])

                self._finding_counter += 1
                bug = PotentialBug(
                    id=f"BUG-{self._finding_counter:06d}",
                    title=pattern.name,
                    description=pattern.description,
                    category=pattern.category,
                    severity=pattern.severity,
                    confidence=0.85 if not is_false_positive else 0.4,
                    file_path=file_path,
                    line_number=line_num,
                    column=match.start() - content.rfind("\n", 0, match.start()) - 1,
                    code_snippet=snippet[:500],
                    pattern_name=pattern.name,
                    explanation=pattern.explanation,
                    fix_suggestion=pattern.fix_suggestion,
                    is_false_positive=is_false_positive,
                )
                bugs.append(bug)

        return bugs

    def detect_in_directory(
        self,
        directory: str,
        exclude_patterns: list[str] | None = None,
        extensions: list[str] | None = None,
    ) -> BugReport:
        """
        Detect potential bugs in a directory.

        Args:
            directory: Root directory to analyze
            exclude_patterns: Glob patterns to exclude
            extensions: File extensions to analyze

        Returns:
            Complete bug detection report
        """
        start_time = datetime.now(timezone.utc)
        scan_id = f"bug_scan_{start_time.strftime('%Y%m%d_%H%M%S')}"

        logger.info("[%s] Starting bug detection in %s", scan_id, directory)

        report = BugReport(
            scan_id=scan_id,
            repository=directory,
            started_at=start_time,
        )

        # Default extensions
        if extensions is None:
            extensions = [".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".c", ".cpp"]

        # Default excludes
        if exclude_patterns is None:
            exclude_patterns = [
                "__pycache__",
                ".git",
                "node_modules",
                ".venv",
                "venv",
                "dist",
                "build",
                "test",
                "tests",
            ]

        # Collect files
        root = Path(directory)
        files_to_scan: list[Path] = []

        for ext in extensions:
            for file_path in root.rglob(f"*{ext}"):
                excluded = False
                for pattern in exclude_patterns:
                    if pattern in str(file_path):
                        excluded = True
                        break
                if not excluded:
                    files_to_scan.append(file_path)

        logger.info("[%s] Found %s files to analyze", scan_id, len(files_to_scan))

        # Analyze files
        total_lines = 0
        for file_path in files_to_scan:
            try:
                with open(file_path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                    total_lines += content.count("\n") + 1

                bugs = self.detect_in_file(str(file_path))
                report.bugs.extend(bugs)
                report.files_scanned += 1

            except (ValueError, OSError) as e:
                logger.warning("[%s] Error analyzing %s: %s", scan_id, file_path, e)

        report.lines_scanned = total_lines
        report.completed_at = datetime.now(timezone.utc)
        report.calculate_summary()

        elapsed = (report.completed_at - start_time).total_seconds()
        logger.info(
            "[%s] Completed in %.2fs: %s potential bugs found", scan_id, elapsed, report.total_bugs
        )

        return report

    def _extension_to_language(self, ext: str) -> str | None:
        """Map file extension to language name."""
        mapping = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".java": "java",
            ".go": "go",
            ".c": "c",
            ".cpp": "cpp",
            ".rs": "rust",
        }
        return mapping.get(ext)


def quick_bug_scan(
    path: str,
    include_smells: bool = False,
) -> dict[str, Any]:
    """
    Quick bug scan of a file or directory.

    Args:
        path: File or directory path
        include_smells: Include code smell patterns

    Returns:
        Dictionary with scan results
    """
    detector = BugDetector(
        include_low_severity=True,
        include_info=False,
        include_smells=include_smells,
    )

    path_obj = Path(path)
    if path_obj.is_file():
        bugs = detector.detect_in_file(str(path))
        return {
            "path": path,
            "bugs_found": len(bugs),
            "critical": sum(1 for b in bugs if b.severity == BugSeverity.CRITICAL),
            "high": sum(1 for b in bugs if b.severity == BugSeverity.HIGH),
            "details": [b.to_dict() for b in bugs[:20]],
        }
    else:
        report = detector.detect_in_directory(str(path))
        return report.to_dict()
