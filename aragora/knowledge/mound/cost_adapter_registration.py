"""Knowledge-side composition for billing cost persistence."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register_billing_cost_adapter() -> None:
    """Attach the Knowledge Mound cost adapter to the global billing tracker."""
    from aragora.billing.cost_tracker import get_cost_tracker
    from aragora.knowledge.mound.adapters.cost_adapter import CostAdapter

    tracker = get_cost_tracker()
    tracker.set_km_adapter(CostAdapter(enable_dual_write=True))
    logger.info("CostTracker KM adapter registered for bidirectional sync")
