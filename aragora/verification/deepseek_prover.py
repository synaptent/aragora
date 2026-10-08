"""
DeepSeek-Prover Integration - State-of-the-art NL-to-Lean translation.

Uses DeepSeek-Prover-V2 via OpenRouter for high-quality translation of
natural language mathematical claims to Lean 4 theorems.

DeepSeek-Prover-V2 is specifically trained for mathematical reasoning
and formal proof generation, making it superior to general-purpose LLMs
for this task.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from aragora.config import get_api_key
from aragora.observability.http_client_pool import get_http_pool

logger = logging.getLogger(__name__)


@dataclass
class TranslationResult:
    """Result of a natural language to Lean translation."""

    success: bool
    lean_code: str | None = None
    error_message: str = ""
    model_used: str = ""
    translation_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    confidence: float = 0.0  # 0-1 confidence in translation quality

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "lean_code": self.lean_code,
            "error_message": self.error_message,
            "model_used": self.model_used,
            "translation_time_ms": self.translation_time_ms,
            "timestamp": self.timestamp.isoformat(),
            "confidence": self.confidence,
        }


class DeepSeekProverTranslator:
    """
    Translates natural language claims to Lean 4 theorems using DeepSeek-Prover-V2.

    DeepSeek-Prover-V2 is a specialized model trained on mathematical proofs
    and Lean 4 code, achieving state-of-the-art performance on:
    - Natural language to formal statement translation
    - Automatic proof generation
    - Mathematical reasoning

    Requires OPENROUTER_API_KEY environment variable.

    Usage:
        translator = DeepSeekProverTranslator()
        result = await translator.translate("For all natural numbers n, n + 0 = n")
        if result.success:
            print(result.lean_code)
    """

    # Model identifiers on OpenRouter
    PRIMARY_MODEL = "deepseek/deepseek-prover-v2"
    FALLBACK_MODEL = "deepseek/deepseek-v4-pro"  # Fallback if prover unavailable

    # Mathlib 4 common imports
    MATHLIB_IMPORTS = """
import Mathlib.Tactic
import Mathlib.Data.Nat.Basic
import Mathlib.Data.Int.Basic
import Mathlib.Data.Real.Basic
import Mathlib.Algebra.Ring.Basic
"""

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 60.0,
        max_tokens: int = 4096,
    ):
        """
        Initialize DeepSeek-Prover translator.

        Args:
            api_key: OpenRouter API key (defaults to OPENROUTER_API_KEY env var)
            timeout: Request timeout in seconds
            max_tokens: Maximum tokens for response
        """
        self.api_key = api_key or get_api_key("OPENROUTER_API_KEY", required=False)
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._model_available: bool | None = None

    @property
    def is_available(self) -> bool:
        """Check if the translator is available (API key configured)."""
        return bool(self.api_key)

    async def check_model_availability(self) -> bool:
        """Check if DeepSeek-Prover model is available on OpenRouter."""
        if not self.api_key:
            return False

        if self._model_available is not None:
            return self._model_available

        try:
            pool = get_http_pool()
            async with pool.get_session("openrouter") as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=10,
                )
                if response.status_code == 200:
                    data = response.json()
                    models = data.get("data", [])
                    model_ids = {m.get("id") for m in models}
                    self._model_available = self.PRIMARY_MODEL in model_ids
                    return self._model_available
        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as e:
            logger.warning("Failed to check model availability: %s", e)

        return False

    def _build_translation_prompt(self, claim: str, context: str = "") -> str:
        """Build the translation prompt for DeepSeek-Prover."""
        return f"""You are a Lean 4 expert. Translate the following natural language mathematical claim into a Lean 4 theorem with a complete proof.

CLAIM: {claim}
{f"CONTEXT: {context}" if context else ""}

REQUIREMENTS:
1. Use valid Lean 4 syntax (NOT Lean 3)
2. Include necessary Mathlib 4 imports
3. Provide a complete, valid proof using tactics (simp, ring, omega, decide, linarith, etc.)
4. If the claim is false, prove its negation and add a comment explaining why
5. If the claim cannot be formalized, explain why in a comment
6. Use descriptive theorem names (not just theorem_1)
7. Add brief comments explaining the proof strategy

OUTPUT FORMAT:
Return ONLY valid Lean 4 code. Example structure:

```lean
import Mathlib.Tactic

-- Brief description of the theorem
theorem descriptive_name : <formal_statement> := by
  -- Proof strategy explanation
  <tactic_proof>
```

If the claim is UNTRANSLATABLE to Lean 4, return exactly:
-- UNTRANSLATABLE: <reason>"""

    def _extract_lean_code(self, response: str) -> str | None:
        """Extract Lean code from LLM response."""
        # Try to extract from markdown code block
        lean_match = re.search(r"```(?:lean4?|lean)?\n?(.*?)```", response, re.DOTALL)
        if lean_match:
            return lean_match.group(1).strip()

        # Check if it's already plain Lean code (starts with import or theorem)
        response = response.strip()
        if response.startswith("import ") or response.startswith("theorem "):
            return response

        # Check for UNTRANSLATABLE marker
        if "UNTRANSLATABLE" in response:
            return None

        return response

    def _estimate_confidence(self, lean_code: str) -> float:
        """Estimate confidence in translation quality based on code characteristics."""
        if not lean_code:
            return 0.0

        confidence = 0.5  # Base confidence

        # Positive indicators
        if "import Mathlib" in lean_code:
            confidence += 0.1
        if "theorem " in lean_code or "lemma " in lean_code:
            confidence += 0.1
        if " := by" in lean_code:
            confidence += 0.1
        if any(tactic in lean_code for tactic in ["simp", "ring", "omega", "linarith", "decide"]):
            confidence += 0.1

        # Negative indicators
        if "sorry" in lean_code:
            confidence -= 0.3
        if "UNTRANSLATABLE" in lean_code:
            confidence = 0.0
        if lean_code.count("--") > 10:  # Too many comments might indicate uncertainty
            confidence -= 0.1

        return max(0.0, min(1.0, confidence))

    async def translate(
        self,
        claim: str,
        context: str = "",
        use_fallback: bool = True,
    ) -> TranslationResult:
        """
        Translate a natural language claim to Lean 4.

        Args:
            claim: Natural language mathematical claim
            context: Additional context to help translation
            use_fallback: Whether to try fallback model if primary fails

        Returns:
            TranslationResult with Lean code if successful
        """
        import time

        if not self.api_key:
            return TranslationResult(
                success=False,
                error_message="OPENROUTER_API_KEY not configured",
            )

        start_time = time.time()
        prompt = self._build_translation_prompt(claim, context)

        # Try primary model first
        models_to_try = [self.PRIMARY_MODEL]
        if use_fallback:
            models_to_try.append(self.FALLBACK_MODEL)

        last_error = ""

        for model in models_to_try:
            try:
                pool = get_http_pool()
                async with pool.get_session("openrouter") as client:
                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://aragora.ai",
                        "X-Title": "Aragora Formal Verification",
                    }

                    payload = {
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are an expert Lean 4 theorem prover. Translate natural language claims to formal Lean 4 theorems with proofs.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": self.max_tokens,
                        "temperature": 0.1,  # Low temperature for deterministic output
                    }

                    response = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        json=payload,
                        headers=headers,
                        timeout=self.timeout,
                    )
                    elapsed_ms = (time.time() - start_time) * 1000

                    if response.status_code == 200:
                        data = response.json()
                        content = data["choices"][0]["message"]["content"]

                        lean_code = self._extract_lean_code(content)

                        if lean_code is None or "UNTRANSLATABLE" in content:
                            return TranslationResult(
                                success=False,
                                error_message="Claim cannot be translated to Lean 4",
                                model_used=model,
                                translation_time_ms=elapsed_ms,
                            )

                        confidence = self._estimate_confidence(lean_code)

                        return TranslationResult(
                            success=True,
                            lean_code=lean_code,
                            model_used=model,
                            translation_time_ms=elapsed_ms,
                            confidence=confidence,
                        )

                    else:
                        error_text = response.text
                        last_error = f"API error {response.status_code}: {error_text[:200]}"
                        logger.warning("DeepSeek-Prover %s failed: %s", model, last_error)

            except asyncio.TimeoutError:
                last_error = f"Timeout after {self.timeout}s"
                logger.warning("DeepSeek-Prover %s timed out", model)
            except (OSError, ConnectionError) as e:
                last_error = f"Network error: {e}"
                logger.warning("DeepSeek-Prover %s network error: %s", model, e)
            except (ValueError, KeyError, TypeError, RuntimeError) as e:
                last_error = f"Unexpected error: {type(e).__name__}: {e}"
                logger.warning("DeepSeek-Prover %s error: %s", model, e)

        # All models failed
        elapsed_ms = (time.time() - start_time) * 1000
        return TranslationResult(
            success=False,
            error_message=last_error,
            translation_time_ms=elapsed_ms,
        )

    async def translate_batch(
        self,
        claims: list[str],
        context: str = "",
        max_concurrent: int = 3,
    ) -> list[TranslationResult]:
        """
        Translate multiple claims concurrently.

        Args:
            claims: List of natural language claims
            context: Shared context for all translations
            max_concurrent: Maximum concurrent translations

        Returns:
            List of TranslationResults in same order as input
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def translate_with_limit(claim: str) -> TranslationResult:
            async with semaphore:
                return await self.translate(claim, context)

        tasks = [translate_with_limit(claim) for claim in claims]
        return await asyncio.gather(*tasks)


# Convenience function
async def translate_to_lean(
    claim: str,
    context: str = "",
    api_key: str | None = None,
) -> TranslationResult:
    """
    Convenience function to translate a claim to Lean 4.

    Args:
        claim: Natural language mathematical claim
        context: Additional context
        api_key: OpenRouter API key (optional, uses env var if not provided)

    Returns:
        TranslationResult with Lean code if successful
    """
    translator = DeepSeekProverTranslator(api_key=api_key)
    return await translator.translate(claim, context)


__all__ = [
    "DeepSeekProverTranslator",
    "TranslationResult",
    "translate_to_lean",
]
