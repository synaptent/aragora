"""Constants and helpers shared by the debate write-isolation tests.

The ``storage`` fixture (``conftest.py``) seeds a private debate of org A
(``DA``), one of org B (``DB``), one with no recorded org (``DN``) and a public
debate of org A (``DP``). Requests are sent as A, as B, as a user without an
org and anonymously.
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from typing import Any

ORG_A = "org-a"
ORG_B = "org-b"
DA, DB, DN, DP = "deb-alpha-a", "deb-bravo-b", "deb-null-org", "deb-public-a"
DX = "deb-missing-x"
DA_TASK = "Write isolation topic alpha for org A only"
DB_TASK = "Write isolation topic bravo for org B"

NOT_FOUND = {"error": "Debate not found", "code": "not_found"}


def debate_record(debate_id: str, task: str) -> dict[str, Any]:
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


def _user(org_id: str | None, user_id: str, role: str = "owner") -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id, org_id=org_id, role=role, is_authenticated=True, authenticated=True
    )


ANON = SimpleNamespace(user_id=None, org_id=None, role=None, is_authenticated=False)
USER_A = _user(ORG_A, "user-a")
USER_B = _user(ORG_B, "user-b")
USER_NO_ORG = _user(None, "user-no-org")

# Caller, debate, expected status. Refusals of an owner-org write: another org's
# private and public debates, a debate with no org, a missing id, no user, no org.
REFUSALS = (
    (USER_B, DA, 404),
    (USER_B, DP, 404),
    (USER_A, DN, 404),
    (USER_B, DN, 404),
    (USER_B, DX, 404),
    (ANON, DA, 401),
    (USER_NO_ORG, DA, 403),
)


class Request:
    """An HTTP request as handlers see it: method, headers, JSON body, RBAC context."""

    client_address = ("10.0.0.9", 4000)

    def __init__(self, method: str, user: Any, body: dict[str, Any] | None = None) -> None:
        from aragora.rbac.models import AuthorizationContext

        raw = json.dumps(body if body is not None else {}).encode()
        self.command = method
        self.headers = {
            "Host": "localhost",
            "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
        }
        self.rfile = io.BytesIO(raw)
        self._auth_context = (
            AuthorizationContext(user_id=user.user_id, org_id=user.org_id, roles={user.role})
            if user.is_authenticated
            else None
        )


def route(handler: Any, method: str, path: str, request: Request):
    """Dispatch like the handler registry: the verb method, then ``handle`` if it passes."""
    verb = {"POST": "handle_post", "PATCH": "handle_patch", "DELETE": "handle_delete"}
    result = getattr(handler, verb[method])(path, {}, request) if method in verb else None
    if result is None:
        result = handler.handle(path, {}, request)
    return result


def act_as(monkeypatch: Any, user: Any) -> None:
    monkeypatch.setattr(
        "aragora.billing.jwt_auth.extract_user_from_request",
        lambda request, user_store=None: user,
    )


def body_of(result: Any) -> Any:
    raw = result.body
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def text_of(result: Any) -> str:
    raw = result.body
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
