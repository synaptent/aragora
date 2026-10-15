"""Backbone handoff contracts (compatibility path).

The module lives in :mod:`aragora.types.backbone_contracts`. This path resolves to that same
module object, so the run-ledger classes and any patch applied through either path stay in
step.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aragora.types import backbone_contracts as _module

if not TYPE_CHECKING:
    sys.modules[__name__] = _module

if TYPE_CHECKING:
    from aragora.types.backbone_contracts import BackboneStage as BackboneStage
    from aragora.types.backbone_contracts import (
        ComputerUseActionBundle as ComputerUseActionBundle,
    )
    from aragora.types.backbone_contracts import DeliberationBundle as DeliberationBundle
    from aragora.types.backbone_contracts import ExecutionAttemptRecord as ExecutionAttemptRecord
    from aragora.types.backbone_contracts import IntakeBundle as IntakeBundle
    from aragora.types.backbone_contracts import OutcomeFeedbackRecord as OutcomeFeedbackRecord
    from aragora.types.backbone_contracts import ReceiptEnvelope as ReceiptEnvelope
    from aragora.types.backbone_contracts import RunLedger as RunLedger
    from aragora.types.backbone_contracts import RunStageEvent as RunStageEvent
    from aragora.types.backbone_contracts import SpecBundle as SpecBundle
    from aragora.types.backbone_contracts import TaintChecker as TaintChecker
    from aragora.types.backbone_contracts import (
        build_goal_refs_from_implement_plan as build_goal_refs_from_implement_plan,
    )
    from aragora.types.backbone_contracts import propagate_taint as propagate_taint
