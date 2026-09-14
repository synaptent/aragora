"""Tests for scripts/measure_work_loss.py (steering program Phase 0.2, Pillar 7).

All three inputs (outbox items, ls-remote output, PR list) are injected;
no git / gh subprocess calls happen in these tests.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.measure_work_loss import (
    UNIT_DEFINITIONS,
    compute_work_loss,
    load_outbox_items,
    main,
    parse_ls_remote,
    render_waste_block,
)

NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
WINDOW_START = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)


def _pr(
    number: int,
    head_ref: str,
    *,
    state: str = "closed",
    merged_at: str | None = None,
    closed_at: str | None = None,
) -> dict:
    return {
        "number": number,
        "head_ref": head_ref,
        "state": state,
        "merged": merged_at is not None,
        "merged_at": merged_at,
        "closed_at": closed_at or merged_at,
    }


class TestParseLsRemote:
    def test_parses_branch_names(self) -> None:
        text = (
            "abc123\trefs/heads/main\n"
            "def456\trefs/heads/codex/fix-thing\n"
            "0a0a0a\trefs/heads/elves/run-x\n"
        )
        assert parse_ls_remote(text) == {"main", "codex/fix-thing", "elves/run-x"}

    def test_ignores_garbage_lines(self) -> None:
        assert parse_ls_remote("\nnot-a-ref-line\n") == set()


class TestComputeWorkLoss:
    def test_categories_and_ratio(self) -> None:
        outbox = [
            # expired, branch pushed, never published -> expired_unpublished
            {
                "idempotency_key": "k1",
                "branch": "codex/expired-pushed",
                "expires_at": "2026-06-01T00:00:00Z",
                "_source": "live",
            },
            # branch never pushed, not published -> lost_never_pushed
            {
                "idempotency_key": "k2",
                "branch": "codex/never-pushed",
                "expires_at": "2026-07-01T00:00:00Z",
                "_source": "live",
            },
            # published via PR for its branch -> not lost
            {
                "idempotency_key": "k3",
                "branch": "codex/published",
                "expires_at": "2026-06-01T00:00:00Z",
                "_source": "archive",
            },
        ]
        remote_heads = {
            "main",
            "codex/expired-pushed",
            "codex/published",
            "codex/orphan-branch",  # pushed, never PR'd
        }
        prs = [
            _pr(1, "codex/published", merged_at="2026-06-09T00:00:00Z"),
            _pr(2, "codex/closed-unmerged", closed_at="2026-06-08T00:00:00Z"),
            _pr(3, "feature/old-merge", merged_at="2026-01-01T00:00:00Z"),
        ]
        result = compute_work_loss(
            outbox_items=outbox,
            remote_heads=remote_heads,
            prs=prs,
            now=NOW,
            window_start=WINDOW_START,
        )
        assert result["outbox_expired_unpublished"] == 1
        assert result["outbox_lost_never_pushed"] == 1
        # orphan-branch only; expired-pushed is claimed by the outbox category
        assert result["branches_pushed_never_prd"] == 1
        assert result["prs_closed_unmerged"] == 1
        assert result["produced_units"] == 1  # only PR 1 merged inside window
        assert result["lost_units"] == 4
        assert result["waste_ratio"] == pytest.approx(4 / 1)
        assert result["methodology_version"] == 1

    def test_no_double_counting_expired_and_never_pushed(self) -> None:
        outbox = [
            {
                "idempotency_key": "k1",
                "branch": "codex/gone",
                "expires_at": "2026-01-01T00:00:00Z",
                "_source": "live",
            }
        ]
        result = compute_work_loss(
            outbox_items=outbox,
            remote_heads={"main"},
            prs=[],
            now=NOW,
            window_start=WINDOW_START,
        )
        # expired AND never pushed -> exactly one unit, in lost_never_pushed
        assert result["outbox_lost_never_pushed"] == 1
        assert result["outbox_expired_unpublished"] == 0
        assert result["lost_units"] == 1

    def test_branch_claimed_by_outbox_not_recounted_as_orphan(self) -> None:
        outbox = [
            {
                "idempotency_key": "k1",
                "branch": "codex/expired-pushed",
                "expires_at": "2026-01-01T00:00:00Z",
                "_source": "live",
            }
        ]
        result = compute_work_loss(
            outbox_items=outbox,
            remote_heads={"main", "codex/expired-pushed"},
            prs=[],
            now=NOW,
            window_start=WINDOW_START,
        )
        assert result["outbox_expired_unpublished"] == 1
        assert result["branches_pushed_never_prd"] == 0
        assert result["lost_units"] == 1

    def test_explicit_publication_state_respected(self) -> None:
        outbox = [
            {
                "idempotency_key": "k1",
                "branch": "codex/x",
                "expires_at": "2026-01-01T00:00:00Z",
                "publication": {"state": "published"},
                "_source": "archive",
            },
            {
                "idempotency_key": "k2",
                "branch": "codex/y",
                "expires_at": "2026-01-01T00:00:00Z",
                "requested_action": "mark_already_satisfied_or_close_stale_branch",
                "_source": "archive",
            },
        ]
        result = compute_work_loss(
            outbox_items=outbox,
            remote_heads={"main"},
            prs=[],
            now=NOW,
            window_start=WINDOW_START,
        )
        assert result["lost_units"] == 0

    def test_waste_ratio_denominator_floor(self) -> None:
        result = compute_work_loss(
            outbox_items=[],
            remote_heads={"main", "codex/orphan"},
            prs=[],
            now=NOW,
            window_start=WINDOW_START,
        )
        assert result["produced_units"] == 0
        assert result["waste_ratio"] == pytest.approx(1 / 1)

    def test_closed_unmerged_outside_window_excluded(self) -> None:
        prs = [_pr(2, "codex/old-close", closed_at="2026-01-01T00:00:00Z")]
        result = compute_work_loss(
            outbox_items=[],
            remote_heads={"main"},
            prs=prs,
            now=NOW,
            window_start=WINDOW_START,
        )
        assert result["prs_closed_unmerged"] == 0

    def test_unit_definitions_in_result(self) -> None:
        result = compute_work_loss(
            outbox_items=[],
            remote_heads=set(),
            prs=[],
            now=NOW,
            window_start=WINDOW_START,
        )
        assert result["unit_definitions"] == UNIT_DEFINITIONS
        for key in (
            "branches_pushed_never_prd",
            "outbox_expired_unpublished",
            "outbox_lost_never_pushed",
            "prs_closed_unmerged",
            "produced_units",
            "lost_units",
            "waste_ratio",
        ):
            assert key in UNIT_DEFINITIONS


class TestLoadOutboxItems:
    def test_loads_json_and_counts_unreadable(self, tmp_path: Path) -> None:
        d = tmp_path / "outbox"
        d.mkdir()
        (d / "a.json").write_text(json.dumps({"branch": "codex/a"}))
        (d / "broken.json").write_text("{not json")
        items, unreadable = load_outbox_items([d])
        assert len(items) == 1
        assert items[0]["branch"] == "codex/a"
        assert items[0]["_source"] == str(d)
        assert unreadable == 1

    def test_missing_dir_is_skipped(self, tmp_path: Path) -> None:
        items, unreadable = load_outbox_items([tmp_path / "nope"])
        assert items == []
        assert unreadable == 0


class TestMainJson:
    def test_end_to_end_with_injected_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        (outbox / "i1.json").write_text(
            json.dumps(
                {
                    "idempotency_key": "k1",
                    "branch": "codex/never-pushed",
                    "expires_at": "2026-07-01T00:00:00Z",
                }
            )
        )
        ls_remote = tmp_path / "heads.txt"
        ls_remote.write_text("abc\trefs/heads/main\ndef\trefs/heads/codex/orphan\n")
        prs_file = tmp_path / "prs.json"
        prs_file.write_text(
            json.dumps(
                [
                    _pr(1, "codex/merged", merged_at="2026-06-10T01:00:00Z"),
                    _pr(2, "codex/dead", closed_at="2026-06-09T00:00:00Z"),
                ]
            )
        )
        rc = main(
            [
                "--outbox-dir",
                str(outbox),
                "--ls-remote-file",
                str(ls_remote),
                "--prs-file",
                str(prs_file),
                "--since",
                "2026-06-03T12:00:00Z",
                "--json",
            ]
        )
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["outbox_lost_never_pushed"] == 1
        assert out["branches_pushed_never_prd"] == 1
        assert out["prs_closed_unmerged"] == 1
        assert out["produced_units"] == 1
        assert out["lost_units"] == 3
        assert out["waste_ratio"] == pytest.approx(3.0)
        assert "unit_definitions" in out

    def test_publish_updates_waste_block_only(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        from scripts.measure_leverage_ratio import update_leverage_md

        doc = tmp_path / "LEVERAGE.md"
        update_leverage_md(doc, lr_block="LR-SENTINEL")
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        ls_remote = tmp_path / "heads.txt"
        ls_remote.write_text("abc\trefs/heads/main\n")
        prs_file = tmp_path / "prs.json"
        prs_file.write_text("[]")
        rc = main(
            [
                "--outbox-dir",
                str(outbox),
                "--ls-remote-file",
                str(ls_remote),
                "--prs-file",
                str(prs_file),
                "--publish",
                "--status-doc",
                str(doc),
            ]
        )
        assert rc == 0
        text = doc.read_text()
        assert "LR-SENTINEL" in text
        assert "Waste ratio" in text


class TestRenderWasteBlock:
    def test_contains_counts_and_definitions(self) -> None:
        result = compute_work_loss(
            outbox_items=[],
            remote_heads={"main", "codex/orphan"},
            prs=[],
            now=NOW,
            window_start=WINDOW_START,
        )
        block = render_waste_block(result)
        assert "Branches pushed, never PR'd" in block
        assert "Waste ratio" in block
        assert "lost_units / max(1, produced_units)" in block


class TestMalformedItems:
    def test_non_string_branch_and_key_do_not_crash(self) -> None:
        outbox = [
            {"branch": {"weird": "dict"}, "idempotency_key": ["also", "weird"]},
            {"branch": 42, "expires_at": "2026-01-01T00:00:00Z"},
            {"local_evidence": {"branch": {"nested": "dict"}}, "_file": "x.json"},
        ]
        result = compute_work_loss(
            outbox_items=outbox,
            remote_heads={"main"},
            prs=[],
            now=NOW,
            window_start=WINDOW_START,
        )
        # Items without a usable string identity fall back to file name or are
        # skipped; the computation must not crash and must not invent units.
        assert isinstance(result["lost_units"], int)

    def test_non_string_head_ref_ignored(self) -> None:
        prs = [{"number": 1, "head_ref": {"odd": True}, "state": "closed", "merged": False}]
        result = compute_work_loss(
            outbox_items=[],
            remote_heads={"main"},
            prs=prs,
            now=NOW,
            window_start=WINDOW_START,
        )
        assert isinstance(result["lost_units"], int)
