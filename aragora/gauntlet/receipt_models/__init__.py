"""Gauntlet receipt facade over :mod:`aragora.models.receipts.gauntlet`.

The gauntlet receipt family (``DecisionReceipt``, ``ProvenanceRecord``,
``ConsensusProof``, ``AgentResponseRecord``, ``CruxReceipt`` and helpers) lives
in the foundation layer. This path resolves to that same module object, and
importing it registers the operational adapters the foundation module needs:
signing, exporters, compliance artifacts, provider detection and failure
classification.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from aragora.models.receipts import gauntlet as _receipts

if not TYPE_CHECKING:
    # Alias first: the adapter modules below may import this path while it loads.
    sys.modules[__name__] = _receipts

from aragora.agents.receipt_hooks import register_receipt_agent_hooks
from aragora.gauntlet import receipt_exporters as _receipt_exporters
from aragora.models.receipts import operations as _operations


class _DeferredReceiptSigning:
    # Importing aragora.storage.receipt_signing runs the whole storage package init,
    # so it waits for the first signing call instead of loading with this facade.
    def __getattr__(self, name: str) -> Any:
        import aragora.storage.receipt_signing as receipt_signing

        return getattr(receipt_signing, name)


def _compliance_generator(**kwargs: Any) -> Any:
    from aragora.compliance.artifact_generator import ReceiptComplianceGenerator

    return ReceiptComplianceGenerator(**kwargs)


_operations.register_signing(_DeferredReceiptSigning())
_operations.register_exporters(_receipt_exporters)
_operations.register_compliance_generator(_compliance_generator)
register_receipt_agent_hooks()

if TYPE_CHECKING:
    from aragora.models.receipts.gauntlet import (
        RECEIPT_SCHEMA_VERSION as RECEIPT_SCHEMA_VERSION,
    )
    from aragora.models.receipts.gauntlet import (
        RECEIPT_SCHEMA_VERSION_CRUXES as RECEIPT_SCHEMA_VERSION_CRUXES,
    )
    from aragora.models.receipts.gauntlet import (
        RECEIPT_SCHEMA_VERSION_EVIDENCE as RECEIPT_SCHEMA_VERSION_EVIDENCE,
    )
    from aragora.models.receipts.gauntlet import AgentResponseRecord as AgentResponseRecord
    from aragora.models.receipts.gauntlet import ConsensusProof as ConsensusProof
    from aragora.models.receipts.gauntlet import CruxReceipt as CruxReceipt
    from aragora.models.receipts.gauntlet import DecisionReceipt as DecisionReceipt
    from aragora.models.receipts.gauntlet import ProvenanceRecord as ProvenanceRecord
    from aragora.models.receipts.gauntlet import Verdict as Verdict
    from aragora.models.receipts.gauntlet import (
        _canonical_decision_value as _canonical_decision_value,
    )
    from aragora.models.receipts.gauntlet import (
        _clamp_receipt_confidence as _clamp_receipt_confidence,
    )
    from aragora.models.receipts.gauntlet import (
        _compute_risk_summary_from_critiques as _compute_risk_summary_from_critiques,
    )
    from aragora.models.receipts.gauntlet import (
        _normalize_receipt_boolean as _normalize_receipt_boolean,
    )
    from aragora.models.receipts.gauntlet import build_crux_receipt as build_crux_receipt
    from aragora.models.receipts.gauntlet import (
        build_crux_receipt_from_proof as build_crux_receipt_from_proof,
    )
    from aragora.models.receipts.gauntlet import (
        canonicalize_execution_outcome_linkage as canonicalize_execution_outcome_linkage,
    )
    from aragora.models.receipts.gauntlet import (
        compute_decision_payload_hash as compute_decision_payload_hash,
    )
    from aragora.models.receipts.gauntlet import (
        compute_receipt_artifact_hash as compute_receipt_artifact_hash,
    )
    from aragora.models.receipts.gauntlet import (
        crux_cards_from_metadata as crux_cards_from_metadata,
    )
    from aragora.models.receipts.gauntlet import (
        normalize_evidence_references as normalize_evidence_references,
    )
    from aragora.models.receipts.gauntlet import (
        normalize_live_explainability as normalize_live_explainability,
    )
    from aragora.models.receipts.gauntlet import (
        receipt_schema_version as receipt_schema_version,
    )
