"""Canonical ``aragora.review`` homes for review-queue parsing and settlement receipts.

``aragora.review.comment_verdicts``, ``aragora.review.settlement_receipt`` and
``aragora.review.github_transport`` are the application-layer homes of helpers
that ``aragora.cli.commands`` re-exports under their historical names; the
objects at both paths must be the same. The merge-gate classifier loads these
homes, so they are Tier-4 authority-closure members.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from aragora.cli.commands import review_queue, review_queue_comment_verdicts, review_queue_transport
from aragora.review import comment_verdicts, github_transport, settlement_receipt
from aragora.swarm import quorum_evidence
from scripts import tier4_merge_train

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
    "aragora/swarm/quorum_evidence.py",
    "aragora/swarm/quorum_receipt.py",
    "aragora/swarm/review_adjudicator.py",
    "aragora/swarm/settle_plan.py",
)

_COMMENT_VERDICT_FUNCTIONS = (
    "extract_finding_lines",
    "has_blocking_finding_or_label",
    "has_blocking_or_negative_verdict",
    "highest_blocking_severity",
)

# Loaded at import time by the review-queue classifier and quorum_evidence.
_AUTHORITY_HOMES = (
    "aragora/review/__init__.py",
    "aragora/review/comment_verdicts.py",
    "aragora/review/github_transport.py",
    "aragora/review/settlement_receipt.py",
)


def _module_functions(module: object) -> dict[str, object]:
    return {
        name: value
        for name, value in vars(module).items()
        if inspect.isfunction(value) and value.__module__ == module.__name__
    }


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
    assert github_transport.is_github_transport_error.__module__ == (
        "aragora.review.github_transport"
    )


def test_cli_comment_verdicts_module_re_exports_canonical_functions() -> None:
    assert _module_functions(review_queue_comment_verdicts) == {}
    for name in _COMMENT_VERDICT_FUNCTIONS:
        assert getattr(review_queue_comment_verdicts, name) is getattr(comment_verdicts, name)


@pytest.mark.parametrize("body", _BODIES)
@pytest.mark.parametrize("function_name", _COMMENT_VERDICT_FUNCTIONS)
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


def test_cli_settlement_receipt_is_canonical_class() -> None:
    assert review_queue.SettlementReceipt is settlement_receipt.SettlementReceipt
    assert "SettlementReceipt" in review_queue.__all__


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


def test_application_review_consumers_hold_no_cli_import() -> None:
    offenders = {
        path.relative_to(REPO_ROOT).as_posix(): hits
        for package in ("compat", "review", "skills", "swarm")
        for path in sorted((REPO_ROOT / "aragora" / package).rglob("*.py"))
        if (hits := _cli_imports(path))
    }
    assert offenders == {}


@pytest.mark.parametrize(
    ("cli_name", "home_name"),
    (
        ("GITHUB_TRANSPORT_ERROR_KIND", "GITHUB_TRANSPORT_ERROR_KIND"),
        ("GITHUB_TRANSPORT_BLOCKED_STATUS", "GITHUB_TRANSPORT_BLOCKED_STATUS"),
        ("_gh_error_kind", "gh_error_kind"),
        ("_is_github_transport_error", "is_github_transport_error"),
    ),
)
def test_cli_transport_re_exports_canonical_classification(cli_name: str, home_name: str) -> None:
    assert getattr(review_queue_transport, cli_name) is getattr(github_transport, home_name)


def test_quorum_evidence_uses_canonical_transport_classification() -> None:
    assert quorum_evidence._is_github_transport_error is github_transport.is_github_transport_error
    assert quorum_evidence.GITHUB_TRANSPORT_BLOCKED_STATUS == "transport_blocked"


@pytest.mark.parametrize(
    ("error", "kind"),
    (
        ("gh pr view 7 failed: HTTP 502: Bad Gateway", "github_transport"),
        ("gh api repos/o/r timed out after 30s", "github_transport"),
        (RuntimeError("dial tcp: i/o timeout"), "github_transport"),
        ("gh pr view 7 failed: Could not resolve to a PullRequest", "github_error"),
        (None, "github_error"),
    ),
)
def test_transport_classification_fixed_inputs(error: object, kind: str) -> None:
    assert github_transport.gh_error_kind(error) == kind
    assert review_queue_transport._gh_error_kind(error) == kind
    assert github_transport.is_github_transport_error(error) is (kind == "github_transport")


@pytest.mark.parametrize("path", _AUTHORITY_HOMES)
def test_review_homes_are_tier4_authority_dependencies(path: str) -> None:
    assert path in review_queue.CONTRACT_DRIFT_AUTHORITY_DEPENDENCY_PREFIXES
    assert path in tier4_merge_train.CONTRACT_DRIFT_AUTHORITY_DEPENDENCY_PREFIXES
    assert review_queue._classify_model_review_tier([path])[0] == 4
    assert tier4_merge_train.matches_serialized_path(path) == path
