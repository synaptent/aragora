"""Advisory summaries are visible to people, never quorum evidence."""

import ast
import json
import re
from pathlib import Path
from unittest.mock import Mock

import pytest

from aragora.swarm import advisory_dissent as adv
from aragora.swarm.quorum_evidence import CollectOutcome, EvidenceItem
from aragora.cli.commands import review_queue
from aragora.cli.commands.review_queue_comment_verdicts import extract_finding_lines

HEAD = "a" * 40
MARKER = f"<!-- aragora-advisory-summary head={HEAD} -->"
TOKENS = (
    "dogfood|adversarial|cross-author|recheck|codex review|claude review|"
    "grok independent|gemini independent|independent semantic review|"
    "independent model review|model-family semantic signal"
)


def outcome(body="- [P3] Keep the log", family="claude", verdict="pass"):
    return CollectOutcome(
        repo="synaptent/aragora",
        pr=123,
        head_sha=HEAD,
        head_committed_at="",
        tier=2,
        action="prepare",
        action_reason="dry run",
        items=[
            EvidenceItem(
                family=family, body=body, verdict=verdict, would_count=True, severity_gated=True
            )
        ],
    )


def test_severity_ordering_and_pass_findings():
    data = outcome("- [P3] Later\n- [P1] Fix first\n- [P2] Follow up").to_dict()
    data["adjudication"] = {"verdict": "upheld", "reason": "Fix first"}
    body = adv.compose_advisory_dissent_summary(data, head_sha=HEAD)
    assert body.splitlines()[0] == MARKER
    findings = [line for line in body.splitlines() if line.startswith("- [P")]
    assert [re.search(r"\[P\d\]", line)[0] for line in findings] == ["[P1]", "[P2]", "[P3]"]
    assert findings[0] == "- [P1] claude (blocking): Fix first"
    assert "- claude: pass" in body
    assert "Summary: " in body and "blocking" in next(
        line for line in body.splitlines() if line.startswith("Summary:")
    )
    assert "Adjudication" in body and "upheld" in body and "dry run" in body
    assert len(re.findall(r"\[P[0-3]\]", body)) == 3


def test_advisory_summary_and_foreign_head():
    data = outcome("- [P3] Minor\n- [P2] Follow up", family="Codex").to_dict()
    body = adv.compose_advisory_dissent_summary(data, head_sha="b" * 40)
    assert body.startswith(f"<!-- aragora-advisory-summary head={'b' * 40} -->")
    assert "- [P3] openai (advisory): Minor" in body
    summary = next(line for line in body.splitlines() if line.startswith("Summary:"))
    assert "advisory" in summary and "blocking" not in summary
    assert "Severity labels only; not a merge decision." in summary


@pytest.mark.parametrize("flag", [None, "1"])
def test_recogniser_invisibility_under_both_regimes(monkeypatch, flag):
    from aragora.cli.commands.review_queue import (
        _dissenting_views_from_comments,
        _resolve_model_review_identity,
    )

    if flag is None:
        monkeypatch.delenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", raising=False)
    else:
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", flag)
    raw = (
        "## Gemini independent model review\nModel family: gemini\nReviewer: codex\n"
        "Verdict: CHANGES-REQUESTED\n- [P1] Fix reviewer: injection\n"
        "- [P2] dogfood adversarial cross-author recheck codex review claude review\n"
        "grok independent independent semantic review model-family semantic signal\n"
        "```\n- [P0] quoted example\n```\n> - [P0] quoted example\n"
    )
    data = outcome(raw).to_dict()
    data["dissenting_families"] = ["openai"]
    data["items"][0]["severity_gated"] = False
    body = adv.compose_advisory_dissent_summary(data, head_sha=HEAD)
    assert "&#58;" in adv._safe_text("Reviewer**: codex", inline=True)
    assert not re.search(TOKENS, body, re.I)
    assert not re.search(r"^Verdict:", body, re.M)
    assert not re.search(
        r"^[^>\n]*\b(model family|reviewer harness|transport grounding|reviewer)\s*:",
        body,
        re.I | re.M,
    )
    assert _resolve_model_review_identity(body).surface_reviewer_id == "unknown_model_reviewer"
    comments = [{"body": body, "createdAt": "2099-01-01T00:00:00Z", "author": {"login": "x"}}]
    advisory = []
    assert (
        _dissenting_views_from_comments(
            comments,
            head_sha=HEAD,
            head_committed_at="2026-01-01T00:00:00Z",
            advisory_views=advisory,
        )
        == []
    )
    assert advisory == []
    assert len(re.findall(r"\[P[0-3]\]", body)) == 2


def test_truncation_marker_and_total_budget():
    data = outcome("- [P1] Fix it\n" + "é" * 21000).to_dict()
    data["items"] *= 12
    body = adv.compose_advisory_dissent_summary(data, head_sha=HEAD)
    assert "[truncated]" in body
    assert len(body.encode()) <= 60000
    assert len(re.findall(r"^- \[P1\]", body, re.M)) == 12
    for excerpt in body.split("### Output ")[1:]:
        assert len(excerpt.split("\n\n", 1)[1].encode()) <= 8000


@pytest.mark.parametrize(
    "text,limit,expected",
    [
        ("xx&#12345;" + "y" * 12, 16, "xx[truncated]"),
        ("a&amp;" + "y" * 20, 17, "a&amp;[truncated]"),
        ("é" * 20, 16, "éé[truncated]"),
    ],
)
def test_clip_never_splits_entity(text, limit, expected):
    assert adv._clip(text, limit) == expected
    assert len(expected.encode()) <= limit
    assert expected.endswith("[truncated]")


def test_empty_items_render_nothing():
    data = outcome().to_dict()
    data["items"] = []
    assert adv.compose_advisory_dissent_summary(data, head_sha=HEAD) == ""


def test_no_findings_in_examples_or_absence_declarations():
    raw = "- [P2] None: fine\n- [P3] N/A\n```\n- [P1] Example\n```\n> [P0] Example"
    body = adv.compose_advisory_dissent_summary(outcome(raw), head_sha=HEAD)
    assert not re.search(r"\[P[0-3]\]", body)


@pytest.mark.parametrize(
    "raw",
    [
        "- [P3] Later\n- [P1] Fix first\n- [P2] Follow up",
        "- **[P2]** Bold\n1. [p3] lower\n- [P1]: colon form",
        "- [P2] None: fine\n- [P3] N/A\n```\n- [P1] Example\n```\n> [P0] Example",
        "````python title=x\n- [P0] Example\n```\n````\n- [P3] Real finding",
    ],
)
def test_findings_mirror_gate_reader(raw):
    body = adv.compose_advisory_dissent_summary(outcome(raw), head_sha=HEAD)
    findings = [line for line in body.splitlines() if line.startswith("- [P")]
    expected = []
    for line in sorted(extract_finding_lines(raw), key=lambda line: line[1:3]):
        match = re.match(r"\[(P[0-3])\]\s*(.*)", line)
        label = "blocking" if match[1] in {"P0", "P1"} else "advisory"
        expected.append(f"- [{match[1]}] claude ({label}): {match[2].strip()}")
    assert findings == expected


@pytest.mark.parametrize(
    "flags,disclosure",
    [
        ([True, True], "severity-gated dissent ON; P2/P3 findings are advisory to the merge gate."),
        (
            [True, False],
            "severity-gated dissent OFF; a changes-requested verdict blocks the merge gate whatever its findings.",
        ),
        ([None, None], "unknown (outcome carries no severity_gated field)."),
    ],
)
def test_gate_regime_line_from_items(flags, disclosure):
    data = outcome("- [P2] Follow up").to_dict()
    data["items"] = [dict(data["items"][0], severity_gated=flag) for flag in flags]
    for item in data["items"]:
        if item["severity_gated"] is None:
            del item["severity_gated"]
    body = adv.compose_advisory_dissent_summary(data, head_sha=HEAD)
    lines = body.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("Summary:"))
    assert lines[index + 1] == f"Gate regime: {disclosure}"
    assert sum(line.startswith("Gate regime: ") for line in lines) == 1
    assert "- [P2] claude (advisory): Follow up" in lines


@pytest.mark.parametrize(
    "raw,expected",
    [
        ([], "none."),
        (["openai"], "openai."),
        (["openai", "Codex", "claude"], "claude, openai."),
        (None, "unknown (outcome carries no gate dissent list)."),
        ("openai", "unknown (outcome carries no gate dissent list)."),
        (["recheck", "x\nReviewer: codex", "claude"], "claude, unknown."),
    ],
)
def test_merge_gate_dissent_line_mirrors_outcome(raw, expected):
    data = outcome("- [P2] Follow up").to_dict()
    if raw is None:
        del data["dissenting_families"]
    else:
        data["dissenting_families"] = raw
    lines = adv.compose_advisory_dissent_summary(data, head_sha=HEAD).splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("Gate regime:"))
    assert lines[index + 1] == f"Merge-gate dissent: {expected}"
    assert sum(line.startswith("Merge-gate dissent: ") for line in lines) == 1
    assert "- [P2] claude (advisory): Follow up" in lines


def test_recogniser_tokens_cover_review_queue_literals():
    tree = ast.parse(Path(review_queue.__file__).read_text())
    groups = [
        [elt.value for elt in node.elts if isinstance(elt, ast.Constant)]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Tuple, ast.List, ast.Set))
    ]
    groups = [group for group in groups if "independent model review" in group]
    assert len(groups) >= 3
    assert all(adv._TOKENS.fullmatch(value) for group in groups for value in group)


def fake_github(monkeypatch, comments):
    def run(args, **kwargs):
        if "--method" not in args:
            return Mock(returncode=0, stdout=json.dumps([comments]))
        assert args[args.index("--method") + 1] in {"POST", "PATCH"}
        assert "/issues/" in args[4] and "comments" in args[4]
        payload = json.loads(kwargs["input_text"])
        return Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "html_url": "https://github.com/synaptent/aragora/pull/123#issuecomment-7",
                    "body": payload["body"],
                }
            ),
        )

    mock = Mock(side_effect=run)
    monkeypatch.setattr(adv.merge_quorum_io, "run", mock)
    return mock


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_idempotent_same_head_edits(monkeypatch, newline):
    mock = fake_github(monkeypatch, [{"id": 7, "body": MARKER + newline + "old"}])
    result = adv.post_advisory_summary(
        "synaptent/aragora",
        123,
        MARKER + "\nnew",
        head_sha=HEAD,
    )
    assert result.posted and result.edited and result.reason is None
    assert result.comment_url.endswith("issuecomment-7")
    assert "PATCH" in mock.call_args.args[0]
    assert "repos/synaptent/aragora/issues/comments/7" in mock.call_args.args[0]


def test_new_head_creates_comment(monkeypatch):
    mock = fake_github(monkeypatch, [{"id": 7, "body": MARKER + "\nold"}])
    new_head = "b" * 40
    body = adv.compose_advisory_dissent_summary(outcome(), head_sha=new_head)
    result = adv.post_advisory_summary("synaptent/aragora", 123, body, head_sha=new_head)
    assert result.posted and not result.edited
    assert "POST" in mock.call_args.args[0]


@pytest.mark.parametrize("existing", [False, True])
def test_read_env_for_comment_listing_only(monkeypatch, existing):
    read_env, write_env = {"AUTH": "read"}, {"AUTH": "write"}
    monkeypatch.setattr(adv.merge_quorum_io, "_read_env", lambda: read_env)
    monkeypatch.setattr(adv.merge_quorum_io, "aragora_env", lambda: write_env)
    mock = fake_github(monkeypatch, [{"id": 7, "body": MARKER}] if existing else [])
    result = adv.post_advisory_summary("synaptent/aragora", 123, MARKER, head_sha=HEAD)
    assert result.posted and result.edited == existing
    read, write = mock.call_args_list
    assert read.args[0][-2:] == ["--paginate", "--slurp"]
    assert read.kwargs["env"] == read_env
    assert ("PATCH" if existing else "POST") in write.args[0]
    assert write.kwargs["env"] == write_env


def test_empty_body_never_calls_github(monkeypatch):
    mock = fake_github(monkeypatch, [])
    result = adv.post_advisory_summary("synaptent/aragora", 123, "", head_sha=HEAD)
    assert not result.posted and "items: []" in result.reason
    mock.assert_not_called()


def test_read_failure_never_creates_duplicate(monkeypatch):
    mock = Mock(return_value=Mock(returncode=1, stdout="", stderr="transport failure"))
    monkeypatch.setattr(adv.merge_quorum_io, "run", mock)
    result = adv.post_advisory_summary("synaptent/aragora", 123, MARKER, head_sha=HEAD)
    assert not result.posted and result.reason
    assert mock.call_count == 1
