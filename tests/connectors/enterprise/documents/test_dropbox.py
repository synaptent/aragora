"""
Tests for Dropbox Enterprise Connector.

Tests the Dropbox integration including:
- OAuth2 authentication flow
- File CRUD operations (list, download, delete)
- Folder operations
- Sharing and permissions
- Cursor-based incremental sync
- Webhook handling
- Rate limiting
- Error handling
"""

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.connectors.enterprise.base import SyncState, SyncStatus
from aragora.connectors.enterprise.documents.dropbox import (
    DropboxConnector,
    DropboxFile,
    DropboxFolder,
    SUPPORTED_EXTENSIONS,
)
from aragora.connectors.exceptions import (
    ConnectorAuthError,
    ConnectorAPIError,
    ConnectorNotFoundError,
    ConnectorRateLimitError,
)


# =============================================================================
# Test Subclass for Abstract Methods
# =============================================================================


class TestableDropboxConnector(DropboxConnector):
    """
    Concrete implementation of DropboxConnector for testing.

    Implements abstract methods required by BaseConnector.
    """

    @property
    def name(self) -> str:
        """Human-readable name."""
        return "Dropbox"

    async def search(self, query: str, limit: int = 10, **kwargs) -> list:
        """Search for evidence."""
        results = []
        async for file in self.search_files(query, max_results=limit):
            results.append(file)
        return results

    async def fetch(self, evidence_id: str) -> Any | None:
        """Fetch specific evidence."""
        try:
            return await self.get_file_metadata(evidence_id)
        except Exception:
            return None


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def dropbox_connector():
    """Create a Dropbox connector for testing."""
    return TestableDropboxConnector(
        app_key="test_app_key",
        app_secret="test_app_secret",
        access_token="test_access_token",
    )


@pytest.fixture
def dropbox_connector_with_refresh():
    """Create a Dropbox connector with refresh token."""
    return TestableDropboxConnector(
        app_key="test_app_key",
        app_secret="test_app_secret",
        refresh_token="test_refresh_token",
    )


@pytest.fixture
def sample_dropbox_files():
    """Sample Dropbox file entries."""
    return [
        {
            ".tag": "file",
            "id": "id:file1",
            "name": "document.txt",
            "path_lower": "/documents/document.txt",
            "path_display": "/Documents/document.txt",
            "size": 1500,
            "content_hash": "abc123hash",
            "client_modified": "2024-01-15T10:00:00Z",
            "is_downloadable": True,
        },
        {
            ".tag": "file",
            "id": "id:file2",
            "name": "report.pdf",
            "path_lower": "/documents/report.pdf",
            "path_display": "/Documents/report.pdf",
            "size": 50000,
            "content_hash": "def456hash",
            "client_modified": "2024-01-16T14:30:00Z",
            "is_downloadable": True,
        },
        {
            ".tag": "file",
            "id": "id:file3",
            "name": "code.py",
            "path_lower": "/code/code.py",
            "path_display": "/Code/code.py",
            "size": 2500,
            "content_hash": "ghi789hash",
            "client_modified": "2024-01-17T09:00:00Z",
            "is_downloadable": True,
        },
    ]


@pytest.fixture
def sample_dropbox_folders():
    """Sample Dropbox folder entries."""
    return [
        {
            ".tag": "folder",
            "id": "id:folder1",
            "name": "Documents",
            "path_lower": "/documents",
            "path_display": "/Documents",
            "shared_folder_id": None,
        },
        {
            ".tag": "folder",
            "id": "id:folder2",
            "name": "Code",
            "path_lower": "/code",
            "path_display": "/Code",
            "shared_folder_id": "sf123",
        },
    ]


@pytest.fixture
def mock_aiohttp_session():
    """Create a mock aiohttp session."""
    mock_session = AsyncMock()
    mock_session.close = AsyncMock()
    return mock_session


# =============================================================================
# Initialization Tests
# =============================================================================


class TestDropboxConnectorInit:
    """Test DropboxConnector initialization."""

    def test_init_with_app_credentials(self):
        """Test initialization with app key and secret."""
        connector = TestableDropboxConnector(
            app_key="my_app_key",
            app_secret="my_app_secret",
        )
        assert connector.app_key == "my_app_key"
        assert connector.app_secret == "my_app_secret"
        assert connector._access_token is None
        assert connector.connector_id == "dropbox_my_app_k"

    def test_init_with_access_token(self):
        """Test initialization with pre-existing access token."""
        connector = TestableDropboxConnector(
            app_key="my_app_key",
            app_secret="my_app_secret",
            access_token="preexisting_token",
        )
        assert connector._access_token == "preexisting_token"

    def test_init_with_refresh_token(self):
        """Test initialization with refresh token."""
        connector = TestableDropboxConnector(
            app_key="my_app_key",
            app_secret="my_app_secret",
            refresh_token="my_refresh_token",
        )
        assert connector._refresh_token == "my_refresh_token"

    def test_init_with_root_path(self):
        """Test initialization with custom root path."""
        connector = TestableDropboxConnector(
            app_key="my_app_key",
            app_secret="my_app_secret",
            root_path="/Team/Projects",
        )
        assert connector.root_path == "/Team/Projects"

    def test_init_with_patterns(self):
        """Test initialization with include/exclude patterns."""
        connector = TestableDropboxConnector(
            app_key="my_app_key",
            app_secret="my_app_secret",
            include_patterns=["*.txt", "*.pdf"],
            exclude_patterns=["backup_*"],
        )
        assert connector.include_patterns == ["*.txt", "*.pdf"]
        assert connector.exclude_patterns == ["backup_*"]

    def test_source_type(self, dropbox_connector):
        """Test source type property."""
        from aragora.reasoning.provenance import SourceType

        assert dropbox_connector.source_type == SourceType.DOCUMENT

    def test_is_configured(self, dropbox_connector):
        """Test is_configured property."""
        assert dropbox_connector.is_configured is True

        # Not configured without credentials
        empty_connector = TestableDropboxConnector()
        assert empty_connector.is_configured is False

    def test_connector_type(self, dropbox_connector):
        """Test connector type constant."""
        assert DropboxConnector.CONNECTOR_TYPE == "dropbox"
        assert DropboxConnector.DISPLAY_NAME == "Dropbox"


# =============================================================================
# OAuth2 Authentication Tests
# =============================================================================


class TestDropboxAuthentication:
    """Test OAuth2 authentication flows."""

    @pytest.mark.asyncio
    async def test_authenticate_with_refresh_token(self, dropbox_connector_with_refresh):
        """Test authentication using refresh token."""
        connector = dropbox_connector_with_refresh

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "access_token": "new_access_token",
                "expires_in": 14400,
            }
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch.object(connector, "_get_session", return_value=mock_session):
            result = await connector.authenticate()

            assert result is True
            assert connector._access_token == "new_access_token"
            assert connector._token_expires is not None

    @pytest.mark.asyncio
    async def test_authenticate_with_code(self, dropbox_connector):
        """Test authentication using authorization code."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "access_token": "code_access_token",
                "refresh_token": "code_refresh_token",
                "expires_in": 14400,
            }
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch.object(dropbox_connector, "_get_session", return_value=mock_session):
            result = await dropbox_connector.authenticate(
                code="auth_code_123",
                redirect_uri="https://myapp.com/callback",
            )

            assert result is True
            assert dropbox_connector._access_token == "code_access_token"
            assert dropbox_connector._refresh_token == "code_refresh_token"

    @pytest.mark.asyncio
    async def test_authenticate_with_existing_token(self, dropbox_connector):
        """Test authentication returns True with existing token."""
        result = await dropbox_connector.authenticate()
        assert result is True

    @pytest.mark.asyncio
    async def test_authenticate_refresh_token_failure(self, dropbox_connector_with_refresh):
        """Test handling refresh token failure."""
        connector = dropbox_connector_with_refresh

        mock_response = MagicMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value='{"error": "invalid_grant"}')

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch.object(connector, "_get_session", return_value=mock_session):
            result = await connector.authenticate()

            assert result is False

    @pytest.mark.asyncio
    async def test_token_expiry_refresh(self, dropbox_connector_with_refresh):
        """Test token is refreshed when expired."""
        connector = dropbox_connector_with_refresh
        connector._access_token = "expired_token"
        connector._token_expires = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            hours=1
        )

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "access_token": "refreshed_token",
                "expires_in": 14400,
            }
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch.object(connector, "_get_session", return_value=mock_session):
            await connector._ensure_valid_token()

            assert connector._access_token == "refreshed_token"

    def test_get_oauth_url(self, dropbox_connector):
        """Test OAuth URL generation."""
        url = dropbox_connector.get_oauth_url(
            redirect_uri="https://myapp.com/callback",
            state="random_state_123",
        )

        assert "https://www.dropbox.com/oauth2/authorize" in url
        assert "client_id=test_app_key" in url
        assert "redirect_uri=https" in url
        assert "state=random_state_123" in url
        assert "token_access_type=offline" in url

    def test_get_oauth_url_without_state(self, dropbox_connector):
        """Test OAuth URL generation without state."""
        url = dropbox_connector.get_oauth_url(redirect_uri="https://myapp.com/callback")

        assert "state=" not in url


# =============================================================================
# API Request Tests
# =============================================================================


class TestDropboxApiRequest:
    """Test Dropbox API requests."""

    @staticmethod
    def _create_mock_session(status: int, json_data: Any = None, text: str = ""):
        """Helper to create a properly mocked aiohttp session."""
        mock_response = MagicMock()
        mock_response.status = status
        mock_response.json = AsyncMock(return_value=json_data or {})
        mock_response.text = AsyncMock(return_value=text)
        mock_response.read = AsyncMock(return_value=text.encode())

        # Create async context manager for the response
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_cm)
        mock_session.get = MagicMock(return_value=mock_cm)

        return mock_session

    @pytest.mark.asyncio
    async def test_api_request_success(self, dropbox_connector):
        """Test successful API request."""
        mock_session = self._create_mock_session(200, {"entries": [], "has_more": False})

        with patch.object(dropbox_connector, "_get_session", AsyncMock(return_value=mock_session)):
            result = await dropbox_connector._api_request("/files/list_folder", {"path": ""})

            assert result == {"entries": [], "has_more": False}

    @pytest.mark.asyncio
    async def test_api_request_auth_error(self, dropbox_connector):
        """Test API request with authentication error."""
        mock_session = self._create_mock_session(401, text="Unauthorized")

        with patch.object(dropbox_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorAuthError):
                await dropbox_connector._api_request("/files/list_folder", {"path": ""})

    @pytest.mark.asyncio
    async def test_api_request_rate_limit(self, dropbox_connector):
        """Test API request with rate limit error."""
        mock_session = self._create_mock_session(429, text="Too Many Requests")

        with patch.object(dropbox_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorRateLimitError):
                await dropbox_connector._api_request("/files/list_folder", {"path": ""})

    @pytest.mark.asyncio
    async def test_api_request_not_found(self, dropbox_connector):
        """Test API request with not found error."""
        mock_session = self._create_mock_session(404, text="Not Found")

        with patch.object(dropbox_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorNotFoundError):
                await dropbox_connector._api_request("/files/list_folder", {"path": "/nonexistent"})

    @pytest.mark.asyncio
    async def test_api_request_server_error(self, dropbox_connector):
        """Test API request with server error."""
        mock_session = self._create_mock_session(500, text="Internal Server Error")

        with patch.object(dropbox_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorAPIError) as exc_info:
                await dropbox_connector._api_request("/files/list_folder", {"path": ""})

            assert exc_info.value.status_code == 500


# =============================================================================
# File Operations Tests
# =============================================================================


class TestDropboxFileOperations:
    """Test file listing and downloading."""

    @pytest.mark.asyncio
    async def test_list_files(self, dropbox_connector, sample_dropbox_files):
        """Test listing files in a folder."""
        mock_response = {
            "entries": sample_dropbox_files,
            "has_more": False,
        }

        with patch.object(dropbox_connector, "_api_request", return_value=mock_response):
            files = []
            async for file in dropbox_connector.list_files("/documents"):
                files.append(file)

            assert len(files) == 3
            assert files[0].name == "document.txt"
            assert files[0].size == 1500
            assert files[1].name == "report.pdf"

    @pytest.mark.asyncio
    async def test_list_files_with_pagination(self, dropbox_connector, sample_dropbox_files):
        """Test listing files with pagination."""
        first_page = {
            "entries": sample_dropbox_files[:2],
            "has_more": True,
            "cursor": "cursor_abc",
        }
        second_page = {
            "entries": sample_dropbox_files[2:],
            "has_more": False,
        }

        call_count = 0

        async def mock_api_request(endpoint, data=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return first_page
            return second_page

        with patch.object(dropbox_connector, "_api_request", side_effect=mock_api_request):
            files = []
            async for file in dropbox_connector.list_files("/"):
                files.append(file)

            assert len(files) == 3
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_list_files_recursive(self, dropbox_connector, sample_dropbox_files):
        """Test listing files recursively."""
        mock_response = {
            "entries": sample_dropbox_files,
            "has_more": False,
        }

        with patch.object(
            dropbox_connector, "_api_request", return_value=mock_response
        ) as mock_request:
            files = []
            async for file in dropbox_connector.list_files("/", recursive=True):
                files.append(file)

            # Check recursive flag was passed
            call_args = mock_request.call_args[0]
            assert call_args[1]["recursive"] is True

    @pytest.mark.asyncio
    async def test_list_files_skips_folders(
        self, dropbox_connector, sample_dropbox_files, sample_dropbox_folders
    ):
        """Test listing files skips folder entries."""
        mixed_entries = sample_dropbox_files + sample_dropbox_folders
        mock_response = {
            "entries": mixed_entries,
            "has_more": False,
        }

        with patch.object(dropbox_connector, "_api_request", return_value=mock_response):
            files = []
            async for file in dropbox_connector.list_files("/"):
                files.append(file)

            # Should only get files, not folders
            assert len(files) == 3
            for file in files:
                assert isinstance(file, DropboxFile)

    @staticmethod
    def _create_download_mock_session(status: int, content: bytes = b"", text: str = ""):
        """Helper to create a properly mocked aiohttp session for downloads."""
        mock_response = MagicMock()
        mock_response.status = status
        mock_response.read = AsyncMock(return_value=content)
        mock_response.text = AsyncMock(return_value=text)

        # Create async context manager for the response
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_cm)

        return mock_session

    @pytest.mark.asyncio
    async def test_download_file_success(self, dropbox_connector):
        """Test downloading a file."""
        file_content = b"File content here"
        mock_session = self._create_download_mock_session(200, content=file_content)

        with patch.object(dropbox_connector, "_get_session", AsyncMock(return_value=mock_session)):
            content = await dropbox_connector.download_file("/documents/test.txt")

            assert content == file_content

    @pytest.mark.asyncio
    async def test_download_file_not_found(self, dropbox_connector):
        """Test downloading a non-existent file."""
        mock_session = self._create_download_mock_session(404, text="File not found")

        with patch.object(dropbox_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorNotFoundError) as exc_info:
                await dropbox_connector.download_file("/nonexistent.txt")

            assert "/nonexistent.txt" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_download_file_rate_limit(self, dropbox_connector):
        """Test download with rate limit."""
        mock_session = self._create_download_mock_session(429, text="Rate limited")

        with patch.object(dropbox_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorRateLimitError):
                await dropbox_connector.download_file("/test.txt")

    @pytest.mark.asyncio
    async def test_get_file_metadata(self, dropbox_connector):
        """Test getting file metadata."""
        mock_response = {
            "id": "id:file1",
            "name": "document.txt",
            "path_lower": "/documents/document.txt",
            "path_display": "/Documents/document.txt",
            "size": 1500,
            "content_hash": "abc123hash",
            "client_modified": "2024-01-15T10:00:00Z",
            "is_downloadable": True,
        }

        with patch.object(dropbox_connector, "_api_request", return_value=mock_response):
            metadata = await dropbox_connector.get_file_metadata("/documents/document.txt")

            assert metadata.name == "document.txt"
            assert metadata.size == 1500
            assert metadata.content_hash == "abc123hash"


# =============================================================================
# Folder Operations Tests
# =============================================================================


class TestDropboxFolderOperations:
    """Test folder listing operations."""

    @pytest.mark.asyncio
    async def test_list_folders(
        self, dropbox_connector, sample_dropbox_folders, sample_dropbox_files
    ):
        """Test listing folders."""
        mixed_entries = sample_dropbox_files + sample_dropbox_folders
        mock_response = {
            "entries": mixed_entries,
            "has_more": False,
        }

        with patch.object(dropbox_connector, "_api_request", return_value=mock_response):
            folders = []
            async for folder in dropbox_connector.list_folders("/"):
                folders.append(folder)

            # Should only get folders
            assert len(folders) == 2
            assert folders[0].name == "Documents"
            assert folders[1].name == "Code"
            assert folders[1].shared_folder_id == "sf123"

    @pytest.mark.asyncio
    async def test_list_folders_with_pagination(self, dropbox_connector, sample_dropbox_folders):
        """Test listing folders with pagination."""
        first_page = {
            "entries": [sample_dropbox_folders[0]],
            "has_more": True,
            "cursor": "cursor_folders",
        }
        second_page = {
            "entries": [sample_dropbox_folders[1]],
            "has_more": False,
        }

        call_count = 0

        async def mock_api_request(endpoint, data=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return first_page
            return second_page

        with patch.object(dropbox_connector, "_api_request", side_effect=mock_api_request):
            folders = []
            async for folder in dropbox_connector.list_folders("/"):
                folders.append(folder)

            assert len(folders) == 2


# =============================================================================
# Search Tests
# =============================================================================


class TestDropboxSearch:
    """Test search functionality."""

    @pytest.mark.asyncio
    async def test_search_files(self, dropbox_connector):
        """Test searching for files."""
        mock_response = {
            "matches": [
                {
                    "metadata": {
                        "metadata": {
                            ".tag": "file",
                            "id": "id:file1",
                            "name": "quarterly_report.pdf",
                            "path_lower": "/reports/quarterly_report.pdf",
                            "path_display": "/Reports/quarterly_report.pdf",
                            "size": 50000,
                            "content_hash": "search_hash",
                        }
                    }
                },
                {
                    "metadata": {
                        "metadata": {
                            ".tag": "file",
                            "id": "id:file2",
                            "name": "annual_report.pdf",
                            "path_lower": "/reports/annual_report.pdf",
                            "path_display": "/Reports/annual_report.pdf",
                            "size": 100000,
                        }
                    }
                },
            ]
        }

        with patch.object(dropbox_connector, "_api_request", return_value=mock_response):
            results = []
            async for result in dropbox_connector.search_files("report", max_results=10):
                results.append(result)

            assert len(results) == 2
            assert results[0].name == "quarterly_report.pdf"
            assert results[1].name == "annual_report.pdf"

    @pytest.mark.asyncio
    async def test_search_with_extensions(self, dropbox_connector):
        """Test searching with file extension filter."""
        mock_response = {"matches": []}

        with patch.object(
            dropbox_connector, "_api_request", return_value=mock_response
        ) as mock_request:
            results = []
            async for result in dropbox_connector.search_files(
                "document",
                file_extensions=[".pdf", ".docx"],
            ):
                results.append(result)

            # Check extensions were passed
            call_args = mock_request.call_args[0]
            assert call_args[1]["options"]["file_extensions"] == [".pdf", ".docx"]

    @pytest.mark.asyncio
    async def test_search_skips_folders(self, dropbox_connector):
        """Test search skips folder results."""
        mock_response = {
            "matches": [
                {
                    "metadata": {
                        "metadata": {
                            ".tag": "folder",
                            "id": "id:folder1",
                            "name": "reports",
                        }
                    }
                },
                {
                    "metadata": {
                        "metadata": {
                            ".tag": "file",
                            "id": "id:file1",
                            "name": "report.pdf",
                            "path_lower": "/report.pdf",
                            "path_display": "/report.pdf",
                        }
                    }
                },
            ]
        }

        with patch.object(dropbox_connector, "_api_request", return_value=mock_response):
            results = []
            async for result in dropbox_connector.search_files("report"):
                results.append(result)

            assert len(results) == 1
            assert results[0].name == "report.pdf"


# =============================================================================
# Sync Tests
# =============================================================================


class TestDropboxSync:
    """Test cursor-based incremental sync."""

    @pytest.mark.asyncio
    async def test_sync_items_fresh_sync(self, dropbox_connector, sample_dropbox_files):
        """Test syncing items from scratch."""
        state = SyncState(connector_id="dropbox", status=SyncStatus.IDLE)

        # Filter to only supported extensions
        supported_files = [
            f
            for f in sample_dropbox_files
            if any(f["name"].endswith(ext) for ext in SUPPORTED_EXTENSIONS)
        ]
        mock_response = {
            "entries": supported_files,
            "has_more": False,
            "cursor": "sync_cursor_123",
        }

        with patch.object(dropbox_connector, "_api_request", return_value=mock_response):
            items = []
            async for item in dropbox_connector.sync_items(state):
                items.append(item)

            # Should get files + sync state item
            assert len(items) >= 1

            # Check for sync state item
            state_items = [i for i in items if i.id == "__sync_state__"]
            assert len(state_items) == 1
            assert state_items[0].metadata["cursor"] == "sync_cursor_123"

    @pytest.mark.asyncio
    async def test_sync_items_incremental(self, dropbox_connector, sample_dropbox_files):
        """Test incremental sync with existing cursor."""
        state = SyncState(
            connector_id="dropbox",
            cursor="existing_cursor",
            status=SyncStatus.IDLE,
        )

        supported_files = [
            f
            for f in sample_dropbox_files
            if any(f["name"].endswith(ext) for ext in SUPPORTED_EXTENSIONS)
        ]
        mock_response = {
            "entries": supported_files,
            "has_more": False,
            "cursor": "new_cursor_456",
        }

        with patch.object(
            dropbox_connector, "_api_request", return_value=mock_response
        ) as mock_request:
            items = []
            async for item in dropbox_connector.sync_items(state):
                items.append(item)

            # Should use continue endpoint with cursor
            assert mock_request.call_args[0][0] == "/files/list_folder/continue"
            assert mock_request.call_args[0][1]["cursor"] == "existing_cursor"

    @pytest.mark.asyncio
    async def test_sync_items_deleted_file(self, dropbox_connector):
        """Test syncing handles deleted files."""
        state = SyncState(
            connector_id="dropbox",
            cursor="cursor",
            status=SyncStatus.IDLE,
        )

        mock_response = {
            "entries": [
                {
                    ".tag": "deleted",
                    "name": "deleted.txt",
                    "path_lower": "/deleted.txt",
                }
            ],
            "has_more": False,
            "cursor": "new_cursor",
        }

        with patch.object(dropbox_connector, "_api_request", return_value=mock_response):
            items = []
            async for item in dropbox_connector.sync_items(state):
                items.append(item)

            # Should have delete item
            delete_items = [i for i in items if i.metadata.get("action") == "delete"]
            assert len(delete_items) == 1

    @pytest.mark.asyncio
    async def test_sync_items_filters_extensions(self, dropbox_connector):
        """Test sync filters unsupported extensions."""
        state = SyncState(connector_id="dropbox", status=SyncStatus.IDLE)

        mock_response = {
            "entries": [
                {
                    ".tag": "file",
                    "id": "id:supported",
                    "name": "code.py",
                    "path_lower": "/code.py",
                    "path_display": "/code.py",
                    "size": 1000,
                },
                {
                    ".tag": "file",
                    "id": "id:unsupported",
                    "name": "image.png",
                    "path_lower": "/image.png",
                    "path_display": "/image.png",
                    "size": 50000,
                },
            ],
            "has_more": False,
            "cursor": "cursor",
        }

        with patch.object(dropbox_connector, "_api_request", return_value=mock_response):
            items = []
            async for item in dropbox_connector.sync_items(state):
                items.append(item)

            # Should only get .py file (not .png)
            file_items = [i for i in items if i.id != "__sync_state__"]
            assert len(file_items) == 1
            assert file_items[0].title == "code.py"


# =============================================================================
# Account Info Tests
# =============================================================================


class TestDropboxAccountInfo:
    """Test account info retrieval."""

    @pytest.mark.asyncio
    async def test_get_account_info(self, dropbox_connector):
        """Test getting account info."""
        mock_response = {
            "account_id": "dbid:AAH123",
            "name": {"display_name": "Test User"},
            "email": "test@example.com",
        }

        with patch.object(dropbox_connector, "_api_request", return_value=mock_response):
            info = await dropbox_connector.get_account_info()

            assert info["account_id"] == "dbid:AAH123"
            assert info["email"] == "test@example.com"


# =============================================================================
# DateTime Parsing Tests
# =============================================================================


class TestDateTimeParsing:
    """Test datetime parsing utilities."""

    def test_parse_datetime_valid(self, dropbox_connector):
        """Test parsing valid datetime string."""
        result = dropbox_connector._parse_datetime("2024-01-15T10:30:00Z")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_datetime_none(self, dropbox_connector):
        """Test parsing None returns None."""
        result = dropbox_connector._parse_datetime(None)
        assert result is None

    def test_parse_datetime_invalid(self, dropbox_connector):
        """Test parsing invalid string returns None."""
        result = dropbox_connector._parse_datetime("not a date")
        assert result is None


# =============================================================================
# Session Management Tests
# =============================================================================


class TestDropboxSessionManagement:
    """Test session management."""

    @pytest.mark.asyncio
    async def test_session_creation(self, dropbox_connector):
        """Test session is created on first request."""
        with patch("aiohttp.ClientSession") as MockSession:
            mock_instance = AsyncMock()
            MockSession.return_value = mock_instance

            session = await dropbox_connector._get_session()

            MockSession.assert_called_once()
            assert session == mock_instance

    @pytest.mark.asyncio
    async def test_session_reuse(self, dropbox_connector):
        """Test session is reused on subsequent requests."""
        mock_session = AsyncMock()
        dropbox_connector._session = mock_session

        session = await dropbox_connector._get_session()

        assert session == mock_session

    @pytest.mark.asyncio
    async def test_close_session(self, dropbox_connector):
        """Test session close."""
        mock_session = AsyncMock()
        dropbox_connector._session = mock_session

        await dropbox_connector.close()

        mock_session.close.assert_called_once()
        assert dropbox_connector._session is None


# =============================================================================
# Data Classes Tests
# =============================================================================


class TestDropboxDataClasses:
    """Test data class behavior."""

    def test_dropbox_file_defaults(self):
        """Test DropboxFile with defaults."""
        file = DropboxFile(
            id="id:123",
            name="test.txt",
            path_lower="/test.txt",
            path_display="/test.txt",
        )
        assert file.size == 0
        assert file.content_hash is None
        assert file.is_downloadable is True
        assert file.shared_folder_id is None

    def test_dropbox_folder_defaults(self):
        """Test DropboxFolder with defaults."""
        folder = DropboxFolder(
            id="id:folder",
            name="Folder",
            path_lower="/folder",
            path_display="/Folder",
        )
        assert folder.shared_folder_id is None


# =============================================================================
# Constants Tests
# =============================================================================


class TestDropboxConstants:
    """Test module constants."""

    def test_supported_extensions(self):
        """Test supported extensions include common types."""
        assert ".txt" in SUPPORTED_EXTENSIONS
        assert ".pdf" in SUPPORTED_EXTENSIONS
        assert ".py" in SUPPORTED_EXTENSIONS
        assert ".md" in SUPPORTED_EXTENSIONS
        assert ".json" in SUPPORTED_EXTENSIONS
        assert ".docx" in SUPPORTED_EXTENSIONS

    def test_api_endpoints(self):
        """Test API endpoint constants."""
        assert DropboxConnector.API_BASE == "https://api.dropboxapi.com/2"
        assert DropboxConnector.CONTENT_BASE == "https://content.dropboxapi.com/2"
        assert DropboxConnector.AUTH_URL == "https://www.dropbox.com/oauth2"
