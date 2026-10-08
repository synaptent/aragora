from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import claude_pool_verify as verify


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (
            subprocess.CompletedProcess(
                [],
                0,
                "Using profile home: private\nCommand: private\nYou're out of usage credits",
                "",
            ),
            ("unauthenticated", "quota_exhausted"),
        ),
        (
            subprocess.CompletedProcess(
                [],
                0,
                "",
                "Failed to authenticate. API Error: 401 OAuth access token has been revoked",
            ),
            ("expired", "auth_revoked"),
        ),
        (
            subprocess.CompletedProcess(
                [], 0, '{"type":"result","is_error":true,"result":"private failure"}', ""
            ),
            ("unauthenticated", "unknown_failure"),
        ),
        (subprocess.CompletedProcess([], 2, "private failure", ""), ("expired", "unknown_failure")),
        (
            subprocess.TimeoutExpired("private command", 1, output=b"private output"),
            ("unauthenticated", "transport_timeout"),
        ),
        (OSError("private error"), ("expired", "unknown_failure")),
        (FileNotFoundError("private path"), ("not_configured", "auth_missing")),
        (subprocess.CompletedProcess([], 0, "OK", ""), ("ok", "ok")),
        (
            subprocess.CompletedProcess([], 0, "OK", "API Error: 429 rate limit"),
            ("unauthenticated", "quota_exhausted"),
        ),
        (subprocess.CompletedProcess([], 0, "OK", "Warning: update available"), ("ok", "ok")),
        (
            subprocess.CompletedProcess([], 2, "Starting...", "API Error: 401 token revoked"),
            ("expired", "auth_revoked"),
        ),
        (
            subprocess.CompletedProcess([], 0, "OK", '{"is_error":'),
            ("unauthenticated", "invalid_response"),
        ),
    ],
)
def test_single_probe_reason_and_legacy_helper(monkeypatch, outcome, expected):
    run = Mock(
        side_effect=[outcome] if isinstance(outcome, Exception) else None, return_value=outcome
    )
    monkeypatch.setattr(verify.subprocess, "run", run)
    assert verify._probe_with_reason(Path("unused"), "max-01", "hi", 1) == expected
    assert run.call_count == 1
    run.reset_mock(side_effect=True)
    if isinstance(outcome, Exception):
        run.side_effect = [outcome]
    assert verify._probe(Path("unused"), "max-01", "hi", 1) == expected[0]
    assert run.call_count == 1


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("You have hit your usage limit", ("unauthenticated", "quota_exhausted")),
        ("API Error: 401 Invalid authentication credentials", ("expired", "auth_expired")),
        (
            '{"type":"result","is_error":true,"result":"You’re out of usage credits"}',
            ("unauthenticated", "quota_exhausted"),
        ),
    ],
)
def test_probe_failure_after_warning_and_wrapper_preamble(monkeypatch, stream, text, expected):
    preamble = "Using profile home: private\nCommand: private\n"
    failure = f"Warning: update available\n{text}"
    stdout = preamble + (failure if stream == "stdout" else "OK")
    stderr = failure if stream == "stderr" else ""
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout, stderr))
    monkeypatch.setattr(verify.subprocess, "run", run)
    assert verify._probe_with_reason(Path("unused"), "max-01", "hi", 1) == expected
    assert run.call_count == 1


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize(
    ("text", "reason", "label"),
    [
        ("You're out of usage credits: private-token", "quota_exhausted", "Quota exhausted:"),
        (
            "Failed to authenticate. API Error: 401 OAuth access token has been revoked: private-token",
            "auth_revoked",
            "Re-auth needed:",
        ),
    ],
)
def test_main_reason_metadata_without_raw_output(
    monkeypatch, tmp_path, capsys, as_json, text, reason, label
):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, text, ""))
    monkeypatch.setattr(verify.subprocess, "run", run)
    monkeypatch.setattr(verify, "_profile_email", lambda *args: "")
    path = tmp_path / "snapshot.json"
    argv = ["--snapshot-path", str(path), "max-01"] + (["--json"] if as_json else [])
    assert verify.main(argv) == 1
    output = capsys.readouterr().out
    snapshot = json.loads(path.read_text())
    assert snapshot["profiles"][0]["reason_code"] == reason
    assert "private-token" not in output + path.read_text()
    assert run.call_count == 1
    if as_json:
        assert json.loads(output) == snapshot
    else:
        assert label in output
        if reason == "quota_exhausted":
            assert "Re-auth needed:" not in output
