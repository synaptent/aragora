"""Pre-execution receipt gating for DecisionPlan action-taking.

This module makes plan execution fail closed unless there is either:
- a persisted, signed decision receipt in the expected lifecycle state, or
- an explicit documented exemption in plan metadata.

The receipt is created before execution, not after, so action-taking can
verify receipt state before any workflow/hybrid/computer-use path runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from aragora.gauntlet.receipt_models import DecisionReceipt
from aragora.gauntlet.receipt_store import (
    ReceiptState,
    ReceiptStateError,
    get_receipt_store,
)
from aragora.pipeline.decision_plan.core import PlanStatus

logger = logging.getLogger(__name__)


class PlanReceiptGateError(RuntimeError):
    """Raised when a plan lacks a valid pre-execution decision receipt."""


@dataclass
class PlanReceiptStatus:
    """Resolved receipt gate state for one plan."""

    receipt_id: str | None
    state: str
    signature_valid: bool
    integrity_valid: bool
    exempted: bool = False


def _metadata(plan: Any) -> dict[str, Any]:
    metadata = getattr(plan, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    metadata = {}
    setattr(plan, "metadata", metadata)
    return metadata


def _receipt_meta(plan: Any) -> dict[str, Any]:
    metadata = _metadata(plan)
    receipt_meta = metadata.get("decision_receipt")
    if isinstance(receipt_meta, dict):
        return receipt_meta
    receipt_meta = {}
    metadata["decision_receipt"] = receipt_meta
    return receipt_meta


def _documented_exemption(plan: Any) -> dict[str, Any] | None:
    exemption = _metadata(plan).get("receipt_gate_exemption")
    if not isinstance(exemption, dict):
        return None
    reason = str(exemption.get("reason", "") or "").strip()
    approved_by = str(exemption.get("approved_by", "") or "").strip()
    if not reason or not approved_by:
        return None
    return {
        "reason": reason,
        "approved_by": approved_by,
    }


def _expected_receipt_state(plan: Any, *, on_status: PlanStatus | None = None) -> ReceiptState:
    status = on_status or getattr(plan, "status", PlanStatus.CREATED)
    if status == PlanStatus.REJECTED:
        return ReceiptState.EXPIRED
    if status == PlanStatus.COMPLETED:
        return ReceiptState.EXECUTED

    requires_human = bool(getattr(plan, "requires_human_approval", False))
    is_approved = bool(getattr(plan, "is_approved", False))
    if status == PlanStatus.AWAITING_APPROVAL or (requires_human and not is_approved):
        return ReceiptState.CREATED
    return ReceiptState.APPROVED


def _list_of_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text:
                result.append(text)
        return result
    return []


def _synthetic_debate_result(plan: Any) -> Any:
    metadata = _metadata(plan)
    deliberation = metadata.get("deliberation_bundle")
    if not isinstance(deliberation, dict):
        deliberation = {}

    gate = metadata.get("execution_gate")
    if not isinstance(gate, dict):
        gate = {}

    signed_receipt = gate.get("signed_receipt")
    if not isinstance(signed_receipt, dict):
        signed_receipt = {}

    signed_consensus = signed_receipt.get("consensus_proof")
    if not isinstance(signed_consensus, dict):
        signed_consensus = {}

    supporting_agents = _list_of_strings(signed_consensus.get("supporting_agents"))
    dissenting_agents = _list_of_strings(signed_consensus.get("dissenting_agents"))
    participants = supporting_agents + [
        agent for agent in dissenting_agents if agent not in supporting_agents
    ]
    if not participants:
        participants = _list_of_strings(metadata.get("decision_participants"))

    dissenting_views = _list_of_strings(deliberation.get("dissenting_views"))
    if not dissenting_views:
        dissenting_views = _list_of_strings(signed_receipt.get("dissenting_views"))

    confidence = float(
        deliberation.get("confidence")
        or signed_receipt.get("confidence")
        or metadata.get("decision_confidence")
        or 0.0
    )
    consensus_reached = bool(deliberation.get("consensus_reached"))
    if not consensus_reached:
        consensus_reached = bool(signed_consensus.get("reached"))

    return SimpleNamespace(
        debate_id=str(getattr(plan, "debate_id", "") or getattr(plan, "id", "")),
        task=str(getattr(plan, "task", "") or ""),
        final_answer=str(
            deliberation.get("verdict")
            or metadata.get("decision_summary")
            or getattr(plan, "task", "")
            or ""
        ),
        confidence=confidence,
        consensus_reached=consensus_reached,
        rounds_used=int(metadata.get("rounds_used") or 1),
        duration_seconds=float(metadata.get("duration_seconds") or 0.0),
        consensus_strength=str(
            deliberation.get("consensus_strength") or signed_consensus.get("method") or "majority"
        ),
        participants=participants,
        dissenting_views=dissenting_views,
        messages=[],
        votes=[],
        winner=None,
    )


def _build_receipt(plan: Any) -> DecisionReceipt:
    source = getattr(plan, "debate_result", None) or _synthetic_debate_result(plan)
    receipt = DecisionReceipt.from_debate_result(source)

    metadata = _metadata(plan)
    gate = metadata.get("execution_gate")
    if not isinstance(gate, dict):
        gate = {}

    deliberation = metadata.get("deliberation_bundle")
    if not isinstance(deliberation, dict):
        deliberation = {}

    receipt.config_used.update(
        {
            "plan_id": getattr(plan, "id", ""),
            "debate_id": getattr(plan, "debate_id", ""),
            "approval_mode": getattr(getattr(plan, "approval_mode", None), "value", ""),
            "execution_gate": gate,
        }
    )

    profile = getattr(plan, "implementation_profile", None)
    if profile is not None and hasattr(profile, "to_dict"):
        receipt.config_used["implementation_profile"] = profile.to_dict()

    settlement_metadata = dict(receipt.settlement_metadata or {})
    if deliberation:
        settlement_metadata["deliberation_bundle"] = deliberation
    if gate:
        settlement_metadata["execution_gate"] = gate
    if settlement_metadata:
        receipt.settlement_metadata = settlement_metadata

    taint_flags = _list_of_strings(deliberation.get("taint_flags"))
    if gate.get("context_taint_detected"):
        taint_flags.append("context_taint_detected")
    if taint_flags or gate:
        taint_analysis = {
            "tainted": bool(taint_flags) or bool(gate.get("context_taint_detected")),
            "flags": sorted(set(taint_flags)),
            "provider_diversity": gate.get("provider_diversity"),
            "model_family_diversity": gate.get("model_family_diversity"),
            "providers": _list_of_strings(gate.get("providers")),
            "model_families": _list_of_strings(gate.get("model_families")),
            "reason_codes": _list_of_strings(gate.get("reason_codes")),
        }
        receipt.taint_analysis = taint_analysis
        receipt.config_used["taint_analysis"] = taint_analysis

    signed_receipt = gate.get("signed_receipt")
    if (
        receipt.consensus_proof is not None
        and isinstance(signed_receipt, dict)
        and isinstance(signed_receipt.get("consensus_proof"), dict)
    ):
        consensus = signed_receipt["consensus_proof"]
        trust_score = consensus.get("trust_score")
        if trust_score is not None:
            try:
                receipt.consensus_proof.trust_score = float(trust_score)
            except (TypeError, ValueError):
                pass
        tainted_proposals = _list_of_strings(consensus.get("tainted_proposals"))
        if tainted_proposals:
            receipt.consensus_proof.tainted_proposals = tainted_proposals

    return receipt


def _update_metadata_from_store(
    plan: Any, *, receipt_id: str, state: ReceiptState, stored: Any
) -> None:
    metadata = _metadata(plan)
    receipt_meta = _receipt_meta(plan)
    receipt_meta.update(
        {
            "receipt_id": receipt_id,
            "state": state.value,
            "signature_key_id": getattr(stored, "signature_key_id", None),
            "signed_at": getattr(stored, "signed_at", None),
            "signature_algorithm": getattr(stored, "signature_algorithm", None),
            "exempted": False,
        }
    )
    metadata["decision_receipt_id"] = receipt_id


def _mark_exemption_metadata(plan: Any, exemption: dict[str, Any]) -> None:
    metadata = _metadata(plan)
    receipt_meta = _receipt_meta(plan)
    receipt_meta.update(
        {
            "receipt_id": None,
            "state": "EXEMPTED",
            "exempted": True,
            "reason": exemption["reason"],
            "approved_by": exemption["approved_by"],
        }
    )
    metadata["decision_receipt_id"] = None


def _validate_existing_receipt(
    plan: Any,
    *,
    require_state: ReceiptState | None,
) -> PlanReceiptStatus:
    receipt_meta = _receipt_meta(plan)
    receipt_id = str(
        receipt_meta.get("receipt_id") or _metadata(plan).get("decision_receipt_id") or ""
    ).strip()
    if not receipt_id:
        raise PlanReceiptGateError(
            f"Plan {getattr(plan, 'id', '<unknown>')} has no decision receipt"
        )

    store = get_receipt_store()
    stored = store.get(receipt_id)
    if stored is None:
        raise PlanReceiptGateError(
            f"Decision receipt {receipt_id} not found for plan {getattr(plan, 'id', '<unknown>')}"
        )

    if require_state is not None and stored.state != require_state:
        raise PlanReceiptGateError(
            f"Decision receipt {receipt_id} is in state {stored.state.value}, "
            f"expected {require_state.value}"
        )

    signature_valid = bool(stored.signature) and store.verify_receipt(receipt_id)
    if not signature_valid:
        raise PlanReceiptGateError(f"Decision receipt {receipt_id} failed signature verification")

    integrity_valid = True
    try:
        receipt = DecisionReceipt.from_dict(stored.receipt_data)
        integrity_valid = receipt.verify_integrity()
    except (TypeError, ValueError, KeyError) as exc:
        raise PlanReceiptGateError(
            f"Decision receipt {receipt_id} could not be reconstructed"
        ) from exc

    if not integrity_valid:
        raise PlanReceiptGateError(f"Decision receipt {receipt_id} failed integrity verification")

    _update_metadata_from_store(
        plan,
        receipt_id=receipt_id,
        state=stored.state,
        stored=stored,
    )
    return PlanReceiptStatus(
        receipt_id=receipt_id,
        state=stored.state.value,
        signature_valid=signature_valid,
        integrity_valid=integrity_valid,
    )


def ensure_plan_receipt(
    plan: Any,
    *,
    on_status: PlanStatus | None = None,
) -> PlanReceiptStatus:
    """Ensure a plan has a persisted decision receipt in the expected state."""
    exemption = _documented_exemption(plan)
    if exemption is not None:
        _mark_exemption_metadata(plan, exemption)
        return PlanReceiptStatus(
            receipt_id=None,
            state="EXEMPTED",
            signature_valid=False,
            integrity_valid=False,
            exempted=True,
        )

    require_state = _expected_receipt_state(plan, on_status=on_status)
    receipt_meta = _receipt_meta(plan)
    receipt_id = str(
        receipt_meta.get("receipt_id") or _metadata(plan).get("decision_receipt_id") or ""
    ).strip()

    if receipt_id:
        return _validate_existing_receipt(plan, require_state=require_state)

    receipt = _build_receipt(plan)
    receipt.sign()

    store = get_receipt_store()
    stored = store.persist(
        receipt_id=receipt.receipt_id,
        receipt_data=receipt.to_dict(),
        signature=receipt.signature,
        signature_key_id=receipt.signature_key_id,
        signed_at=receipt.signed_at,
        signature_algorithm=receipt.signature_algorithm,
        state=require_state,
    )
    _update_metadata_from_store(
        plan,
        receipt_id=receipt.receipt_id,
        state=require_state,
        stored=stored,
    )
    return _validate_existing_receipt(plan, require_state=require_state)


def sync_plan_receipt_state(
    plan: Any,
    *,
    on_status: PlanStatus | None = None,
) -> PlanReceiptStatus | None:
    """Synchronize persisted receipt lifecycle state with plan lifecycle state."""
    exemption = _documented_exemption(plan)
    if exemption is not None:
        _mark_exemption_metadata(plan, exemption)
        return PlanReceiptStatus(
            receipt_id=None,
            state="EXEMPTED",
            signature_valid=False,
            integrity_valid=False,
            exempted=True,
        )

    target_state = _expected_receipt_state(plan, on_status=on_status)
    receipt_meta = _receipt_meta(plan)
    receipt_id = str(
        receipt_meta.get("receipt_id") or _metadata(plan).get("decision_receipt_id") or ""
    ).strip()
    if receipt_id:
        status = _validate_existing_receipt(plan, require_state=None)
    else:
        status = ensure_plan_receipt(plan, on_status=on_status)
        if status.exempted or status.receipt_id is None:
            return status

    store = get_receipt_store()
    stored = store.get(status.receipt_id)
    if stored is None:
        raise PlanReceiptGateError(f"Decision receipt {status.receipt_id} missing during sync")

    if stored.state != target_state:
        try:
            stored = store.transition(status.receipt_id, target_state)
        except ReceiptStateError as exc:
            raise PlanReceiptGateError(
                f"Could not transition decision receipt {status.receipt_id} "
                f"from {stored.state.value} to {target_state.value}"
            ) from exc

    _update_metadata_from_store(
        plan,
        receipt_id=status.receipt_id,
        state=stored.state,
        stored=stored,
    )
    return _validate_existing_receipt(plan, require_state=target_state)


__all__ = [
    "PlanReceiptGateError",
    "PlanReceiptStatus",
    "ensure_plan_receipt",
    "sync_plan_receipt_state",
]
