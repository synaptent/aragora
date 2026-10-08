"""Characterization corpus for the review_queue module split (C-1 to C-4).

Step 1 of ``docs/architecture/P5_REVIEW_QUEUE_SPLIT_DESIGN.md``: the public surface, gate
outputs and CLI help recorded under ``review_queue_characterization/`` must stay byte-equal
while code moves out of ``aragora/cli/commands/review_queue.py``. Every input is a mocked
GitHub payload. Rewriting a golden file is a behavior change that needs its own reviewed PR;
``REVIEW_QUEUE_CHARACTERIZATION_REGEN=1`` only produces that diff.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from aragora.cli.commands import review_queue as rq
from aragora.cli.commands import review_queue_transport as transport

GOLDEN_DIR = Path(__file__).parent / "review_queue_characterization"
REPO_ROOT = Path(__file__).resolve().parents[3]
REGEN = os.environ.get("REVIEW_QUEUE_CHARACTERIZATION_REGEN") == "1"
HEAD = "a" * 40
REPO = "synaptent/aragora"
HELP_PYTHON = (3, 11)
# Unit modules named by the design's target table (section 4).
UNIT_MODULES = "models render parsers checks settlement evidence packet quorum".split()
DESIGN_SEAMS = set(
    """_gh_json _fetch_required_pr_check_surface _build_packet _build_queue
    _explicit_merged_pr_merge_packet_entry _build_merge_authorization_packet
    _trusted_settlement_creator _human_settlement_status_creator_verified
    _record_external_settlement _require_clean_worktree _has_successful_status_context""".split()
)
REPORTING_CASES = tuple(
    """green low_risk unavailable quorum_fail quorum_pending
    required_fail required_pending optional_fail optional_pending""".split()
)
REQUIRED = ("lint", "typecheck", "sdk-parity", "Generate & Validate", "TypeScript SDK Type Check")
VOLATILE_KEYS = {"generated_at", "packet_sha"}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _write_golden(name: str, entries: dict[str, Any]) -> None:
    rows = [f"{json.dumps(key)}: {_canonical(value)}" for key, value in sorted(entries.items())]
    (GOLDEN_DIR / name).write_text("{\n" + ",\n".join(rows) + "\n}\n", encoding="utf-8")


def _read_golden(name: str) -> dict[str, Any]:
    path = GOLDEN_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _assert_matches_golden(name: str, key: str, actual: Any) -> None:
    if REGEN:
        entries = _read_golden(name)
        entries[key] = json.loads(_canonical(actual))
        _write_golden(name, entries)
    expected = _read_golden(name).get(key)
    if _canonical(expected) != _canonical(actual):
        old, new = (json.dumps(v, indent=1, sort_keys=True).split("\n") for v in (expected, actual))
        diff = difflib.unified_diff(old, new, "golden", "actual", lineterm="")
        pytest.fail(f"{name}[{key}] drifted:\n" + "\n".join(list(diff)[:120]))


def _normalize(value: Any, tmp_path: Path) -> Any:
    if isinstance(value, dict):
        return {
            key: "<volatile>" if key in VOLATILE_KEYS else _normalize(item, tmp_path)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(item, tmp_path) for item in value]
    if isinstance(value, str):
        for prefix in (str(tmp_path), tmp_path.as_posix()):
            if prefix in value:
                value = value.replace(prefix, "<tmp>").replace("\\", "/")
        return value
    return value


@pytest.fixture
def hermetic(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[list[str]]]:
    """Drop ambient CI and gate flags; fail closed on any live ``gh`` call."""
    for key in list(os.environ):
        if key.startswith(("GITHUB_", "ARAGORA_ENABLE_", "ARAGORA_REVIEW_QUEUE_ROOT")) or key in {
            "ARAGORA_SETTLEMENT_CREATOR",
            "ARAGORA_TRUSTED_EVIDENCE_POSTERS",
            "ARAGORA_AUTOMATION_STATE_ROOT",
        }:
            monkeypatch.delenv(key)
    live: list[list[str]] = []

    def no_live_gh(args: list[str]) -> Any:
        live.append(list(args))
        raise AssertionError(f"live gh call: {args}")

    for module in (rq, transport):
        monkeypatch.setattr(module, "_gh_json", no_live_gh)
        monkeypatch.setattr(module, "_gh_text", no_live_gh)
    yield live
    assert live == []


def _pr(**overrides: Any) -> dict[str, Any]:
    pr: dict[str, Any] = {
        "number": 6283,
        "title": "test PR",
        "url": "https://github.com/synaptent/aragora/pull/6283",
        "state": "OPEN",
        "mergedAt": "",
        "headRefName": "branch-6283",
        "headRefOid": HEAD,
        "baseRefName": "main",
        "baseRefOid": "basesha0001",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "reviewDecision": "",
        "labels": [],
        "author": {"login": "an0mium"},
        "additions": 10,
        "deletions": 5,
        "changedFiles": 2,
        "files": [{"path": "aragora/server/handlers/x.py"}],
        "body": "",
    }
    pr.update(overrides)
    return pr


def _in_job(
    mp: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[list[str]]]:
    """Same inputs as ``in_job_advisory_inputs`` in test_review_queue.py, plus a call log."""
    for flag in """TIERED_MERGE_GATE SEVERITY_GATED_DISSENT ADVISORY_DISSENT_SETTLE
    OPERATOR_ADVISORY_SETTLEMENT""".split():
        mp.setenv(f"ARAGORA_ENABLE_{flag}", "1")
    for key, value in {
        "ARAGORA_SETTLEMENT_CREATOR": "scarmani",
        "ARAGORA_TRUSTED_EVIDENCE_POSTERS": "scarmani",
        "GITHUB_WORKFLOW": "Aragora Merge Quorum",
        "GITHUB_JOB": "merge-quorum",
        "GITHUB_RUN_ID": "26288586838",
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_SERVER_URL": "https://github.com",
    }.items():
        mp.setenv(key, value)
    quorum_row = {
        "name": "aragora-merge-quorum",
        "workflowName": "Aragora Merge Quorum",
        "status": "IN_PROGRESS",
        "conclusion": "",
        "detailsUrl": "https://github.com/synaptent/aragora/actions/runs/26288586838/job/1",
    }
    green = [{"name": n, "status": "COMPLETED", "conclusion": "SUCCESS"} for n in REQUIRED]
    pr = _pr(
        statusCheckRollup=[
            quorum_row,
            *green,
            {"context": "aragora/human-settlement", "state": "SUCCESS"},
        ],
        commits=[{"commit": {"committedDate": "2026-07-10T23:00:00Z"}}],
    )
    pr["comments"] = [
        {
            "author": {"login": "scarmani"},
            "createdAt": "2026-07-11T00:00:00Z",
            "body": (
                f"## {family} independent model review\n**Model family:** {family}\n"
                f"Current head: {HEAD}\nVerdict: CHANGES-REQUESTED\n"
                "- [P2] A non-blocking advisory."
            ),
        }
        for family in ("claude", "openai")
    ] + [
        {
            "author": {"login": "scarmani"},
            "body": f"Tier-4 Human Settlement Authorization\n{HEAD}\n"
            "admin_squash_merge\nhuman-risk settlement",
        }
    ]
    required = [
        {**row, "bucket": "pending" if row is quorum_row else "pass"}
        for row in [quorum_row, *green]
    ]
    calls: list[list[str]] = []

    def fake_gh_json(args: list[str]) -> Any:
        calls.append(list(args))
        return pr

    mp.setattr(rq, "_gh_json", fake_gh_json)
    mp.setattr(
        rq,
        "_fetch_required_pr_check_surface",
        lambda *_args: {"available": True, "checks": required},
    )
    mp.setattr(rq, "_human_settlement_status_creator_verified", lambda **_kw: (True, "ok"))
    mp.setattr(rq, "_has_successful_status_context", lambda *_args, **_kw: True)
    return pr, required, calls


def _apply_reporting_case(
    case: str, mp: pytest.MonkeyPatch, pr: dict[str, Any], required: list[dict[str, Any]]
) -> None:
    """Mirror of the ``reporting_case`` fixture in test_review_queue.py."""
    if case == "low_risk":
        pr["files"] = [{"path": "docs/example.md"}]
    if case == "unavailable":
        mp.setattr(
            rq,
            "_fetch_required_pr_check_surface",
            lambda *_args: {
                "available": False,
                "checks": [],
                "error": "required surface transport unavailable",
            },
        )
    row: dict[str, Any] = {}
    required_row: dict[str, Any] = {}
    if case.startswith("quorum_"):
        mp.delenv("GITHUB_JOB")
        row, required_row = pr["statusCheckRollup"][0], required[0]
    elif case.startswith("required_"):
        row, required_row = pr["statusCheckRollup"][1], required[1]
    elif case.startswith("optional_"):
        row = {"name": "optional-audit"}
        pr["statusCheckRollup"].append(row)
    if case.endswith(("_fail", "_pending")):
        pending = case.endswith("_pending")
        row.update(
            status="IN_PROGRESS" if pending else "COMPLETED",
            conclusion="" if pending else "FAILURE",
        )
        required_row.update(row, bucket="pending" if pending else "fail")


def _write_receipt(tmp_path: Path, action: str, event: str) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    payload = {"pr_number": 6283, "head_sha": HEAD, "action": action, "github_event": event}
    (receipts / "pr-6283-characterization.json").write_text(json.dumps(payload), encoding="utf-8")


def _state_variant(case: str, mp: pytest.MonkeyPatch, tmp_path: Path, pr: dict[str, Any]) -> None:
    if case.startswith("merged"):
        pr.update(state="MERGED", mergedAt="2026-07-11T01:00:00Z")
    if case == "merged_settled":
        _write_receipt(tmp_path, "admin_squash_merge", "ADMIN_SQUASH_MERGE")
    if case == "open_settled":
        _write_receipt(tmp_path, "approve", "RECORDED_EXTERNAL_APPROVE")
    if case == "draft":
        pr["isDraft"] = True
    if case == "parked_label":
        pr["labels"] = [{"name": "do-not-merge"}]
    if case == "operator_review_label":
        pr["labels"] = [{"name": rq.OPERATOR_REVIEW_REQUIRED_LABEL}]
    if case == "conflicting":
        pr.update(mergeable="CONFLICTING", mergeStateStatus="DIRTY")


def _boundary_variant(case: str, pr: dict[str, Any], required: list[dict[str, Any]]) -> None:
    """Design section 8 inputs: P3-2 name collision and P3-3 surface skew."""
    if case.startswith("p3_2_"):
        name = "lint" if case == "p3_2_collision" else "shadow-lint"
        pr["statusCheckRollup"].append(
            {
                "name": name,
                "workflowName": "Optional Shadow Lint",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
            }
        )
    if case.startswith("p3_3_"):
        lint = pr["statusCheckRollup"][1]
        if case == "p3_3_skew":
            lint.update(status="IN_PROGRESS", conclusion="")
        else:
            lint.update(status="COMPLETED", conclusion="FAILURE")
        required[1].update(status="COMPLETED", conclusion="FAILURE", bucket="fail")


def _routed_gh(routes: dict[str, Any], calls: list[list[str]]) -> Callable[[list[str]], Any]:
    def fake_gh_json(args: list[str]) -> Any:
        calls.append(list(args))
        key = "pr view" if args[:2] == ["pr", "view"] else args[1] if args[:1] == ["api"] else ""
        for pattern, result in routes.items():
            if pattern == key or (pattern.startswith("~") and pattern[1:] in key):
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"unexpected gh call: {args}")

    return fake_gh_json


def _direct_check_run_routes() -> dict[str, Any]:
    pr = _pr(number=7465, files=[{"path": "docs/status/open.md"}], statusCheckRollup=[])
    grok = "## Grok independent model review\nVerdict: approve."
    pr["comments"] = [
        {"author": {"login": "an0mium"}, "body": "## Claude focused dogfood\npass"},
        {"author": {"login": "an0mium"}, "body": grok},
    ]
    runs = [
        {"name": "lint", "status": "completed", "conclusion": "success"},
        {"name": "typecheck", "status": "completed", "conclusion": "success"},
        {"name": "Python SDK Tests (3.11)", "status": "completed", "conclusion": "failure"},
    ]
    return {
        "pr view": pr,
        "~required_status_checks": {"contexts": ["lint", "typecheck"]},
        "~check-runs": {"check_runs": runs},
    }


def _rest_fallback_routes() -> dict[str, Any]:
    head = "abc1234567890abcdef"
    base = "repos/synaptent/aragora"
    rest_pr = {
        "number": 7466,
        "title": "docs status fallback",
        "html_url": "https://github.com/synaptent/aragora/pull/7466",
        "state": "open",
        "merged_at": None,
        "merge_commit_sha": "",
        "draft": False,
        "mergeable": True,
        "mergeable_state": "clean",
        "user": {"login": "an0mium"},
        "head": {"ref": "codex/rest-fallback-test", "sha": head},
        "base": {"ref": "main", "sha": "basesha0001"},
        "labels": [],
        "additions": 1,
        "deletions": 0,
        "changed_files": 1,
        "body": "",
    }
    comment = (
        f"## Grok independent model review\n\nHead: abc1234 ({head}).\nPR: #7466.\n"
        "Model family: grok\n\nVerdict: PASS\n- adversarial dogfood recheck found no blocker.\n"
        "dogfood: yes\n"
    )
    status = {"context": "legacy/status", "state": "success", "created_at": "2026-06-12T00:02:00Z"}
    return {
        "pr view": transport._GhError("GraphQL: API rate limit already exceeded"),
        f"{base}/pulls/7466": rest_pr,
        f"{base}/pulls/7466/files?per_page=100": [{"filename": "docs/status/fallback.md"}],
        f"{base}/issues/7466/comments?per_page=100": [
            {"user": {"login": "an0mium"}, "body": comment, "created_at": "2026-06-12T00:01:00Z"}
        ],
        f"{base}/pulls/7466/reviews?per_page=100": [],
        f"{base}/pulls/7466/commits?per_page=100": [
            {"sha": head, "commit": {"author": {"date": "2026-06-12T00:00:00Z"}}}
        ],
        f"{base}/commits/{head}/statuses?per_page=100": [],
        f"{base}/commits/{head}/status": {
            "statuses": [{**status, "updated_at": status["created_at"]}]
        },
        f"{base}/branches/main/protection/required_status_checks": {
            "contexts": ["legacy/status"],
            "checks": [],
            "strict": False,
        },
        f"{base}/commits/{head}/check-runs?per_page=100": {"check_runs": []},
    }


STATE_CASES = tuple(
    "merged merged_settled open_settled draft parked_label operator_review_label conflicting".split()
)
BOUNDARY_CASES = ("p3_2_collision", "p3_2_control", "p3_3_skew", "p3_3_control")
FALLBACK_CASES = ("direct_check_run_fallback", "rest_fallback_metadata")
PACKET_CASES = (*REPORTING_CASES, *STATE_CASES, *BOUNDARY_CASES, *FALLBACK_CASES)


def _packet_for(case: str, mp: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, list[list[str]]]:
    if case in FALLBACK_CASES:
        direct = case.startswith("direct")
        routes = _direct_check_run_routes() if direct else _rest_fallback_routes()
        calls: list[list[str]] = []
        mp.setattr(rq, "_gh_json", _routed_gh(routes, calls))
        number = "7465" if direct else "7466"
        return rq._build_packet(number, repo_override=REPO, review_queue_root=tmp_path), calls
    pr, required, calls = _in_job(mp)
    if case in REPORTING_CASES:
        _apply_reporting_case(case, mp, pr, required)
    _state_variant(case, mp, tmp_path, pr)
    _boundary_variant(case, pr, required)
    return rq._build_packet("6283", repo_override=REPO, review_queue_root=tmp_path), calls


@pytest.mark.parametrize("case", PACKET_CASES)
def test_build_packet_corpus(
    case: str, hermetic: list[list[str]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packet, calls = _packet_for(case, monkeypatch, tmp_path)
    record = {"packet": packet.to_dict(), "gh_calls": calls}
    _assert_matches_golden("behavior_corpus.json", f"packet/{case}", _normalize(record, tmp_path))


@pytest.mark.parametrize("case", ("green", "required_fail", "merged"))
def test_merge_authorization_packet_corpus(
    case: str, hermetic: list[list[str]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pr, required, calls = _in_job(monkeypatch)
    if case in REPORTING_CASES:
        _apply_reporting_case(case, monkeypatch, pr, required)
    _state_variant(case, monkeypatch, tmp_path, pr)
    packet = rq._build_merge_authorization_packet(
        pr_refs=["6283"], limit=1, repo_override=REPO, review_queue_root=tmp_path
    )
    record = _normalize({"packet": packet, "gh_calls": calls}, tmp_path)
    _assert_matches_golden("behavior_corpus.json", f"merge_auth/{case}", record)


QUORUM_CASES: dict[str, dict[str, Any]] = {
    "tier3_green": {},
    "tier3_checks_unavailable": {"checks_unavailable": True},
    "tier3_pending": {"has_pending": True},
    "tier3_failing": {"has_failures": True, "machine_recommendation": "repair_first"},
    "tier3_human_risk_settled": {"human_risk_settlement_recorded": True},
    "tier3_admin_squash_settled": {"settlement_recorded": True},
    "tier0_docs": {"files": ["docs/example.md"]},
    "tier4_review_queue": {"files": ["aragora/cli/commands/review_queue.py"]},
}


@pytest.mark.parametrize("case", sorted(QUORUM_CASES))
def test_model_review_quorum_corpus(
    case: str, hermetic: list[list[str]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pr, _required, calls = _in_job(monkeypatch)
    packet = rq._build_packet("6283", repo_override=REPO, review_queue_root=tmp_path)
    kwargs: dict[str, Any] = {
        "pr": pr,
        "files": ["aragora/server/handlers/x.py"],
        "protocol": packet.protocol,
        "machine_recommendation": "approve_candidate",
        "has_pending": False,
        "has_failures": False,
        "check_surfaces": packet.check_surfaces,
        "repo_slug": REPO,
        **QUORUM_CASES[case],
    }
    calls.clear()
    record = {"quorum": rq._build_model_review_quorum(**kwargs), "gh_calls": calls}
    _assert_matches_golden("behavior_corpus.json", f"quorum/{case}", _normalize(record, tmp_path))


def _classification_inputs() -> dict[str, list[str]]:
    tier4 = list(rq.TIER_4_PREFIXES)
    near_misses = [
        f"{path}{suffix}" if not path.endswith("/") else f"{path}child/file.py"
        for path in tier4
        for suffix in ((".bak", "/child") if not path.endswith("/") else ("",))
    ]
    return {
        "tier4_roots": tier4,
        "tier4_near_misses": near_misses,
        "tier3_roots": list(rq.TIER_3_PREFIXES),
        "tier2_roots": list(rq.TIER_2_PREFIXES),
        "samples": [
            "",
            *"""docs/example.md tests/cli/commands/test_example.py aragora/example.py
            aragora/server/handlers/x.py scripts/example.py sdk/python/aragora_sdk/client.py
            README.md pyproject.toml""".split(),
        ],
    }


def test_tier_classification_corpus() -> None:
    record: dict[str, Any] = {
        group: {path: list(rq._classify_model_review_tier([path])) for path in paths}
        for group, paths in _classification_inputs().items()
    }
    record["titles"] = {
        keyword: list(rq._classify_model_review_tier(["docs/x.md"], pr={"title": f"fix {keyword}"}))
        for keyword in rq.TIER_3_TITLE_KEYWORDS
    }
    record["empty_file_list"] = list(rq._classify_model_review_tier([]))
    _assert_matches_golden("behavior_corpus.json", "classify/all", record)


def test_corpus_has_no_unrecorded_cases() -> None:
    expected = {f"packet/{case}" for case in PACKET_CASES}
    expected |= {f"merge_auth/{case}" for case in ("green", "required_fail", "merged")}
    expected |= {f"quorum/{case}" for case in QUORUM_CASES} | {"classify/all"}
    assert set(_read_golden("behavior_corpus.json")) == expected


@pytest.mark.parametrize(
    ("case", "recommendation", "non_required_count", "admin_squash"),
    [
        ("unavailable", "approve_candidate", None, False),
        ("p3_2_collision", "approve_candidate", 0, True),
        ("p3_2_control", "approve_candidate", 1, True),
        ("p3_3_skew", "approve_candidate", None, False),
        ("p3_3_control", "repair_first", None, False),
    ],
)
def test_section8_advisory_behaviors_stay_frozen(
    case: str,
    recommendation: str,
    non_required_count: int | None,
    admin_squash: bool,
    hermetic: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Open P3 debt from PR #10039 r2; a repair needs its own adjudicated PR."""
    packet, _calls = _packet_for(case, monkeypatch, tmp_path)
    quorum = packet.model_review_quorum
    assert packet.machine_recommendation == recommendation
    assert quorum["admin_squash_allowed"] is admin_squash
    if non_required_count is not None:
        assert (
            packet.check_surfaces["pr_rollup"]["non_required_non_green_count"] == non_required_count
        )
        assert bool(packet.risk_flags) is bool(non_required_count)
    if case in {"unavailable", "p3_3_skew"}:
        assert packet.risk_flags == []
        assert (quorum["status"], quorum["verdict"]) == (
            "needs_model_review_quorum",
            "collect_model_quorum_before_merge",
        )
    if case == "p3_3_skew":
        assert packet.checks_summary == "1 pending / 6 total"
        assert "required checks are failing" in packet.machine_recommendation_reason
    if case == "p3_3_control":
        assert "checks failing (1 failing / 6 total)" in packet.risk_flags
        assert (quorum["status"], quorum["verdict"]) == (
            "repair_or_wait",
            "not_ready_for_settlement",
        )


# --- C-1 public surface -----------------------------------------------------
def _fresh_public_names() -> list[str]:
    """Names from a fresh facade import; attributes other tests attach in-process do not count."""
    probe = "import json, aragora.cli.commands.review_queue as m; print(json.dumps(dir(m)))"
    path = os.pathsep.join(filter(None, (str(REPO_ROOT), os.environ.get("PYTHONPATH"))))
    env = {**os.environ, "PYTHONPATH": path}
    out = subprocess.check_output([sys.executable, "-c", probe], cwd=REPO_ROOT, env=env, text=True)
    return sorted(name for name in json.loads(out.splitlines()[-1]) if not name.startswith("__"))


def test_public_surface_matches_the_recorded_names() -> None:
    names = _fresh_public_names()
    if REGEN:
        _write_golden("public_surface.json", {"names": names})
    recorded = _read_golden("public_surface.json")["names"]
    assert recorded and recorded == sorted(recorded)
    drift = {
        "missing": sorted(set(recorded) - set(names)),
        "added": sorted(set(names) - set(recorded)),
    }
    assert drift == {"missing": [], "added": []}
    for name in recorded:
        obj = getattr(rq, name)
        owner = getattr(obj, "__module__", None)
        if not (isinstance(owner, str) and owner.startswith("aragora.cli.commands.review_queue_")):
            continue
        unit = sys.modules[owner]
        aliases = [alias for alias in (name, getattr(obj, "__name__", None)) if alias]
        assert any(getattr(unit, alias, None) is obj for alias in aliases), (name, owner)


# --- C-3 monkeypatch seams --------------------------------------------------
def _seam_census() -> set[str]:
    """Design section 11 census: string patch targets plus setattr targets on the CLI facade."""
    string_target = re.compile(rb"aragora\.cli\.commands\.review_queue\.([A-Za-z_]+)")
    setattr_target = re.compile(rb"setattr\(\s*(?:rq|review_queue),\s*\"([A-Za-z_]+)\"")
    facade_re = re.compile(rb"(?:from|import) aragora\.cli\.commands(?: import |\.)review_queue\b")
    seams: set[str] = set()
    for path in (REPO_ROOT / "tests").rglob("*.py"):
        data = path.read_bytes()
        # Server handler tests also bind ``rq``, to a different module.
        for pattern in (string_target, setattr_target)[: 2 if facade_re.search(data) else 1]:
            seams.update(match.group(1).decode() for match in pattern.finditer(data))
    return seams


def _seam_violations(tree: ast.Module, seams: set[str]) -> list[str]:
    """Rule I2: a unit references a seam only as ``_review_queue_backend().<name>`` or through a
    function-local facade import (the I2 precedent, used by review_queue_render.py). A static
    guard: string-based access such as ``getattr(module, "name")`` is out of its reach."""
    facade = "aragora.cli.commands.review_queue"
    violations: list[str] = []

    def facade_names(scope: ast.AST) -> set[str]:
        # Python scoping: an import inside a nested function does not bind in the outer one.
        names: set[str] = set()
        for child in ast.iter_child_nodes(scope):
            if isinstance(child, ast.ImportFrom):
                names.update(
                    alias.asname or alias.name
                    for alias in child.names
                    if facade in (child.module, f"{child.module}.{alias.name}")
                )
            elif not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                names |= facade_names(child)
        return names

    def visit(node: ast.AST, late_bound: frozenset[str], import_time: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            late_bound, import_time = late_bound | facade_names(node), False
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            return
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in seams and (import_time or node.module != facade):
                    violations.append(f"line {node.lineno}: binds seam {alias.name}")
        if isinstance(node, ast.Name) and node.id in seams and node.id not in late_bound:
            violations.append(f"line {node.lineno}: uses seam {node.id}")
        if isinstance(node, ast.Attribute) and node.attr in seams:
            if ast.unparse(node.value) not in {"_review_queue_backend()", *late_bound}:
                violations.append(f"line {node.lineno}: uses seam {node.attr}")
        for child in ast.iter_child_nodes(node):
            visit(child, late_bound, import_time)

    visit(tree, frozenset(), True)
    return violations


def test_seam_census_covers_design_patch_targets() -> None:
    assert DESIGN_SEAMS <= _seam_census()


def test_units_reach_seams_through_the_facade_at_call_time() -> None:
    seams = _seam_census()
    units = [REPO_ROOT / f"aragora/cli/commands/review_queue_{unit}.py" for unit in UNIT_MODULES]
    existing = [path for path in units if path.exists()]
    assert existing, "no review_queue unit modules found"
    violations = {
        path.name: found
        for path in existing
        if (found := _seam_violations(ast.parse(path.read_text(encoding="utf-8")), seams))
    }
    assert violations == {}


def test_seam_checker_flags_bindings_and_direct_calls() -> None:
    tree = ast.parse(
        "from aragora.cli.commands.review_queue_transport import _gh_json as gh\n"
        "def moved():\n    return _gh_json([])\n"
        "def late():\n"
        "    from aragora.cli.commands.review_queue import _gh_json\n    return _gh_json([])\n"
        "def backend():\n    return _review_queue_backend()._gh_json([])\n"
        "if TYPE_CHECKING:\n    from aragora.cli.commands.review_queue_transport import _gh_json\n"
        "def other():\n    from aragora.cli.commands.review_queue_transport import _gh_json\n"
        "    return _gh_json([])\n"
        "def via_module(t):\n    from aragora.cli.commands import review_queue as rq\n"
        "    gh = t._gh_json\n    return rq._gh_json([]), helper()._gh_json([]), gh([])\n"
        "def outer():\n    def inner(): from aragora.cli.commands.review_queue import _gh_json\n"
        "    return _gh_json([])\n"
    )
    expected = {1: "binds", 3: "uses", 12: "binds", 13: "uses", 16: "uses", 17: "uses", 20: "uses"}
    found = _seam_violations(tree, {"_gh_json"})
    assert found == [f"line {n}: {verb} seam _gh_json" for n, verb in expected.items()]


# --- C-4 CLI surface --------------------------------------------------------
def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError(f"no subparsers on {parser.prog!r}")


def _help_surface(root: argparse.ArgumentParser, label: str) -> dict[str, str]:
    review_queue = _subparsers(root)["review-queue"]
    surface = {f"{label}/review-queue": review_queue.format_help()}
    for name, sub in sorted(_subparsers(review_queue).items()):
        surface[f"{label}/review-queue {name}"] = sub.format_help()
    return surface


@pytest.mark.skipif(
    sys.version_info[:2] != HELP_PYTHON,
    reason="argparse help layout differs across Python minor versions; recorded on 3.11",
)
def test_cli_help_is_byte_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    from aragora.cli.parser import build_parser

    monkeypatch.setenv("COLUMNS", "100")
    monkeypatch.setattr(sys, "argv", ["aragora"])
    standalone = argparse.ArgumentParser(prog="aragora")
    rq.add_review_queue_parser(standalone.add_subparsers(dest="command"))
    surface = {**_help_surface(build_parser(), "main"), **_help_surface(standalone, "standalone")}
    for key, text in surface.items():
        _assert_matches_golden("cli_help_py311.json", key, text)
    assert set(_read_golden("cli_help_py311.json")) == set(surface)
