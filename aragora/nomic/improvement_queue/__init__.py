"""
Improvement queue (compatibility path).

The queue lives in :mod:`aragora.learning.improvement_queue`; this module
re-exports the same objects. The queue singleton lives only in the new module;
patch or reset it there.
"""

from __future__ import annotations

from aragora.learning.improvement_queue import (
    ImprovementQueue,
    ImprovementSuggestion,
    get_improvement_queue,
)

__all__ = ["ImprovementQueue", "ImprovementSuggestion", "get_improvement_queue"]
