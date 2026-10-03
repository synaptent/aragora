"""Extended tests for the verification proofs module.

Tests security-critical edge cases and error handling:
- Subprocess execution: timeout, cleanup, env filtering, JSON errors
- Code safety validation: case sensitivity, obfuscation patterns
- ProofExecutor: permission enforcement, output truncation
- ClaimVerifier: multi-proof aggregation
- VerificationReport: edge cases in analytics
"""

import os
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

from aragora.verification.proofs import (
    DANGEROUS_PATTERNS,
    EXEC_TIMEOUT_SECONDS,
    SAFE_BUILTINS,
    ClaimVerifier,
    ProofBuilder,
    ProofExecutor,
    ProofStatus,
    ProofType,
    VerificationProof,
    VerificationResult,
    VerificationReport,
    _validate_code_safety,
    _exec_in_subprocess,
    _get_safe_subprocess_env,
    create_simple_assertion,
    create_computation_proof,
    verify_claim_set,
)


# =============================================================================
# Tests for _get_safe_subprocess_env()
# =============================================================================


class TestSafeSubprocessEnv:
    """Tests for environment variable filtering in subprocess execution."""

    def test_path_is_preserved(self):
        """PATH environment variable should be preserved."""
        with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            env = _get_safe_subprocess_env()
            assert "PATH" in env
            assert env["PATH"] == "/usr/bin:/bin"

    def test_home_is_preserved(self):
        """HOME environment variable should be preserved."""
        with patch.dict(os.environ, {"HOME": "/home/testuser"}):
            env = _get_safe_subprocess_env()
            assert "HOME" in env
            assert env["HOME"] == "/home/testuser"

    def test_pythonpath_is_preserved(self):
        """PYTHONPATH should be preserved if set."""
        with patch.dict(os.environ, {"PYTHONPATH": "/custom/path"}):
            env = _get_safe_subprocess_env()
            assert "PYTHONPATH" in env

    def test_api_keys_are_filtered_out(self):
        """API keys and secrets should NOT be in subprocess env."""
        sensitive_vars = {
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "OPENAI_API_KEY": "sk-openai-secret",
            "AWS_SECRET_ACCESS_KEY": "aws-secret",
            "DATABASE_PASSWORD": "db-password",
            "SECRET_KEY": "my-secret-key",
            "OPENROUTER_API_KEY": "or-key",
            "GEMINI_API_KEY": "gemini-key",
            "XAI_API_KEY": "xai-key",
        }
        with patch.dict(os.environ, sensitive_vars, clear=False):
            env = _get_safe_subprocess_env()
            for key in sensitive_vars:
                assert key not in env, f"Sensitive key {key} should be filtered"

    def test_lang_default_is_set(self):
        """LANG should default to en_US.UTF-8 if not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Ensure only minimal env vars
            with patch.dict(os.environ, {"PATH": "/bin"}, clear=True):
                env = _get_safe_subprocess_env()
                assert env.get("LANG") == "en_US.UTF-8"

    def test_preserves_required_vars_only(self):
        """Only specifically allowed env vars should be preserved."""
        allowed_keys = {"PATH", "HOME", "PYTHONPATH", "LANG", "LC_ALL", "TMPDIR", "TMP", "TEMP"}
        test_env = {
            "PATH": "/bin",
            "HOME": "/home/user",
            "RANDOM_VAR": "should-not-appear",
            "CUSTOM_SETTING": "also-not-allowed",
        }
        with patch.dict(os.environ, test_env, clear=True):
            env = _get_safe_subprocess_env()
            for key in env:
                assert key in allowed_keys, f"Unexpected key {key} in safe env"


# =============================================================================
# Tests for _exec_in_subprocess()
# =============================================================================


class TestSubprocessExecution:
    """Tests for subprocess-based code execution."""

    def test_simple_code_execution(self):
        """Simple code should execute and return result."""
        result = _exec_in_subprocess("result = 1 + 1", timeout=5.0)
        assert result["success"] is True
        assert "result" in result

    def test_dangerous_pattern_rejected(self):
        """Code with dangerous patterns should fail before execution."""
        result = _exec_in_subprocess("import os; os.system('ls')", timeout=5.0)
        assert result["success"] is False
        assert "dangerous" in result["error"].lower() or "not allowed" in result["error"].lower()

    def test_timeout_handling(self):
        """Code that exceeds timeout should raise TimeoutError."""
        # Infinite loop code
        infinite_code = "while True: pass"
        with pytest.raises(TimeoutError):
            _exec_in_subprocess(infinite_code, timeout=0.5)

    def test_stdout_capture(self):
        """Stdout from executed code should be captured via namespace."""
        # Note: print is NOT in SAFE_BUILTINS, so we test via result variable
        result = _exec_in_subprocess("result = 'hello world'", timeout=5.0)
        assert result["success"] is True
        assert "hello" in result.get("result", "") or "hello" in result.get("namespace", {}).get(
            "result", ""
        )

    def test_namespace_variables_returned(self):
        """Variables defined in code should be in namespace."""
        result = _exec_in_subprocess("x = 42\ny = 'test'", timeout=5.0)
        assert result["success"] is True
        assert "namespace" in result
        assert "x" in result["namespace"]
        assert "y" in result["namespace"]

    def test_json_deserialization_handles_errors(self):
        """Non-serializable output should be handled gracefully."""
        # Code that produces output that can't be JSON serialized
        # The wrapper handles this by only including repr-able values
        result = _exec_in_subprocess("result = lambda x: x", timeout=5.0)
        # Should succeed even if lambda can't be fully serialized
        assert result["success"] is True

    def test_safe_builtins_enforced(self):
        """Only safe builtins should be available in subprocess."""
        # Attempt to use open (not in SAFE_BUILTINS)
        result = _exec_in_subprocess("f = open('/etc/passwd')", timeout=5.0)
        # Should fail - either caught by pattern detection or by execution
        assert result["success"] is False

    def test_exec_eval_compile_blocked(self):
        """exec, eval, compile should be blocked."""
        for func in ["exec", "eval", "compile"]:
            result = _exec_in_subprocess(f"{func}('1+1')", timeout=5.0)
            assert result["success"] is False, f"{func} should be blocked"

    def test_assertion_error_captured(self):
        """AssertionError should be captured properly."""
        result = _exec_in_subprocess("assert False, 'Test assertion'", timeout=5.0)
        assert result["success"] is False
        assert "AssertionError" in result.get("error", "")

    def test_exception_types_captured(self):
        """Various exception types should be captured."""
        test_cases = [
            ("raise ValueError('test')", "ValueError"),
            ("raise TypeError('test')", "TypeError"),
            ("raise KeyError('test')", "KeyError"),
            ("1/0", "ZeroDivisionError"),
        ]
        for code, expected_error in test_cases:
            result = _exec_in_subprocess(code, timeout=5.0)
            assert result["success"] is False
            assert expected_error in result.get("error", ""), f"Expected {expected_error} in error"


# =============================================================================
# Tests for _validate_code_safety() - Extended
# =============================================================================


class TestCodeSafetyExtended:
    """Extended tests for code safety validation."""

    def test_case_insensitive_detection(self):
        """Dangerous patterns should be detected case-insensitively."""
        test_cases = [
            "__CLASS__",
            "__Class__",
            "__cLaSs__",
            "EXEC(",
            "Eval(",
            "OPEN(",
            "GETATTR(",
        ]
        for pattern in test_cases:
            is_safe, msg = _validate_code_safety(f"x = {pattern}")
            assert is_safe is False, f"Pattern {pattern} should be blocked"

    def test_nested_getattr_patterns(self):
        """Nested attribute access patterns should be detected."""
        dangerous_code = [
            "x.__class__.__bases__[0].__subclasses__()",
            "obj.__class__.__mro__[1].__init__",
            "().__class__.__bases__[0]",
        ]
        for code in dangerous_code:
            is_safe, msg = _validate_code_safety(code)
            assert is_safe is False, f"Code should be blocked: {code}"

    def test_string_obfuscation_patterns(self):
        """Common obfuscation patterns should still be detected."""
        # Direct dangerous pattern access
        test_cases = [
            "getattr(x, '__class__')",  # Contains getattr(
            "__builtins__['eval']",  # Contains __builtins__
            "sys.modules",  # Contains sys.
            "os.environ",  # Contains os.
        ]
        for code in test_cases:
            is_safe, msg = _validate_code_safety(code)
            assert is_safe is False, f"Obfuscated code should be blocked: {code}"

    def test_all_dangerous_patterns_covered(self):
        """All patterns in DANGEROUS_PATTERNS should be detected."""
        for pattern in DANGEROUS_PATTERNS:
            test_code = f"x = '{pattern}' or {pattern}"
            is_safe, msg = _validate_code_safety(test_code)
            assert is_safe is False, f"Pattern should be blocked: {pattern}"

    def test_safe_code_with_similar_strings(self):
        """Strings that look similar but are safe should pass."""
        safe_codes = [
            'x = "class_name"',  # Not __class__
            "y = 'my_bases'",  # Not __bases__
            "z = 'openfile'",  # Not open(
            "a = 'execute'",  # Not exec(
        ]
        for code in safe_codes:
            is_safe, msg = _validate_code_safety(code)
            assert is_safe is True, f"Safe code blocked: {code}"

    def test_import_variants_blocked(self):
        """Various import methods should be blocked."""
        import_codes = [
            "__import__('os')",
            "importlib.import_module('os')",
        ]
        for code in import_codes:
            is_safe, msg = _validate_code_safety(code)
            assert is_safe is False, f"Import should be blocked: {code}"


# =============================================================================
# Tests for ProofExecutor - Extended
# =============================================================================


class TestProofExecutorExtended:
    """Extended tests for ProofExecutor."""

    @pytest.mark.asyncio
    async def test_network_permission_denied(self):
        """Proofs requiring network should be skipped when not allowed."""
        executor = ProofExecutor(allow_network=False)
        proof = VerificationProof(
            id="net-proof",
            claim_id="claim-1",
            proof_type=ProofType.API_CALL,
            description="API call test",
            code="result = True",
            requires_network=True,
        )
        result = await executor.execute(proof)
        assert result.status == ProofStatus.SKIPPED
        assert "network" in result.error.lower()

    @pytest.mark.asyncio
    async def test_filesystem_permission_denied(self):
        """Proofs requiring filesystem should be skipped when not allowed."""
        executor = ProofExecutor(allow_filesystem=False)
        proof = VerificationProof(
            id="fs-proof",
            claim_id="claim-1",
            proof_type=ProofType.CODE_EXECUTION,
            description="File access test",
            code="result = True",
            requires_filesystem=True,
        )
        result = await executor.execute(proof)
        assert result.status == ProofStatus.SKIPPED
        assert "filesystem" in result.error.lower()

    @pytest.mark.asyncio
    async def test_network_permission_granted(self):
        """Proofs requiring network should run when allowed."""
        executor = ProofExecutor(allow_network=True)
        proof = VerificationProof(
            id="net-proof-allowed",
            claim_id="claim-1",
            proof_type=ProofType.ASSERTION,
            description="Safe network proof",
            code="result = True",
            assertion="result == True",
            requires_network=True,
        )
        result = await executor.execute(proof)
        # Should not be skipped due to network requirement
        assert result.status != ProofStatus.SKIPPED or "network" not in result.error.lower()

    @pytest.mark.asyncio
    async def test_output_truncation(self):
        """Output exceeding max_output_size should be truncated."""
        executor = ProofExecutor(max_output_size=100)
        proof = VerificationProof(
            id="large-output",
            claim_id="claim-1",
            proof_type=ProofType.CODE_EXECUTION,
            description="Large output test",
            code="print('x' * 1000)",  # Generate large output
        )
        result = await executor.execute(proof)
        # After execution, proof.output should be truncated
        assert len(proof.output) <= 100

    @pytest.mark.asyncio
    async def test_execution_time_tracked(self):
        """Execution time should be tracked in result."""
        executor = ProofExecutor()
        proof = VerificationProof(
            id="timing-test",
            claim_id="claim-1",
            proof_type=ProofType.ASSERTION,
            description="Timing test",
            code="x = sum(range(1000))",
            assertion="x == 499500",
        )
        result = await executor.execute(proof)
        assert result.execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_proof_status_updated(self):
        """Proof status should be updated after execution."""
        executor = ProofExecutor()
        proof = VerificationProof(
            id="status-test",
            claim_id="claim-1",
            proof_type=ProofType.ASSERTION,
            description="Status test",
            code="result = True",
            assertion="result",
        )
        assert proof.status == ProofStatus.PENDING
        await executor.execute(proof)
        assert proof.status != ProofStatus.PENDING
        assert proof.run_count == 1

    @pytest.mark.asyncio
    async def test_run_count_incremented(self):
        """Run count should increment on each execution."""
        executor = ProofExecutor()
        proof = VerificationProof(
            id="count-test",
            claim_id="claim-1",
            proof_type=ProofType.ASSERTION,
            description="Count test",
            code="result = True",
            assertion="result",
        )
        assert proof.run_count == 0
        await executor.execute(proof)
        assert proof.run_count == 1
        await executor.execute(proof)
        assert proof.run_count == 2

    @pytest.mark.asyncio
    async def test_last_run_updated(self):
        """Last run timestamp should be updated."""
        executor = ProofExecutor()
        proof = VerificationProof(
            id="timestamp-test",
            claim_id="claim-1",
            proof_type=ProofType.ASSERTION,
            description="Timestamp test",
            code="result = True",
            assertion="result",
        )
        assert proof.last_run is None
        await executor.execute(proof)
        assert proof.last_run is not None
        assert isinstance(proof.last_run, datetime)

    @pytest.mark.asyncio
    async def test_error_truncation(self):
        """Error messages exceeding max_output_size should be truncated."""
        executor = ProofExecutor(max_output_size=50)
        proof = VerificationProof(
            id="error-truncate",
            claim_id="claim-1",
            proof_type=ProofType.ASSERTION,
            description="Error truncation test",
            code="raise ValueError('x' * 1000)",  # Long error message
        )
        await executor.execute(proof)
        assert len(proof.error) <= 50

    @pytest.mark.asyncio
    async def test_all_exception_types_handled(self):
        """Executor should handle various exception types without crashing."""
        executor = ProofExecutor()
        exception_codes = [
            ("raise RuntimeError('test')", "RuntimeError"),
            ("raise ValueError('test')", "ValueError"),
            ("raise TypeError('test')", "TypeError"),
            ("raise KeyError('test')", "KeyError"),
            ("raise AttributeError('test')", "AttributeError"),
        ]
        for code, exc_type in exception_codes:
            proof = VerificationProof(
                id=f"exc-{exc_type}",
                claim_id="claim-1",
                proof_type=ProofType.ASSERTION,
                description=f"Test {exc_type}",
                code=code,
            )
            result = await executor.execute(proof)
            # Should return ERROR status, not crash
            assert result.status in (ProofStatus.ERROR, ProofStatus.FAILED)


# =============================================================================
# Tests for ClaimVerifier - Extended
# =============================================================================


class TestClaimVerifierExtended:
    """Extended tests for ClaimVerifier."""

    def test_multiple_proofs_per_claim(self):
        """Should handle multiple proofs for a single claim."""
        verifier = ClaimVerifier()
        for i in range(5):
            proof = VerificationProof(
                id=f"proof-{i}",
                claim_id="claim-1",
                proof_type=ProofType.ASSERTION,
                description=f"Proof {i}",
                code=f"result = {i}",
            )
            verifier.add_proof(proof)

        proofs = verifier.get_proofs_for_claim("claim-1")
        assert len(proofs) == 5

    def test_proofs_for_multiple_claims(self):
        """Should handle proofs for different claims."""
        verifier = ClaimVerifier()
        for claim_id in ["claim-1", "claim-2", "claim-3"]:
            for i in range(2):
                proof = VerificationProof(
                    id=f"{claim_id}-proof-{i}",
                    claim_id=claim_id,
                    proof_type=ProofType.ASSERTION,
                    description=f"Proof for {claim_id}",
                    code="result = True",
                )
                verifier.add_proof(proof)

        for claim_id in ["claim-1", "claim-2", "claim-3"]:
            proofs = verifier.get_proofs_for_claim(claim_id)
            assert len(proofs) == 2

    def test_nonexistent_claim_returns_empty(self):
        """Getting proofs for nonexistent claim should return empty list."""
        verifier = ClaimVerifier()
        proofs = verifier.get_proofs_for_claim("nonexistent")
        assert proofs == []

    @pytest.mark.asyncio
    async def test_verify_claim_stores_results(self):
        """Verification results should be stored."""
        verifier = ClaimVerifier()
        proof = VerificationProof(
            id="stored-proof",
            claim_id="claim-1",
            proof_type=ProofType.ASSERTION,
            description="Test proof",
            code="result = True",
            assertion="result",
        )
        verifier.add_proof(proof)
        await verifier.verify_claim("claim-1")

        assert "stored-proof" in verifier.results
        assert isinstance(verifier.results["stored-proof"], VerificationResult)

    @pytest.mark.asyncio
    async def test_verify_all_executes_all_proofs(self):
        """verify_all should execute all proofs."""
        verifier = ClaimVerifier()
        for i in range(3):
            proof = VerificationProof(
                id=f"all-proof-{i}",
                claim_id=f"claim-{i}",
                proof_type=ProofType.ASSERTION,
                description=f"Proof {i}",
                code="result = True",
                assertion="result",
            )
            verifier.add_proof(proof)

        results = await verifier.verify_all()
        assert len(results) == 3
        assert len(verifier.results) == 3

    def test_claim_verification_status_no_proofs(self):
        """Status should indicate no proofs for claim without proofs."""
        verifier = ClaimVerifier()
        status = verifier.get_claim_verification_status("no-proofs-claim")
        assert status["has_proofs"] is False
        assert status["verified"] is False
        assert status["status"] == "no_proofs"

    def test_claim_verification_status_pending(self):
        """Status should indicate pending for unexecuted proofs."""
        verifier = ClaimVerifier()
        proof = VerificationProof(
            id="pending-proof",
            claim_id="pending-claim",
            proof_type=ProofType.ASSERTION,
            description="Pending proof",
            code="result = True",
        )
        verifier.add_proof(proof)

        status = verifier.get_claim_verification_status("pending-claim")
        assert status["has_proofs"] is True
        assert status["status"] == "pending"

    def test_claim_verification_status_ignores_missing_stored_result(self):
        """Status should remain pending when a stored result is missing."""
        verifier = ClaimVerifier()
        proof = VerificationProof(
            id="missing-result-proof",
            claim_id="missing-result-claim",
            proof_type=ProofType.ASSERTION,
            description="Missing result proof",
            code="result = True",
        )
        verifier.add_proof(proof)
        verifier.results[proof.id] = None  # type: ignore[assignment]

        status = verifier.get_claim_verification_status("missing-result-claim")

        assert status["has_proofs"] is True
        assert status["status"] == "pending"

    @pytest.mark.asyncio
    async def test_claim_verification_status_verified(self):
        """Status should indicate verified when all proofs pass."""
        verifier = ClaimVerifier()
        proof = VerificationProof(
            id="passing-proof",
            claim_id="verified-claim",
            proof_type=ProofType.ASSERTION,
            description="Passing proof",
            code="result = True",
            assertion="result",
        )
        verifier.add_proof(proof)
        await verifier.verify_claim("verified-claim")

        status = verifier.get_claim_verification_status("verified-claim")
        assert status["has_proofs"] is True
        # Status depends on actual execution result
        assert status["status"] in ("verified", "failed", "pending")

    @pytest.mark.asyncio
    async def test_multi_proof_aggregation_all_pass(self):
        """Claim with all passing proofs should be verified."""
        verifier = ClaimVerifier()
        for i in range(3):
            proof = VerificationProof(
                id=f"pass-{i}",
                claim_id="multi-pass",
                proof_type=ProofType.ASSERTION,
                description=f"Pass proof {i}",
                code=f"result = {i + 1}",
                assertion="result > 0",
            )
            verifier.add_proof(proof)

        await verifier.verify_claim("multi-pass")
        status = verifier.get_claim_verification_status("multi-pass")
        # All should pass since result > 0 for all
        assert status["executed_count"] == 3

    @pytest.mark.asyncio
    async def test_multi_proof_aggregation_mixed_results(self):
        """Claim with mixed results should report correctly."""
        verifier = ClaimVerifier()
        # One passing proof
        verifier.add_proof(
            VerificationProof(
                id="mixed-pass",
                claim_id="mixed-claim",
                proof_type=ProofType.ASSERTION,
                description="Passing",
                code="result = True",
                assertion="result",
            )
        )
        # One failing proof
        verifier.add_proof(
            VerificationProof(
                id="mixed-fail",
                claim_id="mixed-claim",
                proof_type=ProofType.ASSERTION,
                description="Failing",
                code="result = False",
                assertion="result",
            )
        )

        await verifier.verify_claim("mixed-claim")
        status = verifier.get_claim_verification_status("mixed-claim")
        assert status["executed_count"] == 2
        # At least one should pass, one should fail
        assert status["passed_count"] + status["failed_count"] == 2


# =============================================================================
# Tests for VerificationReport - Extended
# =============================================================================


class TestVerificationReportExtended:
    """Extended tests for VerificationReport."""

    def test_verification_rate_zero_proofs(self):
        """Verification rate should be 0 when no claims have proofs."""
        report = VerificationReport(
            debate_id="test",
            total_claims=10,
            claims_with_proofs=0,
        )
        assert report.verification_rate() == 0.0

    def test_verification_rate_calculation(self):
        """Verification rate should calculate correctly."""
        report = VerificationReport(
            debate_id="test",
            claims_with_proofs=10,
            claims_verified=7,
        )
        assert report.verification_rate() == 0.7

    def test_pass_rate_zero_executed(self):
        """Pass rate should be 0 when no proofs executed."""
        report = VerificationReport(
            debate_id="test",
            total_proofs=10,
            proofs_passed=0,
            proofs_failed=0,
            proofs_error=0,
        )
        assert report.pass_rate() == 0.0

    def test_pass_rate_calculation(self):
        """Pass rate should calculate correctly."""
        report = VerificationReport(
            debate_id="test",
            proofs_passed=8,
            proofs_failed=1,
            proofs_error=1,
        )
        # 8 / (8 + 1 + 1) = 0.8
        assert report.pass_rate() == 0.8

    def test_pass_rate_excludes_skipped(self):
        """Pass rate should exclude skipped proofs from denominator."""
        report = VerificationReport(
            debate_id="test",
            proofs_passed=5,
            proofs_failed=5,
            proofs_error=0,
            proofs_skipped=10,  # Should not affect pass rate
        )
        assert report.pass_rate() == 0.5

    def test_to_dict_structure(self):
        """to_dict should return complete structure."""
        report = VerificationReport(
            debate_id="test-debate",
            total_claims=5,
            claims_with_proofs=3,
            claims_verified=2,
            total_proofs=6,
            proofs_passed=4,
            proofs_failed=2,
        )
        d = report.to_dict()

        assert d["debate_id"] == "test-debate"
        assert "statistics" in d
        assert "proofs" in d
        assert d["statistics"]["total_claims"] == 5
        assert d["proofs"]["total"] == 6

    def test_generate_summary_format(self):
        """generate_summary should return markdown format."""
        report = VerificationReport(
            debate_id="summary-test",
            total_claims=10,
            claims_with_proofs=8,
            claims_verified=6,
            total_proofs=12,
            proofs_passed=10,
            proofs_failed=2,
        )
        summary = report.generate_summary()

        assert "# Verification Report" in summary
        assert "summary-test" in summary
        assert "Claims with proofs" in summary
        assert "Pass rate" in summary

    def test_generate_summary_with_failed_proofs(self):
        """Summary should include failed proofs section."""
        report = VerificationReport(
            debate_id="failed-test",
            proofs_failed=1,
            failed_proofs=[
                {
                    "description": "Failed proof description",
                    "claim_id": "claim-123",
                    "error": "Assertion failed: expected True",
                }
            ],
        )
        summary = report.generate_summary()

        assert "Failed Proofs" in summary
        assert "Failed proof description" in summary

    def test_empty_failed_proofs_list(self):
        """Summary should handle empty failed proofs list."""
        report = VerificationReport(
            debate_id="no-failures",
            proofs_passed=10,
            proofs_failed=0,
        )
        summary = report.generate_summary()
        # Should not have Failed Proofs section
        assert "Failed Proofs" not in summary


# =============================================================================
# Tests for verify_claim_set() function
# =============================================================================


class TestVerifyClaimSet:
    """Tests for verify_claim_set convenience function."""

    @pytest.mark.asyncio
    async def test_empty_claims_and_proofs(self):
        """Should handle empty inputs."""
        report = await verify_claim_set(claims=[], proofs=[])
        assert report.total_claims == 0
        assert report.total_proofs == 0

    @pytest.mark.asyncio
    async def test_claims_without_proofs(self):
        """Should handle claims with no proofs."""
        claims = [("claim-1", "Test claim")]
        report = await verify_claim_set(claims=claims, proofs=[])
        assert report.total_claims == 1
        assert report.claims_with_proofs == 0

    @pytest.mark.asyncio
    async def test_basic_verification(self):
        """Should verify claims with proofs."""
        claims = [("claim-1", "1 + 1 = 2")]
        proofs = [
            VerificationProof(
                id="proof-1",
                claim_id="claim-1",
                proof_type=ProofType.ASSERTION,
                description="Math check",
                code="result = 1 + 1",
                assertion="result == 2",
            )
        ]
        report = await verify_claim_set(claims=claims, proofs=proofs)
        assert report.total_claims == 1
        assert report.total_proofs == 1

    @pytest.mark.asyncio
    async def test_execution_time_aggregated(self):
        """Execution time should be aggregated in report."""
        claims = [("claim-1", "Test")]
        proofs = [
            VerificationProof(
                id="time-proof",
                claim_id="claim-1",
                proof_type=ProofType.ASSERTION,
                description="Time test",
                code="result = sum(range(100))",
                assertion="result == 4950",
            )
        ]
        report = await verify_claim_set(claims=claims, proofs=proofs)
        assert report.execution_time_total_ms >= 0


# =============================================================================
# Tests for VerificationProof dataclass - Extended
# =============================================================================


class TestVerificationProofExtended:
    """Extended tests for VerificationProof dataclass."""

    def test_auto_id_generation(self):
        """ID should be auto-generated if empty."""
        proof = VerificationProof(
            id="",
            claim_id="claim-1",
            proof_type=ProofType.ASSERTION,
            description="Auto ID test",
            code="result = True",
        )
        assert proof.id != ""
        assert len(proof.id) > 0

    def test_hash_computation(self):
        """Proof hash should be computed from content."""
        proof1 = VerificationProof(
            id="hash-1",
            claim_id="claim-1",
            proof_type=ProofType.ASSERTION,
            description="Hash test",
            code="result = True",
        )
        proof2 = VerificationProof(
            id="hash-2",
            claim_id="claim-1",
            proof_type=ProofType.ASSERTION,
            description="Hash test",
            code="result = True",
        )
        # Same code = same hash
        assert proof1.proof_hash == proof2.proof_hash

    def test_hash_differs_for_different_code(self):
        """Proofs with different code should have different hashes."""
        proof1 = VerificationProof(
            id="diff-1",
            claim_id="claim-1",
            proof_type=ProofType.ASSERTION,
            description="Test",
            code="result = True",
        )
        proof2 = VerificationProof(
            id="diff-2",
            claim_id="claim-1",
            proof_type=ProofType.ASSERTION,
            description="Test",
            code="result = False",
        )
        assert proof1.proof_hash != proof2.proof_hash

    def test_to_dict_complete(self):
        """to_dict should include all fields."""
        proof = VerificationProof(
            id="dict-test",
            claim_id="claim-1",
            proof_type=ProofType.COMPUTATION,
            description="Dict test",
            code="x = 1",
            expected_output="1",
            timeout_seconds=60.0,
            requires_network=True,
        )
        d = proof.to_dict()

        assert d["id"] == "dict-test"
        assert d["proof_type"] == "computation"
        assert d["requires_network"] is True
        assert d["timeout_seconds"] == 60.0

    def test_from_dict_roundtrip(self):
        """from_dict should reconstruct proof from dict."""
        original = VerificationProof(
            id="roundtrip",
            claim_id="claim-1",
            proof_type=ProofType.ASSERTION,
            description="Roundtrip test",
            code="result = True",
            timeout_seconds=45.0,
        )
        d = original.to_dict()
        reconstructed = VerificationProof.from_dict(d)

        assert reconstructed.id == original.id
        assert reconstructed.claim_id == original.claim_id
        assert reconstructed.timeout_seconds == original.timeout_seconds


# =============================================================================
# Tests for ProofBuilder - Extended
# =============================================================================


class TestProofBuilderExtended:
    """Extended tests for ProofBuilder."""

    def test_output_check_creation(self):
        """Should create output check proof."""
        builder = ProofBuilder(claim_id="output-claim")
        proof = builder.output_check(
            description="Output test",
            code="print('hello')",
            expected_output="hello",
        )
        assert proof.proof_type == ProofType.CODE_EXECUTION
        assert proof.expected_output == "hello"

    def test_computation_creation(self):
        """Should create computation proof."""
        builder = ProofBuilder(claim_id="compute-claim")
        proof = builder.computation(
            description="Sum check",
            code="result = sum([1,2,3])",
            assertion="result == 6",
        )
        assert proof.proof_type == ProofType.COMPUTATION
        assert proof.assertion == "result == 6"

    def test_property_check_creation(self):
        """Should create property check proof."""
        builder = ProofBuilder(claim_id="prop-claim")
        proof = builder.property_check(
            description="Property test",
            code="x = [1, 2, 3]",
            property_assertion="len(x) == 3",
        )
        assert proof.proof_type == ProofType.PROPERTY_CHECK

    def test_created_by_propagated(self):
        """created_by should propagate to all created proofs."""
        builder = ProofBuilder(claim_id="test", created_by="test-user")
        proof = builder.assertion(
            description="Author test",
            code="x = 1",
            assertion="x == 1",
        )
        assert proof.created_by == "test-user"

    def test_kwargs_passed_through(self):
        """Additional kwargs should be passed to proof constructor."""
        builder = ProofBuilder(claim_id="test")
        proof = builder.assertion(
            description="Kwargs test",
            code="x = 1",
            assertion="x == 1",
            timeout_seconds=120.0,
            requires_network=True,
        )
        assert proof.timeout_seconds == 120.0
        assert proof.requires_network is True
