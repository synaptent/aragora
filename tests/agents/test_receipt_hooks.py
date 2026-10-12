"""Receipt operation hooks registered from the agents package."""

from __future__ import annotations

import builtins

import pytest

from aragora.agents import receipt_hooks
from aragora.agents.failure_semantics import all_responses_are_failures
from aragora.models.receipts import operations


def test_registration_installs_provider_detection_and_failure_classification() -> None:
    receipt_hooks.register_receipt_agent_hooks()

    assert {"provider_detection", "failure_classification"} <= operations.registered_operations()
    assert operations.detect_provider("gpt-4") == receipt_hooks.detect_provider("gpt-4")
    texts = ["anthropic-api got confused and needs to recalibrate."]
    assert operations.all_responses_are_failures(texts) is all_responses_are_failures(texts)


def test_gauntlet_facade_registers_the_same_hooks() -> None:
    import aragora.gauntlet.receipt_models  # noqa: F401

    receipt_hooks.register_receipt_agent_hooks()
    from aragora.models.receipts.gauntlet import DecisionReceipt

    assert DecisionReceipt._detect_provider("claude-opus-5") == receipt_hooks.detect_provider(
        "claude-opus-5"
    )


def test_provider_detection_without_the_debate_package_reports_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "aragora.debate.provider_diversity":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    assert receipt_hooks.detect_provider("gpt-4") == "unknown"
