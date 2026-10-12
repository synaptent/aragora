"""Executable contract traces for the agent operating loop."""

from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH_IN_REPO = "docs/schemas/orientation.v1.json"
SCHEMA_PATH = ROOT / SCHEMA_PATH_IN_REPO
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
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
GROUNDED_AUTHORITIES = AUTHORITY_PRECEDENCE[:-1]
EVIDENCE_COLLECTIONS = (*DERIVED_COLLECTIONS, "source_observations", "facts")
EVIDENCE_URI_SCHEMES = frozenset({"aragora", "https"})
FRESHNESS_EXAMPLES = (("fresh_orientation.json", "facts"), *DERIVED_EXAMPLES)
NOMIC_REFS = ("pack_ref", "result_ref", "receipt_ref")
OMITTABLE_COLLECTIONS = ("work_recommendations", "beliefs", "questions")
NEVER_OMITTED_COLLECTIONS = (
    "source_observations",
    "facts",
    "affordances",
    "obligations",
    "source_health",
    "next_legal_actions",
)


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


def _unresolved_blocker_links(document: dict[str, Any]) -> list[str]:
    """Return blocker links that do not name exactly one of their affordance's own handles.

    JSON Schema cannot compare sibling values, so this resolution rule lives in
    the contract tests (and in every emitter) rather than in the schema.
    """
    unresolved: list[str] = []
    for affordance in document.get("affordances", ()):
        cited = [handle["id"] for handle in affordance["evidence_refs"]]
        for link in affordance["blocked_by"]:
            if cited.count(link["evidence_ref"]) != 1:
                unresolved.append(f"{affordance['id']} -> {link['evidence_ref']}")
    return unresolved


def _commit_evidence_handle(name: str, status: str = "fresh") -> dict[str, Any]:
    return {
        "id": f"nomic:{name}",
        "uri": f"aragora://synaptent/aragora/nomic/{name}",
        "authority": "commit_evidence",
        "fingerprint": "sha256:" + hashlib.sha256(name.encode("utf-8")).hexdigest(),
        "freshness": {"status": status, "observed_at": "2026-08-31T13:30:00Z", "expires_at": None},
        "invalidators": ["repository anchor changes"],
    }


def _nomic(state: str) -> dict[str, Any]:
    if state == "absent":
        return {
            "state": state,
            "exact_commit_match": False,
            "evidence_coverage": 0.0,
            "dissent": [],
        }
    status = "fresh" if state == "verified" else "stale"
    return {
        "state": state,
        "exact_commit_match": state == "verified",
        "evidence_coverage": 1.0,
        **{ref: _commit_evidence_handle(ref.removesuffix("_ref"), status) for ref in NOMIC_REFS},
        "dissent": [],
    }


def _ungrounded_nomic_refs() -> list[Any]:
    handle = _commit_evidence_handle("pack")
    without_fingerprint = {key: value for key, value in handle.items() if key != "fingerprint"}
    return [
        pytest.param("x", id="free-form-string"),
        pytest.param("aragora://synaptent/aragora/nomic/pack", id="bare-uri-string"),
        pytest.param("javascript:alert(1)", id="javascript-string"),
        pytest.param("data:text/html,<script>alert(1)</script>", id="data-string"),
        pytest.param("file:///etc/passwd", id="file-string"),
        pytest.param({**handle, "uri": "javascript:alert(1)"}, id="javascript-handle"),
        pytest.param({**handle, "uri": "data:text/html,x"}, id="data-handle"),
        pytest.param({**handle, "uri": "file:///etc/passwd"}, id="file-handle"),
        pytest.param({**handle, "authority": "live_authority"}, id="live-authority-handle"),
        pytest.param({**handle, "authority": "durable_state"}, id="durable-state-handle"),
        pytest.param({**handle, "authority": "derived_recommendation"}, id="derived-handle"),
        pytest.param({**handle, "fingerprint": "sha256:x"}, id="malformed-fingerprint"),
        pytest.param(without_fingerprint, id="no-fingerprint"),
    ]


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
    assert {urlsplit(handle["uri"]).scheme for handle in handles} == EVIDENCE_URI_SCHEMES


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

    if fact_authority not in GROUNDED_AUTHORITIES or (
        AUTHORITY_PRECEDENCE.index(fact_authority) < AUTHORITY_PRECEDENCE.index(evidence_authority)
    ):
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
    if exceeds or observation_authority not in GROUNDED_AUTHORITIES:
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(document)
    else:
        validator.validate(document)


@pytest.mark.parametrize("collection", ("facts", "source_observations"))
def test_evidence_backed_records_cannot_ground_themselves_in_derived_guidance(
    bare_validator: Any, collection: str
) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    record = document[collection][0]
    record["authority"] = "derived_recommendation"
    for handle in record["evidence_refs"]:
        handle["authority"] = "derived_recommendation"

    error = jsonschema.exceptions.best_match(bare_validator.iter_errors(document))
    assert error is not None
    assert list(error.absolute_path) == [collection, 0, "authority"]


@pytest.mark.parametrize("weaker_status", ["stale", "unknown"])
@pytest.mark.parametrize(("fixture_name", "collection"), FRESHNESS_EXAMPLES)
def test_fresh_record_cites_only_fresh_evidence(
    bare_validator: Any, fixture_name: str, collection: str, weaker_status: str
) -> None:
    document = _load(FIXTURE_DIR / fixture_name)
    record = document[collection][0]
    assert record["freshness"]["status"] == "fresh"
    fresh_sibling = copy.deepcopy(record["evidence_refs"][0])
    record["evidence_refs"][0]["freshness"]["status"] = weaker_status
    # A fresh sibling handle must not carry a stale one: every cited handle counts.
    record["evidence_refs"].append(fresh_sibling)
    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)


@pytest.mark.parametrize("record_status", ["stale", "unknown"])
@pytest.mark.parametrize(("fixture_name", "collection"), FRESHNESS_EXAMPLES)
def test_non_fresh_record_keeps_stale_evidence_visible(
    bare_validator: Any, fixture_name: str, collection: str, record_status: str
) -> None:
    document = _load(FIXTURE_DIR / fixture_name)
    record = document[collection][0]
    record["freshness"]["status"] = record_status
    for handle in record["evidence_refs"]:
        handle["freshness"]["status"] = "stale"
    bare_validator.validate(document)


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
        "File:///tmp/orientation.json",
        "FILE:///tmp/orientation.json",
        "../architecture/agent-operating-loop.md",
        "README.md",
        "/absolute/local/path",
        "https://example.invalid/a b",
        "https://example.invalid/a\n",
        "C:\\data\\orientation.json",
        "c:/data/orientation.json",
        "x:",
        # Active content, in any case and behind whitespace a consumer might trim.
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "JAVASCRIPT:alert(1)",
        " javascript:alert(1)",
        "\tjavascript:alert(1)",
        "\njavascript:alert(1)",
        "javascript:alert(1) ",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "Data:text/html,<script>alert(1)</script>",
        "DATA:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "VBScript:msgbox(1)",
        "VBSCRIPT:msgbox(1)",
        # Every other scheme, including ones that extend an allowed name.
        "git:head",
        "urn:uuid:8f1a",
        "http://example.invalid/a",
        "ftp://example.invalid/a",
        "mailto:ops@example.invalid",
        "blob:https://example.invalid/0f1e",
        "httpsx://example.invalid/a",
        "https.evil://example.invalid/a",
        "aragoraz://synaptent/aragora/missions/m1",
        "\u04bbttps://example.invalid/a",
        " https://example.invalid/a",
    ],
)
def test_evidence_uris_must_be_portable(validator: Any, unusable_uri: str) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["facts"][0]["evidence_refs"][0]["uri"] = unusable_uri
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(document)


@pytest.mark.parametrize(
    "usable_uri",
    [
        "https://api.github.com/repos/synaptent/aragora/pulls/1",
        "HTTPS://api.github.com/repos/synaptent/aragora/pulls/1",
        "Https://api.github.com/repos/synaptent/aragora/pulls/1",
        "aragora://synaptent/aragora/missions/m1",
        "ARAGORA://synaptent/aragora/missions/m1",
        "aRaGoRa://synaptent/aragora/missions/m1",
    ],
)
def test_evidence_uris_accept_real_schemes(validator: Any, usable_uri: str) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["facts"][0]["evidence_refs"][0]["uri"] = usable_uri
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


@pytest.mark.parametrize("collection", DERIVED_COLLECTIONS)
def test_derived_records_cannot_cite_derived_evidence(bare_validator: Any, collection: str) -> None:
    fixture_name = next(name for name, coll in DERIVED_EXAMPLES if coll == collection)
    document = _load(FIXTURE_DIR / fixture_name)
    document[collection][0]["evidence_refs"][0]["authority"] = "derived_recommendation"
    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)


def test_mission_cannot_cite_derived_evidence(bare_validator: Any) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["mission"]["evidence_refs"][0]["authority"] = "derived_recommendation"
    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)


@pytest.mark.parametrize("authority", ["live_authority", "durable_state", "commit_evidence"])
def test_mission_accepts_every_grounding_layer(bare_validator: Any, authority: str) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["mission"]["evidence_refs"][0]["authority"] = authority
    bare_validator.validate(document)


def test_timestamps_reject_non_ascii_digits(bare_validator: Any) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["generated_at"] = "٢٠٢٦-08-31T13:30:00Z"
    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)


def test_timestamps_reject_leap_seconds(bare_validator: Any) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["generated_at"] = "2026-06-30T23:59:60Z"
    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)


@pytest.mark.parametrize(
    ("disposition", "blocked_by"),
    [
        ("allowed", [{"evidence_ref": "git:README", "reason": "README changed"}]),
        ("blocked", []),
        ("requires_authorization", []),
        ("wait", []),
    ],
)
def test_affordance_disposition_must_agree_with_its_blockers(
    bare_validator: Any, disposition: str, blocked_by: list[dict[str, str]]
) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    affordance = document["affordances"][0]
    affordance["disposition"] = disposition
    affordance["blocked_by"] = blocked_by
    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)


@pytest.mark.parametrize("fixture_name", sorted(FIXTURE_NAMES - {"quiet_no_change.json"}))
def test_blocker_links_resolve_to_the_affordances_own_evidence(fixture_name: str) -> None:
    assert _unresolved_blocker_links(_load(FIXTURE_DIR / fixture_name)) == []


def test_traces_exercise_blocker_links() -> None:
    linked = {
        link["evidence_ref"]
        for fixture_name in FIXTURE_NAMES - {"quiet_no_change.json"}
        for affordance in _load(FIXTURE_DIR / fixture_name)["affordances"]
        for link in affordance["blocked_by"]
    }
    assert linked == {"settlement:PR-2", "authorization:PR-3"}


def _blocker_link_mutations() -> list[Any]:
    def unrelated_text(affordance: dict[str, Any]) -> None:
        affordance["blocked_by"] = [
            {"evidence_ref": "zzz unrelated free text", "reason": "zzz unrelated free text"}
        ]

    def renamed_handle(affordance: dict[str, Any]) -> None:
        affordance["evidence_refs"][0]["id"] = "unrelated:handle"

    def another_records_handle(affordance: dict[str, Any]) -> None:
        affordance["blocked_by"][0]["evidence_ref"] = "lease:lease-1"

    def ambiguous_handle(affordance: dict[str, Any]) -> None:
        affordance["evidence_refs"].append(copy.deepcopy(affordance["evidence_refs"][0]))

    return [
        pytest.param(unrelated_text, id="unrelated-text"),
        pytest.param(renamed_handle, id="renamed-cited-handle"),
        pytest.param(another_records_handle, id="another-records-handle"),
        pytest.param(ambiguous_handle, id="ambiguous-cited-handle"),
    ]


@pytest.mark.parametrize("mutate", _blocker_link_mutations())
def test_unresolved_blocker_links_break_the_contract(bare_validator: Any, mutate: Any) -> None:
    """A link the schema accepts still has to name one of the affordance's own handles."""
    document = _load(FIXTURE_DIR / "interrupted_resumption.json")
    assert _unresolved_blocker_links(document) == []

    mutate(document["affordances"][0])
    bare_validator.validate(document)
    assert _unresolved_blocker_links(document)


@pytest.mark.parametrize(
    "link",
    [
        pytest.param("settlement:BLOCKED", id="bare-string"),
        pytest.param({"evidence_ref": "settlement:PR-2"}, id="no-reason"),
        pytest.param({"reason": "settlement is BLOCKED"}, id="no-evidence-ref"),
        pytest.param({"evidence_ref": "", "reason": "settlement is BLOCKED"}, id="empty-ref"),
        pytest.param({"evidence_ref": "settlement:PR-2", "reason": ""}, id="empty-reason"),
        pytest.param(
            {
                "evidence_ref": "settlement:PR-2",
                "reason": "settlement is BLOCKED",
                "work_id": "PR-2",
            },
            id="undeclared-field",
        ),
    ],
)
def test_blocker_links_are_structured(bare_validator: Any, link: Any) -> None:
    document = _load(FIXTURE_DIR / "interrupted_resumption.json")
    document["affordances"][0]["blocked_by"] = [link]
    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)


@pytest.mark.parametrize(("truncated", "omitted"), [(True, []), (False, ["beliefs"])])
def test_truncation_flag_must_agree_with_omissions(
    bare_validator: Any, truncated: bool, omitted: list[str]
) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["truncation"]["truncated"] = truncated
    document["truncation"]["omitted"] = omitted
    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)


def test_every_envelope_collection_is_classified_for_truncation(bare_validator: Any) -> None:
    envelope = bare_validator.schema["$defs"]["fullEnvelope"]["properties"]
    collections = {
        name
        for name, rule in envelope.items()
        if rule.get("type") == "array" and rule.get("maxItems") != 0
    }
    assert collections == {*OMITTABLE_COLLECTIONS, *NEVER_OMITTED_COLLECTIONS}
    omitted = bare_validator.schema["$defs"]["truncation"]["properties"]["omitted"]
    assert omitted["items"]["enum"] == list(OMITTABLE_COLLECTIONS)


@pytest.mark.parametrize("collection", OMITTABLE_COLLECTIONS)
def test_truncation_may_omit_derived_guidance(bare_validator: Any, collection: str) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document[collection] = []
    document["truncation"]["truncated"] = True
    document["truncation"]["omitted"] = [collection]
    bare_validator.validate(document)


@pytest.mark.parametrize("collection", NEVER_OMITTED_COLLECTIONS)
def test_truncation_never_omits_a_blocker_bearing_collection(
    bare_validator: Any, collection: str
) -> None:
    """Dropping the only live blocker must not leave the ready recommendation standing."""
    document = _load(FIXTURE_DIR / "interrupted_resumption.json")
    assert document["work_recommendations"][0]["classification"] == "ready"
    document[collection] = []
    document["truncation"]["truncated"] = True
    document["truncation"]["omitted"] = [collection]
    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)


@pytest.mark.parametrize(
    "omitted",
    [
        pytest.param(["anything at all"], id="free-text"),
        pytest.param([""], id="empty-name"),
        pytest.param(["Beliefs"], id="wrong-case"),
        pytest.param(["mission"], id="mission-object"),
        pytest.param(["nomic"], id="nomic-object"),
        pytest.param(["beliefs", "anything at all"], id="mixed"),
        pytest.param(["beliefs", "beliefs"], id="repeated"),
        pytest.param(["affordances", "obligations", "source_health"], id="all-blocker-collections"),
    ],
)
def test_truncation_omissions_use_the_closed_vocabulary(
    bare_validator: Any, omitted: list[str]
) -> None:
    document = _load(FIXTURE_DIR / "interrupted_resumption.json")
    document["truncation"]["truncated"] = True
    document["truncation"]["omitted"] = omitted
    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)


def test_verified_nomic_state_requires_an_exact_commit_and_refs(bare_validator: Any) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["nomic"] = _nomic("verified")
    document["nomic"]["exact_commit_match"] = False
    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)

    document["nomic"]["exact_commit_match"] = True
    bare_validator.validate(document)

    for required_ref in ("pack_ref", "receipt_ref"):
        missing = copy.deepcopy(document)
        del missing["nomic"][required_ref]
        with pytest.raises(jsonschema.ValidationError):
            bare_validator.validate(missing)

    del document["nomic"]["result_ref"]
    bare_validator.validate(document)


@pytest.mark.parametrize("state", ["verified", "stale", "invalid"])
def test_nomic_refs_accept_commit_evidence_handles(bare_validator: Any, state: str) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["nomic"] = _nomic(state)
    bare_validator.validate(document)


@pytest.mark.parametrize("ungrounded", _ungrounded_nomic_refs())
@pytest.mark.parametrize("ref", NOMIC_REFS)
@pytest.mark.parametrize("state", ["verified", "stale", "invalid"])
def test_nomic_refs_must_be_commit_evidence_handles(
    bare_validator: Any, state: str, ref: str, ungrounded: Any
) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["nomic"] = _nomic(state)
    bare_validator.validate(document)

    document["nomic"][ref] = copy.deepcopy(ungrounded)
    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)


@pytest.mark.parametrize("weaker_status", ["stale", "unknown"])
@pytest.mark.parametrize("ref", NOMIC_REFS)
def test_verified_nomic_cites_only_fresh_commit_evidence(
    bare_validator: Any, ref: str, weaker_status: str
) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["nomic"] = _nomic("verified")
    bare_validator.validate(document)

    document["nomic"][ref]["freshness"]["status"] = weaker_status
    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)


@pytest.mark.parametrize("state", ["absent", "stale", "invalid"])
def test_only_a_verified_nomic_state_may_claim_an_exact_commit(
    bare_validator: Any, state: str
) -> None:
    document = _load(FIXTURE_DIR / "fresh_orientation.json")
    document["nomic"] = _nomic(state)
    bare_validator.validate(document)

    document["nomic"]["exact_commit_match"] = True
    with pytest.raises(jsonschema.ValidationError):
        bare_validator.validate(document)


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
    assert affordance["blocked_by"] == [
        {"evidence_ref": affordance["evidence_refs"][0]["id"], "reason": "settlement is BLOCKED"}
    ]


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
    assert affordance["blocked_by"] == [
        {"evidence_ref": "authorization:PR-3", "reason": "missing human authorization"}
    ]
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


def _glob_matches(pattern: str, path: str) -> bool:
    # GitHub's `**` spans directory separators, which is exactly what fnmatch's
    # single `*` already does, so collapsing the two is faithful here.
    return fnmatch.fnmatchcase(path, pattern.replace("**", "*"))


def _infra_shard(workflow: dict[str, Any]) -> dict[str, Any]:
    categories = workflow["jobs"]["test-fast"]["strategy"]["matrix"]["category"]
    return next(entry for entry in categories if entry["name"] == "infra")


@pytest.mark.parametrize(
    "changed_path", ["tests/orientation/test_orientation_contract.py", SCHEMA_PATH_IN_REPO]
)
def test_pull_request_ci_runs_this_suite_for_its_own_sources(changed_path: str) -> None:
    """A shard filter is inert unless the workflow trigger admits the same path."""
    workflow = yaml.safe_load(TEST_WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML resolves the unquoted `on:` key to the boolean True.
    triggers = workflow[True]["pull_request"]["paths"]
    assert any(_glob_matches(pattern, changed_path) for pattern in triggers), (
        f"{changed_path} does not trigger the Tests workflow at all"
    )

    infra = _infra_shard(workflow)
    scope_step = next(
        step
        for step in workflow["jobs"]["test-shard-scope"]["steps"]
        if "filters" in (step.get("with") or {})
    )
    filters = yaml.safe_load(scope_step["with"]["filters"])
    assert any(_glob_matches(pattern, changed_path) for pattern in filters[infra["scope"]])
    assert "tests/orientation" in infra["pytest_args"].split()
