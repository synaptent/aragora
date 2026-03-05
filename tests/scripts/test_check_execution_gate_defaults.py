from __future__ import annotations

from pathlib import Path

from scripts.check_execution_gate_defaults import (
    check_repo,
    find_orchestrator_runner_default_violations,
    find_post_debate_default_violations,
)


def _valid_post_debate_source() -> str:
    return """
from dataclasses import dataclass

@dataclass
class PostDebateConfig:
    enforce_execution_safety_gate: bool = True
    execution_gate_require_verified_signed_receipt: bool = True
    execution_gate_enforce_receipt_signer_allowlist: bool = False
    execution_gate_allowed_receipt_signer_keys: tuple[str, ...] = ()
    execution_gate_require_signed_receipt_timestamp: bool = True
    execution_gate_receipt_max_age_seconds: int = 86400
    execution_gate_receipt_max_future_skew_seconds: int = 120
    execution_gate_min_provider_diversity: int = 2
    execution_gate_min_model_family_diversity: int = 2
    execution_gate_block_on_context_taint: bool = True
    execution_gate_block_on_high_severity_dissent: bool = True
    execution_gate_high_severity_dissent_threshold: float = 0.7
"""


def _valid_orchestrator_source() -> str:
    return """
from aragora.debate.execution_safety import ExecutionSafetyPolicy

def build_policy(post_cfg):
    return ExecutionSafetyPolicy(
        require_verified_signed_receipt=getattr(
            post_cfg, "execution_gate_require_verified_signed_receipt", True
        ),
        require_receipt_signer_allowlist=getattr(
            post_cfg, "execution_gate_enforce_receipt_signer_allowlist", False
        ),
        allowed_receipt_signer_keys=getattr(
            post_cfg, "execution_gate_allowed_receipt_signer_keys", ()
        ),
        require_signed_receipt_timestamp=getattr(
            post_cfg, "execution_gate_require_signed_receipt_timestamp", True
        ),
        receipt_max_age_seconds=getattr(
            post_cfg, "execution_gate_receipt_max_age_seconds", 86400
        ),
        receipt_max_future_skew_seconds=getattr(
            post_cfg, "execution_gate_receipt_max_future_skew_seconds", 120
        ),
        min_provider_diversity=getattr(post_cfg, "execution_gate_min_provider_diversity", 2),
        min_model_family_diversity=getattr(post_cfg, "execution_gate_min_model_family_diversity", 2),
        block_on_context_taint=getattr(post_cfg, "execution_gate_block_on_context_taint", True),
        block_on_high_severity_dissent=getattr(
            post_cfg, "execution_gate_block_on_high_severity_dissent", True
        ),
        high_severity_dissent_threshold=getattr(
            post_cfg, "execution_gate_high_severity_dissent_threshold", 0.7
        ),
    )
"""


def test_post_debate_defaults_accept_secure_baseline() -> None:
    violations = find_post_debate_default_violations(_valid_post_debate_source())
    assert violations == []


def test_post_debate_defaults_reject_weakened_boolean() -> None:
    text = _valid_post_debate_source().replace(
        "execution_gate_block_on_context_taint: bool = True",
        "execution_gate_block_on_context_taint: bool = False",
    )
    violations = find_post_debate_default_violations(text)
    assert violations
    assert any("execution_gate_block_on_context_taint" in message for message in violations)


def test_post_debate_defaults_reject_weakened_diversity_floor() -> None:
    text = _valid_post_debate_source().replace(
        "execution_gate_min_provider_diversity: int = 2",
        "execution_gate_min_provider_diversity: int = 1",
    )
    violations = find_post_debate_default_violations(text)
    assert violations
    assert any("execution_gate_min_provider_diversity" in message for message in violations)


def test_post_debate_defaults_reject_overly_lenient_receipt_age() -> None:
    text = _valid_post_debate_source().replace(
        "execution_gate_receipt_max_age_seconds: int = 86400",
        "execution_gate_receipt_max_age_seconds: int = 172800",
    )
    violations = find_post_debate_default_violations(text)
    assert violations
    assert any("execution_gate_receipt_max_age_seconds" in message for message in violations)


def test_orchestrator_fallbacks_accept_secure_baseline() -> None:
    violations = find_orchestrator_runner_default_violations(_valid_orchestrator_source())
    assert violations == []


def test_orchestrator_fallbacks_reject_threshold_regression() -> None:
    text = _valid_orchestrator_source().replace(
        '"execution_gate_high_severity_dissent_threshold", 0.7',
        '"execution_gate_high_severity_dissent_threshold", 0.9',
    )
    violations = find_orchestrator_runner_default_violations(text)
    assert violations
    assert any("high_severity_dissent_threshold" in message for message in violations)


def test_orchestrator_fallbacks_require_getattr_pattern() -> None:
    text = _valid_orchestrator_source().replace(
        'min_provider_diversity=getattr(post_cfg, "execution_gate_min_provider_diversity", 2),',
        "min_provider_diversity=2,",
    )
    violations = find_orchestrator_runner_default_violations(text)
    assert violations
    assert any("min_provider_diversity" in message for message in violations)


def test_repo_execution_gate_defaults_pass_for_current_tree() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    violations = check_repo(repo_root)
    assert violations == []
