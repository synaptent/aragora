"""
Codebase context builder (compatibility path).

The module lives in :mod:`aragora.rlm.context_builder`; this module re-exports the same objects.
"""

from __future__ import annotations

from aragora.rlm.context_builder import (
    CodebaseIndex,
    IndexedFile,
    MAX_FILE_SIZE,
    NomicContextBuilder,
    SKIP_DIRS,
    SOURCE_EXTENSIONS,
)

__all__ = [
    "CodebaseIndex",
    "IndexedFile",
    "MAX_FILE_SIZE",
    "NomicContextBuilder",
    "SKIP_DIRS",
    "SOURCE_EXTENSIONS",
]
