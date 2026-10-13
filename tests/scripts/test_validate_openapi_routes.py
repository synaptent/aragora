"""Tests for scripts/validate_openapi_routes.py baseline behavior."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

import scripts.validate_openapi_routes as validate_openapi_routes


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_bytes,
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8").strip()


@dataclass(frozen=True)
class ExactRefRepo:
    repo: Path
    handler_registry: Path
    spec: Path
    ref_a: str
    ref_b: str


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    return repo


@pytest.fixture
def exact_ref_repo(git_repo: Path) -> ExactRefRepo:
    repo = git_repo
    source_root = Path(validate_openapi_routes.__file__).resolve().parents[1]

    for relative in (
        "scripts/sdk_path_normalize.py",
        "scripts/baselines/contract_drift_inventory.json",
    ):
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / relative, destination)

    (repo / "scripts/baselines/internal_route_prefixes.json").write_text(
        '{"prefixes":["/api/v1/internal/"]}\n',
        encoding="utf-8",
    )
    for relative in (
        "aragora/__init__.py",
        "aragora/server/__init__.py",
        "aragora/server/stream/__init__.py",
    ):
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("", encoding="utf-8")
    registration = repo / "aragora/server/stream/servers_route_registration.py"
    registration.write_text("# no literal wired registrations\n", encoding="utf-8")

    handler_registry = repo / "aragora/server/handler_registry.py"
    handler_registry.write_text(
        """
class ExactRefHandler:
    GET_ROUTES = ["/api/v1/ref-a"]

HANDLER_REGISTRY = [("_exact_ref", ExactRefHandler)]

def get_active_tiers():
    return {"core"}

def filter_registry_by_tier(registry, active_tiers=None):
    return list(registry)
""".lstrip(),
        encoding="utf-8",
    )
    spec = repo / "docs/api/openapi.json"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        json.dumps({"paths": {"/api/v1/ref-a": {"get": {}}}}) + "\n",
        encoding="utf-8",
    )

    _git(repo, "config", "user.name", "Exact Ref Test")
    _git(repo, "config", "user.email", "exact-ref@example.invalid")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "fixture ref a")
    ref_a = _git(repo, "rev-parse", "HEAD")

    handler_registry.write_text(
        handler_registry.read_text(encoding="utf-8").replace("/api/v1/ref-a", "/api/v1/ref-b"),
        encoding="utf-8",
    )
    spec.write_text(
        json.dumps({"paths": {"/api/v1/ref-b": {"post": {}}}}) + "\n",
        encoding="utf-8",
    )
    registration.write_text(
        'router.add_post("/api/v1/ref-b-wired", handler)\n',
        encoding="utf-8",
    )
    (repo / "scripts/sdk_path_normalize.py").write_text(
        'def normalize_sdk_path(path): return "/api/ref-b-normalized"\n',
        encoding="utf-8",
    )
    (repo / "scripts/baselines/internal_route_prefixes.json").write_text(
        '{"prefixes":["/api/"]}\n',
        encoding="utf-8",
    )
    (repo / "scripts/baselines/contract_drift_inventory.json").write_text(
        '{"ref_b":"not valid projection authority"}\n',
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "fixture ref b")
    ref_b = _git(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "moving-ref", ref_a)

    return ExactRefRepo(
        repo=repo,
        handler_registry=handler_registry,
        spec=spec,
        ref_a=ref_a,
        ref_b=ref_b,
    )


def _run_exact_ref_fixture(fixture: ExactRefRepo, resolved_ref: str) -> dict:
    return validate_openapi_routes._run_method_aware_plane_at_commit(
        spec_path="docs/api/openapi.json",
        resolved_ref=resolved_ref,
        internal_prefixes_path="scripts/baselines/internal_route_prefixes.json",
        source_repo_root=fixture.repo,
    )


def test_zero_sha_ref_fails_closed(git_repo: Path):
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="cannot resolve"):
        validate_openapi_routes._require_exact_ref(
            "0" * 40,
            source_repo_root=git_repo,
        )


def test_nonexistent_and_noncommit_refs_fail_closed(git_repo: Path):
    repo = git_repo
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="cannot resolve"):
        validate_openapi_routes._require_exact_ref(
            "refs/heads/does-not-exist",
            source_repo_root=repo,
        )

    blob = _git(repo, "hash-object", "-w", "--stdin", input_bytes=b"not a commit\n")
    _git(repo, "tag", "blob-ref", blob)
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="commit"):
        validate_openapi_routes._require_exact_ref("blob-ref", source_repo_root=repo)


def test_valid_non_head_ref_reads_only_that_commit(exact_ref_repo: ExactRefRepo):
    ref_a = exact_ref_repo.ref_a
    assert _git(exact_ref_repo.repo, "rev-parse", "HEAD") == exact_ref_repo.ref_b

    plane = _run_exact_ref_fixture(exact_ref_repo, ref_a)

    assert plane["ref"] == ref_a
    assert {entry["operation_id"] for entry in plane["declared_and_served"]} == {"GET /api/ref-a"}
    assert all(entry["source_sha"] == ref_a for entry in plane["served_operations"])
    assert all(entry["source_sha"] == ref_a for entry in plane["spec_operations"])
    assert "POST /api/ref-b" not in {entry["operation_id"] for entry in plane["spec_operations"]}


def test_dirty_caller_state_cannot_change_same_sha_output(exact_ref_repo: ExactRefRepo):
    ref_a = exact_ref_repo.ref_a
    clean = _run_exact_ref_fixture(exact_ref_repo, ref_a)

    exact_ref_repo.handler_registry.write_text(
        """
class DirtyHandler:
    DELETE_ROUTES = ["/api/v1/dirty-only"]
HANDLER_REGISTRY = [("_dirty", DirtyHandler)]
def get_active_tiers():
    return {"core"}
def filter_registry_by_tier(registry, active_tiers=None):
    return list(registry)
""".lstrip(),
        encoding="utf-8",
    )
    exact_ref_repo.spec.write_text(
        json.dumps({"paths": {"/api/v1/dirty-only": {"delete": {}}}}) + "\n",
        encoding="utf-8",
    )
    repo = exact_ref_repo.repo
    (repo / "aragora/server/stream/servers_route_registration.py").write_text(
        'router.add_delete("/api/v1/dirty-wired", handler)\n',
        encoding="utf-8",
    )
    (repo / "scripts/sdk_path_normalize.py").write_text(
        'def normalize_sdk_path(path): return "/api/dirty-normalized"\n',
        encoding="utf-8",
    )
    (repo / "scripts/baselines/internal_route_prefixes.json").write_text(
        '{"prefixes":["/api/"]}\n',
        encoding="utf-8",
    )
    (repo / "scripts/baselines/contract_drift_inventory.json").write_text(
        '{"dirty":"ambient inventory must not be read"}\n',
        encoding="utf-8",
    )
    (repo / "untracked-dirty.txt").write_text(
        "ambient caller state\n",
        encoding="utf-8",
    )

    dirty = _run_exact_ref_fixture(exact_ref_repo, ref_a)

    assert dirty == clean
    assert all("/dirty-only" not in entry["operation_id"] for entry in dirty["served_operations"])


def test_moving_symbolic_ref_is_resolved_once(
    exact_ref_repo: ExactRefRepo,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = exact_ref_repo.repo
    with monkeypatch.context() as isolated_env:
        isolated_env.setenv("GIT_DIR", str(repo / "ambient-wrong.git"))
        resolved = validate_openapi_routes._require_exact_ref(
            "moving-ref",
            source_repo_root=repo,
        )
    assert resolved == exact_ref_repo.ref_a

    _git(repo, "branch", "-f", "moving-ref", exact_ref_repo.ref_b)
    plane = _run_exact_ref_fixture(exact_ref_repo, resolved)

    assert plane["ref"] == exact_ref_repo.ref_a
    assert {entry["operation_id"] for entry in plane["declared_and_served"]} == {"GET /api/ref-a"}


def test_direct_method_aware_entrypoint_delegates_to_exact_tree(
    monkeypatch: pytest.MonkeyPatch,
):
    resolved = "a" * 40
    expected = {"ref": resolved}
    captured: dict[str, object] = {}

    def fake_resolve(ref, *, source_repo_root):
        captured["ref"] = ref
        captured["source_repo_root"] = source_repo_root
        return resolved

    def fake_run(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(validate_openapi_routes, "_require_exact_ref", fake_resolve)
    monkeypatch.setattr(
        validate_openapi_routes,
        "_run_method_aware_plane_at_commit",
        fake_run,
    )

    result = validate_openapi_routes.validate_method_aware_plane(
        "docs/api/openapi.json",
        "moving-ref",
        internal_prefixes_path="scripts/baselines/internal_route_prefixes.json",
    )

    assert result is expected
    assert captured == {
        "ref": "moving-ref",
        "source_repo_root": validate_openapi_routes._SOURCE_REPO_ROOT,
        "spec_path": "docs/api/openapi.json",
        "resolved_ref": resolved,
        "internal_prefixes_path": "scripts/baselines/internal_route_prefixes.json",
        "inventory_path": None,
    }


def _fake_registry(entries):
    """Fake handler_registry module mirroring the real tier-filter surface."""
    return types.SimpleNamespace(
        HANDLER_REGISTRY=entries,
        get_active_tiers=lambda: {"core", "extended", "optional"},
        filter_registry_by_tier=lambda registry, active_tiers=None: list(registry),
    )


def test_fail_on_missing_passes_when_only_baseline_drift(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        validate_openapi_routes, "get_handler_routes", lambda: {"/api/v1/a", "/api/v1/b"}
    )
    monkeypatch.setattr(validate_openapi_routes, "get_openapi_routes", lambda _spec: {"/api/v1/b"})
    monkeypatch.setattr(validate_openapi_routes, "get_wired_function_routes", lambda: set())

    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "missing_in_spec": ["/api/v1/a"],
                "orphaned_in_spec": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    results = validate_openapi_routes.validate_coverage(
        "ignored.json",
        fail_on_missing=True,
        output_json=False,
        baseline_path=str(baseline),
    )
    assert results["missing_in_spec_count"] == 1
    assert results["new_missing_in_spec_count"] == 0


def test_fail_on_missing_fails_on_new_drift(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        validate_openapi_routes, "get_handler_routes", lambda: {"/api/v1/a", "/api/v1/b"}
    )
    monkeypatch.setattr(validate_openapi_routes, "get_openapi_routes", lambda _spec: {"/api/v1/b"})
    monkeypatch.setattr(validate_openapi_routes, "get_wired_function_routes", lambda: set())

    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "missing_in_spec": [],
                "orphaned_in_spec": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        validate_openapi_routes.validate_coverage(
            "ignored.json",
            fail_on_missing=True,
            output_json=False,
            baseline_path=str(baseline),
        )
    assert excinfo.value.code == 1


def test_internal_prefixes_are_excluded_by_default(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        validate_openapi_routes,
        "get_handler_routes",
        lambda: {"/api/v1/control-plane/agents"},
    )
    monkeypatch.setattr(validate_openapi_routes, "get_openapi_routes", lambda _spec: set())
    monkeypatch.setattr(validate_openapi_routes, "get_wired_function_routes", lambda: set())

    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"missing_in_spec": [], "orphaned_in_spec": []}\n', encoding="utf-8")

    results = validate_openapi_routes.validate_coverage(
        "ignored.json",
        fail_on_missing=True,
        output_json=False,
        baseline_path=str(baseline),
    )
    assert results["missing_in_spec_count"] == 0


def test_get_handler_routes_resolves_deferred_imports(monkeypatch):
    class DummyHandler:
        ROUTES = ["/api/v1/test/routes"]
        GET_ROUTES = ["/api/v1/test/get"]

    class DummyDeferred:
        def resolve(self):
            return DummyHandler

    fake_registry = _fake_registry([("_dummy", DummyDeferred())])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)

    routes = validate_openapi_routes.get_handler_routes()
    assert "/api/v1/test/routes" in routes
    assert "/api/v1/test/get" in routes


def test_get_handler_routes_includes_api_endpoint_metadata(monkeypatch):
    endpoint = types.SimpleNamespace(path="/api/v1/coordination/fleet/status")

    class DummyHandler:
        def handle(self):
            return None

    setattr(DummyHandler.handle, "_openapi", endpoint)

    fake_registry = _fake_registry([("_dummy", DummyHandler)])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)

    routes = validate_openapi_routes.get_handler_routes()

    assert "/api/v1/coordination/fleet/status" in routes


def test_get_wired_function_routes_accepts_only_called_literal_app_routes(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    handler = tmp_path / "aragora" / "server" / "handlers" / "wired.py"
    registration.parent.mkdir(parents=True)
    handler.parent.mkdir(parents=True)
    registration.write_text(
        """
from aragora.server.handlers.wired import register_routes as register_wired
from aragora.server.handlers.wired import register_unused

def install(app):
    register_wired(app)
""".lstrip(),
        encoding="utf-8",
    )
    handler.write_text(
        """
def register_routes(app):
    computed = "/api/v1/computed"
    app.router.add_get("/api/v1/wired", object())
    app.router.add_post("/api/wired-legacy", object())
    app.router.add_put(computed, object())
    other.router.add_delete("/api/v1/other-router", object())
    def dormant():
        app.router.add_get("/api/v1/nested-unwired", object())

def register_unused(app):
    app.router.add_get("/api/v1/unwired", object())
""".lstrip(),
        encoding="utf-8",
    )

    routes = validate_openapi_routes.get_wired_function_routes(registration, tmp_path)

    assert routes == {"/api/v1/wired", "/api/wired-legacy"}
    assert {validate_openapi_routes.normalize_route(route) for route in routes} == {
        "/api/v1/wired",
        "/api/v1/wired-legacy",
    }
    assert {
        validate_openapi_routes.normalize_route(route, normalize_version=False) for route in routes
    } == {"/api/v1/wired", "/api/wired-legacy"}


def test_get_wired_function_routes_fails_closed_on_unparseable_source(tmp_path: Path):
    registration = tmp_path / "registration.py"
    registration.write_text("def broken(:\n", encoding="utf-8")

    with pytest.raises(validate_openapi_routes.RouteRegistrationScanError):
        validate_openapi_routes.get_wired_function_routes(registration, tmp_path)


def test_get_wired_function_routes_follows_package_reexports(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    package = tmp_path / "aragora" / "server" / "handlers" / "reexported"
    registration.parent.mkdir(parents=True)
    package.mkdir(parents=True)
    registration.write_text(
        "from aragora.server.handlers.reexported import register_routes\nregister_routes(app)\n",
        encoding="utf-8",
    )
    (package / "__init__.py").write_text("from .routes import register_routes\n", encoding="utf-8")
    (package / "routes.py").write_text(
        'def register_routes(app):\n    app.router.add_get("/api/v1/reexported", object())\n',
        encoding="utf-8",
    )

    routes = validate_openapi_routes.get_wired_function_routes(registration, tmp_path)

    assert routes == {"/api/v1/reexported"}


def test_get_wired_function_routes_fails_closed_on_unresolved_reexport(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    package = tmp_path / "aragora" / "server" / "handlers" / "reexported"
    registration.parent.mkdir(parents=True)
    package.mkdir(parents=True)
    registration.write_text(
        "from aragora.server.handlers.reexported import register_routes\nregister_routes(app)\n",
        encoding="utf-8",
    )
    (package / "__init__.py").write_text("from .missing import register_routes\n", encoding="utf-8")

    with pytest.raises(validate_openapi_routes.RouteRegistrationScanError):
        validate_openapi_routes.get_wired_function_routes(registration, tmp_path)


def test_wired_function_routes_include_known_server_registrations():
    routes = validate_openapi_routes.get_wired_function_routes()

    assert {
        "/api/v1/accounting/callback",
        "/api/v1/accounting/gusto/callback",
        "/api/v1/accounting/gusto/connect",
        "/api/v1/accounting/gusto/disconnect",
        "/api/v1/accounting/report",
        "/api/v1/codebase/quick-scan",
        "/api/v1/codebase/quick-scans",
        "/api/v1/costs",
        "/api/v1/payments/charge",
    } <= routes


def test_validate_coverage_uses_exact_wired_routes_for_missing_and_orphans(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setattr(validate_openapi_routes, "get_handler_routes", lambda: set())
    monkeypatch.setattr(
        validate_openapi_routes,
        "get_openapi_routes",
        lambda _spec: {"/api/v1/wired", "/api/v1/wired-legacy", "/api/v1/dark"},
    )
    monkeypatch.setattr(
        validate_openapi_routes,
        "get_wired_function_routes",
        lambda: {"/api/v1/wired", "/api/wired-legacy"},
    )

    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"missing_in_spec": [], "orphaned_in_spec": []}\n', encoding="utf-8")

    results = validate_openapi_routes.validate_coverage(
        "ignored.json",
        baseline_path=str(baseline),
        include_internal=True,
    )

    assert results["missing_in_spec"] == ["/api/wired-legacy"]
    assert results["orphaned_in_spec"] == ["/api/v1/dark", "/api/v1/wired-legacy"]
    assert results["served_wired_registration"] == ["/api/v1/wired"]


@pytest.mark.parametrize(
    ("spec_routes", "wired_routes", "handler_routes", "orphaned", "served"),
    [
        ({"/api/foo"}, {"/api/foo"}, set(), [], ["/api/foo"]),
        ({"/api/v1/foo"}, {"/api/foo"}, set(), ["/api/v1/foo"], []),
        (
            {"/api/foo", "/api/v1/foo"},
            {"/api/foo"},
            set(),
            ["/api/v1/foo"],
            ["/api/foo"],
        ),
        ({"/api/v1/foo"}, {"/api/v1/foo"}, set(), [], ["/api/v1/foo"]),
        ({"/api/foo"}, set(), {"/api/v1/foo"}, [], []),
    ],
)
def test_validate_coverage_preserves_exact_wired_alias_semantics(
    monkeypatch,
    tmp_path: Path,
    spec_routes: set[str],
    wired_routes: set[str],
    handler_routes: set[str],
    orphaned: list[str],
    served: list[str],
):
    monkeypatch.setattr(validate_openapi_routes, "get_handler_routes", lambda: handler_routes)
    monkeypatch.setattr(validate_openapi_routes, "get_openapi_routes", lambda _spec: spec_routes)
    monkeypatch.setattr(validate_openapi_routes, "get_wired_function_routes", lambda: wired_routes)

    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"missing_in_spec": [], "orphaned_in_spec": []}\n', encoding="utf-8")

    results = validate_openapi_routes.validate_coverage(
        "ignored.json",
        baseline_path=str(baseline),
        include_internal=True,
    )

    assert results["orphaned_in_spec"] == orphaned
    assert results["served_wired_registration"] == served


def test_validate_coverage_counts_wired_routes_missing_from_spec(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(validate_openapi_routes, "get_handler_routes", lambda: set())
    monkeypatch.setattr(
        validate_openapi_routes,
        "get_openapi_routes",
        lambda _spec: {"/api/v1/wired-present", "/api/wired-legacy"},
    )
    monkeypatch.setattr(
        validate_openapi_routes,
        "get_wired_function_routes",
        lambda: {
            "/api/v1/wired-present",
            "/api/v1/wired-missing",
            "/api/wired-legacy",
        },
    )

    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"missing_in_spec": [], "orphaned_in_spec": []}\n', encoding="utf-8")

    results = validate_openapi_routes.validate_coverage(
        "ignored.json",
        baseline_path=str(baseline),
        include_internal=True,
    )

    assert results["missing_in_spec"] == ["/api/v1/wired-missing"]


def test_validate_coverage_excludes_internal_wired_routes(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(validate_openapi_routes, "get_handler_routes", lambda: set())
    monkeypatch.setattr(validate_openapi_routes, "get_openapi_routes", lambda _spec: set())
    monkeypatch.setattr(
        validate_openapi_routes,
        "get_wired_function_routes",
        lambda: {"/api/v1/control-plane/private", "/api/control-plane/legacy"},
    )

    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"missing_in_spec": [], "orphaned_in_spec": []}\n', encoding="utf-8")

    results = validate_openapi_routes.validate_coverage(
        "ignored.json",
        baseline_path=str(baseline),
    )

    assert results["missing_in_spec"] == []


def test_filter_wired_orphans_preserves_exact_default_registry(monkeypatch):
    monkeypatch.setattr(
        validate_openapi_routes,
        "load_wired_routes_for_validation",
        lambda: {"/api/wired-legacy"},
    )

    orphaned, served = validate_openapi_routes.filter_wired_orphans({"/api/v1/wired-legacy"})

    assert orphaned == {"/api/v1/wired-legacy"}
    assert served == set()


def test_validate_coverage_treats_decorator_routes_as_implemented(monkeypatch, tmp_path: Path):
    endpoint = types.SimpleNamespace(path="/api/v1/coordination/swarm/integrator")

    class DummyHandler:
        def handle(self):
            return None

    setattr(DummyHandler.handle, "_openapi", endpoint)

    fake_registry = _fake_registry([("_dummy", DummyHandler)])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)
    monkeypatch.setattr(
        validate_openapi_routes,
        "get_openapi_routes",
        lambda _spec: {"/api/v1/coordination/swarm/integrator"},
    )
    monkeypatch.setattr(validate_openapi_routes, "get_wired_function_routes", lambda: set())

    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"missing_in_spec": [], "orphaned_in_spec": []}\n', encoding="utf-8")

    results = validate_openapi_routes.validate_coverage(
        "ignored.json",
        fail_on_missing=False,
        output_json=True,
        baseline_path=str(baseline),
        include_internal=True,
    )

    assert "/api/v1/coordination/swarm/integrator" not in results["orphaned_in_spec"]


def test_get_openapi_routes_includes_sibling_generated_snapshot(tmp_path: Path):
    spec = tmp_path / "openapi.json"
    generated = tmp_path / "openapi_generated.json"
    spec.write_text(json.dumps({"paths": {"/api/v1/canonical": {"get": {}}}}), encoding="utf-8")
    generated.write_text(
        json.dumps({"paths": {"/api/v1/generated": {"get": {}}}}), encoding="utf-8"
    )

    routes = validate_openapi_routes.get_openapi_routes(str(spec))

    assert "/api/v1/canonical" in routes
    assert "/api/v1/generated" in routes


def test_validate_coverage_counts_prompt_engine_registry_routes() -> None:
    results = validate_openapi_routes.validate_coverage(
        "docs/api/openapi.json",
        output_json=True,
    )

    assert "/api/v1/prompt-engine/run" not in results["orphaned_in_spec"]
    assert "/api/v1/prompt-engine/decompose" not in results["orphaned_in_spec"]


def test_filter_served_orphans_drops_can_handle_routes(monkeypatch):
    class ServingHandler:
        def can_handle(self, path: str, method: str = "GET") -> bool:
            return path in ("/api/v1/served/route", "/api/served/route")

    fake_registry = _fake_registry([("_serving", ServingHandler)])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)

    orphaned, served = validate_openapi_routes.filter_served_orphans(
        {"/api/v1/served/route", "/api/v1/dark/route"}
    )

    assert served == {"/api/v1/served/route"}
    assert orphaned == {"/api/v1/dark/route"}


def test_filter_served_orphans_does_not_credit_v1_matcher_for_legacy_candidate(monkeypatch):
    """A v1-only exact matcher must NOT suppress a legacy /api/ candidate.

    The live router passes the raw request path to can_handle with no
    legacy<->v1 aliasing, so a legacy-path request 404s even when the
    handler accepts the /api/v1/ form. Probing the v1 variant for a legacy
    candidate would mark genuinely-orphaned spec paths as served.
    """

    class VersionedOnlyHandler:
        def can_handle(self, path: str, method: str = "GET") -> bool:
            return path == "/api/v1/served/versioned-only"

    fake_registry = _fake_registry([("_serving", VersionedOnlyHandler)])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)

    orphaned, served = validate_openapi_routes.filter_served_orphans({"/api/served/versioned-only"})

    assert orphaned == {"/api/served/versioned-only"}
    assert served == set()


def test_filter_served_orphans_survives_broken_can_handle(monkeypatch):
    class BrokenHandler:
        def can_handle(self, path: str, method: str = "GET") -> bool:
            raise AttributeError("uninitialized state")

    fake_registry = _fake_registry([("_broken", BrokenHandler)])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)

    orphaned, served = validate_openapi_routes.filter_served_orphans({"/api/v1/x"})

    assert orphaned == {"/api/v1/x"}
    assert served == set()


def test_load_internal_prefixes_fails_closed_on_missing_file(tmp_path: Path):
    missing = tmp_path / "nope" / "internal_route_prefixes.json"

    with pytest.raises(SystemExit) as excinfo:
        validate_openapi_routes.load_internal_prefixes(str(missing))
    assert excinfo.value.code == 1


def test_load_internal_prefixes_fails_closed_on_unparseable_file(tmp_path: Path):
    policy = tmp_path / "internal_route_prefixes.json"
    policy.write_text("{not json", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        validate_openapi_routes.load_internal_prefixes(str(policy))
    assert excinfo.value.code == 1


def test_load_internal_prefixes_fails_closed_on_invalid_shape(tmp_path: Path):
    policy = tmp_path / "internal_route_prefixes.json"
    policy.write_text('{"prefixes": "not-a-list"}', encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        validate_openapi_routes.load_internal_prefixes(str(policy))
    assert excinfo.value.code == 1


def test_load_internal_prefixes_reads_repo_policy_by_default():
    prefixes = validate_openapi_routes.load_internal_prefixes()

    assert prefixes
    assert all(p.startswith("/api/") for p in prefixes)


def test_filter_served_orphans_rejects_prefix_matching_can_handle(monkeypatch):
    class BroadHandler:
        def can_handle(self, path: str, method: str = "GET") -> bool:
            return path.startswith("/api/v1/broad") or path.startswith("/api/broad")

    fake_registry = _fake_registry([("_broad", BroadHandler)])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)

    orphaned, served = validate_openapi_routes.filter_served_orphans({"/api/v1/broad/route"})

    # BroadHandler also claims the nonexistent canary path, so its can_handle
    # is non-specific and must not suppress the orphan.
    assert orphaned == {"/api/v1/broad/route"}
    assert served == set()


def test_filter_served_orphans_logs_suppressions(monkeypatch, capsys):
    class ServingHandler:
        def can_handle(self, path: str, method: str = "GET") -> bool:
            return path in ("/api/v1/served/route", "/api/served/route")

    fake_registry = _fake_registry([("_serving", ServingHandler)])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)

    orphaned, served = validate_openapi_routes.filter_served_orphans({"/api/v1/served/route"})

    assert served == {"/api/v1/served/route"}
    assert orphaned == set()
    err = capsys.readouterr().err
    assert "/api/v1/served/route" in err
    assert "ServingHandler" in err


def test_validate_coverage_excludes_served_orphans(monkeypatch, tmp_path: Path):
    class ServingHandler:
        ROUTES = ["/api/v1/declared"]

        def can_handle(self, path: str, method: str = "GET") -> bool:
            return path == "/api/v1/served-only"

    fake_registry = _fake_registry([("_serving", ServingHandler)])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)
    monkeypatch.setattr(
        validate_openapi_routes,
        "get_openapi_routes",
        lambda _spec: {"/api/v1/declared", "/api/v1/served-only", "/api/v1/dark"},
    )
    monkeypatch.setattr(validate_openapi_routes, "get_wired_function_routes", lambda: set())

    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"missing_in_spec": [], "orphaned_in_spec": []}\n', encoding="utf-8")

    results = validate_openapi_routes.validate_coverage(
        "ignored.json",
        fail_on_missing=False,
        output_json=True,
        baseline_path=str(baseline),
        include_internal=True,
    )

    assert results["orphaned_in_spec"] == ["/api/v1/dark"]
    assert results["served_undeclared"] == ["/api/v1/served-only"]


def test_is_internal_route_matches_exact_family_not_sibling_names():
    """Round-1 review P2 on #9360: startswith on the prefix without its
    trailing slash overmatches — /api/v1/smear must NOT fall under the
    /api/v1/sme/ internal family."""
    prefixes = ("/api/v1/sme/",)
    assert validate_openapi_routes.is_internal_route("/api/v1/sme/dashboard", prefixes)
    assert validate_openapi_routes.is_internal_route("/api/v1/sme", prefixes)
    assert not validate_openapi_routes.is_internal_route("/api/v1/smear", prefixes)
    assert not validate_openapi_routes.is_internal_route("/api/v1/smear/x", prefixes)


# ---------------------------------------------------------------------------
# Mounted-FastAPI-router evidence plane (additive; ledger 397 point 3)
# ---------------------------------------------------------------------------


def _write_fastapi_tree(
    tmp_path: Path,
    factory_source: str,
    route_modules: dict[str, str],
) -> Path:
    """Lay out a synthetic aragora/server/fastapi tree and return factory path."""
    fastapi_dir = tmp_path / "aragora" / "server" / "fastapi"
    routes_dir = fastapi_dir / "routes"
    routes_dir.mkdir(parents=True)
    (routes_dir / "__init__.py").write_text("", encoding="utf-8")
    factory = fastapi_dir / "factory.py"
    factory.write_text(factory_source, encoding="utf-8")
    for name, source in route_modules.items():
        (routes_dir / f"{name}.py").write_text(source, encoding="utf-8")
    return factory


def test_get_fastapi_mounted_routes_extracts_mounted_router_paths(tmp_path: Path):
    factory = _write_fastapi_tree(
        tmp_path,
        """
from .routes import shop, ghost

def create_app():
    app = object()
    app.include_router(shop.router)
    return app
""".lstrip(),
        {
            "shop": """
from fastapi import APIRouter

router = APIRouter(prefix="/api/v2/shop", tags=["Shop"])

@router.get("/items")
async def list_items():
    return []

@router.post("/items")
async def create_item():
    return {}

@router.get("/items/{item_id}")
async def get_item(item_id: str):
    return {}
""".lstrip(),
            # Imported in the factory but never mounted: contributes nothing.
            "ghost": """
from fastapi import APIRouter

router = APIRouter(prefix="/api/v2/ghost")

@router.get("/status")
async def ghost_status():
    return {}
""".lstrip(),
        },
    )

    routes = validate_openapi_routes.get_fastapi_mounted_routes(factory, tmp_path)

    assert routes == {
        "/api/v2/shop/items",
        "/api/v2/shop/items/{item_id}",
    }


def test_get_fastapi_mounted_routes_combines_include_router_prefix(tmp_path: Path):
    factory = _write_fastapi_tree(
        tmp_path,
        """
from .routes import things

def create_app(app):
    app.include_router(things.router, prefix="/api/v2")
""".lstrip(),
        {
            "things": """
from fastapi import APIRouter

router = APIRouter()

@router.get("/things")
async def list_things():
    return []
""".lstrip(),
        },
    )

    routes = validate_openapi_routes.get_fastapi_mounted_routes(factory, tmp_path)

    assert routes == {"/api/v2/things"}


def test_get_fastapi_mounted_routes_skips_non_literal_paths(tmp_path: Path):
    factory = _write_fastapi_tree(
        tmp_path,
        """
from .routes import mixed, computed_prefix

PREFIX = "/api/v2"

def create_app(app):
    app.include_router(mixed.router)
    app.include_router(computed_prefix.router, prefix=PREFIX)
""".lstrip(),
        {
            "mixed": """
from fastapi import APIRouter

router = APIRouter(prefix="/api/v2/mixed")
_computed = "/computed"

@router.get("/literal")
async def literal():
    return {}

@router.get(_computed)
async def computed():
    return {}
""".lstrip(),
            # Mount uses a computed prefix: unverifiable, contributes nothing.
            "computed_prefix": """
from fastapi import APIRouter

router = APIRouter()

@router.get("/whatever")
async def whatever():
    return {}
""".lstrip(),
        },
    )

    routes = validate_openapi_routes.get_fastapi_mounted_routes(factory, tmp_path)

    assert routes == {"/api/v2/mixed/literal"}


def test_get_fastapi_mounted_routes_fails_closed_on_unparseable_factory(tmp_path: Path):
    factory = tmp_path / "aragora" / "server" / "fastapi" / "factory.py"
    factory.parent.mkdir(parents=True)
    factory.write_text("def broken(:\n", encoding="utf-8")

    with pytest.raises(validate_openapi_routes.RouteRegistrationScanError):
        validate_openapi_routes.get_fastapi_mounted_routes(factory, tmp_path)


def test_get_fastapi_mounted_routes_fails_closed_on_missing_mounted_module(tmp_path: Path):
    factory = _write_fastapi_tree(
        tmp_path,
        """
from .routes import shop

def create_app(app):
    app.include_router(shop.router)
""".lstrip(),
        {
            "shop": """
from fastapi import APIRouter

router = APIRouter(prefix="/api/v2/shop")

@router.get("/items")
async def list_items():
    return []
""".lstrip(),
        },
    )
    (tmp_path / "aragora" / "server" / "fastapi" / "routes" / "shop.py").unlink()

    with pytest.raises(validate_openapi_routes.RouteRegistrationScanError):
        validate_openapi_routes.get_fastapi_mounted_routes(factory, tmp_path)


def test_get_fastapi_mounted_routes_fails_closed_on_missing_router_definition(tmp_path: Path):
    factory = _write_fastapi_tree(
        tmp_path,
        """
from .routes import broken

def create_app(app):
    app.include_router(broken.router)
""".lstrip(),
        {
            # Mounted, but no module-level `router = APIRouter(...)` to inspect.
            "broken": """
def make_router():
    from fastapi import APIRouter

    router = APIRouter(prefix="/api/v2/broken")
    return router
""".lstrip(),
        },
    )

    with pytest.raises(validate_openapi_routes.RouteRegistrationScanError):
        validate_openapi_routes.get_fastapi_mounted_routes(factory, tmp_path)


def test_validate_coverage_credits_fastapi_mounted_routes(monkeypatch, tmp_path: Path):
    """Positive + negative: a mounted path is served, an unmounted one stays orphaned."""
    monkeypatch.setattr(validate_openapi_routes, "get_handler_routes", lambda: set())
    monkeypatch.setattr(
        validate_openapi_routes,
        "get_openapi_routes",
        lambda _spec: {"/api/v2/shop/items", "/api/v2/zz-truly-unmounted"},
    )
    monkeypatch.setattr(validate_openapi_routes, "get_wired_function_routes", lambda: set())
    monkeypatch.setattr(
        validate_openapi_routes,
        "get_fastapi_mounted_routes",
        lambda: {"/api/v2/shop/items"},
    )
    fake_registry = types.SimpleNamespace(HANDLER_REGISTRY=[])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)

    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"missing_in_spec": [], "orphaned_in_spec": []}\n', encoding="utf-8")

    results = validate_openapi_routes.validate_coverage(
        "ignored.json",
        baseline_path=str(baseline),
        include_internal=True,
    )

    assert results["orphaned_in_spec"] == ["/api/v2/zz-truly-unmounted"]
    assert results["served_fastapi_mounted"] == ["/api/v2/shop/items"]
    assert "/api/v2/shop/items" in results["served_undeclared"]


def test_validate_coverage_fastapi_plane_does_not_feed_missing_in_spec(monkeypatch, tmp_path: Path):
    """The FastAPI plane is serve evidence only: a mounted route absent from the
    spec must NOT become missing_in_spec (the mounted surface is opt-in, so it
    carries no declaration obligation), and the existing planes' missing_in_spec
    arithmetic stays untouched."""
    monkeypatch.setattr(validate_openapi_routes, "get_handler_routes", lambda: set())
    monkeypatch.setattr(
        validate_openapi_routes,
        "get_openapi_routes",
        lambda _spec: {"/api/v2/shop/items"},
    )
    monkeypatch.setattr(validate_openapi_routes, "get_wired_function_routes", lambda: set())
    monkeypatch.setattr(
        validate_openapi_routes,
        "get_fastapi_mounted_routes",
        lambda: {"/api/v2/shop/items", "/api/v2/shop/absent-from-spec"},
    )
    fake_registry = types.SimpleNamespace(HANDLER_REGISTRY=[])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)

    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"missing_in_spec": [], "orphaned_in_spec": []}\n', encoding="utf-8")

    results = validate_openapi_routes.validate_coverage(
        "ignored.json",
        baseline_path=str(baseline),
        include_internal=True,
    )

    assert results["missing_in_spec"] == []
    assert results["orphaned_in_spec"] == []
    assert results["served_fastapi_mounted"] == ["/api/v2/shop/items"]


def test_validate_coverage_excludes_internal_fastapi_routes(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(validate_openapi_routes, "get_handler_routes", lambda: set())
    monkeypatch.setattr(
        validate_openapi_routes,
        "get_openapi_routes",
        lambda _spec: {"/api/v1/control-plane/private"},
    )
    monkeypatch.setattr(validate_openapi_routes, "get_wired_function_routes", lambda: set())
    monkeypatch.setattr(
        validate_openapi_routes,
        "get_fastapi_mounted_routes",
        lambda: {"/api/v1/control-plane/private"},
    )
    fake_registry = types.SimpleNamespace(HANDLER_REGISTRY=[])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)

    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"missing_in_spec": [], "orphaned_in_spec": []}\n', encoding="utf-8")

    results = validate_openapi_routes.validate_coverage(
        "ignored.json",
        baseline_path=str(baseline),
    )

    # Internal families are excluded from BOTH the candidates and the plane, so
    # nothing is orphaned and nothing is credited to the FastAPI plane.
    assert results["orphaned_in_spec"] == []
    assert results["served_fastapi_mounted"] == []


def test_filter_fastapi_orphans_logs_suppressions(monkeypatch, capsys):
    monkeypatch.setattr(
        validate_openapi_routes,
        "load_fastapi_routes_for_validation",
        lambda: {"/api/v2/shop/items"},
    )

    orphaned, served = validate_openapi_routes.filter_fastapi_orphans(
        {"/api/v2/shop/items", "/api/v2/dark"}
    )

    assert served == {"/api/v2/shop/items"}
    assert orphaned == {"/api/v2/dark"}
    err = capsys.readouterr().err
    assert "mounted FastAPI routers" in err
    assert "/api/v2/shop/items" in err


def test_real_factory_mounts_v2_marketplace_and_orchestration_paths():
    """The real factory mounts the v2 marketplace/orchestration routers whose
    spec entries were re-added by PR #9724 (ledger 397 point 1)."""
    routes = validate_openapi_routes.get_fastapi_mounted_routes()

    assert {
        "/api/v2/marketplace/categories",
        "/api/v2/marketplace/status",
        "/api/v2/marketplace/templates",
        "/api/v2/marketplace/templates/import",
        "/api/v2/orchestration/deliberate",
        "/api/v2/orchestration/deliberate/sync",
        "/api/v2/orchestration/templates",
    } <= routes


def test_real_factory_does_not_credit_unmounted_swarm_status_router():
    """swarm_status.py defines an APIRouter but is not imported/mounted by the
    factory, so its paths must never enter the evidence plane."""
    routes = validate_openapi_routes.get_fastapi_mounted_routes()

    assert not any(route.startswith("/api/v1/swarm") for route in routes)


# ---------------------------------------------------------------------------
# VAL-CDG-011: method-aware operation plane
# ---------------------------------------------------------------------------

REF = "a" * 40


def _op(method: str, path: str, **extra):
    return {
        "evidence_type": extra.pop("evidence_type", "handler_route_metadata"),
        "method": method,
        "raw_path_literal": path,
        "source_path": extra.pop("source_path", "aragora/server/handlers/test.py"),
        "symbol": extra.pop("symbol", "TestHandler.ROUTES"),
        **extra,
    }


def _build(witnesses, *, universe=None):
    return validate_openapi_routes._build_operations(
        witnesses,
        REF,
        method_universe=universe or validate_openapi_routes._RUNTIME_METHODS,
    )


def _algebra(served_witnesses, spec_witnesses, prefixes=("/api/v1/sme/",)):
    served = _build(served_witnesses)
    spec = _build(
        spec_witnesses,
        universe=frozenset(validate_openapi_routes.OPENAPI_METHOD_SET),
    )
    return validate_openapi_routes.build_route_set_algebra(served, spec, prefixes)


def _ids(collections, name):
    return [op["operation_id"] for op in collections[name]]


def test_route_set_algebra_is_exact_disjoint_and_complete():
    collections = _algebra(
        [
            _op("GET", "/api/public/thing"),
            _op("POST", "/api/public/thing"),
            _op("GET", "/api/v1/sme/dashboard"),
            _op("CONNECT", "/api/tunnel"),
        ],
        [
            _op("GET", "/api/public/thing", evidence_type="openapi_operation_key"),
            _op("DELETE", "/api/spec-only", evidence_type="openapi_operation_key"),
        ],
    )
    served = set(_ids(collections, "served_operations"))
    spec = set(_ids(collections, "spec_operations"))
    public = set(_ids(collections, "public_operations"))
    internal = set(_ids(collections, "internal_operations"))
    unresolved = set(_ids(collections, "unresolved_exposure"))
    sbu = set(_ids(collections, "served_but_undeclared"))
    das = set(_ids(collections, "declared_and_served"))
    unserved = set(_ids(collections, "unserved_spec"))

    # exact algebra, reconstructed from IDs (not counts)
    assert served == public | internal | unresolved
    assert not (public & internal) and not (public & unresolved) and not (internal & unresolved)
    assert sbu == served - spec
    assert das == served & spec
    assert unserved == spec - served
    assert served == sbu | das and not (sbu & das)
    assert spec == unserved | das and not (unserved & das)
    # sorted by canonical operation ID, no duplicates
    for name in (
        "served_operations",
        "spec_operations",
        "public_operations",
        "internal_operations",
        "unresolved_exposure",
        "served_but_undeclared",
        "declared_and_served",
        "unserved_spec",
    ):
        ids = _ids(collections, name)
        assert ids == sorted(ids)
        assert len(ids) == len(set(ids))
    # disjointness violations fail closed: two distinct collections sharing an
    # operation ID are rejected by the algebra's own disjointness prover
    shared = {
        "operation_id": "GET /api/a",
        "method": "GET",
        "path": "/api/a",
        "source_sha": REF,
        "evidence": [],
    }
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="disjoint"):
        validate_openapi_routes._assert_disjoint(
            {"public_operations": [shared], "internal_operations": [dict(shared)]}
        )
    # a spec-side operation carrying a non-OpenAPI method fails inside the
    # algebra even if it bypassed witness construction
    hostile_spec = {
        "CONNECT /api/a": {
            "operation_id": "CONNECT /api/a",
            "method": "CONNECT",
            "path": "/api/a",
            "source_sha": REF,
            "evidence": [],
        }
    }
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="non-OpenAPI"):
        validate_openapi_routes.build_route_set_algebra({}, hostile_spec, ("/api/v1/sme/",))
    # duplicate operation IDs inside one collection are rejected at sort time
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="duplicate"):
        validate_openapi_routes._sorted_operations([shared, dict(shared)])


def test_runtime_method_set_is_exact_including_connect_and_trace():
    assert validate_openapi_routes.RUNTIME_METHOD_SET == (
        "CONNECT",
        "DELETE",
        "GET",
        "HEAD",
        "OPTIONS",
        "PATCH",
        "POST",
        "PUT",
        "TRACE",
    )
    # every member is accepted as served evidence
    for method in validate_openapi_routes.RUNTIME_METHOD_SET:
        ops = _build([_op(method, "/api/x")])
        assert f"{method} /api/x" in ops
    # an alien verb fails closed, never silently coerced
    with pytest.raises(validate_openapi_routes.MethodAwareError):
        _build([_op("FETCH", "/api/x")])
    # a lowercase alias fails closed
    with pytest.raises(validate_openapi_routes.MethodAwareError):
        _build([_op("get", "/api/x")])


def test_openapi_method_set_is_exact_and_excludes_connect():
    assert validate_openapi_routes.OPENAPI_METHOD_SET == (
        "DELETE",
        "GET",
        "HEAD",
        "OPTIONS",
        "PATCH",
        "POST",
        "PUT",
        "TRACE",
    )
    assert "CONNECT" not in validate_openapi_routes.OPENAPI_METHOD_SET
    # a CONNECT witness on the spec side fails closed
    with pytest.raises(validate_openapi_routes.MethodAwareError):
        _build(
            [_op("CONNECT", "/api/x", evidence_type="openapi_operation_key")],
            universe=frozenset(validate_openapi_routes.OPENAPI_METHOD_SET),
        )


def test_connect_is_explicit_nonrepresentable_served_but_undeclared_debt(tmp_path: Path):
    collections = _algebra(
        [_op("CONNECT", "/api/tunnel"), _op("GET", "/api/tunnel")],
        [_op("GET", "/api/tunnel", evidence_type="openapi_operation_key")],
    )
    connects = [op for op in collections["served_but_undeclared"] if op["method"] == "CONNECT"]
    assert len(connects) == 1
    assert connects[0]["path"] == "/api/tunnel"
    assert connects[0]["non_representable_in_standard_openapi"] is True
    assert "CONNECT /api/tunnel" not in _ids(collections, "declared_and_served")
    # a spec that claims to declare CONNECT can never make it declared_and_served
    served = _build([_op("CONNECT", "/api/tunnel")])
    hostile_spec = {
        "CONNECT /api/tunnel": {
            "operation_id": "CONNECT /api/tunnel",
            "method": "CONNECT",
            "path": "/api/tunnel",
            "source_sha": REF,
            "evidence": [_op("CONNECT", "/api/tunnel")],
        }
    }
    with pytest.raises(validate_openapi_routes.MethodAwareError):
        validate_openapi_routes.build_route_set_algebra(served, hostile_spec, ("/api/v1/sme/",))
    # CONNECT is never inferred from spec files: the extractor ignores a
    # literal "connect" path-item key entirely.
    spec = tmp_path / "openapi.json"
    spec.write_text(
        json.dumps({"paths": {"/api/v1/tunnel": {"connect": {}, "get": {}}}}),
        encoding="utf-8",
    )
    witnesses = validate_openapi_routes.get_openapi_operation_witnesses(str(spec))
    assert {w["method"] for w in witnesses} == {"GET"}


def test_unresolved_exposure_remains_governed_debt():
    # version-form differences alone never manufacture ambiguity: the
    # unversioned wired literal aliases into the policy's /api/v1/ space and
    # both witnesses agree -> internal
    collections = _algebra(
        [
            _op("GET", "/api/v1/sme/dashboard"),
            _op("GET", "/api/sme/dashboard", evidence_type="wired_router_registration"),
        ],
        [],
    )
    assert "GET /api/sme/dashboard" in set(_ids(collections, "internal_operations"))
    # genuinely disagreeing witnesses (a v2 serving of a v1-internal family)
    # stay unresolved governed debt, never guessed either way
    collections = _algebra(
        [
            _op("GET", "/api/v1/sme/dashboard"),
            _op("GET", "/api/v2/sme/dashboard", evidence_type="wired_router_registration"),
        ],
        [],
    )
    target_id = "GET /api/sme/dashboard"
    assert target_id in set(_ids(collections, "unresolved_exposure"))
    assert target_id not in set(_ids(collections, "public_operations"))
    assert target_id not in set(_ids(collections, "internal_operations"))
    # unresolved operations still participate in served-side algebra
    assert target_id in set(_ids(collections, "served_operations"))


def test_legacy_missing_spec_cannot_double_count():
    collections = _algebra(
        [_op("GET", "/api/only-served")],
        [_op("DELETE", "/api/only-spec", evidence_type="openapi_operation_key")],
    )
    # the canonical missing-spec set is served_but_undeclared; no legacy
    # missing_spec key exists anywhere in the algebra output
    assert "missing_spec" not in collections
    plane_keys = set(collections.keys())
    assert "served_but_undeclared" in plane_keys


def test_method_aware_route_census_distinguishes_same_path_methods():
    ops = _build(
        [
            _op("GET", "/api/v1/debates/active"),
            _op("POST", "/api/v1/debates/active"),
            _op("DELETE", "/api/v1/debates/active"),
        ]
    )
    assert set(ops) == {
        "GET /api/debates/active",
        "POST /api/debates/active",
        "DELETE /api/debates/active",
    }
    # same path, distinct methods: three distinct operations, never merged
    assert len({op["path"] for op in ops.values()}) == 1


def test_explicit_head_and_options_are_not_inferred_from_get():
    ops = _build([_op("GET", "/api/thing")])
    assert "GET /api/thing" in ops
    assert "HEAD /api/thing" not in ops
    assert "OPTIONS /api/thing" not in ops
    # explicit witnesses are honored
    ops = _build([_op("HEAD", "/api/thing"), _op("OPTIONS", "/api/thing")])
    assert set(ops) == {"HEAD /api/thing", "OPTIONS /api/thing"}


def test_method_specific_route_maps_and_decorators_are_evidence(monkeypatch):
    endpoint = types.SimpleNamespace(path="/api/v1/deco/route", method="POST")

    class DummyHandler:
        ROUTES = [("PUT", "/api/v1/tuple/route"), "GET /api/v1/inline/route"]
        GET_ROUTES = ["/api/v1/map/route"]
        PATCH_ROUTES = ["/api/v1/map/route"]

        def deco(self):
            return None

    DummyHandler.deco._openapi = endpoint

    fake_registry = _fake_registry([("_dummy", DummyHandler)])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)

    witnesses, path_only = validate_openapi_routes.get_handler_metadata_operations()
    seen = {(w["method"], w["raw_path_literal"]) for w in witnesses}
    assert ("PUT", "/api/v1/tuple/route") in seen
    assert ("GET", "/api/v1/inline/route") in seen
    assert ("GET", "/api/v1/map/route") in seen
    assert ("PATCH", "/api/v1/map/route") in seen
    assert ("POST", "/api/v1/deco/route") in seen


def test_handler_path_presence_is_not_method_evidence(monkeypatch):
    class DummyHandler:
        ROUTES = ["/api/v1/pathonly/route"]

    fake_registry = _fake_registry([("_dummy", DummyHandler)])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)

    witnesses, path_only = validate_openapi_routes.get_handler_metadata_operations()
    assert witnesses == []
    assert "/api/v1/pathonly/route" in path_only
    # no method is ever fabricated for a bare path
    ops = _build(witnesses)
    assert ops == {}


def test_wildcard_prefix_is_not_operation_evidence(monkeypatch, tmp_path: Path):
    # wildcard handler metadata
    class DummyHandler:
        GET_ROUTES = ["/api/v1/files/*"]

    fake_registry = _fake_registry([("_dummy", DummyHandler)])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)
    witnesses, path_only = validate_openapi_routes.get_handler_metadata_operations()
    assert witnesses == []
    assert "/api/v1/files/*" in path_only
    # wildcard source literal
    src = tmp_path / "handler.py"
    src.write_text('X = "GET /api/v1/files/*"\n', encoding="utf-8")
    lits = validate_openapi_routes.get_handler_source_literal_operations(tmp_path)
    assert lits == []
    # exact literal still witnesses
    src.write_text('X = "GET /api/v1/files/list"\n', encoding="utf-8")
    lits = validate_openapi_routes.get_handler_source_literal_operations(tmp_path)
    assert [(w["method"], w["raw_path_literal"]) for w in lits] == [("GET", "/api/v1/files/list")]


def test_fstring_fragments_and_prose_substrings_are_never_witnesses(tmp_path: Path):
    src = tmp_path / "handler.py"
    src.write_text(
        "def h(debate_id):\n"
        '    usage = "  - GET /api/debates - List recent debates"\n'
        '    raise ValueError("POST /api/v1/x denied for this role")\n'
        '    return f"GET /api/v1/debates/{debate_id}/messages"\n',
        encoding="utf-8",
    )
    lits = validate_openapi_routes.get_handler_source_literal_operations(tmp_path)
    # prose containing an operation substring and truncated f-string fragments
    # never fabricate served operations
    assert lits == []
    # the exact whole-string dispatch-key form still witnesses
    src.write_text('KEY = "GET /api/v1/debates"\n', encoding="utf-8")
    lits = validate_openapi_routes.get_handler_source_literal_operations(tmp_path)
    assert [(w["method"], w["raw_path_literal"]) for w in lits] == [("GET", "/api/v1/debates")]
    # and no fragment of any f-string is ever yielded as a constant
    import ast as ast_module

    tree = ast_module.parse('def h(x):\n    return f"GET /api/v1/debates/{x}/messages"\n')
    assert list(validate_openapi_routes._iter_executable_string_constants(tree)) == []


def test_dict_route_metadata_is_explicit_method_evidence(monkeypatch):
    class DictHandler:
        ROUTES = {
            "/api/v1/accounting/expenses": ["GET", "POST"],
            "/api/v1/accounting/expenses/upload": ["POST"],
        }
        DYNAMIC_ROUTES = {
            "/api/v1/accounting/expenses/{expense_id}": ["GET", "PUT", "DELETE"],
        }

    monkeypatch.setitem(
        sys.modules,
        "aragora.server.handler_registry",
        _fake_registry([("_dict", DictHandler)]),
    )
    witnesses, path_only = validate_openapi_routes.get_handler_metadata_operations()
    seen = {(w["method"], w["raw_path_literal"]) for w in witnesses}
    assert ("GET", "/api/v1/accounting/expenses") in seen
    assert ("POST", "/api/v1/accounting/expenses") in seen
    assert ("POST", "/api/v1/accounting/expenses/upload") in seen
    assert ("GET", "/api/v1/accounting/expenses/{expense_id}") in seen
    assert ("PUT", "/api/v1/accounting/expenses/{expense_id}") in seen
    assert ("DELETE", "/api/v1/accounting/expenses/{expense_id}") in seen
    assert path_only == set()

    # a lowercase verb in the method list stays method-unresolved, not guessed
    class SloppyHandler:
        ROUTES = {"/api/v1/sloppy": ["get"]}

    monkeypatch.setitem(
        sys.modules,
        "aragora.server.handler_registry",
        _fake_registry([("_sloppy", SloppyHandler)]),
    )
    witnesses, path_only = validate_openapi_routes.get_handler_metadata_operations()
    assert witnesses == []
    assert "/api/v1/sloppy" in path_only


def test_unrecognized_route_metadata_shape_fails_closed(monkeypatch):
    # a dict value that is not a method list is unproven served surface
    class BadValueHandler:
        ROUTES = {"/api/v1/bad": "GET"}

    monkeypatch.setitem(
        sys.modules,
        "aragora.server.handler_registry",
        _fake_registry([("_bad", BadValueHandler)]),
    )
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="explicit"):
        validate_openapi_routes.get_handler_metadata_operations()

    # an alien entry shape inside list ROUTES is rejected, never dropped
    class AlienEntryHandler:
        ROUTES = [{"path": "/api/v1/alien"}]

    monkeypatch.setitem(
        sys.modules,
        "aragora.server.handler_registry",
        _fake_registry([("_alien", AlienEntryHandler)]),
    )
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="unrecognized"):
        validate_openapi_routes.get_handler_metadata_operations()

    # an alien ROUTES container type is rejected
    class AlienContainerHandler:
        ROUTES = 42

    monkeypatch.setitem(
        sys.modules,
        "aragora.server.handler_registry",
        _fake_registry([("_container", AlienContainerHandler)]),
    )
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="container"):
        validate_openapi_routes.get_handler_metadata_operations()


def test_literal_witnesses_are_scoped_to_active_handler_source_files(tmp_path: Path):
    active_src = tmp_path / "active_handler.py"
    active_src.write_text('KEY = "GET /api/v1/active/literal"\n', encoding="utf-8")
    inactive_src = tmp_path / "inactive_handler.py"
    inactive_src.write_text('KEY = "POST /api/v1/inactive/literal"\n', encoding="utf-8")

    # unscoped: both literals witness (legacy behavior when no census given)
    unscoped = validate_openapi_routes.get_handler_source_literal_operations(tmp_path)
    assert {(w["method"], w["raw_path_literal"]) for w in unscoped} == {
        ("GET", "/api/v1/active/literal"),
        ("POST", "/api/v1/inactive/literal"),
    }
    # scoped to the active-tier handler file census: literals in files that
    # host no active handler are never served evidence (round 3: optional
    # AP/AR dispatch literals must not count under a core-only tier filter)
    allowed = frozenset({validate_openapi_routes._relative_source_path(str(active_src.resolve()))})
    scoped = validate_openapi_routes.get_handler_source_literal_operations(
        tmp_path, allowed_files=allowed
    )
    assert [(w["method"], w["raw_path_literal"]) for w in scoped] == [
        ("GET", "/api/v1/active/literal")
    ]


def test_active_handler_source_files_cover_reexported_method_code(monkeypatch):
    class ActiveHandler:
        GET_ROUTES = ["/api/v1/active/route"]

        def handle(self):
            return None

    monkeypatch.setitem(
        sys.modules,
        "aragora.server.handler_registry",
        _fake_registry([("_active", ActiveHandler)]),
    )
    files = validate_openapi_routes._active_handler_source_files()
    # the census includes the file defining the class's method code
    assert any(path.endswith("test_validate_openapi_routes.py") for path in files)


def test_active_handler_file_census_walks_the_full_mro(monkeypatch):
    # inherited base/mixin methods dispatch for the handler, so base-class
    # modules are served surface (round 4: own-__dict__-only census dropped
    # base modules and their literals)
    base = type("SecureBase", (), {"authorize": lambda self: None})
    handler = type("ChildHandler", (base,), {"GET_ROUTES": ["/api/v1/child/route"]})
    monkeypatch.setitem(
        sys.modules,
        "aragora.server.handler_registry",
        _fake_registry([("_child", handler)]),
    )
    files = validate_openapi_routes._active_handler_source_files()
    base_file = validate_openapi_routes._relative_source_path(
        str(Path(base.authorize.__code__.co_filename).resolve())
    )
    assert base_file in files


def test_handler_class_defining_resolve_method_is_not_invoked_as_deferred_ref(monkeypatch):
    # a handler CLASS with a `resolve` instance method is not a deferred-import
    # handle; invoking it unbound would raise TypeError and kill the plane
    class ResolverHandler:
        GET_ROUTES = ["/api/v1/resolver/route"]

        def resolve(self):
            return "not a handler class"

    monkeypatch.setitem(
        sys.modules,
        "aragora.server.handler_registry",
        _fake_registry([("_resolver", ResolverHandler)]),
    )
    classes = list(validate_openapi_routes._iter_registry_handler_classes())
    assert classes == [ResolverHandler]


def test_fstring_folding_drops_unsound_bindings(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    handler = tmp_path / "aragora" / "server" / "handlers" / "wired.py"
    registration.parent.mkdir(parents=True)
    handler.parent.mkdir(parents=True)
    registration.write_text(
        "from aragora.server.handlers.wired import register_routes\nregister_routes(app)\n",
        encoding="utf-8",
    )
    # round 6: each shape below over-claimed operations that never register
    handler.write_text(
        """
def register_routes(router):
    # (a) rebinding in the body invalidates the fold
    for base in ("/api/a", "/api/b"):
        base = base + "/v1"
        router.add_get(f"{base}/rebound", object())
    # (b) a nested NON-literal loop shadows the outer binding
    for base in ("/api/c", "/api/d"):
        for base in compute():
            router.add_get(f"{base}/shadowed", object())
    # (c) conditional registration may filter values
    for base in ("/api/e", "/api/f"):
        if base == "/api/e":
            router.add_get(f"{base}/guarded", object())
    # constant paths inside conditionals still count individually
    for base in ("/api/g",):
        if flag:
            router.add_get("/api/v1/const-in-if", object())
    # a nested LITERAL loop rebinds to its own exact values
    for base in ("/api/outer",):
        for base in ("/api/x", "/api/y"):
            router.add_get(f"{base}/inner", object())
    # straight-line folding remains exact
    for base in ("/api/h", "/api/v1/h"):
        router.add_route("GET", f"{base}/log", object())
""".lstrip(),
        encoding="utf-8",
    )
    operations = validate_openapi_routes.get_wired_function_operations(
        registration, tmp_path, extended=True
    )
    assert {(op["method"], op["path"]) for op in operations} == {
        ("GET", "/api/v1/const-in-if"),
        ("GET", "/api/x/inner"),
        ("GET", "/api/y/inner"),
        ("GET", "/api/h/log"),
        ("GET", "/api/v1/h/log"),
    }


def test_unparseable_server_file_fails_closed_in_scoped_literal_scan(tmp_path: Path):
    good = tmp_path / "good.py"
    good.write_text('KEY = "GET /api/v1/good"\n', encoding="utf-8")
    broken = tmp_path / "broken.py"
    broken.write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="cannot parse"):
        validate_openapi_routes.get_handler_source_literal_operations(tmp_path)


def test_legacy_wired_routes_keep_original_narrow_semantics(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    handler = tmp_path / "aragora" / "server" / "handlers" / "wired.py"
    registration.parent.mkdir(parents=True)
    handler.parent.mkdir(parents=True)
    registration.write_text(
        "from aragora.server.handlers.wired import register_routes\nregister_routes(app)\n",
        encoding="utf-8",
    )
    handler.write_text(
        """
def register_routes(router):
    router.add_route("POST", "/api/v1/direct/pause", object())
    router.add_get("/api/v1/direct/state", object())
    for base in ("/api/a", "/api/v1/a"):
        router.add_route("GET", f"{base}/log", object())
""".lstrip(),
        encoding="utf-8",
    )
    # legacy narrow semantics: no add_route, no direct-router receiver, no
    # f-string folding -> the pinned baseline's input set cannot re-scope
    legacy = validate_openapi_routes.get_wired_function_routes(registration, tmp_path)
    assert legacy == set()
    # extended method-aware semantics: all three exact evidence forms count
    extended_ops = validate_openapi_routes.get_wired_function_operations(
        registration, tmp_path, extended=True
    )
    assert {(op["method"], op["path"]) for op in extended_ops} == {
        ("POST", "/api/v1/direct/pause"),
        ("GET", "/api/v1/direct/state"),
        ("GET", "/api/a/log"),
        ("GET", "/api/v1/a/log"),
    }


def test_attribute_called_class_registrars_count_with_literal_default_prefix(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    handler = tmp_path / "aragora" / "server" / "handlers" / "auto.py"
    registration.parent.mkdir(parents=True)
    handler.parent.mkdir(parents=True)
    # round 7: the autonomous handlers register via Handler.register_routes(app)
    registration.write_text(
        """
from aragora.server.handlers.auto import AlertHandler, OverriddenHandler, ComputedHandler

def install(app):
    AlertHandler.register_routes(app)
    OverriddenHandler.register_routes(app, "/api/v1/custom")
    ComputedHandler.register_routes(app, compute_prefix())
""".lstrip(),
        encoding="utf-8",
    )
    handler.write_text(
        """
class AlertHandler:
    @staticmethod
    def register_routes(app, prefix="/api/v1/auto"):
        app.router.add_get(f"{prefix}/alerts/active", AlertHandler.list_active)
        app.router.add_post(f"{prefix}/alerts/{alert_id}/ack", AlertHandler.ack)

class OverriddenHandler:
    @classmethod
    def register_routes(cls, app, prefix="/api/v1/never"):
        app.router.add_get(f"{prefix}/overridden", cls.get)

class ComputedHandler:
    @staticmethod
    def register_routes(app, prefix="/api/v1/unused"):
        app.router.add_get(f"{prefix}/computed", ComputedHandler.get)
        app.router.add_get("/api/v1/computed/constant", ComputedHandler.get_const)
""".lstrip(),
        encoding="utf-8",
    )
    operations = validate_openapi_routes.get_wired_function_operations(
        registration, tmp_path, extended=True
    )
    assert {(op["method"], op["path"]) for op in operations} == {
        # literal default folds; the {alert_id} interpolation is NOT a bound
        # name so that path stays unverified
        ("GET", "/api/v1/auto/alerts/active"),
        # explicit literal call-site argument overrides the default
        ("GET", "/api/v1/custom/overridden"),
        # computed prefix: f-string stays unverified, constant still counts
        ("GET", "/api/v1/computed/constant"),
    }
    symbols = {op["symbol"] for op in operations}
    assert "aragora.server.handlers.auto:AlertHandler.register_routes" in symbols
    # class registrars are extended-plane evidence only: the legacy pinned
    # baseline never re-scopes
    assert validate_openapi_routes.get_wired_function_routes(registration, tmp_path) == set()


def test_loop_flow_escapes_invalidate_fstring_folding(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    handler = tmp_path / "aragora" / "server" / "handlers" / "wired.py"
    registration.parent.mkdir(parents=True)
    handler.parent.mkdir(parents=True)
    registration.write_text(
        "from aragora.server.handlers.wired import register_routes\nregister_routes(app)\n",
        encoding="utf-8",
    )
    # round 8: continue/break/return/raise can skip iterations, so a fold
    # would claim registrations that never execute
    handler.write_text(
        """
def register_routes(router):
    for name in ("/api/a", "/api/b"):
        if not enabled(name):
            continue
        router.add_get(f"{name}/filtered", object())
    for name in ("/api/c", "/api/d"):
        router.add_get(f"{name}/broken", object())
        break
    for name in ("/api/e", "/api/f"):
        try:
            check(name)
        except ValueError:
            raise
        router.add_get(f"{name}/raised", object())
    # a nested def containing return does NOT invalidate the fold
    for name in ("/api/g",):
        def helper():
            return None
        router.add_get(f"{name}/kept", object())
""".lstrip(),
        encoding="utf-8",
    )
    operations = validate_openapi_routes.get_wired_function_operations(
        registration, tmp_path, extended=True
    )
    assert {(op["method"], op["path"]) for op in operations} == {("GET", "/api/g/kept")}


def test_add_routes_route_tables_count_with_exact_literals(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    handler = tmp_path / "aragora" / "server" / "handlers" / "wired.py"
    registration.parent.mkdir(parents=True)
    handler.parent.mkdir(parents=True)
    registration.write_text(
        "from aragora.server.handlers.wired import register_routes\nregister_routes(app)\n",
        encoding="utf-8",
    )
    # round 12: aiohttp route tables (threat-intel registers exactly this way)
    handler.write_text(
        """
from aiohttp import web

def register_routes(app):
    handler = object()
    routes = [
        web.post("/api/v1/threat/url", handler),
        web.get("/api/v1/threat/status", handler),
        web.route("DELETE", "/api/v1/threat/cache", handler),
        web.route(compute_method(), "/api/v1/threat/computed", handler),
    ]
    app.router.add_routes(routes)
    logger.info("Registered %s routes", len(routes))
    app.router.add_routes([web.get("/api/v1/inline", handler)])
""".lstrip(),
        encoding="utf-8",
    )
    operations = validate_openapi_routes.get_wired_function_operations(
        registration, tmp_path, extended=True
    )
    # the computed-method entry stays unverified; everything literal counts,
    # and a len(...) logging read does not disqualify the table
    assert {(op["method"], op["path"]) for op in operations} == {
        ("POST", "/api/v1/threat/url"),
        ("GET", "/api/v1/threat/status"),
        ("DELETE", "/api/v1/threat/cache"),
        ("GET", "/api/v1/inline"),
    }
    # add_routes tables are extended evidence only
    assert validate_openapi_routes.get_wired_function_routes(registration, tmp_path) == set()


def test_mutated_route_tables_stay_unverified(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    handler = tmp_path / "aragora" / "server" / "handlers" / "wired.py"
    registration.parent.mkdir(parents=True)
    handler.parent.mkdir(parents=True)
    registration.write_text(
        "from aragora.server.handlers.wired import register_routes\nregister_routes(app)\n",
        encoding="utf-8",
    )
    # a table that is appended to, reassigned, or passed to an arbitrary
    # callee could register different entries than its literal — unverified
    handler.write_text(
        """
from aiohttp import web

def register_routes(app):
    appended = [web.get("/api/v1/base", object())]
    appended.append(web.get("/api/v1/appended", object()))
    app.router.add_routes(appended)
    reassigned = [web.get("/api/v1/first", object())]
    reassigned = [web.get("/api/v1/second", object())]
    app.router.add_routes(reassigned)
    escaped = [web.get("/api/v1/mut", object())]
    mutate(escaped)
    app.router.add_routes(escaped)
""".lstrip(),
        encoding="utf-8",
    )
    assert (
        validate_openapi_routes.get_wired_function_operations(registration, tmp_path, extended=True)
        == []
    )


def test_non_dominating_route_table_assignments_stay_unverified(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    handler = tmp_path / "aragora" / "server" / "handlers" / "wired.py"
    registration.parent.mkdir(parents=True)
    handler.parent.mkdir(parents=True)
    registration.write_text(
        "from aragora.server.handlers.wired import register_routes\nregister_routes(app)\n",
        encoding="utf-8",
    )
    # round 13: a conditionally-executed or post-call assignment does not
    # prove what add_routes registers — only a straight-line top-level
    # assignment preceding the call dominates it
    handler.write_text(
        """
from aiohttp import web

def register_routes(app):
    if enabled:
        conditional = [web.get("/api/v1/conditional", object())]
    app.router.add_routes(conditional)
    try:
        tried = [web.get("/api/v1/tried", object())]
    except Exception:
        pass
    app.router.add_routes(tried)

def register_late(app):
    app.router.add_routes(late)
    late = [web.get("/api/v1/late", object())]
""".lstrip(),
        encoding="utf-8",
    )
    assert (
        validate_openapi_routes.get_wired_function_operations(registration, tmp_path, extended=True)
        == []
    )


def test_match_capture_rebinding_invalidates_fstring_folding(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    handler = tmp_path / "aragora" / "server" / "handlers" / "wired.py"
    registration.parent.mkdir(parents=True)
    handler.parent.mkdir(parents=True)
    registration.write_text(
        "from aragora.server.handlers.wired import register_routes\nregister_routes(app)\n",
        encoding="utf-8",
    )
    # round 11: match-statement captures (MatchAs/MatchStar/MatchMapping.rest)
    # store plain-str names; the rebound-name census must see them
    handler.write_text(
        """
def register_routes(router):
    for base in ("/api/a", "/api/b"):
        match compute():
            case str() as base:
                pass
        router.add_get(f"{base}/x", object())
""".lstrip(),
        encoding="utf-8",
    )
    assert (
        validate_openapi_routes.get_wired_function_operations(registration, tmp_path, extended=True)
        == []
    )


def test_module_attribute_registrar_resolves_to_module_function(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    package = tmp_path / "aragora" / "server" / "handlers" / "grouped"
    registration.parent.mkdir(parents=True)
    package.mkdir(parents=True)
    # round 8 P3: ``from ... import module; module.register_all(app)`` is an
    # attribute call whose receiver is a MODULE, not a class
    registration.write_text(
        "from aragora.server.handlers import grouped\ngrouped.register_all(app)\n",
        encoding="utf-8",
    )
    (package / "__init__.py").write_text(
        'def register_all(app):\n    app.router.add_get("/api/v1/grouped", object())\n',
        encoding="utf-8",
    )
    operations = validate_openapi_routes.get_wired_function_operations(
        registration, tmp_path, extended=True
    )
    assert [(op["method"], op["path"]) for op in operations] == [("GET", "/api/v1/grouped")]


def test_class_registrar_with_unknown_decorator_stays_unverified(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    handler = tmp_path / "aragora" / "server" / "handlers" / "auto.py"
    registration.parent.mkdir(parents=True)
    handler.parent.mkdir(parents=True)
    registration.write_text(
        "from aragora.server.handlers.auto import WrappedHandler\nWrappedHandler.register_routes(app)\n",
        encoding="utf-8",
    )
    # an unrecognized decorator changes call semantics unprovably; the
    # registrations must stay unverified rather than fabricated
    handler.write_text(
        """
class WrappedHandler:
    @some_wrapper
    def register_routes(app):
        app.router.add_get("/api/v1/wrapped", WrappedHandler.get)
""".lstrip(),
        encoding="utf-8",
    )
    operations = validate_openapi_routes.get_wired_function_operations(
        registration, tmp_path, extended=True
    )
    assert operations == []


def test_unreachable_attribute_registrars_stay_unverified_without_aborting(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    handler = tmp_path / "aragora" / "server" / "handlers" / "auto.py"
    registration.parent.mkdir(parents=True)
    handler.parent.mkdir(parents=True)
    # round 9: attribute registrars outside static reach (missing class,
    # non-local base, TYPE_CHECKING-guarded dead code) must SKIP — leaving
    # their registrations unverified surfaces more drift, while aborting
    # would hard-fail the validator on dead or third-party code. The
    # name-called registrar alongside them still counts.
    registration.write_text(
        """
from typing import TYPE_CHECKING
from aragora.server.handlers.auto import GhostHandler, ExternalChild, register_real

if TYPE_CHECKING:
    from aragora.server.handlers.auto import DeadHandler
    DeadHandler.register_routes(app)

def install(app):
    GhostHandler.register_routes(app)
    ExternalChild.register_routes(app)
    register_real(app)
""".lstrip(),
        encoding="utf-8",
    )
    handler.write_text(
        """
from aiohttp.web import View

class ExternalChild(View):
    pass

def register_real(app):
    app.router.add_get("/api/v1/real", object())
""".lstrip(),
        encoding="utf-8",
    )
    operations = validate_openapi_routes.get_wired_function_operations(
        registration, tmp_path, extended=True
    )
    assert [(op["method"], op["path"]) for op in operations] == [("GET", "/api/v1/real")]


def test_diamond_hierarchy_never_aborts_the_scan(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    handler = tmp_path / "aragora" / "server" / "handlers" / "wired.py"
    registration.parent.mkdir(parents=True)
    handler.parent.mkdir(parents=True)
    registration.write_text(
        "from aragora.server.handlers.wired import C\nC.register_routes(app)\n",
        encoding="utf-8",
    )
    # round 10: a diamond (C -> A,B -> Base) revisits Base; the visited-key
    # guard must report "unproven" instead of raising a cyclic error
    handler.write_text(
        """
class Base:
    pass

class A(Base):
    pass

class B(Base):
    pass

class C(A, B):
    pass
""".lstrip(),
        encoding="utf-8",
    )
    assert (
        validate_openapi_routes.get_wired_function_operations(registration, tmp_path, extended=True)
        == []
    )
    # when the shared base DOES define the registrar, it resolves normally
    handler.write_text(
        """
class Base:
    @staticmethod
    def register_routes(app, prefix="/api/v1/diamond"):
        app.router.add_get(f"{prefix}/route", object())

class A(Base):
    pass

class B(Base):
    pass

class C(A, B):
    pass
""".lstrip(),
        encoding="utf-8",
    )
    operations = validate_openapi_routes.get_wired_function_operations(
        registration, tmp_path, extended=True
    )
    assert [(op["method"], op["path"]) for op in operations] == [("GET", "/api/v1/diamond/route")]


def test_inherited_class_registrar_resolves_through_local_bases(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    handler = tmp_path / "aragora" / "server" / "handlers" / "auto.py"
    base = tmp_path / "aragora" / "server" / "handlers" / "base.py"
    registration.parent.mkdir(parents=True)
    handler.parent.mkdir(parents=True)
    registration.write_text(
        "from aragora.server.handlers.auto import ChildHandler\nChildHandler.register_routes(app)\n",
        encoding="utf-8",
    )
    handler.write_text(
        """
from aragora.server.handlers.base import BaseReg

class ChildHandler(BaseReg):
    pass
""".lstrip(),
        encoding="utf-8",
    )
    base.write_text(
        """
class BaseReg:
    @staticmethod
    def register_routes(app, prefix="/api/v1/child"):
        app.router.add_get(f"{prefix}/inherited", object())
""".lstrip(),
        encoding="utf-8",
    )
    operations = validate_openapi_routes.get_wired_function_operations(
        registration, tmp_path, extended=True
    )
    assert [(op["method"], op["path"]) for op in operations] == [("GET", "/api/v1/child/inherited")]


def test_direct_router_receiver_requires_router_parameter_name(tmp_path: Path):
    registration = tmp_path / "aragora" / "server" / "stream" / "registration.py"
    handler = tmp_path / "aragora" / "server" / "handlers" / "wired.py"
    registration.parent.mkdir(parents=True)
    handler.parent.mkdir(parents=True)
    registration.write_text(
        "from aragora.server.handlers.wired import register_routes\nregister_routes(app)\n",
        encoding="utf-8",
    )
    # first parameter is NOT named "router": a bare <first-arg>.add_get(...)
    # on an arbitrary object with unrelated add_* helpers is never evidence
    handler.write_text(
        'def register_routes(collector):\n    collector.add_get("/api/v1/collected", object())\n',
        encoding="utf-8",
    )
    extended_ops = validate_openapi_routes.get_wired_function_operations(
        registration, tmp_path, extended=True
    )
    assert extended_ops == []
    # app.router.add_* still counts regardless of the first parameter's name
    handler.write_text(
        'def register_routes(app):\n    app.router.add_get("/api/v1/approuted", object())\n',
        encoding="utf-8",
    )
    extended_ops = validate_openapi_routes.get_wired_function_operations(
        registration, tmp_path, extended=True
    )
    assert [(op["method"], op["path"]) for op in extended_ops] == [("GET", "/api/v1/approuted")]


def test_served_census_mirrors_server_active_tier_filter(monkeypatch):
    class ActiveHandler:
        GET_ROUTES = ["/api/v1/active/route"]

    class InactiveHandler:
        GET_ROUTES = ["/api/v1/inactive/route"]

    tiers = {"_active": "core", "_inactive": "enterprise"}

    def filter_registry_by_tier(registry, active_tiers=None):
        return [(name, ref) for name, ref in registry if tiers[name] in active_tiers]

    fake = types.SimpleNamespace(
        HANDLER_REGISTRY=[("_active", ActiveHandler), ("_inactive", InactiveHandler)],
        get_active_tiers=lambda: {"core", "extended", "optional"},
        filter_registry_by_tier=filter_registry_by_tier,
    )
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake)
    witnesses, _path_only = validate_openapi_routes.get_handler_metadata_operations()
    paths = {w["raw_path_literal"] for w in witnesses}
    # the inactive-tier handler is genuinely not served, so it never enters
    # the served census; the active-tier handler does
    assert "/api/v1/active/route" in paths
    assert "/api/v1/inactive/route" not in paths
    # if the registry stops exposing the tier surface, the census fails closed
    broken = types.SimpleNamespace(
        HANDLER_REGISTRY=[("_active", ActiveHandler)],
    )
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", broken)
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="mirror"):
        validate_openapi_routes.get_handler_metadata_operations()


def test_internal_prefix_matching_is_segment_bounded():
    collections = _algebra(
        [_op("GET", "/api/v1/sme/dashboard"), _op("GET", "/api/v1/smear")],
        [],
        prefixes=("/api/v1/sme/",),
    )
    internal = set(_ids(collections, "internal_operations"))
    public = set(_ids(collections, "public_operations"))
    assert "GET /api/sme/dashboard" in internal
    assert "GET /api/smear" in public


def test_query_trailing_slash_version_and_parameter_normalization_align():
    ops = _build(
        [
            _op("GET", "/api/v1/debates/{debate_id}/"),
            _op("GET", "/api/v2/debates/:id?verbose=1"),
            _op("GET", "/api/debates/{param}"),
        ]
    )
    # all three collapse to the same canonical operation via the single
    # normalization authority (scripts/sdk_path_normalize.py)
    assert set(ops) == {"GET /api/debates/{param}"}
    from scripts.sdk_path_normalize import normalize_sdk_path

    assert normalize_sdk_path("/api/v1/debates/{debate_id}/") == "/api/debates/{param}"


def test_openapi_non_method_path_keys_are_ignored(tmp_path: Path):
    spec = tmp_path / "openapi.json"
    spec.write_text(
        json.dumps(
            {
                "paths": {
                    "/api/v1/thing": {
                        "get": {},
                        "parameters": [{"name": "x"}],
                        "summary": "text",
                        "description": "text",
                        "servers": [],
                        "x-internal": True,
                        "GET": {},
                        "connect": {},
                        "fetch": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    witnesses = validate_openapi_routes.get_openapi_operation_witnesses(str(spec))
    assert [(w["method"], w["operation_key"]) for w in witnesses] == [("GET", "get")]


def test_missing_primary_spec_fails_closed_never_an_empty_spec_plane(tmp_path: Path):
    missing = tmp_path / "definitely" / "not" / "here.json"
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="not found"):
        validate_openapi_routes.get_openapi_operation_witnesses(str(missing))
    # an absent optional *_generated sibling remains fine
    primary = tmp_path / "openapi.json"
    primary.write_text(json.dumps({"paths": {"/api/v1/x": {"get": {}}}}), encoding="utf-8")
    witnesses = validate_openapi_routes.get_openapi_operation_witnesses(str(primary))
    assert [(w["method"], w["raw_path_literal"]) for w in witnesses] == [("GET", "/api/v1/x")]


def test_autogenerated_placeholder_cannot_retire_drift(tmp_path: Path):
    primary = tmp_path / "openapi.json"
    primary.write_text(json.dumps({"paths": {}}), encoding="utf-8")
    generated = tmp_path / "openapi_generated.json"
    generated.write_text(
        json.dumps({"paths": {"/api/v1/ghost": {"get": {}}, "/api/v1/real": {"get": {}}}}),
        encoding="utf-8",
    )
    witnesses = validate_openapi_routes.get_openapi_operation_witnesses(str(primary))
    assert all(w["autogenerated"] for w in witnesses)
    spec_all = _build(witnesses, universe=frozenset(validate_openapi_routes.OPENAPI_METHOD_SET))
    served = _build([_op("GET", "/api/v1/real")])
    admitted = validate_openapi_routes._admit_spec_operations(spec_all, served)
    # the autogenerated-only ghost cannot enter the spec plane (it would
    # otherwise retire served-but-undeclared drift for free)...
    assert "GET /api/ghost" not in admitted
    # ...while the independently-served path is admitted
    assert "GET /api/real" in admitted


def test_incomplete_or_conflicting_operation_metadata_is_retained_as_drift(monkeypatch):
    bad_endpoint = types.SimpleNamespace(path="/api/v1/deco/bad", method="fetch")
    missing_endpoint = types.SimpleNamespace(path="/api/v1/deco/missing")

    class DummyHandler:
        ROUTES = [("FETCH", "/api/v1/alien"), "SOMETHING /api/v1/conflicted"]

        def bad(self):
            return None

        def missing(self):
            return None

    DummyHandler.bad._openapi = bad_endpoint
    DummyHandler.missing._openapi = missing_endpoint

    fake_registry = _fake_registry([("_dummy", DummyHandler)])
    monkeypatch.setitem(sys.modules, "aragora.server.handler_registry", fake_registry)

    witnesses, path_only = validate_openapi_routes.get_handler_metadata_operations()
    assert witnesses == []
    assert "/api/v1/alien" in path_only
    assert "/api/v1/conflicted" in path_only
    assert "/api/v1/deco/bad" in path_only
    assert "/api/v1/deco/missing" in path_only


def test_canonical_normalization_alignment_across_routes_sdk_and_inventory():
    import scripts.check_sdk_parity as check_sdk_parity
    from scripts.sdk_path_normalize import normalize_sdk_path

    samples = [
        "/api/v1/debates/{debate_id}/",
        "/api/v2/thing/:id?x=1",
        "/api/api-keys",
        "/API/V1/UPPER",
    ]
    for sample in samples:
        canonical = normalize_sdk_path(sample)
        # parity checker delegates to the same authority
        assert check_sdk_parity.normalize_route(sample) == canonical
        # the method-aware plane uses the same authority for operation paths
        ops = _build([_op("GET", sample)])
        assert set(ops) == {f"GET {canonical}"}
    # every ratified projection edge binds its operation ID exactly as the
    # plane constructs IDs, and live reconciliation maps historical edge paths
    # through the same single authority (the ratified /api/api-keys edges
    # alias to /api/auth/api-keys under the evolved live normalizer — the
    # projection identity is immutable while comparison stays canonical)
    projection = validate_openapi_routes.load_operation_projection()
    for record in projection["route_records"]:
        for edge in record["operation_edges"]:
            assert edge["normalized_operation"] == validate_openapi_routes._operation_id(
                edge["method"], edge["normalized_path"]
            )
            live_path = normalize_sdk_path(edge["normalized_path"])
            assert normalize_sdk_path(live_path) == live_path
    # the plane's output binding carries the exact live authority bytes' digest
    binding = validate_openapi_routes.path_normalization_binding()
    authority = Path(validate_openapi_routes.__file__).parent / "sdk_path_normalize.py"
    assert binding["authority_path"] == "scripts/sdk_path_normalize.py"
    assert binding["authority_sha256"] == hashlib.sha256(authority.read_bytes()).hexdigest()
    assert binding["schema"] == "sdk-path-normalize-v1"
    assert binding["version"] == 1


# ---------------------------------------------------------------------------
# VAL-CDG-011: ratified operation projection binding
# ---------------------------------------------------------------------------

ROUTE_CATS = ("routes_missing_in_spec", "routes_orphaned_in_spec", "sdk_missing_from_both")


@pytest.fixture(scope="module")
def ratified_cohort():
    inventory = json.loads(
        validate_openapi_routes._DEFAULT_INVENTORY_PATH.read_text(encoding="utf-8")
    )
    return inventory["accepted_authority"]["canonical_artifacts"]["original_cohort"]


def _write_cohort(tmp_path: Path, cohort: dict) -> Path:
    target = tmp_path / "inventory.json"
    target.write_text(
        json.dumps({"accepted_authority": {"canonical_artifacts": {"original_cohort": cohort}}}),
        encoding="utf-8",
    )
    return target


def _rehash_route_projection(cohort: dict) -> str:
    projection = cohort["operation_projection"]
    for record in projection["records"]:
        body = {k: v for k, v in record.items() if k != "record_sha256"}
        record["record_sha256"] = validate_openapi_routes._sha256_hex(
            validate_openapi_routes._canonical_json_bytes(body)
        )
    return validate_openapi_routes._sha256_hex(
        validate_openapi_routes._canonical_json_bytes(
            {
                "record_sha256_values": sorted(r["record_sha256"] for r in projection["records"]),
                "schema": "cdg-operation-projection-record-digest-set-v1",
            }
        )
    )


def _route_records(cohort: dict) -> list[dict]:
    return [r for r in cohort["operation_projection"]["records"] if r["category"] in ROUTE_CATS]


def test_operation_projection_schema_version_and_digest_are_bound(ratified_cohort, tmp_path: Path):
    projection = validate_openapi_routes.load_operation_projection()
    assert projection["schema"] == "cdg-operation-projection-v1"
    assert projection["schema_version"] == 1
    descriptor = {
        "one_to_many_rule": ratified_cohort["operation_projection"]["one_to_many_rule"],
        "record_digest_encoding": ratified_cohort["operation_projection"]["record_digest_encoding"],
        "schema": "cdg-operation-projection-v1",
        "schema_version": 1,
    }
    assert projection["schema_sha256"] == validate_openapi_routes._sha256_hex(
        validate_openapi_routes._canonical_json_bytes(descriptor)
    )
    assert (
        projection["original_record_id_set_sha256"]
        == validate_openapi_routes.ORIGINAL_RECORD_ID_SET_SHA256
    )
    assert (
        projection["record_digest_set_sha256"]
        == validate_openapi_routes.PROJECTION_RECORD_DIGEST_SET_SHA256
    )
    # hostile: a renamed projection schema fails closed
    hostile = copy.deepcopy(ratified_cohort)
    hostile["operation_projection"]["schema"] = "cdg-operation-projection-v2"
    with pytest.raises(validate_openapi_routes.MethodAwareError):
        validate_openapi_routes.load_operation_projection(_write_cohort(tmp_path, hostile))


def test_route_category_keys_match_exactly_including_zero_counts(monkeypatch):
    projection = validate_openapi_routes.load_operation_projection()
    assert projection["route_category_counts"] == {
        "routes_missing_in_spec": 11,
        "routes_orphaned_in_spec": 17,
        "sdk_missing_from_both": 29,
    }
    assert sorted(validate_openapi_routes.ROUTE_CATEGORY_SELECTION) == sorted(ROUTE_CATS)
    # exact key equality: a phantom zero-count category is a key mismatch
    # against the ratified counts, not a tolerated zero
    monkeypatch.setattr(
        validate_openapi_routes,
        "ROUTE_CATEGORY_SELECTION",
        {
            **validate_openapi_routes.ROUTE_CATEGORY_SELECTION,
            "routes_phantom": {
                "source_manifest": "scripts/baselines/phantom.json",
                "source_json_key": "phantom",
                "selection_rule": "phantom",
            },
        },
    )
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="category counts"):
        validate_openapi_routes.load_operation_projection()
    monkeypatch.undo()
    # and a dropped category key is equally fatal
    monkeypatch.setattr(
        validate_openapi_routes,
        "ROUTE_CATEGORY_SELECTION",
        {
            key: value
            for key, value in validate_openapi_routes.ROUTE_CATEGORY_SELECTION.items()
            if key != "sdk_missing_from_both"
        },
    )
    with pytest.raises(validate_openapi_routes.MethodAwareError):
        validate_openapi_routes.load_operation_projection()


def test_source_operation_sets_are_exclusive_and_exhaustive(
    ratified_cohort, tmp_path: Path, monkeypatch
):
    selection = validate_openapi_routes.ROUTE_CATEGORY_SELECTION
    # one exclusive source set and one deterministic rule per category
    pairs = {(spec["source_manifest"], spec["source_json_key"]) for spec in selection.values()}
    assert len(pairs) == len(selection) == 3
    for spec in selection.values():
        assert spec["selection_rule"]
    # exhaustive over route-governance memberships: every route/parity record
    # belongs to exactly one named category and the counts partition all 57
    records = _route_records(ratified_cohort)
    assert len(records) == 57
    assert {r["category"] for r in records} == set(selection)
    assert sum(validate_openapi_routes.ROUTE_CATEGORY_COUNTS.values()) == 57
    # the ratified artifact's own source manifests agree with the schema
    originals = {r["original_record_id"]: r for r in ratified_cohort["original_records"]}
    for record in records:
        original = originals[record["original_record_id"]]
        named = selection[record["category"]]
        assert original["source_manifest"]["path"] == named["source_manifest"]
        assert original["source_json_key"] == named["source_json_key"]
    # hostile: two memberships claiming the same normalized path violate
    # source-set exclusivity and fail closed
    hostile = copy.deepcopy(ratified_cohort)
    hostile_routes = _route_records(hostile)
    singles = [r for r in hostile_routes if len(r["operation_edges"]) == 1]
    victim, donor = singles[0], singles[1]
    donor_path = donor["operation_edges"][0]["normalized_path"]
    edge = victim["operation_edges"][0]
    edge["normalized_path"] = donor_path
    edge["normalized_operation"] = f"{edge['method']} {donor_path}"
    digest_set = _rehash_route_projection(hostile)
    monkeypatch.setattr(validate_openapi_routes, "PROJECTION_RECORD_DIGEST_SET_SHA256", digest_set)
    with pytest.raises(
        validate_openapi_routes.MethodAwareError, match="exclusive source-operation"
    ):
        validate_openapi_routes.load_operation_projection(_write_cohort(tmp_path, hostile))


def test_projection_selection_rule_is_deterministic():
    first = validate_openapi_routes.load_operation_projection()
    second = validate_openapi_routes.load_operation_projection()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    ids = [r["original_record_id"] for r in first["route_records"]]
    assert ids == sorted(ids)


def test_projection_preserves_all_57_path_level_null_method_originals(
    ratified_cohort, tmp_path: Path
):
    projection = validate_openapi_routes.load_operation_projection()
    records = projection["route_records"]
    assert len(records) == 57
    ids = [r["original_record_id"] for r in records]
    assert len(set(ids)) == 57
    originals = {r["original_record_id"]: r for r in ratified_cohort["original_records"]}
    for record in records:
        original = originals[record["original_record_id"]]
        # singular exact path-level membership with method=null, never
        # rewritten, duplicated, or counted once per method
        assert original["method"] is None
        assert (
            original["exact_historical_literal_record"] == record["exact_historical_literal_record"]
        )
    # hostile: a method-bearing rewrite of a path-level original fails closed
    hostile = copy.deepcopy(ratified_cohort)
    victim_id = _route_records(hostile)[0]["original_record_id"]
    for original in hostile["original_records"]:
        if original["original_record_id"] == victim_id:
            original["method"] = "GET"
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="method=null"):
        validate_openapi_routes.load_operation_projection(_write_cohort(tmp_path, hostile))


def test_projection_has_68_route_edges_nine_multi_edge_and_max_four():
    projection = validate_openapi_routes.load_operation_projection()
    records = projection["route_records"]
    # independently derived from records, not trusted from summary counts
    edge_counts = [len(r["operation_edges"]) for r in records]
    assert sum(edge_counts) == 68
    assert sum(1 for n in edge_counts if n > 1) == 9
    assert max(edge_counts) == 4
    assert min(edge_counts) >= 1
    distribution = {}
    for count in edge_counts:
        distribution[count] = distribution.get(count, 0) + 1
    assert distribution == {1: 48, 2: 8, 4: 1}
    assert projection["route_edge_total"] == 68
    assert projection["route_multi_edge_originals"] == 9
    assert projection["route_max_edges"] == 4
    assert projection["route_edge_distribution"] == {"1": 48, "2": 8, "4": 1}


def test_projection_supports_one_original_to_multiple_method_edges():
    projection = validate_openapi_routes.load_operation_projection()
    quad = [r for r in projection["route_records"] if len(r["operation_edges"]) == 4]
    assert len(quad) == 1
    record = quad[0]
    methods = {edge["method"] for edge in record["operation_edges"]}
    paths = {edge["normalized_path"] for edge in record["operation_edges"]}
    assert methods == {"DELETE", "GET", "PATCH", "POST"}
    assert len(paths) == 1
    # one original, one membership, four method-specific operations
    assert (
        tuple(sorted(e["normalized_operation"] for e in record["operation_edges"]))
        == validate_openapi_routes.MULTI_EDGE_OPERATION_PINS[record["original_record_id"]]
    )
    # every ratified multi-edge original matches its pinned edges exactly
    multi = {
        r["original_record_id"]: tuple(
            sorted(e["normalized_operation"] for e in r["operation_edges"])
        )
        for r in projection["route_records"]
        if len(r["operation_edges"]) > 1
    }
    assert multi == dict(validate_openapi_routes.MULTI_EDGE_OPERATION_PINS)


def test_projection_supports_multiple_originals_to_one_operation_without_deduplication(
    ratified_cohort,
):
    by_operation: dict[str, list[str]] = {}
    for record in ratified_cohort["operation_projection"]["records"]:
        for edge in record["operation_edges"]:
            by_operation.setdefault(edge["normalized_operation"], []).append(
                record["original_record_id"]
            )
    convergent = {op: ids for op, ids in by_operation.items() if len(ids) > 1}
    # many-to-one convergence exists in the ratified artifact...
    assert convergent
    for operation, ids in convergent.items():
        # ...and never collapses original memberships: every converging
        # original keeps its own distinct membership record
        assert len(set(ids)) == len(ids)
    # the loader retains all 655 memberships despite convergence
    projection = validate_openapi_routes.load_operation_projection()
    assert projection["original_cohort_total"] == 655
    assert len(projection["route_records"]) == 57


def test_distinct_methods_on_same_path_never_collapse(ratified_cohort, tmp_path: Path, monkeypatch):
    projection = validate_openapi_routes.load_operation_projection()
    for record in projection["route_records"]:
        operation_ids = [e["normalized_operation"] for e in record["operation_edges"]]
        assert len(set(operation_ids)) == len(operation_ids)
        assert len({e["normalized_path"] for e in record["operation_edges"]}) == 1
    # hostile: collapsing two distinct methods into a duplicate edge fails
    hostile = copy.deepcopy(ratified_cohort)
    pair = next(r for r in _route_records(hostile) if len(r["operation_edges"]) == 2)
    pair["operation_edges"][1] = copy.deepcopy(pair["operation_edges"][0])
    digest_set = _rehash_route_projection(hostile)
    monkeypatch.setattr(validate_openapi_routes, "PROJECTION_RECORD_DIGEST_SET_SHA256", digest_set)
    with pytest.raises(validate_openapi_routes.MethodAwareError):
        validate_openapi_routes.load_operation_projection(_write_cohort(tmp_path, hostile))


def test_every_projected_edge_has_exact_method_witness(
    ratified_cohort, tmp_path: Path, monkeypatch
):
    for record in validate_openapi_routes.load_operation_projection()["route_records"]:
        for edge in record["operation_edges"]:
            assert any(w.get("method") == edge["method"] for w in edge["evidence"])
    # hostile: an edge whose witnesses all carry another method fails closed
    hostile = copy.deepcopy(ratified_cohort)
    record = next(r for r in _route_records(hostile) if len(r["operation_edges"]) == 2)
    edge = record["operation_edges"][0]
    other = "POST" if edge["method"] != "POST" else "GET"
    for witness in edge["evidence"]:
        witness["method"] = other
    digest_set = _rehash_route_projection(hostile)
    monkeypatch.setattr(validate_openapi_routes, "PROJECTION_RECORD_DIGEST_SET_SHA256", digest_set)
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="exact-method witness"):
        validate_openapi_routes.load_operation_projection(_write_cohort(tmp_path, hostile))


def test_null_method_is_forbidden_on_projected_edges(ratified_cohort, tmp_path: Path, monkeypatch):
    for hostile_method in (None, "get", "FETCH", ""):
        hostile = copy.deepcopy(ratified_cohort)
        record = _route_records(hostile)[0]
        record["operation_edges"][0]["method"] = hostile_method
        digest_set = _rehash_route_projection(hostile)
        monkeypatch.setattr(
            validate_openapi_routes, "PROJECTION_RECORD_DIGEST_SET_SHA256", digest_set
        )
        with pytest.raises(validate_openapi_routes.MethodAwareError, match="invalid method"):
            validate_openapi_routes.load_operation_projection(_write_cohort(tmp_path, hostile))


def test_every_witnessed_method_specific_edge_is_required(
    ratified_cohort, tmp_path: Path, monkeypatch
):
    # omitting a still-witnessed edge from the ratified quad fails closed even
    # when digests are recomputed to match the tampered artifact
    hostile = copy.deepcopy(ratified_cohort)
    quad = next(r for r in _route_records(hostile) if len(r["operation_edges"]) == 4)
    del quad["operation_edges"][0]
    digest_set = _rehash_route_projection(hostile)
    monkeypatch.setattr(validate_openapi_routes, "PROJECTION_RECORD_DIGEST_SET_SHA256", digest_set)
    with pytest.raises(validate_openapi_routes.MethodAwareError):
        validate_openapi_routes.load_operation_projection(_write_cohort(tmp_path, hostile))
    # without digest recomputation the same omission fails at the digest layer
    hostile2 = copy.deepcopy(ratified_cohort)
    quad2 = next(r for r in _route_records(hostile2) if len(r["operation_edges"]) == 4)
    del quad2["operation_edges"][0]
    monkeypatch.undo()
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="digest"):
        validate_openapi_routes.load_operation_projection(_write_cohort(tmp_path, hostile2))


def test_edge_count_cannot_replace_original_cohort_count(monkeypatch):
    projection = validate_openapi_routes.load_operation_projection()
    # 68 and 666-style edge counts are edge facts; the original cohort count is
    # a separate immutable 655 identity fact bound by digest, never by count
    assert projection["original_cohort_total"] == 655
    assert projection["route_edge_total"] == 68
    assert projection["original_cohort_total"] != projection["route_edge_total"]
    monkeypatch.setattr(validate_openapi_routes, "ORIGINAL_COHORT_TOTAL", 68)
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="655|68"):
        validate_openapi_routes.load_operation_projection()


def test_projection_digest_is_canonical(ratified_cohort, tmp_path: Path):
    record = _route_records(ratified_cohort)[0]
    body = {k: v for k, v in record.items() if k != "record_sha256"}
    canonical = validate_openapi_routes._canonical_json_bytes(body)
    assert validate_openapi_routes._sha256_hex(canonical) == record["record_sha256"]
    # canonical bytes are compact sorted-key UTF-8 without BOM or trailing LF
    assert not canonical.startswith(b"\xef\xbb\xbf")
    assert not canonical.endswith(b"\n")
    assert b": " not in canonical.split(b'"selection_rule"')[0][:200]
    # a non-canonical encoding (indented) does not reproduce the digest
    pretty = json.dumps(body, sort_keys=True, indent=1).encode("utf-8")
    assert validate_openapi_routes._sha256_hex(pretty) != record["record_sha256"]
    # digest tampering fails closed
    hostile = copy.deepcopy(ratified_cohort)
    victim = _route_records(hostile)[0]
    victim["record_sha256"] = "0" * 64
    with pytest.raises(validate_openapi_routes.MethodAwareError, match="digest"):
        validate_openapi_routes.load_operation_projection(_write_cohort(tmp_path, hostile))


def test_projection_revision_preserves_global_and_per_category_original_id_sets(
    ratified_cohort, tmp_path: Path, monkeypatch
):
    # a category rewrite changes the derived identity and can never satisfy
    # the immutable global ID-set digest, even with recomputed record digests
    hostile = copy.deepcopy(ratified_cohort)
    victim = next(
        r for r in hostile["original_records"] if r["category"] == "routes_missing_in_spec"
    )
    twin = next(
        r
        for r in hostile["operation_projection"]["records"]
        if r["original_record_id"] == victim["original_record_id"]
    )
    for record in (victim, twin):
        record["category"] = "routes_orphaned_in_spec"
    digest_set = _rehash_route_projection(hostile)
    monkeypatch.setattr(validate_openapi_routes, "PROJECTION_RECORD_DIGEST_SET_SHA256", digest_set)
    with pytest.raises(validate_openapi_routes.MethodAwareError):
        validate_openapi_routes.load_operation_projection(_write_cohort(tmp_path, hostile))
    # the ratified artifact itself proves global and per-category preservation
    monkeypatch.undo()
    projection = validate_openapi_routes.load_operation_projection()
    assert (
        projection["original_record_id_set_sha256"]
        == "c1235670c183b1887ba3fe4280fa0320f9fd6f4a85b8f346d4332ac2aebbe269"
    )
    per_category: dict[str, set[str]] = {}
    for record in _route_records(ratified_cohort):
        per_category.setdefault(record["category"], set()).add(record["original_record_id"])
    assert {k: len(v) for k, v in per_category.items()} == {
        "routes_missing_in_spec": 11,
        "routes_orphaned_in_spec": 17,
        "sdk_missing_from_both": 29,
    }


def test_omitted_extra_duplicate_identity_edge_witness_or_digest_tamper_fails_closed(
    ratified_cohort, tmp_path: Path
):
    def _omit_original(cohort):
        victim = _route_records(cohort)[0]["original_record_id"]
        cohort["original_records"] = [
            r for r in cohort["original_records"] if r["original_record_id"] != victim
        ]
        cohort["operation_projection"]["records"] = [
            r
            for r in cohort["operation_projection"]["records"]
            if r["original_record_id"] != victim
        ]

    def _extra_original(cohort):
        clone = copy.deepcopy(_route_records(cohort)[0])
        clone["exact_historical_literal_record"] = "/api/v1/invented/route"
        payload = validate_openapi_routes._canonical_json_bytes(
            {
                "category": clone["category"],
                "exact_historical_literal_record": clone["exact_historical_literal_record"],
                "schema": "cdg-original-record-id-v1",
            }
        )
        clone["original_record_id"] = f"cdg1:{validate_openapi_routes._sha256_hex(payload)}"
        cohort["operation_projection"]["records"].append(clone)

    def _duplicate_membership(cohort):
        cohort["operation_projection"]["records"].append(copy.deepcopy(_route_records(cohort)[0]))

    def _identity_rewrite(cohort):
        _route_records(cohort)[0]["original_record_id"] = "cdg1:" + "f" * 64

    def _edge_omission(cohort):
        quad = next(r for r in _route_records(cohort) if len(r["operation_edges"]) == 4)
        del quad["operation_edges"][1]

    def _invented_witness_edge(cohort):
        record = _route_records(cohort)[0]
        fabricated = copy.deepcopy(record["operation_edges"][0])
        fabricated["method"] = "TRACE"
        fabricated["normalized_operation"] = f"TRACE {fabricated['normalized_path']}"
        for witness in fabricated["evidence"]:
            witness["method"] = "TRACE"
        record["operation_edges"].append(fabricated)

    def _digest_tamper(cohort):
        cohort["operation_projection"]["records"][0]["record_sha256"] = "1" * 64

    for name, mutate in (
        ("omitted original", _omit_original),
        ("extra original", _extra_original),
        ("duplicate membership", _duplicate_membership),
        ("identity rewrite", _identity_rewrite),
        ("edge omission", _edge_omission),
        ("invented witness edge", _invented_witness_edge),
        ("digest tamper", _digest_tamper),
    ):
        hostile = copy.deepcopy(ratified_cohort)
        mutate(hostile)
        with pytest.raises(validate_openapi_routes.MethodAwareError):
            validate_openapi_routes.load_operation_projection(_write_cohort(tmp_path, hostile))
