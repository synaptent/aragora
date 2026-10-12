"""Pure receipt implementations in the foundation layer.

Modules here import only the standard library and other foundation packages,
so any layer can construct, canonicalize and hash receipt material. The
application packages (``aragora.receipts``, ``aragora.gauntlet``,
``aragora.export``) keep their import paths as facades over these modules.

- :mod:`aragora.models.receipts.jcs`: RFC 8785 canonicalization and the ODR
  content digest.
- :mod:`aragora.models.receipts.attestation`: human-oversight attestation
  blocks for ODR receipts.
"""

from __future__ import annotations

from aragora.models.receipts.attestation import (
    AUTONOMOUS_DISPOSITION,
    HUMAN_ATTESTED_DISPOSITION,
    HUMAN_SETTLEMENT_CONTEXT,
    OversightAttestation,
    attestation_from_preapproval_comment,
    attestation_from_settlement_status,
    build_oversight_attestation,
)
from aragora.models.receipts.jcs import (
    ODR_SIGNATURE_INPUT_V02,
    jcs_canonicalize,
    odr_content_digest,
    odr_signature_message,
)

__all__ = [
    "AUTONOMOUS_DISPOSITION",
    "HUMAN_ATTESTED_DISPOSITION",
    "HUMAN_SETTLEMENT_CONTEXT",
    "ODR_SIGNATURE_INPUT_V02",
    "OversightAttestation",
    "attestation_from_preapproval_comment",
    "attestation_from_settlement_status",
    "build_oversight_attestation",
    "jcs_canonicalize",
    "odr_content_digest",
    "odr_signature_message",
]
