"""
Google Sheets Enterprise Connector.

Provides real-time integration with Google Sheets:
- OAuth2 authentication flow
- Full spreadsheet data extraction
- Sheet-by-sheet parsing with headers
- Named ranges and metadata
- Incremental sync via modified timestamps
- Formula evaluation (values, not formulas)

Requires Google Cloud OAuth2 credentials with Sheets API enabled.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from collections.abc import AsyncIterator

import httpx

_MAX_PAGES = 1000  # Safety cap for pagination loops

from aragora.connectors.enterprise.base import (
    EnterpriseConnector,
    SyncItem,
    SyncState,
)
from aragora.reasoning.provenance import SourceType
from aragora.observability.http_client_pool import get_http_pool

logger = logging.getLogger(__name__)


@dataclass
class SheetData:
    """Data from a single sheet within a spreadsheet."""

    title: str
    sheet_id: int
    row_count: int
    column_count: int
    headers: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    frozen_rows: int = 0
    frozen_cols: int = 0


@dataclass
class Spreadsheet:
    """A Google Sheets spreadsheet."""

    id: str
    title: str
    locale: str = "en_US"
    timezone: str = "UTC"
    created_time: datetime | None = None
    modified_time: datetime | None = None
    web_view_link: str = ""
    owner: str = ""
    sheets: list[SheetData] = field(default_factory=list)


class GoogleSheetsConnector(EnterpriseConnector):
    """
    Enterprise connector for Google Sheets.

    Features:
    - OAuth2 authentication with refresh
    - Full spreadsheet extraction with all sheets
    - Header detection and structured data parsing
    - Named range support
    - Incremental sync via Drive API modified times
    - Batch operations for efficiency

    Authentication:
    - OAuth2 with refresh token (same as Google Drive)
    - Service account (for domain-wide access)

    Usage:
        connector = GoogleSheetsConnector(
            spreadsheet_ids=["1abc...xyz"],  # Optional: specific sheets
            include_formulas=False,  # Get values, not formulas
        )
        result = await connector.sync()
    """

    # Google Sheets API base URL
    SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
    DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"

    def __init__(
        self,
        spreadsheet_ids: list[str] | None = None,
        folder_ids: list[str] | None = None,
        include_formulas: bool = False,
        include_hidden_sheets: bool = False,
        max_rows_per_sheet: int = 50000,
        max_sheets_per_file: int = 100,
        header_row: int = 1,
        **kwargs: Any,
    ):
        """
        Initialize Google Sheets connector.

        Args:
            spreadsheet_ids: Specific spreadsheet IDs to sync
            folder_ids: Drive folders to scan for spreadsheets
            include_formulas: Return formulas instead of calculated values
            include_hidden_sheets: Include hidden sheets in extraction
            max_rows_per_sheet: Maximum rows to extract per sheet
            max_sheets_per_file: Maximum sheets to process per spreadsheet
            header_row: Row number to use as headers (1-indexed)
        """
        super().__init__(connector_id="gsheets", **kwargs)

        self.spreadsheet_ids = spreadsheet_ids or []
        self.folder_ids = folder_ids or []
        self.include_formulas = include_formulas
        self.include_hidden_sheets = include_hidden_sheets
        self.max_rows_per_sheet = max_rows_per_sheet
        self.max_sheets_per_file = max_sheets_per_file
        self.header_row = header_row

        self._access_token: str | None = None
        self._token_expiry: datetime | None = None

    @property
    def source_type(self) -> SourceType:
        return SourceType.DOCUMENT

    @property
    def name(self) -> str:
        return "Google Sheets"

    async def _get_access_token(self) -> str:
        """Get valid access token, refreshing if needed."""
        now = datetime.now(timezone.utc)

        if self._access_token and self._token_expiry and now < self._token_expiry:
            return self._access_token

        # Get credentials (same as Google Drive)
        client_id = await self.credentials.get_credential("GDRIVE_CLIENT_ID")
        client_secret = await self.credentials.get_credential("GDRIVE_CLIENT_SECRET")
        refresh_token = await self.credentials.get_credential("GDRIVE_REFRESH_TOKEN")

        if not all([client_id, client_secret, refresh_token]):
            raise ValueError(
                "Google credentials not configured. "
                "Set GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, and GDRIVE_REFRESH_TOKEN"
            )

        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            data = response.json()

        self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        from datetime import timedelta

        self._token_expiry = now.replace(microsecond=0) + timedelta(seconds=expires_in - 60)

        return self._access_token

    async def _api_request(
        self,
        url: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make a request to Google API."""
        token = await self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                params=params,
                timeout=60,
                **kwargs,
            )
            response.raise_for_status()
            return response.json() if response.content else {}

    async def _list_spreadsheets_in_folder(
        self,
        folder_id: str,
        page_token: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """List spreadsheets in a Drive folder."""
        query = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"

        params: dict[str, Any] = {
            "q": query,
            "pageSize": 100,
            "fields": "nextPageToken,files(id,name,modifiedTime,owners,webViewLink)",
        }

        if page_token:
            params["pageToken"] = page_token

        data = await self._api_request(f"{self.DRIVE_API_BASE}/files", params=params)

        return data.get("files", []), data.get("nextPageToken")

    async def _get_spreadsheet_metadata(self, spreadsheet_id: str) -> dict[str, Any]:
        """Get spreadsheet metadata from Drive API."""
        params = {
            "fields": "id,name,modifiedTime,createdTime,owners,webViewLink",
        }

        return await self._api_request(
            f"{self.DRIVE_API_BASE}/files/{spreadsheet_id}",
            params=params,
        )

    async def _get_spreadsheet(self, spreadsheet_id: str) -> Spreadsheet:
        """Fetch full spreadsheet data including all sheets."""
        # Get metadata first
        metadata = await self._get_spreadsheet_metadata(spreadsheet_id)

        # Parse timestamps
        created = None
        modified = None
        if metadata.get("createdTime"):
            try:
                created = datetime.fromisoformat(metadata["createdTime"].replace("Z", "+00:00"))
            except ValueError as e:
                logger.debug("Failed to parse datetime value: %s", e)
        if metadata.get("modifiedTime"):
            try:
                modified = datetime.fromisoformat(metadata["modifiedTime"].replace("Z", "+00:00"))
            except ValueError as e:
                logger.debug("Failed to parse datetime value: %s", e)

        # Get spreadsheet structure
        params: dict[str, Any] = {
            "includeGridData": False,  # We'll fetch data separately
        }

        structure = await self._api_request(
            f"{self.SHEETS_API_BASE}/{spreadsheet_id}",
            params=params,
        )

        spreadsheet = Spreadsheet(
            id=spreadsheet_id,
            title=metadata.get("name", structure.get("properties", {}).get("title", "")),
            locale=structure.get("properties", {}).get("locale", "en_US"),
            timezone=structure.get("properties", {}).get("timeZone", "UTC"),
            created_time=created,
            modified_time=modified,
            web_view_link=metadata.get("webViewLink", ""),
            owner=(
                metadata.get("owners", [{}])[0].get("displayName", "")
                if metadata.get("owners")
                else ""
            ),
        )

        # Process each sheet
        sheets_processed = 0
        for sheet_info in structure.get("sheets", []):
            if sheets_processed >= self.max_sheets_per_file:
                break

            props = sheet_info.get("properties", {})
            sheet_id = props.get("sheetId", 0)
            sheet_title = props.get("title", f"Sheet{sheet_id}")
            hidden = props.get("hidden", False)

            if hidden and not self.include_hidden_sheets:
                continue

            grid_props = props.get("gridProperties", {})
            row_count = min(grid_props.get("rowCount", 0), self.max_rows_per_sheet)
            col_count = grid_props.get("columnCount", 0)

            if row_count == 0 or col_count == 0:
                continue

            # Fetch sheet data
            sheet_data = await self._fetch_sheet_data(
                spreadsheet_id,
                sheet_title,
                row_count,
                col_count,
            )

            if sheet_data:
                sheet_data.frozen_rows = grid_props.get("frozenRowCount", 0)
                sheet_data.frozen_cols = grid_props.get("frozenColumnCount", 0)
                spreadsheet.sheets.append(sheet_data)
                sheets_processed += 1

        return spreadsheet

    async def _fetch_sheet_data(
        self,
        spreadsheet_id: str,
        sheet_title: str,
        row_count: int,
        col_count: int,
    ) -> SheetData | None:
        """Fetch data from a specific sheet."""
        # Build range - use A1 notation
        end_col = self._col_index_to_letter(col_count)
        range_notation = f"'{sheet_title}'!A1:{end_col}{row_count}"

        params: dict[str, Any] = {
            "ranges": range_notation,
            "valueRenderOption": "FORMULA" if self.include_formulas else "FORMATTED_VALUE",
            "dateTimeRenderOption": "FORMATTED_STRING",
        }

        try:
            data = await self._api_request(
                f"{self.SHEETS_API_BASE}/{spreadsheet_id}/values:batchGet",
                params=params,
            )

            value_ranges = data.get("valueRanges", [])
            if not value_ranges:
                return None

            values = value_ranges[0].get("values", [])
            if not values:
                return None

            # Extract headers from specified row
            headers = []
            rows = []
            header_idx = self.header_row - 1  # Convert to 0-indexed

            for i, row in enumerate(values):
                if i == header_idx:
                    headers = [
                        str(cell) if cell else f"Column{j + 1}" for j, cell in enumerate(row)
                    ]
                elif i > header_idx:
                    rows.append(row)

            # If no header row found, use generic headers
            if not headers and values:
                max_cols = max(len(row) for row in values)
                headers = [f"Column{i + 1}" for i in range(max_cols)]
                rows = values

            return SheetData(
                title=sheet_title,
                sheet_id=0,  # We don't have this from values API
                row_count=len(rows),
                column_count=len(headers),
                headers=headers,
                rows=rows,
            )

        except (httpx.HTTPStatusError, httpx.RequestError, KeyError) as e:
            logger.warning("[%s] Failed to fetch sheet '%s': %s", self.name, sheet_title, e)
            return None

    def _col_index_to_letter(self, col: int) -> str:
        """Convert column index (1-based) to A1 notation letter."""
        result = ""
        while col > 0:
            col -= 1
            result = chr(65 + (col % 26)) + result
            col //= 26
        return result or "A"

    def _spreadsheet_to_text(self, spreadsheet: Spreadsheet) -> str:
        """Convert spreadsheet to text representation."""
        lines = [
            f"# {spreadsheet.title}",
            "",
        ]

        for sheet in spreadsheet.sheets:
            lines.append(f"## {sheet.title}")
            lines.append("")

            if sheet.headers:
                lines.append("| " + " | ".join(sheet.headers) + " |")
                lines.append("| " + " | ".join(["---"] * len(sheet.headers)) + " |")

            for row in sheet.rows[:1000]:  # Limit rows in text output
                # Pad row to match headers
                padded_row = row + [""] * (len(sheet.headers) - len(row))
                cell_texts = [str(cell).replace("|", "\\|")[:100] for cell in padded_row]
                lines.append("| " + " | ".join(cell_texts) + " |")

            if len(sheet.rows) > 1000:
                lines.append(f"... ({len(sheet.rows) - 1000} more rows)")

            lines.append("")

        return "\n".join(lines)

    def _spreadsheet_to_tables(self, spreadsheet: Spreadsheet) -> list[dict[str, Any]]:
        """Convert spreadsheet sheets to table structures."""
        tables = []

        for sheet in spreadsheet.sheets:
            table = {
                "name": sheet.title,
                "headers": sheet.headers,
                "rows": sheet.rows,
                "row_count": sheet.row_count,
                "column_count": sheet.column_count,
                "frozen_rows": sheet.frozen_rows,
                "frozen_cols": sheet.frozen_cols,
            }
            tables.append(table)

        return tables

    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 50,
    ) -> AsyncIterator[SyncItem]:
        """
        Yield Google Sheets spreadsheets for syncing.

        Syncs both explicitly listed spreadsheets and those in specified folders.
        """
        items_yielded = 0
        processed_ids: set = set()

        # Get last sync time for incremental sync
        last_sync = None
        if state.cursor:
            try:
                last_sync = datetime.fromisoformat(state.cursor)
            except ValueError as e:
                logger.debug("Failed to parse datetime value: %s", e)

        # Process explicit spreadsheet IDs
        for spreadsheet_id in self.spreadsheet_ids:
            if spreadsheet_id in processed_ids:
                continue

            try:
                spreadsheet = await self._get_spreadsheet(spreadsheet_id)

                # Skip if not modified since last sync
                if last_sync and spreadsheet.modified_time:
                    if spreadsheet.modified_time <= last_sync:
                        continue

                processed_ids.add(spreadsheet_id)

                yield SyncItem(
                    id=f"gsheets-{spreadsheet.id}",
                    content=self._spreadsheet_to_text(spreadsheet)[:50000],
                    source_type="document",
                    source_id=f"gsheets/{spreadsheet.id}",
                    title=spreadsheet.title,
                    url=spreadsheet.web_view_link,
                    author=spreadsheet.owner,
                    created_at=spreadsheet.created_time,
                    updated_at=spreadsheet.modified_time,
                    domain="enterprise/gsheets",
                    confidence=0.9,
                    metadata={
                        "spreadsheet_id": spreadsheet.id,
                        "sheet_count": len(spreadsheet.sheets),
                        "locale": spreadsheet.locale,
                        "timezone": spreadsheet.timezone,
                        "tables": self._spreadsheet_to_tables(spreadsheet),
                    },
                )

                items_yielded += 1
                if items_yielded >= batch_size:
                    await asyncio.sleep(0)

            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.error("[%s] Failed to sync spreadsheet %s: %s", self.name, spreadsheet_id, e)

        # Process folder IDs
        for folder_id in self.folder_ids:
            page_token = None

            for _page in range(_MAX_PAGES):
                files, page_token = await self._list_spreadsheets_in_folder(folder_id, page_token)

                for file_info in files:
                    spreadsheet_id = file_info["id"]
                    if spreadsheet_id in processed_ids:
                        continue

                    # Check modification time before fetching full data
                    if last_sync and file_info.get("modifiedTime"):
                        try:
                            modified = datetime.fromisoformat(
                                file_info["modifiedTime"].replace("Z", "+00:00")
                            )
                            if modified <= last_sync:
                                continue
                        except ValueError as e:
                            logger.debug("Failed to parse datetime value: %s", e)

                    try:
                        spreadsheet = await self._get_spreadsheet(spreadsheet_id)
                        processed_ids.add(spreadsheet_id)

                        yield SyncItem(
                            id=f"gsheets-{spreadsheet.id}",
                            content=self._spreadsheet_to_text(spreadsheet)[:50000],
                            source_type="document",
                            source_id=f"gsheets/{spreadsheet.id}",
                            title=spreadsheet.title,
                            url=spreadsheet.web_view_link,
                            author=spreadsheet.owner,
                            created_at=spreadsheet.created_time,
                            updated_at=spreadsheet.modified_time,
                            domain="enterprise/gsheets",
                            confidence=0.9,
                            metadata={
                                "spreadsheet_id": spreadsheet.id,
                                "sheet_count": len(spreadsheet.sheets),
                                "folder_id": folder_id,
                                "tables": self._spreadsheet_to_tables(spreadsheet),
                            },
                        )

                        items_yielded += 1
                        if items_yielded >= batch_size:
                            await asyncio.sleep(0)

                    except (httpx.HTTPStatusError, httpx.RequestError) as e:
                        logger.error(
                            "[%s] Failed to sync spreadsheet %s: %s", self.name, spreadsheet_id, e
                        )

                if not page_token:
                    break

        # Update cursor for next sync
        state.cursor = datetime.now(timezone.utc).isoformat()
        state.items_total = items_yielded

    async def search(
        self,
        query: str,
        limit: int = 10,
        folder_id: str | None = None,
        **kwargs: Any,
    ) -> list:
        """Search Google Sheets by name or content."""
        from aragora.connectors.base import Evidence

        # Build search query
        q_parts = [
            f"(name contains '{query}' or fullText contains '{query}')",
            "mimeType = 'application/vnd.google-apps.spreadsheet'",
            "trashed = false",
        ]

        if folder_id:
            q_parts.append(f"'{folder_id}' in parents")

        params: dict[str, Any] = {
            "q": " and ".join(q_parts),
            "pageSize": limit,
            "fields": "files(id,name,modifiedTime,webViewLink)",
        }

        try:
            data = await self._api_request(f"{self.DRIVE_API_BASE}/files", params=params)

            results = []
            for item in data.get("files", []):
                results.append(
                    Evidence(
                        id=f"gsheets-{item['id']}",
                        source_type=self.source_type,
                        source_id=item["id"],
                        content="",  # Fetch content on demand
                        title=item.get("name", ""),
                        url=item.get("webViewLink", ""),
                        confidence=0.8,
                        metadata={
                            "type": "spreadsheet",
                        },
                    )
                )

            return results

        except (httpx.HTTPError, ConnectionError, TimeoutError, OSError, ValueError, KeyError) as e:
            logger.error("[%s] Search failed: %s", self.name, e)
            return []

    async def fetch(self, evidence_id: str) -> Any | None:
        """Fetch a specific spreadsheet."""
        from aragora.connectors.base import Evidence

        # Extract spreadsheet ID
        if evidence_id.startswith("gsheets-"):
            spreadsheet_id = evidence_id[8:]
        else:
            spreadsheet_id = evidence_id

        try:
            spreadsheet = await self._get_spreadsheet(spreadsheet_id)

            return Evidence(
                id=evidence_id,
                source_type=self.source_type,
                source_id=spreadsheet_id,
                content=self._spreadsheet_to_text(spreadsheet),
                title=spreadsheet.title,
                url=spreadsheet.web_view_link,
                author=spreadsheet.owner,
                confidence=0.9,
                metadata={
                    "spreadsheet_id": spreadsheet.id,
                    "sheet_count": len(spreadsheet.sheets),
                    "tables": self._spreadsheet_to_tables(spreadsheet),
                },
            )

        except (httpx.HTTPError, ConnectionError, TimeoutError, OSError, ValueError, KeyError) as e:
            logger.error("[%s] Fetch failed: %s", self.name, e)
            return None

    async def get_sheet_as_dataframe(
        self,
        spreadsheet_id: str,
        sheet_name: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Get a sheet as a DataFrame-like structure.

        Returns dict with 'columns' and 'data' keys for easy conversion
        to pandas or polars DataFrames.
        """
        try:
            spreadsheet = await self._get_spreadsheet(spreadsheet_id)

            if not spreadsheet.sheets:
                return None

            # Find target sheet
            sheet = spreadsheet.sheets[0]  # Default to first sheet
            if sheet_name:
                for s in spreadsheet.sheets:
                    if s.title == sheet_name:
                        sheet = s
                        break

            return {
                "columns": sheet.headers,
                "data": sheet.rows,
                "name": sheet.title,
                "row_count": sheet.row_count,
            }

        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            logger.error("[%s] DataFrame conversion failed: %s", self.name, e)
            return None


__all__ = ["GoogleSheetsConnector", "Spreadsheet", "SheetData"]
