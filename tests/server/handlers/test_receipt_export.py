"""
Tests for aragora.server.handlers.receipt_export - Receipt Export Handlers.

Tests cover:
- ReceiptExportHandler: instantiation, can_handle
- GET /api/v1/receipts/:id/export: json, html, pdf formats
- Invalid format parameter
- Missing receipt ID in path
- Receipt not found (neither store nor ctx)
- Receipt found in ctx fallback
- _VALID_FORMATS constant
- handle() routing: returns None for non-matching paths
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.receipt_export import (
    ReceiptExportHandler,
    _VALID_FORMATS,
)
from aragora.server.handlers.utils.responses import HandlerResult


# ===========================================================================
# Helpers
# ===========================================================================


def _parse_body(result: HandlerResult) -> dict[str, Any]:
    """Parse JSON body from HandlerResult."""
    return json.loads(result.body)


def _make_mock_handler(
    method: str = "GET",
    body: bytes = b"",
    content_type: str = "application/json",
) -> MagicMock:
    """Create a mock HTTP handler object."""
    handler = MagicMock()
    handler.command = method
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {
        "Content-Length": str(len(body)),
        "Content-Type": content_type,
        "Host": "localhost:8080",
    }
    handler.rfile = MagicMock()
    handler.rfile.read.return_value = body
    return handler


# ===========================================================================
# Mock Objects
# ===========================================================================


class MockReceipt:
    """Mock receipt object."""

    def __init__(self, receipt_id: str = "receipt-001"):
        self.id = receipt_id
        self.debate_id = "debate-001"
        self.decision = "Approved"
        self.timestamp = "2026-02-14T10:00:00Z"
        self.hash = "abc123"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "debate_id": self.debate_id,
            "decision": self.decision,
            "timestamp": self.timestamp,
            "hash": self.hash,
        }


class MockReceiptStore:
    """Mock receipt store."""

    def __init__(self, receipts: dict[str, MockReceipt] | None = None):
        self._receipts = receipts or {}

    def get(self, receipt_id: str) -> MockReceipt | None:
        return self._receipts.get(receipt_id)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def handler():
    """Create a ReceiptExportHandler with no store."""
    with patch(
        "aragora.server.handlers.receipt_export._get_receipt_store",
        return_value=None,
    ):
        h = ReceiptExportHandler(ctx={})
        return h


@pytest.fixture
def handler_with_store():
    """Create a ReceiptExportHandler with a populated store."""
    store = MockReceiptStore({"receipt-001": MockReceipt("receipt-001")})
    with patch(
        "aragora.server.handlers.receipt_export._get_receipt_store",
        return_value=store,
    ):
        h = ReceiptExportHandler(ctx={})
        yield h


@pytest.fixture
def handler_with_ctx_store():
    """Create a ReceiptExportHandler with receipt in ctx."""
    receipt = MockReceipt("receipt-ctx")
    ctx = {"receipt_store": {"receipt-ctx": receipt}}
    with patch(
        "aragora.server.handlers.receipt_export._get_receipt_store",
        return_value=None,
    ):
        h = ReceiptExportHandler(ctx=ctx)
        yield h


# ===========================================================================
# Test Instantiation and Basics
# ===========================================================================


class TestReceiptExportHandlerBasics:
    """Basic instantiation and attribute tests."""

    def test_instantiation(self, handler):
        assert handler is not None
        assert isinstance(handler, ReceiptExportHandler)

    def test_valid_formats(self):
        assert "json" in _VALID_FORMATS
        assert "html" in _VALID_FORMATS
        assert "pdf" in _VALID_FORMATS
        assert len(_VALID_FORMATS) == 3


# ===========================================================================
# Test can_handle
# ===========================================================================


class TestCanHandle:
    """Tests for can_handle routing logic."""

    def test_can_handle_export_path(self, handler):
        assert handler.can_handle("/api/v1/receipts/receipt-001/export") is True

    def test_can_handle_different_id(self, handler):
        assert handler.can_handle("/api/v1/receipts/abc-xyz/export") is True

    def test_cannot_handle_without_export(self, handler):
        assert handler.can_handle("/api/v1/receipts/receipt-001") is False

    def test_cannot_handle_unrelated(self, handler):
        assert handler.can_handle("/api/v1/debates/123") is False

    def test_cannot_handle_partial_prefix(self, handler):
        assert handler.can_handle("/api/v1/receipt/123/export") is False


# ===========================================================================
# Test JSON Export
# ===========================================================================


class TestJsonExport:
    """Tests for JSON format export."""

    def test_export_json_success(self, handler_with_store):
        mock_handler = _make_mock_handler()
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=MockReceiptStore({"receipt-001": MockReceipt("receipt-001")}),
        ):
            result = handler_with_store.handle(
                "/api/v1/receipts/receipt-001/export",
                {"format": "json"},
                mock_handler,
            )
            assert result is not None
            assert result.status_code == 200
            data = _parse_body(result)
            assert data["id"] == "receipt-001"
            assert data["decision"] == "Approved"

    def test_export_default_format_is_json(self, handler_with_store):
        mock_handler = _make_mock_handler()
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=MockReceiptStore({"receipt-001": MockReceipt("receipt-001")}),
        ):
            result = handler_with_store.handle(
                "/api/v1/receipts/receipt-001/export",
                {},
                mock_handler,
            )
            assert result is not None
            assert result.status_code == 200
            data = _parse_body(result)
            assert "id" in data


# ===========================================================================
# Test HTML Export
# ===========================================================================


class TestHtmlExport:
    """Tests for HTML format export."""

    def test_export_html_success(self, handler_with_store):
        mock_handler = _make_mock_handler()
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=MockReceiptStore({"receipt-001": MockReceipt("receipt-001")}),
        ):
            with patch(
                "aragora.gauntlet.export.receipt_to_html",
                return_value="<html><body>Receipt</body></html>",
            ):
                result = handler_with_store.handle(
                    "/api/v1/receipts/receipt-001/export",
                    {"format": "html"},
                    mock_handler,
                )
                assert result is not None
                assert result.status_code == 200
                assert result.content_type == "text/html; charset=utf-8"
                assert b"Receipt" in result.body
                assert result.headers["Content-Disposition"].startswith("attachment")


# ===========================================================================
# Test PDF Export
# ===========================================================================


class TestPdfExport:
    """Tests for PDF format export."""

    def test_export_pdf_success(self, handler_with_store):
        mock_handler = _make_mock_handler()
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=MockReceiptStore({"receipt-001": MockReceipt("receipt-001")}),
        ):
            with patch(
                "aragora.gauntlet.export.receipt_to_pdf",
                return_value=b"%PDF-1.4 fake content",
            ):
                result = handler_with_store.handle(
                    "/api/v1/receipts/receipt-001/export",
                    {"format": "pdf"},
                    mock_handler,
                )
                assert result is not None
                assert result.status_code == 200
                assert result.content_type == "application/pdf"
                assert b"%PDF" in result.body
                assert result.headers["Content-Disposition"].startswith("attachment")


# ===========================================================================
# Test Invalid Format
# ===========================================================================


class TestInvalidFormat:
    """Tests for invalid format parameter."""

    def test_invalid_format(self, handler_with_store):
        mock_handler = _make_mock_handler()
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=MockReceiptStore({"receipt-001": MockReceipt("receipt-001")}),
        ):
            result = handler_with_store.handle(
                "/api/v1/receipts/receipt-001/export",
                {"format": "xml"},
                mock_handler,
            )
            assert result is not None
            assert result.status_code == 400
            data = _parse_body(result)
            assert "xml" in data["error"].lower() or "invalid" in data["error"].lower()

    def test_invalid_format_csv(self, handler_with_store):
        mock_handler = _make_mock_handler()
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=MockReceiptStore({"receipt-001": MockReceipt("receipt-001")}),
        ):
            result = handler_with_store.handle(
                "/api/v1/receipts/receipt-001/export",
                {"format": "csv"},
                mock_handler,
            )
            assert result is not None
            assert result.status_code == 400


# ===========================================================================
# Test Receipt Not Found
# ===========================================================================


class TestReceiptNotFound:
    """Tests for receipt not found scenarios."""

    def test_receipt_not_in_store(self, handler):
        mock_handler = _make_mock_handler()
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=None,
        ):
            result = handler.handle(
                "/api/v1/receipts/nonexistent/export",
                {"format": "json"},
                mock_handler,
            )
            assert result is not None
            assert result.status_code == 404

    def test_receipt_not_in_store_or_ctx(self, handler):
        mock_handler = _make_mock_handler()
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=MockReceiptStore({}),
        ):
            result = handler.handle(
                "/api/v1/receipts/nonexistent/export",
                {"format": "json"},
                mock_handler,
            )
            assert result is not None
            assert result.status_code == 404


# ===========================================================================
# Test Receipt Found in Context Fallback
# ===========================================================================


class TestReceiptCtxFallback:
    """Tests for finding receipt in ctx when store returns None."""

    def test_receipt_found_in_ctx(self, handler_with_ctx_store):
        mock_handler = _make_mock_handler()
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=None,
        ):
            result = handler_with_ctx_store.handle(
                "/api/v1/receipts/receipt-ctx/export",
                {"format": "json"},
                mock_handler,
            )
            assert result is not None
            assert result.status_code == 200
            data = _parse_body(result)
            assert data["id"] == "receipt-ctx"


# ===========================================================================
# Test handle() Routing
# ===========================================================================


class TestHandleRouting:
    """Tests for the top-level handle() method routing."""

    def test_handle_non_matching_path_returns_none(self, handler):
        mock_handler = _make_mock_handler()
        result = handler.handle("/api/v1/debates/123", {"format": "json"}, mock_handler)
        assert result is None

    def test_handle_short_path_returns_400(self, handler):
        """Path too short to extract receipt ID."""
        mock_handler = _make_mock_handler()
        # Force can_handle to return True for this test
        with patch.object(handler, "can_handle", return_value=True):
            result = handler.handle("/api/export", {"format": "json"}, mock_handler)
            assert result is not None
            assert result.status_code == 400

    def test_handle_extracts_receipt_id(self, handler_with_store):
        """Verify the receipt ID is correctly extracted from the path."""
        mock_handler = _make_mock_handler()
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=MockReceiptStore({"my-receipt-123": MockReceipt("my-receipt-123")}),
        ):
            result = handler_with_store.handle(
                "/api/v1/receipts/my-receipt-123/export",
                {"format": "json"},
                mock_handler,
            )
            assert result is not None
            assert result.status_code == 200
            data = _parse_body(result)
            assert data["id"] == "my-receipt-123"


# ===========================================================================
# Public ODR export + stateless verification (aragora.server.handlers.decisions.receipts)
# ===========================================================================


class _StaticReceiptStore:
    """Receipt store returning pre-seeded payloads."""

    def __init__(self, receipts: dict[str, Any]) -> None:
        self._receipts = receipts

    def get(self, receipt_id: str) -> Any:
        return self._receipts.get(receipt_id)


def _gauntlet_receipt_payload(receipt_id: str = "r-odr-1") -> dict[str, Any]:
    """A stored receipt payload rich enough to map onto a full ODR document."""
    from aragora.gauntlet.receipt_models import (
        AgentResponseRecord,
        ConsensusProof,
        DecisionReceipt as GauntletDecisionReceipt,
    )

    return GauntletDecisionReceipt(
        receipt_id=receipt_id,
        gauntlet_id="g-odr-1",
        timestamp="2026-06-11T12:00:00+00:00",
        input_summary="Should we ship the public receipt endpoints?",
        input_hash="a" * 64,
        risk_summary={"critical": 0, "high": 1, "medium": 0, "low": 0, "total": 1},
        attacks_attempted=3,
        attacks_successful=0,
        probes_run=2,
        vulnerabilities_found=1,
        verdict="PASS",
        confidence=0.875,
        robustness_score=0.8,
        verdict_reasoning="Consensus reached with strong agreement",
        consensus_proof=ConsensusProof(
            reached=True,
            confidence=0.875,
            supporting_agents=["claude-agent", "mistral-agent"],
            dissenting_agents=["grok-agent"],
            method="majority",
        ),
        agent_responses=[
            AgentResponseRecord(
                agent="claude-agent",
                response="I support shipping.",
                provider="anthropic",
                model="claude-opus-4",
            ),
            AgentResponseRecord(
                agent="mistral-agent",
                response="Agreed.",
                provider="mistral",
                model="mistral-large-2",
            ),
            AgentResponseRecord(agent="grok-agent", response="Latency risk."),
        ],
    ).to_dict()


def _receipts_handler(receipt_id: str = "r-odr-1") -> Any:
    from aragora.server.handlers.decisions.receipts import ReceiptsHandler

    handler = ReceiptsHandler(MagicMock())
    handler._store = _StaticReceiptStore(  # type: ignore[assignment]
        {receipt_id: _gauntlet_receipt_payload(receipt_id)}
    )
    return handler


def _export_gate(*, public: bool, auth: bool = True) -> Any:
    """Patch the two request-time predicates the export dispatch reads."""
    return patch.multiple(
        "aragora.server.handlers.decisions.receipts",
        _auth_enabled=lambda: auth,
        _public_odr_export_enabled=lambda: public,
    )


def _signing_material() -> tuple[Any, str, str]:
    """Generate a throwaway Ed25519 signing key with its PEM and key id."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from aragora.gauntlet.odr_signing import compute_key_id, public_key_pem

    private_key = Ed25519PrivateKey.generate()
    return private_key, public_key_pem(private_key), compute_key_id(private_key.public_key())


class TestPublicOdrExport:
    """GET /api/v2/receipts/{id}/export?format=odr is public and self-describing."""

    @pytest.mark.asyncio
    async def test_returns_canonical_document_with_digest_header(self):
        from aragora.gauntlet.odr_jcs import jcs_canonicalize, odr_content_digest

        handler = _receipts_handler()
        result = await handler.handle(
            "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}
        )

        assert result.status_code == 200
        assert result.content_type == "application/json"
        document = json.loads(result.body)
        assert document["receipt_id"] == "r-odr-1"
        assert document["odr_version"] in {"0.1", "0.2"}
        assert result.body == jcs_canonicalize(document)
        digest = result.headers["X-ODR-Digest"]
        assert len(digest) == 64
        assert digest == digest.lower()
        assert digest == odr_content_digest(document)

    @pytest.mark.asyncio
    async def test_format_value_is_case_insensitive(self):
        handler = _receipts_handler()
        result = await handler.handle(
            "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "ODR"}
        )

        assert result.status_code == 200
        assert "X-ODR-Digest" in result.headers

    @pytest.mark.asyncio
    async def test_repeated_format_parameter_resolves_to_the_last_value(self):
        handler = _receipts_handler()
        with patch("aragora.server.handlers.decisions.receipts._auth_enabled", return_value=False):
            result = await handler.handle(
                "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": ["odr", "json"]}
            )

        assert result.status_code == 200
        assert "X-ODR-Digest" not in result.headers
        assert "odr_version" not in json.loads(result.body)

    @pytest.mark.asyncio
    async def test_explicit_odr_version_is_honoured(self):
        handler = _receipts_handler()
        result = await handler.handle(
            "GET",
            "/api/v2/receipts/r-odr-1/export",
            {},
            {"format": "odr", "odr_version": "0.2"},
        )

        assert result.status_code == 200
        assert json.loads(result.body)["odr_version"] == "0.2"

    @pytest.mark.asyncio
    async def test_invalid_odr_version_is_a_400_naming_the_parameter(self):
        handler = _receipts_handler()
        result = await handler.handle(
            "GET",
            "/api/v2/receipts/r-odr-1/export",
            {},
            {"format": "odr", "odr_version": "9.9"},
        )

        assert result.status_code == 400
        assert "odr_version" in json.loads(result.body)["error"]

    @pytest.mark.asyncio
    async def test_unknown_receipt_is_a_404_json_body(self):
        handler = _receipts_handler()
        result = await handler.handle(
            "GET", "/api/v2/receipts/missing/export", {}, {"format": "odr"}
        )

        assert result.status_code == 404
        assert "error" in json.loads(result.body)

    @pytest.mark.asyncio
    async def test_unsupported_format_is_a_400(self):
        handler = _receipts_handler()
        with patch("aragora.server.handlers.decisions.receipts._auth_enabled", return_value=False):
            result = await handler.handle(
                "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "xlsx"}
            )

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_download_query_parameter_reaches_the_attachment_branch(self):
        """The server-level allow-list gates the query before the handler sees it."""
        from aragora.server.http_utils import validate_query_params

        assert validate_query_params({"download": ["true"]}) == (True, "")
        handler = _receipts_handler()
        result = await handler.handle(
            "GET",
            "/api/v2/receipts/r-odr-1/export",
            {},
            {"format": "odr", "download": "true"},
        )

        assert result.status_code == 200
        assert result.headers["Content-Disposition"].startswith("attachment; ")

    @pytest.mark.asyncio
    async def test_unsigned_deployment_exports_without_signatures(self):
        handler = _receipts_handler()
        result = await handler.handle(
            "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}
        )

        assert json.loads(result.body).get("signatures", []) == []

    @pytest.mark.asyncio
    async def test_repeated_export_is_byte_identical(self):
        handler = _receipts_handler()
        first = await handler.handle(
            "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}
        )
        second = await handler.handle(
            "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}
        )

        assert first.body == second.body
        assert first.headers["X-ODR-Digest"] == second.headers["X-ODR-Digest"]

    @pytest.mark.asyncio
    async def test_signing_key_is_loaded_once_per_ttl(self, monkeypatch):
        import time

        from aragora.gauntlet import odr_signing

        private_key, _, key_id = _signing_material()
        clock = [1000.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        loader = MagicMock(return_value=private_key)
        handler = _receipts_handler()

        with patch.object(odr_signing, "load_signing_key_from_secrets", loader):
            for _ in range(5):
                result = await handler.handle(
                    "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}
                )
                assert json.loads(result.body)["signatures"][0]["key_id"] == key_id
            assert loader.call_count == 1

            clock[0] += handler.SIGNING_KEY_CACHE_TTL_SECONDS
            await handler.handle("GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"})
            assert loader.call_count == 2

    @pytest.mark.asyncio
    async def test_unconfigured_signing_key_is_negative_cached(self, monkeypatch):
        import time

        from aragora.gauntlet import odr_signing

        clock = [1000.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        loader = MagicMock(side_effect=odr_signing.OdrSigningUnconfiguredError("no key"))
        handler = _receipts_handler()

        with patch.object(odr_signing, "load_signing_key_from_secrets", loader):
            for _ in range(3):
                result = await handler.handle(
                    "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}
                )
                assert result.status_code == 200
                assert json.loads(result.body).get("signatures", []) == []
            assert loader.call_count == 1

            clock[0] += handler.SIGNING_KEY_NEGATIVE_CACHE_TTL_SECONDS
            await handler.handle("GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"})
            assert loader.call_count == 2

    @pytest.mark.asyncio
    async def test_legacy_format_needs_a_context_when_auth_is_enabled(self):
        handler = _receipts_handler()
        with patch("aragora.server.handlers.decisions.receipts._auth_enabled", return_value=True):
            result = await handler.handle(
                "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "json"}
            )

        assert result.status_code == 401
        body = json.loads(result.body)
        assert body["error"] == "Authentication required"
        assert body["code"] == "auth_required"

    @pytest.mark.asyncio
    async def test_odr_format_stays_public_when_auth_is_enabled(self):
        handler = _receipts_handler()
        with _export_gate(public=True):
            result = await handler.handle(
                "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}
            )

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_odr_is_denied_to_an_anonymous_caller_when_the_gate_is_closed(self):
        handler = _receipts_handler()
        with _export_gate(public=False):
            result = await handler.handle(
                "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}
            )

        assert result.status_code == 401
        assert json.loads(result.body) == {
            "error": "Authentication required",
            "code": "auth_required",
        }

    @pytest.mark.asyncio
    async def test_odr_serves_a_receipts_read_context_when_the_gate_is_closed(self):
        from aragora.rbac.models import AuthorizationContext

        request = _make_mock_handler()
        request._auth_context = AuthorizationContext(
            user_id="auditor-1", permissions={"receipts:read"}
        )
        handler = _receipts_handler()

        with _export_gate(public=False):
            result = await handler.handle(
                "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}, {}, request
            )

        assert result.status_code == 200
        assert json.loads(result.body)["receipt_id"] == "r-odr-1"

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_odr_denies_a_context_without_receipts_read(self):
        """The conftest RBAC bypass is opted out of so the real checker decides."""
        from aragora.rbac.models import AuthorizationContext

        request = _make_mock_handler()
        request._auth_context = AuthorizationContext(
            user_id="u-member", roles={"member"}, permissions=set()
        )
        handler = _receipts_handler()

        with patch("aragora.server.handlers.decisions.receipts._auth_enabled", return_value=True):
            result = await handler.handle(
                "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}, {}, request
            )

        assert result.status_code == 403
        body = json.loads(result.body)
        assert body["error"].startswith("Permission denied: ")
        assert body["code"] == "permission_denied"

    @pytest.mark.asyncio
    async def test_legacy_format_succeeds_with_a_receipts_read_context(self):
        from aragora.rbac.models import AuthorizationContext

        handler = _receipts_handler()
        context = AuthorizationContext(user_id="auditor-1", permissions={"receipts:read"})

        result = await handler._export_receipt("r-odr-1", {"format": "json"}, context=context)

        assert result.status_code == 200
        assert json.loads(result.body)["receipt_id"] == "r-odr-1"

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_legacy_format_denies_a_context_without_receipts_read(self):
        """The conftest RBAC bypass is opted out of so the real checker decides."""
        from aragora.rbac.models import AuthorizationContext

        request = _make_mock_handler()
        request._auth_context = AuthorizationContext(
            user_id="u-member", roles={"member"}, permissions=set()
        )
        handler = _receipts_handler()

        with patch("aragora.server.handlers.decisions.receipts._auth_enabled", return_value=True):
            result = await handler.handle(
                "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "json"}, {}, request
            )

        assert result.status_code == 403
        body = json.loads(result.body)
        assert body["error"].startswith("Permission denied: ")
        assert body["code"] == "permission_denied"


class TestStatelessOdrVerification:
    """POST /api/v2/receipts/verify checks a caller-supplied document."""

    @pytest.mark.asyncio
    async def test_exported_document_is_unverified_on_a_keyless_deployment(self):
        handler = _receipts_handler()
        export = await handler.handle(
            "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}
        )
        document = json.loads(export.body)

        result = await handler.handle("POST", "/api/v2/receipts/verify", document, {})

        assert result.status_code == 200
        payload = json.loads(result.body)
        assert payload["verified"] is False
        assert {c["name"]: c["status"] for c in payload["checks"]}["signature"] == "warn"
        assert payload["receipt_id"] == "r-odr-1"
        names = [check["name"] for check in payload["checks"]]
        assert "schema_conformance" in names
        assert "canonical_digest" in names
        assert "signature" in names
        assert "chain_link" not in names
        assert all({"name", "status", "detail"} == set(check) for check in payload["checks"])
        assert isinstance(payload["warnings"], list)
        assert payload["dissent_trail"], "the fixture records a dissenting agent"
        assert any("grok-agent" in entry for entry in payload["dissent_trail"])
        assert payload["key_id"] is None

    @pytest.mark.asyncio
    async def test_dissent_findings_render_like_the_packaged_verifier(self):
        handler = _receipts_handler()
        export = await handler.handle(
            "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}
        )
        document = json.loads(export.body)
        document["quorum"]["dissent"]["findings"] = [
            {
                "issuer": "claude",
                "severity": "P1",
                "blocking": True,
                "text": "latency budget is unproven",
            },
            {"issuer": "openai", "severity": "P3", "blocking": False, "text": "naming nit"},
        ]

        result = await handler.handle("POST", "/api/v2/receipts/verify", document, {})

        trail = json.loads(result.body)["dissent_trail"]
        assert trail[0] == "[P1] claude (blocking): latency budget is unproven"
        assert trail[1] == "[P3] openai (advisory): naming nit"

    @pytest.mark.asyncio
    async def test_signed_document_verifies_and_tampering_fails_the_signature(self):
        from aragora.gauntlet import odr_signing

        private_key, pem, key_id = _signing_material()
        handler = _receipts_handler()

        async def _resolved() -> tuple[str, str]:
            return pem, key_id

        with patch.object(odr_signing, "load_signing_key_from_secrets", return_value=private_key):
            export = await handler.handle(
                "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}
            )
        document = json.loads(export.body)
        assert document["signatures"][0]["key_id"] == key_id

        handler._get_signing_public_key = _resolved  # type: ignore[method-assign]
        good = json.loads(
            (await handler.handle("POST", "/api/v2/receipts/verify", document, {})).body
        )
        assert good["verified"] is True
        assert good["key_id"] == key_id

        tampered = dict(document)
        tampered["claim"] = dict(tampered["claim"], statement="Rewritten after signing")
        bad = json.loads(
            (await handler.handle("POST", "/api/v2/receipts/verify", tampered, {})).body
        )
        assert bad["verified"] is False
        statuses = {check["name"]: check["status"] for check in bad["checks"]}
        assert statuses["signature"] == "fail"
        assert statuses["canonical_digest"] == "pass"

    @pytest.mark.asyncio
    async def test_unsigned_document_is_unverified_when_a_key_is_served(self):
        _, pem, key_id = _signing_material()
        handler = _receipts_handler()
        export = await handler.handle(
            "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}
        )
        document = json.loads(export.body)
        assert document["signatures"] == []

        async def _resolved() -> tuple[str, str]:
            return pem, key_id

        handler._get_signing_public_key = _resolved  # type: ignore[method-assign]
        payload = json.loads(
            (await handler.handle("POST", "/api/v2/receipts/verify", document, {})).body
        )

        assert payload["verified"] is False
        statuses = {check["name"]: check["status"] for check in payload["checks"]}
        assert statuses["signature"] == "warn"
        assert payload["key_id"] == key_id

    @pytest.mark.asyncio
    async def test_signed_document_is_unverified_when_no_key_is_served(self):
        from aragora.gauntlet import odr_signing

        private_key, _, _ = _signing_material()
        handler = _receipts_handler()
        with patch.object(odr_signing, "load_signing_key_from_secrets", return_value=private_key):
            export = await handler.handle(
                "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}
            )
        document = json.loads(export.body)
        assert document["signatures"]

        async def _unconfigured() -> None:
            return None

        handler._get_signing_public_key = _unconfigured  # type: ignore[method-assign]
        for candidate in (document, dict(document, claim=dict(document["claim"], statement="x"))):
            payload = json.loads(
                (await handler.handle("POST", "/api/v2/receipts/verify", candidate, {})).body
            )
            assert payload["verified"] is False
            statuses = {check["name"]: check["status"] for check in payload["checks"]}
            assert statuses["signature"] == "skip"
            assert payload["key_id"] is None

    @pytest.mark.asyncio
    async def test_empty_object_is_a_400_naming_odr_version(self):
        handler = _receipts_handler()
        result = await handler.handle("POST", "/api/v2/receipts/verify", {}, {})

        assert result.status_code == 400
        assert "odr_version" in json.loads(result.body)["error"]

    @pytest.mark.asyncio
    async def test_oversized_body_is_a_413(self):
        handler = _receipts_handler()
        result = await handler.handle(
            "POST",
            "/api/v2/receipts/verify",
            {"odr_version": "0.1"},
            {},
            {"Content-Length": "300000"},
        )

        assert result.status_code == 413
        assert "error" in json.loads(result.body)

    @pytest.mark.asyncio
    async def test_body_under_the_cap_is_verified(self):
        handler = _receipts_handler()
        export = await handler.handle(
            "GET", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}
        )
        document = json.loads(export.body)
        document["reasoning"] = dict(document["reasoning"], padding="x" * 200_000)

        result = await handler.handle("POST", "/api/v2/receipts/verify", document, {})

        assert result.status_code == 200
        assert json.loads(result.body)["verified"] is False

    @pytest.mark.asyncio
    async def test_get_on_the_verify_route_is_a_404_json_body(self):
        handler = _receipts_handler()
        result = await handler.handle("GET", "/api/v2/receipts/verify", {}, {})

        assert result.status_code == 404
        assert "error" in json.loads(result.body)

    @pytest.mark.asyncio
    async def test_oversized_verify_body_is_never_read(self):
        """The public route must reject on Content-Length, not after parsing."""
        from aragora.server.handlers.decisions.receipts import MAX_VERIFY_BODY_BYTES

        request = _make_mock_handler(method="POST")
        request.headers["Content-Length"] = str(MAX_VERIFY_BODY_BYTES + 1)
        handler = _receipts_handler()

        result = await handler.handle(
            method="POST", path="/api/v2/receipts/verify", handler=request
        )

        assert result.status_code == 413
        assert "error" in json.loads(result.body)
        request.rfile.read.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_ascii_body_under_the_cap_is_not_rejected(self):
        """ensure_ascii escaping must not push a wire-legal document over the cap."""
        from aragora.server.handlers.decisions.receipts import MAX_VERIFY_BODY_BYTES

        handler = _receipts_handler()
        document = {"odr_version": "0.2", "reasoning": {"padding": "é" * 130_000}}
        assert len(json.dumps(document).encode("utf-8")) > MAX_VERIFY_BODY_BYTES
        assert len(json.dumps(document, ensure_ascii=False).encode("utf-8")) < (
            MAX_VERIFY_BODY_BYTES
        )

        result = await handler.handle("POST", "/api/v2/receipts/verify", document, {})

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_odr_export_branch_requires_get(self):
        """A non-GET on the export path must not reach the unauthenticated branch."""
        handler = _receipts_handler()

        result = await handler.handle(
            "POST", "/api/v2/receipts/r-odr-1/export", {}, {"format": "odr"}
        )

        assert result.status_code == 405
        assert "error" in json.loads(result.body)


class TestExportOperationSecurity:
    """exportReceipt is callable anonymously (format=odr) or with a bearer token."""

    EXPORT_PATH = "/api/v2/receipts/{receipt_id}/export"

    def test_committed_spec_declares_anonymous_and_bearer(self):
        """The published contract offers an external generator both call shapes."""
        repo_root = Path(__file__).resolve().parents[3]
        spec = json.loads((repo_root / "docs" / "api" / "openapi.json").read_text())

        security = spec["paths"][self.EXPORT_PATH]["get"]["security"]

        assert {} in security
        assert {"bearerAuth": []} in security

    def test_canonical_source_matches_the_committed_spec(self):
        """Set at the source, so a later regeneration preserves it."""
        from aragora.server.openapi.endpoints.response_schemas import (
            RESPONSE_SCHEMA_ENDPOINTS,
        )

        security = RESPONSE_SCHEMA_ENDPOINTS[self.EXPORT_PATH]["get"]["security"]

        assert security == [{}, {"bearerAuth": []}]
