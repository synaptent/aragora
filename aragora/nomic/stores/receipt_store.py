"""Persistent store for Nomic cycle receipts.

JSONL-backed store following the same pattern as ``run_store.py``.
Each receipt is a JSON object appended to a JSONL file with an
in-memory index for fast lookups.

Part of Epic #295 Stream 1: Signed receipts for self-improvement audit.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from aragora.nomic.cycle_receipt import NomicCycleReceipt

logger = logging.getLogger(__name__)


class NomicReceiptStore:
    """Persistent store for Nomic self-improvement cycle receipts.

    Uses JSONL file for durable append-only storage with an in-memory
    index for fast lookups.  Follows the same pattern as
    :class:`~aragora.nomic.stores.run_store.SelfImproveRunStore`.

    Example::

        store = NomicReceiptStore(data_dir=Path("/tmp/test"))
        store.save_receipt(receipt)
        retrieved = store.get_receipt(receipt.receipt_id)
        assert retrieved is not None
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        if data_dir is None:
            from aragora.persistence.db_config import get_default_data_dir

            data_dir = get_default_data_dir()
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._receipts_file = self._data_dir / "nomic_cycle_receipts.jsonl"
        self._receipts: dict[str, NomicCycleReceipt] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load receipts from JSONL file."""
        if not self._receipts_file.exists():
            return
        try:
            for line in self._receipts_file.read_text().strip().splitlines():
                if line.strip():
                    d = json.loads(line)
                    receipt = NomicCycleReceipt.from_dict(d)
                    self._receipts[receipt.receipt_id] = receipt
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Error loading nomic cycle receipts: %s", type(e).__name__)

    def _persist(self) -> None:
        """Rewrite the full JSONL file from the in-memory index."""
        lines = [json.dumps(r.to_dict()) for r in self._receipts.values()]
        self._receipts_file.write_text("\n".join(lines) + "\n" if lines else "")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_receipt(self, receipt: NomicCycleReceipt) -> None:
        """Save (or update) a receipt."""
        self._receipts[receipt.receipt_id] = receipt
        self._persist()

    def get_receipt(self, receipt_id: str) -> NomicCycleReceipt | None:
        """Retrieve a receipt by ID, or ``None`` if not found."""
        return self._receipts.get(receipt_id)

    def list_receipts(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NomicCycleReceipt]:
        """List receipts ordered by timestamp (newest first)."""
        receipts = sorted(
            self._receipts.values(),
            key=lambda r: r.timestamp,
            reverse=True,
        )
        return receipts[offset : offset + limit]

    def verify_receipt(self, receipt_id: str) -> bool | None:
        """Verify the integrity of a stored receipt.

        Returns:
            ``True`` if the receipt passes its integrity hash check,
            ``False`` if it fails, or ``None`` if the receipt is not found.
        """
        receipt = self._receipts.get(receipt_id)
        if receipt is None:
            return None
        return receipt.verify_integrity()

    def count(self) -> int:
        """Return the number of stored receipts."""
        return len(self._receipts)
