"""Debate document context and decision-integrity snapshots stay inside the debate org.

The arena cases go through the real server path: ``DebateConfig`` ->
``DebateFactory.create_arena`` -> ``ArenaBuilder`` -> ``Arena`` ->
``ContextGatherer``, against a real ``DocumentStore`` on ``tmp_path`` and the
offline ``demo`` agents (no provider calls).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from aragora.documents.parsing import DocumentStore, parse_document
from aragora.pipeline.decision_integrity import (
    build_decision_integrity_package,
    capture_context_snapshot,
)
from aragora.pipeline.decision_integrity_utils import build_decision_integrity_payload
from aragora.rbac.models import AuthorizationContext
from aragora.server.debate_factory import DebateConfig, DebateFactory

TASK = "Design a rate limiter for the billing gateway"
A_SENTINEL = "ZEBRACORN-A-7731"
U_SENTINEL = "UNOWNED-QUOKKA-0042"


@pytest.fixture
def docs(tmp_path):
    store = DocumentStore(tmp_path / "documents")
    # A's and the unknown-owner document match the task better than B's, so a
    # relevance listing over every document would pick them first.
    a_doc = parse_document(
        f"{A_SENTINEL} rate limiter billing gateway design limiter gateway".encode(),
        "a-confidential-rate-limiter.md",
        org_id="org-a",
        created_by="user-a",
    )
    u_doc = parse_document(
        f"{U_SENTINEL} rate limiter billing gateway design limiter".encode(),
        "unowned-rate-limiter.md",
    )
    b_doc = parse_document(b"bravo notes on a limiter", "b-notes.md", org_id="org-b")
    for doc in (a_doc, u_doc, b_doc):
        store.add(doc)
    return SimpleNamespace(store=store, a=a_doc, u=u_doc, b=b_doc)


def _arena(store, *, org_id, documents=()):
    config = DebateConfig(
        question=TASK,
        agents_str="demo,demo",
        rounds=1,
        documents=list(documents),
        org_id=org_id,
        auto_trim_unavailable=False,
        enable_verticals=False,
    )
    return DebateFactory(document_store=store).create_arena(config, enable_rlm_training=False)


async def _document_context(arena) -> str:
    return await arena.context_gatherer.gather_document_store_context(TASK) or ""


def _assert_no_foreign(text: str) -> None:
    for foreign in (A_SENTINEL, "a-confidential-rate-limiter.md", U_SENTINEL, "unowned-"):
        assert foreign not in text


@pytest.mark.asyncio
async def test_no_ids_relevance_listing_uses_only_the_debate_org(docs):
    context = await _document_context(_arena(docs.store, org_id="org-b"))

    assert "## DOCUMENT CONTEXT" in context
    assert "b-notes.md" in context
    _assert_no_foreign(context)


@pytest.mark.asyncio
async def test_explicit_cross_org_id_is_dropped_as_missing(docs):
    only_a = await _document_context(_arena(docs.store, org_id="org-b", documents=[docs.a.id]))
    mixed = await _document_context(
        _arena(docs.store, org_id="org-b", documents=[docs.a.id, docs.b.id])
    )

    assert only_a == ""
    assert "b-notes.md" in mixed
    _assert_no_foreign(mixed)


@pytest.mark.asyncio
async def test_unknown_owner_document_is_never_used(docs):
    for org in ("org-a", "org-b"):
        explicit = await _document_context(_arena(docs.store, org_id=org, documents=[docs.u.id]))
        listing = await _document_context(_arena(docs.store, org_id=org))
        assert explicit == ""
        assert U_SENTINEL not in listing
        assert "unowned-" not in listing


@pytest.mark.asyncio
async def test_no_org_debate_gets_no_document_context(docs):
    listing = await _document_context(_arena(docs.store, org_id=None))
    explicit = await _document_context(
        _arena(docs.store, org_id=None, documents=[docs.a.id, docs.b.id, docs.u.id])
    )

    assert listing == ""
    assert explicit == ""


@pytest.mark.asyncio
async def test_same_org_owner_still_gets_its_documents(docs):
    listing = await _document_context(_arena(docs.store, org_id="org-a"))
    explicit = await _document_context(_arena(docs.store, org_id="org-a", documents=[docs.a.id]))

    for context in (listing, explicit):
        assert A_SENTINEL in context
        assert "a-confidential-rate-limiter.md" in context
        assert U_SENTINEL not in context


def _auth(org_id):
    return AuthorizationContext(user_id="user-x", org_id=org_id, roles={"member"})


@pytest.mark.asyncio
async def test_decision_integrity_snapshot_lists_only_the_caller_org(docs):
    as_b = await capture_context_snapshot(
        TASK, document_store=docs.store, auth_context=_auth("org-b")
    )
    as_a = await capture_context_snapshot(
        TASK, document_store=docs.store, auth_context=_auth("org-a")
    )
    no_org = await capture_context_snapshot(
        TASK, document_store=docs.store, auth_context=_auth(None)
    )
    anonymous = await capture_context_snapshot(TASK, document_store=docs.store)

    assert [item["id"] for item in as_b.document_items] == [docs.b.id]
    assert [item["id"] for item in as_a.document_items] == [docs.a.id]
    assert no_org.document_items == []
    assert anonymous.document_items == []


@pytest.mark.asyncio
async def test_decision_integrity_package_route_path_hides_other_org_documents(docs):
    debate = {"debate_id": "deb-b", "task": TASK, "final_answer": "Use a token bucket."}

    package = await build_decision_integrity_package(
        debate,
        include_receipt=False,
        include_plan=False,
        include_context=True,
        document_store=docs.store,
        auth_context=_auth("org-b"),
    )

    serialized = str(package.to_dict())
    assert [item["id"] for item in package.context_snapshot.document_items] == [docs.b.id]
    _assert_no_foreign(serialized)


@pytest.mark.asyncio
async def test_post_debate_integrity_payload_uses_the_arena_org(docs):
    result = SimpleNamespace(debate_id="deb-b", task=TASK, final_answer="Use a token bucket.")
    common = dict(
        result=result,
        debate_id="deb-b",
        decision_integrity={
            "include_receipt": False,
            "include_plan": False,
            "include_context": True,
        },
        document_store=docs.store,
    )

    as_b = await build_decision_integrity_payload(
        arena=SimpleNamespace(document_org_id="org-b"), **common
    )
    no_org = await build_decision_integrity_payload(arena=SimpleNamespace(), **common)

    assert [item["id"] for item in as_b["context_snapshot"]["document_items"]] == [docs.b.id]
    _assert_no_foreign(str(as_b))
    assert no_org["context_snapshot"]["document_items"] == []
