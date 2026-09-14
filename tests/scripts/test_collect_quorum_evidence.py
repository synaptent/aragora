"""The wrapper adds advisory delivery without changing collection semantics."""

import json
from unittest.mock import Mock

import pytest

from aragora.swarm import advisory_dissent as adv
from aragora.swarm import quorum_evidence as quorum
from scripts import collect_quorum_evidence as cli


@pytest.fixture
def collected(monkeypatch):
    data = quorum.CollectOutcome(
        repo="synaptent/aragora",
        pr=123,
        head_sha="a" * 40,
        head_committed_at="",
        tier=2,
        action="prepare",
        action_reason="dry run",
        items=[
            quorum.EvidenceItem(
                family="claude",
                body="- [P3] Minor",
                verdict="pass",
                would_count=True,
                severity_gated=True,
            )
        ],
    ).to_dict()

    def run(**kwargs):
        assert kwargs["json_output"] is True
        kwargs["printer"](json.dumps(data))
        return 2

    collector = Mock(side_effect=run)
    poster = Mock(
        return_value=adv.AdvisoryPostResult(
            posted=True,
            comment_url="https://example.test/comment",
            reason=None,
            edited=False,
        )
    )
    monkeypatch.setattr(cli, "_hydrate_provider_secrets", lambda: None)
    monkeypatch.setattr(quorum, "run_collect_cli", collector)
    monkeypatch.setattr(adv, "post_advisory_summary", poster)
    return data, collector, poster


ARGS = ["--repo", "synaptent/aragora", "--pr", "123"]


def test_default_off_json_keys(collected, capsys):
    _, _, poster = collected
    assert cli.main(ARGS + ["--json"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["advisory_posted"] is False
    assert data["advisory_comment_url"] is None and data["advisory_reason"]
    poster.assert_not_called()


@pytest.mark.parametrize("prepared", [False, True])
def test_flag_plumbing_fresh_and_prepared(collected, capsys, prepared, tmp_path):
    original, collector, poster = collected
    path = tmp_path / "prepared.json"
    path.write_text(json.dumps(original))
    flags = ["--prepared-json", str(path)] if prepared else []
    assert (
        cli.main(
            ARGS
            + flags
            + [
                "--post-advisory-summary",
                "--json",
                "--apply",
                "--author",
                "x",
                "--reviewers",
                "claude",
                "openai",
                "--reviewer-timeout",
                "30",
                "--overall-timeout",
                "60",
            ]
        )
        == 2
    )
    data = json.loads(capsys.readouterr().out)
    assert data["advisory_posted"] is True and data["advisory_reason"] is None
    assert data["advisory_comment_url"] == "https://example.test/comment"
    assert all(data[key] == value for key, value in original.items())
    kwargs = collector.call_args.kwargs
    assert kwargs["prepared_json"] == (path if prepared else None)
    assert kwargs["families"] == ["claude", "openai"] and kwargs["author"] == "x"
    assert kwargs["apply"] is True
    assert kwargs["reviewer_timeout_seconds"] == 30 and kwargs["overall_timeout_seconds"] == 60
    poster.assert_called_once()
    assert poster.call_args.kwargs["head_sha"] == original["head_sha"]


@pytest.mark.parametrize("artifact", ["stale", "missing", "malformed", "[]", "null", "{}"])
def test_prepared_json_stale_head_not_summarised(collected, capsys, tmp_path, artifact):
    data, _, poster = collected
    path = tmp_path / "prepared.json"
    if artifact != "missing":
        path.write_text(
            json.dumps(dict(data, head_sha="b" * 40)) if artifact == "stale" else artifact
        )
    assert cli.main(ARGS + ["--prepared-json", str(path), "--post-advisory-summary", "--json"]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["advisory_posted"] is False
    reason = output["advisory_reason"]
    assert reason == (
        "prepared head bbbbbbb differs from live head aaaaaaa; not summarised"
        if artifact == "stale"
        else "prepared artifact unreadable; not summarised"
    )
    poster.assert_not_called()


def test_empty_items_never_calls_poster(collected, capsys):
    data, _, poster = collected
    data["items"] = []
    assert cli.main(ARGS + ["--post-advisory-summary", "--json"]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["advisory_posted"] is False and "items: []" in output["advisory_reason"]
    poster.assert_not_called()


@pytest.mark.parametrize("raises", [False, True])
def test_posting_failure_preserves_exit_code(collected, capsys, raises):
    _, _, poster = collected
    if raises:
        poster.side_effect = RuntimeError("delivery failed")
    else:
        poster.return_value = adv.AdvisoryPostResult(False, None, "delivery failed", False)
    assert cli.main(ARGS + ["--post-advisory-summary", "--json"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["advisory_posted"] is False and data["advisory_reason"]


def test_text_output_keeps_collection_and_advisory_fields(collected, capsys):
    assert cli.main(ARGS) == 2
    text = capsys.readouterr().out
    assert "action: prepare (dry run)" in text
    assert "advisory_posted: False" in text and "advisory_reason:" in text


@pytest.mark.parametrize("malformed", ["empty_item", "foreign_mode", "missing_target"])
def test_text_output_malformed_object_never_tracebacks(collected, capsys, malformed):
    data, _, poster = collected
    if malformed == "empty_item":
        data["items"] = [{}]
    elif malformed == "foreign_mode":
        data["mode"] = "foreign"
    else:
        del data["repo"], data["pr_number"]
    assert cli.main(ARGS) == 2
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "error: outcome could not be rendered (ValueError)",
        "  advisory_posted: False",
        "  advisory_comment_url: None",
        "  advisory_reason: --post-advisory-summary not enabled",
        "  advisory_edited: False",
    ]
    assert "Traceback" not in captured.err
    poster.assert_not_called()


def test_collect_failure_payload(collected, capsys):
    data, _, poster = collected
    data.clear()
    data.update(mode="collect_evidence", error="preflight failed")
    assert cli.main(ARGS + ["--post-advisory-summary"]) == 2
    assert "error: preflight failed" in capsys.readouterr().out
    poster.assert_not_called()


@pytest.mark.parametrize("payload", ["", "diagnostic text", "[]", "null"])
def test_malformed_capture_failure_preserves_exit(collected, capsys, payload):
    _, collector, poster = collected

    def run(**kwargs):
        if payload:
            kwargs["printer"](payload)
        return 2

    collector.side_effect = run
    assert cli.main(ARGS + ["--post-advisory-summary", "--json"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["error"] == "collection outcome was not a JSON object"
    assert data["advisory_posted"] is False
    poster.assert_not_called()


def test_transport_failure_keeps_text_context(collected, capsys):
    data, _, poster = collected
    error = quorum.CollectPreflightTransportError(
        repo="synaptent/aragora",
        pr=123,
        phase="fetch_pr_context",
        error=RuntimeError("network unavailable"),
        attempts=3,
    )
    data.clear()
    data.update(error.to_dict())
    assert cli.main(ARGS) == 2
    assert capsys.readouterr().out.splitlines()[0] == f"error: {error}"
    poster.assert_not_called()


def test_help_lists_existing_and_new_flags(collected, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    for flag in (
        "--repo",
        "--pr",
        "--reviewers",
        "--author",
        "--apply",
        "--reviewer-timeout",
        "--overall-timeout",
        "--prepared-json",
        "--json",
        "--post-advisory-summary",
    ):
        assert flag in help_text
