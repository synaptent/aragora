"""Pin the move of the reporter's field and text helpers into ``aragora.swarm.reporter_fields``."""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone

import pytest

from aragora.swarm import reporter, reporter_fields

MOVED_NAMES = [
    "_PLACEHOLDER_BLOCKERS",
    "_CLI_TRANSCRIPT_MARKERS",
    "_SENSITIVE_OUTPUT_MARKERS",
    "_parse_iso_timestamp",
    "_age_seconds",
    "_seconds_between",
    "_text",
    "_metadata",
    "_first_text",
    "_text_list",
    "_blocker_list",
    "_normalize_blocker_text",
    "_first_list",
    "_first_dict_list",
    "_compact_text",
    "_single_line_text",
    "_cli_transcript_placeholder",
    "_looks_like_sensitive_cli_output",
    "_sanitize_boss_evidence_text",
    "_optional_int",
    "_repair_journal_entries",
    "_latest_repair_summary",
    "_render_repair_summary",
]


@pytest.mark.parametrize("name", MOVED_NAMES)
def test_moved_names_are_reexported_from_the_reporter(name: str) -> None:
    moved = getattr(reporter_fields, name)
    assert getattr(reporter, name) is moved
    if callable(moved):
        assert moved.__module__ == "aragora.swarm.reporter_fields"


def test_fields_module_does_not_import_the_reporter() -> None:
    tree = ast.parse(inspect.getsource(reporter_fields))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not any(
        name.startswith("aragora.swarm.reporter")
        for name in imported - {"aragora.swarm.reporter_fields"}
    )


def test_timestamps_are_normalized_to_utc() -> None:
    parsed = reporter._parse_iso_timestamp("2026-03-18T12:00:00")
    assert parsed == datetime(2026, 3, 18, 12, 0, tzinfo=timezone.utc)
    assert reporter._parse_iso_timestamp("not a time") is None


def test_boss_evidence_redacts_cli_transcripts_and_secrets() -> None:
    transcript = "OpenAI Codex v1.2\nworkdir: /tmp/x\napproval: never"
    secret = "request failed: Authorization: Bearer abc123"
    for text in (transcript, secret):
        assert reporter._sanitize_boss_evidence_text(text) == "worker_cli_transcript_captured"
    assert reporter._sanitize_boss_evidence_text("plain failure") == "plain failure"


def test_repair_summary_renders_the_latest_journal_entry() -> None:
    task = {
        "metadata": {
            "repair_journal": [
                {"failure_reason": "old"},
                {
                    "failure_reason": "tests_failed",
                    "exit_code": "1",
                    "failing_verification": {"command": "pytest -q", "exit_code": 2},
                },
            ]
        }
    }
    summary = reporter._latest_repair_summary(task)
    assert summary == {
        "failure_reason": "tests_failed",
        "exit_code": 1,
        "verification_command": "pytest -q",
        "verification_exit_code": 2,
    }
    assert reporter._render_repair_summary(summary) == (
        "reason=tests_failed; cmd=pytest -q; verify_exit=2; worker_exit=1"
    )
