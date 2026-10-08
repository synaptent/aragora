"""``POST /api/v1/spectate/emit`` through the real server dispatch.

The path stays exempt from the server's token gate, so the handler is what
refuses: anonymous 401, no org (or the bare static token) 403, another org's
debate the 404 of a missing one. Nothing reaches the spectate bridge.
"""

from __future__ import annotations

import pytest

from aragora.spectate.ws_bridge import get_spectate_bridge, reset_spectate_bridge
from tests.server.handlers.debates.write_isolation.support import DA, DP, NOT_FOUND, ORG_A
from tests.server.rbac_dispatch import (
    ORG_REQUIRED_BODY,
    STATIC_TOKEN,
    dispatch,
    handler_for,
    jwt,
)

EMIT = "/api/v1/spectate/emit"


@pytest.fixture
def bridge():
    reset_spectate_bridge()
    bridge = get_spectate_bridge()
    bridge.start()
    yield bridge
    bridge.stop()
    reset_spectate_bridge()


@pytest.fixture
def emit_server(server, storage):
    handler_for(server, EMIT).ctx["storage"] = storage
    return server


@pytest.mark.no_auto_auth
@pytest.mark.parametrize(
    ("server", "static_token_status"), [(None, 401), (STATIC_TOKEN, 403)], indirect=["server"]
)
def test_only_the_owner_org_can_emit(emit_server, bridge, static_token_status):
    refused = [
        (None, 401, None),
        (jwt("user-no-org", None, "owner"), 403, ORG_REQUIRED_BODY),
        (jwt("user-b", "org-b", "owner"), 404, NOT_FOUND),
        (f"Bearer {STATIC_TOKEN}", static_token_status, None),
    ]
    for debate_id in (DA, DP):
        body = {"debate_id": debate_id, "details": "injected"}
        for token, status, expected in refused:
            got, payload = dispatch(emit_server, "POST", EMIT, token, body=body)
            assert got == status, (debate_id, payload)
            assert expected is None or payload == expected, (debate_id, payload)
    assert bridge.get_recent_events(50) == []

    token_a = jwt("user-a", ORG_A, "owner")
    status, payload = dispatch(emit_server, "POST", EMIT, token_a, body={"debate_id": DA})
    assert (status, payload) == (200, {"emitted": 1, "debate_id": DA})
    assert [event.debate_id for event in bridge.get_recent_events(50)] == [DA]
