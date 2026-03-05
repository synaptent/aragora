"""Execution safety gate for autonomous post-debate actions.

This module centralizes policy checks required before high-impact
auto-execution is allowed (plan execution, workflow triggers, PR creation).

Checks include:
- Verified signed decision receipt
- Ensemble diversity floor (provider + model family)
- Context taint signals (prompt-injection style risks)
- High-severity dissent
- Correlated-failure/collusion heuristics
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from aragora.debate.provider_diversity import detect_provider
from aragora.gauntlet.receipt_models import DecisionReceipt

_MODEL_FAMILY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("claude", re.compile(r"claude", re.I)),
    ("gpt", re.compile(r"\bgpt\b|chatgpt|o1|o3|o4|o5", re.I)),
    ("gemini", re.compile(r"gemini|palm|bard", re.I)),
    ("grok", re.compile(r"grok", re.I)),
    ("llama", re.compile(r"llama", re.I)),
    ("mistral", re.compile(r"mistral|mixtral|codestral", re.I)),
    ("deepseek", re.compile(r"deepseek", re.I)),
    ("qwen", re.compile(r"qwen", re.I)),
    ("kimi", re.compile(r"kimi|moonshot", re.I)),
    ("command-r", re.compile(r"command", re.I)),
    ("yi", re.compile(r"\byi\b|01-ai", re.I)),
]


@dataclass
class ExecutionSafetyPolicy:
    """Policy used to decide whether auto-execution is allowed."""

    require_verified_signed_receipt: bool = True
    min_provider_diversity: int = 2
    min_model_family_diversity: int = 2
    block_on_context_taint: bool = True
    block_on_high_severity_dissent: bool = True
    high_severity_dissent_threshold: float = 0.7  # 0..1 scale


@dataclass
class ExecutionSafetyDecision:
    """Result of execution safety evaluation."""

    allow_auto_execution: bool
    reason_codes: list[str] = field(default_factory=list)
    receipt_signed: bool = False
    receipt_integrity_valid: bool = False
    receipt_signature_valid: bool = False
    receipt_id: str | None = None
    provider_diversity: int = 0
    model_family_diversity: int = 0
    providers: list[str] = field(default_factory=list)
    model_families: list[str] = field(default_factory=list)
    context_taint_detected: bool = False
    high_severity_dissent_detected: bool = False
    correlated_failure_risk: bool = False
    suspicious_unanimity_risk: bool = False
    signed_receipt: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_auto_execution": self.allow_auto_execution,
            "reason_codes": list(self.reason_codes),
            "receipt_signed": self.receipt_signed,
            "receipt_integrity_valid": self.receipt_integrity_valid,
            "receipt_signature_valid": self.receipt_signature_valid,
            "receipt_id": self.receipt_id,
            "provider_diversity": self.provider_diversity,
            "model_family_diversity": self.model_family_diversity,
            "providers": list(self.providers),
            "model_families": list(self.model_families),
            "context_taint_detected": self.context_taint_detected,
            "high_severity_dissent_detected": self.high_severity_dissent_detected,
            "correlated_failure_risk": self.correlated_failure_risk,
            "suspicious_unanimity_risk": self.suspicious_unanimity_risk,
            "signed_receipt": self.signed_receipt,
        }


def _normalize_operator(agent: Any) -> str:
    """Infer an operator key from agent metadata."""
    agent_type = str(getattr(agent, "agent_type", "") or "").strip().lower()
    if agent_type:
        return agent_type

    model = str(getattr(agent, "model", "") or "").strip().lower()
    if model:
        return model
    return "unknown"


def _detect_model_family(model_name: str) -> str:
    """Infer model family from model identifier."""
    if not model_name:
        return "unknown"
    for family, pattern in _MODEL_FAMILY_PATTERNS:
        if pattern.search(model_name):
            return family

    normalized = model_name.strip().lower().replace(":", "/")
    if "/" in normalized:
        return normalized.split("/", 1)[-1].split("-", 1)[0] or "unknown"
    return normalized.split("-", 1)[0] or "unknown"


def _extract_ensemble(agents: list[Any] | None) -> tuple[set[str], set[str], set[str]]:
    """Extract diversity signals from participating agents."""
    providers: set[str] = set()
    model_families: set[str] = set()
    operators: set[str] = set()

    for agent in agents or []:
        model = str(getattr(agent, "model", "") or "")
        provider = detect_provider(model)

        # Fallback to agent_type hints when model detection fails.
        if provider == "unknown":
            at = str(getattr(agent, "agent_type", "") or "").lower()
            if "anthropic" in at or "claude" in at:
                provider = "anthropic"
            elif "openai" in at or "codex" in at:
                provider = "openai"
            elif "gemini" in at or "google" in at:
                provider = "google"
            elif "grok" in at or "xai" in at:
                provider = "xai"
            elif "mistral" in at or "codestral" in at:
                provider = "mistral"
            elif "qwen" in at or "alibaba" in at:
                provider = "alibaba"
            elif "deepseek" in at:
                provider = "deepseek"
            elif "openrouter" in at:
                provider = "openrouter"

        providers.add(provider or "unknown")
        model_families.add(_detect_model_family(model))
        operators.add(_normalize_operator(agent))

    if not providers:
        providers.add("unknown")
    if not model_families:
        model_families.add("unknown")
    if not operators:
        operators.add("unknown")

    return providers, model_families, operators


def _normalize_severity(raw: Any) -> float:
    """Normalize severity to 0..1 scale."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if value > 1.0:
        # Many critique paths use 0..10.
        value = value / 10.0
    return max(0.0, min(1.0, value))


def _has_high_severity_dissent(result: Any, threshold: float) -> bool:
    """Check whether debate output contains high-severity unresolved dissent."""
    critiques = list(getattr(result, "critiques", []) or [])
    for critique in critiques:
        sev = _normalize_severity(getattr(critique, "severity", 0.0))
        if sev >= threshold:
            return True

    for view in list(getattr(result, "dissenting_views", []) or []):
        if isinstance(view, dict):
            sev = _normalize_severity(view.get("severity", 0.0))
            if sev >= threshold:
                return True

    return False


def _context_taint_detected(result: Any) -> bool:
    """Read context-taint signal from debate metadata."""
    metadata = getattr(result, "metadata", None)
    if not isinstance(metadata, dict):
        return False
    if bool(metadata.get("context_taint_detected")):
        return True
    patterns = metadata.get("context_taint_patterns")
    return isinstance(patterns, list) and len(patterns) > 0


def _build_signed_receipt(result: Any) -> tuple[DecisionReceipt | None, bool, bool, bool]:
    """Build, sign, and verify a receipt for execution gating.

    Returns:
        (receipt, signed, integrity_valid, signature_valid)
    """
    try:
        receipt = DecisionReceipt.from_debate_result(result)
        signed = receipt.sign()
        integrity_valid = signed.verify_integrity()
        signature_valid = signed.verify_signature()
        return signed, True, integrity_valid, signature_valid
    except (RuntimeError, ValueError, TypeError, AttributeError, OSError):
        return None, False, False, False


def evaluate_auto_execution_safety(
    result: Any,
    *,
    agents: list[Any] | None = None,
    policy: ExecutionSafetyPolicy | None = None,
) -> ExecutionSafetyDecision:
    """Evaluate whether post-debate auto-execution should proceed."""
    policy = policy or ExecutionSafetyPolicy()

    providers, model_families, operators = _extract_ensemble(agents)
    provider_diversity = len(providers)
    model_family_diversity = len(model_families)
    operator_diversity = len(operators)

    receipt, receipt_signed, integrity_valid, signature_valid = _build_signed_receipt(result)
    context_taint = _context_taint_detected(result)
    high_dissent = _has_high_severity_dissent(result, policy.high_severity_dissent_threshold)

    consensus_reached = bool(getattr(result, "consensus_reached", False))
    confidence = float(getattr(result, "confidence", 0.0) or 0.0)

    correlated_failure_risk = (
        provider_diversity < policy.min_provider_diversity
        or model_family_diversity < policy.min_model_family_diversity
    )
    suspicious_unanimity_risk = (
        consensus_reached
        and confidence >= 0.9
        and (provider_diversity <= 1 or model_family_diversity <= 1 or operator_diversity <= 1)
    )

    reason_codes: list[str] = []
    if policy.require_verified_signed_receipt and not (
        receipt_signed and integrity_valid and signature_valid
    ):
        reason_codes.append("receipt_verification_failed")
    if provider_diversity < policy.min_provider_diversity:
        reason_codes.append("provider_diversity_below_minimum")
    if model_family_diversity < policy.min_model_family_diversity:
        reason_codes.append("model_family_diversity_below_minimum")
    if policy.block_on_context_taint and context_taint:
        reason_codes.append("tainted_context_detected")
    if policy.block_on_high_severity_dissent and high_dissent:
        reason_codes.append("high_severity_dissent_detected")
    if correlated_failure_risk:
        reason_codes.append("correlated_failure_risk")
    if suspicious_unanimity_risk:
        reason_codes.append("suspicious_unanimity_risk")

    allow = len(reason_codes) == 0
    return ExecutionSafetyDecision(
        allow_auto_execution=allow,
        reason_codes=reason_codes,
        receipt_signed=receipt_signed,
        receipt_integrity_valid=integrity_valid,
        receipt_signature_valid=signature_valid,
        receipt_id=getattr(receipt, "receipt_id", None) if receipt else None,
        provider_diversity=provider_diversity,
        model_family_diversity=model_family_diversity,
        providers=sorted(providers),
        model_families=sorted(model_families),
        context_taint_detected=context_taint,
        high_severity_dissent_detected=high_dissent,
        correlated_failure_risk=correlated_failure_risk,
        suspicious_unanimity_risk=suspicious_unanimity_risk,
        signed_receipt=receipt.to_dict() if receipt else None,
    )


__all__ = [
    "ExecutionSafetyDecision",
    "ExecutionSafetyPolicy",
    "evaluate_auto_execution_safety",
]
