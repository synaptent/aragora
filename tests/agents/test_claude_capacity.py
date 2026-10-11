"""Capacity observations are not evidence, execution health or admission grants."""

import json
from copy import deepcopy

import pytest

from aragora.agents import claude_capacity as capacity

NOW = 1_789_280_000.0
FUTURE = "2026-10-01T00:00:00+00:00"
ACCOUNT = "11111111-1111-1111-1111-111111111111"
ORG = "22222222-2222-2222-2222-222222222222"
OTHER = "33333333-3333-3333-3333-333333333333"
PROFILE = {
    "account": {"uuid": ACCOUNT, "email": "private@example.test"},
    "organization": {
        "uuid": ORG,
        "organization_type": "claude_max",
        "subscription_status": "active",
    },
}
USAGE = {
    "five_hour": {"utilization": 0, "resets_at": None},
    "seven_day": {"utilization": 53, "resets_at": FUTURE},
    "extra_usage": {"is_enabled": False, "disabled_reason": "out_of_credits"},
}


def credential(label="max-01", token="secret-token", cached=None):
    return capacity.Credential(label, token, NOW + 600, "loaded", cached)


def run(credentials=None, profile=None, usage=None, fetch=None, **kwargs):
    def fake(token, endpoint, timeout):
        return (profile or PROFILE) if endpoint == "profile" else (usage or USAGE)

    return capacity.collect(
        credentials or [credential()], fetch=fetch or fake, now=lambda: NOW, **kwargs
    )


def test_included_quota_is_independent_of_extra_credits_and_not_admission():
    report = run()
    row = report["observations"][0]
    assert row["quota_state"] == "available"
    assert row["windows"]["seven_day"]["remaining_percent"] == 47
    assert row["extra_usage_enabled"] is False
    assert row["expires_at"] == NOW + 300
    assert report["unique_identities_with_allowance"] == 1
    assert report["execution_verified"] is False
    assert report["admission_authorized"] is False
    assert report["countability_evaluated"] is False
    assert "Keychain" in report["coverage"]


@pytest.mark.parametrize("value", [True, "0", -1, 101, float("nan"), float("inf"), 10**400, {}])
def test_invalid_utilization_is_unknown(value):
    usage = deepcopy(USAGE)
    usage["five_hour"]["utilization"] = value
    assert capacity.summarize_usage(usage, NOW)["quota_state"] == "unknown"


@pytest.mark.parametrize("key", ["five_hour", "seven_day", "seven_day_opus"])
def test_any_exhausted_window_is_reported(key):
    usage = {**USAGE, key: {"utilization": 100, "resets_at": FUTURE}}
    assert capacity.summarize_usage(usage, NOW)["quota_state"] == "restricted"


@pytest.mark.parametrize(
    "window",
    [
        None,
        [],
        {},
        {"utilization": 5},
        {"utilization": 0, "resets_at": "yesterday"},
        {"utilization": 2, "resets_at": "2020-01-01T00:00:00Z"},
        {"utilization": 0, "locked_reason": "secret"},
    ],
)
def test_unknown_or_stale_window_never_reports_available(window):
    assert capacity.summarize_usage({**USAGE, "five_hour": window}, NOW)["quota_state"] == "unknown"


def test_null_optional_window_is_not_a_failure():
    assert (
        capacity.summarize_usage({**USAGE, "seven_day_opus": None}, NOW)["quota_state"]
        == "available"
    )


def test_deduplicates_file_tokens_without_exposing_token_or_identity():
    calls = []

    def fake(token, endpoint, timeout):
        calls.append(endpoint)
        return PROFILE if endpoint == "profile" else USAGE

    report = run([credential(), credential("vibeproxy:123")], fetch=fake)
    assert calls == ["profile", "usage"]
    assert len(report["observations"]) == 2
    text = json.dumps(report)
    for private in ["secret-token", ACCOUNT, ORG, "private@example.test"]:
        assert private not in text
    assert "secret-token" not in repr(credential())


def test_cached_identity_mismatch_is_not_silently_corrected():
    report = run([credential(cached=(ACCOUNT, OTHER))])
    assert report["observations"][0]["cached_identity"] == "mismatch"
    assert report["execution_verified"] is False


def test_distinguishes_accounts_within_one_org_and_orgs_within_one_account():
    def fake(token, endpoint, timeout):
        if endpoint == "usage":
            return USAGE
        profile = deepcopy(PROFILE)
        if token == "different-user":
            profile["account"]["uuid"] = OTHER
        if token == "different-org":
            profile["organization"]["uuid"] = OTHER
        return profile

    report = run(
        [
            credential(),
            credential("max-02", "different-user"),
            credential("max-03", "different-org"),
            credential("max-04", "same-identity-new-token"),
        ],
        fetch=fake,
    )
    assert report["unique_identities_with_allowance"] == 3


@pytest.mark.parametrize(
    "profile",
    [
        {"account": {}},
        {"account": [], "organization": PROFILE["organization"]},
        {"account": PROFILE["account"], "organization": {"uuid": "not-a-uuid"}},
    ],
)
def test_unknown_identity_stops_before_usage(profile):
    calls = []

    def fake(token, endpoint, timeout):
        calls.append(endpoint)
        return profile

    row = run(fetch=fake)["observations"][0]
    assert row["state"] == "identity_unknown"
    assert calls == ["profile"]


def test_expired_credentials_and_budget_stop_without_fetch():
    def forbidden(*args):
        pytest.fail("must not query")

    old = credential()
    old.expires_at = NOW - 1
    assert run([old], fetch=forbidden)["observations"][0]["state"] == "credential_expired"
    ticks = iter([0, 2])
    assert (
        run(fetch=forbidden, clock=lambda: next(ticks), budget=1)["observations"][0]["state"]
        == "budget_exhausted"
    )


@pytest.mark.parametrize("config_relative", [".claude.json", ".claude/.claude.json"])
def test_discovery_preserves_files_and_redacts_proxy_filenames(tmp_path, config_relative):
    named, proxy = tmp_path / "profiles", tmp_path / "proxy"
    home = named / "max-01"
    (home / ".claude").mkdir(parents=True)
    proxy.mkdir()
    path = home / ".claude/.credentials.json"
    path.write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "secret", "expiresAt": (NOW + 600) * 1000}})
    )
    cache = home / config_relative
    cache.write_text(
        json.dumps({"oauthAccount": {"accountUuid": ACCOUNT, "organizationUuid": OTHER}})
    )
    vp = proxy / "claude-private@example.test.json"
    vp.write_text(json.dumps({"type": "claude", "access_token": "secret", "expired": FUTURE}))
    before = {p: p.read_bytes() for p in [path, cache, vp]}
    rows = capacity.discover(named, proxy)
    assert len(rows) == 2
    assert rows[0].cached_identity == (ACCOUNT, OTHER)
    assert rows[1].label.startswith("vibeproxy:")
    assert "@" not in rows[1].label
    assert before == {p: p.read_bytes() for p in before}


def test_config_directory_identity_takes_precedence(tmp_path):
    home = tmp_path / "max-01"
    (home / ".claude").mkdir(parents=True)
    path = home / ".claude/.credentials.json"
    path.write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "secret", "expiresAt": NOW * 1000}})
    )
    for config, org in [(home / ".claude.json", OTHER), (home / ".claude/.claude.json", ORG)]:
        config.write_text(
            json.dumps({"oauthAccount": {"accountUuid": ACCOUNT, "organizationUuid": org}})
        )
    assert capacity.discover(tmp_path, tmp_path / "absent")[0].cached_identity == (ACCOUNT, ORG)


def scoped_limit(**overrides):
    return {
        "kind": "weekly_scoped",
        "percent": 100,
        "resets_at": FUTURE,
        "is_active": True,
        "scope": {"model": {"id": None, "display_name": "Fable"}},
        **overrides,
    }


def test_new_scoped_limit_overrides_base_headroom_without_leaking_breakdown():
    usage = {**USAGE, "seven_day_breakdown": {"rows": ["private"]}, "limits": [scoped_limit()]}
    report = run(usage=usage)
    row = report["observations"][0]
    assert row["base_window_headroom"] is True
    assert row["quota_state"] == "restricted"
    assert row["windows"]["limit_0"]["model"] == "Fable"
    assert row["windows"]["limit_0"]["remaining_percent"] == 0
    assert report["unique_identities_with_allowance"] == 0
    assert report["unique_identities_with_base_headroom"] == 1
    assert "private" not in json.dumps(report)


@pytest.mark.parametrize(
    "limits",
    [
        None,
        {},
        [None],
        [scoped_limit(kind={})],
        [scoped_limit(scope=None)],
        [scoped_limit(is_active="false")],
        [scoped_limit()] * 33,
    ],
)
def test_unsupported_limits_are_unknown(limits):
    result = capacity.summarize_usage({**USAGE, "limits": limits}, NOW)
    assert result["quota_state"] == "unknown"
    assert result["reason_codes"] == ["unsupported_limits"]


def test_scoped_headroom_does_not_imply_execution_and_unknown_labels_are_redacted():
    limit = scoped_limit(percent=20, is_active=False, scope={"model": {"display_name": "secret"}})
    report = run(usage={**USAGE, "limits": [limit]})
    assert report["observations"][0]["quota_state"] == "available"
    assert report["execution_verified"] is False
    assert "secret" not in json.dumps(report)


def test_active_warning_is_reported_without_interpreting_admission():
    limit = scoped_limit(percent=88, severity="warning")
    row = run(usage={**USAGE, "limits": [limit]})["observations"][0]
    assert row["quota_state"] == "unknown"
    assert row["reason_codes"] == ["active_limit_needs_interpretation"]
    assert row["windows"]["limit_0"]["severity"] == "warning"
    assert row["windows"]["limit_0"]["remaining_percent"] == 12


def test_contradictory_identity_observations_never_count_as_available():
    def fetch(token, endpoint, timeout):
        if endpoint == "profile":
            return PROFILE
        return USAGE if token == "good" else {**USAGE, "limits": [scoped_limit()]}

    report = run([credential(token="good"), credential("max-02", "restricted")], fetch=fetch)
    assert report["unique_identities_with_allowance"] == 0


def test_duplicate_token_observation_is_clipped_to_each_file_expiry():
    earlier = credential("max-02")
    earlier.expires_at = NOW + 10
    assert run([credential(), earlier])["observations"][1]["expires_at"] == NOW + 10


def test_malformed_credential_is_unknown(tmp_path):
    home = tmp_path / "max-01"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude/.credentials.json").write_text('{"private":')
    assert capacity.discover(tmp_path, tmp_path / "absent")[0].state == "credential_unknown"


def test_wrong_provider_file_is_never_sent_to_anthropic(tmp_path):
    (tmp_path / "claude-mislabeled.json").write_text(
        json.dumps({"type": "codex", "access_token": "other-provider-secret", "expired": FUTURE})
    )
    row = capacity.discover(tmp_path / "missing", tmp_path)[0]
    assert row.state == "credential_unknown"
    assert row.token == ""


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b"null",
        b"not json: secret",
        b"x" * (capacity.MAX_BYTES + 1),
        b'{"x":' + b"[" * 2000 + b"]" * 2000 + b"}",
    ],
)
def test_invalid_or_oversized_response_is_sanitized(monkeypatch, body):
    class Response:
        status = 200

        def read(self, limit):
            assert limit == capacity.MAX_BYTES + 1
            return body

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(capacity.http.client, "HTTPSConnection", Connection)
    report = run(fetch=capacity.oauth_get)
    assert report["observations"][0]["state"] in {"invalid_response", "oversized_response"}
    assert "secret" not in json.dumps(report)


@pytest.mark.parametrize(
    "status,reason",
    [
        (302, "http_error"),
        (401, "auth_rejected"),
        (403, "permission_denied"),
        (429, "rate_limited"),
        (500, "http_error"),
    ],
)
def test_http_errors_do_not_leak_bodies_retry_or_redirect(monkeypatch, status, reason):
    class Response:
        def read(self, *args):
            pytest.fail("error response body must not be read")

    response = Response()
    response.status = status
    requests = []

    class Connection:
        def __init__(self, host, timeout):
            assert host == "api.anthropic.com"

        def request(self, method, endpoint, headers):
            requests.append((method, endpoint))

        def getresponse(self):
            return response

        def close(self):
            pass

    monkeypatch.setattr(capacity.http.client, "HTTPSConnection", Connection)
    report = run(fetch=capacity.oauth_get)
    assert report["observations"][0]["state"] == reason
    assert requests == [("GET", "/api/oauth/profile")]
    assert "quota_state" not in report["observations"][0]


@pytest.mark.parametrize(
    "error,reason",
    [
        (TimeoutError("secret"), "timeout"),
        (OSError("secret"), "transport_error"),
        (ValueError("secret"), "invalid_response"),
    ],
)
def test_transport_exception_messages_are_sanitized(monkeypatch, error, reason):
    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            raise error

        def close(self):
            pass

    monkeypatch.setattr(capacity.http.client, "HTTPSConnection", Connection)
    report = run(fetch=capacity.oauth_get)
    assert report["observations"][0]["state"] == reason
    assert "secret" not in json.dumps(report)
