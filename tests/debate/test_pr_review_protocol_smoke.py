from __future__ import annotations

import pytest

from aragora.swarm.pr_review_protocol import (
    PROTOCOL_STATUS,
    RECOMMEND_ATTENTION,
    PRReviewerExecutionFailure,
    default_pr_review_protocol,
)

_PACKET_KWARGS = dict(
    repo="synaptent/aragora",
    pr_number=6355,
    title="Add PR review protocol scaffold",
    base_sha="base123",
    head_sha="head456",
    mergeable="MERGEABLE",
    review_decision="REVIEW_REQUIRED",
    checks_summary="2 pending / 10 total",
    has_failures=False,
    has_pending=True,
    additions=650,
    deletions=20,
    changed_files=5,
    labels=["parked"],
    high_risk_paths=["aragora/swarm/pr_review_protocol.py"],
    validation_commands=["python -m pytest tests/debate/test_pr_review_protocol_smoke.py -q"],
    machine_recommendation=RECOMMEND_ATTENTION,
    machine_recommendation_reason="metadata-derived attention recommendation",
)


def _mock_provider_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")

    def fake_which(binary: str) -> str | None:
        return {
            "claude": "/usr/bin/claude",
            "gemini": "/usr/bin/gemini",
        }.get(binary)

    monkeypatch.setattr("aragora.review.provider_slots.shutil.which", fake_which)


def test_pr_review_protocol_packet_smoke() -> None:
    """Metadata-only packets must not probe provider availability (#8185)."""
    packet = default_pr_review_protocol().build_packet(**_PACKET_KWARGS)

    assert packet.status == PROTOCOL_STATUS
    assert packet.binding.pr_number == 6355
    assert packet.recommendation_class == RECOMMEND_ATTENTION
    assert len(packet.provider_slots) == 5
    assert [slot.status for slot in packet.provider_slots] == ["not_probed"] * 5
    assert [slot.selected_provider for slot in packet.provider_slots] == [None] * 5
    for slot in packet.provider_slots:
        assert slot.candidate_checks == []
    assert packet.provider_slots[0].candidates == ["claude", "anthropic-api"]
    assert packet.top_findings
    assert packet.top_findings[0].source == PROTOCOL_STATUS
    assert packet.validation_summary["has_pending"] is True
    assert packet.to_dict()["binding"]["head_sha"] == "head456"


def test_pr_review_protocol_packet_probes_providers_for_live_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Packets carrying live reviewer results resolve real provider slots."""
    _mock_provider_availability(monkeypatch)

    packet = default_pr_review_protocol().build_packet(
        **_PACKET_KWARGS,
        execution_failures=[
            PRReviewerExecutionFailure(
                slot_id="logic",
                review_role="logic_reviewer",
                provider="claude",
                reason="reviewer timed out",
            )
        ],
    )

    assert packet.status == f"{PROTOCOL_STATUS}_fallback_execution_failed"
    assert packet.binding.pr_number == 6355
    assert len(packet.provider_slots) == 5
    assert packet.provider_slots[0].selected_provider == "claude"
    assert packet.provider_slots[1].selected_provider == "openai-api"
    assert packet.provider_slots[2].selected_provider == "gemini-cli"
    assert packet.provider_slots[4].selected_provider == "mistral-api"
    assert packet.top_findings
    assert packet.validation_summary["has_pending"] is True
    assert packet.to_dict()["binding"]["head_sha"] == "head456"
