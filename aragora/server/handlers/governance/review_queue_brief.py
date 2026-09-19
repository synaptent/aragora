"""HTTP handlers for Mode 3 on-demand brief generation.

Three endpoints layered on top of the existing
:class:`aragora.server.handlers.governance.review_queue.ReviewQueueHandler`:

- ``POST   /api/v1/review-queue/prs/{number}/brief/generate``
- ``GET    /api/v1/review-queue/prs/{number}/brief/state``
- ``DELETE /api/v1/review-queue/prs/{number}/brief/generate``

All three are gated by the feature flag
``ARAGORA_PDB_BRIEF_GENERATION_ENABLED``. When off, each returns 503 —
the existing ``GET /brief`` read path and the ``/review-queue`` list are
unaffected (they live in ``review_queue.py``).

Authentication: each handler function receives ``user`` from the
dispatching :class:`ReviewQueueHandler.handle_post` / ``handle_get`` /
``handle_delete`` methods, which call ``self.require_auth_or_error``
on the request before routing here. As defense-in-depth, each handler
below re-checks ``user is not None`` and returns 401 if the caller
somehow reaches this module without an authenticated session.

Invariants:

- On ``POST``, the caller's current head SHA is refreshed from ``gh``
  and used to key storage. Any older ``ready`` brief is moved to
  ``invalidated/``.
- Dedupe runs in the worker, not here. This module only enforces the
  409 path via the worker's :class:`AlreadyRunningError`.
- The ``invoker_factory`` passed to the worker is a placeholder that
  raises a clear error — PR 3 ships without a real provider wiring.
  Integration tests use a mocked factory via the
  ``ARAGORA_PDB_TEST_INVOKER`` attribute hook.
"""

from __future__ import annotations

__all__ = [
    "BRIEF_GENERATION_FLAG",
    "DEFAULT_ESTIMATED_SECONDS",
    "feature_enabled",
    "handle_generate",
    "handle_state",
    "handle_cancel",
]

import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable

from aragora.pdb import storage
from aragora.pdb.brief_state import BriefLifecycleState
from aragora.pdb.input_loader import (
    InputLoaderError,
    InputLoaderErrorReason,
    LoadedExecutionInput,
    load_execution_input,
)
from aragora.pdb.invoker_factory import InvokerFactoryError, build_default_invoker
from aragora.pdb.protocol import ProviderInvoker
from aragora.pdb.worker import (
    AlreadyRunningError,
    BriefGenerationWorker,
    JobKey,
    JobRequest,
)
from aragora.review.policy import ReviewPolicy

from ..utils.responses import HandlerResult, error_response, json_response

logger = logging.getLogger(__name__)

UTC = timezone.utc

BRIEF_GENERATION_FLAG = "ARAGORA_PDB_BRIEF_GENERATION_ENABLED"
DEFAULT_ESTIMATED_SECONDS = 180  # aligns with design doc §Single generation flow


# Hook for test-time invoker injection. Tests set this to a callable that
# returns a :class:`ProviderInvoker`; production leaves it None so the
# handler raises the "not yet wired" error before scheduling real work.
_INVOKER_FACTORY_OVERRIDE: Callable[[], ProviderInvoker] | None = None


def set_test_invoker_factory(factory: Callable[[], ProviderInvoker] | None) -> None:
    """Install (or clear) a test-only invoker factory."""
    global _INVOKER_FACTORY_OVERRIDE
    _INVOKER_FACTORY_OVERRIDE = factory


# Hook for test-time input loader injection. Tests can stub this to
# bypass `gh` entirely.
_INPUT_LOADER_OVERRIDE: (
    Callable[[int, str | None, ReviewPolicy | None], LoadedExecutionInput] | None
) = None


def set_test_input_loader(
    loader: Callable[[int, str | None, ReviewPolicy | None], LoadedExecutionInput] | None,
) -> None:
    """Install (or clear) a test-only input loader."""
    global _INPUT_LOADER_OVERRIDE
    _INPUT_LOADER_OVERRIDE = loader


# ---------------------------------------------------------------------------
# Flag + helpers
# ---------------------------------------------------------------------------


def feature_enabled() -> bool:
    """Return True if Mode 3 brief generation is enabled via env flag."""
    raw = os.environ.get(BRIEF_GENERATION_FLAG, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _feature_disabled_response() -> HandlerResult:
    return error_response(
        f"Mode 3 brief generation is disabled. Set {BRIEF_GENERATION_FLAG}=1 to enable.",
        status=503,
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_input(
    pr_number: int, repo: str | None, policy: ReviewPolicy | None
) -> LoadedExecutionInput:
    loader = _INPUT_LOADER_OVERRIDE
    if loader is not None:
        return loader(pr_number, repo, policy)
    return load_execution_input(
        pr_number=pr_number,
        repo=repo,
        policy=policy,
    )


def _translate_input_error(err: InputLoaderError) -> HandlerResult:
    reason = err.reason
    if reason is InputLoaderErrorReason.PR_NOT_FOUND:
        return error_response(err.detail or "PR not found", status=404)
    if reason is InputLoaderErrorReason.GH_MISSING:
        return error_response(
            "gh CLI not found on server. Install and authenticate `gh` to "
            "generate briefs from the web UI.",
            status=503,
        )
    if reason is InputLoaderErrorReason.GH_AUTHENTICATION:
        return error_response(
            "gh CLI not authenticated. Run `gh auth login` to attach your GitHub identity.",
            status=403,
        )
    if reason is InputLoaderErrorReason.TIMEOUT:
        return error_response(err.detail or "gh CLI timed out", status=504)
    if reason is InputLoaderErrorReason.EMPTY_HEAD_SHA:
        return error_response(err.detail or "PR has no head SHA", status=422)
    if reason is InputLoaderErrorReason.MALFORMED_RESPONSE:
        return error_response(err.detail or "malformed gh response", status=502)
    return error_response(err.detail or reason.value, status=502)


_CREDENTIAL_KEYS_FOR_INVOKER: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",  # invoker_factory accepts either GEMINI_API_KEY or GOOGLE_API_KEY for the Gemini slot
    "GROK_API_KEY",
    "XAI_API_KEY",
    "OPENROUTER_API_KEY",
    "MISTRAL_API_KEY",
)


def _collect_provider_credentials() -> dict[str, str]:
    """Read provider credentials for this specific brief request.

    Returns a per-call env mapping suitable for passing to
    ``build_default_invoker(env=...)``. This function is non-mutating:
    it does NOT write to ``os.environ``. That matters because the
    server handles concurrent requests, and mutating process-global
    env from a live request path would make provider credentials
    shared mutable global state — a correctness bug on any deployment
    with more than one concurrent brief request.

    Ambient env wins over Secrets Manager so local-dev workflows
    (direnv / ``.env``) keep working without extra config. Secrets
    Manager fills in gaps when ``ARAGORA_USE_SECRETS_MANAGER=true``.
    """

    env: dict[str, str] = {}
    # Start with whatever is already in ambient env for these keys.
    for name in _CREDENTIAL_KEYS_FOR_INVOKER:
        value = os.environ.get(name)
        if value:
            env[name] = value

    # Fill missing keys from Secrets Manager (non-mutating: uses the
    # single-value getter, does not touch os.environ).
    try:
        from aragora.config.secrets import get_secret
    except ImportError:
        return env

    for name in _CREDENTIAL_KEYS_FOR_INVOKER:
        if name in env:
            continue
        try:
            # strict=False: Secrets Manager may not be configured;
            # that's fine — we'll hand whatever we collected to the
            # invoker factory, which raises a clean InvokerFactoryError
            # if required core slots are missing.
            value = get_secret(name, strict=False)
        except Exception:  # noqa: BLE001 — credential lookup must never block briefs
            logger.warning(
                "review_queue_brief: get_secret(%r) failed; falling back to whatever env is set",
                name,
            )
            continue
        if value:
            env[name] = value
    return env


def _resolve_invoker_factory() -> Callable[[], ProviderInvoker]:
    if _INVOKER_FACTORY_OVERRIDE is not None:
        return _INVOKER_FACTORY_OVERRIDE

    def _default_factory() -> ProviderInvoker:
        # Phase A: builds a RealProviderInvoker with Claude + GPT
        # wired. Heterodox slots (gemini / grok / deepseek / kimi /
        # qwen / mistral) degrade gracefully via the executor's
        # per-slot unavailable path. See
        # :mod:`aragora.pdb.invoker_factory`.
        #
        # Per-call credentials instead of os.environ mutation — the
        # server handles concurrent requests and must not share
        # provider credentials as a mutable global.
        env = _collect_provider_credentials()
        try:
            return build_default_invoker(env=env)
        except InvokerFactoryError as exc:
            # Re-raise with the factory's message; the handler turns
            # this into a 503 so the UI explains which env var is
            # missing.
            raise NotImplementedError(str(exc)) from exc

    return _default_factory


def _state_payload(pr_number: int, head_sha: str) -> dict[str, Any]:
    """Read the on-disk state for ``(pr_number, head_sha)`` and project to JSON."""
    state = storage.get_state(pr_number, head_sha)
    payload: dict[str, Any] = {
        "pr_number": pr_number,
        "head_sha": head_sha,
        "state": state.value,
    }
    # Surface phase / cost / timestamps when they exist on disk.
    briefs_root = storage.briefs_root()
    filename = f"pr-{pr_number}-{head_sha[:12]}.json"
    subdir: str | None = None
    if state == BriefLifecycleState.QUEUED:
        subdir = storage.QUEUED_SUBDIR
    elif state == BriefLifecycleState.RUNNING:
        subdir = storage.RUNNING_SUBDIR
    elif state == BriefLifecycleState.FAILED:
        subdir = storage.FAILED_SUBDIR
    if subdir is not None:
        path = briefs_root / subdir / filename
        if path.exists():
            try:
                import json

                record = json.loads(path.read_text(encoding="utf-8"))
                for key in (
                    "requested_at",
                    "started_at",
                    "current_phase",
                    "cost_usd_so_far",
                    "panel_models",
                    "updated_at",
                    "error_message",
                    "failed_phase",
                    "failed_at",
                ):
                    if key in record:
                        payload[key] = record[key]
            except (OSError, ValueError):
                logger.warning("review_queue_brief: state file unreadable at %s", path)
    return payload


# ---------------------------------------------------------------------------
# Endpoint handlers
# ---------------------------------------------------------------------------


def handle_generate(
    pr_number: int,
    body: dict[str, Any],
    user: Any,
    *,
    worker: BriefGenerationWorker,
) -> HandlerResult:
    """Schedule a brief-generation job for ``pr_number``.

    Behavior:

    - Feature flag off → 503.
    - Loads current head SHA via the input loader.
    - Moves any older ``ready`` briefs to ``invalidated/``.
    - Rejects with 409 when a live queued/running brief already exists.
    - Writes the queued record atomically; submits to the worker.
    - Returns ``{state: "queued"}`` + estimated completion seconds.
    """
    if user is None:
        return error_response("Authentication required", status=401)

    if not feature_enabled():
        return _feature_disabled_response()

    repo = None
    if isinstance(body, dict):
        raw = body.get("repo")
        if isinstance(raw, str) and raw.strip():
            repo = raw.strip()

    try:
        loaded = _load_input(pr_number, repo, None)
    except InputLoaderError as exc:
        return _translate_input_error(exc)
    except NotImplementedError as exc:
        logger.warning("review_queue_brief: generate hit test-only path: %s", exc)
        return error_response(str(exc), status=503)

    head_sha = loaded.head_sha

    # Invalidate stale ready briefs before acting on this request.
    storage.invalidate_if_head_changed(pr_number, head_sha)

    current_state = storage.get_state(pr_number, head_sha)
    if current_state in (
        BriefLifecycleState.QUEUED,
        BriefLifecycleState.RUNNING,
        BriefLifecycleState.READY,
    ):
        return json_response(
            {
                "status": "conflict",
                "pr_number": pr_number,
                "head_sha": head_sha,
                "state": current_state.value,
                "message": (
                    f"brief is already {current_state.value}; "
                    "poll /brief/state for progress or DELETE to cancel."
                ),
            },
            status=409,
        )

    panel_models = list(loaded.panel_models)
    storage.queue_generation(
        pr_number,
        head_sha,
        panel_models=panel_models,
        extra_fields={
            "repo": loaded.repo,
            "requested_by": str(getattr(user, "user_id", "") or ""),
        },
    )

    request = JobRequest(
        key=JobKey(
            repo=loaded.repo,
            pr_number=pr_number,
            head_sha=head_sha,
        ),
        input=loaded.input,
        invoker_factory=_resolve_invoker_factory(),
        panel_models=tuple(panel_models),
    )

    try:
        worker.submit(request)
    except AlreadyRunningError as exc:
        # Worker-side dedupe raced a parallel request. Surface as 409
        # with the observed state.
        return json_response(
            {
                "status": "conflict",
                "pr_number": pr_number,
                "head_sha": head_sha,
                "state": exc.state.value,
                "message": str(exc),
            },
            status=409,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("review_queue_brief: worker.submit failed for pr=%s", pr_number)
        storage.mark_failed(
            pr_number,
            head_sha,
            str(exc),
            "submit_exception",
            0.0,
        )
        return error_response(f"worker submit failed: {exc}", status=500)

    logger.info(
        "review-queue-brief generate: pr=%s head=%s user=%s",
        pr_number,
        head_sha[:12],
        getattr(user, "user_id", None),
    )

    return json_response(
        {
            "pr_number": pr_number,
            "head_sha": head_sha,
            "state": BriefLifecycleState.QUEUED.value,
            "queued_at": _now_iso(),
            "estimated_completion_seconds": DEFAULT_ESTIMATED_SECONDS,
            "panel_models": panel_models,
        },
        status=202,
    )


def handle_state(pr_number: int) -> HandlerResult:
    """Return the current lifecycle state for ``pr_number``.

    Resolves the current head SHA via the input loader so polling sees
    a fresh view. If the PR can't be reached we fall back to the
    latest-on-disk ready-brief SHA when one exists, to keep polling
    cheap after the head changes.
    """
    if not feature_enabled():
        return _feature_disabled_response()

    try:
        loaded = _load_input(pr_number, None, None)
        head_sha: str | None = loaded.head_sha
    except InputLoaderError as exc:
        if exc.reason is InputLoaderErrorReason.PR_NOT_FOUND:
            return _translate_input_error(exc)
        # gh unavailable, malformed, etc — try the latest ready brief fallback.
        ready_paths = storage.find_ready_briefs_for_pr(pr_number)
        if not ready_paths:
            return _translate_input_error(exc)
        # Extract the full sha from the on-disk record.
        first = ready_paths[0]
        try:
            import json

            data = json.loads(first.read_text(encoding="utf-8"))
            head_sha = str(data.get("head_sha", "")).strip() or first.stem.split("-", 2)[-1]
        except (OSError, ValueError):
            head_sha = first.stem.split("-", 2)[-1]
    if head_sha:
        storage.invalidate_if_head_changed(pr_number, head_sha)

    if not head_sha:
        return error_response("could not resolve head SHA", status=502)

    return json_response(_state_payload(pr_number, head_sha))


def handle_cancel(
    pr_number: int,
    user: Any,
    *,
    worker: BriefGenerationWorker,
) -> HandlerResult:
    """Cancel an in-flight generation for ``pr_number``.

    DELETE semantics:

    - Flag off → 503.
    - Resolves current head SHA. Looks up state — only queued/running
      can be cancelled; other states are a no-op returning 200 with
      the current state.
    - Fires :meth:`BriefGenerationWorker.cancel` (best-effort).
    - Calls :func:`storage.cancel_generation` to remove the queued
      record if one is still present. Running state transitions to
      ``failed`` by the worker when cancel propagates.
    """
    if user is None:
        return error_response("Authentication required", status=401)

    if not feature_enabled():
        return _feature_disabled_response()

    try:
        loaded = _load_input(pr_number, None, None)
        head_sha = loaded.head_sha
        repo = loaded.repo
    except InputLoaderError as exc:
        return _translate_input_error(exc)

    current = storage.get_state(pr_number, head_sha)
    if current not in (BriefLifecycleState.QUEUED, BriefLifecycleState.RUNNING):
        return json_response(
            {
                "pr_number": pr_number,
                "head_sha": head_sha,
                "state": current.value,
                "cancelled": False,
                "message": f"no active generation to cancel (state={current.value})",
            }
        )

    cancelled_worker = worker.cancel(JobKey(repo=repo, pr_number=pr_number, head_sha=head_sha))
    # Clear the queued record directly if the worker hadn't picked it up
    # yet (queued records have no worker-side finalization path). For
    # running work the worker transitions to ``failed`` when the cancel
    # propagates — do NOT remove the running record here, that would
    # race the worker's ``mark_failed`` call.
    if current == BriefLifecycleState.QUEUED:
        post_state = storage.cancel_generation(pr_number, head_sha)
    else:
        # RUNNING: wait briefly for the worker to emit its failed record.
        import time as _time

        deadline = _time.monotonic() + 2.0
        while _time.monotonic() < deadline:
            observed = storage.get_state(pr_number, head_sha)
            if observed != BriefLifecycleState.RUNNING:
                break
            _time.sleep(0.02)
        post_state = storage.get_state(pr_number, head_sha)

    logger.info(
        "review-queue-brief cancel: pr=%s head=%s user=%s worker_cancelled=%s state=%s",
        pr_number,
        head_sha[:12],
        getattr(user, "user_id", None),
        cancelled_worker,
        post_state.value,
    )
    return json_response(
        {
            "pr_number": pr_number,
            "head_sha": head_sha,
            "state": post_state.value,
            "cancelled": True,
            "worker_cancelled": cancelled_worker,
            "previous_state": current.value,
        }
    )
