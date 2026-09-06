from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from aragora.swarm.rescue_events import RescueEvent, RescueEventLedger

_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import publish_rescue_productization_report as mod  # noqa: E402


def _ledger_with_events(tmp_path: Path, events: list[RescueEvent]) -> RescueEventLedger:
    ledger = RescueEventLedger(path=tmp_path / "rescue_events.jsonl")
    for event in events:
        ledger.record(event)
    return ledger


def test_build_published_report_links_existing_issue_and_updates_map(
    tmp_path: Path, monkeypatch
) -> None:
    ledger = _ledger_with_events(
        tmp_path,
        [
            RescueEvent(
                event_type="followup_prompt",
                reason="needs explicit next step from founder",
                issue_number=5512,
            ),
            RescueEvent(
                event_type="followup_prompt",
                reason="needs explicit next step from founder",
                issue_number=5515,
            ),
        ],
    )
    productization_map_path = tmp_path / "rescue_productization.json"
    mod.write_productization_map_payload(
        productization_map_path,
        {
            "schema_version": 1,
            "entries": [],
        },
    )

    monkeypatch.setattr(
        mod,
        "find_existing_issue_by_title",
        lambda **_: {
            "number": 6001,
            "title": "[TW-03] Productize repeated rescue class: followup-prompt-needs-explicit-next-step-from-founder",
            "url": "https://github.com/synaptent/aragora/issues/6001",
            "state": "open",
        },
    )

    payload = mod.build_published_report(
        ledger_path=ledger.path,
        productization_map_path=productization_map_path,
        repo="synaptent/aragora",
        generated_at="2026-04-14T18:35:00Z",
        ensure_issues=True,
    )

    assert payload["ok"] is True
    assert payload["summary"]["linked_issue_count"] == 1
    assert payload["source"]["status"] == "available"
    assert payload["source"]["event_count"] == 2
    assert len(payload["source"]["sha256"]) == 64
    assert payload["issue_drafts"] == []
    assert payload["issue_linkage_results"] == [
        {
            "action": "linked_existing_issue",
            "class": "followup_prompt:needs explicit next step from founder",
            "target": "#6001",
            "target_kind": "issue",
            "url": "https://github.com/synaptent/aragora/issues/6001",
        }
    ]
    written_map = json.loads(productization_map_path.read_text(encoding="utf-8"))
    assert written_map["entries"] == [
        {
            "class": "followup_prompt:needs explicit next step from founder",
            "notes": "Auto-linked by recurring TW-03 harvest.",
            "target": "#6001",
            "target_kind": "issue",
            "title": "[TW-03] Productize repeated rescue class: followup-prompt-needs-explicit-next-step-from-founder",
        }
    ]


def test_publish_report_bundle_writes_timestamped_and_latest(tmp_path: Path) -> None:
    payload = {
        "generated_at": "2026-04-14T18:36:07Z",
        "summary": {"repeated_class_count": 0},
    }

    written = mod.publish_report_bundle(
        publish_dir=tmp_path / "published",
        payload=payload,
    )

    assert written["timestamped"] == (
        tmp_path / "published" / "rescue-productization-20260414T183607Z.json"
    )
    assert written["latest"] == tmp_path / "published" / "latest.json"
    assert json.loads(written["latest"].read_text(encoding="utf-8"))["generated_at"] == (
        "2026-04-14T18:36:07Z"
    )


@pytest.mark.parametrize("schema_version", [0, -1, True, "1"])
def test_load_productization_map_rejects_invalid_schema_version(
    tmp_path: Path,
    schema_version: object,
) -> None:
    productization_map_path = tmp_path / "rescue_productization.json"
    productization_map_path.write_text(
        json.dumps({"schema_version": schema_version, "entries": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="schema_version must be a positive integer"):
        mod.load_productization_map_payload(productization_map_path)


def test_write_productization_map_rejects_invalid_schema_version(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="schema_version must be a positive integer"):
        mod.write_productization_map_payload(
            tmp_path / "rescue_productization.json",
            {
                "schema_version": False,
                "entries": [
                    {
                        "class": "followup_prompt:needs explicit next step from founder",
                    }
                ],
            },
        )


@pytest.mark.parametrize(
    "entries",
    [
        {"class": "not-a-list"},
        [{"target": "#6001"}],
        ["followup_prompt:needs explicit next step from founder"],
    ],
)
def test_load_productization_map_rejects_invalid_entries(
    tmp_path: Path,
    entries: object,
) -> None:
    productization_map_path = tmp_path / "rescue_productization.json"
    productization_map_path.write_text(
        json.dumps({"schema_version": 1, "entries": entries}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="entries"):
        mod.load_productization_map_payload(productization_map_path)


def test_write_productization_map_rejects_invalid_entries(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-empty `class`"):
        mod.write_productization_map_payload(
            tmp_path / "rescue_productization.json",
            {
                "schema_version": 1,
                "entries": [
                    {
                        "target": "#6001",
                    }
                ],
            },
        )


def test_main_dry_run_does_not_publish_report_bundle(tmp_path: Path, capsys) -> None:
    ledger = _ledger_with_events(
        tmp_path,
        [
            RescueEvent(
                event_type="followup_prompt",
                reason="needs explicit next step from founder",
                issue_number=5512,
            ),
            RescueEvent(
                event_type="followup_prompt",
                reason="needs explicit next step from founder",
                issue_number=5515,
            ),
        ],
    )
    productization_map_path = tmp_path / "rescue_productization.json"
    mod.write_productization_map_payload(
        productization_map_path,
        {
            "schema_version": 1,
            "entries": [],
        },
    )
    publish_dir = tmp_path / "published"

    exit_code = mod.main(
        [
            "--path",
            str(ledger.path),
            "--productization-map",
            str(productization_map_path),
            "--publish-dir",
            str(publish_dir),
            "--repo",
            "synaptent/aragora",
            "--dry-run",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["repo"] == "synaptent/aragora"
    assert "generated_at" in payload
    assert payload["summary"]["repeated_class_count"] == 1
    assert not publish_dir.exists()


def test_main_missing_ledger_publishes_unavailable_source(tmp_path: Path, capsys) -> None:
    ledger_path = tmp_path / "missing" / "rescue_events.jsonl"
    productization_map_path = tmp_path / "rescue_productization.json"
    mod.write_productization_map_payload(
        productization_map_path,
        {"schema_version": 1, "entries": []},
    )
    publish_dir = tmp_path / "published"

    exit_code = mod.main(
        [
            "--path",
            str(ledger_path),
            "--productization-map",
            str(productization_map_path),
            "--publish-dir",
            str(publish_dir),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is False
    assert payload["source"]["status"] == "unavailable"
    assert payload["source"]["event_count"] is None
    assert payload["source"]["error"]["code"] == "rescue_ledger_missing"
    assert payload["source"]["error"]["path"] == mod._repo_stable_path(ledger_path)
    assert "[rescue_ledger_missing]" in captured.err
    assert json.loads((publish_dir / "latest.json").read_text(encoding="utf-8")) == payload


def test_main_require_source_fails_without_publishing(tmp_path: Path, capsys) -> None:
    ledger_path = tmp_path / "missing" / "rescue_events.jsonl"
    productization_map_path = tmp_path / "rescue_productization.json"
    mod.write_productization_map_payload(
        productization_map_path,
        {"schema_version": 1, "entries": []},
    )
    publish_dir = tmp_path / "published"

    exit_code = mod.main(
        [
            "--path",
            str(ledger_path),
            "--productization-map",
            str(productization_map_path),
            "--publish-dir",
            str(publish_dir),
            "--require-source",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 3
    assert payload["ok"] is False
    assert payload["error"]["code"] == "rescue_ledger_missing"
    assert "[rescue_ledger_missing]" in captured.err
    assert not publish_dir.exists()


def test_main_malformed_ledger_dry_run_reports_unavailable_source(tmp_path: Path, capsys) -> None:
    ledger_path = tmp_path / "rescue_events.jsonl"
    ledger_path.write_text('{"event_type":"manual_merge"}\n', encoding="utf-8")
    productization_map_path = tmp_path / "rescue_productization.json"
    mod.write_productization_map_payload(
        productization_map_path,
        {"schema_version": 1, "entries": []},
    )
    publish_dir = tmp_path / "published"

    exit_code = mod.main(
        [
            "--path",
            str(ledger_path),
            "--productization-map",
            str(productization_map_path),
            "--publish-dir",
            str(publish_dir),
            "--dry-run",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["source"]["status"] == "unavailable"
    assert payload["source"]["error"]["code"] == "rescue_ledger_malformed"
    assert "line 1" in payload["source"]["error"]["detail"]
    assert "[rescue_ledger_malformed]" in captured.err
    assert not publish_dir.exists()


def test_validator_tolerates_only_torn_trailing_append(tmp_path: Path) -> None:
    ledger_path = tmp_path / "rescue_events.jsonl"
    complete = json.dumps(
        {
            "event_type": "followup_prompt",
            "reason": "needs explicit next step",
        }
    )
    ledger_path.write_text(f'{complete}\n{{"event_type":"followup', encoding="utf-8")

    source = mod.validate_rescue_ledger(ledger_path)

    assert source["event_count"] == 1
    assert source["skipped_trailing_partial_line_count"] == 1


def test_validator_accepts_empty_string_event_fields_supported_by_data_model(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "rescue_events.jsonl"
    ledger_path.write_text('{"event_type":"","reason":""}\n', encoding="utf-8")

    source = mod.validate_rescue_ledger(ledger_path)

    assert source["event_count"] == 1


@pytest.mark.parametrize(
    "contents",
    [
        '{"event_type":"followup',
        '{"event_type":"followup\n',
        "not-json",
        'not-json\n{"event_type":"followup_prompt","reason":"ok"}\n',
    ],
)
def test_validator_rejects_non_trailing_or_complete_corruption(
    tmp_path: Path,
    contents: str,
) -> None:
    ledger_path = tmp_path / "rescue_events.jsonl"
    ledger_path.write_text(contents, encoding="utf-8")

    with pytest.raises(mod.RescueLedgerValidationError) as exc_info:
        mod.validate_rescue_ledger(ledger_path)

    assert exc_info.value.code == "rescue_ledger_malformed"


def test_validator_sanitizes_unreadable_path_detail(tmp_path: Path, monkeypatch) -> None:
    ledger_path = tmp_path / "rescue_events.jsonl"
    ledger_path.touch()

    def raise_permission_error(_path: Path) -> bytes:
        raise PermissionError(13, "Permission denied", str(ledger_path))

    monkeypatch.setattr(Path, "read_bytes", raise_permission_error)

    with pytest.raises(mod.RescueLedgerValidationError) as exc_info:
        mod.validate_rescue_ledger(ledger_path)

    assert exc_info.value.code == "rescue_ledger_unreadable"
    assert exc_info.value.detail.count(str(ledger_path)) == 1
    assert "Permission denied" in exc_info.value.detail


def test_report_uses_one_snapshot_when_source_appends_during_build(
    tmp_path: Path, monkeypatch
) -> None:
    ledger = _ledger_with_events(
        tmp_path,
        [
            RescueEvent(
                event_type="followup_prompt",
                reason="needs explicit next step",
            )
        ],
    )
    productization_map_path = tmp_path / "rescue_productization.json"
    mod.write_productization_map_payload(
        productization_map_path,
        {"schema_version": 1, "entries": []},
    )
    original_bytes = ledger.path.read_bytes()
    fixtures = mod._rescue_fixtures()
    real_load = fixtures.load_rescue_productization_report
    observed_snapshots: list[bytes] = []

    def append_source_during_load(**kwargs):
        snapshot_path = kwargs["ledger_path"]
        observed_snapshots.append(snapshot_path.read_bytes())
        if len(observed_snapshots) == 1:
            ledger.record(
                RescueEvent(
                    event_type="manual_merge",
                    reason="operator settlement",
                )
            )
        return real_load(**kwargs)

    monkeypatch.setattr(fixtures, "load_rescue_productization_report", append_source_during_load)

    payload = mod.build_published_report(
        ledger_path=ledger.path,
        productization_map_path=productization_map_path,
        repo="synaptent/aragora",
    )

    assert observed_snapshots == [original_bytes, original_bytes]
    assert ledger.path.read_bytes() != original_bytes
    assert payload["source"]["event_count"] == 1
    assert payload["source"]["sha256"] == mod.hashlib.sha256(original_bytes).hexdigest()


def test_existing_empty_ledger_is_a_valid_zero_observation(tmp_path: Path) -> None:
    ledger_path = tmp_path / "rescue_events.jsonl"
    ledger_path.touch()
    productization_map_path = tmp_path / "rescue_productization.json"
    mod.write_productization_map_payload(
        productization_map_path,
        {"schema_version": 1, "entries": []},
    )

    payload = mod.build_published_report(
        ledger_path=ledger_path,
        productization_map_path=productization_map_path,
        repo="synaptent/aragora",
        generated_at="2026-08-29T23:30:00Z",
    )

    assert payload["source"] == {
        "status": "available",
        "event_count": 0,
        "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "summary_event_limit": 500,
        "summary_truncated": False,
    }
    assert payload["summary"]["total_unique_classes"] == 0


def test_home_relative_path_collapses_home_rooted_path(monkeypatch, tmp_path):
    # Regression guard for the #7706/#7739 username leak: a $HOME-rooted path
    # written into the committed truth surface must serialize as ~-relative.
    monkeypatch.setenv("HOME", str(tmp_path))
    raw = str(tmp_path / ".aragora" / "rescue_events.jsonl")
    assert mod._home_relative_path(raw) == "~/.aragora/rescue_events.jsonl"


def test_home_relative_path_leaves_non_home_path_untouched(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert mod._home_relative_path("/etc/ci/rescue_events.jsonl") == "/etc/ci/rescue_events.jsonl"


def test_repo_stable_path_collapses_home_ledger_to_tilde(monkeypatch, tmp_path):
    # _repo_stable_path resolves the path first, so use a resolved HOME to keep
    # the assertion hermetic across platforms with symlinked temp dirs (macOS).
    home = tmp_path.resolve()
    monkeypatch.setenv("HOME", str(home))
    ledger = home / ".aragora" / "rescue_events.jsonl"
    result = mod._repo_stable_path(ledger)
    assert result == "~/.aragora/rescue_events.jsonl"
    assert not result.startswith("/")
    assert home.name not in result


def test_repo_stable_path_keeps_repo_relative_posix():
    target = mod.REPO_ROOT / "docs" / "benchmarks" / "rescue_productization.json"
    assert mod._repo_stable_path(target) == "docs/benchmarks/rescue_productization.json"
