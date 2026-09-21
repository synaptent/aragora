"""Unit tests for DIC-23 Dialectical Runtime Loop (aragora.epistemic.runtime_loop)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aragora.epistemic.decay_monitor import DecayReason, DecaySignal
from aragora.epistemic.quarantine_policy import QuarantinePolicy
from aragora.epistemic.runtime_loop import (
    DialecticalEvent,
    DialecticalRuntimeError,
    _build_synthetic_crux_payload,
    dialectical_runtime_enabled,
    run_dialectical_loop,
)


def test_epistemic_imports_without_python311_utc_alias():
    # A fresh interpreter avoids package imports cached by test collection.
    probe = """
import datetime
import importlib

if hasattr(datetime, "UTC"):
    del datetime.UTC
for name in ("runtime_loop", "repair", "gardening", "genealogy", "genealogy_report"):
    module = importlib.import_module("aragora.epistemic." + name)
    assert module.UTC is datetime.timezone.utc, name
from aragora.epistemic.runtime_loop import dialectical_runtime_enabled
assert not dialectical_runtime_enabled()
"""
    env = dict(os.environ, ARAGORA_USE_SECRETS_MANAGER="false", AWS_EC2_METADATA_DISABLED="true")
    env.pop("ARAGORA_DIALECTICAL_RUNTIME_ENABLED", None)
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _signal(
    *,
    unit_id: str = "unit.test",
    integrity_score: float = 0.8,
    recommended_action: str = "report_only",
    reasons: list[DecayReason] | None = None,
) -> DecaySignal:
    return DecaySignal(
        code_unit_id=unit_id,
        integrity_score=integrity_score,
        reasons=reasons or [],
        recommended_action=recommended_action,
    )


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ARAGORA_DIALECTICAL_RUNTIME_ENABLED", raising=False)
        assert not dialectical_runtime_enabled()

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
    def test_truthy_values_enable_runtime(self, monkeypatch: pytest.MonkeyPatch, value: str):
        monkeypatch.setenv("ARAGORA_DIALECTICAL_RUNTIME_ENABLED", value)
        assert dialectical_runtime_enabled() is True

    def test_raises_when_flag_off_and_require_enabled(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ARAGORA_DIALECTICAL_RUNTIME_ENABLED", raising=False)
        with pytest.raises(DialecticalRuntimeError, match="ARAGORA_DIALECTICAL_RUNTIME_ENABLED"):
            run_dialectical_loop(_signal())

    def test_require_enabled_false_bypasses_flag(self):
        event = run_dialectical_loop(_signal(), require_enabled=False)
        assert isinstance(event, DialecticalEvent)

    def test_flag_on_allows_call(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ARAGORA_DIALECTICAL_RUNTIME_ENABLED", "1")
        event = run_dialectical_loop(_signal())
        assert isinstance(event, DialecticalEvent)


# ---------------------------------------------------------------------------
# Report-only (default) trace
# ---------------------------------------------------------------------------


class TestReportOnlyTrace:
    def test_event_fields_populated(self):
        sig = _signal(unit_id="unit.alpha", integrity_score=0.75)
        event = run_dialectical_loop(sig, require_enabled=False)

        assert event.code_unit_id == "unit.alpha"
        assert event.integrity_score == 0.75
        assert event.recommended_action == "report_only"
        assert event.repair_spec is None
        assert event.crux_probe_skipped is True
        assert event.prior_receipt_ids == ()
        assert event.created_at  # non-empty timestamp

    def test_event_id_has_drt_prefix(self):
        event = run_dialectical_loop(_signal(), require_enabled=False)
        assert event.event_id.startswith("drt_")

    def test_quarantine_action_for_healthy_unit(self):
        # integrity_score=0.8 → above default fail_closed_threshold (0.4)
        # recommended_action="report_only" → policy resolves to report_only
        event = run_dialectical_loop(_signal(integrity_score=0.8), require_enabled=False)
        assert event.quarantine_action == "report_only"

    def test_prior_receipt_ids_preserved(self):
        receipts = ["rcpt-001", "rcpt-002"]
        event = run_dialectical_loop(_signal(), prior_receipt_ids=receipts, require_enabled=False)
        assert event.prior_receipt_ids == tuple(receipts)

    def test_metadata_preserved(self):
        event = run_dialectical_loop(_signal(), metadata={"source": "test"}, require_enabled=False)
        assert event.metadata == {"source": "test"}

    def test_metadata_outer_mapping_is_immutable(self):
        event = run_dialectical_loop(_signal(), metadata={"source": "test"}, require_enabled=False)

        with pytest.raises(TypeError):
            event.metadata["source"] = "mutated"  # type: ignore[index]

    def test_to_dict_is_json_friendly(self):
        import json

        event = run_dialectical_loop(_signal(), require_enabled=False)
        d = event.to_dict()
        serialized = json.dumps(d)
        assert "drt_" in serialized
        assert "report_only" in serialized

    def test_to_dict_repair_spec_is_none(self):
        event = run_dialectical_loop(_signal(), require_enabled=False)
        assert event.to_dict()["repair_spec"] is None


# ---------------------------------------------------------------------------
# Repair-proposal path
# ---------------------------------------------------------------------------


class TestRepairProposal:
    def test_repair_spec_none_when_flag_false(self):
        sig = _signal(integrity_score=0.1, recommended_action="repair_required")
        event = run_dialectical_loop(sig, enable_repair_proposal=False, require_enabled=False)
        assert event.repair_spec is None

    def test_repair_spec_absent_when_policy_escalates_to_fail_closed(self):
        # score=0.1 is below default fail_closed_threshold=0.4, so the policy
        # escalates to fail_closed — NOT repair_required.  repair_spec must stay
        # None even when enable_repair_proposal=True.
        sig = _signal(integrity_score=0.1, recommended_action="repair_required")
        event = run_dialectical_loop(
            sig,
            code_unit_class="default",
            enable_repair_proposal=True,
            require_enabled=False,
        )
        assert event.quarantine_action == "fail_closed"
        assert event.repair_spec is None

    def test_repair_spec_produced_with_custom_policy(self):
        from aragora.epistemic.quarantine_policy import EscalationMap

        sig = _signal(integrity_score=0.5, recommended_action="repair_required")
        # Custom policy: repair_required stays repair_required, threshold=0.3
        policy = QuarantinePolicy(
            code_unit_class="custom",
            escalation_map=EscalationMap(
                report_only="report_only",
                repair_required="repair_required",
                fail_closed="fail_closed",
            ),
            fail_closed_threshold=0.3,
        )
        event = run_dialectical_loop(
            sig, policy=policy, enable_repair_proposal=True, require_enabled=False
        )
        assert event.repair_spec is not None
        assert event.repair_spec.code_unit_id == "unit.test"
        assert event.repair_spec.repair_kind == "report_only"
        assert event.quarantine_action == "repair_required"


# ---------------------------------------------------------------------------
# Policy resolution
# ---------------------------------------------------------------------------


class TestPolicyResolution:
    def test_explicit_policy_overrides_class(self):
        from aragora.epistemic.quarantine_policy import EscalationMap

        sig = _signal(integrity_score=0.9, recommended_action="report_only")
        policy = QuarantinePolicy(
            code_unit_class="strict",
            escalation_map=EscalationMap(),
            fail_closed_threshold=0.95,  # very strict: 0.9 → fail_closed
        )
        event = run_dialectical_loop(sig, policy=policy, require_enabled=False)
        assert event.quarantine_action == "fail_closed"

    def test_code_unit_class_live_dispatch(self):
        # live_dispatch policy has fail_closed_threshold=0.6; score=0.5 → fail_closed
        sig = _signal(integrity_score=0.5, recommended_action="report_only")
        event = run_dialectical_loop(sig, code_unit_class="live_dispatch", require_enabled=False)
        assert event.quarantine_action == "fail_closed"

    def test_code_unit_class_report_surface(self):
        # report_surface policy has fail_closed_threshold=0.3; score=0.5 → degrade
        sig = _signal(integrity_score=0.5, recommended_action="repair_required")
        event = run_dialectical_loop(sig, code_unit_class="report_surface", require_enabled=False)
        assert event.quarantine_action in {"degrade", "repair_required", "report_only"}


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_to_dict_keys(self):
        event = run_dialectical_loop(_signal(), require_enabled=False)
        d = event.to_dict()
        expected_keys = {
            "event_id",
            "code_unit_id",
            "integrity_score",
            "recommended_action",
            "quarantine_action",
            "crux_probe_skipped",
            "repair_spec",
            "prior_receipt_ids",
            "created_at",
            "metadata",
        }
        assert set(d.keys()) == expected_keys

    def test_integrity_score_rounded(self):
        sig = _signal(integrity_score=0.123456789)
        event = run_dialectical_loop(sig, require_enabled=False)
        d = event.to_dict()
        assert d["integrity_score"] == round(0.123456789, 4)

    def test_prior_receipt_ids_is_immutable_tuple(self):
        receipts = ["r1", "r2"]
        event = run_dialectical_loop(_signal(), prior_receipt_ids=receipts, require_enabled=False)
        # Stored as an immutable tuple
        assert isinstance(event.prior_receipt_ids, tuple)
        assert event.prior_receipt_ids == ("r1", "r2")
        # to_dict() returns a list for JSON-serializability
        d = event.to_dict()
        assert d["prior_receipt_ids"] == ["r1", "r2"]
        # Mutation of the original list does not affect the event
        receipts.append("r3")
        assert event.prior_receipt_ids == ("r1", "r2")

    def test_with_repair_spec_in_dict(self):
        from aragora.epistemic.quarantine_policy import EscalationMap

        sig = _signal(integrity_score=0.5, recommended_action="repair_required")
        policy = QuarantinePolicy(
            code_unit_class="custom",
            escalation_map=EscalationMap(
                report_only="report_only",
                repair_required="repair_required",
                fail_closed="fail_closed",
            ),
            fail_closed_threshold=0.3,
        )
        event = run_dialectical_loop(
            sig, policy=policy, enable_repair_proposal=True, require_enabled=False
        )
        d = event.to_dict()
        assert d["repair_spec"] is not None
        assert isinstance(d["repair_spec"], dict)
        assert "spec_id" in d["repair_spec"]


# ---------------------------------------------------------------------------
# Crux probe (DIC-23 + DIC-15 integration)
# Tests patch _attempt_crux_probe directly to avoid the pydantic-dependent
# cruxset_emission import chain (pre-existing CI gap; unrelated to this slice).
# ---------------------------------------------------------------------------

_FAKE_PROBE = {
    "cruxset_id": "fake-cs-001",
    "crux_count": 2,
    "top_crux_ids": ["crux.fake.001"],
    "convergence_barrier": 0.65,
}


# Sentinel for distinguishing "use the default fake probe" from "explicitly
# pass this value (including None)". Without this, ``probe_result or dict(_FAKE_PROBE)``
# short-circuited the ``probe_result=None`` case to the fake dict, making
# ``test_skipped_when_attempt_returns_none`` impossible to express truthfully.
_NO_PROBE_OVERRIDE: object = object()


def _probe_event(
    signal: DecaySignal | None = None,
    *,
    probe_result: dict | None | object = _NO_PROBE_OVERRIDE,
    extra_metadata: dict | None = None,
    question: str = "Is the proof still valid?",
) -> DialecticalEvent:
    import aragora.epistemic.runtime_loop as _m

    if probe_result is _NO_PROBE_OVERRIDE:
        patched_return: dict | None = dict(_FAKE_PROBE)
    else:
        # Explicit override (including ``probe_result=None``) is passed through
        # verbatim so callers can assert behaviour when the patched probe
        # returns ``None``.
        patched_return = probe_result  # type: ignore[assignment]
    with patch.object(_m, "_attempt_crux_probe", return_value=patched_return):
        return run_dialectical_loop(
            signal or _signal(),
            enable_crux_probe=True,
            crux_question=question,
            metadata=extra_metadata or {},
            require_enabled=False,
        )


class TestCruxProbe:
    """Gate and result verification for the crux-probe (DIC-23 + DIC-15) integration."""

    # --- disabled/skipped paths ---

    def test_skipped_by_default(self) -> None:
        e = run_dialectical_loop(_signal(), require_enabled=False)
        assert e.crux_probe_skipped is True
        assert "crux_probe" not in e.metadata

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"enable_crux_probe": False, "crux_question": "Q"},
            {"enable_crux_probe": True, "crux_question": None},
            {"enable_crux_probe": True, "crux_question": "   "},
        ],
    )
    def test_skipped_for_missing_or_empty_question(self, kwargs: dict) -> None:
        e = run_dialectical_loop(_signal(), **kwargs, require_enabled=False)
        assert e.crux_probe_skipped is True

    def test_skipped_when_attempt_returns_none(self) -> None:
        e = _probe_event(probe_result=None)
        assert e.crux_probe_skipped is True
        assert "crux_probe" not in e.metadata

    def test_skipped_when_attempt_raises(self) -> None:
        import aragora.epistemic.runtime_loop as _m

        with patch.object(_m, "_attempt_crux_probe", side_effect=RuntimeError("boom")):
            e = run_dialectical_loop(
                _signal(), enable_crux_probe=True, crux_question="Q", require_enabled=False
            )
        assert e.crux_probe_skipped is True

    # --- enabled paths ---

    def test_not_skipped_and_metadata_present(self) -> None:
        e = _probe_event()
        assert e.crux_probe_skipped is False
        assert "crux_probe" in e.metadata

    def test_metadata_summary_shape(self) -> None:
        e = _probe_event()
        cp = e.metadata["crux_probe"]
        assert cp["cruxset_id"] == "fake-cs-001"
        assert cp["crux_count"] == 2
        assert isinstance(cp["top_crux_ids"], list)
        assert cp["convergence_barrier"] == 0.65

    def test_does_not_overwrite_existing_metadata(self) -> None:
        e = _probe_event(extra_metadata={"source": "caller"})
        assert e.metadata["source"] == "caller"
        assert e.metadata["crux_probe"]["cruxset_id"] == "fake-cs-001"

    def test_to_dict_reflects_not_skipped(self) -> None:
        d = _probe_event().to_dict()
        assert d["crux_probe_skipped"] is False
        assert d["metadata"]["crux_probe"]["cruxset_id"] == "fake-cs-001"


# ---------------------------------------------------------------------------
# _build_synthetic_crux_payload unit tests
# ---------------------------------------------------------------------------


class TestBuildSyntheticCruxPayload:
    def test_one_crux_per_reason(self) -> None:
        sig = _signal(
            reasons=[
                DecayReason(kind="failed_claim", detail="A", claim_id="c1"),
                DecayReason(kind="stale_evidence", detail="B"),
            ]
        )
        p = _build_synthetic_crux_payload(sig, "Q")
        assert len(p["cruxes"]) == 2
        assert p["cruxes"][0]["crux_score"] == 0.85
        assert p["cruxes"][1]["crux_score"] == 0.60

    def test_no_reasons_produces_one_root_cause_crux(self) -> None:
        p = _build_synthetic_crux_payload(_signal(integrity_score=0.4, reasons=[]), "Q")
        assert len(p["cruxes"]) == 1
        assert "unit.test" in p["cruxes"][0]["claim_id"]

    def test_required_payload_keys(self) -> None:
        p = _build_synthetic_crux_payload(_signal(), "Q")
        assert {
            "cruxes",
            "total_claims",
            "total_disagreements",
            "average_uncertainty",
            "convergence_barrier",
            "recommended_focus",
        }.issubset(set(p.keys()))

    def test_unresolved_crux_counts_in_total_disagreements(self) -> None:
        sig = _signal(
            reasons=[
                DecayReason(kind="unresolved_crux", detail="x", crux_id="crux.x"),
                DecayReason(kind="unresolved_crux", detail="y", crux_id="crux.y"),
                DecayReason(kind="failed_claim", detail="z"),
            ]
        )
        p = _build_synthetic_crux_payload(sig, "Q")
        assert p["total_disagreements"] == 2
        assert p["total_claims"] == 3

    def test_claim_and_crux_id_preference(self) -> None:
        sig = _signal(
            reasons=[
                DecayReason(kind="failed_claim", detail="a", claim_id="my.claim"),
                DecayReason(kind="unresolved_crux", detail="b", crux_id="my.crux"),
            ]
        )
        p = _build_synthetic_crux_payload(sig, "Q")
        assert p["cruxes"][0]["claim_id"] == "my.claim"
        assert p["cruxes"][1]["claim_id"] == "my.crux"

    def test_recommended_focus_capped_at_three(self) -> None:
        sig = _signal(reasons=[DecayReason(kind="failed_claim", detail=f"r{i}") for i in range(5)])
        assert len(_build_synthetic_crux_payload(sig, "Q")["recommended_focus"]) <= 3
