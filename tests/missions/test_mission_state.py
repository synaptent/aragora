"""Tests for the Phase-A mission spine: state + the survivable tick loop.

The load-bearing test is ``test_crash_mid_feature_resumes_no_loss`` — it proves
the whole reason the engine exists: kill it mid-feature, relaunch, finish with no
lost and no double-done work.
"""

from __future__ import annotations

import pytest

from aragora.missions import Feature, Handoff, MissionOrchestrator, MissionState, Status


def _mission(n: int = 3, milestone: str = "m1") -> MissionState:
    return MissionState(
        mission_id="test",
        goal="prove the spine",
        milestones=[milestone],
        features=[
            Feature(id=f"f{i}", description=f"feat {i}", milestone=milestone)
            for i in range(1, n + 1)
        ],
    )


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    _mission().save(p)
    loaded = MissionState.load(p)
    assert loaded.mission_id == "test"
    assert [f.id for f in loaded.features] == ["f1", "f2", "f3"]
    assert all(f.status == Status.PENDING for f in loaded.features)


def test_feature_metadata_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    mission = _mission(1)
    mission.get("f1").metadata = {
        "branch": "codex/native-mission-engine",
        "pr": 8625,
        "tier": 2,
        "paths": ["aragora/missions/state.py"],
        "autonomy": "auto-drain",
    }

    mission.save(p)

    loaded = MissionState.load(p)
    assert loaded.get("f1").metadata == mission.get("f1").metadata


def test_concurrent_saves_never_tear(tmp_path):
    """Atomic os.replace means a reader never sees a torn/partial file even under
    concurrent saves (the real torn-read guarantee; concurrent *writers* are an
    error caught by the owner fence, tested separately)."""
    import threading

    p = tmp_path / "state.json"
    _mission(3).save(p)
    barrier = threading.Barrier(12)

    def writer(i: int) -> None:
        m = MissionState.load(p)
        m.goal = f"writer-{i}"
        barrier.wait()  # maximize the race on the same file
        m.save(p)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Never corrupt: load succeeds and the doc is one writer's complete document.
    final = MissionState.load(p)
    assert final.goal.startswith("writer-")
    assert [f.id for f in final.features] == ["f1", "f2", "f3"]


def test_owner_fence_refuses_second_writer(tmp_path):
    """The honest single-writer fence: a second driver on the same mission fails
    fast with MissionOwnershipError instead of silently double-dispatching."""
    from aragora.missions.state import MissionOwnershipError, mission_owner_lock

    p = tmp_path / "state.json"
    _mission(2).save(p)
    with mission_owner_lock(p):  # first owner holds it
        with pytest.raises(MissionOwnershipError):
            with mission_owner_lock(p):  # second owner is refused
                pass
    # Once released, a new owner can acquire cleanly.
    with mission_owner_lock(p):
        pass


def test_owner_fence_fails_closed_when_fcntl_unavailable(tmp_path, monkeypatch):
    """Without POSIX fcntl, the mission must not silently drive unfenced."""
    import aragora.missions.state as state_mod
    from aragora.missions.state import MissionOwnershipError, mission_owner_lock

    p = tmp_path / "state.json"
    _mission(1).save(p)
    monkeypatch.setattr(state_mod, "fcntl", None)
    with pytest.raises(MissionOwnershipError, match="requires POSIX fcntl"):
        with mission_owner_lock(p):
            pass


def test_run_holds_owner_fence_against_concurrent_orchestrator(tmp_path):
    """run() holds the fence for its whole duration: a second orchestrator that
    tries to start mid-run is refused, not allowed to race next_pending."""
    from aragora.missions.state import MissionOwnershipError

    p = tmp_path / "state.json"
    _mission(2).save(p)
    other = MissionOrchestrator(p)

    def dispatch_that_probes_a_second_orchestrator(feat):
        # While THIS run owns the fence, a second run() must fail fast.
        with pytest.raises(MissionOwnershipError):
            other.run(lambda f: Handoff(success=True))
        return Handoff(success=True)

    done, total = MissionOrchestrator(p).run(dispatch_that_probes_a_second_orchestrator)
    assert (done, total) == (2, 2)  # the owning run still completes normally


def test_shared_and_exclusive_fence_make_modes_exclusive(tmp_path):
    """The shared/exclusive lock: many workers (shared) coexist, but an orchestrator
    (exclusive) and a swarm worker (shared) are mutually exclusive."""
    from aragora.missions.state import MissionOwnershipError, mission_owner_lock

    p = tmp_path / "state.json"
    _mission(2).save(p)

    # Two workers (shared) can hold the mission at once.
    with mission_owner_lock(p, exclusive=False):
        with mission_owner_lock(p, exclusive=False):  # second worker: allowed
            # ...but an orchestrator (exclusive) is refused while a worker holds it.
            with pytest.raises(MissionOwnershipError):
                with mission_owner_lock(p, exclusive=True):
                    pass

    # And a worker is refused while an orchestrator (exclusive) holds it.
    with mission_owner_lock(p, exclusive=True):
        with pytest.raises(MissionOwnershipError):
            with mission_owner_lock(p, exclusive=False):
                pass


def test_public_tick_is_fenced(tmp_path):
    """grok [P2]: the public tick() acquires the exclusive fence itself, so even a
    hand-rolled tick loop is protected — not only run()."""
    from aragora.missions.state import MissionOwnershipError, mission_owner_lock

    p = tmp_path / "state.json"
    _mission(1).save(p)
    orch = MissionOrchestrator(p)
    with mission_owner_lock(p, exclusive=True):  # someone else owns the mission
        with pytest.raises(MissionOwnershipError):
            orch.tick(lambda feat: Handoff(success=True))


def test_owner_fence_fails_closed_without_fcntl(tmp_path, monkeypatch):
    """Non-POSIX platforms must not silently disable the owner fence."""
    import aragora.missions.state as state_module
    from aragora.missions.state import MissionOwnershipError, mission_owner_lock

    p = tmp_path / "state.json"
    _mission(1).save(p)
    monkeypatch.setattr(state_module, "fcntl", None)
    with pytest.raises(MissionOwnershipError, match="requires POSIX fcntl"):
        with mission_owner_lock(p):
            pass


def test_load_tolerates_unknown_fields_from_newer_schema(tmp_path):
    """[P3] forward-compat: state written by a newer schema with an extra feature
    field loads (dropping the unknown key) instead of crashing with TypeError."""
    import json

    p = tmp_path / "state.json"
    _mission(1).save(p)
    raw = json.loads(p.read_text())
    raw["features"][0]["future_field"] = "from a newer version"
    p.write_text(json.dumps(raw))
    loaded = MissionState.load(p)  # must not raise
    assert loaded.get("f1").description == "feat 1"


def test_next_pending_is_array_order():
    m = _mission()
    m.mark_completed("f1")
    assert m.next_pending().id == "f2"


def test_precondition_gating():
    m = MissionState(
        mission_id="t",
        goal="g",
        milestones=["m1"],
        features=[
            Feature(id="a", description="", milestone="m1", preconditions=["feature:b"]),
            Feature(id="b", description="", milestone="m1"),
        ],
    )
    # 'a' is gated on 'b'; b must come first even though a is earlier in the list.
    assert m.next_pending().id == "b"
    m.mark_completed("b")
    assert m.next_pending().id == "a"


def test_unknown_precondition_is_not_silently_satisfied():
    m = MissionState(
        mission_id="t",
        goal="g",
        milestones=["m1"],
        features=[
            Feature(id="a", description="", milestone="m1", preconditions=["assertion:ready"]),
            Feature(id="b", description="", milestone="m1"),
        ],
    )
    assert m.next_pending().id == "b"


def test_run_marks_unknown_precondition_deadlock_blocked(tmp_path):
    """Unsupported precondition tokens must be operator-visible, not silent drain."""
    p = tmp_path / "state.json"
    MissionState(
        mission_id="t",
        goal="g",
        milestones=["m1"],
        features=[
            Feature(
                id="a",
                description="needs assertion",
                milestone="m1",
                preconditions=["assertion:ready"],
            )
        ],
    ).save(p)

    done, total = MissionOrchestrator(p).run(lambda feat: Handoff(success=True))

    assert (done, total) == (0, 1)
    final = MissionState.load(p)
    assert final.get("a").status == Status.BLOCKED
    assert "assertion:ready" in final.get("a").notes


def test_public_tick_reconciles_ledger_when_configured(tmp_path):
    """A hand-rolled tick loop with ledger_path should still fold ledger-done work
    before dispatching, matching run()'s swarm→orchestrator handoff behavior."""
    from aragora.missions.ledger import Ledger

    p = tmp_path / "state.json"
    lp = tmp_path / "ledger.json"
    _mission(2).save(p)
    Ledger(lp).record_done("f1")
    seen: list[str] = []

    def dispatch(feat):
        seen.append(feat.id)
        return Handoff(success=True)

    assert MissionOrchestrator(p, ledger_path=lp).tick(dispatch) is True
    assert seen == ["f2"]
    final = MissionState.load(p)
    assert final.get("f1").status == Status.COMPLETED
    assert final.get("f2").status == Status.COMPLETED


def test_public_tick_reconciles_default_sibling_ledger(tmp_path):
    """The standard state.json/ledger.json layout must be safe without wiring."""
    from aragora.missions.ledger import Ledger

    p = tmp_path / "state.json"
    lp = tmp_path / "ledger.json"
    _mission(2).save(p)
    Ledger(lp).record_done("f1")
    seen: list[str] = []

    def dispatch(feat):
        seen.append(feat.id)
        return Handoff(success=True)

    assert MissionOrchestrator(p).tick(dispatch) is True
    assert seen == ["f2"]
    final = MissionState.load(p)
    assert final.get("f1").status == Status.COMPLETED
    assert final.get("f2").status == Status.COMPLETED


def test_corrupt_sibling_ledger_blocks_all_open_work(tmp_path):
    p = tmp_path / "state.json"
    lp = tmp_path / "ledger.json"
    state = _mission(4)
    state.get("f2").status = Status.IN_PROGRESS
    state.get("f3").status = Status.AWAITING_CLAIM
    state.get("f4").status = Status.PARKED
    state.save(p)
    lp.write_text("{not valid json", encoding="utf-8")

    assert MissionOrchestrator(p).tick(lambda feat: Handoff(success=True)) is False

    final = MissionState.load(p)
    assert all(feature.status == Status.BLOCKED for feature in final.features)
    assert "ledger reconcile failed closed" in final.get("f1").notes


def test_insert_followup_extends_queue():
    m = _mission(2)
    m.insert_feature(Feature(id="f1.5", description="follow", milestone="m1"), before="f2")
    assert [f.id for f in m.features] == ["f1", "f1.5", "f2"]
    with pytest.raises(ValueError, match="duplicate"):
        m.insert_feature(Feature(id="f1", description="dup", milestone="m1"))


def test_milestone_complete():
    m = _mission(2)
    assert not m.milestone_complete("m1")
    m.mark_completed("f1")
    m.mark_completed("f2")
    assert m.milestone_complete("m1")


def test_reclaim_orphaned_in_progress():
    m = _mission(2)
    m.mark_in_progress("f1", session_id="dead-worker")
    assert m.reclaim_in_progress() == ["f1"]
    assert m.get("f1").status == Status.PENDING
    # session id is retained for a future resume policy
    assert "dead-worker" in m.get("f1").worker_session_ids


def test_unknown_status_quarantines_to_blocked():
    """#8766 claude P3 (forward-compat): a state file written by a NEWER
    writer may carry statuses this reader does not know. The load must not
    hard-fail the whole mission; the single feature quarantines to BLOCKED
    (operator-recoverable) with the original status preserved in notes."""
    feat = Feature(id="x", description="", milestone="m1", status="bogus")
    assert feat.status == Status.BLOCKED
    assert "unknown status 'bogus'" in feat.notes


def test_run_drains_queue(tmp_path):
    p = tmp_path / "state.json"
    _mission(3).save(p)
    orch = MissionOrchestrator(p)
    done, total = orch.run(lambda feat: Handoff(success=True, session_id="w"))
    assert (done, total) == (3, 3)
    assert all(f.status == Status.COMPLETED for f in MissionState.load(p).features)


def test_handoff_followups_are_advisory_by_default(tmp_path):
    p = tmp_path / "state.json"
    _mission(1).save(p)

    def dispatch(feat: Feature) -> Handoff:
        return Handoff(
            success=True,
            discovered=["found a stale assertion"],
            follow_ups=[Feature(id="f1-followup", description="fix it", milestone="m1")],
        )

    MissionOrchestrator(p).run(dispatch)
    final = MissionState.load(p)
    assert {f.id for f in final.features} == {"f1"}
    notes = final.get("f1").notes
    assert "found a stale assertion" in notes
    assert "follow-up proposed: f1-followup" in notes


def test_accepted_handoff_followups_extend_queue(tmp_path):
    p = tmp_path / "state.json"
    state = _mission(1)
    state.get("f1").metadata["paths"] = ["aragora/missions"]
    state.save(p)

    def dispatch(feat: Feature) -> Handoff:
        return Handoff(
            success=True,
            accept_follow_ups=True,
            follow_ups=[Feature(id="f1-followup", description="fix it", milestone="m1")],
        )

    MissionOrchestrator(p).run(dispatch)
    final = MissionState.load(p)
    assert {f.id for f in final.features} == {"f1", "f1-followup"}
    assert final.get("f1-followup").metadata["paths"] == ["aragora/missions"]


def test_crash_mid_feature_resumes_no_loss(tmp_path):
    """THE exit test: kill mid-feature, relaunch, finish with no loss/dup.

    Models an *uncatchable* SIGKILL-class death with ``KeyboardInterrupt`` (a
    ``BaseException``, so the orchestrator's ``except Exception`` in-process guard
    does NOT swallow it — that guard is only for recoverable 402/poison raises). The
    true ``kill -9`` path is exercised by scripts/mission_resume_demo.py.
    """
    p = tmp_path / "state.json"
    _mission(4).save(p)

    completed_calls: list[str] = []

    def crashing_dispatch(feat: Feature) -> Handoff:
        if feat.id == "f3":
            raise KeyboardInterrupt  # uncatchable death mid-f3 (not the BLE001 guard)
        completed_calls.append(feat.id)
        return Handoff(success=True, session_id="w1")

    # First run: completes f1, f2, then dies inside f3.
    orch = MissionOrchestrator(p)
    with pytest.raises(KeyboardInterrupt):
        orch.run(crashing_dispatch)

    mid = MissionState.load(p)
    assert mid.get("f1").status == Status.COMPLETED
    assert mid.get("f2").status == Status.COMPLETED
    # f3 was checkpointed IN_PROGRESS before the crash — not lost, not completed.
    assert mid.get("f3").status == Status.IN_PROGRESS
    assert mid.get("f4").status == Status.PENDING

    # Second run on the SAME disk state with a healthy worker resumes cleanly.
    def healthy_dispatch(feat: Feature) -> Handoff:
        completed_calls.append(feat.id)
        return Handoff(success=True, session_id="w2")

    done, total = MissionOrchestrator(p).run(healthy_dispatch)
    assert (done, total) == (4, 4)

    # f1/f2 done exactly once; f3 retried once after the crash; f4 once. No dupes.
    assert completed_calls == ["f1", "f2", "f3", "f4"]


def test_orchestrator_caps_retries_instead_of_spinning(tmp_path):
    """A success=False handoff with no reason must NOT re-pick the same feature
    forever (the merge-gate-caught [P1])."""
    p = tmp_path / "state.json"
    _mission(2).save(p)
    calls: list[str] = []

    def always_fail_no_reason(feat):
        calls.append(feat.id)
        return Handoff(success=False)  # default blocked_reason=None — the dangerous case

    MissionOrchestrator(p, max_retries=3).run(always_fail_no_reason)
    final = MissionState.load(p)
    assert final.get("f1").status == Status.BLOCKED  # parked after the cap, not spinning
    assert final.get("f1").retry_count == 3
    assert calls == ["f1", "f1", "f1", "f2", "f2", "f2"]  # bounded: 3 each, not 10_000


def test_handoff_blocked_reason_defaults_to_failure(tmp_path):
    """A worker returning only blocked_reason must not be triaged as success."""
    p = tmp_path / "state.json"
    _mission(1).save(p)

    MissionOrchestrator(p, max_retries=1).run(lambda feat: Handoff(blocked_reason="needs operator"))

    final = MissionState.load(p)
    assert final.get("f1").status == Status.BLOCKED
    assert "needs operator" in final.get("f1").notes


def test_orchestrator_terminal_block_is_not_retried(tmp_path):
    p = tmp_path / "state.json"
    _mission(1).save(p)
    calls: list[str] = []

    def op_block(feat):
        calls.append(feat.id)
        return Handoff(success=False, terminal=True, blocked_reason="operator settlement required")

    MissionOrchestrator(p, max_retries=5).run(op_block)
    assert MissionState.load(p).get("f1").status == Status.BLOCKED
    assert calls == ["f1"]  # terminal fork — not retried 5x pointlessly


def test_orchestrator_bounds_a_raising_dispatch(tmp_path):
    """grok [P2]: a dispatch that RAISES (the real kill-9/402 case) must be bounded
    in-process — one raising callback must NOT abort the whole run() — and the
    feature parked after the crash cap, not re-picked forever via reclaim."""
    p = tmp_path / "state.json"
    _mission(2).save(p)
    raises: list[str] = []

    def always_raises(feat):
        raises.append(feat.id)
        raise RuntimeError("worker crashed mid-feature")

    # run() completes in ONE call despite every dispatch raising — no external
    # restart loop, no propagated exception.
    MissionOrchestrator(p, max_retries=2).run(always_raises)

    final = MissionState.load(p)
    # Both features reached the crash cap and are BLOCKED (not spinning), and the
    # loop advanced past f1 to f2 instead of dying on the first raise.
    assert final.get("f1").status == Status.BLOCKED
    assert final.get("f1").crash_count == 3
    assert final.get("f2").status == Status.BLOCKED
    assert raises.count("f1") == 3  # max_retries plus one idempotent confirmation attempt
    assert raises.count("f2") == 3  # the loop reached f2; one bad feature didn't abort it


def test_crashed_but_successful_dispatch_is_not_false_blocked(tmp_path):
    """grok's deep [P2]: a dispatch that SUCCEEDS but whose process dies before the
    triage save must be re-dispatched (idempotent) and confirmed, not BLOCKed by
    the crash cap. With in-process bounding this also resolves within one run()."""
    p = tmp_path / "state.json"
    _mission(1).save(p)
    attempts = {"n": 0}

    def crash_then_succeed(feat):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("crashed after doing the work, before save")
        return Handoff(success=True)  # idempotent re-dispatch confirms success

    MissionOrchestrator(p, max_retries=2).run(crash_then_succeed)

    # Crash bumped crash_count to 1; the re-dispatch succeeded → COMPLETED, not BLOCKED.
    assert MissionState.load(p).get("f1").status == Status.COMPLETED


def test_max_retry_crash_gets_one_idempotent_confirmation(tmp_path):
    """If work may have succeeded before dying at the crash cap, resume confirms it."""
    p = tmp_path / "state.json"
    _mission(1).save(p)
    attempts = {"n": 0}

    def crash_at_cap_then_confirm(feat):
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise RuntimeError("died after external work")
        return Handoff(success=True)

    MissionOrchestrator(p, max_retries=2).run(crash_at_cap_then_confirm)

    assert attempts["n"] == 3
    assert MissionState.load(p).get("f1").status == Status.COMPLETED


def test_discovered_notes_deduped_across_retries(tmp_path):
    p = tmp_path / "state.json"
    _mission(1).save(p)

    def fail_twice_then_pass(feat):
        done = feat.retry_count >= 2
        return Handoff(success=done, discovered=["same note"])

    MissionOrchestrator(p, max_retries=5).run(fail_twice_then_pass)
    notes = MissionState.load(p).get("f1").notes
    assert notes.count("discovered: same note") == 1  # not re-appended each retry
