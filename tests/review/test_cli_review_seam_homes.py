"""Canonical ``aragora.review`` homes for review-queue parsing and settlement receipts.

``aragora.review.comment_verdicts`` and ``aragora.review.settlement_receipt`` are
the application-layer homes of helpers that ``aragora.cli.commands`` also
defines. Until the CLI modules re-export these objects, the two definitions must
stay identical; once they re-export, the objects must be the same.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import textwrap
from pathlib import Path

import pytest

from aragora.cli.commands import review_queue, review_queue_comment_verdicts
from aragora.review import comment_verdicts, settlement_receipt

REPO_ROOT = Path(__file__).resolve().parents[2]

_FINDINGS_BODY = (
    "Summary\n[P1] first finding\n\n```\n[P0] fenced example\n```\n[P2] second finding\n"
)
_NEGATIVE_BODY = "Verdict: FAIL\n\n[P1] aragora/x.py:3 drops the error path\n"
_LABEL_BODY = "Blocking findings:\n- aragora/y.py:9 leaks a handle\n"
_CLEAN_BODY = "LGTM, no findings"
_BODIES = (_FINDINGS_BODY, _NEGATIVE_BODY, _LABEL_BODY, _CLEAN_BODY, "")

# Application-layer modules that consume review-queue parsing. They must not
# import ``aragora.cli`` at any scope.
_FLIPPED_IMPORTERS = (
    "aragora/swarm/advisory_dissent.py",
    "aragora/swarm/quorum_receipt.py",
    "aragora/swarm/review_adjudicator.py",
    "aragora/swarm/settle_plan.py",
)

# Remaining ``aragora.cli`` importers under swarm/review whose flip needs a
# Tier-4 edit (``quorum_evidence.py`` is a merge-authority root).
_PENDING_TIER4_IMPORTERS = frozenset({"aragora/swarm/quorum_evidence.py"})


def _module_functions(module: object) -> dict[str, object]:
    return {
        name: value
        for name, value in vars(module).items()
        if inspect.isfunction(value) and value.__module__ == module.__name__
    }


def _source_dump(obj: object) -> str:
    tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
    return ast.dump(tree, include_attributes=False)


def _cli_imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    type_checking_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and ast.unparse(node.test).endswith("TYPE_CHECKING"):
            type_checking_nodes |= {id(child) for child in ast.walk(node)}
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if id(node) in type_checking_nodes:
            continue
        if isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            names = []
        for name in names:
            if name == "aragora.cli" or name.startswith("aragora.cli."):
                hits.append((node.lineno, name))
        if (
            isinstance(node, ast.Call)
            and ast.unparse(node.func) in ("importlib.import_module", "__import__")
            and node.args
            and "aragora.cli" in ast.unparse(node.args[0])
        ):
            hits.append((node.lineno, "dynamic"))
    return hits


def test_canonical_homes_live_in_aragora_review() -> None:
    assert comment_verdicts.extract_finding_lines.__module__ == "aragora.review.comment_verdicts"
    assert (
        inspect.getmodule(settlement_receipt.SettlementReceipt).__name__
        == "aragora.review.settlement_receipt"
    )


def test_comment_verdict_functions_match_cli_definitions() -> None:
    cli_functions = _module_functions(review_queue_comment_verdicts)
    review_functions = _module_functions(comment_verdicts)
    if not cli_functions:
        # The CLI module re-exports the canonical objects.
        for name, value in review_functions.items():
            assert getattr(review_queue_comment_verdicts, name) is value, name
        return
    assert sorted(cli_functions) == sorted(review_functions)
    for name, cli_value in cli_functions.items():
        assert _source_dump(cli_value) == _source_dump(review_functions[name]), name


def test_comment_verdict_constants_match_cli_definitions() -> None:
    names = {
        name
        for name, value in vars(comment_verdicts).items()
        if name.lstrip("_").isupper() and not inspect.ismodule(value)
    }
    assert names
    for name in names:
        assert getattr(review_queue_comment_verdicts, name) == getattr(comment_verdicts, name), name


@pytest.mark.parametrize("body", _BODIES)
@pytest.mark.parametrize(
    "function_name",
    (
        "extract_finding_lines",
        "has_blocking_finding_or_label",
        "has_blocking_or_negative_verdict",
        "highest_blocking_severity",
    ),
)
def test_fixed_input_results_match_at_both_paths(function_name: str, body: str) -> None:
    cli_function = getattr(review_queue_comment_verdicts, function_name)
    review_function = getattr(comment_verdicts, function_name)
    assert review_function(body) == cli_function(body)


def test_extract_finding_lines_fixed_fixture() -> None:
    for module in (review_queue_comment_verdicts, comment_verdicts):
        assert module.extract_finding_lines(_FINDINGS_BODY) == [
            "[P1] first finding",
            "[P2] second finding",
        ]
        assert module.extract_finding_lines(_CLEAN_BODY) == []


def test_settlement_receipt_matches_cli_definition() -> None:
    cli_class = review_queue.SettlementReceipt
    review_class = settlement_receipt.SettlementReceipt
    if cli_class is review_class:
        return
    assert _source_dump(cli_class) == _source_dump(review_class)
    cli_fields = [(f.name, f.type, f.default) for f in dataclasses.fields(cli_class)]
    review_fields = [(f.name, f.type, f.default) for f in dataclasses.fields(review_class)]
    assert cli_fields == review_fields
    assert cli_class.__slots__ == review_class.__slots__


@pytest.mark.parametrize("audit", (None, {"lane": "merge", "ok": True}))
def test_settlement_receipt_round_trips_at_both_paths(audit: dict[str, object] | None) -> None:
    kwargs: dict[str, object] = {
        "session_id": "sess-1",
        "reviewed_at": "2026-04-15T12:00:00+00:00",
        "actor": "founder",
        "action": "approve",
        "reason": "fixture",
        "pr_number": 7,
        "pr_url": "https://github.com/o/r/pull/7",
        "head_sha": "a" * 40,
        "base_sha": "b" * 40,
        "packet_sha": "c" * 64,
        "queue_bucket": "ready_now",
        "machine_recommendation": "approve",
        "github_event": "APPROVE",
        "outcome_rollback": False,
        "post_merge_lane_audit": audit,
    }
    cli_payload = review_queue.SettlementReceipt(**kwargs).to_dict()
    review_payload = settlement_receipt.SettlementReceipt(**kwargs).to_dict()
    assert review_payload == cli_payload
    assert ("post_merge_lane_audit" in review_payload) is (audit is not None)
    rebuilt = settlement_receipt.SettlementReceipt(**review_payload)
    assert rebuilt.to_dict() == review_payload


def test_observe_outcomes_materializes_canonical_receipt() -> None:
    from aragora.review import observe_outcomes_cli

    payload = {
        "session_id": "sess-1",
        "reviewed_at": "2026-04-15T12:00:00+00:00",
        "actor": "founder",
        "action": "approve",
        "reason": "fixture",
        "pr_number": 7,
        "pr_url": "https://github.com/o/r/pull/7",
        "head_sha": "a" * 40,
        "base_sha": "b" * 40,
        "packet_sha": "c" * 64,
        "queue_bucket": "ready_now",
        "machine_recommendation": "approve",
        "github_event": "APPROVE",
        "unknown_extra_field": "ignored",
    }
    receipt = observe_outcomes_cli._materialize_receipt(payload)
    assert type(receipt) is settlement_receipt.SettlementReceipt
    assert receipt.pr_number == 7
    assert "unknown_extra_field" not in receipt.to_dict()


@pytest.mark.parametrize("relative_path", _FLIPPED_IMPORTERS)
def test_flipped_importers_hold_no_cli_import(relative_path: str) -> None:
    assert _cli_imports(REPO_ROOT / relative_path) == []


def test_review_and_swarm_cli_imports_are_limited_to_pending_tier4_sites() -> None:
    offenders = {
        path.relative_to(REPO_ROOT).as_posix(): hits
        for package in ("review", "swarm")
        for path in sorted((REPO_ROOT / "aragora" / package).rglob("*.py"))
        if (hits := _cli_imports(path))
    }
    assert set(offenders) <= _PENDING_TIER4_IMPORTERS, offenders
