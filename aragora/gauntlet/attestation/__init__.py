"""Compatibility path for :mod:`aragora.models.receipts.attestation`.

Human-oversight attestation blocks moved to the foundation receipts package so
compliance code can build them without importing ``aragora.gauntlet``. This
path resolves to the same module object, so every name (and every patch
applied through this path) is shared with the new home.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aragora.models.receipts import attestation as _attestation

if TYPE_CHECKING:
    from aragora.models.receipts.attestation import (
        AUTONOMOUS_DISPOSITION as AUTONOMOUS_DISPOSITION,
    )
    from aragora.models.receipts.attestation import (
        HUMAN_ATTESTED_DISPOSITION as HUMAN_ATTESTED_DISPOSITION,
    )
    from aragora.models.receipts.attestation import (
        HUMAN_SETTLEMENT_CONTEXT as HUMAN_SETTLEMENT_CONTEXT,
    )
    from aragora.models.receipts.attestation import OversightAttestation as OversightAttestation
    from aragora.models.receipts.attestation import (
        attestation_from_preapproval_comment as attestation_from_preapproval_comment,
    )
    from aragora.models.receipts.attestation import (
        attestation_from_settlement_status as attestation_from_settlement_status,
    )
    from aragora.models.receipts.attestation import (
        build_oversight_attestation as build_oversight_attestation,
    )
else:
    sys.modules[__name__] = _attestation
