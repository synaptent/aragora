"""Focused tests for the incremental ACE fleet-playbook curator."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ace_curator.py"
SPEC = importlib.util.spec_from_file_location("ace_curator_under_test", SCRIPT)
assert SPEC and SPEC.loader
ace_curator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ace_curator
SPEC.loader.exec_module(ace_curator)


def source(identifier: str, text: str = "bounded failure evidence"):
    return ace_curator.SourceEntry(identifier, "fixture.jsonl", 1, text)


def test_first_run_adds_traceable_stable_lessons() -> None:
    sources = [source("SRC-A"), source("SRC-B")]
    decisions = [
        {
            "action": "add",
            "stable_key": "exact-head-before-settlement",
            "lesson": "Recheck the exact PR head before settlement.",
            "reason": "Repeated head drift invalidated earlier gate evidence.",
            "source_ids": ["SRC-A", "SRC-B"],
        }
    ]

    result = ace_curator.apply_decisions([], sources, decisions, now="2026-07-11T00:00:00Z")

    assert result.added == 1
    assert result.updated == 0
    assert result.lessons[0].id == ace_curator.lesson_id("exact-head-before-settlement")
    assert result.lessons[0].sources == (
        "SRC-A@fixture.jsonl:1",
        "SRC-B@fixture.jsonl:1",
    )
    rendered = ace_curator.render_playbook(result.lessons)
    assert "Recheck the exact PR head" in rendered
    assert '"sources": ["SRC-A@fixture.jsonl:1", "SRC-B@fixture.jsonl:1"]' in rendered


def test_second_run_updates_in_place_and_appends_without_reordering() -> None:
    first = ace_curator.apply_decisions(
        [],
        [source("SRC-A")],
        [
            {
                "action": "add",
                "stable_key": "exact-head",
                "lesson": "Check the exact head.",
                "reason": "Initial reflection.",
                "source_ids": ["SRC-A"],
            }
        ],
        now="2026-07-11T00:00:00Z",
    )
    original_id = first.lessons[0].id
    second = ace_curator.apply_decisions(
        first.lessons,
        [source("SRC-B"), source("SRC-C")],
        [
            {
                "action": "update",
                "target_id": original_id,
                "lesson": "Check the exact head before every irreversible action.",
                "reason": "A second incident broadened the lesson.",
                "source_ids": ["SRC-B"],
            },
            {
                "action": "add",
                "stable_key": "bounded-polling",
                "lesson": "Bound polling to the watched surface's change rate.",
                "reason": "Repeated polling produced no new evidence.",
                "source_ids": ["SRC-C"],
            },
        ],
        now="2026-07-12T00:00:00Z",
    )

    assert second.updated == 1
    assert second.added == 1
    assert [item.id for item in second.lessons][0] == original_id
    assert second.lessons[0].sources == (
        "SRC-A@fixture.jsonl:1",
        "SRC-B@fixture.jsonl:1",
    )
    assert second.lessons[1].id == ace_curator.lesson_id("bounded-polling")


def test_semantic_dedupe_is_idempotent_when_model_targets_existing_lesson() -> None:
    existing = ace_curator.Lesson(
        id=ace_curator.lesson_id("owner-check"),
        stable_key="owner-check",
        lesson="Check live ownership before mutation.",
        sources=("SRC-A@fixture.jsonl:1",),
        change_reason="Initial lesson.",
        updated_at="2026-07-11T00:00:00Z",
    )
    decision = {
        "action": "update",
        "target_id": existing.id,
        "lesson": existing.lesson,
        "reason": "Semantically equivalent evidence.",
        "source_ids": ["SRC-A"],
    }

    result = ace_curator.apply_decisions(
        [existing], [source("SRC-A")], [decision], now="2026-07-12T00:00:00Z"
    )

    assert result.unchanged == 1
    assert result.updated == 0
    assert result.lessons == (existing,)


def test_edit_requires_reason_and_known_traceable_sources() -> None:
    with pytest.raises(ValueError, match="lesson and reason"):
        ace_curator.apply_decisions(
            [],
            [source("SRC-A")],
            [
                {
                    "action": "add",
                    "stable_key": "missing-reason",
                    "lesson": "Do something.",
                    "source_ids": ["SRC-A"],
                }
            ],
        )
    with pytest.raises(ValueError, match="unknown source"):
        ace_curator.apply_decisions(
            [],
            [source("SRC-A")],
            [
                {
                    "action": "add",
                    "stable_key": "unknown-source",
                    "lesson": "Do something.",
                    "reason": "Grounded elsewhere.",
                    "source_ids": ["SRC-UNKNOWN"],
                }
            ],
        )


def test_collection_redacts_secrets_and_leaves_input_unchanged(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    original = (
        json.dumps(
            {
                "summary": "provider failed",
                "failure_detail": "OPENAI_API_KEY=sk-supersecretvalue",
            }
        )
        + "\n"
    )
    ledger.write_text(original, encoding="utf-8")

    entries = ace_curator.collect_sources([ledger], max_sources=10)

    assert ledger.read_text(encoding="utf-8") == original
    assert len(entries) == 1
    assert "supersecretvalue" not in entries[0].text
    assert "[REDACTED_SECRET]" in entries[0].text


@pytest.mark.parametrize(
    "secret",
    [
        '"password": "quoted-json-secret"',
        '"api_key": "quoted-json-key"',
        "'token': 'quoted-python-token'",
    ],
)
def test_redact_matches_quoted_generic_secret_keys(secret: str) -> None:
    redacted = ace_curator.redact(secret)

    assert "quoted-" not in redacted
    assert "[REDACTED_SECRET]" in redacted


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        (
            "AWS_SECRET_ACCESS_KEY=abcdefghijklmnopqrstuvwxyz1234567890ABCD",
            "abcdefghijklmnopqrstuvwxyz1234567890ABCD",
        ),
        (
            "github_pat_11AA22bb33CC44dd55EE66ff77GG88hh99II00jj",
            "github_pat_11AA22bb33CC44dd55EE66ff77GG88hh99II00jj",
        ),
        (
            "Authorization: Bearer opaqueAccessTokenValue1234567890",
            "opaqueAccessTokenValue1234567890",
        ),
        (
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signatureValue123",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signatureValue123",
        ),
        ("openaiApiKey=camelCaseSecretValue", "camelCaseSecretValue"),
        ("client-secret: hyphenatedSecretValue", "hyphenatedSecretValue"),
        ("awsSecretAccessKey=camelCaseAwsSecret", "camelCaseAwsSecret"),
    ],
)
def test_redact_covers_model_boundary_credential_forms(text: str, secret: str) -> None:
    redacted = ace_curator.redact(text)

    assert secret not in redacted
    assert "[REDACTED_SECRET]" in redacted


@pytest.mark.parametrize(
    "text",
    [
        "The token budget is 4096 and secret handling is documented.",
        "Bearer responsibilities remain with the operator.",
        "Rotate the api-key on the documented schedule.",
        "monkey=value keyboard=mechanical not-secret-note=public",
    ],
)
def test_redact_preserves_ordinary_prose_and_credential_lookalikes(text: str) -> None:
    assert ace_curator.redact(text) == text


def test_collection_applies_source_limit_after_deduplication(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl"
    first.write_text(
        "\n".join(
            [
                json.dumps({"summary": "duplicate lesson"}),
                json.dumps({"summary": "duplicate lesson"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    second = tmp_path / "second.jsonl"
    second.write_text(json.dumps({"summary": "unique lesson"}) + "\n", encoding="utf-8")

    entries = ace_curator.collect_sources([first, second], max_sources=2)

    assert [entry.text for entry in entries] == [
        "summary: duplicate lesson",
        "summary: unique lesson",
    ]


@pytest.mark.parametrize("suffix", [".json", ".jsonl", ".md", ".markdown", ".JSON"])
def test_collection_accepts_only_documented_input_types(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"evidence{suffix}"
    if suffix.lower() == ".json":
        path.write_text(json.dumps({"summary": "bounded evidence"}), encoding="utf-8")
    elif suffix.lower() == ".jsonl":
        path.write_text(json.dumps({"summary": "bounded evidence"}) + "\n", encoding="utf-8")
    else:
        path.write_text("bounded evidence\n", encoding="utf-8")

    entries = ace_curator.collect_sources([path], max_sources=10)
    expected = (
        ["summary: bounded evidence"]
        if suffix.lower() in {".json", ".jsonl"}
        else ["bounded evidence"]
    )

    assert [entry.text for entry in entries] == expected


def test_collection_rejects_unsupported_suffix_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".env"
    path.write_text("OPENAI_API_KEY=secret\n", encoding="utf-8")

    def fail_read(*args, **kwargs):
        raise AssertionError("unsupported input must not be read")

    monkeypatch.setattr(Path, "read_text", fail_read)

    with pytest.raises(ValueError, match="unsupported input suffix"):
        ace_curator.collect_sources([path], max_sources=10)


def test_playbook_round_trip_and_noop_write(tmp_path: Path) -> None:
    lesson = ace_curator.Lesson(
        id=ace_curator.lesson_id("stable"),
        stable_key="stable",
        lesson="Keep stable lessons stable.",
        sources=("SRC-A@fixture.jsonl:1",),
        change_reason="Fixture.",
        updated_at="2026-07-11T00:00:00Z",
    )
    path = tmp_path / "playbook.md"
    rendered = ace_curator.render_playbook([lesson])

    assert ace_curator.write_playbook(path, rendered) is True
    assert ace_curator.load_playbook(path) == [lesson]
    assert ace_curator.write_playbook(path, rendered) is False


def test_model_text_cannot_inject_playbook_markers_or_secret_stable_keys(tmp_path: Path) -> None:
    result = ace_curator.apply_decisions(
        [],
        [source("SRC-A")],
        [
            {
                "action": "add",
                "stable_key": "API_KEY=stableSecret ACE-CURATOR:LESSON",
                "lesson": "Never emit ACE-CURATOR:END from model text.",
                "reason": "ACE-CURATOR:LESSON would corrupt the next parse.",
                "source_ids": ["SRC-A"],
            }
        ],
        now="2026-07-22T00:00:00Z",
    )
    path = tmp_path / "playbook.md"
    rendered = ace_curator.render_playbook(result.lessons)

    assert "stableSecret" not in rendered
    assert rendered.count("ACE-CURATOR:LESSON") == 1
    assert rendered.count("ACE-CURATOR:END") == 1
    assert ace_curator.write_playbook(path, rendered)
    assert ace_curator.load_playbook(path) == list(result.lessons)


def test_playbook_rejects_malformed_block_after_valid_block(tmp_path: Path) -> None:
    lesson = ace_curator.Lesson(
        id=ace_curator.lesson_id("stable"),
        stable_key="stable",
        lesson="Keep stable lessons stable.",
        sources=("SRC-A@fixture.jsonl:1",),
        change_reason="Fixture.",
        updated_at="2026-07-11T00:00:00Z",
    )
    path = tmp_path / "playbook.md"
    path.write_text(
        ace_curator.render_playbook([lesson])
        + "\n<!-- ACE-CURATOR:LESSON\n{}\n-->\n- malformed block\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="malformed ACE curator block"):
        ace_curator.load_playbook(path)


def test_write_playbook_disables_platform_newline_translation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_fdopen = ace_curator.os.fdopen
    observed: dict[str, object] = {}

    def recording_fdopen(fd: int, mode: str, **kwargs):
        observed.update(kwargs)
        return real_fdopen(fd, mode, **kwargs)

    monkeypatch.setattr(ace_curator.os, "fdopen", recording_fdopen)

    assert ace_curator.write_playbook(tmp_path / "playbook.md", "line one\nline two\n")
    assert observed["newline"] == "\n"


def test_cli_uses_offline_model_decisions_without_live_api(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps({"summary": "owner collision repeated", "blocker_class": "owner"}) + "\n",
        encoding="utf-8",
    )
    entries = ace_curator.collect_sources([ledger], max_sources=10)
    decisions = tmp_path / "decisions.json"
    decisions.write_text(
        json.dumps(
            {
                "decisions": [
                    {
                        "action": "add",
                        "stable_key": "owner-collision",
                        "lesson": "Check object ownership before mutation.",
                        "reason": "Fixture reflection.",
                        "source_ids": [entries[0].id],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "playbook.md"

    rc = ace_curator.main(
        [
            "--input",
            str(ledger),
            "--output",
            str(output),
            "--decisions-json",
            str(decisions),
            "--json",
        ]
    )

    assert rc == 0
    assert "Check object ownership" in output.read_text(encoding="utf-8")


def test_cli_refuses_to_overwrite_an_input(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    original = json.dumps({"summary": "do not overwrite me"}) + "\n"
    ledger.write_text(original, encoding="utf-8")
    decisions = tmp_path / "decisions.json"
    decisions.write_text('{"decisions": []}\n', encoding="utf-8")

    rc = ace_curator.main(
        [
            "--input",
            str(ledger),
            "--output",
            str(ledger),
            "--decisions-json",
            str(decisions),
        ]
    )

    assert rc == 2
    assert ledger.read_text(encoding="utf-8") == original


def test_cli_refuses_to_overwrite_decisions_fixture(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"summary": "preserve decisions"}) + "\n", encoding="utf-8")
    decisions = tmp_path / "decisions.json"
    original = '{"decisions": []}\n'
    decisions.write_text(original, encoding="utf-8")

    rc = ace_curator.main(
        [
            "--input",
            str(ledger),
            "--output",
            str(decisions),
            "--decisions-json",
            str(decisions),
        ]
    )

    assert rc == 2
    assert decisions.read_text(encoding="utf-8") == original


def test_cli_reports_model_timeout_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"summary": "bounded evidence"}) + "\n", encoding="utf-8")

    def time_out(*args, **kwargs):
        raise subprocess.TimeoutExpired("consult", 1)

    monkeypatch.setattr(ace_curator, "consult_model", time_out)

    rc = ace_curator.main(["--input", str(ledger), "--output", str(tmp_path / "playbook.md")])

    assert rc == 2
    assert "timed out" in capsys.readouterr().err
