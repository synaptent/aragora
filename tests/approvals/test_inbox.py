from __future__ import annotations

import builtins
from unittest.mock import patch

from aragora.approvals import settlement_inbox as settlement_inbox_module
from aragora.approvals.inbox import DEFAULT_APPROVAL_SOURCES, collect_pending_approvals
from aragora.approvals.settlement_inbox import (
    collect_pending_settlement_approvals,
    refresh_settlement_approval_cache,
)
from aragora.gauntlet.signing import HMACSigner, ReceiptSigner
from aragora.inbox.trust_wedge import (
    ActionIntent,
    InboxTrustWedgeService,
    InboxTrustWedgeStore,
    TriageDecision,
)
from aragora.services.email_actions import EmailActionsService


def test_default_approval_sources_include_inbox_wedge():
    assert "inbox_wedge" in DEFAULT_APPROVAL_SOURCES


def test_default_approval_sources_do_not_include_settlement_without_flag():
    assert "settlement" not in DEFAULT_APPROVAL_SOURCES


def test_collect_pending_approvals_includes_inbox_wedge_receipts(tmp_path):
    signer = ReceiptSigner(HMACSigner(secret_key=b"\x04" * 32, key_id="approval-test-key"))
    store = InboxTrustWedgeStore(db_path=str(tmp_path / "approvals-wedge.db"))
    service = InboxTrustWedgeService(
        email_actions_service=EmailActionsService(),
        store=store,
        signer=signer,
    )
    envelope = service.create_receipt(
        ActionIntent.create(
            provider="gmail",
            user_id="user-1",
            message_id="msg-1",
            action="archive",
            content_hash=ActionIntent.compute_content_hash("subject", "body"),
            synthesized_rationale="Archive promotional noise",
            confidence=0.9,
            provider_route="openrouter-fallback",
            debate_id="debate-approval-1",
        ),
        TriageDecision.create(
            final_action="archive",
            confidence=0.9,
            dissent_summary="critic asked for a quick human check",
        ),
    )

    with patch("aragora.inbox.get_inbox_trust_wedge_store", return_value=store):
        approvals = collect_pending_approvals(limit=10, sources=["inbox_wedge"])

    store.close()

    assert len(approvals) == 1
    item = approvals[0]
    assert item["id"] == envelope.receipt.receipt_id
    assert item["kind"] == "inbox_wedge"
    assert item["metadata"]["message_id"] == "msg-1"
    assert item["actions"]["approve"]["path"].endswith(
        f"/api/v1/inbox/wedge/receipts/{envelope.receipt.receipt_id}/review"
    )
    assert item["actions"]["approve"]["body"] == {"choice": "approve", "execute": True}


def test_collect_pending_approvals_skips_non_mapping_gateway_records():
    class GatewayStore:
        def list_approvals(self, *, limit: int, offset: int):
            return ([object()], 1)

    with patch(
        "aragora.server.handlers.openclaw.store._get_store",
        return_value=GatewayStore(),
    ):
        approvals = collect_pending_approvals(limit=10, sources=["gateway"])

    assert approvals == []


def _settlement_packet() -> dict:
    return {
        "generated_at": "2026-07-04T18:00:00+00:00",
        "entries": [
            {
                "pr_number": 7736,
                "title": "touch merge gate",
                "url": "https://github.com/synaptent/aragora/pull/7736",
                "head_sha": "abc123def4567890",
                "tier": 4,
                "tier_name": "tier_4_preapproval_required",
                "status": "human_preapproval_required",
                "verdict": "tier_4_human_preapproval_required",
                "checks_summary": "all required checks green",
                "requires_human_risk_settlement": True,
                "requires_human_preapproval": True,
                "unresolved_dissent": False,
                "counted_model_families": ["claude", "openai"],
                "reviewer_signals": [],
                "dogfood_evidence": [{"source": "local"}],
                "reasons": [
                    "workflow/deploy/destructive surface touched",
                    "Tier 4 human preapproval required",
                ],
                "settlement_creator_pin": {
                    "trusted_creator": "scarmani",
                    "checked": False,
                },
            },
            {
                "pr_number": 8827,
                "title": "needs quorum",
                "url": "https://github.com/synaptent/aragora/pull/8827",
                "head_sha": "def456",
                "tier": 2,
                "tier_name": "tier_2_live_automation",
                "status": "needs_model_review_quorum",
                "verdict": "collect_model_quorum_before_merge",
                "checks_summary": "merge-quorum failing",
                "requires_human_risk_settlement": False,
                "requires_human_preapproval": False,
                "unresolved_dissent": False,
                "reasons": ["model quorum incomplete: 0/2 signal(s)"],
            },
            {
                "pr_number": 8845,
                "title": "missing exact head",
                "url": "https://github.com/synaptent/aragora/pull/8845",
                "head_sha": "",
                "tier": 3,
                "tier_name": "tier_3_human_risk",
                "status": "human_risk_settlement_required",
                "verdict": "human_risk_settlement_required",
                "checks_summary": "all required checks green",
                "requires_human_risk_settlement": True,
                "requires_human_preapproval": False,
                "unresolved_dissent": False,
                "reasons": ["missing exact head"],
            },
        ],
    }


def test_collect_pending_settlement_approvals_filters_to_human_boundary():
    calls = []

    def merge_packet_builder(**kwargs):
        calls.append(kwargs)
        return _settlement_packet()

    approvals = collect_pending_settlement_approvals(
        limit=10,
        repo="synaptent/aragora",
        merge_packet_builder=merge_packet_builder,
    )

    assert len(approvals) == 1
    item = approvals[0]
    assert item["id"] == "settlement-pr-7736-abc123def456"
    assert item["kind"] == "settlement"
    assert item["status"] == "pending"
    assert item["metadata"]["pr_number"] == 7736
    assert item["metadata"]["head_sha"] == "abc123def4567890"
    assert item["metadata"]["settlement_kind"] == "tier4_human_preapproval"
    assert item["metadata"]["counted_model_families"] == ["claude", "openai"]
    assert item["actions"]["approve"]["implemented"] is False
    assert item["actions"]["approve"]["cli_preview"][:5] == [
        "python3",
        "-m",
        "aragora.cli.main",
        "review-queue",
        "record-settlement",
    ]
    assert "--post-github-status" in item["actions"]["approve"]["cli_preview"]
    assert calls[0]["repo_override"] == "synaptent/aragora"
    assert calls[0]["limit"] == 10
    assert calls[0]["execute_reviewers"] is False


def test_collect_pending_settlement_approvals_bounds_packet_scan_limit():
    calls = []

    def merge_packet_builder(**kwargs):
        calls.append(kwargs)
        return _settlement_packet()

    approvals = collect_pending_settlement_approvals(
        limit=500,
        repo="synaptent/aragora",
        merge_packet_builder=merge_packet_builder,
    )

    assert len(approvals) == 1
    assert calls[0]["limit"] == 20


def test_collect_pending_settlement_approvals_cache_only_cold_path_does_not_scan(monkeypatch):
    settlement_inbox_module._PACKET_CACHE.clear()

    from aragora.cli.commands import review_queue

    def forbidden_scan(**kwargs):
        raise AssertionError(f"unexpected cold scan: {kwargs}")

    monkeypatch.setattr(review_queue, "_build_merge_authorization_packet", forbidden_scan)
    monkeypatch.delenv("ARAGORA_SETTLEMENT_INBOX_ALLOW_SYNC_REFRESH", raising=False)

    approvals = collect_pending_settlement_approvals(
        limit=10,
        repo="synaptent/aragora",
        allow_sync_refresh=False,
    )

    assert approvals == []


def test_collect_pending_settlement_approvals_uses_warmed_cache(monkeypatch):
    settlement_inbox_module._PACKET_CACHE.clear()
    calls = []

    def merge_packet_builder(**kwargs):
        calls.append(kwargs)
        return _settlement_packet()

    refresh_settlement_approval_cache(
        limit=10,
        repo="synaptent/aragora",
        pr_refs=["7736"],
        merge_packet_builder=merge_packet_builder,
    )

    from aragora.cli.commands import review_queue

    def forbidden_scan(**kwargs):
        raise AssertionError(f"unexpected cold scan: {kwargs}")

    monkeypatch.setattr(review_queue, "_build_merge_authorization_packet", forbidden_scan)
    monkeypatch.delenv("ARAGORA_SETTLEMENT_INBOX_ALLOW_SYNC_REFRESH", raising=False)
    monkeypatch.setenv("ARAGORA_SETTLEMENT_INBOX_PR_REFS", "7736")

    approvals = collect_pending_settlement_approvals(
        limit=5,
        repo="synaptent/aragora",
        allow_sync_refresh=False,
    )

    assert len(approvals) == 1
    assert approvals[0]["metadata"]["pr_number"] == 7736
    assert calls[0]["limit"] == 10
    assert calls[0]["pr_refs"] == ["7736"]


def test_collect_pending_settlement_approvals_does_not_use_expired_cache(monkeypatch):
    settlement_inbox_module._PACKET_CACHE.clear()
    monkeypatch.setenv("ARAGORA_SETTLEMENT_INBOX_PR_REFS", "7736")
    monkeypatch.setenv("ARAGORA_SETTLEMENT_INBOX_CACHE_TTL_SECONDS", "1")

    def merge_packet_builder(**kwargs):
        return _settlement_packet()

    refresh_settlement_approval_cache(
        limit=10,
        repo="synaptent/aragora",
        pr_refs=["7736"],
        merge_packet_builder=merge_packet_builder,
    )
    for cache_key, (_timestamp, packet) in list(settlement_inbox_module._PACKET_CACHE.items()):
        settlement_inbox_module._PACKET_CACHE[cache_key] = (0.0, packet)

    from aragora.cli.commands import review_queue

    def forbidden_scan(**kwargs):
        raise AssertionError(f"unexpected cold scan: {kwargs}")

    monkeypatch.setattr(review_queue, "_build_merge_authorization_packet", forbidden_scan)

    approvals = collect_pending_settlement_approvals(
        limit=5,
        repo="synaptent/aragora",
        allow_sync_refresh=False,
    )

    assert approvals == []
    assert settlement_inbox_module._PACKET_CACHE == {}


def test_collect_pending_settlement_approvals_cache_is_scoped_to_pr_refs(monkeypatch):
    settlement_inbox_module._PACKET_CACHE.clear()

    def merge_packet_builder(**kwargs):
        return _settlement_packet()

    refresh_settlement_approval_cache(
        limit=10,
        repo="synaptent/aragora",
        pr_refs=["7736"],
        merge_packet_builder=merge_packet_builder,
    )

    from aragora.cli.commands import review_queue

    def forbidden_scan(**kwargs):
        raise AssertionError(f"unexpected cold scan: {kwargs}")

    monkeypatch.setattr(review_queue, "_build_merge_authorization_packet", forbidden_scan)
    monkeypatch.setenv("ARAGORA_SETTLEMENT_INBOX_PR_REFS", "8845")

    approvals = collect_pending_settlement_approvals(
        limit=5,
        repo="synaptent/aragora",
        allow_sync_refresh=False,
    )

    assert approvals == []


def test_collect_pending_settlement_approvals_queue_scan_reuses_larger_warmed_cache(
    monkeypatch,
):
    settlement_inbox_module._PACKET_CACHE.clear()
    monkeypatch.setenv("ARAGORA_SETTLEMENT_INBOX_ALLOW_BOUNDED_QUEUE_SCAN", "1")
    monkeypatch.setenv("ARAGORA_SETTLEMENT_INBOX_PACKET_LIMIT", "20")

    def merge_packet_builder(**kwargs):
        assert kwargs["pr_refs"] == []
        assert kwargs["limit"] == 20
        return _settlement_packet()

    refresh_settlement_approval_cache(
        limit=20,
        repo="synaptent/aragora",
        pr_refs=[],
        merge_packet_builder=merge_packet_builder,
    )

    from aragora.cli.commands import review_queue

    def forbidden_scan(**kwargs):
        raise AssertionError(f"unexpected cold scan: {kwargs}")

    monkeypatch.setattr(review_queue, "_build_merge_authorization_packet", forbidden_scan)

    approvals = collect_pending_settlement_approvals(
        limit=10,
        repo="synaptent/aragora",
        allow_sync_refresh=False,
    )

    assert [item["metadata"]["pr_number"] for item in approvals] == [7736]


def test_collect_pending_settlement_approvals_queue_scan_does_not_use_smaller_cache(
    monkeypatch,
):
    settlement_inbox_module._PACKET_CACHE.clear()
    monkeypatch.setenv("ARAGORA_SETTLEMENT_INBOX_ALLOW_BOUNDED_QUEUE_SCAN", "1")
    monkeypatch.setenv("ARAGORA_SETTLEMENT_INBOX_PACKET_LIMIT", "20")

    def merge_packet_builder(**kwargs):
        assert kwargs["pr_refs"] == []
        assert kwargs["limit"] == 10
        return _settlement_packet()

    refresh_settlement_approval_cache(
        limit=10,
        repo="synaptent/aragora",
        pr_refs=[],
        merge_packet_builder=merge_packet_builder,
    )

    from aragora.cli.commands import review_queue

    def forbidden_scan(**kwargs):
        raise AssertionError(f"unexpected cold scan: {kwargs}")

    monkeypatch.setattr(review_queue, "_build_merge_authorization_packet", forbidden_scan)

    approvals = collect_pending_settlement_approvals(
        limit=20,
        repo="synaptent/aragora",
        allow_sync_refresh=False,
    )

    assert approvals == []


def test_refresh_settlement_approval_cache_bounds_cache_entries(monkeypatch):
    settlement_inbox_module._PACKET_CACHE.clear()
    monkeypatch.setenv("ARAGORA_SETTLEMENT_INBOX_CACHE_MAX_ENTRIES", "2")

    def merge_packet_builder(**kwargs):
        return _settlement_packet()

    for ref in ["7736", "7737", "7738"]:
        refresh_settlement_approval_cache(
            limit=10,
            repo="synaptent/aragora",
            pr_refs=[ref],
            merge_packet_builder=merge_packet_builder,
        )

    assert len(settlement_inbox_module._PACKET_CACHE) == 2
    cached_ref_sets = [cache_key[2] for cache_key in settlement_inbox_module._PACKET_CACHE]
    assert cached_ref_sets == [("7737",), ("7738",)]


def test_collect_pending_settlement_approvals_preserves_settlement_context():
    def merge_packet_builder(**kwargs):
        return _settlement_packet()

    approvals = collect_pending_settlement_approvals(
        limit=10,
        repo="synaptent/aragora",
        review_queue_root="/tmp/review-queue",
        merge_packet_builder=merge_packet_builder,
    )

    item = approvals[0]
    approve = item["actions"]["approve"]
    reject = item["actions"]["reject"]
    assert ["--repo", "synaptent/aragora"] == approve["cli_preview"][-4:-2]
    assert ["--review-queue-root", "/tmp/review-queue"] == approve["cli_preview"][-2:]
    assert ["--repo", "synaptent/aragora"] == reject["cli_preview"][-4:-2]
    assert ["--review-queue-root", "/tmp/review-queue"] == reject["cli_preview"][-2:]
    assert approve["body"]["repo"] == "synaptent/aragora"
    assert approve["body"]["review_queue_root"] == "/tmp/review-queue"
    assert reject["body"]["decision"] == "request_changes"
    assert reject["body"]["reason"].startswith("Settlement Inbox rejection")


def test_collect_pending_approvals_explicit_settlement_source_requires_flag(monkeypatch):
    monkeypatch.delenv("ARAGORA_ENABLE_SETTLEMENT_APPROVAL_INBOX", raising=False)
    called = False

    def fake_collect(limit):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(
        "aragora.approvals.settlement_inbox.collect_pending_settlement_approvals",
        fake_collect,
    )

    approvals = collect_pending_approvals(limit=5, sources=["settlement"])

    assert approvals == []
    assert called is False


def test_collect_pending_approvals_settlement_import_failure_is_best_effort(monkeypatch):
    monkeypatch.setenv("ARAGORA_ENABLE_SETTLEMENT_APPROVAL_INBOX", "1")
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "aragora.approvals.settlement_inbox":
            raise ImportError("settlement source unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    approvals = collect_pending_approvals(limit=5, sources=["settlement"])

    assert approvals == []


def test_collect_pending_approvals_settlement_runtime_import_failure_is_best_effort(
    monkeypatch,
):
    monkeypatch.setenv("ARAGORA_ENABLE_SETTLEMENT_APPROVAL_INBOX", "1")

    def fake_collect(limit):
        assert limit == 5
        raise ImportError("review queue unavailable")

    monkeypatch.setattr(
        "aragora.approvals.settlement_inbox.collect_pending_settlement_approvals",
        fake_collect,
    )

    approvals = collect_pending_approvals(limit=5, sources=["settlement"])

    assert approvals == []


def test_collect_pending_approvals_explicit_settlement_source_with_flag(monkeypatch):
    monkeypatch.setenv("ARAGORA_ENABLE_SETTLEMENT_APPROVAL_INBOX", "1")

    def fake_collect(limit):
        assert limit == 5
        return [
            {
                "id": "settlement-pr-1-head",
                "kind": "settlement",
                "status": "pending",
                "title": "Settlement approval",
                "description": "Needs human risk settlement",
                "requested_at": "2026-07-04T18:00:00+00:00",
                "requested_by": "review-queue merge-packet",
                "metadata": {"pr_number": 1},
                "actions": {"approve": {"method": "POST"}},
            }
        ]

    monkeypatch.setattr(
        "aragora.approvals.settlement_inbox.collect_pending_settlement_approvals",
        fake_collect,
    )

    approvals = collect_pending_approvals(limit=5, sources=["settlement"])

    assert [item["id"] for item in approvals] == ["settlement-pr-1-head"]
    assert approvals[0]["metadata"]["pr_number"] == 1


def test_collect_pending_approvals_sorts_settlement_iso_timestamps(monkeypatch):
    monkeypatch.setenv("ARAGORA_ENABLE_SETTLEMENT_APPROVAL_INBOX", "1")

    def fake_collect(limit):
        assert limit == 2
        return [
            {
                "id": "settlement-pr-1-old",
                "kind": "settlement",
                "status": "pending",
                "title": "Old settlement approval",
                "description": "Older",
                "requested_at": "2026-07-04T17:00:00+00:00",
                "requested_by": "review-queue merge-packet",
                "metadata": {"pr_number": 1},
                "actions": {},
            },
            {
                "id": "settlement-pr-2-new",
                "kind": "settlement",
                "status": "pending",
                "title": "New settlement approval",
                "description": "Newer",
                "requested_at": "2026-07-04T18:00:00+00:00",
                "requested_by": "review-queue merge-packet",
                "metadata": {"pr_number": 2},
                "actions": {},
            },
        ]

    monkeypatch.setattr(
        "aragora.approvals.settlement_inbox.collect_pending_settlement_approvals",
        fake_collect,
    )

    approvals = collect_pending_approvals(limit=2, sources=["settlement"])

    assert [item["id"] for item in approvals] == [
        "settlement-pr-2-new",
        "settlement-pr-1-old",
    ]


def test_collect_pending_approvals_default_settlement_source_is_flag_gated(monkeypatch):
    monkeypatch.delenv("ARAGORA_ENABLE_SETTLEMENT_APPROVAL_INBOX", raising=False)
    called = False

    def fake_collect(limit):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(
        "aragora.approvals.settlement_inbox.collect_pending_settlement_approvals",
        fake_collect,
    )

    collect_pending_approvals(limit=1, sources=None)

    assert called is False


def test_collect_pending_approvals_default_settlement_source_can_be_enabled(monkeypatch):
    monkeypatch.setenv("ARAGORA_ENABLE_SETTLEMENT_APPROVAL_INBOX", "1")
    called = False

    def fake_collect(limit):
        nonlocal called
        called = True
        assert limit == 1
        return []

    monkeypatch.setattr(
        "aragora.approvals.settlement_inbox.collect_pending_settlement_approvals",
        fake_collect,
    )

    collect_pending_approvals(limit=1, sources=None)

    assert called is True
