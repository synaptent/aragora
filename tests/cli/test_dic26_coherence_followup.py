"""CLI tests: ``aragora coherence-scan --emit-followup`` (DIC-17 × DIC-26 bridge).

Verifies that the ``--emit-followup`` flag on ``coherence-scan``:
- Is off by default (no proposals emitted without the flag).
- Requires ``ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED=1`` to generate proposals.
- Emits DIC-17 proposals in text mode when both flags are set and
  error-severity issues are present.
- Emits DIC-17 proposals in JSON mode (rich dict with source_key / title /
  rationale / labels).
- Produces no proposals for warning-severity issues only.
- Omits the ``proposals`` JSON key when there are no proposals.

Gating: ``ARAGORA_COHERENCE_MONITOR_ENABLED`` + ``ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED``
must both be set for proposals to flow. Default is OFF; live queue is unaffected.

Advances: issue #6027 (DIC-17), issue #6220 (DIC-26).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from aragora.cli.commands.dic26_coherence import cmd_coherence_scan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _args(
    input_path: str,
    *,
    json_output: bool = False,
    emit_followup: bool = False,
    gap: float = 0.5,
    min_conf: float = 0.3,
) -> argparse.Namespace:
    ns = argparse.Namespace()
    ns.input = input_path
    ns.json = json_output
    ns.emit_followup = emit_followup
    ns.contradiction_gap = gap
    ns.min_confidence = min_conf
    return ns


def _write(tmp_path: Path, data: object, name: str = "beliefs.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


_CONTRADICTING = [
    {"belief_id": "b1", "subject": "rate-limiter", "confidence": 0.95, "status": "pass"},
    {"belief_id": "b2", "subject": "rate-limiter", "confidence": 0.04, "status": "fail"},
]

_WARNING_ONLY = [
    {
        "belief_id": "b3",
        "subject": "auth-pass",
        "confidence": 0.40,
        "status": "pass",
        "evidence_paths": ["docs/auth.md"],
    },
    {
        "belief_id": "b4",
        "subject": "auth-fail",
        "confidence": 0.60,
        "status": "fail",
        "evidence_paths": ["docs/auth.md"],
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmitFollowupDefault:
    def test_no_proposals_without_emit_followup_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Without --emit-followup, proposals section never appears."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        p = _write(tmp_path, _CONTRADICTING)
        rc = cmd_coherence_scan(_args(str(p), emit_followup=False))
        assert rc == 0
        assert "follow-up" not in capsys.readouterr().out

    def test_json_no_proposals_key_without_emit_followup_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """JSON output omits proposals key when --emit-followup is not set."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        p = _write(tmp_path, _CONTRADICTING)
        rc = cmd_coherence_scan(_args(str(p), json_output=True, emit_followup=False))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "proposals" not in d


class TestEmitFollowupGating:
    def test_no_proposals_when_followup_flag_unset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--emit-followup with ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED unset yields no proposals."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.delenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", raising=False)
        p = _write(tmp_path, _CONTRADICTING)
        rc = cmd_coherence_scan(_args(str(p), emit_followup=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "DIC-17 follow-up proposals: none" in out
        assert "ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED" in out

    def test_json_no_proposals_key_when_followup_flag_unset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.delenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", raising=False)
        p = _write(tmp_path, _CONTRADICTING)
        rc = cmd_coherence_scan(_args(str(p), json_output=True, emit_followup=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "proposals" not in d


class TestEmitFollowupWithBothFlagsSet:
    def test_proposals_appear_in_text_output(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        p = _write(tmp_path, _CONTRADICTING)
        rc = cmd_coherence_scan(_args(str(p), emit_followup=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "DIC-17 follow-up proposals:" in out
        assert "none" not in out
        assert "source_key" not in out  # rich dict in JSON only; text uses bracket format

    def test_proposals_source_key_in_text_output(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        p = _write(tmp_path, _CONTRADICTING)
        cmd_coherence_scan(_args(str(p), emit_followup=True))
        out = capsys.readouterr().out
        assert "[coherence_issue_" in out

    def test_no_boss_ready_label_in_output(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Queue-governance invariant: boss-ready must never appear in proposals."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        p = _write(tmp_path, _CONTRADICTING)
        cmd_coherence_scan(_args(str(p), emit_followup=True))
        assert "boss-ready" not in capsys.readouterr().out

    def test_proposals_in_json_output(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        p = _write(tmp_path, _CONTRADICTING)
        rc = cmd_coherence_scan(_args(str(p), json_output=True, emit_followup=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "proposals" in d
        assert len(d["proposals"]) >= 1
        prop = d["proposals"][0]
        assert prop["source_kind"] == "coherence_issue"
        assert "source_key" in prop
        assert "title" in prop
        assert "rationale" in prop
        assert "labels" in prop
        assert "boss-ready" not in prop["labels"]


class TestEmitFollowupWarningsOnly:
    def test_warning_issues_produce_no_proposals(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Warning-severity evidence conflicts must not generate follow-up proposals."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        p = _write(tmp_path, _WARNING_ONLY)
        rc = cmd_coherence_scan(_args(str(p), emit_followup=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "DIC-17 follow-up proposals: none" in out

    def test_json_no_proposals_for_warnings(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        p = _write(tmp_path, _WARNING_ONLY)
        rc = cmd_coherence_scan(_args(str(p), json_output=True, emit_followup=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "proposals" not in d
