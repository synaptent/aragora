"""Fixtures for the workspace route tests, which run through the real server dispatch."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import aragora.pipeline.plan_store as plan_store_module
import aragora.storage.receipt_store as receipt_store_module
from aragora.decision_workspace import store as workspace_store
from aragora.documents.parsing import DocumentStore
from aragora.pipeline.plan_store import PlanStore
from aragora.storage.receipt_store import ReceiptStore
from tests.decision_workspace.routes import AGENTS, BASE, ORG_A, ORG_B
from tests.server.rbac_dispatch import STATIC_TOKEN, build_server, handler_for, isolate_auth, jwt


@pytest.fixture(scope="module")
def server():
    return build_server()


@pytest.fixture(params=["token", "stock"])
def mode(request, monkeypatch):
    """Run with ``ARAGORA_API_TOKEN`` set (central RBAC gate active) and without."""
    isolate_auth(monkeypatch, STATIC_TOKEN if request.param == "token" else None)
    return request.param


@pytest.fixture
def users(mode):
    # Tokens are signed with the JWT secret that ``mode`` installs.
    return SimpleNamespace(
        a=jwt("user-a", ORG_A, "owner"),
        a_member=jwt("user-a-member", ORG_A, "member"),
        a_viewer=jwt("user-a-viewer", ORG_A, "viewer"),
        b=jwt("user-b", ORG_B, "owner"),
        no_org=jwt("user-no-org", None, "owner"),
    )


@pytest.fixture
def env(server, tmp_path, monkeypatch):
    plans_db = tmp_path / "plans.db"
    monkeypatch.setattr(plan_store_module, "_store", PlanStore(str(plans_db)))
    monkeypatch.setattr(workspace_store, "_stores", {})
    workspace_store.get_workspace_store(str(plans_db))
    monkeypatch.setattr(
        receipt_store_module, "_receipt_store", ReceiptStore(db_path=tmp_path / "receipts.db")
    )
    documents = DocumentStore(tmp_path / "documents")
    monkeypatch.setitem(handler_for(server, f"{BASE}/decisions").ctx, "document_store", documents)
    monkeypatch.setenv("ARAGORA_WORKSPACE_AGENTS", AGENTS)
    return SimpleNamespace(plans_db=plans_db, documents=documents)
