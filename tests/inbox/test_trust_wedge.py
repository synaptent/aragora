"""
Tests for inbox trust wedge contract types, CLI review loop,
and auto-approval policy.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from aragora.inbox.trust_wedge import (
    ActionIntent,
    AllowedAction,
    ReceiptState,
    TriageDecision,
    compute_content_hash,
)
from aragora.inbox.cli_review import CLIReviewLoop
from aragora.inbox.auto_approval import AutoApprovalPolicy


# -----------------------------------------------------------------------
# AllowedAction enum
# -----------------------------------------------------------------------


class TestAllowedAction:
    def test_values(self) -> None:
        assert AllowedAction.ARCHIVE.value == "archive"
        assert AllowedAction.STAR.value == "star"
        assert AllowedAction.LABEL.value == "label"
        assert AllowedAction.IGNORE.value == "ignore"

    def test_is_str_enum(self) -> None:
        assert isinstance(AllowedAction.ARCHIVE, str)
        assert AllowedAction.ARCHIVE == "archive"

    def test_members_count(self) -> None:
        assert len(AllowedAction) == 4


# -----------------------------------------------------------------------
# ReceiptState enum
# -----------------------------------------------------------------------


class TestReceiptState:
    def test_values(self) -> None:
        assert ReceiptState.CREATED.value == "created"
        assert ReceiptState.APPROVED.value == "approved"
        assert ReceiptState.EXPIRED.value == "expired"
        assert ReceiptState.EXECUTED.value == "executed"


# -----------------------------------------------------------------------
# compute_content_hash
# -----------------------------------------------------------------------


class TestContentHash:
    def test_deterministic(self) -> None:
        h1 = compute_content_hash("hello world")
        h2 = compute_content_hash("hello world")
        assert h1 == h2

    def test_differs_for_different_content(self) -> None:
        h1 = compute_content_hash("hello")
        h2 = compute_content_hash("world")
        assert h1 != h2

    def test_sha256_length(self) -> None:
        h = compute_content_hash("test")
        assert len(h) == 64  # SHA-256 hex digest


# -----------------------------------------------------------------------
# ActionIntent
# -----------------------------------------------------------------------


class TestActionIntent:
    def _make_intent(self, **overrides: object) -> ActionIntent:
        defaults: dict = {
            "provider": "claude-3",
            "message_id": "msg-123",
            "action": AllowedAction.ARCHIVE.value,
            "content_hash": compute_content_hash("body"),
            "synthesized_rationale": "Low priority newsletter",
            "confidence": 0.92,
            "provider_route": "direct",
            "debate_id": "debate-abc",
            "created_at": "2026-03-06T12:00:00+00:00",
        }
        defaults.update(overrides)
        return ActionIntent(**defaults)

    def test_creation(self) -> None:
        intent = self._make_intent()
        assert intent.provider == "claude-3"
        assert intent.message_id == "msg-123"
        assert intent.confidence == 0.92

    def test_to_dict(self) -> None:
        intent = self._make_intent()
        d = intent.to_dict()
        assert d["provider"] == "claude-3"
        assert d["action"] == "archive"
        assert isinstance(d["content_hash"], str)

    def test_roundtrip(self) -> None:
        intent = self._make_intent()
        d = intent.to_dict()
        restored = ActionIntent.from_dict(d)
        assert restored.provider == intent.provider
        assert restored.message_id == intent.message_id
        assert restored.confidence == intent.confidence
        assert restored.action == intent.action

    def test_content_hash_matches_body(self) -> None:
        body = "Important meeting tomorrow"
        expected_hash = compute_content_hash(body)
        intent = self._make_intent(content_hash=expected_hash)
        assert intent.content_hash == expected_hash


# -----------------------------------------------------------------------
# TriageDecision
# -----------------------------------------------------------------------


class TestTriageDecision:
    def _make_decision(self, **overrides: object) -> TriageDecision:
        defaults: dict = {
            "final_action": AllowedAction.ARCHIVE.value,
            "confidence": 0.90,
            "dissent_summary": "",
            "receipt_id": "receipt-001",
            "auto_approval_eligible": False,
            "provider_route": "direct",
            "intent": None,
            "receipt_state": ReceiptState.CREATED.value,
        }
        defaults.update(overrides)
        return TriageDecision(**defaults)

    def test_creation(self) -> None:
        d = self._make_decision()
        assert d.final_action == "archive"
        assert d.receipt_state == "created"

    def test_auto_approval_eligible_default(self) -> None:
        d = self._make_decision()
        assert d.auto_approval_eligible is False

    def test_to_dict_with_intent(self) -> None:
        intent = ActionIntent(
            provider="gpt-4",
            message_id="msg-456",
            action="star",
            content_hash="abc123",
            synthesized_rationale="Important from boss",
            confidence=0.95,
            provider_route="direct",
            debate_id="debate-xyz",
        )
        d = self._make_decision(intent=intent)
        result = d.to_dict()
        assert result["intent"]["provider"] == "gpt-4"
        assert result["intent"]["action"] == "star"

    def test_to_dict_without_intent(self) -> None:
        d = self._make_decision()
        result = d.to_dict()
        assert result["intent"] is None

    def test_roundtrip(self) -> None:
        intent = ActionIntent(
            provider="claude-3",
            message_id="msg-789",
            action="ignore",
            content_hash="def456",
            synthesized_rationale="Spam",
            confidence=0.88,
            provider_route="openrouter",
            debate_id="debate-123",
        )
        decision = self._make_decision(
            final_action="ignore",
            confidence=0.88,
            dissent_summary="One agent wanted archive",
            intent=intent,
        )
        d = decision.to_dict()
        restored = TriageDecision.from_dict(d)
        assert restored.final_action == "ignore"
        assert restored.dissent_summary == "One agent wanted archive"
        assert restored.intent is not None
        assert restored.intent.provider == "claude-3"


# -----------------------------------------------------------------------
# AutoApprovalPolicy
# -----------------------------------------------------------------------


class TestAutoApprovalPolicy:
    def _make_decision(self, **overrides: object) -> TriageDecision:
        defaults: dict = {
            "final_action": AllowedAction.ARCHIVE.value,
            "confidence": 0.90,
            "dissent_summary": "",
            "receipt_state": ReceiptState.CREATED.value,
        }
        defaults.update(overrides)
        return TriageDecision(**defaults)

    def test_can_auto_approve_archive_high_confidence(self) -> None:
        policy = AutoApprovalPolicy()
        d = self._make_decision(confidence=0.90)
        assert policy.can_auto_approve(d) is True

    def test_blocks_label_action(self) -> None:
        policy = AutoApprovalPolicy()
        d = self._make_decision(final_action=AllowedAction.LABEL.value)
        assert policy.can_auto_approve(d) is False

    def test_blocks_low_confidence(self) -> None:
        policy = AutoApprovalPolicy()
        d = self._make_decision(confidence=0.50)
        assert policy.can_auto_approve(d) is False

    def test_blocks_dissent(self) -> None:
        policy = AutoApprovalPolicy()
        d = self._make_decision(dissent_summary="Agent disagreed about action")
        assert policy.can_auto_approve(d) is False

    def test_blocks_non_created_state(self) -> None:
        policy = AutoApprovalPolicy()
        d = self._make_decision(receipt_state=ReceiptState.APPROVED.value)
        assert policy.can_auto_approve(d) is False

    def test_auto_approve_transitions_state(self) -> None:
        policy = AutoApprovalPolicy()
        d = self._make_decision(confidence=0.95)
        result = policy.auto_approve(d)
        assert result is True
        assert d.receipt_state == ReceiptState.APPROVED.value
        assert d.auto_approval_eligible is True

    def test_auto_approve_returns_false_when_blocked(self) -> None:
        policy = AutoApprovalPolicy()
        d = self._make_decision(confidence=0.50)
        result = policy.auto_approve(d)
        assert result is False
        assert d.receipt_state == ReceiptState.CREATED.value

    def test_custom_threshold(self) -> None:
        policy = AutoApprovalPolicy(confidence_threshold=0.95)
        d = self._make_decision(confidence=0.90)
        assert policy.can_auto_approve(d) is False
        d2 = self._make_decision(confidence=0.96)
        assert policy.can_auto_approve(d2) is True

    def test_star_auto_approvable(self) -> None:
        policy = AutoApprovalPolicy()
        d = self._make_decision(final_action=AllowedAction.STAR.value, confidence=0.90)
        assert policy.can_auto_approve(d) is True

    def test_ignore_auto_approvable(self) -> None:
        policy = AutoApprovalPolicy()
        d = self._make_decision(final_action=AllowedAction.IGNORE.value, confidence=0.90)
        assert policy.can_auto_approve(d) is True

    def test_to_dict_roundtrip(self) -> None:
        policy = AutoApprovalPolicy(confidence_threshold=0.92)
        d = policy.to_dict()
        restored = AutoApprovalPolicy.from_dict(d)
        assert restored.confidence_threshold == 0.92


# -----------------------------------------------------------------------
# CLIReviewLoop
# -----------------------------------------------------------------------


class TestCLIReviewLoop:
    def _make_decision(self, **overrides: object) -> TriageDecision:
        defaults: dict = {
            "final_action": AllowedAction.ARCHIVE.value,
            "confidence": 0.90,
            "dissent_summary": "",
            "receipt_id": "test-receipt",
            "receipt_state": ReceiptState.CREATED.value,
        }
        defaults.update(overrides)
        return TriageDecision(**defaults)

    def test_approve_flow(self) -> None:
        inputs = iter(["a"])
        output: list[str] = []
        loop = CLIReviewLoop(
            input_fn=lambda _prompt="": next(inputs),
            print_fn=lambda *args: output.append(str(args)),
        )
        decision = self._make_decision()
        results = loop.review_batch([decision])
        assert len(results) == 1
        assert results[0]["action_taken"] == "approve"
        assert decision.receipt_state == ReceiptState.APPROVED.value

    def test_reject_flow(self) -> None:
        inputs = iter(["r"])
        loop = CLIReviewLoop(
            input_fn=lambda _prompt="": next(inputs),
            print_fn=lambda *_args: None,
        )
        decision = self._make_decision()
        results = loop.review_batch([decision])
        assert results[0]["action_taken"] == "reject"
        assert decision.receipt_state == ReceiptState.EXPIRED.value

    def test_skip_flow(self) -> None:
        inputs = iter(["s"])
        loop = CLIReviewLoop(
            input_fn=lambda _prompt="": next(inputs),
            print_fn=lambda *_args: None,
        )
        decision = self._make_decision()
        results = loop.review_batch([decision])
        assert results[0]["action_taken"] == "skip"
        assert decision.receipt_state == ReceiptState.CREATED.value

    def test_edit_flow(self) -> None:
        inputs = iter(["e", "star"])
        loop = CLIReviewLoop(
            input_fn=lambda _prompt="": next(inputs),
            print_fn=lambda *_args: None,
        )
        decision = self._make_decision(final_action="archive")
        results = loop.review_batch([decision])
        assert results[0]["action_taken"] == "edit"
        assert results[0]["final_action"] == "star"
        assert decision.final_action == "star"

    def test_invalid_then_valid_choice(self) -> None:
        inputs = iter(["x", "z", "a"])
        loop = CLIReviewLoop(
            input_fn=lambda _prompt="": next(inputs),
            print_fn=lambda *_args: None,
        )
        decision = self._make_decision()
        results = loop.review_batch([decision])
        assert results[0]["action_taken"] == "approve"

    def test_approve_callback(self) -> None:
        approved: list[TriageDecision] = []
        inputs = iter(["a"])
        loop = CLIReviewLoop(
            input_fn=lambda _prompt="": next(inputs),
            print_fn=lambda *_args: None,
            on_approve=lambda d: approved.append(d),
        )
        decision = self._make_decision()
        loop.review_batch([decision])
        assert len(approved) == 1
        assert approved[0].receipt_id == "test-receipt"

    def test_reject_callback(self) -> None:
        rejected: list[TriageDecision] = []
        inputs = iter(["r"])
        loop = CLIReviewLoop(
            input_fn=lambda _prompt="": next(inputs),
            print_fn=lambda *_args: None,
            on_reject=lambda d: rejected.append(d),
        )
        decision = self._make_decision()
        loop.review_batch([decision])
        assert len(rejected) == 1

    def test_batch_multiple_decisions(self) -> None:
        inputs = iter(["a", "r", "s"])
        loop = CLIReviewLoop(
            input_fn=lambda _prompt="": next(inputs),
            print_fn=lambda *_args: None,
        )
        decisions = [
            self._make_decision(receipt_id="r1"),
            self._make_decision(receipt_id="r2"),
            self._make_decision(receipt_id="r3"),
        ]
        results = loop.review_batch(decisions)
        assert len(results) == 3
        assert results[0]["action_taken"] == "approve"
        assert results[1]["action_taken"] == "reject"
        assert results[2]["action_taken"] == "skip"
