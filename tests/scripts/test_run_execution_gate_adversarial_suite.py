from __future__ import annotations

from scripts import run_execution_gate_adversarial_suite as suite


def test_run_suite_passes_with_current_baseline() -> None:
    failures, rows = suite.run_suite()
    assert failures == 0
    assert rows
    assert all(row["status"] == "pass" for row in rows)


def test_run_suite_detects_regression(monkeypatch) -> None:
    class _AlwaysAllow:
        allow_auto_execution = True
        reason_codes: list[str] = []

    monkeypatch.setattr(
        suite,
        "evaluate_auto_execution_safety",
        lambda *_args, **_kwargs: _AlwaysAllow(),
    )

    failures, rows = suite.run_suite()
    assert failures > 0
    assert any(row["status"] == "fail" for row in rows)
