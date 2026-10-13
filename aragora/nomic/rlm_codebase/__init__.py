"""
Codebase RLM summary (compatibility path).

The module lives in :mod:`aragora.rlm.codebase_summary`; this module re-exports the same objects.
"""

from __future__ import annotations

from aragora.rlm.codebase_summary import (
    DEFAULT_QUERY as DEFAULT_QUERY,
    CodebaseCorpus,
    CodebaseRLMResult,
    build_codebase_corpus,
    summarize_codebase_with_rlm,
)

__all__ = [
    "CodebaseCorpus",
    "CodebaseRLMResult",
    "build_codebase_corpus",
    "summarize_codebase_with_rlm",
]
