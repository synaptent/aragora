"""Tests for scripts/check_contract_drift_ratchet.py."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import inspect
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast, overload

import pytest
import scripts.check_contract_drift_ratchet as ratchet
import scripts.generate_contract_drift_inventory as gen
from tests.scripts._contract_drift_historical_git import ensure_pr_9320_head

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

PROGRAM_REL = "scripts/baselines/contract_drift_program.json"
_DISCOVER_CANONICAL_ARTIFACT = ratchet._discover_canonical_artifact
_CDG_TEST_ROOT = Path(__file__).resolve().parents[2]
_DECISION_351_PACK = (
    _CDG_TEST_ROOT / "tests/fixtures/contract_drift_decision_351_immutable_evidence.pack"
)
_REAL_NEXT_EVENT_PACK = (
    _CDG_TEST_ROOT / "tests/fixtures/contract_drift_trusted_bootstrap_real_next_event.pack"
)
_EXPECTED_DECISION_351_PACK_SHA256 = (
    "df888b46a3f94d784dd005773ac70b45d98140d955c5252e6b555a3d4b9e83ea"
)
_EXPECTED_REAL_NEXT_EVENT_PACK_SHA256 = (
    "2e5436cd6d0fbbb692cd4a1fd289ae7e8d80b6594f49cc612f09c493c2414bb8"
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _cohort_items(docs: dict[str, dict]) -> list[dict]:
    return [
        {
            "id": item_id,
            "source": list_key,
            "class": "start_cohort",
            "discovered_on": gen.COHORT_DATE,
            "provenance": gen.COHORT_PROVENANCE,
            "status": "open",
        }
        for item_id, list_key in sorted(gen.collect_ids(docs).items())
    ]


def _write_inventory(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(gen.render_inventory(sorted(items, key=lambda i: i["id"]), "test"))


def _commit(repo: Path, msg: str = "snap") -> str:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-qm",
            msg,
            "--allow-empty",
        ],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_docs(repo: Path, docs: dict[str, dict]) -> None:
    for alias, (rel_path, _keys) in gen.BASELINE_SPECS.items():
        if alias in docs:
            _write_json(repo / rel_path, docs[alias])


@overload
def _seed(
    tmp_path: Path,
    *,
    verify: dict | None = None,
    routes: dict | None = None,
    parity: dict | None = None,
    program: dict | None = None,
    inventory_items: list[dict] | None = None,
    commit: Literal[True] = True,
) -> tuple[dict[str, Path], Path, str]: ...


@overload
def _seed(
    tmp_path: Path,
    *,
    verify: dict | None = None,
    routes: dict | None = None,
    parity: dict | None = None,
    program: dict | None = None,
    inventory_items: list[dict] | None = None,
    commit: Literal[False],
) -> tuple[dict[str, Path], Path, None]: ...


def _seed(
    tmp_path: Path,
    *,
    verify: dict | None = None,
    routes: dict | None = None,
    parity: dict | None = None,
    program: dict | None = None,
    inventory_items: list[dict] | None = None,
    commit: bool = True,
) -> tuple[dict[str, Path], Path, str | None]:
    """Create a git repo with baselines at canonical paths; the initial commit
    is both the test's cohort commit and (for pr-mode tests) the base ref."""
    verify = (
        verify
        if verify is not None
        else {
            "python_sdk_drift": ["a", "b"],
            "typescript_sdk_drift": ["x", "y", "z"],
            "missing_stable": [],
        }
    )
    routes = (
        routes
        if routes is not None
        else {"missing_in_spec": ["m1", "m2"], "orphaned_in_spec": ["o1"]}
    )
    parity = parity if parity is not None else {"missing_from_both_sdks": ["p1", "p2"]}
    docs = {"verify": verify, "routes": routes, "parity": parity}

    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    if not (repo / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    _write_docs(repo, docs)
    paths = {alias: repo / rel_path for alias, (rel_path, _k) in gen.BASELINE_SPECS.items()}
    paths["program"] = repo / PROGRAM_REL
    paths["inventory"] = repo / gen.DEFAULT_INVENTORY
    if program is not None:
        _write_json(paths["program"], program)
    items = inventory_items if inventory_items is not None else _cohort_items(docs)
    _write_inventory(paths["inventory"], items)

    sha = _commit(repo, "cohort") if commit else None
    return paths, repo, sha


def _argv(paths: dict[str, Path], repo: Path, cohort: str, *extra: str) -> list[str]:
    return [
        "check_contract_drift_ratchet.py",
        "--repo-root",
        str(repo),
        "--cohort-commit",
        cohort,
        "--program-baseline",
        str(paths["program"]),
        "--verify-baseline",
        str(paths["verify"]),
        "--routes-baseline",
        str(paths["routes"]),
        "--parity-baseline",
        str(paths["parity"]),
        "--inventory",
        str(paths["inventory"]),
        *extra,
    ]


def _result(paths: dict[str, Path], as_of: str, *, repo: Path, cohort: str, **kwargs) -> dict:
    return ratchet.build_ratchet_result(
        mode=kwargs.pop("mode", "program"),
        program_baseline=paths["program"],
        verify_baseline=paths["verify"],
        routes_baseline=paths["routes"],
        parity_baseline=paths["parity"],
        inventory_path=paths["inventory"],
        repo_root=repo,
        as_of=date.fromisoformat(as_of),
        cohort_commit=cohort,
        **kwargs,
    )


def _edit_inventory(paths: dict[str, Path], mutate) -> None:
    inventory = json.loads(paths["inventory"].read_text())
    mutate(inventory)
    paths["inventory"].write_text(json.dumps(inventory))


# ---------------------------------------------------------------- program mode


def test_strict_passes_on_program_start(monkeypatch, tmp_path: Path):
    today = date.today().isoformat()
    paths, repo, cohort = _seed(
        tmp_path,
        program={
            "start_date": today,
            "start_total_items": 10,
            "weekly_reduction": 0.1,
            "grace_weeks": 0,
        },
    )
    monkeypatch.setattr(sys, "argv", _argv(paths, repo, cohort, "--strict", "--as-of", today))
    assert ratchet.main() == 0


def test_strict_fails_when_above_target(monkeypatch, tmp_path: Path):
    today = date.today()
    paths, repo, cohort = _seed(
        tmp_path,
        program={
            "start_date": today.isoformat(),
            "start_total_items": 10,
            "weekly_reduction": 0.1,
            "grace_weeks": 0,
        },
    )
    as_of = (today + timedelta(days=8)).isoformat()
    monkeypatch.setattr(sys, "argv", _argv(paths, repo, cohort, "--strict", "--as-of", as_of))
    assert ratchet.main() == 1


def test_program_numbers_read_only_from_program_baseline(tmp_path: Path):
    """Changing contract_drift_program.json (and nothing else) moves the target."""
    program = {
        "start_date": "2026-06-01",
        "start_total_items": 40,
        "weekly_reduction": 0.5,
        "grace_weeks": 0,
    }
    paths, repo, cohort = _seed(tmp_path, program=program)
    result = _result(paths, "2026-06-08", repo=repo, cohort=cohort)
    assert result["program"]["start_total_items"] == 40
    assert result["target"]["max_open_items"] == 20  # 40 * 0.5 after one week

    _write_json(paths["program"], dict(program, start_total_items=80))
    later = _result(paths, "2026-06-08", repo=repo, cohort=cohort)
    assert later["target"]["max_open_items"] == 40


def test_program_schedule_math_per_class_and_batch_clocks(tmp_path: Path):
    cohort_verify = {"python_sdk_drift": ["a", "b"], "typescript_sdk_drift": []}
    routes: dict[str, list[str]] = {"missing_in_spec": [], "orphaned_in_spec": []}
    parity: dict[str, list[str]] = {"missing_from_both_sdks": []}
    paths, repo, cohort = _seed(
        tmp_path,
        verify=cohort_verify,
        routes=routes,
        parity=parity,
        program={
            "start_date": "2026-06-01",
            "start_total_items": 30,
            "weekly_reduction": 0.1,
            "grace_weeks": 0,
        },
    )

    # Post-cohort: a discovered batch of 10 (8 still open) lands on 2026-06-01.
    _write_json(
        paths["verify"],
        dict(cohort_verify, typescript_sdk_drift=[f"d{i}" for i in range(1, 9)]),
    )
    discovered = [
        {
            "id": f"typescript_sdk_drift:d{i}",
            "source": "typescript_sdk_drift",
            "class": "discovered",
            "discovered_on": "2026-06-01",
            "provenance": "batch from #1234",
            "status": "open" if i <= 8 else "resolved",
            **({} if i <= 8 else {"resolved_on": "2026-06-10"}),
        }
        for i in range(1, 11)
    ]
    docs = {"verify": cohort_verify, "routes": routes, "parity": parity}
    _write_inventory(paths["inventory"], _cohort_items(docs) + discovered)

    result = _result(paths, "2026-06-15", repo=repo, cohort=cohort)
    assert result["integrity"]["passing"], result["integrity"]["issues"]
    classes = {cls["name"]: cls for cls in result["classes"]}

    cohort_cls = classes["start_cohort"]
    assert cohort_cls["batch_size"] == 30
    assert cohort_cls["target_max"] == ratchet._target_after_weeks(30, 0.1, 2)
    assert cohort_cls["open_items"] == 2
    assert cohort_cls["passing"]

    batch = classes["discovered:2026-06-01"]
    assert batch["batch_size"] == 10  # open + resolved; clock starts at its own date
    assert batch["weeks_elapsed"] == 2
    assert batch["target_max"] == 8  # 10 -> 9 -> 8
    assert batch["open_items"] == 8  # resolved items excluded from open count
    assert batch["passing"]
    assert result["passing"]

    # One week later the batch target drops to 7 while 8 remain open -> FAIL.
    later = _result(paths, "2026-06-22", repo=repo, cohort=cohort)
    batch_later = {c["name"]: c for c in later["classes"]}["discovered:2026-06-01"]
    assert batch_later["target_max"] == 7
    assert not batch_later["passing"]
    assert not later["passing"]


def test_fail_closed_missing_inventory(monkeypatch, tmp_path: Path):
    today = date.today().isoformat()
    paths, repo, cohort = _seed(
        tmp_path,
        program={"start_date": today, "start_total_items": 10, "weekly_reduction": 0.1},
    )
    paths["inventory"].unlink()
    # Fails even without --strict: integrity violations always fail closed.
    monkeypatch.setattr(sys, "argv", _argv(paths, repo, cohort, "--as-of", today))
    assert ratchet.main() == 1


def test_fail_closed_missing_program_baseline(monkeypatch, tmp_path: Path):
    today = date.today().isoformat()
    paths, repo, cohort = _seed(tmp_path)  # no program file written
    monkeypatch.setattr(sys, "argv", _argv(paths, repo, cohort, "--as-of", today))
    assert ratchet.main() == 1


def test_fail_closed_unexplained_baseline_entry(monkeypatch, tmp_path: Path):
    today = date.today().isoformat()
    paths, repo, cohort = _seed(
        tmp_path,
        program={"start_date": today, "start_total_items": 10, "weekly_reduction": 0.1},
    )
    verify = json.loads(paths["verify"].read_text())
    verify["python_sdk_drift"].append("sneaky-new-item")  # baseline grows, no inventory
    _write_json(paths["verify"], verify)
    monkeypatch.setattr(sys, "argv", _argv(paths, repo, cohort, "--as-of", today))
    assert ratchet.main() == 1


def test_fail_closed_unknown_class(monkeypatch, tmp_path: Path):
    today = date.today().isoformat()
    paths, repo, cohort = _seed(
        tmp_path,
        program={"start_date": today, "start_total_items": 10, "weekly_reduction": 0.1},
    )
    _edit_inventory(paths, lambda inv: inv["items"][0].update(**{"class": "grandfathered"}))
    monkeypatch.setattr(sys, "argv", _argv(paths, repo, cohort, "--as-of", today))
    assert ratchet.main() == 1


def test_fail_closed_unknown_status(tmp_path: Path):
    today = date.today().isoformat()
    paths, repo, cohort = _seed(
        tmp_path,
        program={"start_date": today, "start_total_items": 10, "weekly_reduction": 0.1},
    )
    _edit_inventory(paths, lambda inv: inv["items"][0].update(status="wip"))
    result = _result(paths, today, repo=repo, cohort=cohort)
    assert not result["integrity"]["passing"]
    assert any("Unknown status" in issue for issue in result["integrity"]["issues"])


def test_resolved_items_excluded_but_retained(tmp_path: Path):
    today = date.today().isoformat()
    cohort_verify = {"python_sdk_drift": ["a", "gone"], "typescript_sdk_drift": []}
    routes: dict[str, list[str]] = {"missing_in_spec": [], "orphaned_in_spec": []}
    parity: dict[str, list[str]] = {"missing_from_both_sdks": []}
    paths, repo, cohort = _seed(
        tmp_path,
        verify=cohort_verify,
        routes=routes,
        parity=parity,
        program={"start_date": today, "start_total_items": 5, "weekly_reduction": 0.1},
    )
    # "gone" was fixed: pruned from the baseline, resolved in the inventory.
    _write_json(paths["verify"], dict(cohort_verify, python_sdk_drift=["a"]))

    def resolve_gone(inv):
        for item in inv["items"]:
            if item["id"] == "python_sdk_drift:gone":
                item["status"] = "resolved"
                item["resolved_on"] = "2026-05-01"

    _edit_inventory(paths, resolve_gone)

    result = _result(paths, today, repo=repo, cohort=cohort)
    assert result["integrity"]["passing"], result["integrity"]["issues"]
    cohort_cls = {c["name"]: c for c in result["classes"]}["start_cohort"]
    assert cohort_cls["open_items"] == 1  # resolved item not counted
    assert len(json.loads(paths["inventory"].read_text())["items"]) == 2  # retained


def test_program_mode_future_discovered_on_fails(tmp_path: Path):
    paths, repo, cohort = _seed(
        tmp_path,
        program={
            "start_date": "2026-04-17",
            "start_total_items": 10,
            "weekly_reduction": 0.1,
        },
    )
    verify = json.loads(paths["verify"].read_text())
    verify["python_sdk_drift"].append("future1")
    _write_json(paths["verify"], verify)
    _edit_inventory(
        paths,
        lambda inv: inv["items"].append(
            {
                "id": "python_sdk_drift:future1",
                "source": "python_sdk_drift",
                "class": "discovered",
                "discovered_on": "2026-08-01",  # after as_of below
                "provenance": "claimed in #9",
                "status": "open",
            }
        ),
    )
    result = _result(paths, "2026-07-16", repo=repo, cohort=cohort)
    assert not result["integrity"]["passing"]
    assert any("out of bounds" in issue for issue in result["integrity"]["issues"])


def test_program_mode_pre_cohort_discovered_on_fails(tmp_path: Path):
    paths, repo, cohort = _seed(
        tmp_path,
        program={
            "start_date": "2026-04-17",
            "start_total_items": 10,
            "weekly_reduction": 0.1,
        },
    )
    verify = json.loads(paths["verify"].read_text())
    verify["python_sdk_drift"].append("ancient1")
    _write_json(paths["verify"], verify)
    _edit_inventory(
        paths,
        lambda inv: inv["items"].append(
            {
                "id": "python_sdk_drift:ancient1",
                "source": "python_sdk_drift",
                "class": "discovered",
                "discovered_on": "2026-01-01",  # before the program start
                "provenance": "claimed in #9",
                "status": "open",
            }
        ),
    )
    result = _result(paths, "2026-07-16", repo=repo, cohort=cohort)
    assert not result["integrity"]["passing"]
    assert any("out of bounds" in issue for issue in result["integrity"]["issues"])


def test_cohort_reclassification_fails_both_modes(monkeypatch, tmp_path: Path):
    """Forging class=discovered with a fresh date on a cohort item must fail
    integrity in BOTH modes (derivable-metadata invariant)."""
    paths, repo, cohort = _seed(
        tmp_path,
        program={
            "start_date": "2026-04-17",
            "start_total_items": 10,
            "weekly_reduction": 0.1,
        },
    )
    _edit_inventory(
        paths,
        lambda inv: inv["items"][0].update(
            **{
                "class": "discovered",
                "discovered_on": "2026-07-01",
                "provenance": "forged reset #1",
            }
        ),
    )

    program_result = _result(paths, "2026-07-16", repo=repo, cohort=cohort)
    assert not program_result["integrity"]["passing"]
    assert any("reclassified" in i for i in program_result["integrity"]["issues"])

    pr_result = _result(paths, "2026-07-16", repo=repo, cohort=cohort, mode="pr", base_ref=cohort)
    assert not pr_result["integrity"]["passing"]
    assert not pr_result["passing"]

    monkeypatch.setattr(sys, "argv", _argv(paths, repo, cohort, "--as-of", "2026-07-16"))
    assert ratchet.main() == 1  # exit 1 even without --strict


# --------------------------------------------------------------------- pr mode

# 10 items @ -10%/week from 2026-04-17: by 2026-07-16 the target is well below
# the 10 seeded open items, so the program schedule is red at that as-of date.
RED_PROGRAM = {
    "start_date": "2026-04-17",
    "start_total_items": 10,
    "weekly_reduction": 0.1,
    "grace_weeks": 0,
}


def test_pr_mode_passes_on_equal_counts_while_program_red(tmp_path: Path):
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)
    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["passing"]
    assert not result["program_passing"]  # program schedule still honestly red
    assert result["pr_delta"]["increased"] == []


def test_pr_mode_passes_on_decrease_via_legitimate_resolution(tmp_path: Path):
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)

    verify = json.loads(paths["verify"].read_text())
    verify["python_sdk_drift"].remove("b")
    _write_json(paths["verify"], verify)

    def resolve_b(inv):
        for item in inv["items"]:
            if item["id"] == "python_sdk_drift:b":
                item["status"] = "resolved"
                item["resolved_on"] = "2026-07-16"

    _edit_inventory(paths, resolve_b)

    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["integrity"]["passing"]  # open -> resolved is a legal transition
    assert result["pr_delta"]["counts"]["verify_python_sdk_drift"]["delta"] == -1
    assert result["passing"]


# NOTE: the original test_pr_mode_fails_on_any_single_list_increase asserted
# that even a fully inventoried discovered entry fails pr mode. That design
# had no intake path for legitimately discovered debt (first contact: #9332)
# and was amended: its exact scenario is now the designed PASS path, covered
# by test_pr_mode_increase_with_inventoried_discovered_intake_passes below.
# Increases that are NOT explained intake still fail — see the
# "pr mode: discovered intake" section.


def test_duplicate_baseline_entry_fails_integrity_program_mode(tmp_path: Path):
    """A duplicated baseline entry inflates the count-based ratchet while the
    id-deduped inventory holds one item — fail closed rather than let the
    duplicate sit as a count-decrease freebie."""
    verify = {"python_sdk_drift": ["a", "a", "b"], "typescript_sdk_drift": [], "missing_stable": []}
    paths, repo, cohort = _seed(tmp_path, verify=verify, program=RED_PROGRAM)
    result = _result(paths, "2026-07-16", repo=repo, cohort=cohort)
    assert not result["integrity"]["passing"]
    assert any(
        "Duplicate baseline entry: python_sdk_drift:a" in i for i in result["integrity"]["issues"]
    )
    assert not result["passing"]


def test_pr_mode_inherited_duplicate_fails_despite_equal_counts(tmp_path: Path):
    """A duplicate present at base AND head leaves every count delta at zero —
    only the duplicate integrity check catches it."""
    verify = {"python_sdk_drift": ["a", "a", "b"], "typescript_sdk_drift": [], "missing_stable": []}
    paths, repo, base = _seed(tmp_path, verify=verify, program=RED_PROGRAM)
    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["pr_delta"]["increased"] == []
    assert not result["integrity"]["passing"]
    assert not result["passing"]


def test_pr_mode_passes_on_duplicate_removal(tmp_path: Path):
    """Removing a duplicated baseline entry is a pure dedup: count decreases by
    one, the inventory (already deduped by id) needs no change, and pr mode
    passes."""
    verify = {"python_sdk_drift": ["a", "a", "b"], "typescript_sdk_drift": [], "missing_stable": []}
    paths, repo, base = _seed(tmp_path, verify=verify, program=RED_PROGRAM)

    deduped = json.loads(paths["verify"].read_text())
    deduped["python_sdk_drift"] = ["a", "b"]
    _write_json(paths["verify"], deduped)

    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["integrity"]["passing"]
    assert result["pr_delta"]["counts"]["verify_python_sdk_drift"]["delta"] == -1
    assert result["passing"]


def test_pr_mode_fails_on_integrity_violation(monkeypatch, tmp_path: Path):
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)

    verify = json.loads(paths["verify"].read_text())
    verify["python_sdk_drift"].append("unexplained")  # not added to inventory
    _write_json(paths["verify"], verify)

    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert not result["integrity"]["passing"]
    assert not result["passing"]

    monkeypatch.setattr(
        sys,
        "argv",
        _argv(
            paths,
            repo,
            base,
            "--mode",
            "pr",
            "--base-ref",
            base,
            "--as-of",
            "2026-07-16",
        ),
    )
    assert ratchet.main() == 1  # fails closed even without --strict


def test_pr_mode_immutable_field_mutation_fails(tmp_path: Path):
    """A PR may not rewrite class/discovered_on/provenance of an existing item."""
    paths, repo, cohort = _seed(tmp_path, program=RED_PROGRAM)

    # Base (post-cohort) commit adds a legitimate discovered item x1.
    verify = json.loads(paths["verify"].read_text())
    verify["typescript_sdk_drift"].append("x1")
    _write_json(paths["verify"], verify)
    _edit_inventory(
        paths,
        lambda inv: inv["items"].append(
            {
                "id": "typescript_sdk_drift:x1",
                "source": "typescript_sdk_drift",
                "class": "discovered",
                "discovered_on": "2026-06-01",
                "provenance": "tracked in #77",
                "status": "open",
            }
        ),
    )
    base = _commit(repo, "base with x1")

    # Head attempts to reset x1's burn-down clock. Counts are unchanged.
    def reset_clock(inv):
        for item in inv["items"]:
            if item["id"] == "typescript_sdk_drift:x1":
                item["discovered_on"] = "2026-07-01"

    _edit_inventory(paths, reset_clock)

    result = _result(paths, "2026-07-16", repo=repo, cohort=cohort, mode="pr", base_ref=base)
    assert result["pr_delta"]["increased"] == []  # only metadata was forged
    assert not result["integrity"]["passing"]
    assert any(
        "Immutable inventory field 'discovered_on'" in i for i in result["integrity"]["issues"]
    )
    assert not result["passing"]


def test_pr_mode_reopen_with_new_date_fails(tmp_path: Path):
    """Reopening a resolved item must preserve its original clock."""
    paths, repo, cohort = _seed(tmp_path, program=RED_PROGRAM)

    # Base: x1 was discovered 2026-06-01 and already resolved.
    _edit_inventory(
        paths,
        lambda inv: inv["items"].append(
            {
                "id": "typescript_sdk_drift:x1",
                "source": "typescript_sdk_drift",
                "class": "discovered",
                "discovered_on": "2026-06-01",
                "provenance": "tracked in #77",
                "status": "resolved",
                "resolved_on": "2026-06-10",
            }
        ),
    )
    base = _commit(repo, "base with resolved x1")

    # Head: x1 regresses back into the baseline, reopened with a reset clock.
    verify = json.loads(paths["verify"].read_text())
    verify["typescript_sdk_drift"].append("x1")
    _write_json(paths["verify"], verify)

    def reopen_reset(inv):
        for item in inv["items"]:
            if item["id"] == "typescript_sdk_drift:x1":
                item["status"] = "open"
                item.pop("resolved_on", None)
                item["discovered_on"] = "2026-07-01"  # forged clock reset

    _edit_inventory(paths, reopen_reset)
    result = _result(paths, "2026-07-16", repo=repo, cohort=cohort, mode="pr", base_ref=base)
    assert not result["integrity"]["passing"]
    assert any(
        "Immutable inventory field 'discovered_on'" in i for i in result["integrity"]["issues"]
    )

    # Reopening with the ORIGINAL date keeps integrity clean; the PR still
    # fails via the increase gate — a reopen is a regression, never intake
    # (see test_pr_mode_reopen_is_regression_not_intake).
    def reopen_honest(inv):
        for item in inv["items"]:
            if item["id"] == "typescript_sdk_drift:x1":
                item["discovered_on"] = "2026-06-01"

    _edit_inventory(paths, reopen_honest)
    honest = _result(paths, "2026-07-16", repo=repo, cohort=cohort, mode="pr", base_ref=base)
    assert honest["integrity"]["passing"], honest["integrity"]["issues"]
    assert honest["pr_delta"]["increased"] == ["verify_typescript_sdk_drift"]
    assert not honest["passing"]


def test_pr_mode_inventory_deletion_fails(tmp_path: Path):
    """Deleting an item (instead of resolving it) violates append-only."""
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)

    verify = json.loads(paths["verify"].read_text())
    verify["python_sdk_drift"].remove("b")
    _write_json(paths["verify"], verify)
    _edit_inventory(
        paths,
        lambda inv: inv.update(items=[i for i in inv["items"] if i["id"] != "python_sdk_drift:b"]),
    )

    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    # Counts decreased, but the audit trail was destroyed -> fail closed.
    assert result["pr_delta"]["counts"]["verify_python_sdk_drift"]["delta"] == -1
    assert not result["integrity"]["passing"]
    assert any("append-only" in i for i in result["integrity"]["issues"])
    assert not result["passing"]


def test_pr_mode_missing_file_at_base_treated_as_empty(tmp_path: Path):
    paths, repo, _ = _seed(
        tmp_path,
        parity={"missing_from_both_sdks": []},
        program=RED_PROGRAM,
        commit=False,
    )
    paths["parity"].unlink()
    base = _commit(repo, "base without parity file")  # also the cohort commit

    # HEAD parity file exists with zero entries: 0 vs empty-at-base -> equal, PASS.
    _write_json(paths["parity"], {"missing_from_both_sdks": []})
    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["pr_delta"]["counts"]["sdk_missing_from_both"] == {
        "base": 0,
        "head": 0,
        "delta": 0,
    }
    assert result["passing"]

    # HEAD grows an entry: the increase is computed against the EMPTY base
    # (0 -> 1), proving a file missing at the ref hides nothing. Uninventoried,
    # the increase is unexplained and fails.
    _write_json(paths["parity"], {"missing_from_both_sdks": ["p-new"]})
    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["pr_delta"]["increased"] == ["sdk_missing_from_both"]
    assert result["pr_delta"]["unexplained_increase"] != []
    assert not result["passing"]

    # Fully inventoried, the same increase is explained discovered intake.
    _edit_inventory(
        paths,
        lambda inv: inv["items"].append(
            {
                "id": "missing_from_both_sdks:p-new",
                "source": "missing_from_both_sdks",
                "class": "discovered",
                "discovered_on": "2026-07-16",
                "provenance": "explained in #4242",
                "status": "open",
            }
        ),
    )
    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["pr_delta"]["increased"] == ["sdk_missing_from_both"]
    assert result["pr_delta"]["unexplained_increase"] == []
    assert result["passing"]


def test_target_decay_has_no_fixed_points_and_reaches_zero():
    """Regression: iterative int(round(n*0.9)) stuck at 1-4 forever (review P2

    on #9346); the one-shot floored decay must be monotonic to zero so small
    discovered batches cannot satisfy their clocks indefinitely.
    """
    for start in (1, 2, 3, 4, 10, 655):
        prev = ratchet._target_after_weeks(start, 0.1, 0)
        assert prev == start
        for weeks in range(1, 120):
            cur = ratchet._target_after_weeks(start, 0.1, weeks)
            assert cur <= prev
            prev = cur
        assert ratchet._target_after_weeks(start, 0.1, 120) == 0


def test_pr_mode_new_resolved_item_fails_birth_state(tmp_path: Path):
    """An item absent from the base inventory must be born open; a fabricated
    resolved item (delta-neutral by construction) is an integrity failure."""
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)

    _edit_inventory(
        paths,
        lambda inv: inv["items"].append(
            {
                "id": "typescript_sdk_drift:fake1",
                "source": "typescript_sdk_drift",
                "class": "discovered",
                "discovered_on": "2026-06-01",
                "provenance": "padding #666",
                "status": "resolved",
                "resolved_on": "2026-06-15",
            }
        ),
    )
    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["pr_delta"]["increased"] == []  # counts untouched by the fake
    assert not result["integrity"]["passing"]
    assert any("born open" in i for i in result["integrity"]["issues"])
    assert not result["passing"]

    # The sibling case: a new OPEN item without a baseline entry fails the
    # global sync check (open items must be baseline-backed, new ones too).
    def swap_to_ghost(inv):
        inv["items"] = [i for i in inv["items"] if i["id"] != "typescript_sdk_drift:fake1"]
        inv["items"].append(
            {
                "id": "typescript_sdk_drift:ghost",
                "source": "typescript_sdk_drift",
                "class": "discovered",
                "discovered_on": "2026-07-16",
                "provenance": "padding #666",
                "status": "open",
            }
        )

    _edit_inventory(paths, swap_to_ghost)
    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert not result["integrity"]["passing"]
    assert any("absent from baselines" in i for i in result["integrity"]["issues"])


def test_pr_mode_batch_inflation_attack_fails(tmp_path: Path):
    """Fake resolved items padding a batch's size + real new drift hidden in
    the same list (net-zero open delta) must fail on the birth-state rule."""
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)

    # Real new drift swapped in for a legitimately resolved item: same list,
    # count unchanged, so the delta gate alone would pass.
    verify = json.loads(paths["verify"].read_text())
    verify["python_sdk_drift"].remove("b")
    verify["python_sdk_drift"].append("evil1")
    _write_json(paths["verify"], verify)

    def mutate(inv):
        for item in inv["items"]:
            if item["id"] == "python_sdk_drift:b":
                item["status"] = "resolved"
                item["resolved_on"] = "2026-07-16"
        inv["items"].append(
            {
                "id": "python_sdk_drift:evil1",
                "source": "python_sdk_drift",
                "class": "discovered",
                "discovered_on": "2026-06-01",
                "provenance": "explained in #666",
                "status": "open",
            }
        )
        # Batch padding: five fabricated resolved items in the same batch
        # inflate batch_size 1 -> 6 and raise its scheduled target.
        for i in range(5):
            inv["items"].append(
                {
                    "id": f"python_sdk_drift:fake{i}",
                    "source": "python_sdk_drift",
                    "class": "discovered",
                    "discovered_on": "2026-06-01",
                    "provenance": "padding #666",
                    "status": "resolved",
                    "resolved_on": "2026-06-15",
                }
            )

    _edit_inventory(paths, mutate)
    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["pr_delta"]["increased"] == []  # the attack is delta-neutral
    assert not result["integrity"]["passing"]
    born_open_issues = [i for i in result["integrity"]["issues"] if "born open" in i]
    assert len(born_open_issues) == 5  # every fabricated item rejected
    assert not result["passing"]


def test_pr_mode_legitimate_lifecycle_two_generations(monkeypatch, tmp_path: Path):
    """born open -> resolved with history -> retained: two real generator runs
    bracketing a fix must pass pr mode end-to-end."""
    paths, repo, cohort = _seed(tmp_path, program=RED_PROGRAM)

    def run_gen(*extra: str) -> int:
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "generate_contract_drift_inventory.py",
                "--repo-root",
                str(repo),
                "--cohort-commit",
                cohort,
                *extra,
            ],
        )
        return gen.main()

    assert run_gen("--as-of", "2026-07-10") == 0  # generation 1: all born open
    base = _commit(repo, "generation 1")

    verify = json.loads(paths["verify"].read_text())
    verify["python_sdk_drift"].remove("b")  # the item gets fixed
    _write_json(paths["verify"], verify)
    assert run_gen("--as-of", "2026-07-16") == 0  # generation 2: resolves it

    items = {i["id"]: i for i in json.loads(paths["inventory"].read_text())["items"]}
    assert items["python_sdk_drift:b"]["status"] == "resolved"
    assert items["python_sdk_drift:b"]["resolved_on"] == "2026-07-16"

    result = _result(paths, "2026-07-16", repo=repo, cohort=cohort, mode="pr", base_ref=base)
    assert result["integrity"]["passing"], result["integrity"]["issues"]
    assert result["pr_delta"]["counts"]["verify_python_sdk_drift"]["delta"] == -1
    assert result["passing"]


# ------------------------------------------------- pr mode: discovered intake
# Amendment after first contact (#9332): newly VISIBLE debt with clear
# provenance must have an intake path. A count increase is allowed iff EVERY
# baseline entry new vs the base ref is born in this PR as class=discovered
# with a PR/issue-referenced provenance and a valid discovered_on date.


def _discovered_route_item(name: str, *, provenance: str = "canary probe #9332") -> dict:
    return {
        "id": f"orphaned_in_spec:{name}",
        "source": "orphaned_in_spec",
        "class": "discovered",
        "discovered_on": "2026-07-16",
        "provenance": provenance,
        "status": "open",
    }


def test_pr_mode_increase_with_inventoried_discovered_intake_passes(tmp_path: Path):
    """The #9332 shape: canary-probe-exposed orphan routes land as a fully
    inventoried discovered batch -> explained intake, pr mode PASSES, and the
    batch starts its own program-mode burn-down clock."""
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)

    routes = json.loads(paths["routes"].read_text())
    routes["orphaned_in_spec"] += ["probe1", "probe2", "probe3"]
    _write_json(paths["routes"], routes)
    _edit_inventory(
        paths,
        lambda inv: inv["items"].extend(_discovered_route_item(f"probe{i}") for i in (1, 2, 3)),
    )

    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["integrity"]["passing"], result["integrity"]["issues"]
    assert result["pr_delta"]["increased"] == ["routes_orphaned_in_spec"]
    assert result["pr_delta"]["unexplained_increase"] == []
    assert result["passing"]

    # The intake batch gets its own clock in program mode (already implemented).
    batch = {c["name"]: c for c in result["classes"]}["discovered:2026-07-16"]
    assert batch["batch_size"] == 3
    assert batch["target_max"] == 3  # week 0 of its own -10%/week schedule


def test_pr_mode_increase_with_one_uninventoried_entry_fails(tmp_path: Path):
    """A batch where even one new baseline entry lacks an inventory record is
    NOT explained intake: the increase fails (and sync integrity fails too)."""
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)

    routes = json.loads(paths["routes"].read_text())
    routes["orphaned_in_spec"] += ["probe1", "probe2"]
    _write_json(paths["routes"], routes)
    _edit_inventory(paths, lambda inv: inv["items"].append(_discovered_route_item("probe1")))

    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert any(
        "orphaned_in_spec:probe2" in reason for reason in result["pr_delta"]["unexplained_increase"]
    )
    assert not result["integrity"]["passing"]  # sync: probe2 is unexplained debt
    assert not result["passing"]


def test_pr_mode_increase_with_free_text_provenance_fails(tmp_path: Path):
    """Provenance without a PR/issue reference is not intake-grade: the
    increase stays unexplained and the provenance-format invariant fires."""
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)

    routes = json.loads(paths["routes"].read_text())
    routes["orphaned_in_spec"].append("probe1")
    _write_json(paths["routes"], routes)
    _edit_inventory(
        paths,
        lambda inv: inv["items"].append(
            _discovered_route_item("probe1", provenance="found during a canary sweep")
        ),
    )

    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert any(
        "orphaned_in_spec:probe1" in reason for reason in result["pr_delta"]["unexplained_increase"]
    )
    assert not result["integrity"]["passing"]  # provenance-reference invariant
    assert not result["passing"]


def test_pr_mode_increase_without_new_entries_fails(tmp_path: Path):
    """A count can increase with ZERO new ids (duplicate list entries). The
    'every new entry is explained' rule must not pass vacuously."""
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)

    routes = json.loads(paths["routes"].read_text())
    routes["orphaned_in_spec"].append("o1")  # duplicate of an existing entry
    _write_json(paths["routes"], routes)

    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["pr_delta"]["increased"] == ["routes_orphaned_in_spec"]
    assert result["pr_delta"]["unexplained_increase"] != []
    assert not result["passing"]


def test_pr_mode_duplicate_bundled_with_valid_intake_fails(tmp_path: Path):
    """Round-1 review P2 on #9352 (both reviewers): a duplicate-entry increase
    must not ride along with a legitimate discovered entry in the SAME list —
    every unit of count increase needs its own distinct new inventoried entry."""
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)

    routes = json.loads(paths["routes"].read_text())
    routes["orphaned_in_spec"] += ["o1", "probe1"]  # dup of existing o1 + real probe1
    _write_json(paths["routes"], routes)
    _edit_inventory(paths, lambda inv: inv["items"].append(_discovered_route_item("probe1")))

    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["pr_delta"]["counts"]["routes_orphaned_in_spec"]["delta"] == 2
    assert any(
        "routes_orphaned_in_spec" in reason for reason in result["pr_delta"]["unexplained_increase"]
    )
    assert not result["integrity"]["passing"]  # duplicated entry fails closed
    assert any("Duplicate baseline entry" in i for i in result["integrity"]["issues"])
    assert not result["passing"]


def test_pr_mode_cross_list_duplicate_masking_fails(tmp_path: Path):
    """Round-1 review P2 variant: a pure duplicate increase in one list must
    not be masked by the only new id coming from a net-zero swap in ANOTHER
    list — the explained-intake bound is per list, not repo-wide."""
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)

    routes = json.loads(paths["routes"].read_text())
    routes["orphaned_in_spec"].append("o1")  # duplicate: +1 with zero new route ids
    _write_json(paths["routes"], routes)

    verify = json.loads(paths["verify"].read_text())
    verify["python_sdk_drift"].remove("b")
    verify["python_sdk_drift"].append("swap1")  # net-zero swap: the sole new id
    _write_json(paths["verify"], verify)

    def mutate(inv):
        for item in inv["items"]:
            if item["id"] == "python_sdk_drift:b":
                item["status"] = "resolved"
                item["resolved_on"] = "2026-07-16"
        inv["items"].append(
            {
                "id": "python_sdk_drift:swap1",
                "source": "python_sdk_drift",
                "class": "discovered",
                "discovered_on": "2026-07-16",
                "provenance": "swap tracked in #4242",
                "status": "open",
            }
        )

    _edit_inventory(paths, mutate)

    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["pr_delta"]["increased"] == ["routes_orphaned_in_spec"]
    assert any(
        "routes_orphaned_in_spec" in reason for reason in result["pr_delta"]["unexplained_increase"]
    )
    assert not result["passing"]


def test_pr_mode_delta_neutral_duplicate_smuggle_fails(tmp_path: Path):
    """Remove one entry and duplicate another in the same list: deltas are
    all zero, but the minted duplicate is slack a later PR could cash in as
    fake burn-down — must fail via integrity, independent of the delta gate.
    (#9354's unconditional duplicate check is what catches it.)"""
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)

    routes = json.loads(paths["routes"].read_text())
    routes["missing_in_spec"] = ["m1", "m1"]  # m2 removed, m1 duplicated: count still 2
    _write_json(paths["routes"], routes)

    def resolve_m2(inv):
        for item in inv["items"]:
            if item["id"] == "missing_in_spec:m2":
                item["status"] = "resolved"
                item["resolved_on"] = "2026-07-16"

    _edit_inventory(paths, resolve_m2)

    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["pr_delta"]["increased"] == []  # the smuggle is delta-neutral
    assert not result["integrity"]["passing"]
    assert any(
        "Duplicate baseline entry" in i and "missing_in_spec:m1" in i
        for i in result["integrity"]["issues"]
    )
    assert not result["passing"]


def test_pr_mode_non_string_discovered_on_fails_closed_without_crash(tmp_path: Path):
    """Round-1 review P3 on #9352: a non-string discovered_on (e.g. a JSON
    number) must produce integrity/unexplained failures, not a TypeError."""
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)

    routes = json.loads(paths["routes"].read_text())
    routes["orphaned_in_spec"].append("probe1")
    _write_json(paths["routes"], routes)
    item = _discovered_route_item("probe1")
    item["discovered_on"] = 20260716  # number, not an ISO date string
    _edit_inventory(paths, lambda inv: inv["items"].append(item))

    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert not result["integrity"]["passing"]
    assert any("discovered_on" in i for i in result["integrity"]["issues"])
    assert any("discovered_on" in reason for reason in result["pr_delta"]["unexplained_increase"])
    assert not result["passing"]


def test_pr_mode_reopen_is_regression_not_intake(tmp_path: Path):
    """An item with base-inventory history regressing back into the baseline
    is a regression, not newly discovered debt: honest reopen (original clock)
    must NOT ride the discovered-intake allowance."""
    paths, repo, cohort = _seed(tmp_path, program=RED_PROGRAM)

    _edit_inventory(
        paths,
        lambda inv: inv["items"].append(
            {
                "id": "typescript_sdk_drift:x1",
                "source": "typescript_sdk_drift",
                "class": "discovered",
                "discovered_on": "2026-06-01",
                "provenance": "tracked in #77",
                "status": "resolved",
                "resolved_on": "2026-06-10",
            }
        ),
    )
    base = _commit(repo, "base with resolved x1")

    verify = json.loads(paths["verify"].read_text())
    verify["typescript_sdk_drift"].append("x1")
    _write_json(paths["verify"], verify)

    def reopen_honest(inv):
        for item in inv["items"]:
            if item["id"] == "typescript_sdk_drift:x1":
                item["status"] = "open"
                item.pop("resolved_on", None)

    _edit_inventory(paths, reopen_honest)

    result = _result(paths, "2026-07-16", repo=repo, cohort=cohort, mode="pr", base_ref=base)
    assert result["integrity"]["passing"], result["integrity"]["issues"]
    assert any(
        "typescript_sdk_drift:x1" in reason for reason in result["pr_delta"]["unexplained_increase"]
    )
    assert not result["passing"]


def test_pr_mode_program_parameter_change_fails(tmp_path: Path):
    """Round-5 review P2: editing contract_drift_program.json in a PR is

    threshold inflation by definition and must fail pr-mode integrity even
    though counts and inventory are untouched.
    """
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)

    program = json.loads(paths["program"].read_text())
    program["start_total_items"] = 5000
    _write_json(paths["program"], program)

    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["pr_delta"]["increased"] == []
    assert not result["integrity"]["passing"]
    assert any("Program baseline parameter changed" in i for i in result["integrity"]["issues"])
    assert not result["passing"]


# --------------------------------------------------------------- boundary mode


def _canonical_boundary_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _rule_suite_record(
    end_sha: str,
    **overrides: Any,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "after_sha": end_sha,
        "before_sha": "0" * 40,
        "evaluation_result": "pass",
        "id": 987654,
        "pushed_at": "2026-07-20T00:00:00Z",
        "ref": "refs/heads/main",
        "repository_id": 1126097105,
        "repository_name": "aragora",
        "result": "pass",
        "rule_evaluations": [{"result": "pass", "rule_source": {"type": "repository"}}],
    }
    record.update(overrides)
    return record


def _rule_suite_claim(
    end_sha: str,
    *,
    delete: str | None = None,
    bypassed: bool = False,
    **overrides: Any,
) -> dict[str, Any]:
    record = _rule_suite_record(end_sha, **overrides)
    if delete is not None:
        record.pop(delete, None)
    raw = ratchet._canonical_json_bytes(record)
    claim = {
        field: copy.deepcopy(record[field])
        for field in (
            "after_sha",
            "before_sha",
            "evaluation_result",
            "id",
            "pushed_at",
            "ref",
            "repository_id",
            "repository_name",
            "result",
            "rule_evaluations",
        )
        if field in record
    }
    claim.update(
        {
            "authenticated": True,
            "available": True,
            "bypassed": bypassed,
            "raw_response": raw.decode("utf-8"),
            "raw_response_byte_length": len(raw),
            "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
        }
    )
    return claim


def _write_canonical_boundary_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    raw = _canonical_boundary_bytes(payload)
    path.write_bytes(raw)
    return {
        "byte_length": len(raw),
        "name": path.stem,
        "path": path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _canonical_fixture_artifact_paths() -> tuple[Path, Path] | None:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        return (
            _DISCOVER_CANONICAL_ARTIFACT(None, ratchet.COHORT_ARTIFACT, repo_root),
            _DISCOVER_CANONICAL_ARTIFACT(None, ratchet.PROVENANCE_ARTIFACT, repo_root),
        )
    except ValueError:
        return None


def _write_synthetic_canonical_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    category_sizes = (
        ("python_sdk_drift", 74),
        ("routes_missing_in_spec", 11),
        ("routes_orphaned_in_spec", 17),
        ("sdk_missing_from_both", 29),
        ("typescript_sdk_drift", 524),
    )
    cohort_records: list[dict[str, Any]] = []
    sdk_records: list[dict[str, Any]] = []
    category_indices: dict[str, int] = {}
    for category, count in category_sizes:
        for _index in range(count):
            source_array_index = category_indices.get(category, 0)
            category_indices[category] = source_array_index + 1
            literal = f"fixture:{category}:{source_array_index:04d}"
            payload = {
                "category": category,
                "exact_historical_literal_record": literal,
                "schema": "cdg-original-record-id-v1",
            }
            payload_raw = ratchet._canonical_json_bytes(payload)
            payload_sha256 = hashlib.sha256(payload_raw).hexdigest()
            record: dict[str, Any] = {
                "category": category,
                "exact_historical_literal_record": literal,
                "id_payload_byte_length": len(payload_raw),
                "id_payload_sha256": payload_sha256,
                "original_record_id": f"cdg1:{payload_sha256}",
                "source_array_index": source_array_index,
            }
            if category in {"python_sdk_drift", "typescript_sdk_drift"}:
                record.update(
                    {
                        "method": "GET",
                        "sdk_language": [
                            "python" if category == "python_sdk_drift" else "typescript"
                        ],
                    }
                )
                sdk_records.append(record)
            cohort_records.append(record)

    provenance_records: list[dict[str, Any]] = []
    for index, cohort_record in enumerate(sdk_records):
        core = index < 75
        atoms = ["agents" if core else "billing"]
        if index < 12:
            atoms.append(f"fixture_{index}")
        partition, matches = ratchet._partition_from_atoms(atoms)
        occurrences = [
            {
                "provenance_atom": atoms[0],
                "sdk_language": cohort_record["sdk_language"][0],
            }
        ]
        if index < 92:
            occurrences.append(dict(occurrences[0]))
        record = {
            "category": cohort_record["category"],
            "exact_historical_literal_record": cohort_record["exact_historical_literal_record"],
            "id_payload_byte_length": cohort_record["id_payload_byte_length"],
            "id_payload_sha256": cohort_record["id_payload_sha256"],
            "matched_domains": matches,
            "original_record_id": cohort_record["original_record_id"],
            "partition": partition,
            "provenance_atoms": atoms,
            "sdk_language": cohort_record["sdk_language"][0],
            "source_array_index": cohort_record["source_array_index"],
            "source_occurrences": occurrences,
        }
        record_sha256 = hashlib.sha256(ratchet._canonical_json_bytes(record)).hexdigest()
        record["record_sha256"] = record_sha256
        cohort_record["sdk_provenance_record_sha256"] = record_sha256
        provenance_records.append(record)

    projection_records = []
    for index, cohort_record in enumerate(cohort_records):
        edge_count = 4 if index == 0 else 2 if index < 9 else 1
        record = {
            "operation_edges": [
                {
                    "evidence": [f"fixture:{index}:{edge_index}"],
                    "method": "GET",
                    "normalized_path": f"/fixture/{index}/{edge_index}",
                }
                for edge_index in range(edge_count)
            ],
            "original_record_id": cohort_record["original_record_id"],
        }
        record_sha256 = hashlib.sha256(ratchet._canonical_json_bytes(record)).hexdigest()
        record["record_sha256"] = record_sha256
        projection_records.append(record)

    original_ids = sorted(record["original_record_id"] for record in cohort_records)
    original_id_set_sha256 = ratchet._digest_set(
        "cdg-original-record-id-set-v1",
        original_ids,
        "original_record_ids",
    )
    projection_record_set_sha256 = ratchet._digest_set(
        "cdg-operation-projection-record-digest-set-v1",
        [record["record_sha256"] for record in projection_records],
        "record_sha256_values",
    )
    cohort = {
        "counts": {
            "by_category": ratchet.EXPECTED_CATEGORY_COUNTS,
            "method_bearing_sdk_records": 598,
            "method_null_route_parity_records": 57,
            "records": 655,
        },
        "id_encoding": "fixture",
        "membership_anchor": "fixture",
        "membership_sources": ["fixture"],
        "operation_projection": {
            "one_to_many_rule": "fixture",
            "record_digest_set_sha256": projection_record_set_sha256,
            "records": projection_records,
            "schema": "cdg-operation-projection-v1",
            "witness_dependencies": ["fixture"],
        },
        "original_record_id_set": {
            "original_record_ids": original_ids,
            "sha256": original_id_set_sha256,
        },
        "original_records": cohort_records,
        "schema": "contract-drift-original-cohort-v1",
    }

    provenance_record_set_sha256 = ratchet._digest_set(
        "cdg-sdk-provenance-record-digest-set-v1",
        [record["record_sha256"] for record in provenance_records],
        "record_sha256_values",
    )
    sdk_ids = [record["original_record_id"] for record in provenance_records]
    core_ids = [
        record["original_record_id"]
        for record in provenance_records
        if record["partition"] == "core"
    ]
    extended_ids = [
        record["original_record_id"]
        for record in provenance_records
        if record["partition"] == "extended"
    ]
    sdk_id_set_sha256 = ratchet._digest_set(
        "cdg-sdk-original-record-id-set-v1",
        sdk_ids,
        "original_record_ids",
    )
    core_id_set_sha256 = ratchet._digest_set(
        "cdg-core-original-record-id-set-v1",
        core_ids,
        "original_record_ids",
    )
    extended_id_set_sha256 = ratchet._digest_set(
        "cdg-extended-original-record-id-set-v1",
        extended_ids,
        "original_record_ids",
    )
    provenance = {
        "baseline_birth": "fixture",
        "counts": {
            "core": 75,
            "extended": 523,
            "python_sdk_drift": 74,
            "records": 598,
            "records_with_multiple_distinct_atoms": 12,
            "source_occurrences": 690,
            "typescript_sdk_drift": 524,
        },
        "dependencies": ["fixture"],
        "extraction_algorithm": "fixture",
        "partition": {
            "core_original_record_id_set_sha256": core_id_set_sha256,
            "extended_original_record_id_set_sha256": extended_id_set_sha256,
            "intersection_count": 0,
            "rule_schema": "cdg-sdk-partition-rule-v1",
            "sdk_original_record_id_set_sha256": sdk_id_set_sha256,
            "union_count": 598,
        },
        "record_digest_set_sha256": provenance_record_set_sha256,
        "records": provenance_records,
        "schema": "contract-drift-sdk-provenance-v1",
    }

    cohort_path = tmp_path / ratchet.COHORT_ARTIFACT["filename"]
    provenance_path = tmp_path / ratchet.PROVENANCE_ARTIFACT["filename"]
    cohort_raw = ratchet._canonical_json_bytes(cohort, terminal_lf=True)
    provenance_raw = ratchet._canonical_json_bytes(provenance, terminal_lf=True)
    cohort_path.write_bytes(cohort_raw)
    provenance_path.write_bytes(provenance_raw)
    monkeypatch.setitem(ratchet.COHORT_ARTIFACT, "byte_length", len(cohort_raw))
    monkeypatch.setitem(
        ratchet.COHORT_ARTIFACT,
        "sha256",
        hashlib.sha256(cohort_raw).hexdigest(),
    )
    monkeypatch.setitem(ratchet.PROVENANCE_ARTIFACT, "byte_length", len(provenance_raw))
    monkeypatch.setitem(
        ratchet.PROVENANCE_ARTIFACT,
        "sha256",
        hashlib.sha256(provenance_raw).hexdigest(),
    )
    monkeypatch.setattr(ratchet, "ORIGINAL_ID_SET_SHA256", original_id_set_sha256)
    monkeypatch.setattr(
        ratchet,
        "PROJECTION_RECORD_SET_SHA256",
        projection_record_set_sha256,
    )
    monkeypatch.setattr(
        ratchet,
        "PROVENANCE_RECORD_SET_SHA256",
        provenance_record_set_sha256,
    )
    monkeypatch.setattr(ratchet, "SDK_ID_SET_SHA256", sdk_id_set_sha256)
    monkeypatch.setattr(ratchet, "CORE_ID_SET_SHA256", core_id_set_sha256)
    monkeypatch.setattr(ratchet, "EXTENDED_ID_SET_SHA256", extended_id_set_sha256)
    return cohort_path, provenance_path


def _clone_repository_with_synthetic_accepted_authority(
    tmp_path: Path,
    *,
    cohort_path: Path,
    provenance_path: Path,
) -> tuple[Path, str, str]:
    source_repo = Path(__file__).resolve().parents[2]
    repo_root = tmp_path / "synthetic-authority-repo"
    subprocess.run(
        ["git", "clone", "-q", "--no-hardlinks", str(source_repo), str(repo_root)],
        check=True,
    )
    production_sha = subprocess.check_output(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    inventory_path = repo_root / gen.DEFAULT_INVENTORY
    inventory = json.loads(inventory_path.read_bytes())
    accepted_authority = inventory.get("accepted_authority")
    if not isinstance(accepted_authority, dict):
        raise AssertionError("production accepted authority is missing or malformed")
    canonical_artifacts = accepted_authority.get("canonical_artifacts")
    if not isinstance(canonical_artifacts, dict):
        raise AssertionError("production accepted authority lacks canonical artifacts")
    before = copy.deepcopy(inventory)
    original_canonical_artifacts = copy.deepcopy(canonical_artifacts)
    cohort = json.loads(cohort_path.read_bytes())
    provenance = json.loads(provenance_path.read_bytes())
    canonical_artifacts["original_cohort"] = cohort
    canonical_artifacts["sdk_provenance"] = provenance
    reverted = copy.deepcopy(inventory)
    reverted_artifacts = reverted["accepted_authority"]["canonical_artifacts"]
    reverted_artifacts["original_cohort"] = original_canonical_artifacts["original_cohort"]
    reverted_artifacts["sdk_provenance"] = original_canonical_artifacts["sdk_provenance"]
    assert reverted == before
    _write_json(inventory_path, inventory)
    fixture_sha = _commit(repo_root, "bind synthetic accepted authority")
    return repo_root, production_sha, fixture_sha


def _mutate_cloned_production_inventory(
    monkeypatch: pytest.MonkeyPatch,
    mutate: Any,
) -> None:
    real_run = subprocess.run

    def run_then_mutate(
        argv: list[str],
        *args: Any,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[Any]:
        result = real_run(argv, *args, **kwargs)
        if argv[:3] == ["git", "clone", "-q"]:
            inventory_path = Path(argv[-1]) / gen.DEFAULT_INVENTORY
            inventory = json.loads(inventory_path.read_bytes())
            mutate(inventory)
            _write_json(inventory_path, inventory)
        return result

    monkeypatch.setattr(subprocess, "run", run_then_mutate)


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        pytest.param(
            lambda inventory: inventory.pop("accepted_authority"),
            "production accepted authority",
            id="missing-authority",
        ),
        pytest.param(
            lambda inventory: inventory.__setitem__("accepted_authority", None),
            "production accepted authority",
            id="malformed-authority",
        ),
        pytest.param(
            lambda inventory: inventory["accepted_authority"].pop("canonical_artifacts"),
            "lacks canonical artifacts",
            id="missing-canonical-artifacts",
        ),
    ),
)
def test_synthetic_accepted_authority_fixture_rejects_invalid_production_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Any,
    message: str,
):
    cohort_path, provenance_path = _write_synthetic_canonical_artifacts(
        tmp_path,
        monkeypatch,
    )
    _mutate_cloned_production_inventory(monkeypatch, mutate)

    with pytest.raises(AssertionError, match=message):
        _clone_repository_with_synthetic_accepted_authority(
            tmp_path,
            cohort_path=cohort_path,
            provenance_path=provenance_path,
        )


def _fixture_sdk_partitions() -> dict[str, list[str]]:
    artifact_paths = _canonical_fixture_artifact_paths()
    if artifact_paths is None:
        return {
            "core": [
                _fixture_original_record_id("python_sdk_drift", f"fixture-core-{index}")
                for index in range(75)
            ],
            "extended": [
                _fixture_original_record_id(
                    "typescript_sdk_drift",
                    f"fixture-extended-{index}",
                )
                for index in range(523)
            ],
        }
    provenance = json.loads(artifact_paths[1].read_bytes())
    partitions: dict[str, list[str]] = {"core": [], "extended": []}
    for record in provenance["records"]:
        partitions[record["partition"]].append(record["original_record_id"])
    for values in partitions.values():
        values.sort()
    return partitions


def _fixture_original_record_id(category: str, literal: str) -> str:
    payload = {
        "category": category,
        "exact_historical_literal_record": literal,
        "schema": "cdg-original-record-id-v1",
    }
    return f"cdg1:{hashlib.sha256(ratchet._canonical_json_bytes(payload)).hexdigest()}"


def _fixture_sdk_literal(partition: str) -> tuple[str, str]:
    artifact_paths = _canonical_fixture_artifact_paths()
    if artifact_paths is None:
        if partition == "core":
            return "python_sdk_drift", "fixture-core-0"
        return "typescript_sdk_drift", "fixture-extended-0"
    cohort_path, provenance_path = artifact_paths
    cohort = json.loads(cohort_path.read_bytes())
    provenance = json.loads(provenance_path.read_bytes())
    cohort_by_id = {record["original_record_id"]: record for record in cohort["original_records"]}
    record = next(record for record in provenance["records"] if record["partition"] == partition)
    cohort_record = cohort_by_id[record["original_record_id"]]
    return (
        cohort_record["category"],
        cohort_record["exact_historical_literal_record"],
    )


def _boundary_git_repo(
    tmp_path: Path,
    *,
    route_debt: bool = False,
    route_debt_at: str | None = None,
    sdk_debt_partition: str | None = None,
    sdk_debt_at: str | None = None,
) -> tuple[Path, str, dict[str, str]]:
    repo = tmp_path / "boundary-repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    baselines = repo / "scripts" / "baselines"
    baselines.mkdir(parents=True)
    _write_json(
        baselines / "check_sdk_parity.json",
        {"missing_from_both_sdks": []},
    )
    _write_json(
        baselines / "validate_openapi_routes.json",
        {"missing_in_spec": [], "orphaned_in_spec": []},
    )
    _write_json(
        baselines / "verify_sdk_contracts.json",
        {"python_sdk_drift": [], "typescript_sdk_drift": []},
    )
    (repo / "fixture.txt").write_text("start\n", encoding="utf-8")
    start_sha = _commit(repo, "accepted corrective bootstrap")
    shas: dict[str, str] = {}
    for index, boundary in enumerate(ratchet.BOUNDARY_NAMES, start=1):
        effective_route_debt_at = route_debt_at or ("route_truth" if route_debt else None)
        if boundary == effective_route_debt_at:
            _write_json(
                baselines / "validate_openapi_routes.json",
                {
                    "missing_in_spec": ["/api/contradiction"],
                    "orphaned_in_spec": [],
                },
            )
        if sdk_debt_partition is not None and boundary == sdk_debt_at:
            category, literal = _fixture_sdk_literal(sdk_debt_partition)
            verify: dict[str, list[str]] = {"python_sdk_drift": [], "typescript_sdk_drift": []}
            verify[category] = [literal]
            _write_json(baselines / "verify_sdk_contracts.json", verify)
        (repo / "fixture.txt").write_text(f"boundary-{index}\n", encoding="utf-8")
        shas[boundary] = _commit(repo, boundary)
    return repo, start_sha, shas


def _fixture_git_changed_paths(repo: Path, base_sha: str, head_sha: str) -> list[str]:
    raw = subprocess.check_output(
        [
            "git",
            "-C",
            str(repo),
            "diff",
            "--no-renames",
            "--name-only",
            "-z",
            f"{base_sha}^{{tree}}",
            f"{head_sha}^{{tree}}",
        ]
    )
    assert not raw or raw.endswith(b"\0")
    return sorted(path.decode("utf-8") for path in raw[:-1].split(b"\0") if path)


def _stable_attestation_claim() -> dict[str, Any]:
    # The payload-embedded attestation claim binds the demonstrated stable
    # identity fields (entry 30) — never a digest over verification outputs,
    # which embed payload.json's own SHA-256 (unsolvable fixed point).
    return {
        "predicate_type": ratchet.RELEASE_ATTESTATION_PREDICATE_TYPE,
        "signer_san_regexp": ratchet.RELEASE_ATTESTATION_SIGNER_SAN_REGEXP,
        "verified": True,
        "workflow": "actions/attest@v4",
    }


def _real_shaped_verification_payload(
    asset_sha256s: dict[str, str],
    *,
    tag: str,
    repository: str = "synaptent/aragora",
    signer_san_regexp: str | None = None,
    predicate_type: str | None = None,
) -> dict[str, Any]:
    # Mirrors the live gh 2.96.0 `release verify`/`verify-asset --format json`
    # shape recorded in the 2026-08-01 double-run exercise: verifiedIdentity
    # SAN regexp, in-toto release/v0.2 statement, and a subject set covering
    # the release pkg-URI plus one sha256 entry per asset.
    subjects: list[dict[str, Any]] = [
        {
            "uri": f"pkg:github/{repository}@{tag}",
            "digest": {"sha1": "0" * 40},
        }
    ]
    for name in sorted(asset_sha256s):
        subjects.append({"name": name, "digest": {"sha256": asset_sha256s[name]}})
    return {
        "attestation": {"bundle": {"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json"}},
        "verificationResult": {
            "mediaType": "application/vnd.dev.sigstore.verificationresult+json;version=0.1",
            "statement": {
                "_type": "https://in-toto.io/Statement/v1",
                "predicate": {"repository": repository, "tag": tag},
                "predicateType": (
                    ratchet.RELEASE_ATTESTATION_PREDICATE_TYPE
                    if predicate_type is None
                    else predicate_type
                ),
                "subject": subjects,
            },
            "verifiedIdentity": {
                "subjectAlternativeName": {
                    "regexp": (
                        ratchet.RELEASE_ATTESTATION_SIGNER_SAN_REGEXP
                        if signer_san_regexp is None
                        else signer_san_regexp
                    ),
                    "subjectAlternativeName": "",
                },
            },
            "verifiedTimestamps": [
                {
                    "timestamp": "2026-08-01T06:35:29Z",
                    "type": "TimestampAuthority",
                    "uri": "timestamp.githubapp.com",
                }
            ],
        },
    }


def _boundary_payloads(
    boundary: str,
    start_sha: str,
    end_sha: str,
    boundary_shas: dict[str, str],
    *,
    repo: Path,
    release_immutability: bool = True,
) -> dict[str, dict[str, Any]]:
    chronology = [{"boundary": name, "sha": boundary_shas[name]} for name in ratchet.BOUNDARY_NAMES]
    common = {"boundary": boundary, "end_sha": end_sha, "start_sha": start_sha}

    def proof_interval(name: str) -> dict[str, str]:
        return {
            "predicate": name,
            "proof_end_sha": end_sha,
            "proof_for_boundary": boundary,
            "proof_start_sha": start_sha,
        }

    def fact(schema: str, value: dict[str, Any]) -> dict[str, Any]:
        return {
            "fact": value,
            "sha256": ratchet._fact_digest(schema, value),
        }

    sdk_partitions = _fixture_sdk_partitions()

    governed_records = []
    receipt_records = []
    prior_sha = start_sha
    for index, name in enumerate(
        ratchet.BOUNDARY_NAMES[: ratchet.BOUNDARY_NAMES.index(boundary) + 1],
        start=1,
    ):
        merge_sha = boundary_shas[name]
        merge_tree_sha = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", f"{merge_sha}^{{tree}}"],
            text=True,
        ).strip()
        governed_records.append(
            {
                "base_sha": prior_sha,
                "changed_files_complete": True,
                "head_sha": merge_sha,
                "head_tree_sha": merge_tree_sha,
                "pr": 9998 + index,
            }
        )
        receipt_records.append(
            {
                "base_sha": prior_sha,
                "first_parent_sha": prior_sha,
                "head_sha": merge_sha,
                "head_tree_sha": merge_tree_sha,
                "merge_sha": merge_sha,
                "merge_tree_sha": merge_tree_sha,
                "pr": 9998 + index,
            }
        )
        prior_sha = merge_sha

    return {
        "boundary_chronology": {
            **common,
            "boundaries": chronology,
            "schema": "contract-drift-boundary-chronology-v1",
        },
        "corrective_bootstrap": {
            **proof_interval("corrective_bootstrap"),
            "accepted_stage1_closure": fact(
                "contract-drift-stage1-closure-fact-v1",
                {
                    "authority_manifest_sha256": "1" * 64,
                    "boundary_verifier_sha256": "7" * 64,
                    "dependency_manifest_sha256": "2" * 64,
                    "inventory_sha256": "3" * 64,
                    "repo_file_count": 42,
                },
            ),
            "corrective_transition": fact(
                "contract-drift-corrective-transition-fact-v1",
                {
                    "commit_count": 1,
                    "end_sha": boundary_shas["corrective_bootstrap"],
                    "start_sha": start_sha,
                },
            ),
            "schema": "contract-drift-corrective-bootstrap-proof-v1",
            "stage2_verifier_chronology": fact(
                "contract-drift-stage2-verifier-chronology-fact-v1",
                {
                    "corrective_boundary_sha": boundary_shas["corrective_bootstrap"],
                    "ordered_after_stage1": True,
                    "start_sha": start_sha,
                    "verifier_sha256": "7" * 64,
                },
            ),
        },
        "route_truth": {
            **proof_interval("route_truth"),
            "openapi_truth": fact(
                "contract-drift-openapi-truth-fact-v1",
                {
                    "boundary_sha": boundary_shas["route_truth"],
                    "complete": True,
                    "route_boundary_sha256": "5" * 64,
                },
            ),
            "route_truth": fact(
                "contract-drift-route-truth-fact-v1",
                {
                    "authority_route_member_count": 2,
                    "boundary_sha": boundary_shas["route_truth"],
                    "complete": True,
                    "method_aware": True,
                    "route_boundary_sha256": "5" * 64,
                },
            ),
            "schema": "contract-drift-route-truth-proof-v1",
        },
        "core_sdk": {
            **proof_interval("core_sdk"),
            "qualifying_paydown": fact(
                "contract-drift-core-sdk-paydown-fact-v1",
                {
                    "added_units": [],
                    "boundary_sha": boundary_shas["core_sdk"],
                    "category_growth": [],
                    "max_pr_delta": 800,
                    "removed_original_record_ids": sdk_partitions["core"],
                    "replacement_units": [],
                },
            ),
            "schema": "contract-drift-core-sdk-proof-v1",
            "zero_core_debt": fact(
                "contract-drift-zero-core-debt-fact-v1",
                {
                    "boundary_sha": boundary_shas["core_sdk"],
                    "partition_set_sha256": "b3a1755f027c998d507f13f3ba9093f769cea8720d44bfac12be6beccd626787",
                    "remaining_original_units": 0,
                },
            ),
        },
        "extended_sdk": {
            **proof_interval("extended_sdk"),
            "qualifying_paydown": fact(
                "contract-drift-extended-sdk-paydown-fact-v1",
                {
                    "added_units": [],
                    "boundary_sha": boundary_shas["extended_sdk"],
                    "category_growth": [],
                    "max_pr_delta": 800,
                    "removed_original_record_ids": sdk_partitions["extended"],
                    "replacement_units": [],
                },
            ),
            "schema": "contract-drift-extended-sdk-proof-v1",
            "zero_sdk_debt": fact(
                "contract-drift-zero-sdk-debt-fact-v1",
                {
                    "boundary_sha": boundary_shas["extended_sdk"],
                    "partition_set_sha256": "51a963079136a92a86485b56f6cef42aafc7749bfad146ce5fb37293524c5762",
                    "remaining_original_units": 0,
                },
            ),
        },
        "final_seal": {
            **proof_interval("final_seal"),
            "complete_paydown": fact(
                "contract-drift-complete-paydown-fact-v1",
                {
                    "boundary_sha": boundary_shas["final_seal"],
                    "remaining_original_units": 0,
                },
            ),
            "dated_trajectory": fact(
                "contract-drift-dated-trajectory-fact-v1",
                {
                    "as_of": "2026-07-20",
                    "boundary_sha": boundary_shas["final_seal"],
                    "target": 0,
                    "total": 0,
                },
            ),
            "final_zero": fact(
                "contract-drift-final-zero-fact-v1",
                {
                    "all_categories_zero": True,
                    "boundary_sha": boundary_shas["final_seal"],
                },
            ),
            "publication": fact(
                "contract-drift-publication-fact-v1",
                {
                    "attestation_predicate_type": ratchet.RELEASE_ATTESTATION_PREDICATE_TYPE,
                    "attestation_signer_san_regexp": (
                        ratchet.RELEASE_ATTESTATION_SIGNER_SAN_REGEXP
                    ),
                    "boundary_sha": boundary_shas["final_seal"],
                    "release_api_id": 100,
                    "rule_suite_id": 987654,
                },
            ),
            "schema": "contract-drift-final-seal-proof-v1",
        },
        "external_prerequisites": {
            **common,
            "administration": {"authenticated": True, "available": True},
            "future_release_immutability": {
                "authenticated": True,
                "available": True,
                "enabled": release_immutability,
            },
            "rule_suite": _rule_suite_claim(end_sha),
            "schema": "contract-drift-external-prerequisites-v1",
        },
        "durable_capsule": {
            **common,
            "attestation": _stable_attestation_claim(),
            # Entry 32: the release claim carries only publication-time
            # pre-known identity (release_api_id is assigned at draft
            # creation); asset_api_ids is expressly absent.
            "release": {
                "asset_names": ["manifest.json", "payload.json", "checksums.txt"],
                "exact_full_sha_tag": end_sha,
                "immutable": release_immutability,
                "release_api_id": 100,
                "tag_name": f"cdg-{boundary}-{end_sha}",
                "verified": release_immutability,
            },
            "schema": "contract-drift-durable-capsule-v1",
        },
        "governed_prs": {
            **common,
            "records": governed_records,
            "schema": "contract-drift-governed-prs-v1",
        },
        "first_parent_receipts": {
            **common,
            "records": receipt_records,
            "schema": "contract-drift-first-parent-receipts-v1",
        },
    }


def _write_boundary_index(
    tmp_path: Path,
    boundary: str,
    start_sha: str,
    end_sha: str,
    boundary_shas: dict[str, str],
    *,
    repo: Path,
    release_immutability: bool = True,
    mutate: Any | None = None,
) -> tuple[Path, int, str]:
    resources_dir = tmp_path / f"resources-{boundary}"
    resources_dir.mkdir(parents=True)
    payloads = _boundary_payloads(
        boundary,
        start_sha,
        end_sha,
        boundary_shas,
        repo=repo,
        release_immutability=release_immutability,
    )
    if mutate is not None:
        mutate(payloads)
    payloads["boundary_chronology"]["boundaries"] = payloads["boundary_chronology"]["boundaries"][
        : ratchet.BOUNDARY_NAMES.index(boundary) + 1
    ]
    selected = set(ratchet.BOUNDARY_NAMES[: ratchet.BOUNDARY_NAMES.index(boundary) + 1])
    selected.update(
        {
            "boundary_chronology",
            "durable_capsule",
            "external_prerequisites",
            "first_parent_receipts",
            "governed_prs",
        }
    )
    payloads = {name: payload for name, payload in payloads.items() if name in selected}
    descriptors = []
    for name, payload in sorted(payloads.items()):
        descriptor = _write_canonical_boundary_json(resources_dir / f"{name}.json", payload)
        descriptor["name"] = name
        descriptor["path"] = f"{resources_dir.name}/{name}.json"
        descriptors.append(descriptor)
    index = {
        "boundary": boundary,
        "end_sha": end_sha,
        "resources": descriptors,
        "schema": ratchet.BOUNDARY_EVIDENCE_INDEX_SCHEMA,
        "start_sha": start_sha,
    }
    raw = _canonical_boundary_bytes(index)
    path = tmp_path / f"{boundary}-evidence-index.json"
    path.write_bytes(raw)
    return path, len(raw), hashlib.sha256(raw).hexdigest()


def _stub_boundary_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    partitions = _fixture_sdk_partitions()
    monkeypatch.setattr(
        ratchet,
        "_authenticate_canonical_artifacts",
        lambda **_kwargs: {
            "operation_projection": {"membership_count": 655},
            "original_cohort": {
                "byte_length": 1,
                "record_count": 655,
                "sha256": "8" * 64,
            },
            "sdk_provenance": {
                "byte_length": 1,
                "core_original_record_id_set_sha256": ratchet.CORE_ID_SET_SHA256,
                "core_original_record_ids": partitions["core"],
                "extended_original_record_id_set_sha256": ratchet.EXTENDED_ID_SET_SHA256,
                "extended_original_record_ids": partitions["extended"],
                "record_count": 598,
                "sdk_original_record_id_set_sha256": ratchet.SDK_ID_SET_SHA256,
                "sdk_original_record_ids": sorted(partitions["core"] + partitions["extended"]),
                "sha256": "9" * 64,
            },
        },
    )
    monkeypatch.setattr(
        ratchet,
        "_discover_canonical_artifact",
        lambda _explicit, _descriptor, _repo_root: Path(__file__).resolve(),
    )
    monkeypatch.setattr(
        ratchet,
        "_reauthenticate_canonical_input",
        lambda _path, **_kwargs: None,
    )
    monkeypatch.setattr(
        ratchet,
        "_authenticate_authority_manifest",
        lambda **_kwargs: {
            "authority_manifest_sha256": "1" * 64,
            "boundary_verifier_sha256": "7" * 64,
            "dependency_manifest_sha256": "2" * 64,
            "inventory_sha256": "3" * 64,
            "public_symbol_sha256": "4" * 64,
            "repo_file_count": 42,
            "route_authority_member_count": 2,
            "route_boundary_sha256": "5" * 64,
        },
    )


def _stub_boundary_evidence_index(
    monkeypatch: pytest.MonkeyPatch,
    *,
    repo: Path,
    index_path: Path,
    index_length: int,
    index_sha256: str,
    pr_additions: int = 400,
    pr_deletions: int = 400,
) -> None:
    state: dict[str, dict[str, Any]] = {}

    def collect(
        **kwargs: Any,
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, Any],
        dict[str, Any],
    ]:
        resources, summary = ratchet._load_evidence_resources(
            evidence_index_path=index_path,
            evidence_index_byte_length=index_length,
            evidence_index_sha256=index_sha256,
            boundary=kwargs["boundary"],
            start_sha=kwargs["start_sha"],
            end_sha=kwargs["end_sha"],
            operation_log=kwargs["operation_log"],
        )
        state["summary"] = summary
        governed = resources["governed_prs"]["records"]
        authenticated_pr_changes = {
            record["pr"]: {
                "additions": pr_additions,
                "deletions": pr_deletions,
            }
            for record in governed
        }
        authenticated_pr_files = {
            record["pr"]: _fixture_git_changed_paths(
                repo,
                record["base_sha"],
                record["head_sha"],
            )
            for record in governed
        }
        return (
            resources,
            summary,
            {
                "authenticated_pr_changes": authenticated_pr_changes,
                "authenticated_pr_files": authenticated_pr_files,
                "expected_rule_suite_ref": "refs/heads/main",
                "fixture_evidence_index": True,
                "repository_id": 1126097105,
                "repository_name": "aragora",
            },
        )

    def reauthenticate(
        _context: dict[str, Any],
        *,
        operation_log: list[dict[str, Any]],
        end_sha: str,
    ) -> dict[str, Any]:
        del end_sha
        return ratchet._reauthenticate_evidence_resources(
            evidence_index_path=index_path,
            evidence_summary=state["summary"],
            operation_log=operation_log,
        )

    monkeypatch.setattr(ratchet, "_collect_live_evidence", collect)
    monkeypatch.setattr(ratchet, "_reauthenticate_live_context", reauthenticate)


def _boundary_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    *,
    release_immutability: bool = True,
    mutate: Any | None = None,
    pr_additions: int = 400,
    pr_deletions: int = 400,
) -> dict[str, Any]:
    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path)
    end_sha = boundary_shas[boundary]
    index_path, index_length, index_sha256 = _write_boundary_index(
        tmp_path,
        boundary,
        start_sha,
        end_sha,
        boundary_shas,
        repo=repo,
        release_immutability=release_immutability,
        mutate=mutate,
    )
    _stub_boundary_dependencies(monkeypatch)
    _stub_boundary_evidence_index(
        monkeypatch,
        repo=repo,
        index_path=index_path,
        index_length=index_length,
        index_sha256=index_sha256,
        pr_additions=pr_additions,
        pr_deletions=pr_deletions,
    )
    return ratchet.build_boundary_result(
        repo_root=repo,
        schema_version=1,
        boundary=boundary,
        start_ref=start_sha,
        end_ref=end_sha,
    )


def test_boundary_pass_fixture_uses_production_artifact_and_authority_authentication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cohort_path, provenance_path = _write_synthetic_canonical_artifacts(
        tmp_path,
        monkeypatch,
    )
    repo_root, start_sha, end_sha = _clone_repository_with_synthetic_accepted_authority(
        tmp_path,
        cohort_path=cohort_path,
        provenance_path=provenance_path,
    )
    operation_log: list[dict[str, Any]] = []
    authority = ratchet._authenticate_authority_manifest(
        repo_root=repo_root,
        end_sha=end_sha,
        authority_manifest_path=None,
        authority_manifest_byte_length=None,
        authority_manifest_sha256=None,
        cohort_artifact_path=cohort_path,
        sdk_provenance_artifact_path=provenance_path,
        scratch_root=tmp_path,
        operation_log=operation_log,
    )
    boundary_shas = dict.fromkeys(ratchet.BOUNDARY_NAMES, end_sha)
    payloads = _boundary_payloads(
        "corrective_bootstrap",
        start_sha,
        end_sha,
        boundary_shas,
        repo=repo_root,
    )
    transition = payloads["corrective_bootstrap"]["corrective_transition"]
    transition["fact"]["commit_count"] = int(
        subprocess.check_output(
            [
                "git",
                "-C",
                str(repo_root),
                "rev-list",
                "--count",
                f"{start_sha}..{end_sha}",
            ],
            text=True,
        ).strip()
    )
    transition["sha256"] = ratchet._fact_digest(
        "contract-drift-corrective-transition-fact-v1",
        transition["fact"],
    )
    closure_fact = payloads["corrective_bootstrap"]["accepted_stage1_closure"]["fact"]
    closure_fact.update(
        {
            "authority_manifest_sha256": authority["authority_manifest_sha256"],
            "boundary_verifier_sha256": authority["boundary_verifier_sha256"],
            "dependency_manifest_sha256": authority["dependency_manifest_sha256"],
            "inventory_sha256": authority["inventory_sha256"],
            "repo_file_count": authority["repo_file_count"],
        }
    )
    payloads["corrective_bootstrap"]["accepted_stage1_closure"]["sha256"] = ratchet._fact_digest(
        "contract-drift-stage1-closure-fact-v1",
        closure_fact,
    )
    verifier_fact = payloads["corrective_bootstrap"]["stage2_verifier_chronology"]["fact"]
    verifier_fact["verifier_sha256"] = authority["boundary_verifier_sha256"]
    payloads["corrective_bootstrap"]["stage2_verifier_chronology"]["sha256"] = ratchet._fact_digest(
        "contract-drift-stage2-verifier-chronology-fact-v1",
        verifier_fact,
    )
    selected = {
        "boundary_chronology",
        "corrective_bootstrap",
        "durable_capsule",
        "external_prerequisites",
        "first_parent_receipts",
        "governed_prs",
    }
    resources = {name: value for name, value in payloads.items() if name in selected}
    resources["boundary_chronology"]["boundaries"] = resources["boundary_chronology"]["boundaries"][
        :1
    ]
    capsule_tag = f"cdg-corrective_bootstrap-{end_sha}"
    # Entry 32: the claim omits asset_api_ids — the payload bytes must be
    # final before GitHub assigns any asset ID at upload.
    resources["durable_capsule"]["release"] = {
        "asset_names": ["manifest.json", "payload.json", "checksums.txt"],
        "exact_full_sha_tag": end_sha,
        "immutable": True,
        "release_api_id": 100,
        "tag_name": capsule_tag,
        "verified": True,
    }
    # Stable identity claim: computable before any verification output exists,
    # unlike the retired bundle_sha256 fixed point (entry 30).
    resources["durable_capsule"]["attestation"] = _stable_attestation_claim()
    capsule_payload = {
        "boundary": "corrective_bootstrap",
        "end_sha": end_sha,
        "resources": [{"name": name, "value": value} for name, value in sorted(resources.items())],
        "schema": ratchet.BOUNDARY_CAPSULE_PAYLOAD_SCHEMA,
        "start_sha": start_sha,
    }
    payload_raw = _canonical_boundary_bytes(capsule_payload)
    capsule_manifest = {
        "boundary": "corrective_bootstrap",
        "end_sha": end_sha,
        "payload_byte_length": len(payload_raw),
        "payload_sha256": hashlib.sha256(payload_raw).hexdigest(),
        "schema": ratchet.BOUNDARY_CAPSULE_MANIFEST_SCHEMA,
        "start_sha": start_sha,
    }
    manifest_raw = _canonical_boundary_bytes(capsule_manifest)
    checksums_raw = (
        f"{hashlib.sha256(manifest_raw).hexdigest()}  manifest.json\n"
        f"{hashlib.sha256(payload_raw).hexdigest()}  payload.json\n"
    ).encode()
    assets = {
        101: checksums_raw,
        102: manifest_raw,
        103: payload_raw,
    }
    asset_sha256s = {
        "checksums.txt": hashlib.sha256(checksums_raw).hexdigest(),
        "manifest.json": hashlib.sha256(manifest_raw).hexdigest(),
        "payload.json": hashlib.sha256(payload_raw).hexdigest(),
    }
    release_verification_raw = ratchet._canonical_json_bytes(
        _real_shaped_verification_payload(asset_sha256s, tag=capsule_tag)
    )
    sigstore_verification_raw = b'[{"verified":true}]'
    tree_sha = subprocess.check_output(
        ["git", "-C", str(repo_root), "rev-parse", f"{end_sha}^{{tree}}"],
        text=True,
    ).strip()
    real_subprocess_run = subprocess.run

    def github_transport(
        argv: list[str],
        *args: Any,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[bytes]:
        if Path(argv[0]).name != "gh":
            return real_subprocess_run(argv, *args, **kwargs)
        if argv[1] == "release":
            return subprocess.CompletedProcess(argv, 0, stdout=release_verification_raw, stderr=b"")
        if argv[1] != "api":
            return subprocess.CompletedProcess(
                argv, 0, stdout=sigstore_verification_raw, stderr=b""
            )
        endpoint = argv[-1]
        if "/releases/assets/" in endpoint:
            body = assets[int(endpoint.rsplit("/", 1)[1])]
        elif endpoint == "repos/synaptent/aragora":
            body = ratchet._canonical_json_bytes(
                {
                    "full_name": "synaptent/aragora",
                    "id": 1126097105,
                    "name": "aragora",
                }
            )
        elif endpoint.endswith("/branches/main"):
            body = ratchet._canonical_json_bytes({"commit": {"sha": end_sha}, "name": "main"})
        elif endpoint.endswith("/branches/main/protection"):
            body = ratchet._canonical_json_bytes({"required_status_checks": {"strict": False}})
        elif endpoint.endswith("/immutable-releases"):
            body = ratchet._canonical_json_bytes({"enabled": True})
        elif endpoint.endswith("/releases?per_page=100&page=1"):
            body = ratchet._canonical_json_bytes([{"id": 100, "tag_name": capsule_tag}])
        elif endpoint.endswith("/releases/100"):
            body = ratchet._canonical_json_bytes(
                {
                    "assets": [
                        {"id": 101, "name": "checksums.txt"},
                        {"id": 102, "name": "manifest.json"},
                        {"id": 103, "name": "payload.json"},
                    ],
                    "draft": False,
                    "id": 100,
                    "immutable": True,
                    "prerelease": False,
                    "tag_name": capsule_tag,
                }
            )
        elif endpoint.endswith(f"/git/ref/tags/{capsule_tag}"):
            body = ratchet._canonical_json_bytes(
                {
                    "object": {"sha": end_sha, "type": "commit"},
                    "ref": f"refs/tags/{capsule_tag}",
                }
            )
        elif "/rulesets/rule-suites?ref=refs/heads/main&time_period=day" in endpoint:
            body = ratchet._canonical_json_bytes([_rule_suite_record(end_sha)])
        elif endpoint.endswith("/rulesets/rule-suites/987654"):
            body = ratchet._canonical_json_bytes(_rule_suite_record(end_sha))
        elif endpoint.endswith("/pulls/9999/files?per_page=100&page=1"):
            # Truthful disposition: the synthetic authority commit changes
            # exactly the accepted inventory, and the always-on VAL-CDG-018
            # disposition check compares the recomputed first-parent semantic
            # delta against this authenticated file set.
            body = ratchet._canonical_json_bytes(
                [{"filename": "scripts/baselines/contract_drift_inventory.json", "id": 1}]
            )
        elif endpoint.endswith("/pulls/9999"):
            body = ratchet._canonical_json_bytes(
                {
                    "additions": 400,
                    "base": {"sha": start_sha},
                    "changed_files": 1,
                    "deletions": 400,
                    "head": {"sha": end_sha},
                    "merge_commit_sha": end_sha,
                    "merged_at": "2026-07-20T00:00:00Z",
                    "number": 9999,
                }
            )
        elif endpoint.endswith(f"/git/commits/{end_sha}"):
            body = ratchet._canonical_json_bytes(
                {
                    "parents": [{"sha": start_sha}],
                    "sha": end_sha,
                    "tree": {"sha": tree_sha},
                }
            )
        else:
            raise AssertionError(endpoint)
        stdout = (
            b'HTTP/2 200 OK\r\nETag: "fixture"\r\n'
            b"Last-Modified: Mon, 20 Jul 2026 00:00:00 GMT\r\n\r\n" + body
        )
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(subprocess, "run", github_transport)

    result = ratchet.build_boundary_result(
        repo_root=repo_root,
        schema_version=1,
        boundary="corrective_bootstrap",
        start_ref=start_sha,
        end_ref=end_sha,
        cohort_artifact_path=cohort_path,
        sdk_provenance_artifact_path=provenance_path,
        scratch_root=tmp_path,
        output_root=tmp_path,
    )

    assert result["status"] == "pass", result.get("blocked_reason") or result.get("error")
    assert result["canonical_artifacts"]["original_cohort"]["record_count"] == 655
    assert result["canonical_artifacts"]["sdk_provenance"]["record_count"] == 598
    assert result["authority"]["repo_file_count"] > 0
    assert any(
        entry["resource"] == "sigstore-attestation:manifest.json"
        for entry in result["operation_log"]
    )
    authority_reads = [
        entry
        for entry in result["operation_log"]
        if entry["resource"] == "authority_manifest"
        and entry["kind"] in {"authority_reconstruction", "external_authority_manifest"}
    ]
    assert len(authority_reads) == 2
    assert authority_reads[0]["byte_length"] > 0
    assert authority_reads[0]["sha256"] == authority_reads[1]["sha256"]


def test_original_cohort_descriptor_is_immutable_across_authority_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cohort_path, provenance_path = _write_synthetic_canonical_artifacts(
        tmp_path,
        monkeypatch,
    )
    original_raw = cohort_path.read_bytes()

    def authenticate() -> dict[str, Any]:
        return ratchet._authenticate_canonical_artifacts(
            repo_root=tmp_path,
            cohort_artifact_path=cohort_path,
            sdk_provenance_artifact_path=provenance_path,
            scratch_root=tmp_path,
            operation_log=[],
        )

    def bind_cohort(raw: bytes) -> None:
        cohort_path.write_bytes(raw)
        monkeypatch.setitem(ratchet.COHORT_ARTIFACT, "byte_length", len(raw))
        monkeypatch.setitem(
            ratchet.COHORT_ARTIFACT,
            "sha256",
            hashlib.sha256(raw).hexdigest(),
        )

    with pytest.raises(ValueError, match="byte-length mismatch"):
        cohort_path.write_bytes(original_raw + b" ")
        authenticate()

    cohort_path.write_bytes(original_raw.replace(b'"fixture"', b'"fixturx"', 1))
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        authenticate()

    cohort = json.loads(original_raw)
    cohort["original_record_id_set"]["sha256"] = "0" * 64
    bind_cohort(ratchet._canonical_json_bytes(cohort, terminal_lf=True))
    with pytest.raises(ValueError, match="original-record ID-set digest mismatch"):
        authenticate()

    cohort = json.loads(original_raw)
    cohort["original_records"][1] = copy.deepcopy(cohort["original_records"][0])
    bind_cohort(ratchet._canonical_json_bytes(cohort, terminal_lf=True))
    with pytest.raises(ValueError, match="duplicate original record IDs"):
        authenticate()


def test_canonical_cohort_and_provenance_artifacts_are_in_authority_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cohort_path, provenance_path = _write_synthetic_canonical_artifacts(
        tmp_path,
        monkeypatch,
    )
    original_raw = provenance_path.read_bytes()
    provenance = json.loads(original_raw)
    provenance["records"][1] = copy.deepcopy(provenance["records"][0])
    duplicate_raw = ratchet._canonical_json_bytes(provenance, terminal_lf=True)
    provenance_path.write_bytes(duplicate_raw)
    monkeypatch.setitem(ratchet.PROVENANCE_ARTIFACT, "byte_length", len(duplicate_raw))
    monkeypatch.setitem(
        ratchet.PROVENANCE_ARTIFACT,
        "sha256",
        hashlib.sha256(duplicate_raw).hexdigest(),
    )

    with pytest.raises(ValueError, match="does not biject"):
        ratchet._authenticate_canonical_artifacts(
            repo_root=tmp_path,
            cohort_artifact_path=cohort_path,
            sdk_provenance_artifact_path=provenance_path,
            scratch_root=tmp_path,
            operation_log=[],
        )

    provenance_path.write_bytes(original_raw)
    monkeypatch.setitem(ratchet.PROVENANCE_ARTIFACT, "byte_length", len(original_raw))
    monkeypatch.setitem(
        ratchet.PROVENANCE_ARTIFACT,
        "sha256",
        hashlib.sha256(original_raw).hexdigest(),
    )
    repo_root, production_sha, end_sha = _clone_repository_with_synthetic_accepted_authority(
        tmp_path,
        cohort_path=cohort_path,
        provenance_path=provenance_path,
    )
    with pytest.raises(
        gen.AuthorityClosureError,
        match="accepted authority differs from authenticated canonical artifacts",
    ):
        ratchet._authenticate_authority_manifest(
            repo_root=repo_root,
            end_sha=production_sha,
            authority_manifest_path=None,
            authority_manifest_byte_length=None,
            authority_manifest_sha256=None,
            cohort_artifact_path=cohort_path,
            sdk_provenance_artifact_path=provenance_path,
            scratch_root=tmp_path,
            operation_log=[],
        )
    captured: dict[str, Any] = {}
    original_build = ratchet.inventory_mod.build_authority_manifest

    def capture_manifest(*args: Any, **kwargs: Any) -> dict[str, Any]:
        manifest = original_build(*args, **kwargs)
        captured["manifest"] = manifest
        return manifest

    monkeypatch.setattr(
        ratchet.inventory_mod,
        "build_authority_manifest",
        capture_manifest,
    )
    ratchet._authenticate_authority_manifest(
        repo_root=repo_root,
        end_sha=end_sha,
        authority_manifest_path=None,
        authority_manifest_byte_length=None,
        authority_manifest_sha256=None,
        cohort_artifact_path=cohort_path,
        sdk_provenance_artifact_path=provenance_path,
        scratch_root=tmp_path,
        operation_log=[],
    )

    external_artifacts = captured["manifest"]["inventory"]["external_artifacts"]
    expected_artifacts: list[dict[str, Any]] = [
        {
            "byte_length": cohort_path.stat().st_size,
            "canonical_bytes": True,
            "path": cohort_path.name,
            "sha256": hashlib.sha256(cohort_path.read_bytes()).hexdigest(),
        },
        {
            "byte_length": provenance_path.stat().st_size,
            "canonical_bytes": True,
            "path": provenance_path.name,
            "sha256": hashlib.sha256(provenance_path.read_bytes()).hexdigest(),
        },
    ]
    assert external_artifacts == sorted(expected_artifacts, key=lambda item: item["path"])


def test_external_authority_manifest_and_evidence_index_bytes_are_canonical_before_semantic_digest(
    tmp_path: Path,
):
    canonical = tmp_path / "canonical.json"
    descriptor = _write_canonical_boundary_json(canonical, {"schema": "fixture", "value": 1})
    payload, authenticated = ratchet._load_canonical_json_bytes(
        canonical,
        label="fixture",
        expected_byte_length=descriptor["byte_length"],
        expected_sha256=descriptor["sha256"],
        terminal_lf=True,
    )
    assert payload == {"schema": "fixture", "value": 1}
    assert authenticated["canonical_bytes_valid"] is True

    for raw, message in (
        (b"\xef\xbb\xbf" + canonical.read_bytes(), "BOM"),
        (b'{ "schema": "fixture", "value": 1 }\n', "canonical"),
        (b'{"schema":"fixture","value":1}', "terminal LF"),
        (b'{"value":1,"schema":"fixture"}\n', "canonical"),
    ):
        candidate = tmp_path / f"bad-{hashlib.sha256(raw).hexdigest()}.json"
        candidate.write_bytes(raw)
        with pytest.raises(ValueError, match=message):
            ratchet._load_canonical_json_bytes(
                candidate,
                label="fixture",
                expected_byte_length=len(raw),
                expected_sha256=hashlib.sha256(raw).hexdigest(),
                terminal_lf=True,
            )


@pytest.mark.parametrize(
    ("flag", "value"),
    (
        ("--evidence-index", "forged.json"),
        ("--github-repository", "attacker/mirror"),
        ("--github-branch", "forged"),
    ),
)
def test_boundary_cli_rejects_caller_supplied_authority(
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
    value: str,
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_contract_drift_ratchet.py",
            "--mode",
            "boundary",
            "--schema-version",
            "1",
            "--boundary",
            "corrective_bootstrap",
            "--start-ref",
            "0" * 40,
            "--end-ref",
            "1" * 40,
            flag,
            value,
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        ratchet.main()
    assert exc_info.value.code == 2


def test_boundary_python_api_rejects_caller_supplied_evidence_or_github_trust_roots():
    parameters = inspect.signature(ratchet.build_boundary_result).parameters
    assert "evidence_index_path" not in parameters
    assert "evidence_index_byte_length" not in parameters
    assert "evidence_index_sha256" not in parameters
    assert "github_repository" not in parameters
    assert "github_branch" not in parameters


def test_parse_http_response_preserves_exact_body_bytes():
    body = b"binary\r\nbody\n\nHTTP/1.1 200 OK\r\nnot-a-header"
    headers, parsed = ratchet._parse_http_response(
        b'HTTP/1.1 200 OK\r\nETag: "fixture"\r\nContent-Type: application/octet-stream'
        b"\r\n\r\n" + body
    )
    assert headers["etag"] == '"fixture"'
    assert parsed == body

    headers, parsed = ratchet._parse_http_response(
        b"HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 200 OK\nETag: final\n\npayload\r\nbytes"
    )
    assert headers["etag"] == "final"
    assert parsed == b"payload\r\nbytes"

    with pytest.raises(ValueError, match="authenticated HTTP headers"):
        ratchet._parse_http_response(b"headerless")


def test_boundary_rule_suite_binds_repository_main_ref_and_end_sha():
    end_sha = "1" * 40
    rule_suite = _rule_suite_claim(end_sha)
    operation_log: list[dict[str, Any]] = []

    authenticated = ratchet._authenticate_persisted_rule_suite_claim(
        rule_suite,
        repository_id=1126097105,
        repository_name="aragora",
        expected_ref="refs/heads/main",
        end_sha=end_sha,
        operation_log=operation_log,
    )
    ratchet._validate_current_rule_suite_binding(
        rule_suite,
        observed_rule_suite=_rule_suite_record(end_sha),
        observed_identity={
            "byte_length": rule_suite["raw_response_byte_length"],
            "raw_response": rule_suite["raw_response"],
            "response_fields": _rule_suite_record(end_sha),
            "sha256": rule_suite["raw_response_sha256"],
        },
        repository_id=1126097105,
        repository_name="aragora",
        expected_ref="refs/heads/main",
        end_sha=end_sha,
        operation_log=operation_log,
    )

    assert authenticated["repository_id"] == 1126097105
    assert authenticated["repository_name"] == "aragora"
    assert authenticated["ref"] == "refs/heads/main"
    assert authenticated["after_sha"] == end_sha
    assert authenticated["result"] == "pass"
    raw_entries = [
        entry
        for entry in operation_log
        if entry["resource"] == "github-rule-suite-seal-time-response"
    ]
    assert raw_entries
    assert raw_entries[0]["raw_response"] == rule_suite["raw_response"]
    assert raw_entries[0]["response_fields"] == _rule_suite_record(end_sha)


@pytest.mark.parametrize(
    ("label", "claim"),
    (
        pytest.param(
            "stale-after-sha",
            _rule_suite_claim("2" * 40),
            id="stale-after-sha",
        ),
        pytest.param(
            "wrong-repository-id",
            _rule_suite_claim("1" * 40, repository_id=7),
            id="wrong-repository-id",
        ),
        pytest.param(
            "wrong-repository-name",
            _rule_suite_claim("1" * 40, repository_name="mirror"),
            id="wrong-repository-name",
        ),
        pytest.param(
            "wrong-ref",
            _rule_suite_claim("1" * 40, ref="refs/heads/feature"),
            id="wrong-ref",
        ),
        pytest.param(
            "masked-ref",
            _rule_suite_claim("1" * 40, ref="refs/__gh__/UNKNOWN"),
            id="masked-ref",
        ),
        pytest.param(
            "missing-after-sha",
            _rule_suite_claim("1" * 40, delete="after_sha"),
            id="missing-after-sha",
        ),
        pytest.param(
            "null-repository-id",
            _rule_suite_claim("1" * 40, repository_id=None),
            id="null-repository-id",
        ),
        pytest.param(
            "plain-result-fail",
            _rule_suite_claim("1" * 40, result="fail"),
            id="plain-result-fail",
        ),
        pytest.param(
            "result-bypass",
            _rule_suite_claim("1" * 40, result="bypass"),
            id="result-bypass",
        ),
        pytest.param(
            "evaluation-bypass",
            _rule_suite_claim("1" * 40, evaluation_result="bypass"),
            id="evaluation-bypass",
        ),
        pytest.param(
            "nested-evaluation-bypass",
            _rule_suite_claim(
                "1" * 40,
                rule_evaluations=[{"result": "bypass", "rule_source": {"type": "repository"}}],
            ),
            id="nested-evaluation-bypass",
        ),
        pytest.param(
            "capsule-bypassed",
            _rule_suite_claim("1" * 40, bypassed=True),
            id="capsule-bypassed",
        ),
    ),
)
def test_stale_wrong_repository_wrong_ref_missing_fields_or_bypassed_rule_suite_fails_closed(
    label: str,
    claim: dict[str, Any],
):
    if label != "capsule-bypassed":
        with pytest.raises(ValueError):
            ratchet._select_current_rule_suite_candidate(
                [json.loads(claim["raw_response"])],
                rule_suite_id=987654,
                repository_id=1126097105,
                repository_name="aragora",
                expected_ref="refs/heads/main",
                end_sha="1" * 40,
            )
    with pytest.raises(ValueError) as exc_info:
        ratchet._authenticate_persisted_rule_suite_claim(
            claim,
            repository_id=1126097105,
            repository_name="aragora",
            expected_ref="refs/heads/main",
            end_sha="1" * 40,
            operation_log=[],
        )
    assert str(exc_info.value), label


def test_blocked_boundary_exit_code_is_distinct_from_argparse_errors(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        ratchet,
        "build_boundary_result",
        lambda **_kwargs: {
            "blocked_reason": "authenticated prerequisite unavailable",
            "manifest_sha256": "a" * 64,
            "status": "blocked",
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_contract_drift_ratchet.py",
            "--mode",
            "boundary",
            "--schema-version",
            "1",
            "--boundary",
            "corrective_bootstrap",
            "--start-ref",
            "0" * 40,
            "--end-ref",
            "1" * 40,
        ],
    )
    assert ratchet.main() == 3


def test_scratch_asset_write_rejects_preexisting_symlink(tmp_path: Path):
    target = tmp_path / "target"
    target.write_bytes(b"preserve")
    candidate = tmp_path / "asset"
    candidate.symlink_to(target)

    with pytest.raises(ValueError, match="created exclusively"):
        ratchet._write_exclusive_private_file(
            candidate,
            b"replacement",
            scratch_root=tmp_path,
            output_root=tmp_path,
        )

    assert target.read_bytes() == b"preserve"


def test_nonzero_read_only_probe_is_not_logged_as_authenticated_pass(tmp_path: Path):
    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path)
    operation_log: list[dict[str, Any]] = []
    proc = ratchet._run_read_only(
        [
            "git",
            "-C",
            str(repo),
            "merge-base",
            "--is-ancestor",
            boundary_shas["final_seal"],
            start_sha,
        ],
        operation_log=operation_log,
        resource="negative-ancestry-probe",
        check=False,
    )

    assert proc.returncode == 1
    assert operation_log[-1]["authentication"] == "observed_nonzero"


def test_boundary_verifier_independently_reads_resources_and_emits_own_operation_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    result = _boundary_result(tmp_path, monkeypatch, "corrective_bootstrap")
    assert result["status"] == "pass"
    resources = {
        entry["resource"]
        for entry in result["operation_log"]
        if entry["kind"] == "external_resource"
    }
    assert "corrective_bootstrap" in resources
    assert "external_prerequisites" in resources
    assert all(entry["authentication"] == "pass" for entry in result["operation_log"])
    assert result["evidence"]["resource_count"] == len(resources)


def test_caller_summaries_and_parse_reserialize_are_not_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path)
    boundary = "corrective_bootstrap"
    end_sha = boundary_shas[boundary]
    index_path, index_length, index_sha256 = _write_boundary_index(
        tmp_path,
        boundary,
        start_sha,
        end_sha,
        boundary_shas,
        repo=repo,
    )
    index = json.loads(index_path.read_text())
    index["summary"] = {"status": "pass", "resource_count": len(index["resources"])}
    raw = _canonical_boundary_bytes(index)
    index_path.write_bytes(raw)
    _stub_boundary_dependencies(monkeypatch)
    _stub_boundary_evidence_index(
        monkeypatch,
        repo=repo,
        index_path=index_path,
        index_length=len(raw),
        index_sha256=hashlib.sha256(raw).hexdigest(),
    )
    result = ratchet.build_boundary_result(
        repo_root=repo,
        schema_version=1,
        boundary=boundary,
        start_ref=start_sha,
        end_ref=end_sha,
    )
    assert result["status"] == "fail"
    assert "caller-supplied" in result["error"]

    pretty = (
        json.dumps(json.loads(index_path.read_text()), indent=2, sort_keys=True).encode() + b"\n"
    )
    index_path.write_bytes(pretty)
    _stub_boundary_evidence_index(
        monkeypatch,
        repo=repo,
        index_path=index_path,
        index_length=len(pretty),
        index_sha256=hashlib.sha256(pretty).hexdigest(),
    )
    result = ratchet.build_boundary_result(
        repo_root=repo,
        schema_version=1,
        boundary=boundary,
        start_ref=start_sha,
        end_ref=end_sha,
    )
    assert result["status"] == "fail"
    assert "terminal LF" in result["error"] or "canonical" in result["error"]


def test_boundary_predicates_are_distinct_nonempty_strictly_ordered_and_start_differs_from_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    results = [
        _boundary_result(tmp_path / boundary, monkeypatch, boundary)
        for boundary in ratchet.BOUNDARY_NAMES
    ]
    predicate_shapes = []
    for result, boundary in zip(results, ratchet.BOUNDARY_NAMES, strict=True):
        assert result["start_sha"] != result["end_sha"]
        assert result["status"] == "pass"
        selected = result["predicates"]
        assert selected
        assert list(selected) == list(
            ratchet.BOUNDARY_NAMES[: ratchet.BOUNDARY_NAMES.index(boundary) + 1]
        )
        assert all(selected[name]["proven"] is True for name in selected)
        predicate_shapes.append(tuple(selected[boundary]["checks"]))
    assert len(set(predicate_shapes)) == len(ratchet.BOUNDARY_NAMES)


def test_boundary_status_pass_requires_all_predicates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def break_route(payloads: dict[str, dict[str, Any]]) -> None:
        payloads["route_truth"]["route_truth"]["fact"]["complete"] = False

    result = _boundary_result(
        tmp_path,
        monkeypatch,
        "core_sdk",
        mutate=break_route,
    )
    assert result["status"] == "fail"
    assert not result["passing"]
    assert "route truth" in result["error"]


def test_boundary_status_blocked_is_only_verified_external_prerequisite_or_movement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    blocked = _boundary_result(
        tmp_path / "prerequisite",
        monkeypatch,
        "corrective_bootstrap",
        release_immutability=False,
    )
    assert blocked["status"] == "blocked"
    assert "future GitHub Release immutability" in blocked["blocked_reason"]

    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path / "movement")
    _stub_boundary_dependencies(monkeypatch)
    monkeypatch.setattr(
        ratchet,
        "_collect_live_evidence",
        lambda **_kwargs: (_ for _ in ()).throw(
            ratchet.BoundaryBlocked("authenticated remote resource moved concurrently")
        ),
    )
    movement = ratchet.build_boundary_result(
        repo_root=repo,
        schema_version=1,
        boundary="corrective_bootstrap",
        start_ref=start_sha,
        end_ref=boundary_shas["corrective_bootstrap"],
    )
    assert movement["status"] == "blocked"
    assert "moved concurrently" in movement["blocked_reason"]

    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path / "no-main-evaluation")
    monkeypatch.setattr(
        ratchet,
        "_collect_live_evidence",
        lambda **_kwargs: ratchet._select_current_rule_suite_candidate(
            [],
            rule_suite_id=987654,
            repository_id=1126097105,
            repository_name="aragora",
            expected_ref="refs/heads/main",
            end_sha=boundary_shas["corrective_bootstrap"],
        ),
    )
    no_main_evaluation = ratchet.build_boundary_result(
        repo_root=repo,
        schema_version=1,
        boundary="corrective_bootstrap",
        start_ref=start_sha,
        end_ref=boundary_shas["corrective_bootstrap"],
    )
    assert no_main_evaluation["status"] == "blocked"
    assert "absence of a main rule evaluation" in no_main_evaluation["blocked_reason"]


def test_boundary_status_fail_covers_malformed_false_missing_bypass_and_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    mutations = {
        "malformed": lambda payloads: payloads["core_sdk"].update(
            {"qualifying_paydown": "trusted summary"}
        ),
        "false": lambda payloads: payloads["core_sdk"]["zero_core_debt"]["fact"].update(
            {"remaining_original_units": 1}
        ),
        "missing": lambda payloads: payloads.pop("core_sdk"),
        "bypass": lambda payloads: payloads["external_prerequisites"]["rule_suite"].update(
            {"bypassed": True}
        ),
        "mutation": lambda payloads: payloads["external_prerequisites"].update(
            {"mutation_tainted": True}
        ),
    }
    for label, mutate in mutations.items():
        result = _boundary_result(
            tmp_path / label,
            monkeypatch,
            "core_sdk",
            mutate=mutate,
        )
        assert result["status"] == "fail", (label, result)
        assert not result["passing"]


@pytest.mark.parametrize(
    ("pr_additions", "pr_deletions", "max_pr_delta", "expected_error"),
    (
        # Contract L76: the census admits the 801 authenticated delta, but the
        # paydown fact (capped at 800) can never bind it — an over-cap
        # core/extended paydown PR fails closed on the paydown plane.
        pytest.param(
            401,
            400,
            800,
            "max_pr_delta does not match authenticated live PR data",
            id="live-pr-over-cap",
        ),
        pytest.param(400, 400, 799, "max_pr_delta", id="paydown-max-mismatch"),
    ),
)
def test_paydown_pr_delta_is_authenticated_and_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pr_additions: int,
    pr_deletions: int,
    max_pr_delta: int,
    expected_error: str,
):
    def mutate(payloads: dict[str, dict[str, Any]]) -> None:
        paydown = payloads["core_sdk"]["qualifying_paydown"]
        paydown["fact"]["max_pr_delta"] = max_pr_delta
        paydown["sha256"] = ratchet._fact_digest(
            "contract-drift-core-sdk-paydown-fact-v1",
            paydown["fact"],
        )

    result = _boundary_result(
        tmp_path,
        monkeypatch,
        "core_sdk",
        mutate=mutate,
        pr_additions=pr_additions,
        pr_deletions=pr_deletions,
    )

    assert result["status"] == "fail"
    assert expected_error in result["error"]


def test_canonical_route_fact_fails_when_exact_ref_baseline_contradicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path, route_debt=True)
    end_sha = boundary_shas["route_truth"]
    index_path, index_length, index_sha256 = _write_boundary_index(
        tmp_path,
        "route_truth",
        start_sha,
        end_sha,
        boundary_shas,
        repo=repo,
    )
    _stub_boundary_dependencies(monkeypatch)
    _stub_boundary_evidence_index(
        monkeypatch,
        repo=repo,
        index_path=index_path,
        index_length=index_length,
        index_sha256=index_sha256,
    )

    result = ratchet.build_boundary_result(
        repo_root=repo,
        schema_version=1,
        boundary="route_truth",
        start_ref=start_sha,
        end_ref=end_sha,
    )

    assert result["status"] == "fail"
    assert "contradicted by exact-ref route baselines" in result["error"]


@pytest.mark.parametrize(
    ("category", "path_name"),
    (
        ("python_sdk_drift", "verify_sdk_contracts.json"),
        ("typescript_sdk_drift", "verify_sdk_contracts.json"),
        ("missing_in_spec", "validate_openapi_routes.json"),
        ("orphaned_in_spec", "validate_openapi_routes.json"),
        ("missing_from_both_sdks", "check_sdk_parity.json"),
    ),
)
@pytest.mark.parametrize(
    ("mode", "value"),
    (
        ("missing", None),
        ("null", None),
        ("string", "not-a-list"),
        ("object", {"not": "a-list"}),
        ("mixed", ["valid", 7]),
    ),
)
def test_exact_ref_baseline_categories_require_lists_of_strings(
    tmp_path: Path,
    category: str,
    path_name: str,
    mode: str,
    value: Any,
):
    repo, _start_sha, _boundary_shas = _boundary_git_repo(tmp_path)
    path = repo / "scripts" / "baselines" / path_name
    payload = json.loads(path.read_text())
    if mode == "missing":
        payload.pop(category)
    else:
        payload[category] = value
    _write_json(path, payload)
    ref = _commit(repo, f"malformed {category} {mode}")

    with pytest.raises(ValueError, match=category):
        ratchet._baseline_category_counts_at_ref(
            repo,
            ref,
            operation_log=[],
        )


def test_exact_ref_baseline_categories_allow_empty_string_lists(tmp_path: Path):
    repo, _start_sha, boundary_shas = _boundary_git_repo(tmp_path)

    assert ratchet._baseline_category_counts_at_ref(
        repo,
        boundary_shas["final_seal"],
        operation_log=[],
    ) == {
        "python_sdk_drift": 0,
        "routes_missing_in_spec": 0,
        "routes_orphaned_in_spec": 0,
        "sdk_missing_from_both": 0,
        "typescript_sdk_drift": 0,
    }


def test_later_boundary_fails_when_route_debt_is_reintroduced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, start_sha, boundary_shas = _boundary_git_repo(
        tmp_path,
        route_debt_at="core_sdk",
    )
    end_sha = boundary_shas["core_sdk"]
    index_path, index_length, index_sha256 = _write_boundary_index(
        tmp_path,
        "core_sdk",
        start_sha,
        end_sha,
        boundary_shas,
        repo=repo,
    )
    _stub_boundary_dependencies(monkeypatch)
    _stub_boundary_evidence_index(
        monkeypatch,
        repo=repo,
        index_path=index_path,
        index_length=index_length,
        index_sha256=index_sha256,
    )

    result = ratchet.build_boundary_result(
        repo_root=repo,
        schema_version=1,
        boundary="core_sdk",
        start_ref=start_sha,
        end_ref=end_sha,
    )

    assert result["status"] == "fail"
    assert "contradicted by exact-ref route baselines" in result["error"]


@pytest.mark.parametrize(
    ("boundary", "partition"),
    (("core_sdk", "core"), ("extended_sdk", "extended")),
)
def test_sdk_zero_debt_fails_when_exact_ref_baseline_contradicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    partition: str,
):
    repo, start_sha, boundary_shas = _boundary_git_repo(
        tmp_path,
        sdk_debt_partition=partition,
        sdk_debt_at=boundary,
    )
    end_sha = boundary_shas[boundary]
    index_path, index_length, index_sha256 = _write_boundary_index(
        tmp_path,
        boundary,
        start_sha,
        end_sha,
        boundary_shas,
        repo=repo,
    )
    _stub_boundary_dependencies(monkeypatch)
    _stub_boundary_evidence_index(
        monkeypatch,
        repo=repo,
        index_path=index_path,
        index_length=index_length,
        index_sha256=index_sha256,
    )

    result = ratchet.build_boundary_result(
        repo_root=repo,
        schema_version=1,
        boundary=boundary,
        start_ref=start_sha,
        end_ref=end_sha,
    )

    assert result["status"] == "fail"
    assert "contradicted by exact-ref SDK category baselines" in result["error"]


def test_core_sdk_allows_remaining_extended_exact_ref_baseline_debt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, start_sha, boundary_shas = _boundary_git_repo(
        tmp_path,
        sdk_debt_partition="extended",
        sdk_debt_at="core_sdk",
    )
    end_sha = boundary_shas["core_sdk"]
    index_path, index_length, index_sha256 = _write_boundary_index(
        tmp_path,
        "core_sdk",
        start_sha,
        end_sha,
        boundary_shas,
        repo=repo,
    )
    _stub_boundary_dependencies(monkeypatch)
    _stub_boundary_evidence_index(
        monkeypatch,
        repo=repo,
        index_path=index_path,
        index_length=index_length,
        index_sha256=index_sha256,
    )

    result = ratchet.build_boundary_result(
        repo_root=repo,
        schema_version=1,
        boundary="core_sdk",
        start_ref=start_sha,
        end_ref=end_sha,
    )

    assert result["status"] == "pass", result


def test_governed_prs_and_receipts_must_reconcile_exact_identities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    result = _boundary_result(
        tmp_path,
        monkeypatch,
        "core_sdk",
        mutate=lambda payloads: payloads["first_parent_receipts"]["records"][1].update(
            {"pr": 123456}
        ),
    )

    assert result["status"] == "fail"
    assert "do not reconcile" in result["error"]


def test_evidence_reauthentication_blocks_toctou_movement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path)
    end_sha = boundary_shas["corrective_bootstrap"]
    index_path, index_length, index_sha256 = _write_boundary_index(
        tmp_path,
        "corrective_bootstrap",
        start_sha,
        end_sha,
        boundary_shas,
        repo=repo,
    )
    _stub_boundary_dependencies(monkeypatch)
    _stub_boundary_evidence_index(
        monkeypatch,
        repo=repo,
        index_path=index_path,
        index_length=index_length,
        index_sha256=index_sha256,
    )
    original_evaluate = ratchet._evaluate_boundary_evidence

    def evaluate_and_move(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_evaluate(*args, **kwargs)
        resource = tmp_path / "resources-corrective_bootstrap" / "governed_prs.json"
        resource.write_bytes(resource.read_bytes() + b" ")
        return result

    monkeypatch.setattr(ratchet, "_evaluate_boundary_evidence", evaluate_and_move)

    result = ratchet.build_boundary_result(
        repo_root=repo,
        schema_version=1,
        boundary="corrective_bootstrap",
        start_ref=start_sha,
        end_ref=end_sha,
    )

    assert result["status"] == "blocked"
    assert "moved concurrently" in result["blocked_reason"]


def test_deterministic_boundary_fixtures_reach_pass_while_live_release_immutability_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        sys.modules[__name__],
        "_canonical_fixture_artifact_paths",
        lambda: None,
    )
    for boundary in ratchet.BOUNDARY_NAMES:
        result = _boundary_result(tmp_path / boundary, monkeypatch, boundary)
        assert result["status"] == "pass", result

    live = _boundary_result(
        tmp_path / "live-blocked",
        monkeypatch,
        "final_seal",
        release_immutability=False,
    )
    assert live["status"] == "blocked"
    assert live["passing"] is False


def test_boundary_uses_private_scratch_child_and_removes_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path / "repo")
    boundary = "corrective_bootstrap"
    end_sha = boundary_shas[boundary]
    index_path, index_length, index_sha256 = _write_boundary_index(
        tmp_path,
        boundary,
        start_sha,
        end_sha,
        boundary_shas,
        repo=repo,
    )
    _stub_boundary_dependencies(monkeypatch)
    _stub_boundary_evidence_index(
        monkeypatch,
        repo=repo,
        index_path=index_path,
        index_length=index_length,
        index_sha256=index_sha256,
    )
    original_collect = ratchet._collect_live_evidence
    observed: dict[str, Path] = {}

    def collect(**kwargs: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        observed["scratch_root"] = kwargs["scratch_root"]
        return original_collect(**kwargs)

    monkeypatch.setattr(ratchet, "_collect_live_evidence", collect)
    shared_parent = tmp_path / "shared-scratch"
    shared_parent.mkdir()
    result = ratchet.build_boundary_result(
        repo_root=repo,
        schema_version=1,
        boundary=boundary,
        start_ref=start_sha,
        end_ref=end_sha,
        scratch_root=shared_parent,
    )

    private_root = observed["scratch_root"]
    assert result["status"] == "pass", result
    assert private_root.parent == shared_parent.resolve()
    assert private_root.name.startswith("contract-drift-boundary-")
    assert not private_root.exists()


def test_unexpected_boundary_exception_fails_closed_and_cleans_private_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path / "repo")
    observed: dict[str, Path] = {}
    original_temporary_directory = ratchet.tempfile.TemporaryDirectory

    def tracking_temporary_directory(*args: Any, **kwargs: Any) -> Any:
        directory = original_temporary_directory(*args, **kwargs)
        observed["scratch_root"] = Path(directory.name)
        return directory

    monkeypatch.setattr(
        ratchet.tempfile,
        "TemporaryDirectory",
        tracking_temporary_directory,
    )
    monkeypatch.setattr(
        ratchet,
        "_snapshot_repository",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("hostile boundary crash")),
    )

    result = ratchet.build_boundary_result(
        repo_root=repo,
        schema_version=1,
        boundary="corrective_bootstrap",
        start_ref=start_sha,
        end_ref=boundary_shas["corrective_bootstrap"],
        scratch_root=tmp_path,
    )

    assert result["status"] == "fail"
    assert result["error_code"] == "boundary_unexpected_exception"
    assert result["error"] == "unexpected boundary exception: RuntimeError"
    assert not observed["scratch_root"].exists()


@pytest.mark.parametrize(
    ("wrong_first_parent", "expected_error"),
    (
        pytest.param(False, None, id="ignores-pr-api-base-sha"),
        pytest.param(
            True,
            "lacks first-parent or tree equality",
            id="rejects-wrong-merge-first-parent",
        ),
    ),
)
def test_live_evidence_authenticates_base_from_merge_first_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wrong_first_parent: bool,
    expected_error: str | None,
):
    _repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path)
    end_sha = boundary_shas["corrective_bootstrap"]
    resources = _boundary_payloads(
        "corrective_bootstrap",
        start_sha,
        end_sha,
        boundary_shas,
        repo=_repo,
    )
    selected = {
        "boundary_chronology",
        "corrective_bootstrap",
        "durable_capsule",
        "external_prerequisites",
        "first_parent_receipts",
        "governed_prs",
    }
    resources = {name: value for name, value in resources.items() if name in selected}
    resources["boundary_chronology"]["boundaries"] = resources["boundary_chronology"]["boundaries"][
        :1
    ]

    verification_identity = {"byte_length": 18, "sha256": "a" * 64}
    capsule_tag = f"cdg-corrective_bootstrap-{end_sha}"
    # Entry 32: claim shape omits asset_api_ids (pre-known fields only).
    resources["durable_capsule"]["release"] = {
        "asset_names": ["manifest.json", "payload.json", "checksums.txt"],
        "exact_full_sha_tag": end_sha,
        "immutable": True,
        "release_api_id": 100,
        "tag_name": capsule_tag,
        "verified": True,
    }
    resources["durable_capsule"]["attestation"] = _stable_attestation_claim()
    payload = {
        "boundary": "corrective_bootstrap",
        "end_sha": end_sha,
        "resources": [{"name": name, "value": value} for name, value in sorted(resources.items())],
        "schema": ratchet.BOUNDARY_CAPSULE_PAYLOAD_SCHEMA,
        "start_sha": start_sha,
    }
    payload_raw = _canonical_boundary_bytes(payload)
    manifest = {
        "boundary": "corrective_bootstrap",
        "end_sha": end_sha,
        "payload_byte_length": len(payload_raw),
        "payload_sha256": hashlib.sha256(payload_raw).hexdigest(),
        "schema": ratchet.BOUNDARY_CAPSULE_MANIFEST_SCHEMA,
        "start_sha": start_sha,
    }
    manifest_raw = _canonical_boundary_bytes(manifest)
    checksums_raw = (
        f"{hashlib.sha256(manifest_raw).hexdigest()}  manifest.json\n"
        f"{hashlib.sha256(payload_raw).hexdigest()}  payload.json\n"
    ).encode()
    assets = {
        101: checksums_raw,
        102: manifest_raw,
        103: payload_raw,
    }
    asset_sha256s = {
        "checksums.txt": hashlib.sha256(checksums_raw).hexdigest(),
        "manifest.json": hashlib.sha256(manifest_raw).hexdigest(),
        "payload.json": hashlib.sha256(payload_raw).hexdigest(),
    }
    identity = {
        "byte_length": 2,
        "etag": '"stable"',
        "sha256": hashlib.sha256(b"{}").hexdigest(),
        "updated_at": "2026-07-20T00:00:00Z",
    }

    def stable_get(
        endpoint: str,
        *,
        operation_log: list[dict[str, Any]],
        attempts: int = 3,
        preserve_raw: bool = False,
    ) -> tuple[Any, dict[str, Any]]:
        del operation_log, attempts
        if endpoint == "repos/synaptent/aragora":
            return {
                "full_name": "synaptent/aragora",
                "id": 1126097105,
                "name": "aragora",
            }, identity
        if endpoint.endswith("/branches/main"):
            return {"commit": {"sha": end_sha}, "name": "main"}, identity
        if endpoint.endswith("/branches/main/protection"):
            return {"required_status_checks": {"strict": False}}, identity
        if endpoint.endswith("/immutable-releases"):
            return {"enabled": True}, identity
        if endpoint.endswith("/releases/100"):
            return {
                "assets": [
                    {"id": 101, "name": "checksums.txt"},
                    {"id": 102, "name": "manifest.json"},
                    {"id": 103, "name": "payload.json"},
                ],
                "draft": False,
                "id": 100,
                "immutable": True,
                "prerelease": False,
                "tag_name": capsule_tag,
            }, identity
        if endpoint.endswith(f"/git/ref/tags/{capsule_tag}"):
            return {
                "object": {"sha": end_sha, "type": "commit"},
                "ref": f"refs/tags/{capsule_tag}",
            }, identity
        if endpoint.endswith("/rulesets/rule-suites/987654"):
            payload = _rule_suite_record(end_sha)
            raw = ratchet._canonical_json_bytes(payload).decode("utf-8")
            rule_suite_identity = dict(identity)
            if preserve_raw:
                rule_suite_identity.update(
                    {
                        "byte_length": len(raw.encode("utf-8")),
                        "raw_response": raw,
                        "response_fields": payload,
                        "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                    }
                )
            return payload, rule_suite_identity
        if endpoint.endswith("/pulls/9999"):
            return {
                "additions": 400,
                "base": {"sha": "f" * 40},
                "changed_files": 1,
                "deletions": 400,
                "head": {"sha": end_sha},
                "merge_commit_sha": end_sha,
                "merged_at": "2026-07-20T00:00:00Z",
                "number": 9999,
            }, identity
        if endpoint.endswith(f"/git/commits/{end_sha}"):
            tree_sha = resources["governed_prs"]["records"][0]["head_tree_sha"]
            return {
                "parents": [{"sha": "e" * 40 if wrong_first_parent else start_sha}],
                "sha": end_sha,
                "tree": {"sha": tree_sha},
            }, identity
        raise AssertionError(endpoint)

    def paginated_get(
        endpoint: str,
        *,
        operation_log: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        del operation_log
        if endpoint.endswith("/releases"):
            return [{"id": 100, "tag_name": capsule_tag}], {f"{endpoint}?page=1": identity}
        if endpoint.endswith("/rulesets/rule-suites?ref=refs/heads/main&time_period=day"):
            return [_rule_suite_record(end_sha)], {f"{endpoint}&page=1": identity}
        if endpoint.endswith("/pulls/9999/files"):
            return [{"filename": "fixture.txt", "id": 1}], {f"{endpoint}?page=1": identity}
        raise AssertionError(endpoint)

    def raw_get(
        endpoint: str,
        *,
        operation_log: list[dict[str, Any]],
        attempts: int = 3,
    ) -> tuple[bytes, dict[str, Any]]:
        del operation_log, attempts
        asset_id = int(endpoint.rsplit("/", 1)[1])
        raw = assets[asset_id]
        return raw, {
            "byte_length": len(raw),
            "etag": f'"asset-{asset_id}"',
            "sha256": hashlib.sha256(raw).hexdigest(),
            "updated_at": "2026-07-20T00:00:00Z",
        }

    monkeypatch.setattr(ratchet, "_gh_api_get_stable", stable_get)
    monkeypatch.setattr(ratchet, "_gh_api_paginated", paginated_get)
    monkeypatch.setattr(ratchet, "_gh_api_get_raw_stable", raw_get)
    verification_commands: list[list[str]] = []

    def verify(
        argv: list[str],
        *,
        operation_log: list[dict[str, Any]],
        resource: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        del operation_log
        verification_commands.append(argv)
        if argv[1:3] == ["attestation", "verify"]:
            source_index = argv.index("--source-digest")
            assert argv[source_index + 1] == end_sha
            return {"resource": resource, "verified": bool(argv)}, verification_identity
        return (
            _real_shaped_verification_payload(asset_sha256s, tag=capsule_tag),
            verification_identity,
        )

    monkeypatch.setattr(ratchet, "_run_live_verification", verify)

    if expected_error is not None:
        with pytest.raises(ValueError, match=expected_error):
            ratchet._collect_live_evidence(
                github_repository="synaptent/aragora",
                github_branch="main",
                boundary="corrective_bootstrap",
                start_sha=start_sha,
                end_sha=end_sha,
                repo_root=_repo,
                scratch_root=tmp_path,
                operation_log=[],
            )
        return

    discovered, summary, context = ratchet._collect_live_evidence(
        github_repository="synaptent/aragora",
        github_branch="main",
        boundary="corrective_bootstrap",
        start_sha=start_sha,
        end_sha=end_sha,
        repo_root=_repo,
        scratch_root=tmp_path,
        operation_log=[],
    )

    assert set(discovered) == selected
    assert summary["source"] == "immutable_github_release"
    assert summary["resource_count"] == len(selected)
    assert len(context["asset_identities"]) == 3
    assert any(endpoint.endswith("/pulls/9999") for endpoint in context["endpoint_identities"])
    assert (
        len([argv for argv in verification_commands if argv[1:3] == ["attestation", "verify"]]) == 3
    )
    assert all(
        argv[argv.index("--source-digest") + 1] == end_sha
        for argv, _identity, _resource in context["verification_commands"]
        if argv[1:3] == ["attestation", "verify"]
    )


def test_live_verification_rejects_falsey_json_for_initial_and_replay_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    end_sha = "1" * 40
    commands = (
        [
            "gh",
            "release",
            "verify-asset",
            end_sha,
            str(tmp_path / "asset.json"),
            "-R",
            "synaptent/aragora",
            "--format",
            "json",
        ],
        ratchet._attestation_verify_argv(
            tmp_path / "asset.json",
            github_repository="synaptent/aragora",
            end_sha=end_sha,
        ),
    )
    for raw in (b"null", b"{}", b"[]", b"false", b'""', b"0"):
        monkeypatch.setattr(
            ratchet,
            "_run_read_only",
            lambda argv, **_kwargs: subprocess.CompletedProcess(
                argv,
                0,
                stdout=raw,
                stderr=b"",
            ),
        )
        for argv in commands:
            with pytest.raises(ValueError, match="returned empty verification JSON"):
                ratchet._run_live_verification(
                    argv,
                    operation_log=[],
                    resource="initial-verification",
                )
            context = {
                "asset_identities": {},
                "endpoint_identities": {},
                "github_repository": "synaptent/aragora",
                "local_asset_identities": {},
                "verification_commands": [
                    (
                        argv,
                        {
                            "byte_length": len(raw),
                            "sha256": hashlib.sha256(raw).hexdigest(),
                        },
                        "replay-verification",
                    )
                ],
            }
            with pytest.raises(ValueError, match="returned empty verification JSON"):
                ratchet._reauthenticate_live_context(
                    context,
                    operation_log=[],
                    end_sha=end_sha,
                )


@pytest.mark.parametrize("source_digest", (None, "0" * 40))
def test_live_evidence_replay_rejects_missing_or_wrong_attestation_source_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_digest: str | None,
):
    end_sha = "1" * 40
    argv = [
        "gh",
        "attestation",
        "verify",
        str(tmp_path / "asset.json"),
        "-R",
        "synaptent/aragora",
        "--signer-workflow",
        "synaptent/aragora/.github/workflows/contract-drift-boundary.yml",
        "--format",
        "json",
    ]
    if source_digest is not None:
        argv.extend(["--source-digest", source_digest])
    context = {
        "asset_identities": {},
        "endpoint_identities": {},
        "github_repository": "synaptent/aragora",
        "local_asset_identities": {},
        "verification_commands": [
            (
                argv,
                {"byte_length": 1, "sha256": "2" * 64},
                "sigstore-attestation:asset.json",
            )
        ],
    }
    monkeypatch.setattr(
        ratchet,
        "_run_live_verification",
        lambda *_args, **_kwargs: pytest.fail(
            "hostile replay command must fail before transport execution"
        ),
    )

    with pytest.raises(ValueError, match="source digest"):
        ratchet._reauthenticate_live_context(
            context,
            operation_log=[],
            end_sha=end_sha,
        )


def test_live_release_pagination_runs_to_exhaustion(monkeypatch: pytest.MonkeyPatch):
    requests: list[str] = []

    def stable_get(
        endpoint: str,
        *,
        operation_log: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        del operation_log
        requests.append(endpoint)
        page = int(endpoint.rsplit("page=", 1)[1])
        payload = [{"id": index} for index in range(100)] if page == 1 else [{"id": 100}]
        return payload, {
            "byte_length": page,
            "etag": f'"page-{page}"',
            "sha256": f"{page:064x}",
            "updated_at": None,
        }

    monkeypatch.setattr(ratchet, "_gh_api_get_stable", stable_get)
    records, identities = ratchet._gh_api_paginated(
        "repos/synaptent/aragora/releases",
        operation_log=[],
    )

    assert len(records) == 101
    assert requests == [
        "repos/synaptent/aragora/releases?per_page=100&page=1",
        "repos/synaptent/aragora/releases?per_page=100&page=2",
    ]
    assert set(identities) == set(requests)


def test_stage2_inner_rerun_uses_process_lock():
    assert "_stage1_rerun_lock" in inspect.getsource(test_stage2_reruns_full_stage1_matrix)


@contextlib.contextmanager
def _stage1_rerun_lock():
    lock_path = Path(tempfile.gettempdir()) / "aragora-cdg-stage1-rerun.lock"
    with lock_path.open("a+b") as lock:
        if sys.platform == "win32":
            lock.write(b"\0")
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if sys.platform == "win32":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def test_stage2_reruns_full_stage1_matrix():
    stage1_names = {
        "test_all_loaded_repository_modules_are_under_exact_ref_extraction_root",
        "test_authority_roots_are_tier4",
        "test_canonical_tier_cli_is_read_only_and_digest_bound",
        "test_classifier_and_merge_train_closure_match",
        "test_deterministic_bounded_authority_dependency_closure_has_incoming_edges_and_exact_ref_digests",
        "test_local_reusable_workflows_and_composite_actions_join_closure",
        "test_measured_sdk_handler_openapi_subjects_are_not_authority_dependencies",
        "test_merge_train_mirror_is_normal_repo_file_authority_member",
        "test_standalone_classifier_extracts_and_calls_exact_ref_canonical_review_queue_policy_under_I_S",
        "test_workflows_yml_and_yaml_recurse_through_structural_run_uses_and_path_filters",
    }
    assert ratchet.STAGE1_REQUIRED_TESTS == tuple(sorted(stage1_names))
    repo = Path(ratchet.__file__).resolve().parents[1]
    with _stage1_rerun_lock():
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *ratchet.STAGE1_TEST_MATRIX, "-q"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_read_only_cli_hashes_worktree_index_gitdirs_objects_refs_and_reflogs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, _start_sha, _boundary_shas = _boundary_git_repo(tmp_path)
    operation_log: list[dict[str, Any]] = []
    calls: list[tuple[Path, frozenset[str]]] = []
    original_path_manifest = ratchet._path_manifest

    def recording_path_manifest(
        path: Path,
        *,
        content: bool,
        exclude_top_level: frozenset[str] = frozenset(),
    ) -> bytes:
        calls.append((path.resolve(), exclude_top_level))
        return original_path_manifest(
            path,
            content=content,
            exclude_top_level=exclude_top_level,
        )

    monkeypatch.setattr(ratchet, "_path_manifest", recording_path_manifest)
    snapshot = ratchet._snapshot_repository(repo, operation_log)
    assert set(snapshot) == {
        "common_git_dir",
        "index",
        "object_database",
        "refs",
        "reflogs",
        "worktree",
        "worktree_git_dir",
    }
    assert all(
        isinstance(value["sha256"], str) and len(value["sha256"]) == 64
        for value in snapshot.values()
    )
    assert operation_log

    git_dir = Path(
        subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-dir"],
            text=True,
        ).strip()
    ).resolve()
    common_dir = Path(
        subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            text=True,
        ).strip()
    ).resolve()
    assert git_dir == common_dir
    expected_excludes = frozenset({"logs", "objects", "refs", "worktrees"})
    assert [excludes for path, excludes in calls if path == git_dir].count(expected_excludes) == 2

    fake_common = tmp_path / "fake-common"
    fake_common.mkdir()
    metadata = fake_common / "config"
    metadata.write_text("metadata=v1\n", encoding="utf-8")
    for subtree in expected_excludes:
        child = fake_common / subtree / "nested"
        child.mkdir(parents=True)
        (child / "separately-captured").write_bytes(b"before")
    before = original_path_manifest(
        fake_common,
        content=True,
        exclude_top_level=expected_excludes,
    )
    for subtree in expected_excludes:
        (fake_common / subtree / "nested" / "separately-captured").write_bytes(b"after")
    after_common_mutation = original_path_manifest(
        fake_common,
        content=True,
        exclude_top_level=expected_excludes,
    )
    assert after_common_mutation == before
    metadata.write_text("metadata=v2\n", encoding="utf-8")
    after_metadata_mutation = original_path_manifest(
        fake_common,
        content=True,
        exclude_top_level=expected_excludes,
    )
    assert after_metadata_mutation != before

    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "--detach", str(linked), "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    calls.clear()
    linked_before = ratchet._snapshot_repository(linked, [])
    linked_git_dir = Path(
        subprocess.check_output(
            ["git", "-C", str(linked), "rev-parse", "--path-format=absolute", "--git-dir"],
            text=True,
        ).strip()
    ).resolve()
    assert linked_git_dir != common_dir
    linked_excludes = [excludes for path, excludes in calls if path == linked_git_dir]
    assert linked_excludes == [frozenset()]
    linked_entries = json.loads(
        original_path_manifest(
            linked_git_dir,
            content=True,
            exclude_top_level=linked_excludes[0],
        )
    )
    linked_paths = {entry["path"] for entry in linked_entries}
    assert {"HEAD", "commondir", "gitdir", "index"} <= linked_paths
    (linked_git_dir / "verifier-sentinel").write_bytes(b"linked metadata changed")
    linked_after = ratchet._snapshot_repository(linked, [])
    assert linked_after["worktree_git_dir"] != linked_before["worktree_git_dir"]
    assert {name: value for name, value in linked_after.items() if name != "worktree_git_dir"} == {
        name: value for name, value in linked_before.items() if name != "worktree_git_dir"
    }


def test_read_only_cli_allows_only_scratch_and_output_writes(tmp_path: Path):
    scratch = tmp_path / "scratch"
    output = tmp_path / "output"
    ratchet._guard_write_path(scratch / "child.json", scratch, output)
    ratchet._guard_write_path(output / "manifest.json", scratch, output)
    with pytest.raises(ValueError, match="outside"):
        ratchet._guard_write_path(tmp_path / "escape.json", scratch, output)


def test_read_only_cli_is_deterministic_across_double_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    first = _boundary_result(tmp_path, monkeypatch, "extended_sdk")
    repo = tmp_path / "boundary-repo"
    start_sha = first["start_sha"]
    end_sha = first["end_sha"]
    second = ratchet.build_boundary_result(
        repo_root=repo,
        schema_version=1,
        boundary="extended_sdk",
        start_ref=start_sha,
        end_ref=end_sha,
    )
    assert ratchet._canonical_json_bytes(first) == ratchet._canonical_json_bytes(second)


def test_read_only_cli_preserves_etag_and_updated_at():
    before = {"etag": '"stable"', "updated_at": "2026-07-20T00:00:00Z"}
    after = copy.deepcopy(before)
    assert ratchet._remote_identity_moved(before, after) is False
    after["etag"] = '"moved"'
    assert ratchet._remote_identity_moved(before, after) is True


def test_read_only_cli_retries_or_blocks_on_concurrent_mutation():
    calls = 0

    def probe() -> tuple[dict[str, str], dict[str, str]]:
        nonlocal calls
        calls += 1
        before = {"etag": f'"{calls}"', "updated_at": "2026-07-20T00:00:00Z"}
        after = dict(before)
        if calls < 3:
            after["etag"] = '"moved"'
        return before, after

    before, after = ratchet._retry_stable_remote_probe(probe, attempts=3)
    assert calls == 3
    assert before == after

    with pytest.raises(ratchet.BoundaryBlocked, match="moved"):
        ratchet._retry_stable_remote_probe(
            lambda: ({"etag": '"a"'}, {"etag": '"b"'}),
            attempts=2,
        )


def test_read_only_cli_rejects_mutating_http_verbs():
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(ValueError, match="mutating HTTP"):
            ratchet._guard_http_method(method)
    ratchet._guard_http_method("GET")
    ratchet._guard_http_method("HEAD")


def test_read_only_cli_rejects_mutating_git_and_subprocess_actions():
    for argv in (
        ["git", "merge", "main"],
        ["git", "push", "origin", "HEAD"],
        ["git", "config", "user.name", "unsafe"],
        ["git", "-c", "diff.context=3", "merge", "main"],
        ["git", "-c"],
        ["gh", "pr", "merge", "1"],
        ["gh", "run", "rerun", "1"],
        ["gh", "release", "upload", "tag", "asset"],
        ["gh", "api", "-XPOST", "repos/o/r"],
        ["gh", "api", "-f", "key=value", "repos/o/r"],
    ):
        with pytest.raises(ValueError, match="mutating|unsupported"):
            ratchet._guard_subprocess_argv(argv)
    ratchet._guard_subprocess_argv(["git", "status", "--porcelain=v1"])
    ratchet._guard_subprocess_argv(["git", "-c", "diff.context=3", "diff", "HEAD^", "HEAD"])
    ratchet._guard_subprocess_argv(["gh", "api", "--method", "GET", "repos/o/r"])


def test_read_only_git_guard_rejects_command_executing_config_pairs():
    # Inline `-c` bypasses the GIT_CONFIG_GLOBAL/NOSYSTEM scrub, and keys such
    # as core.fsmonitor / diff.external / core.pager execute attacker-chosen
    # commands even under read-only subcommands.
    for argv in (
        ["git", "-c", "core.fsmonitor=/tmp/evil", "status", "--porcelain=v1"],
        ["git", "-c", "diff.external=/tmp/evil", "diff", "HEAD^", "HEAD"],
        ["git", "-c", "core.pager=/tmp/evil", "log"],
    ):
        with pytest.raises(ValueError, match="unsupported git -c configuration"):
            ratchet._guard_subprocess_argv(argv)


def test_read_only_git_guard_config_allowlist_is_fail_closed():
    # Only the exact call-site key=value literals pass: an allowlisted key
    # with a different value, unknown keys, and case variants are all
    # rejected rather than falling through to the subcommand allowlist.
    for pair in (
        "diff.context=99",
        "diff.algorithm=patience",
        "diff.noprefix=true",
        "credential.helper=!/tmp/evil",
        "core.sshCommand=/tmp/evil",
        "Diff.Context=3",
        "diff.context",
        "",
    ):
        with pytest.raises(ValueError, match="unsupported git -c configuration"):
            ratchet._guard_subprocess_argv(["git", "-c", pair, "status", "--porcelain=v1"])


def test_read_only_git_guard_accepts_exact_call_site_patch_argv(tmp_path: Path):
    # The exact argv shape built by the historical-receipt patch call sites.
    argv = [
        "git",
        "-c",
        "diff.noprefix=false",
        "-c",
        "diff.mnemonicPrefix=false",
        "-c",
        "diff.algorithm=myers",
        "-c",
        "diff.context=3",
        "-C",
        str(tmp_path),
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--no-color",
        "--no-indent-heuristic",
        "--full-index",
        "--unified=3",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "-O/dev/null",
        "base^{tree}",
        "head^{tree}",
    ]
    ratchet._guard_subprocess_argv(argv)
    assert ratchet._git_subcommand(argv) == "diff"


def test_read_only_git_config_literal_allowlist_matches_call_sites():
    assert ratchet._READ_ONLY_GIT_CONFIG_LITERALS == frozenset(
        {
            "diff.algorithm=myers",
            "diff.context=3",
            "diff.mnemonicPrefix=false",
            "diff.noprefix=false",
        }
    )


def test_read_only_git_guard_rejects_config_env_joined_form():
    # --config-env=<name>=<envvar> is git's environment-sourced equivalent of
    # -c (including command-executing keys) and slips past the generic option
    # skip as a plain "--" token, bypassing the -c allowlist entirely.
    for argv in (
        ["git", "--config-env=core.pager=EVIL_PAGER", "log"],
        ["git", "--config-env=core.fsmonitor=EVIL_MONITOR", "status", "--porcelain=v1"],
        ["git", "--config-env=diff.external=EVIL_DIFF", "diff", "HEAD^", "HEAD"],
    ):
        with pytest.raises(ValueError, match="config-env"):
            ratchet._guard_subprocess_argv(argv)


def test_read_only_git_guard_rejects_config_env_separate_form():
    # The two-token spelling must be rejected as --config-env fail-closed, not
    # merely misclassified when its value token falls through as a subcommand.
    for argv in (
        ["git", "--config-env", "core.pager=EVIL_PAGER", "log"],
        ["git", "--config-env", "diff.external=EVIL_DIFF", "diff", "HEAD^", "HEAD"],
        ["git", "--config-env", "core.fsmonitor=EVIL_MONITOR", "rev-parse", "HEAD"],
    ):
        with pytest.raises(ValueError, match="config-env"):
            ratchet._guard_subprocess_argv(argv)


def test_read_only_git_scrubs_config_without_scrubbing_gh(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append((argv, kwargs["env"]))
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/hostile/global")
    monkeypatch.delenv("GIT_CONFIG_NOSYSTEM", raising=False)
    monkeypatch.setattr(ratchet.subprocess, "run", fake_run)
    ratchet._run_read_only(
        ["git", "status", "--porcelain=v1"],
        operation_log=[],
        resource="git-status",
    )
    ratchet._run_read_only(
        ["gh", "api", "--method", "GET", "repos/o/r"],
        operation_log=[],
        resource="github-api",
    )
    git_env = calls[0][1]
    assert git_env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert git_env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert git_env["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert git_env["LC_ALL"] == "C"
    gh_env = calls[1][1]
    assert gh_env["GIT_CONFIG_GLOBAL"] == "/hostile/global"
    assert "GIT_CONFIG_NOSYSTEM" not in gh_env


def _accepted_authority() -> dict[str, Any]:
    path = Path(ratchet.__file__).parent / "baselines/contract_drift_inventory.json"
    return json.loads(path.read_text())["accepted_authority"]


def _accepted_authority_at_ref(
    ref: str,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    if repo_root is None:
        repo_root = Path(ratchet.__file__).resolve().parents[1]
    document = ratchet._git_json(repo_root, ref, gen.DEFAULT_INVENTORY)
    authority = document.get("accepted_authority")
    assert isinstance(authority, dict)
    return authority


def _git_text(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
    ).strip()


def _git_bytes(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def _commit_record(repo: Path, oid: str) -> dict[str, Any]:
    body = _git_text(repo, "cat-file", "commit", oid)
    headers, _, message = body.partition("\n\n")
    tree = ""
    parents: list[str] = []
    committed_at = -1
    for line in headers.splitlines():
        key, _, value = line.partition(" ")
        if key == "tree":
            tree = value
        elif key == "parent":
            parents.append(value)
        elif key == "committer":
            committed_at = int(value.rsplit(" ", 2)[-2])
    assert tree and committed_at >= 0
    return {
        "oid": oid,
        "tree": tree,
        "parents": tuple(parents),
        "committed_at": committed_at,
        "subject": message.splitlines()[0],
    }


def _object_ids(repo: Path, kind: str) -> tuple[str, ...]:
    records = _git_text(
        repo,
        "cat-file",
        "--batch-all-objects",
        "--batch-check=%(objectname) %(objecttype)",
    ).splitlines()
    return tuple(sorted(line.split()[0] for line in records if line.split()[1] == kind))


def _decision_351_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "decision-351-evidence"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for pack_path, expected_sha256 in (
        (_DECISION_351_PACK, _EXPECTED_DECISION_351_PACK_SHA256),
        (_REAL_NEXT_EVENT_PACK, _EXPECTED_REAL_NEXT_EVENT_PACK_SHA256),
    ):
        pack = pack_path.read_bytes()
        assert hashlib.sha256(pack).hexdigest() == expected_sha256
        subprocess.run(
            ["git", "-C", str(repo), "index-pack", "--stdin"],
            input=pack,
            check=True,
            capture_output=True,
        )
    return repo


def _decision_351_facts(repo: Path) -> dict[str, dict[str, Any]]:
    commits = {oid: _commit_record(repo, oid) for oid in _object_ids(repo, "commit")}
    missing_parents = {
        parent
        for record in commits.values()
        for parent in record["parents"]
        if parent not in commits
    }
    h3_candidates = [
        record
        for record in commits.values()
        if len(record["parents"]) == 1
        and record["parents"][0] in commits
        and len(commits[record["parents"][0]]["parents"]) == 1
        and commits[record["parents"][0]]["parents"][0] in commits
        and len(commits[commits[record["parents"][0]]["parents"][0]]["parents"]) == 2
    ]
    assert len(h3_candidates) == 1
    h3 = h3_candidates[0]
    assert len(h3["parents"]) == 1
    h2 = commits[h3["parents"][0]]
    assert len(h2["parents"]) == 1
    h1 = commits[h2["parents"][0]]
    assert len(h1["parents"]) == 2
    base = commits[h1["parents"][1]]

    h4_candidates = [
        record
        for record in commits.values()
        if record["parents"] == (h3["oid"],) and record["tree"] == h3["tree"]
    ]
    assert len(h4_candidates) == 1
    h4 = h4_candidates[0]

    absorption_candidates = [
        record
        for record in commits.values()
        if len(record["parents"]) == 2 and record["parents"][0] == h4["oid"]
    ]
    assert len(absorption_candidates) == 1
    absorption = absorption_candidates[0]
    repin = commits[absorption["parents"][1]]
    assert set(repin["parents"]) <= missing_parents

    merge_candidates = [
        record
        for record in commits.values()
        if record["parents"] == (repin["oid"],) and record["tree"] == absorption["tree"]
    ]
    assert len(merge_candidates) == 1
    return {
        "base": base,
        "h1": h1,
        "h2": h2,
        "h3": h3,
        "repin": repin,
        "h4": h4,
        "absorption": absorption,
        "merge": merge_candidates[0],
    }


def _genesis_authority(authority: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct the all-active genesis form of the accepted authority.

    The committed authority now carries the serve-side catch-up paydown
    (257 resolved records). Truncating every disposition history back to the
    genesis event reproduces the exact pre-paydown base, letting tests
    exercise the paydown comparison against the real committed head.
    """
    genesis = copy.deepcopy(authority)
    for item in genesis["active_inventory"]:
        item["status"] = "active"
        item["disposition_history"] = [dict(ratchet.GENESIS_DISPOSITION)]
    genesis["active_inventory_sha256"] = ratchet._sha256_bytes(
        ratchet._canonical_json_bytes(genesis["active_inventory"])
    )
    manifest = {key: value for key, value in genesis.items() if key != "manifest_sha256"}
    genesis["manifest_sha256"] = ratchet._sha256_bytes(ratchet._canonical_json_bytes(manifest))
    return genesis


def _paydown_waves(authority: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """Group the committed paydown into digest-bound waves, in replay order.

    Every resolved record's final event binds the active set it leaves behind,
    so the records sharing one digest form a wave and the waves chain from
    genesis: a wave is next exactly when its digest equals the digest of the
    remaining set minus its own ids. Returns ``(digest, sorted ids)`` pairs.
    """
    waves: dict[str, list[str]] = {}
    as_of_by_digest: dict[str, str] = {}
    for item in authority["active_inventory"]:
        last = item["disposition_history"][-1]
        if item["status"] == "active":
            assert len(item["disposition_history"]) == 1
            continue
        assert item["status"] == "resolved" and last["status"] == "resolved"
        digest = last["evidence"]["fact"]["active_original_record_ids_sha256"]
        waves.setdefault(digest, []).append(item["original_record_id"])
        as_of_by_digest.setdefault(digest, last["as_of"])
        assert as_of_by_digest[digest] == last["as_of"]
    remaining = {item["original_record_id"] for item in authority["active_inventory"]}
    replayed: list[tuple[str, list[str]]] = []
    while waves:
        bound = [
            digest
            for digest, ids in waves.items()
            if ratchet._sha256_bytes(ratchet._canonical_json_bytes(sorted(remaining - set(ids))))
            == digest
        ]
        assert len(bound) == 1, "paydown wave is not bound to the active set it leaves"
        ids = sorted(waves.pop(bound[0]))
        remaining -= set(ids)
        replayed.append((bound[0], ids))
    dates = [as_of_by_digest[digest] for digest, _ids in replayed]
    assert dates == sorted(dates), "paydown waves replay out of chronological order"
    return replayed


def _replay_committed_paydown(
    authority: dict[str, Any], *, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[str, list[str]]]:
    """Replay the committed paydown through the production comparator.

    ``compare_accepted_authorities`` binds the appended events of one head to
    that head's live digest, so a multi-wave authority is judged one wave at a
    time: wave k's base carries waves < k and its head carries waves <= k,
    each validated against the baseline witnesses of its own moment. Those
    witnesses are the committed baselines plus the cohort literals of every
    later wave, served through ``load_git_docs`` under synthetic refs; the
    analyzer bundle is still checked against the real tree.
    """
    waves = _paydown_waves(authority)
    records = {
        record["original_record_id"]: record
        for record in authority["canonical_artifacts"]["original_cohort"]["original_records"]
    }
    alias_of = {
        list_key: alias for alias, (_p, keys) in gen.BASELINE_SPECS.items() for list_key in keys
    }
    committed_docs = gen.load_working_docs(repo_root)
    docs_by_ref: dict[str, dict[str, Any]] = {}
    for index in range(len(waves) + 1):
        docs = copy.deepcopy(committed_docs)
        for _digest, ids in waves[index:]:
            for record_id in ids:
                record = records[record_id]
                docs[alias_of[record["source_json_key"]]][record["source_json_key"]].append(
                    record["exact_historical_literal_record"]
                )
        docs_by_ref[f"wave-{index}"] = docs

    def fake_git_docs(root: Path, ref: str) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(docs_by_ref[ref])

    real_validate_bundle = ratchet._validate_bundle
    monkeypatch.setattr(ratchet.inventory_mod, "load_git_docs", fake_git_docs)
    monkeypatch.setattr(
        ratchet, "_validate_bundle", lambda auth, root, ref=None: real_validate_bundle(auth, root)
    )
    committed = {item["original_record_id"]: item for item in authority["active_inventory"]}
    previous = _genesis_authority(authority)
    for index, (_digest, ids) in enumerate(waves, start=1):
        applied = {record_id for _d, wave_ids in waves[:index] for record_id in wave_ids}
        head = copy.deepcopy(previous)
        head["active_inventory"] = [
            copy.deepcopy(committed[item["original_record_id"]])
            if item["original_record_id"] in applied
            else item
            for item in head["active_inventory"]
        ]
        head["active_inventory_sha256"] = ratchet._sha256_bytes(
            ratchet._canonical_json_bytes(head["active_inventory"])
        )
        _relink_authority_manifest(head)
        compared = ratchet.compare_accepted_authorities(
            previous,
            head,
            repo_root=repo_root,
            base_ref=f"wave-{index - 1}",
            head_ref=f"wave-{index}",
        )
        assert (compared["passing"], compared["status"]) == (True, "pass")
        assert compared["added_original_record_ids"] == []
        assert compared["removed_original_record_ids"] == ids
        previous = head
    assert previous == authority
    return waves


def test_accepted_authority_keeps_genesis_and_reconciles_live_witnesses(
    monkeypatch: pytest.MonkeyPatch,
):
    authority, root = _accepted_authority(), Path(ratchet.__file__).parents[1]
    summary = ratchet.validate_accepted_authority(authority, repo_root=root)
    assert (summary["original_record_total"], summary["sdk_provenance_record_total"]) == (655, 598)
    assert (len(summary["active_original_record_ids"]), len(summary["live_original_record_ids"])) == (288, 288)  # fmt: skip
    # The committed authority equals the genesis authority plus the digest-bound
    # paydown waves (255 historical + the 2 VAL-CDG-016 serve-side literals,
    # then 59 TypeScript and 51 SDK literals): 367 resolved records, each wave
    # passing the production comparator against the wave before it.
    genesis = _genesis_authority(authority)
    genesis_summary = ratchet.validate_accepted_authority(genesis, repo_root=root)
    assert len(genesis_summary["active_original_record_ids"]) == 655
    waves = _replay_committed_paydown(authority, repo_root=root, monkeypatch=monkeypatch)
    assert [len(ids) for _digest, ids in waves] == [257, 59, 51]
    removed = sorted(record_id for _digest, ids in waves for record_id in ids)
    assert removed == sorted(
        set(genesis_summary["active_original_record_ids"])
        - set(summary["active_original_record_ids"])
    )
    live_digest = ratchet._sha256_bytes(
        ratchet._canonical_json_bytes(sorted(summary["live_original_record_ids"]))
    )
    assert waves[-1][0] == live_digest


def test_accepted_authority_rejects_unbound_paydown_and_bundle():
    authority = _accepted_authority()
    item = authority["active_inventory"][0]
    item.update(status="resolved", disposition_history=[ratchet.GENESIS_DISPOSITION, {"as_of": "2026-07-27", "evidence": {}, "status": "resolved"}])  # fmt: skip
    with pytest.raises(ValueError, match="paydown"):
        ratchet.validate_accepted_authority(authority, repo_root=Path(ratchet.__file__).parents[1])
    authority = _accepted_authority()
    authority["analyzer_bundle"]["files"].pop()
    with pytest.raises(ValueError, match="file set"):
        ratchet._bundle_metadata(authority)


def test_accepted_authority_rejects_bundle_evolution(monkeypatch):
    authority, changed = _accepted_authority(), _accepted_authority()
    changed["analyzer_bundle"]["interpreter_flags"] = ["-I", "-S"]
    monkeypatch.setattr(ratchet, "validate_accepted_authority", lambda *args, **kwargs: {})
    with pytest.raises(ValueError, match="immutable authority bindings"):
        ratchet.compare_accepted_authorities(authority, changed, repo_root=Path("."))


def _residue_fixture(root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]], str]:
    authority = _accepted_authority()
    records = authority["canonical_artifacts"]["original_cohort"]["original_records"]
    original = {f"{r['source_json_key']}:{gen.normalize_key(r['exact_historical_literal_record'])}" for r in records}  # fmt: skip
    docs = gen.load_working_docs(root)
    ids = set(gen.collect_ids(docs))
    # Orphan reconciliation PR-1 emptied missing_in_spec, exhausting in-repo
    # residue candidates; synthesize an outside-cohort entry so the residue
    # freeze mechanics stay covered hermetically (refs are faked below).
    entry = "/api/v1/__residue-tolerance-fixture__"
    assert f"missing_in_spec:{gen.normalize_key(entry)}" not in original
    assert f"missing_in_spec:{entry}" not in ids and f"orphaned_in_spec:{entry}" not in ids
    docs["routes"]["missing_in_spec"].append(entry)
    return authority, docs, entry


def test_live_residue_is_frozen_shrink_only_against_tolerance_ref(monkeypatch):
    root = Path(ratchet.__file__).parents[1]
    authority, base_docs, entry = _residue_fixture(root)
    head_docs = copy.deepcopy(base_docs)
    head_docs["routes"]["missing_in_spec"].remove(entry)
    by_ref = {"tolerance-ref": base_docs, "candidate-ref": head_docs}

    def fake_git_docs(repo_root: Path, ref: str) -> dict[str, dict[str, Any]]:
        if ref not in by_ref:
            raise subprocess.CalledProcessError(128, ["git", "rev-parse", ref])
        return copy.deepcopy(by_ref[ref])

    monkeypatch.setattr(ratchet.inventory_mod, "load_git_docs", fake_git_docs)
    kwargs = {"repo_root": root, "live_ref": "candidate-ref", "residue_ref": "tolerance-ref"}
    removal_live = ratchet._live_witnesses(authority, **kwargs)
    equal_live = ratchet._live_witnesses(authority, repo_root=root, live_ref="tolerance-ref", residue_ref="tolerance-ref")  # fmt: skip
    assert removal_live == equal_live and len(equal_live) == 288
    head_docs["routes"]["missing_in_spec"].append(f"{entry}/guard-v2-new")
    with pytest.raises(ValueError, match="new live baseline keys outside immutable original cohort") as one_new:  # fmt: skip
        ratchet._live_witnesses(authority, **kwargs)
    assert f"missing_in_spec:{entry}/guard-v2-new" in str(one_new.value)
    head_docs["routes"]["missing_in_spec"].remove(f"{entry}/guard-v2-new")
    head_docs["routes"]["orphaned_in_spec"].append(entry)
    with pytest.raises(ValueError, match="new live baseline keys outside immutable original cohort") as flipped:  # fmt: skip
        ratchet._live_witnesses(authority, **kwargs)
    assert f"orphaned_in_spec:{gen.normalize_key(entry)}" in str(flipped.value)
    with pytest.raises(ValueError, match="lack a residue tolerance ref"):
        ratchet._live_witnesses(authority, repo_root=root, live_ref="candidate-ref", residue_ref=None)  # fmt: skip
    with pytest.raises(ValueError, match="residue tolerance ref is unavailable"):
        ratchet._live_witnesses(authority, repo_root=root, live_ref="tolerance-ref", residue_ref="0" * 40)  # fmt: skip


def test_residue_tolerance_refs_bind_event_base_and_first_parent(monkeypatch):
    calls: list[tuple[str | None, str | None]] = []

    def fake_validate(authority: dict[str, Any], *, repo_root: Path, live_ref: str | None = None, residue_ref: str | None = None) -> dict[str, Any]:  # fmt: skip
        calls.append((live_ref, residue_ref))
        return {"active_original_record_ids": [], "analyzer_bundle_sha256": "", "live_original_record_ids": []}  # fmt: skip

    monkeypatch.setattr(ratchet, "validate_accepted_authority", fake_validate)
    root = Path(ratchet.__file__).parents[1]
    ratchet.compare_accepted_authorities(_accepted_authority(), _accepted_authority(), repo_root=root, base_ref="base-sha", head_ref="head-sha")  # fmt: skip
    source = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
    parent = subprocess.run(["git", "-C", str(root), "rev-parse", f"{source}^"], capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
    ratchet.build_accepted_result(mode="receipt", repo_root=root, inventory_path=root / "scripts/baselines/contract_drift_inventory.json", source_sha=source)  # fmt: skip
    assert calls == [("base-sha", "base-sha"), ("head-sha", "base-sha"), (source, parent)]


def test_real_h2_h3_pair_tolerates_all_483_inherited_residue_keys(tmp_path: Path):
    root = _decision_351_repo(tmp_path)
    facts = _decision_351_facts(root)
    authority = _accepted_authority_at_ref(facts["h3"]["oid"], repo_root=root)
    records = authority["canonical_artifacts"]["original_cohort"]["original_records"]
    original_keys = {
        f"{record['source_json_key']}:{gen.normalize_key(record['exact_historical_literal_record'])}"
        for record in records
    }
    h2_residue = ratchet._outside_cohort_residue(root, facts["h2"]["oid"], original_keys)
    h3_residue = ratchet._outside_cohort_residue(root, facts["h3"]["oid"], original_keys)
    assert h2_residue == h3_residue
    assert len(h3_residue) == 483
    live = ratchet._live_witnesses(
        authority,
        repo_root=root,
        live_ref=facts["h3"]["oid"],
        residue_ref=facts["h2"]["oid"],
    )
    assert len(live) == 400


def test_real_h2_residue_fixture_rejects_new_and_rekeyed_keys_but_allows_removal(
    tmp_path: Path,
):
    root = _decision_351_repo(tmp_path)
    facts = _decision_351_facts(root)
    authority = _accepted_authority_at_ref(facts["h3"]["oid"], repo_root=root)
    records = authority["canonical_artifacts"]["original_cohort"]["original_records"]
    original_keys = {
        f"{record['source_json_key']}:{gen.normalize_key(record['exact_historical_literal_record'])}"
        for record in records
    }
    h2_docs = gen.load_git_docs(root, facts["h2"]["oid"])
    h2_ids = set(gen.collect_ids(h2_docs))
    repo = tmp_path / "real-h2-residue"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _write_docs(repo, h2_docs)
    base = _commit(repo, "real H2 baseline bytes")

    removed_docs = copy.deepcopy(h2_docs)
    residue_entry = next(
        entry
        for entry in removed_docs["routes"]["missing_in_spec"]
        if f"missing_in_spec:{gen.normalize_key(entry)}" not in original_keys
        and f"orphaned_in_spec:{gen.normalize_key(entry)}" not in h2_ids
    )
    removed_docs["routes"]["missing_in_spec"].remove(residue_entry)
    _write_docs(repo, removed_docs)
    removal = _commit(repo, "remove inherited residue")
    removal_live = ratchet._live_witnesses(
        authority,
        repo_root=repo,
        live_ref=removal,
        residue_ref=base,
    )
    assert len(removal_live) == 400

    new_docs = copy.deepcopy(h2_docs)
    new_entry = "/api/v1/__guard-v2-reference-closure-new__"
    new_docs["routes"]["missing_in_spec"].append(new_entry)
    _write_docs(repo, new_docs)
    new_ref = _commit(repo, "add new residue")
    with pytest.raises(
        ValueError,
        match="new live baseline keys outside immutable original cohort",
    ) as added:
        ratchet._live_witnesses(
            authority,
            repo_root=repo,
            live_ref=new_ref,
            residue_ref=base,
        )
    assert (
        str(added.value) == "new live baseline keys outside immutable original cohort versus "
        f"{base}: ['missing_in_spec:{new_entry}']"
    )

    rekeyed_docs = copy.deepcopy(h2_docs)
    rekeyed_docs["routes"]["missing_in_spec"].remove(residue_entry)
    rekeyed_docs["routes"]["orphaned_in_spec"].append(residue_entry)
    _write_docs(repo, rekeyed_docs)
    rekeyed_ref = _commit(repo, "re-key inherited residue")
    with pytest.raises(
        ValueError,
        match="new live baseline keys outside immutable original cohort",
    ) as rekeyed:
        ratchet._live_witnesses(
            authority,
            repo_root=repo,
            live_ref=rekeyed_ref,
            residue_ref=base,
        )
    assert (
        str(rekeyed.value) == "new live baseline keys outside immutable original cohort versus "
        f"{base}: ['orphaned_in_spec:{gen.normalize_key(residue_entry)}']"
    )


def _run_accepted_cli(
    repo: Path,
    *,
    mode: str,
    source_ref: str | None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    command = [
        sys.executable,
        str(Path(ratchet.__file__)),
        "--mode",
        mode,
        "--repo-root",
        str(repo),
        "--inventory",
        gen.DEFAULT_INVENTORY,
        "--json",
    ]
    if mode == "program":
        command.extend(["--as-of", "2026-04-17", "--strict"])
    if source_ref is not None:
        command.extend(["--ref", source_ref])
    env = {**os.environ}
    env.pop("CDG_AUTHORITY_ROOT", None)
    proc = subprocess.run(
        command,
        cwd=repo,
        capture_output=True,
        env=env,
        text=True,
    )
    return proc, json.loads(proc.stdout)


@pytest.mark.parametrize("mode", ["program", "receipt"])
def test_accepted_main_modes_require_explicit_immutable_ref(
    tmp_path: Path,
    mode: str,
):
    repo, _base, _head = _hermetic_repo(tmp_path)
    proc, result = _run_accepted_cli(repo, mode=mode, source_ref=None)
    assert proc.returncode == 1
    assert result["status"] == "fail" and result["passing"] is False
    assert result["error_code"] == "accepted_authority_ref_required"
    assert "--ref" in result["error"]


@pytest.mark.parametrize("mode", ["program", "receipt"])
def test_accepted_main_modes_reject_malformed_unresolvable_and_noncommit_refs(
    tmp_path: Path,
    mode: str,
):
    repo, base, head = _hermetic_repo(tmp_path)
    tree = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", f"{head}^{{tree}}"],
        text=True,
    ).strip()
    hostile_refs = ("HEAD", head[:12], head.upper(), "0" * 40, tree, base)
    for source_ref in hostile_refs:
        proc, result = _run_accepted_cli(repo, mode=mode, source_ref=source_ref)
        assert proc.returncode == 1, source_ref
        assert result["status"] == "fail" and result["passing"] is False
        assert result["error_code"] == "accepted_authority_ref_invalid"
        assert "--ref" in result["error"] or "first parent" in result["error"]


@pytest.mark.parametrize("mode", ["program", "receipt"])
def test_accepted_main_modes_bind_non_head_ref_and_ignore_dirty_worktree_authority(
    tmp_path: Path,
    mode: str,
):
    repo, _base, source = _hermetic_repo(tmp_path)
    (repo / "later.txt").write_text("later commit\n", encoding="utf-8")
    later = _commit(repo, "later")
    assert source != later
    (repo / gen.DEFAULT_INVENTORY).write_text(
        '{"accepted_authority":"ambient-hostile"}\n',
        encoding="utf-8",
    )
    (repo / "scripts/baselines/contract_drift_program.json").write_text(
        '{"start_date":"2099-01-01","start_total_items":0,'
        '"weekly_reduction":0.5,"grace_weeks":0}\n',
        encoding="utf-8",
    )
    for _alias, (rel_path, _keys) in gen.BASELINE_SPECS.items():
        (repo / rel_path).write_text("{}\n", encoding="utf-8")
    proc, result = _run_accepted_cli(repo, mode=mode, source_ref=source)
    assert proc.returncode == 0, proc.stderr
    assert result["status"] == "pass" and result["passing"] is True
    if mode == "program":
        assert result["program"]["source_sha"] == source
        assert result["program"]["start_date"] == "2026-04-17"
        assert result["current"]["total_items"] == 288
    else:
        assert result["source_sha"] == source
        assert result["authority"]["first_parent_chain"][0] == source


# ------------------------- VAL-CDG-005 (pr side): file evidence and growth


def _governed_pr_resource(start_sha: str, end_sha: str, **overrides: Any) -> dict[str, Any]:
    record = {
        "base_sha": start_sha,
        "changed_files_complete": True,
        "head_sha": end_sha,
        "head_tree_sha": "d" * 40,
        "pr": 9999,
        **overrides,
    }
    return {
        "boundary": "corrective_bootstrap",
        "end_sha": end_sha,
        "records": [record],
        "schema": "contract-drift-governed-prs-v1",
        "start_sha": start_sha,
    }


def _live_pr_files_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    files_count: int = 1,
    changed_files: int | None = None,
    pr_additions: int = 400,
    pr_deletions: int = 400,
    duplicate_file_ids: bool = False,
    files_link_header: str | None = None,
    mutate: Any | None = None,
    releases_payload: Any | None = None,
    tag_ref_object: Any | None = None,
    annotated_tag_object: Any | None = None,
    verification_payload: Any | None = None,
    tamper_assets: Any | None = None,
    asset_ids: tuple[int, int, int] = (101, 102, 103),
) -> tuple[dict[str, Any], list[str]]:
    """Run _collect_live_evidence with real pagination over fake transport.

    ``asset_ids`` maps (checksums.txt, manifest.json, payload.json) to the
    live-listing asset IDs. Entry 32: these are observed transport routing
    values only — the capsule payload bytes never embed them, so any triple
    (including the real allocator's unpredictable large IDs) must validate.
    """
    file_names = [
        "fixture.txt" if index == 0 else f"file-{index}.txt" for index in range(files_count)
    ]
    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path)
    end_sha = boundary_shas["corrective_bootstrap"]
    resources = _boundary_payloads("corrective_bootstrap", start_sha, end_sha, boundary_shas, repo=repo)  # fmt: skip
    selected = {
        "boundary_chronology",
        "corrective_bootstrap",
        "durable_capsule",
        "external_prerequisites",
        "first_parent_receipts",
        "governed_prs",
    }
    resources = {name: value for name, value in resources.items() if name in selected}
    resources["boundary_chronology"]["boundaries"] = resources["boundary_chronology"]["boundaries"][
        :1
    ]
    verification_identity = {"byte_length": 18, "sha256": "a" * 64}
    capsule_tag = f"cdg-corrective_bootstrap-{end_sha}"
    # Hostile-injection hooks receive the concrete (end_sha, capsule_tag)
    # pair because boundary SHAs are minted per disposable repository.
    if callable(releases_payload):
        releases_payload = releases_payload(end_sha, capsule_tag)
    if callable(tag_ref_object):
        tag_ref_object = tag_ref_object(end_sha, capsule_tag)
    if callable(annotated_tag_object):
        annotated_tag_object = annotated_tag_object(end_sha, capsule_tag)
    # Entry 32: claim shape omits asset_api_ids (pre-known fields only).
    resources["durable_capsule"]["release"] = {
        "asset_names": ["manifest.json", "payload.json", "checksums.txt"],
        "exact_full_sha_tag": end_sha,
        "immutable": True,
        "release_api_id": 100,
        "tag_name": capsule_tag,
        "verified": True,
    }
    resources["durable_capsule"]["attestation"] = _stable_attestation_claim()
    if mutate is not None:
        mutate(resources)
    payload = {
        "boundary": "corrective_bootstrap",
        "end_sha": end_sha,
        "resources": [{"name": name, "value": value} for name, value in sorted(resources.items())],
        "schema": ratchet.BOUNDARY_CAPSULE_PAYLOAD_SCHEMA,
        "start_sha": start_sha,
    }
    payload_raw = _canonical_boundary_bytes(payload)
    manifest = {
        "boundary": "corrective_bootstrap",
        "end_sha": end_sha,
        "payload_byte_length": len(payload_raw),
        "payload_sha256": hashlib.sha256(payload_raw).hexdigest(),
        "schema": ratchet.BOUNDARY_CAPSULE_MANIFEST_SCHEMA,
        "start_sha": start_sha,
    }
    manifest_raw = _canonical_boundary_bytes(manifest)
    checksums_raw = (
        f"{hashlib.sha256(manifest_raw).hexdigest()}  manifest.json\n"
        f"{hashlib.sha256(payload_raw).hexdigest()}  payload.json\n"
    ).encode()
    checksums_id, manifest_id, payload_id = asset_ids
    assets = {checksums_id: checksums_raw, manifest_id: manifest_raw, payload_id: payload_raw}
    if tamper_assets is not None:
        tamper_assets(assets)
    asset_sha256s = {
        "checksums.txt": hashlib.sha256(checksums_raw).hexdigest(),
        "manifest.json": hashlib.sha256(manifest_raw).hexdigest(),
        "payload.json": hashlib.sha256(payload_raw).hexdigest(),
    }
    identity = {
        "byte_length": 2,
        "etag": '"stable"',
        "sha256": hashlib.sha256(b"{}").hexdigest(),
        "updated_at": "2026-07-20T00:00:00Z",
    }
    # The first file record carries the real path changed by the disposable
    # boundary commit so the recomputed first-parent semantic delta stays
    # inside the authenticated disposition.
    files = [{"filename": filename, "id": index + 1} for index, filename in enumerate(file_names)]
    if duplicate_file_ids:
        files = [dict(item, id=1) for item in files]
    observed_changed_files = files_count if changed_files is None else changed_files
    requested: list[str] = []

    def stable_get(
        endpoint: str,
        *,
        operation_log: list[dict[str, Any]],
        attempts: int = 3,
        preserve_raw: bool = False,
    ) -> tuple[Any, dict[str, Any]]:
        del operation_log, attempts
        requested.append(endpoint)
        if "per_page=100&page=" in endpoint:
            page = int(endpoint.rsplit("page=", 1)[1])
            if "/pulls/9999/files" in endpoint:
                files_identity = (
                    identity
                    if files_link_header is None
                    else dict(identity, link=files_link_header)
                )
                return files[(page - 1) * 100 : page * 100], files_identity
            if endpoint.startswith("repos/synaptent/aragora/releases?"):
                if releases_payload is not None:
                    return (releases_payload if page == 1 else []), identity
                return [{"id": 100, "tag_name": capsule_tag}], identity
            if "rulesets/rule-suites?ref=" in endpoint:
                return [_rule_suite_record(end_sha)], identity
            raise AssertionError(endpoint)
        if endpoint == "repos/synaptent/aragora":
            return {"full_name": "synaptent/aragora", "id": 1126097105, "name": "aragora"}, identity
        if endpoint.endswith("/branches/main"):
            return {"commit": {"sha": end_sha}, "name": "main"}, identity
        if endpoint.endswith("/branches/main/protection"):
            return {"required_status_checks": {"strict": False}}, identity
        if endpoint.endswith("/immutable-releases"):
            return {"enabled": True}, identity
        if endpoint.endswith("/releases/100"):
            return {
                "assets": [
                    {"id": checksums_id, "name": "checksums.txt"},
                    {"id": manifest_id, "name": "manifest.json"},
                    {"id": payload_id, "name": "payload.json"},
                ],
                "draft": False,
                "id": 100,
                "immutable": True,
                "prerelease": False,
                "tag_name": capsule_tag,
            }, identity
        if endpoint.endswith(f"/git/ref/tags/{capsule_tag}"):
            if tag_ref_object is not None:
                return tag_ref_object, identity
            return {
                "object": {"sha": end_sha, "type": "commit"},
                "ref": f"refs/tags/{capsule_tag}",
            }, identity
        if "/git/tags/" in endpoint:
            if annotated_tag_object is not None:
                return annotated_tag_object, identity
            return {
                "object": {"sha": end_sha, "type": "commit"},
                "sha": endpoint.rsplit("/", 1)[1],
                "tag": capsule_tag,
            }, identity
        if endpoint.endswith("/rulesets/rule-suites/987654"):
            record = _rule_suite_record(end_sha)
            raw = ratchet._canonical_json_bytes(record).decode("utf-8")
            rule_suite_identity = dict(identity)
            if preserve_raw:
                rule_suite_identity.update(
                    {
                        "byte_length": len(raw.encode("utf-8")),
                        "raw_response": raw,
                        "response_fields": record,
                        "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                    }
                )
            return record, rule_suite_identity
        if endpoint.endswith("/pulls/9999"):
            return {
                "additions": pr_additions,
                "base": {"sha": "f" * 40},
                "changed_files": observed_changed_files,
                "deletions": pr_deletions,
                "head": {"sha": end_sha},
                "merge_commit_sha": end_sha,
                "merged_at": "2026-07-20T00:00:00Z",
                "number": 9999,
            }, identity
        if endpoint.endswith(f"/git/commits/{end_sha}"):
            tree_sha = resources["governed_prs"]["records"][0]["head_tree_sha"]
            return {
                "parents": [{"sha": start_sha}],
                "sha": end_sha,
                "tree": {"sha": tree_sha},
            }, identity
        raise AssertionError(endpoint)

    def raw_get(
        endpoint: str,
        *,
        operation_log: list[dict[str, Any]],
        attempts: int = 3,
    ) -> tuple[bytes, dict[str, Any]]:
        del operation_log, attempts
        asset_id = int(endpoint.rsplit("/", 1)[1])
        raw = assets[asset_id]
        return raw, {
            "byte_length": len(raw),
            "etag": f'"asset-{asset_id}"',
            "sha256": hashlib.sha256(raw).hexdigest(),
            "updated_at": "2026-07-20T00:00:00Z",
        }

    monkeypatch.setattr(ratchet, "_gh_api_get_stable", stable_get)
    monkeypatch.setattr(ratchet, "_gh_api_get_raw_stable", raw_get)

    def fake_verify(
        argv: list[str],
        *,
        operation_log: list[dict[str, Any]],
        resource: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        del operation_log
        if argv[1] == "release":
            if verification_payload is not None:
                return (
                    verification_payload(asset_sha256s, capsule_tag),
                    verification_identity,
                )
            return (
                _real_shaped_verification_payload(asset_sha256s, tag=capsule_tag),
                verification_identity,
            )
        return {"resource": resource, "verified": bool(argv)}, verification_identity

    monkeypatch.setattr(ratchet, "_run_live_verification", fake_verify)
    original_semantic_delta = ratchet._first_parent_semantic_delta
    if files_count != 1:
        expected_paths = set(file_names)
        setattr(
            ratchet,
            "_first_parent_semantic_delta",
            lambda *_args, **_kwargs: set(expected_paths),
        )
    try:
        _discovered, _summary, context = ratchet._collect_live_evidence(
            github_repository="synaptent/aragora",
            github_branch="main",
            boundary="corrective_bootstrap",
            start_sha=start_sha,
            end_sha=end_sha,
            repo_root=repo,
            scratch_root=tmp_path,
            operation_log=[],
        )
    finally:
        setattr(ratchet, "_first_parent_semantic_delta", original_semantic_delta)
    return context, requested


def test_pr_files_bind_changed_files_additions_and_deletions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    context, _requested = _live_pr_files_probe(
        tmp_path, monkeypatch, files_count=3, pr_additions=123, pr_deletions=45
    )
    # The exact PR response additions/deletions are bound into the live
    # context, keyed by PR number, with nothing inferred or defaulted.
    assert context["authenticated_pr_changes"] == {9999: {"additions": 123, "deletions": 45}}
    with pytest.raises(ValueError, match="additions/deletions are malformed"):
        _live_pr_files_probe(tmp_path / "neg", monkeypatch, pr_additions=-1)
    with pytest.raises(ValueError, match="additions/deletions are malformed"):
        _live_pr_files_probe(tmp_path / "bool", monkeypatch, pr_additions=True)  # type: ignore[arg-type]

    def wrong_head(resources: dict[str, Any]) -> None:
        resources["governed_prs"]["records"][0]["head_sha"] = "c" * 40

    with pytest.raises(ValueError, match="contradicts capsule evidence"):
        _live_pr_files_probe(tmp_path / "head", monkeypatch, mutate=wrong_head)
    # The downstream governed-PR validator re-binds the same numbers and
    # fails closed on every malformed or unreconciled shape.
    start_sha, end_sha = "1" * 40, "2" * 40
    resource = _governed_pr_resource(start_sha, end_sha)
    validated = ratchet._validate_governed_prs(
        resource,
        authenticated_pr_changes={9999: {"additions": 123, "deletions": 45}},
        repo_root=tmp_path,
        operation_log=[],
    )
    assert (
        validated[0]["authenticated_additions"],
        validated[0]["authenticated_deletions"],
        validated[0]["authenticated_pr_delta"],
    ) == (123, 45, 168)
    # Per contract L76 the census carries no generic cap: an over-800
    # authenticated delta still binds exactly (the cap is enforced only on
    # core/extended paydown facts in _validate_sdk_paydown).
    over_800 = ratchet._validate_governed_prs(
        _governed_pr_resource(start_sha, end_sha),
        authenticated_pr_changes={9999: {"additions": 500, "deletions": 301}},
        repo_root=tmp_path,
        operation_log=[],
    )
    assert over_800[0]["authenticated_pr_delta"] == 801
    with pytest.raises(ValueError, match="lacks authenticated additions/deletions"):
        ratchet._validate_governed_prs(
            _governed_pr_resource(start_sha, end_sha),
            authenticated_pr_changes={},
            repo_root=tmp_path,
            operation_log=[],
        )
    with pytest.raises(ValueError, match="do not reconcile"):
        ratchet._validate_governed_prs(
            _governed_pr_resource(start_sha, end_sha),
            authenticated_pr_changes={
                9999: {"additions": 1, "deletions": 1},
                10000: {"additions": 1, "deletions": 1},
            },
            repo_root=tmp_path,
            operation_log=[],
        )
    for additions, deletions in ((True, 0), (-1, 0), (0, None), ("4", 0)):
        malformed = cast(
            "dict[int, dict[str, int]]",
            {9999: {"additions": additions, "deletions": deletions}},
        )
        with pytest.raises(ValueError, match="additions/deletions are malformed"):
            ratchet._validate_governed_prs(
                _governed_pr_resource(start_sha, end_sha),
                authenticated_pr_changes=malformed,
                repo_root=tmp_path,
                operation_log=[],
            )


def test_capsule_discovery_requires_exactly_one_prefix_tag_release_resolving_to_end_sha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # Deterministic pass: exactly one `cdg-<boundary>-<end_sha>` release whose
    # lightweight tag ref resolves to the exact end SHA, with the tag-ref
    # retrieval recorded among the requested endpoints.
    context, requested = _live_pr_files_probe(tmp_path, monkeypatch)
    assert context["authenticated_pr_changes"] == {9999: {"additions": 400, "deletions": 400}}
    assert any("/git/ref/tags/cdg-corrective_bootstrap-" in endpoint for endpoint in requested)
    # A bare-SHA legacy tag can never satisfy prefix discovery (GitHub's
    # pre-receive hook rejects bare 40/64-hex tag names with HTTP 422, so the
    # convention is the fixed-prefix tag; a bare-SHA claim is also hostile).
    with pytest.raises(ratchet.BoundaryBlocked, match="authenticated and unavailable"):
        _live_pr_files_probe(
            tmp_path / "bare",
            monkeypatch,
            releases_payload=lambda end_sha, _tag: [{"id": 100, "tag_name": end_sha}],
        )
    # A wrong prefix and a wrong boundary name are equally invisible.
    with pytest.raises(ratchet.BoundaryBlocked, match="authenticated and unavailable"):
        _live_pr_files_probe(
            tmp_path / "prefix",
            monkeypatch,
            releases_payload=lambda end_sha, _tag: [
                {"id": 100, "tag_name": f"CDG-corrective_bootstrap-{end_sha}"}
            ],  # fmt: skip
        )
    with pytest.raises(ratchet.BoundaryBlocked, match="authenticated and unavailable"):
        _live_pr_files_probe(
            tmp_path / "boundary",
            monkeypatch,
            releases_payload=lambda end_sha, _tag: [
                {"id": 100, "tag_name": f"cdg-route_truth-{end_sha}"}
            ],  # fmt: skip
        )
    # Duplicate prefixed releases are ambiguous and fail closed.
    with pytest.raises(ValueError, match="identity is ambiguous"):
        _live_pr_files_probe(
            tmp_path / "dup",
            monkeypatch,
            releases_payload=lambda _end, tag: [
                {"id": 100, "tag_name": tag},
                {"id": 200, "tag_name": tag},
            ],
        )
    # The tag ref must independently resolve to exactly the end SHA: a moved
    # or reused tag pointing at any other commit fails closed.
    with pytest.raises(ValueError, match="does not resolve to the exact boundary end SHA"):
        _live_pr_files_probe(
            tmp_path / "moved",
            monkeypatch,
            tag_ref_object=lambda _end, tag: {
                "object": {"sha": "9" * 40, "type": "commit"},
                "ref": f"refs/tags/{tag}",
            },
        )
    # A malformed tag ref (wrong ref name) is rejected before resolution.
    with pytest.raises(ValueError, match="tag ref is malformed"):
        _live_pr_files_probe(
            tmp_path / "ref",
            monkeypatch,
            tag_ref_object=lambda _end, _tag: {
                "object": {"sha": "9" * 40, "type": "commit"},
                "ref": "refs/tags/other",
            },
        )
    # Annotated tags are dereferenced through the tag object: resolution to
    # the exact end SHA passes, any other commit fails closed.
    annotated_ref = lambda _end, tag: {  # noqa: E731
        "object": {"sha": "b" * 40, "type": "tag"},
        "ref": f"refs/tags/{tag}",
    }
    context, requested = _live_pr_files_probe(
        tmp_path / "annotated-pass", monkeypatch, tag_ref_object=annotated_ref
    )
    assert any("/git/tags/" + "b" * 40 in endpoint for endpoint in requested)
    with pytest.raises(ValueError, match="does not resolve to the exact boundary end SHA"):
        _live_pr_files_probe(
            tmp_path / "annotated-moved",
            monkeypatch,
            tag_ref_object=annotated_ref,
            annotated_tag_object=lambda _end, tag: {
                "object": {"sha": "9" * 40, "type": "commit"},
                "sha": "b" * 40,
                "tag": tag,
            },
        )


def test_release_claim_omits_asset_api_ids_and_binds_only_pre_known_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # Entry 32 (B5): GitHub allocates release-asset API IDs at upload time
    # from an unpredictable instance-global counter, AFTER the payload bytes
    # must already be final, so the payload-embedded release claim binds only
    # publication-time-knowable identity. The live plane must accept a capsule
    # whose payload omits asset_api_ids regardless of which IDs the allocator
    # actually assigned: real-shaped unpredictable IDs (empirical B5 probe
    # values) validate identically to the small fixture IDs because the IDs
    # are observed transport routing, never claims.
    context, _requested = _live_pr_files_probe(
        tmp_path,
        monkeypatch,
        asset_ids=(500447298, 500447355, 500447391),
    )
    assert context["authenticated_pr_changes"] == {9999: {"additions": 400, "deletions": 400}}

    # A stale-schema payload still carrying asset_api_ids fails closed in the
    # live plane: the exact claim equality rejects the extra field even when
    # the embedded triple happens to match the live listing.
    def stale_schema_claim(resources: dict[str, Any]) -> None:
        resources["durable_capsule"]["release"]["asset_api_ids"] = [101, 102, 103]

    with pytest.raises(ValueError, match="contradicts live verification"):
        _live_pr_files_probe(tmp_path / "stale", monkeypatch, mutate=stale_schema_claim)

    # Retained binding regressions: every pre-known identity field still
    # rejects a wrong-release capsule.
    def wrong_release_id(resources: dict[str, Any]) -> None:
        resources["durable_capsule"]["release"]["release_api_id"] = 999

    with pytest.raises(ValueError, match="contradicts live verification"):
        _live_pr_files_probe(tmp_path / "relid", monkeypatch, mutate=wrong_release_id)

    def wrong_claimed_tag(resources: dict[str, Any]) -> None:
        resources["durable_capsule"]["release"]["tag_name"] = "cdg-corrective_bootstrap-" + "9" * 40

    with pytest.raises(ValueError, match="contradicts live verification"):
        _live_pr_files_probe(tmp_path / "tag", monkeypatch, mutate=wrong_claimed_tag)

    # Wrong-bytes capsules still fail closed through the checksums.txt
    # cross-binding over the exact downloaded asset bytes.
    def tampered_manifest(assets: dict[int, bytes]) -> None:
        manifest_id = sorted(assets)[1]
        assets[manifest_id] = assets[manifest_id].replace(b"payload_sha256", b"payload_sha25X")

    with pytest.raises(ValueError, match="checksum asset is incomplete or noncanonical"):
        _live_pr_files_probe(tmp_path / "bytes", monkeypatch, tamper_assets=tampered_manifest)


def test_pr_files_paginate_to_exhaustion_and_reconcile_changed_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    context, requested = _live_pr_files_probe(tmp_path, monkeypatch, files_count=237)
    file_pages = [endpoint for endpoint in requested if "/pulls/9999/files" in endpoint]
    assert file_pages == [
        "repos/synaptent/aragora/pulls/9999/files?per_page=100&page=1",
        "repos/synaptent/aragora/pulls/9999/files?per_page=100&page=2",
        "repos/synaptent/aragora/pulls/9999/files?per_page=100&page=3",
    ]
    assert context["authenticated_pr_changes"] == {9999: {"additions": 400, "deletions": 400}}
    # An exact-boundary page count (multiple of 100) still fetches the final
    # short page rather than assuming exhaustion.
    _context, requested_200 = _live_pr_files_probe(tmp_path / "even", monkeypatch, files_count=200)
    assert sum(1 for e in requested_200 if "/pulls/9999/files" in e) == 3
    # File records that do not reconcile exactly to the PR response
    # changed_files fail closed — both short and inflated counts.
    for wrong in (236, 238):
        with pytest.raises(ValueError, match="file discovery is incomplete"):
            _live_pr_files_probe(
                tmp_path / f"wrong-{wrong}",
                monkeypatch,
                files_count=237,
                changed_files=wrong,
            )
    with pytest.raises(ValueError, match="duplicate record IDs"):
        _live_pr_files_probe(
            tmp_path / "dup", monkeypatch, files_count=150, duplicate_file_ids=True
        )


def test_zeroed_stats_dropout_accepted_only_under_dual_witness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # PERMANENT GitHub REST stats dropout (the PR #9850 shape): the pulls
    # endpoint zeroes changed_files/additions/deletions while the files
    # endpoint enumerates the true disposition. The default files_count=1
    # exercises the REAL recomputed first-parent semantic delta over the
    # disposable boundary repository (no injected delta).
    context, requested = _live_pr_files_probe(
        tmp_path,
        monkeypatch,
        changed_files=0,
        pr_additions=0,
        pr_deletions=0,
    )
    assert context["authenticated_pr_files"] == {9999: ["fixture.txt"]}
    assert context["authenticated_pr_changes"] == {9999: {"additions": 0, "deletions": 0}}
    assert any("/pulls/9999/files?per_page=100&page=1" in e for e in requested)
    # Multi-page zeroed enumerations still paginate to exhaustion and
    # reconcile against the (injected) semantic delta.
    context_multi, requested_multi = _live_pr_files_probe(
        tmp_path / "multi",
        monkeypatch,
        files_count=103,
        changed_files=0,
        pr_additions=0,
        pr_deletions=0,
    )
    assert sum(1 for e in requested_multi if "/pulls/9999/files" in e) == 2
    assert context_multi["authenticated_pr_files"][9999] == sorted(
        ["fixture.txt", *(f"file-{index}.txt" for index in range(1, 103))]
    )


def test_zeroed_stats_dropout_requires_fully_zeroed_rest_signature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # changed_files=0 with nonzero REST additions/deletions is NOT the stats
    # dropout signature; it remains incomplete file discovery.
    with pytest.raises(ValueError, match="file discovery is incomplete"):
        _live_pr_files_probe(
            tmp_path / "nonzero-stats",
            monkeypatch,
            files_count=3,
            changed_files=0,
        )
    with pytest.raises(ValueError, match="file discovery is incomplete"):
        _live_pr_files_probe(
            tmp_path / "zero-additions-only",
            monkeypatch,
            files_count=3,
            changed_files=0,
            pr_additions=0,
        )


def test_zeroed_stats_dropout_genuine_truncation_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # A zeroed-stats PR whose short files page still advertises rel="next"
    # is a genuinely truncated enumeration, not a curable dropout.
    with pytest.raises(ValueError, match="ended before an advertised next page"):
        _live_pr_files_probe(
            tmp_path,
            monkeypatch,
            files_count=3,
            changed_files=0,
            pr_additions=0,
            pr_deletions=0,
            files_link_header='<https://api.github.com/x?per_page=100&page=2>; rel="next"',
        )


def test_zeroed_stats_dropout_witness_binds_semantic_delta_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    observed_zeroed = {"additions": 0, "changed_files": 0, "deletions": 0}
    # Rename dispositions participate through previous_filename, exactly as
    # in the downstream VAL-CDG-018 witness.
    monkeypatch.setattr(
        ratchet,
        "_first_parent_semantic_delta",
        lambda *_args, **_kwargs: {"new.txt", "old.txt"},
    )
    operation_log: list[dict[str, Any]] = []
    ratchet._require_stats_dropout_completeness_witness(
        repo_root=tmp_path,
        pr=9850,
        observed_pr=observed_zeroed,
        files=[{"filename": "new.txt", "id": 1, "previous_filename": "old.txt"}],
        first_parent_sha="a" * 40,
        merge_sha="b" * 40,
        operation_log=operation_log,
    )
    assert [entry["kind"] for entry in operation_log] == ["stats_dropout_witness"]
    # Both mismatch directions fail closed.
    monkeypatch.setattr(
        ratchet,
        "_first_parent_semantic_delta",
        lambda *_args, **_kwargs: {"fixture.txt", "foreign.txt"},
    )
    with pytest.raises(ValueError, match="does not equal the recomputed first-parent"):
        ratchet._require_stats_dropout_completeness_witness(
            repo_root=tmp_path,
            pr=9850,
            observed_pr=observed_zeroed,
            files=[{"filename": "fixture.txt", "id": 1}],
            first_parent_sha="a" * 40,
            merge_sha="b" * 40,
            operation_log=[],
        )
    monkeypatch.setattr(ratchet, "_first_parent_semantic_delta", lambda *_args, **_kwargs: set())
    with pytest.raises(ValueError, match="does not equal the recomputed first-parent"):
        ratchet._require_stats_dropout_completeness_witness(
            repo_root=tmp_path,
            pr=9850,
            observed_pr=observed_zeroed,
            files=[{"filename": "fixture.txt", "id": 1}],
            first_parent_sha="a" * 40,
            merge_sha="b" * 40,
            operation_log=[],
        )
    # A bool changed_files is not the zeroed dropout signature even though
    # False == 0 in Python.
    with pytest.raises(ValueError, match="file discovery is incomplete"):
        ratchet._require_stats_dropout_completeness_witness(
            repo_root=tmp_path,
            pr=9850,
            observed_pr={"additions": 0, "changed_files": False, "deletions": 0},
            files=[{"filename": "fixture.txt", "id": 1}],
            first_parent_sha="a" * 40,
            merge_sha="b" * 40,
            operation_log=[],
        )
    # Defensive floors: an empty enumeration and noncanonical first-parent
    # bindings are never curable.
    with pytest.raises(ValueError, match="file enumeration is empty"):
        ratchet._require_stats_dropout_completeness_witness(
            repo_root=tmp_path,
            pr=9850,
            observed_pr=observed_zeroed,
            files=[],
            first_parent_sha="a" * 40,
            merge_sha="b" * 40,
            operation_log=[],
        )
    with pytest.raises(ValueError, match="lacks canonical first-parent bindings"):
        ratchet._require_stats_dropout_completeness_witness(
            repo_root=tmp_path,
            pr=9850,
            observed_pr=observed_zeroed,
            files=[{"filename": "fixture.txt", "id": 1}],
            first_parent_sha="a" * 40,
            merge_sha="953c501c",
            operation_log=[],
        )


def test_paginated_short_page_with_advertised_next_link_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
):
    # Link-exhaustion proof: a short page that still advertises rel="next"
    # is an inconsistent (truncated) enumeration and fails closed; a
    # rel="prev"-only terminal page remains exhausted.
    def serve(link: Any) -> Any:
        identity = {
            "byte_length": 1,
            "etag": '"e"',
            "link": link,
            "sha256": "0" * 64,
            "updated_at": None,
        }
        return lambda endpoint, *, operation_log: ([{"id": 1}], identity)

    monkeypatch.setattr(
        ratchet,
        "_gh_api_get_stable",
        serve('<https://api.github.com/x?per_page=100&page=2>; rel="next"'),
    )
    with pytest.raises(ValueError, match="ended before an advertised next page"):
        ratchet._gh_api_paginated("repos/synaptent/aragora/pulls/9850/files", operation_log=[])
    monkeypatch.setattr(
        ratchet,
        "_gh_api_get_stable",
        serve('<https://api.github.com/x?per_page=100&page=1>; rel="prev"'),
    )
    records, _identities = ratchet._gh_api_paginated(
        "repos/synaptent/aragora/pulls/9850/files", operation_log=[]
    )
    assert len(records) == 1
    # A malformed (non-string) Link identity fails closed rather than being
    # treated as exhausted.
    monkeypatch.setattr(ratchet, "_gh_api_get_stable", serve(7))
    with pytest.raises(ValueError, match="Link header is malformed"):
        ratchet._gh_api_paginated("repos/synaptent/aragora/pulls/9850/files", operation_log=[])


def test_files_api_incomplete_uses_exact_tree_diff_with_pinned_rename_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # A capsule that cannot prove complete file discovery fails closed.
    def denies_complete(resources: dict[str, Any]) -> None:
        resources["governed_prs"]["records"][0]["changed_files_complete"] = False

    with pytest.raises(ValueError, match="denies complete file discovery"):
        _live_pr_files_probe(tmp_path / "denied", monkeypatch, mutate=denies_complete)
    with pytest.raises(ValueError, match="file discovery is false or missing"):
        ratchet._validate_governed_prs(
            _governed_pr_resource("1" * 40, "2" * 40, changed_files_complete=False),
            authenticated_pr_changes={9999: {"additions": 1, "deletions": 1}},
            repo_root=tmp_path,
            operation_log=[],
        )

    # The completeness backstop is the exact immutable BASE/HEAD tree binding:
    # a governed record whose head tree disagrees with the authenticated
    # first-parent receipt tree is rejected.
    def wrong_tree(resources: dict[str, Any]) -> None:
        resources["governed_prs"]["records"][0]["head_tree_sha"] = "d" * 40

    with pytest.raises(ValueError, match="lacks first-parent or tree equality"):
        _live_pr_files_probe(tmp_path / "tree", monkeypatch, mutate=wrong_tree)
    # Pinned rename policy: baseline identity is the exact canonical path at
    # the exact ref. A rename is a removal at the canonical path — it is never
    # followed, so renamed content cannot masquerade as the governed baseline.
    repo = tmp_path / "rename-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _write_docs(
        repo,
        {
            "verify": {"python_sdk_drift": ["GET /a"], "typescript_sdk_drift": []},
            "routes": {"missing_in_spec": [], "orphaned_in_spec": []},
            "parity": {"missing_from_both_sdks": []},
        },
    )
    base_sha = _commit(repo, "base")
    verify_rel = gen.BASELINE_SPECS["verify"][0]
    subprocess.run(
        ["git", "-C", str(repo), "mv", str(verify_rel), "scripts/baselines/renamed.json"],
        check=True,
    )
    head_sha = _commit(repo, "rename")
    base_docs = gen.load_git_docs(repo, base_sha)
    head_docs = gen.load_git_docs(repo, head_sha)
    assert "python_sdk_drift:GET /a" in gen.collect_ids(base_docs)
    assert head_docs["verify"] == {}
    assert gen.collect_ids(head_docs) == {}
    assert ratchet._git_doc(repo, head_sha, repo / verify_rel) == {}
    # No rename-following flags exist anywhere in the analyzer sources.
    for module_file in (ratchet.__file__, gen.__file__):
        source = Path(module_file).read_text(encoding="utf-8")
        assert "--follow" not in source
        assert "find-renames" not in source
        assert "-M100" not in source


def test_compare_api_is_never_a_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Static: neither analyzer module constructs a GitHub compare endpoint.
    for module_file in (ratchet.__file__, gen.__file__):
        source = Path(module_file).read_text(encoding="utf-8")
        assert "/compare" not in source
        assert "compare/" not in source
        assert "compare?" not in source
    # Live evidence collection never requests a compare endpoint.
    _context, requested = _live_pr_files_probe(tmp_path, monkeypatch, files_count=3)
    assert requested and not any("compare" in endpoint for endpoint in requested)

    # PR-mode CLI analysis is exact-ref local git only: no GitHub API surface
    # (compare or otherwise) is ever consulted.
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("pr mode must not consult the GitHub API")

    monkeypatch.setattr(ratchet, "_gh_api_get_stable", forbidden)
    monkeypatch.setattr(ratchet, "_gh_api_paginated", forbidden)
    monkeypatch.setattr(ratchet, "_gh_api_get_raw_stable", forbidden)
    (tmp_path / "cli").mkdir()
    paths, repo, base = _seed(tmp_path / "cli", program=RED_PROGRAM)
    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["passing"]


def test_pr_mode_fails_total_growth(monkeypatch, tmp_path: Path):
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)
    verify = json.loads(paths["verify"].read_text())
    verify["python_sdk_drift"].append("new")
    _write_json(paths["verify"], verify)
    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert not result["passing"]
    deltas = result["pr_delta"]["counts"]
    assert sum(d["head"] for d in deltas.values()) - sum(d["base"] for d in deltas.values()) == 1
    assert result["pr_delta"]["increased"] == ["verify_python_sdk_drift"]
    assert result["pr_delta"]["new_entries"] == ["python_sdk_drift:new"]
    assert any("python_sdk_drift:new" in r for r in result["pr_delta"]["unexplained_increase"])
    monkeypatch.setattr(
        sys,
        "argv",
        _argv(paths, repo, base, "--mode", "pr", "--base-ref", base, "--as-of", "2026-07-16"),
    )
    assert ratchet.main() == 1
    # Accepted-authority layer: any head-live original ID beyond base fails
    # with the exact added set named.
    calls: list[str | None] = []

    def fake_validate(
        authority: dict[str, Any],
        *,
        repo_root: Path,
        live_ref: str | None = None,
        residue_ref: str | None = None,
    ) -> dict[str, Any]:
        del authority, repo_root, residue_ref
        calls.append(live_ref)
        live = ["cdg1:aa"] if live_ref == "base-sha" else ["cdg1:aa", "cdg1:xx"]
        return {
            "active_original_record_ids": ["cdg1:aa", "cdg1:bb"],
            "analyzer_bundle_sha256": "0" * 64,
            "live_original_record_ids": live,
        }

    monkeypatch.setattr(ratchet, "validate_accepted_authority", fake_validate)
    compared = ratchet.compare_accepted_authorities(
        _accepted_authority(),
        _accepted_authority(),
        repo_root=tmp_path,
        base_ref="base-sha",
        head_ref="head-sha",
    )
    assert (compared["passing"], compared["status"]) == (False, "fail")
    assert compared["added_original_record_ids"] == ["cdg1:xx"]
    assert compared["removed_original_record_ids"] == []


def test_pr_mode_fails_any_category_growth(tmp_path: Path):
    paths, repo, base = _seed(
        tmp_path,
        program=RED_PROGRAM,
        routes={"missing_in_spec": ["m1", "m2"], "orphaned_in_spec": []},
        parity={"missing_from_both_sdks": []},
    )
    # Head shrinks typescript by two (legitimately resolved) but grows python
    # by one: net total decreases, yet the single growing category fails.
    verify = json.loads(paths["verify"].read_text())
    verify["typescript_sdk_drift"] = ["x"]
    verify["python_sdk_drift"].append("new")
    _write_json(paths["verify"], verify)

    def resolve(inv: dict) -> None:
        for item in inv["items"]:
            if item["id"] in {"typescript_sdk_drift:y", "typescript_sdk_drift:z"}:
                item["status"] = "resolved"
                item["resolved_on"] = "2026-07-16"

    _edit_inventory(paths, resolve)
    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert not result["passing"]
    deltas = result["pr_delta"]["counts"]
    assert sum(d["delta"] for d in deltas.values()) == -1
    assert result["pr_delta"]["increased"] == ["verify_python_sdk_drift"]
    assert deltas["verify_typescript_sdk_drift"]["delta"] == -2
    reasons = result["pr_delta"]["unexplained_increase"]
    assert any("python_sdk_drift:new" in reason for reason in reasons)
    # The category-count key set is exactly the ratified five-count schema,
    # including the zero-count categories.
    assert sorted(deltas) == sorted(key for key, _alias, _list in ratchet.COUNT_KEYS)
    assert (deltas["sdk_missing_from_both"]["base"], deltas["sdk_missing_from_both"]["head"]) == (0, 0)  # fmt: skip
    assert (deltas["routes_orphaned_in_spec"]["base"], deltas["routes_orphaned_in_spec"]["head"]) == (0, 0)  # fmt: skip


def test_pr_mode_reports_complete_exact_original_record_set_diagnostics(
    monkeypatch,
    tmp_path: Path,
):
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)
    added = [f"p{index:02d}" for index in range(12)]
    verify = json.loads(paths["verify"].read_text())
    verify["python_sdk_drift"].extend(added)
    _write_json(paths["verify"], verify)
    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert not result["passing"]
    expected_ids = sorted(f"python_sdk_drift:{entry}" for entry in added)
    # Every added unit is enumerated exactly — no truncation, no count-only
    # summary, and one diagnostic naming each specific missing record.
    assert result["pr_delta"]["new_entries"] == expected_ids
    reasons = result["pr_delta"]["unexplained_increase"]
    assert len(reasons) == 12
    for item_id in expected_ids:
        assert any(item_id in reason for reason in reasons)
    assert result["pr_delta"]["counts"]["verify_python_sdk_drift"]["delta"] == 12

    # Accepted-authority layer: every added original_record_id is listed,
    # sorted, with no cap.
    def fake_validate(
        authority: dict[str, Any],
        *,
        repo_root: Path,
        live_ref: str | None = None,
        residue_ref: str | None = None,
    ) -> dict[str, Any]:
        del authority, repo_root, residue_ref
        live = ["cdg1:aa"]
        if live_ref == "head-sha":
            live = ["cdg1:aa", "cdg1:zz", "cdg1:xx", "cdg1:yy"]
        return {
            "active_original_record_ids": ["cdg1:aa"],
            "analyzer_bundle_sha256": "0" * 64,
            "live_original_record_ids": live,
        }

    monkeypatch.setattr(ratchet, "validate_accepted_authority", fake_validate)
    compared = ratchet.compare_accepted_authorities(
        _accepted_authority(),
        _accepted_authority(),
        repo_root=tmp_path,
        base_ref="base-sha",
        head_ref="head-sha",
    )
    assert compared["added_original_record_ids"] == ["cdg1:xx", "cdg1:yy", "cdg1:zz"]
    assert not compared["passing"]


def test_pr_mode_passes_equal_or_subset_original_record_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Equal head: identical baselines pass with empty deltas.
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)
    equal = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert equal["passing"]
    assert equal["pr_delta"]["increased"] == []
    assert equal["pr_delta"]["new_entries"] == []
    # Subset head: remove one unit per SDK list with matching resolution.
    verify = json.loads(paths["verify"].read_text())
    verify["python_sdk_drift"].remove("b")
    verify["typescript_sdk_drift"].remove("z")
    _write_json(paths["verify"], verify)

    def resolve(inv: dict) -> None:
        for item in inv["items"]:
            if item["id"] in {"python_sdk_drift:b", "typescript_sdk_drift:z"}:
                item["status"] = "resolved"
                item["resolved_on"] = "2026-07-16"

    _edit_inventory(paths, resolve)
    subset = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert subset["passing"]
    base_docs = {
        "verify": ratchet._git_doc(repo, base, paths["verify"]),
        "routes": ratchet._git_doc(repo, base, paths["routes"]),
        "parity": ratchet._git_doc(repo, base, paths["parity"]),
    }
    head_docs = {
        "verify": json.loads(paths["verify"].read_text()),
        "routes": json.loads(paths["routes"].read_text()),
        "parity": json.loads(paths["parity"].read_text()),
    }
    base_ids = gen.collect_ids(base_docs)
    head_ids = gen.collect_ids(head_docs)
    assert set(head_ids) < set(base_ids)
    for list_key in {list_key for _c, _a, list_key in ratchet.COUNT_KEYS}:
        assert {i for i, lk in head_ids.items() if lk == list_key} <= {
            i for i, lk in base_ids.items() if lk == list_key
        }
    # Accepted-authority layer: an exact evidenced paydown subset passes with
    # the complete sorted removed set and no added IDs. The committed head IS
    # that paydown relative to its reconstructed all-active genesis base,
    # one comparator-verified wave at a time.
    root = Path(ratchet.__file__).parents[1]
    authority = _accepted_authority()
    summary = ratchet.validate_accepted_authority(authority, repo_root=root)
    live = set(summary["live_original_record_ids"])
    genesis_summary = ratchet.validate_accepted_authority(
        _genesis_authority(authority), repo_root=root
    )
    waves = _replay_committed_paydown(authority, repo_root=root, monkeypatch=monkeypatch)
    removed = sorted(record_id for _digest, ids in waves for record_id in ids)
    assert set(genesis_summary["active_original_record_ids"]) - set(removed) == live
    assert removed == sorted(removed) and len(removed) == 367
    assert set(removed).isdisjoint(live)


# --------------------- VAL-CDG-003 (pr side): annotations are nonoperative


_ANNOTATION_ZOO: dict[str, Any] = {
    "accepted": True,
    "annotations": {"nested": {"deep": [1, 2, {"three": None}]}},
    "candidate_intentional_growth": True,
    "generated_artifact": {"path": "generated/openapi.json"},
    "handler_backed": False,
    "public": False,
    "resolved_note": "claims resolution without evidence",
    "stale_sdk": ["python"],
    "wildcard": "*",
    "zz_unknown_future_key": [{"scalar": 1}, None, "text"],
}


def _governed_view(result: dict) -> tuple:
    return (
        result["passing"],
        result["integrity"]["passing"],
        tuple(sorted(result["integrity"]["issues"])),
        result["current"],
        {key: value for key, value in result["pr_delta"].items() if key != "base_ref"},
    )


def test_all_annotation_fields_are_nonoperative(tmp_path: Path):
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)
    before = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)

    def annotate(inv: dict) -> None:
        inv["annotation_sidecar"] = {"version": 99, "labels": ["future"]}
        for item in inv["items"]:
            item.update(copy.deepcopy(_ANNOTATION_ZOO))

    _edit_inventory(paths, annotate)
    after = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert _governed_view(after) == _governed_view(before)
    assert after["passing"]
    program_after = _result(paths, "2026-07-16", repo=repo, cohort=base)
    assert program_after["current"] == before["current"]
    assert program_after["integrity"]["passing"]


def test_known_classification_labels_cannot_exclude_live_units(tmp_path: Path):
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)
    baseline = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)

    # Known nonoperative labels on an open item change nothing.
    def label(inv: dict) -> None:
        for item in inv["items"]:
            if item["id"] == "python_sdk_drift:a":
                item.update(
                    accepted=True,
                    candidate_intentional_growth=True,
                    generated_artifact={"path": "x"},
                )

    _edit_inventory(paths, label)
    labeled = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert _governed_view(labeled) == _governed_view(baseline)

    # A classification that tries to subtract a live unit (resolving an item
    # whose baseline witness is still present) fails closed with the unit
    # named — it is never silently excluded from the governed set.
    def resolve_live(inv: dict) -> None:
        for item in inv["items"]:
            if item["id"] == "python_sdk_drift:a":
                item["status"] = "resolved"
                item["resolved_on"] = "2026-07-16"

    _edit_inventory(paths, resolve_live)
    excluded = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert not excluded["passing"]
    assert not excluded["integrity"]["passing"]
    assert any(
        "Baseline entry not open in inventory" in issue and "python_sdk_drift:a" in issue
        for issue in excluded["integrity"]["issues"]
    )
    assert excluded["current"] == baseline["current"]  # counts still include the unit


def test_unknown_annotation_keys_cannot_exclude_live_units(tmp_path: Path):
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)
    baseline = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)

    # Unknown future annotation keys that "claim" exclusion are inert.
    def annotate(inv: dict) -> None:
        inv["excluded_ids"] = ["python_sdk_drift:a"]
        for item in inv["items"]:
            item.update(live=False, excluded=True, suppress={"reason": "future"})

    _edit_inventory(paths, annotate)
    annotated = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert _governed_view(annotated) == _governed_view(baseline)
    assert annotated["current"]["total_items"] == baseline["current"]["total_items"]

    # An unknown status value is not an exclusion channel either: it fails
    # closed while the unit stays counted.
    def unknown_status(inv: dict) -> None:
        inv["items"][0]["status"] = "suppressed"

    _edit_inventory(paths, unknown_status)
    suppressed = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert not suppressed["passing"]
    assert any("Unknown status" in issue for issue in suppressed["integrity"]["issues"])
    assert suppressed["current"] == baseline["current"]


def test_accepted_inventory_annotation_tamper_does_not_change_enforcement():
    root = Path(ratchet.__file__).parents[1]
    # Untampered enforcement outcome (the invariant being defended).
    summary = ratchet.validate_accepted_authority(_accepted_authority(), repo_root=root)
    assert summary["original_record_total"] == 655
    assert len(summary["live_original_record_ids"]) == 288
    # Any annotation key added to an accepted-inventory row fails closed: the
    # row schema is exactly {category, disposition_history, original_record_id,
    # status}, so tamper can never ride along as metadata.
    annotated = _accepted_authority()
    annotated["active_inventory"][0]["annotation"] = {"accepted": True}
    with pytest.raises(ValueError, match="disposition is malformed"):
        ratchet.validate_accepted_authority(annotated, repo_root=root)
    # Reclassifying a row's category label is identity tamper, not annotation.
    relabeled = _accepted_authority()
    row = relabeled["active_inventory"][0]
    row["category"] = next(
        category for category in ratchet.ACCEPTED_CATEGORIES if category != row["category"]
    )
    with pytest.raises(ValueError, match="identity or genesis is invalid"):
        ratchet.validate_accepted_authority(relabeled, repo_root=root)
    # Reordering rows (a pure presentation change) breaks the bound digest
    # rather than silently changing enforcement order.
    reordered = _accepted_authority()
    reordered["active_inventory"] = list(reversed(reordered["active_inventory"]))
    with pytest.raises(ValueError, match="differs from live witnesses or its digest"):
        ratchet.validate_accepted_authority(reordered, repo_root=root)


def test_annotations_cannot_change_pr_verdict_projection_or_exact_diagnostics(
    tmp_path: Path,
):
    # Failing PR: annotations claiming the growth is intentional change
    # neither the verdict nor one byte of the exact diagnostics.
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)
    verify = json.loads(paths["verify"].read_text())
    verify["python_sdk_drift"].append("new")
    _write_json(paths["verify"], verify)
    failing = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert not failing["passing"]

    def annotate(inv: dict) -> None:
        inv["intentional_growth"] = ["python_sdk_drift:new"]
        for item in inv["items"]:
            item.update(copy.deepcopy(_ANNOTATION_ZOO))

    _edit_inventory(paths, annotate)
    annotated = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert not annotated["passing"]
    assert _governed_view(annotated) == _governed_view(failing)
    assert (
        annotated["pr_delta"]["unexplained_increase"] == failing["pr_delta"]["unexplained_increase"]
    )
    # Passing PR: annotations cannot flip a pass to a fail either.
    (tmp_path / "clean").mkdir()
    clean_paths, clean_repo, clean_base = _seed(tmp_path / "clean", program=RED_PROGRAM)
    clean_before = _result(clean_paths, "2026-07-16", repo=clean_repo, cohort=clean_base, mode="pr", base_ref=clean_base)  # fmt: skip
    _edit_inventory(clean_paths, annotate)
    clean_after = _result(clean_paths, "2026-07-16", repo=clean_repo, cohort=clean_base, mode="pr", base_ref=clean_base)  # fmt: skip
    assert clean_before["passing"] and clean_after["passing"]
    assert _governed_view(clean_after) == _governed_view(clean_before)
    # Operation projection: an annotation smuggled onto a projection record
    # breaks its digest binding — the projection is tamper-evident, never
    # silently reshaped.
    hostile = _accepted_authority()
    hostile["canonical_artifacts"]["original_cohort"]["operation_projection"]["records"][0][
        "annotations"
    ] = {"collapse": True}
    with pytest.raises(ValueError, match="projection"):
        ratchet._validate_original_cohort(hostile["canonical_artifacts"]["original_cohort"])


# ------------------- VAL-CDG-007 (boundary side): fail-closed negatives


def test_duplicate_or_incomplete_paginated_collection_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
):
    # Duplicate record IDs across pages fail closed.
    def duplicated(
        endpoint: str, *, operation_log: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        del operation_log
        page = int(endpoint.rsplit("page=", 1)[1])
        payload = [{"id": index} for index in range(100)] if page == 1 else [{"id": 99}]
        return payload, {"byte_length": page, "etag": f'"p{page}"', "sha256": f"{page:064x}", "updated_at": None}  # fmt: skip

    monkeypatch.setattr(ratchet, "_gh_api_get_stable", duplicated)
    with pytest.raises(ValueError, match="duplicate record IDs"):
        ratchet._gh_api_paginated("repos/synaptent/aragora/releases", operation_log=[])
    # A non-list page is malformed, never silently treated as exhaustion.
    monkeypatch.setattr(
        ratchet,
        "_gh_api_get_stable",
        lambda endpoint, *, operation_log: ({"not": "a list"}, {}),
    )
    with pytest.raises(ValueError, match="paginated GitHub response is malformed"):
        ratchet._gh_api_paginated("repos/synaptent/aragora/releases", operation_log=[])
    # Nonterminating pagination is bounded and fails closed.
    monkeypatch.setattr(
        ratchet,
        "_gh_api_get_stable",
        lambda endpoint, *, operation_log: (
            [{"id": None} for _ in range(100)],
            {"byte_length": 1, "etag": '"e"', "sha256": "0" * 64, "updated_at": None},
        ),
    )
    with pytest.raises(ValueError, match="pagination did not terminate"):
        ratchet._gh_api_paginated("repos/synaptent/aragora/releases", operation_log=[])


def test_pr_changed_files_additions_deletions_mismatch_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # A PR response whose changed_files disagrees with the exhaustively
    # paginated file records fails closed (both directions).
    for wrong in (2, 5):
        with pytest.raises(ValueError, match="file discovery is incomplete"):
            _live_pr_files_probe(
                tmp_path / f"count-{wrong}",
                monkeypatch,
                files_count=3,
                changed_files=wrong,
            )
    # Malformed additions/deletions in the authenticated PR response fail.
    with pytest.raises(ValueError, match="additions/deletions are malformed"):
        _live_pr_files_probe(tmp_path / "neg-del", monkeypatch, pr_deletions=-4)
    # Contract L76 (entry 30): a corrective-boundary governed PR is not a
    # core/extended paydown PR, so an over-800 authenticated delta binds into
    # the census and the boundary still evaluates on its own predicates.
    over_cap = _boundary_result(
        tmp_path / "cap",
        monkeypatch,
        "corrective_bootstrap",
        pr_additions=500,
        pr_deletions=400,
    )
    assert (over_cap["status"], over_cap["passing"]) == ("pass", True), over_cap.get("error")


def test_release_attestation_stable_identity_hostile_shapes_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # Entry 30 hostile plane: every stable-identity forgery fails closed
    # before any capsule claim comparison. The happy path (real-shaped gh
    # 2.96.0 payload) is exercised by every passing _live_pr_files_probe run.
    def forged_signer(asset_sha256s: dict[str, str], tag: str) -> dict[str, Any]:
        return _real_shaped_verification_payload(
            asset_sha256s, tag=tag, signer_san_regexp=r"^https://evil\.example\.com$"
        )

    with pytest.raises(ValueError, match="signer identity contradicts"):
        _live_pr_files_probe(tmp_path / "signer", monkeypatch, verification_payload=forged_signer)

    def forged_predicate(asset_sha256s: dict[str, str], tag: str) -> dict[str, Any]:
        return _real_shaped_verification_payload(
            asset_sha256s, tag=tag, predicate_type="https://slsa.dev/provenance/v1"
        )

    with pytest.raises(ValueError, match="predicateType contradicts"):
        _live_pr_files_probe(
            tmp_path / "predicate", monkeypatch, verification_payload=forged_predicate
        )

    def wrong_repository(asset_sha256s: dict[str, str], tag: str) -> dict[str, Any]:
        return _real_shaped_verification_payload(asset_sha256s, tag=tag, repository="evil/aragora")

    with pytest.raises(ValueError, match="repository contradicts"):
        _live_pr_files_probe(tmp_path / "repo", monkeypatch, verification_payload=wrong_repository)

    def missing_subject(asset_sha256s: dict[str, str], tag: str) -> dict[str, Any]:
        partial = {name: sha for name, sha in asset_sha256s.items() if name != "payload.json"}
        return _real_shaped_verification_payload(partial, tag=tag)

    with pytest.raises(ValueError, match="subject digest set does not cover"):
        _live_pr_files_probe(
            tmp_path / "missing", monkeypatch, verification_payload=missing_subject
        )

    def tampered_asset_digest(asset_sha256s: dict[str, str], tag: str) -> dict[str, Any]:
        # Post-attestation asset tampering: the attested subject digest no
        # longer equals the SHA-256 of the exact downloaded asset bytes.
        tampered = dict(asset_sha256s, **{"payload.json": "f" * 64})
        return _real_shaped_verification_payload(tampered, tag=tag)

    with pytest.raises(ValueError, match="subject digest set does not cover"):
        _live_pr_files_probe(
            tmp_path / "tampered", monkeypatch, verification_payload=tampered_asset_digest
        )

    def duplicated_subject(asset_sha256s: dict[str, str], tag: str) -> dict[str, Any]:
        payload = _real_shaped_verification_payload(asset_sha256s, tag=tag)
        subjects = payload["verificationResult"]["statement"]["subject"]
        subjects.append(dict(subjects[-1]))
        return payload

    with pytest.raises(ValueError, match="duplicates"):
        _live_pr_files_probe(tmp_path / "dup", monkeypatch, verification_payload=duplicated_subject)

    def malformed_result(asset_sha256s: dict[str, str], tag: str) -> dict[str, Any]:
        del asset_sha256s, tag
        return {"verificationResult": "trusted"}

    with pytest.raises(ValueError, match="verification result is malformed"):
        _live_pr_files_probe(
            tmp_path / "malformed", monkeypatch, verification_payload=malformed_result
        )
    # And unit-level: a non-dict payload is malformed regardless of transport.
    with pytest.raises(ValueError, match="verification payload is malformed"):
        ratchet._validate_release_attestation_identity(
            [{"verified": True}],
            github_repository="synaptent/aragora",
            asset_sha256s={},
            resource="release-attestation",
        )


def test_files_api_cap_or_incomplete_tree_diff_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # A capsule that denies complete file discovery fails closed even when
    # every other predicate proves.
    def denies(resources: dict[str, Any]) -> None:
        resources["governed_prs"]["records"][0]["changed_files_complete"] = False

    with pytest.raises(ValueError, match="denies complete file discovery"):
        _live_pr_files_probe(tmp_path / "denied", monkeypatch, mutate=denies)

    # The tree-equality backstop: a head tree that does not equal the
    # authenticated merge tree fails closed (no partial diff is accepted).
    def wrong_tree(resources: dict[str, Any]) -> None:
        resources["first_parent_receipts"]["records"][0]["merge_tree_sha"] = "b" * 40

    with pytest.raises(ValueError, match="lacks first-parent or tree equality"):
        _live_pr_files_probe(tmp_path / "tree", monkeypatch, mutate=wrong_tree)


def test_compare_api_fallback_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # The read-only subprocess guard rejects a compare-endpoint mutation
    # dressed as gh api with a mutating method, and there is no compare
    # fallback anywhere in live evidence collection.
    with pytest.raises(ValueError, match="mutating HTTP"):
        ratchet._guard_subprocess_argv(["gh", "api", "--method", "POST", "repos/o/r/compare/a...b"])
    _context, requested = _live_pr_files_probe(tmp_path, monkeypatch, files_count=1)
    assert not any("compare" in endpoint for endpoint in requested)

    # An unexpected compare request would be unauthenticated: the transport
    # fake raises AssertionError, surfacing as a hard boundary failure, not a
    # silent fallback. Prove the failure path by asking for a compare probe.
    def compare_probe(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("compare endpoint must never be requested")

    monkeypatch.setattr(ratchet, "_gh_api_get_stable", compare_probe)
    with pytest.raises(AssertionError, match="compare endpoint"):
        ratchet._gh_api_get_stable("repos/synaptent/aragora/compare/a...b", operation_log=[])


def test_total_count_reconciliation_failure_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # Governed-PR reconciliation: authenticated changes for a PR that is not
    # in the capsule (or missing for one that is) fail closed.
    resource = _governed_pr_resource("1" * 40, "2" * 40)
    with pytest.raises(ValueError, match="do not reconcile"):
        ratchet._validate_governed_prs(
            resource,
            authenticated_pr_changes={
                9999: {"additions": 1, "deletions": 1},
                4242: {"additions": 1, "deletions": 1},
            },
            repo_root=tmp_path,
            operation_log=[],
        )
    # Empty governed evidence is missing evidence, not a zero-count success.
    empty = _governed_pr_resource("1" * 40, "2" * 40)
    empty["records"] = []
    with pytest.raises(ValueError, match="governed PR evidence is missing"):
        ratchet._validate_governed_prs(
            empty,
            authenticated_pr_changes={},
            repo_root=tmp_path,
            operation_log=[],
        )
    # Live collection: a capsule count that disagrees with the observed PR
    # response total fails during authentication, not after.
    with pytest.raises(ValueError, match="file discovery is incomplete"):
        _live_pr_files_probe(tmp_path / "short", monkeypatch, files_count=3, changed_files=99)


def test_boundary_manifest_digest_mismatch_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path)
    boundary = "corrective_bootstrap"
    end_sha = boundary_shas[boundary]
    index_path, index_length, index_sha256 = _write_boundary_index(
        tmp_path, boundary, start_sha, end_sha, boundary_shas, repo=repo
    )
    # Tamper with one resource file after the index digests were computed.
    resource_path = tmp_path / f"resources-{boundary}" / "governed_prs.json"
    payload = json.loads(resource_path.read_text())
    payload["records"][0]["pr"] = 4242
    resource_path.write_bytes(_canonical_boundary_bytes(payload))
    with pytest.raises(ValueError, match="SHA-256 mismatch|byte-length mismatch"):
        ratchet._load_evidence_resources(
            evidence_index_path=index_path,
            evidence_index_byte_length=index_length,
            evidence_index_sha256=index_sha256,
            boundary=boundary,
            start_sha=start_sha,
            end_sha=end_sha,
            operation_log=[],
        )
    # And a wrong index digest never reaches resource loading.
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        ratchet._load_evidence_resources(
            evidence_index_path=index_path,
            evidence_index_byte_length=index_length,
            evidence_index_sha256="0" * 64,
            boundary=boundary,
            start_sha=start_sha,
            end_sha=end_sha,
            operation_log=[],
        )


def test_boundary_start_equals_end_or_required_predicate_empty_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, start_sha, _boundary_shas = _boundary_git_repo(tmp_path)
    equal = ratchet.build_boundary_result(
        repo_root=repo,
        schema_version=1,
        boundary="corrective_bootstrap",
        start_ref=start_sha,
        end_ref=start_sha,
    )
    assert (equal["status"], equal["passing"]) == ("fail", False)
    assert "start SHA must differ from end SHA" in equal["error"]
    assert equal["error_code"] == "boundary_validation_failed"

    def empty_predicate(payloads: dict[str, dict[str, Any]]) -> None:
        proof = payloads["corrective_bootstrap"]
        for key in list(proof):
            if key not in {"schema", "predicate", "proof_for_boundary", "proof_start_sha", "proof_end_sha"}:  # fmt: skip
                del proof[key]

    empty = _boundary_result(
        tmp_path / "empty", monkeypatch, "corrective_bootstrap", mutate=empty_predicate
    )
    assert (empty["status"], empty["passing"]) == ("fail", False)
    assert empty["error_code"] == "boundary_validation_failed"


def test_caller_summary_or_caller_operation_log_cannot_authenticate_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # A capsule resource carrying caller-summary fields is rejected wholesale.
    for field in ("caller_summary", "operation_log", "summary", "results", "prior_boundary_manifest"):  # fmt: skip

        def smuggle(resources: dict[str, Any], field: str = field) -> None:
            resources["governed_prs"][field] = {"authenticated": True}

        with pytest.raises(ValueError, match="caller-supplied or inherited authority"):
            _live_pr_files_probe(tmp_path / f"caller-{field}", monkeypatch, mutate=smuggle)

    # Nested caller authority is found recursively.
    def nested(resources: dict[str, Any]) -> None:
        resources["corrective_bootstrap"]["accepted_stage1_closure"]["fact"]["summaries"] = []

    with pytest.raises(ValueError, match="caller-supplied or inherited authority"):
        _live_pr_files_probe(tmp_path / "nested", monkeypatch, mutate=nested)
    # The Python API rejects caller-supplied evidence/GitHub trust roots.
    with pytest.raises(TypeError):
        ratchet.build_boundary_result(
            repo_root=tmp_path,
            schema_version=1,
            boundary="corrective_bootstrap",
            start_ref="1" * 40,
            end_ref="2" * 40,
            evidence_resources={"governed_prs": {}},  # type: ignore[call-arg]
        )


def test_release_immutability_or_rule_suite_prerequisite_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    result = _boundary_result(
        tmp_path,
        monkeypatch,
        "corrective_bootstrap",
        release_immutability=False,
    )
    assert (result["status"], result["passing"]) == ("blocked", False)
    assert "future GitHub Release immutability" in result["blocked_reason"]
    assert result["blocked_reason"].endswith("authenticated and unavailable")
    # Unavailable rule-suite access blocks; unauthenticated claims fail.
    prerequisites = {
        "administration": {"authenticated": True, "available": False},
        "boundary": "corrective_bootstrap",
        "end_sha": "2" * 40,
        "future_release_immutability": {
            "authenticated": True,
            "available": True,
            "enabled": True,
        },  # fmt: skip
        "rule_suite": {"authenticated": True, "available": True},
        "schema": "contract-drift-external-prerequisites-v1",
        "start_sha": "1" * 40,
    }
    with pytest.raises(ratchet.BoundaryBlocked, match="authenticated and unavailable"):
        ratchet._validate_external_prerequisites(
            copy.deepcopy(prerequisites),
            repository_id=1,
            repository_name="aragora",
            expected_ref="refs/heads/main",
            end_sha="2" * 40,
            operation_log=[],
        )
    unauthenticated = copy.deepcopy(prerequisites)
    unauthenticated["administration"] = {"authenticated": False, "available": False}
    with pytest.raises(ValueError, match="not independently authenticated"):
        ratchet._validate_external_prerequisites(
            unauthenticated,
            repository_id=1,
            repository_name="aragora",
            expected_ref="refs/heads/main",
            end_sha="2" * 40,
            operation_log=[],
        )


def test_boundary_evidence_inheritance_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # Evidence stamped for a different boundary interval cannot be inherited.
    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path)
    boundary = "route_truth"
    end_sha = boundary_shas[boundary]
    index_path, index_length, index_sha256 = _write_boundary_index(
        tmp_path, boundary, start_sha, end_sha, boundary_shas, repo=repo
    )
    with pytest.raises(ValueError, match="interval mismatch"):
        ratchet._load_evidence_resources(
            evidence_index_path=index_path,
            evidence_index_byte_length=index_length,
            evidence_index_sha256=index_sha256,
            boundary=boundary,
            start_sha=start_sha,
            end_sha=boundary_shas["core_sdk"],  # a later boundary's SHA
            operation_log=[],
        )

    # An explicit inherited-authority marker on a resource is rejected.
    def inherit(resources: dict[str, Any]) -> None:
        resources["governed_prs"]["inherited_from_boundary"] = "corrective_bootstrap"

    with pytest.raises(ValueError, match="caller-supplied or inherited authority"):
        _live_pr_files_probe(tmp_path / "inherit", monkeypatch, mutate=inherit)


def test_boundary_status_blocked_rejects_internal_malformed_false_missing_or_bypass_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # Internal falsity: a false predicate fact fails (never blocked).
    def false_fact(payloads: dict[str, dict[str, Any]]) -> None:
        payloads["corrective_bootstrap"]["stage2_verifier_chronology"]["fact"][
            "ordered_after_stage1"
        ] = False

    false_result = _boundary_result(
        tmp_path / "false", monkeypatch, "corrective_bootstrap", mutate=false_fact
    )
    assert (false_result["status"], false_result["blocked_reason"]) == ("fail", None)

    # Missing evidence: a dropped predicate resource fails, never blocks.
    def drop(payloads: dict[str, dict[str, Any]]) -> None:
        del payloads["corrective_bootstrap"]["corrective_transition"]

    missing = _boundary_result(
        tmp_path / "missing", monkeypatch, "corrective_bootstrap", mutate=drop
    )
    assert (missing["status"], missing["blocked_reason"]) == ("fail", None)

    # Malformed digest binding on a fact fails, never blocks.
    def forge(payloads: dict[str, dict[str, Any]]) -> None:
        payloads["corrective_bootstrap"]["corrective_transition"]["sha256"] = "0" * 64

    forged = _boundary_result(
        tmp_path / "forged", monkeypatch, "corrective_bootstrap", mutate=forge
    )
    assert (forged["status"], forged["blocked_reason"]) == ("fail", None)
    # Bypassed rule suites fail closed (relabeled-blocked is impossible).
    bypassed = _rule_suite_record(
        "2" * 40,
        rule_evaluations=[{"result": "bypass", "rule_source": {"type": "repository"}}],
    )
    with pytest.raises(ValueError, match="bypassed evaluation"):
        ratchet._validate_rule_suite_record_fields(
            bypassed,
            repository_id=1126097105,
            repository_name="aragora",
            expected_ref="refs/heads/main",
            end_sha="2" * 40,
        )
    not_passing = _rule_suite_record("2" * 40, evaluation_result="bypass")
    with pytest.raises(ValueError, match="evaluation is not passing"):
        ratchet._validate_rule_suite_record_fields(
            not_passing,
            repository_id=1126097105,
            repository_name="aragora",
            expected_ref="refs/heads/main",
            end_sha="2" * 40,
        )
    # Mutation-tainted external prerequisite evidence fails, never blocks.
    with pytest.raises(ValueError, match="mutation-tainted"):
        ratchet._validate_external_prerequisites(
            {"mutation_tainted": True},
            repository_id=1,
            repository_name="aragora",
            expected_ref="refs/heads/main",
            end_sha="2" * 40,
            operation_log=[],
        )


def test_deterministic_boundary_status_pass_is_reachable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    for boundary in ("corrective_bootstrap", "final_seal"):
        base = tmp_path / boundary
        repo, start_sha, boundary_shas = _boundary_git_repo(base)
        end_sha = boundary_shas[boundary]
        index_path, index_length, index_sha256 = _write_boundary_index(
            base, boundary, start_sha, end_sha, boundary_shas, repo=repo
        )
        _stub_boundary_dependencies(monkeypatch)
        _stub_boundary_evidence_index(
            monkeypatch,
            repo=repo,
            index_path=index_path,
            index_length=index_length,
            index_sha256=index_sha256,
            pr_additions=400,
            pr_deletions=400,
        )
        runs = [
            ratchet.build_boundary_result(
                repo_root=repo,
                schema_version=1,
                boundary=boundary,
                start_ref=start_sha,
                end_ref=end_sha,
            )
            for _run in range(2)
        ]
        for result in runs:
            assert (result["status"], result["passing"]) == ("pass", True)
            assert result["blocked_reason"] is None
            assert list(result["predicates"]) == list(
                ratchet.BOUNDARY_NAMES[: ratchet.BOUNDARY_NAMES.index(boundary) + 1]
            )
            assert all(entry["proven"] is True for entry in result["predicates"].values())
        # Deterministic: the same fixture double-runs to identical canonical
        # bytes (the manifest digest covers everything but the fresh
        # operation log).
        assert runs[0]["predicates"] == runs[1]["predicates"]
        assert runs[0]["manifest_sha256"] == runs[1]["manifest_sha256"]


def test_read_only_cli_mutation_attempt_fails_closed(tmp_path: Path):
    # Mutating git/gh/HTTP actions are rejected before execution.
    for argv in (
        ["git", "commit", "-m", "x"],
        ["git", "push"],
        ["gh", "pr", "merge", "1"],
        ["gh", "api", "-XDELETE", "repos/o/r"],
        ["rm", "-rf", str(tmp_path)],
        [],
    ):
        with pytest.raises(ValueError, match="mutating|unsupported"):
            ratchet._guard_subprocess_argv(argv)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(ValueError, match="mutating HTTP"):
            ratchet._guard_http_method(method)
    # Write attempts outside the declared scratch/output roots are rejected.
    scratch = tmp_path / "scratch"
    output = tmp_path / "output"
    scratch.mkdir()
    output.mkdir()
    with pytest.raises(ValueError, match="write outside explicit scratch/output roots"):
        ratchet._guard_write_path(tmp_path / "escape.txt", scratch, output)
    ratchet._guard_write_path(scratch / "ok.txt", scratch, output)
    ratchet._guard_write_path(output / "ok.txt", scratch, output)
    # The exclusive private writer refuses to follow a preexisting symlink.
    target = tmp_path / "outside-target.txt"
    target.write_text("x", encoding="utf-8")
    link = scratch / "sneaky.json"
    link.symlink_to(target)
    with pytest.raises((ValueError, OSError)):
        ratchet._write_exclusive_private_file(link, b"{}", scratch_root=scratch, output_root=output)


# ------------- VAL-CDG-004: trusted base-SHA authority, hermetic execution

_HERMETIC_FILES = (
    "scripts/check_contract_drift_ratchet.py",
    "scripts/generate_contract_drift_inventory.py",
    "scripts/baselines/contract_drift_program.json",
    "scripts/baselines/contract_drift_inventory.json",
    "scripts/baselines/verify_sdk_contracts.json",
    "scripts/baselines/validate_openapi_routes.json",
    "scripts/baselines/check_sdk_parity.json",
)
_HERMETIC_INVENTORY = Path("scripts/baselines/contract_drift_inventory.json")


def _hermetic_repo(
    tmp_path: Path,
    *,
    mutate_base_inventory=None,
    head_writes: dict[str, str] | None = None,
) -> tuple[Path, str, str]:
    """Disposable repo whose base commit carries the real accepted authority
    and analyzer bundle; head applies `head_writes` (default: README only)."""
    src = Path(ratchet.__file__).parents[1]
    repo = tmp_path / "hermetic-repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for rel in _HERMETIC_FILES:
        destination = repo / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(
            subprocess.check_output(["git", "-C", str(src), "show", f"HEAD:{rel}"])
        )
    if mutate_base_inventory is not None:
        inventory = json.loads((repo / _HERMETIC_INVENTORY).read_text())
        mutate_base_inventory(inventory)
        (repo / _HERMETIC_INVENTORY).write_text(json.dumps(inventory))
    base = _commit(repo, "base")
    for rel, content in (head_writes or {"README.md": "head change\n"}).items():
        head_path = repo / rel
        head_path.parent.mkdir(parents=True, exist_ok=True)
        head_path.write_text(content, encoding="utf-8")
    head = _commit(repo, "head")
    return repo, base, head


def _recorded_hermetic_pr(
    repo: Path, base: str, head: str, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    real_run = subprocess.run

    def recorder(cmd, *args, **kwargs):
        entry: dict[str, Any] = {
            "argv": [str(part) for part in cmd],
            "cwd": kwargs.get("cwd"),
            "env": kwargs.get("env"),
        }
        if entry["argv"] and entry["argv"][0] == sys.executable and kwargs.get("cwd"):
            entry["cwd_listing"] = sorted(os.listdir(kwargs["cwd"]))
        calls.append(entry)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", recorder)
    result = ratchet._run_hermetic_pr(
        repo_root=repo, base_ref=base, head_ref=head, inventory_path=_HERMETIC_INVENTORY
    )
    monkeypatch.setattr(subprocess, "run", real_run)
    return result, calls


_HERMETIC_PROBE = """
import importlib, json, sys
report = {
    "path": list(sys.path),
    "base_prefix": sys.base_prefix,
    "prefix": sys.prefix,
    "site_loaded": "site" in sys.modules,
    "sitecustomize_loaded": "sitecustomize" in sys.modules,
}
module = importlib.import_module("generate_contract_drift_inventory")
report["gen_file"] = module.__file__
report["gen_marker"] = getattr(module, "HOSTILE_MARKER", None)
try:
    importlib.import_module("cdg_namespace_probe")
    report["namespace_import"] = "imported"
except ModuleNotFoundError:
    report["namespace_import"] = "missing"
print(json.dumps(report))
"""


def _hermetic_probe(tmp_path: Path, *, env_extra: dict[str, str] | None = None) -> dict[str, Any]:
    """Run a probe script through the real launcher + interpreter flags with
    only the bundle on the injected path, returning its introspection JSON."""
    src = Path(ratchet.__file__).parents[1]
    bundle_scripts = tmp_path / "bundle" / "scripts"
    bundle_scripts.mkdir(parents=True, exist_ok=True)
    for rel in ("check_contract_drift_ratchet.py", "generate_contract_drift_inventory.py"):
        (bundle_scripts / rel).write_bytes((src / "scripts" / rel).read_bytes())
    probe = tmp_path / "probe.py"
    probe.write_text(_HERMETIC_PROBE, encoding="utf-8")
    cwd = tmp_path / "empty-cwd"
    cwd.mkdir(exist_ok=True)
    launcher = cwd / "launcher.py"
    launcher.write_bytes(ratchet.HERMETIC_LAUNCHER)
    env = {
        "CDG_EXECUTED_LAUNCHER_SHA256": ratchet._sha256_bytes(ratchet.HERMETIC_LAUNCHER),
        "HOME": str(cwd),
        "PATH": "/usr/bin:/bin",
        **(env_extra or {}),
    }
    proc = subprocess.run(
        [sys.executable, *ratchet.ANALYZER_FLAGS, str(launcher), str(bundle_scripts), str(probe)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    report["bundle_scripts"] = str(bundle_scripts)
    return report


def _hostile_module(directory: Path, marker: Path, label: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "generate_contract_drift_inventory.py").write_text(
        f'HOSTILE_MARKER = "{label}"\nopen(r"{marker}", "w").write("{label}")\n',
        encoding="utf-8",
    )


def test_pr_mode_uses_analyzer_from_resolved_base_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, base, head = _hermetic_repo(tmp_path)
    result, calls = _recorded_hermetic_pr(repo, base, head, monkeypatch)
    assert result["passing"] and result["status"] == "pass"
    # The executed analyzer authority is the resolved base SHA, and every
    # bundle file is extracted from that SHA (never the head or the caller
    # worktree).
    assert result["execution"]["analyzer_sha"] == base
    assert result["execution"]["base_sha"] == base
    assert result["execution"]["head_sha"] == head
    extractions = [
        call["argv"][-1]
        for call in calls
        if "show" in call["argv"]
        and call["argv"][-1].endswith(tuple(ratchet.ANALYZER_BUNDLE_FILES))  # fmt: skip
    ]
    assert extractions == [f"{base}:{rel}" for rel in ratchet.ANALYZER_BUNDLE_FILES]

    # A base whose manifest digest does not match the base blob fails closed
    # before any analyzer byte executes.
    def forge(inventory: dict[str, Any]) -> None:
        inventory["accepted_authority"]["analyzer_bundle"]["files"][0]["sha256"] = "0" * 64

    forged_repo, forged_base, forged_head = _hermetic_repo(
        tmp_path / "forged", mutate_base_inventory=forge
    )
    with pytest.raises(ValueError, match="authority analyzer binding differs from exact ref"):
        ratchet._run_hermetic_pr(
            repo_root=forged_repo,
            base_ref=forged_base,
            head_ref=forged_head,
            inventory_path=_HERMETIC_INVENTORY,
        )


def test_pr_mode_resolves_base_and_head_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo, base, head = _hermetic_repo(tmp_path)
    result, calls = _recorded_hermetic_pr(repo, base, head, monkeypatch)
    assert result["passing"]
    # Exactly one resolution per ref; every subsequent git read binds the
    # already-resolved full SHA (no mutable-ref reread).
    resolves = [call["argv"] for call in calls if "rev-parse" in call["argv"]]
    assert [argv[-1] for argv in resolves] == [f"{base}^{{commit}}", f"{head}^{{commit}}"]
    shows = [call["argv"][-1] for call in calls if "show" in call["argv"]]
    assert shows and all(spec.startswith((f"{base}:", f"{head}:")) for spec in shows)
    # Abbreviated or symbolic refs are rejected outright.
    for hostile_ref in (base[:12], "HEAD", "main", base.upper()):
        with pytest.raises(ValueError, match="full lowercase 40-hex"):
            ratchet._run_hermetic_pr(
                repo_root=repo,
                base_ref=hostile_ref,
                head_ref=head,
                inventory_path=_HERMETIC_INVENTORY,
            )


def test_hermetic_launcher_uses_explicit_interpreter_I_S_and_empty_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, base, head = _hermetic_repo(tmp_path)
    result, calls = _recorded_hermetic_pr(repo, base, head, monkeypatch)
    analyzer = next(call for call in calls if call["argv"][0] == sys.executable)
    # Explicitly resolved interpreter (absolute path), with -I and -S flags.
    assert os.path.isabs(analyzer["argv"][0])
    assert analyzer["argv"][1:4] == list(ratchet.ANALYZER_FLAGS)
    assert {"-I", "-S"} <= set(analyzer["argv"][1:4])
    # Empty temporary working directory: at spawn the cwd holds only the
    # digest-pinned launcher, and the caller worktree is not the cwd.
    assert analyzer["cwd_listing"] == ["launcher.py"]
    assert Path(analyzer["cwd"]).name.startswith("cdg-cwd-")
    assert Path(analyzer["cwd"]).resolve() != Path.cwd().resolve()
    assert result["execution"]["working_directory"] == "<empty-temporary-directory>"
    assert result["execution"]["interpreter_flags"] == list(ratchet.ANALYZER_FLAGS)
    # Scrubbed environment manifest: exactly the declared keys, nothing
    # ambient.
    assert set(analyzer["env"]) == {
        "CDG_AUTHORITY_ROOT",
        "CDG_EXECUTED_LAUNCHER_SHA256",
        "CDG_TRUSTED_BUNDLE",
        "HOME",
        "PATH",
    }
    assert analyzer["env"]["HOME"] == analyzer["cwd"]
    launcher_sha = result["execution"]["launcher_sha256"]
    assert launcher_sha == ratchet._sha256_bytes(ratchet.HERMETIC_LAUNCHER)
    assert analyzer["env"]["CDG_EXECUTED_LAUNCHER_SHA256"] == launcher_sha


def test_hermetic_sys_path_contains_only_base_bundle_hashed_dependencies_and_stdlib(
    tmp_path: Path,
):
    report = _hermetic_probe(tmp_path)
    entries = report["path"]
    # The bundle is the first entry; the rest is the standard library. The
    # accepted dependency manifest is empty, so no other roots may appear.
    assert entries[0] == report["bundle_scripts"]
    assert "" not in entries
    repo_root = str(Path(ratchet.__file__).parents[1])
    for entry in entries[1:]:
        assert not entry.startswith(repo_root)
        assert "site-packages" not in entry
        assert entry.startswith((report["base_prefix"], report["prefix"])) or entry.endswith(".zip")
    assert report["gen_file"].startswith(report["bundle_scripts"])


def test_stdlib_only_or_base_pinned_hashed_dependencies(tmp_path: Path):
    # The ratified analyzer bundle is stdlib-only: its dependency manifest is
    # exactly empty and the execution contract pins interpreter flags and the
    # launcher digest.
    authority = _accepted_authority()
    bundle, files = ratchet._bundle_metadata(authority)
    assert bundle["dependencies"] == []
    assert bundle["interpreter_flags"] == list(ratchet.ANALYZER_FLAGS)
    assert [item["path"] for item in files] == list(ratchet.ANALYZER_BUNDLE_FILES)
    assert all(ratchet.SHA256_RE.fullmatch(item["sha256"]) for item in files)
    # A dependency claim without base-pinned hash identity is not accepted in
    # any form: the contract admits no unhashed dependency records at all.
    for hostile_dependencies in (
        [{"name": "requests"}],
        [{"name": "requests", "version": "2.32.0"}],
        [{"name": "requests", "version": "2.32.0", "sha256": "0" * 64}],
    ):
        hostile = _accepted_authority()
        hostile["analyzer_bundle"]["dependencies"] = hostile_dependencies
        with pytest.raises(ValueError, match="execution contract mismatch"):
            ratchet._bundle_metadata(hostile)


def test_head_cannot_replace_base_analyzer_authority(tmp_path: Path):
    marker = tmp_path / "hostile-analyzer-executed.txt"
    hostile_checker = (
        f'open(r"{marker}", "w").write("executed")\nraise SystemExit("hostile analyzer executed")\n'
    )
    repo, base, head = _hermetic_repo(
        tmp_path,
        head_writes={"scripts/check_contract_drift_ratchet.py": hostile_checker},
    )
    result = ratchet._run_hermetic_pr(
        repo_root=repo, base_ref=base, head_ref=head, inventory_path=_HERMETIC_INVENTORY
    )
    # The measuring authority stays the base SHA and the head's replacement
    # analyzer never executes; tampering with a pinned bundle surface is
    # itself fail-closed drift.
    assert result["execution"]["analyzer_sha"] == base
    assert (result["passing"], result["status"]) == (False, "fail")
    assert "bundle digest mismatch" in result["error"]
    assert not marker.exists()


def test_hostile_head_module_shadowing_is_not_executed(tmp_path: Path):
    marker = tmp_path / "hostile-shadow-executed.txt"
    # The head plants a same-name module at the repository root — outside the
    # pinned bundle file set — hoping the analyzer import resolves to it.
    repo, base, head = _hermetic_repo(
        tmp_path,
        head_writes={
            "generate_contract_drift_inventory.py": (
                f'open(r"{marker}", "w").write("shadow")\n'
                'raise RuntimeError("hostile head shadow executed")\n'
            )
        },
    )
    result = ratchet._run_hermetic_pr(
        repo_root=repo, base_ref=base, head_ref=head, inventory_path=_HERMETIC_INVENTORY
    )
    assert result["passing"] is True
    assert result["execution"]["analyzer_sha"] == base
    assert not marker.exists()


def test_hostile_head_sitecustomize_is_not_executed(tmp_path: Path):
    marker = tmp_path / "sitecustomize-executed.txt"
    # Repo layer: a head-introduced sitecustomize is never extracted (it is
    # not a pinned bundle member).
    repo, base, head = _hermetic_repo(
        tmp_path,
        head_writes={
            "scripts/sitecustomize.py": f'open(r"{marker}", "w").write("site")\n',
            "sitecustomize.py": f'open(r"{marker}", "w").write("site")\n',
        },
    )
    result = ratchet._run_hermetic_pr(
        repo_root=repo, base_ref=base, head_ref=head, inventory_path=_HERMETIC_INVENTORY
    )
    assert result["passing"] is True
    assert not marker.exists()
    # Interpreter layer: even a sitecustomize planted directly inside the
    # bundle directory (sys.path[0]) is not imported because -S disables site
    # processing entirely.
    probe_dir = tmp_path / "probe"
    bundle_scripts = probe_dir / "bundle" / "scripts"
    bundle_scripts.mkdir(parents=True)
    (bundle_scripts / "sitecustomize.py").write_text(
        f'open(r"{marker}", "w").write("site")\n', encoding="utf-8"
    )
    report = _hermetic_probe(probe_dir)
    assert report["site_loaded"] is False
    assert report["sitecustomize_loaded"] is False
    assert not marker.exists()


def test_hostile_caller_module_shadowing_is_not_executed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    marker = tmp_path / "caller-shadow-executed.txt"
    hostile_cwd = tmp_path / "caller-cwd"
    _hostile_module(hostile_cwd, marker, "caller")
    monkeypatch.chdir(hostile_cwd)
    repo, base, head = _hermetic_repo(tmp_path)
    result = ratchet._run_hermetic_pr(
        repo_root=repo, base_ref=base, head_ref=head, inventory_path=_HERMETIC_INVENTORY
    )
    # The caller's working directory is not the analyzer cwd and -I removes
    # implicit cwd entries: the hostile caller module never executes.
    assert result["passing"] is True
    assert not marker.exists()
    report = _hermetic_probe(tmp_path / "probe")
    assert str(hostile_cwd) not in report["path"]
    assert report["gen_marker"] is None


def test_editable_or_global_project_install_is_not_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    marker = tmp_path / "global-install-executed.txt"
    fake_site = tmp_path / "venv" / "lib" / "site-packages"
    _hostile_module(fake_site, marker, "editable-install")
    # Caller-level: editable/global install env vars never propagate into the
    # scrubbed analyzer environment.
    monkeypatch.setenv("PYTHONPATH", str(fake_site))
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "venv"))
    monkeypatch.setenv("PYTHONUSERBASE", str(tmp_path / "venv"))
    repo, base, head = _hermetic_repo(tmp_path)
    result, calls = _recorded_hermetic_pr(repo, base, head, monkeypatch)
    assert result["passing"] is True
    analyzer = next(call for call in calls if call["argv"][0] == sys.executable)
    assert "PYTHONPATH" not in analyzer["env"]
    assert "VIRTUAL_ENV" not in analyzer["env"]
    assert not marker.exists()
    # Interpreter-level: even with user-site variables set, -I -S never adds
    # a site-packages root.
    report = _hermetic_probe(
        tmp_path / "probe", env_extra={"PYTHONUSERBASE": str(tmp_path / "venv")}
    )
    assert not any("site-packages" in entry for entry in report["path"])
    assert report["gen_file"].startswith(report["bundle_scripts"])
    assert report["gen_marker"] is None


def test_hostile_same_version_global_package_is_not_imported(tmp_path: Path):
    marker = tmp_path / "same-version-executed.txt"
    hostile_root = tmp_path / "global-site"
    _hostile_module(hostile_root, marker, "same-version-global")
    # The hostile global package carries the same module name (and any
    # version string it likes): with PYTHONPATH pointing straight at it, -I
    # still ignores it and the bundle module wins.
    report = _hermetic_probe(tmp_path / "probe", env_extra={"PYTHONPATH": str(hostile_root)})
    assert str(hostile_root) not in report["path"]
    assert report["gen_file"].startswith(report["bundle_scripts"])
    assert report["gen_marker"] is None
    assert not marker.exists()


def test_hostile_namespace_package_contribution_is_not_blended(tmp_path: Path):
    marker = tmp_path / "namespace-executed.txt"
    hostile_root = tmp_path / "namespace-site"
    # A namespace-package portion shadowing the bundle module name, plus a
    # hostile namespace-only package.
    portion = hostile_root / "generate_contract_drift_inventory"
    portion.mkdir(parents=True)
    (portion / "extra.py").write_text(f'open(r"{marker}", "w").write("ns")\n', encoding="utf-8")
    probe_pkg = hostile_root / "cdg_namespace_probe"
    probe_pkg.mkdir()
    (probe_pkg / "inner.py").write_text("VALUE = 1\n", encoding="utf-8")
    report = _hermetic_probe(tmp_path / "probe", env_extra={"PYTHONPATH": str(hostile_root)})
    # The namespace contribution is never blended: the file module from the
    # bundle wins, and the namespace-only package is unimportable.
    assert report["gen_file"].startswith(report["bundle_scripts"])
    assert report["namespace_import"] == "missing"
    assert str(hostile_root) not in report["path"]
    assert not marker.exists()


def test_hostile_pth_injector_is_not_executed(tmp_path: Path):
    marker = tmp_path / "pth-executed.txt"
    hostile_site = tmp_path / "pth-site"
    hostile_site.mkdir()
    (hostile_site / "inject.pth").write_text(
        f'import os; open(r"{marker}", "w").write("pth")\n', encoding="utf-8"
    )
    probe_dir = tmp_path / "probe"
    # Even a .pth planted inside the bundle directory itself is inert: .pth
    # execution is a site-module feature and -S disables site processing.
    bundle_scripts = probe_dir / "bundle" / "scripts"
    bundle_scripts.mkdir(parents=True)
    (bundle_scripts / "inject.pth").write_text(
        f'import os; open(r"{marker}", "w").write("pth")\n', encoding="utf-8"
    )
    report = _hermetic_probe(probe_dir, env_extra={"PYTHONPATH": str(hostile_site)})
    assert report["site_loaded"] is False
    assert str(hostile_site) not in report["path"]
    assert not marker.exists()


def test_caller_pythonpath_cannot_replace_base_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    marker = tmp_path / "pythonpath-executed.txt"
    hostile_root = tmp_path / "pythonpath-authority"
    _hostile_module(hostile_root, marker, "pythonpath")
    (hostile_root / "check_contract_drift_ratchet.py").write_text(
        f'open(r"{marker}", "w").write("pythonpath-checker")\n', encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(hostile_root))
    repo, base, head = _hermetic_repo(tmp_path)
    result, calls = _recorded_hermetic_pr(repo, base, head, monkeypatch)
    assert result["passing"] is True
    assert result["execution"]["analyzer_sha"] == base
    analyzer = next(call for call in calls if call["argv"][0] == sys.executable)
    assert "PYTHONPATH" not in analyzer["env"]
    assert not marker.exists()
    # Even if PYTHONPATH leaked into the child environment, -I ignores it.
    report = _hermetic_probe(tmp_path / "probe", env_extra={"PYTHONPATH": str(hostile_root)})
    assert report["gen_file"].startswith(report["bundle_scripts"])
    assert report["gen_marker"] is None
    assert not marker.exists()


def test_analyzer_dependency_manifest_is_identical_for_both_trees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, base, head = _hermetic_repo(tmp_path)
    result, calls = _recorded_hermetic_pr(repo, base, head, monkeypatch)
    # One extraction measures both trees: each pinned bundle file is read
    # exactly once, from the base SHA, and the (empty) dependency manifest is
    # bound into the execution record for the whole run.
    assert result["execution"]["dependencies"] == []
    extractions = [
        call["argv"][-1]
        for call in calls
        if "show" in call["argv"]
        and call["argv"][-1].endswith(tuple(ratchet.ANALYZER_BUNDLE_FILES))  # fmt: skip
    ]
    assert extractions == [f"{base}:{rel}" for rel in ratchet.ANALYZER_BUNDLE_FILES]
    bundle_metadata, _files = ratchet._bundle_metadata(_accepted_authority())
    assert result["execution"]["base_bundle_sha256"] == ratchet._sha256_bytes(
        ratchet._canonical_json_bytes(bundle_metadata)
    )
    # A head proposing a different dependency manifest is a binding change
    # and fails closed.
    monkeypatch.setattr(ratchet, "validate_accepted_authority", lambda *a, **k: {})
    hostile = _accepted_authority()
    hostile["analyzer_bundle"]["dependencies"] = [
        {"name": "requests", "sha256": "0" * 64, "version": "2.32.0"}
    ]
    with pytest.raises(ValueError, match="immutable authority bindings changed"):
        ratchet.compare_accepted_authorities(_accepted_authority(), hostile, repo_root=repo)


def test_dependency_hash_or_version_mismatch_fails_closed(tmp_path: Path):
    authority = copy.deepcopy(_accepted_authority())
    authority["analyzer_bundle"]["files"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="bundle digest mismatch"):
        ratchet._validate_bundle(authority, Path(ratchet.__file__).parents[1])
    versioned = copy.deepcopy(_accepted_authority())
    versioned["analyzer_bundle"]["dependencies"] = [{"name": "requests", "version": "2.0"}]
    with pytest.raises(ValueError, match="execution contract mismatch"):
        ratchet._bundle_metadata(versioned)
    flags = copy.deepcopy(_accepted_authority())
    flags["analyzer_bundle"]["interpreter_flags"] = ["-I"]
    with pytest.raises(ValueError, match="execution contract mismatch"):
        ratchet._bundle_metadata(flags)
    launcher = copy.deepcopy(_accepted_authority())
    launcher["analyzer_bundle"]["launcher_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="execution contract mismatch"):
        ratchet._bundle_metadata(launcher)


def test_undeclared_import_fails_closed(tmp_path: Path):
    root = tmp_path / "extraction"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts/module_under_test.py").write_text(
        "import importlib\nimportlib.import_module(computed_name)\n",
        encoding="utf-8",
    )
    with pytest.raises(gen.AuthorityClosureError, match="dynamic repository import is forbidden"):
        gen._python_import_edges(root, "scripts/module_under_test.py")
    (root / "scripts/missing_target.py").write_text(
        "import scripts.never_written_module\n", encoding="utf-8"
    )
    with pytest.raises(gen.AuthorityClosureError, match="repository-local import is unavailable"):
        gen._python_import_edges(root, "scripts/missing_target.py")


# ------- VAL-CDG-006: no item replacement; mathematically exact set diffs


def _swap_baseline_entry(paths: dict[str, Path], alias: str, list_key: str, old: str, new: str):
    doc = json.loads(paths[alias].read_text())
    entries = doc[list_key]
    entries[entries.index(old)] = new
    _write_json(paths[alias], doc)


def _pr_result_and_recomputed_sets(
    paths: dict[str, Path], repo: Path, base: str
) -> tuple[dict, set[str], set[str]]:
    """PR-mode result plus independently recomputed base/head ID-set diffs."""
    base_docs = {
        alias: json.loads(
            subprocess.run(
                ["git", "-C", str(repo), "show", f"{base}:{rel_path}"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        for alias, (rel_path, _k) in gen.BASELINE_SPECS.items()
    }
    head_docs = {alias: json.loads(paths[alias].read_text()) for alias in base_docs}
    base_ids = set(gen.collect_ids(base_docs))
    head_ids = set(gen.collect_ids(head_docs))
    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    return result, base_ids - head_ids, head_ids - base_ids


def test_pr_mode_fails_same_count_sdk_literal_replacement(tmp_path: Path):
    # Replace one python SDK literal with a distinct literal: total and every
    # category count are unchanged, yet admission fails and names both sides.
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)
    _swap_baseline_entry(paths, "verify", "python_sdk_drift", "b", "b-replacement")
    result, removed, added = _pr_result_and_recomputed_sets(paths, repo, base)
    assert not result["passing"]
    deltas = result["pr_delta"]["counts"]
    assert all(entry["delta"] == 0 for entry in deltas.values())
    assert result["pr_delta"]["increased"] == []
    # Independently recomputed set differences match the JSON exactly.
    assert added == {"python_sdk_drift:b-replacement"}
    assert removed == {"python_sdk_drift:b"}
    assert result["pr_delta"]["new_entries"] == sorted(added)
    issues = result["integrity"]["issues"]
    assert any("python_sdk_drift:b-replacement" in issue for issue in issues)
    assert any("python_sdk_drift:b" in issue for issue in issues)
    # Accepted-authority layer: a same-count literal method edit rehashes the
    # record ID, which cannot exist in the immutable cohort.
    authority = _accepted_authority()
    record = next(
        item
        for item in authority["canonical_artifacts"]["original_cohort"]["original_records"]
        if item["category"] == "python_sdk_drift"
    )
    record["exact_historical_literal_record"] = record["exact_historical_literal_record"].replace(
        record["method"], "BREW", 1
    )
    with pytest.raises(ValueError, match="ID payload .*mismatch"):
        ratchet._validate_original_cohort(authority["canonical_artifacts"]["original_cohort"])


def test_pr_mode_fails_same_count_route_literal_replacement(tmp_path: Path):
    # Replace one route path literal with a distinct path: same counts, fail.
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)
    _swap_baseline_entry(paths, "routes", "missing_in_spec", "m2", "/api/replaced")
    result, removed, added = _pr_result_and_recomputed_sets(paths, repo, base)
    assert not result["passing"]
    assert all(entry["delta"] == 0 for entry in result["pr_delta"]["counts"].values())
    assert added == {"missing_in_spec:/api/replaced"}
    assert removed == {"missing_in_spec:m2"}
    assert result["pr_delta"]["new_entries"] == sorted(added)
    issues = result["integrity"]["issues"]
    assert any("missing_in_spec:/api/replaced" in issue for issue in issues)
    assert any("missing_in_spec:m2" in issue for issue in issues)
    # A parity path-literal replacement is equally identity tamper.
    (tmp_path / "parity").mkdir()
    parity_paths, parity_repo, parity_base = _seed(tmp_path / "parity", program=RED_PROGRAM)
    _swap_baseline_entry(parity_paths, "parity", "missing_from_both_sdks", "p1", "p1-swapped")
    parity_result, parity_removed, parity_added = _pr_result_and_recomputed_sets(
        parity_paths, parity_repo, parity_base
    )
    assert not parity_result["passing"]
    assert parity_added == {"missing_from_both_sdks:p1-swapped"}
    assert parity_removed == {"missing_from_both_sdks:p1"}


def test_pr_mode_fails_cross_category_original_record_replacement(tmp_path: Path):
    # Move one unit from missing_in_spec to orphaned_in_spec: total is
    # unchanged but the growing category and both exact IDs are named.
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)
    routes = json.loads(paths["routes"].read_text())
    routes["missing_in_spec"].remove("m2")
    routes["orphaned_in_spec"].append("o-cross")
    _write_json(paths["routes"], routes)
    result, removed, added = _pr_result_and_recomputed_sets(paths, repo, base)
    assert not result["passing"]
    deltas = result["pr_delta"]["counts"]
    assert sum(entry["delta"] for entry in deltas.values()) == 0
    assert deltas["routes_missing_in_spec"]["delta"] == -1
    assert deltas["routes_orphaned_in_spec"]["delta"] == 1
    assert result["pr_delta"]["increased"] == ["routes_orphaned_in_spec"]
    assert added == {"orphaned_in_spec:o-cross"}
    assert removed == {"missing_in_spec:m2"}
    reasons = result["pr_delta"]["unexplained_increase"]
    assert any("orphaned_in_spec:o-cross" in reason for reason in reasons)
    # Same entry text flipped across categories is still a new identity: the
    # per-category ID is the unit of identity, not the literal alone.
    (tmp_path / "flip").mkdir()
    flip_paths, flip_repo, flip_base = _seed(tmp_path / "flip", program=RED_PROGRAM)
    flip_routes = json.loads(flip_paths["routes"].read_text())
    flip_routes["missing_in_spec"].remove("m2")
    flip_routes["orphaned_in_spec"].append("m2")
    _write_json(flip_paths["routes"], flip_routes)
    flip_result, flip_removed, flip_added = _pr_result_and_recomputed_sets(
        flip_paths, flip_repo, flip_base
    )
    assert not flip_result["passing"]
    assert flip_added == {"orphaned_in_spec:m2"}
    assert flip_removed == {"missing_in_spec:m2"}
    # Accepted-authority layer: swapping a disposition row's category to
    # another category is identity tamper.
    authority = _accepted_authority()
    row = authority["active_inventory"][0]
    row["category"] = next(
        category for category in ratchet.ACCEPTED_CATEGORIES if category != row["category"]
    )
    with pytest.raises(ValueError, match="identity or genesis is invalid"):
        ratchet.validate_accepted_authority(authority, repo_root=Path(ratchet.__file__).parents[1])


def _projection_case(mutate) -> tuple[dict, dict]:
    """Deep-copied real cohort with `mutate(projection_records)` applied and
    projection digests relinked, so validation reaches semantic checks."""
    inventory = json.loads(
        (Path(ratchet.__file__).parent / "baselines/contract_drift_inventory.json").read_text()
    )
    cohort = inventory["accepted_authority"]["canonical_artifacts"]["original_cohort"]
    projection = cohort["operation_projection"]
    mutate(projection["records"])
    for record in projection["records"]:
        record["record_sha256"] = ratchet._sha256_bytes(
            ratchet._canonical_json_bytes(
                {key: value for key, value in record.items() if key != "record_sha256"}
            )
        )
    projection["record_digest_set_sha256"] = ratchet._digest_set(
        "cdg-operation-projection-record-digest-set-v1",
        [record["record_sha256"] for record in projection["records"]],
        "record_sha256_values",
    )
    return cohort, projection


def test_projection_many_to_one_dedup_cannot_remove_original_record(tmp_path: Path):
    # The ratified projection contains 66 operations shared by multiple
    # originals; deduplicating any shared operation to one membership record
    # (654 memberships) breaks the 655 bijection and fails closed.
    inventory = json.loads(
        (Path(ratchet.__file__).parent / "baselines/contract_drift_inventory.json").read_text()
    )
    records = inventory["accepted_authority"]["canonical_artifacts"]["original_cohort"][
        "operation_projection"
    ]["records"]
    by_operation: dict[tuple, list[int]] = {}
    for index, record in enumerate(records):
        key = tuple(
            sorted((edge["method"], edge["normalized_path"]) for edge in record["operation_edges"])
        )
        by_operation.setdefault(key, []).append(index)
    shared = next(indexes for indexes in by_operation.values() if len(indexes) > 1)
    assert sum(1 for indexes in by_operation.values() if len(indexes) > 1) == 66

    def dedup(projection_records: list[dict]) -> None:
        del projection_records[shared[1]]

    cohort, _projection = _projection_case(dedup)
    with pytest.raises(ValueError, match="655 membership records"):
        ratchet._validate_original_cohort(cohort)

    # Padding the count back with a duplicate membership for the surviving
    # original is caught by the bijection check.
    def dedup_and_pad(projection_records: list[dict]) -> None:
        clone = copy.deepcopy(projection_records[shared[0]])
        projection_records[shared[1]] = clone

    padded, _projection = _projection_case(dedup_and_pad)
    with pytest.raises(ValueError, match="does not biject"):
        ratchet._validate_original_cohort(padded)


def test_projection_one_to_many_edge_omission_cannot_hide_original_or_operation(tmp_path: Path):
    inventory = json.loads(
        (Path(ratchet.__file__).parent / "baselines/contract_drift_inventory.json").read_text()
    )
    records = inventory["accepted_authority"]["canonical_artifacts"]["original_cohort"][
        "operation_projection"
    ]["records"]
    multi_index = next(
        index for index, record in enumerate(records) if len(record["operation_edges"]) > 1
    )

    # Omitting one witnessed edge from a multi-edge membership departs from
    # the ratified projection witness (digest-set pin) and, arithmetically,
    # from the 666-edge cardinality; either way it fails closed.
    def omit_edge(projection_records: list[dict]) -> None:
        projection_records[multi_index]["operation_edges"].pop()

    omitted, _projection = _projection_case(omit_edge)
    with pytest.raises(ValueError, match="record-digest-set mismatch|cardinality mismatch"):
        ratchet._validate_original_cohort(omitted)

    # Fanning one original into multiple membership records is a membership
    # count/bijection failure, not silent growth.
    def fan_out(projection_records: list[dict]) -> None:
        clone = copy.deepcopy(projection_records[multi_index])
        clone["operation_edges"] = [clone["operation_edges"][0]]
        projection_records[multi_index]["operation_edges"] = projection_records[multi_index][
            "operation_edges"
        ][1:]
        projection_records.append(clone)

    fanned, _projection = _projection_case(fan_out)
    with pytest.raises(ValueError, match="655 membership records"):
        ratchet._validate_original_cohort(fanned)


def test_projection_method_refinement_cannot_replace_original_record(tmp_path: Path):
    # "Refining" a projected edge's method (GET -> POST) is a digest-set
    # departure from the ratified projection witness, never a re-keyed
    # original: the 655 original-record IDs are computed from category +
    # literal only, so no projection edit can mint or replace an identity.
    inventory = json.loads(
        (Path(ratchet.__file__).parent / "baselines/contract_drift_inventory.json").read_text()
    )
    records = inventory["accepted_authority"]["canonical_artifacts"]["original_cohort"][
        "original_records"
    ]
    expected_ids = sorted(record["original_record_id"] for record in records)

    def refine(projection_records: list[dict]) -> None:
        edge = projection_records[0]["operation_edges"][0]
        edge["method"] = "POST" if edge["method"] != "POST" else "PUT"

    refined, projection = _projection_case(refine)
    assert projection["record_digest_set_sha256"] != ratchet.PROJECTION_RECORD_SET_SHA256
    with pytest.raises(ValueError, match="record-digest-set mismatch"):
        ratchet._validate_original_cohort(refined)
    # The original-ID universe is untouched by the attempted refinement.
    assert sorted(record["original_record_id"] for record in refined["original_records"]) == expected_ids  # fmt: skip
    # An inferred method on a path-level original record remains forbidden.
    authority = _accepted_authority()
    path_record = next(
        record
        for record in authority["canonical_artifacts"]["original_cohort"]["original_records"]
        if record["category"] == "routes_missing_in_spec"
    )
    path_record["method"] = "GET"
    with pytest.raises(ValueError, match="carries a method"):
        ratchet._validate_original_cohort(authority["canonical_artifacts"]["original_cohort"])


def test_pr_mode_language_metadata_change_does_not_replace_identity(tmp_path: Path):
    # sdk_language is category-derived provenance, not identity: it is not an
    # input to the original-record ID hash.
    authority = _accepted_authority()
    record = next(
        item
        for item in authority["canonical_artifacts"]["original_cohort"]["original_records"]
        if item["category"] == "python_sdk_drift"
    )
    payload = {
        "category": record["category"],
        "exact_historical_literal_record": record["exact_historical_literal_record"],
        "schema": "cdg-original-record-id-v1",
    }
    raw = ratchet._canonical_json_bytes(payload)
    assert record["original_record_id"] == f"cdg1:{ratchet._sha256_bytes(raw)}"
    assert "sdk_language" not in payload
    # Flipping the language annotation neither creates a new identity nor
    # hides a replacement: the canonical artifact binding rejects the edit
    # wholesale (separately versioned projection witnesses cannot alter the
    # added/removed sets either).
    flipped = copy.deepcopy(authority)
    flipped_record = next(
        item
        for item in flipped["canonical_artifacts"]["original_cohort"]["original_records"]
        if item["category"] == "python_sdk_drift"
    )
    flipped_record["sdk_language"] = ["typescript"]
    assert flipped_record["original_record_id"] == record["original_record_id"]
    with pytest.raises(ValueError, match="canonical artifact or category binding mismatch"):
        ratchet.validate_accepted_authority(flipped, repo_root=Path(ratchet.__file__).parents[1])
    # And a language-only mutation inside the cohort validator is a literal
    # shape violation, not a new/removed ID.
    cohort = copy.deepcopy(authority["canonical_artifacts"]["original_cohort"])
    target = next(
        item for item in cohort["original_records"] if item["category"] == "python_sdk_drift"
    )
    target["sdk_language"] = []
    with pytest.raises(ValueError, match="language"):
        ratchet._validate_sdk_provenance(
            copy.deepcopy(_accepted_authority()["canonical_artifacts"]["sdk_provenance"]),
            ratchet._validate_original_cohort(cohort),
        )


def test_pr_mode_exact_original_record_diagnostics_are_sorted_complete_and_untruncated(
    tmp_path: Path,
):
    # 26 added + 1 removed in one PR: every ID appears, sorted, no caps.
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)
    added_entries = [f"bulk-{index:03d}" for index in range(26)]
    verify = json.loads(paths["verify"].read_text())
    verify["python_sdk_drift"].remove("a")
    verify["python_sdk_drift"].extend(added_entries)
    _write_json(paths["verify"], verify)
    result, removed, added = _pr_result_and_recomputed_sets(paths, repo, base)
    assert not result["passing"]
    expected_added = sorted(f"python_sdk_drift:{entry}" for entry in added_entries)
    assert added == set(expected_added)
    assert removed == {"python_sdk_drift:a"}
    # JSON diagnostics equal the independently recomputed sets: complete,
    # sorted, unique, untruncated (no ellipses/caps/count-only summaries).
    assert result["pr_delta"]["new_entries"] == expected_added
    assert len(result["pr_delta"]["new_entries"]) == len(set(result["pr_delta"]["new_entries"]))
    reasons = result["pr_delta"]["unexplained_increase"]
    for item_id in expected_added:
        assert any(item_id in reason for reason in reasons)
    assert not any("..." in reason for reason in reasons)
    stale = [issue for issue in result["integrity"]["issues"] if "python_sdk_drift:a" in issue]
    assert stale
    # Per-category delta arithmetic is exact.
    assert result["pr_delta"]["counts"]["verify_python_sdk_drift"]["delta"] == 25


def test_pr_mode_passes_strict_original_record_subset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # A strict subset in two categories (with matching resolutions) passes
    # while the program schedule stays honestly red.
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)
    verify = json.loads(paths["verify"].read_text())
    verify["python_sdk_drift"].remove("b")
    _write_json(paths["verify"], verify)
    routes = json.loads(paths["routes"].read_text())
    routes["missing_in_spec"].remove("m2")
    _write_json(paths["routes"], routes)

    def resolve(inventory: dict) -> None:
        for item in inventory["items"]:
            if item["id"] in {"python_sdk_drift:b", "missing_in_spec:m2"}:
                item["status"] = "resolved"
                item["resolved_on"] = "2026-07-16"

    _edit_inventory(paths, resolve)
    result, removed, added = _pr_result_and_recomputed_sets(paths, repo, base)
    assert result["passing"] and not result["program_passing"]
    assert added == set() and removed == {"missing_in_spec:m2", "python_sdk_drift:b"}
    assert result["pr_delta"]["increased"] == []
    assert result["pr_delta"]["new_entries"] == []
    assert result["pr_delta"]["counts"]["verify_python_sdk_drift"]["delta"] == -1
    assert result["pr_delta"]["counts"]["routes_missing_in_spec"]["delta"] == -1
    # Accepted-authority layer: a global+per-category strict subset head
    # passes with exact removed IDs and empty added IDs. The committed head
    # is that subset relative to its reconstructed all-active genesis base,
    # reached through comparator-verified paydown waves.
    root = Path(ratchet.__file__).parents[1]
    authority = _accepted_authority()
    summary = ratchet.validate_accepted_authority(authority, repo_root=root)
    live = set(summary["live_original_record_ids"])
    genesis_summary = ratchet.validate_accepted_authority(
        _genesis_authority(authority), repo_root=root
    )
    waves = _replay_committed_paydown(authority, repo_root=root, monkeypatch=monkeypatch)
    replayed_removed = sorted(record_id for _digest, ids in waves for record_id in ids)
    expected_removed = sorted(set(genesis_summary["active_original_record_ids"]) - live)
    assert replayed_removed == expected_removed
    assert len(expected_removed) == 367


# ---- VAL-CDG-008: exact UTC week arithmetic, non-backdated final as-of


def _program_dict(program: dict) -> dict:
    return {**program, "start_date": date.fromisoformat(program["start_date"])}


def test_program_preserves_655_2026_04_17_ten_percent():
    baseline = json.loads(
        (Path(ratchet.__file__).parent / "baselines/contract_drift_program.json").read_text()
    )
    assert baseline["start_total_items"] == 655
    assert baseline["start_date"] == "2026-04-17"
    assert baseline["weekly_reduction"] == 0.10
    assert baseline.get("grace_weeks", 0) == 0
    program = ratchet._load_program(
        Path(ratchet.__file__).parent / "baselines/contract_drift_program.json"
    )
    assert program["start_date"] == date(2026, 4, 17)
    assert program["start_total_items"] == 655
    assert program["weekly_reduction"] == 0.1
    assert program["grace_weeks"] == 0


def test_target_uses_exact_integer_floor_recurrence():
    # T(0)=655, T(n+1) = 9*T(n)//10 — the exact integer recurrence chain.
    expected = [655, 589, 530, 477, 429, 386, 347, 312, 280, 252, 226, 203, 182, 163, 146, 131]
    chain = [ratchet._target_after_weeks(655, 0.1, weeks) for weeks in range(16)]
    assert chain == expected
    # Divergence witnesses: one-shot binary-float flooring first differs at
    # week 6 (348 vs 347) and nearest-rounding differs at week 1 (590 vs
    # 589) — the recurrence matches neither.
    import math

    assert math.floor(655 * 0.9**6) == 348 and chain[6] == 347
    assert round(655 * 0.9**1) == 590 and chain[1] == 589
    # Monotone and eventually zero; never negative.
    long_chain = [ratchet._target_after_weeks(655, 0.1, weeks) for weeks in range(100)]
    assert all(later <= earlier for earlier, later in zip(long_chain, long_chain[1:]))
    assert long_chain[-1] == 0 and min(long_chain) == 0
    # Only exact integer recurrences are accepted — arbitrary multipliers
    # (which would need binary-float multiplication) fail closed.
    with pytest.raises(ValueError, match="exact integer recurrence"):
        ratchet._target_after_weeks(655, 0.25, 1)


def test_utc_boundary_controls_week_increment(tmp_path: Path):
    # Fixed dates around the start pin the integer week boundaries exactly:
    # days 0/6 -> week 0; days 7/13 -> week 1; day 14 -> week 2.
    program = {
        "start_date": "2026-04-17",
        "start_total_items": 655,
        "weekly_reduction": 0.1,
        "grace_weeks": 0,
    }
    start = date(2026, 4, 17)
    for offset, expected_weeks, expected_target in (
        (0, 0, 655),
        (6, 0, 655),
        (7, 1, 589),
        (13, 1, 589),
        (14, 2, 530),
    ):
        classes = ratchet._evaluate_classes(
            _program_dict(program), [], start + timedelta(days=offset)
        )
        assert classes[0]["weeks_elapsed"] == expected_weeks
        assert classes[0]["target_max"] == expected_target


def test_before_start_and_partial_week_do_not_decay(tmp_path: Path):
    program = {
        "start_date": "2026-04-17",
        "start_total_items": 655,
        "weekly_reduction": 0.1,
        "grace_weeks": 0,
    }
    # Before the start date the clock clamps to zero (never negative weeks).
    for as_of in (date(2026, 4, 10), date(2026, 4, 16), date(2025, 12, 31)):
        classes = ratchet._evaluate_classes(_program_dict(program), [], as_of)
        assert classes[0]["weeks_elapsed"] == 0
        assert classes[0]["target_max"] == 655
    # A partial week (1-6 days) never decays the target.
    for days in range(1, 7):
        classes = ratchet._evaluate_classes(
            _program_dict(program), [], date(2026, 4, 17) + timedelta(days=days)
        )
        assert classes[0]["target_max"] == 655


def test_local_timezone_cannot_change_default_as_of(monkeypatch: pytest.MonkeyPatch):
    root = Path(ratchet.__file__).parents[1]
    inventory = root / "scripts/baselines/contract_drift_inventory.json"
    source = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    utc_today = datetime.now(UTC).date().isoformat()
    observed: dict[str, str] = {}
    for timezone_name in ("Pacific/Kiritimati", "Etc/GMT+11", "UTC"):
        monkeypatch.setenv("TZ", timezone_name)
        time.tzset()
        try:
            result = ratchet.build_accepted_result(
                mode="program",
                repo_root=root,
                inventory_path=inventory,
                source_sha=source,
            )
        finally:
            monkeypatch.setenv("TZ", "UTC")
            time.tzset()
        observed[timezone_name] = result["program"]["as_of"]
    # Kiritimati (UTC+14) local "today" is ahead of UTC and GMT+11 local
    # "today" is behind around midnight, yet the default as-of is the UTC
    # date in every process timezone.
    assert set(observed.values()) == {utc_today}


def test_malformed_or_future_live_as_of_fails_closed():
    root = Path(ratchet.__file__).parents[1]
    inventory = root / "scripts/baselines/contract_drift_inventory.json"
    source = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    future = (datetime.now(UTC).date() + timedelta(days=2)).isoformat()
    result = ratchet.build_accepted_result(
        mode="program",
        repo_root=root,
        inventory_path=inventory,
        as_of=future,
        source_sha=source,
    )
    assert (result["status"], result["passing"]) == ("fail", False)
    assert result["error_code"] == "future_as_of"
    for malformed in ("07/31/2026", "2026-7-1x", "yesterday", "2026-13-40"):
        malformed_result = ratchet.build_accepted_result(
            mode="program",
            repo_root=root,
            inventory_path=inventory,
            as_of=malformed,
            source_sha=source,
        )
        assert (malformed_result["status"], malformed_result["passing"]) == ("fail", False)
        assert malformed_result["error_code"] == "invalid_as_of"


def test_program_mode_exit_matches_truthful_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Red: 10 open items against a decayed target -> exit 1 under --strict,
    # with passing == (total <= target) truthfully false.
    paths, repo, cohort = _seed(tmp_path, program=RED_PROGRAM)
    red = _result(paths, "2026-07-16", repo=repo, cohort=cohort)
    assert red["passing"] is False
    assert red["current"]["total_items"] == 10
    assert red["current"]["total_items"] > red["target"]["max_open_items"]
    monkeypatch.setattr(
        sys, "argv", _argv(paths, repo, cohort, "--strict", "--as-of", "2026-07-16")
    )
    assert ratchet.main() == 1
    # Green: same inventory on day zero -> exit 0, passing truthfully true.
    monkeypatch.setattr(
        sys, "argv", _argv(paths, repo, cohort, "--strict", "--as-of", "2026-04-17")
    )
    assert ratchet.main() == 0
    green = _result(paths, "2026-04-17", repo=repo, cohort=cohort)
    assert green["passing"] is (green["current"]["total_items"] <= green["target"]["max_open_items"])  # fmt: skip
    assert green["passing"] is True


# - VAL-CDG-009 (ratchet side): PR admission is independent of program red


def test_unchanged_pr_passes_while_program_is_red(tmp_path: Path):
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)
    program = _result(paths, "2026-07-16", repo=repo, cohort=base)
    assert not program["passing"]  # trajectory is intentionally red
    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    # The unchanged PR passes on its own signal; the red program is reported
    # separately and cannot mask or replace the PR-delta verdict.
    assert result["passing"] is True
    assert result["program_passing"] is False
    assert result["pr_delta"]["counts"] == {
        key: {"base": value, "head": value, "delta": 0}
        for key, value in {
            "verify_python_sdk_drift": 2,
            "verify_typescript_sdk_drift": 3,
            "routes_missing_in_spec": 2,
            "routes_orphaned_in_spec": 1,
            "sdk_missing_from_both": 2,
        }.items()
    }
    assert result["pr_delta"]["unexplained_increase"] == []


def test_shrinking_pr_passes_while_program_is_red(tmp_path: Path):
    paths, repo, base = _seed(tmp_path, program=RED_PROGRAM)
    verify = json.loads(paths["verify"].read_text())
    verify["typescript_sdk_drift"].remove("z")
    _write_json(paths["verify"], verify)

    def resolve(inventory: dict) -> None:
        for item in inventory["items"]:
            if item["id"] == "typescript_sdk_drift:z":
                item["status"] = "resolved"
                item["resolved_on"] = "2026-07-16"

    _edit_inventory(paths, resolve)
    program = _result(paths, "2026-07-16", repo=repo, cohort=base)
    assert not program["passing"]  # still red: 9 open vs decayed target
    result = _result(paths, "2026-07-16", repo=repo, cohort=base, mode="pr", base_ref=base)
    assert result["passing"] is True
    assert result["program_passing"] is False
    assert result["pr_delta"]["counts"]["verify_typescript_sdk_drift"]["delta"] == -1
    assert result["pr_delta"]["increased"] == []
    assert result["pr_delta"]["unexplained_increase"] == []


# ---------------------------------------------------------------------------
# VAL-CDG-013 / VAL-CDG-014: corrective bootstrap chronology and authority
# transitions.  These tests bind the checked-in enforcement surfaces only
# (analyzer modules, trusted bootstrap module, settlement helper, review-queue
# policy) plus disposable git fixtures, so they hold on a fresh clone of main.
# ---------------------------------------------------------------------------

import ast as _ast
import importlib.util as _importlib_util

import scripts.settle_tier4_pr as settle
import scripts.tier4_merge_train as merge_train
from aragora.cli.commands import review_queue

_REPO_ROOT = Path(ratchet.__file__).resolve().parents[1]
_BOOTSTRAP_PATH = _REPO_ROOT / ".github/workflows/contract_drift_trusted_bootstrap.py"


def _load_bootstrap():
    name = "contract_drift_trusted_bootstrap"
    if name in sys.modules:
        return sys.modules[name]
    spec = _importlib_util.spec_from_file_location(name, _BOOTSTRAP_PATH)
    assert spec and spec.loader
    module = _importlib_util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bootstrap = _load_bootstrap()

_EXPECTED_GUARD_V2_PATCH_SHA256 = "3f4d656bc4678997899508f92c649b845655145351dc36d8a47e5112d84a004b"
_EXPECTED_GUARD_V2_PATCH_PATHS = (
    ".github/workflows/contract-drift-governance.yml",
    "scripts/baselines/contract_drift_inventory.json",
    "scripts/check_contract_drift_ratchet.py",
    "tests/scripts/test_check_contract_drift_ratchet.py",
)
_EXPECTED_GUARD_V2_RESPONSE = (
    (55, 166, ".github/workflows/contract-drift-governance.yml"),
    (1, 0, "scripts/baselines/contract_drift_inventory.json"),
    (428, 9, "scripts/check_contract_drift_ratchet.py"),
    (78, 3, "scripts/generate_contract_drift_inventory.py"),
    (99, 0, "tests/scripts/test_check_contract_drift_ratchet.py"),
    (26, 0, "tests/scripts/test_contract_drift_workflow.py"),
)
_EXPECTED_GUARD_V2_DELTA = 865


def _decision_351_patch_blob(repo: Path) -> bytes:
    candidates = [
        _git_bytes(repo, "cat-file", "blob", oid)
        for oid in _object_ids(repo, "blob")
        if int(_git_text(repo, "cat-file", "-s", oid)) > 5_000_000
    ]
    patches = [blob for blob in candidates if blob.startswith(b"diff --git ")]
    assert len(patches) == 1
    return patches[0]


def _mission_guard_v2_patch() -> Path | None:
    runtime_settings = os.environ.get("FACTORY_RUNTIME_SETTINGS_PATH")
    if runtime_settings is None:
        return None
    patch = Path(runtime_settings).resolve().parent / "library/guard-v2.patch"
    return patch if patch.is_file() else None


OLD_H2_PIN_SHA = "017ce1d7a4024f3001858d2385cd153c1ffc8bb2"
CORRECTIVE_BASE_SHA = "d5c9df5cea5719404b54c34fdb62a89daf65a92f"
PR_9346_FACT = {
    "actor": "scarmani",
    "head_sha": "83a7c59169ea238e0439a27fbb80d3cb3ce7e916",
    "merge_sha": "14d1ef53e23c5466c0491ed93f72752944c78cd4",
    "merged_at": "2026-07-16T18:30:08Z",
    "pr": 9346,
}
PR_9320_FACT = {
    "actor": "scarmani",
    "head_sha": "aba6b14c94eca3a9c825b1a303ea67684d5f8daa",
    "merge_sha": "0b28f68b9f4d204ae14814169093723ea84c1364",
    "merged_at": "2026-07-16T20:00:49Z",
    "pr": 9320,
}


def _real_inventory() -> dict:
    return json.loads((_REPO_ROOT / gen.DEFAULT_INVENTORY).read_bytes())


def _real_authority() -> dict:
    return _real_inventory()["accepted_authority"]


def _bound_authority_bytes(binding: dict[str, Any]) -> bytes:
    authority_root = os.environ.get("CDG_AUTHORITY_ROOT")
    if authority_root:
        return (Path(authority_root) / binding["path"]).read_bytes()
    return (_REPO_ROOT / binding["path"]).read_bytes()


@pytest.fixture(autouse=True)
def _authenticate_committed_authority_while_checker_is_dirty(
    monkeypatch: pytest.MonkeyPatch,
):
    authority = _real_authority()
    checker_binding = next(
        binding
        for binding in authority["analyzer_bundle"]["files"]
        if binding["path"] == "scripts/check_contract_drift_ratchet.py"
    )
    live_checker = _REPO_ROOT / checker_binding["path"]
    if hashlib.sha256(live_checker.read_bytes()).hexdigest() == checker_binding["sha256"]:
        yield
        return
    with tempfile.TemporaryDirectory(prefix="cdg-committed-authority-") as temp:
        root = Path(temp)
        for binding in authority["analyzer_bundle"]["files"]:
            target = root / binding["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                subprocess.check_output(
                    ["git", "-C", str(_REPO_ROOT), "show", f"HEAD:{binding['path']}"]
                )
            )
        monkeypatch.setenv("CDG_AUTHORITY_ROOT", str(root))
        yield


def _relink_fact(schema: str, value: dict) -> dict:
    return {"fact": value, "sha256": ratchet._fact_digest(schema, value)}


def _relink_authority_manifest(authority: dict) -> None:
    manifest = {key: value for key, value in authority.items() if key != "manifest_sha256"}
    authority["manifest_sha256"] = ratchet._sha256_bytes(ratchet._canonical_json_bytes(manifest))


def _settle_pr_view(
    head: str,
    *,
    comments: list[dict] | None = None,
    settlement_success: bool = True,
    head_committed_at: str = "2026-07-20T00:00:00Z",
) -> dict:
    statuses = []
    if settlement_success:
        statuses.append({"context": settle.HUMAN_SETTLEMENT_CONTEXT, "state": "SUCCESS"})
    return {
        "headRefOid": head,
        "state": "OPEN",
        "isDraft": False,
        "mergeStateStatus": "CLEAN",
        "commitStatuses": statuses,
        "statusCheckRollup": [],
        "comments": comments or [],
        "reviews": [],
        "commits": [{"committedDate": head_committed_at}],
    }


def _settle_packet(pr: int) -> dict:
    return {
        "not_ready": [str(pr)],
        "entries": [
            {
                "pr_number": pr,
                "status": "human_preapproval_required",
                "requires_human_risk_settlement": True,
                "counted_reviewer_ids": ["reviewer-a", "reviewer-b"],
                "dogfood_evidence": [{"kind": "dogfood", "url": "https://example.test"}],
            }
        ],
    }


def _settlement_comment(pr: int, head: str, *, created_at: str = "2026-07-21T00:00:00Z") -> dict:
    return {
        "body": settle._settlement_comment_template(pr=pr, head=head),
        "authorAssociation": "OWNER",
        "author": {"login": "operator"},
        "createdAt": created_at,
        "url": "https://example.test/comment",
    }


def test_historical_9346_exact_disposition_cannot_supply_forward_authority():
    # Exactly one historical_nonconforming disposition, bound to the exact
    # head/merge/time/actor facts, in both the checked-in bootstrap policy and
    # the live accepted authority.
    expected = bootstrap.EXPECTED_HISTORICAL_NONCONFORMING
    assert [entry["pr"] for entry in expected] == [9346, 9320]
    assert expected[0] == PR_9346_FACT
    transition = _real_authority()["transition"]
    matches = [e for e in transition["historical_nonconforming"] if e["pr"] == 9346]
    assert matches == [PR_9346_FACT]
    # The disposition record carries only the five legacy fact fields: no
    # authority, chronology, settlement, quorum, or no-admin evidence fields,
    # and no compliance/800-LOC claim of any kind.
    assert set(PR_9346_FACT) == {"actor", "head_sha", "merge_sha", "merged_at", "pr"}
    assert not (set(PR_9346_FACT) & ratchet.AUTHORITY_FIELDS)
    # Tampering with the disposition (e.g. duplicating it to widen authority)
    # breaks the accepted authority manifest digest: legacy facts cannot be
    # edited into forward authority.
    authority = _real_authority()
    authority["transition"]["historical_nonconforming"].append(dict(PR_9346_FACT))
    with pytest.raises(ValueError, match="manifest digest mismatch"):
        ratchet.validate_accepted_authority(authority, repo_root=_REPO_ROOT)
    # Even a digest-relinked mutation is rejected by the first-authority
    # admission: the transition facts are pinned exactly.
    policy = bootstrap.BootstrapPolicy()
    forged = copy.deepcopy(_real_authority())
    forged["transition"]["historical_nonconforming"][0]["pr"] = 9345
    _relink_authority_manifest(forged)
    with pytest.raises(bootstrap.BootstrapError, match="self-authorization"):
        bootstrap._validate_first_authority(Path("."), "f" * 40, forged, policy)


def test_historical_9320_exact_disposition_cannot_supply_forward_authority():
    expected = bootstrap.EXPECTED_HISTORICAL_NONCONFORMING
    assert expected[1] == PR_9320_FACT
    transition = _real_authority()["transition"]
    matches = [e for e in transition["historical_nonconforming"] if e["pr"] == 9320]
    assert matches == [PR_9320_FACT]
    # 9320 is not a future merge: it is strictly ordered after the 9346 merge
    # on the historical record and its facts are frozen alongside it.
    assert PR_9320_FACT["merged_at"] > PR_9346_FACT["merged_at"]
    assert set(PR_9320_FACT) == {"actor", "head_sha", "merge_sha", "merged_at", "pr"}
    assert not (set(PR_9320_FACT) & ratchet.AUTHORITY_FIELDS)
    # Removing the 9320 disposition (consuming the delegation without a
    # trace) is equally rejected by the pinned transition facts.
    policy = bootstrap.BootstrapPolicy()
    forged = copy.deepcopy(_real_authority())
    del forged["transition"]["historical_nonconforming"][1]
    _relink_authority_manifest(forged)
    with pytest.raises(bootstrap.BootstrapError, match="self-authorization"):
        bootstrap._validate_first_authority(Path("."), "f" * 40, forged, policy)
    # A legacy fact object is not a settlement identity: the settlement
    # preconditions reject a head bound to the historical 9320 head SHA when
    # the live PR head differs.
    gate = settle.evaluate_tier4_settlement_preconditions(
        pr=9320,
        expected_head=PR_9320_FACT["head_sha"],
        pr_view=_settle_pr_view("a" * 40),
        merge_packet=_settle_packet(9320),
        required_checks=[{"name": "x", "state": "SUCCESS"}],
    )
    assert not gate["ok"]
    assert any("head mismatch" in blocker for blocker in gate["blockers"])


def test_corrective_bootstrap_is_bounded_and_descends_from_current_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # The corrective transition proof must equal the exact bounded git
    # interval start..corrective with a positive commit count.
    result = _boundary_result(tmp_path, monkeypatch, "corrective_bootstrap")
    assert result["status"] == "pass"
    assert result["predicates"]["corrective_bootstrap"]["checks"] == [
        "accepted_stage1_closure",
        "stage2_verifier_chronology",
        "corrective_transition",
    ]
    assert result["predicates"]["corrective_bootstrap"]["proven"] is True

    def wrong_interval(payloads: dict) -> None:
        proof = payloads["corrective_bootstrap"]
        fact = proof["corrective_transition"]["fact"]
        fact = dict(fact, commit_count=fact["commit_count"] + 7)
        proof["corrective_transition"] = _relink_fact(
            "contract-drift-corrective-transition-fact-v1", fact
        )

    broken = _boundary_result(
        tmp_path / "interval", monkeypatch, "corrective_bootstrap", mutate=wrong_interval
    )
    assert broken["status"] == "fail"
    assert "exact git interval" in broken["error"]
    # Descent is enforced by the chronology validator: the corrective SHA must
    # be a strict descendant of the interval start on the fixture main line.
    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path / "descent")
    side = subprocess.check_output(
        ["git", "-C", str(repo), "commit-tree", f"{start_sha}^{{tree}}", "-m", "orphan"],
        text=True,
    ).strip()
    with pytest.raises(ValueError, match="not strictly ordered"):
        ratchet._validate_boundary_chronology(
            {
                "boundaries": [{"boundary": "corrective_bootstrap", "sha": side}],
                "boundary": "corrective_bootstrap",
                "end_sha": side,
                "schema": "contract-drift-boundary-chronology-v1",
                "start_sha": start_sha,
            },
            repo_root=repo,
            boundary="corrective_bootstrap",
            start_sha=start_sha,
            end_sha=side,
            operation_log=[],
        )


def test_corrective_guard_v2_sequence_is_h2_then_h3_repin_merge_then_empty_h4(tmp_path: Path):
    repo = _decision_351_repo(tmp_path)
    facts = _decision_351_facts(repo)
    base = facts["base"]
    h1 = facts["h1"]
    h2 = facts["h2"]
    h3 = facts["h3"]
    repin = facts["repin"]
    h4 = facts["h4"]
    absorption = facts["absorption"]
    merge = facts["merge"]

    assert base["oid"] == "8f1dd9684a3bf311e65b40de2ab35415612cc051"
    assert h2["oid"] == "d4ab26e4b30b7f65956b4cdd9d738837b78ca4a3"
    assert h3["oid"] == "1722a6145c0c23a2c1c0d20be5ed1329bb01d666"
    assert repin["oid"] == "5080b125d3c9595efdca020db5e60266e01ac9c5"
    assert h4["oid"] == "f50902a19bdc6cce7049da87212dc27759f727a0"
    assert absorption["oid"] == "967b1c82a285affbd191b57bdaf08512d6e6e3f7"
    assert merge["oid"] == "d3e45fafe6dd04508882935c813f6896abc859d7"

    assert h1["parents"][1] == base["oid"]
    assert h2["parents"] == (h1["oid"],)
    assert h3["parents"] == (h2["oid"],)
    assert h4["parents"] == (h3["oid"],)
    assert h4["tree"] == h3["tree"]
    assert absorption["parents"] == (h4["oid"], repin["oid"])
    assert merge["parents"] == (repin["oid"],)
    assert merge["tree"] == absorption["tree"]
    ordered = (base, h1, h2, h3, repin, h4, absorption, merge)
    assert [record["committed_at"] for record in ordered] == sorted(
        record["committed_at"] for record in ordered
    )
    assert "#9679" in repin["subject"]
    assert "Decision-351 absorption" in absorption["subject"]
    assert "#9645" in merge["subject"]
    assert bootstrap.ANALYZER_SOURCE_SHA == h3["oid"]
    assert bootstrap.BootstrapPolicy().transition_base_sha == CORRECTIVE_BASE_SHA
    for binding in _real_authority()["analyzer_bundle"]["files"]:
        live = hashlib.sha256(_bound_authority_bytes(binding)).hexdigest()
        assert live == binding["sha256"]


def test_corrective_guard_v2_binds_exact_patch_and_six_file_687_178_865_response(tmp_path: Path):
    repo = _decision_351_repo(tmp_path)
    facts = _decision_351_facts(repo)
    patch_blob = _decision_351_patch_blob(repo)
    immutable_diff = _git_bytes(
        repo,
        "diff",
        "--no-ext-diff",
        "--binary",
        "--full-index",
        facts["h2"]["oid"],
        facts["h3"]["oid"],
    )
    assert patch_blob == immutable_diff
    assert hashlib.sha256(patch_blob).hexdigest() == _EXPECTED_GUARD_V2_PATCH_SHA256

    mission_patch = _mission_guard_v2_patch()
    if mission_patch is not None:
        assert mission_patch.read_bytes() == patch_blob

    patch_paths = tuple(
        _git_text(
            repo,
            "diff",
            "--name-only",
            facts["h2"]["oid"],
            facts["h3"]["oid"],
        ).splitlines()
    )
    assert patch_paths == _EXPECTED_GUARD_V2_PATCH_PATHS

    response = tuple(
        (int(additions), int(deletions), path)
        for additions, deletions, path in (
            line.split("\t", 2)
            for line in _git_text(
                repo,
                "diff",
                "--numstat",
                facts["base"]["oid"],
                facts["h3"]["oid"],
            ).splitlines()
        )
    )
    assert response == _EXPECTED_GUARD_V2_RESPONSE
    additions = sum(record[0] for record in response)
    deletions = sum(record[1] for record in response)
    delta = additions + deletions
    assert (len(response), additions, deletions, delta) == (6, 687, 178, 865)
    assert delta == _EXPECTED_GUARD_V2_DELTA and delta > 800
    # The census (contract L76) admits the guard-v2 delta as authenticated
    # governed evidence; because 865 exceeds the paydown cap, the atom can
    # never be admitted as a core/extended paydown fact (max_pr_delta <= 800
    # in _validate_sdk_paydown), only on the corrective proof plane.
    census = ratchet._validate_governed_prs(
        _governed_pr_resource("1" * 40, "2" * 40),
        authenticated_pr_changes={9999: {"additions": additions, "deletions": deletions}},
        repo_root=tmp_path,
        operation_log=[],
    )
    assert census[0]["authenticated_pr_delta"] == delta
    # The corrective proof plane it rides instead carries no PR-delta field at
    # all: its exact closed field set is the bounded-transition proof.
    with pytest.raises(ValueError, match="corrective_bootstrap proof"):
        ratchet._validate_corrective_bootstrap(
            {"max_pr_delta": delta},
            {},
            authority={},
            repo_root=tmp_path,
            operation_log=[],
        )
    # The guard-v2 patch product is pinned by digest in the historical H3
    # bootstrap policy; the live analyzer bytes are pinned by the accepted
    # authority manifest, which authorized rotations rebind in place.
    for binding in _real_authority()["analyzer_bundle"]["files"]:
        live = hashlib.sha256(_bound_authority_bytes(binding)).hexdigest()
        assert live == binding["sha256"]


def test_corrective_guard_v2_old_h2_and_017ce1d7_evidence_are_historical_only(
    tmp_path: Path,
):
    # The superseded H2 pin head and its evidence cannot be posted, settled,
    # or reused: no live enforcement surface references it.
    live_surfaces = [
        Path(ratchet.__file__),
        Path(gen.__file__),
        _BOOTSTRAP_PATH,
        _REPO_ROOT / ".github/workflows/contract_drift_trusted_launcher.py",
        _REPO_ROOT / ".github/workflows/contract-drift-trusted-bootstrap.yml",
        _REPO_ROOT / ".github/workflows/contract-drift-trusted-bootstrap-manifest.json",
        _REPO_ROOT / ".github/workflows/contract-drift-governance.yml",
        Path(settle.__file__),
        Path(review_queue.__file__),
        Path(merge_train.__file__),
    ]
    for surface in live_surfaces:
        text = surface.read_text(encoding="utf-8")
        assert OLD_H2_PIN_SHA not in text, surface
        assert OLD_H2_PIN_SHA[:12] not in text, surface
    # The accepted analyzer source is the H3 product, not the old H2 pin.
    repo = _decision_351_repo(tmp_path)
    facts = _decision_351_facts(repo)
    assert bootstrap.ANALYZER_SOURCE_SHA != OLD_H2_PIN_SHA
    assert bootstrap.ANALYZER_SOURCE_SHA == facts["h3"]["oid"]
    h2_source = subprocess.check_output(
        [
            "git",
            "-C",
            str(repo),
            "show",
            f"{facts['h2']['oid']}:scripts/check_contract_drift_ratchet.py",
        ],
        text=True,
    )
    current_source = Path(ratchet.__file__).read_text(encoding="utf-8")
    zero_residue_rule = (
        'raise ValueError(f"live baseline keys outside immutable original cohort: {residue}")'
    )
    assert zero_residue_rule in h2_source
    assert zero_residue_rule not in current_source
    assert "residue - tolerated" in current_source
    # Settlement identity is head-exact: evidence bound to the old head can
    # never authorize the live head (exact-head token mismatch).
    stale = _settlement_comment(9645, OLD_H2_PIN_SHA)
    diagnostics = settle.authorization_diagnostics(
        _settle_pr_view("b" * 40, comments=[stale]),
        pr=9645,
        head="b" * 40,
        permission_checker=lambda _login: True,
    )
    (diagnostic,) = diagnostics["authorization_diagnostics"]
    assert diagnostic["accepted"] is False
    assert "exact head is missing" in diagnostic["rejection_reasons"]


def test_constants_pr_precedes_matcher_repair_and_fulfills_no_val_cdg_assertion():
    # The constants layer: exact eight-prefix tuple, policy version, tier, and
    # the byte-identical merge-train mirror.
    expected_prefixes = (
        "scripts/check_contract_drift_ratchet.py",
        "scripts/generate_contract_drift_inventory.py",
        "scripts/baselines/contract_drift_inventory.json",
        "scripts/sdk_path_normalize.py",
        "scripts/baselines/internal_route_prefixes.json",
        "scripts/baselines/contract_drift_program.json",
        "scripts/check_sdk_parity.py",
        "scripts/validate_openapi_routes.py",
    )
    assert review_queue.CONTRACT_DRIFT_AUTHORITY_PREFIXES == expected_prefixes
    assert review_queue.CONTRACT_DRIFT_AUTHORITY_POLICY_VERSION == 1
    assert review_queue.CONTRACT_DRIFT_AUTHORITY_TIER == 4
    assert merge_train.CONTRACT_DRIFT_AUTHORITY_PREFIXES == expected_prefixes
    assert merge_train.CONTRACT_DRIFT_AUTHORITY_POLICY_VERSION == 1
    assert merge_train.CONTRACT_DRIFT_AUTHORITY_TIER == 4
    assert merge_train.CONTRACT_DRIFT_AUTHORITY_CANONICAL_SOURCE == (
        "aragora.cli.commands.review_queue.CONTRACT_DRIFT_AUTHORITY_PREFIXES"
    )
    # Precedence: the matcher and classifier consume the constants (the tier-4
    # prefix set embeds them), never the reverse.
    for prefix in expected_prefixes:
        assert prefix in review_queue.TIER_4_PREFIXES
    # The constants layer fulfills no VAL-CDG assertion: neither constants
    # module contains a VAL-CDG ownership marker.
    for module in (review_queue, merge_train):
        assert "VAL-CDG" not in Path(module.__file__).read_text(encoding="utf-8")


def test_matcher_repair_precedes_stage1_and_fulfills_no_full_val_cdg_assertion():
    # Boundary-aware matcher semantics: exact file match, no suffix bleed, and
    # directory semantics only for explicit directory prefixes.
    prefixes = review_queue.CONTRACT_DRIFT_AUTHORITY_PREFIXES
    assert review_queue._matches_prefix("scripts/check_contract_drift_ratchet.py", prefixes)
    assert not review_queue._matches_prefix("scripts/check_contract_drift_ratchet.pyx", prefixes)
    assert not review_queue._matches_prefix("scripts/check_contract_drift_ratchet.py.bak", prefixes)  # fmt: skip
    assert not review_queue._matches_prefix("scripts/check_contract_drift_ratchet.py/child", prefixes)  # fmt: skip
    assert not review_queue._matches_prefix("x/scripts/check_contract_drift_ratchet.py", prefixes)
    directory_prefixes = tuple(p for p in review_queue.TIER_4_PREFIXES if p.endswith("/"))
    assert directory_prefixes, "tier-4 policy must contain directory prefixes"
    sample_dir = directory_prefixes[0]
    assert review_queue._matches_prefix(f"{sample_dir}nested/file.py", (sample_dir,))
    assert not review_queue._matches_prefix(f"{sample_dir[:-1]}x/file.py", (sample_dir,))
    # Stage 1 (the exact-ref classifier) consumes this matcher: the inventory
    # authority extraction imports the canonical review_queue module and calls
    # the matcher/classifier rather than re-implementing them.
    gen_source = Path(gen.__file__).read_text(encoding="utf-8")
    assert 'importlib.import_module("aragora.cli.commands.review_queue")' in gen_source
    assert "review_queue._matches_prefix" in gen_source
    assert "review_queue._classify_model_review_tier" in gen_source
    # The matcher layer fulfills no full VAL-CDG assertion.
    assert "VAL-CDG" not in Path(review_queue.__file__).read_text(encoding="utf-8")


def test_stage1_precedes_stage2_and_has_no_fulfills():
    # Stage 1 is the exact-ref closure/classifier/inventory matrix; Stage 2
    # (the boundary verifier) reruns it as a prerequisite: the Stage-1 matrix
    # is embedded in the Stage-2 module and its result manifest.
    assert ratchet.STAGE1_TEST_MATRIX == (
        "tests/governance/test_contract_drift_measurement_authority_tier.py",
        "tests/scripts/test_generate_contract_drift_inventory.py",
        "tests/scripts/test_tier4_merge_train.py",
    )
    assert "tests/scripts/test_check_contract_drift_ratchet.py" not in ratchet.STAGE1_TEST_MATRIX
    # Stage-1 surfaces own no boundary verifier: only the Stage-2 module
    # exposes the boundary predicate engine.
    assert hasattr(ratchet, "build_boundary_result")
    assert not hasattr(gen, "build_boundary_result")
    assert not hasattr(review_queue, "build_boundary_result")
    assert not hasattr(merge_train, "build_boundary_result")
    # Stage-1 layers carry no `fulfills` ownership claims.
    for module in (gen, review_queue, merge_train):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "fulfills" not in source, module.__name__


def test_stage2_precedes_corrective_and_is_sole_val_cdg_001_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # The corrective boundary proof binds the Stage-2 verifier digest and its
    # strict ordering after Stage 1; breaking either fails closed.
    def unordered(payloads: dict) -> None:
        proof = payloads["corrective_bootstrap"]
        fact = dict(proof["stage2_verifier_chronology"]["fact"], ordered_after_stage1=False)
        proof["stage2_verifier_chronology"] = _relink_fact(
            "contract-drift-stage2-verifier-chronology-fact-v1", fact
        )

    broken = _boundary_result(
        tmp_path / "unordered", monkeypatch, "corrective_bootstrap", mutate=unordered
    )
    assert broken["status"] == "fail"
    assert "Stage-2 verifier chronology" in broken["error"]

    def wrong_verifier(payloads: dict) -> None:
        proof = payloads["corrective_bootstrap"]
        fact = dict(proof["stage2_verifier_chronology"]["fact"], verifier_sha256="a" * 64)
        proof["stage2_verifier_chronology"] = _relink_fact(
            "contract-drift-stage2-verifier-chronology-fact-v1", fact
        )

    broken = _boundary_result(
        tmp_path / "verifier", monkeypatch, "corrective_bootstrap", mutate=wrong_verifier
    )
    assert broken["status"] == "fail"
    assert "Stage-2 verifier chronology" in broken["error"]
    # Sole VAL-CDG-001 ownership: the Stage-1 required-test matrix contains
    # none of the Stage-2 boundary predicates; the boundary engine (predicate
    # authentication, status, read-only operation log) lives only in Stage 2.
    assert not any("boundary" in name for name in ratchet.STAGE1_REQUIRED_TESTS)
    result = _boundary_result(tmp_path / "own", monkeypatch, "corrective_bootstrap")
    assert result["stage1_test_matrix"] == list(ratchet.STAGE1_TEST_MATRIX)
    assert result["status"] == "pass"
    assert result["operation_log"], "Stage-2 result must carry its own operation log"


def test_stage1_exact_ref_classifier_is_isolated_and_closure_complete():
    # One real end-to-end run of the standalone exact-ref classifier CLI over
    # an authority file at the current HEAD.
    head = subprocess.check_output(
        ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            "scripts/generate_contract_drift_inventory.py",
            "--classify-tier",
            "--changed-file",
            "scripts/check_contract_drift_ratchet.py",
            "--ref",
            head,
            "--json",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    output = json.loads(proc.stdout)
    assert output["tier"] == 4
    assert output["ref"] == head
    assert output["changed_file"] == "scripts/check_contract_drift_ratchet.py"
    assert output["matched_rule"] == output["merge_train_matched_rule"]
    assert output["schema"] == gen.AUTHORITY_CLASSIFICATION_SCHEMA
    assert len(output["authority_manifest_sha256"]) == 64
    # Closure completeness: the bound inventory summary carries the complete
    # 655-record authority closure with the ratified set digest.
    authority = output["inventory"]["accepted_authority"]
    assert authority["original_record_total"] == 655
    assert len(authority["original_records"]) == 655
    assert authority["original_record_id_set_sha256"] == ratchet.ORIGINAL_ID_SET_SHA256
    assert sorted(authority["original_record_ids"]) == sorted(
        record["original_record_id"] for record in authority["original_records"]
    )
    assert authority["sdk_provenance_record_total"] == 598
    assert len(authority["core_unit_ids"]) == 75
    assert len(authority["extended_unit_ids"]) == 523


def test_stage2_boundary_verifier_is_independent_and_status_truthful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Truthful tri-state on the same fixture family: pass, fail, blocked.
    passing = _boundary_result(tmp_path / "pass", monkeypatch, "corrective_bootstrap")
    assert (passing["status"], passing["passing"], passing["blocked_reason"]) == (
        "pass",
        True,
        None,
    )

    def falsify(payloads: dict) -> None:
        proof = payloads["corrective_bootstrap"]
        fact = dict(proof["accepted_stage1_closure"]["fact"], repo_file_count=41)
        proof["accepted_stage1_closure"] = _relink_fact(
            "contract-drift-stage1-closure-fact-v1", fact
        )

    failing = _boundary_result(
        tmp_path / "fail", monkeypatch, "corrective_bootstrap", mutate=falsify
    )
    assert failing["status"] == "fail" and failing["passing"] is False
    assert "closure" in failing["error"]
    blocked = _boundary_result(
        tmp_path / "blocked",
        monkeypatch,
        "corrective_bootstrap",
        release_immutability=False,
    )
    assert blocked["status"] == "blocked" and blocked["passing"] is False
    assert blocked["blocked_reason"]
    # Independence: the verifier accepts no caller-supplied evidence object;
    # its only evidence inputs are authenticated file paths and digests.
    parameters = set(inspect.signature(ratchet.build_boundary_result).parameters)
    assert "resources" not in parameters and "evidence" not in parameters
    assert {"repo_root", "schema_version", "boundary", "start_ref", "end_ref"} <= parameters


def test_stages_do_not_claim_later_sdk_route_publication_paydown_or_final_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # At the corrective boundary the chronology is exactly the one-boundary
    # prefix: claiming the route boundary at the corrective slot fails closed.
    def premature_route(payloads: dict) -> None:
        payloads["boundary_chronology"]["boundaries"][0]["boundary"] = "route_truth"

    broken = _boundary_result(
        tmp_path / "route", monkeypatch, "corrective_bootstrap", mutate=premature_route
    )
    assert broken["status"] == "fail"
    assert "exact selected ordered prefix" in broken["error"]
    # The corrective proof itself has no publication/paydown/zero facts: its
    # closed field set is exactly the three corrective predicates.
    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path / "fields")
    payloads = _boundary_payloads(
        "corrective_bootstrap",
        start_sha,
        boundary_shas["corrective_bootstrap"],
        boundary_shas,
        repo=repo,
    )
    corrective_fields = set(payloads["corrective_bootstrap"])
    assert corrective_fields == {
        "accepted_stage1_closure",
        "corrective_transition",
        "predicate",
        "proof_end_sha",
        "proof_for_boundary",
        "proof_start_sha",
        "schema",
        "stage2_verifier_chronology",
    }
    for later_fact in ("publication", "complete_paydown", "final_zero", "qualifying_paydown"):
        assert later_fact not in corrective_fields
    # Stage-1's own required-test names claim no later-boundary surface.
    for name in ratchet.STAGE1_REQUIRED_TESTS:
        for claim in ("publication", "paydown", "final_zero", "route_truth", "sdk_compat"):
            assert claim not in name


def test_constants_diff_is_constants_only_without_parser_dispatch_handler_or_settlement_change():
    # Targeted AST proof: the authority constants are literal tuple/int
    # assignments (pure data), not computed or behavioral code.
    tree = _ast.parse(Path(review_queue.__file__).read_text(encoding="utf-8"))
    bindings: dict[str, _ast.AST] = {}
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, _ast.Name):
                bindings[target.id] = node.value
        elif isinstance(node, _ast.AnnAssign) and isinstance(node.target, _ast.Name):
            if node.value is not None:
                bindings[node.target.id] = node.value
    prefixes_node = bindings["CONTRACT_DRIFT_AUTHORITY_PREFIXES"]
    assert isinstance(prefixes_node, _ast.Tuple)
    assert all(
        isinstance(element, _ast.Constant) and isinstance(element.value, str)
        for element in prefixes_node.elts
    )
    for name in (
        "CONTRACT_DRIFT_AUTHORITY_POLICY_VERSION",
        "CONTRACT_DRIFT_AUTHORITY_TIER",
    ):
        node = bindings[name]
        assert isinstance(node, _ast.Constant) and isinstance(node.value, int)
    # The mirror constant is likewise a literal string tuple (pure data), and
    # the mirror module carries no dispatch/handler/settlement machinery.
    train_tree = _ast.parse(Path(merge_train.__file__).read_text(encoding="utf-8"))
    train_bindings: dict[str, _ast.AST] = {}
    for node in _ast.walk(train_tree):
        if isinstance(node, _ast.Assign) and len(node.targets) == 1:
            if isinstance(node.targets[0], _ast.Name):
                train_bindings[node.targets[0].id] = node.value
        elif isinstance(node, _ast.AnnAssign) and isinstance(node.target, _ast.Name):
            if node.value is not None:
                train_bindings[node.target.id] = node.value
    mirror_node = train_bindings["CONTRACT_DRIFT_AUTHORITY_PREFIXES"]
    assert isinstance(mirror_node, _ast.Tuple)
    assert all(
        isinstance(element, _ast.Constant) and isinstance(element.value, str)
        for element in mirror_node.elts
    )
    train_source = Path(merge_train.__file__).read_text(encoding="utf-8")
    assert "import settle_tier4_pr" not in train_source
    assert settle.HUMAN_SETTLEMENT_CONTEXT not in train_source
    assert "add_subparsers" not in train_source
    assert "def handle_" not in train_source


def test_matcher_diff_is_boundary_matcher_only_without_parser_dispatch_handler_or_settlement_scope():  # noqa: E501
    # The matcher is a pure two-argument predicate over (path, prefixes).
    signature = inspect.signature(review_queue._matches_prefix)
    assert list(signature.parameters) == ["path", "prefixes"]
    matcher_source = inspect.getsource(review_queue._matches_prefix)
    for forbidden in ("subprocess", "settle", "argparse", "open(", "requests"):
        assert forbidden not in matcher_source
    # Boundary semantics only: the matcher changes classification exclusively
    # at path boundaries and leaves every non-matching shape untouched.
    prefixes = ("scripts/check_contract_drift_ratchet.py",)
    assert review_queue._matches_prefix(prefixes[0], prefixes)
    for hostile in (
        prefixes[0] + "x",
        prefixes[0] + ".orig",
        prefixes[0] + "/nested",
        "prefix/" + prefixes[0],
        prefixes[0].upper(),
    ):
        assert not review_queue._matches_prefix(hostile, prefixes), hostile
    # Settlement scope is untouched by the matcher layer: the settlement
    # helper never imports or calls the matcher.
    settle_source = Path(settle.__file__).read_text(encoding="utf-8")
    assert "_matches_prefix" not in settle_source


def test_matcher_parser_guard_is_behavioral_or_targeted_ast_not_whole_source_scan():
    # The Stage-1 policy proof is behavioral (import + call of the canonical
    # module) and targeted-AST (gen walks specific AST node types), never a
    # whole-source regex scan of the policy module.
    gen_source = Path(gen.__file__).read_text(encoding="utf-8")
    assert 'importlib.import_module("aragora.cli.commands.review_queue")' in gen_source
    assert "import ast" in gen_source
    # No whole-source scan: gen never reads the review_queue source as text.
    assert 'review_queue.py").read_text' not in gen_source
    assert 're.search' not in gen_source or "review_queue" not in gen_source.split("re.search")[1][:120]  # fmt: skip
    # Behavioral matcher guard: substring occurrences of an authority path do
    # not classify (a whole-source scan would match these).
    prefixes = review_queue.CONTRACT_DRIFT_AUTHORITY_PREFIXES
    assert not review_queue._matches_prefix(
        "docs/notes-about-scripts/check_contract_drift_ratchet.py.md", prefixes
    )
    assert not review_queue._matches_prefix("scripts/check_contract_drift_ratchet_py", prefixes)
    # Targeted AST support exists and is used for executable-node selection.
    assert isinstance(gen._is_type_checking_guard.__module__, str)
    guard_source = inspect.getsource(gen._is_type_checking_guard)
    assert "ast.Name" in guard_source


def test_classifier_uses_parity_without_accepted_authority():
    # The tier classification itself is path-policy-only: it needs no
    # accepted-authority manifest to classify an authority path as Tier 4.
    tier, tier_name, tier_reason = review_queue._classify_model_review_tier(
        ["scripts/check_contract_drift_ratchet.py"]
    )
    assert tier == 4
    assert isinstance(tier_name, str) and tier_name
    assert isinstance(tier_reason, str) and tier_reason
    # Parity: the canonical policy and the merge-train mirror agree rule by
    # rule for every authority prefix and for hostile near-misses.
    for path in review_queue.CONTRACT_DRIFT_AUTHORITY_PREFIXES:
        canonical = review_queue._matches_prefix(path, review_queue.CONTRACT_DRIFT_AUTHORITY_PREFIXES)  # fmt: skip
        mirrored = path in merge_train.CONTRACT_DRIFT_AUTHORITY_PREFIXES
        assert canonical and mirrored
    for hostile in (
        "scripts/check_contract_drift_ratchet.py.bak",
        "scripts/check_contract_drift_ratchet.pyx",
    ):
        assert not review_queue._matches_prefix(hostile, review_queue.CONTRACT_DRIFT_AUTHORITY_PREFIXES)  # fmt: skip
        assert hostile not in merge_train.CONTRACT_DRIFT_AUTHORITY_PREFIXES
    # Non-authority paths gain no Tier-4 lane from the classifier.
    low_tier, _low_name, _low_reason = review_queue._classify_model_review_tier(["README.md"])
    assert low_tier < 4


def test_corrective_uses_transition_check_not_ordinary_pr_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # A first transition must install the all-active genesis authority; the
    # committed authority now carries the catch-up paydown, so reconstruct
    # the genesis form for the synthetic transition head.
    original_doc = json.loads((_REPO_ROOT / gen.DEFAULT_INVENTORY).read_text(encoding="utf-8"))
    original_doc["accepted_authority"] = _genesis_authority(original_doc["accepted_authority"])
    genesis_inventory = json.dumps(original_doc)

    def drop_authority(inventory: dict) -> None:
        del inventory["accepted_authority"]

    # Transition admission: authority-less base + head installing the real
    # authority is admitted only through the dedicated transition check.
    repo, base, head = _hermetic_repo(
        tmp_path,
        mutate_base_inventory=drop_authority,
        head_writes={
            str(_HERMETIC_INVENTORY): genesis_inventory,
            "README.md": "corrective head\n",
        },
    )
    result, _calls = _recorded_hermetic_pr(repo, base, head, monkeypatch)
    assert result["transition"] is True
    assert result["error_code"] == "authority_transition_required"
    assert result["passing"] is True and result["status"] == "pass"
    assert result["proposed_transition"]["original_record_total"] == 655
    # Ordinary PR success is a different verdict shape: base authority
    # present yields a non-transition result with no transition error code.
    ordinary_repo, ordinary_base, ordinary_head = _hermetic_repo(tmp_path / "ordinary")
    ordinary, _ordinary_calls = _recorded_hermetic_pr(
        ordinary_repo, ordinary_base, ordinary_head, monkeypatch
    )
    assert ordinary["passing"] is True
    assert "transition" not in ordinary or ordinary.get("transition") is not True
    assert ordinary.get("error_code") != "authority_transition_required"
    assert ordinary["added_original_record_ids"] == []
    assert ordinary["removed_original_record_ids"] == []


def test_corrective_binds_canonical_cohort_and_provenance_artifact_bytes():
    # The accepted authority binds the exact ratified artifact byte pairs.
    summary = ratchet.validate_accepted_authority(_real_authority(), repo_root=_REPO_ROOT)
    assert summary["original_record_total"] == 655
    assert summary["sdk_provenance_record_total"] == 598
    bindings = _real_authority()["canonical_artifact_bindings"]
    assert bindings == [
        {
            "byte_length": ratchet.COHORT_ARTIFACT["byte_length"],
            "path": ratchet.COHORT_ARTIFACT["logical_path"],
            "sha256": ratchet.COHORT_ARTIFACT["sha256"],
        },
        {
            "byte_length": ratchet.PROVENANCE_ARTIFACT["byte_length"],
            "path": ratchet.PROVENANCE_ARTIFACT["logical_path"],
            "sha256": ratchet.PROVENANCE_ARTIFACT["sha256"],
        },
    ]
    assert ratchet.COHORT_ARTIFACT["byte_length"] == 1692125
    assert ratchet.COHORT_ARTIFACT["sha256"] == "565cd84a9a5d266f61b66bd7965e0a036e4817ef5fed32edb8c41a2dea6cc208"  # fmt: skip
    assert ratchet.PROVENANCE_ARTIFACT["byte_length"] == 898099
    assert ratchet.PROVENANCE_ARTIFACT["sha256"] == "21ae1c30200cda6df51dbca7053bbbbde6241ab78a73347b0fe5e4d2ed79f07f"  # fmt: skip
    # A single byte of artifact drift fails closed at the binding layer.
    tampered = _real_authority()
    records = tampered["canonical_artifacts"]["original_cohort"]["original_records"]
    records[0]["exact_historical_literal_record"] += "-tampered"
    with pytest.raises(ValueError, match="canonical artifact or category binding mismatch"):
        ratchet.validate_accepted_authority(tampered, repo_root=_REPO_ROOT)


def test_corrective_reconstructs_all_655_ids_and_598_provenance_records():
    cohort = _real_authority()["canonical_artifacts"]["original_cohort"]
    recomputed: list[str] = []
    for record in cohort["original_records"]:
        payload = ratchet._canonical_json_bytes(
            {
                "category": record["category"],
                "exact_historical_literal_record": record["exact_historical_literal_record"],
                "schema": "cdg-original-record-id-v1",
            }
        )
        digest = ratchet._sha256_bytes(payload)
        assert record["id_payload_byte_length"] == len(payload)
        assert record["id_payload_sha256"] == digest
        assert record["original_record_id"] == f"cdg1:{digest}"
        recomputed.append(record["original_record_id"])
    assert len(recomputed) == 655 and len(set(recomputed)) == 655
    assert (
        ratchet._digest_set("cdg-original-record-id-set-v1", recomputed, "original_record_ids")
        == ratchet.ORIGINAL_ID_SET_SHA256
    )
    # Full independent provenance reconstruction of all 598 records.
    cohort_summary = ratchet._validate_original_cohort(cohort)
    provenance = _real_authority()["canonical_artifacts"]["sdk_provenance"]
    provenance_summary = ratchet._validate_sdk_provenance(provenance, cohort_summary)
    assert provenance_summary["record_count"] == 598
    assert provenance_summary["record_digest_set_sha256"] == ratchet.PROVENANCE_RECORD_SET_SHA256
    # A minted ID that does not equal the payload hash fails closed.
    forged = copy.deepcopy(cohort)
    forged["original_records"][0]["id_payload_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="ID payload .*mismatch"):
        ratchet._validate_original_cohort(forged)
    # A dropped provenance record breaks the exact 598 closure.
    short = copy.deepcopy(provenance)
    del short["records"][0]
    with pytest.raises(ValueError, match="598 records"):
        ratchet._validate_sdk_provenance(short, cohort_summary)


def test_corrective_binds_projection_membership_and_edge_cardinalities():
    summary = ratchet._validate_original_cohort(
        _real_authority()["canonical_artifacts"]["original_cohort"]
    )
    projection = summary["operation_projection"]
    assert projection["membership_count"] == 655
    assert projection["edge_count"] == 666
    assert projection["multi_edge_originals"] == 9
    assert projection["max_edges"] == 4
    assert projection["edge_count_distribution"] == {"1": 646, "2": 8, "4": 1}
    assert projection["record_digest_set_sha256"] == ratchet.PROJECTION_RECORD_SET_SHA256

    # Removing a witnessed edge from the four-edge membership fails closed.
    def strip_four_edge(records: list[dict]) -> None:
        target = next(r for r in records if len(r["operation_edges"]) == 4)
        target["operation_edges"] = target["operation_edges"][:3]

    cohort, _projection = _projection_case(strip_four_edge)
    with pytest.raises(ValueError, match="record-digest-set mismatch|cardinality mismatch"):
        ratchet._validate_original_cohort(cohort)

    # Inflating a single-edge membership with a duplicate edge fails closed.
    def duplicate_edge(records: list[dict]) -> None:
        target = next(r for r in records if len(r["operation_edges"]) == 1)
        target["operation_edges"] = target["operation_edges"] * 2

    cohort, _projection = _projection_case(duplicate_edge)
    with pytest.raises(ValueError, match="duplicate edges"):
        ratchet._validate_original_cohort(cohort)


def test_pr_file_evidence_reconciles_changed_files_additions_and_deletions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Complete pagination reconciles exactly to the PR's changed_files and
    # binds authenticated additions/deletions integers.
    context, requested = _live_pr_files_probe(
        tmp_path, monkeypatch, files_count=3, pr_additions=11, pr_deletions=7
    )
    assert context["authenticated_pr_changes"] == {9999: {"additions": 11, "deletions": 7}}
    assert any("/pulls/9999/files?per_page=100&page=1" in endpoint for endpoint in requested)
    # A canonical-file/changed_files mismatch fails closed.
    with pytest.raises(ValueError, match="file discovery is incomplete"):
        _live_pr_files_probe(tmp_path / "short", monkeypatch, files_count=2, changed_files=3)
    # Malformed additions/deletions (bool/negative) are rejected downstream.
    for additions, deletions in ((True, 0), (-1, 0), (0, -2)):
        with pytest.raises(ValueError, match="additions/deletions are malformed"):
            ratchet._validate_governed_prs(
                _governed_pr_resource("1" * 40, "2" * 40),
                authenticated_pr_changes={9999: {"additions": additions, "deletions": deletions}},
                repo_root=tmp_path,
                operation_log=[],
            )


def test_exact_tree_diff_with_pinned_rename_policy_is_only_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # The completeness fallback is the immutable base/head tree binding:
    # governed head trees must equal the authenticated receipt trees exactly.
    def wrong_tree(resources: dict[str, Any]) -> None:
        resources["governed_prs"]["records"][0]["head_tree_sha"] = "e" * 40

    with pytest.raises(ValueError, match="lacks first-parent or tree equality"):
        _live_pr_files_probe(tmp_path / "tree", monkeypatch, mutate=wrong_tree)
    # Pinned rename policy on a real disposable repo: a renamed baseline is a
    # removal at the canonical path; rename following never resurrects it.
    repo = tmp_path / "rename"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _write_docs(
        repo,
        {
            "verify": {"python_sdk_drift": ["GET /pinned"], "typescript_sdk_drift": []},
            "routes": {"missing_in_spec": [], "orphaned_in_spec": []},
            "parity": {"missing_from_both_sdks": []},
        },
    )
    base_sha = _commit(repo, "base")
    verify_rel = gen.BASELINE_SPECS["verify"][0]
    subprocess.run(
        ["git", "-C", str(repo), "mv", str(verify_rel), "scripts/baselines/moved.json"],
        check=True,
    )
    head_sha = _commit(repo, "renamed")
    assert "python_sdk_drift:GET /pinned" in gen.collect_ids(gen.load_git_docs(repo, base_sha))
    assert gen.collect_ids(gen.load_git_docs(repo, head_sha)) == {}
    # No rename-following or copy-detection flags exist in any live analyzer,
    # settlement, or bootstrap surface.
    for module_path in (Path(ratchet.__file__), Path(gen.__file__), Path(settle.__file__), _BOOTSTRAP_PATH):  # fmt: skip
        source = module_path.read_text(encoding="utf-8")
        assert "--follow" not in source
        assert "find-renames" not in source
        assert "find-copies" not in source


def test_compare_api_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # No evidence-collection surface constructs a GitHub compare endpoint:
    # analyzers, trusted bootstrap, launcher, or governance workflows carry
    # zero compare-URL fragments, so a compare fallback cannot even be built.
    surfaces = [
        Path(ratchet.__file__),
        Path(gen.__file__),
        _BOOTSTRAP_PATH,
        _REPO_ROOT / ".github/workflows/contract_drift_trusted_launcher.py",
        _REPO_ROOT / ".github/workflows/contract-drift-governance.yml",
        _REPO_ROOT / ".github/workflows/contract-drift-trusted-bootstrap.yml",
    ]
    for surface in surfaces:
        source = surface.read_text(encoding="utf-8")
        assert "/compare" not in source, surface
        assert "compare/" not in source, surface
    # Behavioral: complete live evidence collection touches pulls/files,
    # commits, releases, and rule-suites — never a compare endpoint.
    _context, requested = _live_pr_files_probe(tmp_path, monkeypatch, files_count=1)
    assert requested
    assert not any("compare" in endpoint for endpoint in requested)


def test_cdg_800_cap_applies_only_to_core_extended_paydown_with_exact_corrective_guard_v2_exception(  # noqa: E501
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Contract L76 (review-history entry 30): the 800 cap binds only the
    # individually enumerated core/extended SDK paydown implementation PRs.
    # The governed census admits authenticated non-paydown deltas uncapped:
    # the real d3e45faf..559426b7 interval — whose tests-only contract-closure
    # PR #9687 carries +7397/-12 = 7409 — validates as governed evidence.
    real_interval_changes = {
        9683: {"additions": 72, "deletions": 23},
        9687: {"additions": 7397, "deletions": 12},
        9691: {"additions": 195, "deletions": 0},
        9692: {"additions": 50, "deletions": 24},
        9693: {"additions": 245, "deletions": 28},
    }
    real_heads = {
        9683: "e26935b6eeacf2ea83182c20aecd45b62b836e23",
        9687: "492405a6c134745741709838caf56ee2a5d20ece",
        9691: "486b24fbb131d27b90853c1d64dd949834427e1f",
        9692: "4b36750a2ea3433e42a06927c79056b3bd5a9e3d",
        9693: "559426b7d88fb748217b1008551c97bf426d0fcf",
    }
    base = "d3e45fafe6dd04508882935c813f6896abc859d7"
    records = []
    for number in sorted(real_interval_changes):
        records.append(
            {
                "base_sha": base,
                "changed_files_complete": True,
                "head_sha": real_heads[number],
                "head_tree_sha": "d" * 40,
                "pr": number,
            }
        )
        base = real_heads[number]
    interval_resource = {
        "boundary": "corrective_bootstrap",
        "end_sha": real_heads[9693],
        "records": records,
        "schema": "contract-drift-governed-prs-v1",
        "start_sha": "d3e45fafe6dd04508882935c813f6896abc859d7",
    }
    validated = ratchet._validate_governed_prs(
        interval_resource,
        authenticated_pr_changes=real_interval_changes,
        repo_root=tmp_path,
        operation_log=[],
    )
    deltas = {record["pr"]: record["authenticated_pr_delta"] for record in validated}
    assert deltas == {9683: 95, 9687: 7409, 9691: 195, 9692: 74, 9693: 273}
    # An 866 single-PR census delta also binds uncapped.
    validated = ratchet._validate_governed_prs(
        _governed_pr_resource("1" * 40, "2" * 40),
        authenticated_pr_changes={9999: {"additions": 433, "deletions": 433}},
        repo_root=tmp_path,
        operation_log=[],
    )
    assert validated[0]["authenticated_pr_delta"] == 866

    # The cap binds the core/extended paydown facts (801 fails closed).
    def inflate_core_cap(payloads: dict) -> None:
        proof = payloads["core_sdk"]
        fact = dict(proof["qualifying_paydown"]["fact"], max_pr_delta=801)
        proof["qualifying_paydown"] = _relink_fact("contract-drift-core-sdk-paydown-fact-v1", fact)

    broken = _boundary_result(
        tmp_path / "core-cap", monkeypatch, "core_sdk", mutate=inflate_core_cap
    )
    assert broken["status"] == "fail"
    assert "per-PR size cap" in broken["error"]
    # The exact corrective guard-v2 atom (+687/-178 = 865 across six files)
    # rides the corrective proof plane, which carries no PR-delta cap field.
    assert _EXPECTED_GUARD_V2_DELTA == 865 and _EXPECTED_GUARD_V2_DELTA > 800
    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path / "corrective")
    corrective = _boundary_payloads(
        "corrective_bootstrap",
        start_sha,
        boundary_shas["corrective_bootstrap"],
        boundary_shas,
        repo=repo,
    )["corrective_bootstrap"]
    assert "max_pr_delta" not in json.dumps(corrective)


def test_non_quorum_checks_and_evidence_precede_settlement():
    head = "a" * 40
    packet = _settle_packet(9645)
    # A failing non-quorum required check blocks settlement outright.
    gate = settle.evaluate_tier4_settlement_preconditions(
        pr=9645,
        expected_head=head,
        pr_view=_settle_pr_view(head),
        merge_packet=packet,
        required_checks=[
            {"name": "contract-drift-pr-delta", "state": "FAILURE"},
            {"name": settle.MERGE_QUORUM_CONTEXT, "state": "SUCCESS"},
        ],
    )
    assert not gate["ok"]
    assert any("contract-drift-pr-delta is FAILURE" in blocker for blocker in gate["blockers"])
    # A quorum-only failure is the one state that may precede settlement, and
    # only with missing-settlement proof (packet-borne or explicitly flagged).
    quorum_only = [
        {"name": "contract-drift-pr-delta", "state": "SUCCESS"},
        {"name": settle.MERGE_QUORUM_CONTEXT, "state": "FAILURE"},
    ]
    unproven_packet = _settle_packet(9645)
    unproven_packet["entries"][0]["status"] = "pending"
    unproven = settle.evaluate_tier4_settlement_preconditions(
        pr=9645,
        expected_head=head,
        pr_view=_settle_pr_view(head),
        merge_packet=unproven_packet,
        required_checks=quorum_only,
    )
    assert not unproven["ok"]
    assert settle.MERGE_QUORUM_SETTLEMENT_PROOF_BLOCKER in unproven["blockers"]
    flagged = settle.evaluate_tier4_settlement_preconditions(
        pr=9645,
        expected_head=head,
        pr_view=_settle_pr_view(head),
        merge_packet=unproven_packet,
        required_checks=quorum_only,
        quorum_missing_settlement_proof=True,
    )
    assert flagged["ok"], flagged["blockers"]
    packet_borne = settle.evaluate_tier4_settlement_preconditions(
        pr=9645,
        expected_head=head,
        pr_view=_settle_pr_view(head),
        merge_packet=packet,
        required_checks=quorum_only,
    )
    assert packet_borne["ok"], packet_borne["blockers"]
    # Missing Tier-4 evidence blocks settlement even with green checks.
    bare_packet = {"not_ready": [], "entries": [{"pr_number": 9645, "tier": 4}]}
    no_evidence = settle.evaluate_tier4_settlement_preconditions(
        pr=9645,
        expected_head=head,
        pr_view=_settle_pr_view(head),
        merge_packet=bare_packet,
        required_checks=[{"name": "x", "state": "SUCCESS"}],
    )
    assert settle.TIER4_EVIDENCE_BLOCKER in no_evidence["blockers"]


def test_prerequisite_check_ids_and_evidence_digests_are_bound(tmp_path: Path):
    # Tier-4 evidence binding: counted reviewer identities and dogfood
    # evidence must both be present; anything less is unbound.
    assert settle._packet_has_counted_tier4_evidence(_settle_packet(9645), pr=9645)
    thin = _settle_packet(9645)
    thin["entries"][0]["counted_reviewer_ids"] = ["only-one"]
    assert not settle._packet_has_counted_tier4_evidence(thin, pr=9645)
    no_dogfood = _settle_packet(9645)
    no_dogfood["entries"][0]["dogfood_evidence"] = []
    assert not settle._packet_has_counted_tier4_evidence(no_dogfood, pr=9645)
    dissent = _settle_packet(9645)
    dissent["entries"][0]["unresolved_dissent"] = True
    assert not settle._packet_has_counted_tier4_evidence(dissent, pr=9645)
    # Evidence digests: every boundary resource is bound by byte length and
    # SHA-256 in the index; a one-byte flip fails closed.
    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path)
    end_sha = boundary_shas["corrective_bootstrap"]
    index_path, index_length, index_sha256 = _write_boundary_index(
        tmp_path, "corrective_bootstrap", start_sha, end_sha, boundary_shas, repo=repo
    )
    resource_path = tmp_path / "resources-corrective_bootstrap" / "corrective_bootstrap.json"
    raw = bytearray(resource_path.read_bytes())
    raw[0] ^= 0x01
    resource_path.write_bytes(bytes(raw))
    with pytest.raises(ValueError, match="SHA-256 mismatch|byte-length mismatch"):
        ratchet._load_evidence_resources(
            evidence_index_path=index_path,
            evidence_index_byte_length=index_length,
            evidence_index_sha256=index_sha256,
            boundary="corrective_bootstrap",
            start_sha=start_sha,
            end_sha=end_sha,
            operation_log=[],
        )


def test_settlement_identity_binds_base_and_head_and_approved_actor():
    head = "c" * 40
    # Head binding: the settlement gate refuses any head other than the bound
    # exact head.
    moved = settle.evaluate_tier4_settlement_preconditions(
        pr=9645,
        expected_head=head,
        pr_view=_settle_pr_view("d" * 40),
        merge_packet=_settle_packet(9645),
        required_checks=[{"name": "x", "state": "SUCCESS"}],
    )
    assert any("head mismatch" in blocker for blocker in moved["blockers"])
    # Actor binding: --settle-only demands a trusted allowlisted invoker with
    # admin authority; absent allowlist or untrusted login are hard blockers.
    no_allowlist = settle.evaluate_tier4_settlement_preconditions(
        pr=9645,
        expected_head=head,
        pr_view=_settle_pr_view(head),
        merge_packet=_settle_packet(9645),
        required_checks=[{"name": "x", "state": "SUCCESS"}],
        require_trusted_invoker=True,
    )
    assert settle.SETTLE_ONLY_TRUSTED_OPERATOR_BLOCKER in no_allowlist["blockers"]
    untrusted = settle.evaluate_tier4_settlement_preconditions(
        pr=9645,
        expected_head=head,
        pr_view=_settle_pr_view(head),
        merge_packet=_settle_packet(9645),
        required_checks=[{"name": "x", "state": "SUCCESS"}],
        trusted_operator_logins=["operator"],
        invoker_login="intruder",
        require_trusted_invoker=True,
        require_invoker_admin_permission=True,
    )
    assert any("not in trusted operator allowlist" in b for b in untrusted["blockers"])
    no_admin = settle.evaluate_tier4_settlement_preconditions(
        pr=9645,
        expected_head=head,
        pr_view=_settle_pr_view(head),
        merge_packet=_settle_packet(9645),
        required_checks=[{"name": "x", "state": "SUCCESS"}],
        trusted_operator_logins=["operator"],
        invoker_login="operator",
        invoker_has_admin_permission=False,
        require_trusted_invoker=True,
        require_invoker_admin_permission=True,
    )
    assert any(
        settle.SETTLE_ONLY_ADMIN_PERMISSION_BLOCKER in blocker for blocker in no_admin["blockers"]
    )
    approved = settle.evaluate_tier4_settlement_preconditions(
        pr=9645,
        expected_head=head,
        pr_view=_settle_pr_view(head),
        merge_packet=_settle_packet(9645),
        required_checks=[{"name": "x", "state": "SUCCESS"}],
        trusted_operator_logins=["operator"],
        invoker_login="operator",
        invoker_has_admin_permission=True,
        require_trusted_invoker=True,
        require_invoker_admin_permission=True,
    )
    assert approved["ok"], approved["blockers"]
    # The settlement identity text itself binds PR and exact head.
    template = settle._settlement_comment_template(pr=9645, head=head)
    assert f"#{9645}" in template and head in template
    assert settle.AUTHORIZED_MARKER in template


def test_identical_settlement_identity_is_reused_not_reposted(monkeypatch: pytest.MonkeyPatch):
    head = "e" * 40
    # The settlement identity for a (pr, head) pair is deterministic: a
    # repost could only ever be byte-identical.
    assert settle._settlement_comment_template(pr=9645, head=head) == (
        settle._settlement_comment_template(pr=9645, head=head)
    )

    # An existing fresh exact-head settlement comment is accepted as-is by
    # the gate — evaluation is pure and performs no write commands.
    def forbid_writes(*_args, **_kwargs):
        raise AssertionError("gate evaluation must not run commands")

    monkeypatch.setattr(settle, "_run_command", forbid_writes)
    monkeypatch.setattr(settle, "_run_text_command", forbid_writes)
    view = _settle_pr_view(head, comments=[_settlement_comment(9645, head)])
    gate = settle.evaluate_tier4_gate(
        pr=9645,
        expected_head=head,
        pr_view=view,
        merge_packet=_settle_packet(9645),
        required_checks=[{"name": "x", "state": "SUCCESS"}],
        permission_checker=lambda _login: True,
    )
    assert gate["ok"], gate["blockers"]
    assert "merge" in gate["authorized_actions"]
    (diagnostic,) = gate["authorization_diagnostics"]
    assert diagnostic["accepted"] is True
    # The identical identity re-evaluated is stable (retry-safe reuse).
    again = settle.evaluate_tier4_gate(
        pr=9645,
        expected_head=head,
        pr_view=view,
        merge_packet=_settle_packet(9645),
        required_checks=[{"name": "x", "state": "SUCCESS"}],
        permission_checker=lambda _login: True,
    )
    assert again["ok"] and again["authorized_actions"] == gate["authorized_actions"]


def test_settlement_helper_is_settle_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # The settlement signal consists of exactly one comment and one commit
    # status — never a merge command.
    recorded: list[list[str]] = []

    def record_text(command: list[str], *, cwd: Path, input_text: str | None = None) -> str:
        del cwd, input_text
        recorded.append(command)
        return "https://example.test/comment"

    def record(command: list[str], *, cwd: Path, input_text: str | None = None) -> None:
        del cwd, input_text
        recorded.append(command)

    monkeypatch.setattr(settle, "_run_text_command", record_text)
    monkeypatch.setattr(settle, "_run_command", record)
    commands = settle._apply_settlement_signal(
        pr=9645, head="f" * 40, repo="synaptent/aragora", cwd=tmp_path
    )
    assert [command[:3] for command in commands] == [
        ["gh", "pr", "comment"],
        ["gh", "api", "--method"],
    ]
    flattened = " ".join(part for command in recorded for part in command)
    assert " merge" not in f" {flattened}"
    assert settle.HUMAN_SETTLEMENT_CONTEXT in flattened
    # --settle-only and --merge-apply are mutually exclusive modes.
    with pytest.raises(SystemExit):
        settle.build_parser().parse_args(
            ["--settle-only", "--merge-apply", "--pr", "9645", "--head", "f" * 40]
        )


def test_workflow_history_is_unfiltered_or_disjoint_below_1000_shards(
    monkeypatch: pytest.MonkeyPatch,
):
    # The authenticated pagination surface appends only per_page/page to the
    # caller's endpoint — it never injects status/conclusion filters — and it
    # fails closed on duplicate API identities.
    requested: list[str] = []
    pages = {
        1: [{"id": index} for index in range(100)],
        2: [{"id": 100 + index} for index in range(3)],
    }

    def fake_stable(endpoint: str, *, operation_log: list, attempts: int = 3):
        del operation_log, attempts
        requested.append(endpoint)
        page = int(endpoint.rsplit("page=", 1)[1])
        return pages[page], {"etag": '"x"'}

    monkeypatch.setattr(ratchet, "_gh_api_get_stable", fake_stable)
    records, _identities = ratchet._gh_api_paginated(
        "repos/synaptent/aragora/actions/runs", operation_log=[]
    )
    assert len(records) == 103
    assert requested == [
        "repos/synaptent/aragora/actions/runs?per_page=100&page=1",
        "repos/synaptent/aragora/actions/runs?per_page=100&page=2",
    ]
    for endpoint in requested:
        assert "status=" not in endpoint
        assert "conclusion=" not in endpoint
        assert "created=" not in endpoint

    def duplicated(endpoint: str, *, operation_log: list, attempts: int = 3):
        del operation_log, attempts
        return [{"id": 7}, {"id": 7}], {"etag": '"x"'}

    monkeypatch.setattr(ratchet, "_gh_api_get_stable", duplicated)
    with pytest.raises(ValueError, match="duplicate record IDs"):
        ratchet._gh_api_paginated("repos/synaptent/aragora/actions/runs", operation_log=[])
    # No analyzer surface bakes a status/conclusion filter into a workflow
    # history query.
    for module_file in (ratchet.__file__, gen.__file__):
        source = Path(module_file).read_text(encoding="utf-8")
        assert "status=completed" not in source
        assert "conclusion=success" not in source


def test_post_settlement_execution_identity_is_run_id_and_strictly_greater_attempt(
    tmp_path: Path,
):
    # Execution identity is (run_id, run_attempt) with positive integers and
    # bool coercion rejected.
    valid = bootstrap.RunProvenance(
        event_name="pull_request_target",
        repository="synaptent/aragora",
        run_attempt=2,
        run_id=12345,
        workflow_ref=bootstrap.EXPECTED_WORKFLOW_REF,
    )
    workflow_run = bootstrap._validate_run_provenance(valid)
    assert workflow_run == {
        "event_name": "pull_request_target",
        "repository": "synaptent/aragora",
        "run_attempt": 2,
        "run_id": 12345,
        "workflow_ref": bootstrap.EXPECTED_WORKFLOW_REF,
    }
    for hostile in (
        valid.__class__(**{**workflow_run, "run_attempt": 0}),
        valid.__class__(**{**workflow_run, "run_attempt": True}),
        valid.__class__(**{**workflow_run, "run_id": 0}),
    ):
        with pytest.raises(bootstrap.BootstrapError, match="run provenance"):
            bootstrap._validate_run_provenance(hostile)
    # The comparison signal is attempt-specific: a signal minted at attempt 2
    # cannot satisfy admission observing any other execution identity.
    signal_path = bootstrap._write_comparison_signal(
        tmp_path,
        "1" * 40,
        "2" * 40,
        "3" * 40,
        {"path": "digest"},
        {"authority": True},
        {"bundle": True},
        [{"schema": "artifact"}],
        workflow_run,
    )
    assert bootstrap._authenticate_comparison_signal(
        signal_path, base_sha="1" * 40, head_sha="2" * 40, workflow_run=workflow_run
    )
    with pytest.raises(bootstrap.BootstrapError, match="comparison signal is invalid"):
        bootstrap._authenticate_comparison_signal(
            signal_path,
            base_sha="1" * 40,
            head_sha="2" * 40,
            workflow_run={**workflow_run, "run_attempt": 3},
        )


def test_all_attempts_and_attempt_specific_jobs_checks_are_bound(tmp_path: Path):
    # Check URLs bind attempt-specific job executions: job IDs parse only
    # from /job/ URLs and quorum log proof is impossible without one.
    assert (
        settle._github_actions_job_id_from_url(
            "https://github.com/synaptent/aragora/actions/runs/99/job/123?pr=1"
        )
        == "123"
    )
    assert (
        settle._github_actions_job_id_from_url(
            "https://github.com/synaptent/aragora/actions/runs/99"
        )
        == ""
    )
    assert settle._github_actions_job_id_from_url("") == ""
    quorum_without_job = [
        {"name": "x", "state": "SUCCESS"},
        {
            "name": settle.MERGE_QUORUM_CONTEXT,
            "state": "FAILURE",
            "link": "https://github.com/synaptent/aragora/actions/runs/99",
        },
    ]
    assert (
        settle._quorum_failure_log_proves_missing_settlement(
            quorum_without_job, repo="synaptent/aragora", cwd=tmp_path, head="a" * 40
        )
        is False
    )
    # The run-level artifact binding carries the full execution identity
    # (run_id and run_attempt) inside the authenticated payload.
    workflow_run = bootstrap._validate_run_provenance(
        bootstrap.RunProvenance(
            event_name="pull_request_target",
            repository="synaptent/aragora",
            run_attempt=1,
            run_id=777,
            workflow_ref=bootstrap.EXPECTED_WORKFLOW_REF,
        )
    )
    signal_path = bootstrap._write_comparison_signal(
        tmp_path,
        "1" * 40,
        "2" * 40,
        "3" * 40,
        {},
        {},
        {},
        [],
        workflow_run,
    )
    payload = json.loads(signal_path.read_bytes())["payload"]
    assert payload["workflow_run"]["run_id"] == 777
    assert payload["workflow_run"]["run_attempt"] == 1
    # Superseded-run extraction parses run IDs from attempt-specific details
    # URLs only, deduplicated in order.
    skew = {
        "stale_failed_required_contexts": [
            {"details_url": "https://github.com/x/y/actions/runs/11/job/1"},
            {"details_url": "https://github.com/x/y/actions/runs/11/job/2"},
            {"details_url": "https://github.com/x/y/actions/runs/12/job/3"},
            {"details_url": "https://example.test/no-run"},
        ]
    }
    assert settle._superseded_run_ids(skew) == ["11", "12"]


def test_pre_settlement_execution_identity_cannot_satisfy_final_gate():
    head = "a" * 40
    # Green checks without the settlement status: the final gate refuses.
    unsettled = settle.evaluate_tier4_gate(
        pr=9645,
        expected_head=head,
        pr_view=_settle_pr_view(head, settlement_success=False),
        merge_packet=_settle_packet(9645),
        required_checks=[{"name": "x", "state": "SUCCESS"}],
        permission_checker=lambda _login: True,
    )
    assert not unsettled["ok"]
    assert settle.HUMAN_SETTLEMENT_STATUS_BLOCKER in unsettled["blockers"]
    # A settlement comment minted before the current head commit is
    # pre-settlement evidence relative to this execution: rejected as stale.
    stale_comment = _settlement_comment(9645, head, created_at="2026-07-10T00:00:00Z")
    stale = settle.evaluate_tier4_gate(
        pr=9645,
        expected_head=head,
        pr_view=_settle_pr_view(head, comments=[stale_comment]),
        merge_packet=_settle_packet(9645),
        required_checks=[{"name": "x", "state": "SUCCESS"}],
        permission_checker=lambda _login: True,
    )
    assert not stale["ok"]
    assert settle.OPERATOR_COMMENT_BLOCKER in stale["blockers"]
    (diagnostic,) = stale["authorization_diagnostics"]
    assert "authorization is older than head commit" in diagnostic["rejection_reasons"]


def test_strict_false_movement_restarts_evidence_settlement_and_quorum(
    monkeypatch: pytest.MonkeyPatch,
):
    # Concurrent movement of a remote identity forces a restart (blocked),
    # never a silent pass.
    tick = {"count": 0}

    def moving_probe():
        tick["count"] += 1
        return {"noise": tick["count"]}, {"etag": f'"v{tick["count"]}"'}

    with pytest.raises(ratchet.BoundaryBlocked, match="moved concurrently"):
        ratchet._retry_stable_remote_probe(
            lambda: (moving_probe(), None)[0] if False else moving_probe(), attempts=3
        )
    # A body change without an identity change is a contradiction, not a
    # movement: it fails closed loudly.
    bodies = iter([b"one", b"two"])

    def contradictory(endpoint: str, *, operation_log: list, attempts: int = 3):
        del endpoint, attempts
        operation_log.append({})
        return next(bodies), {"etag": '"same"'}

    monkeypatch.setattr(ratchet, "_gh_api_get_raw", contradictory)
    with pytest.raises(ValueError, match="contradicted stable identity"):
        ratchet._gh_api_get_raw_stable("repos/synaptent/aragora/releases/1", operation_log=[])
    # Settlement and quorum evidence restart on head movement: the bound
    # exact head no longer matches the live view.
    moved_gate = settle.evaluate_tier4_gate(
        pr=9645,
        expected_head="a" * 40,
        pr_view=_settle_pr_view("b" * 40),
        merge_packet=_settle_packet(9645),
        required_checks=[{"name": "x", "state": "SUCCESS"}],
        permission_checker=lambda _login: True,
    )
    assert not moved_gate["ok"]
    assert any("head mismatch" in blocker for blocker in moved_gate["blockers"])
    assert moved_gate["authorized_actions"] == []


def test_merge_first_parent_equals_bound_base():
    # The receipt schema freezes base == first parent; any drift is rejected
    # before git is even consulted.
    def receipt(**overrides: Any) -> dict[str, Any]:
        record = {
            "base_sha": "1" * 40,
            "first_parent_sha": "1" * 40,
            "head_sha": "2" * 40,
            "head_tree_sha": "3" * 40,
            "merge_sha": "4" * 40,
            "merge_tree_sha": "3" * 40,
            "pr": 9645,
            **overrides,
        }
        return {
            "boundary": "corrective_bootstrap",
            "end_sha": "4" * 40,
            "records": [record],
            "schema": "contract-drift-first-parent-receipts-v1",
            "start_sha": "1" * 40,
        }

    validated = ratchet._validate_first_parent_receipts(receipt())
    assert validated[0]["base_sha"] == validated[0]["first_parent_sha"]
    with pytest.raises(ValueError, match="does not equal the frozen base SHA"):
        ratchet._validate_first_parent_receipts(receipt(first_parent_sha="9" * 40))
    with pytest.raises(ValueError, match="first-parent receipt base_sha is malformed"):
        ratchet._validate_first_parent_receipts(receipt(base_sha="short"))
    with pytest.raises(ValueError, match="invalid or duplicated"):
        ratchet._validate_first_parent_receipts(receipt(pr=0))


def test_normal_protected_exact_head_merge_is_last_and_never_admin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    # The forward no-admin proof is executable: a protection-bypassing merge
    # records a bypassed rule evaluation, which fails closed everywhere.
    assert ratchet._contains_rule_suite_bypass({"result": "bypass"})
    assert ratchet._contains_rule_suite_bypass(
        {"rule_evaluations": [{"result": "pass"}, {"evaluation_result": "bypass"}]}
    )
    assert ratchet._contains_rule_suite_bypass({"bypass_actors": [123]})
    assert not ratchet._contains_rule_suite_bypass(
        {"result": "pass", "bypassed": False, "note": None}
    )
    with pytest.raises(ValueError, match="bypassed evaluation"):
        ratchet._validate_rule_suite_record_fields(
            _rule_suite_record("5" * 40, rule_evaluations=[{"result": "bypass"}]),
            repository_id=1126097105,
            repository_name="aragora",
            expected_ref="refs/heads/main",
            end_sha="5" * 40,
        )
    # The rule evaluation must bind the exact merged head (after_sha) — a
    # merge at any other SHA cannot satisfy the boundary.
    with pytest.raises(ValueError, match="stale or unrelated"):
        ratchet._validate_rule_suite_record_fields(
            _rule_suite_record("6" * 40),
            repository_id=1126097105,
            repository_name="aragora",
            expected_ref="refs/heads/main",
            end_sha="5" * 40,
        )
    # The merge action is exact-head-pinned and terminal: the merge command
    # binds --match-head-commit to the settled head and, without protection
    # reconciliation, is the only command issued.
    commands: list[list[str]] = []

    def _record_command(command: list[str], *, cwd: Any, input_text: Any = None) -> None:
        commands.append(command)

    def _record_text_command(command: list[str], *, cwd: Any, input_text: Any = None) -> str:
        commands.append(command)
        return ""

    monkeypatch.setattr(settle, "_run_command", _record_command)
    monkeypatch.setattr(settle, "_run_text_command", _record_text_command)
    settle._apply_merge(pr=9645, head="7" * 40, repo="synaptent/aragora", cwd=tmp_path)
    assert len(commands) == 1
    merge_command = commands[0]
    assert merge_command[:3] == ["gh", "pr", "merge"]
    assert "--match-head-commit" in merge_command
    assert merge_command[merge_command.index("--match-head-commit") + 1] == "7" * 40


# ---------------------------------------------------------------------------
# VAL-CDG-014: authority transitions are closed, atomic, and fail safely
# across old bases.
# ---------------------------------------------------------------------------


def test_base_without_accepted_authority_requires_transition(tmp_path: Path):
    # An inventory without the accepted-authority manifest yields the
    # dedicated transition error, never head-authority execution.
    repo = tmp_path / "transition-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "parent.txt").write_text("parent\n", encoding="utf-8")
    _commit(repo, "parent")
    inventory = _real_inventory()
    del inventory["accepted_authority"]
    bare = repo / gen.DEFAULT_INVENTORY
    bare.parent.mkdir(parents=True)
    bare.write_text(json.dumps(inventory), encoding="utf-8")
    source = _commit(repo, "inventory without authority")
    result = ratchet.build_accepted_result(
        mode="program",
        repo_root=repo,
        inventory_path=Path(gen.DEFAULT_INVENTORY),
        source_sha=source,
    )
    assert result["status"] == "fail" and result["passing"] is False
    assert result["error_code"] == "authority_transition_required"
    # A source commit without the canonical inventory is the same closed
    # transition failure.
    bare.unlink()
    missing_source = _commit(repo, "inventory absent")
    missing = ratchet.build_accepted_result(
        mode="program",
        repo_root=repo,
        inventory_path=Path(gen.DEFAULT_INVENTORY),
        source_sha=missing_source,
    )
    assert missing["error_code"] == "authority_transition_required"
    # Degraded-schema bases (manifest present but not an object) fail the
    # same way rather than executing whatever the head proposes.
    inventory["accepted_authority"] = "not-a-manifest"
    bare.write_text(json.dumps(inventory), encoding="utf-8")
    degraded_source = _commit(repo, "malformed authority")
    degraded = ratchet.build_accepted_result(
        mode="program",
        repo_root=repo,
        inventory_path=Path(gen.DEFAULT_INVENTORY),
        source_sha=degraded_source,
    )
    assert degraded["error_code"] == "authority_transition_required"


def test_corrective_merge_parent_requires_transition(tmp_path: Path):
    # PARENT is the recorded corrective transition base: it descends to the
    # current main and its inventory has no accepted authority manifest.
    parent = _real_authority()["transition"]["base_sha"]
    assert parent == CORRECTIVE_BASE_SHA
    subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "merge-base", "--is-ancestor", parent, "HEAD"],
        check=True,
    )
    parent_doc = json.loads(
        subprocess.check_output(
            ["git", "-C", str(_REPO_ROOT), "show", f"{parent}:{gen.DEFAULT_INVENTORY}"],
            text=True,
        )
    )
    assert not isinstance(parent_doc.get("accepted_authority"), dict)
    # Program mode at PARENT's immutable inventory fails
    # authority_transition_required.
    result = ratchet.build_accepted_result(
        mode="program",
        repo_root=_REPO_ROOT,
        inventory_path=Path(gen.DEFAULT_INVENTORY),
        source_sha=parent,
    )
    assert result["error_code"] == "authority_transition_required"
    assert result["passing"] is False


def test_head_cannot_self_bootstrap_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # When the resolved base carries accepted authority, PR mode executes the
    # base analyzer/authority — the head cannot swap in its own.
    repo, base, head = _hermetic_repo(tmp_path)
    result, _calls = _recorded_hermetic_pr(repo, base, head, monkeypatch)
    assert result["passing"] is True
    assert result["execution"]["analyzer_sha"] == base
    assert result["authority"] == {"source": "accepted_authority"}
    # A head that rewrites the authority manifest cannot smuggle it through
    # the comparison: immutable bindings are compared exactly.
    hostile = _real_authority()
    hostile["analyzer_bundle"]["interpreter_flags"] = ["-I"]
    _relink_authority_manifest(hostile)
    monkeypatch.setattr(ratchet, "validate_accepted_authority", lambda *a, **k: {})
    with pytest.raises(ValueError, match="immutable authority bindings changed"):
        ratchet.compare_accepted_authorities(_real_authority(), hostile, repo_root=_REPO_ROOT)


def test_approved_authority_transition_is_atomic():
    # The accepted authority is a closed atomic unit: its field set is exact,
    # and removing any single plane fails the whole manifest closed.
    authority = _real_authority()
    assert set(authority) == ratchet.AUTHORITY_FIELDS
    for field in sorted(ratchet.AUTHORITY_FIELDS):
        partial = _real_authority()
        del partial[field]
        with pytest.raises(ValueError, match="schema or fields mismatch"):
            ratchet.validate_accepted_authority(partial, repo_root=_REPO_ROOT)
    # The installed transition is the dedicated authority_transition kind
    # with the exact recorded base.
    transition = authority["transition"]
    assert transition["kind"] == "authority_transition"
    assert transition["base_sha"] == CORRECTIVE_BASE_SHA
    assert set(transition) == {
        "accepted_transition_head",
        "base_sha",
        "historical_nonconforming",
        "kind",
    }


def test_accepted_authority_manifest_is_unique():
    # Exactly one accepted-authority manifest exists in the tree.
    listing = subprocess.run(
        [
            "git",
            "-C",
            str(_REPO_ROOT),
            "grep",
            "-l",
            '"accepted_authority"',
            "HEAD",
            "--",
            "*.json",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert listing == [f"HEAD:{gen.DEFAULT_INVENTORY}"]
    # The manifest digest binds every field: duplicating or editing any part
    # of the unique manifest breaks the digest and fails closed.
    forged = _real_authority()
    forged["categories"] = list(forged["categories"]) + ["python_sdk_drift"]
    with pytest.raises(ValueError, match="mismatch"):
        ratchet.validate_accepted_authority(forged, repo_root=_REPO_ROOT)


def test_canonical_cohort_and_provenance_artifact_bytes_never_change_across_transition(
    monkeypatch: pytest.MonkeyPatch,
):
    # Both canonical artifacts re-serialize to the exact ratified byte pairs.
    authority = _real_authority()
    artifacts = authority["canonical_artifacts"]
    cohort_bytes = ratchet._canonical_json_bytes(artifacts["original_cohort"], terminal_lf=True)
    provenance_bytes = ratchet._canonical_json_bytes(artifacts["sdk_provenance"], terminal_lf=True)
    assert len(cohort_bytes) == ratchet.COHORT_ARTIFACT["byte_length"]
    assert ratchet._sha256_bytes(cohort_bytes) == ratchet.COHORT_ARTIFACT["sha256"]
    assert len(provenance_bytes) == ratchet.PROVENANCE_ARTIFACT["byte_length"]
    assert ratchet._sha256_bytes(provenance_bytes) == ratchet.PROVENANCE_ARTIFACT["sha256"]
    # A transition that changes artifact bytes is rejected before any set
    # comparison is attempted.
    head = _real_authority()
    head["canonical_artifacts"]["original_cohort"]["original_records"][0][
        "exact_historical_literal_record"
    ] += "-drift"
    monkeypatch.setattr(ratchet, "validate_accepted_authority", lambda *a, **k: {})
    with pytest.raises(ValueError, match="immutable authority bindings changed"):
        ratchet.compare_accepted_authorities(_real_authority(), head, repo_root=_REPO_ROOT)


def test_ratified_literal_anchors_and_original_descriptor_never_change_across_transition():
    # The ratified anchors are pinned: category tuple, genesis disposition,
    # and the sole normative original-ID set digest.
    authority = _real_authority()
    assert authority["categories"] == list(ratchet.ACCEPTED_CATEGORIES)
    assert ratchet.GENESIS_DISPOSITION == {
        "as_of": "2026-04-17",
        "evidence": "canonical-original-cohort-v1",
        "status": "active",
    }
    cohort = authority["canonical_artifacts"]["original_cohort"]
    assert cohort["original_record_id_set"]["sha256"] == ratchet.ORIGINAL_ID_SET_SHA256
    # The original descriptor is exactly (category, exact historical literal):
    # changing either re-derives a different ID and fails closed.
    tampered = copy.deepcopy(cohort)
    tampered["original_records"][0]["exact_historical_literal_record"] += "!"
    with pytest.raises(ValueError, match="ID payload length mismatch|ID payload digest mismatch"):
        ratchet._validate_original_cohort(tampered)
    recategorized = copy.deepcopy(cohort)
    record = next(
        item for item in recategorized["original_records"] if item["category"] == "python_sdk_drift"
    )
    record["category"] = "typescript_sdk_drift"
    with pytest.raises(ValueError, match="mismatch"):
        ratchet._validate_original_cohort(recategorized)


def test_transition_reconstructs_all_655_ids_and_598_provenance_records():
    # The validator independently reconstructs the full closure end to end.
    summary = ratchet.validate_accepted_authority(_real_authority(), repo_root=_REPO_ROOT)
    assert summary["original_record_total"] == 655
    assert summary["sdk_provenance_record_total"] == 598
    assert len(summary["active_original_record_ids"]) == 288
    # The genesis reconstruction of the committed authority still spans the
    # full 655-record cohort — paydown resolves records, never removes them.
    genesis_summary = ratchet.validate_accepted_authority(
        _genesis_authority(_real_authority()), repo_root=_REPO_ROOT
    )
    assert len(genesis_summary["active_original_record_ids"]) == 655
    # Reconstruction is not trust-the-artifact: a self-consistent-looking but
    # wrong ID payload digest is recomputed and rejected.
    cohort = _real_authority()["canonical_artifacts"]["original_cohort"]
    cohort["original_records"][7]["id_payload_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="ID payload digest mismatch"):
        ratchet._validate_original_cohort(cohort)
    # Provenance records are reconstructed against the cohort link plane.
    authority = _real_authority()
    cohort_summary = ratchet._validate_original_cohort(
        authority["canonical_artifacts"]["original_cohort"]
    )
    provenance = authority["canonical_artifacts"]["sdk_provenance"]
    short = copy.deepcopy(provenance)
    short["records"] = short["records"][:-1]
    with pytest.raises(ValueError, match="must contain 598 records"):
        ratchet._validate_sdk_provenance(short, cohort_summary)


def test_transition_preserves_exact_provenance_links_counts_partitions_and_digests():
    authority = _real_authority()
    cohort_summary = ratchet._validate_original_cohort(
        authority["canonical_artifacts"]["original_cohort"]
    )
    provenance = authority["canonical_artifacts"]["sdk_provenance"]
    summary = ratchet._validate_sdk_provenance(provenance, cohort_summary)
    # Exact 598/690/12/0/75/523 counts and the ratified partition digests.
    assert summary["record_count"] == 598
    assert summary["source_occurrence_count"] == 690
    assert summary["multiple_atom_record_count"] == 12
    assert summary["missing_provenance_count"] == 0
    assert summary["core_count"] == 75
    assert summary["extended_count"] == 523
    assert summary["core_original_record_id_set_sha256"] == ratchet.CORE_ID_SET_SHA256
    assert summary["extended_original_record_id_set_sha256"] == ratchet.EXTENDED_ID_SET_SHA256
    assert summary["sdk_original_record_id_set_sha256"] == ratchet.SDK_ID_SET_SHA256
    assert len(summary["record_links"]) == 598
    # Per-record links/partitions are reconstructed, not declared: flipping a
    # declared partition fails against the atom-derived partition.
    flipped = copy.deepcopy(provenance)
    flipped["records"][0]["partition"] = (
        "extended" if flipped["records"][0]["partition"] == "core" else "core"
    )
    with pytest.raises(ValueError, match="partition mismatch|digest mismatch"):
        ratchet._validate_sdk_provenance(flipped, cohort_summary)
    miscounted = copy.deepcopy(provenance)
    miscounted["counts"]["source_occurrences"] = 691
    with pytest.raises(ValueError, match="declared counts mismatch"):
        ratchet._validate_sdk_provenance(miscounted, cohort_summary)


def test_transition_preserves_exact_global_and_per_category_original_record_sets():
    cohort = _real_authority()["canonical_artifacts"]["original_cohort"]
    by_category: dict[str, list[str]] = {}
    for record in cohort["original_records"]:
        by_category.setdefault(record["category"], []).append(record["original_record_id"])
    assert {name: len(ids) for name, ids in sorted(by_category.items())} == {
        "python_sdk_drift": 74,
        "routes_missing_in_spec": 11,
        "routes_orphaned_in_spec": 17,
        "sdk_missing_from_both": 29,
        "typescript_sdk_drift": 524,
    }
    # The global set digest is recomputed from the exact IDs and must be the
    # sole normative digest across every transition.
    all_ids = [record["original_record_id"] for record in cohort["original_records"]]
    assert len(set(all_ids)) == 655
    recomputed = ratchet._digest_set(
        "cdg-original-record-id-set-v1", all_ids, "original_record_ids"
    )
    assert recomputed == ratchet.ORIGINAL_ID_SET_SHA256
    # Any other digest fails: swapping in a different 655th ID breaks both
    # the ID-set listing and the digest.
    swapped = copy.deepcopy(cohort)
    swapped["original_record_id_set"]["original_record_ids"][-1] = "cdg1:" + "0" * 64
    with pytest.raises(ValueError, match="ID set is incomplete or unsorted"):
        ratchet._validate_original_cohort(swapped)


def test_transition_rejects_addition_removal_replacement_dedup_fanout_or_reidentification():
    base_cohort = _real_authority()["canonical_artifacts"]["original_cohort"]
    # Addition and removal break the exact 655 cardinality.
    grown = copy.deepcopy(base_cohort)
    grown["original_records"].append(copy.deepcopy(grown["original_records"][0]))
    with pytest.raises(ValueError, match="exactly 655 original records"):
        ratchet._validate_original_cohort(grown)
    shrunk = copy.deepcopy(base_cohort)
    shrunk["original_records"].pop()
    with pytest.raises(ValueError, match="exactly 655 original records"):
        ratchet._validate_original_cohort(shrunk)
    # Replacement/re-identification: the ID derives only from the descriptor,
    # so a swapped literal or category cannot keep its recorded ID.
    replaced = copy.deepcopy(base_cohort)
    replaced["original_records"][3]["exact_historical_literal_record"] += " replaced"
    with pytest.raises(ValueError, match="mismatch"):
        ratchet._validate_original_cohort(replaced)
    # Dedup/fanout: membership multiplicity is pinned via the projection
    # bijection — duplicating one membership and dropping another fails.
    faned = copy.deepcopy(base_cohort)
    projection_records = faned["operation_projection"]["records"]
    projection_records[1] = copy.deepcopy(projection_records[0])
    with pytest.raises(ValueError, match="does not biject|digest"):
        ratchet._validate_original_cohort(faned)


def test_operation_projection_revision_preserves_655_memberships_666_complete_edges_nine_multi_edge_and_max_four():  # noqa: E501
    summary = ratchet.validate_accepted_authority(_real_authority(), repo_root=_REPO_ROOT)
    projection = summary["operation_projection"]
    assert projection["membership_count"] == 655
    assert projection["edge_count"] == 666
    assert projection["multi_edge_originals"] == 9
    assert projection["max_edges"] == 4
    assert projection["record_digest_set_sha256"] == ratchet.PROJECTION_RECORD_SET_SHA256
    distribution = projection["edge_count_distribution"]
    assert sum(int(size) * count for size, count in distribution.items()) == 666
    assert sum(count for size, count in distribution.items() if int(size) > 1) == 9
    assert max(int(size) for size in distribution) == 4
    # A revision that drops one witnessed edge (even with a relinked record
    # digest) cannot reproduce the pinned record-digest set.
    cohort = _real_authority()["canonical_artifacts"]["original_cohort"]
    record = next(
        item
        for item in cohort["operation_projection"]["records"]
        if len(item["operation_edges"]) > 1
    )
    record["operation_edges"].pop()
    relinked = {key: value for key, value in record.items() if key != "record_sha256"}
    record["record_sha256"] = ratchet._sha256_bytes(ratchet._canonical_json_bytes(relinked))
    with pytest.raises(ValueError, match="record-digest-set mismatch|cardinality mismatch"):
        ratchet._validate_original_cohort(cohort)


def test_operation_projection_revision_cannot_change_original_identity_or_omit_witnessed_edge():
    cohort = _real_authority()["canonical_artifacts"]["original_cohort"]
    # Re-identifying a projection membership breaks the cohort bijection.
    reidentified = copy.deepcopy(cohort)
    record = reidentified["operation_projection"]["records"][0]
    record["original_record_id"] = "cdg1:" + "1" * 64
    relinked = {key: value for key, value in record.items() if key != "record_sha256"}
    record["record_sha256"] = ratchet._sha256_bytes(ratchet._canonical_json_bytes(relinked))
    with pytest.raises(ValueError, match="does not biject|record-digest-set mismatch"):
        ratchet._validate_original_cohort(reidentified)
    # Omitting a witnessed edge's evidence fails closed: every edge must
    # carry nonempty witness evidence.
    unwitnessed = copy.deepcopy(cohort)
    edge_record = unwitnessed["operation_projection"]["records"][0]
    edge_record["operation_edges"][0]["evidence"] = []
    relinked = {key: value for key, value in edge_record.items() if key != "record_sha256"}
    edge_record["record_sha256"] = ratchet._sha256_bytes(ratchet._canonical_json_bytes(relinked))
    with pytest.raises(ValueError, match="lacks evidence|record-digest-set mismatch"):
        ratchet._validate_original_cohort(unwitnessed)


def test_null_method_never_enters_runtime_or_projection_edges():
    cohort = _real_authority()["canonical_artifacts"]["original_cohort"]
    # Exactly the 57 path-level route/parity originals carry method=null.
    null_methods = [
        record["category"] for record in cohort["original_records"] if record["method"] is None
    ]
    assert len(null_methods) == 57
    assert set(null_methods) == {
        "routes_missing_in_spec",
        "routes_orphaned_in_spec",
        "sdk_missing_from_both",
    }
    # Every projected operation edge carries an exact uppercase method token.
    for record in cohort["operation_projection"]["records"]:
        for edge in record["operation_edges"]:
            assert isinstance(edge["method"], str) and edge["method"].isupper()
    # A null method in a projection edge fails closed.
    nulled = copy.deepcopy(cohort)
    edge_record = nulled["operation_projection"]["records"][0]
    edge_record["operation_edges"][0]["method"] = None
    relinked = {key: value for key, value in edge_record.items() if key != "record_sha256"}
    edge_record["record_sha256"] = ratchet._sha256_bytes(ratchet._canonical_json_bytes(relinked))
    with pytest.raises(ValueError, match="invalid method|record-digest-set mismatch"):
        ratchet._validate_original_cohort(nulled)
    # An SDK record with a null method fails closed (598 are method-bearing).
    stripped = copy.deepcopy(cohort)
    sdk_record = next(
        item for item in stripped["original_records"] if item["category"] == "python_sdk_drift"
    )
    sdk_record["method"] = None
    with pytest.raises(ValueError, match="lacks a method"):
        ratchet._validate_original_cohort(stripped)


def test_strict_subset_requires_separate_authenticated_paydown():
    root = _REPO_ROOT
    authority = _real_authority()
    summary = ratchet.validate_accepted_authority(authority, repo_root=root)
    live = set(summary["live_original_record_ids"])
    live_digest = ratchet._sha256_bytes(ratchet._canonical_json_bytes(sorted(live)))

    def resolve(target: dict, digest: str) -> None:
        for item in target["active_inventory"]:
            if item["original_record_id"] in live:
                continue
            fact = {
                "active_original_record_ids_sha256": digest,
                "as_of": "2026-07-27",
                "original_record_id": item["original_record_id"],
            }
            item.update(
                status="resolved",
                disposition_history=[
                    ratchet.GENESIS_DISPOSITION,
                    {
                        "as_of": fact["as_of"],
                        "evidence": _relink_fact(ratchet.PAYDOWN_SCHEMA, fact),
                        "status": "resolved",
                    },
                ],
            )
        target["active_inventory_sha256"] = ratchet._sha256_bytes(
            ratchet._canonical_json_bytes(target["active_inventory"])
        )
        _relink_authority_manifest(target)

    # A strict subset with exact appended paydown evidence is a paydown
    # disposition — not a transition — and passes the comparison. Build the
    # synthetic paydown from the all-active genesis base so its histories
    # append to the base rather than rewriting committed paydown events.
    genesis = _genesis_authority(authority)
    paydown = copy.deepcopy(genesis)
    resolve(paydown, live_digest)
    compared = ratchet.compare_accepted_authorities(genesis, paydown, repo_root=root)
    assert compared["passing"] is True
    assert len(compared["removed_original_record_ids"]) == 367
    assert compared["authority"] == {"source": "accepted_authority"}
    assert "transition" not in compared
    # The same subset without the exact appended active-set digest cannot be
    # folded through: it fails the paydown authentication.
    unauthenticated = copy.deepcopy(genesis)
    resolve(unauthenticated, "0" * 64)
    with pytest.raises(ValueError, match="exact appended paydown evidence"):
        ratchet.compare_accepted_authorities(genesis, unauthenticated, repo_root=root)


def test_transition_changes_only_versioned_analyzer_schema_dependency_projection_evidence_and_active_representation(  # noqa: E501
    monkeypatch: pytest.MonkeyPatch,
):
    # Original identities are frozen: canonical artifacts and the analyzer
    # bundle cannot drift through an ordinary comparison.
    monkeypatch.setattr(ratchet, "validate_accepted_authority", lambda *a, **k: {})
    for mutate in (
        lambda head: head["canonical_artifacts"]["original_cohort"]["original_records"][0].update(
            {"exact_historical_literal_record": "swapped"}
        ),
        lambda head: head["analyzer_bundle"].update({"dependencies": ["pyyaml==6.0"]}),
    ):
        head = _real_authority()
        mutate(head)
        with pytest.raises(ValueError, match="immutable authority bindings changed"):
            ratchet.compare_accepted_authorities(_real_authority(), head, repo_root=_REPO_ROOT)
    # The active representation may only move append-only: truncating a
    # disposition history is rejected.
    base = _real_authority()
    event = {
        "as_of": "2026-07-27",
        "evidence": _relink_fact(
            ratchet.PAYDOWN_SCHEMA,
            {
                "active_original_record_ids_sha256": "1" * 64,
                "as_of": "2026-07-27",
                "original_record_id": base["active_inventory"][0]["original_record_id"],
            },
        ),
        "status": "resolved",
    }
    base["active_inventory"][0]["disposition_history"] = [ratchet.GENESIS_DISPOSITION, event]
    truncated = copy.deepcopy(base)
    truncated["active_inventory"][0]["disposition_history"] = [ratchet.GENESIS_DISPOSITION]
    with pytest.raises(ValueError, match="append-only"):
        ratchet.compare_accepted_authorities(base, truncated, repo_root=_REPO_ROOT)


def test_post_merge_authority_capsule_is_full_merge_sha_bound():
    # Pre-merge, publication is exactly the pending future-capsule marker.
    assert _real_authority()["publication"] == {
        "authority": "future-immutable-github-release-capsule",
        "status": "pending-merge",
    }
    # The durable capsule validator binds the release tag to the exact full
    # merge SHA: any other tag fails closed.
    end_sha = "5" * 40
    capsule = {
        "attestation": _stable_attestation_claim(),
        "boundary": "corrective_bootstrap",
        "end_sha": end_sha,
        "release": {
            "asset_names": ["manifest.json", "payload.json", "checksums.txt"],
            "exact_full_sha_tag": end_sha,
            "immutable": True,
            "release_api_id": 100,
            "tag_name": f"cdg-corrective_bootstrap-{end_sha}",
            "verified": True,
        },
        "schema": "contract-drift-durable-capsule-v1",
        "start_sha": "1" * 40,
    }
    validated = ratchet._validate_durable_capsule(
        capsule, boundary="corrective_bootstrap", end_sha=end_sha
    )
    assert validated["release"]["exact_full_sha_tag"] == end_sha
    assert validated["release"]["tag_name"] == f"cdg-corrective_bootstrap-{end_sha}"
    retagged = copy.deepcopy(capsule)
    retagged["release"]["exact_full_sha_tag"] = "4" * 40
    with pytest.raises(ValueError, match="not the exact end SHA"):
        ratchet._validate_durable_capsule(
            retagged, boundary="corrective_bootstrap", end_sha=end_sha
        )
    # GitHub rejects bare 40/64-hex tag names (HTTP 422), so the claimed
    # tag_name must be exactly the fixed-prefix capsule form. A bare-SHA
    # legacy tag_name, a wrong prefix, and a wrong boundary all fail closed.
    for wrong_tag in (
        end_sha,
        f"CDG-corrective_bootstrap-{end_sha}",
        f"cdg-route_truth-{end_sha}",
        f"backfill-{end_sha}",
    ):
        hostile = copy.deepcopy(capsule)
        hostile["release"]["tag_name"] = wrong_tag
        with pytest.raises(ValueError, match="fixed-prefix capsule tag"):
            ratchet._validate_durable_capsule(
                hostile, boundary="corrective_bootstrap", end_sha=end_sha
            )
    # The prefixed tag must embed this boundary's end SHA, not another SHA.
    moved = copy.deepcopy(capsule)
    moved["release"]["tag_name"] = f"cdg-corrective_bootstrap-{'4' * 40}"
    with pytest.raises(ValueError, match="fixed-prefix capsule tag"):
        ratchet._validate_durable_capsule(moved, boundary="corrective_bootstrap", end_sha=end_sha)


def test_accepted_authority_capsule_pins_artifact_manifest_payload_checksums_attestation_rule_suite_sets_and_edges():  # noqa: E501
    end_sha = "5" * 40
    capsule = {
        "attestation": _stable_attestation_claim(),
        "boundary": "corrective_bootstrap",
        "end_sha": end_sha,
        "release": {
            "asset_names": ["manifest.json", "payload.json", "checksums.txt"],
            "exact_full_sha_tag": end_sha,
            "immutable": True,
            "release_api_id": 100,
            "tag_name": f"cdg-corrective_bootstrap-{end_sha}",
            "verified": True,
        },
        "schema": "contract-drift-durable-capsule-v1",
        "start_sha": "1" * 40,
    }
    # The capsule pins exactly the manifest/payload/checksums asset triple.
    partial = copy.deepcopy(capsule)
    partial["release"]["asset_names"] = ["manifest.json", "payload.json"]
    with pytest.raises(ValueError, match="asset names are incomplete or noncanonical"):
        ratchet._validate_durable_capsule(partial, boundary="corrective_bootstrap", end_sha=end_sha)
    # Entry 32: a stale-schema payload still carrying asset_api_ids fails
    # closed — the release claim binds only publication-time-knowable fields.
    stale_schema = copy.deepcopy(capsule)
    stale_schema["release"]["asset_api_ids"] = [101, 102, 103]
    with pytest.raises(ValueError, match="durable release claim fields"):
        ratchet._validate_durable_capsule(
            stale_schema, boundary="corrective_bootstrap", end_sha=end_sha
        )
    # A claim that DROPS a required pre-known field fails the same exact-shape
    # check: the retained binding set is mandatory, not optional.
    missing_release_id = copy.deepcopy(capsule)
    del missing_release_id["release"]["release_api_id"]
    with pytest.raises(ValueError, match="durable release claim fields"):
        ratchet._validate_durable_capsule(
            missing_release_id, boundary="corrective_bootstrap", end_sha=end_sha
        )
    # Attestation provenance is exactly actions/attest@v4 with the stable
    # release-attestation identity plane (entry 30): signer SAN regexp and
    # predicateType. A wrong workflow, signer, or predicate fails closed, as
    # does the retired output-digest claim shape.
    unattested = copy.deepcopy(capsule)
    unattested["attestation"]["workflow"] = "actions/attest@v3"
    with pytest.raises(ValueError, match="attestation workflow identity mismatch"):
        ratchet._validate_durable_capsule(
            unattested, boundary="corrective_bootstrap", end_sha=end_sha
        )
    wrong_signer = copy.deepcopy(capsule)
    wrong_signer["attestation"]["signer_san_regexp"] = r"^https://evil\.example\.com$"
    with pytest.raises(ValueError, match="signer identity mismatch"):
        ratchet._validate_durable_capsule(
            wrong_signer, boundary="corrective_bootstrap", end_sha=end_sha
        )
    wrong_predicate = copy.deepcopy(capsule)
    wrong_predicate["attestation"]["predicate_type"] = "https://slsa.dev/provenance/v1"
    with pytest.raises(ValueError, match="predicate type mismatch"):
        ratchet._validate_durable_capsule(
            wrong_predicate, boundary="corrective_bootstrap", end_sha=end_sha
        )
    legacy_digest_claim = copy.deepcopy(capsule)
    legacy_digest_claim["attestation"] = {
        "bundle_sha256": "6" * 64,
        "verified": True,
        "workflow": "actions/attest@v4",
    }
    with pytest.raises(ValueError, match="signer identity mismatch"):
        ratchet._validate_durable_capsule(
            legacy_digest_claim, boundary="corrective_bootstrap", end_sha=end_sha
        )
    # Rule-suite pass results are part of the boundary prerequisites: a
    # bypassed evaluation can never authenticate.
    with pytest.raises(ValueError, match="bypassed evaluation"):
        ratchet._validate_rule_suite_record_fields(
            _rule_suite_record(end_sha, rule_evaluations=[{"result": "bypass"}]),
            repository_id=1126097105,
            repository_name="aragora",
            expected_ref="refs/heads/main",
            end_sha=end_sha,
        )
    # The capsule-bound sets/edges plane is the pinned projection digest.
    summary = ratchet.validate_accepted_authority(_real_authority(), repo_root=_REPO_ROOT)
    assert (
        summary["operation_projection"]["record_digest_set_sha256"]
        == ratchet.PROJECTION_RECORD_SET_SHA256
    )


def test_release_replacement_deletion_or_tag_reuse_is_detected():
    end_sha = "5" * 40
    capsule = {
        "attestation": _stable_attestation_claim(),
        "boundary": "corrective_bootstrap",
        "end_sha": end_sha,
        "release": {
            "asset_names": ["manifest.json", "payload.json", "checksums.txt"],
            "exact_full_sha_tag": end_sha,
            "immutable": True,
            "release_api_id": 100,
            "tag_name": f"cdg-corrective_bootstrap-{end_sha}",
            "verified": True,
        },
        "schema": "contract-drift-durable-capsule-v1",
        "start_sha": "1" * 40,
    }
    # A replaced (mutable) or unverified release fails closed.
    for field in ("immutable", "verified"):
        mutable = copy.deepcopy(capsule)
        mutable["release"][field] = False
        with pytest.raises(ValueError, match="false or missing"):
            ratchet._validate_durable_capsule(
                mutable, boundary="corrective_bootstrap", end_sha=end_sha
            )
    # Tag reuse from any other SHA is detected by exact-tag binding.
    reused = copy.deepcopy(capsule)
    reused["release"]["exact_full_sha_tag"] = "9" * 40
    with pytest.raises(ValueError, match="not the exact end SHA"):
        ratchet._validate_durable_capsule(reused, boundary="corrective_bootstrap", end_sha=end_sha)
    # Replacement/deletion of the remote resource surfaces as identity
    # movement, which blocks rather than silently passing.
    assert ratchet._remote_identity_moved({"etag": '"a"'}, {"etag": '"b"'}) is True
    assert (
        ratchet._remote_identity_moved(
            {"etag": '"a"', "updated_at": "t"}, {"etag": '"a"', "updated_at": "t"}
        )
        is False
    )
    with pytest.raises(ratchet.BoundaryBlocked, match="moved"):
        ratchet._retry_stable_remote_probe(lambda: ({"etag": '"a"'}, {"etag": '"b"'}), attempts=2)


def test_transition_uses_hermetic_base_bundle_and_hashed_dependencies():
    # The accepted analyzer bundle execution contract is hermetic: empty
    # hashed dependency manifest, pinned isolation flags, pinned launcher.
    metadata, files = ratchet._bundle_metadata(_real_authority())
    assert metadata["dependencies"] == []
    assert metadata["interpreter_flags"] == list(ratchet.ANALYZER_FLAGS)
    assert ratchet.ANALYZER_FLAGS == ("-I", "-S", "-B")
    assert metadata["launcher_sha256"] == ratchet._sha256_bytes(ratchet.HERMETIC_LAUNCHER)
    assert [binding["path"] for binding in files] == list(ratchet.ANALYZER_BUNDLE_FILES)
    for binding in files:
        assert len(binding["sha256"]) == 64
    # The launcher itself enforces its own digest before executing anything.
    assert b"CDG_EXECUTED_LAUNCHER_SHA256" in ratchet.HERMETIC_LAUNCHER
    # Any drift in the execution contract fails closed.
    for mutate in (
        lambda bundle: bundle.update({"dependencies": ["requests==2.32.0"]}),
        lambda bundle: bundle.update({"interpreter_flags": ["-I"]}),
        lambda bundle: bundle.update({"launcher_sha256": "0" * 64}),
    ):
        drifted = _real_authority()
        mutate(drifted["analyzer_bundle"])
        with pytest.raises(ValueError, match="execution contract mismatch"):
            ratchet._bundle_metadata(drifted)


def test_transition_chronology_binds_base_head_checks_evidence_settlement_run_attempt_and_merge(
    tmp_path: Path,
):
    # BASE/HEAD binding: chronology must start at the bound base and end at
    # the bound head, in exact order.
    repo, start_sha, boundary_shas = _boundary_git_repo(tmp_path)
    end_sha = boundary_shas["corrective_bootstrap"]
    chronology = {
        "boundaries": [{"boundary": "corrective_bootstrap", "sha": end_sha}],
        "boundary": "corrective_bootstrap",
        "end_sha": end_sha,
        "schema": "contract-drift-boundary-chronology-v1",
        "start_sha": start_sha,
    }
    validated = ratchet._validate_boundary_chronology(
        chronology,
        repo_root=repo,
        boundary="corrective_bootstrap",
        start_sha=start_sha,
        end_sha=end_sha,
        operation_log=[],
    )
    assert validated["corrective_bootstrap"] == end_sha
    moved_head = copy.deepcopy(chronology)
    with pytest.raises(ValueError, match="does not equal end SHA"):
        ratchet._validate_boundary_chronology(
            moved_head,
            repo_root=repo,
            boundary="corrective_bootstrap",
            start_sha=start_sha,
            end_sha=boundary_shas["route_truth"],
            operation_log=[],
        )
    # Settlement identity binds the exact head before any merge action.
    moved = settle.evaluate_tier4_settlement_preconditions(
        pr=9645,
        expected_head="a" * 40,
        pr_view=_settle_pr_view("b" * 40),
        merge_packet=_settle_packet(9645),
        required_checks=[{"name": "x", "state": "SUCCESS"}],
    )
    assert any("head mismatch" in blocker for blocker in moved["blockers"])
    # Post-settlement execution identity is (run_id, run_attempt) and the
    # comparison signal is attempt- and base+head-specific.
    run = bootstrap._validate_run_provenance(
        bootstrap.RunProvenance(
            event_name="pull_request_target",
            repository="synaptent/aragora",
            run_attempt=2,
            run_id=777,
            workflow_ref=bootstrap.EXPECTED_WORKFLOW_REF,
        )
    )
    signal = bootstrap._write_comparison_signal(
        tmp_path,
        "1" * 40,
        "2" * 40,
        "3" * 40,
        {"path": "digest"},
        {"authority": True},
        {"bundle": True},
        [{"schema": "artifact"}],
        run,
    )
    assert bootstrap._authenticate_comparison_signal(
        signal, base_sha="1" * 40, head_sha="2" * 40, workflow_run=run
    )
    for base_sha, head_sha, workflow_run in (
        ("9" * 40, "2" * 40, run),
        ("1" * 40, "9" * 40, run),
        ("1" * 40, "2" * 40, {**run, "run_attempt": 3}),
    ):
        with pytest.raises(bootstrap.BootstrapError, match="comparison signal is invalid"):
            bootstrap._authenticate_comparison_signal(
                signal, base_sha=base_sha, head_sha=head_sha, workflow_run=workflow_run
            )


def test_strict_false_main_or_head_movement_restarts_all_evidence(
    monkeypatch: pytest.MonkeyPatch,
):
    # Head movement invalidates the settlement gate and authorizes nothing.
    moved_gate = settle.evaluate_tier4_gate(
        pr=9645,
        expected_head="a" * 40,
        pr_view=_settle_pr_view("b" * 40),
        merge_packet=_settle_packet(9645),
        required_checks=[{"name": "x", "state": "SUCCESS"}],
        permission_checker=lambda _login: True,
    )
    assert not moved_gate["ok"]
    assert moved_gate["authorized_actions"] == []
    # Main/remote movement during evidence collection blocks the boundary
    # (restart), never a partial pass.
    tick = {"count": 0}

    def moving_probe():
        tick["count"] += 1
        return {"noise": tick["count"]}, {"etag": f'"v{tick["count"]}"'}

    with pytest.raises(ratchet.BoundaryBlocked, match="moved concurrently"):
        ratchet._retry_stable_remote_probe(moving_probe, attempts=3)
    # A strict-false (contradictory) reread fails loudly rather than reusing
    # stale evidence.
    bodies = iter([b"one", b"two"])

    def contradictory(endpoint: str, *, operation_log: list, attempts: int = 3):
        del endpoint, attempts
        operation_log.append({})
        return next(bodies), {"etag": '"same"'}

    monkeypatch.setattr(ratchet, "_gh_api_get_raw", contradictory)
    with pytest.raises(ValueError, match="contradicted stable identity"):
        ratchet._gh_api_get_raw_stable("repos/synaptent/aragora/releases/1", operation_log=[])


def test_transition_merge_first_parent_equals_bound_base():
    # The transition merge receipt freezes first parent == BASE_SHA.
    def receipt(**overrides: Any) -> dict[str, Any]:
        record = {
            "base_sha": CORRECTIVE_BASE_SHA,
            "first_parent_sha": CORRECTIVE_BASE_SHA,
            "head_sha": "2" * 40,
            "head_tree_sha": "3" * 40,
            "merge_sha": "4" * 40,
            "merge_tree_sha": "3" * 40,
            "pr": 9645,
            **overrides,
        }
        return {
            "boundary": "corrective_bootstrap",
            "end_sha": "4" * 40,
            "records": [record],
            "schema": "contract-drift-first-parent-receipts-v1",
            "start_sha": CORRECTIVE_BASE_SHA,
        }

    validated = ratchet._validate_first_parent_receipts(receipt())
    assert validated[0]["first_parent_sha"] == CORRECTIVE_BASE_SHA
    with pytest.raises(ValueError, match="does not equal the frozen base SHA"):
        ratchet._validate_first_parent_receipts(receipt(first_parent_sha="9" * 40))


def test_identical_settlement_identity_is_retry_safe_with_base_and_head(
    monkeypatch: pytest.MonkeyPatch,
):
    head = "e" * 40
    # The settlement identity is a pure function of (pr, head): a retry can
    # only ever produce the byte-identical settlement text naming the head.
    first = settle._settlement_comment_template(pr=9645, head=head)
    assert first == settle._settlement_comment_template(pr=9645, head=head)
    assert head in first and "#9645" in first
    assert settle._settlement_comment_template(pr=9645, head="f" * 40) != first

    def forbid_writes(*_args, **_kwargs):
        raise AssertionError("gate evaluation must not run commands")

    monkeypatch.setattr(settle, "_run_command", forbid_writes)
    monkeypatch.setattr(settle, "_run_text_command", forbid_writes)
    view = _settle_pr_view(head, comments=[_settlement_comment(9645, head)])
    gate = settle.evaluate_tier4_gate(
        pr=9645,
        expected_head=head,
        pr_view=view,
        merge_packet=_settle_packet(9645),
        required_checks=[{"name": "x", "state": "SUCCESS"}],
        permission_checker=lambda _login: True,
    )
    retried = settle.evaluate_tier4_gate(
        pr=9645,
        expected_head=head,
        pr_view=view,
        merge_packet=_settle_packet(9645),
        required_checks=[{"name": "x", "state": "SUCCESS"}],
        permission_checker=lambda _login: True,
    )
    assert gate["ok"] and retried["ok"]
    assert gate["authorized_actions"] == retried["authorized_actions"]


def test_settlement_helper_never_merges(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    recorded: list[list[str]] = []

    def record_text(command: list[str], *, cwd: Path, input_text: str | None = None) -> str:
        del cwd, input_text
        recorded.append(command)
        return "https://example.test/comment"

    def record(command: list[str], *, cwd: Path, input_text: str | None = None) -> None:
        del cwd, input_text
        recorded.append(command)

    monkeypatch.setattr(settle, "_run_text_command", record_text)
    monkeypatch.setattr(settle, "_run_command", record)
    settle._apply_settlement_signal(pr=9645, head="f" * 40, repo="synaptent/aragora", cwd=tmp_path)
    assert [command[:3] for command in recorded] == [
        ["gh", "pr", "comment"],
        ["gh", "api", "--method"],
    ]
    flattened = " ".join(part for command in recorded for part in command)
    assert " merge" not in f" {flattened}"
    # Settle-only cannot be combined with the merge phase in one invocation.
    with pytest.raises(SystemExit):
        settle.build_parser().parse_args(
            ["--settle-only", "--merge-apply", "--pr", "9645", "--head", "f" * 40]
        )


def test_admin_merge_is_rejected():
    # A protection-bypassing merge is visible as a bypassed rule evaluation
    # and fails the boundary closed, in every shape GitHub reports it.
    assert ratchet._contains_rule_suite_bypass({"result": "bypass"})
    assert ratchet._contains_rule_suite_bypass(
        {"rule_evaluations": [{"result": "pass"}, {"evaluation_result": "bypass"}]}
    )
    assert ratchet._contains_rule_suite_bypass({"bypass_actors": [123]})
    assert not ratchet._contains_rule_suite_bypass({"result": "pass", "bypassed": False})
    with pytest.raises(ValueError, match="bypassed evaluation"):
        ratchet._validate_rule_suite_record_fields(
            _rule_suite_record("5" * 40, rule_evaluations=[{"result": "bypass"}]),
            repository_id=1126097105,
            repository_name="aragora",
            expected_ref="refs/heads/main",
            end_sha="5" * 40,
        )
    # A rule suite that did not pass cannot satisfy the boundary either.
    with pytest.raises(ValueError, match="not passing"):
        ratchet._validate_rule_suite_record_fields(
            _rule_suite_record("5" * 40, result="failed", evaluation_result="failed"),
            repository_id=1126097105,
            repository_name="aragora",
            expected_ref="refs/heads/main",
            end_sha="5" * 40,
        )


def test_legacy_entrypoints_delegate_to_canonical_inventory(monkeypatch: pytest.MonkeyPatch):
    # The ratchet imports the canonical inventory module and defaults every
    # mode to the canonical inventory path.
    assert ratchet.inventory_mod is gen
    assert gen.DEFAULT_INVENTORY == "scripts/baselines/contract_drift_inventory.json"
    main_source = inspect.getsource(ratchet.main)
    assert "inventory_mod.DEFAULT_INVENTORY" in main_source
    # Legacy program/receipt entrypoints route through the accepted authority
    # (build_accepted_result -> validate_accepted_authority) — never through
    # a parallel raw-baseline reader.
    calls: list[tuple[str | None, str | None]] = []

    def fake_validate(
        authority: dict[str, Any],
        *,
        repo_root: Path,
        live_ref: str | None = None,
        residue_ref: str | None = None,
    ) -> dict[str, Any]:
        calls.append((live_ref, residue_ref))
        return {
            "active_original_record_ids": [],
            "analyzer_bundle_sha256": "",
            "live_original_record_ids": [],
        }

    monkeypatch.setattr(ratchet, "validate_accepted_authority", fake_validate)
    source = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    parent = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "rev-parse", f"{source}^"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    result = ratchet.build_accepted_result(
        mode="receipt",
        repo_root=_REPO_ROOT,
        inventory_path=_REPO_ROOT / gen.DEFAULT_INVENTORY,
        source_sha=source,
    )
    assert calls == [(source, parent)]
    assert result["authority"]["source"] == "accepted_authority"
    # Live-witness reconciliation delegates to the canonical inventory
    # loaders rather than reading baselines through a private copy.
    live_source = inspect.getsource(ratchet._live_witnesses)
    assert "inventory_mod.load_git_docs" in live_source
    assert "inventory_mod.collect_ids" in live_source


def test_historical_receipt_mode_supports_the_exact_9320_pair(
    monkeypatch: pytest.MonkeyPatch,
):
    assert ensure_pr_9320_head(_CDG_TEST_ROOT) == PR_9320_FACT["head_sha"]
    monkeypatch.setattr(
        ratchet,
        "validate_accepted_authority",
        lambda *args, **kwargs: {
            "active_original_record_ids": [],
            "analyzer_bundle_sha256": "",
            "live_original_record_ids": [],
        },
    )
    result = ratchet.build_accepted_result(
        mode="receipt",
        repo_root=_REPO_ROOT,
        inventory_path=_REPO_ROOT / gen.DEFAULT_INVENTORY,
        source_sha=subprocess.check_output(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            text=True,
        ).strip(),
        historical_base_sha="14d1ef53e23c5466c0491ed93f72752944c78cd4",
        historical_head_sha="aba6b14c94eca3a9c825b1a303ea67684d5f8daa",
        historical_merge_sha="0b28f68b9f4d204ae14814169093723ea84c1364",
        historical_first_parent_sha="e448b840dad03ee28accd218c14a27fa8b87c7b4",
    )
    assert result["status"] == "pass"
    assert result["passing"] is True
    assert result["execution"] == {
        "base_sha": "14d1ef53e23c5466c0491ed93f72752944c78cd4",
        "first_parent_sha": "e448b840dad03ee28accd218c14a27fa8b87c7b4",
        "first_parent_patch_byte_length": 6054,
        "first_parent_patch_sha256": (
            "7c53f6c8b9bd17847cdb4ecc5dfa1c7aa1699105faabc47439a4437709a175b4"
        ),
        "head_sha": "aba6b14c94eca3a9c825b1a303ea67684d5f8daa",
        "head_tree_sha": "e5c6c3d07a918cf43fffed6d4a9f472bc10a674a",
        "merge_sha": "0b28f68b9f4d204ae14814169093723ea84c1364",
        "merge_tree_sha": "79c1c374eed261c42468dc526d837e726e73425a",
        "semantic_delta_paths": [
            "aragora/server/handlers/social/__init__.py",
            "aragora/server/handlers/social/sharing.py",
            "tests/handlers/social/test_sharing.py",
        ],
        "source_sha": subprocess.check_output(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            text=True,
        ).strip(),
    }


def test_historical_receipt_patch_binding_ignores_hostile_git_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    assert ensure_pr_9320_head(_CDG_TEST_ROOT) == PR_9320_FACT["head_sha"]
    global_config = tmp_path / "hostile-gitconfig"
    global_config.write_text(
        "[diff]\n"
        "\tnoprefix = true\n"
        "\talgorithm = histogram\n"
        "\tcontext = 19\n"
        "[core]\n"
        "\tabbrev = 40\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.delenv("GIT_CONFIG_NOSYSTEM", raising=False)
    monkeypatch.setattr(
        ratchet,
        "validate_accepted_authority",
        lambda *args, **kwargs: {
            "active_original_record_ids": [],
            "analyzer_bundle_sha256": "",
            "live_original_record_ids": [],
        },
    )
    result = ratchet.build_accepted_result(
        mode="receipt",
        repo_root=_REPO_ROOT,
        inventory_path=_REPO_ROOT / gen.DEFAULT_INVENTORY,
        source_sha=subprocess.check_output(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            text=True,
        ).strip(),
        historical_base_sha="14d1ef53e23c5466c0491ed93f72752944c78cd4",
        historical_head_sha=cast(str, PR_9320_FACT["head_sha"]),
        historical_merge_sha=cast(str, PR_9320_FACT["merge_sha"]),
        historical_first_parent_sha="e448b840dad03ee28accd218c14a27fa8b87c7b4",
    )
    assert result["status"] == "pass"
    assert result["execution"]["first_parent_patch_byte_length"] == 6054
    assert result["execution"]["first_parent_patch_sha256"] == (
        "7c53f6c8b9bd17847cdb4ecc5dfa1c7aa1699105faabc47439a4437709a175b4"
    )


def test_historical_receipt_mode_fails_closed_on_incomplete_or_mismatched_pair(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        ratchet,
        "validate_accepted_authority",
        lambda *args, **kwargs: {
            "active_original_record_ids": [],
            "analyzer_bundle_sha256": "",
            "live_original_record_ids": [],
        },
    )
    source_sha = subprocess.check_output(
        ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    incomplete = ratchet.build_accepted_result(
        mode="receipt",
        repo_root=_REPO_ROOT,
        inventory_path=_REPO_ROOT / gen.DEFAULT_INVENTORY,
        source_sha=source_sha,
        historical_merge_sha="0b28f68b9f4d204ae14814169093723ea84c1364",
    )
    assert incomplete["error_code"] == "accepted_authority_historical_pair_incomplete"
    assert incomplete["passing"] is False

    mismatched = ratchet.build_accepted_result(
        mode="receipt",
        repo_root=_REPO_ROOT,
        inventory_path=_REPO_ROOT / gen.DEFAULT_INVENTORY,
        source_sha=source_sha,
        historical_base_sha="14d1ef53e23c5466c0491ed93f72752944c78cd4",
        historical_head_sha="aba6b14c94eca3a9c825b1a303ea67684d5f8daa",
        historical_merge_sha="0b28f68b9f4d204ae14814169093723ea84c1364",
        historical_first_parent_sha="14d1ef53e23c5466c0491ed93f72752944c78cd4",
    )
    assert mismatched["error_code"] == "accepted_authority_historical_pair_mismatch"
    assert mismatched["passing"] is False

    wrong_base = ratchet.build_accepted_result(
        mode="receipt",
        repo_root=_REPO_ROOT,
        inventory_path=_REPO_ROOT / gen.DEFAULT_INVENTORY,
        source_sha=source_sha,
        historical_base_sha="e448b840dad03ee28accd218c14a27fa8b87c7b4",
        historical_head_sha="aba6b14c94eca3a9c825b1a303ea67684d5f8daa",
        historical_merge_sha="0b28f68b9f4d204ae14814169093723ea84c1364",
        historical_first_parent_sha="e448b840dad03ee28accd218c14a27fa8b87c7b4",
    )
    assert wrong_base["error_code"] in {
        "accepted_authority_historical_pair_invalid",
        "accepted_authority_historical_pair_mismatch",
    }
    assert wrong_base["passing"] is False


def test_no_reachable_classification_filtered_or_raw_baseline_fallback():
    # Neither analyzer surface carries PR #9346's classification-filtered or
    # raw-baseline fallback identifiers at all.
    for module in (ratchet, gen):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "classification_filtered" not in source
        assert "raw_baseline" not in source
        assert "raw-baseline" not in source
    # With accepted authority present, program mode routes to the accepted
    # authority; without it, the only reachable verdict is the transition
    # failure — never a fallback execution.
    main_source = inspect.getsource(ratchet.main)
    assert "accepted_default" in main_source
    result = ratchet.build_accepted_result(
        mode="program",
        repo_root=_REPO_ROOT,
        inventory_path=_REPO_ROOT / gen.DEFAULT_INVENTORY,
        source_sha=subprocess.check_output(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            text=True,
        ).strip(),
    )
    assert result["authority"]["source"] == "accepted_authority"


def test_post_transition_noop_pr_uses_only_accepted_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # A hermetic no-op at the transition merge passes with
    # base_sha == head_sha == analyzer_sha == MERGE.
    repo, base, _head = _hermetic_repo(tmp_path)
    result, _calls = _recorded_hermetic_pr(repo, base, base, monkeypatch)
    assert result["passing"] is True and result["status"] == "pass"
    assert result["authority"] == {"source": "accepted_authority"}
    assert result["added_original_record_ids"] == []
    assert result["removed_original_record_ids"] == []
    execution = result["execution"]
    assert execution["base_sha"] == execution["head_sha"] == execution["analyzer_sha"] == base
    assert execution["dependencies"] == []
    assert execution["interpreter_flags"] == list(ratchet.ANALYZER_FLAGS)


def _stale_base_squash_repo(tmp_path: Path) -> dict[str, Any]:
    """Disposable repo reproducing the real PR #9696 stale-base squash shape.

    START -> A (a prior squash adding sibling.txt) -> M (squash of the governed
    PR, first parent A). The PR head H forked from START, so H's tree lacks
    sibling.txt while M's tree has it: head tree != merge tree, yet the exact
    first-parent semantic delta A -> M is the single owned path. This is the
    interval geometry the checker must accept under VAL-CDG-018.
    """
    repo = tmp_path / "stale-base-squash"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    start = _commit(repo, "start")
    # PR head H: forked from START, adds only the owned file.
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "pr-head", start], check=True)
    (repo / "owned.txt").write_text("owned\n", encoding="utf-8")
    head = _commit(repo, "pr head")
    head_tree = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{head}^{{tree}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    # Meanwhile a sibling PR merges first on main: A adds sibling.txt.
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-B", "main", start], check=True)
    (repo / "sibling.txt").write_text("sibling\n", encoding="utf-8")
    prior_merge = _commit(repo, "sibling squash")
    # The stale-base squash M: first parent A, content = A + owned.txt only.
    (repo / "owned.txt").write_text("owned\n", encoding="utf-8")
    merge = _commit(repo, "stale-base squash of pr-head")
    merge_tree = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{merge}^{{tree}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head_tree != merge_tree  # the defining B4 geometry
    return {
        "head": head,
        "head_tree": head_tree,
        "merge": merge,
        "merge_tree": merge_tree,
        "prior_merge": prior_merge,
        "repo": repo,
        "start": start,
    }


def _stale_base_receipt_resources(
    shape: dict[str, Any],
    *,
    owned_paths: dict[int, list[str]] | None = None,
    forge_merge_tree: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, list[str]]]:
    """Governed + receipt records for the two-PR stale-base interval."""
    governed = [
        {
            "authenticated_additions": 1,
            "authenticated_deletions": 0,
            "authenticated_pr_delta": 1,
            "base_sha": shape["start"],
            "changed_files_complete": True,
            "head_sha": shape["prior_merge"],
            "head_tree_sha": subprocess.run(
                ["git", "-C", str(shape["repo"]), "rev-parse", f"{shape['prior_merge']}^{{tree}}"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "pr": 9695,
        },
        {
            "authenticated_additions": 1,
            "authenticated_deletions": 0,
            "authenticated_pr_delta": 1,
            "base_sha": shape["prior_merge"],
            "changed_files_complete": True,
            "head_sha": shape["head"],
            "head_tree_sha": shape["head_tree"],
            "pr": 9696,
        },
    ]
    receipts = [
        {
            "base_sha": shape["start"],
            "first_parent_sha": shape["start"],
            "head_sha": shape["prior_merge"],
            "head_tree_sha": governed[0]["head_tree_sha"],
            "merge_sha": shape["prior_merge"],
            "merge_tree_sha": governed[0]["head_tree_sha"],
            "pr": 9695,
        },
        {
            "base_sha": shape["prior_merge"],
            "first_parent_sha": shape["prior_merge"],
            "head_sha": shape["head"],
            "head_tree_sha": shape["head_tree"],
            "merge_sha": shape["merge"],
            "merge_tree_sha": shape["head_tree"] if forge_merge_tree else shape["merge_tree"],
            "pr": 9696,
        },
    ]
    files = owned_paths if owned_paths is not None else {9695: ["sibling.txt"], 9696: ["owned.txt"]}
    return governed, receipts, files


def test_real_shaped_stale_base_squash_passes_via_semantic_delta_witness(tmp_path: Path):
    # The #9696 shape: head tree != merge tree, single owned file, and the
    # recomputed first-parent semantic delta equals the authenticated PR
    # disposition. VAL-CDG-018 requires acceptance via the semantic-delta
    # witness; requiring PR-head tree equality here is forbidden.
    shape = _stale_base_squash_repo(tmp_path)
    governed, receipts, files = _stale_base_receipt_resources(shape)
    operation_log: list[dict[str, Any]] = []
    ratchet._reconcile_prs_and_receipts(
        governed,
        receipts,
        repo_root=shape["repo"],
        start_sha=shape["start"],
        end_sha=shape["merge"],
        authenticated_pr_files=files,
        operation_log=operation_log,
    )
    witnesses = {
        entry["resource"]: entry["identifier"]
        for entry in operation_log
        if entry["kind"] == "squash_binding_witness"
    }
    corroborations = {
        entry["resource"]: entry["response_identity"]["corroborating_witnesses"]
        for entry in operation_log
        if entry["kind"] == "squash_binding_witness"
    }
    # Both squashes bind through exact semantic equality. Tree equality is
    # structured corroboration only, never the binding witness identity.
    assert witnesses["squash-binding:9695"] == "first_parent_semantic_delta"
    assert witnesses["squash-binding:9696"] == "first_parent_semantic_delta"
    assert corroborations == {
        "squash-binding:9695": ["head_tree_equality"],
        "squash-binding:9696": [],
    }


def test_squash_semantic_delta_round_trips_hostile_github_filenames(tmp_path: Path):
    repo = tmp_path / "hostile-semantic-delta"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    base = _commit(repo, "base")
    paths = {
        "hostile/back\\slash.txt",
        'hostile/double"quote.txt',
        "hostile/line\nbreak.txt",
        "hostile/tab\tname.txt",
        "hostile/路径-雪.txt",
    }
    for relative in paths:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    merge = _commit(repo, "hostile paths")
    operation_log: list[dict[str, Any]] = []

    assert (
        ratchet._first_parent_semantic_delta(
            repo,
            first_parent_sha=base,
            merge_sha=merge,
            pr=9707,
            operation_log=operation_log,
        )
        == paths
    )
    semantic_diff = next(
        entry for entry in operation_log if entry["resource"] == "squash-semantic-delta:9707"
    )
    assert "-z" in semantic_diff["identifier"].split()
    merge_tree = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{merge}^{{tree}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert (
        ratchet._require_squash_binding_witness(
            repo_root=repo,
            pr=9707,
            head_tree_sha=merge_tree,
            merge_tree_sha=merge_tree,
            first_parent_sha=base,
            merge_sha=merge,
            owned_paths=sorted(paths),
            operation_log=[],
        )
        == "first_parent_semantic_delta"
    )


@pytest.mark.parametrize(
    ("stdout", "message"),
    (
        (b"unterminated", "unterminated NUL-delimited path output"),
        (b"valid.txt\0\0", "empty path record"),
        (b"\xff\0", "cannot round-trip through a GitHub UTF-8 filename"),
        (b"duplicate.txt\0duplicate.txt\0", "duplicate paths"),
    ),
)
def test_squash_semantic_delta_rejects_malformed_raw_git_paths(
    monkeypatch: pytest.MonkeyPatch,
    stdout: bytes,
    message: str,
):
    monkeypatch.setattr(
        ratchet,
        "_run_read_only",
        lambda argv, **_kwargs: subprocess.CompletedProcess(
            argv,
            0,
            stdout=stdout,
            stderr=b"",
        ),
    )

    with pytest.raises(ValueError, match=message):
        ratchet._first_parent_semantic_delta(
            Path("."),
            first_parent_sha="1" * 40,
            merge_sha="2" * 40,
            pr=9707,
            operation_log=[],
        )


def test_foreign_path_semantic_delta_fails_closed(tmp_path: Path):
    # The recomputed first-parent delta reaches a path outside the
    # authenticated PR disposition: fail closed on both shapes (stale-base
    # and equality-present).
    shape = _stale_base_squash_repo(tmp_path)
    governed, receipts, _files = _stale_base_receipt_resources(shape)
    with pytest.raises(ValueError, match="outside the authenticated disposition"):
        ratchet._reconcile_prs_and_receipts(
            governed,
            receipts,
            repo_root=shape["repo"],
            start_sha=shape["start"],
            end_sha=shape["merge"],
            authenticated_pr_files={9695: ["sibling.txt"], 9696: ["something-else.txt"]},
            operation_log=[],
        )


def test_head_tree_equality_rejects_strict_subset_of_owned_paths(tmp_path: Path):
    # Tree equality is corroboration only: an authenticated disposition with
    # an extra owned path must fail even when the PR-head and squash trees are
    # identical and every actual delta path is owned.
    shape = _stale_base_squash_repo(tmp_path)
    clean_tree = subprocess.run(
        ["git", "-C", str(shape["repo"]), "rev-parse", f"{shape['prior_merge']}^{{tree}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    with pytest.raises(ValueError, match="authenticated paths missing from semantic delta"):
        ratchet._require_squash_binding_witness(
            repo_root=shape["repo"],
            pr=9695,
            head_tree_sha=clean_tree,
            merge_tree_sha=clean_tree,
            first_parent_sha=shape["start"],
            merge_sha=shape["prior_merge"],
            owned_paths=["declared-but-missing.txt", "sibling.txt"],
            operation_log=[],
        )


def test_head_tree_equality_with_disposition_mismatch_fails_closed(tmp_path: Path):
    # Equality present but disposition mismatched: a squash merge whose tree
    # literally equals the PR head tree still fails when its recomputed
    # first-parent semantic delta touches paths outside the authenticated
    # disposition (equality is one witness, never an override).
    shape = _stale_base_squash_repo(tmp_path)
    # Craft M2 on top of prior_merge whose tree IS the PR head tree: the
    # first-parent delta then both adds owned.txt and REMOVES sibling.txt —
    # the removal is outside the single-file disposition.
    merge2 = subprocess.run(
        [
            "git",
            "-C",
            str(shape["repo"]),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit-tree",
            shape["head_tree"],
            "-p",
            shape["prior_merge"],
            "-m",
            "equality-shaped squash that reverts the sibling",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    governed, receipts, files = _stale_base_receipt_resources(shape)
    receipts[1]["merge_sha"] = merge2
    receipts[1]["merge_tree_sha"] = shape["head_tree"]
    with pytest.raises(ValueError, match="outside the authenticated disposition"):
        ratchet._reconcile_prs_and_receipts(
            governed,
            receipts,
            repo_root=shape["repo"],
            start_sha=shape["start"],
            end_sha=merge2,
            authenticated_pr_files=files,
            operation_log=[],
        )


def test_forged_receipt_squash_tree_claim_fails_against_local_git(tmp_path: Path):
    # A receipt forging merge_tree_sha == head_tree_sha cannot evade the
    # local-git recompute: the checker derives the squash tree from the
    # immutable merge commit, not from the claimed record value.
    shape = _stale_base_squash_repo(tmp_path)
    governed, receipts, files = _stale_base_receipt_resources(shape, forge_merge_tree=True)
    with pytest.raises(ValueError, match="misstates the squash merge tree"):
        ratchet._reconcile_prs_and_receipts(
            governed,
            receipts,
            repo_root=shape["repo"],
            start_sha=shape["start"],
            end_sha=shape["merge"],
            authenticated_pr_files=files,
            operation_log=[],
        )


def test_squash_binding_requires_a_witness_and_pins_rename_policy(tmp_path: Path):
    # Neither witness available: head tree != merge tree and no authenticated
    # disposition file set for the PR — fail closed, never default open.
    shape = _stale_base_squash_repo(tmp_path)
    governed, receipts, _files = _stale_base_receipt_resources(shape)
    with pytest.raises(ValueError, match="lacks a squash binding witness"):
        ratchet._reconcile_prs_and_receipts(
            governed,
            receipts,
            repo_root=shape["repo"],
            start_sha=shape["start"],
            end_sha=shape["merge"],
            authenticated_pr_files={9695: ["sibling.txt"]},
            operation_log=[],
        )
    # Pinned rename policy: the semantic-delta recompute never follows
    # renames — a rename surfaces as removal@old + addition@new and both
    # paths must be inside the authenticated disposition.
    source = Path(ratchet.__file__).read_text(encoding="utf-8")
    assert "--no-renames" in source
    assert "--follow" not in source
    assert "-M100" not in source
    repo = shape["repo"]
    subprocess.run(
        ["git", "-C", str(repo), "mv", "owned.txt", "renamed.txt"],
        check=True,
    )
    renamed_merge = _commit(repo, "rename squash")
    governed_r, receipts_r, _unused = _stale_base_receipt_resources(shape)
    governed_r[1]["head_sha"] = renamed_merge
    governed_r[1]["head_tree_sha"] = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{renamed_merge}^{{tree}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    receipts_r[1].update(
        {
            "base_sha": shape["merge"],
            "first_parent_sha": shape["merge"],
            "head_sha": renamed_merge,
            "head_tree_sha": governed_r[1]["head_tree_sha"],
            "merge_sha": renamed_merge,
            "merge_tree_sha": governed_r[1]["head_tree_sha"],
        }
    )
    governed_r[1]["base_sha"] = shape["merge"]
    three_governed = [
        governed_r[0],
        {
            "authenticated_additions": 1,
            "authenticated_deletions": 0,
            "authenticated_pr_delta": 1,
            "base_sha": shape["prior_merge"],
            "changed_files_complete": True,
            "head_sha": shape["head"],
            "head_tree_sha": shape["head_tree"],
            "pr": 9696,
        },
        dict(governed_r[1], pr=9697),
    ]
    three_receipts = [
        receipts_r[0],
        {
            "base_sha": shape["prior_merge"],
            "first_parent_sha": shape["prior_merge"],
            "head_sha": shape["head"],
            "head_tree_sha": shape["head_tree"],
            "merge_sha": shape["merge"],
            "merge_tree_sha": shape["merge_tree"],
            "pr": 9696,
        },
        dict(receipts_r[1], pr=9697),
    ]
    # Rename covered only when BOTH old and new paths are in the disposition.
    ratchet._reconcile_prs_and_receipts(
        three_governed,
        three_receipts,
        repo_root=repo,
        start_sha=shape["start"],
        end_sha=renamed_merge,
        authenticated_pr_files={
            9695: ["sibling.txt"],
            9696: ["owned.txt"],
            9697: ["owned.txt", "renamed.txt"],
        },
        operation_log=[],
    )
    with pytest.raises(ValueError, match="outside the authenticated disposition"):
        ratchet._reconcile_prs_and_receipts(
            three_governed,
            three_receipts,
            repo_root=repo,
            start_sha=shape["start"],
            end_sha=renamed_merge,
            authenticated_pr_files={
                9695: ["sibling.txt"],
                9696: ["owned.txt"],
                9697: ["renamed.txt"],
            },
            operation_log=[],
        )


def test_live_evidence_plane_accepts_stale_base_squash_and_rejects_foreign_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # Plane 1 (_collect_live_evidence) applies the same VAL-CDG-018 witness
    # rule to the authenticated API trees: the probe's clean-squash fixture
    # passes via tree equality, and a mismatched governed/receipt tree claim
    # still fails the binding check.
    context, _requested = _live_pr_files_probe(tmp_path, monkeypatch, files_count=1)
    assert context["authenticated_pr_files"] == {9999: ["fixture.txt"]}

    def wrong_receipt_tree(resources: dict[str, Any]) -> None:
        resources["first_parent_receipts"]["records"][0]["merge_tree_sha"] = "b" * 40

    with pytest.raises(ValueError, match="lacks first-parent or tree equality"):
        _live_pr_files_probe(tmp_path / "claim", monkeypatch, mutate=wrong_receipt_tree)


def _github_json_transport(bodies: dict[str, Any]) -> Any:
    # GitHub's weak entity tags are derived from the exact response body, so
    # any byte change to the body also changes the ETag header.
    def run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        body = ratchet._canonical_json_bytes(bodies[argv[-1]])
        etag = hashlib.sha256(body).hexdigest()[:32].encode()
        stdout = b'HTTP/2 200 OK\r\nETag: W/"' + etag + b'"\r\n\r\n' + body
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")

    return run


def _github_identity(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    body: Any,
) -> dict[str, Any]:
    monkeypatch.setattr(ratchet, "_run_read_only", _github_json_transport({endpoint: body}))
    _payload, identity = ratchet._gh_api_get(endpoint, operation_log=[])
    return identity


def _tick(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    return f"{value}-ticked"


def _volatile_fixture_repository() -> dict[str, Any]:
    return {
        "default_branch": "main",
        "description": "fixture",
        "forks": 3,
        "forks_count": 3,
        "full_name": "synaptent/aragora",
        "id": 1126097105,
        "name": "aragora",
        "network_count": 3,
        "open_issues": 1019,
        "open_issues_count": 1019,
        "pushed_at": "2026-09-02T03:27:50Z",
        "size": 4096,
        "stargazers_count": 7,
        "subscribers_count": 2,
        "updated_at": "2026-09-01T00:00:00Z",
        "watchers": 7,
        "watchers_count": 7,
    }


def _volatile_fixture_pull_request(end_sha: str) -> dict[str, Any]:
    return {
        "additions": 400,
        "base": {"ref": "main", "repo": _volatile_fixture_repository(), "sha": "f" * 40},
        "changed_files": 1,
        "deletions": 400,
        "head": {"ref": "structex/fixture", "repo": _volatile_fixture_repository(), "sha": end_sha},
        "merge_commit_sha": "e" * 40,
        "mergeable": None,
        "mergeable_state": "unknown",
        "merged_at": "2026-08-31T00:00:00Z",
        "number": 8766,
        "title": "fixture",
        "updated_at": "2026-08-31T00:00:00Z",
    }


def _volatile_fixture_release(end_sha: str) -> dict[str, Any]:
    tag = f"cdg-route_truth-{end_sha}"
    return {
        "assets": [
            {
                "digest": "sha256:" + "1" * 64,
                "download_count": 12,
                "id": 538132370,
                "name": "checksums.txt",
                "size": 159,
                "updated_at": "2026-08-31T14:55:16Z",
            },
            {
                "digest": "sha256:" + "2" * 64,
                "download_count": 12,
                "id": 538132327,
                "name": "manifest.json",
                "size": 302,
                "updated_at": "2026-08-31T14:55:14Z",
            },
            {
                "digest": "sha256:" + "3" * 64,
                "download_count": 12,
                "id": 538132338,
                "name": "payload.json",
                "size": 90447,
                "updated_at": "2026-08-31T14:55:15Z",
            },
        ],
        "draft": False,
        "id": 379772162,
        "immutable": True,
        "prerelease": False,
        "tag_name": tag,
        "target_commitish": end_sha,
        "updated_at": "2026-08-31T14:56:04Z",
    }


def _bump_download_counts(release: dict[str, Any], by: int = 6) -> dict[str, Any]:
    ticked = copy.deepcopy(release)
    for asset in ticked["assets"]:
        asset["download_count"] += by
    return ticked


def _tick_repository_counters(repository: dict[str, Any]) -> dict[str, Any]:
    ticked = dict(repository)
    for field in ratchet._VOLATILE_REPOSITORY_FIELDS:
        ticked[field] = _tick(repository[field])
    return ticked


def test_release_identity_excludes_only_asset_download_counts(monkeypatch: pytest.MonkeyPatch):
    # The verifier's own paired octet-stream asset downloads bump every
    # assets[].download_count inside the release body it captured before the
    # downloads, so that counter alone must not read as concurrent movement.
    end_sha = "2b94459bc0e316c3c0c1eb285695bf2a0c73c647"
    endpoint = f"repos/synaptent/aragora/releases/{379772162}"
    release = _volatile_fixture_release(end_sha)
    before = _github_identity(monkeypatch, endpoint, release)
    ticked = _github_identity(monkeypatch, endpoint, _bump_download_counts(release))
    assert ratchet._remote_identity_moved(before, ticked) is False
    assert before["excluded_volatile_fields"] == ["assets[].download_count"]
    assert before["etag"] is None
    assert before["updated_at"] == release["updated_at"]
    assert before["sha256"] == ticked["sha256"]

    def mutate_asset(index: int, field: str) -> Any:
        def apply(body: dict[str, Any]) -> None:
            body["assets"][index][field] = _tick(body["assets"][index][field])

        return apply

    def mutate_field(field: str) -> Any:
        def apply(body: dict[str, Any]) -> None:
            body[field] = _tick(body[field])

        return apply

    semantic = {
        "asset size": mutate_asset(0, "size"),
        "asset digest": mutate_asset(1, "digest"),
        "asset id": mutate_asset(2, "id"),
        "asset name": mutate_asset(0, "name"),
        "tag_name": mutate_field("tag_name"),
        "target_commitish": mutate_field("target_commitish"),
        "draft": mutate_field("draft"),
        "immutable": mutate_field("immutable"),
        "prerelease": mutate_field("prerelease"),
        "updated_at": mutate_field("updated_at"),
    }
    for label, apply in semantic.items():
        moved_body = _bump_download_counts(release)
        apply(moved_body)
        moved = _github_identity(monkeypatch, endpoint, moved_body)
        assert ratchet._remote_identity_moved(before, moved) is True, label

    # The paginated release listing embeds the same per-asset counters and is
    # reauthenticated too; a newly published release still moves it.
    listing = "repos/synaptent/aragora/releases?per_page=100&page=1"
    listing_before = _github_identity(monkeypatch, listing, [release])
    listing_ticked = _github_identity(monkeypatch, listing, [_bump_download_counts(release)])
    assert ratchet._remote_identity_moved(listing_before, listing_ticked) is False
    assert listing_before["excluded_volatile_fields"] == ["[].assets[].download_count"]
    extra = copy.deepcopy(release)
    extra["id"] = 379772163
    extra["tag_name"] = "v-other"
    listing_grown = _github_identity(monkeypatch, listing, [release, extra])
    assert ratchet._remote_identity_moved(listing_before, listing_grown) is True


def test_repository_and_pull_request_identity_exclude_only_embedded_activity_counters(
    monkeypatch: pytest.MonkeyPatch,
):
    # Issue open/close, pushes to any branch, and stars tick counters inside
    # the repository object (also nested as base.repo/head.repo in governed
    # PR bodies) during a multi-minute run; only those counters are excluded.
    end_sha = "2b94459bc0e316c3c0c1eb285695bf2a0c73c647"
    repo_endpoint = "repos/synaptent/aragora"
    repository = _volatile_fixture_repository()
    before = _github_identity(monkeypatch, repo_endpoint, repository)
    assert before["etag"] is None
    assert before["updated_at"] is None
    assert before["excluded_volatile_fields"] == list(ratchet._VOLATILE_REPOSITORY_FIELDS)
    assert set(ratchet._VOLATILE_REPOSITORY_FIELDS) == {
        "forks",
        "forks_count",
        "network_count",
        "open_issues",
        "open_issues_count",
        "pushed_at",
        "size",
        "stargazers_count",
        "subscribers_count",
        "updated_at",
        "watchers",
        "watchers_count",
    }
    for field in ratchet._VOLATILE_REPOSITORY_FIELDS:
        ticked = dict(repository)
        ticked[field] = _tick(repository[field])
        moved = ratchet._remote_identity_moved(
            before, _github_identity(monkeypatch, repo_endpoint, ticked)
        )
        assert moved is False, field
    all_ticked = _github_identity(monkeypatch, repo_endpoint, _tick_repository_counters(repository))
    assert ratchet._remote_identity_moved(before, all_ticked) is False
    for field in ("default_branch", "description", "full_name", "id", "name"):
        changed = _tick_repository_counters(repository)
        changed[field] = _tick(repository[field])
        moved = ratchet._remote_identity_moved(
            before, _github_identity(monkeypatch, repo_endpoint, changed)
        )
        assert moved is True, field

    pr_endpoint = "repos/synaptent/aragora/pulls/8766"
    pull_request = _volatile_fixture_pull_request(end_sha)
    pr_before = _github_identity(monkeypatch, pr_endpoint, pull_request)
    assert pr_before["etag"] is None
    assert pr_before["updated_at"] == pull_request["updated_at"]
    assert pr_before["excluded_volatile_fields"] == [
        f"{side}.repo.{field}"
        for side in ("base", "head")
        for field in ratchet._VOLATILE_REPOSITORY_FIELDS
    ]
    ticked_pr = copy.deepcopy(pull_request)
    for side in ("base", "head"):
        ticked_pr[side]["repo"] = _tick_repository_counters(pull_request[side]["repo"])
    assert (
        ratchet._remote_identity_moved(
            pr_before, _github_identity(monkeypatch, pr_endpoint, ticked_pr)
        )
        is False
    )

    def nested(path: tuple[str, ...]) -> Any:
        def apply(body: dict[str, Any]) -> None:
            target = body
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = _tick(target[path[-1]])

        return apply

    semantic = {
        "head sha": nested(("head", "sha")),
        "base sha": nested(("base", "sha")),
        "head ref": nested(("head", "ref")),
        "head repo full_name": nested(("head", "repo", "full_name")),
        "merge_commit_sha": nested(("merge_commit_sha",)),
        "mergeable_state": nested(("mergeable_state",)),
        "merged_at": nested(("merged_at",)),
        "changed_files": nested(("changed_files",)),
        "title": nested(("title",)),
        "updated_at": nested(("updated_at",)),
    }
    for label, apply in semantic.items():
        moved_body = copy.deepcopy(ticked_pr)
        apply(moved_body)
        moved = ratchet._remote_identity_moved(
            pr_before, _github_identity(monkeypatch, pr_endpoint, moved_body)
        )
        assert moved is True, label

    # Endpoints outside the three normalized classes keep the raw-body plane.
    branch = "repos/synaptent/aragora/branches/main"
    raw = _github_identity(monkeypatch, branch, {"commit": {"sha": end_sha}, "name": "main"})
    assert raw["etag"] is not None
    assert "excluded_volatile_fields" not in raw


def test_stable_get_tolerates_counter_ticks_between_paired_fetches_and_blocks_on_content(
    monkeypatch: pytest.MonkeyPatch,
):
    endpoint = "repos/synaptent/aragora"
    repository = _volatile_fixture_repository()
    served = iter([repository, _tick_repository_counters(repository)])

    def ticking(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return _github_json_transport({endpoint: next(served)})(argv)

    monkeypatch.setattr(ratchet, "_run_read_only", ticking)
    operation_log: list[dict[str, Any]] = []
    payload, identity = ratchet._gh_api_get_stable(endpoint, operation_log=operation_log)
    assert payload["open_issues_count"] == repository["open_issues_count"] + 1
    assert payload["full_name"] == "synaptent/aragora"
    assert identity["etag"] is None
    assert [entry["movement_observed"] for entry in operation_log] == [False, False]
    assert all(entry["raw_etag"] for entry in operation_log)
    assert operation_log[0]["sha256"] != operation_log[1]["sha256"]
    assert operation_log[0]["response_identity"] == operation_log[1]["response_identity"]

    flipping = iter([repository, {**repository, "default_branch": "develop"}] * 3)

    def content_moves(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return _github_json_transport({endpoint: next(flipping)})(argv)

    monkeypatch.setattr(ratchet, "_run_read_only", content_moves)
    blocked_log: list[dict[str, Any]] = []
    with pytest.raises(ratchet.BoundaryBlocked, match="moved concurrently"):
        ratchet._gh_api_get_stable(endpoint, operation_log=blocked_log)
    assert [entry["movement_observed"] for entry in blocked_log] == [True] * 6


def test_reauthentication_tolerates_volatile_counter_ticks_and_blocks_on_content_movement(
    monkeypatch: pytest.MonkeyPatch,
):
    end_sha = "2b94459bc0e316c3c0c1eb285695bf2a0c73c647"
    repo_endpoint = "repos/synaptent/aragora"
    pr_endpoint = "repos/synaptent/aragora/pulls/8766"
    release_endpoint = "repos/synaptent/aragora/releases/379772162"
    listing_endpoint = "repos/synaptent/aragora/releases?per_page=100&page=1"
    release = _volatile_fixture_release(end_sha)
    before_bodies: dict[str, Any] = {
        repo_endpoint: _volatile_fixture_repository(),
        pr_endpoint: _volatile_fixture_pull_request(end_sha),
        release_endpoint: release,
        listing_endpoint: [release],
    }
    monkeypatch.setattr(ratchet, "_run_read_only", _github_json_transport(before_bodies))
    operation_log: list[dict[str, Any]] = []
    endpoint_identities: dict[str, dict[str, Any]] = {}
    for endpoint in sorted(before_bodies):
        _payload, identity = ratchet._gh_api_get_stable(endpoint, operation_log=operation_log)
        endpoint_identities[endpoint] = identity
    context = {
        "asset_identities": {},
        "endpoint_identities": endpoint_identities,
        "github_repository": "synaptent/aragora",
        "local_asset_identities": {},
        "verification_commands": [],
    }
    before_snapshot = {
        "assets": {},
        "endpoints": endpoint_identities,
        "local_assets": {},
        "repository": "synaptent/aragora",
        "verifications": [],
    }
    # End of run: the janitor ticked the repository counters and the
    # verifier's own asset downloads bumped every download_count.
    ticked_pr = copy.deepcopy(before_bodies[pr_endpoint])
    for side in ("base", "head"):
        ticked_pr[side]["repo"] = _tick_repository_counters(ticked_pr[side]["repo"])
    ticked_bodies: dict[str, Any] = {
        repo_endpoint: _tick_repository_counters(before_bodies[repo_endpoint]),
        pr_endpoint: ticked_pr,
        release_endpoint: _bump_download_counts(release),
        listing_endpoint: [_bump_download_counts(release)],
    }
    monkeypatch.setattr(ratchet, "_run_read_only", _github_json_transport(ticked_bodies))
    after_snapshot = ratchet._reauthenticate_live_context(
        context,
        operation_log=operation_log,
        end_sha=end_sha,
    )
    assert ratchet._canonical_json_bytes(after_snapshot) == ratchet._canonical_json_bytes(
        before_snapshot
    )

    def move_head_sha(body: dict[str, Any]) -> None:
        body["head"]["sha"] = "d" * 40

    def move_asset_digest(body: dict[str, Any]) -> None:
        body["assets"][2]["digest"] = "sha256:" + "f" * 64

    def move_repository_name(body: dict[str, Any]) -> None:
        body["full_name"] = "synaptent/renamed"

    def publish_extra_release(body: list[dict[str, Any]]) -> None:
        body.append({**copy.deepcopy(release), "id": 379772163, "tag_name": "v-other"})

    for endpoint, apply in (
        (pr_endpoint, move_head_sha),
        (release_endpoint, move_asset_digest),
        (repo_endpoint, move_repository_name),
        (listing_endpoint, publish_extra_release),
    ):
        moved_bodies = copy.deepcopy(ticked_bodies)
        apply(moved_bodies[endpoint])
        monkeypatch.setattr(ratchet, "_run_read_only", _github_json_transport(moved_bodies))
        with pytest.raises(ratchet.BoundaryBlocked, match="moved concurrently") as excinfo:
            ratchet._reauthenticate_live_context(context, operation_log=[], end_sha=end_sha)
        assert str(excinfo.value).endswith(endpoint)
