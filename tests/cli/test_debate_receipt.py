from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aragora.cli.commands.debate import _persist_debate_receipt
from aragora.cli.commands.receipt import cmd_receipt_verify
from aragora.gauntlet.receipt_models import DecisionReceipt


def test_persisted_debate_receipt_verifies_with_receipt_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = SimpleNamespace(
        debate_id="debate-smoke",
        task="Verify provider-bootstrap dogfood receipts.",
        consensus_reached=True,
        confidence=0.87,
        final_answer="Provider bootstrap receipt is verifiable.",
        rounds_used=1,
        dissenting_views=[],
        metadata={
            "agent_models": {
                "grok_proposer": {
                    "provider": "xai",
                    "provider_display": "xAI",
                    "model": "grok-4-latest",
                    "llm_label": "grok-4-latest via xAI",
                }
            }
        },
        messages=[
            SimpleNamespace(
                agent="grok_proposer",
                role="proposer",
                round=0,
                content="Provider bootstrap receipt is verifiable.",
            )
        ],
    )

    receipt_path = _persist_debate_receipt(result)

    assert receipt_path is not None
    data = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    assert data["receipt_id"] == "debate-debate-smoke"
    assert data["verdict"] == "PASS"
    assert data["timestamp"].endswith("Z")
    assert len(data["artifact_hash"]) == 64
    assert DecisionReceipt.from_dict(data).verify_integrity() is True

    with pytest.raises(SystemExit) as excinfo:
        cmd_receipt_verify(argparse.Namespace(receipt=receipt_path, verbose=False))

    assert excinfo.value.code == 0
    assert "Result: VALID" in capsys.readouterr().out


def _mixed_family_result() -> SimpleNamespace:
    """A mixed-family debate result where mistral participated (critique)
    but produced no Message — the #8101 silent-drop scenario."""
    return SimpleNamespace(
        debate_id="debate-mixed",
        task="Mixed family debate",
        consensus_reached=True,
        confidence=0.8,
        final_answer="Answer",
        rounds_used=1,
        dissenting_views=[],
        participants=["grok", "mistral-api"],
        proposals={"grok": "Proposal text"},
        critiques=[SimpleNamespace(agent="mistral-api", target_agent="grok")],
        votes=[],
        metadata={
            "agent_models": {
                "grok": {
                    "provider": "xai",
                    "provider_display": "xAI",
                    "model": "grok-4-latest",
                    "llm_label": "grok-4-latest via xAI",
                },
                "mistral-api": {
                    "provider": "mistral",
                    "provider_display": "Mistral",
                    "model": "mistral-large-latest",
                    "llm_label": "mistral-large-latest via Mistral",
                },
            },
            "agent_roster": {
                "requested": ["grok", "mistral-api"],
                "created": ["grok", "mistral-api"],
                "failed": [],
            },
        },
        messages=[SimpleNamespace(agent="grok", role="proposer", round=0, content="Proposal text")],
    )


def test_receipt_records_full_roster_in_mixed_family_debate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #8101: mixed grok,mistral-api debates must not silently drop
    mistral from the receipt agents list just because it authored no Message."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    receipt_path = _persist_debate_receipt(_mixed_family_result())

    assert receipt_path is not None
    data = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    assert data["agents"] == ["grok", "mistral-api"]
    assert data["agents_requested"] == ["grok", "mistral-api"]
    assert data["agents_failed"] == []
    assert DecisionReceipt.from_dict(data).verify_integrity() is True


def test_receipt_agent_contributions_are_artifact_backed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-agent contribution counts must reflect actual artifacts so the
    roster entry cannot be mistaken for fabricated participation."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    receipt_path = _persist_debate_receipt(_mixed_family_result())

    assert receipt_path is not None
    data = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    contributions = data["agent_contributions"]
    assert contributions["grok"]["messages"] == 1
    assert contributions["grok"]["proposals"] == 1
    assert contributions["mistral-api"]["critiques"] == 1
    assert contributions["mistral-api"]["messages"] == 0
    # Consensus support must stay artifact-backed (both contributed here).
    assert set(data["consensus_proof"]["supporting_agents"]) == {"grok", "mistral-api"}


def test_receipt_does_not_count_silent_agents_as_supporting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An agent in the roster with zero artifacts is listed (requested/created)
    but must NOT appear among consensus supporting_agents."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = _mixed_family_result()
    result.critiques = []  # mistral now produced nothing at all

    receipt_path = _persist_debate_receipt(result)

    assert receipt_path is not None
    data = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    assert data["agents"] == ["grok", "mistral-api"]
    assert data["agent_contributions"]["mistral-api"] == {
        "messages": 0,
        "proposals": 0,
        "critiques": 0,
        "votes": 0,
    }
    assert data["consensus_proof"]["supporting_agents"] == ["grok"]


def test_receipt_agents_fall_back_to_artifact_authors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a participants roster, agents are unioned from all artifact
    sources (messages, proposals, critiques, votes) — not just messages."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = _mixed_family_result()
    del result.participants
    result.metadata.pop("agent_roster")

    receipt_path = _persist_debate_receipt(result)

    assert receipt_path is not None
    data = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    assert set(data["agents"]) == {"grok", "mistral-api"}


def test_receipt_carries_crux_cards_from_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A debate run with enable_crux_cards (--crux-cards) attaches a crux_cards
    block to result metadata; the persisted receipt must carry it as cruxes
    and still verify."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = _mixed_family_result()
    result.metadata["crux_cards"] = {
        "items": [
            {
                "claim_id": "c1",
                "statement": "Rate limiter should be token-bucket",
                "crux_score": 0.72,
                "author": "grok",
                "contesting_agents": ["mistral-api"],
            }
        ],
        "total_claims": 4,
        "total_disagreements": 1,
        "convergence_barrier": 0.4,
        "detector": "belief_network",
    }

    receipt_path = _persist_debate_receipt(result)

    assert receipt_path is not None
    data = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    assert data["cruxes"]["items"][0]["claim_id"] == "c1"
    assert data["cruxes"]["detector"] == "belief_network"
    # Cruxes bind into artifact_hash, so the schema version must signal it
    # to older verifiers instead of reading as tampering.
    assert data["schema_version"] == "1.2"
    assert DecisionReceipt.from_dict(data).verify_integrity() is True


def test_receipt_preserves_long_reasoning_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Receipts are audit artifacts: verdict_reasoning, final_answer, and
    agent responses longer than 2,000 chars must survive persistence intact
    (previously silently cut mid-word at 2,000, weakening signed evidence)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    long_answer = "All twelve mitigations were weighed against Article 14. " * 100
    long_response = "The proposer's threat model holds because " * 120
    assert len(long_answer) > 2000 and len(long_response) > 2000
    result = _mixed_family_result()
    result.final_answer = long_answer
    result.messages = [
        SimpleNamespace(agent="grok", role="proposer", round=0, content=long_response)
    ]

    receipt_path = _persist_debate_receipt(result)

    assert receipt_path is not None
    data = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    assert data["final_answer"] == long_answer
    assert data["verdict_reasoning"] == long_answer
    assert data["agent_responses"][0]["response"] == long_response.strip()
    assert DecisionReceipt.from_dict(data).verify_integrity() is True


def test_receipt_omits_cruxes_when_crux_cards_absent_or_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flag-off receipts must stay byte-identical: no cruxes key without items."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    result = _mixed_family_result()
    receipt_path = _persist_debate_receipt(result)
    assert receipt_path is not None
    data = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    assert "cruxes" not in data
    assert data["schema_version"] == "1.1"

    empty = _mixed_family_result()
    empty.metadata["crux_cards"] = {"items": []}
    receipt_path = _persist_debate_receipt(empty)
    assert receipt_path is not None
    data = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    assert "cruxes" not in data
    assert data["schema_version"] == "1.1"
