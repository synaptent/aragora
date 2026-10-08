"""Only a debate's own org may intervene in it or read its intervention log.

``POST /api/v1/debates/{id}/{pause,resume,nudge,challenge,inject-evidence}`` and
``GET .../intervention-log`` reach ``DebateInterventionsHandler``;
``DebateInterventionHandler`` serves ``POST .../intervene`` and
``GET .../reasoning`` (through the server those paths currently reach
``DebatesHandler``, which refuses them the same way). Another org's debate (public or not), a debate
with no recorded org and a missing id get the 404 of a missing debate, and no
intervention state is created, changed or queued. The reasoning summary is
readable like the debate itself: public debates by anyone, others by their org;
its queued interventions only by the debate's org.
"""

from __future__ import annotations

from typing import Any

import pytest

from aragora.debate import intervention as intervention_module
from aragora.debate.intervention import (
    InterventionQueue,
    _reset_managers,
    get_intervention_manager,
    get_intervention_queue,
    list_intervention_managers,
)
from aragora.server.handlers.debates import debate_intervention
from aragora.server.handlers.debates.debate_intervention import DebateInterventionHandler
from aragora.server.handlers.debates.interventions import DebateInterventionsHandler
from tests.server.handlers.debates.write_isolation.support import (
    ANON,
    DA,
    DB,
    DN,
    DP,
    DX,
    NOT_FOUND,
    ORG_A,
    ORG_B,
    REFUSALS,
    USER_A,
    USER_B,
    USER_NO_ORG,
    Request,
    act_as,
    body_of,
    route,
    text_of,
)

RUN_A, RUN_B = "deb-running-a", "deb-running-b"
ACTIONS = {
    "pause": {},
    "resume": {},
    "nudge": {"message": "Steer toward cost"},
    "challenge": {"challenge": "Counter the cost claim"},
    "inject-evidence": {"evidence": "A study on cost", "source": "https://example.test"},
    "intervene": {"type": "redirect", "content": "Steer toward cost", "user_id": "spoofed"},
}
LIVE_REFUSALS = REFUSALS + (
    (USER_B, RUN_A, 404),
    (USER_A, RUN_B, 404),
    (ANON, RUN_A, 401),
    (USER_NO_ORG, RUN_A, 403),
)
ALL_DEBATES = (DA, DB, DN, DP, DX, RUN_A, RUN_B)


@pytest.fixture(autouse=True)
def live_debates(state_manager, monkeypatch):
    """A running debate of org A and one of org B, and empty intervention state."""
    _reset_managers()
    monkeypatch.setattr(intervention_module, "_global_queue", InterventionQueue())
    monkeypatch.setattr(debate_intervention._intervention_limiter, "is_allowed", lambda _ip: True)
    for debate_id, org_id in ((RUN_A, ORG_A), (RUN_B, ORG_B)):
        state_manager.register_debate(
            debate_id, f"Live topic of {org_id}", ["claude"], metadata={"org_id": org_id}
        )
    yield
    _reset_managers()


@pytest.fixture
def act(monkeypatch, storage):
    """``act(user, method, debate_id, action, body)`` runs the handler that owns ``action``."""
    interventions = DebateInterventionsHandler(ctx={"storage": storage})
    intervene = DebateInterventionHandler({"storage": storage})

    def _act(
        user: Any, method: str, debate_id: str, action: str, body: dict[str, Any] | None = None
    ):
        act_as(monkeypatch, user)
        path = f"/api/v1/debates/{debate_id}/{action}"
        request = Request(method, user, body)
        if action not in ("intervene", "reasoning"):
            return route(interventions, method, path, request)
        if method == "POST":
            return intervene.handle_post(path, body or {}, request)
        return intervene.handle(path, {}, request)

    return _act


def _queued(debate_id: str) -> list[Any]:
    return get_intervention_queue().get_debate_interventions(debate_id)


class TestRefusedCallers:
    @pytest.mark.parametrize("action", sorted(ACTIONS))
    def test_refused_post_creates_no_intervention_state(self, act, action):
        for user, debate_id, status in LIVE_REFUSALS:
            result = act(user, "POST", debate_id, action, ACTIONS[action])
            assert result.status_code == status, (action, debate_id, user.user_id)
            if status == 404:
                assert body_of(result) == NOT_FOUND, (action, debate_id)

        assert list_intervention_managers() == {}
        assert all(_queued(debate_id) == [] for debate_id in ALL_DEBATES)

    @pytest.mark.parametrize("action", sorted(ACTIONS))
    def test_refused_post_leaves_the_owner_manager_unchanged(self, act, action):
        assert act(USER_A, "POST", RUN_A, "pause").status_code == 200
        manager = get_intervention_manager(RUN_A, create=False)

        for user, debate_id, _status in LIVE_REFUSALS:
            act(user, "POST", debate_id, action, ACTIONS[action])

        assert manager.is_paused
        assert [e.intervention_type.value for e in manager.get_log().entries] == ["pause"]
        assert set(list_intervention_managers()) == {RUN_A}
        assert _queued(RUN_A) == []

    def test_other_orgs_cannot_read_the_intervention_log(self, act):
        act(USER_A, "POST", RUN_A, "nudge", {"message": "Private steer"})

        for user, debate_id, status in LIVE_REFUSALS:
            result = act(user, "GET", debate_id, "intervention-log")
            assert result.status_code == status, (debate_id, user.user_id)
            if status == 404:
                assert body_of(result) == NOT_FOUND, debate_id
            assert "Private steer" not in text_of(result)
            assert "user-a" not in text_of(result)


class TestOwner:
    def test_owner_pauses_nudges_and_reads_the_log(self, act):
        paused = act(USER_A, "POST", RUN_A, "pause")
        assert paused.status_code == 200, text_of(paused)
        assert body_of(paused)["intervention"]["user_id"] == "user-a"

        nudged = act(USER_A, "POST", RUN_A, "nudge", {"message": "Consider cost"})
        assert nudged.status_code == 200, text_of(nudged)

        log = act(USER_A, "GET", RUN_A, "intervention-log")
        assert log.status_code == 200, text_of(log)
        payload = body_of(log)
        assert payload["state"] == "paused"
        assert [(e["type"], e["user_id"]) for e in payload["entries"]] == [
            ("pause", "user-a"),
            ("nudge", "user-a"),
        ]
        assert payload["entries"][1]["message"] == "Consider cost"

    def test_owner_intervene_is_queued_as_the_signed_in_user(self, act):
        result = act(USER_A, "POST", RUN_A, "intervene", ACTIONS["intervene"])

        assert result.status_code == 201, text_of(result)
        assert body_of(result)["debate_id"] == RUN_A
        [queued] = _queued(RUN_A)
        assert (queued.user_id, queued.content) == ("user-a", "Steer toward cost")

    def test_owner_reads_the_empty_log_of_a_stored_debate(self, act):
        result = act(USER_A, "GET", DA, "intervention-log")

        assert result.status_code == 200, text_of(result)
        assert body_of(result)["entries"] == []


class TestReasoning:
    def test_owner_org_reads_its_private_debates(self, act):
        for debate_id in (DA, RUN_A):
            result = act(USER_A, "GET", debate_id, "reasoning")
            assert result.status_code == 200, (debate_id, text_of(result))
            assert body_of(result)["data"]["debate_id"] == debate_id

    def test_private_debates_are_hidden_from_others(self, act):
        for user, debate_id, status in (
            (USER_B, DA, 404),
            (USER_B, RUN_A, 404),
            (USER_A, DN, 404),
            (USER_B, DX, 404),
            (ANON, DA, 401),
            (USER_NO_ORG, DA, 403),
        ):
            result = act(user, "GET", debate_id, "reasoning")
            assert result.status_code == status, (debate_id, user.user_id)
            if status == 404:
                assert body_of(result) == NOT_FOUND, debate_id

    def test_public_debate_is_readable_by_anyone(self, act):
        for user in (ANON, USER_B, USER_NO_ORG, USER_A):
            result = act(user, "GET", DP, "reasoning")
            assert result.status_code == 200, (user.user_id, text_of(result))

    def test_only_the_owner_org_sees_queued_interventions_of_a_public_debate(self, act):
        get_intervention_queue().queue_intervention(
            debate_id=DP,
            intervention_type="redirect",
            content="Private steer of org A",
            user_id="user-a",
            metadata={"note": "internal"},
        )

        for user in (ANON, USER_B, USER_NO_ORG):
            result = act(user, "GET", DP, "reasoning")
            assert result.status_code == 200, (user.user_id, text_of(result))
            assert body_of(result)["data"]["interventions"] == {}
            for secret in ("Private steer of org A", "user-a", "internal"):
                assert secret not in text_of(result), (user.user_id, secret)

        owner = body_of(act(USER_A, "GET", DP, "reasoning"))["data"]["interventions"]
        assert owner["total_interventions"] == 1
        assert owner["interventions"][0]["content"] == "Private steer of org A"


@pytest.mark.no_auto_auth
class TestThroughTheServer:
    """The real dispatch path: route index, auth gates and RBAC, with real JWTs."""

    POSTS = (
        f"/api/v1/debates/{DA}/pause",
        f"/api/v1/debates/{RUN_A}/pause",
        f"/api/v1/debates/{RUN_A}/nudge",
        f"/api/v1/debates/{DA}/intervene",
        f"/api/v1/debates/{RUN_A}/intervene",
    )

    @pytest.fixture(autouse=True)
    def _wire(self, server, storage):
        server.cls._debate_interventions_handler.ctx["storage"] = storage
        server.cls._debate_intervention_handler.ctx["storage"] = storage
        server.cls._debate_intervention_handler.queue = get_intervention_queue()

    def test_intervention_routes_reach_their_handlers(self, server):
        from aragora.server.handlers.debates import DebatesHandler
        from tests.server.rbac_dispatch import handler_for

        for action in ("pause", "resume", "nudge", "challenge", "inject-evidence"):
            path = f"/api/v1/debates/{DA}/{action}"
            assert isinstance(handler_for(server, path), DebateInterventionsHandler), path
        path = f"/api/v1/debates/{DA}/intervention-log"
        assert isinstance(handler_for(server, path), DebateInterventionsHandler), path
        # DebateInterventionHandler registers no route or prefix the index can
        # match, so DebatesHandler's /api/v1/debates/ prefix claims these.
        for action in ("intervene", "reasoning"):
            path = f"/api/v1/debates/{DA}/{action}"
            assert isinstance(handler_for(server, path), DebatesHandler), path

    def test_other_org_gets_the_missing_debate_404(self, server):
        from tests.server.rbac_dispatch import dispatch, jwt

        token_b = jwt("user-b", ORG_B, "owner")
        for path in self.POSTS:
            status, payload = dispatch(server, "POST", path, token_b, body=ACTIONS["intervene"])
            assert (status, payload) == (404, NOT_FOUND), path
        for path in (
            f"/api/v1/debates/{RUN_A}/intervention-log",
            f"/api/v1/debates/{DA}/reasoning",
        ):
            status, payload = dispatch(server, "GET", path, token_b)
            assert (status, payload) == (404, NOT_FOUND), path
        assert list_intervention_managers() == {}
        assert _queued(DA) == [] and _queued(RUN_A) == []

    def test_owner_pauses_through_the_server(self, server):
        from tests.server.rbac_dispatch import dispatch, jwt

        token_a = jwt("user-a", ORG_A, "owner")
        status, payload = dispatch(server, "POST", f"/api/v1/debates/{RUN_A}/pause", token_a)

        assert status == 200, payload
        assert get_intervention_manager(RUN_A, create=False).is_paused

    @pytest.mark.parametrize("server", [None, "rbac-route-rules-static-token"], indirect=True)
    def test_anonymous_interventions_get_401(self, server):
        from tests.server.rbac_dispatch import dispatch

        for path in self.POSTS:
            status, _payload = dispatch(server, "POST", path, body=ACTIONS["intervene"])
            assert status == 401, path
        assert list_intervention_managers() == {}
        assert _queued(DA) == [] and _queued(RUN_A) == []
