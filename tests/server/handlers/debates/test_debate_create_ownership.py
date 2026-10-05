"""Debate create paths persist the creator's org and default to private.

Covers inventory D0: ``POST /api/v1/debates``, ``/api/v1/debate``,
``/api/v1/debate-this`` and ``/api/v1/debates/batch`` stamp the authenticated
caller's org on the debate, ``DebateStorage`` writes ``org_id`` and
``is_public = 0`` for new rows, and only the share flow makes a debate public.
The FastAPI ``POST /api/v2/debates`` path is covered in
``tests/server/fastapi/test_debate_routes.py``.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from aragora.server.debate_controller import DebateController, DebateRequest
from aragora.server.debate_factory import DebateConfig
from aragora.server.debate_queue import BatchItem
from aragora.storage.debate_storage import DebateStorage
from aragora.tenancy.record_scope import OrgScope

ORG_A = "org-a"
ORG_B = "org-b"


@pytest.fixture(autouse=True)
def _reset_limits_and_share_state(monkeypatch):
    from aragora.server.handlers.debates.public_viewer import _reset_public_viewer_rate_limits
    from aragora.server.handlers.debates.share import _reset_share_state
    from aragora.server.middleware.rate_limit import decorators as rl_decorators
    from aragora.server.middleware.rate_limit.limiter import RateLimitResult
    from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

    def _always_allowed(*args, **kwargs):
        return RateLimitResult(allowed=True, remaining=99, limit=100, key="test")

    monkeypatch.setattr(rl_decorators, "check_user_rate_limit", _always_allowed)
    reset_rate_limiters()
    _reset_public_viewer_rate_limits()
    _reset_share_state()
    yield
    reset_rate_limiters()
    _reset_public_viewer_rate_limits()
    _reset_share_state()


@pytest.fixture(autouse=True)
def state_managers():
    """A fresh real StateManager per test; the process-wide one is restored afterwards."""
    from aragora.server.state import StateManager, get_state_manager
    from aragora.services import ServiceRegistry

    registry, inherited, owned = ServiceRegistry.get(), get_state_manager(), StateManager()
    registry.unregister(StateManager)
    registry.register(StateManager, owned)
    assert get_state_manager() is owned and owned.get_active_debate_count() == 0
    try:
        yield SimpleNamespace(inherited=inherited, owned=owned)
    finally:
        registry.unregister(StateManager)
        registry.register(StateManager, inherited)
        owned.shutdown()
    assert get_state_manager() is inherited and owned.get_active_debate_count() == 0


@pytest.fixture
def storage(tmp_path) -> DebateStorage:
    return DebateStorage(str(tmp_path / "debates.db"))


def _row(storage: DebateStorage, debate_id: str) -> tuple[Any, Any] | None:
    with storage.connection() as conn:
        row = conn.execute(
            "SELECT org_id, is_public FROM debates WHERE id = ?", (debate_id,)
        ).fetchone()
    return tuple(row) if row is not None else None


def _body(result) -> dict[str, Any]:
    raw = result.body
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw) if isinstance(raw, str) else raw


def _user(org_id: str | None = ORG_A, user_id: str = "user-a") -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        org_id=org_id,
        role="member",
        is_authenticated=True,
        authenticated=True,
    )


def _scope(org_id: str = ORG_A) -> OrgScope:
    return OrgScope(org_id=org_id, user_id="user-a", role="member")


@pytest.fixture
def caller(monkeypatch):
    """Set the user that request authentication resolves to."""

    def _set(user: Any) -> None:
        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            lambda handler, user_store=None: user,
        )

    return _set


def _http_handler() -> MagicMock:
    handler = MagicMock()
    handler.command = "POST"
    handler.headers = {"Content-Length": "2", "Host": "localhost"}
    handler.client_address = ("10.0.0.9", 4321)
    handler.stream_emitter = MagicMock()
    del handler.user_store
    return handler


def _debate_result() -> Mock:
    result = Mock()
    result.final_answer = "Ship it behind a flag"
    result.consensus_reached = True
    result.confidence = 0.8
    result.grounded_verdict = None
    result.status = "consensus_reached"
    result.agent_failures = {}
    result.participants = ["agent1", "agent2"]
    result.messages = []
    result.explanation = None
    result.total_cost_usd = 0.0
    result.per_agent_cost = {}
    result.plan = None
    return result


def _make_factory() -> Mock:
    factory = Mock()
    arena = MagicMock()
    result = _debate_result()

    async def _run():
        return result

    arena.run = _run
    factory.create_arena.return_value = arena
    factory.reset_circuit_breakers = Mock()
    return factory


class _InlineExecutor:
    """Runs submitted work immediately so persistence is observable in the test."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return Mock()


def _real_controller(storage: DebateStorage) -> DebateController:
    controller = DebateController(
        factory=_make_factory(),
        emitter=Mock(),
        storage=storage,
    )
    controller._preflight_agents = Mock(return_value=None)  # type: ignore[method-assign]
    controller._get_executor = Mock(return_value=_InlineExecutor())  # type: ignore[method-assign]
    controller._emit_leaderboard_update = Mock()  # type: ignore[method-assign]
    controller._generate_debate_receipt = Mock()  # type: ignore[method-assign]
    controller._quick_classify = Mock()  # type: ignore[method-assign]
    return controller


def _make_create_handler(body: dict[str, Any] | None, user: Any):
    from aragora.server.handlers.base import BaseHandler
    from aragora.server.handlers.debates.create import CreateOperationsMixin

    class _Handler(CreateOperationsMixin, BaseHandler):
        def __init__(self):
            self.ctx = {}

        def read_json_body(self, handler, max_size=None):
            return body

        def get_current_user(self, handler):
            return user

        def _check_spam_content(self, body):
            return None

    return _Handler()


def _make_batch_handler(body: dict[str, Any] | None, ctx: dict[str, Any] | None = None):
    from aragora.server.handlers.base import BaseHandler
    from aragora.server.handlers.debates.batch import BatchOperationsMixin

    class _Handler(BatchOperationsMixin, BaseHandler):
        def __init__(self):
            self.ctx = dict(ctx or {})

        def read_json_body(self, handler, max_size=None):
            return body

    return _Handler()


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class TestDebateStorageOwnership:
    def test_save_dict_stores_org_and_private_flag(self, storage):
        storage.save_dict({"id": "d-1", "task": "Pick a queue", "agents": ["a"]}, org_id=ORG_A)

        assert _row(storage, "d-1") == (ORG_A, 0)
        assert storage.is_public("d-1") is False

    def test_save_dict_without_org_leaves_org_null_and_private(self, storage):
        storage.save_dict({"id": "d-2", "task": "Pick a cache", "agents": ["a"]})

        assert _row(storage, "d-2") == (None, 0)

    def test_save_artifact_is_private(self, storage):
        artifact = SimpleNamespace(
            artifact_id="d-3",
            task="Pick a database",
            agents=["a", "b"],
            consensus_proof=None,
            to_json=lambda: json.dumps({"id": "d-3"}),
        )

        storage.save(artifact)

        assert _row(storage, "d-3") == (None, 0)

    def test_set_public_still_marks_debate_public(self, storage):
        storage.save_dict({"id": "d-4", "task": "Pick a CDN", "agents": ["a"]}, org_id=ORG_A)

        assert storage.set_public("d-4", True) is True
        assert _row(storage, "d-4") == (ORG_A, 1)
        assert storage.is_public("d-4") is True

    def test_existing_null_org_rows_are_not_rewritten(self, storage):
        with storage.connection() as conn:
            conn.execute(
                "INSERT INTO debates (id, slug, task, agents, artifact_json) "
                "VALUES ('legacy-1', 'legacy-1', 'Old debate', '[]', '{}')"
            )
            conn.commit()

        storage.save_dict({"id": "d-5", "task": "New debate", "agents": ["a"]}, org_id=ORG_A)

        assert _row(storage, "legacy-1") == (None, None)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class TestControllerOwnership:
    def test_from_dict_never_reads_owner_from_client_payload(self):
        request = DebateRequest.from_dict(
            {
                "question": "Should we migrate?",
                "org_id": "org-evil",
                "metadata": {"organization_id": "org-evil", "org_id": "org-evil"},
            }
        )

        assert request.org_id is None

    def test_start_debate_carries_org_to_debate_config(self, storage):
        controller = DebateController(factory=Mock(), emitter=Mock(), storage=storage)
        controller._preflight_agents = Mock(return_value=None)  # type: ignore[method-assign]
        controller._quick_classify = Mock()  # type: ignore[method-assign]
        executor = Mock()
        controller._get_executor = Mock(return_value=executor)  # type: ignore[method-assign]

        response = controller.start_debate(DebateRequest(question="Q?", org_id=ORG_A))

        assert response.success is True
        config = executor.submit.call_args.args[1]
        assert isinstance(config, DebateConfig)
        assert config.org_id == ORG_A

    @patch("aragora.server.debate_controller.update_debate_status")
    def test_run_debate_persists_org_and_private_flag(self, _mock_status, storage):
        controller = _real_controller(storage)
        config = DebateConfig(
            question="Which queue?",
            agents_str="agent1,agent2",
            rounds=1,
            debate_id="adhoc_owned",
            org_id=ORG_A,
        )

        controller._run_debate(config, "adhoc_owned")

        assert _row(storage, "adhoc_owned") == (ORG_A, 0)

    @patch("aragora.server.debate_controller.update_debate_status")
    def test_run_debate_without_org_stays_unowned(self, _mock_status, storage):
        controller = _real_controller(storage)
        config = DebateConfig(question="Which cache?", agents_str="agent1", debate_id="adhoc_anon")

        controller._run_debate(config, "adhoc_anon")

        assert _row(storage, "adhoc_anon") == (None, 0)


# ---------------------------------------------------------------------------
# Legacy create handlers: /api/v1/debates, /api/v1/debate, /api/v1/debate-this
# ---------------------------------------------------------------------------


class TestCreateHandlersOwnership:
    def _capture_controller(self, handler: MagicMock) -> MagicMock:
        controller = MagicMock()
        controller.start_debate.return_value = SimpleNamespace(
            success=True,
            debate_id="adhoc_x",
            status_code=200,
            to_dict=lambda: {"success": True, "debate_id": "adhoc_x", "status": "starting"},
        )
        handler._get_debate_controller = MagicMock(return_value=controller)
        return controller

    def test_create_direct_uses_scope_org_not_client_metadata(self):
        body = {
            "question": "Should we adopt event sourcing?",
            "org_id": "org-evil",
            "metadata": {"organization_id": "org-evil"},
        }
        h = _make_create_handler(body, _user(ORG_A))
        handler = _http_handler()
        controller = self._capture_controller(handler)

        result = h._create_debate_direct(handler, body, _scope(ORG_A))

        assert result.status_code == 200
        request = controller.start_debate.call_args.args[0]
        assert request.org_id == ORG_A

    @pytest.mark.parametrize(("user", "status"), [(None, 401), (_user(None), 403)])
    @pytest.mark.parametrize("route", ["_create_debate", "_debate_this"])
    def test_caller_without_org_is_refused_before_the_controller(self, caller, route, user, status):
        body = {"question": "Should we adopt CQRS?", "metadata": {"organization_id": ORG_B}}
        h = _make_create_handler(body, user)
        handler = _http_handler()
        controller = self._capture_controller(handler)
        caller(user)

        result = getattr(h, route)(handler)

        assert result.status_code == status
        controller.start_debate.assert_not_called()

    @patch("aragora.server.handlers.debates.create.importlib.import_module")
    def test_create_debate_route_persists_caller_org(self, _mock_import, storage, caller):
        body = {"question": "Should we split the monolith?", "agents": ["agent1", "agent2"]}
        caller(_user(ORG_A))
        h = _make_create_handler(body, _user(ORG_A))
        handler = _http_handler()
        handler._get_debate_controller = MagicMock(return_value=_real_controller(storage))

        with patch("aragora.server.debate_controller.update_debate_status"):
            result = h._create_debate(handler)

        assert result.status_code == 200, _body(result)
        debate_id = _body(result)["debate_id"]
        assert _row(storage, debate_id) == (ORG_A, 0)

    def test_debate_this_persists_caller_org(self, storage, caller):
        body = {"question": "Should we rewrite the billing service?"}
        caller(_user(ORG_A))
        h = _make_create_handler(body, _user(ORG_A))
        handler = _http_handler()
        handler._get_debate_controller = MagicMock(return_value=_real_controller(storage))

        with patch("aragora.server.debate_controller.update_debate_status"):
            result = h._debate_this(handler)

        assert result.status_code == 200, _body(result)
        debate_id = _body(result)["debate_id"]
        assert _row(storage, debate_id) == (ORG_A, 0)


# ---------------------------------------------------------------------------
# Batch: /api/v1/debates/batch
# ---------------------------------------------------------------------------


class TestBatchOwnership:
    def test_batch_item_from_dict_never_reads_owner(self):
        item = BatchItem.from_dict(
            {"question": "Q?", "org_id": "org-evil", "metadata": {"organization_id": "org-evil"}}
        )

        assert item.org_id is None

    def test_submit_batch_stamps_every_item_with_caller_org(self):
        body = {
            "items": [
                {"question": "First?", "org_id": "org-evil"},
                {"question": "Second?", "metadata": {"organization_id": "org-evil"}},
            ]
        }
        h = _make_batch_handler(body)
        captured: dict[str, Any] = {}
        queue = MagicMock()
        queue.debate_executor = MagicMock()

        async def _submit_batch(batch):
            captured["batch"] = batch
            return "batch_owned"

        queue.submit_batch = _submit_batch

        async def _get_queue():
            return queue

        spam = MagicMock(enabled=False, _initialized=True)
        with (
            patch("aragora.server.debate_queue.get_debate_queue", _get_queue),
            patch("aragora.moderation.get_spam_moderation", return_value=spam),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=_user(ORG_A),
            ),
        ):
            result = h._submit_batch(_http_handler())

        assert result.status_code == 200, _body(result)
        assert [item.org_id for item in captured["batch"].items] == [ORG_A, ORG_A]

    def test_executor_uses_server_storage_and_item_org(self):
        storage = MagicMock()
        h = _make_batch_handler(None, ctx={"storage": storage})
        executor = h._create_debate_executor()
        item = BatchItem(question="Batch Q?", agents="agent1,agent2", rounds=1)
        item.org_id = ORG_A

        with patch("aragora.server.debate_controller.DebateController") as controller_cls:
            controller_cls.return_value.start_debate.return_value = SimpleNamespace(
                success=True, debate_id="adhoc_batch"
            )
            result = asyncio.run(executor(item))

        assert result == {"success": True, "debate_id": "adhoc_batch"}
        assert controller_cls.call_args.kwargs["storage"] is storage
        request = controller_cls.return_value.start_debate.call_args.args[0]
        assert request.org_id == ORG_A
        assert request.question == "Batch Q?"

    @patch("aragora.server.debate_controller.update_debate_status")
    def test_executor_persists_batch_debate_with_org(self, _mock_status, storage):
        h = _make_batch_handler(None, ctx={"storage": storage})
        executor = h._create_debate_executor()
        item = BatchItem(question="Batch persisted?", agents="agent1,agent2", rounds=1)
        item.org_id = ORG_A
        real_init = DebateController.__init__

        def _init(self, *args, **kwargs):
            real_init(self, *args, **kwargs)
            self.factory = _make_factory()
            self._preflight_agents = Mock(return_value=None)
            self._get_executor = Mock(return_value=_InlineExecutor())
            self._emit_leaderboard_update = Mock()
            self._generate_debate_receipt = Mock()
            self._quick_classify = Mock()

        with patch.object(DebateController, "__init__", _init):
            result = asyncio.run(executor(item))

        assert _row(storage, result["debate_id"]) == (ORG_A, 0)


# ---------------------------------------------------------------------------
# Visibility after creation: lists and the anonymous public viewer
# ---------------------------------------------------------------------------


class TestVisibilityAfterCreate:
    def _create(self, storage: DebateStorage, org_id: str) -> str:
        body = {"question": f"Visibility check for {org_id}?", "agents": "agent1,agent2"}
        h = _make_create_handler(body, _user(org_id))
        handler = _http_handler()
        handler._get_debate_controller = MagicMock(return_value=_real_controller(storage))
        with patch("aragora.server.debate_controller.update_debate_status"):
            result = h._create_debate_direct(handler, body, _scope(org_id))
        return _body(result)["debate_id"]

    def _public_get(self, storage: DebateStorage, debate_id: str):
        from aragora.server.handlers.debates.public_viewer import PublicDebateViewerHandler

        playground_store = MagicMock()
        playground_store.get.return_value = None
        viewer_handler = MagicMock()
        viewer_handler.client_address = ("10.0.0.10", 5555)
        with (
            patch("aragora.storage.debate_store.get_debate_store", return_value=playground_store),
            patch("aragora.server.storage.get_debates_db", return_value=storage),
        ):
            return PublicDebateViewerHandler().handle(
                f"/api/v1/debates/public/{debate_id}", {}, viewer_handler
            )

    def test_creator_org_lists_new_debate_and_other_org_does_not(self, storage):
        debate_id = self._create(storage, ORG_A)

        org_a_ids = [d.debate_id for d in storage.list_recent(limit=50, org_id=ORG_A)]
        org_b_ids = [d.debate_id for d in storage.list_recent(limit=50, org_id=ORG_B)]

        assert debate_id in org_a_ids
        assert debate_id not in org_b_ids
        assert storage.count_debates(org_id=ORG_B) == 0

    def test_new_debate_is_not_served_by_public_viewer(self, storage):
        debate_id = self._create(storage, ORG_A)

        result = self._public_get(storage, debate_id)

        assert result is not None
        assert result.status_code == 404

    def test_share_flow_makes_debate_public_in_storage(self, storage):
        from aragora.server.handlers.debates.share import DebateShareHandler, _reset_share_state

        debate_id = self._create(storage, ORG_A)
        share_result = DebateShareHandler(ctx={"storage": storage}).handle_post(
            f"/api/v1/debates/{debate_id}/share", {}, _http_handler()
        )
        assert share_result.status_code == 200, _body(share_result)
        # Drop the in-memory share flag so only the persisted storage flag counts.
        _reset_share_state()

        assert _row(storage, debate_id) == (ORG_A, 1)
        result = self._public_get(storage, debate_id)
        assert result is not None
        assert result.status_code == 200

    def test_public_viewer_reads_server_storage_from_context(self, storage, tmp_path):
        """The server writes debates to ctx["storage"]; get_debates_db() opens another file."""
        from aragora.server.handlers.debates.public_viewer import PublicDebateViewerHandler

        private_id = self._create(storage, ORG_A)
        public_id = self._create(storage, ORG_A)
        assert storage.set_public(public_id, True)
        other_db = DebateStorage(str(tmp_path / "aragora_debates.db"))
        playground_store = MagicMock()
        playground_store.get.return_value = None
        viewer = PublicDebateViewerHandler({"storage": storage})
        request = MagicMock()
        request.client_address = ("10.0.0.11", 5555)

        with (
            patch("aragora.storage.debate_store.get_debate_store", return_value=playground_store),
            patch("aragora.server.storage.get_debates_db", return_value=other_db),
        ):
            public = viewer.handle(f"/api/v1/debates/public/{public_id}", {}, request)
            public_og = viewer.handle(f"/api/v1/debates/public/{public_id}/og", {}, request)
            private = viewer.handle(f"/api/v1/debates/public/{private_id}", {}, request)

        assert public.status_code == 200
        assert _body(public)["id"] == public_id
        assert public_og.status_code == 200
        assert private.status_code == 404


# ---------------------------------------------------------------------------
# Route dispatch: /api/v1/debates/public/* must reach the public viewer
# ---------------------------------------------------------------------------


def _public_route_index():
    from aragora.server.handler_registry import RouteIndex
    from aragora.server.handlers.debates import DebatesHandler
    from aragora.server.handlers.debates.interventions import DebateInterventionsHandler
    from aragora.server.handlers.debates.public_viewer import PublicDebateViewerHandler
    from aragora.server.handlers.explainability import ExplainabilityHandler

    # Real registry attr names in real registry order, so RouteIndex.build()
    # applies the production PREFIX_PATTERNS wiring.
    subset = [
        ("_debates_handler", DebatesHandler),
        ("_explainability_handler", ExplainabilityHandler),
        ("_public_debate_viewer_handler", PublicDebateViewerHandler),
        ("_debate_interventions_handler", DebateInterventionsHandler),
    ]
    registry = SimpleNamespace(**{name: cls({}) for name, cls in subset})
    index = RouteIndex()
    index.build(registry, subset)
    return index, [name for name, _ in subset]


class TestPublicViewerRouteDispatch:
    def test_subset_preserves_real_registry_order(self):
        from aragora.server.handler_registry import HANDLER_REGISTRY

        _, names = _public_route_index()
        registry_names = [name for name, _ in HANDLER_REGISTRY]
        positions = [registry_names.index(name) for name in names]
        assert positions == sorted(positions)

    @pytest.mark.parametrize(
        "path",
        ["/api/v1/debates/public/adhoc_1234abcd", "/api/v1/debates/public/adhoc_1234abcd/og"],
    )
    def test_public_paths_resolve_to_public_viewer(self, path):
        index, _ = _public_route_index()

        match = index.get_handler(path)

        assert match is not None
        assert match[0] == "_public_debate_viewer_handler"

    def test_plain_debate_path_still_resolves_to_debates_handler(self):
        index, _ = _public_route_index()

        match = index.get_handler("/api/v1/debates/adhoc_1234abcd")

        assert match is not None
        assert match[0] == "_debates_handler"
