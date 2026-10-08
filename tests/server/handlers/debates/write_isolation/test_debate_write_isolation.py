"""Debate write routes are scoped to the debate's org (inventory D9, D10).

Only the owning org may write: another org's debate, a debate with no recorded
org and another org's *public* debate all answer the 404 of a missing id, and
nothing changes. Setup is in ``conftest.py`` and ``support.py``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from tests.server.handlers.debates.write_isolation.support import (
    ANON,
    DA,
    DA_TASK,
    DB,
    DN,
    DP,
    NOT_FOUND,
    ORG_A,
    REFUSALS,
    USER_A,
    USER_B,
    USER_NO_ORG,
    body_of,
    text_of,
)
from tests.server.rbac_dispatch import STATIC_TOKEN

# POST suffixes under /api/v1/debates/{id}/ that no handler serves.
UNSERVED_POST_SUFFIXES = ("intervene", "checkpoint", "checkpoint/pause", "bridge")
INTERVENTION = {"type": "redirect", "content": "Probe intervention"}


class TestPerDebatePostRoutes:
    """D9: fork, followup, decision-integrity, and the verify and cancel writes."""

    TARGETS = {
        "fork": ("_fork_debate", {"branch_point": 0}),
        "followup": ("_create_followup_debate", {"task": "Follow-up probe"}),
        "decision-integrity": ("_create_decision_integrity", {}),
        "verify": ("_verify_outcome", {"correct": True}),
        "cancel": ("_cancel_debate", {}),
    }

    @pytest.mark.parametrize("suffix", sorted(TARGETS))
    def test_refused_callers_never_reach_the_route(self, send, debates, monkeypatch, suffix):
        method_name, body = self.TARGETS[suffix]
        spy = MagicMock()
        monkeypatch.setattr(debates, method_name, spy)

        for user, debate_id, status in REFUSALS:
            for prefix in ("/api/v1/debates", "/api/debates"):
                result = send(user, "POST", f"{prefix}/{debate_id}/{suffix}", body)
                assert result.status_code == status, (suffix, debate_id, user.user_id)
                if status == 404:
                    assert body_of(result) == NOT_FOUND, (suffix, debate_id)
                assert DA_TASK not in text_of(result)
        spy.assert_not_called()

    @pytest.mark.parametrize("suffix", sorted(TARGETS))
    def test_owner_reaches_the_route_for_own_debates(self, send, debates, monkeypatch, suffix):
        from aragora.server.handlers.base import json_response

        method_name, body = self.TARGETS[suffix]
        spy = MagicMock(return_value=json_response({"ok": True}))
        monkeypatch.setattr(debates, method_name, spy)

        for debate_id in (DA, DP):
            result = send(USER_A, "POST", f"/api/v1/debates/{debate_id}/{suffix}", body)
            assert result.status_code == 200, (suffix, debate_id, text_of(result))
        assert [c.args[1] for c in spy.call_args_list] == [DA, DP]

    def test_owner_fork_carries_owner_org_and_stays_private(self, send, tmp_path):
        result = send(USER_A, "POST", f"/api/v1/debates/{DA}/fork", {"branch_point": 1})

        assert result.status_code == 200, text_of(result)
        branch_id = body_of(result)["branch_id"]
        record = json.loads((tmp_path / "branches" / f"{branch_id}.json").read_text())
        assert (record["org_id"], record["created_by"]) == (ORG_A, "user-a")

        forks_a = send(USER_A, "GET", f"/api/v1/debates/{DA}/forks")
        forks_b = send(USER_B, "GET", f"/api/v1/debates/{DA}/forks")
        assert [f["branch_id"] for f in body_of(forks_a)["forks"]] == [branch_id]
        assert (forks_b.status_code, body_of(forks_b)) == (404, NOT_FOUND)
        fork_as_b = send(USER_B, "GET", f"/api/v1/debates/{branch_id}")
        assert (fork_as_b.status_code, body_of(fork_as_b)) == (404, NOT_FOUND)

    def test_owner_followup_carries_owner_org(self, send, tmp_path):
        result = send(USER_A, "POST", f"/api/v1/debates/{DA}/followup", {"task": "Dig deeper"})

        assert result.status_code == 200, text_of(result)
        followup_id = body_of(result)["followup_id"]
        record = json.loads((tmp_path / "followups" / f"{followup_id}.json").read_text())
        assert (record["org_id"], record["created_by"]) == (ORG_A, "user-a")

    def test_refused_forks_and_followups_write_nothing(self, send, tmp_path):
        for user, debate_id, _status in REFUSALS:
            send(user, "POST", f"/api/v1/debates/{debate_id}/fork", {"branch_point": 0})
            send(user, "POST", f"/api/v1/debates/{debate_id}/followup", {"task": "x"})

        assert list(tmp_path.glob("branches/*.json")) == []
        assert list(tmp_path.glob("followups/*.json")) == []

    def test_running_debate_of_another_org_cannot_be_cancelled(self, send, state_manager):
        state_manager.register_debate("deb-running-a", "Running for A", ["claude"])
        state_manager.get_debate("deb-running-a").metadata["org_id"] = ORG_A
        state_manager.update_debate_status("deb-running-a", status="running")

        refused = send(USER_B, "POST", "/api/v1/debates/deb-running-a/cancel")
        assert (refused.status_code, body_of(refused)) == (404, NOT_FOUND)
        assert state_manager.get_debate("deb-running-a").status == "running"

        owner = send(USER_A, "POST", "/api/v1/debates/deb-running-a/cancel")
        assert owner.status_code == 200, text_of(owner)

    @pytest.mark.parametrize("suffix", UNSERVED_POST_SUFFIXES)
    def test_unserved_suffixes_answer_the_write_gate_then_404(self, send, suffix):
        cases = REFUSALS + (
            (ANON, DP, 401),
            (USER_NO_ORG, DP, 403),
            (USER_A, DA, 404),
            (USER_A, DP, 404),
        )
        for user, debate_id, status in cases:
            for prefix in ("/api/v1/debates", "/api/debates"):
                result = send(user, "POST", f"{prefix}/{debate_id}/{suffix}", INTERVENTION)
                assert result.status_code == status, (suffix, debate_id, user.user_id)
                if status == 404:
                    assert body_of(result) == NOT_FOUND, (suffix, debate_id)


class TestPatchAndDelete:
    """D10: PATCH and DELETE /api/v1/debates/{id}."""

    def test_refused_callers_change_nothing(self, send, storage):
        before = {d: storage.get_debate(d) for d in (DA, DB, DN, DP)}

        for user, debate_id, status in REFUSALS:
            for method, body in (("PATCH", {"title": "Hijacked"}), ("DELETE", None)):
                result = send(user, method, f"/api/v1/debates/{debate_id}", body)
                assert result.status_code == status, (method, debate_id, user.user_id)
                if status == 404:
                    assert body_of(result) == NOT_FOUND, (method, debate_id)

        assert {d: storage.get_debate(d) for d in (DA, DB, DN, DP)} == before
        assert storage.is_public(DP) and not storage.is_public(DA)

    def test_owner_patch_is_saved_and_visible_on_next_read(self, send, storage):
        result = send(USER_A, "PATCH", f"/api/v1/debates/{DA}", {"title": "Renamed by A"})

        assert result.status_code == 200, text_of(result)
        assert body_of(send(USER_A, "GET", f"/api/v1/debates/{DA}"))["title"] == "Renamed by A"
        assert storage.get_access_info(DA) == (DA, ORG_A, False)

    def test_owner_deletes_own_debate(self, send, storage):
        result = send(USER_A, "DELETE", f"/api/v1/debates/{DA}")

        assert result.status_code == 200, text_of(result)
        assert storage.get_debate(DA) is None
        assert storage.get_debate(DB) is not None


@pytest.mark.no_auto_auth
class TestWithoutTheRbacTestBypass:
    """Anonymous writes are refused with the API token unset (stock dev mode) and set."""

    @pytest.mark.parametrize("token", [None, "static-test-token"])
    def test_anonymous_writes_get_401_and_change_nothing(self, send, storage, monkeypatch, token):
        from aragora.server.auth import auth_config

        monkeypatch.setattr(auth_config, "api_token", token)
        monkeypatch.setattr(auth_config, "enabled", token is not None)
        before = storage.get_debate(DA)

        for method, path, body in (
            ("DELETE", f"/api/v1/debates/{DA}", None),
            ("PATCH", f"/api/v1/debates/{DA}", {"title": "Anonymous edit"}),
            ("POST", f"/api/v1/debates/{DA}/fork", {"branch_point": 0}),
            ("POST", f"/api/v1/debates/{DA}/followup", {"task": "x"}),
            ("POST", f"/api/v1/debates/{DA}/decision-integrity", {}),
        ):
            result = send(ANON, method, path, body)
            assert result.status_code == 401, (method, path, text_of(result))
        assert storage.get_debate(DA) == before


@pytest.mark.no_auto_auth
class TestThroughTheServer:
    """The real dispatch path: route index, auth gates and RBAC, with real JWTs."""

    WRITES = (
        ("PATCH", f"/api/v1/debates/{DA}", {"title": "Hijacked"}),
        ("DELETE", f"/api/v1/debates/{DA}", None),
        ("POST", f"/api/v1/debates/{DA}/fork", {"branch_point": 0}),
        ("POST", f"/api/v1/debates/{DP}/followup", {"task": "x"}),
    )

    def test_other_org_gets_the_missing_debate_404(self, server, storage):
        from tests.server.rbac_dispatch import dispatch, jwt

        token_b = jwt("user-b", "org-b", "owner")
        for method, path, body in self.WRITES:
            status, payload = dispatch(server, method, path, token_b, body=body)
            assert (status, payload) == (404, NOT_FOUND), (method, path)
        assert storage.get_debate(DA)["task"] == DA_TASK

    @pytest.mark.parametrize("server", [None, "rbac-route-rules-static-token"], indirect=True)
    def test_anonymous_writes_get_401(self, server, storage):
        from tests.server.rbac_dispatch import dispatch

        for method, path, body in self.WRITES:
            status, _payload = dispatch(server, method, path, body=body)
            assert status == 401, (method, path)
        assert storage.get_debate(DA)["task"] == DA_TASK

    def test_owner_patch_and_delete(self, server, storage):
        from tests.server.rbac_dispatch import dispatch, jwt

        token_a = jwt("user-a", ORG_A, "owner")
        status, payload = dispatch(
            server, "PATCH", f"/api/v1/debates/{DA}", token_a, body={"title": "Renamed"}
        )
        assert status == 200, payload
        assert storage.get_debate(DA)["title"] == "Renamed"

        status, payload = dispatch(server, "DELETE", f"/api/v1/debates/{DA}", token_a)
        assert status == 200, payload
        assert storage.get_debate(DA) is None

    def test_unserved_post_suffixes_of_a_public_debate(self, server):
        from aragora.debate.intervention import get_intervention_queue
        from tests.server.rbac_dispatch import ORG_REQUIRED_BODY, dispatch, jwt

        callers = (
            (None, 401, None),
            (jwt("user-no-org", None, "owner"), 403, ORG_REQUIRED_BODY),
            (jwt("user-b", "org-b", "owner"), 404, NOT_FOUND),
            (jwt("user-a", ORG_A, "owner"), 404, NOT_FOUND),
        )
        for suffix in UNSERVED_POST_SUFFIXES:
            for debate_id in (DP, DA):
                path = f"/api/v1/debates/{debate_id}/{suffix}"
                for token, status, expected in callers:
                    got, payload = dispatch(server, "POST", path, token, body=INTERVENTION)
                    assert got == status, (path, payload)
                    assert expected is None or payload == expected, path
        assert get_intervention_queue().get_debate_interventions(DP) == []

    @pytest.mark.parametrize("server", [STATIC_TOKEN], indirect=True)
    def test_unserved_post_suffixes_with_the_api_token_set(self, server):
        from tests.server.rbac_dispatch import ORG_REQUIRED_BODY, dispatch

        for suffix in UNSERVED_POST_SUFFIXES:
            path = f"/api/v1/debates/{DP}/{suffix}"
            assert dispatch(server, "POST", path, body=INTERVENTION)[0] == 401, path
            status, payload = dispatch(server, "POST", path, f"Bearer {STATIC_TOKEN}")
            assert (status, payload) == (403, ORG_REQUIRED_BODY), path


def test_storage_save_debate_updates_the_stored_artifact_only(storage):
    debate = storage.get_debate(DA)
    debate["title"] = "Saved title"

    storage.save_debate(DA, debate)

    assert storage.get_debate(DA)["title"] == "Saved title"
    assert storage.get_access_info(DA) == (DA, ORG_A, False)
    assert storage.get_debate(DB).get("title") is None
