from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import measure_b0_scorecard as mod  # noqa: E402


def _write_metrics(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_repo_stable_path_relativizes_git_common_root(tmp_path: Path, monkeypatch) -> None:
    worktree_root = tmp_path / "worktree"
    shared_root = tmp_path / "shared"
    metrics_path = shared_root / ".aragora" / "overnight" / "boss_metrics.jsonl"
    metrics_path.parent.mkdir(parents=True)
    metrics_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(mod, "REPO_ROOT", worktree_root)
    monkeypatch.setattr(mod, "git_common_repo_root", lambda _repo_root: shared_root)

    assert mod._repo_stable_path(metrics_path) == ".aragora/overnight/boss_metrics.jsonl"


def test_main_ci_passes_at_threshold(tmp_path: Path, capsys) -> None:
    metrics_path = _write_metrics(
        tmp_path / "boss_metrics.jsonl",
        [
            {"issue_number": 1001, "terminal_class": "deliverable_pr_created"},
            {"issue_number": 1002, "terminal_class": "rescue_worker_crash"},
        ],
    )

    exit_code = mod.main(["--metrics", str(metrics_path), "--ci", "--threshold", "0.5"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert (
        captured.out.strip()
        == "status=pass scorecard_status=active success_rate=0.500 threshold=0.500 coverage_status=n/a "
        "total_ticks=2 unique_issues_attempted=2 unique_issues_succeeded=1 unique_issues_failed=1"
    )


def test_main_ci_fails_below_threshold(tmp_path: Path, capsys) -> None:
    metrics_path = _write_metrics(
        tmp_path / "boss_metrics.jsonl",
        [
            {"issue_number": 1001, "terminal_class": "deliverable_pr_created"},
            {"issue_number": 1002, "terminal_class": "rescue_worker_crash"},
        ],
    )

    exit_code = mod.main(["--metrics", str(metrics_path), "--ci", "--threshold", "0.75"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert (
        captured.out.strip()
        == "status=fail scorecard_status=active success_rate=0.500 threshold=0.750 coverage_status=n/a "
        "total_ticks=2 unique_issues_attempted=2 unique_issues_succeeded=1 unique_issues_failed=1"
    )


def test_main_json_mode_keeps_json_output(tmp_path: Path, capsys) -> None:
    metrics_path = _write_metrics(
        tmp_path / "boss_metrics.jsonl",
        [
            {"issue_number": 1001, "terminal_class": "deliverable_pr_created"},
        ],
    )

    exit_code = mod.main(["--metrics", str(metrics_path), "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "active"
    assert payload["no_rescue_success_rate"] == 1.0
    assert payload["unique_issues_attempted"] == 1


def test_load_metrics_rejects_malformed_jsonl_row(tmp_path: Path) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text(
        "\n".join(
            [
                json.dumps({"issue_number": 1001, "terminal_class": "deliverable_pr_created"}),
                "{not json}",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"malformed JSONL row at .*boss_metrics\.jsonl:2"):
        mod.load_metrics(metrics_path)


def test_load_metrics_rejects_non_object_jsonl_row(tmp_path: Path) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text(json.dumps([{"issue_number": 1001}]), encoding="utf-8")

    with pytest.raises(ValueError, match=r"JSONL row at .*boss_metrics\.jsonl:1 must be an object"):
        mod.load_metrics(metrics_path)


def test_main_uses_resolved_metrics_path_for_default_metrics(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    shared_metrics_path = tmp_path / "shared" / ".aragora" / "overnight" / "boss_metrics.jsonl"
    shared_metrics_path.parent.mkdir(parents=True)
    _write_metrics(
        shared_metrics_path,
        [{"issue_number": 1001, "terminal_class": "deliverable_pr_created"}],
    )
    seen_candidates: list[Path] = []

    def _fake_resolve_metrics_path(candidate: Path) -> Path:
        seen_candidates.append(candidate)
        return shared_metrics_path

    monkeypatch.setattr(mod, "resolve_metrics_path", _fake_resolve_metrics_path)

    exit_code = mod.main(["--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert seen_candidates == [mod.DEFAULT_METRICS_PATH]
    assert payload["status"] == "active"
    assert payload["unique_issues_attempted"] == 1


def test_compute_scorecard_uses_latest_terminal_state_per_issue() -> None:
    scorecard = mod.compute_scorecard(
        [
            {"issue_number": 1001, "terminal_class": "blocked_no_runner"},
            {"issue_number": 1001, "terminal_class": "deliverable_pr_created"},
            {"issue_number": 1002, "terminal_class": "deliverable_pr_created"},
            {"issue_number": 1002, "terminal_class": "rescue_worker_crash"},
        ]
    )

    assert scorecard["unique_issues_attempted"] == 2
    assert scorecard["unique_issues_succeeded"] == 1
    assert scorecard["unique_issues_failed"] == 1
    assert scorecard["no_rescue_success_rate"] == 0.5
    assert scorecard["tick_success_rate"] == 0.5


def test_compute_scorecard_tracks_neutral_issue_rows_without_counting_success() -> None:
    scorecard = mod.compute_scorecard(
        [
            {"issue_number": 1001, "terminal_class": "issue_already_resolved"},
            {"issue_number": 1002, "terminal_class": "deliverable_pr_created"},
            {"issue_number": 1003, "terminal_class": "blocked_auth_failure"},
        ]
    )

    assert scorecard["unique_issues_attempted"] == 3
    assert scorecard["unique_issues_succeeded"] == 1
    assert scorecard["unique_issues_failed"] == 1
    assert scorecard["unique_issues_neutral"] == 1
    assert scorecard["no_rescue_success_rate"] == 0.333
    assert scorecard["tick_success_rate"] == 0.333
    assert scorecard["neutral_classes"] == {"issue_already_resolved": 1}


def test_build_published_scorecard_links_truth_artifact_and_previous_delta(
    tmp_path: Path,
) -> None:
    metrics_path = _write_metrics(
        tmp_path / "boss_metrics.jsonl",
        [
            {"issue_number": 1001, "terminal_class": "deliverable_pr_created"},
            {"issue_number": 1002, "terminal_class": "rescue_worker_crash"},
        ],
    )
    truth_artifact_path = _write_json(
        tmp_path / "truth-artifact.json",
        {
            "generated_at": "2026-04-14T14:00:00Z",
            "corpus": {
                "path": "docs/benchmarks/corpus.json",
                "corpus_id": "tw-01-bounded-execution-v1",
                "revision": 3,
                "recorded_on": "2026-04-14",
                "success_contract": "mergeable_pr_or_merged_pr",
                "manifest_sha256": "abc123",
                "membership_sha256": "def456",
                "membership_issue_numbers": [1001, 1002],
                "issue_count": 2,
            },
            "primary_metrics": {
                "truth_success_rate": 0.5,
                "no_rescue_truth_success_rate": 0.5,
                "merged_only_rate": 0.5,
            },
            "coverage": {"is_complete": True, "missing_issue_numbers": []},
            "failure_class_distribution": {"rescue_worker_crash": 1},
            "rescue_counts_by_type": {"rescue_worker_crash": 1},
        },
    )
    previous_dir = tmp_path / "published" / "tw-01-bounded-execution-v1" / "rev-3"
    previous_dir.mkdir(parents=True)
    _write_json(
        previous_dir / "scorecard-20260407T120000Z.json",
        {
            "generated_at": "2026-04-07T12:00:00Z",
            "truth_metrics": {
                "truth_success_rate": 0.25,
                "no_rescue_truth_success_rate": 0.25,
                "merged_only_rate": 0.25,
            },
            "proxy_metrics": {
                "no_rescue_success_rate": 0.0,
                "unique_issues_attempted": 1,
            },
        },
    )

    published = mod.build_published_scorecard(
        scorecard=mod.compute_scorecard(mod.load_metrics(metrics_path)),
        rows=mod.load_metrics(metrics_path),
        metrics_path=metrics_path,
        truth_artifact_path=truth_artifact_path,
        publish_dir=tmp_path / "published",
        generated_at="2026-04-14T15:16:17Z",
    )

    assert published["generated_at"] == "2026-04-14T15:16:17Z"
    assert published["corpus"]["corpus_id"] == "tw-01-bounded-execution-v1"
    assert published["corpus"]["manifest_sha256"] == "abc123"
    assert published["corpus"]["membership_sha256"] == "def456"
    assert published["corpus"]["membership_issue_numbers"] == [1001, 1002]
    assert published["truth_metrics"]["truth_success_rate"] == 0.5
    assert published["proxy_metrics"]["no_rescue_success_rate"] == 0.5
    assert published["previous_artifact"]["path"].endswith(
        "tw-01-bounded-execution-v1/rev-3/scorecard-20260407T120000Z.json"
    )
    assert published["deltas"]["truth_success_rate"] == 0.25
    assert published["deltas"]["proxy_no_rescue_success_rate"] == 0.5
    assert published["deltas"]["unique_issues_attempted"] == 1


def test_resolve_available_published_scorecard_path_avoids_same_second_collision(
    tmp_path: Path,
) -> None:
    publish_dir = tmp_path / "published"
    published_scorecard = {
        "generated_at": "2026-04-14T15:16:17Z",
        "corpus": {"corpus_id": "tw-01-bounded-execution-v1", "revision": 3},
    }
    first_path = mod.resolve_published_scorecard_path(
        publish_dir=publish_dir,
        published_scorecard=published_scorecard,
    )
    first_path.parent.mkdir(parents=True)
    first_path.write_text("{}", encoding="utf-8")

    reserved_path = mod.resolve_available_published_scorecard_path(
        publish_dir=publish_dir,
        published_scorecard=published_scorecard,
    )

    assert reserved_path.name == "scorecard-20260414T151617Z-2.json"


def test_resolve_latest_scorecard_paths_use_corpus_and_revision_roots() -> None:
    paths = mod.resolve_latest_scorecard_paths(
        publish_dir=Path("/tmp/published"),
        published_scorecard={
            "generated_at": "2026-04-14T15:16:17Z",
            "corpus": {"corpus_id": "tw-01-bounded-execution-v1", "revision": 3},
        },
    )

    assert paths == {
        "corpus_latest": Path("/tmp/published/tw-01-bounded-execution-v1/latest.json"),
        "revision_latest": Path("/tmp/published/tw-01-bounded-execution-v1/rev-3/latest.json"),
    }


def test_main_publish_dir_writes_timestamped_artifact_and_prints_path(
    tmp_path: Path, capsys
) -> None:
    metrics_path = _write_metrics(
        tmp_path / "boss_metrics.jsonl",
        [{"issue_number": 1001, "terminal_class": "deliverable_pr_created"}],
    )
    truth_artifact_path = _write_json(
        tmp_path / "truth-artifact.json",
        {
            "generated_at": "2026-04-14T14:00:00Z",
            "corpus": {
                "path": "docs/benchmarks/corpus.json",
                "corpus_id": "tw-01-bounded-execution-v1",
                "revision": 4,
                "recorded_on": "2026-04-14",
                "success_contract": "mergeable_pr_or_merged_pr",
                "manifest_sha256": "abc123",
                "membership_sha256": "def456",
                "membership_issue_numbers": [1001],
                "issue_count": 1,
            },
            "primary_metrics": {"truth_success_rate": 1.0},
            "coverage": {"is_complete": True},
            "failure_class_distribution": {},
            "rescue_counts_by_type": {},
        },
    )

    exit_code = mod.main(
        [
            "--metrics",
            str(metrics_path),
            "--publish-dir",
            str(tmp_path / "published"),
            "--truth-artifact",
            str(truth_artifact_path),
        ]
    )

    captured = capsys.readouterr()
    written_path = Path(captured.out.strip())
    assert exit_code == 0
    assert written_path.parent == tmp_path / "published" / "tw-01-bounded-execution-v1" / "rev-4"
    payload = json.loads(written_path.read_text(encoding="utf-8"))
    assert payload["truth_artifact_path"] == str(truth_artifact_path)
    assert payload["proxy_metrics"]["no_rescue_success_rate"] == 1.0
    assert (
        json.loads(
            (tmp_path / "published" / "tw-01-bounded-execution-v1" / "latest.json").read_text(
                encoding="utf-8"
            )
        )["proxy_metrics"]["no_rescue_success_rate"]
        == 1.0
    )
    assert json.loads(
        (tmp_path / "published" / "tw-01-bounded-execution-v1" / "rev-4" / "latest.json").read_text(
            encoding="utf-8"
        )
    )["truth_artifact_path"] == str(truth_artifact_path)
    assert captured.err == ""


def test_main_publish_dir_with_json_keeps_stdout_json_and_reports_path_on_stderr(
    tmp_path: Path, capsys
) -> None:
    metrics_path = _write_metrics(
        tmp_path / "boss_metrics.jsonl",
        [{"issue_number": 1001, "terminal_class": "deliverable_pr_created"}],
    )
    truth_artifact_path = _write_json(
        tmp_path / "truth-artifact.json",
        {
            "generated_at": "2026-04-14T14:00:00Z",
            "corpus": {
                "path": "docs/benchmarks/corpus.json",
                "corpus_id": "tw-01-bounded-execution-v1",
                "revision": 5,
                "recorded_on": "2026-04-14",
                "success_contract": "mergeable_pr_or_merged_pr",
                "manifest_sha256": "abc123",
                "membership_sha256": "def456",
                "membership_issue_numbers": [1001],
                "issue_count": 1,
            },
            "primary_metrics": {"truth_success_rate": 1.0},
            "coverage": {"is_complete": True},
            "failure_class_distribution": {},
            "rescue_counts_by_type": {},
        },
    )

    exit_code = mod.main(
        [
            "--metrics",
            str(metrics_path),
            "--publish-dir",
            str(tmp_path / "published"),
            "--truth-artifact",
            str(truth_artifact_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    reported_path = Path(captured.err.strip())
    assert exit_code == 0
    assert payload["corpus"]["revision"] == 5
    assert payload["proxy_metrics"]["unique_issues_attempted"] == 1
    assert (
        json.loads(
            (tmp_path / "published" / "tw-01-bounded-execution-v1" / "latest.json").read_text(
                encoding="utf-8"
            )
        )["corpus"]["revision"]
        == 5
    )
    assert reported_path.parent == tmp_path / "published" / "tw-01-bounded-execution-v1" / "rev-5"


def test_main_json_with_corpus_filters_metrics_and_reports_coverage(tmp_path: Path, capsys) -> None:
    metrics_path = _write_metrics(
        tmp_path / "boss_metrics.jsonl",
        [
            {"issue_number": 1001, "terminal_class": "deliverable_pr_created"},
            {"issue_number": 2002, "terminal_class": "rescue_worker_crash"},
        ],
    )
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 7,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [
                {"issue_id": 1001, "title": "Issue A"},
                {"issue_id": 1003, "title": "Issue B"},
            ],
        },
    )

    exit_code = mod.main(["--metrics", str(metrics_path), "--corpus", str(corpus_path), "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["unique_issues_attempted"] == 1
    assert payload["unique_issues_succeeded"] == 1
    assert payload["unique_issues_failed"] == 0
    assert payload["no_rescue_success_rate"] == 1.0
    assert payload["corpus"]["revision"] == 7
    assert payload["coverage"]["missing_issue_numbers"] == [1003]
    assert payload["coverage"]["status"] == "incomplete"


def test_main_publish_fail_incomplete_honors_complete_truth_artifact(
    tmp_path: Path, capsys
) -> None:
    metrics_path = _write_metrics(
        tmp_path / "boss_metrics.jsonl",
        [{"issue_number": 1001, "terminal_class": "deliverable_pr_created"}],
    )
    truth_artifact_path = _write_json(
        tmp_path / "truth-artifact.json",
        {
            "generated_at": "2026-04-14T14:00:00Z",
            "corpus": {
                "path": "docs/benchmarks/corpus.json",
                "corpus_id": "tw-01-bounded-execution-v1",
                "revision": 4,
                "recorded_on": "2026-04-14",
                "success_contract": "mergeable_pr_or_merged_pr",
                "manifest_sha256": "abc123",
                "membership_sha256": "def456",
                "membership_issue_numbers": [1001, 1002],
                "issue_count": 2,
            },
            "issues": [{"issue_number": 1001}, {"issue_number": 1002}],
            "primary_metrics": {"truth_success_rate": 0.5},
            "coverage": {"is_complete": True, "missing_issue_numbers": [], "status": "complete"},
            "failure_class_distribution": {},
            "rescue_counts_by_type": {},
        },
    )

    exit_code = mod.main(
        [
            "--metrics",
            str(metrics_path),
            "--publish-dir",
            str(tmp_path / "published"),
            "--truth-artifact",
            str(truth_artifact_path),
            "--json",
            "--fail-incomplete",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["coverage"]["is_complete"] is True
    assert payload["proxy_metrics"]["coverage"]["is_complete"] is False
    assert payload["proxy_metrics"]["coverage"]["missing_issue_numbers"] == [1002]
    assert (tmp_path / "published" / "tw-01-bounded-execution-v1" / "rev-4").exists()


def test_main_publish_mode_uses_default_corpus_to_build_truth_artifact(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    metrics_path = _write_metrics(
        tmp_path / "boss_metrics.jsonl",
        [
            {"issue_number": 1001, "terminal_class": "deliverable_pr_created"},
            {"issue_number": 2002, "terminal_class": "rescue_worker_crash"},
        ],
    )
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 3,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1001, "title": "Issue A"}],
        },
    )
    truth_artifact_path = tmp_path / "truth-artifacts" / "truth-20260414T150000Z.json"

    def _fake_auto_publish_truth_artifact(**_: object) -> tuple[Path, dict[str, object]]:
        payload = {
            "generated_at": "2026-04-14T15:00:00Z",
            "corpus": {
                "path": "docs/benchmarks/corpus.json",
                "corpus_id": "tw-01-bounded-execution-v1",
                "revision": 3,
                "recorded_on": "2026-04-14",
                "success_contract": "mergeable_pr_or_merged_pr",
                "issue_count": 1,
            },
            "primary_metrics": {"truth_success_rate": 1.0},
            "coverage": {"is_complete": True, "status": "complete", "missing_issue_numbers": []},
            "failure_class_distribution": {},
            "rescue_counts_by_type": {},
            "issues": [{"issue_number": 1001}],
        }
        truth_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        truth_artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (tmp_path / "truth-artifacts" / "tw-01-bounded-execution-v1").mkdir(
            parents=True, exist_ok=True
        )
        (tmp_path / "truth-artifacts" / "tw-01-bounded-execution-v1" / "latest.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        return truth_artifact_path, payload

    monkeypatch.setattr(mod, "DEFAULT_CORPUS_PATH", corpus_path)
    monkeypatch.setattr(mod, "auto_publish_truth_artifact", _fake_auto_publish_truth_artifact)

    exit_code = mod.main(
        [
            "--metrics",
            str(metrics_path),
            "--publish",
            "--publish-dir",
            str(tmp_path / "published"),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    reported_path = Path(captured.err.strip())
    assert exit_code == 0
    assert payload["corpus"]["revision"] == 3
    assert payload["proxy_metrics"]["unique_issues_attempted"] == 1
    assert payload["truth_artifact_path"] == str(truth_artifact_path)
    assert json.loads(
        (tmp_path / "published" / "tw-01-bounded-execution-v1" / "latest.json").read_text(
            encoding="utf-8"
        )
    )["truth_artifact_path"] == str(truth_artifact_path)
    assert (
        json.loads(
            (tmp_path / "truth-artifacts" / "tw-01-bounded-execution-v1" / "latest.json").read_text(
                encoding="utf-8"
            )
        )["generated_at"]
        == "2026-04-14T15:00:00Z"
    )
    assert reported_path.parent == tmp_path / "published" / "tw-01-bounded-execution-v1" / "rev-3"


def test_main_ci_fail_incomplete_fails_for_missing_corpus_issue(tmp_path: Path, capsys) -> None:
    metrics_path = _write_metrics(
        tmp_path / "boss_metrics.jsonl",
        [{"issue_number": 1001, "terminal_class": "deliverable_pr_created"}],
    )
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 1,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [
                {"issue_id": 1001, "title": "Issue A"},
                {"issue_id": 1002, "title": "Issue B"},
            ],
        },
    )

    exit_code = mod.main(
        [
            "--metrics",
            str(metrics_path),
            "--corpus",
            str(corpus_path),
            "--ci",
            "--threshold",
            "0.5",
            "--fail-incomplete",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "coverage_status=incomplete" in captured.out


def test_main_publish_fail_incomplete_does_not_write_scorecard_or_truth_artifact(
    tmp_path: Path, capsys
) -> None:
    metrics_path = _write_metrics(
        tmp_path / "boss_metrics.jsonl",
        [{"issue_number": 1001, "terminal_class": "deliverable_pr_created"}],
    )
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 1,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [
                {"issue_id": 1001, "title": "Issue A"},
                {"issue_id": 1002, "title": "Issue B"},
            ],
        },
    )

    exit_code = mod.main(
        [
            "--metrics",
            str(metrics_path),
            "--corpus",
            str(corpus_path),
            "--publish-dir",
            str(tmp_path / "published"),
            "--truth-publish-dir",
            str(tmp_path / "truth-published"),
            "--fail-incomplete",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "incomplete corpus coverage" in captured.err
    assert not (tmp_path / "published").exists()
    assert not (tmp_path / "truth-published").exists()


_OBSERVED_CORPUS = {
    "path": "docs/benchmarks/corpus.json",
    "corpus_id": "tw-01-bounded-execution-v1",
    "revision": 7,
    "recorded_on": "2026-08-19",
    "success_contract": "mergeable_pr_or_merged_pr",
    "membership_issue_numbers": [1001, 1002],
    "issue_count": 2,
}
_COMPLETE_STATUS = {
    "raw_inputs": "available",
    "elapsed_time": "measured",
    "rescue_history": "complete",
    "raw_input_replay": "unmeasured",
}
# Shape of the hand-disclosed 2026-09-04 rev-7 snapshot (#9980).
_SEP4_PREVIOUS = {
    "generated_at": "2026-09-04T13:28:39Z",
    "truth_metrics": {
        "truth_success_rate": 0.5,
        "no_rescue_truth_success_rate": 0.5,
        "merged_only_rate": 0.5,
    },
    "proxy_metrics": {"no_rescue_success_rate": 0.0, "unique_issues_attempted": 2},
    "observation_status": {
        "raw_inputs": "unavailable",
        "elapsed_time": "unmeasured",
        "rescue_history": "incomplete",
        "raw_input_replay": "unmeasured",
    },
    "observation_limits": {
        "non_authoritative_fields": [
            "proxy_metrics",
            "proxy_metrics.mean_elapsed_seconds",
            "proxy_metrics.median_elapsed_seconds",
            "failure_class_distribution",
            "rescue_counts_by_type",
            "truth_metrics.no_rescue_truth_success_rate",
        ]
    },
}


def _publish_observed(
    tmp_path: Path,
    *,
    rows: list[dict[str, object]] | None,
    truth_observation_status: dict[str, str] | None,
    previous: dict[str, object] | None = None,
) -> dict[str, object]:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    if rows is not None:
        _write_metrics(metrics_path, rows)
    truth_payload: dict[str, object] = {
        "generated_at": "2026-09-29T01:59:04Z",
        "corpus": dict(_OBSERVED_CORPUS),
        "primary_metrics": {
            "truth_success_rate": 0.5,
            "no_rescue_truth_success_rate": 0.5,
            "merged_only_rate": 0.5,
        },
        "coverage": {"is_complete": True, "missing_issue_numbers": []},
        "failure_class_distribution": {},
        "rescue_counts_by_type": {},
    }
    if truth_observation_status is not None:
        truth_payload["observation_status"] = truth_observation_status
    truth_artifact_path = _write_json(tmp_path / "truth-artifact.json", truth_payload)
    publish_dir = tmp_path / "published"
    if previous is not None:
        previous_dir = publish_dir / "tw-01-bounded-execution-v1" / "rev-7"
        previous_dir.mkdir(parents=True)
        _write_json(previous_dir / "scorecard-20260904T132839Z.json", previous)
    loaded = mod.load_metrics(metrics_path)
    return mod.build_published_scorecard(
        scorecard=mod.compute_scorecard(loaded),
        rows=loaded,
        metrics_path=metrics_path,
        truth_artifact_path=truth_artifact_path,
        publish_dir=publish_dir,
        generated_at="2026-09-29T01:59:14Z",
    )


def test_published_scorecard_discloses_placeholder_elapsed_and_inherited_rescue_gap(
    tmp_path: Path,
) -> None:
    # The recurrence placeholder rows behind the 2026-09-29 rev-7 publication.
    rows = [
        {
            "issue_number": 1001,
            "terminal_class": "issue_already_resolved",
            "dispatch_skip_reason": "no_work_orders",
            "elapsed_seconds": 0.0,
        },
        {
            "issue_number": 1002,
            "terminal_class": "blocked_not_dispatch_bounded",
            "dispatch_skip_reason": "needs_human_no_prompt",
            "elapsed_seconds": 0.0,
        },
    ]
    published = _publish_observed(
        tmp_path,
        rows=rows,
        truth_observation_status={**_COMPLETE_STATUS, "rescue_history": "incomplete"},
        previous=_SEP4_PREVIOUS,
    )

    assert published["observation_status"] == {
        "raw_inputs": "available",
        "elapsed_time": "unmeasured",
        "rescue_history": "incomplete",
        "raw_input_replay": "unmeasured",
    }
    assert published["proxy_metrics"]["mean_elapsed_seconds"] == 0.0
    limits = published["observation_limits"]
    assert limits["non_authoritative_fields"] == [
        *mod.ELAPSED_DEPENDENT_FIELDS,
        *mod.RESCUE_DEPENDENT_FIELDS,
        "deltas.no_rescue_truth_success_rate",
        "deltas.proxy_no_rescue_success_rate",
        # Current row counts are observed; the Sep 4 side of this delta is not.
        "deltas.unique_issues_attempted",
    ]
    assert "placeholders" in limits["reason"]
    assert "rescue history as `incomplete`" in limits["reason"]
    assert "previous snapshot" in limits["reason"]
    assert "zero-duration" in limits["value_semantics"]


def test_published_scorecard_with_measured_inputs_carries_no_limits(tmp_path: Path) -> None:
    rows = [
        {"issue_number": 1001, "terminal_class": "deliverable_pr_created", "elapsed_seconds": 90.0},
        {"issue_number": 1002, "terminal_class": "rescue_timeout", "elapsed_seconds": 30.0},
    ]
    published = _publish_observed(
        tmp_path,
        rows=rows,
        truth_observation_status=dict(_COMPLETE_STATUS),
        previous={**_SEP4_PREVIOUS, "observation_status": dict(_COMPLETE_STATUS)}
        | {"observation_limits": {"non_authoritative_fields": []}},
    )

    assert published["observation_status"] == _COMPLETE_STATUS
    assert "observation_limits" not in published
    assert published["proxy_metrics"]["mean_elapsed_seconds"] == 60.0


def test_published_scorecard_treats_legacy_truth_artifact_rescue_history_as_unknown(
    tmp_path: Path,
) -> None:
    rows = [
        {"issue_number": 1001, "terminal_class": "deliverable_pr_created", "elapsed_seconds": 90.0},
        # An executed attempt without a sample: the mean covers only 1001.
        {"issue_number": 1002, "terminal_class": "rescue_timeout"},
    ]
    published = _publish_observed(tmp_path, rows=rows, truth_observation_status=None)

    assert published["observation_status"]["elapsed_time"] == "incomplete"
    assert published["observation_status"]["rescue_history"] == "unknown"
    limits = published["observation_limits"]
    assert limits["non_authoritative_fields"] == [
        *mod.ELAPSED_DEPENDENT_FIELDS,
        *mod.RESCUE_DEPENDENT_FIELDS,
    ]
    assert "only part of the executed attempts" in limits["reason"]


def test_published_scorecard_without_metrics_file_marks_proxy_metrics_unavailable(
    tmp_path: Path,
) -> None:
    published = _publish_observed(
        tmp_path,
        rows=None,
        truth_observation_status=dict(_COMPLETE_STATUS),
    )

    assert published["observation_status"]["raw_inputs"] == "unavailable"
    assert published["observation_status"]["elapsed_time"] == "unmeasured"
    limits = published["observation_limits"]
    assert limits["non_authoritative_fields"][0] == "proxy_metrics"
    assert "could not be read" in limits["reason"]


def test_published_scorecard_demotes_deltas_against_a_legacy_previous_snapshot(
    tmp_path: Path,
) -> None:
    rows = [
        {"issue_number": 1001, "terminal_class": "deliverable_pr_created", "elapsed_seconds": 90.0},
        {"issue_number": 1002, "terminal_class": "rescue_timeout", "elapsed_seconds": 30.0},
    ]
    legacy_previous = {
        key: value
        for key, value in _SEP4_PREVIOUS.items()
        if key not in {"observation_status", "observation_limits"}
    }
    published = _publish_observed(
        tmp_path,
        rows=rows,
        truth_observation_status=dict(_COMPLETE_STATUS),
        previous=legacy_previous,
    )

    assert published["observation_status"] == _COMPLETE_STATUS
    assert published["observation_limits"]["non_authoritative_fields"] == [
        "deltas.no_rescue_truth_success_rate",
        "deltas.proxy_no_rescue_success_rate",
        "deltas.unique_issues_attempted",
    ]


def test_main_publish_writes_observation_markers_into_both_published_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Mirrors the workflow's "Publish tracked trust-loop surfaces" invocation.
    metrics_path = _write_metrics(
        tmp_path / "boss_metrics.jsonl",
        [
            {
                "issue_number": 1001,
                "terminal_class": "issue_already_resolved",
                "dispatch_skip_reason": "no_work_orders",
                "elapsed_seconds": 0.0,
            }
        ],
    )
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 7,
            "recorded_on": "2026-08-19",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1001, "title": "Issue A"}],
        },
    )

    class _FakeTruthClient:
        def get_issue(self, repo: str, number: int) -> dict[str, object]:
            return {"title": "Issue A", "comments": [], "closedByPullRequestsReferences": []}

        def get_pr(self, repo: str, number: int) -> dict[str, object]:
            raise AssertionError("no linked PRs expected")

        def get_cross_referenced_pr_numbers(self, repo: str, number: int) -> list[int]:
            return []

    monkeypatch.setattr(mod, "GitHubTruthClient", _FakeTruthClient)

    exit_code = mod.main(
        [
            "--metrics",
            str(metrics_path),
            "--corpus",
            str(corpus_path),
            "--publish",
            "--publish-dir",
            str(tmp_path / "scorecards"),
            "--truth-publish-dir",
            str(tmp_path / "truth"),
            "--freshness-map",
            str(tmp_path / "freshness.json"),
            "--rescue-ledger",
            str(tmp_path / "rescue_events.jsonl"),
            "--fail-incomplete",
        ]
    )

    assert exit_code == 0
    truth = json.loads(
        (tmp_path / "truth" / "tw-01-bounded-execution-v1" / "rev-7" / "latest.json").read_text(
            encoding="utf-8"
        )
    )
    scorecard = json.loads(
        (
            tmp_path / "scorecards" / "tw-01-bounded-execution-v1" / "rev-7" / "latest.json"
        ).read_text(encoding="utf-8")
    )
    assert truth["observation_status"]["rescue_history"] == "incomplete"
    assert truth["rescue_ledger"]["error_code"] == "rescue_ledger_missing"
    assert truth["observation_limits"]["issues_without_executed_attempt"] == [1001]
    assert scorecard["observation_status"] == {
        "raw_inputs": "available",
        "elapsed_time": "unmeasured",
        "rescue_history": "incomplete",
        "raw_input_replay": "unmeasured",
    }
    assert (
        "proxy_metrics.mean_elapsed_seconds"
        in (scorecard["observation_limits"]["non_authoritative_fields"])
    )
