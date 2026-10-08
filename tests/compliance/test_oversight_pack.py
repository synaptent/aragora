"""Article 14 oversight evidence pack (#8230).

Acceptance: the pack cites real receipts (native or ODR) over a window with
per-receipt dispositions, honest exclusions, computed clause statuses, and a
tamper-evidence digest; the CLI command produces JSON + Markdown.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aragora.compliance.oversight_pack import (
    ARTICLE_14_CLAUSES,
    build_oversight_pack,
    load_receipts_from_dirs,
    render_oversight_pack_markdown,
)

NOW = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)


def _native(receipt_id: str, ts: str, verdict: str = "PASS") -> dict:
    return {
        "receipt_id": receipt_id,
        "timestamp": ts,
        "verdict": verdict,
        "confidence": 0.9,
    }


def _odr(receipt_id: str, ts: str, attested: bool) -> dict:
    doc = {
        "odr_version": "0.1",
        "receipt_id": receipt_id,
        "issued_at": ts,
        "claim": {"verdict": "PASS"},
        "confidence": {"value": 0.8},
        "attestation": {"disposition": "autonomous"},
    }
    if attested:
        doc["attestation"] = {
            "disposition": "human_attested",
            "attestor": {"id": "scarmani", "role": "oversight"},
            "execution_identity": {"id": "an0mium"},
            "attested_at": ts,
            "observed": {"head_sha": "b" * 40, "evidence_digest": "sha256:" + "a" * 64},
            "mechanism": {"type": "settlement_status", "context": "aragora/human-settlement"},
        }
    return doc


class TestBuildPack:
    def test_windowing_and_dispositions(self) -> None:
        receipts = [
            _native("in-window-auto", "2026-07-10T00:00:00+00:00"),
            _odr("in-window-attested", "2026-07-12T00:00:00+00:00", attested=True),
            _native("too-old", "2026-05-01T00:00:00+00:00"),
            _native("no-timestamp", ""),
        ]
        pack = build_oversight_pack(receipts, window_days=30, now=NOW)
        summary = pack["summary"]
        assert summary["receipts_in_window"] == 2
        assert summary["human_attested"] == 1
        assert summary["autonomous"] == 1
        assert summary["excluded_out_of_window"] == 1
        assert summary["excluded_no_timestamp"] == 1
        assert summary["attestor_identities"] == ["scarmani"]
        assert summary["mechanisms"] == {"settlement_status": 1}

    def test_attestations_map_upgrades_native_receipt(self) -> None:
        att = {
            "disposition": "human_attested",
            "attestor": {"id": "scarmani"},
            "execution_identity": {"id": "an0mium"},
            "attested_at": "2026-07-10T01:00:00+00:00",
            "mechanism": {"type": "preapproval_comment"},
        }
        pack = build_oversight_pack(
            [_native("r1", "2026-07-10T00:00:00+00:00")],
            window_days=30,
            now=NOW,
            attestations={"r1": att},
        )
        entry = pack["receipts"][0]
        assert entry["disposition"] == "human_attested"
        assert entry["attestor"] == "scarmani"
        assert entry["mechanism"] == "preapproval_comment"

    def test_clause_statuses_with_attestation(self) -> None:
        pack = build_oversight_pack(
            [_odr("r1", "2026-07-10T00:00:00+00:00", attested=True)],
            window_days=30,
            now=NOW,
        )
        by_clause = {c["clause"]: c for c in pack["article_14_mapping"]}
        assert len(by_clause) == len(ARTICLE_14_CLAUSES)
        assert by_clause["14(1)"]["status"] == "satisfied"
        assert by_clause["14(4)(d)"]["status"] == "satisfied"
        # 14(4)(e) is capped at partial by design: receipts alone cannot
        # evidence interruption capability.
        assert by_clause["14(4)(e)"]["status"] == "partial"

    def test_clause_statuses_without_attestation_are_honest(self) -> None:
        pack = build_oversight_pack(
            [_native("r1", "2026-07-10T00:00:00+00:00")], window_days=30, now=NOW
        )
        by_clause = {c["clause"]: c for c in pack["article_14_mapping"]}
        assert by_clause["14(1)"]["status"] == "partial"
        assert by_clause["14(4)(d)"]["status"] == "partial"
        # Content-dependent clauses need the evidence fields, not mere
        # receipt presence: a bare native receipt carries verdict+confidence
        # (14(2)) but no responses/dissent/reasoning.
        assert by_clause["14(2)"]["status"] == "satisfied"
        assert by_clause["14(4)(a)"]["status"] == "partial"
        assert by_clause["14(4)(b)"]["status"] == "partial"
        assert by_clause["14(4)(c)"]["status"] == "partial"

    def test_content_clauses_need_actual_evidence_fields(self) -> None:
        """Round-5 finding (claude): clause presence must be computed from the
        evidence fields the clause names, never from receipt presence."""
        rich = {
            "receipt_id": "r-rich",
            "timestamp": "2026-07-10T00:00:00+00:00",
            "verdict": "PASS",
            "confidence": 0.9,
            "dissenting_views": ["grok: latency risk"],
            "agent_responses": [{"agent": "a", "response": "supported"}],
            "verdict_reasoning": "Consensus reached with strong agreement",
        }
        pack = build_oversight_pack([rich], window_days=30, now=NOW)
        by_clause = {c["clause"]: c for c in pack["article_14_mapping"]}
        for clause in ("14(2)", "14(4)(a)", "14(4)(b)", "14(4)(c)"):
            assert by_clause[clause]["status"] == "satisfied", clause
        entry = pack["receipts"][0]
        assert entry["evidence"] == {
            "has_confidence": True,
            "has_responses": True,
            "has_dissent_record": True,
            "has_reasoning": True,
        }
        # Mixed evidence: one rich + one bare receipt -> partial with counts.
        pack = build_oversight_pack(
            [rich, _native("r-bare", "2026-07-11T00:00:00+00:00")],
            window_days=30,
            now=NOW,
        )
        by_clause = {c["clause"]: c for c in pack["article_14_mapping"]}
        assert by_clause["14(4)(a)"]["status"] == "partial"
        assert "1/2" in by_clause["14(4)(a)"]["status_basis"]

    def test_odr_absent_blocks_do_not_count_as_evidence(self) -> None:
        doc = _odr("r-abs", "2026-07-10T00:00:00+00:00", attested=False)
        doc["reasoning"] = {"status": "absent", "reason": "none recorded"}
        doc["quorum"] = {"status": "absent", "reason": "none recorded"}
        pack = build_oversight_pack([doc], window_days=30, now=NOW)
        entry = pack["receipts"][0]
        assert entry["evidence"]["has_reasoning"] is False
        assert entry["evidence"]["has_responses"] is False

    def test_bare_human_attested_block_not_trusted(self) -> None:
        """A block claiming human_attested without attestor/when/mechanism is
        recorded as invalid_attestation and never counts as oversight
        (openai review round 2 on #9417)."""
        doc = _odr("r-bare", "2026-07-10T00:00:00+00:00", attested=False)
        doc["attestation"] = {"disposition": "human_attested"}
        pack = build_oversight_pack([doc], window_days=30, now=NOW)
        entry = pack["receipts"][0]
        assert entry["disposition"] == "invalid_attestation"
        assert entry["attestation_invalid_reason"] == "missing attestor.id"
        assert pack["summary"]["human_attested"] == 0
        assert pack["summary"]["other_dispositions"] == {"invalid_attestation": 1}
        assert pack["summary"]["attestor_identities"] == []
        by_clause = {c["clause"]: c for c in pack["article_14_mapping"]}
        assert by_clause["14(1)"]["status"] == "partial"

    def test_self_attested_block_not_trusted(self) -> None:
        doc = _odr("r-self", "2026-07-10T00:00:00+00:00", attested=True)
        doc["attestation"]["execution_identity"] = {"id": "scarmani"}
        pack = build_oversight_pack([doc], window_days=30, now=NOW)
        entry = pack["receipts"][0]
        assert entry["disposition"] == "invalid_attestation"
        assert entry["attestation_invalid_reason"] == "attestor equals execution identity"
        assert pack["summary"]["human_attested"] == 0

    def test_attestations_map_also_validated(self) -> None:
        pack = build_oversight_pack(
            [_native("r1", "2026-07-10T00:00:00+00:00")],
            window_days=30,
            now=NOW,
            attestations={"r1": {"disposition": "human_attested"}},
        )
        assert pack["receipts"][0]["disposition"] == "invalid_attestation"
        assert pack["summary"]["human_attested"] == 0

    def test_non_object_attestations_value_reported_not_crash(self) -> None:
        """Round-6 finding (openai P3): a non-object --attestations value must
        be reported as an invalid attestation, not crash the pack."""
        pack = build_oversight_pack(
            [_native("r1", "2026-07-10T00:00:00+00:00")],
            window_days=30,
            now=NOW,
            attestations={"r1": "human_attested"},
        )
        entry = pack["receipts"][0]
        assert entry["disposition"] == "invalid_attestation"
        assert entry["attestation_invalid_reason"] == "attestation block is not an object"
        assert pack["summary"]["human_attested"] == 0

    def test_invalid_settlement_attestations_reported_not_counted(self) -> None:
        good = {
            "pr": 1,
            "attestation": {
                "disposition": "human_attested",
                "attestor": {"id": "overseer"},
                "attested_at": "2026-07-10T01:00:00+00:00",
                "mechanism": {
                    "type": "settlement_status",
                    "ref": "https://api.github.com/repos/o/r/statuses/abc",
                },
                "execution_identity": {"id": "agent-bot"},
                "observed": {"head_sha": "b" * 40, "evidence_digest": "sha256:" + "1" * 64},
            },
        }
        bad = {"pr": 2, "attestation": {"disposition": "human_attested"}}
        pack = build_oversight_pack(
            [], window_days=30, now=NOW, settlement_attestations=[good, bad]
        )
        assert pack["summary"]["settlement_attestations"] == 1
        assert pack["summary"]["settlement_attestations_invalid"] == 1
        assert pack["settlement_attestations_invalid"][0]["invalid_reason"] == (
            "missing attestor.id"
        )
        by_clause = {c["clause"]: c for c in pack["article_14_mapping"]}
        # Trail settlements alone cap identity clauses at partial (round 7).
        assert by_clause["14(1)"]["status"] == "partial"
        assert (
            "demonstrate the oversight mechanism operating" in (by_clause["14(1)"]["status_basis"])
        )

    def test_settlement_without_resolvable_trail_not_counted(self) -> None:
        """Settlement entries face a stricter bar than receipt blocks: without
        a resolvable mechanism.ref and observed.head_sha, a synthetic block
        could satisfy identity clauses with no verifiable trail (round-4
        finding)."""
        no_ref = {
            "pr": 5,
            "attestation": {
                "disposition": "human_attested",
                "attestor": {"id": "overseer"},
                "attested_at": "2026-07-10T01:00:00+00:00",
                "mechanism": {"type": "settlement_status"},
                "execution_identity": {"id": "agent-bot"},
                "observed": {"head_sha": "e" * 40, "evidence_digest": "sha256:" + "4" * 64},
            },
        }
        no_head = {
            "pr": 6,
            "attestation": {
                "disposition": "human_attested",
                "attestor": {"id": "overseer"},
                "attested_at": "2026-07-10T01:00:00+00:00",
                "mechanism": {
                    "type": "settlement_status",
                    "ref": "https://api.github.com/repos/o/r/statuses/y",
                },
                "execution_identity": {"id": "agent-bot"},
                "observed": {"evidence_digest": "sha256:" + "5" * 64},
            },
        }
        pack = build_oversight_pack(
            [], window_days=30, now=NOW, settlement_attestations=[no_ref, no_head]
        )
        assert pack["summary"]["settlement_attestations"] == 0
        reasons = {e["invalid_reason"] for e in pack["settlement_attestations_invalid"]}
        assert reasons == {
            "missing mechanism.ref (settlement evidence must be resolvable)",
            "missing observed.head_sha (settlement must be head-bound)",
        }
        by_clause = {c["clause"]: c for c in pack["article_14_mapping"]}
        assert by_clause["14(1)"]["status"] == "partial"

    def test_autonomous_block_does_not_leak_oversight_fields(self) -> None:
        """Round-10 finding: attestor/mechanism on a non-human disposition
        must not enter the entry or the audit summary."""
        doc = _odr("r-auto", "2026-07-10T00:00:00+00:00", attested=False)
        doc["attestation"] = {
            "disposition": "autonomous",
            "attestor": {"id": "stray-identity"},
            "mechanism": {"type": "settlement_status"},
        }
        pack = build_oversight_pack([doc], window_days=30, now=NOW)
        entry = pack["receipts"][0]
        assert entry["disposition"] == "autonomous"
        assert "attestor" not in entry
        assert "mechanism" not in entry
        assert pack["summary"]["attestor_identities"] == []
        assert pack["summary"]["mechanisms"] == {}

    def test_non_string_attestation_fields_not_coerced(self) -> None:
        """Round-11 finding: non-string attestor.id/attested_at/mechanism.type
        must be rejected, never str()-coerced into countable evidence."""
        for field_patch, reason in [
            ({"attestor": {"id": 123}}, "attestor.id must be a string"),
            ({"attested_at": 1234567890}, "attested_at must be a string"),
            (
                {"mechanism": {"type": ["settlement_status"]}},
                "mechanism.type must be a string",
            ),
        ]:
            doc = _odr("r-coerce", "2026-07-10T00:00:00+00:00", attested=True)
            doc["attestation"].update(field_patch)
            pack = build_oversight_pack([doc], window_days=30, now=NOW)
            entry = pack["receipts"][0]
            assert entry["disposition"] == "invalid_attestation", field_patch
            assert entry["attestation_invalid_reason"] == reason
            assert pack["summary"]["human_attested"] == 0

    def test_receipt_attestation_timestamp_windowed(self) -> None:
        """Round-12 finding: receipt-level attestations get the same
        parse/window discipline as settlement entries."""
        unparseable = _odr("r-when", "2026-07-10T00:00:00+00:00", attested=True)
        unparseable["attestation"]["attested_at"] = "yesterday-ish"
        pack = build_oversight_pack([unparseable], window_days=30, now=NOW)
        entry = pack["receipts"][0]
        assert entry["disposition"] == "invalid_attestation"
        assert entry["attestation_invalid_reason"] == "unparseable attested_at"
        assert pack["summary"]["human_attested"] == 0

        stale = _odr("r-old", "2026-07-10T00:00:00+00:00", attested=True)
        stale["attestation"]["attested_at"] = "2026-01-01T00:00:00+00:00"
        pack = build_oversight_pack([stale], window_days=30, now=NOW)
        entry = pack["receipts"][0]
        assert entry["disposition"] == "invalid_attestation"
        assert entry["attestation_invalid_reason"] == "attested_at outside pack window"
        by_clause = {c["clause"]: c for c in pack["article_14_mapping"]}
        assert by_clause["14(1)"]["status"] == "partial"

    def test_missing_execution_identity_not_counted(self) -> None:
        """Round-13 finding: without a named executor the separation check
        cannot run, so the block never counts as oversight."""
        doc = _odr("r-noexec", "2026-07-10T00:00:00+00:00", attested=True)
        del doc["attestation"]["execution_identity"]
        pack = build_oversight_pack([doc], window_days=30, now=NOW)
        entry = pack["receipts"][0]
        assert entry["disposition"] == "invalid_attestation"
        assert "identity separation unverifiable" in entry["attestation_invalid_reason"]
        assert pack["summary"]["human_attested"] == 0

    def test_settlement_without_evidence_digest_not_counted(self) -> None:
        """Round-13 finding: the pack claims status→receipt binding; a
        settlement without the embedded receipt digest cannot provide it."""
        no_digest = {
            "pr": 7,
            "attestation": {
                "disposition": "human_attested",
                "attestor": {"id": "overseer"},
                "execution_identity": {"id": "agent-bot"},
                "attested_at": "2026-07-10T01:00:00+00:00",
                "mechanism": {
                    "type": "settlement_status",
                    "ref": "https://api.github.com/repos/o/r/statuses/z",
                },
                "observed": {"head_sha": "f" * 40},
            },
        }
        pack = build_oversight_pack(
            [], window_days=30, now=NOW, settlement_attestations=[no_digest]
        )
        assert pack["summary"]["settlement_attestations"] == 0
        assert (
            "status-to-receipt binding absent"
            in (pack["settlement_attestations_invalid"][0]["invalid_reason"])
        )

    def test_odr_verdict_field_normalized(self) -> None:
        """The ODR exporter/schema use claim.verdict (round-3 finding: reading
        claim.decision produced blank verdicts for real ODR inputs); legacy
        claim.decision still tolerated."""
        pack = build_oversight_pack(
            [_odr("r-v", "2026-07-10T00:00:00+00:00", attested=False)],
            window_days=30,
            now=NOW,
        )
        assert pack["receipts"][0]["verdict"] == "PASS"
        legacy = _odr("r-d", "2026-07-10T00:00:00+00:00", attested=False)
        legacy["claim"] = {"decision": "FAIL"}
        pack = build_oversight_pack([legacy], window_days=30, now=NOW)
        assert pack["receipts"][0]["verdict"] == "FAIL"

    def test_out_of_window_settlement_not_counted(self) -> None:
        """An old externally supplied settlement must not satisfy a fresh
        pack's identity clauses (round-3 finding)."""
        stale = {
            "pr": 3,
            "attestation": {
                "disposition": "human_attested",
                "attestor": {"id": "overseer"},
                "attested_at": "2026-01-01T00:00:00+00:00",
                "mechanism": {
                    "type": "settlement_status",
                    "ref": "https://api.github.com/repos/o/r/statuses/old",
                },
                "execution_identity": {"id": "agent-bot"},
                "observed": {"head_sha": "c" * 40, "evidence_digest": "sha256:" + "2" * 64},
            },
        }
        pack = build_oversight_pack([], window_days=30, now=NOW, settlement_attestations=[stale])
        assert pack["summary"]["settlement_attestations"] == 0
        assert pack["summary"]["settlement_attestations_out_of_window"] == 1
        by_clause = {c["clause"]: c for c in pack["article_14_mapping"]}
        assert by_clause["14(1)"]["status"] == "partial"

    def test_unparseable_attested_at_settlement_invalid(self) -> None:
        bad = {
            "pr": 4,
            "attestation": {
                "disposition": "human_attested",
                "attestor": {"id": "overseer"},
                "attested_at": "yesterday-ish",
                "mechanism": {
                    "type": "settlement_status",
                    "ref": "https://api.github.com/repos/o/r/statuses/x",
                },
                "execution_identity": {"id": "agent-bot"},
                "observed": {"head_sha": "d" * 40, "evidence_digest": "sha256:" + "3" * 64},
            },
        }
        pack = build_oversight_pack([], window_days=30, now=NOW, settlement_attestations=[bad])
        assert pack["summary"]["settlement_attestations"] == 0
        assert pack["settlement_attestations_invalid"][0]["invalid_reason"] == (
            "unparseable attested_at"
        )

    def test_empty_window_all_partial_or_honest(self) -> None:
        pack = build_oversight_pack([], window_days=30, now=NOW)
        assert pack["summary"]["receipts_in_window"] == 0
        assert all(c["status"] == "partial" for c in pack["article_14_mapping"])

    def test_integrity_digest_stable_and_tamper_evident(self) -> None:
        receipts = [_odr("r1", "2026-07-10T00:00:00+00:00", attested=True)]
        pack1 = build_oversight_pack(receipts, window_days=30, now=NOW)
        pack2 = build_oversight_pack(receipts, window_days=30, now=NOW)
        assert pack1["integrity"]["content_digest"] == pack2["integrity"]["content_digest"]
        pack3 = build_oversight_pack(
            [_odr("r1", "2026-07-10T00:00:00+00:00", attested=False)],
            window_days=30,
            now=NOW,
        )
        assert pack1["integrity"]["content_digest"] != pack3["integrity"]["content_digest"]

    def test_pack_is_json_serializable(self) -> None:
        pack = build_oversight_pack(
            [_odr("r1", "2026-07-10T00:00:00+00:00", attested=True)],
            window_days=30,
            now=NOW,
        )
        json.dumps(pack)

    def test_source_paths_carried(self) -> None:
        pack = build_oversight_pack(
            [(_native("r1", "2026-07-10T00:00:00+00:00"), "docs/receipts/r1.json")],
            window_days=30,
            now=NOW,
        )
        assert pack["receipts"][0]["source"] == "docs/receipts/r1.json"


class TestMarkdown:
    def test_render_contains_clauses_and_receipts(self) -> None:
        pack = build_oversight_pack(
            [_odr("receipt-abc", "2026-07-10T00:00:00+00:00", attested=True)],
            window_days=30,
            now=NOW,
        )
        md = render_oversight_pack_markdown(pack)
        assert "Article 14" in md
        assert "14(4)(e)" in md
        assert "receipt-abc"[:16] in md
        assert "scarmani" in md
        assert pack["integrity"]["content_digest"] in md


class TestLoader:
    def test_loads_receipts_and_skips_junk(self, tmp_path: Path) -> None:
        (tmp_path / "a.json").write_text(
            json.dumps(_native("r1", "2026-07-10T00:00:00+00:00")), encoding="utf-8"
        )
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.json").write_text(
            json.dumps(_odr("r2", "2026-07-11T00:00:00+00:00", attested=True)),
            encoding="utf-8",
        )
        (tmp_path / "junk.json").write_text("[1,2,3]", encoding="utf-8")
        (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
        loaded = load_receipts_from_dirs([tmp_path, tmp_path / "missing"])
        ids = sorted(receipt["receipt_id"] for receipt, _ in loaded)
        assert ids == ["r1", "r2"]
        assert all(str(tmp_path) in source for _, source in loaded)


class TestCli:
    def test_cli_writes_json_and_markdown(self, tmp_path: Path) -> None:
        from aragora.cli.commands.compliance import _cmd_oversight_pack

        receipts_dir = tmp_path / "receipts"
        receipts_dir.mkdir()
        recent = datetime.now(timezone.utc).isoformat()
        (receipts_dir / "r1.json").write_text(
            json.dumps(_odr("r-cli-1", recent, attested=True)), encoding="utf-8"
        )
        out_json = tmp_path / "pack.json"
        out_md = tmp_path / "pack.md"
        args = argparse.Namespace(
            window="30d",
            receipts_dirs=[str(receipts_dir)],
            attestations=None,
            output=str(out_json),
            markdown=str(out_md),
        )
        _cmd_oversight_pack(args)
        pack = json.loads(out_json.read_text(encoding="utf-8"))
        assert pack["summary"]["receipts_in_window"] == 1
        assert pack["summary"]["human_attested"] == 1
        assert "Article 14" in out_md.read_text(encoding="utf-8")

    def test_cli_invalid_window_exits(self, tmp_path: Path) -> None:
        from aragora.cli.commands.compliance import _parse_window_days

        assert _parse_window_days("30d") == 30
        assert _parse_window_days("12w") == 84
        assert _parse_window_days("720h") == 30
        assert _parse_window_days("45") == 45
        with pytest.raises(SystemExit):
            _parse_window_days("soon")
