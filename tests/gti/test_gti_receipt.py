from aragora.gti.receipt import BeliefProvenance, validate_belief_provenance

NOW = "2026-06-06T12:00:00+00:00"


def _belief(**kw):
    base = dict(
        belief_id="b1",
        source="git rev-parse origin/main",
        as_of="2026-06-06T11:59:00+00:00",
        verification_method="git",
        freshness_ttl_seconds=300.0,
        was_revalidated_at_decision=False,
    )
    base.update(kw)
    return BeliefProvenance(**base)


def test_fresh_belief_is_valid():
    assert validate_belief_provenance([_belief()], NOW) == []


def test_missing_source_is_invalid():
    problems = validate_belief_provenance([_belief(source="")], NOW)
    assert any("missing" in p for p in problems)


def test_missing_as_of_is_invalid():
    problems = validate_belief_provenance([_belief(as_of="")], NOW)
    assert any("missing" in p for p in problems)


def test_missing_verification_method_is_invalid():
    problems = validate_belief_provenance([_belief(verification_method="")], NOW)
    assert problems == ["b1: missing verification_method provenance"]


def test_malformed_now_is_invalid_problem_not_exception():
    problems = validate_belief_provenance([_belief()], "not-a-timestamp")
    assert problems == ["now_iso: invalid ISO timestamp"]


def test_malformed_as_of_is_invalid_problem_not_exception():
    problems = validate_belief_provenance([_belief(as_of="not-a-timestamp")], NOW)
    assert problems == ["b1: invalid as_of timestamp"]


def test_mixed_naive_and_aware_timestamps_are_invalid_problem_not_exception():
    problems = validate_belief_provenance([_belief(as_of="2026-06-06T11:59:00")], NOW)
    assert problems == ["b1: as_of timestamp timezone must match now_iso"]


def test_future_as_of_is_invalid():
    problems = validate_belief_provenance([_belief(as_of="2026-06-06T12:01:00+00:00")], NOW)
    assert problems == ["b1: as_of timestamp is in the future"]


def test_non_positive_ttl_is_invalid():
    problems = validate_belief_provenance([_belief(freshness_ttl_seconds=0.0)], NOW)
    assert problems == ["b1: invalid freshness_ttl_seconds"]


def test_non_finite_ttl_is_invalid():
    problems = validate_belief_provenance([_belief(freshness_ttl_seconds=float("inf"))], NOW)
    assert problems == ["b1: invalid freshness_ttl_seconds"]


def test_revalidation_flag_must_be_boolean():
    problems = validate_belief_provenance([_belief(was_revalidated_at_decision="false")], NOW)
    assert problems == ["b1: invalid was_revalidated_at_decision"]


def test_past_ttl_without_revalidation_is_invalid():
    problems = validate_belief_provenance(
        [_belief(as_of="2026-06-06T11:00:00+00:00", freshness_ttl_seconds=300.0)], NOW
    )
    assert any("ttl" in p.lower() for p in problems)


def test_past_ttl_but_revalidated_is_valid():
    problems = validate_belief_provenance(
        [
            _belief(
                as_of="2026-06-06T11:00:00+00:00",
                freshness_ttl_seconds=300.0,
                was_revalidated_at_decision=True,
            )
        ],
        NOW,
    )
    assert problems == []


def test_huge_int_ttl_is_valid_not_overflow_error():
    problems = validate_belief_provenance([_belief(freshness_ttl_seconds=10**400)], NOW)
    assert problems == []


def test_huge_negative_int_ttl_is_invalid_problem_not_exception():
    problems = validate_belief_provenance([_belief(freshness_ttl_seconds=-(10**400))], NOW)
    assert problems == ["b1: invalid freshness_ttl_seconds"]
