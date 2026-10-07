"""Only the debate's own org may share or unshare it (inventory D12).

``POST``/``DELETE /api/v1/debates/{id}/share`` reach ``DebateShareHandler``,
which answers another org's debate (public or not), one with no recorded org
and a missing id with the 404 of a missing debate and changes nothing.
"""

from __future__ import annotations

from typing import Any

import pytest

from aragora.server.handlers.debates.share import (
    DebateShareHandler,
    _reset_share_state,
    is_publicly_shared,
)
from tests.server.handlers.debates.write_isolation.support import (
    DA,
    DA_TASK,
    DB,
    DN,
    DP,
    DX,
    NOT_FOUND,
    ORG_A,
    ORG_B,
    REFUSALS,
    USER_A,
    Request,
    act_as,
    body_of,
    route,
    text_of,
)


@pytest.fixture(autouse=True)
def _clean_share_state():
    _reset_share_state()
    yield
    _reset_share_state()


@pytest.fixture
def share(monkeypatch, storage):
    handler = DebateShareHandler(ctx={"storage": storage})

    def _share(user: Any, method: str, debate_id: str):
        act_as(monkeypatch, user)
        path = f"/api/v1/debates/{debate_id}/share"
        return route(handler, method, path, Request(method, user))

    return _share


def test_owner_shares_and_unshares(share, storage):
    shared = share(USER_A, "POST", DA)
    assert shared.status_code == 200, text_of(shared)
    assert storage.is_public(DA) and is_publicly_shared(DA)

    revoked = share(USER_A, "DELETE", DA)
    assert revoked.status_code == 200, text_of(revoked)
    assert not storage.is_public(DA) and not is_publicly_shared(DA)


def test_refused_callers_change_nothing(share, storage):
    for user, debate_id, status in REFUSALS:
        for method in ("POST", "DELETE"):
            result = share(user, method, debate_id)
            assert result.status_code == status, (method, debate_id, user.user_id)
            if status == 404:
                assert body_of(result) == NOT_FOUND

    assert not storage.is_public(DA) and not storage.is_public(DN)
    assert storage.is_public(DP)
    assert not any(is_publicly_shared(d) for d in (DA, DB, DN, DX))


def test_share_permission_key_is_registered_and_held_by_owner():
    from aragora.rbac.defaults import SYSTEM_PERMISSIONS, get_role_permissions

    for method in ("handle_post", "handle_delete"):
        key = _permission_key(DebateShareHandler, method).replace(":", ".")
        assert key in SYSTEM_PERMISSIONS, (method, key)
        assert key in get_role_permissions("owner", include_inherited=True)


def _permission_key(cls: type, method_name: str) -> str:
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(cls, method_name))))
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef)
    keys = [
        decorator.args[0].value
        for decorator in function.decorator_list
        if isinstance(decorator, ast.Call)
        and getattr(decorator.func, "id", None) == "require_permission"
    ]
    assert len(keys) == 1
    return keys[0]


@pytest.mark.no_auto_auth
class TestThroughTheServer:
    """The real dispatch path: route index, auth gates and RBAC, with real JWTs."""

    def test_share_routes_reach_the_share_handler(self, server):
        from tests.server.rbac_dispatch import handler_for

        for path in (f"/api/v1/debates/{DA}/share", f"/api/v1/debates/{DA}/spectate/public"):
            assert isinstance(handler_for(server, path), DebateShareHandler), path

    def test_other_org_gets_the_missing_debate_404_and_owner_shares(self, server, storage):
        from tests.server.rbac_dispatch import dispatch, jwt

        token_b = jwt("user-b", ORG_B, "owner")
        for method, debate_id in (("POST", DA), ("DELETE", DP)):
            path = f"/api/v1/debates/{debate_id}/share"
            status, payload = dispatch(server, method, path, token_b)
            assert (status, payload) == (404, NOT_FOUND), (method, path)
        assert storage.is_public(DP) and not storage.is_public(DA)

        token_a = jwt("user-a", ORG_A, "owner")
        status, payload = dispatch(server, "POST", f"/api/v1/debates/{DA}/share", token_a)
        assert status == 200, payload
        assert storage.is_public(DA)

    @pytest.mark.parametrize("server", [None, "rbac-route-rules-static-token"], indirect=True)
    def test_anonymous_share_writes_get_401(self, server, storage):
        from tests.server.rbac_dispatch import dispatch

        for method, debate_id in (("POST", DA), ("DELETE", DP)):
            status, _payload = dispatch(server, method, f"/api/v1/debates/{debate_id}/share")
            assert status == 401, (method, debate_id)
        assert storage.get_debate(DA)["task"] == DA_TASK
        assert storage.is_public(DP) and not storage.is_public(DA)
