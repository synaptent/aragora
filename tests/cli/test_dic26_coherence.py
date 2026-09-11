"""DIC-26 coherence-scan CLI tests.

Flags: ARAGORA_COHERENCE_MONITOR_ENABLED (default OFF),
       ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED (default OFF, required for proposals)
Live queue effect: none
Advances: issues #6220 (DIC-26) and #6027 (DIC-17 --emit-followup flag)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from aragora.cli.commands.dic26_coherence import (
    _load_entries,
    _render_proposals,
    cmd_coherence_scan,
)


def _args(
    input_path: str,
    *,
    json_output: bool = False,
    gap: float = 0.5,
    min_conf: float = 0.3,
    emit_followup: bool = False,
) -> argparse.Namespace:
    ns = argparse.Namespace()
    ns.input = input_path
    ns.json = json_output
    ns.contradiction_gap = gap
    ns.min_confidence = min_conf
    ns.emit_followup = emit_followup
    return ns


def _write(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "beliefs.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_disabled_by_default_exits_1(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ARAGORA_COHERENCE_MONITOR_ENABLED", raising=False)
    assert cmd_coherence_scan(_args(str(_write(tmp_path, [])))) == 1


def test_missing_input_file_exits_1(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
    assert cmd_coherence_scan(_args(str(tmp_path / "nonexistent.json"))) == 1


def test_empty_ledger_exits_0_and_reports_coherent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
    assert cmd_coherence_scan(_args(str(_write(tmp_path, [])))) == 0
    assert "coherent" in capsys.readouterr().out


def test_json_output_is_valid_for_coherent_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
    entries = [
        {"belief_id": "b1", "subject": "claim.rate_limit", "confidence": 0.9, "status": "pass"}
    ]
    assert cmd_coherence_scan(_args(str(_write(tmp_path, entries)), json_output=True)) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["scanned"] == 1 and data["coherent"] is True and data["issue_count"] == 0


def test_contradiction_flagged_in_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
    entries = [
        {"belief_id": "b_high", "subject": "claim.x", "confidence": 0.95, "status": "pass"},
        {"belief_id": "b_low", "subject": "claim.x", "confidence": 0.05, "status": "fail"},
    ]
    assert cmd_coherence_scan(_args(str(_write(tmp_path, entries)), json_output=True)) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["contradiction_count"] == 1 and data["coherent"] is False


def test_confidence_rot_flagged_in_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
    entries = [
        {"belief_id": "b_rotten", "subject": "claim.stale", "confidence": 0.1, "status": "stale"}
    ]
    assert (
        cmd_coherence_scan(_args(str(_write(tmp_path, entries)), json_output=True, min_conf=0.3))
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert data["confidence_rot_count"] == 1


def test_load_entries_skips_bad_confidence_type(tmp_path: Path) -> None:
    raw = [
        {"belief_id": "good", "subject": "s", "confidence": 0.8},
        {"belief_id": "bad_conf", "subject": "s", "confidence": "not-a-float"},
    ]
    p = tmp_path / "b.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    entries = _load_entries(p)
    assert len(entries) == 1 and entries[0].belief_id == "good"


def test_load_entries_skips_missing_belief_id(tmp_path: Path) -> None:
    raw = [
        {"belief_id": "ok", "subject": "s", "confidence": 0.7},
        {"subject": "no_id", "confidence": 0.5},
    ]
    p = tmp_path / "b.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    entries = _load_entries(p)
    assert len(entries) == 1 and entries[0].belief_id == "ok"


def test_load_entries_accepts_single_object(tmp_path: Path) -> None:
    raw = {"belief_id": "singleton", "subject": "s", "confidence": 0.6}
    p = tmp_path / "b.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    entries = _load_entries(p)
    assert len(entries) == 1 and entries[0].belief_id == "singleton"


# ---------------------------------------------------------------------------
# DIC-17 --emit-followup flag tests
# ---------------------------------------------------------------------------

_CONTRADICTING = [
    {"belief_id": "bH", "subject": "auth.gateway", "confidence": 0.95, "status": "pass"},
    {"belief_id": "bL", "subject": "auth.gateway", "confidence": 0.04, "status": "fail"},
]
_WARNING_ONLY = [
    {"belief_id": "w1", "subject": "cache.hit", "confidence": 0.40, "status": "pass",
     "evidence_paths": ["docs/cache.md"]},
    {"belief_id": "w2", "subject": "cache.miss", "confidence": 0.60, "status": "fail",
     "evidence_paths": ["docs/cache.md"]},
]


class TestEmitFollowupFlag:
    def test_emit_followup_absent_by_default_no_proposals(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Without --emit-followup, proposals must never appear in text output."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        rc = cmd_coherence_scan(_args(str(_write(tmp_path, _CONTRADICTING))))
        assert rc == 0
        out = capsys.readouterr().out
        assert "follow-up proposals" not in out

    def test_emit_followup_requires_env_flag_for_proposals(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--emit-followup is set but ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED is off."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.delenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", raising=False)
        rc = cmd_coherence_scan(
            _args(str(_write(tmp_path, _CONTRADICTING)), emit_followup=True)
        )
        assert rc == 0
        out = capsys.readouterr().out
        # The --emit-followup section is printed but proposals list is empty
        # (env gate not set), so the "follow-up proposals (N)" line must not appear
        assert "follow-up proposals" not in out

    def test_emit_followup_populates_proposals_in_text(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Both flags set: text output shows follow-up proposals section."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        rc = cmd_coherence_scan(
            _args(str(_write(tmp_path, _CONTRADICTING)), emit_followup=True)
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "follow-up proposals" in out
        assert "printed, not filed" in out

    def test_emit_followup_proposals_in_json_output(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Both flags set in JSON mode: JSON output includes 'proposals' key."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        rc = cmd_coherence_scan(
            _args(str(_write(tmp_path, _CONTRADICTING)), json_output=True, emit_followup=True)
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "proposals" in data
        assert isinstance(data["proposals"], list) and len(data["proposals"]) >= 1

    def test_emit_followup_no_proposals_for_warning_only_issues(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Warning-severity evidence conflicts must never produce proposals."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        rc = cmd_coherence_scan(
            _args(str(_write(tmp_path, _WARNING_ONLY)), emit_followup=True)
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "follow-up proposals" not in out

    def test_emit_followup_no_boss_ready_label_in_json(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Queue-governance invariant: boss-ready must never appear in proposals."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        rc = cmd_coherence_scan(
            _args(str(_write(tmp_path, _CONTRADICTING)), json_output=True, emit_followup=True)
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        for proposal_prov in data.get("proposals", []):
            labels = proposal_prov.get("labels", [])
            assert "boss-ready" not in labels, f"boss-ready found in {labels}"

    def test_render_proposals_noop_when_empty(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """_render_proposals prints nothing when report.proposals is empty."""
        from aragora.epistemic.coherence import CoherenceReport

        report = CoherenceReport(scanned=0)
        _render_proposals(report)
        assert capsys.readouterr().out == ""
