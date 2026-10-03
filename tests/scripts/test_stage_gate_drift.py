from __future__ import annotations

import json
import subprocess

import pytest

from scripts import stage_gate_drift as mod


def _issue(number: int, title: str = "t", body: str = "") -> dict:
    return {"number": number, "title": title, "body": body}


class TestSlugifyFingerprint:
    def test_normalizes_to_kebab_slug(self) -> None:
        assert mod.slugify_fingerprint("B0 corpus exhausted!") == "b0-corpus-exhausted"

    def test_collapses_separator_runs_and_strips_edges(self) -> None:
        assert mod.slugify_fingerprint("--B0__corpus  rev-6--") == "b0-corpus-rev-6"

    def test_rejects_empty_input(self) -> None:
        with pytest.raises(ValueError):
            mod.slugify_fingerprint("!!!")


class TestExtractFingerprint:
    def test_finds_marker_in_body(self) -> None:
        body = "## Drift\n\nstuff\n\n`Drift-Fingerprint: b0-corpus-exhausted`\n"
        assert mod.extract_fingerprint(body) == "b0-corpus-exhausted"

    def test_marker_is_case_insensitive_and_backtick_optional(self) -> None:
        assert mod.extract_fingerprint("drift-fingerprint: My-Slug") == "my-slug"

    def test_returns_none_when_absent(self) -> None:
        assert mod.extract_fingerprint("no marker here, just corpus talk") is None

    def test_returns_none_for_empty_body(self) -> None:
        assert mod.extract_fingerprint("") is None

    def test_ignores_inline_reference_before_marker_line(self) -> None:
        body = (
            "Prior Drift-Fingerprint: stale-slug was superseded.\n\n"
            + mod.render_fingerprint_line("current-slug")
        )
        assert mod.extract_fingerprint(body) == "current-slug"

    def test_uses_last_marker_when_legacy_body_has_duplicates(self) -> None:
        body = "\n".join(
            [
                mod.render_fingerprint_line("stale-slug"),
                "observation",
                mod.render_fingerprint_line("current-slug"),
            ]
        )
        assert mod.extract_fingerprint(body) == "current-slug"


class TestFindAnchor:
    def test_picks_lowest_numbered_matching_issue(self) -> None:
        issues = [
            _issue(9452, body=mod.render_fingerprint_line("b0-corpus-exhausted")),
            _issue(9438, body=mod.render_fingerprint_line("b0-corpus-exhausted")),
            _issue(9511, body=mod.render_fingerprint_line("rs-11a-boss-ready")),
        ]
        anchor = mod.find_anchor(issues, "b0-corpus-exhausted")
        assert anchor is not None
        assert anchor["number"] == 9438

    def test_returns_none_when_no_fingerprint_matches(self) -> None:
        issues = [_issue(1, body="no marker"), _issue(2, body="drift-fingerprint: other")]
        assert mod.find_anchor(issues, "b0-corpus-exhausted") is None


class TestFileDrift:
    @pytest.fixture()
    def recorder(self, monkeypatch) -> dict:
        calls: dict = {"comments": [], "creates": []}
        monkeypatch.setattr(
            mod,
            "list_open_drift_issues",
            lambda *, repo, label=mod.DRIFT_LABEL: calls.setdefault("listed", True)
            and calls["issues"],
        )
        monkeypatch.setattr(
            mod,
            "comment_on_issue",
            lambda *, repo, number, body: calls["comments"].append((number, body)),
        )

        def _create(*, repo, title, body, labels):
            calls["creates"].append({"title": title, "body": body, "labels": labels})
            return {"number": 9999, "title": title}

        monkeypatch.setattr(mod, "create_issue", _create)
        return calls

    def test_comments_on_existing_anchor_instead_of_creating(self, recorder) -> None:
        recorder["issues"] = [
            _issue(9438, body="evidence\n\n" + mod.render_fingerprint_line("b0-corpus-exhausted"))
        ]
        result = mod.file_drift(
            repo="org/repo",
            fingerprint="b0-corpus-exhausted",
            title="[stage-gate] B0 corpus exhausted",
            body="fresh observation",
            apply=True,
        )
        assert result["action"] == "commented"
        assert result["number"] == 9438
        assert len(recorder["comments"]) == 1
        assert recorder["comments"][0][0] == 9438
        assert "fresh observation" in recorder["comments"][0][1]
        assert recorder["creates"] == []

    def test_creates_new_issue_with_embedded_fingerprint_when_no_anchor(self, recorder) -> None:
        recorder["issues"] = []
        result = mod.file_drift(
            repo="org/repo",
            fingerprint="tw01-ledger-vacuous",
            title="[stage-gate] TW-01 ledger vacuous",
            body="observation",
            apply=True,
        )
        assert result["action"] == "created"
        assert result["number"] == 9999
        assert len(recorder["creates"]) == 1
        created = recorder["creates"][0]
        assert mod.extract_fingerprint(created["body"]) == "tw01-ledger-vacuous"
        assert mod.DRIFT_LABEL in created["labels"]
        assert recorder["comments"] == []

    def test_does_not_duplicate_marker_already_in_body(self, recorder) -> None:
        recorder["issues"] = []
        body = "observation\n\n" + mod.render_fingerprint_line("tw01-ledger-vacuous")
        mod.file_drift(
            repo="org/repo",
            fingerprint="tw01-ledger-vacuous",
            title="t",
            body=body,
            apply=True,
        )
        created_body = recorder["creates"][0]["body"]
        assert created_body.lower().count("drift-fingerprint:") == 1

    def test_replaces_mismatched_marker_in_body(self, recorder) -> None:
        recorder["issues"] = []
        body = "observation\n\n" + mod.render_fingerprint_line("stale-finding")
        mod.file_drift(
            repo="org/repo",
            fingerprint="current-finding",
            title="t",
            body=body,
            apply=True,
        )
        created_body = recorder["creates"][0]["body"]
        assert created_body.lower().count("drift-fingerprint:") == 1
        assert mod.extract_fingerprint(created_body) == "current-finding"

    def test_dry_run_reports_without_mutating(self, recorder) -> None:
        recorder["issues"] = [_issue(9438, body=mod.render_fingerprint_line("b0-corpus-exhausted"))]
        result = mod.file_drift(
            repo="org/repo",
            fingerprint="b0-corpus-exhausted",
            title="t",
            body="b",
            apply=False,
        )
        assert result["action"] == "would_comment"
        assert result["number"] == 9438
        assert recorder["comments"] == []
        assert recorder["creates"] == []

    def test_dry_run_reports_would_create_when_no_anchor(self, recorder) -> None:
        recorder["issues"] = []
        result = mod.file_drift(
            repo="org/repo", fingerprint="new-finding", title="t", body="b", apply=False
        )
        assert result["action"] == "would_create"
        assert recorder["creates"] == []

    def test_fingerprint_is_slugified_before_matching(self, recorder) -> None:
        recorder["issues"] = [_issue(9438, body=mod.render_fingerprint_line("b0-corpus-exhausted"))]
        result = mod.file_drift(
            repo="org/repo",
            fingerprint="B0 Corpus Exhausted",
            title="t",
            body="b",
            apply=True,
        )
        assert result["action"] == "commented"
        assert result["number"] == 9438


class TestLogAnchor:
    @pytest.fixture()
    def recorder(self, monkeypatch) -> dict:
        calls: dict = {"comments": [], "creates": []}
        monkeypatch.setattr(
            mod,
            "list_open_drift_issues",
            lambda *, repo, label=mod.DRIFT_LABEL: calls["issues"],
        )
        monkeypatch.setattr(
            mod,
            "comment_on_issue",
            lambda *, repo, number, body: calls["comments"].append((number, body)),
        )

        def _create(*, repo, title, body, labels):
            calls["creates"].append({"title": title, "body": body, "labels": labels})
            return {"number": 8888, "title": title}

        monkeypatch.setattr(mod, "create_issue", _create)
        return calls

    def test_appends_to_existing_monthly_log_anchor(self, recorder) -> None:
        title = mod.log_anchor_title("2026-07")
        recorder["issues"] = [_issue(9296, title=title)]
        result = mod.post_log_entry(
            repo="org/repo", month="2026-07", body="run summary", apply=True
        )
        assert result["action"] == "commented"
        assert result["number"] == 9296
        assert recorder["comments"] == [(9296, "run summary")]
        assert recorder["creates"] == []

    def test_creates_monthly_log_anchor_when_missing(self, recorder) -> None:
        recorder["issues"] = [
            _issue(9488, title="[automation] Stage-Gate Conductor Log"),
        ]
        result = mod.post_log_entry(
            repo="org/repo", month="2026-08", body="run summary", apply=True
        )
        assert result["action"] == "created"
        assert result["number"] == 8888
        assert recorder["creates"][0]["title"] == mod.log_anchor_title("2026-08")
        assert mod.LOG_LABEL in recorder["creates"][0]["labels"]
        # the run body must still land on the new anchor
        assert recorder["comments"] == [(8888, "run summary")]

    def test_rejects_malformed_month(self, recorder) -> None:
        with pytest.raises(ValueError):
            mod.post_log_entry(repo="org/repo", month="July 2026", body="b", apply=True)


class TestGitHubIssueCommands:
    def test_create_issue_finds_url_before_trailing_notice(self, monkeypatch) -> None:
        monkeypatch.setattr(
            mod,
            "_run_gh",
            lambda args: subprocess.CompletedProcess(
                args,
                0,
                stdout=(
                    "https://github.com/org/repo/issues/123?notification_referrer_id=abc\n"
                    "A new release of gh is available\n"
                ),
                stderr="",
            ),
        )
        created = mod.create_issue(repo="org/repo", title="t", body="b", labels=["label"])
        assert created["number"] == 123
        assert created["url"] == (
            "https://github.com/org/repo/issues/123?notification_referrer_id=abc"
        )

    def test_create_issue_rejects_missing_url(self, monkeypatch) -> None:
        monkeypatch.setattr(
            mod,
            "_run_gh",
            lambda args: subprocess.CompletedProcess(args, 0, stdout="", stderr=""),
        )
        with pytest.raises(RuntimeError, match="returned no issue URL"):
            mod.create_issue(repo="org/repo", title="t", body="b", labels=[])

    def test_issue_listing_requests_full_supported_limit(self, monkeypatch) -> None:
        calls: list[list[str]] = []

        def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")

        monkeypatch.setattr(mod, "_run_gh", _run)
        assert mod.list_open_drift_issues(repo="org/repo") == []
        assert calls[0][calls[0].index("--limit") + 1] == "1000"


class TestCli:
    def test_file_subcommand_dry_run_outputs_json(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(
            mod,
            "list_open_drift_issues",
            lambda *, repo, label=mod.DRIFT_LABEL: [
                _issue(9438, body=mod.render_fingerprint_line("b0-corpus-exhausted"))
            ],
        )
        rc = mod.main(
            [
                "file",
                "--repo",
                "org/repo",
                "--fingerprint",
                "b0-corpus-exhausted",
                "--title",
                "[stage-gate] B0 corpus exhausted",
                "--body",
                "observation",
            ]
        )
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["action"] == "would_comment"
        assert payload["number"] == 9438
