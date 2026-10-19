"""Org boundary on the FastAPI v2 debate routes, with a real DebateStorage.

A debate's owner comes only from its stored ``org_id`` and ``is_public``
columns. A private debate with an org is readable and changeable only by that
org: another org gets the same 404 as a missing debate, an anonymous caller 401
and a caller without an org 403. Public debates stay readable by anyone and
debates with no recorded org keep their open reads, but only the owning org may
export or change a debate. A failed ownership lookup answers like a missing
debate.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aragora.rbac.models import AuthorizationContext
from aragora.resilience import CircuitOpenError
from aragora.server.fastapi import create_app
from aragora.server.postgres_storage import PostgresDebateStorage
from aragora.storage.debate_storage import DebateStorage
from aragora.storage.postgres_store import PoolExhaustedError
from tests.conftest import REQUIRES_POSTGRES, requires_postgres

_PG_URL = os.environ.get("DATABASE_URL", "")  # read at import: an autouse fixture unsets it
ORG_A, ORG_B = "org-a", "org-b"
NOT_FOUND = {"error": "Debate not found", "code": "not_found"}
_PERMISSIONS = {"debates:write", "debates:delete", "export:read", "analysis:read"}
_CALLERS = {
    "a": AuthorizationContext(user_id="user-a", org_id=ORG_A, permissions=_PERMISSIONS),
    "b": AuthorizationContext(user_id="user-b", org_id=ORG_B, permissions=_PERMISSIONS),
    "no-org": AuthorizationContext(user_id="user-x", org_id=None, permissions=_PERMISSIONS),
}
_ANONYMOUS = AuthorizationContext(user_id="anonymous", org_id=None)
READS = ("", "/messages", "/convergence", "/argument-graph", "/stats")
EXPORT = "/export/json"


def _debate(debate_id: str) -> dict[str, Any]:
    return {
        "id": debate_id,
        "task": f"Task {debate_id}",
        "agents": ["a1", "a2"],
        "rounds": [
            {
                "round_num": 1,
                "messages": [{"role": "proposal", "content": f"secret {debate_id}", "agent": "a1"}],
            }
        ],
        "consensus": {"confidence": 0.8, "final_answer": f"answer {debate_id}"},
    }


@pytest.fixture
def storage(tmp_path) -> DebateStorage:
    store = DebateStorage(str(tmp_path / "debates.db"))
    for debate_id, org_id in (
        ("deb-a", ORG_A),
        ("deb-b", ORG_B),
        ("deb-public", ORG_A),
        ("deb-legacy", None),
    ):
        store.save_dict(_debate(debate_id), org_id=org_id)
    assert store.set_public("deb-public", True)
    return store


@pytest.fixture
def client(storage, tmp_path, monkeypatch) -> TestClient:
    async def _auth(request: Any, require_auth: bool = False) -> AuthorizationContext:
        return _CALLERS.get(request.headers.get("X-Test-Caller", ""), _ANONYMOUS)

    monkeypatch.setattr("aragora.server.handlers.utils.auth.get_auth_context", _auth)

    # argument-graph and stats read debate traces from the nomic dir.
    class _Trace:
        def to_debate_result(self) -> SimpleNamespace:
            message = SimpleNamespace(agent="a1", content="claim", role="proposer", round=1)
            return SimpleNamespace(task="t", messages=[message], critiques=[])

    monkeypatch.setattr("aragora.debate.traces.DebateTrace.load", lambda path: _Trace())
    monkeypatch.setenv("ARAGORA_NOMIC_DIR", str(tmp_path))
    (tmp_path / "traces").mkdir()
    for debate_id in ("deb-a", "deb-b", "deb-public", "deb-legacy", "deb-missing"):
        (tmp_path / "traces" / f"{debate_id}.json").write_text("{}")

    app = create_app()
    app.state.context = {"storage": storage, "elo_system": None, "user_store": None}
    return TestClient(app, raise_server_exceptions=False)


def _call(client: TestClient, caller: str | None, method: str, path: str, **kwargs: Any):
    headers = {"X-Test-Caller": caller} if caller else {}
    return client.request(method, f"/api/v2/debates{path}", headers=headers, **kwargs)


def _get(client: TestClient, caller: str | None, path: str):
    return _call(client, caller, "GET", path)


def _ids(response) -> set[str]:
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["debates"]}


class TestPerDebateReads:
    def test_anonymous_and_org_less_callers_get_no_private_org_debate(self, client):
        for suffix in (*READS, EXPORT):
            anonymous = _get(client, None, f"/deb-a{suffix}")
            no_org = _get(client, "no-org", f"/deb-a{suffix}")

            assert anonymous.status_code == 401, suffix
            assert "deb-a" not in anonymous.text, suffix
            assert (no_org.status_code, no_org.json()["code"]) == (403, "org_required"), suffix

    def test_other_org_gets_the_missing_debate_404_everywhere(self, client):
        for suffix in (*READS, EXPORT):
            other = _get(client, "b", f"/deb-a{suffix}")
            missing = _get(client, "b", f"/deb-missing{suffix}")

            assert (other.status_code, other.json()) == (404, NOT_FOUND), suffix
            assert (missing.status_code, missing.json()) == (404, NOT_FOUND), suffix

    def test_owner_org_reads_every_route(self, client):
        for suffix in (*READS, EXPORT):
            response = _get(client, "a", f"/deb-a{suffix}")
            assert response.status_code == 200, (suffix, response.text)
        assert "secret deb-a" in _get(client, "a", "/deb-a/messages").text
        assert "secret deb-a" in _get(client, "a", f"/deb-a{EXPORT}").text

    def test_public_debate_stays_readable_by_anyone(self, client):
        for suffix in ("", "/messages", "/convergence"):
            assert _get(client, None, f"/deb-public{suffix}").status_code == 200, suffix
        for suffix in (*READS, EXPORT):
            assert _get(client, "b", f"/deb-public{suffix}").status_code == 200, suffix

    def test_debate_without_an_org_keeps_open_reads_but_is_not_exported(self, client):
        for suffix in ("", "/messages", "/convergence"):
            assert _get(client, None, f"/deb-legacy{suffix}").status_code == 200, suffix
        for suffix in READS:
            assert _get(client, "b", f"/deb-legacy{suffix}").status_code == 200, suffix
        for caller in ("a", "b"):
            export = _get(client, caller, f"/deb-legacy{EXPORT}")
            assert (export.status_code, export.json()) == (404, NOT_FOUND), caller


class TestList:
    def test_results_and_total_hold_only_debates_the_caller_may_read(self, client):
        expected = {
            None: {"deb-public", "deb-legacy"},
            "no-org": {"deb-public", "deb-legacy"},
            "a": {"deb-a", "deb-public", "deb-legacy"},
            "b": {"deb-b", "deb-public", "deb-legacy"},
        }
        for caller, ids in expected.items():
            response = _get(client, caller, "")
            assert _ids(response) == ids, caller
            assert response.json()["total"] == len(ids), caller

    def test_pages_never_include_another_orgs_private_debate(self, client):
        seen: set[str] = set()
        for offset in range(4):
            page = _get(client, "b", f"?limit=1&offset={offset}")
            assert page.json()["total"] == 3
            seen |= _ids(page)
        assert seen == {"deb-b", "deb-public", "deb-legacy"}


class TestWrites:
    def test_other_org_cannot_change_or_delete_and_gets_the_missing_404(self, client, storage):
        before = storage.get_by_id("deb-a")
        for target in ("/deb-a", "/deb-missing"):
            patch = _call(client, "b", "PATCH", target, json={"title": "taken"})
            delete = _call(client, "b", "DELETE", target)

            assert (patch.status_code, patch.json()) == (404, NOT_FOUND), target
            assert (delete.status_code, delete.json()) == (404, NOT_FOUND), target
        assert storage.get_by_id("deb-a") == before
        assert storage.get_read_access("deb-a") == ("deb-a", ORG_A, False)

    def test_public_and_org_less_debates_are_changed_by_no_one_else(self, client, storage):
        for target, callers in (("/deb-public", ("b",)), ("/deb-legacy", ("a", "b"))):
            for caller in callers:
                patch = _call(client, caller, "PATCH", target, json={"title": "taken"})
                delete = _call(client, caller, "DELETE", target)
                assert (patch.status_code, patch.json()) == (404, NOT_FOUND), (target, caller)
                assert (delete.status_code, delete.json()) == (404, NOT_FOUND), (target, caller)
        assert storage.get_by_id("deb-legacy") is not None
        assert storage.get_by_id("deb-public") is not None

    def test_anonymous_and_org_less_writes_are_refused(self, client, storage):
        assert _call(client, None, "PATCH", "/deb-a", json={"title": "x"}).status_code == 401
        assert _call(client, None, "DELETE", "/deb-a").status_code == 401
        no_org = _call(client, "no-org", "DELETE", "/deb-a")
        assert (no_org.status_code, no_org.json()["code"]) == (403, "org_required")
        assert storage.get_by_id("deb-a") is not None

    def test_owner_org_changes_and_deletes_its_debate(self, client, storage):
        patch = _call(client, "a", "PATCH", "/deb-a", json={"title": "renamed"})
        assert patch.status_code == 200, patch.text
        assert patch.json()["updated_fields"] == ["title"]

        delete = _call(client, "a", "DELETE", "/deb-a")
        assert delete.status_code == 200, delete.text
        assert storage.get_by_id("deb-a") is None


class _NoAccessLookup:
    """A store that serves debates but cannot say who owns them."""

    def __init__(self, inner: DebateStorage) -> None:
        self.get_debate = inner.get_debate
        self.delete_debate = inner.delete_debate


def _lookup_errors() -> list[Exception]:
    """Errors the SQLite and Postgres stores can raise while reading the owner row."""
    errors: list[Exception] = [
        sqlite3.OperationalError("database is locked"),
        PoolExhaustedError(5.0, 1.0),
        CircuitOpenError("postgres_pool", 30.0),
    ]
    try:
        from asyncpg import exceptions as pg
    except ImportError:
        return errors
    return [*errors, pg.ConnectionDoesNotExistError("closed"), pg.InterfaceError("pool closed")]


LOOKUP_FAILURES: list[Any] = ["no_row", "no_method", *_lookup_errors()]


class TestLookupFailure:
    @pytest.mark.parametrize(
        "failure", LOOKUP_FAILURES, ids=lambda f: str(f) if isinstance(f, str) else type(f).__name__
    )
    def test_unknown_owner_answers_like_a_missing_debate(
        self, client, storage, failure, monkeypatch
    ):
        if failure == "no_method":
            client.app.state.context["storage"] = _NoAccessLookup(storage)
        else:

            def _lookup(debate_id: str) -> Any:
                if isinstance(failure, Exception):
                    raise failure
                return None

            monkeypatch.setattr(storage, "get_read_access", _lookup)

        for suffix in (*READS, EXPORT):
            response = _get(client, "a", f"/deb-a{suffix}")
            assert (response.status_code, response.json()) == (404, NOT_FOUND), suffix
        delete = _call(client, "a", "DELETE", "/deb-a")
        assert (delete.status_code, delete.json()) == (404, NOT_FOUND)
        assert DebateStorage.get_by_id(storage, "deb-a") is not None

    def test_list_without_a_visibility_query_lists_nothing(self, client, storage):
        client.app.state.context["storage"] = _NoAccessLookup(storage)

        response = _get(client, "a", "")

        assert (_ids(response), response.json()["total"]) == (set(), 0)


@pytest.mark.parametrize(
    "engine",
    [
        "sqlite",
        pytest.param(
            "postgresql", marks=pytest.mark.skipif(requires_postgres, reason=REQUIRES_POSTGRES)
        ),
    ],
)
def test_store_reports_owner_and_lists_what_each_caller_may_read(engine, tmp_path):
    rows = (("deb-a", ORG_A), ("deb-b", ORG_B), ("deb-public", ORG_A), ("deb-legacy", None))
    readable = {
        None: {"deb-public", "deb-legacy"},
        ORG_A: {"deb-a", "deb-public", "deb-legacy"},
        ORG_B: {"deb-b", "deb-public", "deb-legacy"},
    }
    if engine == "sqlite":
        store = DebateStorage(str(tmp_path / "debates.db"))
        for debate_id, org_id in rows:
            store.save_dict(_debate(debate_id), org_id=org_id)
        store.set_public("deb-public", True)
        access = {debate_id: store.get_read_access(debate_id) for debate_id, _ in rows}
        missing = store.get_read_access("deb-missing")
        listed = {
            org: ({m.debate_id for m in store.list_readable(10, 0, org)}, store.count_readable(org))
            for org in readable
        }
    else:
        access, missing, listed = asyncio.run(_postgres_scenario(rows, list(readable)))

    assert access == {
        "deb-a": ("deb-a", ORG_A, False),
        "deb-b": ("deb-b", ORG_B, False),
        "deb-public": ("deb-public", ORG_A, True),
        "deb-legacy": ("deb-legacy", None, False),
    }
    assert missing is None
    assert listed == {org: (ids, len(ids)) for org, ids in readable.items()}


async def _postgres_scenario(rows: Any, orgs: list[str | None]) -> tuple[Any, Any, Any]:
    """Run the store checks in a throwaway schema of the ``DATABASE_URL`` database."""
    import asyncpg

    schema = f"debate_boundary_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(_PG_URL)
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    pool = await asyncpg.create_pool(
        _PG_URL, min_size=1, max_size=2, server_settings={"search_path": schema}
    )
    try:
        store = PostgresDebateStorage(pool, use_resilient=False)
        await store.initialize()
        for debate_id, org_id in rows:
            await store.save_dict_async(_debate(debate_id), org_id=org_id)
        await store.set_public_async("deb-public", True)
        access = {debate_id: await store.get_read_access_async(debate_id) for debate_id, _ in rows}
        missing = await store.get_read_access_async("deb-missing")
        listed = {}
        for org in orgs:
            page = await store.list_readable_async(10, 0, org)
            listed[org] = ({m.debate_id for m in page}, await store.count_readable_async(org))
        return access, missing, listed
    finally:
        await pool.close()
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()
