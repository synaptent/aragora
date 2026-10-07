"""One review invocation, consistent offline exports, no fabricated clean runs."""

import argparse
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from aragora.cli import review
from aragora.core import DebateResult
from aragora.gauntlet.odr_verify import verify_odr_document


def test_installed_cli_parser_accepts_bundle_flags():
    from aragora.cli.parser import _add_review_parser

    parsed = []
    for register in (_add_review_parser, review.create_review_parser):
        parser = argparse.ArgumentParser()
        register(parser.add_subparsers())
        args = parser.parse_args(
            [
                "review",
                "--bundle",
                "--output-dir",
                "out",
                "--head-sha",
                "a" * 40,
                "--diff-truncated",
            ]
        )
        parsed.append((args.bundle, args.output_dir, args.head_sha, args.diff_truncated))
    assert parsed == [(True, "out", "a" * 40, True)] * 2


def test_receipt_failure_is_not_masked_by_ci_findings(execution, monkeypatch):
    args, _, _, _ = execution
    args.ci = True
    monkeypatch.setattr(review, "_emit_requested_odr", lambda *a: False)
    assert review.cmd_review(args) == 3
    assert read_bundle(args)[1]["status"] == "failed"


@pytest.fixture
def execution(tmp_path, monkeypatch):
    parser = argparse.ArgumentParser()
    review.create_review_parser(parser.add_subparsers())
    diff = tmp_path / "pr.diff"
    diff.write_text("diff --git a/a.py b/a.py\n+print('hello')\n")
    args = parser.parse_args(
        [
            "review",
            "https://github.com/example/repo/pull/7",
            "--diff-file",
            str(diff),
            "--output-dir",
            str(tmp_path / "out"),
            "--bundle",
            "--head-sha",
            "a" * 40,
            "--agents",
            "anthropic-api,openai-api",
        ]
    )
    result = DebateResult(
        final_answer="A completed advisory review, not merge authorization.",
        debate_status="completed",
        messages=[
            SimpleNamespace(agent=a, content="Reviewed", role="reviewer")
            for a in ["anthropic-api", "openai-api"]
        ],
    )
    findings = review.get_demo_findings()
    findings["all_critiques"] = [object()]  # Engine objects must not leak into JSON exports.
    run = AsyncMock(return_value=result)
    monkeypatch.setattr(review, "run_review_debate", run)
    monkeypatch.setattr(review, "extract_review_findings", lambda _: findings)
    monkeypatch.setattr(review, "_persist_review_to_km", lambda *a, **k: True)
    monkeypatch.setattr(review, "get_available_agents", lambda: args.agents)
    return args, result, findings, run


def read_bundle(args):
    from pathlib import Path

    directory = Path(args.output_dir)
    return directory, json.loads((directory / "bundle.json").read_text())


def test_one_run_exports_consistent_artifacts_and_provenance(execution):
    args, _, findings, run = execution
    assert review.cmd_review(args) == 0
    run.assert_awaited_once()
    directory, manifest = read_bundle(args)
    assert manifest["status"] == "complete"
    assert manifest["head_sha"] == "a" * 40
    assert (
        manifest["input_diff_sha256"]
        == hashlib.sha256(run.call_args.kwargs["diff"].encode()).hexdigest()
    )
    assert set(manifest["files"]) == {"comment.md", "review.json", "review.sarif"}
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest
    data = json.loads((directory / "review.json").read_text())
    sarif = json.loads((directory / "review.sarif").read_text())
    assert data["critical_issues"] == findings["critical_issues"]
    assert data["split_opinions"] == [list(value) for value in findings["split_opinions"]]
    assert sarif["runs"][0]["properties"]["review_context"] == data["review_context"]
    assert manifest["review_run_id"] in (directory / "comment.md").read_text()
    assert "all_critiques" not in data


@pytest.mark.parametrize(
    "failure", [TimeoutError("private detail"), RuntimeError("private detail")]
)
def test_provider_failure_is_not_clean(execution, failure):
    args, _, _, run = execution
    run.side_effect = failure
    assert review.cmd_review(args) != 0
    directory, manifest = read_bundle(args)
    assert manifest["status"] == "failed"
    assert "not a clean review" in " ".join(manifest["limitations"])
    assert "private detail" not in (directory / "comment.md").read_text()
    assert json.loads((directory / "review.sarif").read_text())["runs"][0]["invocations"] == [
        {"executionSuccessful": False}
    ]


@pytest.mark.parametrize("reason", ["missing", "failure", "truncated", "unfinished", "gauntlet"])
def test_incomplete_execution_retains_findings_without_success(execution, monkeypatch, reason):
    args, result, _, run = execution
    if reason == "missing":
        result.messages.pop()
    elif reason == "failure":
        result.agent_failures = {"openai-api": [{"type": "timeout"}]}
    elif reason == "truncated":
        args.diff_truncated = True
    elif reason == "unfinished":
        result.debate_status = "failed"
    else:
        args.gauntlet = True
        monkeypatch.setattr(review, "run_gauntlet_on_diff", AsyncMock(side_effect=TimeoutError()))
    assert review.cmd_review(args) == 3
    _, manifest = read_bundle(args)
    assert manifest["status"] == "incomplete"
    assert manifest["exit_code"] == 3
    run.assert_awaited_once()


def test_bundle_requires_directory_without_calling_provider(execution):
    args, _, _, run = execution
    args.output_dir = None
    assert review.cmd_review(args) == 1
    run.assert_not_called()


def test_default_agent_fallback_is_disclosed_not_missing(execution, monkeypatch):
    args, result, _, _ = execution
    args.agents = review.DEFAULT_REVIEW_AGENTS
    monkeypatch.setattr(review, "get_available_agents", lambda: "anthropic-api")
    result.messages = result.messages[:1]
    assert review.cmd_review(args) == 0
    manifest = read_bundle(args)[1]
    assert manifest["effective_agents"] == ["anthropic-api"]
    assert manifest["missing_agents"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested,resolved",
    [
        ("anthropic-api", False),
        ("openai-api", False),
        ("claude", False),
        ("claude,codex", False),
        (review.DEFAULT_REVIEW_AGENTS, True),
    ],
)
async def test_explicit_reviewers_are_not_substituted(requested, resolved, monkeypatch):
    available = Mock(return_value="anthropic-api,openai-api")
    create = Mock(return_value=object())
    monkeypatch.setattr(review, "get_available_agents", available)
    monkeypatch.setattr(review, "create_agent", create)
    monkeypatch.setattr(review, "Arena", lambda *a: SimpleNamespace(run=AsyncMock()))
    await review.run_review_debate("diff", agents_str=requested, rounds=1, resolved_agents=resolved)
    assert [call.kwargs["model_type"] for call in create.call_args_list] == requested.split(",")
    available.assert_not_called()


@pytest.mark.parametrize("agent", ["anthropic-api", "openai-api"])
def test_single_key_bundle_records_only_the_selected_provider(execution, monkeypatch, agent):
    args, result, _, run = execution
    args.agents = agent
    monkeypatch.setattr(review, "get_available_agents", lambda: "anthropic-api,openai-api")
    result.messages = [SimpleNamespace(agent=agent, content="Reviewed", role="reviewer")]
    assert review.cmd_review(args) == 0
    assert run.call_args.kwargs["agents_str"] == agent
    manifest = read_bundle(args)[1]
    assert manifest["requested_agents"] == manifest["effective_agents"] == [agent]
    assert manifest["missing_agents"] == []


def test_bundle_does_not_publish_without_head_checked_action(execution):
    args, _, _, run = execution
    args.post_comment = True
    assert review.cmd_review(args) == 1
    run.assert_not_called()


def test_existing_json_output_is_unchanged_without_bundle(execution):
    args, _, _, _ = execution
    args.bundle = False
    args.output_format = "json"
    assert review.cmd_review(args) == 0
    from pathlib import Path

    directory = Path(args.output_dir)
    assert {p.name for p in directory.iterdir()} == {"review.json"}
    data = json.loads((directory / "review.json").read_text())
    assert "review_context" not in data
    assert set(data) == {
        "unanimous_critiques",
        "split_opinions",
        "risk_areas",
        "agreement_score",
        "critical_issues",
        "high_issues",
        "medium_issues",
        "low_issues",
        "meta_issues",
        "summary",
    }


def test_demo_remains_explicitly_synthetic_and_offline(execution):
    args, _, _, run = execution
    args.demo = True
    assert review.cmd_review(args) == 0
    run.assert_not_called()
    _, manifest = read_bundle(args)
    assert manifest["demo"] and manifest["status"] == "incomplete"


def test_ci_findings_exit_is_not_execution_failure(execution):
    args, _, _, _ = execution
    args.ci = True
    assert review.cmd_review(args) == 1
    assert read_bundle(args)[1]["status"] == "complete"


def test_receipt_binds_bundle_identity_and_diff(execution, monkeypatch):
    args, result, _, _ = execution
    args.emit_odr = ""
    result.messages.pop()  # Retained findings must not yield a clean receipt.
    monkeypatch.setattr("aragora.gauntlet.odr_export.sign_odr_if_configured", lambda doc: doc)
    assert review.cmd_review(args) == 3
    directory, manifest = read_bundle(args)
    odr = json.loads((directory / "review.odr.json").read_text())
    assert odr["subject"]["identifier"] == manifest["review_run_id"]
    assert odr["subject"]["digest"]["value"] == manifest["input_diff_sha256"]
    assert odr["subject"]["repository"] == "example/repo"
    assert odr["subject"]["head_sha"] == "a" * 40
    assert odr["claim"]["verdict"] == "INCONCLUSIVE"
    assert verify_odr_document(odr).ok


def test_renderer_failure_leaves_failed_manifest(execution, monkeypatch):
    args, _, _, _ = execution
    monkeypatch.setattr(
        review, "findings_to_sarif", lambda _: (_ for _ in ()).throw(ValueError("bad"))
    )
    assert review.cmd_review(args) == 3
    assert read_bundle(args)[1]["status"] == "failed"
