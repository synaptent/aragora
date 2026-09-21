"""Executable contract traces for the agent operating loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "docs" / "schemas" / "orientation.v1.json"
FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_NAMES = {
    "fresh_orientation.json",
    "interrupted_resumption.json",
    "quiet_no_change.json",
    "uncertain_high_risk.json",
}
DERIVED_COLLECTIONS = (
    "work_recommendations",
    "beliefs",
    "questions",
    "affordances",
    "obligations",
)
DERIVED_METADATA = {
    "basis_fingerprint",
    "evidence_refs",
    "authority",
    "freshness",
    "invalidators",
    "bounded_cost",
}
DERIVED_EXAMPLES = (
    ("fresh_orientation.json", "work_recommendations"),
    ("fresh_orientation.json", "beliefs"),
    ("uncertain_high_risk.json", "questions"),
    ("fresh_orientation.json", "affordances"),
    ("interrupted_resumption.json", "obligations"),
)
AUTHORITY_PRECEDENCE = (
    "live_authority",
    "durable_state",
    "commit_evidence",
    "derived_recommendation",
)
EVIDENCE_COLLECTIONS = (*DERIVED_COLLECTIONS, "source_observations", "facts")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _evidence_handles(document: dict[str, Any]) -> list[dict[str, Any]]:
    handles: list[dict[str, Any]] = []
    for collection in EVIDENCE_COLLECTIONS:
        for record in document.get(collection, ()):
            handles.extend(record["evidence_refs"])
    return handles


@pytest.fixture(scope="module")
def validator() -> Any:
    schema = _load(SCHEMA_PATH)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


@pytest.fixture(scope="module")
def bare_validator() -> Any:
    """A validator with no format checker: the shape of a locked runtime env.

    `jsonschema` only asserts `format: date-time` when `rfc3339-validator` is
    installed, which nothing in this repository pins, so every constraint the
    envelope relies on has to hold without it.
    """
    return jsonschema.Draft202012Validator(_load(SCHEMA_PATH))


@pytest.mark.parametrize("fixture_name", sorted(FIXTURE_NAMES))
def test_trace_conforms_to_orientation_v1(validator: Any, fixture_name: str) -> None:
    validator.validate(_load(FIXTURE_DIR / fixture_name))


def test_trace_set_is_exact() -> None:
    assert {path.name for path in FIXTURE_DIR.glob("*.json")} == FIXTURE_NAMES


@pytest.mark.parametrize("fixture_name", sorted(FIXTURE_NAMES - {"quiet_no_change.json"}))
def test_derived_records_preserve_lower_layer_basis(fixture_name: str) -> None:
    document = _load(FIXTURE_DIR / fixture_name)
    for collection in DERIVED_COLLECTIONS:
        for record in document[collection]:
            assert DERIVED_METADATA <= record.keys()
            assert "reasoning_fingerprint" not in record
            assert record["authority"] == "derived_recommendation"
            assert record["evidence_refs"]


@pytest.mark.parametrize(("fixture_name", "collection"), DERIVED_EXAMPLES)
def test_schema_rejects_undeclared_derived_fields(
    validator: Any, fixture_name: str, collection: str
) -> None:
    document = _load(FIXTURE_DIR / fixture_name)
    document[collection][0]["reasoning_fingerprint"] = "sha256:" + ("0" * 64)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(document)


def test_traces_exercise_portable_lower_layer_evidence() -> None:
    handles: list[dict[str, Any]] = []
    for fixture_name in FIXTURE_NAMES - {"quiet_no_change.json"}:
        handles.extend(_evidence_handles(_load(FIXTURE_DIR / fixture_name)))
    assert handles
    assert all(urlsplit(handle["uri"]).scheme not in {"", "file"} for handle in handles)


def test_fresh_trace_exercises_source_fact_belief_and_nomic() -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    assert document["source_observations"] and document["facts"] and document["beliefs"]
    assert document["nomic"]["state"] == "absent"


@pytest.mark.parametrize("fixture_name", sorted(FIXTURE_NAMES - {"quiet_no_change.json"}))
def test_truncation_emitted_bytes_is_canonically_measured(fixture_name: str) -> None:
    document = _load(FIXTURE_DIR / fixture_name)
    emitted_bytes = len(_canonical_bytes(document))
    assert document["truncation"]["emitted_bytes"] == emitted_bytes
    assert emitted_bytes <= document["truncation"]["budget_bytes"]


@pytest.mark.parametrize("fact_authority", AUTHORITY_PRECEDENCE)
@pytest.mark.parametrize("evidence_authority", AUTHORITY_PRECEDENCE)
def test_fact_authority_cannot_exceed_cited_evidence(
    validator: Any, fact_authority: str, evidence_authority: str
) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    fact = document["facts"][0]
    fact["authority"] = fact_authority
    fact["evidence_refs"][0]["authority"] = evidence_authority

    if AUTHORITY_PRECEDENCE.index(fact_authority) < AUTHORITY_PRECEDENCE.index(evidence_authority):
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(document)
    else:
        validator.validate(document)


@pytest.mark.parametrize("observation_authority", AUTHORITY_PRECEDENCE)
@pytest.mark.parametrize("evidence_authority", AUTHORITY_PRECEDENCE)
def test_source_observation_authority_cannot_exceed_cited_evidence(
    validator: Any, observation_authority: str, evidence_authority: str
) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    observation = document["source_observations"][0]
    observation["authority"] = observation_authority
    observation["evidence_refs"][0]["authority"] = evidence_authority

    exceeds = AUTHORITY_PRECEDENCE.index(observation_authority) < AUTHORITY_PRECEDENCE.index(
        evidence_authority
    )
    if exceeds:
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(document)
    else:
        validator.validate(document)


@pytest.mark.parametrize(
    "malformed",
    [
        "not-a-date",
        "2026-08-31",
        "2026-08-31 13:30:00Z",
        "2026-13-31T13:30:00Z",
        "2026-08-31T25:30:00Z",
        "2026-08-31T13:30:00",
        "",
    ],
)
@pytest.mark.parametrize(
    ("fixture_name", "pointer"),
    [
        ("fresh_orientation.json", ("generated_at",)),
        ("fresh_orientation.json", ("source_observations", 0, "observed_at")),
        ("fresh_orientation.json", ("facts", 0, "freshness", "observed_at")),
        ("fresh_orientation.json", ("facts", 0, "freshness", "expires_at")),
    ],
)
def test_schema_rejects_malformed_timestamps(
    validator: Any, fixture_name: str, pointer: tuple[Any, ...], malformed: str
) -> None:
    document = _load(FIXTURE_DIR / fixture_name)
    target: Any = document
    for key in pointer[:-1]:
        target = target[key]
    target[pointer[-1]] = malformed

    with pytest.raises(jsonschema.ValidationError):
        validator.validate(document)


@pytest.mark.parametrize(
    "well_formed",
    [
        "2026-08-31T13:30:00Z",
        "2026-08-31T13:30:00.123456Z",
        "2026-08-31T13:30:00+05:30",
        "2026-08-31T13:30:00-08:00",
        "2026-12-01T00:00:00Z",
    ],
)
def test_schema_accepts_rfc3339_timestamps(validator: Any, well_formed: str) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["generated_at"] = well_formed
    validator.validate(document)


@pytest.mark.parametrize(
    "impossible_date",
    [
        "2026-02-29T13:30:00Z",
        "2026-02-30T13:30:00Z",
        "2026-02-31T13:30:00Z",
        "2026-04-31T13:30:00Z",
        "2026-06-31T13:30:00Z",
        "2100-02-29T13:30:00Z",
        "1900-02-29T13:30:00Z",
    ],
)
def test_schema_rejects_impossible_calendar_dates(
    bare_validator: Any, impossible_date: str
) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["generated_at"] = impossible_date
    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)


@pytest.mark.parametrize(
    "leap_day", ["2024-02-29T13:30:00Z", "2000-02-29T13:30:00Z", "2400-02-29T13:30:00Z"]
)
def test_schema_accepts_real_leap_days(bare_validator: Any, leap_day: str) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["generated_at"] = leap_day
    bare_validator.validate(document)


@pytest.mark.parametrize(
    "pointer",
    [
        ("generated_at",),
        ("orientation_fingerprint",),
        ("repository_anchor", "commit_sha"),
        ("repository_anchor", "tree_sha"),
    ],
)
@pytest.mark.parametrize("trailer", ["\n", " ", "\r\n", "\t"])
def test_anchored_patterns_reject_trailing_whitespace(
    bare_validator: Any, pointer: tuple[str, ...], trailer: str
) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    target: Any = document
    for key in pointer[:-1]:
        target = target[key]
    target[pointer[-1]] = f"{target[pointer[-1]]}{trailer}"

    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)


def test_source_observation_requires_at_least_one_evidence_handle(validator: Any) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["source_observations"][0]["evidence_refs"] = []
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(document)


def test_mission_projection_requires_an_evidence_handle(validator: Any) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    assert document["mission"]["evidence_refs"]
    document["mission"]["evidence_refs"] = []
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(document)


@pytest.mark.parametrize(
    "unusable_uri",
    [
        "file:///tmp/orientation.json",
        "../architecture/agent-operating-loop.md",
        "README.md",
        "/absolute/local/path",
        "https://example.invalid/a b",
        "https://example.invalid/a\n",
    ],
)
def test_evidence_uris_must_be_portable(validator: Any, unusable_uri: str) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["facts"][0]["evidence_refs"][0]["uri"] = unusable_uri
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(document)


def test_no_change_envelope_can_be_judged_for_freshness(validator: Any) -> None:
    document = _load(FIXTURE_DIR / "quiet_no_change.json")
    assert document["generated_at"]
    validator.validate(document)

    del document["generated_at"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(document)


def test_no_change_envelope_carries_exactly_one_next_legal_action(validator: Any) -> None:
    document = _load(FIXTURE_DIR / "quiet_no_change.json")
    assert len(document["next_legal_actions"]) == 1

    document["next_legal_actions"] = []
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(document)


def test_evidence_handles_bind_one_fingerprint_per_uri() -> None:
    for fixture_name in sorted(FIXTURE_NAMES):
        document = _load(FIXTURE_DIR / fixture_name)
        by_uri: dict[str, set[str]] = {}
        for handle in _evidence_handles(document):
            by_uri.setdefault(handle["uri"], set()).add(handle["fingerprint"])
        divergent = {uri: prints for uri, prints in by_uri.items() if len(prints) > 1}
        assert not divergent, f"{fixture_name} binds one uri to several fingerprints: {divergent}"


def test_live_blocker_overrides_ready_recommendation() -> None:
    document = _load(FIXTURE_DIR / "interrupted_resumption.json")
    assert document["work_recommendations"][0]["classification"] == "ready"
    affordance = document["affordances"][0]
    assert affordance["authority"] == "derived_recommendation"
    assert affordance["evidence_refs"][0]["authority"] == "live_authority"
    assert affordance["disposition"] == "blocked"
    assert affordance["blocked_by"] == ["settlement:BLOCKED"]


def test_named_sources_sit_in_the_layer_the_contract_assigns() -> None:
    """Pin the two sources whose layer the contract names explicitly.

    Live check state outranks the work board, while the lease a lane must hold
    open is ledger state. Reclassifying either silently would let a derived
    recommendation outrank a blocker, so both are asserted rather than implied.
    """
    document = _load(FIXTURE_DIR / "interrupted_resumption.json")
    settlement = document["affordances"][0]["evidence_refs"][0]
    lease = document["obligations"][0]["evidence_refs"][0]

    assert settlement["id"] == "settlement:PR-2"
    assert settlement["authority"] == "live_authority"
    assert lease["id"] == "lease:lease-1"
    assert lease["authority"] == "durable_state"
    assert AUTHORITY_PRECEDENCE.index(settlement["authority"]) < AUTHORITY_PRECEDENCE.index(
        document["work_recommendations"][0]["authority"]
    )


def test_high_risk_trace_requests_authorization_without_effect() -> None:
    document = _load(FIXTURE_DIR / "uncertain_high_risk.json")
    affordance = document["affordances"][0]
    assert affordance["risk_tier"] == 4
    assert affordance["disposition"] == "requires_authorization"
    assert document["mutations"] == []


def test_quiet_no_change_trace_fits_wire_budget() -> None:
    document = _load(FIXTURE_DIR / "quiet_no_change.json")
    encoded = _canonical_bytes(document)
    assert len(encoded) <= 800
    assert "since_fingerprint" not in document
    assert document["mutations"] == []


def test_no_change_rejects_a_second_fingerprint(validator: Any) -> None:
    document = _load(FIXTURE_DIR / "quiet_no_change.json")
    document["since_fingerprint"] = "sha256:" + ("0" * 64)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(document)


@pytest.mark.parametrize(
    "doc_path",
    [
        "docs/THESIS.md",
        "docs/plans/ARAGORA_EVOLUTION_ROADMAP.md",
        "docs/AGENT_FLYWHEEL_ARAGORA_NATIVE.md",
        "docs/plans/2026-06-25-native-mission-orchestrator-spec.md",
        "docs/architecture/nomic-context-builder-plan.md",
    ],
)
def test_canonical_sources_link_to_operating_loop(doc_path: str) -> None:
    assert "agent-operating-loop.md" in (ROOT / doc_path).read_text(encoding="utf-8")
