"""
Formal Verification Backends - Interface for theorem provers.

Provides a protocol for integrating formal proof assistants like Lean, Coq,
or Isabelle. Includes LLM-assisted translation for natural language claims.

IMPORTANT LIMITATIONS:
- LLM translations may produce valid proofs that don't match the original claim
- The `verify_claim()` method includes semantic verification to detect this
- Always check `is_high_confidence` property for reliable results
- For critical decisions, manually review the `formal_statement`

Usage:
    backend = LeanBackend()
    result = await backend.verify_claim("All prime numbers > 2 are odd")

    if result.is_high_confidence:
        print("Verified with high confidence")
    elif result.is_verified:
        print(f"Proof compiles but: {result.confidence_warning}")
    else:
        print(f"Verification failed: {result.error_message}")

Supported backends:
- LeanBackend: Lean 4 with LLM translation (DeepSeek-Prover, Claude, GPT-4)
- Z3Backend: Z3 SMT solver for decidable claims (arithmetic, logic)

Rationale (from aragora self-debate):
- LLM-to-Lean tools improving rapidly (DeepSeek-Prover-V2, LeanDojo)
- Trust differentiation: "machine-verified proof" is valuable signaling
- Semantic verification step prevents false positives from hallucination
- Can connect with ProvenanceManager for "verified provenance"
"""

from __future__ import annotations

__all__ = [
    "FormalProofStatus",
    "FormalLanguage",
    "FormalProofResult",
    "FormalVerificationBackend",
    "TranslationModel",
    "LeanBackend",
    "Z3Backend",
    "FormalVerificationManager",
    "get_formal_verification_manager",
]

import asyncio
import hashlib
import json
import logging
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from aragora.config import get_api_key
from aragora.models.compat import first_text_block

logger = logging.getLogger(__name__)


class FormalProofStatus(Enum):
    """Status of a formal proof attempt."""

    NOT_ATTEMPTED = "not_attempted"
    TRANSLATION_FAILED = "translation_failed"  # Couldn't translate to formal language
    PROOF_FOUND = "proof_found"
    PROOF_FAILED = "proof_failed"  # Theorem false or unprovable
    TIMEOUT = "timeout"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    NOT_SUPPORTED = "not_supported"  # Claim type not suitable for formal proof


class FormalLanguage(Enum):
    """Supported formal proof languages."""

    LEAN4 = "lean4"
    COQ = "coq"
    ISABELLE = "isabelle"
    AGDA = "agda"
    Z3_SMT = "z3_smt"  # SMT solver (simpler, more practical)


@dataclass
class FormalProofResult:
    """Result of a formal verification attempt."""

    status: FormalProofStatus
    language: FormalLanguage

    # The formal statement (if translation succeeded)
    formal_statement: str | None = None

    # The proof (if found)
    proof_text: str | None = None
    proof_hash: str | None = None  # For verification/caching

    # Timing
    translation_time_ms: float = 0.0
    proof_search_time_ms: float = 0.0

    # Error info
    error_message: str = ""

    # Metadata
    prover_version: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    # Translation confidence and verification (for LLM-translated proofs)
    # WARNING: LLM-translated proofs may not semantically match the original claim.
    # A high confidence score requires both successful compilation AND semantic alignment.
    translation_confidence: float = 0.0  # 0.0-1.0, how confident is the translation
    original_claim: str = ""  # The natural language claim that was translated
    semantic_match_verified: bool = False  # Whether we verified the theorem matches the claim
    confidence_warning: str = ""  # Warning if confidence is low

    @property
    def is_verified(self) -> bool:
        """Check if proof is formally verified. Note: this only means the proof compiles."""
        return self.status == FormalProofStatus.PROOF_FOUND

    @property
    def is_high_confidence(self) -> bool:
        """Check if this is a high-confidence verification (>0.8 and semantically verified)."""
        return (
            self.is_verified and self.translation_confidence >= 0.8 and self.semantic_match_verified
        )

    def to_dict(self) -> dict:
        result = {
            "status": self.status.value,
            "language": self.language.value,
            "formal_statement": self.formal_statement,
            "proof_hash": self.proof_hash,
            "is_verified": self.is_verified,
            "translation_time_ms": self.translation_time_ms,
            "proof_search_time_ms": self.proof_search_time_ms,
            "error_message": self.error_message,
            "prover_version": self.prover_version,
            "timestamp": self.timestamp.isoformat(),
            # New confidence fields
            "translation_confidence": self.translation_confidence,
            "is_high_confidence": self.is_high_confidence,
            "semantic_match_verified": self.semantic_match_verified,
        }
        if self.confidence_warning:
            result["confidence_warning"] = self.confidence_warning
        if self.original_claim:
            result["original_claim"] = self.original_claim
        return result


@runtime_checkable
class FormalVerificationBackend(Protocol):
    """
    Protocol for formal proof backends.

    Implementations should handle:
    1. Translation: natural language claim → formal theorem
    2. Proof search: attempt to prove the theorem
    3. Verification: check that a proof is valid

    Example future implementations:
    - LeanBackend: Lean 4 with LLM-assisted translation
    - Z3Backend: SMT solver for decidable fragments
    - MathlibLookup: Check if claim exists in Mathlib
    """

    @property
    def language(self) -> FormalLanguage:
        """The formal language this backend uses."""
        ...

    @property
    def is_available(self) -> bool:
        """Check if the backend is available (toolchain installed, etc.)."""
        ...

    def can_verify(self, claim: str, claim_type: str | None = None) -> bool:
        """
        Check if this backend can attempt to verify the claim.

        Args:
            claim: Natural language claim
            claim_type: Optional hint about claim type (math, logic, protocol, etc.)

        Returns:
            True if the backend should attempt verification
        """
        ...

    async def translate(self, claim: str, context: str = "") -> str | None:
        """
        Translate a natural language claim to a formal statement.

        Args:
            claim: Natural language claim
            context: Additional context to help translation

        Returns:
            Formal statement in the backend's language, or None if translation fails
        """
        ...

    async def prove(
        self, formal_statement: str, timeout_seconds: float = 60.0
    ) -> FormalProofResult:
        """
        Attempt to prove a formal statement.

        Args:
            formal_statement: Statement in the backend's formal language
            timeout_seconds: Maximum time for proof search

        Returns:
            FormalProofResult with status and proof if found
        """
        ...

    async def verify_proof(self, formal_statement: str, proof: str) -> bool:
        """
        Verify that a proof is valid for a statement.

        Args:
            formal_statement: The theorem to verify
            proof: The purported proof

        Returns:
            True if the proof is valid
        """
        ...


class TranslationModel(Enum):
    """Available models for NL-to-Lean translation."""

    DEEPSEEK_PROVER = "deepseek_prover"  # Best for mathematical proofs
    CLAUDE = "claude"  # General-purpose, good at reasoning
    OPENAI = "openai"  # GPT-4, solid alternative
    AUTO = "auto"  # Automatically select best available


class LeanBackend:
    """
    Lean 4 formal verification backend.

    Uses LLM-assisted translation to convert natural language claims to Lean 4
    theorems, then runs the Lean type checker to verify proofs.

    Features:
    - DeepSeek-Prover-V2 integration for state-of-the-art translation
    - Fallback to Claude/GPT-4 for translation
    - Sandboxed Lean execution with resource limits
    - Proof caching for repeated verification
    - Support for common mathematical patterns

    Prerequisites:
    - Lean 4 toolchain installed (lean, lake)
    - API key for translation (OPENROUTER_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY)
    """

    # Claim types suitable for Lean verification
    LEAN_CLAIM_TYPES = {
        "MATHEMATICAL",
        "LOGICAL",
        "ARITHMETIC",
        "PROOF",
        "THEOREM",
        "LEMMA",
        "PROPERTY",
        "INVARIANT",
    }

    # Patterns indicating mathematical content
    MATH_PATTERNS = [
        r"\bfor all\b",
        r"\bforall\b",
        r"\bexists\b",
        r"\bthere exists\b",
        r"\biff\b",
        r"\bimplies\b",
        r"\bif and only if\b",
        r"\bprove\b",
        r"\bproof\b",
        r"\btheorem\b",
        r"\blemma\b",
        r"\bprime\b",
        r"\bdivisible\b",
        r"\beven\b",
        r"\bodd\b",
        r"\bsum\b",
        r"\bproduct\b",
        r"\bintegral\b",
        r"\bderivative\b",
        r"[∀∃→←↔∧∨¬⊢⊨≡≠≤≥∈∉⊂⊃∩∪∅ℕℤℚℝℂ]",
    ]

    def __init__(
        self,
        sandbox_timeout: float = 60.0,
        sandbox_memory_mb: int = 1024,
        translation_model: TranslationModel = TranslationModel.AUTO,
    ):
        """
        Initialize Lean backend.

        Args:
            sandbox_timeout: Maximum seconds for Lean execution.
            sandbox_memory_mb: Memory limit for Lean process.
            translation_model: Which model to use for NL-to-Lean translation.
                              AUTO will prefer DeepSeek-Prover if available.
        """
        self._sandbox_timeout = sandbox_timeout
        self._sandbox_memory_mb = sandbox_memory_mb
        self._translation_model = translation_model
        self._proof_cache: dict[str, FormalProofResult] = {}
        self._lean_version: str | None = None
        self._deepseek_translator: Any | None = None

    @property
    def language(self) -> FormalLanguage:
        return FormalLanguage.LEAN4

    @property
    def is_available(self) -> bool:
        """Check if Lean 4 toolchain (lean and lake) is available."""
        import shutil

        has_lean = shutil.which("lean") is not None
        if has_lean and self._lean_version is None:
            try:
                result = subprocess.run(
                    ["lean", "--version"],  # noqa: S607 -- fixed command
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    self._lean_version = result.stdout.strip().split("\n")[0]
            except (subprocess.SubprocessError, OSError, FileNotFoundError) as e:
                logger.debug("Lean version check failed: %s", e)
        return has_lean

    @property
    def lean_version(self) -> str:
        """Get Lean version string."""
        if self._lean_version is None and self.is_available:
            pass  # is_available sets version
        return self._lean_version or "unknown"

    def can_verify(self, claim: str, claim_type: str | None = None) -> bool:
        """
        Check if this backend can attempt to verify the claim.

        Returns True for:
        - Claims with explicit mathematical claim types
        - Claims containing mathematical notation or keywords
        - Claims that appear to be theorems or proofs
        """
        import re

        if not self.is_available:
            return False

        # Check explicit claim type
        if claim_type and claim_type.upper() in self.LEAN_CLAIM_TYPES:
            return True

        # Check for mathematical patterns
        for pattern in self.MATH_PATTERNS:
            if re.search(pattern, claim, re.IGNORECASE):
                return True

        return False

    def _get_deepseek_translator(self) -> Any | None:
        """Get DeepSeek-Prover translator instance."""
        if self._deepseek_translator is None:
            try:
                from aragora.verification.deepseek_prover import DeepSeekProverTranslator

                translator = DeepSeekProverTranslator()
                if translator.is_available:
                    self._deepseek_translator = translator
            except ImportError:
                pass
        return self._deepseek_translator

    async def translate(self, claim: str, context: str = "") -> str | None:
        """
        Use LLM to translate a natural language claim to a Lean 4 theorem.

        Returns None if translation fails or no LLM is available.
        Example output: "theorem claim_123 : ∀ n : ℕ, n + 0 = n := by simp"

        Translation model selection (for AUTO mode):
        1. DeepSeek-Prover-V2 (best for mathematical proofs)
        2. Claude (fallback, good reasoning)
        3. GPT-4 (fallback)
        """
        from aragora.observability.http_client_pool import get_http_pool

        # Try DeepSeek-Prover first if configured
        if self._translation_model in (TranslationModel.AUTO, TranslationModel.DEEPSEEK_PROVER):
            translator = self._get_deepseek_translator()
            if translator:
                result = await translator.translate(claim, context)
                if result.success and result.lean_code:
                    logger.debug(
                        f"DeepSeek-Prover translation succeeded (confidence: {result.confidence:.2f})"
                    )
                    return result.lean_code
                elif self._translation_model == TranslationModel.DEEPSEEK_PROVER:
                    # Explicit DeepSeek selection but failed
                    logger.warning("DeepSeek-Prover translation failed: %s", result.error_message)
                    return None

        # Fall back to Claude/OpenAI
        api_key = get_api_key("ANTHROPIC_API_KEY", "OPENAI_API_KEY", required=False)
        if not api_key:
            return None

        # Create translation prompt
        prompt = f"""Translate the following natural language claim into a Lean 4 theorem with proof.

Claim: {claim}
{f"Context: {context}" if context else ""}

Requirements:
1. Use valid Lean 4 syntax (not Lean 3)
2. Include necessary imports (e.g., import Mathlib.Tactic)
3. Provide a complete proof using tactics like simp, ring, omega, decide, etc.
4. If the claim is false, prove its negation instead and note this
5. Keep theorem name simple (claim_1, main_theorem)

If the claim cannot be expressed as a Lean theorem, return exactly: UNTRANSLATABLE

Return ONLY the Lean 4 code, no explanations. Example:
```lean
import Mathlib.Tactic

theorem claim_1 : ∀ n : Nat, n + 0 = n := by simp
```"""

        try:
            anthropic_key = get_api_key("ANTHROPIC_API_KEY", required=False)
            openai_key = get_api_key("OPENAI_API_KEY", required=False)

            if anthropic_key:
                url = "https://api.anthropic.com/v1/messages"
                headers = {
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                }
                payload = {
                    "model": "claude-opus-5",
                    "max_tokens": 2048,
                    "messages": [{"role": "user", "content": prompt}],
                }
            elif openai_key:
                url = "https://api.openai.com/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": "gpt-4o",
                    "max_tokens": 2048,
                    "messages": [{"role": "user", "content": prompt}],
                }
            else:
                return None

            pool = get_http_pool()
            provider = "anthropic" if anthropic_key else "openai"
            async with pool.get_session(provider) as client:
                response = await client.post(url, json=payload, headers=headers, timeout=30)
                if response.status_code != 200:
                    logger.warning(
                        "LLM API returned status %s for Lean translation", response.status_code
                    )
                    return None

                try:
                    data = response.json()
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning("Failed to parse LLM API response as JSON: %s", e)
                    return None

                try:
                    if anthropic_key:
                        # Opus 5 thinks by default: content[0] is a thinking
                        # block, so scan for the text block. Absent text is the
                        # same failure the old content[0] KeyError signalled.
                        result = first_text_block(data.get("content")).strip()
                        if not result:
                            logger.warning(
                                "Anthropic response carried no text block for Lean translation"
                            )
                            return None
                    else:
                        result = data["choices"][0]["message"]["content"].strip()
                except (KeyError, IndexError, TypeError) as e:
                    logger.warning("Unexpected LLM response format for Lean translation: %s", e)
                    return None

                if "UNTRANSLATABLE" in result:
                    return None

                # Extract Lean code from markdown if present
                import re

                lean_match = re.search(r"```(?:lean4?|lean)?\n?(.*?)```", result, re.DOTALL)
                if lean_match:
                    return lean_match.group(1).strip()
                return result

        except (OSError, ConnectionError) as e:
            logger.warning("Network error translating claim to Lean 4: %s", e)
            return None
        except asyncio.TimeoutError:
            logger.warning("Timeout translating claim to Lean 4")
            return None
        except (ValueError, KeyError, TypeError, RuntimeError) as e:
            logger.warning("Failed to translate claim to Lean 4: %s: %s", type(e).__name__, e)
            return None

    async def prove(
        self, formal_statement: str, timeout_seconds: float = 60.0
    ) -> FormalProofResult:
        """
        Attempt to verify a Lean 4 theorem using the Lean type checker.

        Runs the Lean code in a sandboxed subprocess and checks if it
        type-checks successfully (meaning the proof is valid).

        Args:
            formal_statement: Lean 4 code with theorem and proof.
            timeout_seconds: Maximum time for Lean execution.

        Returns:
            FormalProofResult with verification status.
        """
        import time

        if not self.is_available:
            return FormalProofResult(
                status=FormalProofStatus.BACKEND_UNAVAILABLE,
                language=FormalLanguage.LEAN4,
                error_message="Lean 4 not installed. Install from https://leanprover.github.io/",
            )

        # Check cache
        cache_key = hashlib.sha256(formal_statement.encode()).hexdigest()
        if cache_key in self._proof_cache:
            cached = self._proof_cache[cache_key]
            logger.debug("Lean proof cache hit for %s", cache_key[:8])
            return cached

        start_time = time.time()

        try:
            from aragora.verification.sandbox import ProofSandbox, SandboxStatus

            sandbox = ProofSandbox(
                timeout=timeout_seconds,
                memory_mb=self._sandbox_memory_mb,
            )

            result = await sandbox.execute_lean(formal_statement)
            elapsed_ms = (time.time() - start_time) * 1000

            if result.status == SandboxStatus.TIMEOUT:
                proof_result = FormalProofResult(
                    status=FormalProofStatus.TIMEOUT,
                    language=FormalLanguage.LEAN4,
                    formal_statement=formal_statement,
                    proof_search_time_ms=elapsed_ms,
                    error_message=f"Lean execution exceeded {timeout_seconds}s timeout",
                    prover_version=self.lean_version,
                )
            elif result.status == SandboxStatus.SETUP_FAILED:
                proof_result = FormalProofResult(
                    status=FormalProofStatus.BACKEND_UNAVAILABLE,
                    language=FormalLanguage.LEAN4,
                    formal_statement=formal_statement,
                    error_message=result.error_message,
                    prover_version=self.lean_version,
                )
            elif result.is_success:
                # Lean returned 0 = proof type-checked successfully
                proof_hash = hashlib.sha256(formal_statement.encode()).hexdigest()[:16]
                proof_result = FormalProofResult(
                    status=FormalProofStatus.PROOF_FOUND,
                    language=FormalLanguage.LEAN4,
                    formal_statement=formal_statement,
                    proof_text=formal_statement,
                    proof_hash=proof_hash,
                    proof_search_time_ms=elapsed_ms,
                    prover_version=self.lean_version,
                )
            else:
                # Lean returned non-zero = type error or proof failure
                error_msg = result.stderr or result.stdout or "Unknown error"
                # Check for common error patterns
                if "sorry" in error_msg.lower() or "declaration uses 'sorry'" in error_msg:
                    error_msg = "Proof incomplete (contains 'sorry')"
                elif "type mismatch" in error_msg.lower():
                    error_msg = f"Type error in proof: {error_msg[:200]}"

                proof_result = FormalProofResult(
                    status=FormalProofStatus.PROOF_FAILED,
                    language=FormalLanguage.LEAN4,
                    formal_statement=formal_statement,
                    proof_search_time_ms=elapsed_ms,
                    error_message=error_msg[:500],
                    prover_version=self.lean_version,
                )

            # Cache the result
            self._proof_cache[cache_key] = proof_result
            return proof_result

        except ImportError:
            return FormalProofResult(
                status=FormalProofStatus.BACKEND_UNAVAILABLE,
                language=FormalLanguage.LEAN4,
                formal_statement=formal_statement,
                error_message="ProofSandbox not available",
            )
        except (RuntimeError, ValueError, OSError) as e:
            return FormalProofResult(
                status=FormalProofStatus.BACKEND_UNAVAILABLE,
                language=FormalLanguage.LEAN4,
                formal_statement=formal_statement,
                error_message=f"Lean execution error: {type(e).__name__}: {e}",
                prover_version=self.lean_version,
            )

    async def verify_proof(self, formal_statement: str, proof: str) -> bool:
        """
        Verify that a proof is valid by re-running Lean.

        For Lean, we combine the statement and proof and check if it type-checks.
        """
        # If proof is separate from statement, combine them
        if proof and proof.strip() not in formal_statement:
            full_code = f"{formal_statement}\n\n{proof}"
        else:
            full_code = formal_statement

        result = await self.prove(full_code, timeout_seconds=30.0)
        return result.status == FormalProofStatus.PROOF_FOUND

    def clear_cache(self) -> int:
        """Clear the proof cache. Returns number of entries cleared."""
        count = len(self._proof_cache)
        self._proof_cache.clear()
        return count

    async def verify_semantic_match(
        self, original_claim: str, formal_statement: str
    ) -> tuple[bool, float, str]:
        """
        Verify that a formal statement semantically matches the original claim.

        Uses LLM to check if the theorem actually proves what was claimed.
        This is essential because LLM translation may produce valid Lean code
        that proves something entirely different from the original claim.

        Args:
            original_claim: The natural language claim.
            formal_statement: The Lean 4 code produced by translation.

        Returns:
            Tuple of (matches, confidence, explanation)
            - matches: True if the theorem appears to prove the claim
            - confidence: 0.0-1.0 confidence in the match
            - explanation: Why it matches or doesn't match
        """
        from aragora.observability.http_client_pool import get_http_pool

        api_key = get_api_key("ANTHROPIC_API_KEY", "OPENAI_API_KEY", required=False)
        if not api_key:
            # Can't verify without LLM - return low confidence
            return False, 0.3, "No LLM available to verify semantic match"

        prompt = f"""Analyze whether this Lean 4 theorem actually proves the given natural language claim.

ORIGINAL CLAIM: {original_claim}

LEAN 4 CODE:
```lean
{formal_statement}
```

Answer these questions:
1. Does the theorem statement (the part after the colon) logically correspond to the claim?
2. Is the theorem trivially true (e.g., 1=1) rather than proving the actual claim?
3. Does the proof actually prove the stated theorem (not just compile)?

Respond in this exact format:
MATCHES: YES or NO
CONFIDENCE: 0.0 to 1.0
EXPLANATION: Brief explanation (1-2 sentences)

Examples of NON-MATCHING:
- Claim "all primes > 2 are odd" but theorem proves "1 = 1"
- Claim "x + y = y + x" but theorem proves unrelated property
- Proof uses 'sorry' (incomplete proof)

Examples of MATCHING:
- Claim about addition commutativity and theorem proves ∀ a b, a + b = b + a
- Claim about prime divisibility and theorem proves corresponding property"""

        try:
            anthropic_key = get_api_key("ANTHROPIC_API_KEY", required=False)
            openai_key = get_api_key("OPENAI_API_KEY", required=False)

            if anthropic_key:
                url = "https://api.anthropic.com/v1/messages"
                headers = {
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                }
                payload = {
                    "model": "claude-opus-5",
                    # Opus 5 thinks by default; max_tokens covers thinking +
                    # response, so keep headroom.
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                }
            else:
                url = "https://api.openai.com/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": "gpt-4o",
                    "max_tokens": 512,
                    "messages": [{"role": "user", "content": prompt}],
                }

            pool = get_http_pool()
            provider = "anthropic" if anthropic_key else "openai"
            async with pool.get_session(provider) as client:
                response = await client.post(url, json=payload, headers=headers, timeout=30)
                if response.status_code != 200:
                    return False, 0.3, f"LLM API error: status {response.status_code}"

                data = response.json()

                if anthropic_key:
                    # Opus 5 thinks by default: content[0] is a thinking block,
                    # so scan for the text block.
                    result = first_text_block(data.get("content")).strip()
                    if not result:
                        return False, 0.3, "LLM response carried no text block"
                else:
                    result = data["choices"][0]["message"]["content"].strip()

                # Parse response
                import re

                matches_match = re.search(r"MATCHES:\s*(YES|NO)", result, re.IGNORECASE)
                conf_match = re.search(r"CONFIDENCE:\s*([0-9.]+)", result)
                expl_match = re.search(r"EXPLANATION:\s*(.+?)(?:\n|$)", result, re.DOTALL)

                matches = bool(matches_match and matches_match.group(1).upper() == "YES")
                confidence = float(conf_match.group(1)) if conf_match else 0.5
                explanation = (
                    expl_match.group(1).strip() if expl_match else "Unable to parse explanation"
                )

                return matches, min(1.0, max(0.0, confidence)), explanation

        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
            logger.warning("Semantic verification failed: %s", e)
            return False, 0.3, f"Verification error: {e}"

    async def verify_claim(
        self, claim: str, context: str = "", verify_semantic_match: bool = True
    ) -> FormalProofResult:
        """
        Complete verification pipeline: translate, prove, and verify semantic match.

        This is the recommended entry point for verifying natural language claims.
        It includes all safety checks to avoid false positives from LLM hallucination.

        Args:
            claim: Natural language claim to verify.
            context: Optional context to help translation.
            verify_semantic_match: Whether to verify the theorem matches the claim.
                                   Set to False only for debugging/testing.

        Returns:
            FormalProofResult with confidence information.

        IMPORTANT LIMITATIONS:
        - LLM translation may produce theorems that don't match the original claim
        - Even with semantic verification, there's no guarantee of correctness
        - Use is_high_confidence property to check for reliable results
        - Always review formal_statement manually for critical decisions
        """
        import time

        start_time = time.time()

        # Step 1: Translate claim to Lean
        formal_statement = await self.translate(claim, context)
        translation_time_ms = (time.time() - start_time) * 1000

        if formal_statement is None:
            return FormalProofResult(
                status=FormalProofStatus.TRANSLATION_FAILED,
                language=FormalLanguage.LEAN4,
                original_claim=claim,
                translation_time_ms=translation_time_ms,
                error_message="Failed to translate claim to Lean 4",
                translation_confidence=0.0,
                confidence_warning="Translation failed - claim may not be suitable for formal verification",
            )

        # Step 2: Prove the translated theorem
        proof_result = await self.prove(formal_statement)
        proof_result.original_claim = claim
        proof_result.translation_time_ms = translation_time_ms

        if proof_result.status != FormalProofStatus.PROOF_FOUND:
            proof_result.translation_confidence = 0.3  # Low confidence on failed proofs
            proof_result.confidence_warning = f"Proof failed: {proof_result.error_message}"
            return proof_result

        # Step 3: Verify semantic match (optional but recommended)
        if verify_semantic_match:
            matches, confidence, explanation = await self.verify_semantic_match(
                claim, formal_statement
            )
            proof_result.semantic_match_verified = matches
            proof_result.translation_confidence = confidence

            if not matches:
                proof_result.confidence_warning = (
                    f"WARNING: The proven theorem may not match the original claim. {explanation}"
                )
                logger.warning(
                    "Lean proof compiled but may not match claim: %s (claim: %s...)",
                    explanation,
                    claim[:50],
                )
            elif confidence < 0.8:
                proof_result.confidence_warning = (
                    f"Moderate confidence ({confidence:.0%}): {explanation}"
                )
        else:
            # Without verification, assign low confidence
            proof_result.translation_confidence = 0.5
            proof_result.confidence_warning = (
                "Semantic verification skipped - proof validity not confirmed"
            )

        return proof_result


class Z3Backend:
    """
    Z3 SMT solver backend for decidable verification.

    Handles decidable fragments of first-order logic:
    - Linear/nonlinear arithmetic
    - Boolean satisfiability
    - Bitvector operations
    - Array theory
    - Quantifier-free theories

    Good for claims like:
    - "If X > Y and Y > Z, then X > Z"
    - "This function returns a value in range [0, 100]"
    - "These constraints have no solution"

    Translation strategy:
    1. If claim is already SMT-LIB2 format, use directly
    2. If LLM translator is provided, use it for natural language
    3. Fall back to pattern-based translation for simple claims
    """

    def __init__(
        self,
        llm_translator: Any | None = None,
        cache_size: int = 100,
        cache_ttl_seconds: float = 3600.0,
    ):
        """
        Initialize Z3 backend.

        Args:
            llm_translator: Optional async callable(claim, context) -> str
                           for LLM-assisted translation to SMT-LIB2
            cache_size: Maximum number of proof results to cache
            cache_ttl_seconds: Time-to-live for cached results (default: 1 hour)
        """
        self._llm_translator = llm_translator
        self._z3_version: str | None = None
        self._cache_size = cache_size
        self._cache_ttl = cache_ttl_seconds
        # Cache: hash -> (timestamp, FormalProofResult)
        self._proof_cache: dict[str, tuple[float, FormalProofResult]] = {}

    @property
    def language(self) -> FormalLanguage:
        return FormalLanguage.Z3_SMT

    @property
    def is_available(self) -> bool:
        """Check if z3 Python package is installed."""
        try:
            import z3

            self._z3_version = f"z3-{z3.get_version_string()}"
            return True
        except ImportError:
            return False

    @property
    def z3_version(self) -> str:
        """Get Z3 version string."""
        if self._z3_version is None and self.is_available:
            pass  # is_available sets the version
        return self._z3_version or "unknown"

    def can_verify(self, claim: str, claim_type: str | None = None) -> bool:
        """
        Check if this backend can attempt to verify the claim.

        Returns True for:
        - Claims already in SMT-LIB2 format
        - Claim types: assertion, precondition, arithmetic, constraint, logical
        - Claims containing quantifiable patterns (for all, exists, implies, etc.)
        """
        import re

        if not self.is_available:
            return False

        # Already SMT-LIB2 format
        if claim.strip().startswith("(") and ("assert" in claim or "declare" in claim):
            return True

        # Explicit claim types we handle
        z3_types = {
            "assertion",
            "precondition",
            "postcondition",
            "arithmetic",
            "constraint",
            "logical",
            "invariant",
            "LOGICAL",
            "FACTUAL",  # ClaimType enum values
        }
        if claim_type and claim_type in z3_types:
            return True

        # Heuristic: check for patterns that suggest formal logic
        quantifiable_patterns = r"\b(for all|forall|exists|there exists|greater than|less than|equal to|equals|implies|if.*then|and|or|not|sum|product|divides|prime|even|odd|positive|negative|integer|real|boolean)\b"
        if re.search(quantifiable_patterns, claim, re.IGNORECASE):
            return True

        # Check for mathematical notation
        math_patterns = r"[<>=≤≥≠∀∃→∧∨¬+\-*/^]"
        if re.search(math_patterns, claim):
            return True

        return False

    def _cache_key(self, formal_statement: str) -> str:
        """Generate cache key from formal statement."""
        return hashlib.sha256(formal_statement.encode()).hexdigest()[:16]

    def _get_cached(self, formal_statement: str) -> FormalProofResult | None:
        """Get cached proof result if valid and not expired."""
        import time

        key = self._cache_key(formal_statement)
        if key not in self._proof_cache:
            return None

        timestamp, result = self._proof_cache[key]
        if time.time() - timestamp > self._cache_ttl:
            # Expired, remove from cache
            del self._proof_cache[key]
            return None

        logger.debug("Z3 proof cache hit for key %s", key)
        return result

    def _cache_result(self, formal_statement: str, result: FormalProofResult) -> None:
        """Cache a proof result with LRU eviction."""
        import time

        key = self._cache_key(formal_statement)

        # LRU eviction if at capacity
        if len(self._proof_cache) >= self._cache_size:
            # Remove oldest entry
            oldest_key = min(self._proof_cache.keys(), key=lambda k: self._proof_cache[k][0])
            del self._proof_cache[oldest_key]

        self._proof_cache[key] = (time.time(), result)

    def clear_cache(self) -> int:
        """Clear the proof cache. Returns number of entries cleared."""
        count = len(self._proof_cache)
        self._proof_cache.clear()
        return count

    def _is_smtlib2(self, text: str) -> bool:
        """Check if text is already in SMT-LIB2 format."""
        text = text.strip()
        return text.startswith("(") and any(
            kw in text for kw in ["declare-", "assert", "check-sat", "define-"]
        )

    def _validate_smtlib2(self, smtlib: str) -> bool:
        """Validate SMT-LIB2 syntax using Z3 parser."""
        try:
            import z3

            ctx = z3.Context()
            z3.parse_smt2_string(smtlib, ctx=ctx)
            return True
        except (RuntimeError, ValueError, TypeError) as e:
            logger.debug("SMT-LIB2 validation failed: %s: %s", type(e).__name__, e)
            return False
        except Exception as e:  # noqa: BLE001 - Z3Exception doesn't inherit builtins
            # Z3Exception and other Z3-specific errors
            logger.debug("SMT-LIB2 validation failed (Z3 error): %s: %s", type(e).__name__, e)
            return False

    def _simple_translate(self, claim: str) -> str | None:
        """
        Pattern-based translation for simple claims.

        Handles basic arithmetic and logical claims without LLM.
        """
        import re

        claim_lower = claim.lower().strip()

        # Pattern: "X > Y and Y > Z implies X > Z" (transitivity)
        trans_match = re.match(
            r"(?:if\s+)?(\w+)\s*([<>=]+)\s*(\w+)\s+and\s+(\w+)\s*([<>=]+)\s*(\w+)\s*(?:,?\s*then\s+|implies\s+)(\w+)\s*([<>=]+)\s*(\w+)",
            claim_lower,
        )
        if trans_match:
            a, op1, b, c, op2, d, e, op3, f = trans_match.groups()
            return f"""
(declare-const {a} Int)
(declare-const {b} Int)
(declare-const {c} Int)
(declare-const {d} Int)
(declare-const {e} Int)
(declare-const {f} Int)
(assert (not (=> (and ({op1} {a} {b}) ({op2} {c} {d})) ({op3} {e} {f}))))
(check-sat)
"""

        # Pattern: "for all n, n + 0 = n"
        forall_match = re.match(
            r"for all (\w+),?\s+(.+)",
            claim_lower,
        )
        if forall_match:
            var, body = forall_match.groups()
            # Very simplified - just create a quantified assertion
            # Real implementation would parse the body properly
            return None  # Defer to LLM for complex quantified statements

        return None

    async def translate(self, claim: str, context: str = "") -> str | None:
        """
        Translate a natural language claim to SMT-LIB2 format.

        Strategy:
        1. If already SMT-LIB2, validate and return
        2. Try pattern-based translation for simple claims
        3. Use LLM translator if available
        """
        # Already in SMT-LIB2 format
        if self._is_smtlib2(claim):
            if self._validate_smtlib2(claim):
                return claim
            # Invalid SMT-LIB2, try to fix or reject
            return None

        # Try simple pattern-based translation
        simple = self._simple_translate(claim)
        if simple and self._validate_smtlib2(simple):
            return simple

        # Use LLM translator if available
        if self._llm_translator is not None:
            try:
                prompt = f"""Translate this claim to SMT-LIB2 format for Z3 solver.

Claim: {claim}
Context: {context}

Requirements:
- Use (declare-const name Type) for variables
- Use (assert (not ...)) to check validity (prove by showing negation is unsat)
- End with (check-sat)
- Use Int, Real, or Bool types
- Common operators: +, -, *, /, <, >, <=, >=, =, and, or, not, =>

Return ONLY the SMT-LIB2 code, no explanation."""

                smtlib = await self._llm_translator(prompt, context)

                # Extract SMT-LIB2 from response (may have markdown)
                if "```" in smtlib:
                    import re

                    match = re.search(r"```(?:smt2?|smtlib2?)?\n?(.*?)```", smtlib, re.DOTALL)
                    if match:
                        smtlib = match.group(1)

                smtlib = smtlib.strip()

                if self._validate_smtlib2(smtlib):
                    return smtlib

            except (
                ConnectionError,
                TimeoutError,
                OSError,
                ValueError,
                KeyError,
                TypeError,
                RuntimeError,
            ) as e:
                # LLM translation failed, log and continue to return None
                logger.debug("LLM translation to SMT-LIB2 failed: %s", e)

        return None

    async def prove(
        self, formal_statement: str, timeout_seconds: float = 60.0
    ) -> FormalProofResult:
        """
        Attempt to prove a formal statement using Z3.

        The statement should be in SMT-LIB2 format with the claim negated.
        If Z3 returns 'unsat', the original claim is proven.
        If Z3 returns 'sat', a counterexample exists.

        Results are cached by statement hash with configurable TTL.
        """
        import time

        # Check cache first
        cached = self._get_cached(formal_statement)
        if cached is not None:
            return cached

        if not self.is_available:
            return FormalProofResult(
                status=FormalProofStatus.BACKEND_UNAVAILABLE,
                language=FormalLanguage.Z3_SMT,
                error_message="Z3 Python package not installed. Run: pip install z3-solver",
            )

        try:
            import z3

            start = time.time()

            # Create solver with timeout
            solver = z3.Solver()
            solver.set("timeout", int(timeout_seconds * 1000))  # ms

            # Parse and add assertions
            try:
                assertions = z3.parse_smt2_string(formal_statement)
                for a in assertions:
                    solver.add(a)
            except z3.Z3Exception as e:
                return FormalProofResult(
                    status=FormalProofStatus.TRANSLATION_FAILED,
                    language=FormalLanguage.Z3_SMT,
                    formal_statement=formal_statement,
                    error_message=f"Failed to parse SMT-LIB2: {e}",
                    prover_version=self.z3_version,
                )

            # Check satisfiability
            result = solver.check()
            elapsed_ms = (time.time() - start) * 1000

            if result == z3.unsat:
                # Negation is unsatisfiable → original claim is valid
                proof_text = "QED (negation is unsatisfiable)"
                proof_hash = hashlib.sha256(formal_statement.encode()).hexdigest()[:16]

                proof_result = FormalProofResult(
                    status=FormalProofStatus.PROOF_FOUND,
                    language=FormalLanguage.Z3_SMT,
                    formal_statement=formal_statement,
                    proof_text=proof_text,
                    proof_hash=proof_hash,
                    proof_search_time_ms=elapsed_ms,
                    prover_version=self.z3_version,
                )
                self._cache_result(formal_statement, proof_result)
                return proof_result

            elif result == z3.sat:
                # Counterexample found
                model = solver.model()
                counterexample = f"COUNTEREXAMPLE: {model}"

                proof_result = FormalProofResult(
                    status=FormalProofStatus.PROOF_FAILED,
                    language=FormalLanguage.Z3_SMT,
                    formal_statement=formal_statement,
                    proof_text=counterexample,
                    proof_search_time_ms=elapsed_ms,
                    error_message="Claim is false - counterexample found",
                    prover_version=self.z3_version,
                )
                self._cache_result(formal_statement, proof_result)
                return proof_result

            else:
                # Unknown (timeout or undecidable) - don't cache timeouts
                return FormalProofResult(
                    status=FormalProofStatus.TIMEOUT,
                    language=FormalLanguage.Z3_SMT,
                    formal_statement=formal_statement,
                    proof_search_time_ms=elapsed_ms,
                    error_message="Solver returned unknown (timeout or undecidable)",
                    prover_version=self.z3_version,
                )

        except (ImportError, RuntimeError, ValueError, TypeError) as e:
            return FormalProofResult(
                status=FormalProofStatus.BACKEND_UNAVAILABLE,
                language=FormalLanguage.Z3_SMT,
                formal_statement=formal_statement,
                error_message=f"Z3 error: {e}",
                prover_version=self.z3_version,
            )

    async def verify_proof(self, formal_statement: str, proof: str) -> bool:
        """
        Verify a proof by re-running Z3.

        For Z3, proofs are implicit (unsat result), so we re-run the solver
        and check if we get the same result.
        """
        result = await self.prove(formal_statement, timeout_seconds=30.0)
        return result.status == FormalProofStatus.PROOF_FOUND


class FormalVerificationManager:
    """
    Manages formal verification backends.

    Coordinates between multiple backends, choosing the most
    appropriate one for each claim type.
    """

    def __init__(self, event_callback: Any | None = None) -> None:
        self.backends: list[FormalVerificationBackend] = [
            Z3Backend(),  # Try Z3 first (simpler, faster)
            LeanBackend(),  # Fall back to Lean for complex proofs
        ]
        # Optional callback invoked with StreamEvent after each verification.
        # Allows callers (e.g., consensus phase) to bridge events to their emitter.
        self._event_callback = event_callback

    def get_available_backends(self) -> list[FormalVerificationBackend]:
        """Get all available backends."""
        return [b for b in self.backends if b.is_available]

    def get_backend_for_claim(
        self, claim: str, claim_type: str | None = None
    ) -> FormalVerificationBackend | None:
        """Find the best backend for a claim."""
        for backend in self.backends:
            if backend.is_available and backend.can_verify(claim, claim_type):
                return backend
        return None

    async def attempt_formal_verification(
        self,
        claim: str,
        claim_type: str | None = None,
        context: str = "",
        timeout_seconds: float = 60.0,
    ) -> FormalProofResult:
        """
        Attempt to formally verify a claim using available backends.

        Args:
            claim: Natural language claim to verify
            claim_type: Optional hint about claim type
            context: Additional context for translation
            timeout_seconds: Maximum time for proof search

        Returns:
            FormalProofResult with verification status
        """
        backend = self.get_backend_for_claim(claim, claim_type)

        if backend is None:
            return FormalProofResult(
                status=FormalProofStatus.NOT_SUPPORTED,
                language=FormalLanguage.LEAN4,  # Default
                error_message="No suitable formal verification backend available",
            )

        # Translate claim to formal language
        formal_statement = await backend.translate(claim, context)

        if formal_statement is None:
            return FormalProofResult(
                status=FormalProofStatus.TRANSLATION_FAILED,
                language=backend.language,
                error_message="Could not translate claim to formal language",
            )

        # Attempt proof
        result = await backend.prove(formal_statement, timeout_seconds)
        result.formal_statement = formal_statement

        # Emit verification result event
        self._emit_verification_event(claim, result)

        return result

    async def verify_argument_structure(
        self,
        argument_graph: Any,
        timeout_seconds: float = 30.0,
    ) -> Any:
        """
        Verify the logical structure of an argument graph.

        Uses ArgumentStructureVerifier with LeanBackend for structural proofs
        and Z3Backend as fallback for decidable fragments.

        Args:
            argument_graph: An ArgumentCartographer instance with populated
                           nodes and edges.
            timeout_seconds: Maximum time for each proof attempt.

        Returns:
            ArgumentVerificationResult with valid/invalid chains,
            unsupported conclusions, contradictions, and circular dependencies.
        """
        from aragora.verification.argument_verifier import ArgumentStructureVerifier

        # Extract the Lean and Z3 backends from our backend list
        lean_backend = None
        z3_backend = None
        for backend in self.backends:
            if isinstance(backend, LeanBackend):
                lean_backend = backend
            elif isinstance(backend, Z3Backend):
                z3_backend = backend

        verifier = ArgumentStructureVerifier(
            lean_backend=lean_backend,
            z3_backend=z3_backend,
        )
        return await verifier.verify(argument_graph, timeout_seconds=timeout_seconds)

    def _emit_verification_event(self, claim: str, result: FormalProofResult) -> None:
        """Emit a FORMAL_VERIFICATION_RESULT event after verification completes.

        Uses lazy imports to avoid circular dependencies. Gracefully degrades
        if the events module or dispatcher is unavailable.

        Args:
            claim: The original natural language claim (truncated to 200 chars).
            result: The verification result to emit.
        """
        try:
            from aragora.events.types import StreamEvent, StreamEventType

            event = StreamEvent(
                type=StreamEventType.FORMAL_VERIFICATION_RESULT,
                data={
                    "claim": claim[:200],
                    "status": result.status.value,
                    "is_verified": result.is_verified,
                    "is_high_confidence": result.is_high_confidence,
                    "backend": result.language.value if result.language else "",
                    "formal_language": result.language.value if result.language else "",
                },
            )

            # Notify registered callback if present
            if self._event_callback is not None:
                self._event_callback(event)
        except (ImportError, RuntimeError, AttributeError) as e:
            logger.debug("Formal verification event emission unavailable: %s", e)

    def status_report(self) -> dict[str, Any]:
        """Get status of all backends."""
        return {
            "backends": [
                {
                    "language": b.language.value,
                    "available": b.is_available,
                }
                for b in self.backends
            ],
            "any_available": any(b.is_available for b in self.backends),
        }


# Singleton instance with thread-safe initialization
_manager: FormalVerificationManager | None = None
_manager_lock = threading.Lock()


def get_formal_verification_manager() -> FormalVerificationManager:
    """Get the global formal verification manager (thread-safe)."""
    global _manager
    if _manager is None:
        with _manager_lock:
            # Double-checked locking pattern
            if _manager is None:
                _manager = FormalVerificationManager()
    return _manager
