"""Characterization contracts for the batch-A admin/analytics handlers.

Covers VAL-TYPEADMIN-001..007 and the VAL-TYPEALIAS-001 identity rows for the
nine batch-A modules. Every case exercises the real services (BackupManager on
temporary SQLite, the real RBAC checker with explicit contexts, real analytics
singletons on temporary databases, the real moderation queue) under the typing
harness network guard. Only narrow pass-through spies, module constants and
singleton slots are injected; no whole-module mocks.

Observations are recorded with ``record_property("observation", ...)`` after
narrow normalization of generated ids, timestamps, durations, checksums, sizes
and temporary-root prefixes; the raw values are kept in a separate ``raw``
property and their types/relationships are asserted in code.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import io
import json
import logging
import os
import re
import sqlite3
import sys
import tempfile
import traceback
from collections import OrderedDict
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# Imported at collection time on purpose: the suite's autouse external-API mock
# swaps ``httpx.Client`` during tests, and a TestClient class created while that
# patch is active would subclass the mock instead of the real client.
from fastapi.testclient import TestClient

import aragora
from aragora.rbac.decorators import PermissionDeniedError
from aragora.rbac.models import AuthorizationContext
from aragora.server.auth import auth_config
from aragora.server.handlers.utils import decorators as handler_decorators

HANDLERS_PKG = "aragora.server.handlers"

# module name -> (relocated area, exported symbols that must share identity)
BATCH_A: dict[str, tuple[str, list[str]]] = {
    "backup_handler": ("admin", ["BackupHandler", "create_backup_handler"]),
    "backup_offsite_handler": ("admin", ["BackupOffsiteHandler"]),
    "dr_handler": ("admin", ["DRHandler", "create_dr_handler"]),
    "system_health": ("admin", ["SystemHealthDashboardHandler"]),
    "decision_analytics": ("analytics", ["DecisionAnalyticsHandler", "_get_outcome_analytics"]),
    "moderation_analytics": (
        "analytics",
        ["ModerationAnalyticsHandler", "_get_moderation", "_get_queue_size", "_list_queue"],
    ),
    "spend_analytics": ("analytics", ["SpendAnalyticsHandler"]),
    "differentiation": ("analytics_dashboard", ["DifferentiationHandler"]),
    "outcome_dashboard": ("analytics_dashboard", ["OutcomeDashboardHandler", "_parse_period"]),
}

NONE_ATTR = "'NoneType' object has no attribute '{}'"


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
_ALWAYS_VOLATILE = frozenset(
    {
        "id",
        "drill_id",
        "trace_id",
        "request_id",
        "timestamp",
        "last_check",
        "collection_time_ms",
        "generated_at",
        "size_bytes",
        "compressed_size_bytes",
        "total_size_bytes",
        "total_size_mb",
        "hours_since_backup",
        "current_hours",
        "backup_path",
        "source_path",
        "target_path",
        "restore_path",
        "X-Trace-Id",
        "current",
        "compliance_percentage",
        "error_budget_remaining",
        "burn_rate",
        "estimated_minutes",
        "last_backup_age_hours",
        "current_rpo_hours",
        "current_rto_minutes",
    }
)


def _volatile_key(key: str) -> bool:
    if key in _ALWAYS_VOLATILE:
        return True
    lowered = key.lower()
    return (
        lowered.endswith("_at")
        or "checksum" in lowered
        or "hash" in lowered
        or "duration" in lowered
        or "elapsed" in lowered
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
    if inspect.iscoroutine(result):
        result = asyncio.run(result)
    headers = dict(getattr(result, "headers", {}) or {})
    return {
        "status": result.status_code,
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

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        return self.target(*args, **kwargs)

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
        query: dict[str, Any] | None = None,
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
        self.query = dict(query or {})
        if auth is not None:
            self._auth_context = auth


def exc_frames(exc: BaseException, module: ModuleType) -> list[str]:
    """Function names of traceback frames that belong to ``module`` (outermost first)."""
    module_file = os.path.realpath(module.__file__ or "")
    return [
        frame.name
        for frame in traceback.extract_tb(exc.__traceback__)
        if os.path.realpath(frame.filename) == module_file
    ]


def frame_locals(exc: BaseException, function: str) -> dict[str, Any]:
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_name == function:
            return dict(tb.tb_frame.f_locals)
        tb = tb.tb_next
    return {}


def run(coro_or_value: Any) -> Any:
    if inspect.iscoroutine(coro_or_value):
        return asyncio.run(coro_or_value)
    return coro_or_value


# ---------------------------------------------------------------------------
# Fixtures
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


@pytest.fixture
def source_db(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    db_path = data_dir / "source.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE debates (id INTEGER PRIMARY KEY, topic TEXT NOT NULL)")
        conn.executemany(
            "INSERT INTO debates (id, topic) VALUES (?, ?)",
            [(1, "rate limiter"), (2, "consensus"), (3, "typing")],
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


@pytest.fixture
def manager(tmp_path: Path):
    from aragora.backup.manager import BackupManager

    return BackupManager(tmp_path / "backups", metrics_enabled=False)


@pytest.fixture
def backup_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Point the module-level allow-lists at temporary directories."""
    module = flat("backup_handler")
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    restore_dir = tmp_path / "restore"
    monkeypatch.setattr(module, "_ALLOWED_BACKUP_SOURCE_DIRS", [data_dir.resolve()])
    monkeypatch.setattr(module, "_ALLOWED_RESTORE_DIRS", [restore_dir.resolve()])
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path / "absent-data-dir"))
    return {"data": data_dir, "restore": restore_dir}


@pytest.fixture
def backup_handler(manager, backup_paths):
    module = flat("backup_handler")
    handler = module.BackupHandler({})
    handler._manager = manager
    return handler


def _make_backup(manager: Any, source_db: Path) -> Any:
    backup = manager.create_backup(source_path=source_db)
    assert backup.verified is True
    return backup


# ---------------------------------------------------------------------------
# VAL-TYPEADMIN-001: backup handler entry on a real BackupManager
# ---------------------------------------------------------------------------


@pytest.mark.no_auto_auth
class TestTYPEADMIN001BackupHandler:
    @pytest.mark.parametrize(
        "case",
        [
            "create",
            "list",
            "get",
            "verify",
            "restore_test",
            "stats",
            "missing_source",
            "invalid_source",
        ],
    )
    async def test_TYPEADMIN_001_handler_entry(
        self,
        case: str,
        backup_handler,
        manager,
        source_db: Path,
        tmp_path: Path,
        rbac_enabled,
        record_property,
    ) -> None:
        roots = tmp_roots(tmp_path)
        auth = context("backups:read", "backups:create", "backups:verify", "backups:restore")
        backup_handler._auth_context = auth
        known: dict[str, str] = {}

        if case == "create":
            request = Request(method="POST", body={"source_path": "source.db"})
            result = await backup_handler.handle("/api/v2/backups", {}, request)
            body = payload(result)
            assert result.status_code == 201, body
            backup_id = body["backup"]["id"]
            known[backup_id] = "<backup_id>"
            assert body["message"] == f"Backup created: {backup_id}"
            assert body["backup"]["verified"] is True
            assert body["backup"]["tables"] == ["debates"]
            assert body["backup"]["row_counts"] == {"debates": 3}
            assert Path(body["backup"]["backup_path"]).exists()
            assert manager.list_backups()[0].id == backup_id
        elif case == "missing_source":
            request = Request(method="POST", body={})
            result = await backup_handler.handle("/api/v2/backups", {}, request)
            assert result.status_code == 404
            assert payload(result)["error"] == "Default backup source not found"
            assert manager.list_backups() == []
        elif case == "invalid_source":
            request = Request(method="POST", body={"source_path": "does-not-exist.db"})
            result = await backup_handler.handle("/api/v2/backups", {}, request)
            assert result.status_code == 400
            assert payload(result)["error"] == (
                "Invalid source path. Path must be within allowed backup directories."
            )
            assert manager.list_backups() == []
        else:
            backup = _make_backup(manager, source_db)
            known[backup.id] = "<backup_id>"
            if case == "list":
                result = await backup_handler.handle("/api/v2/backups", {"limit": "5"}, Request())
                body = payload(result)
                assert result.status_code == 200
                assert [b["id"] for b in body["backups"]] == [backup.id]
                assert body["pagination"] == {
                    "limit": 5,
                    "offset": 0,
                    "total": 1,
                    "has_more": False,
                }
            elif case == "get":
                result = await backup_handler.handle(f"/api/v2/backups/{backup.id}", {}, Request())
                body = payload(result)
                assert result.status_code == 200
                assert body["id"] == backup.id
                assert body["status"] == "verified"
            elif case == "verify":
                result = await backup_handler.handle(
                    f"/api/v2/backups/{backup.id}/verify", {}, Request(method="POST")
                )
                body = payload(result)
                assert result.status_code == 200, body
                assert body["backup_id"] == backup.id
                assert body["verified"] is True
                assert body["restore_tested"] is True
                assert isinstance(body["duration_seconds"], float)
            elif case == "restore_test":
                result = await backup_handler.handle(
                    f"/api/v2/backups/{backup.id}/restore-test", {}, Request(method="POST", body={})
                )
                body = payload(result)
                assert result.status_code == 200, body
                assert body["restore_test_passed"] is True
                assert body["dry_run"] is True
                assert body["backup_id"] == backup.id
                assert Path(body["target_path"]).name == "restore_test.db"
                assert Path(body["target_path"]).parent == (tmp_path / "restore").resolve()
                assert not Path(body["target_path"]).exists()
            elif case == "stats":
                result = await backup_handler.handle("/api/v2/backups/stats", {}, Request())
                body = payload(result)
                assert result.status_code == 200
                assert body["stats"]["total_backups"] == 1
                assert body["stats"]["verified_backups"] == 1
                assert body["stats"]["failed_backups"] == 0
                assert body["stats"]["latest_backup"]["id"] == backup.id
                assert isinstance(body["stats"]["total_size_bytes"], int)

        observe(
            record_property,
            {"case": case, "result": summarize(result, roots, known)},
            raw={"case": case, "body": payload(result), "known": known},
        )

    @pytest.mark.parametrize("case", ["denied_read", "denied_create", "missing_context"])
    async def test_TYPEADMIN_001_real_rbac_denial(
        self,
        case: str,
        backup_handler,
        manager,
        source_db: Path,
        tmp_path: Path,
        rbac_enabled,
        record_property,
    ) -> None:
        list_spy = Spy(manager.list_backups)
        create_spy = Spy(manager.create_backup)
        manager.list_backups = list_spy
        manager.create_backup = create_spy
        if case == "denied_read":
            backup_handler._auth_context = context("backups:create")
            request = Request()
            path, method = "/api/v2/backups", "GET"
        elif case == "denied_create":
            backup_handler._auth_context = context("backups:read")
            request = Request(method="POST", body={"source_path": "source.db"})
            path, method = "/api/v2/backups", "POST"
        else:
            request = Request()
            path, method = "/api/v2/backups", "GET"

        with pytest.raises(PermissionDeniedError) as excinfo:
            await backup_handler.handle(path, {}, request)

        assert list_spy.count == 0
        assert create_spy.count == 0
        assert manager.list_backups.target() == []
        observe(
            record_property,
            {
                "case": case,
                "exception": type(excinfo.value).__name__,
                "message": str(excinfo.value),
                "list_calls": list_spy.count,
                "create_calls": create_spy.count,
            },
        )


# ---------------------------------------------------------------------------
# VAL-TYPEADMIN-002: offsite handler status/drill/history semantics
# ---------------------------------------------------------------------------


@pytest.mark.no_auto_auth
class TestTYPEADMIN002OffsiteHandler:
    @pytest.fixture
    def offsite(self, manager):
        module = flat("backup_offsite_handler")
        handler = module.BackupOffsiteHandler({})
        handler._manager = manager
        return handler

    @pytest.mark.parametrize(
        "case",
        [
            "status",
            "passed_drill",
            "unsuccessful_drill",
            "history_default",
            "history_invalid",
            "history_below_min",
            "history_above_max",
            "unknown_route",
        ],
    )
    async def test_TYPEADMIN_002_offsite_entry(
        self,
        case: str,
        offsite,
        manager,
        source_db: Path,
        tmp_path: Path,
        rbac_enabled,
        record_property,
    ) -> None:
        roots = tmp_roots(tmp_path)
        offsite._auth_context = context("backups:read", "backups:create")
        history_spy = Spy(manager.get_drill_history)
        manager.get_drill_history = history_spy
        known: dict[str, str] = {}
        extra: dict[str, Any] = {}

        if case == "status":
            backup = _make_backup(manager, source_db)
            known[backup.id] = "<backup_id>"
            result = await offsite.handle("/api/v1/backup/status", {}, Request())
            body = payload(result)
            assert result.status_code == 200
            assert body["data"]["total_backups"] == 1
            assert body["data"]["verified_backups"] == 1
            assert body["data"]["last_successful_backup"]["id"] == backup.id
            assert body["data"]["last_drill"] is None
        elif case == "passed_drill":
            backup = _make_backup(manager, source_db)
            known[backup.id] = "<backup_id>"
            result = await offsite.handle(
                "/api/v1/backup/drill", {}, Request(method="POST", body={"backup_id": backup.id})
            )
            body = payload(result)
            assert result.status_code == 201, body
            assert body["data"]["status"] == "passed"
            assert body["data"]["backup_id"] == backup.id
            assert body["data"]["errors"] == []
            assert manager.get_drill_history.target(limit=1)[0].drill_id == body["data"]["drill_id"]
        elif case == "unsuccessful_drill":
            result = await offsite.handle(
                "/api/v1/backup/drill", {}, Request(method="POST", body={"backup_id": "unknown"})
            )
            body = payload(result)
            assert result.status_code == 200, body
            assert body["data"]["status"] == "failed"
            assert body["data"]["backup_id"] == "unknown"
            assert body["data"]["errors"] == ["Backup not found: unknown"]
        elif case.startswith("history_"):
            query = {
                "history_default": {},
                "history_invalid": {"limit": "abc"},
                "history_below_min": {"limit": "0"},
                "history_above_max": {"limit": "201"},
            }[case]
            expected_limit = {
                "history_default": 50,
                "history_invalid": 50,
                "history_below_min": 1,
                "history_above_max": 200,
            }[case]
            result = await offsite.handle("/api/v1/backup/drills", query, Request())
            body = payload(result)
            assert result.status_code == 200
            assert body["data"] == {"drills": [], "total": 0}
            assert history_spy.calls == [((), {"limit": expected_limit})] or history_spy.calls == [
                ((expected_limit,), {})
            ]
            extra["requested_limit"] = expected_limit
        else:
            result = await offsite.handle("/api/v1/backup/unknown", {}, Request())
            assert result.status_code == 404
            assert payload(result)["error"] == "Not found"

        extra["history_calls"] = [
            {"args": list(args), "kwargs": kwargs} for args, kwargs in history_spy.calls
        ]
        extra["offsite_transfer"] = "not configured: local BackupManager only"
        observe(
            record_property,
            {"case": case, "result": summarize(result, roots, known), **extra},
            raw={"case": case, "body": payload(result), "known": known},
        )

    @pytest.mark.parametrize("case", ["denied_read", "denied_create"])
    async def test_TYPEADMIN_002_real_rbac_denial(
        self, case: str, offsite, manager, tmp_path: Path, rbac_enabled, record_property
    ) -> None:
        status_spy = Spy(manager.get_backup_status)
        drill_spy = Spy(manager.restore_drill)
        manager.get_backup_status = status_spy
        manager.restore_drill = drill_spy
        observation: dict[str, Any] = {"case": case}
        if case == "denied_read":
            offsite._auth_context = context("backups:create")
            with pytest.raises(PermissionDeniedError) as excinfo:
                await offsite.handle("/api/v1/backup/status", {}, Request())
            observation["exception"] = type(excinfo.value).__name__
            observation["message"] = str(excinfo.value)
        else:
            offsite._auth_context = context("backups:read")
            result = await offsite.handle(
                "/api/v1/backup/drill", {}, Request(method="POST", body={"backup_id": "x"})
            )
            body = payload(result)
            assert result.status_code == 403
            assert body["error"] == "An error occurred"
            assert "X-Trace-Id" in result.headers
            observation["result"] = summarize(result)
        assert status_spy.count == 0
        assert drill_spy.count == 0
        assert manager.get_drill_history() == []
        observation["status_calls"] = status_spy.count
        observation["drill_calls"] = drill_spy.count
        observe(record_property, observation)


# ---------------------------------------------------------------------------
# VAL-TYPEADMIN-003: DR handler call forms, body precedence, real routes
# ---------------------------------------------------------------------------


@pytest.mark.no_auto_auth
class TestTYPEADMIN003DRHandler:
    @pytest.fixture
    def dr(self, manager):
        module = flat("dr_handler")
        handler = module.DRHandler({})
        handler._manager = manager
        handler._auth_context = context("dr:read", "dr:drill")
        return handler

    @pytest.mark.parametrize(
        "case",
        [
            "base_call",
            "positional_call",
            "keyword_call",
            "base_alias",
            "slash_alias",
            "no_arguments",
            "unknown_path",
            "absent_body",
            "invalid_parsed_body",
            "explicit_over_parsed",
            "explicit_over_positional",
            "no_backup",
            "unknown_backup",
            "handler_validate",
        ],
    )
    async def test_TYPEADMIN_003_call_forms(
        self, case: str, dr, manager, tmp_path: Path, rbac_enabled, record_property
    ) -> None:
        roots = tmp_roots(tmp_path)
        results: dict[str, Any] = {}
        observation: dict[str, Any] = {"case": case}

        if case in {"base_call", "positional_call", "keyword_call"}:
            base = await dr.handle("/api/v2/dr/status", {}, Request())
            positional = await dr.handle("GET", "/api/v2/dr/status", None)
            keyword = await dr.handle(method="GET", path="/api/v2/dr/status")
            bodies = [payload(base), payload(positional), payload(keyword)]
            for body in bodies:
                assert isinstance(body["readiness_score"], int)
                body["checked_at"] = "<ts>"
            assert bodies[0] == bodies[1] == bodies[2]
            assert base.status_code == positional.status_code == keyword.status_code == 200
            results = {"base_call": base, "positional_call": positional, "keyword_call": keyword}
            result = results[case]
            observation["forms_identical"] = True
        elif case in {"base_alias", "slash_alias"}:
            alias_path = "/api/v2/dr" if case == "base_alias" else "/api/v2/dr/"
            result = await dr.handle(alias_path, {}, Request())
            status = await dr.handle("/api/v2/dr/status", {}, Request())
            left, right = payload(result), payload(status)
            left["checked_at"] = right["checked_at"] = "<ts>"
            assert result.status_code == 200
            assert left == right
        elif case == "no_arguments":
            result = await dr.handle()
            assert result.status_code == 400
            assert payload(result)["error"] == "Invalid request: no path or method provided"
        elif case == "unknown_path":
            result = await dr.handle("/api/v2/dr/nope", {}, Request())
            assert result.status_code == 404
            assert payload(result)["error"] == "Not found"
        elif case in {"absent_body", "invalid_parsed_body"}:
            raw = b"" if case == "absent_body" else b"{not json"
            request = Request(method="POST", body=raw)
            result = await dr.handle("/api/v2/dr/validate", {}, request)
            explicit = await dr.handle("/api/v2/dr/validate", {}, Request(method="POST", body={}))
            assert result.status_code == 200
            assert payload(result) == payload(explicit)
            assert [c["name"] for c in payload(result)["checks"]] == [
                "rbac_permissions",
                "encryption_config",
                "storage_access",
                "retention_policy",
                "compression",
                "auto_verify",
                "backup_exists",
            ]
            observation["normalized_to_empty_dict"] = True
        elif case == "explicit_over_parsed":
            request = Request(method="POST", body={"check_storage": False})
            result = await dr.handle(
                "/api/v2/dr/validate",
                {},
                request,
                body={"check_storage": True, "check_encryption": False},
            )
            names = [c["name"] for c in payload(result)["checks"]]
            assert "storage_access" in names
            assert "encryption_config" not in names
            observation["check_names"] = names
        elif case == "explicit_over_positional":
            result = await dr.handle(
                "POST",
                "/api/v2/dr/validate",
                {"check_storage": False},
                body={"check_storage": True, "check_permissions": False},
            )
            names = [c["name"] for c in payload(result)["checks"]]
            assert "storage_access" in names
            assert "rbac_permissions" not in names
            observation["check_names"] = names
        elif case == "no_backup":
            result = await dr.handle("/api/v2/dr/drill", {}, Request(method="POST", body={}))
            assert result.status_code == 400
            assert payload(result)["error"] == "No verified backup available for drill"
        elif case == "unknown_backup":
            result = await dr.handle(
                "/api/v2/dr/drill", {}, Request(method="POST", body={"backup_id": "nope"})
            )
            assert result.status_code == 404
            assert payload(result)["error"] == "Backup not found: nope"
        else:
            result = await dr.handle("/api/v2/dr/validate", {}, Request(method="POST", body={}))
            body = payload(result)
            assert result.status_code == 200
            assert body["valid"] is True
            statuses = {c["name"]: c["status"] for c in body["checks"]}
            assert statuses["storage_access"] == "passed"
            assert statuses["backup_exists"] == "warning"

        observation["result"] = summarize(result, roots)
        observe(record_property, observation, raw={"case": case, "body": payload(result)})


# ---------------------------------------------------------------------------
# VAL-TYPEADMIN-003 (FastAPI bridge) and VAL-TYPEADMIN-001 bridge rows
# ---------------------------------------------------------------------------


@pytest.mark.no_auto_auth
class TestTYPEADMIN003FastAPIBridge:
    @pytest.fixture
    def client(self, manager, jwt_secret: str):
        from aragora.server.fastapi import create_app

        app = create_app()
        app.state.context = {"backup_manager": manager}
        # No lifespan context: startup would replace ``app.state.context`` with a
        # freshly built server context and a different BackupManager.
        client = TestClient(app, raise_server_exceptions=False)
        try:
            yield client
        finally:
            app.dependency_overrides.clear()
            client.close()

    @staticmethod
    def _bearer(role: str) -> dict[str, str]:
        from aragora.billing.jwt_auth import create_access_token

        token = create_access_token("readiness-fixture", "fixture@example.invalid", role=role)
        return {"Authorization": f"Bearer {token}"}

    @pytest.mark.parametrize(
        "case",
        [
            "http_status",
            "http_objectives",
            "http_drill",
            "http_anonymous",
            "http_backups_owner_denied",
            "http_backups_explicit_context",
        ],
    )
    def test_TYPEADMIN_003_fastapi_bridge(
        self,
        case: str,
        client,
        manager,
        source_db: Path,
        tmp_path: Path,
        rbac_enabled,
        record_property,
    ) -> None:
        roots = tmp_roots(tmp_path)
        known: dict[str, str] = {}
        observation: dict[str, Any] = {"case": case}

        if case == "http_status":
            response = client.get("/api/v2/dr/status", headers=self._bearer("owner"))
            assert response.status_code == 200, response.text
            assert isinstance(response.json()["readiness_score"], int)
        elif case == "http_objectives":
            response = client.get("/api/v2/dr/objectives", headers=self._bearer("owner"))
            assert response.status_code == 200, response.text
            assert "rpo" in response.json()
        elif case == "http_drill":
            backup = _make_backup(manager, source_db)
            known[backup.id] = "<backup_id>"
            target = tmp_path / "drill-target.db"
            response = client.post(
                "/api/v2/dr/drill",
                json={
                    "backup_id": backup.id,
                    "drill_type": "restore_test",
                    "target_path": str(target),
                },
                headers=self._bearer("owner"),
            )
            body = response.json()
            assert response.status_code == 200, response.text
            assert body["success"] is True
            assert body["backup_id"] == backup.id
            assert [s["step"] for s in body["steps"]] == ["verify_backup", "restore_dry_run"]
            assert not target.exists()
        elif case == "http_anonymous":
            response = client.get("/api/v2/dr/status")
            assert response.status_code == 401
            assert response.json()["detail"] == "Authentication required"
        elif case == "http_backups_owner_denied":
            response = client.get("/api/v2/backups/stats", headers=self._bearer("owner"))
            assert response.status_code == 403
            assert response.json()["detail"] == "Permission denied: backups:read"
        else:
            from aragora.server.fastapi.dependencies.auth import require_authenticated

            _make_backup(manager, source_db)
            auth = context("backups:read")
            client.app.dependency_overrides[require_authenticated] = lambda: auth
            try:
                response = client.get("/api/v2/backups/stats")
            finally:
                client.app.dependency_overrides.clear()
            assert response.status_code == 200, response.text
            assert response.json()["stats"]["total_backups"] == 1
            known[manager.list_backups()[0].id] = "<backup_id>"

        observation["status"] = response.status_code
        observation["body"] = norm(response.json(), roots, known)
        observe(record_property, observation, raw={"case": case, "body": response.json()})


# ---------------------------------------------------------------------------
# VAL-TYPEADMIN-004: optional manager getters and first-use failures
# ---------------------------------------------------------------------------


def _none_factory(handler: Any) -> Spy:
    spy = Spy(lambda: None)
    handler._manager_factory.get = spy
    handler._manager = None
    return spy


@pytest.mark.no_auto_auth
class TestTYPEADMIN004OptionalManager:
    @pytest.mark.parametrize(
        "module_name", ["backup_handler", "backup_offsite_handler", "dr_handler"]
    )
    def test_TYPEADMIN_004_getter_triplet(
        self, module_name: str, manager, tmp_path: Path, record_property
    ) -> None:
        module = flat(module_name)
        cls = {
            "backup_handler": "BackupHandler",
            "backup_offsite_handler": "BackupOffsiteHandler",
            "dr_handler": "DRHandler",
        }[module_name]
        getter_name = "_get_backup_manager" if module_name == "dr_handler" else "_get_manager"
        from aragora.backup.manager import BackupManager

        # (a) injected manager identity
        injected = getattr(module, cls)({})
        injected._manager = manager
        assert getattr(injected, getter_name)() is manager

        # (b) lazy factory caches on first call
        lazy = getattr(module, cls)({})
        created = BackupManager(tmp_path / "lazy-backups", metrics_enabled=False)
        lazy_spy = Spy(lambda: created)
        lazy._manager_factory.get = lazy_spy
        first = getattr(lazy, getter_name)()
        second = getattr(lazy, getter_name)()
        assert first is created and second is created
        assert lazy_spy.count == 1

        # (c) factory returning None leaves the getter returning None
        absent = getattr(module, cls)({})
        none_spy = _none_factory(absent)
        assert getattr(absent, getter_name)() is None
        assert getattr(absent, getter_name)() is None
        assert none_spy.count == 2

        observe(
            record_property,
            {
                "module": module_name,
                "injected_identity": True,
                "lazy_factory_calls": lazy_spy.count,
                "none_factory_calls": none_spy.count,
                "none_getter_result": None,
            },
        )

    @pytest.mark.parametrize(
        "case",
        [
            "backup_list",
            "backup_get",
            "backup_verify",
            "backup_restore_test",
            "backup_create_caught_500",
            "backup_stats",
            "offsite_status",
            "offsite_drill",
            "offsite_drills",
            "dr_status",
            "dr_objectives",
            "dr_drill",
            "dr_validate_storage_on",
            "dr_validate_storage_off",
            "dr_validate_checks_off",
        ],
    )
    async def test_TYPEADMIN_004_first_use_failure(
        self,
        case: str,
        source_db: Path,
        backup_paths,
        tmp_path: Path,
        rbac_enabled,
        record_property,
    ) -> None:
        roots = tmp_roots(tmp_path)
        family = case.split("_", 1)[0]
        module_name = {
            "backup": "backup_handler",
            "offsite": "backup_offsite_handler",
            "dr": "dr_handler",
        }[family]
        module = flat(module_name)
        cls = {"backup": "BackupHandler", "offsite": "BackupOffsiteHandler", "dr": "DRHandler"}[
            family
        ]
        handler = getattr(module, cls)({})
        factory_spy = _none_factory(handler)
        handler._auth_context = context(
            "backups:read",
            "backups:create",
            "backups:verify",
            "backups:restore",
            "backups:delete",
            "dr:read",
            "dr:drill",
        )
        observation: dict[str, Any] = {"case": case}

        calls: dict[str, tuple[Any, ...]] = {
            "backup_list": ("/api/v2/backups", {}, Request(), "list_backups"),
            "backup_get": ("/api/v2/backups/abc", {}, Request(), "list_backups"),
            "backup_verify": (
                "/api/v2/backups/abc/verify",
                {},
                Request(method="POST"),
                "verify_backup",
            ),
            "backup_restore_test": (
                "/api/v2/backups/abc/restore-test",
                {},
                Request(method="POST", body={}),
                "restore_backup",
            ),
            "backup_stats": ("/api/v2/backups/stats", {}, Request(), "list_backups"),
            "offsite_status": ("/api/v1/backup/status", {}, Request(), "get_backup_status"),
            "offsite_drill": (
                "/api/v1/backup/drill",
                {},
                Request(method="POST", body={"backup_id": "abc"}),
                "restore_drill",
            ),
            "offsite_drills": ("/api/v1/backup/drills", {}, Request(), "get_drill_history"),
            "dr_status": ("/api/v2/dr/status", {}, Request(), "list_backups"),
            "dr_objectives": ("/api/v2/dr/objectives", {}, Request(), "list_backups"),
            "dr_drill": (
                "/api/v2/dr/drill",
                {},
                Request(method="POST", body={}),
                "get_latest_backup",
            ),
            "dr_validate_storage_on": (
                "/api/v2/dr/validate",
                {},
                Request(method="POST", body={}),
                "backup_dir",
            ),
            "dr_validate_storage_off": (
                "/api/v2/dr/validate",
                {},
                Request(method="POST", body={"check_storage": False}),
                "retention_policy",
            ),
            "dr_validate_checks_off": (
                "/api/v2/dr/validate",
                {},
                Request(
                    method="POST",
                    body={
                        "check_storage": False,
                        "check_permissions": False,
                        "check_encryption": False,
                    },
                ),
                "retention_policy",
            ),
        }

        if case == "backup_create_caught_500":
            result = await handler.handle(
                "/api/v2/backups", {}, Request(method="POST", body={"source_path": "source.db"})
            )
            assert result.status_code == 500
            assert payload(result)["error"] == "Backup operation failed"
            observation["result"] = summarize(result, roots)
        elif case == "offsite_drill":
            path, query, request, member = calls[case]
            result = await handler.handle(path, query, request)
            assert result.status_code == 500
            assert payload(result)["error"] == "An error occurred"
            assert "X-Trace-Id" in result.headers
            observation["result"] = summarize(result, roots)
            observation["expected_member"] = member
        else:
            path, query, request, member = calls[case]
            with pytest.raises(AttributeError) as excinfo:
                await handler.handle(path, query, request)
            assert str(excinfo.value) == NONE_ATTR.format(member)
            frames = exc_frames(excinfo.value, module)
            observation["exception"] = "AttributeError"
            observation["message"] = str(excinfo.value)
            observation["innermost_frame"] = frames[-1] if frames else None
            if case.startswith("dr_validate"):
                completed = frame_locals(excinfo.value, "_validate_configuration").get("checks", [])
                observation["checks_before_failure"] = [
                    {"name": c["name"], "status": c["status"]} for c in completed
                ]
                expected = {
                    "dr_validate_storage_on": ["rbac_permissions", "encryption_config"],
                    "dr_validate_storage_off": ["rbac_permissions", "encryption_config"],
                    "dr_validate_checks_off": [],
                }[case]
                assert [c["name"] for c in completed] == expected
            if case == "backup_restore_test":
                assert (tmp_path / "restore").is_dir(), "target validation ran before manager use"
                observation["validated_before_manager"] = True

        assert factory_spy.count >= 1
        observation["factory_calls"] = factory_spy.count
        observe(record_property, observation)


# ---------------------------------------------------------------------------
# VAL-TYPEADMIN-005: moderation analytics on the real integration and queue
# ---------------------------------------------------------------------------


@pytest.mark.no_auto_auth
class TestTYPEADMIN005Moderation:
    @pytest.fixture
    def moderation_state(self, monkeypatch: pytest.MonkeyPatch):
        import aragora.moderation as moderation_pkg
        from aragora.moderation import spam_integration as si

        SpamVerdict = si.SpamVerdict
        integration = si.SpamModerationIntegration(config=si.SpamModerationConfig(enabled=True))
        integration._stats.update({"checks": 4, "blocked": 1, "flagged": 1, "passed": 2})
        monkeypatch.setattr(si, "_global_moderation", integration)
        monkeypatch.setattr(si, "_REVIEW_QUEUE", OrderedDict())
        items = []
        for index in range(3):
            result = si.SpamCheckResult(
                verdict=SpamVerdict.SUSPICIOUS,
                confidence=0.75,
                reasons=["readiness fixture"],
                should_flag_for_review=True,
                spam_score=0.75,
                content_hash=f"hash-{index}",
            )
            items.append(si.queue_for_review(f"content-{index}", result, {"index": index}))
        size_spy = Spy(si.review_queue_size)
        list_spy = Spy(si.list_review_queue)
        monkeypatch.setattr(moderation_pkg, "review_queue_size", size_spy)
        monkeypatch.setattr(moderation_pkg, "list_review_queue", list_spy)
        return {
            "integration": integration,
            "items": items,
            "size_spy": size_spy,
            "list_spy": list_spy,
        }

    def test_TYPEADMIN_005_getters(self, moderation_state, record_property) -> None:
        module = flat("moderation_analytics")
        from aragora.moderation import spam_integration as si

        integration = module._get_moderation()
        assert integration is moderation_state["integration"]
        assert isinstance(integration, si.SpamModerationIntegration)
        size = module._get_queue_size()
        assert size == 3 and type(size) is int
        listed = module._list_queue(limit=2, offset=1)
        expected = list(reversed(moderation_state["items"]))[1:3]
        assert [item is exp for item, exp in zip(listed, expected)] == [True, True]
        assert all(isinstance(item, si.ModerationQueueItem) for item in listed)
        observe(
            record_property,
            {
                "moderation_is_singleton": True,
                "queue_size": size,
                "listed_ids_match_queue": [item.content for item in listed],
                "statistics_keys": sorted(integration.statistics),
            },
        )

    @pytest.mark.parametrize(
        "case",
        [
            "stats_available",
            "stats_unavailable",
            "queue_default",
            "queue_limit_offset",
            "queue_invalid_limit",
            "queue_negative_offset",
            "queue_limit_cap",
            "unknown_path",
            "denied",
            "missing_context",
        ],
    )
    def test_TYPEADMIN_005_handler_entry(
        self,
        case: str,
        moderation_state,
        monkeypatch: pytest.MonkeyPatch,
        rbac_enabled,
        record_property,
    ) -> None:
        module = flat("moderation_analytics")
        handler = module.ModerationAnalyticsHandler({})
        observation: dict[str, Any] = {"case": case}
        known = {item.id: f"<queue_item_{i}>" for i, item in enumerate(moderation_state["items"])}

        if case in {"denied", "missing_context"}:
            request = Request(auth=context("analytics:read") if case == "denied" else None)
            with pytest.raises(PermissionDeniedError) as excinfo:
                handler.handle("/api/v1/moderation/stats", {}, request)
            observation["exception"] = "PermissionDeniedError"
            observation["message"] = str(excinfo.value)
        else:
            request = Request(auth=context("admin:read"))
            if case == "stats_unavailable":
                monkeypatch.setitem(sys.modules, "aragora.moderation", None)
                result = handler.handle("/api/v1/moderation/stats", {}, request)
                body = payload(result)
                assert result.status_code == 200
                assert body["available"] is False
                assert body["queue_size"] == 0
            elif case == "stats_available":
                result = handler.handle("/api/v1/moderation/stats", {}, request)
                body = payload(result)
                assert result.status_code == 200
                assert body["available"] is True
                assert body["queue_size"] == 3
                assert body["blocked_count"] == 1
                assert body["flagged_count"] == 1
                assert body["total_checks"] == 0
                assert body["block_rate"] == 0.0
            elif case == "unknown_path":
                result = handler.handle("/api/v1/moderation/other", {}, request)
                assert result is None
            else:
                query = {
                    "queue_default": {},
                    "queue_limit_offset": {"limit": "1", "offset": "1"},
                    "queue_invalid_limit": {"limit": "abc"},
                    "queue_negative_offset": {"offset": "-5"},
                    "queue_limit_cap": {"limit": "500"},
                }[case]
                result = handler.handle("/api/v1/moderation/queue", query, request)
                body = payload(result)
                assert result.status_code == 200
                expected_limit, expected_offset = {
                    "queue_default": (50, 0),
                    "queue_limit_offset": (1, 1),
                    "queue_invalid_limit": (50, 0),
                    "queue_negative_offset": (50, 0),
                    "queue_limit_cap": (200, 0),
                }[case]
                assert body["limit"] == expected_limit
                assert body["offset"] == expected_offset
                assert body["count"] == len(body["items"])
                if case == "queue_limit_offset":
                    assert body["items"][0]["content"] == "content-1"
                else:
                    assert [i["content"] for i in body["items"]] == [
                        "content-2",
                        "content-1",
                        "content-0",
                    ]
                assert moderation_state["list_spy"].calls[-1] == (
                    (),
                    {"limit": expected_limit, "offset": expected_offset},
                )
            observation["result"] = summarize(result, known=known)

        observation["queue_size_calls"] = moderation_state["size_spy"].count
        observation["list_queue_calls"] = moderation_state["list_spy"].count
        if case in {"denied", "missing_context"}:
            assert moderation_state["size_spy"].count == 0
            assert moderation_state["list_spy"].count == 0
        observe(record_property, observation)


# ---------------------------------------------------------------------------
# VAL-TYPEADMIN-006: decision analytics on the real OutcomeAnalytics singleton
# ---------------------------------------------------------------------------


@pytest.fixture
def analytics_singletons(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from aragora.analytics import debate_analytics as da_module
    from aragora.analytics import outcome_analytics as oa_module

    debates_db = str(tmp_path / "debates.db")
    outcome = oa_module.OutcomeAnalytics(db_path=debates_db)
    debate = da_module.DebateAnalytics(db_path=debates_db)
    monkeypatch.setattr(oa_module, "_outcome_analytics", outcome)
    monkeypatch.setattr(da_module, "_debate_analytics", debate)
    return {"outcome": outcome, "debate": debate, "db": debates_db}


@pytest.mark.no_auto_auth
class TestTYPEADMIN006DecisionAnalytics:
    def test_TYPEADMIN_006_singleton_identity(self, analytics_singletons, record_property) -> None:
        module = flat("decision_analytics")
        from aragora.analytics import outcome_analytics as oa_module

        first = module._get_outcome_analytics()
        second = module._get_outcome_analytics()
        assert first is second
        assert first is analytics_singletons["outcome"]
        assert first is oa_module.get_outcome_analytics()
        assert isinstance(first, oa_module.OutcomeAnalytics)
        observe(record_property, {"singleton_identity": True, "type": type(first).__name__})

    @pytest.mark.parametrize(
        "case",
        [
            "overview_versioned",
            "overview_legacy",
            "invalid_period",
            "unknown_path",
            "method_not_allowed",
            "denied",
        ],
    )
    def test_TYPEADMIN_006_handler_entry(
        self, case: str, analytics_singletons, rbac_enabled, record_property
    ) -> None:
        module = flat("decision_analytics")
        handler = module.DecisionAnalyticsHandler({})
        auth = context("analytics:read")
        observation: dict[str, Any] = {"case": case}

        if case in {"overview_versioned", "overview_legacy"}:
            path = (
                "/api/v1/decision-analytics/overview"
                if case == "overview_versioned"
                else "/api/decision-analytics/overview"
            )
            result = handler.handle(path, {"period": "7d"}, Request(auth=auth))
            body = payload(result)
            assert result.status_code == 200, body
            assert body == {
                "data": {
                    "total_decisions": 0,
                    "consensus_reached": 0,
                    "consensus_rate": 0.0,
                    "avg_confidence": 0.0,
                    "avg_rounds": 0.0,
                    "period": "7d",
                }
            }
        elif case == "invalid_period":
            result = handler.handle(
                "/api/v1/decision-analytics/overview", {"period": "bogus"}, Request(auth=auth)
            )
            assert result.status_code == 500
            assert payload(result)["error"] == "Internal server error"
        elif case == "unknown_path":
            result = handler.handle("/api/v1/decision-analytics/nope", {}, Request(auth=auth))
            assert result.status_code == 404
            assert payload(result) == {"error": "Not found"}
        elif case == "method_not_allowed":
            result = handler.handle(
                "/api/v1/decision-analytics/overview", {}, Request(method="POST", auth=auth)
            )
            assert result.status_code == 405
            assert payload(result) == {"error": "Method not allowed"}
            assert result.headers.get("Allow") == "GET"
        else:
            with pytest.raises(PermissionDeniedError) as excinfo:
                handler.handle(
                    "/api/v1/decision-analytics/overview", {}, Request(auth=context("debates:read"))
                )
            observation["exception"] = "PermissionDeniedError"
            observation["message"] = str(excinfo.value)
            result = None

        observation["result"] = summarize(result)
        observe(record_property, observation)


# ---------------------------------------------------------------------------
# VAL-TYPEADMIN-007: system health, differentiation, outcome dashboard
# ---------------------------------------------------------------------------


def _fallback_module(name: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Re-execute a flat module with ``aragora.rbac.decorators`` import failing."""
    original = flat(name)
    spec = importlib.util.spec_from_file_location(
        f"{HANDLERS_PKG}._readiness_fallback_{name}", original.__file__
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    module.__package__ = HANDLERS_PKG
    with pytest.MonkeyPatch.context() as local:
        local.setitem(sys.modules, "aragora.rbac.decorators", None)
        spec.loader.exec_module(module)
    return module


@pytest.mark.no_auto_auth
class TestTYPEADMIN007SystemHealth:
    @pytest.mark.parametrize(
        "case",
        [
            "overview_legacy",
            "overview_versioned",
            "unknown_path",
            "denied",
            "missing_context",
            "fallback_identity",
        ],
    )
    async def test_TYPEADMIN_007_system_health(
        self, case: str, monkeypatch: pytest.MonkeyPatch, rbac_enabled, record_property
    ) -> None:
        module = flat("system_health")
        handler = module.SystemHealthDashboardHandler({})
        overview_spy = Spy(handler._get_overview)
        handler._get_overview = overview_spy
        observation: dict[str, Any] = {"case": case}

        def shape(body: dict[str, Any]) -> dict[str, Any]:
            data = body["data"]
            return {
                "overall_status": data["overall_status"],
                "subsystems": data["subsystems"],
                "sections": {
                    key: {"available": data[key].get("available"), "keys": sorted(data[key])}
                    for key in ("circuit_breakers", "slos", "adapters", "agents", "budget")
                },
                "adapters": norm(data["adapters"]),
                "agents": norm(data["agents"]),
                "slo_keys": [s["key"] for s in data["slos"].get("slos", [])],
            }

        if case in {"overview_legacy", "overview_versioned"}:
            legacy = await handler.handle(
                "/api/admin/system-health", {}, Request(auth=context("system:read"))
            )
            versioned = await handler.handle(
                "/api/v1/admin/system-health", {}, Request(auth=context("system:read"))
            )
            assert legacy.status_code == versioned.status_code == 200
            left, right = shape(payload(legacy)), shape(payload(versioned))
            assert left == right
            assert overview_spy.count == 2
            observation["result"] = {
                "status": 200,
                "shape": left if case == "overview_legacy" else right,
            }
            observation["raw_bodies_equal_modulo_time"] = left == right
            raw = {"legacy": payload(legacy), "versioned": payload(versioned)}
        elif case == "unknown_path":
            result = await handler.handle(
                "/api/admin/system-health/nope", {}, Request(auth=context("system:read"))
            )
            assert result.status_code == 404
            observation["result"] = summarize(result)
            raw = None
        elif case in {"denied", "missing_context"}:
            request = Request(auth=context("analytics:read") if case == "denied" else None)
            with pytest.raises(PermissionDeniedError) as excinfo:
                await handler.handle("/api/admin/system-health", {}, request)
            assert overview_spy.count == 0
            observation["exception"] = "PermissionDeniedError"
            observation["message"] = str(excinfo.value)
            observation["overview_calls"] = overview_spy.count
            raw = None
        else:
            fallback = _fallback_module("system_health", monkeypatch)
            assert fallback.require_permission is not module.require_permission

            def probe(*args: Any) -> str:
                return "probe-result"

            decorated = fallback.require_permission("system:read")(probe)
            assert decorated is probe
            assert decorated() == "probe-result"
            fallback_handler = fallback.SystemHealthDashboardHandler({})
            result = await fallback_handler.handle("/api/admin/system-health/nope", {}, Request())
            real = await handler.handle(
                "/api/admin/system-health/nope", {}, Request(auth=context("system:read"))
            )
            assert summarize(result) == summarize(real)
            observation["fallback_identity"] = True
            observation["result"] = summarize(result)
            raw = None

        observe(record_property, observation, raw=raw)


@pytest.mark.no_auto_auth
class TestTYPEADMIN007Differentiation:
    @pytest.fixture
    def elo(self, tmp_path: Path):
        from aragora.ranking.elo import EloSystem

        return EloSystem(db_path=str(tmp_path / "elo.db"))

    @pytest.mark.parametrize(
        "case",
        [
            "summary_legacy",
            "summary_versioned",
            "unknown_path",
            "denied",
            "missing_context",
            "fallback_identity",
        ],
    )
    def test_TYPEADMIN_007_differentiation(
        self, case: str, elo, monkeypatch: pytest.MonkeyPatch, rbac_enabled, record_property
    ) -> None:
        module = flat("differentiation")
        handler = module.DifferentiationHandler({"elo_system": elo})
        summary_spy = Spy(handler._get_summary)
        handler._get_summary = summary_spy
        observation: dict[str, Any] = {"case": case}

        if case in {"summary_legacy", "summary_versioned"}:
            legacy = handler.handle(
                "/api/differentiation/summary", {}, Request(auth=context("analytics:read"))
            )
            versioned = handler.handle(
                "/api/v1/differentiation/summary", {}, Request(auth=context("analytics:read"))
            )
            assert legacy.status_code == versioned.status_code == 200
            assert payload(legacy) == payload(versioned)
            assert payload(legacy)["data"] == {
                "total_decisions": 0,
                "dissent_preserved_rate": 0.0,
                "avg_robustness_score": 0.0,
                "avg_calibration_error": 0.0,
                "active_agent_count": 0,
                "adversarial_vetting_enabled": True,
                "multi_model_consensus": False,
            }
            assert handler.ctx.get("receipt_store") is None
            assert handler.ctx["elo_system"] is elo
            observation["result"] = summarize(legacy if case == "summary_legacy" else versioned)
            observation["receipt_store_import"] = (
                "absent (aragora.gauntlet.receipts not importable)"
            )
        elif case == "unknown_path":
            result = handler.handle(
                "/api/differentiation/nope", {}, Request(auth=context("analytics:read"))
            )
            assert result is None
            observation["result"] = None
        elif case in {"denied", "missing_context"}:
            request = Request(auth=context("system:read") if case == "denied" else None)
            with pytest.raises(PermissionDeniedError) as excinfo:
                handler.handle("/api/differentiation/summary", {}, request)
            assert summary_spy.count == 0
            observation["exception"] = "PermissionDeniedError"
            observation["message"] = str(excinfo.value)
            observation["summary_calls"] = summary_spy.count
        else:
            fallback = _fallback_module("differentiation", monkeypatch)
            assert fallback.require_permission is not module.require_permission

            def probe(*args: Any) -> str:
                return "probe-result"

            decorated = fallback.require_permission("analytics:read")(probe)
            assert decorated is probe
            assert decorated() == "probe-result"
            fallback_handler = fallback.DifferentiationHandler({"elo_system": elo})
            result = fallback_handler.handle("/api/differentiation/summary", {}, Request())
            real = handler.handle(
                "/api/differentiation/summary", {}, Request(auth=context("analytics:read"))
            )
            assert payload(result) == payload(real)
            observation["fallback_identity"] = True
            observation["result"] = summarize(result)

        observe(record_property, observation)


class TestTYPEADMIN007OutcomeDashboard:
    @pytest.mark.parametrize(
        "case",
        [
            "period_valid",
            "period_invalid",
            "quality_valid",
            "quality_invalid",
            "method_not_allowed",
            "unknown_path",
        ],
    )
    def test_TYPEADMIN_007_outcome_dashboard(
        self, case: str, analytics_singletons, record_property
    ) -> None:
        module = flat("outcome_dashboard")
        from aragora.analytics import outcome_analytics as oa_module

        observation: dict[str, Any] = {"case": case}
        if case == "period_valid":
            delta = module._parse_period("7d")
            assert delta == timedelta(days=7)
            assert delta is oa_module._parse_period("7d")
            observation["delta_days"] = delta.days
        elif case == "period_invalid":
            with pytest.raises(ValueError) as excinfo:
                module._parse_period("bogus")
            with pytest.raises(ValueError) as reference:
                oa_module._parse_period("bogus")
            assert str(excinfo.value) == str(reference.value)
            observation["message"] = str(excinfo.value)
        else:
            handler = module.OutcomeDashboardHandler({})
            if case == "method_not_allowed":
                result = handler.handle(
                    "/api/v1/outcome-dashboard/quality", {}, Request(), method="POST"
                )
                assert result.status_code == 405
                assert payload(result)["error"] == "Method not allowed"
            elif case == "unknown_path":
                result = handler.handle("/api/v1/outcome-dashboard/nope", {}, Request())
                assert result is None
            else:
                period = "7d" if case == "quality_valid" else "bogus"
                pending = handler.handle(
                    "/api/v1/outcome-dashboard/quality", {"period": period}, Request()
                )
                assert inspect.iscoroutine(pending)
                result = asyncio.run(pending)
                body = payload(result)
                assert result.status_code == 200
                data = body["data"]
                assert data["period"] == period
                if case == "quality_valid":
                    assert data["total_decisions"] == 0
                    assert len(data["trend"]) == 1
                    assert data["quality_score"] == round((0.3 * 1.0) * 100, 1)
                else:
                    assert data == {
                        "quality_score": 0.0,
                        "consensus_rate": 0.0,
                        "avg_rounds": 0.0,
                        "total_decisions": 0,
                        "completed_decisions": 0,
                        "completion_rate": 0.0,
                        "quality_change": None,
                        "trend": [],
                        "period": "bogus",
                    }
            observation["result"] = summarize(result)
        observe(record_property, observation)


# ---------------------------------------------------------------------------
# VAL-TYPEALIAS-001: legacy/relocated identity rows for the batch-A modules
# ---------------------------------------------------------------------------


def _alias_probe(name: str, module: ModuleType, tmp_path: Path) -> Any:
    """A cheap, deterministic entry behaviour per module used for alias equivalence."""
    if name == "backup_handler":
        return module.BackupHandler({}).can_handle("/api/v2/backups", "DELETE")
    if name == "backup_offsite_handler":
        return summarize(
            module.BackupOffsiteHandler({}).handle("/api/v1/backup/unknown", {}, Request())
        )
    if name == "dr_handler":
        return summarize(module.DRHandler({}).handle())
    if name == "system_health":
        return module.SystemHealthDashboardHandler({}).can_handle("/api/v1/admin/system-health")
    if name == "decision_analytics":
        return summarize(
            module.DecisionAnalyticsHandler({}).handle("/x", {}, Request(method="POST"))
        )
    if name == "moderation_analytics":
        return module.ModerationAnalyticsHandler({}).can_handle("/api/v1/moderation/stats")
    if name == "spend_analytics":
        return module.SpendAnalyticsHandler({}).can_handle("/api/v1/spend/analytics")
    if name == "differentiation":
        return module.DifferentiationHandler({}).can_handle("/api/v1/differentiation/summary")
    if name == "outcome_dashboard":
        return module._parse_period("7d").days
    raise AssertionError(name)


@pytest.mark.parametrize("name", sorted(BATCH_A))
def test_TYPEALIAS_001_identity(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_property
) -> None:
    area, symbols = BATCH_A[name]
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
    legacy_probe = _alias_probe(name, legacy, tmp_path)
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
        assert _alias_probe(name, relocated, tmp_path) == legacy_probe
        observation["identity"] = "shared module object; probe identical through both names"
    else:
        assert legacy_file == (root / "aragora" / "server" / "handlers" / f"{name}.py").resolve()
        observation["identity"] = "not applicable: flat tree, relocated destination absent"
    observe(record_property, observation)
