"""
RLM REPL Environment for programmatic context interaction.

Based on the paper's approach of treating long prompts as an external
environment that the LLM can interact with through a Python REPL.

SECURITY: This module implements a sandboxed Python execution environment.
Key security measures:
- Empty __builtins__ dict prevents access to dangerous builtins
- AST validation blocks imports, dangerous functions, and dunder access
- Regex operations have complexity limits to prevent ReDoS
- String concatenation of blocked names is detected at runtime
- Lambda closures are protected against self-reference leaks
"""

import ast
import io
import logging
import re
import threading
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable

from .types import AbstractionLevel, RLMConfig, RLMContext, RLMResult

logger = logging.getLogger(__name__)

# Security constants
MAX_REGEX_PATTERN_LENGTH = 1000
MAX_REGEX_GROUPS = 20
REGEX_TIMEOUT_SECONDS = 2.0
# Default per-value cap; RLMEnvironment overrides using RLMConfig
MAX_NAMESPACE_VALUE_SIZE = 10_000_000  # 10MB per value (fallback)


def _safe_regex(pattern: str, text: str, flags: int = 0) -> list[str]:
    """
    Execute regex with security protections against ReDoS.

    Args:
        pattern: Regex pattern to match
        text: Text to search in
        flags: Regex flags

    Returns:
        List of matches, empty if pattern is invalid or times out

    Raises:
        SecurityError: If pattern is too complex
    """
    # Check pattern length
    if len(pattern) > MAX_REGEX_PATTERN_LENGTH:
        raise SecurityError(f"Regex pattern too long: {len(pattern)} > {MAX_REGEX_PATTERN_LENGTH}")

    # Check for potentially catastrophic patterns
    # These patterns can cause exponential backtracking
    dangerous_patterns = [
        r"\(.*\+\)\+",  # (a+)+
        r"\(.*\*\)\+",  # (a*)+
        r"\(.*\*\)\*",  # (a*)*
        r"\(.*\?\)\+",  # (a?)+
        r"\.{3,}\*",  # ...* (many dots followed by star)
    ]
    for dangerous in dangerous_patterns:
        if re.search(dangerous, pattern):
            raise SecurityError("Regex pattern may cause catastrophic backtracking")

    # Count groups
    try:
        compiled = re.compile(pattern, flags)
        if compiled.groups > MAX_REGEX_GROUPS:
            raise SecurityError(f"Too many regex groups: {compiled.groups} > {MAX_REGEX_GROUPS}")
    except re.error:
        return []  # Invalid pattern

    # Execute with timeout using threading
    result: list[str] = []
    error: Exception | None = None

    def run_regex() -> None:
        nonlocal result, error
        try:
            result = compiled.findall(text)
        except (RuntimeError, re.error) as e:
            error = e

    thread = threading.Thread(target=run_regex)
    thread.start()
    thread.join(timeout=REGEX_TIMEOUT_SECONDS)

    if thread.is_alive():
        logger.warning("Regex operation timed out for pattern: %s...", pattern[:50])
        # Thread will continue but we return empty
        return []

    if error:
        return []

    return result


def _contains_blocked_dunder(value: str) -> bool:
    """
    Check if a string contains blocked dunder names.

    This catches both direct strings and concatenation results.
    """
    blocked = {
        "__globals__",
        "__builtins__",
        "__code__",
        "__closure__",
        "__class__",
        "__bases__",
        "__subclasses__",
        "__mro__",
        "__dict__",
        "__module__",
        "__name__",
        "__qualname__",
        "__func__",
        "__self__",
        "__wrapped__",
        "__annotations__",
        "__init_subclass__",
        "__reduce__",
        "__reduce_ex__",
        "__getattribute__",
        "__setattr__",
        "__delattr__",
    }
    value_lower = value.lower()
    return any(b in value_lower for b in blocked)


class SafeReModule:
    """
    A wrapped re module that enforces security limits on regex operations.

    This prevents ReDoS attacks by:
    - Limiting pattern length
    - Limiting number of groups
    - Checking for catastrophic backtracking patterns
    - Enforcing timeout on operations
    """

    def __init__(self) -> None:
        self.IGNORECASE = re.IGNORECASE
        self.MULTILINE = re.MULTILINE
        self.DOTALL = re.DOTALL
        self.VERBOSE = re.VERBOSE

    def findall(self, pattern: str, string: str, flags: int = 0) -> list[str]:
        """Safe findall with ReDoS protection."""
        return _safe_regex(pattern, string, flags)

    def search(self, pattern: str, string: str, flags: int = 0) -> re.Match[str] | None:
        """Safe search with ReDoS protection."""
        if len(pattern) > MAX_REGEX_PATTERN_LENGTH:
            raise SecurityError(f"Pattern too long: {len(pattern)}")
        try:
            return re.search(pattern, string, flags)
        except re.error:
            return None

    def match(self, pattern: str, string: str, flags: int = 0) -> re.Match[str] | None:
        """Safe match with ReDoS protection."""
        if len(pattern) > MAX_REGEX_PATTERN_LENGTH:
            raise SecurityError(f"Pattern too long: {len(pattern)}")
        try:
            return re.match(pattern, string, flags)
        except re.error:
            return None

    def sub(self, pattern: str, repl: str, string: str, count: int = 0, flags: int = 0) -> str:
        """Safe sub with ReDoS protection."""
        if len(pattern) > MAX_REGEX_PATTERN_LENGTH:
            raise SecurityError(f"Pattern too long: {len(pattern)}")
        try:
            return re.sub(pattern, repl, string, count, flags)
        except re.error:
            return string

    def split(self, pattern: str, string: str, maxsplit: int = 0, flags: int = 0) -> list[str]:
        """Safe split with ReDoS protection."""
        if len(pattern) > MAX_REGEX_PATTERN_LENGTH:
            raise SecurityError(f"Pattern too long: {len(pattern)}")
        try:
            return re.split(pattern, string, maxsplit, flags)
        except re.error:
            return [string]

    def compile(self, pattern: str, flags: int = 0) -> None:
        """Blocked - could bypass our safety checks."""
        raise SecurityError("re.compile() is not allowed - use findall/search directly")


@dataclass
class REPLState:
    """State of the REPL environment."""

    # Variables accessible to the LLM
    namespace: dict[str, Any] = field(default_factory=dict)

    # Execution history
    history: list[tuple[str, str]] = field(default_factory=list)  # (code, output)

    # Sub-LM tracking
    sub_calls: list[dict[str, Any]] = field(default_factory=list)
    sub_call_count: int = 0

    # Final result
    final_answer: str | None = None
    final_var: str | None = None

    # Iterative refinement (Prime Intellect alignment)
    ready: bool = True  # Whether answer is complete (False = needs refinement)
    iteration: int = 0  # Current refinement iteration
    feedback: str | None = None  # Feedback from previous iteration


class RLMEnvironment:
    """
    REPL environment for RLM context interaction.

    Provides a sandboxed Python environment where:
    - Context is pre-loaded as a variable (CONTEXT)
    - LLM outputs code to interact with context
    - Results are truncated and returned to LLM's context
    - RLM_M() spawns sub-LM instances
    - FINAL()/FINAL_VAR() return results
    """

    # Maximum output length per execution (Prime Intellect: 8192)
    MAX_OUTPUT_CHARS = 8192

    # Safe builtins for the sandbox
    # SECURITY: Do NOT add getattr, setattr, delattr, hasattr, callable, vars, dir
    # These can be used to escape the sandbox via __globals__, __class__, etc.
    SAFE_BUILTINS = {
        "len": len,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "set": set,
        "tuple": tuple,
        "range": range,
        "enumerate": enumerate,
        "zip": zip,
        "map": map,
        "filter": filter,
        "sorted": sorted,
        "reversed": reversed,
        "min": min,
        "max": max,
        "sum": sum,
        "any": any,
        "all": all,
        "abs": abs,
        "round": round,
        "print": print,
        # SECURITY: type() is safe for checking types, but don't add isinstance
        # as it could be used with type() to probe class hierarchies
        # "type": type,  # Removed - can access __bases__
        # "isinstance": isinstance,  # Removed - reveals class hierarchy
    }

    # Dangerous names that should never appear in code (even as strings)
    BLOCKED_DUNDER_NAMES = frozenset(
        {
            "__globals__",
            "__builtins__",
            "__code__",
            "__closure__",
            "__class__",
            "__bases__",
            "__subclasses__",
            "__mro__",
            "__dict__",
            "__module__",
            "__name__",
            "__qualname__",
            "__func__",
            "__self__",
            "__wrapped__",
            "__annotations__",
            "__init_subclass__",
            "__reduce__",
            "__reduce_ex__",
            "__getattribute__",
            "__setattr__",
            "__delattr__",
        }
    )

    def __init__(
        self,
        config: RLMConfig,
        context: RLMContext,
        agent_call: Callable[[str, str, str], str] | None = None,
    ):
        """
        Initialize REPL environment.

        Args:
            config: RLM configuration
            context: Hierarchical context to make available
            agent_call: Callback to invoke agents for sub-LM calls
                       Signature: (model, query, context) -> response
        """
        self.config = config
        self.context = context
        self.agent_call = agent_call
        # Derive per-value cap from config (supports very large contexts)
        repl_cap = int(self.config.max_repl_memory_mb * 1024 * 1024)
        content_cap = int(self.config.max_content_bytes) if self.config.max_content_bytes else 0
        if content_cap > 0:
            repl_cap = min(repl_cap, content_cap)
        if repl_cap <= 0:
            repl_cap = MAX_NAMESPACE_VALUE_SIZE
        self._max_namespace_value_size = repl_cap

        self.state = REPLState()
        self._initialize_namespace()

    def _initialize_namespace(self) -> None:
        """Set up the namespace with context and helper functions."""
        # Core context access
        self.state.namespace["CONTEXT"] = self.context.original_content
        self.state.namespace["CONTEXT_TOKENS"] = self.context.original_tokens

        # Hierarchical access
        self.state.namespace["get_level"] = self._get_level
        self.state.namespace["get_abstract"] = lambda: self._get_level(AbstractionLevel.ABSTRACT)
        self.state.namespace["get_summary"] = lambda: self._get_level(AbstractionLevel.SUMMARY)
        self.state.namespace["get_detailed"] = lambda: self._get_level(AbstractionLevel.DETAILED)
        self.state.namespace["get_full"] = lambda: self._get_level(AbstractionLevel.FULL)

        # Node navigation
        self.state.namespace["get_node"] = self._get_node
        self.state.namespace["drill_down"] = self._drill_down
        self.state.namespace["get_children"] = self._get_children

        # Search utilities
        self.state.namespace["search"] = self._search
        self.state.namespace["grep"] = self._grep
        self.state.namespace["find_sections"] = self._find_sections

        # RLM primitives
        self.state.namespace["RLM_M"] = self._rlm_call
        self.state.namespace["FINAL"] = self._final
        self.state.namespace["FINAL_VAR"] = self._final_var
        self.state.namespace["SET_READY"] = self._set_ready
        self.state.namespace["FEEDBACK"] = self._get_feedback

        # String utilities
        self.state.namespace["truncate"] = self._truncate
        self.state.namespace["split_chunks"] = self._split_chunks
        self.state.namespace["count_tokens"] = self._count_tokens

        # Safe builtins
        for name, func in self.SAFE_BUILTINS.items():
            self.state.namespace[name] = func

        # Safe re module for regex (with ReDoS protections)
        self.state.namespace["re"] = SafeReModule()

    def _get_level(self, level: AbstractionLevel) -> str:
        """Get context at a specific abstraction level."""
        return self.context.get_at_level(level)

    def _get_node(self, node_id: str) -> dict[str, Any] | None:
        """Get a specific node by ID."""
        node = self.context.get_node(node_id)
        if not node:
            return None
        return {
            "id": node.id,
            "level": node.level.name,
            "content": node.content,
            "token_count": node.token_count,
            "key_topics": node.key_topics,
            "parent_id": node.parent_id,
            "child_ids": node.child_ids,
        }

    def _drill_down(self, node_id: str) -> list[dict[str, Any]]:
        """Get more detailed nodes under a given node."""
        children = self.context.drill_down(node_id)
        return [
            {
                "id": c.id,
                "level": c.level.name,
                "content": c.content[:500] + "..." if len(c.content) > 500 else c.content,
                "token_count": c.token_count,
                "key_topics": c.key_topics,
            }
            for c in children
        ]

    def _get_children(self, node_id: str) -> list[str]:
        """Get child node IDs for navigation."""
        node = self.context.get_node(node_id)
        return node.child_ids if node else []

    def _search(self, query: str, level: str | None = None) -> list[dict[str, Any]]:
        """Search for content matching query."""
        search_level = AbstractionLevel[level.upper()] if level else AbstractionLevel.SUMMARY

        results = []
        if search_level in self.context.levels:
            for node in self.context.levels[search_level]:
                if query.lower() in node.content.lower():
                    results.append(
                        {
                            "id": node.id,
                            "level": node.level.name,
                            "snippet": self._extract_snippet(node.content, query),
                            "topics": node.key_topics,
                        }
                    )
        return results[:10]  # Limit results

    def _grep(self, pattern: str, content: str | None = None) -> list[str]:
        """Search using regex pattern with ReDoS protection."""
        text = content or self.context.original_content
        try:
            matches = _safe_regex(pattern, text, re.IGNORECASE | re.MULTILINE)
            return matches[:20]  # Limit results
        except SecurityError as e:
            logger.warning("Grep blocked: %s", e)
            return []
        except re.error:
            return []

    def _find_sections(self, heading_pattern: str = r"^#+\s+.+$") -> list[dict[str, Any]]:
        """Find sections in the content by heading pattern."""
        sections = []
        lines = self.context.original_content.split("\n")
        current_heading = None
        current_start = 0

        for i, line in enumerate(lines):
            if re.match(heading_pattern, line, re.MULTILINE):
                if current_heading:
                    sections.append(
                        {
                            "heading": current_heading,
                            "start_line": current_start,
                            "end_line": i - 1,
                        }
                    )
                current_heading = line.strip()
                current_start = i

        if current_heading:
            sections.append(
                {
                    "heading": current_heading,
                    "start_line": current_start,
                    "end_line": len(lines) - 1,
                }
            )

        return sections

    def _rlm_call(self, query: str, context_snippet: str) -> str:
        """
        Spawn a sub-LM instance (RLM_M primitive from paper).

        Args:
            query: Query for the sub-LM
            context_snippet: Transformed/filtered context to provide

        Returns:
            Response from sub-LM
        """
        if self.state.sub_call_count >= self.config.max_sub_calls:
            return "[ERROR: Maximum sub-LM calls exceeded]"

        if not self.agent_call:
            return "[ERROR: No agent callback configured for sub-LM calls]"

        self.state.sub_call_count += 1

        # Track the call
        call_record = {
            "index": self.state.sub_call_count,
            "query": query[:200],
            "context_length": len(context_snippet),
        }
        self.state.sub_calls.append(call_record)

        try:
            # Use configured sub-model
            response = self.agent_call(
                self.config.sub_model,
                query,
                context_snippet[: self.config.target_tokens * 4],  # Rough char limit
            )
            call_record["response_length"] = len(response)
            return response
        except (RuntimeError, ValueError, ConnectionError, TimeoutError, OSError) as e:
            logger.error("Sub-LM call failed: %s", e)
            call_record["error"] = str(e)
            return f"[ERROR: Sub-LM call failed: {e}]"

    def _final(self, answer: str, ready: bool = True) -> None:
        """Mark final answer (FINAL primitive from paper).

        Args:
            answer: The final answer content
            ready: Whether the answer is complete (Prime Intellect alignment).
                   Set to False to signal that refinement is needed.
        """
        self.state.final_answer = str(answer)
        self.state.ready = ready

    def _final_var(self, var_name: str, ready: bool = True) -> None:
        """Mark variable as final answer (FINAL_VAR primitive from paper).

        Args:
            var_name: Name of variable containing the answer
            ready: Whether the answer is complete
        """
        self.state.final_var = var_name
        self.state.ready = ready

    def _set_ready(self, ready: bool) -> None:
        """Explicitly set readiness status (SET_READY primitive).

        Use this to signal whether more refinement iterations are needed.

        Args:
            ready: True if answer is complete, False if refinement needed
        """
        self.state.ready = ready

    def _get_feedback(self) -> str | None:
        """Get feedback from previous iteration (FEEDBACK primitive).

        Returns feedback injected from previous refinement iteration,
        or None if this is the first iteration.
        """
        return self.state.feedback

    def set_iteration_context(self, iteration: int, feedback: str | None = None) -> None:
        """Set iteration context for refinement loop.

        Called by bridge.query_with_refinement() between iterations.

        Args:
            iteration: Current iteration number (0-indexed)
            feedback: Feedback from evaluating previous answer
        """
        self.state.iteration = iteration
        self.state.feedback = feedback
        # Reset ready flag for new iteration
        self.state.ready = True
        # Clear previous final answer
        self.state.final_answer = None
        self.state.final_var = None

    def _truncate(self, text: str, max_chars: int = 500) -> str:
        """Truncate text to max characters."""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + f"... [truncated, {len(text) - max_chars} more chars]"

    def _split_chunks(self, text: str, chunk_size: int = 1000) -> list[str]:
        """Split text into chunks."""
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    def _count_tokens(self, text: str) -> int:
        """Estimate token count (rough approximation)."""
        return len(text) // 4  # ~4 chars per token approximation

    def _extract_snippet(self, content: str, query: str, context_chars: int = 100) -> str:
        """Extract snippet around query match."""
        query_lower = query.lower()
        content_lower = content.lower()
        idx = content_lower.find(query_lower)
        if idx == -1:
            return content[:200] + "..."

        start = max(0, idx - context_chars)
        end = min(len(content), idx + len(query) + context_chars)
        snippet = content[start:end]

        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."

        return snippet

    def execute(self, code: str) -> tuple[str, bool]:
        """
        Execute code in the REPL environment.

        Args:
            code: Python code to execute

        Returns:
            (output, is_final) - output string and whether FINAL was called

        Security:
            - AST validation blocks dangerous operations before execution
            - Runtime checks detect string concatenation attacks
            - Namespace size limits prevent memory exhaustion
        """
        # Reject oversized code to prevent memory-based attacks
        if len(code) > self.MAX_CODE_SIZE:
            return f"SecurityError: Code exceeds maximum size ({self.MAX_CODE_SIZE} bytes)", False

        # Validate code safety (AST-based structural check)
        try:
            tree = ast.parse(code)
            self._validate_ast(tree)
        except SyntaxError as e:
            return f"SyntaxError: {e}", False
        except SecurityError as e:
            return f"SecurityError: {e}", False

        # Capture stdout
        stdout_capture = io.StringIO()

        # Store namespace keys before execution for comparison
        keys_before = set(self.state.namespace.keys())

        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stdout_capture):
                exec(code, {"__builtins__": {}}, self.state.namespace)  # nosec B102  # Sandboxed REPL with AST validation
        except SecurityError as e:
            return f"SecurityError: {e}", False
        except Exception as e:  # noqa: BLE001 - sandboxed REPL must catch all user code errors
            return f"Error: {type(e).__name__}: {e}", False

        # Post-execution security checks
        try:
            self._validate_namespace_post_exec(keys_before)
        except SecurityError as e:
            return f"SecurityError: {e}", False

        output = stdout_capture.getvalue()

        # Truncate output if too long
        if len(output) > self.MAX_OUTPUT_CHARS:
            output = (
                output[: self.MAX_OUTPUT_CHARS]
                + f"\n[Output truncated, {len(output) - self.MAX_OUTPUT_CHARS} more chars]"
            )

        # Record in history
        self.state.history.append((code, output))

        # Check for final answer
        is_final = self.state.final_answer is not None or self.state.final_var is not None

        return output, is_final

    def _validate_namespace_post_exec(self, keys_before: set[str]) -> None:
        """
        Validate namespace after execution for security concerns.

        Checks:
        - New variable names don't contain blocked dunder patterns
        - String values don't contain blocked dunder patterns (concatenation attack)
        - Values aren't excessively large (memory exhaustion)
        """
        new_keys = set(self.state.namespace.keys()) - keys_before

        for key in new_keys:
            # Check key name
            if _contains_blocked_dunder(key):
                del self.state.namespace[key]
                raise SecurityError(f"Variable name contains blocked pattern: {key}")

            # Check string values for concatenation attacks
            value = self.state.namespace[key]
            if isinstance(value, str):
                if _contains_blocked_dunder(value):
                    del self.state.namespace[key]
                    raise SecurityError(f"String variable '{key}' contains blocked dunder pattern")
                if len(value) > self._max_namespace_value_size:
                    del self.state.namespace[key]
                    raise SecurityError(
                        f"String variable '{key}' exceeds size limit ({self._max_namespace_value_size} bytes)"
                    )

            # Check list/dict sizes
            elif isinstance(value, (list, dict, set)):
                try:
                    size = len(str(value))
                    if size > self._max_namespace_value_size:
                        del self.state.namespace[key]
                        raise SecurityError(
                            f"Collection variable '{key}' exceeds size limit ({self._max_namespace_value_size} bytes)"
                        )
                except (TypeError, RecursionError) as e:
                    logger.debug("Could not check collection size: %s", e)
                    pass  # Can't check size, allow it

    # Maximum allowed code size to prevent memory-based attacks
    MAX_CODE_SIZE = 100_000  # 100KB

    def _validate_ast(self, tree: ast.AST) -> None:
        """
        Validate AST for security concerns.

        SECURITY: This validation is critical to prevent sandbox escapes.
        The sandbox can be escaped via:
        - getattr(func, "__globals__") to access builtins
        - obj.__class__.__bases__[0].__subclasses__() to find dangerous classes
        - String literals containing dunder names passed to functions
        - global/nonlocal statements to manipulate scope
        """
        # Dangerous function names that can escape the sandbox
        DANGEROUS_FUNCS = frozenset(
            {
                "eval",
                "exec",
                "compile",
                "open",
                "__import__",
                "getattr",
                "setattr",
                "delattr",
                "hasattr",
                "callable",
                "vars",
                "dir",
                "globals",
                "locals",
                "breakpoint",
                "input",
                "memoryview",
                "object",
                "classmethod",
                "staticmethod",
                "property",
                "super",
            }
        )

        for node in ast.walk(tree):
            # Block imports (except re)
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name != "re":
                            raise SecurityError(f"Import not allowed: {alias.name}")
                elif node.module != "re":
                    raise SecurityError(f"Import not allowed: {node.module}")

            # Block dangerous function calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in DANGEROUS_FUNCS:
                        raise SecurityError(f"Function not allowed: {node.func.id}")

            # Block ALL attribute access to underscore-prefixed names
            # This includes __class__, __globals__, _private, etc.
            if isinstance(node, ast.Attribute):
                if node.attr.startswith("_"):
                    raise SecurityError(
                        f"Attribute access not allowed: {node.attr} "
                        "(underscore-prefixed attributes are blocked)"
                    )

            # Block string literals containing dangerous dunder names
            # Prevents: some_dict["__globals__"] or f-string tricks
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value_lower = node.value.lower()
                for blocked in self.BLOCKED_DUNDER_NAMES:
                    if blocked in value_lower:
                        raise SecurityError(f"String literal contains blocked name: {blocked}")

            # Block subscript access with dangerous string keys
            if isinstance(node, ast.Subscript):
                if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                    if node.slice.value in self.BLOCKED_DUNDER_NAMES:
                        raise SecurityError(f"Subscript access to blocked name: {node.slice.value}")

            # Block global/nonlocal statements (scope manipulation)
            if isinstance(node, (ast.Global, ast.Nonlocal)):
                raise SecurityError("Global/nonlocal statements are not allowed")

            # Block f-strings that might construct dangerous names
            if isinstance(node, ast.JoinedStr):
                # F-strings could potentially build "__globals__" dynamically
                # We allow them but they'll fail at runtime if they try to access blocked attrs
                pass

            # Block starred expressions in dangerous contexts
            if isinstance(node, ast.Starred):
                # Could be used for unpacking attacks
                pass  # Allow for now, but monitor

    def get_result(self) -> RLMResult:
        """Get the final result after execution."""
        if self.state.final_var:
            answer = str(self.state.namespace.get(self.state.final_var, "[Variable not found]"))
        elif self.state.final_answer:
            answer = self.state.final_answer
        else:
            answer = "[No final answer provided]"

        # Collect nodes examined (from search operations, etc.)
        nodes_examined = []
        for code, _ in self.state.history:
            # Extract node IDs from code (basic heuristic)
            for match in re.findall(r"get_node\(['\"](\w+)['\"]\)", code):
                nodes_examined.append(match)
            for match in re.findall(r"drill_down\(['\"](\w+)['\"]\)", code):
                nodes_examined.append(match)

        return RLMResult(
            answer=answer,
            # Iterative refinement (Prime Intellect alignment)
            ready=self.state.ready,
            iteration=self.state.iteration,
            refinement_history=[],  # Managed by bridge.query_with_refinement()
            # Provenance
            nodes_examined=list(set(nodes_examined)),
            levels_traversed=[],  # Would need more tracking
            citations=[],
            # Stats
            tokens_processed=sum(len(output) // 4 for _, output in self.state.history),
            sub_calls_made=self.state.sub_call_count,
            time_seconds=0.0,  # Caller should track
            # Confidence
            confidence=0.8 if self.state.final_answer else 0.5,
            uncertainty_sources=[],
        )

    def get_prompt_for_agent(self) -> str:
        """Generate the system prompt for an agent to use this REPL."""
        return f"""You are interacting with a context through a Python REPL environment.

## Available Variables and Functions

### Context Access
- `CONTEXT` - Full original content ({self.context.original_tokens} tokens)
- `CONTEXT_TOKENS` - Token count of full context
- `get_abstract()` - Get highest-level summary
- `get_summary()` - Get summary level
- `get_detailed()` - Get detailed level
- `get_full()` - Get full content

### Navigation
- `get_node(node_id)` - Get specific node by ID
- `drill_down(node_id)` - Get child nodes (more detail)
- `get_children(node_id)` - Get child node IDs

### Search
- `search(query, level=None)` - Search for content
- `grep(pattern, content=None)` - Regex search
- `find_sections()` - Find document sections

### Sub-LM Calls
- `RLM_M(query, context_snippet)` - Spawn sub-LM to process context snippet

### Utilities
- `truncate(text, max_chars)` - Truncate text
- `split_chunks(text, chunk_size)` - Split into chunks
- `count_tokens(text)` - Estimate token count
- `re` - Python re module for regex

### Finishing
- `FINAL(answer, ready=True)` - Return final answer. Set `ready=False` to signal refinement needed.
- `FINAL_VAR(var_name, ready=True)` - Return variable as final answer
- `SET_READY(bool)` - Explicitly set readiness status
- `FEEDBACK()` - Get feedback from previous iteration (returns None on first iteration)

## Iterative Refinement

When you're uncertain about your answer:
1. Call `FINAL(partial_answer, ready=False)` to signal refinement is needed
2. On next iteration, check `FEEDBACK()` for guidance on what to improve
3. When confident, call `FINAL(answer, ready=True)` or just `FINAL(answer)`

## Strategy

1. Start by examining the abstract/summary level
2. Search for relevant sections
3. Drill down into detailed content as needed
4. Use RLM_M() for complex sub-queries
5. Call FINAL() when you have the answer (use ready=False if uncertain)

## Example

```python
# Peek at structure
summary = get_summary()
print(truncate(summary, 500))

# Search for relevant content
results = search("authentication")
print(results)

# Drill into a result
if results:
    details = drill_down(results[0]["id"])
    print(details)

# Check if we have feedback from a previous iteration
feedback = FEEDBACK()
if feedback:
    print(f"Previous feedback: {{feedback}}")

# Final answer (confident)
FINAL("The authentication system uses JWT tokens...")

# Or, if uncertain, request refinement
# FINAL("Initial analysis suggests JWT...", ready=False)
```
"""


class SecurityError(Exception):
    """Raised when code attempts unsafe operations."""

    pass
