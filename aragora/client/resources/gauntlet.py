"""Gauntlet API resource for adversarial validation."""

from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.client.client import AragoraClient

from aragora.client.errors import AragoraAPIError
from aragora.client.models import (
    GauntletComparison,
    GauntletHeatmapExtended,
    GauntletPersona,
    GauntletReceipt,
    GauntletResult,
    GauntletRun,
    GauntletRunRequest,
    GauntletRunResponse,
)


class GauntletAPI:
    """API interface for gauntlet (adversarial validation)."""

    def __init__(self, client: AragoraClient):
        self._client = client

    def run(
        self,
        input_content: str,
        input_type: str = "text",
        persona: str = "security",
        profile: str = "default",
    ) -> GauntletRunResponse:
        """
        Start a gauntlet analysis run.

        Args:
            input_content: Content to analyze.
            input_type: Type of content (text, policy, code).
            persona: Analysis persona (security, gdpr, hipaa, etc).
            profile: Analysis depth (quick, default, thorough).

        Returns:
            GauntletRunResponse with gauntlet_id.
        """
        request = GauntletRunRequest(
            input_content=input_content,
            input_type=input_type,
            persona=persona,
            profile=profile,
        )

        response = self._client._post("/api/gauntlet/run", request.model_dump())
        return GauntletRunResponse(**response)

    async def run_async(
        self,
        input_content: str,
        input_type: str = "text",
        persona: str = "security",
        profile: str = "default",
    ) -> GauntletRunResponse:
        """Async version of run()."""
        request = GauntletRunRequest(
            input_content=input_content,
            input_type=input_type,
            persona=persona,
            profile=profile,
        )

        response = await self._client._post_async("/api/gauntlet/run", request.model_dump())
        return GauntletRunResponse(**response)

    def get_receipt(self, gauntlet_id: str) -> GauntletReceipt:
        """
        Get the decision receipt for a gauntlet run.

        Args:
            gauntlet_id: The gauntlet run ID.

        Returns:
            GauntletReceipt with verdict and findings.
        """
        response = self._client._get(f"/api/gauntlet/{gauntlet_id}/receipt")
        return GauntletReceipt(**response)

    async def get_receipt_async(self, gauntlet_id: str) -> GauntletReceipt:
        """Async version of get_receipt()."""
        response = await self._client._get_async(f"/api/gauntlet/{gauntlet_id}/receipt")
        return GauntletReceipt(**response)

    def run_and_wait(
        self,
        input_content: str,
        input_type: str = "text",
        persona: str = "security",
        profile: str = "default",
        timeout: int = 900,
    ) -> GauntletReceipt:
        """
        Run gauntlet and wait for completion.

        Args:
            input_content: Content to analyze.
            input_type: Type of content.
            persona: Analysis persona.
            profile: Analysis depth.
            timeout: Polling budget in seconds after submission. Individual
                requests retain the client's transport timeout.

        Returns:
            GauntletReceipt with full results.
        """
        response = self.run(input_content, input_type, persona, profile)
        gauntlet_id = response.gauntlet_id
        if not gauntlet_id.strip():
            raise AragoraAPIError(
                "Gauntlet submission returned an empty run ID", "INVALID_RESPONSE", 200
            )

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # Pending AND failed runs return receipt HTTP 400/GAUNTLET_406.
            # The shared transport specializes 400 as ValidationError, losing
            # that code. Poll explicit status instead of guessing from an error.
            # Read the actual server shape, not GauntletRun's legacy id/default.
            run = self._client._get(f"/api/v1/gauntlet/{gauntlet_id}")
            status = run.get("status") if isinstance(run, dict) else None
            if (
                not isinstance(run, dict)
                or run.get("gauntlet_id") != gauntlet_id
                or status not in ("pending", "running", "completed", "failed", "cancelled")
            ):
                raise AragoraAPIError(
                    f"Gauntlet {gauntlet_id} returned invalid run status", "INVALID_RESPONSE", 200
                )
            if status in ("failed", "cancelled"):
                # Do not echo potentially sensitive backend error details.
                raise AragoraAPIError(
                    f"Gauntlet {gauntlet_id} {status}",
                    "GAUNTLET_RUN_FAILED",
                    200,
                    suggestion="Inspect the existing run before submitting another analysis",
                )
            if time.monotonic() >= deadline:
                break
            if status == "completed":
                receipt = self.get_receipt(gauntlet_id)
                if (
                    receipt.gauntlet_id not in (None, gauntlet_id)
                    or not receipt.verdict
                    or not receipt.verdict.strip()
                    or (
                        receipt.status is not None and receipt.status.strip().lower() != "completed"
                    )
                ):
                    raise AragoraAPIError(
                        f"Gauntlet {gauntlet_id} returned an invalid completed receipt",
                        "INVALID_RESPONSE",
                        200,
                    )
                return receipt
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(5, remaining))

        raise TimeoutError(f"Gauntlet {gauntlet_id} did not complete within {timeout}s")

    def get(self, gauntlet_id: str) -> GauntletRun:
        """
        Get gauntlet run status.

        Args:
            gauntlet_id: The gauntlet run ID.

        Returns:
            GauntletRun with status and progress.
        """
        response = self._client._get(f"/api/v1/gauntlet/{gauntlet_id}")
        return GauntletRun(**response)

    async def get_async(self, gauntlet_id: str) -> GauntletRun:
        """Async version of get()."""
        response = await self._client._get_async(f"/api/v1/gauntlet/{gauntlet_id}")
        return GauntletRun(**response)

    def delete(self, gauntlet_id: str) -> dict[str, bool]:
        """
        Delete a gauntlet run.

        Args:
            gauntlet_id: The gauntlet run ID.

        Returns:
            Dict with 'deleted' status.
        """
        response = self._client._delete(f"/api/v1/gauntlet/{gauntlet_id}")
        return {"deleted": response.get("deleted", True)}

    async def delete_async(self, gauntlet_id: str) -> dict[str, bool]:
        """Async version of delete()."""
        response = await self._client._delete_async(f"/api/v1/gauntlet/{gauntlet_id}")
        return {"deleted": response.get("deleted", True)}

    def list_personas(
        self, category: str | None = None, enabled: bool | None = None
    ) -> list[GauntletPersona]:
        """
        List available gauntlet personas.

        Args:
            category: Optional filter by category.
            enabled: Optional filter by enabled status.

        Returns:
            List of GauntletPersona.
        """
        params: dict[str, Any] = {}
        if category:
            params["category"] = category
        if enabled is not None:
            params["enabled"] = enabled
        response = self._client._get("/api/v1/gauntlet/personas", params=params)
        personas = response.get("personas", response) if isinstance(response, dict) else response
        return [GauntletPersona(**p) for p in personas]

    async def list_personas_async(
        self, category: str | None = None, enabled: bool | None = None
    ) -> list[GauntletPersona]:
        """Async version of list_personas()."""
        params: dict[str, Any] = {}
        if category:
            params["category"] = category
        if enabled is not None:
            params["enabled"] = enabled
        response = await self._client._get_async("/api/v1/gauntlet/personas", params=params)
        personas = response.get("personas", response) if isinstance(response, dict) else response
        return [GauntletPersona(**p) for p in personas]

    def list_results(
        self,
        gauntlet_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[GauntletResult]:
        """
        List gauntlet results.

        Args:
            gauntlet_id: Optional filter by gauntlet ID.
            status: Optional filter by status.
            limit: Maximum results to return.
            offset: Results to skip.

        Returns:
            List of GauntletResult.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if gauntlet_id:
            params["gauntlet_id"] = gauntlet_id
        if status:
            params["status"] = status
        response = self._client._get("/api/v1/gauntlet/results", params=params)
        results = response.get("results", response) if isinstance(response, dict) else response
        return [GauntletResult(**r) for r in results]

    async def list_results_async(
        self,
        gauntlet_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[GauntletResult]:
        """Async version of list_results()."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if gauntlet_id:
            params["gauntlet_id"] = gauntlet_id
        if status:
            params["status"] = status
        response = await self._client._get_async("/api/v1/gauntlet/results", params=params)
        results = response.get("results", response) if isinstance(response, dict) else response
        return [GauntletResult(**r) for r in results]

    def get_heatmap(self, gauntlet_id: str, format: str = "json") -> GauntletHeatmapExtended:
        """
        Get risk heatmap for a gauntlet run.

        Args:
            gauntlet_id: The gauntlet run ID.
            format: Output format (json or svg).

        Returns:
            GauntletHeatmapExtended with risk matrix.
        """
        response = self._client._get(
            f"/api/v1/gauntlet/{gauntlet_id}/heatmap", params={"format": format}
        )
        return GauntletHeatmapExtended(**response)

    async def get_heatmap_async(
        self, gauntlet_id: str, format: str = "json"
    ) -> GauntletHeatmapExtended:
        """Async version of get_heatmap()."""
        response = await self._client._get_async(
            f"/api/v1/gauntlet/{gauntlet_id}/heatmap", params={"format": format}
        )
        return GauntletHeatmapExtended(**response)

    def compare(self, gauntlet_id_a: str, gauntlet_id_b: str) -> GauntletComparison:
        """
        Compare two gauntlet runs.

        Args:
            gauntlet_id_a: First gauntlet run ID.
            gauntlet_id_b: Second gauntlet run ID.

        Returns:
            GauntletComparison with delta analysis.
        """
        response = self._client._get(f"/api/v1/gauntlet/{gauntlet_id_a}/compare/{gauntlet_id_b}")
        return GauntletComparison(**response)

    async def compare_async(self, gauntlet_id_a: str, gauntlet_id_b: str) -> GauntletComparison:
        """Async version of compare()."""
        response = await self._client._get_async(
            f"/api/v1/gauntlet/{gauntlet_id_a}/compare/{gauntlet_id_b}"
        )
        return GauntletComparison(**response)


__all__ = ["GauntletAPI"]
