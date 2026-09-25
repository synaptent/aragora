"""Phase 2A data verification: test keys only, no live authorization or I/O."""

import base64
import copy
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aragora.policy import operator_grant as g

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
DEFAULT_WIRE = object()


@pytest.fixture
def state():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    payload = {
        "schema_version": g.SCHEMA_VERSION,
        "grant_id": "test-grant",
        "grant_version": 1,
        "repository_id": 123,
        "repository": "example/test-only",
        "operator": "test-operator",
        "delegate": "test-session",
        "campaign_id": "test-campaign",
        "goal_digest": "a" * 64,
        "acceptance_digest": "b" * 64,
        "policy_version": "test-policy-v1",
        "policy_digest": "c" * 64,
        "enforcement_digest": "d" * 64,
        "key_id": "test-key",
        "trust_version": 1,
        "revocation_source": "test-only-snapshot",
        "approval_ref": "test-event",
        "approval_digest": "e" * 64,
        "issued_at": "2026-09-07T11:59:00Z",
        "not_before": "2026-09-07T12:00:00Z",
        "expires_at": "2026-09-08T11:59:00Z",
        "actions": ["validate"],
        "denied_actions": sorted(g.HARD_DENIALS),
        "scope": {
            "branches": ["codex/test"],
            "paths": ["tests/test_example.py"],
            "denied_paths": [".github/workflows/test.yml"],
            "surfaces": ["test-only"],
            "risk_classes": ["test-only"],
            "tiers": [0],
        },
        "contract_ids": ["TEST-01"],
        "validation_commands": ["pytest tests/test_example.py"],
        "review_requirements": ["current-landed-policy"],
        "can_subdelegate": False,
        "budget": {
            "active_prs": 1,
            "merges": 10,
            "attempts": 2,
            "wall_seconds": 86400,
            "paid_microdollars": 0,
            "subdelegates": 0,
        },
    }
    return {
        "payload": payload,
        "private": private,
        "expected": {k: payload[k] for k in g.CONTEXT_FIELDS},
        "trusted_keys": {
            "test-key": g.TrustedKey(
                "test-operator", public, 1, False, NOW, NOW + timedelta(seconds=60)
            )
        },
        "revocation": g.RevocationObservation(
            "test-only-snapshot", "test-grant", 1, False, NOW, NOW + timedelta(seconds=60)
        ),
    }


def wire(state, payload=None, domain=g.DOMAIN):
    # Encode independently of the production validator so malformed shapes reach it.
    p = state["payload"] if payload is None else payload
    data = domain + json.dumps(p, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8", errors="surrogatepass"
    )
    signature = base64.b64encode(state["private"].sign(data)).decode("ascii")
    return json.dumps({"payload": p, "signature": signature}).encode("utf-8")


def verify(state, data=DEFAULT_WIRE, **overrides):
    args = {k: state[k] for k in ("expected", "trusted_keys", "revocation")}
    args["now"] = NOW
    args.update(overrides)
    return g.verify_operator_grant(wire(state) if data is DEFAULT_WIRE else data, **args)


def denied(result, code):
    assert result.code is code
    assert result.grant is None


def test_verified_data_is_immutable_and_not_authority(state):
    result = verify(state)
    assert result.code is g.VerificationCode.VERIFIED
    canonical = g.canonical_grant_payload(state["payload"])
    assert result.grant.canonical_payload == canonical
    assert result.grant.payload_sha256 == hashlib.sha256(canonical).hexdigest()
    assert not hasattr(result, "allowed") and not hasattr(result, "human_preapproval_recorded")
    with pytest.raises(FrozenInstanceError):
        result.grant.canonical_payload = b"changed"
    state["payload"]["actions"].append("ready")
    assert result.grant.canonical_payload == canonical


def test_canonical_encoding_order_unicode_and_wire_format(state):
    p = state["payload"]
    p["approval_ref"] = "test-event-\u00e9"
    assert verify(state).code is g.VerificationCode.VERIFIED
    first = g.canonical_grant_payload(p)
    assert first == g.canonical_grant_payload(dict(reversed(list(p.items()))))
    assert b"\xc3\xa9" in first and b"\\u00e9" not in first
    p["approval_ref"] = "test-event-e\u0301"
    assert first != g.canonical_grant_payload(p)  # No silent Unicode normalization.
    compact = json.dumps(json.loads(wire(state)), separators=(",", ":")).encode()
    assert verify(state, compact).code is g.VerificationCode.VERIFIED


@pytest.mark.parametrize("field", sorted(g.CONTEXT_FIELDS))
def test_every_context_pin_is_required_and_exact(state, field):
    expected = dict(state["expected"])
    expected.pop(field)
    denied(verify(state, expected=expected), g.VerificationCode.CONTEXT_MISMATCH)
    expected = dict(state["expected"])
    expected[field] = 2 if type(expected[field]) is int else "different"
    denied(verify(state, expected=expected), g.VerificationCode.CONTEXT_MISMATCH)


@pytest.mark.parametrize("expected", [None, [], {}, {"grant_version": True}])
def test_unavailable_context_does_not_authorize(state, expected):
    denied(verify(state, expected=expected), g.VerificationCode.CONTEXT_MISMATCH)


def test_context_bool_does_not_match_integer_and_signed_wrong_repo_rejects(state):
    expected = {**state["expected"], "grant_version": True}
    denied(verify(state, expected=expected), g.VerificationCode.CONTEXT_MISMATCH)
    p = {**state["payload"], "repository": "different/repo"}
    denied(verify(state, wire(state, p)), g.VerificationCode.CONTEXT_MISMATCH)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "aragora-delegation-contract/0.1"),
        ("operator", ""),
        ("delegate", 1),
        ("goal_digest", "z" * 64),
        ("policy_digest", "A" * 64),
        ("repository_id", True),
        ("grant_version", 0),
        ("trust_version", "1"),
        ("can_subdelegate", "false"),
        ("can_subdelegate", 0),
        ("can_subdelegate", True),
        ("approval_ref", "quoted\nreply"),
        ("approval_ref", "\ud800"),
        ("actions", []),
        ("actions", ["admin_merge"]),
        ("actions", ["validate", "validate"]),
        ("actions", ["*"]),
        ("denied_actions", []),
        ("contract_ids", []),
        ("validation_commands", []),
        ("review_requirements", None),
        ("issued_at", "2026-02-30T00:00:00Z"),
        ("not_before", "2026-09-07T12:00:00+00:00"),
        ("not_before", "2026-09-07T11:58:00Z"),
        ("expires_at", "2026-09-09T00:00:00Z"),
        ("expires_at", "2026-09-07T12:00:00Z"),
        ("signature", "unexpected-payload-field"),
    ],
)
def test_signed_malformed_payloads_reject(state, field, value):
    p = {**state["payload"], field: value}
    denied(verify(state, wire(state, p)), g.VerificationCode.MALFORMED)
    with pytest.raises(g.GrantValidationError):
        g.canonical_grant_payload(p)


@pytest.mark.parametrize("field", list(g.CONTEXT_FIELDS) + ["scope", "budget", "approval_digest"])
def test_missing_payload_fields_reject(state, field):
    p = dict(state["payload"])
    p.pop(field)
    denied(verify(state, wire(state, p)), g.VerificationCode.MALFORMED)


@pytest.mark.parametrize(
    "field,value",
    [
        ("paths", []),
        ("branches", []),
        ("surfaces", []),
        ("risk_classes", []),
        ("paths", ["../outside.py"]),
        ("paths", ["/tmp/outside.py"]),
        ("paths", ["a/./b"]),
        ("paths", ["a//b"]),
        ("paths", ["a\\b"]),
        ("paths", ["a/*"]),
        ("paths", ["."]),
        ("paths", [".github/workflows/test.yml"]),
        ("tiers", [True]),
        ("tiers", [5]),
        ("tiers", []),
        ("tiers", [0, 0]),
        ("extra", "unknown"),
    ],
)
def test_explicit_scope_required(state, field, value):
    p = copy.deepcopy(state["payload"])
    p["scope"][field] = value
    denied(verify(state, wire(state, p)), g.VerificationCode.MALFORMED)


@pytest.mark.parametrize(
    "field,value",
    [
        ("active_prs", 2),
        ("active_prs", True),
        ("merges", 11),
        ("merges", -1),
        ("attempts", 0),
        ("attempts", 2**53),
        ("attempts", 1.5),
        ("wall_seconds", 604801),
        ("wall_seconds", 0),
        ("subdelegates", 1),
        ("paid_microdollars", 1),
        ("paid_microdollars", False),
        ("merges", float("inf")),
        ("merges", float("nan")),
    ],
)
def test_bounded_integer_budgets(state, field, value):
    p = copy.deepcopy(state["payload"])
    p["budget"][field] = value
    denied(verify(state, wire(state, p)), g.VerificationCode.MALFORMED)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"null",
        b"[]",
        b"{}",
        b"not json",
        b'"approve"',
        b"```json\n{}\n```",
        b"\xff",
        b" " * (g.MAX_BYTES + 1),
        b'{"payload":{},"payload":{},"signature":"a"}',
        b'{"payload":{"x":1,"x":2},"signature":"a"}',
        b"[" * 1200 + b"]" * 1200,
        b'{"contract_id":"legacy","signature":null}',
    ],
)
def test_invalid_envelopes_and_legacy_records(state, data):
    denied(verify(state, data), g.VerificationCode.MALFORMED)


def test_payload_limit_and_noncanonical_signature(state):
    p = copy.deepcopy(state["payload"])
    p["validation_commands"] = ["x" * 2044 + f"{i:04}" for i in range(64)]
    with pytest.raises(g.GrantValidationError):
        g.canonical_grant_payload(p)
    denied(verify(state, wire(state, p)), g.VerificationCode.MALFORMED)
    outer = json.loads(wire(state))
    signature = outer["signature"]
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    outer["signature"] = signature[:-3] + alphabet[alphabet.index(signature[-3]) + 1] + "=="
    denied(verify(state, json.dumps(outer).encode()), g.VerificationCode.MALFORMED)


@pytest.mark.parametrize("data", ["{}", None, {}, bytearray(b"{}")])
def test_wrong_wire_type(state, data):
    denied(verify(state, data), g.VerificationCode.MALFORMED)


def test_signed_tampering_domain_and_wrong_key(state):
    outer = json.loads(wire(state))
    outer["payload"]["approval_ref"] = "tampered"
    denied(verify(state, json.dumps(outer).encode()), g.VerificationCode.INVALID_SIGNATURE)
    denied(
        verify(state, wire(state, domain=b"other-domain\n")), g.VerificationCode.INVALID_SIGNATURE
    )
    other = {**state, "private": Ed25519PrivateKey.generate()}
    denied(verify(state, wire(other)), g.VerificationCode.INVALID_SIGNATURE)
    outer = json.loads(wire(state))
    outer["signature"] = base64.b64encode(bytes(64)).decode()
    denied(verify(state, json.dumps(outer).encode()), g.VerificationCode.INVALID_SIGNATURE)


@pytest.mark.parametrize("signature", [None, "!", "YQ==", "\u00e9", "AA==\n"])
def test_malformed_signatures(state, signature):
    outer = json.loads(wire(state))
    outer["signature"] = signature
    denied(verify(state, json.dumps(outer).encode()), g.VerificationCode.MALFORMED)


@pytest.mark.parametrize(
    "now",
    [
        NOW - timedelta(seconds=1),
        NOW + timedelta(days=1),
        None,
        NOW.replace(tzinfo=None),
        "2026-09-07T12:00:00Z",
    ],
)
def test_time_boundary_and_unavailable_clock(state, now):
    denied(verify(state, now=now), g.VerificationCode.INVALID_TIME)


@pytest.mark.parametrize("keys", [None, {}, [], {"test-key": {}}, {"test-key": None}])
def test_no_implicit_trust(state, keys):
    denied(verify(state, trusted_keys=keys), g.VerificationCode.UNTRUSTED)


@pytest.mark.parametrize(
    "field,value",
    [
        ("operator", "other"),
        ("trust_version", True),
        ("trust_version", 2),
        ("public_key", b"bad"),
        ("public_key", "not bytes"),
        ("revoked", "false"),
        ("revoked", 0),
        ("observed_at", None),
        ("valid_until", NOW),
        ("observed_at", NOW + timedelta(seconds=1)),
        ("observed_at", NOW - timedelta(seconds=61)),
        ("valid_until", NOW + timedelta(seconds=61)),
    ],
)
def test_malformed_stale_or_wrong_trust(state, field, value):
    key = replace(state["trusted_keys"]["test-key"], **{field: value})
    denied(verify(state, trusted_keys={"test-key": key}), g.VerificationCode.UNTRUSTED)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "other"),
        ("grant_id", "other"),
        ("grant_version", 2),
        ("grant_version", True),
        ("revoked", "false"),
        ("revoked", 0),
        ("observed_at", None),
        ("valid_until", NOW),
        ("observed_at", NOW + timedelta(seconds=1)),
        ("observed_at", NOW - timedelta(seconds=61)),
    ],
)
def test_revocation_is_fresh_exact_and_boolean(state, field, value):
    observation = replace(state["revocation"], **{field: value})
    denied(verify(state, revocation=observation), g.VerificationCode.UNTRUSTED)


def test_revoked_and_missing_observations(state):
    denied(verify(state, revocation=None), g.VerificationCode.UNTRUSTED)
    denied(verify(state, revocation={}), g.VerificationCode.UNTRUSTED)
    denied(
        verify(state, revocation=replace(state["revocation"], revoked=True)),
        g.VerificationCode.REVOKED,
    )
    key = replace(state["trusted_keys"]["test-key"], revoked=True)
    denied(verify(state, trusted_keys={"test-key": key}), g.VerificationCode.REVOKED)


def test_crypto_unavailable_fails_closed(state, monkeypatch):
    def unavailable(**kwargs):
        raise ImportError("test: no cryptography")

    monkeypatch.setattr(g, "Ed25519Signer", unavailable)
    denied(verify(state), g.VerificationCode.CRYPTO_UNAVAILABLE)


def test_verifier_only_cannot_sign_and_does_no_io(state, monkeypatch):
    verifier = g.Ed25519Signer(public_key=state["private"].public_key(), key_id="test-key")
    with pytest.raises(ValueError, match="Private key required"):
        verifier.sign(b"test")
    data = wire(state)

    def forbidden(*args, **kwargs):
        pytest.fail("verification attempted I/O")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("pathlib.Path.write_text", forbidden)
    monkeypatch.setattr("pathlib.Path.write_bytes", forbidden)
    assert verify(state, data).code is g.VerificationCode.VERIFIED
    denied(verify(state, b"quoted approval"), g.VerificationCode.MALFORMED)
