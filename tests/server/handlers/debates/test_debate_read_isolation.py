"""Debate read routes are scoped to the caller's org (inventory D1-D8, D-pub).

Seeds a real ``DebateStorage`` with a private debate of org A (``DA``), one of
org B (``DB``), one with no recorded org (``DN``) and a public debate of org A
(``DP``), then calls ``DebatesHandler.handle`` as A, as B, as a user without an
org and anonymously.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from aragora.server.handlers.debates import DebatesHandler
from aragora.storage.debate_storage import DebateStorage

ORG_A = "org-a"
ORG_B = "org-b"
DA, DB, DN, DP = "deb-alpha-a", "deb-bravo-b", "deb-null-org", "deb-public-a"
DX = "deb-missing-x"
DA_TASK = "Isolation topic alpha for org A only"

SUFFIXES = (
    "messages evidence verification-report impasse convergence summary positions diagnostics"
    " costs events forks followups meta-critique graph/stats rhetorical trickster citations"
    " export/json export/md export/html export/csv package package/markdown"
).split()


@pytest.fixture(autouse=True)
def _no_rate_limits(monkeypatch):
    from aragora.server.middleware.rate_limit import decorators as rl_decorators
    from aragora.server.middleware.rate_limit.limiter import RateLimitResult
    from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

    def _always_allowed(*args, **kwargs):
        return RateLimitResult(allowed=True, remaining=99, limit=100, key="test")

    monkeypatch.setattr(rl_decorators, "check_user_rate_limit", _always_allowed)
    reset_rate_limiters()
    yield
    reset_rate_limiters()


@pytest.fixture(autouse=True)
def state_manager():
    """A fresh StateManager per test; the process-wide one is restored afterwards."""
    from aragora.server.state import StateManager, get_state_manager
    from aragora.services import ServiceRegistry

    registry, inherited, owned = ServiceRegistry.get(), get_state_manager(), StateManager()
    registry.unregister(StateManager)
    registry.register(StateManager, owned)
    try:
        yield owned
    finally:
        registry.unregister(StateManager)
        registry.register(StateManager, inherited)
        owned.shutdown()


def _debate(debate_id: str, task: str) -> dict[str, Any]:
    return {
        "id": debate_id,
        "task": task,
        "agents": ["claude", "gpt"],
        "messages": [
            {"role": "proposer", "agent": "claude", "content": f"{task} opening", "round": 1}
        ],
        "critiques": [],
        "votes": [],
        "final_answer": f"{task} answer",
        "consensus_reached": True,
        "confidence": 0.8,
        "status": "completed",
    }


@pytest.fixture
def storage(tmp_path) -> DebateStorage:
    store = DebateStorage(str(tmp_path / "debates.db"))
    store.save_dict(_debate(DA, DA_TASK), org_id=ORG_A)
    store.save_dict(_debate(DB, "Isolation topic bravo for org B"), org_id=ORG_B)
    store.save_dict(_debate(DN, "Isolation topic with no recorded org"))
    store.save_dict(_debate(DP, "Isolation topic shared publicly by A"), org_id=ORG_A)
    assert store.set_public(DP, True)
    return store


def _slug(storage: DebateStorage, debate_id: str) -> str:
    with storage.connection() as conn:
        return conn.execute("SELECT slug FROM debates WHERE id = ?", (debate_id,)).fetchone()[0]


def _user(org_id: str | None, user_id: str, role: str = "member") -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id, org_id=org_id, role=role, is_authenticated=True, authenticated=True
    )


ANON = SimpleNamespace(user_id=None, org_id=None, role=None, is_authenticated=False)
USER_A = _user(ORG_A, "user-a")
USER_B = _user(ORG_B, "user-b")
USER_NO_ORG = _user(None, "user-no-org")


@pytest.fixture
def call(monkeypatch, storage, tmp_path):
    """``call(user, path, query)`` runs ``DebatesHandler.handle`` as ``user``."""
    handler = DebatesHandler(ctx={"storage": storage, "nomic_dir": tmp_path})

    def _call(user: Any, path: str, query: dict[str, Any] | None = None):
        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            lambda request, user_store=None: user,
        )
        request = MagicMock()
        request.command = "GET"
        request.headers = {"Host": "localhost"}
        request.client_address = ("10.0.0.7", 4000)
        return handler.handle(path, dict(query or {}), request)

    return _call


def _body(result) -> Any:
    raw = result.body
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _text(result) -> str:
    raw = result.body
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)


def _ids(result, key: str) -> set[str]:
    return {item.get("debate_id") or item.get("id") for item in _body(result)[key]}


NOT_FOUND = {"error": "Debate not found", "code": "not_found"}


class TestListsAndSearch:
    @pytest.mark.parametrize("path", ["/api/v1/debates", "/api/debates"])
    def test_list_shows_only_callers_org(self, call, path):
        a = call(USER_A, path)
        b = call(USER_B, path)

        assert a.status_code == 200 and b.status_code == 200
        assert _ids(a, "debates") == {DA, DP}
        assert _ids(b, "debates") == {DB}
        assert _body(b)["total"] == 1
        assert DA_TASK not in _text(b)

    @pytest.mark.parametrize("path", ["/api/v1/search", "/api/debates/search"])
    def test_search_shows_only_callers_org(self, call, path):
        a = call(USER_A, path, {"q": "Isolation topic"})
        b = call(USER_B, path, {"q": "Isolation topic"})
        b_alpha = call(USER_B, path, {"q": "alpha"})

        assert _ids(a, "results") == {DA, DP}
        assert _ids(b, "results") == {DB}
        assert _body(b)["total"] == 1
        assert _ids(b_alpha, "results") == set()
        assert _body(b_alpha)["total"] == 0

    def test_search_without_query_lists_only_callers_org(self, call):
        assert _ids(call(USER_B, "/api/v1/search"), "results") == {DB}

    def test_list_cache_never_serves_one_orgs_list_to_another(self, call):
        """The 30 s list cache keys on the caller's org: A then B within the TTL."""
        first_a = call(USER_A, "/api/v1/debates")
        then_b = call(USER_B, "/api/v1/debates")
        again_a = call(USER_A, "/api/v1/debates")

        assert _ids(first_a, "debates") == {DA, DP}
        assert _ids(then_b, "debates") == {DB}
        assert _ids(again_a, "debates") == {DA, DP}

    def test_search_cache_never_serves_one_orgs_results_to_another(self, call):
        assert _ids(call(USER_A, "/api/v1/search", {"q": "Isolation"}), "results") == {DA, DP}
        assert _ids(call(USER_B, "/api/v1/search", {"q": "Isolation"}), "results") == {DB}

    @pytest.mark.parametrize(
        "path", ["/api/v1/debates", "/api/debates", "/api/v1/search", "/api/debates/search"]
    )
    def test_anonymous_gets_401_and_no_debates(self, call, path):
        result = call(ANON, path, {"q": "Isolation"})

        assert result.status_code == 401
        assert _body(result)["code"] == "auth_required"
        assert "Isolation" not in _text(result)

    @pytest.mark.parametrize("path", ["/api/v1/debates", "/api/v1/search"])
    def test_user_without_org_gets_403_org_required(self, call, path):
        result = call(USER_NO_ORG, path, {"q": "Isolation"})

        assert result.status_code == 403
        assert _body(result)["code"] == "org_required"


class TestSingleDebateReads:
    @pytest.mark.parametrize("prefix", ["/api/v1/debates", "/api/debates"])
    def test_owner_reads_debate_by_id(self, call, prefix):
        result = call(USER_A, f"{prefix}/{DA}")

        assert result.status_code == 200
        assert _body(result)["task"] == DA_TASK

    def test_owner_reads_debate_by_slug(self, call, storage):
        slug = _slug(storage, DA)
        assert slug != DA

        by_slug_route = call(USER_A, f"/api/v1/debates/slug/{slug}")
        by_plain_route = call(USER_A, f"/api/v1/debates/{slug}")

        assert by_slug_route.status_code == 200
        assert _body(by_slug_route)["task"] == DA_TASK
        assert by_plain_route.status_code == 200

    def test_other_org_gets_the_missing_debate_404(self, call, storage):
        slug = _slug(storage, DA)
        missing = call(USER_B, f"/api/v1/debates/{DX}")
        missing_slug = call(USER_B, "/api/v1/debates/slug/no-such-slug-2026-01-01")

        for path in (f"/api/v1/debates/{DA}", f"/api/debates/{DA}", f"/api/v1/debates/slug/{slug}"):
            result = call(USER_B, path)
            assert result.status_code == 404, path
            assert _body(result) == NOT_FOUND, path
        assert (missing.status_code, _body(missing)) == (404, NOT_FOUND)
        assert (missing_slug.status_code, _body(missing_slug)) == (404, NOT_FOUND)

    def test_anonymous_gets_401(self, call, storage):
        for path in (f"/api/v1/debates/{DA}", f"/api/v1/debates/slug/{_slug(storage, DA)}"):
            result = call(ANON, path)
            assert result.status_code == 401, path
            assert DA_TASK not in _text(result)

    def test_user_without_org_gets_403(self, call):
        result = call(USER_NO_ORG, f"/api/v1/debates/{DA}")

        assert result.status_code == 403
        assert _body(result)["code"] == "org_required"


class TestSuffixRoutes:
    @pytest.mark.parametrize("suffix", SUFFIXES)
    def test_other_org_gets_the_missing_debate_404(self, call, suffix):
        on_da = call(USER_B, f"/api/v1/debates/{DA}/{suffix}")
        on_dx = call(USER_B, f"/api/v1/debates/{DX}/{suffix}")

        assert on_da.status_code == 404
        assert _body(on_da) == NOT_FOUND
        assert (on_dx.status_code, _body(on_dx)) == (404, NOT_FOUND)

    @pytest.mark.parametrize("suffix", SUFFIXES)
    def test_anonymous_gets_401(self, call, suffix):
        result = call(ANON, f"/api/v1/debates/{DA}/{suffix}")

        assert result.status_code == 401
        assert DA_TASK not in _text(result)

    @pytest.mark.parametrize("suffix", [s for s in SUFFIXES if not s.startswith("package")])
    def test_owner_is_never_refused(self, call, suffix):
        result = call(USER_A, f"/api/v1/debates/{DA}/{suffix}")

        assert result.status_code not in (401, 403), _text(result)
        assert "debate not found" not in _text(result).lower()

    def test_owner_reads_messages_and_export(self, call):
        messages = call(USER_A, f"/api/v1/debates/{DA}/messages")
        export = call(USER_A, f"/api/v1/debates/{DA}/export/json")

        assert messages.status_code == 200
        assert _body(messages)["total"] == 1
        assert export.status_code == 200
        assert DA_TASK in _text(export)

    def test_singular_debate_prefix_is_scoped(self, call):
        for path in (f"/api/v1/debate/{DA}/meta-critique", f"/api/v1/debate/{DA}/graph/stats"):
            assert call(USER_B, path).status_code == 404, path
            assert call(ANON, path).status_code == 401, path

    def test_unknown_suffix_never_reads_its_last_segment(self, call):
        """B names its own debate first and A's debate last; nothing of A's comes back."""
        for path in (f"/api/v1/debates/{DB}/x/{DA}", f"/api/v1/debates/slug/{DB}/{DA}"):
            result = call(USER_B, path)
            assert result.status_code == 404, path
            assert DA_TASK not in _text(result), path

    def test_export_format_is_validated_after_access(self, call):
        assert call(USER_B, f"/api/v1/debates/{DA}/export/exe").status_code == 404
        assert call(USER_A, f"/api/v1/debates/{DA}/export/exe").status_code == 400


class TestSlugRefs:
    """Per-debate routes read the debate the access check resolved, never the raw slug."""

    @pytest.mark.parametrize("suffix", ["messages", "diagnostics", "export/json"])
    def test_owner_reads_suffix_route_by_slug_like_by_id(self, call, storage, suffix):
        by_id = call(USER_A, f"/api/v1/debates/{DA}/{suffix}")
        by_slug = call(USER_A, f"/api/v1/debates/{_slug(storage, DA)}/{suffix}")

        assert by_id.status_code == 200, _text(by_id)
        assert (by_slug.status_code, _text(by_slug)) == (200, _text(by_id))

    def test_hidden_slugs_get_the_missing_debate_404(self, call, storage):
        for user, debate_id in ((USER_B, DA), (USER_A, DN), (USER_B, DN)):
            for suffix in ("messages", "diagnostics", "export/json"):
                result = call(user, f"/api/v1/debates/{_slug(storage, debate_id)}/{suffix}")
                assert (result.status_code, _body(result)) == (404, NOT_FOUND), suffix
        slug_path = f"/api/v1/debates/{_slug(storage, DA)}/messages"
        assert call(ANON, slug_path).status_code == 401
        assert _body(call(USER_NO_ORG, slug_path))["code"] == "org_required"

    def test_a_slug_never_shadows_another_orgs_id(self, call, storage):
        """A's debate takes B's debate id as its slug: the id still names B's debate."""
        with storage.connection() as conn:
            conn.execute("UPDATE debates SET slug = ? WHERE id = ?", (DB, DA))

        as_a = call(USER_A, f"/api/v1/debates/{DB}/messages")
        as_b = call(USER_B, f"/api/v1/debates/{DB}/messages")

        assert (as_a.status_code, _body(as_a)) == (404, NOT_FOUND)
        assert as_b.status_code == 200
        assert "bravo" in _text(as_b) and DA_TASK not in _text(as_b)


class TestUnknownOwner:
    def test_null_org_debate_is_invisible_to_every_org(self, call):
        for user in (USER_A, USER_B):
            assert DN not in _ids(call(user, "/api/v1/debates"), "debates")
            assert DN not in _ids(call(user, "/api/v1/search", {"q": "no recorded"}), "results")
            for path in (
                f"/api/v1/debates/{DN}",
                f"/api/v1/debates/{DN}/messages",
                f"/api/v1/debates/{DN}/export/json",
            ):
                result = call(user, path)
                assert (result.status_code, _body(result)) == (404, NOT_FOUND), path


class TestPublicDebates:
    @pytest.mark.parametrize("user", [ANON, USER_B, USER_NO_ORG])
    def test_public_debate_is_readable_by_anyone(self, call, user):
        detail = call(user, f"/api/v1/debates/{DP}")
        messages = call(user, f"/api/v1/debates/{DP}/messages")

        assert detail.status_code == 200
        assert _body(detail)["id"] == DP
        assert messages.status_code == 200

    def test_public_debate_stays_out_of_other_orgs_lists(self, call):
        assert DP not in _ids(call(USER_B, "/api/v1/debates"), "debates")

    def test_artifact_visibility_field_does_not_make_a_debate_public(self, call, storage):
        data = _debate("deb-visibility-claim", "Claims to be public in its artifact")
        data["visibility"] = "public"
        data["source"] = "landing"
        storage.save_dict(data, org_id=ORG_A)

        assert call(ANON, "/api/v1/debates/deb-visibility-claim").status_code == 401
        assert call(USER_B, "/api/v1/debates/deb-visibility-claim").status_code == 404


class TestRunningDebates:
    @pytest.fixture
    def running(self, state_manager):
        state_manager.register_debate(
            "deb-running-a", "Running isolation topic", ["claude"], metadata={"org_id": ORG_A}
        )
        state_manager.register_debate("deb-running-null", "Running without org", ["claude"])
        return state_manager

    def test_owner_reads_running_debate_and_others_do_not(self, call, running):
        owner = call(USER_A, "/api/v1/debates/deb-running-a")
        other = call(USER_B, "/api/v1/debates/deb-running-a")

        assert owner.status_code == 200
        assert _body(owner)["in_progress"] is True
        assert (other.status_code, _body(other)) == (404, NOT_FOUND)
        assert call(ANON, "/api/v1/debates/deb-running-a").status_code == 401
        assert call(USER_A, "/api/v1/debates/deb-running-null").status_code == 404

    def test_active_list_shows_only_callers_org(self, call, running):
        a = call(USER_A, "/api/v1/debates/active")
        b = call(USER_B, "/api/v1/debates/active")

        assert [d["id"] for d in _body(a)["debates"]] == ["deb-running-a"]
        assert _body(b)["debates"] == []
        assert call(ANON, "/api/v1/debates/active").status_code == 401
        assert call(USER_NO_ORG, "/api/v1/debates/active").status_code == 403

    def test_controller_records_creator_org_on_running_debate(self, state_manager, storage):
        from unittest.mock import Mock

        from aragora.server.debate_controller import DebateController, DebateRequest

        controller = DebateController(factory=Mock(), emitter=Mock(), storage=storage)
        controller._preflight_agents = Mock(return_value=None)  # type: ignore[method-assign]
        controller._quick_classify = Mock()  # type: ignore[method-assign]
        controller._get_executor = Mock(return_value=Mock())  # type: ignore[method-assign]

        response = controller.start_debate(DebateRequest(question="Q?", org_id=ORG_A))

        state = state_manager.get_debate(response.debate_id)
        assert state is not None
        assert state.metadata["org_id"] == ORG_A


@pytest.mark.no_auto_auth
def test_anonymous_without_rbac_bypass_still_gets_401(call):
    for path in ("/api/v1/debates", f"/api/v1/debates/{DA}", f"/api/v1/debates/{DA}/messages"):
        result = call(ANON, path)
        assert result.status_code == 401, path
        assert DA_TASK not in _text(result)


OWNER_A = _user(ORG_A, "owner-a", "owner")
OWNER_B = _user(ORG_B, "owner-b", "owner")
OWNER_NO_ORG = _user(None, "owner-no-org", "owner")


class _RegistryRequest:
    """A request as the handler registry passes it on, carrying the caller's RBAC
    context, so ``require_permission`` runs the real role check."""

    command = "GET"
    client_address = ("10.0.0.7", 4000)

    def __init__(self, user: Any) -> None:
        from aragora.rbac.models import AuthorizationContext

        self.headers = {"Host": "localhost"}
        self._auth_context = (
            AuthorizationContext(user_id=user.user_id, org_id=user.org_id, roles={user.role})
            if user.is_authenticated
            else None
        )


@pytest.mark.no_auto_auth
class TestExportWithRealRoleChecks:
    """Debate export (VAL-DEB-014) with the real permission checker, no test bypass."""

    @pytest.fixture
    def handler(self, storage, tmp_path):
        return DebatesHandler(ctx={"storage": storage, "nomic_dir": tmp_path})

    @pytest.fixture
    def export(self, monkeypatch, handler):
        def _export(user: Any, debate_id: str, fmt: str = "json"):
            monkeypatch.setattr(
                "aragora.billing.jwt_auth.extract_user_from_request",
                lambda request, user_store=None: user,
            )
            path = f"/api/v1/debates/{debate_id}/export/{fmt}"
            return handler.handle(path, {}, _RegistryRequest(user))

        return _export

    @pytest.mark.parametrize("fmt", sorted(DebatesHandler.ALLOWED_EXPORT_FORMATS))
    def test_owner_exports_every_accepted_format(self, export, fmt):
        result = export(OWNER_A, DA, fmt)

        assert result.status_code == 200, _text(result)
        assert DA_TASK in _text(result)

    @pytest.mark.parametrize("fmt", sorted(DebatesHandler.ALLOWED_EXPORT_FORMATS))
    def test_other_org_and_null_org_get_the_missing_debate_404(self, export, fmt):
        for user, debate_id in ((OWNER_B, DA), (OWNER_A, DN), (OWNER_B, DN), (OWNER_B, DX)):
            result = export(user, debate_id, fmt)
            assert (result.status_code, _body(result)) == (404, NOT_FOUND), debate_id
            assert "Content-Disposition" not in (result.headers or {})

    def test_refusals_never_reach_the_export_handler(self, export, handler, monkeypatch):
        spy = MagicMock()
        monkeypatch.setattr(handler, "_export_debate", spy)

        for user, debate_id in ((OWNER_B, DA), (OWNER_A, DN), (ANON, DA), (OWNER_NO_ORG, DA)):
            assert export(user, debate_id).status_code in (401, 403, 404)
        spy.assert_not_called()

    def test_anonymous_gets_401_with_and_without_the_api_token(self, export, monkeypatch):
        from aragora.server.auth import auth_config

        token_unset = export(ANON, DA)
        monkeypatch.setattr(auth_config, "api_token", "static-test-token")
        monkeypatch.setattr(auth_config, "enabled", True)
        token_set = export(ANON, DA)

        for result in (token_unset, token_set):
            assert result.status_code == 401
            assert DA_TASK not in _text(result)

    def test_user_without_org_gets_403_org_required(self, export):
        result = export(OWNER_NO_ORG, DA)

        assert (result.status_code, _body(result)["code"]) == (403, "org_required")


def test_export_permission_key_is_registered_and_held_by_owner():
    import ast
    import inspect

    from aragora.rbac.defaults import SYSTEM_PERMISSIONS, get_role_permissions
    from aragora.server.handlers.debates import export as export_module

    export_fn = next(
        node
        for node in ast.walk(ast.parse(inspect.getsource(export_module)))
        if isinstance(node, ast.FunctionDef) and node.name == "_export_debate"
    )
    keys = [
        decorator.args[0].value
        for decorator in export_fn.decorator_list
        if isinstance(decorator, ast.Call)
        and getattr(decorator.func, "id", None) == "require_permission"
    ]

    assert len(keys) == 1
    key = keys[0].replace(":", ".")
    assert key in SYSTEM_PERMISSIONS
    assert key in get_role_permissions("owner", include_inherited=True)


class TestStorageAccessInfo:
    def test_resolves_id_then_slug(self, storage):
        slug = _slug(storage, DA)

        assert storage.get_access_info(DA) == (DA, ORG_A, False)
        assert storage.get_access_info(slug) == (DA, ORG_A, False)
        assert storage.get_access_info(DN) == (DN, None, False)
        assert storage.get_access_info(DP) == (DP, ORG_A, True)
        assert storage.get_access_info(DX) is None
        assert storage.get_access_info("") is None
