"""Characterization contracts for the batch-B compliance/identity handlers.

Covers VAL-TYPEIDENTITY-001..006 and the VAL-TYPEALIAS-001 identity rows for
the five batch-B modules (audit export, GDPR self-service deletion, privacy,
SCIM, OAuth compatibility shim). Every case exercises the real services under
the typing harness network guard: a temporary ``AuditLog`` behind the
registered aiohttp routes, a ``GDPRDeletionScheduler`` on a disposable store
that is never started, a SQLite ``UserStore`` with fixture accounts, the
in-memory ``SCIMServer`` and a memory-only OAuth state store. Real local JWTs
and explicit ``AuthorizationContext`` grants drive every auth path; only
narrow pass-through spies, module singletons and one documented
permission-matrix grant are injected.

Observations are recorded with ``record_property("observation", ...)`` after
narrow normalization of generated ids, timestamps and temporary-root prefixes;
raw values are kept in a separate ``raw`` property and asserted in code.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import importlib
import inspect
import io
import json
import os
import re
import tempfile
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

import aragora
from aragora.rbac.models import AuthorizationContext
from aragora.server.auth import auth_config
from aragora.server.handlers.utils import decorators as handler_decorators

HANDLERS_PKG = "aragora.server.handlers"

# module name -> (relocated area, exported symbols that must share identity)
BATCH_B: dict[str, tuple[str, list[str]]] = {
    "audit_export": (
        "compliance",
        ["handle_audit_export", "handle_audit_verify", "register_handlers", "get_audit_log"],
    ),
    "gdpr_deletion": ("compliance", ["GDPRDeletionHandler", "_get_scheduler"]),
    "privacy": ("compliance", ["PrivacyHandler"]),
    "scim_handler": ("auth", ["SCIMHandler"]),
    "_oauth_impl": ("oauth", ["_validate_state", "_validate_state_internal", "OAuthHandler"]),
}

FIXED_START = "2026-01-01T00:00:00Z"
FIXED_END = "2026-01-31T23:59:59Z"
EXPORT_PATH = "/api/v1/audit/export"
VERIFY_PATH = "/api/v1/audit/verify"
DELETION_PATH = "/api/v1/users/self/deletion-request"
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
SCIM_CONTENT_TYPE = "application/scim+json"
PASSWORDS = {
    "member": "readiness-member-pass",
    "owner": "readiness-owner-pass",
    "other": "readiness-other-pass",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def tree_root() -> Path:
    env_root = os.environ.get("TYPING_SNAPSHOT_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return Path(aragora.__file__).resolve().parents[1]


def flat(name: str) -> ModuleType:
    return importlib.import_module(f"{HANDLERS_PKG}.{name}")


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
# Generated tokens embedded inside otherwise-stable strings (integrity messages, generated
# account e-mails, date-stamped filenames). Only the token is replaced; the surrounding text stays.
_GENERATED_TOKEN_RES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), "<uuid>"),
    (re.compile(r"\b[0-9a-f]{32}\b"), "<hash32>"),
    (re.compile(r"tampered-[0-9a-f]{8}\b"), "tampered-<hex8>"),
    (re.compile(r"deleted_[0-9a-f]{8}@"), "deleted_<hex8>@"),
    (re.compile(r"_20\d{6}\."), "_<date>."),
)
_ALWAYS_VOLATILE = frozenset(
    {
        "id",
        "timestamp",
        "expires_at",
        "X-Trace-Id",
        "location",
        "Location",
        "days",
    }
)


def _volatile_key(key: str) -> bool:
    if key in _ALWAYS_VOLATILE:
        return True
    lowered = key.lower()
    return (
        lowered.endswith("_at")
        or lowered.endswith("_id")
        or lowered.endswith("timestamp")
        or "hash" in lowered
    )


def norm(value: Any, roots: tuple[str, ...] = (), known: dict[str, str] | None = None) -> Any:
    """Replace generated/volatile values with typed placeholders."""
    known = known or {}
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if _volatile_key(str(key)):
                out[str(key)] = None if item is None else f"<{type(item).__name__}>"
            else:
                out[str(key)] = norm(item, roots, known)
        return out
    if isinstance(value, (list, tuple)):
        return [norm(item, roots, known) for item in value]
    if isinstance(value, str):
        text = value
        for raw, placeholder in known.items():
            if raw:
                text = text.replace(raw, placeholder)
        for root in sorted(roots, key=len, reverse=True):
            if root:
                text = text.replace(root, "<tmp>")
        if _ISO_RE.match(text):
            return "<ts>"
        for pattern, placeholder in _GENERATED_TOKEN_RES:
            text = pattern.sub(placeholder, text)
        return text
    return value


def tmp_roots(tmp_path: Path) -> tuple[str, ...]:
    candidates = {
        str(tmp_path),
        str(tmp_path.resolve()),
        os.path.realpath(tmp_path),
        tempfile.gettempdir(),
        os.path.realpath(tempfile.gettempdir()),
    }
    return tuple(sorted(candidates, key=len, reverse=True))


def observe(record_property: Any, observation: Any, raw: Any = None) -> None:
    record_property("observation", json.dumps(observation, sort_keys=True, default=str))
    if raw is not None:
        record_property("raw", json.dumps(raw, sort_keys=True, default=str))


def payload(result: Any) -> Any:
    body = getattr(result, "body", b"")
    if not body:
        return None
    if isinstance(body, str):
        body = body.encode("utf-8")
    try:
        return json.loads(body)
    except ValueError:
        return body.decode("utf-8", "replace")


def summarize(result: Any, roots: tuple[str, ...] = (), known: dict[str, str] | None = None) -> Any:
    if result is None:
        return None
    headers = dict(getattr(result, "headers", {}) or {})
    return {
        "status": result.status_code,
        "content_type": getattr(result, "content_type", None),
        "body": norm(payload(result), roots, known),
        "headers": norm(headers, roots, known),
    }


def context(*permissions: str, user_id: str = "readiness-user") -> AuthorizationContext:
    return AuthorizationContext(
        user_id=user_id,
        org_id="readiness-org",
        workspace_id="readiness-ws",
        roles={"readiness"},
        permissions=set(permissions),
    )


class Spy:
    """Pass-through spy that records call arguments and forwards to the target."""

    def __init__(self, target: Any) -> None:
        self.target = target
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.results: list[Any] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        result = self.target(*args, **kwargs)
        self.results.append(result)
        return result

    @property
    def count(self) -> int:
        return len(self.calls)


class Request:
    """Minimal request shim carrying the attributes the handlers actually read."""

    def __init__(
        self,
        *,
        method: str = "GET",
        path: str = "/",
        body: Any = None,
        headers: dict[str, str] | None = None,
        auth: AuthorizationContext | None = None,
        client: str = "127.0.0.1",
    ) -> None:
        if body is None:
            raw = b""
        elif isinstance(body, (bytes, bytearray)):
            raw = bytes(body)
        else:
            raw = json.dumps(body).encode("utf-8")
        self.command = method
        self.path = path
        self.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
        self.headers.update(headers or {})
        self.rfile = io.BytesIO(raw)
        self.client_address = (client, 41000)
        if auth is not None:
            self._auth_context = auth


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def run(coro_or_value: Any) -> Any:
    if inspect.iscoroutine(coro_or_value):
        return asyncio.run(coro_or_value)
    return coro_or_value


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rbac_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real RBAC decorator behaviour: auth enabled, no fixture bypass active."""
    assert handler_decorators._test_user_context_override is None
    monkeypatch.setattr(auth_config, "enabled", True)


@pytest.fixture
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = os.environ.get("ARAGORA_JWT_SECRET")
    if not secret:
        secret = "readiness-local-test-secret-never-a-real-credential"
        monkeypatch.setenv("ARAGORA_JWT_SECRET", secret)
        from aragora.billing.auth import config as billing_auth_config

        monkeypatch.setattr(billing_auth_config, "_jwt_secret_cache", None)
    return secret


def access_token(
    user_id: str, email: str, *, org_id: str | None = None, role: str = "owner"
) -> str:
    from aragora.billing.jwt_auth import create_access_token

    return create_access_token(user_id, email, org_id=org_id, role=role)


# ---------------------------------------------------------------------------
# VAL-TYPEIDENTITY-001 / -002: audit export and verification on a real AuditLog
# ---------------------------------------------------------------------------


def _seed_audit_log(
    db_path: Path, count: int, days: list[int] | None = None
) -> tuple[Any, list[Any]]:
    from aragora.audit import AuditCategory, AuditEvent, AuditLog, AuditOutcome

    audit = AuditLog(db_path=db_path)
    events = []
    for index in range(count):
        day = days[index] if days else 1 + index
        event = AuditEvent(
            category=AuditCategory.AUTH,
            action=f"readiness.action.{index}",
            actor_id=f"actor-{index}",
            resource_type="session",
            resource_id=f"session-{index}",
            outcome=AuditOutcome.SUCCESS,
            org_id="readiness-org",
            timestamp=datetime(2026, 1, day, 12, 0, index % 60, tzinfo=timezone.utc),
        )
        audit.log(event)
        events.append(event)
    return audit, events


@pytest.fixture
def audit_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, jwt_secret: str) -> dict[str, Any]:
    module = flat("audit_export")
    audit, events = _seed_audit_log(tmp_path / "audit" / "audit.db", 2, days=[10, 20])
    monkeypatch.setattr(module, "_audit_log", audit)
    exports = tmp_path / "exports"
    exports.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(exports))
    created: list[str] = []
    real_named_temporary_file = tempfile.NamedTemporaryFile

    def spy_named_temporary_file(*args: Any, **kwargs: Any) -> Any:
        handle = real_named_temporary_file(*args, **kwargs)
        created.append(handle.name)
        return handle

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", spy_named_temporary_file)
    token = access_token("readiness-auditor", "auditor@readiness.invalid", org_id="readiness-org")
    return {
        "module": module,
        "audit": audit,
        "events": events,
        "exports": exports,
        "created": created,
        "token": token,
    }


@contextlib.asynccontextmanager
async def audit_client(module: ModuleType) -> AsyncIterator[TestClient]:
    app = web.Application()
    module.register_handlers(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()


def inventory(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


def export_body(fmt: str | None = "json") -> dict[str, Any]:
    body: dict[str, Any] = {"start_date": FIXED_START, "end_date": FIXED_END}
    if fmt is not None:
        body["format"] = fmt
    return body


async def transport(resp: Any) -> dict[str, Any]:
    text = await resp.text()
    try:
        body: Any = json.loads(text)
    except ValueError:
        body = text
    return {
        "status": resp.status,
        "content_type": resp.content_type,
        "headers": {
            key: resp.headers[key]
            for key in ("Content-Disposition", "X-Audit-Event-Count")
            if key in resp.headers
        },
        "body": body,
    }


@pytest.mark.no_auto_auth
class TestTYPEIDENTITY001AuditExport:
    @pytest.mark.parametrize(
        "case",
        [
            "json",
            "csv",
            "soc2",
            "empty",
            "malformed",
            "non_object",
            "missing_start",
            "missing_end",
            "invalid_date",
            "invalid_format",
            "exporter_failure",
            "denied_auth",
        ],
    )
    async def test_TYPEIDENTITY_001_export(
        self,
        case: str,
        audit_env: dict[str, Any],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        record_property: Any,
    ) -> None:
        module = audit_env["module"]
        audit = audit_env["audit"]
        exports: Path = audit_env["exports"]
        created: list[str] = audit_env["created"]
        auth = bearer(audit_env["token"])
        roots = tmp_roots(tmp_path)
        event_ids = sorted(event.id for event in audit_env["events"])
        known = {event_id: f"<event_{index}>" for index, event_id in enumerate(event_ids)}
        before = inventory(exports)
        observation: dict[str, Any] = {"case": case, "temp_before": before}
        raw: dict[str, Any] = {"case": case, "event_ids": event_ids}

        if case == "denied_auth":
            request = make_mocked_request(
                "POST", EXPORT_PATH, headers={"Content-Type": "application/json"}
            )
            direct = await module.handle_audit_export(request)
            assert not isinstance(direct, web.StreamResponse)
            assert direct.status_code == 401
            assert payload(direct) == {"error": "Authentication required"}
            async with audit_client(module) as client:
                resp = await client.post(EXPORT_PATH, json=export_body())
                result = await transport(resp)
            # aiohttp refuses the decorator's HandlerResult as a response object
            assert result["status"] == 500
            observation["direct_entry"] = summarize(direct)
            observation["transport"] = norm(result, roots, known)
            observation["distinction"] = (
                "direct entry returns HandlerResult 401; transport surfaces aiohttp 500"
            )
        else:
            async with audit_client(module) as client:
                if case in {"json", "csv", "soc2"}:
                    resp = await client.post(EXPORT_PATH, json=export_body(case), headers=auth)
                elif case == "empty":
                    resp = await client.post(
                        EXPORT_PATH,
                        data=b"",
                        headers={**auth, "Content-Type": "application/json"},
                    )
                elif case == "malformed":
                    resp = await client.post(
                        EXPORT_PATH,
                        data=b"{not json",
                        headers={**auth, "Content-Type": "application/json"},
                    )
                elif case == "non_object":
                    resp = await client.post(
                        EXPORT_PATH,
                        data=b"[1, 2]",
                        headers={**auth, "Content-Type": "application/json"},
                    )
                elif case == "missing_start":
                    resp = await client.post(EXPORT_PATH, json={}, headers=auth)
                elif case == "missing_end":
                    resp = await client.post(
                        EXPORT_PATH, json={"start_date": FIXED_START}, headers=auth
                    )
                elif case == "invalid_date":
                    resp = await client.post(
                        EXPORT_PATH,
                        json={"start_date": "yesterday", "end_date": FIXED_END},
                        headers=auth,
                    )
                elif case == "invalid_format":
                    resp = await client.post(EXPORT_PATH, json=export_body("xml"), headers=auth)
                elif case == "exporter_failure":

                    def exporter_fault(*args: Any, **kwargs: Any) -> int:
                        raise RuntimeError("readiness exporter fault")

                    monkeypatch.setattr(audit, "export_json", exporter_fault)
                    resp = await client.post(EXPORT_PATH, json=export_body("json"), headers=auth)
                result = await transport(resp)
            raw["transport"] = result

            if case in {"json", "csv", "soc2"}:
                assert result["status"] == 200
                assert result["headers"]["X-Audit-Event-Count"] == "2"
                if case == "json":
                    assert result["content_type"] == "application/json"
                    assert result["headers"]["Content-Disposition"] == (
                        'attachment; filename="audit_export_2026-01-01_2026-01-31.json"'
                    )
                    assert result["body"]["event_count"] == 2
                    assert sorted(e["id"] for e in result["body"]["events"]) == event_ids
                elif case == "csv":
                    assert result["content_type"] == "text/csv"
                    assert result["headers"]["Content-Disposition"] == (
                        'attachment; filename="audit_export_2026-01-01_2026-01-31.csv"'
                    )
                    rows = list(csv.DictReader(io.StringIO(result["body"])))
                    assert sorted(row["id"] for row in rows) == event_ids
                    observation["csv_columns"] = list(rows[0].keys())
                else:
                    assert result["content_type"] == "application/json"
                    assert result["headers"]["Content-Disposition"] == (
                        'attachment; filename="soc2_audit_2026-01-01_2026-01-31.json"'
                    )
                    assert result["body"]["report_type"] == "SOC 2 Type II Audit Log Export"
                    assert result["body"]["integrity"]["chain_verified"] is True
                    assert sorted(e["id"] for e in result["body"]["events"]) == event_ids
                assert len(created) == 1
            elif case in {"empty", "malformed", "non_object"}:
                code = {
                    "empty": ("EMPTY_BODY", "Empty request body"),
                    "malformed": ("INVALID_JSON", "Invalid JSON body"),
                    "non_object": ("INVALID_BODY_TYPE", "Request body must be a JSON object"),
                }[case]
                assert result["status"] == 400
                assert result["body"] == {"error": code[1], "code": code[0]}
                assert created == []
            elif case in {"missing_start", "missing_end", "invalid_date"}:
                message = {
                    "missing_start": "start_date is required",
                    "missing_end": "end_date is required",
                    "invalid_date": "Invalid date format. Use ISO 8601.",
                }[case]
                assert result["status"] == 400
                assert result["body"]["error"] == message
                assert created == []
            elif case == "invalid_format":
                assert result["status"] == 400
                assert result["body"]["error"] == "Invalid format: xml. Use json, csv, or soc2."
                assert len(created) == 1
            elif case == "exporter_failure":
                assert result["status"] == 500
                assert len(created) == 1
                observation["supplemental"] = "instance export_json fault; transport preserved"
            observation["transport"] = norm(result, roots, known)

        after = inventory(exports)
        assert after == before
        assert all(not Path(path).exists() for path in created)
        observation["temp_after"] = after
        observation["temp_created"] = len(created)
        observation["temp_created_under_exports"] = all(
            Path(path).parent == exports for path in created
        )
        observe(record_property, observation, raw=raw)


@pytest.mark.no_auto_auth
class TestTYPEIDENTITY002AuditVerify:
    @pytest.mark.parametrize(
        "case",
        [
            "object_full_range",
            "empty_full_range",
            "malformed_full_range",
            "nonobject_full_range",
            "dated_range",
            "invalid_start",
            "invalid_end",
            "error_cap",
        ],
    )
    async def test_TYPEIDENTITY_002_verify(
        self,
        case: str,
        audit_env: dict[str, Any],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        record_property: Any,
    ) -> None:
        module = audit_env["module"]
        audit = audit_env["audit"]
        auth = bearer(audit_env["token"])
        roots = tmp_roots(tmp_path)
        observation: dict[str, Any] = {"case": case}
        raw: dict[str, Any] = {"case": case}
        tampered = 0

        if case == "error_cap":
            # Real tampered fixture: 25 records, 12 stored hashes overwritten so the
            # real verifier reports both a hash mismatch and a broken chain link each.
            audit, events = _seed_audit_log(tmp_path / "tampered" / "audit.db", 25)
            monkeypatch.setattr(module, "_audit_log", audit)
            for event in events[:12]:
                audit._backend.execute_write(
                    "UPDATE audit_events SET event_hash = ? WHERE id = ?",
                    (f"tampered-{event.id[:8]}", event.id),
                )
                tampered += 1
        assert module.get_audit_log() is audit
        assert Path(audit.db_path).resolve().is_relative_to(tmp_path.resolve())
        full_valid, full_errors = audit.verify_integrity()
        verify_spy = Spy(audit.verify_integrity)
        monkeypatch.setattr(audit, "verify_integrity", verify_spy)

        async with audit_client(module) as client:
            if case in {"object_full_range", "error_cap"}:
                resp = await client.post(VERIFY_PATH, json={}, headers=auth)
            elif case == "empty_full_range":
                resp = await client.post(
                    VERIFY_PATH, data=b"", headers={**auth, "Content-Type": "application/json"}
                )
            elif case == "malformed_full_range":
                resp = await client.post(
                    VERIFY_PATH,
                    data=b"{oops",
                    headers={**auth, "Content-Type": "application/json"},
                )
            elif case == "nonobject_full_range":
                resp = await client.post(
                    VERIFY_PATH, data=b"[1]", headers={**auth, "Content-Type": "application/json"}
                )
            elif case == "dated_range":
                resp = await client.post(
                    VERIFY_PATH,
                    json={"start_date": FIXED_START, "end_date": FIXED_END},
                    headers=auth,
                )
            elif case == "invalid_start":
                resp = await client.post(VERIFY_PATH, json={"start_date": "nope"}, headers=auth)
            elif case == "invalid_end":
                resp = await client.post(
                    VERIFY_PATH,
                    json={"start_date": FIXED_START, "end_date": "nope"},
                    headers=auth,
                )
            result = await transport(resp)
        raw["transport"] = result
        raw["verifier_args"] = [args for args, _ in verify_spy.calls]

        if case in {"invalid_start", "invalid_end"}:
            assert result["status"] == 400
            assert (
                result["body"]["error"]
                == {
                    "invalid_start": "Invalid start_date format",
                    "invalid_end": "Invalid end_date format",
                }[case]
            )
            assert verify_spy.count == 0
        else:
            assert result["status"] == 200
            assert verify_spy.count == 1
            body = result["body"]
            if case == "dated_range":
                expected_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
                expected_end = datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc)
                assert verify_spy.calls[0][0] == (expected_start, expected_end)
                assert body["verified_range"] == {
                    "start_date": expected_start.isoformat(),
                    "end_date": expected_end.isoformat(),
                }
                assert body["verified"] is True and body["errors"] == []
            else:
                assert verify_spy.calls[0][0] == (None, None)
                assert body["verified_range"] == {"start_date": "beginning", "end_date": "now"}
                if case == "error_cap":
                    assert full_valid is False
                    assert len(full_errors) > 20
                    assert body["verified"] is False
                    assert body["errors"] == full_errors[:20]
                    assert body["total_errors"] == len(full_errors)
                    assert body["total_errors"] > 20
                    observation["full_error_count"] = len(full_errors)
                    observation["error_kinds"] = sorted(
                        {"chain" if e.startswith("Hash chain") else "hash" for e in full_errors}
                    )
                    observation["tampered_records"] = tampered
                    observation["fixture_records"] = 25
                    observation["supplemental"] = False
                    raw["full_errors"] = full_errors
                else:
                    assert full_valid is True
                    assert body == {
                        "verified": True,
                        "errors": [],
                        "total_errors": 0,
                        "verified_range": {"start_date": "beginning", "end_date": "now"},
                    }
        observation["transport"] = norm(result, roots)
        observation["verifier_calls"] = [
            [None if value is None else value.isoformat() for value in args]
            for args, _ in verify_spy.calls
        ]
        observation["audit_db_under_tmp"] = True
        observe(record_property, observation, raw=raw)


# ---------------------------------------------------------------------------
# VAL-TYPEIDENTITY-003: GDPR self-service deletion on a disposable scheduler
# ---------------------------------------------------------------------------


@pytest.fixture
def gdpr_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, jwt_secret: str) -> dict[str, Any]:
    from aragora.privacy import deletion as deletion_module

    store = deletion_module.DeletionStore(tmp_path / "deletion" / "deletion_store.json")
    scheduler = deletion_module.GDPRDeletionScheduler(store=store)
    monkeypatch.setattr(deletion_module, "_deletion_scheduler", scheduler)
    execute_spy = Spy(scheduler.execute_deletion)
    start_spy = Spy(scheduler.start)
    monkeypatch.setattr(scheduler, "execute_deletion", execute_spy)
    monkeypatch.setattr(scheduler, "start", start_spy)
    module = flat("gdpr_deletion")
    token = access_token("readiness-gdpr-user", "gdpr@readiness.invalid", role="owner")
    return {
        "module": module,
        "deletion_module": deletion_module,
        "store": store,
        "scheduler": scheduler,
        "execute_spy": execute_spy,
        "start_spy": start_spy,
        "token": token,
        "user_id": "readiness-gdpr-user",
    }


def grant_deletion_permissions(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The real matrix has no privacy deletion keys; grant them to ``owner`` so the
    real decorator path (JWT extraction plus role check) can reach the handler."""
    granted = []
    for key in ("privacy:request_deletion", "privacy:cancel_deletion"):
        assert key not in handler_decorators.PERMISSION_MATRIX
        monkeypatch.setitem(handler_decorators.PERMISSION_MATRIX, key, ["owner"])
        granted.append(key)
    return granted


@pytest.mark.no_auto_auth
class TestTYPEIDENTITY003GDPRDeletion:
    @pytest.mark.parametrize(
        "case",
        [
            "schedule_default",
            "read_pending",
            "duplicate",
            "cancel",
            "cancel_missing",
            "grace_zero",
            "grace_high",
            "grace_string",
            "grace_min",
            "grace_max",
            "unauthenticated",
            "unknown",
            "cancel_conflict",
            "lazy_identity",
            "matrix_denied",
        ],
    )
    def test_TYPEIDENTITY_003_deletion(
        self,
        case: str,
        gdpr_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        record_property: Any,
    ) -> None:
        module = gdpr_env["module"]
        store = gdpr_env["store"]
        scheduler = gdpr_env["scheduler"]
        user_id = gdpr_env["user_id"]
        auth = bearer(gdpr_env["token"])
        handler = module.GDPRDeletionHandler({})
        observation: dict[str, Any] = {"case": case}
        raw: dict[str, Any] = {"case": case}
        known: dict[str, str] = {}
        if case != "matrix_denied":
            observation["granted"] = grant_deletion_permissions(monkeypatch)

        def post(
            body: Any = None, headers: dict[str, str] | None = None, path: str = DELETION_PATH
        ):
            request = Request(
                method="POST", body=body, headers=auth if headers is None else headers
            )
            return handler.handle_post(path, {}, request)

        def get(headers: dict[str, str] | None = None, path: str = DELETION_PATH):
            request = Request(method="GET", headers=auth if headers is None else headers)
            return handler.handle(path, {}, request)

        def delete(
            body: Any = None, headers: dict[str, str] | None = None, path: str = DELETION_PATH
        ):
            request = Request(
                method="DELETE", body=body, headers=auth if headers is None else headers
            )
            return handler.handle_delete(path, {}, request)

        def schedule(body: Any = None) -> Any:
            result = post(body)
            assert result.status_code == 201, payload(result)
            request_id = payload(result)["request_id"]
            known[request_id] = "<request_id>"
            return result

        def offset_days(request_id: str) -> int:
            stored = store.get_request(request_id)
            return (stored.scheduled_for - stored.created_at).days

        results: dict[str, Any] = {}
        if case == "schedule_default":
            results["post"] = schedule({})
            body = payload(results["post"])
            assert body["user_id"] == user_id
            assert body["status"] == "pending"
            assert body["reason"] == "User-initiated deletion request"
            assert offset_days(body["request_id"]) == 30
            observation["scheduled_offset_days"] = 30
        elif case == "read_pending":
            results["post"] = schedule({"reason": "readiness read"})
            results["get"] = get()
            body = payload(results["get"])
            assert results["get"].status_code == 200
            assert body["has_pending_request"] is True
            assert [r["request_id"] for r in body["requests"]] == [
                payload(results["post"])["request_id"]
            ]
        elif case == "duplicate":
            results["post"] = schedule({})
            results["second"] = post({})
            assert results["second"].status_code == 409
            assert payload(results["second"]) == {
                "error": "A deletion request is already pending for this account"
            }
            assert len(store.get_requests_for_user(user_id)) == 1
        elif case == "cancel":
            results["post"] = schedule({})
            request_id = payload(results["post"])["request_id"]
            assert store.get_request(request_id).status.value == "pending"
            results["delete"] = delete({})
            body = payload(results["delete"])
            assert results["delete"].status_code == 200
            assert body["request_id"] == request_id
            assert body["status"] == "cancelled"
            assert store.get_request(request_id).status.value == "cancelled"
            assert store.get_request(request_id).cancelled_reason == (
                "User cancelled deletion request"
            )
            observation["store_transition"] = ["pending", "cancelled"]
        elif case == "cancel_missing":
            results["delete"] = delete({})
            assert results["delete"].status_code == 404
            assert payload(results["delete"]) == {"error": "No pending deletion request found"}
        elif case in {"grace_zero", "grace_high", "grace_string"}:
            value = {"grace_zero": 0, "grace_high": 366, "grace_string": "30"}[case]
            results["post"] = post({"grace_period_days": value})
            assert results["post"].status_code == 400
            assert payload(results["post"]) == {
                "error": {
                    "grace_zero": "grace_period_days must be a positive integer",
                    "grace_high": "grace_period_days cannot exceed 365",
                    "grace_string": "grace_period_days must be a positive integer",
                }[case]
            }
            assert store.get_requests_for_user(user_id) == []
        elif case in {"grace_min", "grace_max"}:
            value = {"grace_min": 1, "grace_max": 365}[case]
            results["post"] = schedule({"grace_period_days": value})
            assert offset_days(payload(results["post"])["request_id"]) == value
            observation["scheduled_offset_days"] = value
        elif case == "unauthenticated":
            anonymous = {"Content-Type": "application/json"}
            results["get"] = get(headers=anonymous)
            results["post"] = post({}, headers=anonymous)
            results["delete"] = delete({}, headers=anonymous)
            for key in ("get", "post", "delete"):
                assert results[key].status_code == 401, key
                assert payload(results[key]) == {"error": "Authentication required"}
            assert store.get_requests_for_user(user_id) == []
        elif case == "unknown":
            other = "/api/v1/users/self/other"
            assert get(path=other) is None
            assert post({}, path=other) is None
            assert delete({}, path=other) is None
            observation["unknown_path_results"] = [None, None, None]
        elif case == "cancel_conflict":
            results["post"] = schedule({})
            request_id = payload(results["post"])["request_id"]

            def conflict(**kwargs: Any) -> Any:
                raise ValueError("readiness injected cancellation conflict")

            monkeypatch.setattr(scheduler, "cancel_deletion", conflict)
            results["delete"] = delete({})
            assert results["delete"].status_code == 409
            assert payload(results["delete"]) == {"error": "Conflict"}
            assert store.get_request(request_id).status.value == "pending"
            observation["supplemental"] = "injected scheduler.cancel_deletion ValueError"
        elif case == "lazy_identity":
            assert "get_deletion_scheduler" not in vars(module)
            first = module._get_scheduler()
            second = module._get_scheduler()
            assert first is scheduler and second is scheduler
            assert isinstance(first, gdpr_env["deletion_module"].GDPRDeletionScheduler)
            assert first.store is store
            observation["lazy_import"] = True
            observation["same_scheduler_on_repeat"] = True
        elif case == "matrix_denied":
            results["post"] = post({})
            assert results["post"].status_code == 403
            assert payload(results["post"]) == {"error": "Permission denied"}
            assert store.get_requests_for_user(user_id) == []
            observation["supplemental"] = (
                "real PERMISSION_MATRIX lacks privacy:request_deletion; owner role denied"
            )

        assert gdpr_env["execute_spy"].count == 0
        assert gdpr_env["start_spy"].count == 0
        assert scheduler._running is False and scheduler._task is None
        observation["results"] = {
            key: summarize(value, known=known) for key, value in results.items()
        }
        observation["store_requests"] = [
            {"status": r.status.value, "user_id": "<fixture>"}
            for r in store.get_requests_for_user(user_id)
        ]
        observation["deletion_executor_calls"] = 0
        observation["scheduler_started"] = False
        raw["results"] = {key: summarize(value) for key, value in results.items()}
        observe(record_property, observation, raw=raw)


# ---------------------------------------------------------------------------
# VAL-TYPEIDENTITY-004: privacy handler on a real SQLite user store
# ---------------------------------------------------------------------------


@pytest.fixture
def privacy_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, jwt_secret: str, rbac_enabled: None
) -> dict[str, Any]:
    from aragora.billing.models import HASH_VERSION_SHA256, _hash_password_sha256
    from aragora.storage.user_store.sqlite_store import UserStore

    store = UserStore(tmp_path / "users" / "users.db")

    def make_user(key: str) -> Any:
        digest, salt = _hash_password_sha256(PASSWORDS[key])
        return store.create_user(
            email=f"{key}@readiness.invalid",
            password_hash=f"{HASH_VERSION_SHA256}{digest}",
            password_salt=salt,
            name=f"Readiness {key.title()}",
        )

    member = make_user("member")
    owner = make_user("owner")
    other = make_user("other")
    org = store.create_organization(name="Readiness Org", owner_id=owner.id)
    assert store.add_user_to_org(owner.id, org.id, role="owner")
    assert store.add_user_to_org(other.id, org.id, role="member")
    assert store.set_user_preferences(
        member.id, {"theme": "dark", "privacy": {"do_not_sell": False}}
    )
    module = flat("privacy")

    def token_for(user: Any, role: str = "member") -> str:
        return access_token(user.id, user.email, org_id=user.org_id, role=role)

    return {
        "module": module,
        "store": store,
        "member": store.get_user_by_id(member.id),
        "owner": store.get_user_by_id(owner.id),
        "other": store.get_user_by_id(other.id),
        "org": org,
        "token_for": token_for,
    }


@pytest.mark.no_auto_auth
class TestTYPEIDENTITY004Privacy:
    @pytest.mark.parametrize(
        "case",
        [
            "export_json_v1",
            "export_json_v2_alias",
            "export_csv",
            "inventory_v1",
            "inventory_v2_alias",
            "preferences_roundtrip",
            "unauth_export",
            "unauth_inventory",
            "unauth_delete",
            "unauth_get_preferences",
            "unauth_update_preferences",
            "unavailable_export",
            "unavailable_delete",
            "unavailable_get_preferences",
            "unavailable_update_preferences",
            "unavailable_inventory_control",
            "delete_invalid_json",
            "delete_unconfirmed",
            "delete_wrong_password",
            "delete_missing_user",
            "delete_owner_restricted",
            "delete_success",
        ],
    )
    def test_TYPEIDENTITY_004_privacy(
        self,
        case: str,
        privacy_env: dict[str, Any],
        tmp_path: Path,
        record_property: Any,
    ) -> None:
        module = privacy_env["module"]
        store = privacy_env["store"]
        member = privacy_env["member"]
        owner = privacy_env["owner"]
        token_for = privacy_env["token_for"]
        roots = tmp_roots(tmp_path)
        known = {
            member.id: "<member_id>",
            owner.id: "<owner_id>",
            privacy_env["other"].id: "<other_id>",
            privacy_env["org"].id: "<org_id>",
        }
        unavailable = case.startswith("unavailable_")
        handler = module.PrivacyHandler({"user_store": None if unavailable else store})
        grant = context("privacy:read", user_id=member.id)
        observation: dict[str, Any] = {"case": case}
        raw: dict[str, Any] = {"case": case}
        results: dict[str, Any] = {}

        def call(
            path: str,
            *,
            method: str = "GET",
            body: Any = None,
            query: dict[str, Any] | None = None,
            user: Any = member,
            token: str | None = None,
        ) -> Any:
            headers: dict[str, str] = {}
            if user is not None:
                headers = bearer(token or token_for(user))
            request = Request(method=method, body=body, headers=headers, auth=grant)
            return handler.handle(path, dict(query or {}), request)

        def snapshot(user_id: str) -> dict[str, Any]:
            user = store.get_user_by_id(user_id)
            return {
                "email": user.email,
                "name": user.name,
                "is_active": user.is_active,
                "org_id": user.org_id,
                "role": user.role,
                "preferences": store.get_user_preferences(user_id),
                # The completion row is written with resource_id only (no user_id):
                # match on either column so both deletion rows are observed.
                "audit_actions": sorted(
                    (row["action"], row.get("user_id") == user_id)
                    for row in store.get_audit_log(resource_type="user", limit=200)
                    if user_id in (row.get("user_id"), row.get("resource_id"))
                ),
            }

        before = {key: snapshot(privacy_env[key].id) for key in ("member", "owner", "other")}

        if case in {"export_json_v1", "export_json_v2_alias"}:
            v1 = call("/api/v1/privacy/export")
            v2 = call("/api/v2/users/me/export")
            results["v1"], results["v2"] = v1, v2
            for result in (v1, v2):
                assert result.status_code == 200
                body = payload(result)
                assert body["profile"]["email"] == member.email
                assert body["profile"]["id"] == member.id
                assert body["preferences"] == {"theme": "dark", "privacy": {"do_not_sell": False}}
                assert body["_export_metadata"]["format"] == "json"
                assert body["_export_metadata"]["legal_basis"] == (
                    "GDPR Article 15 / CCPA Right to Know"
                )
                assert "organization" not in body
            assert norm(payload(v1), roots, known) == norm(payload(v2), roots, known)
            assert v1.content_type == v2.content_type
            observation["alias_bodies_equal"] = True
        elif case == "export_csv":
            result = call("/api/v1/privacy/export", query={"format": "csv"})
            results["csv"] = result
            assert result.status_code == 200
            assert result.content_type == "text/csv; charset=utf-8"
            assert result.headers["Content-Disposition"].startswith(
                "attachment; filename=aragora_export_"
            )
            rows = list(csv.reader(io.StringIO(result.body.decode("utf-8"))))
            assert rows[0] == ["Section", "Field", "Value"]
            assert ["", "email", member.email] in rows
            observation["csv_rows"] = len(rows)
        elif case in {"inventory_v1", "inventory_v2_alias", "unavailable_inventory_control"}:
            v1 = call("/api/v1/privacy/data-inventory")
            v2 = call("/api/v2/users/me/data-inventory")
            results["v1"], results["v2"] = v1, v2
            for result in (v1, v2):
                assert result.status_code == 200
                body = payload(result)
                assert body["data_sold"] is False and body["opt_out_available"] is True
                assert [c["name"] for c in body["categories"]] == [
                    "Identifiers",
                    "Internet Activity",
                    "Geolocation",
                    "Professional Information",
                    "Inferences",
                ]
            assert payload(v1) == payload(v2)
            observation["store_unavailable"] = unavailable
            observation["inventory_503_invented"] = False
        elif case == "preferences_roundtrip":
            initial = call("/api/v1/privacy/preferences")
            update = call(
                "/api/v1/privacy/preferences",
                method="POST",
                body={
                    "do_not_sell": 1,
                    "marketing_opt_out": "yes",
                    "analytics_opt_out": 0,
                    "theme": "light",
                    "third_party_sharing": None,
                },
            )
            final = call("/api/v1/privacy/preferences")
            results.update({"initial": initial, "update": update, "final": final})
            assert payload(initial) == {
                "do_not_sell": False,
                "marketing_opt_out": False,
                "analytics_opt_out": False,
                "third_party_sharing": True,
            }
            assert update.status_code == 200
            assert payload(update) == {
                "message": "Privacy preferences updated",
                "preferences": {
                    "do_not_sell": True,
                    "marketing_opt_out": True,
                    "analytics_opt_out": False,
                    "third_party_sharing": False,
                },
            }
            assert payload(final) == {
                "do_not_sell": True,
                "marketing_opt_out": True,
                "analytics_opt_out": False,
                "third_party_sharing": False,
            }
            stored = store.get_user_preferences(member.id)
            assert stored["theme"] == "dark"
            assert "theme" not in stored["privacy"]
            observation["stored_preferences"] = stored
            observation["audit_actions_added"] = sorted(
                set(snapshot(member.id)["audit_actions"]) - set(before["member"]["audit_actions"])
            )
            assert observation["audit_actions_added"] == [("privacy_preferences_updated", True)]
        elif case.startswith("unauth_"):
            path, method, body = {
                "unauth_export": ("/api/v1/privacy/export", "GET", None),
                "unauth_inventory": ("/api/v1/privacy/data-inventory", "GET", None),
                "unauth_delete": ("/api/v1/privacy/account", "DELETE", {"confirm": True}),
                "unauth_get_preferences": ("/api/v1/privacy/preferences", "GET", None),
                "unauth_update_preferences": (
                    "/api/v1/privacy/preferences",
                    "POST",
                    {"do_not_sell": True},
                ),
            }[case]
            result = call(path, method=method, body=body, user=None)
            results["anonymous"] = result
            assert result.status_code == 401
            assert payload(result) == {"error": "Not authenticated"}
        elif unavailable:
            path, method, body = {
                "unavailable_export": ("/api/v1/privacy/export", "GET", None),
                "unavailable_delete": ("/api/v1/privacy/account", "DELETE", {"confirm": True}),
                "unavailable_get_preferences": ("/api/v1/privacy/preferences", "GET", None),
                "unavailable_update_preferences": (
                    "/api/v1/privacy/preferences",
                    "POST",
                    {"do_not_sell": True},
                ),
            }[case]
            result = call(path, method=method, body=body)
            results["unavailable"] = result
            assert result.status_code == 503
            assert payload(result) == {"error": "Service unavailable"}
        elif case.startswith("delete_"):
            if case == "delete_invalid_json":
                result = call("/api/v1/privacy/account", method="DELETE", body=b"{not json")
                assert result.status_code == 400
                assert payload(result) == {"error": "Invalid JSON body"}
            elif case == "delete_unconfirmed":
                result = call(
                    "/api/v2/users/me", method="DELETE", body={"password": PASSWORDS["member"]}
                )
                assert result.status_code == 400
                assert payload(result) == {
                    "error": "Account deletion must be confirmed with 'confirm': true"
                }
            elif case == "delete_wrong_password":
                result = call(
                    "/api/v1/privacy/account",
                    method="DELETE",
                    body={"confirm": True, "password": "not-the-password"},
                )
                assert result.status_code == 401
                assert payload(result) == {"error": "Invalid password"}
            elif case == "delete_missing_user":
                ghost = access_token("readiness-ghost", "ghost@readiness.invalid", role="member")
                result = call(
                    "/api/v1/privacy/account",
                    method="DELETE",
                    body={"confirm": True, "password": "irrelevant"},
                    token=ghost,
                )
                assert result.status_code == 404
                assert payload(result) == {"error": "User not found"}
            elif case == "delete_owner_restricted":
                result = call(
                    "/api/v1/privacy/account",
                    method="DELETE",
                    body={"confirm": True, "password": PASSWORDS["owner"]},
                    user=owner,
                    token=token_for(owner, role="owner"),
                )
                assert result.status_code == 400
                assert payload(result)["error"].startswith(
                    "Cannot delete account while owning an organization with other members."
                )
                assert len(store.get_org_members(privacy_env["org"].id)) == 2
            elif case == "delete_success":
                result = call(
                    "/api/v1/privacy/account",
                    method="DELETE",
                    body={"confirm": True, "password": PASSWORDS["member"], "reason": "readiness"},
                )
                body = payload(result)
                assert result.status_code == 200, body
                assert body["message"] == "Account deleted successfully"
                assert body["data_deleted"] == ["preferences", "profile"]
                assert body["retention_note"] == (
                    "Audit logs retained for 7 years per compliance requirements"
                )
                deleted = store.get_user_by_id(member.id)
                assert deleted.is_active is False
                assert deleted.name == "[Deleted User]"
                assert deleted.email == f"deleted_{body['deletion_id'][:8]}@deleted.aragora.ai"
                assert store.get_user_preferences(member.id) in ({}, None)
                known[body["deletion_id"]] = "<deletion_id>"
            results["delete"] = result
            after_member = snapshot(member.id)
            if case == "delete_success":
                assert sorted(
                    set(after_member["audit_actions"]) - set(before["member"]["audit_actions"])
                ) == [("account_deletion_completed", False), ("account_deletion_requested", True)]
                observation["fixture_after"] = norm(after_member, roots, known)
            else:
                assert after_member == before["member"]
                assert snapshot(owner.id) == before["owner"]
                observation["fixture_unchanged"] = True

        assert snapshot(privacy_env["other"].id) == before["other"]
        observation["results"] = {
            key: summarize(value, roots, known) for key, value in results.items()
        }
        observation["fixture_before"] = norm(before, roots, known)
        raw["results"] = {key: summarize(value) for key, value in results.items()}
        observe(record_property, observation, raw=raw)


# ---------------------------------------------------------------------------
# VAL-TYPEIDENTITY-005: SCIM handler on the real in-memory SCIMServer
# ---------------------------------------------------------------------------


@pytest.fixture
def scim_env(monkeypatch: pytest.MonkeyPatch, jwt_secret: str) -> dict[str, Any]:
    module = flat("scim_handler")
    assert module.SCIM_AVAILABLE is True
    # The decorated mutation entries validate the Authorization header as a JWT and
    # the SCIM layer compares the same header to its configured bearer token, so the
    # fixture token is a real local JWT configured as the SCIM bearer token.
    token = access_token("readiness-scim", "scim@readiness.invalid", role="owner")
    monkeypatch.setenv("SCIM_BEARER_TOKEN", token)
    monkeypatch.delenv("SCIM_TENANT_ID", raising=False)
    monkeypatch.setenv("SCIM_BASE_URL", "")
    return {"module": module, "token": token}


def scim_user_body(user_name: str, display_name: str) -> dict[str, Any]:
    return {
        "schemas": [SCIM_USER_SCHEMA],
        "userName": user_name,
        "displayName": display_name,
        "emails": [{"value": f"{user_name}@readiness.invalid", "primary": True}],
        "active": True,
    }


def scim_patch(path: str, value: Any) -> dict[str, Any]:
    return {
        "schemas": [SCIM_PATCH_SCHEMA],
        "Operations": [{"op": "replace", "path": path, "value": value}],
    }


@pytest.mark.no_auto_auth
class TestTYPEIDENTITY005SCIM:
    @pytest.mark.parametrize(
        "case",
        [
            "lazy_cache",
            "missing_token",
            "wrong_scheme",
            "wrong_token",
            "correct_token",
            "unconfigured_token",
            "user_crud",
            "group_crud",
            "invalid_json",
            "unknown",
            "missing_module",
        ],
    )
    def test_TYPEIDENTITY_005_scim(
        self,
        case: str,
        scim_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        record_property: Any,
    ) -> None:
        module = scim_env["module"]
        token = scim_env["token"]
        handler = module.SCIMHandler({})
        assert handler._scim_server is None
        auth = bearer(token)
        known = {token: "<redacted-bearer>"}
        observation: dict[str, Any] = {"case": case}
        results: dict[str, Any] = {}

        def req(
            body: Any = None, headers: dict[str, str] | None = None, method: str = "GET"
        ) -> Request:
            return Request(method=method, body=body, headers=auth if headers is None else headers)

        def scim_error(result: Any, detail: str, status: int) -> None:
            assert result.status_code == status
            assert result.content_type == SCIM_CONTENT_TYPE
            assert payload(result) == {
                "schemas": [SCIM_ERROR_SCHEMA],
                "detail": detail,
                "status": str(status),
            }

        if case == "lazy_cache":
            from aragora.auth.scim.server import SCIMServer

            first = handler._get_scim_server()
            second = handler._get_scim_server()
            assert isinstance(first, SCIMServer)
            assert second is first and handler._scim_server is first
            assert first.config.bearer_token == token
            assert first.config.tenant_id is None and first.config.base_url == ""
            observation["server_identity_stable"] = True
            observation["config"] = {"bearer_token": "<redacted-bearer>", "tenant_id": None}
        elif case == "missing_token":
            result = handler.handle("/scim/v2/Users", {}, req(headers={}))
            scim_error(result, "Authorization header required", 401)
            results["missing"] = result
        elif case == "wrong_scheme":
            result = handler.handle(
                "/scim/v2/Users", {}, req(headers={"Authorization": "Basic abc"})
            )
            scim_error(result, "Bearer token required", 401)
            results["wrong_scheme"] = result
        elif case == "wrong_token":
            result = handler.handle(
                "/scim/v2/Users", {}, req(headers={"Authorization": "Bearer not-the-token"})
            )
            scim_error(result, "Invalid bearer token", 401)
            results["wrong"] = result
        elif case == "correct_token":
            result = handler.handle("/scim/v2/Users", {}, req())
            assert result.status_code == 200 and result.content_type == SCIM_CONTENT_TYPE
            body = payload(result)
            assert body["totalResults"] == 0 and body["Resources"] == []
            results["correct"] = result
        elif case == "unconfigured_token":
            monkeypatch.setenv("SCIM_BEARER_TOKEN", "")
            result = handler.handle("/scim/v2/Users", {}, req(headers={}))
            assert result.status_code == 200
            assert payload(result)["totalResults"] == 0
            assert handler._scim_server.config.bearer_token == ""
            results["unconfigured"] = result
            observation["isolated_unconfigured_case"] = True
        elif case == "user_crud":
            created = handler.handle_post(
                "/scim/v2/Users",
                {},
                req(scim_user_body("fixture.user", "Fixture User"), method="POST"),
            )
            assert created.status_code == 201, payload(created)
            user_id = payload(created)["id"]
            known[user_id] = "<scim_user_id>"
            assert payload(created)["userName"] == "fixture.user"
            assert SCIM_USER_SCHEMA in payload(created)["schemas"]
            fetched = handler.handle(f"/scim/v2/Users/{user_id}", {}, req())
            assert fetched.status_code == 200 and payload(fetched)["id"] == user_id
            replaced = handler.handle_put(
                f"/scim/v2/Users/{user_id}",
                {},
                req(scim_user_body("fixture.user", "Replaced User"), method="PUT"),
            )
            assert (
                replaced.status_code == 200 and payload(replaced)["displayName"] == "Replaced User"
            )
            patched = handler.handle_patch(
                f"/scim/v2/Users/{user_id}",
                {},
                req(scim_patch("displayName", "Patched User"), method="PATCH"),
            )
            assert patched.status_code == 200 and payload(patched)["displayName"] == "Patched User"
            deleted = handler.handle_delete(f"/scim/v2/Users/{user_id}", {}, req(method="DELETE"))
            assert deleted.status_code == 204
            assert deleted.body == b"" and deleted.content_type == SCIM_CONTENT_TYPE
            after = handler.handle(f"/scim/v2/Users/{user_id}", {}, req())
            assert after.status_code == 200 and payload(after)["active"] is False
            results.update(
                {
                    "create": created,
                    "get": fetched,
                    "put": replaced,
                    "patch": patched,
                    "delete": deleted,
                    "after": after,
                }
            )
            observation["delete_payload_bytes"] = len(deleted.body)
            observation["soft_delete"] = True
        elif case == "group_crud":
            group_body = {
                "schemas": [SCIM_GROUP_SCHEMA],
                "displayName": "Fixture Group",
                "members": [],
            }
            created = handler.handle_post("/scim/v2/Groups", {}, req(group_body, method="POST"))
            assert created.status_code == 201, payload(created)
            group_id = payload(created)["id"]
            known[group_id] = "<scim_group_id>"
            assert payload(created)["displayName"] == "Fixture Group"
            fetched = handler.handle(f"/scim/v2/Groups/{group_id}", {}, req())
            assert fetched.status_code == 200 and payload(fetched)["id"] == group_id
            replaced = handler.handle_put(
                f"/scim/v2/Groups/{group_id}",
                {},
                req({**group_body, "displayName": "Replaced Group"}, method="PUT"),
            )
            assert (
                replaced.status_code == 200 and payload(replaced)["displayName"] == "Replaced Group"
            )
            member = handler.handle_post(
                "/scim/v2/Users",
                {},
                req(scim_user_body("group.member", "Group Member"), method="POST"),
            )
            assert member.status_code == 201, payload(member)
            member_id = payload(member)["id"]
            known[member_id] = "<scim_member_id>"
            member_patch = {
                "schemas": [SCIM_PATCH_SCHEMA],
                "Operations": [
                    {
                        "op": "add",
                        "path": "members",
                        "value": [{"value": member_id, "display": "Group Member"}],
                    }
                ],
            }
            patched = handler.handle_patch(
                f"/scim/v2/Groups/{group_id}", {}, req(member_patch, method="PATCH")
            )
            assert patched.status_code == 200, payload(patched)
            assert [m["value"] for m in payload(patched)["members"]] == [member_id]
            # Group PATCH only applies member operations; a displayName replace is
            # accepted with 200 but leaves the name untouched.
            ignored = handler.handle_patch(
                f"/scim/v2/Groups/{group_id}",
                {},
                req(scim_patch("displayName", "Patched Group"), method="PATCH"),
            )
            assert (
                ignored.status_code == 200 and payload(ignored)["displayName"] == "Replaced Group"
            )
            listing = handler.handle("/scim/v2/Groups", {}, req())
            assert listing.status_code == 200 and payload(listing)["totalResults"] == 1
            deleted = handler.handle_delete(f"/scim/v2/Groups/{group_id}", {}, req(method="DELETE"))
            assert deleted.status_code == 204 and deleted.body == b""
            after = handler.handle(f"/scim/v2/Groups/{group_id}", {}, req())
            results.update(
                {
                    "create": created,
                    "get": fetched,
                    "put": replaced,
                    "member": member,
                    "patch": patched,
                    "ignored_patch": ignored,
                    "list": listing,
                    "delete": deleted,
                    "after": after,
                }
            )
            observation["delete_payload_bytes"] = len(deleted.body)
            observation["after_delete_status"] = after.status_code
        elif case == "invalid_json":
            result = handler.handle_post("/scim/v2/Users", {}, req(b"{not json", method="POST"))
            scim_error(result, "Invalid JSON in request body", 400)
            results["invalid"] = result
        elif case == "unknown":
            path = "/api/v1/not-scim"
            outcomes = [
                handler.handle(path, {}, req()),
                handler.handle_post(path, {}, req({}, method="POST")),
                handler.handle_put(path, {}, req({}, method="PUT")),
                handler.handle_patch(path, {}, req({}, method="PATCH")),
                handler.handle_delete(path, {}, req(method="DELETE")),
            ]
            assert outcomes == [None] * 5
            observation["unknown_path_results"] = outcomes
        elif case == "missing_module":
            monkeypatch.setattr(module, "SCIM_AVAILABLE", False)
            result = handler.handle("/scim/v2/Users", {}, req())
            assert result.status_code == 503
            assert payload(result) == {"error": "SCIM module not available"}
            assert handler._scim_server is None
            results["missing_module"] = result
            observation["supplemental"] = (
                "SCIM_AVAILABLE flag injected False; server not constructed"
            )

        observation["results"] = {
            key: summarize(value, known=known) for key, value in results.items()
        }
        observation["provider_calls"] = 0
        observe(record_property, observation)


# ---------------------------------------------------------------------------
# VAL-TYPEIDENTITY-006: OAuth compatibility state validation on a memory store
# ---------------------------------------------------------------------------


@pytest.fixture
def memory_state_store(monkeypatch: pytest.MonkeyPatch) -> Any:
    from aragora.server import oauth_state_store as store_module

    store = store_module.FallbackOAuthStateStore(redis_url="", use_sqlite=False, use_jwt=False)
    assert store.backend_name == "memory"
    monkeypatch.setattr(store_module, "_oauth_state_store", store)
    yield store
    store.close()


@pytest.mark.no_auto_auth
class TestTYPEIDENTITY006OAuthState:
    @pytest.mark.parametrize(
        "case",
        ["valid_once", "replay", "expired", "unknown", "delegation", "callback_refusal"],
    )
    def test_TYPEIDENTITY_006_state(
        self,
        case: str,
        memory_state_store: Any,
        monkeypatch: pytest.MonkeyPatch,
        record_property: Any,
    ) -> None:
        from aragora.server import oauth_state_store as store_module

        module = flat("_oauth_impl")
        store = memory_state_store
        assert store_module.get_oauth_state_store() is store
        assert module._validate_state_internal is store_module.validate_oauth_state
        observation: dict[str, Any] = {"case": case, "backend": store.backend_name}
        raw: dict[str, Any] = {"case": case}
        redirect = "http://localhost:3000/after-login"

        if case in {"valid_once", "replay"}:
            state = module._generate_state("readiness-oauth-user", redirect)
            assert store._memory_store.size() == 1
            first = module._validate_state(state)
            assert isinstance(first, dict)
            assert first["user_id"] == "readiness-oauth-user"
            assert first["redirect_url"] == redirect
            assert first["metadata"] is None
            assert (
                isinstance(first["expires_at"], float) and first["expires_at"] > first["created_at"]
            )
            assert store._memory_store.size() == 0
            observation["first"] = norm(first)
            raw["first_keys"] = sorted(first)
            if case == "replay":
                second = module._validate_state(state)
                assert second is None
                observation["second"] = second
        elif case == "expired":
            state = store.generate("readiness-oauth-user", redirect, ttl_seconds=-1)
            result = module._validate_state(state)
            assert result is None
            assert store._memory_store.size() == 0
            observation["result"] = result
        elif case == "unknown":
            result = module._validate_state("never-issued-state")
            assert result is None
            observation["result"] = result
        elif case == "delegation":
            delegate = Spy(module._validate_state_internal)
            monkeypatch.setattr(module, "_validate_state_internal", delegate)
            state = module._generate_state("readiness-oauth-user", redirect)
            result = module._validate_state(state)
            assert delegate.count == 1 and delegate.calls[0] == ((state,), {})
            assert result is delegate.results[0]
            sentinel = {"readiness": "sentinel"}
            monkeypatch.setattr(module, "_validate_state_internal", lambda value: sentinel)
            assert module._validate_state("anything") is sentinel
            observation["delegate_calls"] = delegate.count
            observation["result_identity"] = "delegate return object passed through unmodified"
            observation["wrapper_module"] = module._validate_state.__module__
            observation["delegate_module"] = delegate.target.__module__
        elif case == "callback_refusal":
            handler = module.OAuthHandler({})
            exchange = Spy(handler._exchange_github_code)
            monkeypatch.setattr(handler, "_exchange_github_code", exchange)
            expired = store.generate("readiness-oauth-user", redirect, ttl_seconds=-1)
            outcomes = {}
            for label, state in (("unknown", "never-issued-state"), ("expired", expired)):
                result = run(
                    handler._handle_github_callback(
                        Request(path="/api/v1/auth/oauth/github/callback"),
                        {"state": state, "code": "readiness-code"},
                    )
                )
                assert result.status_code == 302
                location = result.headers["Location"]
                assert location.startswith(module._get_oauth_error_url())
                assert location.endswith("?error=Invalid%20or%20expired%20state")
                outcomes[label] = summarize(result)
            assert exchange.count == 0
            observation["refusals"] = outcomes
            observation["token_exchange_calls"] = 0
        observation["store_size_after"] = store._memory_store.size()
        observe(record_property, observation, raw=raw)


# ---------------------------------------------------------------------------
# VAL-TYPEALIAS-001: legacy/relocated identity rows for the batch-B modules
# ---------------------------------------------------------------------------


def _alias_probe(name: str, module: ModuleType) -> Any:
    """A cheap, deterministic entry behaviour per module used for alias equivalence."""
    if name == "audit_export":
        app = web.Application()
        module.register_handlers(app)
        return sorted(f"{route.method} {route.resource.canonical}" for route in app.router.routes())
    if name == "gdpr_deletion":
        handler = module.GDPRDeletionHandler({})
        return [handler.can_handle(DELETION_PATH), handler.handle("/other", {}, Request())]
    if name == "privacy":
        handler = module.PrivacyHandler({})
        return [handler.can_handle("/api/v1/privacy/export"), handler.can_handle("/api/v1/other")]
    if name == "scim_handler":
        handler = module.SCIMHandler({})
        probe_id = "abc"
        return [
            handler.can_handle("/scim/v2/Users"),
            handler._extract_resource_id(f"/scim/v2/Users/{probe_id}/", "Users"),
        ]
    if name == "_oauth_impl":
        with pytest.MonkeyPatch.context() as local:
            local.setattr(module, "_validate_state_internal", lambda state: ("probe", state))
            return list(module._validate_state("alias-state"))
    raise AssertionError(name)


@pytest.mark.parametrize("name", sorted(BATCH_B))
def test_TYPEALIAS_001_identity(
    name: str, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    area, symbols = BATCH_B[name]
    root = tree_root()
    legacy = flat(name)
    legacy_file = Path(legacy.__file__).resolve()
    assert legacy_file.is_relative_to(root), (legacy_file, root)
    relocated_path = root / "aragora" / "server" / "handlers" / area / f"{name}.py"
    observation: dict[str, Any] = {
        "module": name,
        "area": area,
        "legacy_file": str(legacy_file.relative_to(root)),
        "relocated_present": relocated_path.exists(),
        "symbols": symbols,
    }
    legacy_probe = _alias_probe(name, legacy)
    observation["legacy_probe"] = legacy_probe

    if relocated_path.exists():
        relocated = importlib.import_module(f"{HANDLERS_PKG}.{area}.{name}")
        assert relocated is legacy
        assert Path(relocated.__file__).resolve() == relocated_path.resolve()
        for symbol in symbols:
            assert getattr(legacy, symbol) is getattr(relocated, symbol)
        sentinel = object()
        monkeypatch.setattr(relocated, symbols[0], sentinel)
        assert getattr(legacy, symbols[0]) is sentinel
        monkeypatch.undo()
        if name == "_oauth_impl":
            marker = {"patched": "through-relocated-name"}
            monkeypatch.setattr(relocated, "_validate_state_internal", lambda state: marker)
            assert legacy._validate_state("x") is marker
            monkeypatch.undo()
            observation["delegation_patch_visible"] = True
        assert _alias_probe(name, relocated) == legacy_probe
        observation["identity"] = "shared module object; probe identical through both names"
    else:
        assert legacy_file == (root / "aragora" / "server" / "handlers" / f"{name}.py").resolve()
        observation["identity"] = "not applicable: flat tree, relocated destination absent"
    observe(record_property, observation)
