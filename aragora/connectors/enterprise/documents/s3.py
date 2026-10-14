"""
S3-Compatible Storage Connector.

Supports AWS S3, MinIO, and other S3-compatible storage:
- Incremental sync using LastModified timestamps
- Document parsing (PDF, DOCX, TXT, MD)
- Prefix-based filtering
- Event notifications for real-time sync
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import timezone
from pathlib import Path
from typing import Any
from collections.abc import AsyncIterator

from aragora.connectors.enterprise.base import (
    EnterpriseConnector,
    SyncItem,
    SyncState,
)
from aragora.reasoning.provenance import SourceType

logger = logging.getLogger(__name__)

# Supported document extensions
DOCUMENT_EXTENSIONS = {
    ".txt",
    ".md",
    ".rst",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".csv",
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".xlsx",
}

# Max file size to process (50MB)
MAX_FILE_SIZE = 50 * 1024 * 1024


class S3Connector(EnterpriseConnector):
    """
    S3-compatible storage connector.

    Syncs documents from S3 buckets to the Knowledge Mound with:
    - Incremental sync using LastModified timestamps
    - Document text extraction (PDF, DOCX, etc.)
    - Prefix-based filtering for organizing content
    - Domain classification based on path structure
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,  # For MinIO, etc.
        region: str = "us-east-1",
        extensions: set[str] | None = None,
        exclude_patterns: list[str] | None = None,
        **kwargs: Any,
    ):
        connector_id = f"s3_{bucket}_{prefix.replace('/', '_')}"
        super().__init__(connector_id=connector_id, **kwargs)

        self.bucket = bucket
        self.prefix = prefix
        self.endpoint_url = endpoint_url
        self.region = region
        self.extensions = extensions or DOCUMENT_EXTENSIONS
        self.exclude_patterns = exclude_patterns or ["__MACOSX/", ".DS_Store", "thumbs.db"]

        self._client = None

    @property
    def source_type(self) -> SourceType:
        return SourceType.DOCUMENT

    @property
    def name(self) -> str:
        return f"S3 ({self.bucket}/{self.prefix})"

    async def _get_client(self) -> Any:
        """Get or create boto3 S3 client."""
        if self._client is not None:
            return self._client

        try:
            import boto3
            from botocore.config import Config

            # Get credentials
            access_key = await self.credentials.get_credential("AWS_ACCESS_KEY_ID")
            secret_key = await self.credentials.get_credential("AWS_SECRET_ACCESS_KEY")

            config = Config(
                region_name=self.region,
                retries={"max_attempts": 3, "mode": "adaptive"},
            )

            kwargs = {"config": config}
            if self.endpoint_url:
                kwargs["endpoint_url"] = self.endpoint_url
            if access_key and secret_key:
                kwargs["aws_access_key_id"] = access_key
                kwargs["aws_secret_access_key"] = secret_key

            self._client = boto3.client("s3", **kwargs)
            return self._client

        except ImportError:
            logger.error("boto3 not installed. Run: pip install boto3")
            raise

    def _should_process_file(self, key: str, size: int) -> bool:
        """Check if a file should be processed."""
        # Check exclusion patterns
        for pattern in self.exclude_patterns:
            if pattern.lower() in key.lower():
                return False

        # Check file size
        if size > MAX_FILE_SIZE:
            return False

        # Check extension
        ext = Path(key).suffix.lower()
        return ext in self.extensions

    def _infer_domain(self, key: str) -> str:
        """Infer domain from file path."""
        parts = key.lower().split("/")

        # Check for common patterns
        if any(p in parts for p in ["legal", "contracts", "agreements"]):
            return "legal/contracts"
        elif any(p in parts for p in ["hr", "policies", "employee"]):
            return "operational/hr"
        elif any(p in parts for p in ["finance", "accounting", "invoices"]):
            return "financial/accounting"
        elif any(p in parts for p in ["technical", "docs", "api", "architecture"]):
            return "technical/documentation"
        elif any(p in parts for p in ["compliance", "audit", "regulatory"]):
            return "compliance/audit"

        return "general/documents"

    async def _extract_text(self, key: str, body: bytes, content_type: str) -> str:
        """Extract text from document content."""
        ext = Path(key).suffix.lower()

        # Plain text formats
        if ext in {".txt", ".md", ".rst", ".json", ".yaml", ".yml", ".xml", ".csv"}:
            try:
                return body.decode("utf-8")
            except UnicodeDecodeError:
                return body.decode("latin-1", errors="replace")

        # PDF extraction
        if ext == ".pdf":
            return await self._extract_pdf_text(body)

        # DOCX extraction
        if ext == ".docx":
            return await self._extract_docx_text(body)

        # Fallback
        return f"[Binary document: {key}]"

    async def _extract_pdf_text(self, content: bytes) -> str:
        """Extract text from PDF content."""
        try:
            import io

            # Try pypdf first (lighter weight)
            try:
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(content))
                text_parts = []
                for page in reader.pages[:50]:  # Limit to 50 pages
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
                return "\n\n".join(text_parts)
            except ImportError as pypdf_error:
                logger.debug("pypdf unavailable for PDF extraction: %s", pypdf_error)

            # Fallback to PyPDF2
            try:
                import PyPDF2

                reader = PyPDF2.PdfReader(io.BytesIO(content))
                text_parts = []
                for page in reader.pages[:50]:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
                return "\n\n".join(text_parts)
            except ImportError as pypdf2_error:
                raise RuntimeError("PDF extraction requires pypdf or PyPDF2") from pypdf2_error

        except (OSError, ValueError) as e:
            logger.warning("PDF extraction failed: %s", e)
            return f"[PDF extraction failed: {e}]"

    async def _extract_docx_text(self, content: bytes) -> str:
        """Extract text from DOCX content."""
        try:
            import io
            from docx import Document

            doc = Document(io.BytesIO(content))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs)

        except ImportError as e:
            raise RuntimeError("DOCX extraction requires python-docx") from e
        except (OSError, ValueError, KeyError) as e:
            logger.warning("DOCX extraction failed: %s", e)
            return f"[DOCX extraction failed: {e}]"

    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        """
        Yield items to sync from S3 bucket.

        Uses LastModified timestamps for incremental sync.
        """
        client = await self._get_client()

        # Build list request
        list_kwargs = {
            "Bucket": self.bucket,
            "MaxKeys": batch_size,
        }
        if self.prefix:
            list_kwargs["Prefix"] = self.prefix

        # Use continuation token if available
        if state.cursor:
            list_kwargs["ContinuationToken"] = state.cursor

        items_processed = 0
        last_modified_cutoff = state.last_item_timestamp

        _max_pages = 1000
        try:
            for _page_guard in range(_max_pages):
                # List objects
                response = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: client.list_objects_v2(**list_kwargs)
                )

                contents = response.get("Contents", [])
                state.items_total = response.get("KeyCount", 0)

                for obj in contents:
                    key = obj["Key"]
                    size = obj["Size"]
                    last_modified = obj["LastModified"]

                    # Skip if older than last sync
                    if last_modified_cutoff and last_modified <= last_modified_cutoff:
                        continue

                    # Check if should process
                    if not self._should_process_file(key, size):
                        continue

                    try:
                        # Get object content
                        def get_object(k: str = key) -> dict[str, Any]:
                            return client.get_object(Bucket=self.bucket, Key=k)

                        obj_response = await asyncio.get_running_loop().run_in_executor(
                            None, get_object
                        )
                        body = obj_response["Body"].read()
                        content_type = obj_response.get("ContentType", "")
                        # ETag provides content hash for change detection
                        etag = obj_response.get("ETag", "").strip('"')

                        # Extract text
                        text = await self._extract_text(key, body, content_type)

                        # Infer domain
                        domain = self._infer_domain(key)

                        # Create sync item with content hash
                        yield SyncItem(
                            id=f"s3:{self.bucket}:{hashlib.sha256(key.encode()).hexdigest()[:12]}",
                            content=text[:100000],  # Limit content size
                            source_type="document",
                            source_id=f"s3://{self.bucket}/{key}",
                            title=Path(key).name,
                            url=f"s3://{self.bucket}/{key}",
                            updated_at=(
                                last_modified.replace(tzinfo=timezone.utc)
                                if last_modified.tzinfo is None
                                else last_modified
                            ),
                            domain=domain,
                            confidence=0.75,
                            content_hash=etag,  # Use S3 ETag for change detection
                            metadata={
                                "bucket": self.bucket,
                                "key": key,
                                "size": size,
                                "content_type": content_type,
                                "last_modified": last_modified.isoformat(),
                                "extension": Path(key).suffix.lower(),
                                "etag": etag,
                            },
                        )

                        items_processed += 1

                    except (OSError, ValueError, KeyError, RuntimeError) as e:
                        message = f"Failed to process {key}: {e}"
                        logger.error(message)
                        state.errors.append(message)
                        raise RuntimeError(message) from e

                # Check for more results
                if response.get("IsTruncated"):
                    list_kwargs["ContinuationToken"] = response["NextContinuationToken"]
                    state.cursor = response["NextContinuationToken"]
                else:
                    state.cursor = None
                    break
            else:
                logger.warning("Pagination limit reached (%d pages)", _max_pages)

        except (OSError, ValueError, KeyError) as e:
            message = f"S3 sync failed: {e}"
            logger.error(message)
            state.errors.append(message)
            raise RuntimeError(message) from e

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs: Any,
    ) -> list:
        """Search is not directly supported by S3. Returns empty list."""
        logger.debug("[%s] Search not supported, use Knowledge Mound", self.name)
        return []

    async def fetch(self, evidence_id: str) -> Any:
        """Fetch a specific document by S3 key.

        Not implemented: evidence IDs carry a hash of the key, which cannot be
        reversed, so this always returns None. None here does not mean the
        object does not exist.
        """
        if not evidence_id.startswith("s3:"):
            return None

        parts = evidence_id.split(":", 2)
        if len(parts) < 3:
            return None

        parts[1]
        parts[2]

        # We can't reverse the hash, so this is mainly for verification
        logger.debug("[%s] Fetch not implemented for hash-based IDs", self.name)
        return None

    async def handle_webhook(self, payload: dict[str, Any]) -> bool:
        """Handle S3 event notification."""
        records = payload.get("Records", [])

        for record in records:
            event_name = record.get("eventName", "")
            s3_info = record.get("s3", {})
            bucket = s3_info.get("bucket", {}).get("name", "")
            key = s3_info.get("object", {}).get("key", "")

            if bucket == self.bucket and "ObjectCreated" in event_name:
                logger.info("[%s] Webhook: new object %s", self.name, key)
                # Trigger sync for this specific file
                asyncio.create_task(self.sync(max_items=1))
                return True

        return False
