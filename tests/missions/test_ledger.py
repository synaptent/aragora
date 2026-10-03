"""Tests for the stigmergic Ledger — atomic claims, evaporation, and the
constraint-driven anti-treadmill that the worker swarm relies on.

Time is injected via ``now=`` so the lease/constraint TTL logic is deterministic.
"""

from __future__ import annotations

import pytest

from aragora.missions.ledger import Ledger, LedgerCorruptError, select_for
from aragora.missions.state import Feature, MissionState


def _ledger(tmp_path):
    return Ledger(tmp_path / "ledger.json")


def test_atomic_claim_excludes_other_worker(tmp_path):
    led = _ledger(tmp_path)
    assert led.claim("u1", "w1", now=100.0) is True
    assert led.claim("u1", "w2", now=101.0) is False  # w2 cannot steal a live claim
    assert led.active_claims(now=101.0) == {"u1": "w1"}


def test_reclaim_own_lease_is_idempotent(tmp_path):
    led = _ledger(tmp_path)
    assert led.claim("u1", "w1", now=100.0) is True
    assert led.claim("u1", "w1", now=200.0) is True  # same worker re-claims fine


def test_expired_lease_evaporates_and_is_reclaimable(tmp_path):
    led = _ledger(tmp_path)
    led.claim("u1", "w1", ttl=30.0, now=100.0)
    # 40s later the lease is dead -> a different worker can claim it
    assert led.claim("u1", "w2", now=140.0) is True
    assert led.active_claims(now=140.0) == {"u1": "w2"}


def test_release(tmp_path):
    led = _ledger(tmp_path)
    led.claim("u1", "w1", now=100.0)
    led.release("u1", "w1")
    assert led.active_claims(now=100.0) == {}
    # a non-owner release is a no-op
    led.claim("u1", "w1", now=100.0)
    led.release("u1", "w2")
    assert led.active_claims(now=100.0) == {"u1": "w1"}


def test_constraint_excludes_then_invalidates(tmp_path):
    led = _ledger(tmp_path)
    led.record_constraint("feature:x", "tier-3 needs operator", now=100.0)
    assert led.is_excluded("feature:x", now=100.0) is True
    led.invalidate_constraint("feature:x")  # live state changed
    assert led.is_excluded("feature:x", now=100.0) is False


def test_invalidate_resets_attempt_budget(tmp_path):
    """grok [P2]: invalidating a park must also reset its attempt count, or the
    'invalidate and retry' path re-parks on the very first next failure."""
    led = _ledger(tmp_path)
    led.bump_attempt("feature:x")
    led.bump_attempt("feature:x")  # at/over a park threshold of 2
    led.record_constraint("feature:x", "parked: 2 blocks", now=100.0)
    led.invalidate_constraint("feature:x")  # live state changed → give a fresh budget
    assert led.is_excluded("feature:x", now=100.0) is False
    assert led.attempts("feature:x") == 0  # budget reset, not inherited


def test_records_and_reads_discoveries(tmp_path):
    """Swarm-discovered work is recorded to the locked ledger as advisory notes."""
    led = _ledger(tmp_path)
    led.record_discovery("f1", "a stale assertion")
    led.record_discovery("f1", "a stale assertion")  # deduped
    led.record_discovery("f1", "another note")
    assert led.discoveries() == {"f1": ["a stale assertion", "another note"]}


def test_complete_records_done_and_releases_atomically(tmp_path):
    """The [P1] fix: complete() marks done, folds notes, AND drops the lease under a
    single lock — so there is no released-but-not-done window to re-claim."""
    led = _ledger(tmp_path)
    led.claim("u1", "w1", now=100.0)
    assert led.complete("u1", "w1", discoveries=["found x"], now=100.0) is True
    assert led.is_done("u1") is True
    assert led.active_claims(now=100.0) == {}  # lease dropped in the same transaction
    assert led.discoveries() == {"u1": ["found x"]}
    # A concurrent worker cannot claim it afterward — it is done.
    assert led.claim_actionable("u1", "w2", constraint_key="feature:u1") is False


def test_invalidate_done_removes_stale_completion(tmp_path):
    led = _ledger(tmp_path)
    led.record_done("u1")

    assert led.invalidate_done("u1") is True
    assert led.is_done("u1") is False
    assert led.invalidate_done("u1") is False


def test_complete_refuses_lost_lease(tmp_path):
    """A worker whose lease expired and was claimed by another worker must not record
    a stale success outcome after its dispatch returns."""
    led = _ledger(tmp_path)
    led.claim("u1", "w1", ttl=1.0, now=100.0)
    assert led.claim("u1", "w2", now=102.0) is True
    assert led.complete("u1", "w1", discoveries=["stale success"]) is False
    assert led.is_done("u1") is False
    assert led.discoveries() == {}
    assert led.active_claims(now=102.0) == {"u1": "w2"}


def test_complete_refuses_expired_lease_without_new_owner(tmp_path):
    led = _ledger(tmp_path)
    led.claim("u1", "w1", ttl=1.0, now=100.0)
    assert led.complete("u1", "w1", discoveries=["stale success"], now=102.0) is False
    assert led.is_done("u1") is False
    assert led.discoveries() == {}
    assert led.active_claims(now=102.0) == {}


def test_fail_records_park_and_release_atomically(tmp_path):
    """A repeated blocker should become parked in the same locked transaction that
    releases its lease, so no extra claimant can slip in between release and park."""
    led = _ledger(tmp_path)
    led.claim("u1", "w1", now=100.0)
    assert (
        led.fail(
            "u1",
            "w1",
            discoveries=["blocked note"],
            constraint_key="feature:u1",
            constraint_reason="parked: persistent",
            now=101.0,
        )
        is True
    )
    assert led.active_claims(now=101.0) == {}
    assert led.is_excluded("feature:u1", now=101.0) is True
    assert led.claim_actionable("u1", "w2", constraint_key="feature:u1", now=101.0) is False
    assert led.discoveries() == {"u1": ["blocked note"]}


def test_fail_refuses_lost_lease(tmp_path):
    led = _ledger(tmp_path)
    led.claim("u1", "w1", ttl=1.0, now=100.0)
    assert led.claim("u1", "w2", now=102.0) is True
    assert (
        led.fail(
            "u1",
            "w1",
            discoveries=["stale failure"],
            constraint_key="feature:u1",
            constraint_reason="parked stale",
            now=102.0,
        )
        is False
    )
    assert led.is_excluded("feature:u1", now=102.0) is False
    assert led.discoveries() == {}
    assert led.active_claims(now=102.0) == {"u1": "w2"}


def test_fail_refuses_expired_lease_without_new_owner(tmp_path):
    led = _ledger(tmp_path)
    led.claim("u1", "w1", ttl=1.0, now=100.0)
    assert (
        led.fail(
            "u1",
            "w1",
            discoveries=["stale failure"],
            constraint_key="feature:u1",
            constraint_reason="parked stale",
            now=102.0,
        )
        is False
    )
    assert led.is_excluded("feature:u1", now=102.0) is False
    assert led.discoveries() == {}
    assert led.active_claims(now=102.0) == {}


def test_constraint_ttl_evaporates(tmp_path):
    led = _ledger(tmp_path)
    led.record_constraint("feature:x", "transient", ttl=60.0, now=100.0)
    assert led.is_excluded("feature:x", now=130.0) is True
    assert led.is_excluded("feature:x", now=200.0) is False


def test_attempts_and_prune(tmp_path):
    led = _ledger(tmp_path)
    assert led.bump_attempt("feature:x") == 1
    assert led.bump_attempt("feature:x") == 2
    assert led.attempts("feature:x") == 2
    led.claim("u1", "w1", ttl=10.0, now=100.0)
    led.record_constraint("c1", "old", ttl=5.0, now=100.0)
    dead_leases, dead_constraints = led.prune(now=200.0)
    assert (dead_leases, dead_constraints) == (1, 1)


def _mission(n=4):
    return MissionState(
        mission_id="t",
        goal="g",
        milestones=["m1"],
        features=[Feature(id=f"f{i}", description="", milestone="m1") for i in range(1, n + 1)],
    )


def test_two_workers_self_partition_no_overlap(tmp_path):
    """Non-overlapping fronts emerge with no dispatcher: each worker claims a
    distinct unit off the same queue."""
    state = _mission(4)
    led = _ledger(tmp_path)
    a = select_for(state, led, "wA", now=100.0)
    b = select_for(state, led, "wB", now=100.0)
    c = select_for(state, led, "wC", now=100.0)
    assert a == "f1" and b == "f2" and c == "f3"  # three workers, three distinct units
    assert len({a, b, c}) == 3  # zero collisions


def test_select_skips_parked_feature(tmp_path):
    """The anti-treadmill rule your Codex prompt couldn't enforce: a parked unit
    is skipped because the exclusion lives in the shared environment."""
    state = _mission(2)
    led = _ledger(tmp_path)
    led.record_constraint("feature:f1", "parked: repeated blocker", now=100.0)
    assert select_for(state, led, "wA", now=100.0) == "f2"  # f1 is skipped, not re-attempted


def test_claim_actionable_refuses_done_and_parked(tmp_path):
    """The atomic check-and-claim: a done or parked unit can't be claimed even if a
    stale select snapshot thought it was free."""
    led = _ledger(tmp_path)
    led.record_done("u1")
    assert led.claim_actionable("u1", "w1", constraint_key="feature:u1") is False
    led.record_constraint("feature:u2", "parked")
    assert led.claim_actionable("u2", "w1", constraint_key="feature:u2") is False
    assert led.claim_actionable("u3", "w1", constraint_key="feature:u3") is True  # free → claimed


def test_concurrent_claims_exactly_one_wins(tmp_path):
    """The load-bearing property under real concurrency: 20 threads race for one
    unit through the file lock; exactly one wins (no double-claim)."""
    import threading

    led = _ledger(tmp_path)
    results: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(20)

    def grab(i: int) -> None:
        barrier.wait()  # maximize the race
        won = led.claim("u1", f"w{i}")
        with lock:
            results.append(won)

    threads = [threading.Thread(target=grab, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == 1  # exactly one claimer wins the unit
    assert len(led.active_claims()) == 1


def test_select_claims_orphaned_in_progress_when_owner_fence_is_clear(tmp_path):
    """grok [P2]: with no live orchestrator holding the owner fence, a swarm worker
    may reclaim an IN_PROGRESS checkpoint left behind by a crashed orchestrator."""
    from aragora.missions.state import Status

    state = _mission(2)
    state.features[0].status = Status.IN_PROGRESS
    led = _ledger(tmp_path)
    assert select_for(state, led, "wA", now=100.0) == "f1"


def test_select_claims_awaiting_claim_features(tmp_path):
    """AWAITING_CLAIM is the intake bridge's claimable-wait state (#8758 round-2
    P1): a decomposed child waiting for a worker/branch must be claimable by the
    ordinary stigmergic pickup, with zero manual status resets."""
    from aragora.missions.state import Status

    state = _mission(2)
    state.features[0].status = Status.AWAITING_CLAIM
    led = _ledger(tmp_path)
    assert select_for(state, led, "wA", now=100.0) == "f1"


def test_ledger_load_tolerates_unknown_fields(tmp_path):
    """[P3] forward-compat: a ledger written by a newer schema (extra lease/
    constraint fields) loads instead of crashing with TypeError."""
    import json

    led = _ledger(tmp_path)
    led.claim("u1", "w1", now=100.0)
    led.record_constraint("feature:x", "parked", now=100.0)
    raw = json.loads(led.path.read_text())
    raw["leases"]["u1"]["future_lease_field"] = 1
    raw["constraints"]["feature:x"]["future_constraint_field"] = "x"
    led.path.write_text(json.dumps(raw))
    # Re-reads cleanly, dropping the unknown keys.
    assert led.active_claims(now=100.0) == {"u1": "w1"}
    assert led.is_excluded("feature:x", now=100.0) is True


def test_ledger_corrupt_json_raises_domain_error(tmp_path):
    led = _ledger(tmp_path)
    led.path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(LedgerCorruptError, match="corrupt ledger JSON"):
        led.done_units()


def test_select_respects_preconditions(tmp_path):
    state = MissionState(
        mission_id="t",
        goal="g",
        milestones=["m1"],
        features=[
            Feature(id="a", description="", milestone="m1", preconditions=["feature:b"]),
            Feature(id="b", description="", milestone="m1"),
        ],
    )
    led = _ledger(tmp_path)
    assert select_for(state, led, "wA", now=100.0) == "b"  # gated 'a' is not claimable yet


def test_select_treats_unknown_preconditions_as_unmet(tmp_path):
    state = MissionState(
        mission_id="t",
        goal="g",
        milestones=["m1"],
        features=[
            Feature(id="a", description="", milestone="m1", preconditions=["assertion:ready"]),
            Feature(id="b", description="", milestone="m1"),
        ],
    )
    led = _ledger(tmp_path)
    assert select_for(state, led, "wA", now=100.0) == "b"
