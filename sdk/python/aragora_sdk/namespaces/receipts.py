"""
Receipts Namespace API

Provides methods for decision receipt management:
- List and retrieve receipts
- Verify receipt integrity
- Export in various formats
- Share receipts
"""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient

_List = list  # Preserve builtin list for type annotations

ExportFormat = Literal["json", "html", "markdown", "pdf", "sarif", "csv"]


class ReceiptsAPI:
    """
    Synchronous Receipts API.

    Example:
        >>> client = AragoraClient(base_url="https://api.aragora.ai")
        >>> receipts = client.receipts.list_gauntlet(verdict="PASS")
        >>> for receipt in receipts["results"]:
        ...     print(receipt["receipt_id"], receipt["confidence"])
    """

    def __init__(self, client: AragoraClient):
        self._client = client

    # =========================================================================
    # General Receipts (v2)
    # =========================================================================

    def list(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List decision receipts.

        Args:
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            List of receipts with pagination info.
        """
        return self._client.request(
            "GET",
            "/api/v2/receipts",
            params={"limit": limit, "offset": offset},
        )

    def get(self, receipt_id: str) -> dict[str, Any]:
        """
        Get a decision receipt by ID.

        Args:
            receipt_id: Receipt identifier.

        Returns:
            Receipt details.
        """
        return self._client.request("GET", f"/api/v2/receipts/{receipt_id}")

    def export(
        self,
        receipt_id: str,
        format: ExportFormat = "json",
    ) -> dict[str, Any]:
        """
        Export a decision receipt.

        Args:
            receipt_id: Receipt identifier.
            format: Export format (json, html, markdown, pdf, sarif, csv).

        Returns:
            Exported receipt data.
        """
        format_value = "md" if format == "markdown" else format
        return self._client.request(
            "GET",
            f"/api/v2/receipts/{receipt_id}/export",
            params={"format": format_value},
        )

    def export_odr(
        self,
        receipt_id: str,
        odr_version: str | None = None,
    ) -> dict[str, Any]:
        """
        Export a decision receipt as an Open Decision Receipt (ODR) document.

        Public endpoint (no auth required). The document is signed when the
        deployment configures a signing key, and carries ``signatures: []``
        otherwise.

        Args:
            receipt_id: Receipt identifier.
            odr_version: Requested ODR profile version ("0.1" or "0.2").
                Omitted means the deployment's default.

        Returns:
            The ODR document as JSON.
        """
        params: dict[str, Any] = {"format": "odr"}
        if odr_version:
            params["odr_version"] = odr_version
        return self._client.request(
            "GET",
            f"/api/v2/receipts/{receipt_id}/export",
            params=params,
        )

    def verify_document(self, document: dict[str, Any]) -> dict[str, Any]:
        """
        Verify an ODR document statelessly against the deployment's key.

        Public endpoint (no auth required). The document is not persisted.

        On a deployment that serves no signing key ``verified`` is always false
        and ``key_id`` is null, with the signature entry in ``checks`` reported
        as ``skip`` or ``warn`` rather than ``fail``. A false verdict alone is
        not evidence of tampering: read ``checks``.

        Args:
            document: An ODR document carrying ``odr_version``.

        Returns:
            Dict with ``verified``, ``checks``, ``warnings``, ``dissent_trail``
            and ``key_id``.
        """
        return self._client.request(
            "POST",
            "/api/v2/receipts/verify",
            json=document,
        )

    def formatted(
        self,
        receipt_id: str,
        channel_type: str,
        *,
        compact: bool = False,
    ) -> dict[str, Any]:
        """
        Get a receipt formatted for a specific channel (Slack, Teams, Email, etc.).

        Args:
            receipt_id: Receipt identifier.
            channel_type: Target channel type (slack, teams, email, discord, etc.).
            compact: If True, return a compact version.

        Returns:
            Formatted receipt for the specified channel.
        """
        params: dict[str, Any] = {}
        if compact:
            params["compact"] = "true"
        return self._client.request(
            "GET",
            f"/api/v2/receipts/{receipt_id}/formatted/{channel_type}",
            params=params,
        )

    def send_to_channel(
        self,
        receipt_id: str,
        channel_type: str,
        channel_id: str,
        *,
        workspace_id: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Send a decision receipt to a channel (Slack, Teams, Email, etc.).

        Args:
            receipt_id: Receipt identifier.
            channel_type: Target channel type.
            channel_id: Target channel/conversation/email ID.
            workspace_id: Workspace ID (for Slack/Teams).
            options: Additional delivery options.

        Returns:
            Delivery confirmation with status.
        """
        payload: dict[str, Any] = {
            "channel_type": channel_type,
            "channel_id": channel_id,
        }
        if workspace_id:
            payload["workspace_id"] = workspace_id
        if options:
            payload["options"] = options
        return self._client.request(
            "POST",
            f"/api/v2/receipts/{receipt_id}/send-to-channel",
            json=payload,
        )

    def deliver_v1(
        self,
        receipt_id: str,
        *,
        channel_type: str | None = None,
        channel_id: str | None = None,
        channel: str | None = None,
        destination: str | None = None,
        workspace_id: str | None = None,
        message: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Deliver a receipt via the legacy v1 bridge endpoint.

        Accepts both modern (`channel_type`/`channel_id`) and legacy
        (`channel`/`destination`) field names.
        """
        payload: dict[str, Any] = {}
        if channel_type:
            payload["channel_type"] = channel_type
        if channel_id:
            payload["channel_id"] = channel_id
        if channel:
            payload["channel"] = channel
        if destination:
            payload["destination"] = destination
        if workspace_id:
            payload["workspace_id"] = workspace_id
        if message:
            payload["message"] = message
        if options:
            payload["options"] = options
        return self._client.request(
            "POST",
            f"/api/v1/receipts/{receipt_id}/deliver",
            json=payload,
        )

    def list_deliveries(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        receipt_id: str | None = None,
        channel_type: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """
        List recent receipt delivery attempts.

        Args:
            limit: Maximum deliveries to return.
            offset: Pagination offset.
            receipt_id: Optional receipt ID filter.
            channel_type: Optional delivery channel filter.
            status: Optional delivery status filter.

        Returns:
            Delivery history with pagination metadata.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if receipt_id:
            params["receipt_id"] = receipt_id
        if channel_type:
            params["channel_type"] = channel_type
        if status:
            params["status"] = status
        return self._client.request("GET", "/api/v1/receipts/deliveries", params=params)

    def list_recent_anchors(self, *, limit: int = 10) -> dict[str, Any]:
        """
        List recently anchored receipt hashes.

        Args:
            limit: Maximum anchors to return.

        Returns:
            Recent anchor records with receipt metadata.
        """
        return self._client.request(
            "GET",
            "/api/v1/receipts/recent-anchors",
            params={"limit": limit},
        )

    def get_anchor_status(self, receipt_id: str) -> dict[str, Any]:
        """
        Get blockchain anchor status for a receipt.

        Args:
            receipt_id: Receipt identifier.

        Returns:
            Anchor verification status.
        """
        encoded_receipt_id = quote(receipt_id, safe="")
        return self._client.request(
            "GET",
            f"/api/v1/receipts/{encoded_receipt_id}/anchor-status",
        )

    def share(self, receipt_id: str, **kwargs: Any) -> dict[str, Any]:
        """
        Share a receipt (generate shareable link or send to recipients).

        Args:
            receipt_id: Receipt identifier.
            **kwargs: Share options (recipients, expiry, permissions, etc.).

        Returns:
            Share result with link or delivery status.
        """
        return self._client.request(
            "POST",
            f"/api/v2/receipts/{receipt_id}/share",
            json=kwargs,
        )

    def verify(self, receipt_id: str) -> dict[str, Any]:
        """
        Verify a decision receipt's integrity (hash validation).

        Args:
            receipt_id: Receipt identifier.

        Returns:
            Verification result with valid status and hash.
        """
        return self._client.request(
            "POST",
            f"/api/v2/receipts/{receipt_id}/verify",
        )

    def verify_signature(self, receipt_id: str) -> dict[str, Any]:
        """
        Verify a receipt's cryptographic signature.

        Args:
            receipt_id: Receipt identifier.

        Returns:
            Signature verification result.
        """
        return self._client.request(
            "POST",
            f"/api/v2/receipts/{receipt_id}/verify-signature",
        )

    # =========================================================================
    # Gauntlet Receipts (v1 API)
    # =========================================================================

    def list_v1(
        self,
        *,
        debate_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        consensus_reached: bool | None = None,
        min_confidence: float | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List decision receipts via the v1 gauntlet API with advanced filtering.

        Args:
            debate_id: Filter by debate ID.
            from_date: Filter by start date (ISO format).
            to_date: Filter by end date (ISO format).
            consensus_reached: Filter by consensus status.
            min_confidence: Minimum confidence threshold.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            List of receipts with pagination info.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if debate_id:
            params["debate_id"] = debate_id
        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date
        if consensus_reached is not None:
            params["consensus_reached"] = str(consensus_reached).lower()
        if min_confidence is not None:
            params["min_confidence"] = str(min_confidence)
        return self._client.request("GET", "/api/v1/gauntlet/receipts", params=params)

    def get_v1(self, receipt_id: str) -> dict[str, Any]:
        """
        Get a decision receipt via the v1 gauntlet API.

        Args:
            receipt_id: Receipt identifier.

        Returns:
            Receipt details.
        """
        return self._client.request("GET", f"/api/v1/gauntlet/receipts/{receipt_id}")

    def export_v1(
        self,
        receipt_id: str,
        *,
        format: str = "json",
        include_metadata: bool = True,
        include_evidence: bool = False,
        include_dissent: bool = True,
        pretty_print: bool = False,
    ) -> dict[str, Any]:
        """
        Export a receipt via the v1 gauntlet API with detailed options.

        Args:
            receipt_id: Receipt identifier.
            format: Export format (json, html, markdown, sarif).
            include_metadata: Include decision metadata.
            include_evidence: Include supporting evidence.
            include_dissent: Include dissenting views.
            pretty_print: Format output for readability.

        Returns:
            Exported receipt data.
        """
        params: dict[str, Any] = {
            "format": format,
            "include_metadata": str(include_metadata).lower(),
            "include_evidence": str(include_evidence).lower(),
            "include_dissent": str(include_dissent).lower(),
            "pretty_print": str(pretty_print).lower(),
        }
        return self._client.request(
            "GET",
            f"/api/v1/gauntlet/receipts/{receipt_id}/export",
            params=params,
        )

    def export_bundle(
        self,
        receipt_ids: _List[str],
        *,
        format: str = "json",
        include_metadata: bool = True,
        include_evidence: bool = False,
        include_dissent: bool = True,
    ) -> dict[str, Any]:
        """
        Export multiple receipts as a bundle.

        Args:
            receipt_ids: List of receipt IDs to include.
            format: Export format.
            include_metadata: Include decision metadata.
            include_evidence: Include supporting evidence.
            include_dissent: Include dissenting views.

        Returns:
            Bundle export with all requested receipts.
        """
        payload: dict[str, Any] = {
            "receipt_ids": receipt_ids,
            "format": format,
            "include_metadata": include_metadata,
            "include_evidence": include_evidence,
            "include_dissent": include_dissent,
        }
        return self._client.request(
            "POST",
            "/api/v1/gauntlet/receipts/export/bundle",
            json=payload,
        )

    def stream(self, receipt_id: str) -> dict[str, Any]:
        """
        Stream receipt export data (for large receipts).

        Args:
            receipt_id: Receipt identifier.

        Returns:
            Streamed receipt data.
        """
        return self._client.request(
            "GET",
            f"/api/v1/gauntlet/receipts/{receipt_id}/stream",
        )

    # =========================================================================
    # Gauntlet Receipts / Results
    # =========================================================================

    def list_gauntlet(
        self,
        verdict: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List recent gauntlet results (from attack/defend stress tests).

        Args:
            verdict: Filter by verdict
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of gauntlet results
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if verdict:
            params["verdict"] = verdict
        return self._client.request("GET", "/api/v1/gauntlet/results", params=params)

    def get_gauntlet(self, receipt_id: str) -> dict[str, Any]:
        """
        Get a gauntlet receipt by gauntlet ID.

        Args:
            receipt_id: Receipt ID

        Returns:
            Gauntlet receipt details
        """
        return self._client.request("GET", f"/api/v1/gauntlet/{receipt_id}/receipt")

    def verify_gauntlet(self, receipt_id: str) -> dict[str, Any]:
        """
        Verify a gauntlet receipt's integrity.

        Args:
            receipt_id: Receipt ID

        Returns:
            Verification result
        """
        return self._client.request(
            "POST",
            f"/api/v1/gauntlet/{receipt_id}/receipt/verify",
        )

    def export_gauntlet(
        self,
        receipt_id: str,
        format: Literal["json", "html", "markdown", "sarif"] = "json",
    ) -> dict[str, Any]:
        """
        Export a gauntlet receipt.

        Args:
            receipt_id: Receipt ID
            format: Export format (json, html, markdown, sarif)

        Returns:
            Exported receipt data
        """
        format_value = "md" if format == "markdown" else format
        return self._client.request(
            "GET",
            f"/api/v1/gauntlet/{receipt_id}/receipt",
            params={"format": format_value},
        )

    # =========================================================================
    # Receipt Search & Stats
    # =========================================================================

    def search(
        self,
        query: str | None = None,
        limit: int = 20,
        offset: int = 0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Search receipts.

        Args:
            query: Search query string.
            limit: Maximum results.
            offset: Pagination offset.
            **kwargs: Additional filters (date_from, date_to, verdict, etc.)

        Returns:
            Dict with matching receipts and pagination info.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset, **kwargs}
        if query:
            params["query"] = query
        return self._client.request("GET", "/api/v2/receipts/search", params=params)

    def get_stats(self) -> dict[str, Any]:
        """
        Get receipt statistics (totals, verdicts, trends).

        Returns:
            Dict with receipt stats and breakdowns.
        """
        return self._client.request("GET", "/api/v2/receipts/stats")

    def get_signing_key(self) -> dict[str, Any]:
        """
        Get the deployment's ODR signing public key (trust anchor).

        Public endpoint (no auth required). Also served as raw PEM at
        ``/.well-known/aragora-odr-signing-key``.

        Returns:
            Dict with ``algorithm``, ``key_id``, and ``public_key_pem``.
        """
        return self._client.request("GET", "/api/v2/receipts/signing-key")

    def get_signing_key_pem(self) -> str:
        """Get the ODR signing public key from the well-known PEM endpoint."""
        return self._client.request(
            "GET",
            "/.well-known/aragora-odr-signing-key",
            headers={"Accept": "application/x-pem-file"},
            response_format="text",
        )

    # =========================================================================
    # Helper Methods
    # =========================================================================

    @staticmethod
    def has_dissent(receipt: dict[str, Any]) -> bool:
        """
        Check if a receipt has any dissenting views.

        Args:
            receipt: Receipt data

        Returns:
            True if there are dissenting agents
        """
        dissenting = receipt.get("dissenting_agents", [])
        return len(dissenting) > 0

    @staticmethod
    def get_consensus_status(receipt: dict[str, Any]) -> dict[str, Any]:
        """
        Get the consensus status from a receipt.

        Args:
            receipt: Receipt data

        Returns:
            Consensus status with reached, confidence, and agent counts
        """
        return {
            "reached": receipt.get("consensus_reached", False),
            "confidence": receipt.get("confidence", 0.0),
            "participating_agents": len(receipt.get("participating_agents", [])),
            "dissenting_agents": len(receipt.get("dissenting_agents", [])),
        }


class AsyncReceiptsAPI:
    """
    Asynchronous Receipts API.

    Example:
        >>> async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
        ...     results = await client.receipts.list_gauntlet(verdict="PASS")
    """

    def __init__(self, client: AragoraAsyncClient):
        self._client = client

    # =========================================================================
    # General Receipts (v2)
    # =========================================================================

    async def list(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List decision receipts."""
        return await self._client.request(
            "GET",
            "/api/v2/receipts",
            params={"limit": limit, "offset": offset},
        )

    async def get(self, receipt_id: str) -> dict[str, Any]:
        """Get a decision receipt by ID."""
        return await self._client.request("GET", f"/api/v2/receipts/{receipt_id}")

    async def export(
        self,
        receipt_id: str,
        format: ExportFormat = "json",
    ) -> dict[str, Any]:
        """Export a decision receipt."""
        format_value = "md" if format == "markdown" else format
        return await self._client.request(
            "GET",
            f"/api/v2/receipts/{receipt_id}/export",
            params={"format": format_value},
        )

    async def export_odr(
        self,
        receipt_id: str,
        odr_version: str | None = None,
    ) -> dict[str, Any]:
        """
        Export a decision receipt as an Open Decision Receipt (ODR) document.

        Public endpoint (no auth required). The document is signed when the
        deployment configures a signing key, and carries ``signatures: []``
        otherwise.

        Args:
            receipt_id: Receipt identifier.
            odr_version: Requested ODR profile version ("0.1" or "0.2").
                Omitted means the deployment's default.

        Returns:
            The ODR document as JSON.
        """
        params: dict[str, Any] = {"format": "odr"}
        if odr_version:
            params["odr_version"] = odr_version
        return await self._client.request(
            "GET",
            f"/api/v2/receipts/{receipt_id}/export",
            params=params,
        )

    async def verify_document(self, document: dict[str, Any]) -> dict[str, Any]:
        """
        Verify an ODR document statelessly against the deployment's key.

        Public endpoint (no auth required). The document is not persisted.

        On a deployment that serves no signing key ``verified`` is always false
        and ``key_id`` is null, with the signature entry in ``checks`` reported
        as ``skip`` or ``warn`` rather than ``fail``. A false verdict alone is
        not evidence of tampering: read ``checks``.

        Args:
            document: An ODR document carrying ``odr_version``.

        Returns:
            Dict with ``verified``, ``checks``, ``warnings``, ``dissent_trail``
            and ``key_id``.
        """
        return await self._client.request(
            "POST",
            "/api/v2/receipts/verify",
            json=document,
        )

    async def formatted(
        self,
        receipt_id: str,
        channel_type: str,
        *,
        compact: bool = False,
    ) -> dict[str, Any]:
        """Get a receipt formatted for a specific channel."""
        params: dict[str, Any] = {}
        if compact:
            params["compact"] = "true"
        return await self._client.request(
            "GET",
            f"/api/v2/receipts/{receipt_id}/formatted/{channel_type}",
            params=params,
        )

    async def send_to_channel(
        self,
        receipt_id: str,
        channel_type: str,
        channel_id: str,
        *,
        workspace_id: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a decision receipt to a channel."""
        payload: dict[str, Any] = {
            "channel_type": channel_type,
            "channel_id": channel_id,
        }
        if workspace_id:
            payload["workspace_id"] = workspace_id
        if options:
            payload["options"] = options
        return await self._client.request(
            "POST",
            f"/api/v2/receipts/{receipt_id}/send-to-channel",
            json=payload,
        )

    async def deliver_v1(
        self,
        receipt_id: str,
        *,
        channel_type: str | None = None,
        channel_id: str | None = None,
        channel: str | None = None,
        destination: str | None = None,
        workspace_id: str | None = None,
        message: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Deliver a receipt via the legacy v1 bridge endpoint."""
        payload: dict[str, Any] = {}
        if channel_type:
            payload["channel_type"] = channel_type
        if channel_id:
            payload["channel_id"] = channel_id
        if channel:
            payload["channel"] = channel
        if destination:
            payload["destination"] = destination
        if workspace_id:
            payload["workspace_id"] = workspace_id
        if message:
            payload["message"] = message
        if options:
            payload["options"] = options
        return await self._client.request(
            "POST",
            f"/api/v1/receipts/{receipt_id}/deliver",
            json=payload,
        )

    async def list_deliveries(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        receipt_id: str | None = None,
        channel_type: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """List recent receipt delivery attempts."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if receipt_id:
            params["receipt_id"] = receipt_id
        if channel_type:
            params["channel_type"] = channel_type
        if status:
            params["status"] = status
        return await self._client.request("GET", "/api/v1/receipts/deliveries", params=params)

    async def list_recent_anchors(self, *, limit: int = 10) -> dict[str, Any]:
        """List recently anchored receipt hashes."""
        return await self._client.request(
            "GET",
            "/api/v1/receipts/recent-anchors",
            params={"limit": limit},
        )

    async def get_anchor_status(self, receipt_id: str) -> dict[str, Any]:
        """Get blockchain anchor status for a receipt."""
        encoded_receipt_id = quote(receipt_id, safe="")
        return await self._client.request(
            "GET",
            f"/api/v1/receipts/{encoded_receipt_id}/anchor-status",
        )

    async def share(self, receipt_id: str, **kwargs: Any) -> dict[str, Any]:
        """Share a receipt."""
        return await self._client.request(
            "POST",
            f"/api/v2/receipts/{receipt_id}/share",
            json=kwargs,
        )

    async def verify(self, receipt_id: str) -> dict[str, Any]:
        """Verify a decision receipt's integrity."""
        return await self._client.request(
            "POST",
            f"/api/v2/receipts/{receipt_id}/verify",
        )

    async def verify_signature(self, receipt_id: str) -> dict[str, Any]:
        """Verify a receipt's cryptographic signature."""
        return await self._client.request(
            "POST",
            f"/api/v2/receipts/{receipt_id}/verify-signature",
        )

    # =========================================================================
    # Gauntlet Receipts (v1 API)
    # =========================================================================

    async def list_v1(
        self,
        *,
        debate_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        consensus_reached: bool | None = None,
        min_confidence: float | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List decision receipts via the v1 gauntlet API with advanced filtering."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if debate_id:
            params["debate_id"] = debate_id
        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date
        if consensus_reached is not None:
            params["consensus_reached"] = str(consensus_reached).lower()
        if min_confidence is not None:
            params["min_confidence"] = str(min_confidence)
        return await self._client.request("GET", "/api/v1/gauntlet/receipts", params=params)

    async def get_v1(self, receipt_id: str) -> dict[str, Any]:
        """Get a decision receipt via the v1 gauntlet API."""
        return await self._client.request("GET", f"/api/v1/gauntlet/receipts/{receipt_id}")

    async def export_v1(
        self,
        receipt_id: str,
        *,
        format: str = "json",
        include_metadata: bool = True,
        include_evidence: bool = False,
        include_dissent: bool = True,
        pretty_print: bool = False,
    ) -> dict[str, Any]:
        """Export a receipt via the v1 gauntlet API with detailed options."""
        params: dict[str, Any] = {
            "format": format,
            "include_metadata": str(include_metadata).lower(),
            "include_evidence": str(include_evidence).lower(),
            "include_dissent": str(include_dissent).lower(),
            "pretty_print": str(pretty_print).lower(),
        }
        return await self._client.request(
            "GET",
            f"/api/v1/gauntlet/receipts/{receipt_id}/export",
            params=params,
        )

    async def export_bundle(
        self,
        receipt_ids: builtins.list[str],
        *,
        format: str = "json",
        include_metadata: bool = True,
        include_evidence: bool = False,
        include_dissent: bool = True,
    ) -> dict[str, Any]:
        """Export multiple receipts as a bundle."""
        payload: dict[str, Any] = {
            "receipt_ids": receipt_ids,
            "format": format,
            "include_metadata": include_metadata,
            "include_evidence": include_evidence,
            "include_dissent": include_dissent,
        }
        return await self._client.request(
            "POST",
            "/api/v1/gauntlet/receipts/export/bundle",
            json=payload,
        )

    async def stream(self, receipt_id: str) -> dict[str, Any]:
        """Stream receipt export data (for large receipts)."""
        return await self._client.request(
            "GET",
            f"/api/v1/gauntlet/receipts/{receipt_id}/stream",
        )

    # =========================================================================
    # Gauntlet Receipts / Results
    # =========================================================================

    async def list_gauntlet(
        self,
        verdict: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List recent gauntlet results (from attack/defend stress tests)."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if verdict:
            params["verdict"] = verdict
        return await self._client.request("GET", "/api/v1/gauntlet/results", params=params)

    async def get_gauntlet(self, receipt_id: str) -> dict[str, Any]:
        """Get a gauntlet receipt by gauntlet ID."""
        return await self._client.request(
            "GET",
            f"/api/v1/gauntlet/{receipt_id}/receipt",
        )

    async def verify_gauntlet(self, receipt_id: str) -> dict[str, Any]:
        """Verify a gauntlet receipt's integrity."""
        return await self._client.request(
            "POST",
            f"/api/v1/gauntlet/{receipt_id}/receipt/verify",
        )

    # Receipt Search & Stats
    async def search(
        self,
        query: str | None = None,
        limit: int = 20,
        offset: int = 0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Search receipts."""
        params: dict[str, Any] = {"limit": limit, "offset": offset, **kwargs}
        if query:
            params["query"] = query
        return await self._client.request("GET", "/api/v2/receipts/search", params=params)

    async def get_stats(self) -> dict[str, Any]:
        """Get receipt statistics."""
        return await self._client.request("GET", "/api/v2/receipts/stats")

    async def get_signing_key(self) -> dict[str, Any]:
        """Get the deployment's ODR signing public key (trust anchor)."""
        return await self._client.request("GET", "/api/v2/receipts/signing-key")

    async def get_signing_key_pem(self) -> str:
        """Get the ODR signing public key from the well-known PEM endpoint."""
        return await self._client.request(
            "GET",
            "/.well-known/aragora-odr-signing-key",
            headers={"Accept": "application/x-pem-file"},
            response_format="text",
        )

    async def export_gauntlet(
        self,
        receipt_id: str,
        format: Literal["json", "html", "markdown", "sarif"] = "json",
    ) -> dict[str, Any]:
        """Export a gauntlet receipt."""
        format_value = "md" if format == "markdown" else format
        return await self._client.request(
            "GET",
            f"/api/v1/gauntlet/{receipt_id}/receipt",
            params={"format": format_value},
        )
