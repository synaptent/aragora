"""Tests for AGT-03 per-market stake-cap graduation (sub-deliverable 5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from aragora.connectors.prediction_markets.manifold import (
    MANIFOLD_WRITE_FLAG,
    ManifoldBetAdapter,
    ManifoldError,
)
from aragora.connectors.prediction_markets.stake_caps import (
    CAP_GRADUATION_FLAG,
    StabilityRecord,
    StakeCapSchedule,
    cap_graduation_enabled,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _day(n: float) -> datetime:
    return T0 + timedelta(days=n)


def _record_with_first_bet_at_t0() -> StabilityRecord:
    rec = StabilityRecord()
    rec.record_bet(now=T0)
    return rec


def test_package_exports_and_plan_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    from aragora.connectors.prediction_markets import StakeCapSchedule as PkgSchedule

    assert PkgSchedule is StakeCapSchedule
    s = StakeCapSchedule()
    assert (s.initial_cap_mana, s.graduated_cap_mana, s.stability_period_days) == (50, 200, 30)
    monkeypatch.delenv(CAP_GRADUATION_FLAG, raising=False)
    assert cap_graduation_enabled() is False
    for value, expected in (("1", True), ("YES", True), ("0", False), ("", False)):
        monkeypatch.setenv(CAP_GRADUATION_FLAG, value)
        assert cap_graduation_enabled() is expected


def test_stability_clock_starts_at_first_bet_and_resets_on_incident() -> None:
    rec = StabilityRecord()
    assert rec.stable_since() is None and rec.stable_for(now=T0) is None
    rec.record_incident(now=T0)  # incident before any bet: still no stable run
    assert rec.stable_since() is None
    rec.record_bet(now=_day(1))
    rec.record_bet(now=_day(5))
    assert rec.bets == 2 and rec.stable_since() == _day(1)
    assert rec.stable_for(now=_day(11)) == timedelta(days=10)
    rec.record_incident(now=_day(20))
    assert rec.incidents == 2 and rec.stable_since() == _day(20)
    assert rec.stable_for(now=_day(25)) == timedelta(days=5)
    assert rec.stable_for(now=_day(19)) == timedelta(0)  # clamped on clock skew
    assert rec.stable_for(now=datetime(2026, 1, 26)) == timedelta(days=5)  # naive == UTC


def test_schedule_rejects_invalid_parameters() -> None:
    for kwargs in (
        {"initial_cap_mana": 0},
        {"initial_cap_mana": 60, "graduated_cap_mana": 50},
        {"stability_period_days": 0},
    ):
        with pytest.raises(ValueError):
            StakeCapSchedule(**kwargs)


def test_graduation_boundary_at_thirty_days() -> None:
    s = StakeCapSchedule()
    assert s.is_graduated(StabilityRecord(), now=_day(400)) is False
    rec = _record_with_first_bet_at_t0()
    assert [s.is_graduated(rec, now=_day(d)) for d in (29.99, 30, 45)] == [False, True, True]


def test_incident_defers_graduation_by_a_full_period() -> None:
    rec = _record_with_first_bet_at_t0()
    rec.record_incident(now=_day(40))
    s = StakeCapSchedule()
    assert s.is_graduated(rec, now=_day(69)) is False
    assert s.is_graduated(rec, now=_day(70)) is True


def test_effective_cap_requires_flag_and_stable_period(monkeypatch: pytest.MonkeyPatch) -> None:
    s = StakeCapSchedule()
    rec = _record_with_first_bet_at_t0()
    monkeypatch.delenv(CAP_GRADUATION_FLAG, raising=False)
    assert s.effective_per_market_cap(rec, now=_day(90)) == 50
    monkeypatch.setenv(CAP_GRADUATION_FLAG, "1")
    assert s.effective_per_market_cap(StabilityRecord(), now=_day(90)) == 50
    assert s.effective_per_market_cap(rec, now=_day(29)) == 50
    assert s.effective_per_market_cap(rec, now=_day(30)) == 200


_MARKET = json.dumps(
    {"id": "m1", "slug": "s", "question": "Q?", "creatorUsername": "a", "totalLiquidity": 100_000}
)


def _adapter(mp: pytest.MonkeyPatch, *, post_status: int = 200, **kw) -> ManifoldBetAdapter:
    def client(method: str, url: str, headers: dict, body: str | None = None) -> tuple[int, str]:
        if method == "GET" and url.endswith("market/m1"):
            return (200, _MARKET)
        if method == "POST" and url.endswith("bet"):
            return (post_status, json.dumps({"id": "b"}))
        return (404, "{}")

    mp.setenv(MANIFOLD_WRITE_FLAG, "1")
    kw.setdefault("per_day_cap_mana", 10_000)
    return ManifoldBetAdapter(http_client=client, api_key="k", **kw)


def _bet(a: ManifoldBetAdapter, stake: int, day: float) -> None:
    a.place_bet("m1", probability=0.5, stake_mana=stake, now=_day(day))


def test_adapter_cap_is_unchanged_without_schedule_or_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CAP_GRADUATION_FLAG, "1")
    plain = _adapter(monkeypatch)
    assert plain.cap_schedule is None
    assert plain._effective_per_market_cap(now=_day(90)) == 50
    monkeypatch.delenv(CAP_GRADUATION_FLAG, raising=False)
    scheduled = _adapter(
        monkeypatch,
        cap_schedule=StakeCapSchedule(),
        stability_record=_record_with_first_bet_at_t0(),
    )
    assert scheduled._effective_per_market_cap(now=_day(90)) == 50


def test_adapter_graduates_to_200_thirty_days_after_last_incident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CAP_GRADUATION_FLAG, "1")
    a = _adapter(
        monkeypatch,
        cap_schedule=StakeCapSchedule(),
        stability_record=_record_with_first_bet_at_t0(),
    )
    with pytest.raises(ManifoldError, match="cap=50"):
        _bet(a, 51, 10)  # cap violation on day 10 restarts the clock
    assert a.stability_record.incidents == 1
    assert a._effective_per_market_cap(now=_day(39)) == 50
    _bet(a, 150, 40)  # day 40 is 30 days after the last incident
    with pytest.raises(ManifoldError, match="cap=200"):
        _bet(a, 51, 40)


def test_record_tracks_bets_and_write_errors_but_not_validation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = _adapter(monkeypatch, cap_schedule=StakeCapSchedule())
    with pytest.raises(ManifoldError, match="probability"):
        a.place_bet("m1", probability=1.5, stake_mana=10, now=T0)
    assert a.stability_record.incidents == 0 and a.stability_record.first_bet_at is None
    _bet(a, 10, 0)
    assert a.stability_record.bets == 1 and a.stability_record.first_bet_at == T0

    failing = _adapter(monkeypatch, post_status=500, cap_schedule=StakeCapSchedule())
    with pytest.raises(ManifoldError, match="HTTP 500"):
        _bet(failing, 10, 2)
    assert failing.stability_record.incidents == 1
    assert failing.stability_record.last_incident_at == _day(2)
    assert failing.stability_record.bets == 0
