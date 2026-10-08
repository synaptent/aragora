"""HTTP handler for agent bridge run data and operator-gated dispatch."""

from __future__ import annotations

__all__ = ["AgentBridgeHandler"]

import base64
import binascii
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from aragora.config.settings import get_settings
from aragora.rbac.defaults.permissions import PERM_AGENT_BRIDGE_READ
from aragora.rbac.defaults.permissions import PERM_AGENT_BRIDGE_WRITE
from aragora.rbac.decorators import require_permission
from aragora.server.http_caching import etag_matches
from aragora.server.validation import validate_path_segment
from aragora.server.versioning.compat import strip_version_prefix
from aragora.swarm.agent_bridge.broker import AgentBridgeBroker
from aragora.swarm.agent_bridge.exceptions import TransportError
from aragora.swarm.agent_bridge.footer import extract_footer
from aragora.swarm.agent_bridge.store import BridgeStore
from aragora.swarm.agent_bridge.types import BridgeFooter
from aragora.swarm.agent_bridge.types import BridgeRun
from aragora.swarm.agent_bridge.types import BridgeSession
from aragora.swarm.agent_bridge.types import SCHEMA_VERSION
from aragora.swarm.agent_bridge.types import SessionRegistry
from aragora.swarm.agent_bridge.types import TurnRecord

from ..base import (
    BaseHandler,
    HandlerResult,
    SAFE_SLUG_PATTERN,
    error_response,
    handle_errors,
    json_response,
)

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 100
_MAX_PAGE_SIZE = 500
_RUNS_PATH = "/api/agent-bridge/runs"
_RUNS_PREFIX = f"{_RUNS_PATH}/"

_CursorKind = Literal["run", "event"]


@dataclass(slots=True)
class _TranscriptAccumulator:
    turn_index: int
    author_role: str
    started_at: str | None = None
    completed_at: str | None = None
    parse_status: str | None = None
    footer: dict[str, Any] | None = None
    body_markdown: str = ""
    body_captured: bool = False


def _bridge_repo_root(ctx: dict[str, Any]) -> Path:
    override = ctx.get("agent_bridge_repo_root")
    if override:
        return Path(override).resolve()

    env_override = os.environ.get("ARAGORA_AGENT_BRIDGE_REPO")
    if env_override:
        return Path(env_override).resolve()

    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".git").exists() or (candidate / ".aragora").exists():
            return candidate
    return cwd


def _encode_cursor(kind: _CursorKind, value: str) -> str:
    token = f"{kind}:{value}".encode("utf-8")
    return base64.urlsafe_b64encode(token).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, *, expected_kind: _CursorKind) -> str:
    raw = cursor.strip()
    if not raw:
        raise ValueError("cursor missing")

    padding = "=" * (-len(raw) % 4)
    try:
        decoded = base64.urlsafe_b64decode(raw + padding).decode("utf-8")
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("cursor invalid") from exc

    prefix = f"{expected_kind}:"
    if not decoded.startswith(prefix):
        raise ValueError("cursor kind mismatch")

    value = decoded[len(prefix) :]
    if not value:
        raise ValueError("cursor value missing")
    return value


def _build_weak_etag(value: str) -> str:
    return f'W/"{value}"'


def _not_modified(etag: str) -> HandlerResult:
    return HandlerResult(
        status_code=304,
        content_type="application/json",
        body=b"",
        headers={"ETag": etag},
    )


def _header_value(handler: Any, name: str) -> str | None:
    headers = getattr(handler, "headers", None)
    if headers is None:
        return None

    try:
        items = headers.items()
    except AttributeError:
        value = getattr(headers, name, None)
        return value if isinstance(value, str) else None

    for key, value in items:
        if isinstance(key, str) and key.lower() == name.lower() and isinstance(value, str):
            return value
    return None


def _parse_limit(raw: Any) -> int:
    try:
        value = int(str(raw).strip()) if raw is not None else _DEFAULT_PAGE_SIZE
    except (TypeError, ValueError):
        value = _DEFAULT_PAGE_SIZE
    return max(1, min(value, _MAX_PAGE_SIZE))


class AgentBridgeHandler(BaseHandler):
    """Expose persisted agent-bridge state and feature-gated operator writes."""

    ROUTES = ["/api/v1/agent-bridge/runs"]

    def __init__(self, ctx: dict[str, Any] | None = None) -> None:
        super().__init__(ctx or {})
        self._store = BridgeStore(_bridge_repo_root(self.ctx))

    def can_handle(self, path: str, method: str = "GET") -> bool:
        method = method.upper()
        normalized = strip_version_prefix(path).rstrip("/")
        if method == "GET":
            return normalized == _RUNS_PATH or normalized.startswith(_RUNS_PREFIX)
        if method == "POST":
            if normalized == _RUNS_PATH:
                return True
            if not normalized.startswith(_RUNS_PREFIX):
                return False
            segments = [
                segment for segment in normalized[len(_RUNS_PREFIX) :].split("/") if segment
            ]
            return len(segments) == 2 and segments[1] in {"dispatch", "auto-step"}
        return False

    @handle_errors("agent bridge read API")  # type: ignore[untyped-decorator]
    @require_permission(PERM_AGENT_BRIDGE_READ.key)
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        method = str(getattr(handler, "command", "GET") or "GET").upper()
        normalized = strip_version_prefix(path).rstrip("/")
        if method == "POST":
            return self._handle_post(normalized, handler)
        if method != "GET":
            return error_response("Method not allowed", 405)

        if normalized == _RUNS_PATH:
            return self._handle_list_runs(query_params)
        if not normalized.startswith(_RUNS_PREFIX):
            return None

        tail = normalized[len(_RUNS_PREFIX) :]
        segments = [segment for segment in tail.split("/") if segment]
        if not segments:
            return error_response("Not found", 404)

        run_id = segments[0]
        if len(segments) == 1:
            return self._handle_get_run(run_id, handler)
        if len(segments) == 2 and segments[1] == "events":
            return self._handle_get_events(run_id, query_params, handler)
        if len(segments) == 2 and segments[1] == "transcript":
            return self._handle_get_transcript(run_id)
        return error_response("Not found", 404)

    @require_permission(PERM_AGENT_BRIDGE_WRITE.key)
    def _handle_post(self, normalized: str, handler: Any) -> HandlerResult:
        if not self._write_enabled():
            return error_response("Agent bridge write API is disabled", 403)

        body, body_error = self.read_json_body_validated(handler)
        if body_error:
            return body_error
        if body is None:
            return error_response("Request body must be a JSON object", 400)

        if normalized == _RUNS_PATH:
            return self._handle_start_run(body)
        if not normalized.startswith(_RUNS_PREFIX):
            return error_response("Not found", 404)

        segments = [segment for segment in normalized[len(_RUNS_PREFIX) :].split("/") if segment]
        if len(segments) != 2:
            return error_response("Not found", 404)
        run_id, action = segments
        if action == "dispatch":
            return self._handle_dispatch_turn(run_id, body)
        if action == "auto-step":
            return self._handle_auto_step(run_id, body)
        return error_response("Not found", 404)

    def _write_enabled(self) -> bool:
        override = self.ctx.get("agent_bridge_write_enabled")
        if override is not None:
            return bool(override)
        try:
            return bool(get_settings().features.agent_bridge_write)
        except Exception:
            logger.exception("Unable to read agent bridge write feature flag")
            return False

    def _broker(self) -> Any:
        broker = self.ctx.get("agent_bridge_broker")
        if broker is not None:
            return broker
        factory = self.ctx.get("agent_bridge_broker_factory", AgentBridgeBroker)
        return factory(_bridge_repo_root(self.ctx), store=self._store)

    def _handle_start_run(self, body: dict[str, Any]) -> HandlerResult:
        task = str(body.get("task", "")).strip()
        if not task:
            return error_response("task is required", 400)

        raw_actors = body.get("actors")
        if not isinstance(raw_actors, list) or not raw_actors:
            return error_response("actors must be a non-empty list", 400)

        sessions: dict[str, BridgeSession] = {}
        top_worktree_path = self._optional_string(body.get("worktree_path"))
        top_worktree_agent_slug = str(body.get("worktree_agent_slug", "codex")).strip() or "codex"
        for raw_actor in raw_actors:
            if not isinstance(raw_actor, dict):
                return error_response("each actor must be a JSON object", 400)
            role = str(raw_actor.get("role", "")).strip()
            harness = str(raw_actor.get("harness", "")).strip()
            if not role or not harness:
                return error_response("each actor requires role and harness", 400)
            if not self._is_valid_slug(role):
                return error_response(f"invalid actor role: {role}", 400)
            if role in sessions:
                return error_response(f"duplicate actor role: {role}", 400)
            harness_options = raw_actor.get("harness_options", {})
            if not isinstance(harness_options, dict):
                return error_response("actor harness_options must be an object", 400)
            sessions[role] = BridgeSession(
                role=role,
                harness=harness,
                model=str(raw_actor.get("model", "") or ""),
                session_id=self._optional_string(raw_actor.get("session_id")),
                worktree_agent_slug=self._optional_string(raw_actor.get("worktree_agent_slug"))
                or top_worktree_agent_slug,
                worktree_path=self._optional_string(raw_actor.get("worktree_path"))
                or top_worktree_path,
                branch=self._optional_string(raw_actor.get("branch")),
                session_status="not_started",
                started_at=None,
                last_turn_index=0,
                last_completed_at=None,
                harness_options=dict(harness_options),
            )

        run_id = self._optional_string(body.get("run_id"))
        if run_id is not None and not self._is_valid_run_id(run_id):
            return error_response("invalid run_id", 400)
        if run_id is not None and self._load_run_or_none(run_id) is not None:
            return error_response("Bridge run already exists", 409)

        next_actor = self._optional_string(body.get("next_actor"))
        if next_actor is not None and next_actor not in sessions:
            return error_response("next_actor must match an actor role", 400)

        repair_budget, repair_error = self._parse_nonnegative_int(
            body.get("repair_budget_per_turn", 1),
            "repair_budget_per_turn",
        )
        if repair_error:
            return repair_error

        broker = self._broker()
        try:
            run = broker.start_run(
                task=task,
                sessions=sessions,
                next_actor=next_actor,
                run_id=run_id,
                worktree_path=top_worktree_path,
                worktree_agent_slug=top_worktree_agent_slug,
                repair_budget_per_turn=repair_budget,
            )
            registry = self._store.load_sessions(run.run_id)
        except Exception as exc:
            logger.exception("Agent bridge start-run failed")
            return error_response(f"Agent bridge start-run failed: {exc}", 500)
        return json_response(self._serialize_run_detail(run, registry), status=201)

    def _handle_dispatch_turn(self, run_id: str, body: dict[str, Any]) -> HandlerResult:
        run, registry, error = self._load_dispatchable_run(run_id)
        if error is not None:
            return error
        if run is None or registry is None:
            return self._not_found()

        role = str(body.get("role", "")).strip()
        prompt = str(body.get("prompt", "")).strip()
        if not role:
            return error_response("role is required", 400)
        if not prompt:
            return error_response("prompt is required", 400)
        if role not in registry.sessions:
            return error_response("Unknown role for bridge run", 400)

        return self._dispatch_turn(run_id=run.run_id, role=role, prompt=prompt)

    def _handle_auto_step(self, run_id: str, body: dict[str, Any]) -> HandlerResult:
        run, registry, error = self._load_dispatchable_run(
            run_id,
            allow_awaiting_human=False,
        )
        if error is not None:
            return error
        if run is None or registry is None:
            return self._not_found()

        role = run.next_actor
        if not role:
            return error_response("Bridge run has no next_actor", 409)
        if role not in registry.sessions:
            return error_response("Bridge run next_actor is not a registered role", 409)

        context_turns, turns_error = self._parse_nonnegative_int(
            body.get("context_turns", 5),
            "context_turns",
        )
        if turns_error:
            return turns_error
        context_turns = min(max(context_turns, 1), 20)

        prompt = str(body.get("prompt", "")).strip()
        if not prompt:
            prompt = self._compose_auto_step_prompt(run, context_turns=context_turns)
        result = self._dispatch_turn(run_id=run.run_id, role=role, prompt=prompt)
        if result.status_code != 200:
            return result
        payload = _json_payload(result)
        payload["auto_step"] = {"role": role, "context_turns": context_turns}
        return json_response(payload)

    def _load_dispatchable_run(
        self,
        run_id: str,
        *,
        allow_awaiting_human: bool = True,
    ) -> tuple[BridgeRun | None, SessionRegistry | None, HandlerResult | None]:
        if not self._is_valid_run_id(run_id):
            return None, None, self._not_found()
        run = self._load_run_or_none(run_id)
        if run is None:
            return None, None, self._not_found()
        if run.status in {"completed", "failed"}:
            return None, None, error_response("Bridge run is not dispatchable", 409)
        if run.status == "awaiting_human" and not allow_awaiting_human:
            return None, None, error_response("Bridge run is awaiting human input", 409)
        try:
            registry = self._store.load_sessions(run_id)
        except FileNotFoundError:
            return None, None, self._not_found()
        return run, registry, None

    def _dispatch_turn(self, *, run_id: str, role: str, prompt: str) -> HandlerResult:
        try:
            event = self._broker().dispatch_turn(run_id=run_id, role=role, prompt=prompt)
        except KeyError:
            return error_response("Unknown role for bridge run", 400)
        except FileNotFoundError:
            return self._not_found()
        except TransportError as exc:
            logger.warning("Agent bridge transport failed for %s/%s: %s", run_id, role, exc)
            return error_response(f"Agent bridge transport failed: {exc}", 502)
        except Exception as exc:
            logger.exception("Agent bridge dispatch failed")
            return error_response(f"Agent bridge dispatch failed: {exc}", 500)
        return json_response(event.to_dict())

    def _compose_auto_step_prompt(self, run: BridgeRun, *, context_turns: int) -> str:
        try:
            events = self._store.load_events(run.run_id)
            turns = self._reconstruct_transcript(run, events)[-context_turns:]
        except Exception:
            logger.exception("Unable to reconstruct bridge transcript for auto-step")
            turns = []

        recent_parts: list[str] = []
        for turn in turns:
            body = str(turn.get("body_markdown", "")).strip()
            footer = turn.get("footer")
            if len(body) > 2500:
                body = body[:2500].rstrip() + "\n[truncated]"
            recent_parts.append(
                "\n".join(
                    [
                        f"Turn {turn.get('turn_index')} by {turn.get('author_role')}:",
                        body or "[no body captured]",
                        f"Footer: {footer if footer is not None else '[missing]'}",
                    ]
                )
            )
        recent = "\n\n".join(recent_parts) if recent_parts else "[no prior turns captured]"
        return (
            "Continue this agent-bridge run by taking the next useful step.\n\n"
            f"Task:\n{run.task}\n\n"
            f"Recent transcript:\n{recent}\n\n"
            "Return a normal response followed by a valid bridge footer. "
            "Set needs_human=true if blocked by missing authority, secrets, protected files, "
            "conflicting ownership, or any irreversible action."
        )

    def _handle_list_runs(self, query_params: dict[str, Any]) -> HandlerResult:
        limit = _parse_limit(query_params.get("limit"))
        cursor = query_params.get("cursor")

        try:
            runs = self._load_all_runs()
            start_index = 0
            if isinstance(cursor, str) and cursor.strip():
                cursor_run_id = _decode_cursor(cursor, expected_kind="run")
                start_index = self._find_run_offset(runs, cursor_run_id)
            page = runs[start_index : start_index + limit]
        except ValueError:
            return self._invalid_cursor()
        except Exception:
            return self._bridge_store_unavailable()

        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "runs": [self._serialize_run_summary(run) for run in page],
        }
        if start_index + limit < len(runs) and page:
            payload["next_cursor"] = _encode_cursor("run", page[-1].run_id)
        return json_response(payload)

    def _handle_get_run(self, run_id: str, handler: Any) -> HandlerResult:
        try:
            run = self._load_run_or_none(run_id)
            if run is None:
                return self._not_found()

            etag = _build_weak_etag(run.updated_at)
            if etag_matches(_header_value(handler, "If-None-Match"), etag):
                return _not_modified(etag)

            sessions = self._store.load_sessions(run_id)
        except FileNotFoundError:
            return self._not_found()
        except Exception:
            return self._bridge_store_unavailable()

        detail = self._serialize_run_detail(run, sessions)
        return json_response(detail, headers={"ETag": etag})

    def _handle_get_events(
        self,
        run_id: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        limit = _parse_limit(query_params.get("limit"))
        cursor = query_params.get("cursor")

        try:
            run = self._load_run_or_none(run_id)
            if run is None:
                return self._not_found()

            events = self._store.load_events(run_id)
            start_index = 0
            cursor_event_id: str | None = None
            if isinstance(cursor, str) and cursor.strip():
                cursor_event_id = _decode_cursor(cursor, expected_kind="event")
                start_index = self._find_event_offset(events, cursor_event_id)

            page = events[start_index : start_index + limit]
            etag_source = (
                page[-1].event_id
                if page
                else cursor_event_id or run.last_event_id or f"{run.run_id}:events:empty"
            )
            etag = _build_weak_etag(etag_source)
            if etag_matches(_header_value(handler, "If-None-Match"), etag):
                return _not_modified(etag)
        except ValueError:
            return self._invalid_cursor()
        except Exception:
            return self._bridge_store_unavailable()

        payload: dict[str, Any] = {
            "schema_version": run.schema_version,
            "events": [self._serialize_event(event) for event in page],
        }
        if start_index + limit < len(events) and page:
            payload["next_cursor"] = _encode_cursor("event", page[-1].event_id)
        return json_response(payload, headers={"ETag": etag})

    def _handle_get_transcript(self, run_id: str) -> HandlerResult:
        try:
            run = self._load_run_or_none(run_id)
            if run is None:
                return self._not_found()

            events = self._store.load_events(run_id)
            turns = self._reconstruct_transcript(run, events)
        except Exception:
            return self._bridge_store_unavailable()

        return json_response({"schema_version": run.schema_version, "turns": turns})

    def _load_all_runs(self) -> list[BridgeRun]:
        runs: list[BridgeRun] = []
        for run_path in self._store.runs_root().glob("*/run.json"):
            runs.append(self._store.load_run(run_path.parent.name))
        runs.sort(key=lambda item: item.updated_at, reverse=True)
        return runs

    def _load_run_or_none(self, run_id: str) -> BridgeRun | None:
        if not self._is_valid_run_id(run_id):
            return None
        run_path = self._store.runs_root() / run_id / "run.json"
        if not run_path.exists():
            return None
        return self._store.load_run(run_id)

    def _find_run_offset(self, runs: list[BridgeRun], cursor_run_id: str) -> int:
        for index, run in enumerate(runs):
            if run.run_id == cursor_run_id:
                return index + 1
        raise ValueError("cursor run missing")

    def _find_event_offset(self, events: list[TurnRecord], cursor_event_id: str) -> int:
        for index, event in enumerate(events):
            if event.event_id == cursor_event_id:
                return index + 1
        raise ValueError("cursor event missing")

    def _is_valid_run_id(self, run_id: str) -> bool:
        ok, _ = validate_path_segment(run_id, "run_id", SAFE_SLUG_PATTERN)
        return ok

    def _is_valid_slug(self, slug: str) -> bool:
        ok, _ = validate_path_segment(slug, "slug", SAFE_SLUG_PATTERN)
        return ok

    def _optional_string(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _parse_nonnegative_int(self, value: Any, name: str) -> tuple[int, HandlerResult | None]:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0, error_response(f"{name} must be an integer", 400)
        if parsed < 0:
            return 0, error_response(f"{name} must be non-negative", 400)
        return parsed, None

    def _serialize_run_summary(self, run: BridgeRun) -> dict[str, Any]:
        payload = run.to_dict()
        return {
            "schema_version": payload["schema_version"],
            "run_id": payload["run_id"],
            "task": payload["task"],
            "status": payload["status"],
            "created_at": payload["created_at"],
            "updated_at": payload["updated_at"],
            "completed_at": payload["completed_at"],
            "last_turn_index": payload["last_turn_index"],
            "next_actor": payload["next_actor"],
            "repair_budget_per_turn": payload["repair_budget_per_turn"],
            "footer_mode": payload["footer_mode"],
            "worktree_cleanup_mode": payload["worktree_cleanup_mode"],
            "participants": payload["participants"],
            "last_event_id": payload["last_event_id"],
        }

    def _serialize_run_detail(
        self,
        run: BridgeRun,
        sessions: SessionRegistry,
    ) -> dict[str, Any]:
        detail = run.to_dict()
        detail["roles"] = {
            role: self._serialize_session_entry(session)
            for role, session in sessions.sessions.items()
        }
        return detail

    def _serialize_session_entry(self, session: BridgeSession) -> dict[str, Any]:
        return session.to_dict()

    def _serialize_event(self, event: TurnRecord) -> dict[str, Any]:
        return event.to_dict()

    def _reconstruct_transcript(
        self,
        run: BridgeRun,
        events: list[TurnRecord],
    ) -> list[dict[str, Any]]:
        allowed_roles = {participant.role for participant in run.participants}
        turns: dict[int, _TranscriptAccumulator] = {}

        for event in events:
            if event.turn_index <= 0:
                continue

            turn = turns.get(event.turn_index)
            if turn is None:
                turn = _TranscriptAccumulator(
                    turn_index=event.turn_index,
                    author_role=event.role,
                    started_at=event.ts,
                )
                turns[event.turn_index] = turn

            if event.event_type == "turn.started":
                turn.author_role = event.role
                turn.started_at = event.ts
                continue

            if event.event_type in {"turn.result", "turn.completed"}:
                turn.completed_at = event.ts
                if event.parse_status is not None:
                    turn.parse_status = event.parse_status
                self._capture_turn_body(turn, event.payload, allowed_roles)
                footer = self._footer_dict_from_payload(event.payload.get("footer"))
                if footer is not None:
                    turn.footer = footer
                continue

            if event.event_type == "footer_ok":
                turn.completed_at = event.ts
                turn.parse_status = event.parse_status or "ok"
                turn.footer = self._footer_dict_from_payload(event.payload.get("footer"))
                continue

            if event.event_type == "footer_missing":
                turn.completed_at = event.ts
                turn.parse_status = event.parse_status or "missing"
                continue

            if event.event_type == "footer_malformed":
                turn.completed_at = event.ts
                turn.parse_status = event.parse_status or "malformed"
                continue

        transcript: list[dict[str, Any]] = []
        for turn_index in sorted(turns):
            turn = turns[turn_index]
            transcript.append(
                {
                    "turn_index": turn.turn_index,
                    "author_role": turn.author_role,
                    "started_at": turn.started_at or "",
                    "completed_at": turn.completed_at,
                    "parse_status": turn.parse_status or "missing",
                    "footer": turn.footer,
                    "body_markdown": turn.body_markdown,
                }
            )
        return transcript

    def _capture_turn_body(
        self,
        turn: _TranscriptAccumulator,
        payload: dict[str, Any],
        allowed_roles: set[str],
    ) -> None:
        if turn.body_captured:
            return

        message_text = payload.get("message_text")
        if message_text is None:
            return
        if not isinstance(message_text, str):
            raise TypeError("turn message_text must be a string")

        parsed_turn = extract_footer(message_text, allowed_roles=allowed_roles)
        turn.body_markdown = parsed_turn.body_without_footer
        turn.body_captured = True
        if turn.parse_status is None:
            turn.parse_status = parsed_turn.parse_status
        if turn.footer is None and parsed_turn.footer is not None:
            turn.footer = parsed_turn.footer.to_dict()

    def _footer_dict_from_payload(self, payload: Any) -> dict[str, Any] | None:
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise TypeError("bridge footer payload must be a mapping")
        return BridgeFooter.from_dict(payload).to_dict()

    def _invalid_cursor(self) -> HandlerResult:
        return error_response("Invalid bridge cursor", 400)

    def _not_found(self) -> HandlerResult:
        return error_response("Bridge run not found", 404)

    def _bridge_store_unavailable(self) -> HandlerResult:
        logger.exception("Agent bridge store unavailable")
        return error_response("bridge store unavailable", 500)


def _json_payload(result: HandlerResult) -> dict[str, Any]:
    raw = result.body.decode("utf-8") if isinstance(result.body, bytes) else str(result.body)
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}
