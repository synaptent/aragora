"""
Tests for GauntletReceiptsMixin (aragora/server/handlers/gauntlet/receipts.py).

Covers:
- _get_receipt: JSON/HTML/Markdown/SARIF/PDF/CSV formats, signing, in-memory vs
  persistent storage, not completed, not found, storage errors, webhook notifications
- _verify_receipt: signature verification, integrity checks, ID matching,
  missing fields, invalid format, webhook notifications
- _auto_persist_receipt: receipt generation, storage persistence, signing,
  KM ingestion, auto-signing env var, import errors, runtime errors
- _risk_level_from_score: boundary values for LOW/MEDIUM/HIGH/CRITICAL
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.core_types import DebateResult, Message
from aragora.gauntlet.receipt_models import DecisionReceipt
from aragora.server.handlers.gauntlet.receipts import GauntletReceiptsMixin
from aragora.server.handlers.gauntlet.storage import get_gauntlet_runs
from aragora.server.handlers.utils.responses import HandlerResult

# Patch targets for lazy imports inside method bodies
_DR = "aragora.gauntlet.receipt.DecisionReceipt"
_GER = "aragora.gauntlet.errors.gauntlet_error_response"
_SR = "aragora.gauntlet.signing.SignedReceipt"
_VR = "aragora.gauntlet.signing.verify_receipt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(result: HandlerResult) -> dict[str, Any]:
    """Decode a HandlerResult body into a dict."""
    return json.loads(result.body.decode("utf-8"))


def _status(result: HandlerResult) -> int:
    """Extract status code from HandlerResult."""
    return result.status_code


def _body_bytes(result: HandlerResult) -> bytes:
    """Get raw body bytes."""
    return result.body


async def _ticker(duration: float = 0.45) -> int:
    """Measure whether another async task can keep making progress."""
    ticks = 0
    start = time.perf_counter()
    while time.perf_counter() - start < duration:
        await asyncio.sleep(0.01)
        ticks += 1
    return ticks


# ---------------------------------------------------------------------------
# Fake receipt for testing
# ---------------------------------------------------------------------------


@dataclass
class FakeReceipt:
    """Mimics DecisionReceipt for testing."""

    receipt_id: str = "receipt-abc123"
    gauntlet_id: str = "gauntlet-abc123456789"
    timestamp: str = "2026-01-01T00:00:00"
    input_summary: str = "Test decision"
    input_hash: str = "sha256-deadbeef"
    risk_summary: dict = field(
        default_factory=lambda: {"critical": 0, "high": 1, "medium": 2, "low": 3, "total": 6}
    )
    attacks_attempted: int = 10
    attacks_successful: int = 1
    probes_run: int = 5
    vulnerabilities_found: int = 3
    verdict: str = "CONDITIONAL"
    confidence: float = 0.85
    robustness_score: float = 0.75
    artifact_hash: str = "hash123"
    signature: str | None = None
    signature_algorithm: str | None = None
    signature_key_id: str | None = None
    signed_at: str | None = None
    vulnerability_details: list = field(default_factory=list)
    agent_responses: list = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "gauntlet_id": self.gauntlet_id,
            "timestamp": self.timestamp,
            "input_summary": self.input_summary,
            "input_hash": self.input_hash,
            "risk_summary": self.risk_summary,
            "attacks_attempted": self.attacks_attempted,
            "attacks_successful": self.attacks_successful,
            "probes_run": self.probes_run,
            "vulnerabilities_found": self.vulnerabilities_found,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "robustness_score": self.robustness_score,
            "artifact_hash": self.artifact_hash,
            "agent_responses": self.agent_responses,
        }

    def sign(self, signer=None):
        self.signature = "base64sig"
        self.signature_algorithm = "hmac-sha256"
        self.signature_key_id = "key-001"
        self.signed_at = "2026-01-01T00:00:01"
        return self

    def to_html(self, **kwargs) -> str:
        return "<html><body>Receipt</body></html>"

    def to_markdown(self, **kwargs) -> str:
        return "# Receipt\n\nTest receipt"

    def to_sarif_json(self, **kwargs) -> str:
        return json.dumps({"$schema": "sarif", "runs": []})

    def to_pdf(self) -> bytes:
        return b"%PDF-fake-content"

    def to_csv(self) -> str:
        return "id,verdict\nreceipt-abc123,CONDITIONAL"

    def verify_integrity(self) -> bool:
        return True

    def _calculate_hash(self) -> str:
        return self.artifact_hash


@dataclass
class FakeResult:
    """Mimics a gauntlet result object."""

    debate_id: str = "debate-001"
    agents_involved: list = field(default_factory=lambda: ["agent-a", "agent-b"])
    rounds_completed: int = 3
    total_findings: int = 5
    verdict: str = "CONDITIONAL"
    confidence: float = 0.85
    robustness_score: float = 0.75


# ---------------------------------------------------------------------------
# Stub handler class
# ---------------------------------------------------------------------------


class _Stub(GauntletReceiptsMixin):
    """Minimal concrete class that mixes in GauntletReceiptsMixin."""

    def read_json_body(self, handler, max_size=None):
        """Stub read_json_body for verify_receipt."""
        if handler is None:
            return None
        return getattr(handler, "_json_body", None)


@pytest.fixture
def mixin():
    return _Stub()


@pytest.fixture(autouse=True)
def _clear_runs():
    """Ensure in-memory runs are empty before/after every test."""
    runs = get_gauntlet_runs()
    runs.clear()
    yield
    runs.clear()


# ---------------------------------------------------------------------------
# Mock storage factory
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_storage():
    """Return a MagicMock that acts as GauntletStorage."""
    s = MagicMock()
    s.get.return_value = None
    return s


@pytest.fixture(autouse=True)
def _patch_storage(mock_storage):
    """Patch _get_storage_proxy to return mock_storage for every test."""
    with patch(
        "aragora.server.handlers.gauntlet.receipts._get_storage_proxy",
        return_value=mock_storage,
    ):
        yield


@pytest.fixture
def mock_receipt():
    """Create a FakeReceipt for testing."""
    return FakeReceipt()


@pytest.fixture(autouse=True)
def _patch_receipt_webhooks():
    """Prevent webhook calls from leaking."""
    with patch.dict(
        "sys.modules",
        {
            "aragora.integrations.receipt_webhooks": MagicMock(
                get_receipt_notifier=MagicMock(return_value=MagicMock())
            ),
        },
    ):
        yield


# ============================================================================
# _risk_level_from_score
# ============================================================================


class TestRiskLevelFromScore:
    """Tests for the _risk_level_from_score helper."""

    def test_score_1_0_returns_low(self, mixin):
        assert mixin._risk_level_from_score(1.0) == "LOW"

    def test_score_0_8_returns_low(self, mixin):
        assert mixin._risk_level_from_score(0.8) == "LOW"

    def test_score_0_9_returns_low(self, mixin):
        assert mixin._risk_level_from_score(0.9) == "LOW"

    def test_score_0_79_returns_medium(self, mixin):
        assert mixin._risk_level_from_score(0.79) == "MEDIUM"

    def test_score_0_6_returns_medium(self, mixin):
        assert mixin._risk_level_from_score(0.6) == "MEDIUM"

    def test_score_0_7_returns_medium(self, mixin):
        assert mixin._risk_level_from_score(0.7) == "MEDIUM"

    def test_score_0_59_returns_high(self, mixin):
        assert mixin._risk_level_from_score(0.59) == "HIGH"

    def test_score_0_4_returns_high(self, mixin):
        assert mixin._risk_level_from_score(0.4) == "HIGH"

    def test_score_0_5_returns_high(self, mixin):
        assert mixin._risk_level_from_score(0.5) == "HIGH"

    def test_score_0_39_returns_critical(self, mixin):
        assert mixin._risk_level_from_score(0.39) == "CRITICAL"

    def test_score_0_0_returns_critical(self, mixin):
        assert mixin._risk_level_from_score(0.0) == "CRITICAL"

    def test_score_negative_returns_critical(self, mixin):
        assert mixin._risk_level_from_score(-0.1) == "CRITICAL"


# ============================================================================
# _get_receipt - JSON format (default)
# ============================================================================


class TestGetReceiptJSON:
    """Tests for _get_receipt with JSON format (default)."""

    @pytest.mark.asyncio
    async def test_returns_receipt_from_memory_completed(self, mixin, mock_receipt):
        """In-memory completed run returns receipt JSON."""
        mock_receipt.agent_responses = [
            {
                "agent": "claude",
                "response": "Use Redis for coordination.",
                "provider": "anthropic",
                "provider_display": "Anthropic",
                "model": "claude-sonnet-4",
                "llm_label": "claude-sonnet-4 via Anthropic",
            }
        ]
        runs = get_gauntlet_runs()
        runs["g-001"] = {
            "status": "completed",
            "result": {"total_findings": 3, "verdict": "PASS", "confidence": 0.9},
            "result_obj": None,
            "input_summary": "Test",
            "input_hash": "hash123",
            "completed_at": "2026-01-01T00:00:00",
        }

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-001", {})

        assert _status(result) == 200
        data = _parse(result)
        assert data["receipt_id"] == "receipt-abc123"
        assert data["agent_responses"][0]["llm_label"] == "claude-sonnet-4 via Anthropic"

    @pytest.mark.asyncio
    async def test_returns_receipt_with_result_obj(self, mixin, mock_receipt):
        """When result_obj is present, use from_mode_result."""
        runs = get_gauntlet_runs()
        fake_result_obj = FakeResult()
        runs["g-002"] = {
            "status": "completed",
            "result": {"total_findings": 5},
            "result_obj": fake_result_obj,
            "input_hash": "hash456",
        }

        with patch(_DR) as MockDR:
            MockDR.from_mode_result.return_value = mock_receipt
            result = await mixin._get_receipt("g-002", {})

        assert _status(result) == 200
        MockDR.from_mode_result.assert_called_once_with(fake_result_obj, input_hash="hash456")

    @pytest.mark.asyncio
    async def test_not_completed_returns_error(self, mixin):
        """Non-completed run returns an error."""
        runs = get_gauntlet_runs()
        runs["g-003"] = {"status": "running"}

        with patch(_GER, return_value=({"error": "not_completed"}, 400)):
            result = await mixin._get_receipt("g-003", {})

        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_not_found_in_memory_checks_storage(self, mixin, mock_storage, mock_receipt):
        """When not in memory, check persistent storage."""
        mock_storage.get.return_value = {
            "total_findings": 2,
            "verdict": "PASS",
            "confidence": 0.95,
            "robustness_score": 0.9,
            "input_summary": "Stored decision",
            "input_hash": "stored-hash",
        }

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-missing", {})

        assert _status(result) == 200
        mock_storage.get.assert_called_once_with("g-missing")

    @pytest.mark.asyncio
    async def test_not_found_anywhere_returns_404(self, mixin, mock_storage):
        """When not in memory or storage, return 404."""
        mock_storage.get.return_value = None

        with patch(_GER, return_value=({"error": "gauntlet_not_found"}, 404)):
            result = await mixin._get_receipt("g-gone", {})

        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_storage_oserror_returns_error(self, mixin, mock_storage):
        """Storage OSError returns storage error."""
        mock_storage.get.side_effect = OSError("disk fail")

        with patch(_GER, return_value=({"error": "storage_error"}, 500)):
            result = await mixin._get_receipt("g-err", {})

        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_storage_runtime_error(self, mixin, mock_storage):
        """Storage RuntimeError returns storage error."""
        mock_storage.get.side_effect = RuntimeError("db offline")

        with patch(_GER, return_value=({"error": "storage_error"}, 500)):
            result = await mixin._get_receipt("g-rte", {})

        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_storage_value_error(self, mixin, mock_storage):
        """Storage ValueError returns storage error."""
        mock_storage.get.side_effect = ValueError("bad data")

        with patch(_GER, return_value=({"error": "storage_error"}, 500)):
            result = await mixin._get_receipt("g-val", {})

        assert _status(result) == 500


class TestGetReceiptAsyncSafety:
    """Async-safety checks for gauntlet receipt retrieval."""

    @pytest.mark.asyncio
    async def test_storage_lookup_does_not_block_event_loop(self, mixin, mock_receipt):
        """Slow sync storage should be offloaded from the async receipt path."""

        class _SlowStorage:
            def get_inflight(self, gauntlet_id: str) -> None:
                return None

            def get(self, gauntlet_id: str) -> dict[str, Any]:
                time.sleep(0.2)
                return {
                    "total_findings": 2,
                    "verdict": "PASS",
                    "confidence": 0.95,
                    "robustness_score": 0.9,
                    "input_summary": f"Stored decision for {gauntlet_id}",
                    "input_hash": "stored-hash",
                }

        task = asyncio.create_task(_ticker())
        await asyncio.sleep(0)

        with (
            patch(
                "aragora.server.handlers.gauntlet.receipts._get_storage_proxy",
                return_value=_SlowStorage(),
            ),
            patch(_DR, return_value=mock_receipt),
        ):
            result = await mixin._get_receipt("g-slow-store", {"signed": "false"})

        ticks = await task

        assert _status(result) == 200
        assert ticks >= 30


# ============================================================================
# _get_receipt - signing
# ============================================================================


class TestGetReceiptSigning:
    """Tests for receipt signing behavior in _get_receipt."""

    @pytest.mark.asyncio
    async def test_signs_by_default(self, mixin, mock_receipt):
        """Receipt is signed by default."""
        runs = get_gauntlet_runs()
        runs["g-sign"] = {
            "status": "completed",
            "result": {"total_findings": 0},
            "result_obj": None,
            "input_summary": "Test",
            "input_hash": "h",
            "completed_at": "2026-01-01",
        }

        original_sign = mock_receipt.sign
        sign_called = []

        def track_sign(signer=None):
            sign_called.append(True)
            return original_sign(signer)

        mock_receipt.sign = track_sign

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-sign", {})

        assert _status(result) == 200
        assert len(sign_called) == 1

    @pytest.mark.asyncio
    async def test_skip_signing_when_false(self, mixin, mock_receipt):
        """Signing is skipped when signed=false."""
        runs = get_gauntlet_runs()
        runs["g-nosign"] = {
            "status": "completed",
            "result": {"total_findings": 0},
            "result_obj": None,
            "input_summary": "Test",
            "input_hash": "h",
            "completed_at": "2026-01-01",
        }

        sign_called = []
        mock_receipt.sign = lambda signer=None: sign_called.append(True)

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-nosign", {"signed": "false"})

        assert _status(result) == 200
        assert len(sign_called) == 0

    @pytest.mark.asyncio
    async def test_signing_import_error_continues(self, mixin, mock_receipt):
        """If signing raises ImportError, continue with unsigned receipt."""
        runs = get_gauntlet_runs()
        runs["g-signerr"] = {
            "status": "completed",
            "result": {"total_findings": 0},
            "result_obj": None,
            "input_summary": "Test",
            "input_hash": "h",
            "completed_at": "2026-01-01",
        }

        mock_receipt.sign = MagicMock(side_effect=ImportError("no crypto"))

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-signerr", {})

        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_signing_value_error_continues(self, mixin, mock_receipt):
        """If signing raises ValueError, continue with unsigned receipt."""
        runs = get_gauntlet_runs()
        runs["g-sigvalerr"] = {
            "status": "completed",
            "result": {"total_findings": 0},
            "result_obj": None,
            "input_summary": "Test",
            "input_hash": "h",
            "completed_at": "2026-01-01",
        }

        mock_receipt.sign = MagicMock(side_effect=ValueError("bad key"))

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-sigvalerr", {})

        assert _status(result) == 200


# ============================================================================
# _get_receipt - format variations
# ============================================================================


def _completed_run():
    """Helper to create a completed gauntlet run dict."""
    return {
        "status": "completed",
        "result": {"total_findings": 3, "verdict": "PASS"},
        "result_obj": None,
        "input_summary": "Test",
        "input_hash": "h",
        "completed_at": "2026-01-01",
    }


class TestGetReceiptFormats:
    """Tests for different output formats of _get_receipt."""

    @pytest.mark.asyncio
    async def test_html_format(self, mixin, mock_receipt):
        runs = get_gauntlet_runs()
        runs["g-html"] = _completed_run()

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-html", {"format": "html"})

        assert _status(result) == 200
        assert result.content_type == "text/html"
        assert b"<html>" in _body_bytes(result)

    @pytest.mark.asyncio
    async def test_markdown_format(self, mixin, mock_receipt):
        runs = get_gauntlet_runs()
        runs["g-md"] = _completed_run()

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-md", {"format": "md"})

        assert _status(result) == 200
        assert result.content_type == "text/markdown"
        assert b"# Receipt" in _body_bytes(result)

    @pytest.mark.asyncio
    async def test_sarif_format(self, mixin, mock_receipt):
        runs = get_gauntlet_runs()
        runs["g-sarif"] = _completed_run()

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-sarif", {"format": "sarif"})

        assert _status(result) == 200
        assert result.content_type == "application/sarif+json"
        assert result.headers["Content-Disposition"] == 'attachment; filename="g-sarif.sarif"'
        data = json.loads(_body_bytes(result))
        assert "$schema" in data

    @pytest.mark.asyncio
    async def test_pdf_format(self, mixin, mock_receipt):
        runs = get_gauntlet_runs()
        runs["g-pdf"] = _completed_run()

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-pdf", {"format": "pdf"})

        assert _status(result) == 200
        assert result.content_type == "application/pdf"
        assert result.headers["Content-Disposition"] == 'attachment; filename="g-pdf-receipt.pdf"'
        assert _body_bytes(result) == b"%PDF-fake-content"

    @pytest.mark.asyncio
    async def test_pdf_import_error_returns_501(self, mixin, mock_receipt):
        """PDF export returns 501 when weasyprint is not available."""
        runs = get_gauntlet_runs()
        runs["g-nopdf"] = _completed_run()

        mock_receipt.to_pdf = MagicMock(side_effect=ImportError("no weasyprint"))

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-nopdf", {"format": "pdf"})

        assert _status(result) == 501
        data = _parse(result)
        assert "weasyprint" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_csv_format(self, mixin, mock_receipt):
        runs = get_gauntlet_runs()
        runs["g-csv"] = _completed_run()

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-csv", {"format": "csv"})

        assert _status(result) == 200
        assert result.content_type == "text/csv"
        assert result.headers["Content-Disposition"] == 'attachment; filename="g-csv-findings.csv"'
        body_text = _body_bytes(result).decode("utf-8")
        assert "id,verdict" in body_text

    @pytest.mark.asyncio
    async def test_json_format_explicit(self, mixin, mock_receipt):
        runs = get_gauntlet_runs()
        runs["g-json"] = _completed_run()

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-json", {"format": "json"})

        assert _status(result) == 200
        assert result.content_type == "application/json"

    @pytest.mark.asyncio
    async def test_unknown_format_defaults_to_json(self, mixin, mock_receipt):
        """Unknown format falls through to JSON default."""
        runs = get_gauntlet_runs()
        runs["g-unk"] = _completed_run()

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-unk", {"format": "xml"})

        assert _status(result) == 200
        assert result.content_type == "application/json"


# ============================================================================
# _get_receipt - receipt construction from stored data
# ============================================================================


class TestGetReceiptConstruction:
    """Tests for receipt field construction when no result_obj."""

    @pytest.mark.asyncio
    async def test_receipt_fields_from_run(self, mixin):
        """Verify receipt is built with correct fields from run data."""
        runs = get_gauntlet_runs()
        gid = "gauntlet-123456789abc"
        runs[gid] = {
            "status": "completed",
            "result": {
                "critical_count": 1,
                "high_count": 2,
                "medium_count": 3,
                "low_count": 4,
                "total_findings": 10,
                "verdict": "fail",
                "confidence": 0.7,
                "robustness_score": 0.5,
            },
            "result_obj": None,
            "input_summary": "My decision",
            "input_hash": "my-hash",
            "completed_at": "2026-02-01T12:00:00",
        }

        captured = {}

        def fake_init(**kwargs):
            captured.update(kwargs)
            return FakeReceipt(**{k: v for k, v in kwargs.items() if hasattr(FakeReceipt, k)})

        with patch(_DR, side_effect=fake_init):
            result = await mixin._get_receipt(gid, {"signed": "false"})

        assert _status(result) == 200
        assert captured["receipt_id"] == f"receipt-{gid[-12:]}"
        assert captured["gauntlet_id"] == gid
        assert captured["input_summary"] == "My decision"
        assert captured["input_hash"] == "my-hash"
        assert captured["risk_summary"]["critical"] == 1
        assert captured["risk_summary"]["high"] == 2
        assert captured["verdict"] == "FAIL"
        assert captured["confidence"] == 0.7

    @pytest.mark.asyncio
    async def test_receipt_from_storage_uses_stored_fields(self, mixin, mock_storage):
        """When fetched from storage, uses stored result data."""
        mock_storage.get.return_value = {
            "total_findings": 7,
            "verdict": "pass",
            "confidence": 0.99,
            "robustness_score": 0.95,
            "input_summary": "Stored decision",
            "input_hash": "stored-hash",
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 1,
            "low_count": 6,
        }

        captured = {}

        def fake_init(**kwargs):
            captured.update(kwargs)
            return FakeReceipt(**{k: v for k, v in kwargs.items() if hasattr(FakeReceipt, k)})

        with patch(_DR, side_effect=fake_init):
            result = await mixin._get_receipt("g-stored", {"signed": "false"})

        assert _status(result) == 200
        assert captured["input_summary"] == "Stored decision"
        assert captured["input_hash"] == "stored-hash"
        assert captured["verdict"] == "PASS"

    @pytest.mark.asyncio
    async def test_receipt_from_storage_preserves_agent_responses(self, mixin, mock_storage):
        """Stored provider/model labels are preserved in the JSON receipt."""
        mock_storage.get.return_value = {
            "total_findings": 1,
            "verdict": "pass",
            "confidence": 0.95,
            "robustness_score": 0.9,
            "input_summary": "Stored decision",
            "input_hash": "stored-hash",
            "agent_responses": [
                {
                    "agent": "claude",
                    "response": "Use Redis for coordination.",
                    "provider": "anthropic",
                    "provider_display": "Anthropic",
                    "model": "claude-sonnet-4",
                    "llm_label": "claude-sonnet-4 via Anthropic",
                }
            ],
        }

        captured = {}

        def fake_init(**kwargs):
            captured.update(kwargs)
            return FakeReceipt(**{k: v for k, v in kwargs.items() if hasattr(FakeReceipt, k)})

        with patch(_DR, side_effect=fake_init):
            result = await mixin._get_receipt("g-stored", {"signed": "false"})

        assert _status(result) == 200
        assert captured["agent_responses"][0]["llm_label"] == "claude-sonnet-4 via Anthropic"


class TestDecisionReceiptAgentResponses:
    """Tests for provider/model labels in canonical decision receipts."""

    def test_from_debate_result_includes_llm_labels(self):
        debate_result = DebateResult(
            debate_id="debate-123",
            task="Pick a database",
            final_answer="Use Postgres.",
            confidence=0.92,
            consensus_reached=True,
            rounds_used=1,
            participants=["claude", "gpt"],
            messages=[
                Message(
                    role="proposer",
                    agent="claude",
                    content="Use Postgres with read replicas.",
                    round=1,
                ),
                Message(
                    role="critic",
                    agent="gpt",
                    content="Postgres fits if we shard later.",
                    round=1,
                ),
            ],
            metadata={
                "agent_models": {
                    "claude": {
                        "provider": "anthropic",
                        "model": "claude-sonnet-4",
                    },
                    "gpt": {
                        "provider": "openai",
                        "model": "gpt-4.1",
                    },
                }
            },
        )

        receipt = DecisionReceipt.from_debate_result(debate_result)

        assert [response.agent for response in receipt.agent_responses] == ["claude", "gpt"]
        assert receipt.agent_responses[0].llm_label == "claude-sonnet-4 via Anthropic"
        assert receipt.agent_responses[1].llm_label == "gpt-4.1 via OpenAI"

    @pytest.mark.asyncio
    async def test_receipt_defaults_for_missing_fields(self, mixin, mock_storage):
        """Missing fields fall back to defaults."""
        # Must be truthy for the handler to proceed (empty dict is falsy)
        mock_storage.get.return_value = {"_stored": True}

        captured = {}

        def fake_init(**kwargs):
            captured.update(kwargs)
            return FakeReceipt(**{k: v for k, v in kwargs.items() if hasattr(FakeReceipt, k)})

        with patch(_DR, side_effect=fake_init):
            result = await mixin._get_receipt("g-empty", {"signed": "false"})

        assert _status(result) == 200
        assert captured["verdict"] == "UNKNOWN"
        assert captured["confidence"] == 0
        assert captured["robustness_score"] == 0
        assert captured["vulnerabilities_found"] == 0


# ============================================================================
# _verify_receipt
# ============================================================================


def _make_handler_with_body(body: dict[str, Any] | None) -> MagicMock:
    """Create a mock HTTP handler with a JSON body."""
    h = MagicMock()
    h._json_body = body
    return h


def _valid_verify_body(gauntlet_id: str = "g-verify") -> dict[str, Any]:
    """Return a valid request body for _verify_receipt."""
    return {
        "receipt": {
            "receipt_id": "receipt-verify",
            "gauntlet_id": gauntlet_id,
            "timestamp": "2026-01-01",
            "input_summary": "Test",
            "input_hash": "hash",
            "risk_summary": {},
            "attacks_attempted": 0,
            "attacks_successful": 0,
            "probes_run": 0,
            "vulnerabilities_found": 0,
            "verdict": "PASS",
            "confidence": 0.9,
            "robustness_score": 0.8,
            "artifact_hash": "arthash",
        },
        "signature": "base64sig",
        "signature_metadata": {
            "algorithm": "hmac-sha256",
            "timestamp": "2026-01-01T00:00:00",
            "key_id": "key-001",
        },
    }


class TestVerifyReceipt:
    """Tests for _verify_receipt endpoint."""

    @pytest.mark.asyncio
    async def test_missing_body_returns_400(self, mixin):
        """None body returns 400."""
        handler = _make_handler_with_body(None)
        result = await mixin._verify_receipt("g-001", handler)
        assert _status(result) == 400
        data = _parse(result)
        assert (
            "invalid" in data.get("error", "").lower() or "missing" in data.get("error", "").lower()
        )

    @pytest.mark.asyncio
    async def test_missing_receipt_field_returns_400(self, mixin):
        """Body without 'receipt' field returns 400."""
        handler = _make_handler_with_body({"signature": "sig", "signature_metadata": {}})
        result = await mixin._verify_receipt("g-001", handler)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_missing_signature_field_returns_400(self, mixin):
        """Body without 'signature' field returns 400."""
        handler = _make_handler_with_body({"receipt": {}, "signature_metadata": {}})
        result = await mixin._verify_receipt("g-001", handler)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_missing_signature_metadata_returns_400(self, mixin):
        """Body without 'signature_metadata' field returns 400."""
        handler = _make_handler_with_body({"receipt": {}, "signature": "sig"})
        result = await mixin._verify_receipt("g-001", handler)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_invalid_signed_receipt_key_error_returns_400(self, mixin):
        """Malformed signed receipt (KeyError from from_dict) returns 400."""
        body = {
            "receipt": {},
            "signature": "sig",
            "signature_metadata": {},
        }
        handler = _make_handler_with_body(body)

        with patch(_SR) as MockSR:
            MockSR.from_dict.side_effect = KeyError("algorithm")
            result = await mixin._verify_receipt("g-001", handler)

        assert _status(result) == 400
        data = _parse(result)
        assert "format" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_invalid_signed_receipt_type_error_returns_400(self, mixin):
        """TypeError from from_dict returns 400."""
        body = _valid_verify_body()
        handler = _make_handler_with_body(body)

        with patch(_SR) as MockSR:
            MockSR.from_dict.side_effect = TypeError("wrong type")
            result = await mixin._verify_receipt("g-001", handler)

        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_invalid_signed_receipt_value_error_returns_400(self, mixin):
        """ValueError from from_dict returns 400."""
        body = _valid_verify_body()
        handler = _make_handler_with_body(body)

        with patch(_SR) as MockSR:
            MockSR.from_dict.side_effect = ValueError("bad value")
            result = await mixin._verify_receipt("g-001", handler)

        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_successful_verification(self, mixin):
        """Full successful verification returns verified=True."""
        body = _valid_verify_body("g-verify")
        handler = _make_handler_with_body(body)

        mock_sig_metadata = MagicMock()
        mock_sig_metadata.algorithm = "hmac-sha256"
        mock_sig_metadata.key_id = "key-001"
        mock_sig_metadata.timestamp = "2026-01-01T00:00:00"

        mock_signed = MagicMock()
        mock_signed.receipt_data = body["receipt"]
        mock_signed.signature_metadata = mock_sig_metadata

        mock_receipt_obj = MagicMock()
        mock_receipt_obj.verify_integrity.return_value = True
        mock_receipt_obj._calculate_hash.return_value = "arthash"

        with (
            patch(_SR) as MockSR,
            patch(_VR, return_value=True),
            patch(_DR, return_value=mock_receipt_obj),
        ):
            MockSR.from_dict.return_value = mock_signed
            result = await mixin._verify_receipt("g-verify", handler)

        assert _status(result) == 200
        data = _parse(result)
        assert data["verified"] is True
        assert data["signature_valid"] is True
        assert data["integrity_valid"] is True
        assert data["id_match"] is True

    @pytest.mark.asyncio
    async def test_id_mismatch(self, mixin):
        """Receipt gauntlet_id mismatch sets id_match=False."""
        body = _valid_verify_body("g-different")
        handler = _make_handler_with_body(body)

        mock_sig_metadata = MagicMock()
        mock_sig_metadata.algorithm = "hmac-sha256"
        mock_sig_metadata.key_id = "key-001"
        mock_sig_metadata.timestamp = "2026-01-01T00:00:00"

        mock_signed = MagicMock()
        mock_signed.receipt_data = body["receipt"]
        mock_signed.signature_metadata = mock_sig_metadata

        mock_receipt_obj = MagicMock()
        mock_receipt_obj.verify_integrity.return_value = True
        mock_receipt_obj._calculate_hash.return_value = "arthash"

        with (
            patch(_SR) as MockSR,
            patch(_VR, return_value=True),
            patch(_DR, return_value=mock_receipt_obj),
        ):
            MockSR.from_dict.return_value = mock_signed
            result = await mixin._verify_receipt("g-MISMATCH", handler)

        data = _parse(result)
        assert data["id_match"] is False
        assert data["verified"] is False
        assert any("does not match" in e for e in data["errors"])

    @pytest.mark.asyncio
    async def test_invalid_signature(self, mixin):
        """Failed signature verification sets signature_valid=False."""
        body = _valid_verify_body("g-badsig")
        handler = _make_handler_with_body(body)

        mock_sig_metadata = MagicMock()
        mock_sig_metadata.algorithm = "hmac-sha256"
        mock_sig_metadata.key_id = "key-001"
        mock_sig_metadata.timestamp = "2026-01-01"

        mock_signed = MagicMock()
        mock_signed.receipt_data = body["receipt"]
        mock_signed.signature_metadata = mock_sig_metadata

        mock_receipt_obj = MagicMock()
        mock_receipt_obj.verify_integrity.return_value = True
        mock_receipt_obj._calculate_hash.return_value = "arthash"

        with (
            patch(_SR) as MockSR,
            patch(_VR, return_value=False),
            patch(_DR, return_value=mock_receipt_obj),
        ):
            MockSR.from_dict.return_value = mock_signed
            result = await mixin._verify_receipt("g-badsig", handler)

        data = _parse(result)
        assert data["signature_valid"] is False
        assert data["verified"] is False

    @pytest.mark.asyncio
    async def test_signature_verification_exception(self, mixin):
        """Exception during signature verification adds error."""
        body = _valid_verify_body("g-sigex")
        handler = _make_handler_with_body(body)

        mock_sig_metadata = MagicMock()
        mock_sig_metadata.algorithm = "hmac-sha256"
        mock_sig_metadata.key_id = "key-001"
        mock_sig_metadata.timestamp = "2026-01-01"

        mock_signed = MagicMock()
        mock_signed.receipt_data = body["receipt"]
        mock_signed.signature_metadata = mock_sig_metadata

        mock_receipt_obj = MagicMock()
        mock_receipt_obj.verify_integrity.return_value = True
        mock_receipt_obj._calculate_hash.return_value = "arthash"

        with (
            patch(_SR) as MockSR,
            patch(_VR, side_effect=RuntimeError("crypto error")),
            patch(_DR, return_value=mock_receipt_obj),
        ):
            MockSR.from_dict.return_value = mock_signed
            result = await mixin._verify_receipt("g-sigex", handler)

        data = _parse(result)
        assert data["signature_valid"] is False
        assert any("verification failed" in e.lower() for e in data["errors"])

    @pytest.mark.asyncio
    async def test_integrity_check_fails(self, mixin):
        """Failed integrity check sets integrity_valid=False."""
        body = _valid_verify_body("g-integ")
        handler = _make_handler_with_body(body)

        mock_sig_metadata = MagicMock()
        mock_sig_metadata.algorithm = "hmac-sha256"
        mock_sig_metadata.key_id = "key-001"
        mock_sig_metadata.timestamp = "2026-01-01"

        mock_signed = MagicMock()
        mock_signed.receipt_data = body["receipt"]
        mock_signed.signature_metadata = mock_sig_metadata

        mock_receipt_obj = MagicMock()
        mock_receipt_obj.verify_integrity.return_value = False
        mock_receipt_obj._calculate_hash.return_value = "arthash"

        with (
            patch(_SR) as MockSR,
            patch(_VR, return_value=True),
            patch(_DR, return_value=mock_receipt_obj),
        ):
            MockSR.from_dict.return_value = mock_signed
            result = await mixin._verify_receipt("g-integ", handler)

        data = _parse(result)
        assert data["integrity_valid"] is False
        assert data["verified"] is False
        assert any("tampered" in e for e in data["errors"])

    @pytest.mark.asyncio
    async def test_integrity_check_exception(self, mixin):
        """Exception during integrity check adds error."""
        body = _valid_verify_body("g-integex")
        handler = _make_handler_with_body(body)

        mock_sig_metadata = MagicMock()
        mock_sig_metadata.algorithm = "hmac-sha256"
        mock_sig_metadata.key_id = "key-001"
        mock_sig_metadata.timestamp = "2026-01-01"

        mock_signed = MagicMock()
        mock_signed.receipt_data = body["receipt"]
        mock_signed.signature_metadata = mock_sig_metadata

        mock_receipt_obj = MagicMock()
        # verify_integrity raises to trigger the except branch
        mock_receipt_obj.verify_integrity.side_effect = ValueError("corrupt data")
        mock_receipt_obj._calculate_hash.return_value = "arthash"

        with (
            patch(_SR) as MockSR,
            patch(_VR, return_value=True),
            patch(_DR, return_value=mock_receipt_obj),
        ):
            MockSR.from_dict.return_value = mock_signed
            result = await mixin._verify_receipt("g-integex", handler)

        data = _parse(result)
        assert data["integrity_valid"] is False
        assert any("integrity verification failed" in e.lower() for e in data["errors"])

    @pytest.mark.asyncio
    async def test_verification_result_contains_metadata(self, mixin):
        """Verification result includes signature_metadata."""
        body = _valid_verify_body("g-meta")
        handler = _make_handler_with_body(body)

        mock_sig_metadata = MagicMock()
        mock_sig_metadata.algorithm = "ed25519"
        mock_sig_metadata.key_id = "key-xyz"
        mock_sig_metadata.timestamp = "2026-02-01T10:00:00"

        mock_signed = MagicMock()
        mock_signed.receipt_data = body["receipt"]
        mock_signed.signature_metadata = mock_sig_metadata

        mock_receipt_obj = MagicMock()
        mock_receipt_obj.verify_integrity.return_value = True
        mock_receipt_obj._calculate_hash.return_value = "arthash"

        with (
            patch(_SR) as MockSR,
            patch(_VR, return_value=True),
            patch(_DR, return_value=mock_receipt_obj),
        ):
            MockSR.from_dict.return_value = mock_signed
            result = await mixin._verify_receipt("g-meta", handler)

        data = _parse(result)
        assert data["signature_metadata"]["algorithm"] == "ed25519"
        assert data["signature_metadata"]["key_id"] == "key-xyz"
        assert data["signature_metadata"]["signed_at"] == "2026-02-01T10:00:00"

    @pytest.mark.asyncio
    async def test_verification_contains_verified_at(self, mixin):
        """Result includes a verified_at timestamp."""
        body = _valid_verify_body("g-time")
        handler = _make_handler_with_body(body)

        mock_sig_metadata = MagicMock()
        mock_sig_metadata.algorithm = "hmac-sha256"
        mock_sig_metadata.key_id = "key-001"
        mock_sig_metadata.timestamp = "2026-01-01"

        mock_signed = MagicMock()
        mock_signed.receipt_data = body["receipt"]
        mock_signed.signature_metadata = mock_sig_metadata

        mock_receipt_obj = MagicMock()
        mock_receipt_obj.verify_integrity.return_value = True
        mock_receipt_obj._calculate_hash.return_value = "arthash"

        with (
            patch(_SR) as MockSR,
            patch(_VR, return_value=True),
            patch(_DR, return_value=mock_receipt_obj),
        ):
            MockSR.from_dict.return_value = mock_signed
            result = await mixin._verify_receipt("g-time", handler)

        data = _parse(result)
        assert "verified_at" in data

    @pytest.mark.asyncio
    async def test_all_three_fail_verification(self, mixin):
        """When sig, integrity, and ID all fail, verified is False with multiple errors."""
        body = _valid_verify_body("g-allfail")
        handler = _make_handler_with_body(body)

        mock_sig_metadata = MagicMock()
        mock_sig_metadata.algorithm = "hmac-sha256"
        mock_sig_metadata.key_id = "key-001"
        mock_sig_metadata.timestamp = "2026-01-01"

        mock_signed = MagicMock()
        mock_signed.receipt_data = body["receipt"]
        mock_signed.signature_metadata = mock_sig_metadata

        mock_receipt_obj = MagicMock()
        mock_receipt_obj.verify_integrity.return_value = False
        mock_receipt_obj._calculate_hash.return_value = "arthash"

        with (
            patch(_SR) as MockSR,
            patch(_VR, return_value=False),
            patch(_DR, return_value=mock_receipt_obj),
        ):
            MockSR.from_dict.return_value = mock_signed
            # Use mismatched gauntlet_id
            result = await mixin._verify_receipt("g-WRONG", handler)

        data = _parse(result)
        assert data["verified"] is False
        assert data["signature_valid"] is False
        assert data["integrity_valid"] is False
        assert data["id_match"] is False
        assert len(data["errors"]) >= 3


# ============================================================================
# _auto_persist_receipt
# ============================================================================


class TestAutoPersistReceipt:
    """Tests for _auto_persist_receipt."""

    @pytest.mark.asyncio
    async def test_basic_persist(self, mixin, mock_receipt):
        """Receipt is persisted to store on success."""
        fake_result = FakeResult()
        mock_store = MagicMock()

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-persist")

        mock_store.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_with_signature(self, mixin, mock_receipt):
        """Receipt with signature passes signed_receipt to store.save."""
        fake_result = FakeResult()
        # After receipt.sign() is called, signature will be "base64sig" (from FakeReceipt.sign)
        mock_store = MagicMock()

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-signed-persist")

        call_kwargs = mock_store.save.call_args
        assert call_kwargs is not None
        sr = call_kwargs.kwargs.get("signed_receipt") or call_kwargs[1].get("signed_receipt")
        assert sr is not None
        # FakeReceipt.sign() sets signature to "base64sig"
        assert sr["signature"] == "base64sig"
        assert sr["signature_metadata"]["algorithm"] == "hmac-sha256"

    @pytest.mark.asyncio
    async def test_persist_without_signature(self, mixin, mock_receipt):
        """Receipt without signature passes None for signed_receipt."""
        fake_result = FakeResult()
        # Override sign() to NOT set signature (simulate signing failure path)
        mock_receipt.sign = lambda signer=None: mock_receipt
        mock_receipt.signature = None
        mock_store = MagicMock()

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-unsigned-persist")

        call_kwargs = mock_store.save.call_args
        sr = call_kwargs.kwargs.get("signed_receipt") or call_kwargs[1].get("signed_receipt")
        assert sr is None

    @pytest.mark.asyncio
    async def test_persist_uses_run_input_hash(self, mixin, mock_receipt):
        """Uses input_hash from in-memory run data."""
        fake_result = FakeResult()
        runs = get_gauntlet_runs()
        runs["g-hash"] = {"input_hash": "custom-hash-123"}

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=MagicMock()),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-hash")

        MockDR.from_mode_result.assert_called_once_with(fake_result, input_hash="custom-hash-123")

    @pytest.mark.asyncio
    async def test_persist_import_error_skips(self, mixin):
        """ImportError for receipt module skips persistence."""
        fake_result = FakeResult()

        with patch.dict("sys.modules", {"aragora.gauntlet.receipt": None}):
            await mixin._auto_persist_receipt(fake_result, "g-noimport")

    @pytest.mark.asyncio
    async def test_persist_runtime_error_handled(self, mixin, mock_receipt):
        """RuntimeError during persistence is caught and logged."""
        fake_result = FakeResult()

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(side_effect=RuntimeError("db error")),
                        get_receipt_store=MagicMock(return_value=MagicMock()),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-rterr")

    @pytest.mark.asyncio
    async def test_persist_os_error_handled(self, mixin, mock_receipt):
        """OSError during persistence is caught and logged."""
        fake_result = FakeResult()

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(side_effect=OSError("disk full")),
                        get_receipt_store=MagicMock(return_value=MagicMock()),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-oserr")

    @pytest.mark.asyncio
    async def test_auto_sign_receipts_env_var(self, mixin, mock_receipt):
        """ARAGORA_AUTO_SIGN_RECEIPTS=true triggers auto-signing."""
        fake_result = FakeResult()
        mock_store = MagicMock()
        mock_receipt.signature = "presig"

        mock_signed = MagicMock()
        mock_signed.signature = "auto-sig"
        mock_signed.signature_metadata = MagicMock()
        mock_signed.signature_metadata.algorithm = "hmac-sha256"
        mock_signed.signature_metadata.key_id = "auto-key"

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                    "aragora.gauntlet.signing": MagicMock(
                        sign_receipt=MagicMock(return_value=mock_signed),
                    ),
                },
            ),
            patch.dict("os.environ", {"ARAGORA_AUTO_SIGN_RECEIPTS": "true"}),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-autosign")

        mock_store.update_signature.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_sign_not_triggered_without_env(self, mixin, mock_receipt):
        """Without env var, auto-signing is not triggered."""
        fake_result = FakeResult()
        mock_store = MagicMock()

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                },
            ),
            patch.dict("os.environ", {}, clear=False),
        ):
            import os

            os.environ.pop("ARAGORA_AUTO_SIGN_RECEIPTS", None)
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-noautosign")

        mock_store.update_signature.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_sign_import_error(self, mixin, mock_receipt):
        """ImportError during auto-sign is handled gracefully."""
        fake_result = FakeResult()
        mock_store = MagicMock()
        mock_receipt.signature = "presig"

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                    "aragora.gauntlet.signing": None,
                },
            ),
            patch.dict("os.environ", {"ARAGORA_AUTO_SIGN_RECEIPTS": "1"}),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-autosign-err")

    @pytest.mark.asyncio
    async def test_persist_save_does_not_block_event_loop(self, mixin, mock_receipt):
        """Slow sync receipt-store saves should be offloaded."""
        fake_result = FakeResult()

        class _SlowStore:
            def save(self, receipt_dict: dict[str, Any], signed_receipt=None) -> None:
                time.sleep(0.2)

            def update_signature(self, *args: Any, **kwargs: Any) -> None:
                time.sleep(0.2)

        task = asyncio.create_task(_ticker())
        await asyncio.sleep(0)

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=_SlowStore()),
                    ),
                    "aragora.knowledge.mound.adapters.receipt_adapter": None,
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-slow-persist")

        ticks = await task

        assert ticks >= 30

    @pytest.mark.asyncio
    async def test_risk_level_used_in_stored_receipt(self, mixin, mock_receipt):
        """Stored receipt uses _risk_level_from_score correctly."""
        fake_result = FakeResult()
        mock_receipt.robustness_score = 0.3

        stored_kwargs = {}

        def capture_stored(**kwargs):
            stored_kwargs.update(kwargs)
            m = MagicMock()
            m.checksum = "abc"
            return m

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=capture_stored,
                        get_receipt_store=MagicMock(return_value=MagicMock()),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-risk")

        assert stored_kwargs.get("risk_level") == "CRITICAL"

    @pytest.mark.asyncio
    async def test_risk_score_inverted(self, mixin, mock_receipt):
        """risk_score is 1.0 - robustness_score."""
        fake_result = FakeResult()
        mock_receipt.robustness_score = 0.75

        stored_kwargs = {}

        def capture_stored(**kwargs):
            stored_kwargs.update(kwargs)
            m = MagicMock()
            m.checksum = "abc"
            return m

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=capture_stored,
                        get_receipt_store=MagicMock(return_value=MagicMock()),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-riskscore")

        assert abs(stored_kwargs.get("risk_score", 0) - 0.25) < 0.001

    @pytest.mark.asyncio
    async def test_km_ingestion_success(self, mixin, mock_receipt):
        """Successful KM ingestion logs claims and findings."""
        fake_result = FakeResult()
        mock_store = MagicMock()

        mock_ingest_result = MagicMock()
        mock_ingest_result.success = True
        mock_ingest_result.claims_ingested = 5
        mock_ingest_result.findings_ingested = 3

        mock_adapter = MagicMock()
        mock_adapter.ingest_receipt = AsyncMock(return_value=mock_ingest_result)

        mock_mound = MagicMock()

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                    "aragora.knowledge.mound.adapters.receipt_adapter": MagicMock(
                        ReceiptAdapter=MagicMock(return_value=mock_adapter),
                    ),
                    "aragora.knowledge.mound": MagicMock(
                        get_knowledge_mound=MagicMock(return_value=mock_mound),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-km")

        mock_adapter.ingest_receipt.assert_called_once()

    @pytest.mark.asyncio
    async def test_km_ingestion_import_error(self, mixin, mock_receipt):
        """ImportError during KM ingestion is handled gracefully."""
        fake_result = FakeResult()
        mock_store = MagicMock()

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                    "aragora.knowledge.mound.adapters.receipt_adapter": None,
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-km-noimport")

    @pytest.mark.asyncio
    async def test_km_ingestion_no_mound(self, mixin, mock_receipt):
        """When mound is None, KM ingestion is skipped."""
        fake_result = FakeResult()
        mock_store = MagicMock()

        mock_adapter_cls = MagicMock()

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                    "aragora.knowledge.mound.adapters.receipt_adapter": MagicMock(
                        ReceiptAdapter=mock_adapter_cls,
                    ),
                    "aragora.knowledge.mound": MagicMock(
                        get_knowledge_mound=MagicMock(return_value=None),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-km-nomound")

        mock_adapter_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_webhook_notification_on_persist(self, mixin, mock_receipt):
        """Webhook is notified after receipt persistence."""
        fake_result = FakeResult()
        mock_store = MagicMock()
        mock_notifier = MagicMock()

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="hash-xyz")),
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                    "aragora.integrations.receipt_webhooks": MagicMock(
                        get_receipt_notifier=MagicMock(return_value=mock_notifier),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-webhook")

        mock_notifier.notify_receipt_generated.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_error_handled(self, mixin, mock_receipt):
        """ConnectionError during webhook notification is handled."""
        fake_result = FakeResult()
        mock_store = MagicMock()
        mock_notifier = MagicMock()
        mock_notifier.notify_receipt_generated.side_effect = ConnectionError("timeout")

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                    "aragora.integrations.receipt_webhooks": MagicMock(
                        get_receipt_notifier=MagicMock(return_value=mock_notifier),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-webhookerr")

    @pytest.mark.asyncio
    async def test_debate_id_from_result(self, mixin, mock_receipt):
        """Uses debate_id from result when available."""
        fake_result = FakeResult(debate_id="debate-custom")
        mock_store = MagicMock()

        stored_kwargs = {}

        def capture_stored(**kwargs):
            stored_kwargs.update(kwargs)
            m = MagicMock()
            m.checksum = "abc"
            return m

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=capture_stored,
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-debateid")

        assert stored_kwargs.get("debate_id") == "debate-custom"

    @pytest.mark.asyncio
    async def test_workspace_id_from_run(self, mixin, mock_receipt):
        """Uses workspace_id from run data for KM ingestion."""
        fake_result = FakeResult()
        runs = get_gauntlet_runs()
        runs["g-ws"] = {"workspace_id": "ws-001"}
        mock_store = MagicMock()

        mock_ingest_result = MagicMock()
        mock_ingest_result.success = True
        mock_ingest_result.claims_ingested = 0
        mock_ingest_result.findings_ingested = 0

        mock_adapter = MagicMock()
        mock_adapter.ingest_receipt = AsyncMock(return_value=mock_ingest_result)

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                    "aragora.knowledge.mound.adapters.receipt_adapter": MagicMock(
                        ReceiptAdapter=MagicMock(return_value=mock_adapter),
                    ),
                    "aragora.knowledge.mound": MagicMock(
                        get_knowledge_mound=MagicMock(return_value=MagicMock()),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-ws")

        call_kwargs = mock_adapter.ingest_receipt.call_args
        assert call_kwargs.kwargs.get("workspace_id") == "ws-001"

    @pytest.mark.asyncio
    async def test_tenant_id_fallback(self, mixin, mock_receipt):
        """Falls back to tenant_id when workspace_id is absent."""
        fake_result = FakeResult()
        runs = get_gauntlet_runs()
        runs["g-tenant"] = {"tenant_id": "tenant-002"}
        mock_store = MagicMock()

        mock_ingest_result = MagicMock()
        mock_ingest_result.success = True
        mock_ingest_result.claims_ingested = 0
        mock_ingest_result.findings_ingested = 0

        mock_adapter = MagicMock()
        mock_adapter.ingest_receipt = AsyncMock(return_value=mock_ingest_result)

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                    "aragora.knowledge.mound.adapters.receipt_adapter": MagicMock(
                        ReceiptAdapter=MagicMock(return_value=mock_adapter),
                    ),
                    "aragora.knowledge.mound": MagicMock(
                        get_knowledge_mound=MagicMock(return_value=MagicMock()),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-tenant")

        call_kwargs = mock_adapter.ingest_receipt.call_args
        assert call_kwargs.kwargs.get("workspace_id") == "tenant-002"


# ============================================================================
# _get_receipt - webhook notification per format
# ============================================================================


class TestGetReceiptWebhookNotifications:
    """Tests for webhook notifications in _get_receipt export."""

    @pytest.mark.asyncio
    async def test_json_export_notifies_webhook(self, mixin, mock_receipt):
        runs = get_gauntlet_runs()
        runs["g-wh-json"] = _completed_run()
        mock_notifier = MagicMock()

        with (
            patch(_DR, return_value=mock_receipt),
            patch.dict(
                "sys.modules",
                {
                    "aragora.integrations.receipt_webhooks": MagicMock(
                        get_receipt_notifier=MagicMock(return_value=mock_notifier),
                    ),
                },
            ),
        ):
            result = await mixin._get_receipt("g-wh-json", {"signed": "false"})

        assert _status(result) == 200
        mock_notifier.notify_receipt_exported.assert_called_once()
        call_kwargs = mock_notifier.notify_receipt_exported.call_args
        assert call_kwargs.kwargs.get("export_format") == "json"

    @pytest.mark.asyncio
    async def test_html_export_notifies_webhook(self, mixin, mock_receipt):
        runs = get_gauntlet_runs()
        runs["g-wh-html"] = _completed_run()
        mock_notifier = MagicMock()

        with (
            patch(_DR, return_value=mock_receipt),
            patch.dict(
                "sys.modules",
                {
                    "aragora.integrations.receipt_webhooks": MagicMock(
                        get_receipt_notifier=MagicMock(return_value=mock_notifier),
                    ),
                },
            ),
        ):
            result = await mixin._get_receipt("g-wh-html", {"format": "html", "signed": "false"})

        mock_notifier.notify_receipt_exported.assert_called_once()
        call_kwargs = mock_notifier.notify_receipt_exported.call_args
        assert call_kwargs.kwargs.get("export_format") == "html"

    @pytest.mark.asyncio
    async def test_webhook_import_error_skipped(self, mixin, mock_receipt):
        """ImportError for webhook module is silently skipped."""
        runs = get_gauntlet_runs()
        runs["g-wh-skip"] = _completed_run()

        with (
            patch(_DR, return_value=mock_receipt),
            patch.dict(
                "sys.modules",
                {
                    "aragora.integrations.receipt_webhooks": None,
                },
            ),
        ):
            result = await mixin._get_receipt("g-wh-skip", {"signed": "false"})

        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_csv_export_notifies_webhook(self, mixin, mock_receipt):
        runs = get_gauntlet_runs()
        runs["g-wh-csv"] = _completed_run()
        mock_notifier = MagicMock()

        with (
            patch(_DR, return_value=mock_receipt),
            patch.dict(
                "sys.modules",
                {
                    "aragora.integrations.receipt_webhooks": MagicMock(
                        get_receipt_notifier=MagicMock(return_value=mock_notifier),
                    ),
                },
            ),
        ):
            result = await mixin._get_receipt("g-wh-csv", {"format": "csv", "signed": "false"})

        mock_notifier.notify_receipt_exported.assert_called_once()
        call_kwargs = mock_notifier.notify_receipt_exported.call_args
        assert call_kwargs.kwargs.get("export_format") == "csv"

    @pytest.mark.asyncio
    async def test_sarif_export_notifies_webhook(self, mixin, mock_receipt):
        runs = get_gauntlet_runs()
        runs["g-wh-sarif"] = _completed_run()
        mock_notifier = MagicMock()

        with (
            patch(_DR, return_value=mock_receipt),
            patch.dict(
                "sys.modules",
                {
                    "aragora.integrations.receipt_webhooks": MagicMock(
                        get_receipt_notifier=MagicMock(return_value=mock_notifier),
                    ),
                },
            ),
        ):
            result = await mixin._get_receipt("g-wh-sarif", {"format": "sarif", "signed": "false"})

        mock_notifier.notify_receipt_exported.assert_called_once()
        call_kwargs = mock_notifier.notify_receipt_exported.call_args
        assert call_kwargs.kwargs.get("export_format") == "sarif"

    @pytest.mark.asyncio
    async def test_markdown_export_notifies_webhook(self, mixin, mock_receipt):
        runs = get_gauntlet_runs()
        runs["g-wh-md"] = _completed_run()
        mock_notifier = MagicMock()

        with (
            patch(_DR, return_value=mock_receipt),
            patch.dict(
                "sys.modules",
                {
                    "aragora.integrations.receipt_webhooks": MagicMock(
                        get_receipt_notifier=MagicMock(return_value=mock_notifier),
                    ),
                },
            ),
        ):
            result = await mixin._get_receipt("g-wh-md", {"format": "md", "signed": "false"})

        mock_notifier.notify_receipt_exported.assert_called_once()
        call_kwargs = mock_notifier.notify_receipt_exported.call_args
        assert call_kwargs.kwargs.get("export_format") == "markdown"


# ============================================================================
# _verify_receipt - webhook notifications
# ============================================================================


class TestVerifyReceiptWebhooks:
    """Tests for webhook calls during receipt verification."""

    def _setup_verify(self, gauntlet_id, integrity_valid=True):
        """Helper to set up common mocks for verify tests."""
        body = _valid_verify_body(gauntlet_id)
        handler = _make_handler_with_body(body)

        mock_sig_metadata = MagicMock()
        mock_sig_metadata.algorithm = "hmac-sha256"
        mock_sig_metadata.key_id = "key-001"
        mock_sig_metadata.timestamp = "2026-01-01"

        mock_signed = MagicMock()
        mock_signed.receipt_data = body["receipt"]
        mock_signed.signature_metadata = mock_sig_metadata

        mock_receipt_obj = MagicMock()
        mock_receipt_obj.verify_integrity.return_value = integrity_valid
        mock_receipt_obj._calculate_hash.return_value = "arthash"

        return handler, mock_signed, mock_receipt_obj

    @pytest.mark.asyncio
    async def test_verified_webhook_on_success(self, mixin):
        """Verified receipt triggers notify_receipt_verified."""
        handler, mock_signed, mock_receipt_obj = self._setup_verify("g-wh-ok")
        mock_notifier = MagicMock()

        with (
            patch(_SR) as MockSR,
            patch(_VR, return_value=True),
            patch(_DR, return_value=mock_receipt_obj),
            patch.dict(
                "sys.modules",
                {
                    "aragora.integrations.receipt_webhooks": MagicMock(
                        get_receipt_notifier=MagicMock(return_value=mock_notifier),
                    ),
                },
            ),
        ):
            MockSR.from_dict.return_value = mock_signed
            result = await mixin._verify_receipt("g-wh-ok", handler)

        mock_notifier.notify_receipt_verified.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_webhook_on_failure(self, mixin):
        """Failed verification triggers notify_receipt_integrity_failed."""
        handler, mock_signed, mock_receipt_obj = self._setup_verify("g-wh-fail")
        mock_notifier = MagicMock()

        with (
            patch(_SR) as MockSR,
            patch(_VR, return_value=False),
            patch(_DR, return_value=mock_receipt_obj),
            patch.dict(
                "sys.modules",
                {
                    "aragora.integrations.receipt_webhooks": MagicMock(
                        get_receipt_notifier=MagicMock(return_value=mock_notifier),
                    ),
                },
            ),
        ):
            MockSR.from_dict.return_value = mock_signed
            result = await mixin._verify_receipt("g-wh-fail", handler)

        mock_notifier.notify_receipt_integrity_failed.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_error_during_verify_skipped(self, mixin):
        """Webhook errors during verify don't break the response."""
        handler, mock_signed, mock_receipt_obj = self._setup_verify("g-wh-err")
        mock_notifier = MagicMock()
        mock_notifier.notify_receipt_verified.side_effect = ConnectionError("down")

        with (
            patch(_SR) as MockSR,
            patch(_VR, return_value=True),
            patch(_DR, return_value=mock_receipt_obj),
            patch.dict(
                "sys.modules",
                {
                    "aragora.integrations.receipt_webhooks": MagicMock(
                        get_receipt_notifier=MagicMock(return_value=mock_notifier),
                    ),
                },
            ),
        ):
            MockSR.from_dict.return_value = mock_signed
            result = await mixin._verify_receipt("g-wh-err", handler)

        assert _status(result) == 200


# ============================================================================
# Additional edge cases
# ============================================================================


class TestGetReceiptEdgeCases:
    """Additional edge case tests for _get_receipt."""

    @pytest.mark.asyncio
    async def test_receipt_id_derives_from_gauntlet_id_last_12(self, mixin):
        """Receipt ID is derived from last 12 characters of gauntlet_id."""
        runs = get_gauntlet_runs()
        gid = "gauntlet-XYZW12345678"
        runs[gid] = {
            "status": "completed",
            "result": {"total_findings": 0},
            "result_obj": None,
            "input_summary": "Test",
            "input_hash": "h",
            "completed_at": "2026-01-01",
        }

        captured = {}

        def fake_init(**kwargs):
            captured.update(kwargs)
            return FakeReceipt(**{k: v for k, v in kwargs.items() if hasattr(FakeReceipt, k)})

        with patch(_DR, side_effect=fake_init):
            result = await mixin._get_receipt(gid, {"signed": "false"})

        assert _status(result) == 200
        assert captured["receipt_id"] == f"receipt-{gid[-12:]}"

    @pytest.mark.asyncio
    async def test_format_param_as_list(self, mixin, mock_receipt):
        """Format param passed as list (from query string parsing)."""
        runs = get_gauntlet_runs()
        runs["g-list"] = _completed_run()

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-list", {"format": ["html"]})

        assert _status(result) == 200
        assert result.content_type == "text/html"

    @pytest.mark.asyncio
    async def test_no_format_param_defaults_json(self, mixin, mock_receipt):
        """No format param defaults to JSON."""
        runs = get_gauntlet_runs()
        runs["g-default"] = _completed_run()

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-default", {})

        assert _status(result) == 200
        assert result.content_type == "application/json"

    @pytest.mark.asyncio
    async def test_signed_param_true_signs(self, mixin, mock_receipt):
        """signed=true (explicit) still signs the receipt."""
        runs = get_gauntlet_runs()
        runs["g-strue"] = _completed_run()

        sign_called = []
        original_sign = mock_receipt.sign

        def track_sign(signer=None):
            sign_called.append(True)
            return original_sign(signer)

        mock_receipt.sign = track_sign

        with patch(_DR, return_value=mock_receipt):
            result = await mixin._get_receipt("g-strue", {"signed": "true"})

        assert _status(result) == 200
        assert len(sign_called) == 1

    @pytest.mark.asyncio
    async def test_result_obj_with_no_input_hash(self, mixin, mock_receipt):
        """result_obj path works when run has no input_hash key."""
        runs = get_gauntlet_runs()
        fake_result = FakeResult()
        runs["g-nohash"] = {
            "status": "completed",
            "result": {"total_findings": 0},
            "result_obj": fake_result,
        }

        with patch(_DR) as MockDR:
            MockDR.from_mode_result.return_value = mock_receipt
            result = await mixin._get_receipt("g-nohash", {"signed": "false"})

        assert _status(result) == 200
        MockDR.from_mode_result.assert_called_once_with(fake_result, input_hash=None)

    @pytest.mark.asyncio
    async def test_storage_returns_full_result(self, mixin, mock_storage, mock_receipt):
        """Storage returns result with all counts populated."""
        mock_storage.get.return_value = {
            "critical_count": 5,
            "high_count": 10,
            "medium_count": 15,
            "low_count": 20,
            "total_findings": 50,
            "verdict": "FAIL",
            "confidence": 0.3,
            "robustness_score": 0.2,
            "input_summary": "Complex decision",
            "input_hash": "complex-hash",
        }

        captured = {}

        def fake_init(**kwargs):
            captured.update(kwargs)
            return FakeReceipt(**{k: v for k, v in kwargs.items() if hasattr(FakeReceipt, k)})

        with patch(_DR, side_effect=fake_init):
            result = await mixin._get_receipt("g-full", {"signed": "false"})

        assert _status(result) == 200
        assert captured["risk_summary"]["critical"] == 5
        assert captured["risk_summary"]["total"] == 50
        assert captured["vulnerabilities_found"] == 50
        assert captured["verdict"] == "FAIL"


class TestVerifyReceiptEdgeCases:
    """Additional edge case tests for _verify_receipt."""

    @pytest.mark.asyncio
    async def test_empty_body_returns_400(self, mixin):
        """Empty dict body is treated as missing required fields."""
        handler = _make_handler_with_body({})
        result = await mixin._verify_receipt("g-empty", handler)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_signature_import_error(self, mixin):
        """ImportError during signature verification adds error."""
        body = _valid_verify_body("g-imerr")
        handler = _make_handler_with_body(body)

        mock_sig_metadata = MagicMock()
        mock_sig_metadata.algorithm = "hmac-sha256"
        mock_sig_metadata.key_id = "key-001"
        mock_sig_metadata.timestamp = "2026-01-01"

        mock_signed = MagicMock()
        mock_signed.receipt_data = body["receipt"]
        mock_signed.signature_metadata = mock_sig_metadata

        mock_receipt_obj = MagicMock()
        mock_receipt_obj.verify_integrity.return_value = True
        mock_receipt_obj._calculate_hash.return_value = "arthash"

        with (
            patch(_SR) as MockSR,
            patch(_VR, side_effect=ImportError("no crypto backend")),
            patch(_DR, return_value=mock_receipt_obj),
        ):
            MockSR.from_dict.return_value = mock_signed
            result = await mixin._verify_receipt("g-imerr", handler)

        data = _parse(result)
        assert data["signature_valid"] is False
        assert any("verification failed" in e.lower() for e in data["errors"])

    @pytest.mark.asyncio
    async def test_signature_value_error(self, mixin):
        """ValueError during signature verification adds error."""
        body = _valid_verify_body("g-valerr")
        handler = _make_handler_with_body(body)

        mock_sig_metadata = MagicMock()
        mock_sig_metadata.algorithm = "hmac-sha256"
        mock_sig_metadata.key_id = "key-001"
        mock_sig_metadata.timestamp = "2026-01-01"

        mock_signed = MagicMock()
        mock_signed.receipt_data = body["receipt"]
        mock_signed.signature_metadata = mock_sig_metadata

        mock_receipt_obj = MagicMock()
        mock_receipt_obj.verify_integrity.return_value = True
        mock_receipt_obj._calculate_hash.return_value = "arthash"

        with (
            patch(_SR) as MockSR,
            patch(_VR, side_effect=ValueError("bad key format")),
            patch(_DR, return_value=mock_receipt_obj),
        ):
            MockSR.from_dict.return_value = mock_signed
            result = await mixin._verify_receipt("g-valerr", handler)

        data = _parse(result)
        assert data["signature_valid"] is False

    @pytest.mark.asyncio
    async def test_receipt_gauntlet_id_none(self, mixin):
        """Receipt with no gauntlet_id field still works (mismatch)."""
        body = _valid_verify_body("g-none")
        body["receipt"]["gauntlet_id"] = None
        handler = _make_handler_with_body(body)

        mock_sig_metadata = MagicMock()
        mock_sig_metadata.algorithm = "hmac-sha256"
        mock_sig_metadata.key_id = "key-001"
        mock_sig_metadata.timestamp = "2026-01-01"

        mock_signed = MagicMock()
        mock_signed.receipt_data = body["receipt"]
        mock_signed.signature_metadata = mock_sig_metadata

        mock_receipt_obj = MagicMock()
        mock_receipt_obj.verify_integrity.return_value = True
        mock_receipt_obj._calculate_hash.return_value = "arthash"

        with (
            patch(_SR) as MockSR,
            patch(_VR, return_value=True),
            patch(_DR, return_value=mock_receipt_obj),
        ):
            MockSR.from_dict.return_value = mock_signed
            result = await mixin._verify_receipt("g-none", handler)

        data = _parse(result)
        assert data["id_match"] is False

    @pytest.mark.asyncio
    async def test_verified_false_returns_200(self, mixin):
        """Failed verification still returns 200 (not a client error)."""
        body = _valid_verify_body("g-fail200")
        handler = _make_handler_with_body(body)

        mock_sig_metadata = MagicMock()
        mock_sig_metadata.algorithm = "hmac-sha256"
        mock_sig_metadata.key_id = "key-001"
        mock_sig_metadata.timestamp = "2026-01-01"

        mock_signed = MagicMock()
        mock_signed.receipt_data = body["receipt"]
        mock_signed.signature_metadata = mock_sig_metadata

        mock_receipt_obj = MagicMock()
        mock_receipt_obj.verify_integrity.return_value = False
        mock_receipt_obj._calculate_hash.return_value = "arthash"

        with (
            patch(_SR) as MockSR,
            patch(_VR, return_value=False),
            patch(_DR, return_value=mock_receipt_obj),
        ):
            MockSR.from_dict.return_value = mock_signed
            result = await mixin._verify_receipt("g-fail200", handler)

        # Both success and failure return 200
        assert _status(result) == 200
        data = _parse(result)
        assert data["verified"] is False


class TestAutoPersistEdgeCases:
    """Additional edge case tests for _auto_persist_receipt."""

    @pytest.mark.asyncio
    async def test_auto_sign_env_yes(self, mixin, mock_receipt):
        """ARAGORA_AUTO_SIGN_RECEIPTS=yes also triggers signing."""
        fake_result = FakeResult()
        mock_store = MagicMock()

        mock_signed = MagicMock()
        mock_signed.signature = "auto-sig"
        mock_signed.signature_metadata = MagicMock()
        mock_signed.signature_metadata.algorithm = "hmac-sha256"
        mock_signed.signature_metadata.key_id = "auto-key"

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                    "aragora.gauntlet.signing": MagicMock(
                        sign_receipt=MagicMock(return_value=mock_signed),
                    ),
                },
            ),
            patch.dict("os.environ", {"ARAGORA_AUTO_SIGN_RECEIPTS": "yes"}),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-autosign-yes")

        mock_store.update_signature.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_run_data_uses_empty_dict(self, mixin, mock_receipt):
        """When gauntlet_id not in runs, run defaults to empty dict."""
        fake_result = FakeResult()
        mock_store = MagicMock()

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(return_value=MagicMock(checksum="abc")),
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-norun")

        MockDR.from_mode_result.assert_called_once_with(fake_result, input_hash=None)

    @pytest.mark.asyncio
    async def test_key_error_handled(self, mixin, mock_receipt):
        """KeyError during persistence is caught."""
        fake_result = FakeResult()

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(side_effect=KeyError("missing field")),
                        get_receipt_store=MagicMock(return_value=MagicMock()),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            # Should not raise
            await mixin._auto_persist_receipt(fake_result, "g-keyerr")

    @pytest.mark.asyncio
    async def test_type_error_handled(self, mixin, mock_receipt):
        """TypeError during persistence is caught."""
        fake_result = FakeResult()

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=MagicMock(side_effect=TypeError("bad type")),
                        get_receipt_store=MagicMock(return_value=MagicMock()),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-typeerr")

    @pytest.mark.asyncio
    async def test_result_without_debate_id(self, mixin, mock_receipt):
        """Result without debate_id attribute uses None."""
        fake_result = MagicMock(spec=[])  # No attributes
        mock_store = MagicMock()

        stored_kwargs = {}

        def capture_stored(**kwargs):
            stored_kwargs.update(kwargs)
            m = MagicMock()
            m.checksum = "abc"
            return m

        with (
            patch(_DR) as MockDR,
            patch.dict(
                "sys.modules",
                {
                    "aragora.storage.receipt_store": MagicMock(
                        StoredReceipt=capture_stored,
                        get_receipt_store=MagicMock(return_value=mock_store),
                    ),
                },
            ),
        ):
            MockDR.from_mode_result.return_value = mock_receipt
            await mixin._auto_persist_receipt(fake_result, "g-nodebateid")

        assert stored_kwargs.get("debate_id") is None
