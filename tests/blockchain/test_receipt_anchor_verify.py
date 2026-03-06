"""
Tests for ReceiptAnchor.verify_anchor and receipt anchor API endpoints.
"""

from __future__ import annotations

import hashlib
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from aragora.blockchain.receipt_anchor import AnchorRecord, ReceiptAnchor


class TestVerifyAnchorNoAnchors:
    """Tests for verify_anchor when no anchors exist."""

    def test_verify_no_anchors(self):
        """verify_anchor returns anchored=False when no anchors exist."""
        anchor = ReceiptAnchor()
        receipt_hash = hashlib.sha256(b"nonexistent receipt").hexdigest()
        result = anchor.verify_anchor(receipt_hash)

        assert result["anchored"] is False
        assert result["receipt_hash"] == receipt_hash
        assert result["anchors"] == []
        assert "verified_at" in result
        assert isinstance(result["verified_at"], float)

    def test_verify_no_anchors_for_specific_hash(self):
        """verify_anchor returns anchored=False when other hashes are anchored but not this one."""
        anchor = ReceiptAnchor()
        # Anchor a different receipt
        anchor._local_anchors.append(
            AnchorRecord(
                receipt_hash="other_hash",
                timestamp=time.time(),
                local_only=True,
            )
        )

        result = anchor.verify_anchor("my_hash")
        assert result["anchored"] is False
        assert result["anchors"] == []


class TestVerifyAnchorLocal:
    """Tests for verify_anchor with local anchors."""

    @pytest.mark.asyncio
    async def test_verify_local_anchor(self):
        """verify_anchor returns correct info for a local anchor."""
        anchor = ReceiptAnchor()
        receipt_hash = hashlib.sha256(b"test receipt").hexdigest()
        await anchor.anchor_receipt(receipt_hash, metadata={"debate_id": "d1"})

        result = anchor.verify_anchor(receipt_hash)

        assert result["anchored"] is True
        assert result["receipt_hash"] == receipt_hash
        assert len(result["anchors"]) == 1

        anchor_detail = result["anchors"][0]
        assert anchor_detail["type"] == "local"
        assert anchor_detail["timestamp"] > 0
        assert anchor_detail["metadata"] == {"debate_id": "d1"}

    @pytest.mark.asyncio
    async def test_verify_multiple_local_anchors(self):
        """verify_anchor returns all anchors for the same hash."""
        anchor = ReceiptAnchor()
        receipt_hash = hashlib.sha256(b"test receipt").hexdigest()
        await anchor.anchor_receipt(receipt_hash, metadata={"round": 1})
        await anchor.anchor_receipt(receipt_hash, metadata={"round": 2})

        result = anchor.verify_anchor(receipt_hash)

        assert result["anchored"] is True
        assert len(result["anchors"]) == 2
        assert result["anchors"][0]["metadata"] == {"round": 1}
        assert result["anchors"][1]["metadata"] == {"round": 2}


class TestVerifyAnchorOnChain:
    """Tests for verify_anchor with on-chain anchors."""

    def test_verify_on_chain_anchor(self):
        """verify_anchor returns correct info for an on-chain anchor."""
        anchor = ReceiptAnchor()
        receipt_hash = hashlib.sha256(b"on-chain receipt").hexdigest()

        # Manually add an on-chain anchor record
        anchor._local_anchors.append(
            AnchorRecord(
                receipt_hash=receipt_hash,
                tx_hash="0x" + "ab" * 32,
                chain_id=1,
                timestamp=time.time(),
                metadata={"debate_id": "d1", "block_number": 12345},
                local_only=False,
            )
        )

        result = anchor.verify_anchor(receipt_hash)

        assert result["anchored"] is True
        assert len(result["anchors"]) == 1

        anchor_detail = result["anchors"][0]
        assert anchor_detail["type"] == "on_chain"
        assert anchor_detail["tx_hash"] == "0x" + "ab" * 32
        assert anchor_detail["chain_id"] == 1
        assert anchor_detail["block_number"] == 12345
        assert anchor_detail["timestamp"] > 0

    def test_verify_on_chain_no_block_number(self):
        """On-chain anchor without block_number in metadata omits that field."""
        anchor = ReceiptAnchor()
        receipt_hash = "abc123"

        anchor._local_anchors.append(
            AnchorRecord(
                receipt_hash=receipt_hash,
                tx_hash="0xdef",
                chain_id=5,
                timestamp=time.time(),
                metadata={},
                local_only=False,
            )
        )

        result = anchor.verify_anchor(receipt_hash)
        anchor_detail = result["anchors"][0]
        assert "block_number" not in anchor_detail

    def test_verify_mixed_anchors(self):
        """verify_anchor handles a mix of local and on-chain anchors."""
        anchor = ReceiptAnchor()
        receipt_hash = "mixed_hash"

        anchor._local_anchors.append(
            AnchorRecord(
                receipt_hash=receipt_hash,
                tx_hash="0xtx1",
                chain_id=1,
                timestamp=100.0,
                metadata={},
                local_only=False,
            )
        )
        anchor._local_anchors.append(
            AnchorRecord(
                receipt_hash=receipt_hash,
                timestamp=200.0,
                metadata={},
                local_only=True,
            )
        )

        result = anchor.verify_anchor(receipt_hash)

        assert result["anchored"] is True
        assert len(result["anchors"]) == 2
        assert result["anchors"][0]["type"] == "on_chain"
        assert result["anchors"][1]["type"] == "local"


class TestReceiptAnchorStatusEndpoint:
    """Tests for the _get_receipt_anchor_status handler method."""

    def _make_mixin(self):
        """Create a GauntletReceiptsMixin instance for testing."""
        from aragora.server.handlers.gauntlet.receipts import GauntletReceiptsMixin

        mixin = GauntletReceiptsMixin.__new__(GauntletReceiptsMixin)
        return mixin

    def test_receipt_not_found(self):
        """Returns 404 when receipt does not exist."""
        mock_store = MagicMock()
        mock_store.get.return_value = None

        mixin = self._make_mixin()

        with patch("aragora.storage.receipt_store.get_receipt_store", return_value=mock_store):
            from aragora.server.handlers.gauntlet.receipts import GauntletReceiptsMixin

            result = GauntletReceiptsMixin._get_receipt_anchor_status.__wrapped__(
                mixin, "nonexistent-id", {}
            )

        assert result.status_code == 404

    def test_receipt_found_with_anchor(self):
        """Returns anchor status when receipt exists and has been anchored."""
        receipt_hash = hashlib.sha256(b"test").hexdigest()
        mock_receipt = MagicMock()
        mock_receipt.checksum = receipt_hash

        mock_store = MagicMock()
        mock_store.get.return_value = mock_receipt

        # Create a real ReceiptAnchor with a pre-existing local anchor
        real_anchor = ReceiptAnchor()
        real_anchor._local_anchors.append(
            AnchorRecord(
                receipt_hash=receipt_hash,
                timestamp=time.time(),
                metadata={"debate_id": "d1"},
                local_only=True,
            )
        )

        mixin = self._make_mixin()
        mixin._receipt_anchor = real_anchor

        with patch("aragora.storage.receipt_store.get_receipt_store", return_value=mock_store):
            from aragora.server.handlers.gauntlet.receipts import GauntletReceiptsMixin

            result = GauntletReceiptsMixin._get_receipt_anchor_status.__wrapped__(
                mixin, "receipt-123", {}
            )

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["anchored"] is True
        assert body["receipt_id"] == "receipt-123"
        assert len(body["anchors"]) == 1

    def test_receipt_no_checksum(self):
        """Returns anchored=False when receipt has no checksum."""
        mock_receipt = MagicMock()
        mock_receipt.checksum = ""

        mock_store = MagicMock()
        mock_store.get.return_value = mock_receipt

        mixin = self._make_mixin()

        with patch("aragora.storage.receipt_store.get_receipt_store", return_value=mock_store):
            from aragora.server.handlers.gauntlet.receipts import GauntletReceiptsMixin

            result = GauntletReceiptsMixin._get_receipt_anchor_status.__wrapped__(
                mixin, "receipt-no-hash", {}
            )

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["anchored"] is False


class TestRecentAnchorsEndpoint:
    """Tests for the _get_recent_anchors handler method."""

    def _make_mixin(self):
        from aragora.server.handlers.gauntlet.receipts import GauntletReceiptsMixin

        mixin = GauntletReceiptsMixin.__new__(GauntletReceiptsMixin)
        return mixin

    def test_empty_anchors(self):
        """Returns empty list when no anchors exist."""
        mixin = self._make_mixin()
        mixin._receipt_anchor = ReceiptAnchor()

        from aragora.server.handlers.gauntlet.receipts import GauntletReceiptsMixin

        result = GauntletReceiptsMixin._get_recent_anchors.__wrapped__(mixin, {})

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["anchors"] == []
        assert body["total"] == 0

    def test_returns_limited_anchors(self):
        """Returns anchors respecting the limit parameter."""
        mixin = self._make_mixin()
        anchor = ReceiptAnchor()

        # Add 5 local anchors with increasing timestamps
        for i in range(5):
            anchor._local_anchors.append(
                AnchorRecord(
                    receipt_hash=f"hash_{i}",
                    timestamp=1000.0 + i,
                    metadata={"index": i},
                    local_only=True,
                )
            )

        mixin._receipt_anchor = anchor

        from aragora.server.handlers.gauntlet.receipts import GauntletReceiptsMixin

        result = GauntletReceiptsMixin._get_recent_anchors.__wrapped__(mixin, {"limit": "3"})

        assert result.status_code == 200
        body = json.loads(result.body)
        assert len(body["anchors"]) == 3
        assert body["total"] == 5
        # Most recent first
        assert body["anchors"][0]["receipt_hash"] == "hash_4"
        assert body["anchors"][1]["receipt_hash"] == "hash_3"

    def test_default_limit(self):
        """Uses default limit of 10 when not specified."""
        mixin = self._make_mixin()
        mixin._receipt_anchor = ReceiptAnchor()

        from aragora.server.handlers.gauntlet.receipts import GauntletReceiptsMixin

        result = GauntletReceiptsMixin._get_recent_anchors.__wrapped__(mixin, {})

        body = json.loads(result.body)
        assert body["limit"] == 10
