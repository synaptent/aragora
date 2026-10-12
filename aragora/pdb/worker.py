"""Back-compat shim for :mod:`aragora.brief_engine.worker`.

The in-process brief-generation worker moved to
:mod:`aragora.brief_engine.worker` in the Phase 1 brief-engine
extraction. This module re-exports the worker types so existing Mode 3
callers continue to work. The worker's default runner calls back into
:func:`aragora.pdb.protocol.run_protocol_b` so Mode 3 submissions that
don't supply a custom ``runner`` behave exactly as before.

Do not add new worker logic here — put it in
:mod:`aragora.brief_engine.worker` instead.
"""

from __future__ import annotations

from aragora.brief_engine.worker import (
    AlreadyRunningError,
    BriefGenerationWorker,
    JobKey,
    JobRequest,
    get_worker,
    reset_worker,
    set_worker,
)

# Re-export :func:`run_protocol_b` here so legacy tests that patch
# ``aragora.pdb.worker.run_protocol_b`` (``monkeypatch.setattr(worker,
# "run_protocol_b", ...)``) continue to observe their override. The
# generic worker's default Mode 3 runner dispatches through this
# module attribute precisely to preserve that behaviour.
from aragora.pdb.protocol import run_protocol_b

__all__ = [
    "AlreadyRunningError",
    "BriefGenerationWorker",
    "JobKey",
    "JobRequest",
    "get_worker",
    "reset_worker",
    "run_protocol_b",
    "set_worker",
]
