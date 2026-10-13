"""QuickBooks Connector (DEPRECATED).

This module is superseded by ``aragora.connectors.accounting.qbo`` which
provides a full QuickBooks Online integration with OAuth 2.0, transaction
sync, multi-company support, and more.

Import ``QuickBooksConnector`` from the package or from ``qbo`` instead::

    from aragora.connectors.accounting import QuickBooksConnector
    # or
    from aragora.connectors.accounting.qbo import QuickBooksConnector
"""

from __future__ import annotations

import logging
import os
import re
import warnings
from typing import Any

import httpx

from aragora.connectors.base import BaseConnector, Evidence
from aragora.connectors.exceptions import ConnectorError
from aragora.reasoning.provenance import SourceType

logger = logging.getLogger(__name__)

CONFIG_ENV_VARS = (
    "QUICKBOOKS_CLIENT_ID",
    "QUICKBOOKS_CLIENT_SECRET",
    "QUICKBOOKS_ACCESS_TOKEN",
    "QUICKBOOKS_REALM_ID",
)

_SAFE_QUERY_RE = re.compile(r"[^\w\s@.\-+]")
MAX_QUERY_LENGTH = 500

_QB_API_BASE = "https://quickbooks.api.intuit.com"


def _sanitize_query(query: str) -> str:
    """Sanitize query to prevent injection."""
    query = query[:MAX_QUERY_LENGTH]
    return _SAFE_QUERY_RE.sub("", query)


class QuickBooksConnector(BaseConnector):
    """QuickBooks connector for accounting, invoices, and payments.

    .. deprecated::
        This class is superseded by
        ``aragora.connectors.accounting.qbo.QuickBooksConnector``.
        Use ``from aragora.connectors.accounting import QuickBooksConnector``
        to get the canonical (qbo) implementation.
    """

    def __init__(self) -> None:
        super().__init__()
        self._configured = all(os.environ.get(v) for v in CONFIG_ENV_VARS)
        warnings.warn(
            "aragora.connectors.accounting.quickbooks.QuickBooksConnector is "
            "deprecated. Use aragora.connectors.accounting.qbo.QuickBooksConnector "
            "instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        logger.warning(
            "Using deprecated quickbooks.QuickBooksConnector. "
            "Migrate to aragora.connectors.accounting.qbo.QuickBooksConnector."
        )

    @property
    def name(self) -> str:
        return "quickbooks"

    @property
    def source_type(self) -> SourceType:
        return SourceType.EXTERNAL_API

    @property
    def is_configured(self) -> bool:
        return self._configured

    def _get_headers(self) -> dict[str, str]:
        token = os.environ.get("QUICKBOOKS_ACCESS_TOKEN", "")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def _get_realm_id(self) -> str:
        return os.environ.get("QUICKBOOKS_REALM_ID", "")

    async def search(self, query: str, limit: int = 10, **kwargs: Any) -> list[Evidence]:
        """Search QuickBooks for invoices and payments.

        Args:
            query: Search term (matched against DocNumber for invoices,
                   or PaymentRefNum for payments).
            limit: Maximum number of results to return.
            **kwargs: Optional ``search_type`` ("invoices", "payments", or
                      "all"). Defaults to "all".

        Returns:
            List of Evidence objects from matching QuickBooks records.
        """
        if not self._configured:
            logger.debug("QuickBooks connector not configured")
            return []

        sanitized = _sanitize_query(query)
        if not sanitized.strip():
            return []

        search_type = kwargs.get("search_type", "all")
        realm_id = self._get_realm_id()
        results: list[Evidence] = []

        # --- Invoices ---
        if search_type in ("all", "invoices"):
            inv_limit = limit if search_type == "invoices" else max(1, limit // 2)
            inv_sql = (
                # dynamic clause from internal state
                f"SELECT * FROM Invoice WHERE DocNumber LIKE '%{sanitized}%' MAXRESULTS {inv_limit}"
            )

            async def _invoice_request() -> Any:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(
                        f"{_QB_API_BASE}/v3/company/{realm_id}/query",
                        headers=self._get_headers(),
                        params={"query": inv_sql},
                    )
                    resp.raise_for_status()
                    return resp.json()

            try:
                inv_data = await self._request_with_retry(_invoice_request, "search_invoices")
                query_response = inv_data.get("QueryResponse", {})
                for inv in query_response.get("Invoice", [])[:inv_limit]:
                    inv_id = inv.get("Id", "")
                    doc_num = inv.get("DocNumber", "")
                    total = inv.get("TotalAmt", 0)
                    customer = inv.get("CustomerRef", {}).get("name", "Unknown")
                    due_date = inv.get("DueDate", "")
                    balance = inv.get("Balance", 0)
                    results.append(
                        Evidence(
                            id=f"qb_inv_{inv_id}",
                            source_type=self.source_type,
                            source_id=f"quickbooks://invoices/{inv_id}",
                            content=(
                                f"Invoice #{doc_num}: ${total} from {customer}"
                                f" (balance: ${balance}, due: {due_date})"
                            ),
                            title=f"Invoice #{doc_num}",
                            url=f"{_QB_API_BASE}/v3/company/{realm_id}/invoice/{inv_id}",
                            confidence=0.7,
                            freshness=1.0,
                            authority=0.6,
                            metadata={
                                "type": "invoice",
                                "invoice_id": inv_id,
                                "doc_number": doc_num,
                                "amount": total,
                                "balance": balance,
                                "customer": customer,
                                "due_date": due_date,
                            },
                        )
                    )
            except (ConnectorError, httpx.HTTPError, OSError, ValueError):
                logger.warning("QuickBooks invoice search failed", exc_info=True)

        # --- Payments ---
        if search_type in ("all", "payments"):
            pmt_limit = limit if search_type == "payments" else max(1, limit // 2)
            pmt_sql = (
                # internal query construction
                f"SELECT * FROM Payment WHERE PaymentRefNum LIKE '%{sanitized}%' "
                f"MAXRESULTS {pmt_limit}"
            )

            async def _payment_request() -> Any:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(
                        f"{_QB_API_BASE}/v3/company/{realm_id}/query",
                        headers=self._get_headers(),
                        params={"query": pmt_sql},
                    )
                    resp.raise_for_status()
                    return resp.json()

            try:
                pmt_data = await self._request_with_retry(_payment_request, "search_payments")
                query_response = pmt_data.get("QueryResponse", {})
                for pmt in query_response.get("Payment", [])[:pmt_limit]:
                    pmt_id = pmt.get("Id", "")
                    ref_num = pmt.get("PaymentRefNum", "")
                    total = pmt.get("TotalAmt", 0)
                    customer = pmt.get("CustomerRef", {}).get("name", "Unknown")
                    txn_date = pmt.get("TxnDate", "")
                    results.append(
                        Evidence(
                            id=f"qb_pmt_{pmt_id}",
                            source_type=self.source_type,
                            source_id=f"quickbooks://payments/{pmt_id}",
                            content=(
                                f"Payment #{ref_num}: ${total} from {customer} (date: {txn_date})"
                            ),
                            title=f"Payment #{ref_num}",
                            url=f"{_QB_API_BASE}/v3/company/{realm_id}/payment/{pmt_id}",
                            confidence=0.7,
                            freshness=1.0,
                            authority=0.6,
                            metadata={
                                "type": "payment",
                                "payment_id": pmt_id,
                                "ref_number": ref_num,
                                "amount": total,
                                "customer": customer,
                                "txn_date": txn_date,
                            },
                        )
                    )
            except (ConnectorError, httpx.HTTPError, OSError, ValueError):
                logger.warning("QuickBooks payment search failed", exc_info=True)

        return results[:limit]

    async def fetch(self, evidence_id: str, **kwargs: Any) -> Evidence | None:
        """Fetch a specific invoice or payment from QuickBooks.

        The ``evidence_id`` should be in one of the following formats:
        - ``qb_inv_<id>`` -- fetches an invoice
        - ``qb_pmt_<id>`` -- fetches a payment
        - A plain numeric ID is treated as an invoice for backward compat.
        """
        if not self._configured:
            return None

        cached = self._cache_get(evidence_id)
        if cached is not None:
            return cached

        realm_id = self._get_realm_id()

        # Determine resource type from evidence_id prefix
        if evidence_id.startswith("qb_pmt_"):
            resource_type = "payment"
            resource_id = evidence_id[len("qb_pmt_") :]
        elif evidence_id.startswith("qb_inv_"):
            resource_type = "invoice"
            resource_id = evidence_id[len("qb_inv_") :]
        else:
            # Backward compat: bare ID assumed to be invoice
            resource_type = "invoice"
            resource_id = evidence_id

        endpoint = f"{_QB_API_BASE}/v3/company/{realm_id}/{resource_type}/{resource_id}"

        async def _do_request() -> Any:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(endpoint, headers=self._get_headers())
                resp.raise_for_status()
                return resp.json()

        try:
            data = await self._request_with_retry(_do_request, "fetch")
        except (ConnectorError, httpx.HTTPError, OSError, ValueError):
            logger.warning("QuickBooks fetch failed for %s", evidence_id, exc_info=True)
            return None

        if resource_type == "payment":
            pmt = data.get("Payment", {})
            pmt_id = pmt.get("Id", resource_id)
            ref_num = pmt.get("PaymentRefNum", "")
            total = pmt.get("TotalAmt", 0)
            customer = pmt.get("CustomerRef", {}).get("name", "Unknown")
            txn_date = pmt.get("TxnDate", "")
            evidence = Evidence(
                id=f"qb_pmt_{pmt_id}",
                source_type=self.source_type,
                source_id=f"quickbooks://payments/{pmt_id}",
                content=f"Payment #{ref_num}: ${total} from {customer} (date: {txn_date})",
                title=f"Payment #{ref_num}",
                url=f"{_QB_API_BASE}/v3/company/{realm_id}/payment/{pmt_id}",
                confidence=0.7,
                freshness=1.0,
                authority=0.6,
                metadata={
                    "type": "payment",
                    "payment_id": pmt_id,
                    "ref_number": ref_num,
                    "amount": total,
                    "customer": customer,
                    "txn_date": txn_date,
                },
            )
        else:
            inv = data.get("Invoice", {})
            inv_id = inv.get("Id", resource_id)
            doc_num = inv.get("DocNumber", "")
            total = inv.get("TotalAmt", 0)
            balance = inv.get("Balance", 0)
            customer = inv.get("CustomerRef", {}).get("name", "Unknown")
            due_date = inv.get("DueDate", "")
            evidence = Evidence(
                id=f"qb_inv_{inv_id}",
                source_type=self.source_type,
                source_id=f"quickbooks://invoices/{inv_id}",
                content=(
                    f"Invoice #{doc_num}: ${total} from {customer}"
                    f" (balance: ${balance}, due: {due_date})"
                ),
                title=f"Invoice #{doc_num}",
                url=f"{_QB_API_BASE}/v3/company/{realm_id}/invoice/{inv_id}",
                confidence=0.7,
                freshness=1.0,
                authority=0.6,
                metadata={
                    "type": "invoice",
                    "invoice_id": inv_id,
                    "doc_number": doc_num,
                    "amount": total,
                    "balance": balance,
                    "customer": customer,
                    "due_date": due_date,
                },
            )

        self._cache_put(evidence.id, evidence)
        return evidence
