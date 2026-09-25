from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import pytest

from aragora.evaluation.outcome_backed_analysis import ANALYSIS_CONTRACT_VERSION
from aragora.evaluation.outcome_backed_holdout import (
    HOLDOUT_CONTRACT_VERSION,
    MAX_HOLDOUT_EXPOSURES,
    HoldoutExposureLimitError,
    HoldoutLedgerError,
    OutcomeBackedHoldoutLedger,
    build_holdout_registry,
)
from aragora.evaluation.outcome_backed_scoring import SCORER_CONTRACT_VERSION


CORPUS_DIR = Path("docs/benchmarks/decision_quality/tranches")
EXPOSURE_TIME = datetime(2026, 8, 30, 23, tzinfo=timezone.utc)


def _record(
    ledger: OutcomeBackedHoldoutLedger,
    registry: dict[str, object],
    run_label: str,
) -> dict[str, object]:
    return ledger.record_exposure(
        registry=registry,
        registry_hash=str(registry["registry_hash"]),
        scorer_contract_version=SCORER_CONTRACT_VERSION,
        analysis_contract_version=ANALYSIS_CONTRACT_VERSION,
        run_label=run_label,
        purpose="uncontaminated holdout repetition",
        recorded_at=EXPOSURE_TIME,
    )


def test_real_frozen_holdout_registry_is_deterministic() -> None:
    first = build_holdout_registry(CORPUS_DIR)
    second = build_holdout_registry(CORPUS_DIR)

    assert first == second
    assert first["contract_version"] == HOLDOUT_CONTRACT_VERSION
    assert first["holdout_count"] == 8
    cases = first["cases"]
    assert isinstance(cases, list)
    assert [case["case_id"] for case in cases] == sorted(case["case_id"] for case in cases)
    assert len({case["case_outcome_sha256"] for case in cases}) == 8
    assert len(str(first["registry_hash"])) == 64


def test_registry_refuses_invalidated_corpus_copy(tmp_path) -> None:
    copied = tmp_path / "tranches"
    shutil.copytree(CORPUS_DIR, copied)
    target = copied / "business-operations-holdout-1.corpus.json"
    payload = json.loads(target.read_text())
    payload["cases"][0]["split"] = "development"
    target.write_text(json.dumps(payload, indent=2) + "\n")

    with pytest.raises(ValueError, match="corpus is invalid"):
        build_holdout_registry(copied)


def test_registry_hash_mismatch_fails_before_append(tmp_path) -> None:
    registry = build_holdout_registry(CORPUS_DIR)
    ledger = OutcomeBackedHoldoutLedger(tmp_path / "exposures.jsonl")

    with pytest.raises(ValueError, match="does not match"):
        ledger.record_exposure(
            registry=registry,
            registry_hash="0" * 64,
            scorer_contract_version=SCORER_CONTRACT_VERSION,
            analysis_contract_version=ANALYSIS_CONTRACT_VERSION,
            run_label="holdout-r1",
            purpose="first repetition",
            recorded_at=EXPOSURE_TIME,
        )
    assert not ledger.path.exists()


def test_exposure_cap_fails_closed_on_fourth_epoch(tmp_path) -> None:
    registry = build_holdout_registry(CORPUS_DIR)
    ledger = OutcomeBackedHoldoutLedger(tmp_path / "exposures.jsonl")

    for index in range(1, MAX_HOLDOUT_EXPOSURES + 1):
        _record(ledger, registry, f"holdout-r{index}")

    with pytest.raises(HoldoutExposureLimitError, match="already has 3 exposures"):
        _record(ledger, registry, "holdout-r4")
    snapshot = ledger.snapshot().to_dict()
    assert snapshot["event_count"] == 3
    assert snapshot["registries"] == [
        {
            "registry_hash": registry["registry_hash"],
            "exposure_count": 3,
            "remaining_exposures": 0,
            "run_labels": ["holdout-r1", "holdout-r2", "holdout-r3"],
        }
    ]


def test_duplicate_run_label_is_rejected(tmp_path) -> None:
    registry = build_holdout_registry(CORPUS_DIR)
    ledger = OutcomeBackedHoldoutLedger(tmp_path / "exposures.jsonl")
    _record(ledger, registry, "holdout-r1")

    with pytest.raises(HoldoutLedgerError, match="duplicate run label"):
        _record(ledger, registry, "holdout-r1")


@pytest.mark.parametrize("content", ["{}", "not-json\n", "\n"])
def test_corrupted_ledger_line_fails_closed(tmp_path, content: str) -> None:
    path = tmp_path / "exposures.jsonl"
    path.write_text(content)

    with pytest.raises(HoldoutLedgerError):
        OutcomeBackedHoldoutLedger(path).snapshot()


def test_hash_chain_detects_tampered_exposure(tmp_path) -> None:
    registry = build_holdout_registry(CORPUS_DIR)
    path = tmp_path / "exposures.jsonl"
    ledger = OutcomeBackedHoldoutLedger(path)
    _record(ledger, registry, "holdout-r1")
    event = json.loads(path.read_text())
    event["purpose"] = "contaminated"
    path.write_text(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")

    with pytest.raises(HoldoutLedgerError, match="event hash mismatch"):
        ledger.snapshot()


def test_explicit_utc_timestamp_and_frozen_contracts_are_required(tmp_path) -> None:
    registry = build_holdout_registry(CORPUS_DIR)
    ledger = OutcomeBackedHoldoutLedger(tmp_path / "exposures.jsonl")
    common = {
        "registry": registry,
        "registry_hash": str(registry["registry_hash"]),
        "scorer_contract_version": SCORER_CONTRACT_VERSION,
        "analysis_contract_version": ANALYSIS_CONTRACT_VERSION,
        "run_label": "holdout-r1",
        "purpose": "first repetition",
    }

    with pytest.raises(ValueError, match="explicit UTC"):
        ledger.record_exposure(**common, recorded_at=datetime(2026, 8, 30, 23))
    with pytest.raises(ValueError, match="frozen scorer"):
        ledger.record_exposure(
            **{**common, "scorer_contract_version": "future-scorer"},
            recorded_at=EXPOSURE_TIME,
        )


def test_concurrent_exposures_cannot_cross_cap(tmp_path) -> None:
    registry = build_holdout_registry(CORPUS_DIR)
    ledger = OutcomeBackedHoldoutLedger(tmp_path / "exposures.jsonl")

    def record(index: int) -> str:
        try:
            _record(ledger, registry, f"holdout-r{index}")
        except HoldoutExposureLimitError:
            return "blocked"
        return "recorded"

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = sorted(pool.map(record, range(1, 5)))

    assert outcomes == ["blocked", "recorded", "recorded", "recorded"]
    assert ledger.snapshot().event_count == MAX_HOLDOUT_EXPOSURES
