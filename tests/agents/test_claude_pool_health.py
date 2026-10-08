"""Tests for the Claude pool verify-snapshot helpers."""

from __future__ import annotations

import json

import pytest

from aragora.agents import claude_pool_health as health
from aragora.agents.claude_pool_health import build_snapshot, classify_probe, is_healthy


def test_classify_real_output_is_ok():
    assert classify_probe("OK", returncode=0) == "ok"
    assert classify_probe("Here is your answer.\nLine two", returncode=0) == "ok"


def test_classify_401_is_expired():
    assert (
        classify_probe("Failed to authenticate. API Error: 401 Invalid authentication credentials")
        == "expired"
    )
    assert classify_probe("OAuth token has expired") == "expired"


def test_classify_missing_credentials_is_not_configured():
    assert classify_probe("No such file or directory: .credentials.json") == "not_configured"
    assert classify_probe("not logged in") == "not_configured"


def test_classify_timeout_and_empty_are_unauthenticated():
    assert classify_probe("", timed_out=True) == "unauthenticated"
    assert classify_probe("") == "unauthenticated"


def test_classify_nonzero_returncode_without_text_marker_is_expired():
    assert classify_probe("weird failure", returncode=2) == "expired"


def test_is_healthy_matches_routing_unhealthy_set():
    assert is_healthy("ok")
    for bad in ("expired", "not_configured", "unauthenticated", "logged_out"):
        assert not is_healthy(bad)


def test_build_snapshot_shape_and_counts():
    records = [
        {"name": "max-01", "email": "a@x", "state": "ok"},
        {"name": "max-02", "email": "b@x", "state": "ok"},
        {"name": "max-03", "email": "c@x", "state": "expired"},
    ]
    snap = build_snapshot(records, generated_at="2026-06-05T02:25:00Z")
    assert snap["generated_at"] == "2026-06-05T02:25:00Z"
    assert snap["total"] == 3
    assert snap["healthy"] == 2
    assert snap["profiles"][0] == {"name": "max-01", "email": "a@x", "state": "ok"}
    # The snapshot is consumable by review_routing._load_pool_health (name+state).
    states = {p["name"]: p["state"] for p in snap["profiles"]}
    assert states["max-03"] == "expired"


def test_build_snapshot_defaults_missing_state():
    snap = build_snapshot([{"name": "max-09"}], generated_at="x")
    assert snap["profiles"][0]["state"] == "unauthenticated"
    assert snap["healthy"] == 0


@pytest.mark.parametrize(
    ("text", "code", "timeout", "reason"),
    [
        ("You're out of usage credits", 0, False, "quota_exhausted"),
        ("API Error: 429 rate_limit_error", 0, False, "quota_exhausted"),
        ("Rate limit exceeded", 0, False, "quota_exhausted"),
        ("Insufficient credits", 0, False, "quota_exhausted"),
        (
            "Failed to authenticate. API Error: 401 OAuth access token has been revoked",
            0,
            False,
            "auth_revoked",
        ),
        ("OAuth token has expired", 0, False, "auth_expired"),
        ("API Error: 401 Invalid authentication credentials", 0, False, "auth_expired"),
        ("No such file or directory: .credentials.json", 0, False, "auth_missing"),
        ("not logged in", 0, False, "auth_missing"),
        ("OK", 0, True, "transport_timeout"),
        ("Request timed out", 0, False, "transport_timeout"),
        ("API Error: 503 Service unavailable", 0, False, "service_unavailable"),
        ("Overloaded", 0, False, "service_unavailable"),
        ("I cannot fulfill this request.", 0, False, "invalid_response"),
        ("I'm sorry, but I can't assist with that.", 0, False, "invalid_response"),
        ("Sorry, but I can’t comply.", 0, False, "invalid_response"),
        ("Internal server error", 0, False, "service_unavailable"),
        ('{"type":"result","is_error":', 0, False, "invalid_response"),
        ("", 0, False, "invalid_response"),
        ("weird failure", 2, False, "unknown_failure"),
        ("API Error: unrecognized provider failure", 0, False, "unknown_failure"),
        ("OK", 0, False, "ok"),
        ("The docs discuss 401 and quota exhaustion.", 0, False, "ok"),
    ],
)
def test_probe_reason_and_legacy_availability(text, code, timeout, reason):
    assert health.classify_probe_reason(text, returncode=code, timed_out=timeout) == reason
    assert is_healthy(classify_probe(text, returncode=code, timed_out=timeout)) == (reason == "ok")


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (
            {"type": "result", "is_error": True, "result": "You're out of usage credits"},
            "quota_exhausted",
        ),
        (
            {"type": "result", "is_error": True, "errors": ["OAuth access token has been revoked"]},
            "auth_revoked",
        ),
        ({"type": "result", "is_error": True, "result": "OK"}, "unknown_failure"),
        (
            {"type": "result", "is_error": False, "result": "OK", "errors": ["private failure"]},
            "unknown_failure",
        ),
        (
            {"type": "result", "is_error": False, "subtype": "error_during_execution"},
            "unknown_failure",
        ),
        ({"type": "result", "is_error": "false", "result": "OK"}, "invalid_response"),
        ({"type": "result", "is_error": False, "result": {}}, "invalid_response"),
        ({"type": "result", "is_error": False, "result": ""}, "invalid_response"),
        (
            {"type": "result", "is_error": False, "result": "API Error: 503 overloaded"},
            "service_unavailable",
        ),
        (
            {
                "type": "result",
                "is_error": False,
                "result": "The docs discuss 401 and quota exhaustion.",
            },
            "ok",
        ),
        ({"type": "error", "error": {"type": "rate_limit_error"}}, "quota_exhausted"),
        ({"error": "private failure"}, "unknown_failure"),
        ({"unexpected": "OK"}, "invalid_response"),
        ([], "invalid_response"),
    ],
)
def test_structured_probe_reason(payload, reason):
    text = json.dumps(payload)
    assert health.classify_probe_reason(text, returncode=0) == reason
    assert is_healthy(classify_probe(text, returncode=0)) == (reason == "ok")


@pytest.mark.parametrize(
    "reason", ["quota_exhausted", "auth_revoked", "unknown_failure", "SENSITIVE", None]
)
def test_conflicting_health_reason_cannot_advertise_success(reason):
    snap = build_snapshot(
        [{"name": "max-01", "state": "ok", "reason_code": reason}], generated_at="x"
    )
    assert snap["profiles"][0]["state"] in health.UNHEALTHY_STATES
    assert snap["healthy"] == 0
    assert "SENSITIVE" not in json.dumps(snap)


def test_failed_state_cannot_advertise_ok_reason():
    snap = build_snapshot(
        [{"name": "max-01", "state": "expired", "reason_code": "ok"}], generated_at="x"
    )
    assert snap["profiles"][0]["reason_code"] == "unknown_failure"
    assert snap["healthy"] == 0


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        (
            "Warning: update available\nAPI Error: 401 Invalid authentication credentials",
            "auth_expired",
        ),
        ("Warning: update available\nYou're out of usage credits", "quota_exhausted"),
        ("You have hit your usage limit", "quota_exhausted"),
        ("Invalid API key · Please run /login", "auth_expired"),
    ],
)
def test_provider_failure_after_preamble_is_unhealthy(text, reason):
    assert health.classify_probe_reason(text, returncode=0) == reason
    assert not is_healthy(classify_probe(text, returncode=0))


@pytest.mark.parametrize("ensure_ascii", [False, True])
@pytest.mark.parametrize("preamble", ["", "Warning: update available\n"])
def test_structured_unicode_quota_message(ensure_ascii, preamble):
    text = preamble + json.dumps(
        {"type": "result", "is_error": True, "result": "You’re out of usage credits"},
        ensure_ascii=ensure_ascii,
    )
    assert health.classify_probe_reason(text, returncode=0) == "quota_exhausted"
    assert not is_healthy(classify_probe(text, returncode=0))


@pytest.mark.parametrize(
    ("preamble", "payload", "reason"),
    [
        ("Warning: update available", '{"type":"result","is_error":false,"result":"OK"}', "ok"),
        (
            "API Error: 401 Invalid authentication credentials",
            '{"type":"result","is_error":false,"result":"OK"}',
            "auth_expired",
        ),
        ("Warning: update available", '{"type":"result","is_error":', "invalid_response"),
        (
            "Warning: update available",
            '{\n  "type": "result",\n  "is_error": true,\n  "result": "Insufficient credits"\n}',
            "quota_exhausted",
        ),
    ],
)
def test_preamble_and_structured_probe(preamble, payload, reason):
    text = preamble + "\n" + payload
    assert health.classify_probe_reason(text, returncode=0) == reason
    assert is_healthy(classify_probe(text, returncode=0)) == (reason == "ok")


def test_unknown_states_and_reason_metadata_fail_closed():
    for state in ("new_state", "quota_exhausted", "", None):
        assert not is_healthy(state)
        snap = build_snapshot([{"name": "max-01", "state": state}], generated_at="x")
        assert snap["profiles"][0]["state"] in health.UNHEALTHY_STATES
        assert snap["healthy"] == 0
    for reason in ("quota_exhausted", "auth_revoked", "secret-token-material", None, {}):
        snap = build_snapshot([{"state": "expired", "reason_code": reason}], generated_at="x")
        expected = reason if reason in ("quota_exhausted", "auth_revoked") else "unknown_failure"
        assert snap["profiles"][0]["reason_code"] == expected
