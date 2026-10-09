"""Minimal public debate surface for the standalone wedge."""

from __future__ import annotations

from aragora.debate.model_combinations import (
    CombinationDebateResult,
    ExecutionMode,
    ModelCombination,
    MultiModelDebateResult,
    MultiModelDebateRunner,
    parse_model_combinations,
)
from aragora.debate.orchestrator import Arena
from aragora.debate.protocol_resolver import resolve_default_protocol
from aragora.protocols.debate import (
    ARAGORA_AI_LIGHT_PROTOCOL,
    ARAGORA_AI_PROTOCOL,
    DebateProtocol,
    RoundPhase,
    user_vote_multiplier,
)
from aragora.resilience import CircuitBreaker

__all__ = [
    "ARAGORA_AI_LIGHT_PROTOCOL",
    "ARAGORA_AI_PROTOCOL",
    "Arena",
    "CircuitBreaker",
    "CombinationDebateResult",
    "DebateProtocol",
    "ExecutionMode",
    "ModelCombination",
    "MultiModelDebateResult",
    "MultiModelDebateRunner",
    "RoundPhase",
    "parse_model_combinations",
    "resolve_default_protocol",
    "user_vote_multiplier",
]


# ---------------------------------------------------------------------------
# Golden API collision guard (issue #8780)
#
# This subpackage shares its name with the golden callable ``aragora.debate``
# (:func:`aragora.debate.api.debate`, re-exported by ``aragora.golden``) that
# ``aragora/__init__.py`` exports lazily via ``_EXPORT_MAP``. When this
# subpackage is imported, the import system binds the module object onto the
# ``aragora`` package, shadowing the golden callable. Making the module itself
# callable keeps ``aragora.debate(...)`` working in every import order while
# leaving normal module semantics (attribute access, ``__path__``, patch
# targets) untouched.
# ---------------------------------------------------------------------------
import sys as _sys
import types as _types
from typing import Any as _Any


class _CallableDebateModule(_types.ModuleType):
    """Module subclass forwarding calls to :func:`aragora.debate.api.debate`."""

    def __call__(self, *args: _Any, **kwargs: _Any) -> _Any:
        from .api import debate as _api_debate

        return _api_debate(*args, **kwargs)


_sys.modules[__name__].__class__ = _CallableDebateModule
