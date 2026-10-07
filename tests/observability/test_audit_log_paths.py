"""Old aragora.audit paths and the observability audit modules share one implementation and state."""

from __future__ import annotations

import ast
import importlib
import inspect
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import aragora.audit as audit_pkg
import aragora.audit.log as old_log
import aragora.audit.persistence as old_persistence
import aragora.audit.unified as old_unified
import aragora.observability.audit_log as new_log
import aragora.observability.audit_persistence as new_persistence
import aragora.observability.unified_audit as new_unified

REPO_ROOT = Path(__file__).resolve().parents[2]

LOG_NAMES = (
    "AuditCategory",
    "AuditEvent",
    "AuditLog",
    "AuditOutcome",
    "AuditQuery",
    "audit_admin_action",
    "audit_auth_login",
    "audit_data_access",
    "get_audit_log",
    "reset_audit_log",
)
UNIFIED_NAMES = (
    "UnifiedAuditCategory",
    "AuditOutcome",
    "AuditSeverity",
    "UnifiedAuditEvent",
    "UnifiedAuditLogger",
    "get_unified_audit_logger",
    "configure_unified_audit_logger",
    "audit_log",
    "audit_login",
    "audit_logout",
    "audit_access",
    "audit_data",
    "audit_admin",
    "audit_security",
    "audit_debate",
    "audit_action",
)
PERSISTENCE_NAMES = ("AuditPersistenceBackend", "FileBackend", "PostgresBackend", "get_backend")
PERSISTENCE_SUBMODULE_NAMES = {
    "base": ("AuditPersistenceBackend", "PersistenceError"),
    "file": ("FileBackend",),
    "postgres": ("PostgresBackend", "POSTGRES_SCHEMA"),
}
# Public module-level names outside __all__ that old-path callers import directly.
LOG_EXTRA_NAMES = (
    "AUDIT_COLUMNS",
    "POSTGRES_SCHEMA_STATEMENTS",
    "POSTGRESQL_AVAILABLE",
    "SQLITE_SCHEMA_STATEMENTS",
    "PostgreSQLBackend",
    "SQLiteBackend",
)


@pytest.fixture
def isolated_audit_log(tmp_path, monkeypatch):
    monkeypatch.setattr(new_log, "require_distributed_store", lambda *args, **kwargs: None)
    monkeypatch.delenv("ARAGORA_AUDIT_STORE_BACKEND", raising=False)
    monkeypatch.setenv("ARAGORA_DB_BACKEND", "sqlite")
    new_log.reset_audit_log()
    log = old_log.get_audit_log(db_path=tmp_path / "audit.db")
    yield log
    log._backend.close_all()
    new_log.reset_audit_log()


@pytest.fixture
def middleware_hook():
    saved = new_unified._middleware_logger_factory
    yield
    new_unified._middleware_logger_factory = saved


@pytest.mark.parametrize(
    ("old", "new", "name"),
    [(old_log, new_log, n) for n in LOG_NAMES + LOG_EXTRA_NAMES]
    + [(old_unified, new_unified, n) for n in UNIFIED_NAMES]
    + [(old_persistence, new_persistence, n) for n in PERSISTENCE_NAMES],
    ids=lambda value: value if isinstance(value, str) else value.__name__,
)
def test_old_path_reexports_identical_object(old, new, name: str) -> None:
    assert getattr(old, name) is getattr(new, name)


@pytest.mark.parametrize("submodule", sorted(PERSISTENCE_SUBMODULE_NAMES))
def test_persistence_submodule_paths_reexport(submodule: str) -> None:
    old = importlib.import_module(f"aragora.audit.persistence.{submodule}")
    new = importlib.import_module(f"aragora.observability.audit_persistence.{submodule}")
    for name in PERSISTENCE_SUBMODULE_NAMES[submodule]:
        assert getattr(old, name) is getattr(new, name)


def test_old_path_all_lists_unchanged() -> None:
    assert sorted(old_log.__all__) == sorted(LOG_NAMES)
    assert sorted(old_unified.__all__) == sorted(UNIFIED_NAMES)
    assert sorted(old_persistence.__all__) == sorted(PERSISTENCE_NAMES)
    assert audit_pkg.AuditLog is new_log.AuditLog
    assert audit_pkg.AuditEvent is new_log.AuditEvent


def test_implementation_lives_in_observability() -> None:
    assert inspect.getmodule(old_log.AuditLog) is new_log
    assert inspect.getmodule(old_unified.audit_access) is new_unified
    assert old_persistence.FileBackend.__module__ == "aragora.observability.audit_persistence.file"


def test_fixed_input_event_hash_equal_at_both_paths() -> None:
    fields = {
        "action": "login",
        "actor_id": "user-1",
        "resource_type": "session",
        "resource_id": "sess-1",
        "id": "evt-1",
        "timestamp": datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    }
    old_event = old_log.AuditEvent(category=old_log.AuditCategory.AUTH, **fields)
    new_event = new_log.AuditEvent(category=new_log.AuditCategory.AUTH, **fields)
    assert old_event.compute_hash() == new_event.compute_hash()
    assert old_event.to_dict() == new_event.to_dict()
    assert old_event.to_dict()["category"] == "auth"


def test_fixed_input_helper_calls_at_both_paths() -> None:
    recorded = []
    sink = MagicMock()
    sink.log.side_effect = lambda event: recorded.append(event) or event.id
    old_log.audit_data_access(sink, "user-7", "document", "doc-9", action="read", org_id="org-1")
    new_log.audit_data_access(sink, "user-7", "document", "doc-9", action="read", org_id="org-1")
    first, second = (event.to_dict() for event in recorded)
    for event in (first, second):
        event.pop("id")
        event.pop("timestamp")
    assert first == second
    assert (first["actor_id"], first["resource_id"], first["org_id"]) == (
        "user-7",
        "doc-9",
        "org-1",
    )


def test_unified_event_to_dict_equal_at_both_paths() -> None:
    when = datetime(2026, 1, 2, tzinfo=timezone.utc)
    old_event = old_unified.UnifiedAuditEvent(
        category=old_unified.UnifiedAuditCategory.ACCESS_DENIED,
        action="check",
        actor_id="u1",
        timestamp=when,
    )
    new_event = new_unified.UnifiedAuditEvent(
        category=new_unified.UnifiedAuditCategory.ACCESS_DENIED,
        action="check",
        actor_id="u1",
        timestamp=when,
    )
    assert old_event.to_dict() == new_event.to_dict()
    assert old_event.to_dict()["category"] == "access.denied"


def test_event_logged_via_old_path_is_queried_via_new_path(isolated_audit_log) -> None:
    assert new_log.get_audit_log() is isolated_audit_log
    isolated_audit_log.log(
        old_log.AuditEvent(
            category=old_log.AuditCategory.ACCESS,
            action="se2-probe",
            actor_id="validator",
            resource_id="r1",
        )
    )
    events = new_log.get_audit_log().query(new_log.AuditQuery(actor_id="validator"))
    assert [(e.action, e.actor_id, e.resource_id) for e in events] == [
        ("se2-probe", "validator", "r1")
    ]
    assert events[0].category is new_log.AuditCategory.ACCESS


def test_unified_logger_singleton_shared() -> None:
    configured = old_unified.configure_unified_audit_logger(
        enable_compliance=False, enable_privacy=False, enable_rbac=False, enable_middleware=False
    )
    assert new_unified.get_unified_audit_logger() is configured
    received = []
    configured.add_handler(received.append)
    old_unified.audit_access("u1", "debates:read", granted=False)
    new_unified.audit_access("u2", "debates:read")
    assert [(e.actor_id, e.category.value) for e in received] == [
        ("u1", "access.denied"),
        ("u2", "access.granted"),
    ]


def test_file_backend_from_old_path_is_new_class(tmp_path) -> None:
    backend = old_persistence.get_backend("file", storage_path=tmp_path / "audit")
    assert type(backend) is new_persistence.FileBackend


def test_unregistered_middleware_logger_is_skipped(middleware_hook) -> None:
    new_unified._middleware_logger_factory = None
    assert new_unified.UnifiedAuditLogger()._get_middleware_logger() is None


def test_registered_middleware_logger_is_used(middleware_hook) -> None:
    sentinel = object()
    new_unified.register_middleware_audit_logger(lambda: sentinel)
    assert new_unified.UnifiedAuditLogger()._get_middleware_logger() is sentinel
    assert new_unified.UnifiedAuditLogger(enable_middleware=False)._get_middleware_logger() is None


def test_server_registers_middleware_logger(middleware_hook) -> None:
    from aragora.server.decision_routes import register_decision_routes
    from aragora.server.middleware.audit_logger import get_audit_logger

    new_unified._middleware_logger_factory = None
    register_decision_routes()
    register_decision_routes()
    assert new_unified._middleware_logger_factory is get_audit_logger


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
            if node.module == "aragora":
                found.extend((node.lineno, f"aragora.{alias.name}") for alias in node.names)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in {"import_module", "__import__"} and isinstance(node.args[0].value, str):
                found.append((node.lineno, node.args[0].value))
    return found


MOVED_MODULES = [
    "aragora/observability/audit_log.py",
    "aragora/observability/unified_audit.py",
    "aragora/observability/audit_persistence/__init__.py",
    "aragora/observability/audit_persistence/base.py",
    "aragora/observability/audit_persistence/file.py",
    "aragora/observability/audit_persistence/postgres.py",
]
FLIPPED_SITES = [
    "aragora/storage/production_guards.py",
    "aragora/debate/settlement_event_listener.py",
    "aragora/rlm/bridge.py",
]


def _offenders(relative_path: str, packages: tuple[str, ...]) -> list[str]:
    return [
        f"{relative_path}:{lineno} {module}"
        for lineno, module in _imported_modules(REPO_ROOT / relative_path)
        if ".".join(module.split(".")[:2]) in packages
    ]


@pytest.mark.parametrize("relative_path", MOVED_MODULES)
def test_moved_modules_import_neither_audit_nor_server(relative_path: str) -> None:
    assert _offenders(relative_path, ("aragora.audit", "aragora.server")) == []


@pytest.mark.parametrize("relative_path", MOVED_MODULES + FLIPPED_SITES)
def test_no_import_of_audit_package(relative_path: str) -> None:
    assert _offenders(relative_path, ("aragora.audit",)) == []
