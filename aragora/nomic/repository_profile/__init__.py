"""
Repository profile and evidence models (compatibility path).

The module lives in :mod:`aragora.rlm.repository_profile`; this module re-exports the same objects.
"""

from __future__ import annotations

from aragora.rlm.repository_profile import (
    ContextEvidenceReference,
    ContextPack,
    DEFAULT_EVALUATION_CRITERIA,
    EvaluationCriterion,
    NomicProfileError,
    NomicRepositoryProfile,
    RepositoryRevision,
    RepositoryStateError,
    assert_clean_revision,
    http_permalink,
    infer_repository_id,
    load_nomic_repository_profile,
    normalize_remote_url,
    portable_evidence_uri,
    validate_repository_path,
)

__all__ = [
    "ContextEvidenceReference",
    "ContextPack",
    "DEFAULT_EVALUATION_CRITERIA",
    "EvaluationCriterion",
    "NomicProfileError",
    "NomicRepositoryProfile",
    "RepositoryRevision",
    "RepositoryStateError",
    "assert_clean_revision",
    "http_permalink",
    "infer_repository_id",
    "load_nomic_repository_profile",
    "normalize_remote_url",
    "portable_evidence_uri",
    "validate_repository_path",
]
