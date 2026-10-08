"""Tests for ``scripts/tier4_merge_train.py`` — Tier-4 contention serializer.

Pure-core, fixture-driven: the lane decision is exercised against explicit
open-PR lists, so no ``gh`` subprocess is ever invoked. A drift guard asserts
the vendored serialized-surface list stays in sync with the canonical
``review_queue.TIER_4_PREFIXES`` (skipped when that import's heavy dependency
closure is unavailable, e.g. in a minimal sandbox). The maintained exact-name
Stage-1 regressions additionally exercise canonical classification directly;
those proofs intentionally fail rather than skip when the canonical classifier
cannot be imported.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest


def _load_module() -> Any:
    here = Path(__file__).resolve()
    script_path = here.parents[2] / "scripts" / "tier4_merge_train.py"
    spec = importlib.util.spec_from_file_location("tier4_merge_train_under_test", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


train = _load_module()

HOSTILE_EXACT_FILE_VARIANTS = (".bak", ".old", ".pyx", "/child", "x")


def _pr(number: int, files: list[str], *, created: str = "", title: str = "") -> dict[str, Any]:
    return {
        "number": number,
        "title": title or f"PR {number}",
        "createdAt": created,
        "files": [{"path": f} for f in files],
    }


# ---------------------------------------------------------------------------
# Path classification
# ---------------------------------------------------------------------------


def test_matches_exact_file_surface() -> None:
    assert (
        train.matches_serialized_path("scripts/settle_tier4_pr.py") == "scripts/settle_tier4_pr.py"
    )


def test_matches_directory_prefix_surface() -> None:
    assert (
        train.matches_serialized_path(".github/workflows/aragora-merge-quorum.yml")
        == ".github/workflows/"
    )


def test_every_slash_directory_root_matches_descendant_files_at_two_depths() -> None:
    review_queue = importlib.import_module("aragora.cli.commands.review_queue")
    directory_roots = tuple(rule for rule in train.SERIALIZED_TIER4_PREFIXES if rule.endswith("/"))
    assert directory_roots
    assert directory_roots == tuple(
        rule for rule in review_queue.TIER_4_PREFIXES if rule.endswith("/")
    )

    for index, root in enumerate(directory_roots, start=1):
        shallow = f"{root}stage1_probe.txt"
        deep = f"{root}stage1/nested_probe.txt"
        occupying_pr = 9_000 + index

        for path in (shallow, deep):
            canonical_rule = next(
                (
                    rule
                    for rule in review_queue.TIER_4_PREFIXES
                    if review_queue._matches_prefix(path, (rule,))
                ),
                None,
            )
            tier, name, _reason = review_queue._classify_model_review_tier([path])
            assert canonical_rule == root
            assert (tier, name) == (4, "tier_4_preapproval_required")
            assert train.matches_serialized_path(path) == root
            assert train.serialized_paths_for([path]) == {root}

            allowed = train.evaluate_merge_train([path], open_prs=[], cap=1)
            assert allowed["decision"] == train.ALLOW
            assert allowed["candidate_surfaces"] == [root]

        queued = train.evaluate_merge_train(
            [deep],
            open_prs=[_pr(occupying_pr, [shallow])],
            cap=1,
        )
        assert queued["decision"] == train.QUEUE
        assert queued["blocking_prs"] == [occupying_pr]
        assert queued["contended_surfaces"][root] == {
            "open_pr_numbers": [occupying_pr],
            "head_pr": occupying_pr,
            "lane_full": True,
        }


def test_non_serialized_path_returns_none() -> None:
    assert train.matches_serialized_path("scripts/run_boss_cycle.sh") is None
    assert train.matches_serialized_path("aragora/debate/orchestrator.py") is None


def test_serialized_paths_for_dedupes_by_surface() -> None:
    touched = train.serialized_paths_for(
        ["scripts/settle_tier4_pr.py", "tests/scripts/test_settle_tier4_pr.py", "README.md"]
    )
    assert touched == {"scripts/settle_tier4_pr.py"}


# ---------------------------------------------------------------------------
# Lane decision
# ---------------------------------------------------------------------------


def test_empty_lane_allows_candidate() -> None:
    result = train.evaluate_merge_train(
        ["scripts/settle_tier4_pr.py"],
        open_prs=[],
        cap=1,
    )
    assert result["ok"] is True
    assert result["decision"] == train.ALLOW
    assert result["blocking_prs"] == []


def test_full_lane_queues_candidate() -> None:
    open_prs = [_pr(8405, ["scripts/settle_tier4_pr.py"], created="2026-06-14T04:00:00Z")]
    result = train.evaluate_merge_train(
        ["scripts/settle_tier4_pr.py", "tests/scripts/test_settle_tier4_pr.py"],
        open_prs=open_prs,
        cap=1,
    )
    assert result["ok"] is False
    assert result["decision"] == train.QUEUE
    assert result["blocking_prs"] == [8405]
    assert result["contended_surfaces"]["scripts/settle_tier4_pr.py"]["head_pr"] == 8405
    assert result["contended_surfaces"]["scripts/settle_tier4_pr.py"]["lane_full"] is True


def test_cap_one_contention_is_deterministic_for_exact_authority_file() -> None:
    authority = "scripts/check_contract_drift_ratchet.py"
    open_prs = [
        _pr(9412, [authority], created="2026-07-17T20:01:00Z"),
        _pr(9410, [authority], created="2026-07-17T19:59:00Z"),
    ]

    first = train.evaluate_merge_train([authority], open_prs=open_prs, cap=1)
    second = train.evaluate_merge_train([authority], open_prs=list(reversed(open_prs)), cap=1)

    assert first == second
    assert first["decision"] == train.QUEUE
    assert first["blocking_prs"] == [9410, 9412]
    assert first["contended_surfaces"][authority] == {
        "open_pr_numbers": [9410, 9412],
        "head_pr": 9410,
        "lane_full": True,
    }


def test_every_exact_file_root_serializes_and_contends_with_occupying_pr_and_hostile_variants_join_no_lane() -> (
    None
):
    review_queue = importlib.import_module("aragora.cli.commands.review_queue")
    exact_roots = tuple(rule for rule in train.SERIALIZED_TIER4_PREFIXES if not rule.endswith("/"))
    assert exact_roots
    assert exact_roots == tuple(
        rule for rule in review_queue.TIER_4_PREFIXES if not rule.endswith("/")
    )

    for index, root in enumerate(exact_roots, start=1):
        occupying_pr = 10_000 + index
        assert train.matches_serialized_path(root) == root
        assert train.serialized_paths_for([root]) == {root}
        tier, name, _reason = review_queue._classify_model_review_tier([root])
        assert (tier, name) == (4, "tier_4_preapproval_required")

        allowed = train.evaluate_merge_train([root], open_prs=[], cap=1)
        assert allowed["decision"] == train.ALLOW
        assert allowed["candidate_surfaces"] == [root]
        assert allowed["blocking_prs"] == []

        queued = train.evaluate_merge_train(
            [root],
            open_prs=[_pr(occupying_pr, [root])],
            cap=1,
        )
        assert queued["decision"] == train.QUEUE
        assert queued["blocking_prs"] == [occupying_pr]
        assert queued["contended_surfaces"][root] == {
            "open_pr_numbers": [occupying_pr],
            "head_pr": occupying_pr,
            "lane_full": True,
        }

        for suffix in HOSTILE_EXACT_FILE_VARIANTS:
            variant = f"{root}{suffix}"
            canonical_rule = next(
                (
                    rule
                    for rule in review_queue.TIER_4_PREFIXES
                    if review_queue._matches_prefix(variant, (rule,))
                ),
                None,
            )
            variant_tier, _variant_name, _variant_reason = review_queue._classify_model_review_tier(
                [variant]
            )
            assert canonical_rule is None
            assert variant_tier < 4
            assert train.matches_serialized_path(variant) is None
            assert train.serialized_paths_for([variant]) == set()
            assert train.build_train([_pr(occupying_pr, [variant])]) == {}

            variant_decision = train.evaluate_merge_train(
                [variant],
                open_prs=[_pr(occupying_pr, [root])],
                cap=1,
            )
            assert variant_decision["decision"] == train.ALLOW
            assert variant_decision["candidate_surfaces"] == []
            assert variant_decision["contended_surfaces"] == {}
            assert variant_decision["blocking_prs"] == []
            assert "no serialized Tier-4 surface" in variant_decision["reason"]


def test_cap_two_allows_second_pr() -> None:
    open_prs = [_pr(8405, ["scripts/settle_tier4_pr.py"], created="2026-06-14T04:00:00Z")]
    result = train.evaluate_merge_train(
        ["scripts/settle_tier4_pr.py"],
        open_prs=open_prs,
        cap=2,
    )
    assert result["ok"] is True


def test_candidate_excluded_from_its_own_lane_count() -> None:
    # Re-evaluating an already-open PR must not block on itself.
    open_prs = [_pr(8408, ["scripts/settle_tier4_pr.py"], created="2026-06-14T05:00:00Z")]
    result = train.evaluate_merge_train(
        ["scripts/settle_tier4_pr.py"],
        open_prs=open_prs,
        cap=1,
        candidate_pr=8408,
    )
    assert result["ok"] is True
    assert result["blocking_prs"] == []


def test_non_serialized_candidate_always_allowed() -> None:
    open_prs = [_pr(8405, ["scripts/settle_tier4_pr.py"])]
    result = train.evaluate_merge_train(
        ["aragora/debate/orchestrator.py", "README.md"],
        open_prs=open_prs,
        cap=1,
    )
    assert result["ok"] is True
    assert result["candidate_surfaces"] == []
    assert "no serialized Tier-4 surface" in result["reason"]


def test_distinct_surfaces_do_not_cross_block() -> None:
    # An open PR on settle_one_pr.py must not block a candidate on review_queue.py.
    open_prs = [_pr(8396, ["scripts/settle_one_pr.py"])]
    result = train.evaluate_merge_train(
        ["aragora/cli/commands/review_queue.py"],
        open_prs=open_prs,
        cap=1,
    )
    assert result["ok"] is True


def test_train_ordered_oldest_first_then_number() -> None:
    open_prs = [
        _pr(8412, ["scripts/settle_tier4_pr.py"], created="2026-06-14T07:39:00Z"),
        _pr(8405, ["scripts/settle_tier4_pr.py"], created="2026-06-14T04:56:00Z"),
        _pr(8408, ["scripts/settle_tier4_pr.py"], created="2026-06-14T05:32:00Z"),
    ]
    lanes = train.build_train(open_prs)
    order = [entry["number"] for entry in lanes["scripts/settle_tier4_pr.py"]]
    assert order == [8405, 8408, 8412]


def test_blocking_prs_unions_across_surfaces() -> None:
    open_prs = [
        _pr(8405, ["scripts/settle_tier4_pr.py"], created="2026-06-14T04:00:00Z"),
        _pr(8396, ["scripts/settle_one_pr.py"], created="2026-06-14T03:00:00Z"),
    ]
    result = train.evaluate_merge_train(
        ["scripts/settle_tier4_pr.py", "scripts/settle_one_pr.py"],
        open_prs=open_prs,
        cap=1,
    )
    assert result["ok"] is False
    assert result["blocking_prs"] == [8396, 8405]


# ---------------------------------------------------------------------------
# CLI exit codes (pure path via injected open-PR JSON)
# ---------------------------------------------------------------------------


def test_cli_check_allow_exit_zero(tmp_path: Path, capsys: Any) -> None:
    prs = tmp_path / "open.json"
    prs.write_text("[]", encoding="utf-8")
    code = train.main(
        [
            "--check",
            "--changed-files",
            "scripts/settle_tier4_pr.py",
            "--open-prs-json",
            str(prs),
            "--json",
        ]
    )
    assert code == 0


def test_cli_check_queue_exit_two(tmp_path: Path) -> None:
    prs = tmp_path / "open.json"
    prs.write_text(
        '[{"number": 8405, "title": "x", "createdAt": "2026-06-14T04:00:00Z",'
        ' "files": [{"path": "scripts/settle_tier4_pr.py"}]}]',
        encoding="utf-8",
    )
    code = train.main(
        [
            "--check",
            "--changed-files",
            "scripts/settle_tier4_pr.py",
            "--open-prs-json",
            str(prs),
            "--json",
        ]
    )
    assert code == 2


def test_cli_requires_exactly_one_mode(tmp_path: Path) -> None:
    prs = tmp_path / "open.json"
    prs.write_text("[]", encoding="utf-8")
    # neither --check nor --status
    assert train.main(["--open-prs-json", str(prs)]) == 1
    # both
    assert train.main(["--check", "--status", "--open-prs-json", str(prs)]) == 1


# ---------------------------------------------------------------------------
# Drift guard: vendored list must match the canonical classifier
# ---------------------------------------------------------------------------


def test_serialized_prefixes_match_canonical_tier4() -> None:
    review_queue = pytest.importorskip(
        "aragora.cli.commands.review_queue",
        reason="review_queue import closure unavailable in this environment",
    )
    assert train.SERIALIZED_TIER4_PREFIXES == review_queue.TIER_4_PREFIXES, (
        "scripts/tier4_merge_train.py SERIALIZED_TIER4_PREFIXES has drifted from "
        "review_queue.TIER_4_PREFIXES — re-sync the vendored copy."
    )
