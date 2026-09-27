"""
Executable Verification Proofs - Link claims to verifiable code.

Enables claims in debates to be backed by executable verification:
- Code assertions that can be run to verify claims
- API calls to fetch supporting data
- Mathematical computations
- Test executions
- Property-based checks

Key concepts:
- VerificationProof: Executable code/assertion for a claim
- ProofExecutor: Sandbox for safe proof execution
- ClaimVerifier: Manages proof-claim relationships
- VerificationReport: Aggregated results

SECURITY NOTE:
Code execution is inherently risky. The SAFE_BUILTINS whitelist restricts
what functions are available to executed code. Do not expose proof execution
to untrusted users without additional sandboxing (subprocess, containers).
"""

from __future__ import annotations

__all__ = [
    "EXEC_TIMEOUT_SECONDS",
    "DANGEROUS_PATTERNS",
    "SAFE_BUILTINS",
    "ProofType",
    "ProofStatus",
    "VerificationProof",
    "VerificationResult",
    "ProofExecutor",
    "ClaimVerifier",
    "VerificationReport",
    "ProofBuilder",
    "create_simple_assertion",
    "create_computation_proof",
    "verify_claim_set",
]

import ast
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from aragora.exceptions import VerificationError

import logging

logger = logging.getLogger(__name__)

# Timeout for code execution (seconds) - prevents infinite loops/CPU exhaustion
EXEC_TIMEOUT_SECONDS = 5.0


def _get_safe_subprocess_env() -> dict[str, str]:
    """Get a filtered environment for subprocess execution.

    Removes sensitive environment variables (API keys, secrets, tokens)
    to prevent them from being exposed to executed code.

    Returns:
        Minimal environment dict safe for subprocess execution
    """
    # Start with minimal required environment variables
    safe_env = {}

    # Required for Python to work properly
    for key in ("PATH", "HOME", "PYTHONPATH", "LANG", "LC_ALL", "TMPDIR", "TMP", "TEMP"):
        if key in os.environ:
            safe_env[key] = os.environ[key]

    # Set sensible defaults
    if "LANG" not in safe_env:
        safe_env["LANG"] = "en_US.UTF-8"

    return safe_env


# Maximum allowed code size to prevent memory-based attacks
MAX_CODE_SIZE = 100_000  # 100KB

# Patterns that could enable sandbox escape via Python introspection
DANGEROUS_PATTERNS = [
    # Dunder attribute access (sandbox escape vectors)
    "__class__",
    "__bases__",
    "__subclasses__",
    "__mro__",
    "__globals__",
    "__code__",
    "__builtins__",
    "__import__",
    "__getattribute__",
    "__getattr__",
    "__setattr__",
    "__delattr__",
    "__reduce__",
    "__reduce_ex__",
    "__init_subclass__",
    "__dict__",
    "__init__",
    "__new__",
    "__call__",
    "__del__",
    "__closure__",
    "__func__",
    "__self__",
    "__wrapped__",
    "__module__",
    "__name__",
    "__qualname__",
    "__loader__",
    "__spec__",
    "__annotations__",
    # Dangerous builtin function calls
    "exec(",
    "eval(",
    "compile(",
    "open(",
    "getattr(",
    "setattr(",
    "delattr(",
    "hasattr(",
    "globals(",
    "locals(",
    "vars(",
    "dir(",
    "breakpoint(",
    "input(",
    "memoryview(",
    "type(",
    "classmethod(",
    "staticmethod(",
    "property(",
    "super(",
    # Module access
    "os.",
    "sys.",
    "subprocess",
    "importlib",
    "ctypes",
    "pickle",
    "marshal",
    "shutil",
    "socket",
    "signal",
]


def _validate_code_safety(code: str) -> tuple[bool, str]:
    """
    Check code for dangerous patterns that could enable sandbox escape.

    Uses both string pattern matching (for quick rejection) and AST analysis
    (for structural validation) to catch bypass attempts.

    Returns:
        Tuple of (is_safe, error_message)
    """
    # Reject oversized code to prevent memory-based attacks
    if len(code) > MAX_CODE_SIZE:
        return False, f"Code exceeds maximum size ({MAX_CODE_SIZE} bytes)"

    # String pattern matching (catches obfuscation and non-code patterns)
    code_lower = code.lower()
    for pattern in DANGEROUS_PATTERNS:
        if pattern.lower() in code_lower:
            return False, f"Dangerous pattern detected: '{pattern}' is not allowed"

    # AST-based structural validation (catches patterns that string matching misses)
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error in code: {e}"

    for node in ast.walk(tree):
        # Block all import statements
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = ""
            if isinstance(node, ast.Import):
                module = node.names[0].name if node.names else ""
            elif node.module:
                module = node.module
            return False, f"Import statements are not allowed: {module}"

        # Block dangerous function calls by name
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            dangerous_calls = {
                "eval",
                "exec",
                "compile",
                "open",
                "__import__",
                "getattr",
                "setattr",
                "delattr",
                "hasattr",
                "globals",
                "locals",
                "vars",
                "dir",
                "breakpoint",
                "input",
                "memoryview",
                "type",
                "classmethod",
                "staticmethod",
                "property",
                "super",
                "object",
            }
            if node.func.id in dangerous_calls:
                return False, f"Call to '{node.func.id}' is not allowed"

        # Block access to underscore-prefixed attributes
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            return False, f"Access to private/dunder attribute '{node.attr}' is not allowed"

        # Block subscript access with dangerous string keys
        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                if node.slice.value.startswith("__") and node.slice.value.endswith("__"):
                    return False, f"Subscript access to '{node.slice.value}' is not allowed"

        # Block global/nonlocal statements (could manipulate scope)
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            return False, "Global/nonlocal statements are not allowed"

    return True, ""


# Safe subset of builtins for proof execution (no imports, no file access)
SAFE_BUILTINS = {
    # Math and logic
    "abs": abs,
    "all": all,
    "any": any,
    "bin": bin,
    "bool": bool,
    "divmod": divmod,
    "float": float,
    "hex": hex,
    "int": int,
    "len": len,
    "max": max,
    "min": min,
    "oct": oct,
    "ord": ord,
    "pow": pow,
    "round": round,
    "sum": sum,
    # String/data
    "chr": chr,
    "str": str,
    "repr": repr,
    "ascii": ascii,
    "format": format,
    "hash": hash,
    # Collections
    "dict": dict,
    "frozenset": frozenset,
    "list": list,
    "set": set,
    "tuple": tuple,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "filter": filter,
    "map": map,
    "reversed": reversed,
    "sorted": sorted,
    "slice": slice,
    # Types and inspection
    "callable": callable,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "type": type,
    "id": id,
    "iter": iter,
    "next": next,
    # Exceptions (needed for try/except in proofs)
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "AssertionError": AssertionError,
    "AttributeError": AttributeError,
    "RuntimeError": RuntimeError,
    # Explicitly excluded: __import__, open, exec, eval, compile, globals, locals
}


def _exec_in_subprocess(code: str, timeout: float = EXEC_TIMEOUT_SECONDS) -> dict[str, Any]:
    """
    Execute code in an isolated subprocess with hard timeout.

    Uses subprocess isolation to prevent sandbox escapes via __class__,
    __getattribute__, and other Python introspection mechanisms. The subprocess
    can be killed by the OS, providing a true timeout unlike thread-based approaches.

    Args:
        code: Python code to execute
        timeout: Maximum execution time in seconds

    Returns:
        Dict with:
            - success: bool
            - result: Any value assigned to 'result' variable
            - stdout: Captured stdout
            - error: Error message if failed

    Raises:
        TimeoutError: If execution exceeds timeout
        RuntimeError: If execution fails
    """
    # Validate code for dangerous patterns before execution
    is_safe, error_msg = _validate_code_safety(code)
    if not is_safe:
        return {
            "success": False,
            "error": error_msg,
            "stdout": "",
            "result": None,
        }

    # Create wrapper script that captures execution results
    # Define safe builtins inside subprocess (can't serialize functions)
    wrapper_code = f"""
import json
import sys

# Safe builtins whitelist - matches SAFE_BUILTINS in parent module
SAFE_BUILTINS = {{
    # Math and logic
    'abs': abs, 'all': all, 'any': any, 'bin': bin, 'bool': bool,
    'divmod': divmod, 'float': float, 'hex': hex, 'int': int,
    'len': len, 'max': max, 'min': min, 'oct': oct, 'ord': ord,
    'pow': pow, 'round': round, 'sum': sum,
    # String/data
    'chr': chr, 'str': str, 'repr': repr, 'ascii': ascii,
    'format': format, 'hash': hash,
    # Collections
    'dict': dict, 'frozenset': frozenset, 'list': list, 'set': set,
    'tuple': tuple, 'range': range, 'enumerate': enumerate, 'zip': zip,
    'filter': filter, 'map': map, 'reversed': reversed, 'sorted': sorted,
    'slice': slice,
    # Types and inspection
    'callable': callable, 'isinstance': isinstance, 'issubclass': issubclass,
    'type': type, 'id': id, 'iter': iter, 'next': next,
    # Exceptions (needed for try/except in proofs)
    'Exception': Exception, 'ValueError': ValueError, 'TypeError': TypeError,
    'KeyError': KeyError, 'IndexError': IndexError, 'AssertionError': AssertionError,
    'AttributeError': AttributeError, 'RuntimeError': RuntimeError,
    # Constants
    'True': True, 'False': False, 'None': None,
    # Explicitly excluded: __import__, open, exec, eval, compile, globals, locals
}}

namespace = {{}}
stdout_capture = []

class OutputCapture:
    def write(self, text):
        stdout_capture.append(text)
    def flush(self):
        pass

old_stdout = sys.stdout
sys.stdout = OutputCapture()

try:
    exec({repr(code)}, {{"__builtins__": SAFE_BUILTINS}}, namespace)  # nosec
    sys.stdout = old_stdout
    # Serialize all namespace variables that can be repr'd to literals
    serializable_ns = {{}}
    for key, value in namespace.items():
        if not key.startswith('_'):
            try:
                serializable_ns[key] = repr(value)
            except Exception:  # noqa: BLE001
                pass  # Skip non-repr values
    # Prefer __result__ (assertion result) over result (user variable)
    print(json.dumps({{
        "success": True,
        "namespace": serializable_ns,
        "result": repr(namespace.get("__result__", namespace.get("result", None))),
        "stdout": "".join(stdout_capture)
    }}))
except Exception as e:
    sys.stdout = old_stdout
    print(json.dumps({{
        "success": False,
        "error": f"{{type(e).__name__}}: {{str(e)}}"
    }}))
"""

    try:
        # Write wrapper to temp file and execute in subprocess
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(wrapper_code)
            f.flush()
            temp_path = f.name

        try:
            result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                [sys.executable, temp_path],
                capture_output=True,
                timeout=timeout,
                text=True,
                shell=False,
                env=_get_safe_subprocess_env(),  # Filtered env prevents API key leakage
            )

            if result.returncode != 0 and not result.stdout:
                return {
                    "success": False,
                    "error": result.stderr or "Process failed with no output",
                    "stdout": "",
                    "result": None,
                }

            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "error": f"Invalid JSON output: {result.stdout[:200]}",
                    "stdout": result.stdout,
                    "result": None,
                }

        finally:
            import os

            try:
                os.unlink(temp_path)
            except OSError as e:
                logger.debug("proofs operation failed: %s", e)

    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Code execution exceeded {timeout}s timeout")


def _exec_with_timeout(code: str, namespace: dict, timeout: float = EXEC_TIMEOUT_SECONDS) -> None:
    """
    Execute code with timeout protection using subprocess isolation.

    This function maintains backward compatibility while using subprocess
    isolation under the hood for security.

    Args:
        code: Python code to execute
        namespace: Namespace dict (will be modified in-place with result)
        timeout: Maximum execution time in seconds

    Raises:
        TimeoutError: If execution exceeds timeout
        RuntimeError: If execution fails
    """
    result = _exec_in_subprocess(code, timeout)

    if not result.get("success", False):
        error_msg = result.get("error", "Unknown execution error")
        if "AssertionError" in error_msg:
            raise AssertionError(error_msg)
        raise VerificationError(error_msg)

    # Parse all namespace variables back
    if result.get("namespace"):
        for key, repr_value in result["namespace"].items():
            try:
                # Safely parse repr'd value using ast.literal_eval (only allows literals)
                namespace[key] = ast.literal_eval(repr_value)
            except (ValueError, SyntaxError):
                # If not a valid literal, keep as string
                namespace[key] = repr_value

    # Also set __result__ for backward compatibility
    if result.get("result"):
        try:
            namespace["__result__"] = ast.literal_eval(result["result"])
        except (ValueError, SyntaxError):
            namespace["__result__"] = result["result"]

    if result.get("stdout"):
        namespace["__stdout__"] = result["stdout"]


class ProofType(Enum):
    """Type of verification proof."""

    ASSERTION = "assertion"  # Python assertion/boolean check
    CODE_EXECUTION = "code_execution"  # Run code and check output
    API_CALL = "api_call"  # Fetch data from API
    COMPUTATION = "computation"  # Mathematical verification
    TEST_SUITE = "test_suite"  # Run test suite
    PROPERTY_CHECK = "property_check"  # Property-based testing
    STATIC_ANALYSIS = "static_analysis"  # Code analysis
    MANUAL = "manual"  # Requires human verification


class ProofStatus(Enum):
    """Status of a verification proof."""

    PENDING = "pending"  # Not yet executed
    RUNNING = "running"  # Currently executing
    PASSED = "passed"  # Verification succeeded
    FAILED = "failed"  # Verification failed
    ERROR = "error"  # Execution error
    SKIPPED = "skipped"  # Skipped (e.g., dependencies missing)
    TIMEOUT = "timeout"  # Execution timed out


@dataclass
class VerificationProof:
    """
    An executable proof that can verify a claim.

    Contains code or assertions that can be executed
    to verify the truthfulness of a claim.
    """

    id: str
    claim_id: str  # ID of the claim this verifies
    proof_type: ProofType
    description: str

    # Executable content
    code: str  # Python code to execute
    expected_output: str | None = None  # Expected output for comparison
    assertion: str | None = None  # Boolean expression to evaluate

    # Metadata
    dependencies: list[str] = field(default_factory=list)  # Required packages
    timeout_seconds: float = 30.0
    requires_network: bool = False
    requires_filesystem: bool = False

    # Status
    status: ProofStatus = ProofStatus.PENDING
    last_run: datetime | None = None
    run_count: int = 0

    # Results
    output: str = ""
    error: str = ""
    execution_time_ms: float = 0.0

    # Provenance
    created_at: datetime = field(default_factory=datetime.now)
    created_by: str = ""
    proof_hash: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:12]
        if not self.proof_hash:
            self.proof_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute hash of proof content."""
        data = f"{self.code}:{self.assertion or ''}:{self.expected_output or ''}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "claim_id": self.claim_id,
            "proof_type": self.proof_type.value,
            "description": self.description,
            "code": self.code,
            "expected_output": self.expected_output,
            "assertion": self.assertion,
            "dependencies": self.dependencies,
            "timeout_seconds": self.timeout_seconds,
            "requires_network": self.requires_network,
            "requires_filesystem": self.requires_filesystem,
            "status": self.status.value,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "run_count": self.run_count,
            "output": self.output,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "proof_hash": self.proof_hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> VerificationProof:
        proof = cls(
            id=data["id"],
            claim_id=data["claim_id"],
            proof_type=ProofType(data["proof_type"]),
            description=data["description"],
            code=data["code"],
            expected_output=data.get("expected_output"),
            assertion=data.get("assertion"),
            dependencies=data.get("dependencies", []),
            timeout_seconds=data.get("timeout_seconds", 30.0),
            requires_network=data.get("requires_network", False),
            requires_filesystem=data.get("requires_filesystem", False),
            status=ProofStatus(data.get("status", "pending")),
            run_count=data.get("run_count", 0),
            output=data.get("output", ""),
            error=data.get("error", ""),
            execution_time_ms=data.get("execution_time_ms", 0.0),
            created_by=data.get("created_by", ""),
            proof_hash=data.get("proof_hash", ""),
        )
        if data.get("last_run"):
            proof.last_run = datetime.fromisoformat(data["last_run"])
        if data.get("created_at"):
            proof.created_at = datetime.fromisoformat(data["created_at"])
        return proof


@dataclass
class VerificationResult:
    """Result of executing a verification proof."""

    proof_id: str
    claim_id: str
    status: ProofStatus
    passed: bool

    # Execution details
    output: str = ""
    error: str = ""
    execution_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    # For assertions
    assertion_value: bool | None = None
    assertion_details: str = ""

    # For expected output comparison
    output_matched: bool | None = None
    output_diff: str = ""

    def to_dict(self) -> dict:
        return {
            "proof_id": self.proof_id,
            "claim_id": self.claim_id,
            "status": self.status.value,
            "passed": self.passed,
            "output": self.output,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "timestamp": self.timestamp.isoformat(),
            "assertion_value": self.assertion_value,
            "assertion_details": self.assertion_details,
            "output_matched": self.output_matched,
            "output_diff": self.output_diff,
        }


class ProofExecutor:
    """
    Executes verification proofs in a safe environment.

    Provides sandboxed execution with timeouts and
    resource limits.
    """

    def __init__(
        self,
        allow_network: bool = False,
        allow_filesystem: bool = False,
        default_timeout: float = 30.0,
        max_output_size: int = 10000,
    ):
        self.allow_network = allow_network
        self.allow_filesystem = allow_filesystem
        self.default_timeout = default_timeout
        self.max_output_size = max_output_size

    async def execute(self, proof: VerificationProof) -> VerificationResult:
        """Execute a verification proof."""

        # Check permissions
        if proof.requires_network and not self.allow_network:
            return VerificationResult(
                proof_id=proof.id,
                claim_id=proof.claim_id,
                status=ProofStatus.SKIPPED,
                passed=False,
                error="Proof requires network access which is not allowed",
            )

        if proof.requires_filesystem and not self.allow_filesystem:
            return VerificationResult(
                proof_id=proof.id,
                claim_id=proof.claim_id,
                status=ProofStatus.SKIPPED,
                passed=False,
                error="Proof requires filesystem access which is not allowed",
            )

        # Update proof status
        proof.status = ProofStatus.RUNNING
        proof.last_run = datetime.now()
        proof.run_count += 1

        start_time = datetime.now()

        try:
            timeout = proof.timeout_seconds or self.default_timeout

            if proof.proof_type == ProofType.ASSERTION:
                result = await self._execute_assertion(proof, timeout)
            elif proof.proof_type == ProofType.CODE_EXECUTION:
                result = await self._execute_code(proof, timeout)
            elif proof.proof_type == ProofType.COMPUTATION:
                result = await self._execute_computation(proof, timeout)
            else:
                result = await self._execute_code(proof, timeout)

        except asyncio.TimeoutError:
            result = VerificationResult(
                proof_id=proof.id,
                claim_id=proof.claim_id,
                status=ProofStatus.TIMEOUT,
                passed=False,
                error=f"Execution timed out after {timeout}s",
            )
        except (
            RuntimeError,
            VerificationError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ) as e:
            logging.getLogger(__name__).exception(f"Proof execution failed for {proof.id}")
            result = VerificationResult(
                proof_id=proof.id,
                claim_id=proof.claim_id,
                status=ProofStatus.ERROR,
                passed=False,
                error=f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}",
            )

        # Update execution time
        elapsed = (datetime.now() - start_time).total_seconds() * 1000
        result.execution_time_ms = elapsed

        # Update proof with result
        proof.status = result.status
        proof.output = result.output[: self.max_output_size]
        proof.error = result.error[: self.max_output_size]
        proof.execution_time_ms = elapsed

        return result

    async def _execute_assertion(
        self, proof: VerificationProof, timeout: float
    ) -> VerificationResult:
        """Execute an assertion-based proof."""

        code = proof.code
        assertion = proof.assertion

        # Build execution code
        exec_code = code
        if assertion:
            exec_code += f"\n__result__ = bool({assertion})"

        # Execute in isolated namespace with timeout protection
        namespace: dict[str, Any] = {}

        try:
            _exec_with_timeout(exec_code, namespace, timeout=timeout)

            if assertion:
                assertion_value = namespace.get("__result__", False)
                passed = bool(assertion_value)

                return VerificationResult(
                    proof_id=proof.id,
                    claim_id=proof.claim_id,
                    status=ProofStatus.PASSED if passed else ProofStatus.FAILED,
                    passed=passed,
                    assertion_value=assertion_value,
                    assertion_details=f"Assertion '{assertion}' evaluated to {assertion_value}",
                )
            else:
                # Code executed without error
                return VerificationResult(
                    proof_id=proof.id,
                    claim_id=proof.claim_id,
                    status=ProofStatus.PASSED,
                    passed=True,
                    output="Code executed successfully",
                )

        except AssertionError as e:
            return VerificationResult(
                proof_id=proof.id,
                claim_id=proof.claim_id,
                status=ProofStatus.FAILED,
                passed=False,
                error=f"Assertion failed: {str(e)}",
                assertion_value=False,
            )
        except TimeoutError as e:
            return VerificationResult(
                proof_id=proof.id,
                claim_id=proof.claim_id,
                status=ProofStatus.TIMEOUT,
                passed=False,
                error=str(e),
            )

    async def _execute_code(self, proof: VerificationProof, timeout: float) -> VerificationResult:
        """Execute code and capture output with timeout protection."""

        import io
        import sys

        # Capture stdout
        stdout_capture = io.StringIO()
        old_stdout = sys.stdout

        try:
            sys.stdout = stdout_capture
            namespace: dict[str, Any] = {}
            # Use timeout protection for code execution
            _exec_with_timeout(proof.code, namespace, timeout=timeout)
            output = stdout_capture.getvalue()

        except TimeoutError as e:
            sys.stdout = old_stdout
            return VerificationResult(
                proof_id=proof.id,
                claim_id=proof.claim_id,
                status=ProofStatus.TIMEOUT,
                passed=False,
                error=str(e),
            )
        finally:
            sys.stdout = old_stdout

        # Compare output if expected
        if proof.expected_output is not None:
            output_matched = output.strip() == proof.expected_output.strip()
            diff = ""
            if not output_matched:
                diff = f"Expected:\n{proof.expected_output}\n\nActual:\n{output}"

            return VerificationResult(
                proof_id=proof.id,
                claim_id=proof.claim_id,
                status=ProofStatus.PASSED if output_matched else ProofStatus.FAILED,
                passed=output_matched,
                output=output,
                output_matched=output_matched,
                output_diff=diff,
            )
        else:
            return VerificationResult(
                proof_id=proof.id,
                claim_id=proof.claim_id,
                status=ProofStatus.PASSED,
                passed=True,
                output=output,
            )

    async def _execute_computation(
        self, proof: VerificationProof, timeout: float
    ) -> VerificationResult:
        """Execute a mathematical computation."""
        return await self._execute_assertion(proof, timeout)


class ClaimVerifier:
    """
    Manages verification proofs for claims.

    Links claims to their proofs and provides
    verification orchestration.
    """

    def __init__(self, executor: ProofExecutor | None = None):
        self.executor = executor or ProofExecutor()
        self.proofs: dict[str, VerificationProof] = {}
        self.claim_proofs: dict[str, list[str]] = {}  # claim_id -> [proof_ids]
        self.results: dict[str, VerificationResult] = {}

    def add_proof(self, proof: VerificationProof) -> None:
        """Add a verification proof."""
        self.proofs[proof.id] = proof

        if proof.claim_id not in self.claim_proofs:
            self.claim_proofs[proof.claim_id] = []
        self.claim_proofs[proof.claim_id].append(proof.id)

    def get_proofs_for_claim(self, claim_id: str) -> list[VerificationProof]:
        """Get all proofs for a claim."""
        proof_ids = self.claim_proofs.get(claim_id, [])
        return [self.proofs[pid] for pid in proof_ids if pid in self.proofs]

    async def verify_claim(self, claim_id: str) -> list[VerificationResult]:
        """Verify all proofs for a claim."""
        proofs = self.get_proofs_for_claim(claim_id)
        results = []

        for proof in proofs:
            result = await self.executor.execute(proof)
            self.results[proof.id] = result
            results.append(result)

        return results

    async def verify_all(self) -> list[VerificationResult]:
        """Verify all proofs."""
        results = []
        for proof in self.proofs.values():
            result = await self.executor.execute(proof)
            self.results[proof.id] = result
            results.append(result)
        return results

    def get_claim_verification_status(self, claim_id: str) -> dict[str, Any]:
        """Get verification status for a claim."""
        proof_ids = self.claim_proofs.get(claim_id, [])

        if not proof_ids:
            return {
                "claim_id": claim_id,
                "has_proofs": False,
                "verified": False,
                "status": "no_proofs",
            }

        results = [
            result for proof_id in proof_ids if (result := self.results.get(proof_id)) is not None
        ]

        if not results:
            return {
                "claim_id": claim_id,
                "has_proofs": True,
                "proof_count": len(proof_ids),
                "verified": False,
                "status": "pending",
            }

        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)

        return {
            "claim_id": claim_id,
            "has_proofs": True,
            "proof_count": len(proof_ids),
            "executed_count": len(results),
            "passed_count": passed,
            "failed_count": failed,
            "verified": failed == 0 and passed > 0,
            "status": "verified" if failed == 0 and passed > 0 else "failed",
        }


@dataclass
class VerificationReport:
    """Aggregated verification report for a debate."""

    debate_id: str
    created_at: datetime = field(default_factory=datetime.now)

    # Statistics
    total_claims: int = 0
    claims_with_proofs: int = 0
    claims_verified: int = 0
    claims_failed: int = 0
    claims_pending: int = 0

    total_proofs: int = 0
    proofs_passed: int = 0
    proofs_failed: int = 0
    proofs_error: int = 0
    proofs_skipped: int = 0

    # Details
    claim_statuses: dict[str, dict] = field(default_factory=dict)
    failed_proofs: list[dict] = field(default_factory=list)
    execution_time_total_ms: float = 0.0

    def verification_rate(self) -> float:
        """Calculate verification rate."""
        if self.claims_with_proofs == 0:
            return 0.0
        return self.claims_verified / self.claims_with_proofs

    def pass_rate(self) -> float:
        """Calculate proof pass rate."""
        executed = self.proofs_passed + self.proofs_failed + self.proofs_error
        if executed == 0:
            return 0.0
        return self.proofs_passed / executed

    def to_dict(self) -> dict:
        return {
            "debate_id": self.debate_id,
            "created_at": self.created_at.isoformat(),
            "statistics": {
                "total_claims": self.total_claims,
                "claims_with_proofs": self.claims_with_proofs,
                "claims_verified": self.claims_verified,
                "claims_failed": self.claims_failed,
                "claims_pending": self.claims_pending,
                "verification_rate": self.verification_rate(),
            },
            "proofs": {
                "total": self.total_proofs,
                "passed": self.proofs_passed,
                "failed": self.proofs_failed,
                "error": self.proofs_error,
                "skipped": self.proofs_skipped,
                "pass_rate": self.pass_rate(),
            },
            "execution_time_total_ms": self.execution_time_total_ms,
            "failed_proofs": self.failed_proofs,
        }

    def generate_summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"# Verification Report: {self.debate_id}",
            "",
            "## Summary",
            f"- **Claims with proofs**: {self.claims_with_proofs}/{self.total_claims}",
            f"- **Claims verified**: {self.claims_verified} ({self.verification_rate():.0%})",
            f"- **Claims failed**: {self.claims_failed}",
            "",
            "## Proof Execution",
            f"- **Total proofs**: {self.total_proofs}",
            f"- **Passed**: {self.proofs_passed}",
            f"- **Failed**: {self.proofs_failed}",
            f"- **Errors**: {self.proofs_error}",
            f"- **Pass rate**: {self.pass_rate():.0%}",
            f"- **Total execution time**: {self.execution_time_total_ms:.0f}ms",
        ]

        if self.failed_proofs:
            lines.append("")
            lines.append("## Failed Proofs")
            for fp in self.failed_proofs[:5]:
                lines.append(f"\n### {fp.get('description', 'Unknown')}")
                lines.append(f"- **Claim**: {fp.get('claim_id', 'Unknown')}")
                lines.append(f"- **Error**: {fp.get('error', 'No error message')[:100]}")

        return "\n".join(lines)


class ProofBuilder:
    """Helper class for building verification proofs."""

    def __init__(self, claim_id: str, created_by: str = ""):
        self.claim_id = claim_id
        self.created_by = created_by

    def assertion(
        self,
        description: str,
        code: str,
        assertion: str,
        **kwargs,
    ) -> VerificationProof:
        """Create an assertion-based proof."""
        return VerificationProof(
            id=str(uuid.uuid4())[:12],
            claim_id=self.claim_id,
            proof_type=ProofType.ASSERTION,
            description=description,
            code=code,
            assertion=assertion,
            created_by=self.created_by,
            **kwargs,
        )

    def output_check(
        self,
        description: str,
        code: str,
        expected_output: str,
        **kwargs,
    ) -> VerificationProof:
        """Create a proof that checks code output."""
        return VerificationProof(
            id=str(uuid.uuid4())[:12],
            claim_id=self.claim_id,
            proof_type=ProofType.CODE_EXECUTION,
            description=description,
            code=code,
            expected_output=expected_output,
            created_by=self.created_by,
            **kwargs,
        )

    def computation(
        self,
        description: str,
        code: str,
        assertion: str,
        **kwargs,
    ) -> VerificationProof:
        """Create a mathematical computation proof."""
        return VerificationProof(
            id=str(uuid.uuid4())[:12],
            claim_id=self.claim_id,
            proof_type=ProofType.COMPUTATION,
            description=description,
            code=code,
            assertion=assertion,
            created_by=self.created_by,
            **kwargs,
        )

    def property_check(
        self,
        description: str,
        code: str,
        property_assertion: str,
        **kwargs,
    ) -> VerificationProof:
        """Create a property-based verification proof."""
        return VerificationProof(
            id=str(uuid.uuid4())[:12],
            claim_id=self.claim_id,
            proof_type=ProofType.PROPERTY_CHECK,
            description=description,
            code=code,
            assertion=property_assertion,
            created_by=self.created_by,
            **kwargs,
        )


# Convenience functions


def create_simple_assertion(
    claim_id: str,
    description: str,
    assertion: str,
) -> VerificationProof:
    """Create a simple assertion proof."""
    return VerificationProof(
        id=str(uuid.uuid4())[:12],
        claim_id=claim_id,
        proof_type=ProofType.ASSERTION,
        description=description,
        code="",
        assertion=assertion,
    )


def create_computation_proof(
    claim_id: str,
    description: str,
    computation_code: str,
    expected_assertion: str,
) -> VerificationProof:
    """Create a computation verification proof."""
    return VerificationProof(
        id=str(uuid.uuid4())[:12],
        claim_id=claim_id,
        proof_type=ProofType.COMPUTATION,
        description=description,
        code=computation_code,
        assertion=expected_assertion,
    )


async def verify_claim_set(
    claims: list[tuple[str, str]],  # (claim_id, claim_text)
    proofs: list[VerificationProof],
    executor: ProofExecutor | None = None,
) -> VerificationReport:
    """Verify a set of claims with their proofs."""

    executor = executor or ProofExecutor()
    verifier = ClaimVerifier(executor)

    # Add proofs
    for proof in proofs:
        verifier.add_proof(proof)

    # Execute all proofs
    results = await verifier.verify_all()

    # Build report
    report = VerificationReport(debate_id=str(uuid.uuid4())[:8])
    report.total_claims = len(claims)
    report.total_proofs = len(proofs)

    # Process results
    for result in results:
        report.execution_time_total_ms += result.execution_time_ms

        if result.status == ProofStatus.PASSED:
            report.proofs_passed += 1
        elif result.status == ProofStatus.FAILED:
            report.proofs_failed += 1
            report.failed_proofs.append(result.to_dict())
        elif result.status == ProofStatus.ERROR:
            report.proofs_error += 1
            report.failed_proofs.append(result.to_dict())
        elif result.status == ProofStatus.SKIPPED:
            report.proofs_skipped += 1

    # Count claims with proofs
    for claim_id, _ in claims:
        status = verifier.get_claim_verification_status(claim_id)
        report.claim_statuses[claim_id] = status

        if status["has_proofs"]:
            report.claims_with_proofs += 1
            if status["verified"]:
                report.claims_verified += 1
            elif status["status"] == "failed":
                report.claims_failed += 1
            else:
                report.claims_pending += 1

    return report
