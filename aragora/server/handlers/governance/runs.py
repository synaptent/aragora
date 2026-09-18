"""Backbone run ledger handlers.

Endpoints:
- GET /api/runs          - List persisted backbone runs
- GET /api/runs/{run_id} - Fetch one persisted backbone run
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from aragora.pipeline.backbone_contracts import RunLedger
from aragora.server.handlers.base import BaseHandler, HandlerResult, error_response, json_response
from aragora.server.handlers.utils.decorators import require_permission
from aragora.server.versioning.compat import strip_version_prefix

_RUNS_READ_PERMISSION = "orchestration:read"


def _get_plan_store() -> Any:
    """Lazy import to avoid handler import cycles."""
    from aragora.pipeline.plan_store import get_plan_store

    return get_plan_store()


def _coerce_int(
    value: Any,
    *,
    default: int,
    min_value: int,
    max_value: int | None = None,
) -> int:
    """Parse a bounded integer from query params."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default

    if parsed < min_value:
        return min_value
    if max_value is not None and parsed > max_value:
        return max_value
    return parsed


def _event_value(event: Any, field: str) -> str:
    """Read one string field from a RunStageEvent or serialized dict."""
    if isinstance(event, dict):
        value = event.get(field, "")
    else:
        value = getattr(event, field, "")
    return str(value or "").strip()


def _json_safe_value(value: Any) -> Any:
    """Coerce stage event values into JSON-safe primitives."""
    if value is None or isinstance(value, str | int | float | bool):
        return value

    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}

    if isinstance(value, list | tuple):
        return [_json_safe_value(item) for item in value]

    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()

    return str(value)


def _stage_event_payload(event: Any) -> dict[str, Any]:
    """Serialize one stage event while preserving timeline details when present."""
    if isinstance(event, dict):
        payload = {str(key): _json_safe_value(value) for key, value in event.items()}
    else:
        payload: dict[str, Any] = {}

        model_dump = getattr(event, "model_dump", None)
        if callable(model_dump):
            payload = {
                str(key): _json_safe_value(value)
                for key, value in cast(dict[str, Any], model_dump()).items()
            }
        elif hasattr(event, "_asdict"):
            payload = {
                str(key): _json_safe_value(value)
                for key, value in cast(dict[str, Any], event._asdict()).items()
            }
        elif hasattr(event, "__dict__"):
            payload = {
                str(key): _json_safe_value(value)
                for key, value in vars(event).items()
                if not str(key).startswith("_")
            }

    stage = _event_value(event, "stage")
    status = _event_value(event, "status") or "unknown"
    if stage:
        payload.setdefault("stage", stage)
    payload.setdefault("status", status)
    return payload


def _stage_payload(stage_events: Iterable[Any]) -> list[dict[str, Any]]:
    """Return ordered stage events so operators can inspect the run timeline."""
    payload: list[dict[str, Any]] = []

    for event in stage_events:
        event_payload = _stage_event_payload(event)
        if not str(event_payload.get("stage", "") or "").strip():
            continue
        payload.append(event_payload)

    return payload


def _run_payload(run: RunLedger) -> dict[str, Any]:
    """Serialize the compact run payload used by the runs endpoints."""
    metadata = run.metadata if isinstance(run.metadata, dict) else {}
    safety_mode = str(metadata.get("safety_mode", "") or "").strip() or None

    return {
        "run_id": run.run_id,
        "status": run.status,
        "stages": _stage_payload(run.stage_events),
        "stage_timeline": _stage_payload(run.stage_events),
        "execution_id": run.execution_id or None,
        "receipt_id": run.receipt_id or None,
        "safety_mode": safety_mode,
    }


def _get_backbone_run(store: Any, run_id: str) -> RunLedger | None:
    """Read a single run, preferring the explicit backbone accessor when available."""
    getter = getattr(store, "get_backbone_run", None)
    if callable(getter):
        return cast(RunLedger | None, getter(run_id))

    getter = getattr(store, "get_run", None)
    if callable(getter):
        return cast(RunLedger | None, getter(run_id))

    return None


def _list_backbone_runs(
    store: Any,
    *,
    status: str | None,
    limit: int,
    offset: int,
) -> list[RunLedger]:
    """List runs, preferring the explicit backbone accessor when available."""
    lister = getattr(store, "list_backbone_runs", None)
    if callable(lister):
        return cast(list[RunLedger], lister(status=status, limit=limit, offset=offset))

    lister = getattr(store, "list_runs", None)
    if callable(lister):
        return cast(list[RunLedger], lister(status=status, limit=limit, offset=offset))

    return []


def handle_runs_list(
    query_params: dict[str, Any] | None = None,
    *,
    store: Any | None = None,
) -> HandlerResult:
    """Handle GET /api/runs."""
    params = query_params or {}
    run_store = store or _get_plan_store()

    status = str(params.get("status", "") or "").strip() or None
    limit = _coerce_int(params.get("limit", 50), default=50, min_value=1, max_value=100)
    offset = _coerce_int(params.get("offset", 0), default=0, min_value=0)

    runs = _list_backbone_runs(run_store, status=status, limit=limit, offset=offset)
    return json_response({"runs": [_run_payload(run) for run in runs]})


def handle_run_detail(
    run_id: str,
    *,
    store: Any | None = None,
) -> HandlerResult:
    """Handle GET /api/runs/{run_id}."""
    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        return error_response("run_id is required", 400)

    run_store = store or _get_plan_store()
    run = _get_backbone_run(run_store, normalized_run_id)
    if run is None:
        return error_response("Run not found", 404)

    return json_response({"run": _run_payload(run)})


class RunsHandler(BaseHandler):
    """Legacy aiohttp-style handler for backbone run ledger reads."""

    ROUTES = ["/api/runs"]
    ROUTE_PREFIXES = ["/api/runs/"]

    def can_handle(self, path: str) -> bool:
        """Accept both canonical and versioned backbone run paths."""
        normalized_path = strip_version_prefix(path)
        return normalized_path == "/api/runs" or normalized_path.startswith("/api/runs/")

    @require_permission(_RUNS_READ_PERMISSION)
    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Dispatch GET requests for the backbone runs surface."""
        method = getattr(handler, "command", "GET") if handler is not None else "GET"
        if method != "GET":
            return None

        normalized_path = strip_version_prefix(path)
        store = self.ctx.get("plan_store") or _get_plan_store()

        if normalized_path == "/api/runs":
            return handle_runs_list(query_params, store=store)

        if normalized_path.startswith("/api/runs/"):
            run_id = normalized_path.removeprefix("/api/runs/").strip("/")
            if not run_id or "/" in run_id:
                return error_response("Run not found", 404)
            return handle_run_detail(run_id, store=store)

        return None


__all__ = [
    "RunsHandler",
    "handle_run_detail",
    "handle_runs_list",
]
