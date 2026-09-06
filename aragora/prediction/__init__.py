"""Prediction markets — AGT-04 synthetic GitHub prediction substrate.

All public symbols are importable regardless of the feature flag.
The flag (``ARAGORA_PREDICTION_MARKETS_ENABLED``) only gates the runtime
behaviour of :class:`InMemoryStakeableClaimStore`, the resolution adapter,
and :func:`compute_brier_scores`.
"""

from aragora.prediction.brier import AgentBrierScore, compute_brier_scores
from aragora.prediction.stakeable_claim import (
    GithubResolutionAdapterStub,
    InMemoryStakeableClaimStore,
    QuestionType,
    ResolutionStatus,
    StakeableClaim,
)

__all__ = [
    "AgentBrierScore",
    "GithubResolutionAdapterStub",
    "InMemoryStakeableClaimStore",
    "QuestionType",
    "ResolutionStatus",
    "StakeableClaim",
    "compute_brier_scores",
]
