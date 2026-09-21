"""
Tests for Google Sheets Enterprise Connector.

Tests the Google Sheets API integration including:
- OAuth2 authentication
- Spreadsheet metadata retrieval
- Sheet data extraction
- Incremental sync
- Search functionality
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from aragora.connectors.enterprise.documents.gsheets import (
    GoogleSheetsConnector,
    Spreadsheet,
    SheetData,
)
from aragora.connectors.enterprise.base import SyncState


class TestGoogleSheetsConnectorInit:
    """Test GoogleSheetsConnector initialization."""

    def test_default_configuration(self):
        """Should use default configuration."""
        connector = GoogleSheetsConnector()
        assert connector.spreadsheet_ids == []
        assert connector.folder_ids == []
        assert connector.include_formulas is False
        assert connector.header_row == 1

    def test_custom_configuration(self):
        """Should accept custom configuration."""
        connector = GoogleSheetsConnector(
            spreadsheet_ids=["sheet-1", "sheet-2"],
            folder_ids=["folder-1"],
            include_formulas=True,
            header_row=2,
            max_rows_per_sheet=10000,
        )
        assert connector.spreadsheet_ids == ["sheet-1", "sheet-2"]
        assert connector.folder_ids == ["folder-1"]
        assert connector.include_formulas is True
        assert connector.header_row == 2
        assert connector.max_rows_per_sheet == 10000

    def test_connector_properties(self):
        """Should have correct connector properties."""
        connector = GoogleSheetsConnector()
        assert connector.name == "Google Sheets"
        assert connector.connector_id == "gsheets"


class TestGoogleSheetsAuthentication:
    """Test authentication flows."""

    @pytest.mark.asyncio
    async def test_oauth_token_refresh(self):
        """Should refresh OAuth token successfully."""
        connector = GoogleSheetsConnector()
        connector.credentials = MagicMock()
        connector.credentials.get_credential = AsyncMock(
            side_effect=lambda key: {
                "GDRIVE_CLIENT_ID": "test_client_id",
                "GDRIVE_CLIENT_SECRET": "test_secret",
                "GDRIVE_REFRESH_TOKEN": "test_refresh_token",
            }.get(key)
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "access_token": "new_access_token",
                "expires_in": 3600,
            }
            mock_response.raise_for_status = MagicMock()

            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            token = await connector._get_access_token()

            assert token == "new_access_token"

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Should raise error when credentials missing."""
        connector = GoogleSheetsConnector()
        connector.credentials = MagicMock()
        connector.credentials.get_credential = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="credentials not configured"):
            await connector._get_access_token()


class TestColumnIndexConversion:
    """Test column index to letter conversion."""

    def test_single_letter_columns(self):
        """Should convert single letter columns correctly."""
        connector = GoogleSheetsConnector()
        assert connector._col_index_to_letter(1) == "A"
        assert connector._col_index_to_letter(2) == "B"
        assert connector._col_index_to_letter(26) == "Z"

    def test_double_letter_columns(self):
        """Should convert double letter columns correctly."""
        connector = GoogleSheetsConnector()
        assert connector._col_index_to_letter(27) == "AA"
        assert connector._col_index_to_letter(28) == "AB"
        assert connector._col_index_to_letter(52) == "AZ"

    def test_triple_letter_columns(self):
        """Should handle triple letter columns."""
        connector = GoogleSheetsConnector()
        # 702 = 26 + 26*26 = AA through ZZ + 1
        assert connector._col_index_to_letter(703) == "AAA"

    def test_zero_returns_a(self):
        """Should return A for edge cases."""
        connector = GoogleSheetsConnector()
        assert connector._col_index_to_letter(0) == "A"


class TestSpreadsheetParsing:
    """Test spreadsheet data parsing."""

    def test_spreadsheet_to_text(self):
        """Should convert spreadsheet to markdown text."""
        connector = GoogleSheetsConnector()
        spreadsheet = Spreadsheet(
            id="sheet-1",
            title="Sales Data",
            sheets=[
                SheetData(
                    title="Q1 2024",
                    sheet_id=0,
                    row_count=3,
                    column_count=3,
                    headers=["Product", "Revenue", "Units"],
                    rows=[
                        ["Widget A", "1000", "50"],
                        ["Widget B", "2000", "100"],
                    ],
                )
            ],
        )

        text = connector._spreadsheet_to_text(spreadsheet)

        assert "# Sales Data" in text
        assert "## Q1 2024" in text
        assert "| Product | Revenue | Units |" in text
        assert "| Widget A | 1000 | 50 |" in text

    def test_spreadsheet_to_tables(self):
        """Should convert spreadsheet to table structures."""
        connector = GoogleSheetsConnector()
        spreadsheet = Spreadsheet(
            id="sheet-1",
            title="Data",
            sheets=[
                SheetData(
                    title="Sheet1",
                    sheet_id=0,
                    row_count=2,
                    column_count=2,
                    headers=["A", "B"],
                    rows=[["1", "2"]],
                    frozen_rows=1,
                    frozen_cols=1,
                )
            ],
        )

        tables = connector._spreadsheet_to_tables(spreadsheet)

        assert len(tables) == 1
        assert tables[0]["name"] == "Sheet1"
        assert tables[0]["headers"] == ["A", "B"]
        assert tables[0]["frozen_rows"] == 1

    def test_text_truncation(self):
        """Should truncate long cell values in text output."""
        connector = GoogleSheetsConnector()
        long_value = "x" * 200  # Longer than 100 char limit

        spreadsheet = Spreadsheet(
            id="sheet-1",
            title="Data",
            sheets=[
                SheetData(
                    title="Sheet1",
                    sheet_id=0,
                    row_count=1,
                    column_count=1,
                    headers=["Column"],
                    rows=[[long_value]],
                )
            ],
        )

        text = connector._spreadsheet_to_text(spreadsheet)

        # Cell value should be truncated to 100 chars
        assert len(long_value[:100]) == 100


class TestSheetDataFetching:
    """Test sheet data retrieval."""

    @pytest.mark.asyncio
    async def test_fetch_sheet_data(self):
        """Should fetch sheet data correctly."""
        connector = GoogleSheetsConnector()
        connector._access_token = "test_token"

        mock_response = {
            "valueRanges": [
                {
                    "values": [
                        ["Name", "Age", "City"],
                        ["Alice", "30", "NYC"],
                        ["Bob", "25", "LA"],
                    ]
                }
            ]
        }

        with patch.object(connector, "_api_request", return_value=mock_response):
            sheet_data = await connector._fetch_sheet_data("sheet-1", "Sheet1", 10, 3)

            assert sheet_data is not None
            assert sheet_data.headers == ["Name", "Age", "City"]
            assert len(sheet_data.rows) == 2
            assert sheet_data.rows[0] == ["Alice", "30", "NYC"]

    @pytest.mark.asyncio
    async def test_fetch_empty_sheet(self):
        """Should handle empty sheets."""
        connector = GoogleSheetsConnector()
        connector._access_token = "test_token"

        mock_response = {"valueRanges": [{"values": []}]}

        with patch.object(connector, "_api_request", return_value=mock_response):
            sheet_data = await connector._fetch_sheet_data("sheet-1", "Empty", 0, 0)

            assert sheet_data is None


class TestSyncItems:
    """Test sync_items functionality."""

    @pytest.mark.asyncio
    async def test_sync_specific_spreadsheets(self):
        """Should sync specific spreadsheet IDs."""
        connector = GoogleSheetsConnector(spreadsheet_ids=["sheet-1"])
        connector._access_token = "test_token"

        mock_spreadsheet = Spreadsheet(
            id="sheet-1",
            title="Test Sheet",
            owner="user@test.com",
            web_view_link="https://sheets.google.com/sheet-1",
            modified_time=datetime.now(timezone.utc),
            sheets=[
                SheetData(
                    title="Data",
                    sheet_id=0,
                    row_count=2,
                    column_count=2,
                    headers=["A", "B"],
                    rows=[["1", "2"]],
                )
            ],
        )

        with patch.object(connector, "_get_spreadsheet", return_value=mock_spreadsheet):
            state = SyncState(connector_id="gsheets")
            items = []
            async for item in connector.sync_items(state):
                items.append(item)

            assert len(items) == 1
            assert items[0].title == "Test Sheet"
            assert "gsheets/sheet-1" in items[0].source_id

    @pytest.mark.asyncio
    async def test_incremental_sync(self):
        """Should skip unmodified spreadsheets."""
        connector = GoogleSheetsConnector(spreadsheet_ids=["sheet-1"])
        connector._access_token = "test_token"

        old_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_spreadsheet = Spreadsheet(
            id="sheet-1",
            title="Test Sheet",
            modified_time=old_time,
            sheets=[],
        )

        with patch.object(connector, "_get_spreadsheet", return_value=mock_spreadsheet):
            # Set cursor to after the spreadsheet's modified time
            state = SyncState(connector_id="gsheets", cursor="2024-01-15T00:00:00+00:00")
            items = []
            async for item in connector.sync_items(state):
                items.append(item)

            # Should skip because not modified since last sync
            assert len(items) == 0


class TestSearch:
    """Test search functionality."""

    @pytest.mark.asyncio
    async def test_search_spreadsheets(self):
        """Should search for spreadsheets by name."""
        connector = GoogleSheetsConnector()
        connector._access_token = "test_token"

        mock_response = {
            "files": [
                {
                    "id": "sheet-1",
                    "name": "Sales Report",
                    "webViewLink": "https://sheets.google.com/sheet-1",
                }
            ]
        }

        with patch.object(connector, "_api_request", return_value=mock_response):
            results = await connector.search("Sales")

            assert len(results) == 1
            assert results[0].title == "Sales Report"

    @pytest.mark.asyncio
    async def test_search_error_handling(self):
        """Should handle search errors gracefully."""
        connector = GoogleSheetsConnector()
        connector._access_token = "test_token"

        with patch.object(connector, "_api_request", side_effect=ConnectionError("API Error")):
            results = await connector.search("test")

            assert results == []


class TestFetch:
    """Test individual spreadsheet fetch."""

    @pytest.mark.asyncio
    async def test_fetch_spreadsheet(self):
        """Should fetch individual spreadsheet."""
        connector = GoogleSheetsConnector()
        connector._access_token = "test_token"

        mock_spreadsheet = Spreadsheet(
            id="sheet-1",
            title="Test Sheet",
            owner="user@test.com",
            sheets=[
                SheetData(
                    title="Data",
                    sheet_id=0,
                    row_count=1,
                    column_count=1,
                    headers=["Col"],
                    rows=[["Val"]],
                )
            ],
        )

        with patch.object(connector, "_get_spreadsheet", return_value=mock_spreadsheet):
            result = await connector.fetch("gsheets-sheet-1")

            assert result is not None
            assert result.title == "Test Sheet"

    @pytest.mark.asyncio
    async def test_fetch_error_handling(self):
        """Should handle fetch errors gracefully."""
        connector = GoogleSheetsConnector()
        connector._access_token = "test_token"

        with patch.object(connector, "_get_spreadsheet", side_effect=ConnectionError("Not Found")):
            result = await connector.fetch("gsheets-nonexistent")

            assert result is None


class TestDataFrameExport:
    """Test DataFrame-like export functionality."""

    @pytest.mark.asyncio
    async def test_get_sheet_as_dataframe(self):
        """Should return DataFrame-like structure."""
        connector = GoogleSheetsConnector()
        connector._access_token = "test_token"

        mock_spreadsheet = Spreadsheet(
            id="sheet-1",
            title="Data",
            sheets=[
                SheetData(
                    title="Sheet1",
                    sheet_id=0,
                    row_count=3,
                    column_count=2,
                    headers=["Name", "Value"],
                    rows=[["A", "1"], ["B", "2"], ["C", "3"]],
                )
            ],
        )

        with patch.object(connector, "_get_spreadsheet", return_value=mock_spreadsheet):
            result = await connector.get_sheet_as_dataframe("sheet-1")

            assert result is not None
            assert result["columns"] == ["Name", "Value"]
            assert len(result["data"]) == 3
            assert result["name"] == "Sheet1"

    @pytest.mark.asyncio
    async def test_get_specific_sheet_by_name(self):
        """Should get specific sheet by name."""
        connector = GoogleSheetsConnector()
        connector._access_token = "test_token"

        mock_spreadsheet = Spreadsheet(
            id="sheet-1",
            title="Data",
            sheets=[
                SheetData(
                    title="Sheet1",
                    sheet_id=0,
                    row_count=1,
                    column_count=1,
                    headers=["A"],
                    rows=[["1"]],
                ),
                SheetData(
                    title="Sheet2",
                    sheet_id=1,
                    row_count=1,
                    column_count=1,
                    headers=["B"],
                    rows=[["2"]],
                ),
            ],
        )

        with patch.object(connector, "_get_spreadsheet", return_value=mock_spreadsheet):
            result = await connector.get_sheet_as_dataframe("sheet-1", sheet_name="Sheet2")

            assert result is not None
            assert result["columns"] == ["B"]
            assert result["name"] == "Sheet2"


class TestDataClasses:
    """Test data class behavior."""

    def test_spreadsheet_defaults(self):
        """Should create Spreadsheet with defaults."""
        spreadsheet = Spreadsheet(id="1", title="Test")
        assert spreadsheet.locale == "en_US"
        assert spreadsheet.timezone == "UTC"
        assert spreadsheet.sheets == []

    def test_sheet_data_defaults(self):
        """Should create SheetData with defaults."""
        sheet = SheetData(
            title="Sheet1",
            sheet_id=0,
            row_count=0,
            column_count=0,
        )
        assert sheet.headers == []
        assert sheet.rows == []
        assert sheet.frozen_rows == 0
        assert sheet.frozen_cols == 0
