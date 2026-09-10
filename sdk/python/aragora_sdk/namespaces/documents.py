"""
Documents namespace for document management.

Provides API access to upload, manage, and query documents
that can be used as context for debates and decisions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient

_List = list  # Preserve builtin list for type annotations

DocumentFormat = Literal["pdf", "docx", "txt", "md", "html", "csv", "json"]


class DocumentsAPI:
    """Synchronous documents API."""

    def __init__(self, client: AragoraClient) -> None:
        self._client = client

    def list(
        self,
        workspace_id: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List documents.

        Args:
            workspace_id: Filter by workspace
            tag: Filter by tag
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of documents with pagination
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if workspace_id:
            params["workspace_id"] = workspace_id
        if tag:
            params["tag"] = tag

        return self._client._request("GET", "/api/v1/documents", params=params)

    def upload(
        self,
        content: bytes,
        filename: str,
        format: DocumentFormat,
        tags: _List[str] | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Upload a document.

        Args:
            content: Document content as bytes
            filename: Original filename
            format: Document format
            tags: Optional tags
            workspace_id: Target workspace

        Returns:
            Upload result with document_id
        """
        import base64

        data: dict[str, Any] = {
            "content": base64.b64encode(content).decode("utf-8"),
            "filename": filename,
            "format": format,
        }
        if tags:
            data["tags"] = tags
        if workspace_id:
            data["workspace_id"] = workspace_id

        return self._client._request("POST", "/api/v1/documents", json=data)

    def get(self, document_id: str) -> dict[str, Any]:
        """
        Get document metadata.

        Args:
            document_id: Document identifier

        Returns:
            Document metadata
        """
        return self._client._request("GET", f"/api/v1/documents/{document_id}")

    def update(
        self,
        document_id: str,
        tags: _List[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Update document metadata.

        Args:
            document_id: Document identifier
            tags: New tags
            metadata: New metadata

        Returns:
            Updated document
        """
        data: dict[str, Any] = {}
        if tags is not None:
            data["tags"] = tags
        if metadata is not None:
            data["metadata"] = metadata

        return self._client._request("PATCH", f"/api/v1/documents/{document_id}", json=data)

    def delete(self, document_id: str) -> dict[str, Any]:
        """
        Delete a document.

        Args:
            document_id: Document identifier

        Returns:
            Deletion confirmation
        """
        return self._client._request("DELETE", f"/api/v1/documents/{document_id}")

    def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Search document contents.

        Args:
            query: Search query
            limit: Maximum results
            offset: Pagination offset

        Returns:
            Matching document chunks
        """
        params: dict[str, Any] = {"query": query, "limit": limit, "offset": offset}
        return self._client._request("GET", "/api/v1/documents/search", params=params)

    def get_chunks(
        self,
        document_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Get document chunks (for RAG).

        Args:
            document_id: Document identifier
            limit: Maximum chunks
            offset: Pagination offset

        Returns:
            Document chunks with embeddings info
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        # TODO: server route not yet implemented
        return self._client._request(
            "GET", f"/api/v1/documents/{document_id}/chunks", params=params
        )


class AsyncDocumentsAPI:
    """Asynchronous documents API."""

    def __init__(self, client: AragoraAsyncClient) -> None:
        self._client = client

    async def list(
        self,
        workspace_id: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List documents."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if workspace_id:
            params["workspace_id"] = workspace_id
        if tag:
            params["tag"] = tag

        return await self._client._request("GET", "/api/v1/documents", params=params)

    async def upload(
        self,
        content: bytes,
        filename: str,
        format: DocumentFormat,
        tags: _List[str] | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Upload a document."""
        import base64

        data: dict[str, Any] = {
            "content": base64.b64encode(content).decode("utf-8"),
            "filename": filename,
            "format": format,
        }
        if tags:
            data["tags"] = tags
        if workspace_id:
            data["workspace_id"] = workspace_id

        return await self._client._request("POST", "/api/v1/documents", json=data)

    async def get(self, document_id: str) -> dict[str, Any]:
        """Get document metadata."""
        return await self._client._request("GET", f"/api/v1/documents/{document_id}")

    async def update(
        self,
        document_id: str,
        tags: _List[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update document metadata."""
        data: dict[str, Any] = {}
        if tags is not None:
            data["tags"] = tags
        if metadata is not None:
            data["metadata"] = metadata

        return await self._client._request("PATCH", f"/api/v1/documents/{document_id}", json=data)

    async def delete(self, document_id: str) -> dict[str, Any]:
        """Delete a document."""
        return await self._client._request("DELETE", f"/api/v1/documents/{document_id}")

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search document contents."""
        params: dict[str, Any] = {"query": query, "limit": limit, "offset": offset}
        return await self._client._request("GET", "/api/v1/documents/search", params=params)

    async def get_chunks(
        self,
        document_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Get document chunks (for RAG)."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        # TODO: server route not yet implemented
        return await self._client._request(
            "GET", f"/api/v1/documents/{document_id}/chunks", params=params
        )
