"""
Tests for Microsoft OneDrive Enterprise Connector.

Tests the OneDrive integration including:
- OAuth2 authentication via Microsoft Graph
- File CRUD operations (list, download, upload)
- Folder operations
- Sharing and permissions
- Delta sync for incremental updates
- Webhook handling
- Rate limiting
- Error handling
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import pytest

from aragora.connectors.enterprise.base import SyncState, SyncStatus
from aragora.connectors.enterprise.documents.onedrive import (
    OneDriveConnector,
    OneDriveFile,
    OneDriveFolder,
    SUPPORTED_EXTENSIONS,
    OFFICE_MIMES,
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


class TestableOneDriveConnector(OneDriveConnector):
    """
    Concrete implementation of OneDriveConnector for testing.

    Implements abstract methods required by BaseConnector.
    """

    @property
    def name(self) -> str:
        """Human-readable name."""
        return "Microsoft OneDrive"

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
def onedrive_connector():
    """Create a OneDrive connector for testing."""
    return TestableOneDriveConnector(
        client_id="test_client_id",
        client_secret="test_client_secret",
        tenant_id="test_tenant",
        access_token="test_access_token",
    )


@pytest.fixture
def onedrive_connector_with_refresh():
    """Create a OneDrive connector with refresh token."""
    return TestableOneDriveConnector(
        client_id="test_client_id",
        client_secret="test_client_secret",
        tenant_id="test_tenant",
        refresh_token="test_refresh_token",
    )


@pytest.fixture
def onedrive_connector_with_drive_id():
    """Create a OneDrive connector with specific drive ID."""
    return TestableOneDriveConnector(
        client_id="test_client_id",
        client_secret="test_client_secret",
        tenant_id="test_tenant",
        access_token="test_access_token",
        drive_id="specific_drive_123",
    )


@pytest.fixture
def sample_onedrive_files():
    """Sample OneDrive file entries."""
    return [
        {
            "id": "file-001",
            "name": "document.docx",
            "file": {
                "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            },
            "size": 25000,
            "createdDateTime": "2024-01-15T10:00:00Z",
            "lastModifiedDateTime": "2024-01-16T14:30:00Z",
            "webUrl": "https://onedrive.com/file-001",
            "parentReference": {
                "id": "folder-001",
                "path": "/drive/root:/Documents",
                "driveId": "drive-001",
            },
            "@microsoft.graph.downloadUrl": "https://download.url/file-001",
        },
        {
            "id": "file-002",
            "name": "report.pdf",
            "file": {"mimeType": "application/pdf"},
            "size": 100000,
            "createdDateTime": "2024-01-14T09:00:00Z",
            "lastModifiedDateTime": "2024-01-17T11:00:00Z",
            "webUrl": "https://onedrive.com/file-002",
            "parentReference": {
                "id": "folder-001",
                "path": "/drive/root:/Documents",
            },
            "shared": {"scope": "users"},
        },
        {
            "id": "file-003",
            "name": "code.py",
            "file": {"mimeType": "text/x-python"},
            "size": 5000,
            "createdDateTime": "2024-01-13T08:00:00Z",
            "lastModifiedDateTime": "2024-01-18T09:00:00Z",
            "webUrl": "https://onedrive.com/file-003",
            "parentReference": {
                "id": "folder-002",
                "path": "/drive/root:/Code",
            },
        },
    ]


@pytest.fixture
def sample_onedrive_folders():
    """Sample OneDrive folder entries."""
    return [
        {
            "id": "folder-001",
            "name": "Documents",
            "folder": {"childCount": 10},
            "parentReference": {"id": "root", "path": "/drive/root:"},
        },
        {
            "id": "folder-002",
            "name": "Code",
            "folder": {"childCount": 5},
            "parentReference": {"id": "root", "path": "/drive/root:"},
        },
    ]


@pytest.fixture
def sample_drives():
    """Sample drive list."""
    return [
        {
            "id": "drive-001",
            "name": "OneDrive",
            "driveType": "personal",
        },
        {
            "id": "drive-002",
            "name": "SharePoint",
            "driveType": "business",
        },
    ]


# =============================================================================
# Initialization Tests
# =============================================================================


class TestOneDriveConnectorInit:
    """Test OneDriveConnector initialization."""

    def test_init_with_credentials(self):
        """Test initialization with client credentials."""
        connector = TestableOneDriveConnector(
            client_id="my_client_id",
            client_secret="my_client_secret",
            tenant_id="my_tenant",
        )
        assert connector.client_id == "my_client_id"
        assert connector.client_secret == "my_client_secret"
        assert connector.tenant_id == "my_tenant"
        assert connector.connector_id == "onedrive-my_tenant"

    def test_init_with_common_tenant(self):
        """Test initialization with common (multi-tenant) tenant ID."""
        connector = TestableOneDriveConnector(
            client_id="my_client_id",
            client_secret="my_client_secret",
        )
        assert connector.tenant_id == "common"

    def test_init_with_access_token(self):
        """Test initialization with pre-existing access token."""
        connector = TestableOneDriveConnector(
            client_id="my_client_id",
            client_secret="my_client_secret",
            access_token="preexisting_token",
        )
        assert connector._access_token == "preexisting_token"

    def test_init_with_refresh_token(self):
        """Test initialization with refresh token."""
        connector = TestableOneDriveConnector(
            client_id="my_client_id",
            client_secret="my_client_secret",
            refresh_token="my_refresh_token",
        )
        assert connector._refresh_token == "my_refresh_token"

    def test_init_with_drive_id(self):
        """Test initialization with specific drive ID."""
        connector = TestableOneDriveConnector(
            client_id="my_client_id",
            client_secret="my_client_secret",
            drive_id="specific_drive",
        )
        assert connector.drive_id == "specific_drive"

    def test_init_with_patterns(self):
        """Test initialization with include/exclude patterns."""
        connector = TestableOneDriveConnector(
            client_id="my_client_id",
            client_secret="my_client_secret",
            include_patterns=["*.txt", "*.pdf"],
            exclude_patterns=["backup_*"],
        )
        assert connector.include_patterns == ["*.txt", "*.pdf"]
        assert connector.exclude_patterns == ["backup_*"]

    def test_source_type(self, onedrive_connector):
        """Test source type property."""
        from aragora.reasoning.provenance import SourceType

        assert onedrive_connector.source_type == SourceType.DOCUMENT

    def test_is_configured(self, onedrive_connector):
        """Test is_configured property."""
        assert onedrive_connector.is_configured is True

        # Not configured without credentials
        empty_connector = TestableOneDriveConnector()
        assert empty_connector.is_configured is False

    def test_connector_type(self, onedrive_connector):
        """Test connector type constant."""
        assert OneDriveConnector.CONNECTOR_TYPE == "onedrive"
        assert OneDriveConnector.DISPLAY_NAME == "Microsoft OneDrive"

    def test_get_drive_path_default(self, onedrive_connector):
        """Test default drive path."""
        path = onedrive_connector._get_drive_path()
        assert path == "/me/drive"

    def test_get_drive_path_with_drive_id(self, onedrive_connector_with_drive_id):
        """Test drive path with specific drive ID."""
        path = onedrive_connector_with_drive_id._get_drive_path()
        assert path == "/drives/specific_drive_123"


# =============================================================================
# OAuth2 Authentication Tests
# =============================================================================


class TestOneDriveAuthentication:
    """Test OAuth2 authentication flows."""

    @pytest.mark.asyncio
    async def test_authenticate_with_refresh_token(self, onedrive_connector_with_refresh):
        """Test authentication using refresh token."""
        connector = onedrive_connector_with_refresh

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "access_token": "new_access_token",
                "refresh_token": "new_refresh_token",
                "expires_in": 3600,
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
            assert connector._refresh_token == "new_refresh_token"
            assert connector._token_expires is not None

    @pytest.mark.asyncio
    async def test_authenticate_with_code(self, onedrive_connector):
        """Test authentication using authorization code."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "access_token": "code_access_token",
                "refresh_token": "code_refresh_token",
                "expires_in": 3600,
            }
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch.object(onedrive_connector, "_get_session", return_value=mock_session):
            result = await onedrive_connector.authenticate(
                code="auth_code_123",
                redirect_uri="https://myapp.com/callback",
            )

            assert result is True
            assert onedrive_connector._access_token == "code_access_token"
            assert onedrive_connector._refresh_token == "code_refresh_token"

    @pytest.mark.asyncio
    async def test_authenticate_with_existing_token(self, onedrive_connector):
        """Test authentication returns True with existing token."""
        result = await onedrive_connector.authenticate()
        assert result is True

    @pytest.mark.asyncio
    async def test_authenticate_refresh_token_failure(self, onedrive_connector_with_refresh):
        """Test handling refresh token failure."""
        connector = onedrive_connector_with_refresh

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
    async def test_token_expiry_refresh(self, onedrive_connector_with_refresh):
        """Test token is refreshed when expired."""
        connector = onedrive_connector_with_refresh
        connector._access_token = "expired_token"
        connector._token_expires = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            hours=1
        )

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "access_token": "refreshed_token",
                "expires_in": 3600,
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

    def test_get_oauth_url(self, onedrive_connector):
        """Test OAuth URL generation."""
        url = onedrive_connector.get_oauth_url(
            redirect_uri="https://myapp.com/callback",
            state="random_state_123",
        )

        assert "https://login.microsoftonline.com/test_tenant/oauth2/v2.0/authorize" in url
        assert "client_id=test_client_id" in url
        assert "state=random_state_123" in url
        assert "files.read" in url
        assert "offline_access" in url

    def test_get_oauth_url_without_state(self, onedrive_connector):
        """Test OAuth URL generation without state."""
        url = onedrive_connector.get_oauth_url(redirect_uri="https://myapp.com/callback")

        assert "state=" not in url


# =============================================================================
# API Request Tests
# =============================================================================


class TestOneDriveApiRequest:
    """Test OneDrive API requests."""

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
        mock_session.request = MagicMock(return_value=mock_cm)
        mock_session.get = MagicMock(return_value=mock_cm)

        return mock_session

    @pytest.mark.asyncio
    async def test_api_request_success(self, onedrive_connector):
        """Test successful API request."""
        mock_session = self._create_mock_session(200, {"value": [], "@odata.nextLink": None})

        with patch.object(onedrive_connector, "_get_session", AsyncMock(return_value=mock_session)):
            result = await onedrive_connector._api_request("GET", "/me/drive/root/children")

            assert result == {"value": [], "@odata.nextLink": None}

    @pytest.mark.asyncio
    async def test_api_request_204_no_content(self, onedrive_connector):
        """Test API request with 204 No Content response."""
        mock_session = self._create_mock_session(204)

        with patch.object(onedrive_connector, "_get_session", AsyncMock(return_value=mock_session)):
            result = await onedrive_connector._api_request("DELETE", "/me/drive/items/file-001")

            assert result == {}

    @pytest.mark.asyncio
    async def test_api_request_auth_error(self, onedrive_connector):
        """Test API request with authentication error."""
        mock_session = self._create_mock_session(401, text="Unauthorized")

        with patch.object(onedrive_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorAuthError):
                await onedrive_connector._api_request("GET", "/me/drive")

    @pytest.mark.asyncio
    async def test_api_request_rate_limit(self, onedrive_connector):
        """Test API request with rate limit error."""
        mock_session = self._create_mock_session(429, text="Too Many Requests")

        with patch.object(onedrive_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorRateLimitError):
                await onedrive_connector._api_request("GET", "/me/drive")

    @pytest.mark.asyncio
    async def test_api_request_not_found(self, onedrive_connector):
        """Test API request with not found error."""
        mock_session = self._create_mock_session(404, text="Not Found")

        with patch.object(onedrive_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorNotFoundError):
                await onedrive_connector._api_request("GET", "/me/drive/items/nonexistent")

    @pytest.mark.asyncio
    async def test_api_request_server_error(self, onedrive_connector):
        """Test API request with server error."""
        mock_session = self._create_mock_session(500, text="Internal Server Error")

        with patch.object(onedrive_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorAPIError) as exc_info:
                await onedrive_connector._api_request("GET", "/me/drive")

            assert exc_info.value.status_code == 500


# =============================================================================
# File Operations Tests
# =============================================================================


class TestOneDriveFileOperations:
    """Test file listing and downloading."""

    @pytest.mark.asyncio
    async def test_list_files_root(self, onedrive_connector, sample_onedrive_files):
        """Test listing files in root."""
        mock_response = {
            "value": sample_onedrive_files,
            "@odata.nextLink": None,
        }

        with patch.object(onedrive_connector, "_api_request", return_value=mock_response):
            files = []
            async for file in onedrive_connector.list_files("/"):
                files.append(file)

            assert len(files) == 3
            assert files[0].name == "document.docx"
            assert files[0].size == 25000
            assert files[1].name == "report.pdf"

    @pytest.mark.asyncio
    async def test_list_files_subfolder(self, onedrive_connector, sample_onedrive_files):
        """Test listing files in a subfolder."""
        mock_response = {
            "value": sample_onedrive_files,
        }

        with patch.object(
            onedrive_connector, "_api_request", return_value=mock_response
        ) as mock_request:
            files = []
            async for file in onedrive_connector.list_files("/Documents"):
                files.append(file)

            # Check the encoded path was used
            call_args = mock_request.call_args
            assert "Documents" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_list_files_with_pagination(self, onedrive_connector, sample_onedrive_files):
        """Test listing files with pagination."""
        first_page = {
            "value": sample_onedrive_files[:2],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/drive/root/children?$skiptoken=abc",
        }
        second_page = {
            "value": sample_onedrive_files[2:],
        }

        call_count = 0

        async def mock_api_request(method, endpoint, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return first_page
            return second_page

        with patch.object(onedrive_connector, "_api_request", side_effect=mock_api_request):
            files = []
            async for file in onedrive_connector.list_files("/"):
                files.append(file)

            assert len(files) == 3
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_list_files_skips_folders(
        self, onedrive_connector, sample_onedrive_files, sample_onedrive_folders
    ):
        """Test listing files skips folder entries."""
        mixed_items = sample_onedrive_files + sample_onedrive_folders
        mock_response = {
            "value": mixed_items,
        }

        with patch.object(onedrive_connector, "_api_request", return_value=mock_response):
            files = []
            async for file in onedrive_connector.list_files("/"):
                files.append(file)

            # Should only get files, not folders
            assert len(files) == 3
            for file in files:
                assert isinstance(file, OneDriveFile)

    @staticmethod
    def _create_download_mock_session(status: int, content: bytes = b""):
        """Helper to create a properly mocked aiohttp session for downloads."""
        mock_response = MagicMock()
        mock_response.status = status
        mock_response.read = AsyncMock(return_value=content)

        # Create async context manager for the response
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)

        return mock_session

    @pytest.mark.asyncio
    async def test_download_file_success(self, onedrive_connector):
        """Test downloading a file."""
        file_content = b"File content here"
        mock_session = self._create_download_mock_session(200, content=file_content)

        with patch.object(onedrive_connector, "_get_session", AsyncMock(return_value=mock_session)):
            content = await onedrive_connector.download_file("file-001")

            assert content == file_content

    @pytest.mark.asyncio
    async def test_download_file_not_found(self, onedrive_connector):
        """Test downloading a non-existent file."""
        mock_session = self._create_download_mock_session(404)

        with patch.object(onedrive_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorNotFoundError) as exc_info:
                await onedrive_connector.download_file("nonexistent")

            assert "nonexistent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_download_file_rate_limit(self, onedrive_connector):
        """Test download with rate limit."""
        mock_session = self._create_download_mock_session(429)

        with patch.object(onedrive_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorRateLimitError):
                await onedrive_connector.download_file("file-001")

    @pytest.mark.asyncio
    async def test_get_file_metadata(self, onedrive_connector, sample_onedrive_files):
        """Test getting file metadata."""
        mock_response = sample_onedrive_files[0]

        with patch.object(onedrive_connector, "_api_request", return_value=mock_response):
            metadata = await onedrive_connector.get_file_metadata("file-001")

            assert metadata.name == "document.docx"
            assert metadata.size == 25000
            assert (
                metadata.mime_type
                == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )


# =============================================================================
# Folder Operations Tests
# =============================================================================


class TestOneDriveFolderOperations:
    """Test folder listing operations."""

    @pytest.mark.asyncio
    async def test_list_folders(
        self, onedrive_connector, sample_onedrive_folders, sample_onedrive_files
    ):
        """Test listing folders."""
        mixed_items = sample_onedrive_files + sample_onedrive_folders
        mock_response = {
            "value": mixed_items,
        }

        with patch.object(onedrive_connector, "_api_request", return_value=mock_response):
            folders = []
            async for folder in onedrive_connector.list_folders("/"):
                folders.append(folder)

            # Should only get folders
            assert len(folders) == 2
            assert folders[0].name == "Documents"
            assert folders[0].child_count == 10
            assert folders[1].name == "Code"

    @pytest.mark.asyncio
    async def test_list_folders_with_pagination(self, onedrive_connector, sample_onedrive_folders):
        """Test listing folders with pagination."""
        first_page = {
            "value": [sample_onedrive_folders[0]],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/next",
        }
        second_page = {
            "value": [sample_onedrive_folders[1]],
        }

        call_count = 0

        async def mock_api_request(method, endpoint, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return first_page
            return second_page

        with patch.object(onedrive_connector, "_api_request", side_effect=mock_api_request):
            folders = []
            async for folder in onedrive_connector.list_folders("/"):
                folders.append(folder)

            assert len(folders) == 2


# =============================================================================
# Drive Operations Tests
# =============================================================================


class TestOneDriveDriveOperations:
    """Test drive listing operations."""

    @pytest.mark.asyncio
    async def test_list_drives(self, onedrive_connector, sample_drives):
        """Test listing available drives."""
        mock_response = {"value": sample_drives}

        with patch.object(onedrive_connector, "_api_request", return_value=mock_response):
            drives = await onedrive_connector.list_drives()

            assert len(drives) == 2
            assert drives[0]["id"] == "drive-001"
            assert drives[1]["driveType"] == "business"

    @pytest.mark.asyncio
    async def test_get_user_info(self, onedrive_connector):
        """Test getting user info."""
        mock_response = {
            "id": "user-001",
            "displayName": "Test User",
            "mail": "test@example.com",
        }

        with patch.object(onedrive_connector, "_api_request", return_value=mock_response):
            info = await onedrive_connector.get_user_info()

            assert info["displayName"] == "Test User"
            assert info["mail"] == "test@example.com"


# =============================================================================
# Search Tests
# =============================================================================


class TestOneDriveSearch:
    """Test search functionality."""

    @pytest.mark.asyncio
    async def test_search_files(self, onedrive_connector, sample_onedrive_files):
        """Test searching for files."""
        mock_response = {
            "value": sample_onedrive_files[:2],
        }

        with patch.object(onedrive_connector, "_api_request", return_value=mock_response):
            results = []
            async for result in onedrive_connector.search_files("report"):
                results.append(result)

            assert len(results) == 2
            assert results[0].name == "document.docx"
            assert results[1].name == "report.pdf"

    @pytest.mark.asyncio
    async def test_search_skips_folders(self, onedrive_connector, sample_onedrive_folders):
        """Test search skips folder results."""
        mock_response = {
            "value": sample_onedrive_folders
            + [
                {
                    "id": "file-001",
                    "name": "result.pdf",
                    "file": {"mimeType": "application/pdf"},
                }
            ],
        }

        with patch.object(onedrive_connector, "_api_request", return_value=mock_response):
            results = []
            async for result in onedrive_connector.search_files("test"):
                results.append(result)

            assert len(results) == 1
            assert results[0].name == "result.pdf"

    @pytest.mark.asyncio
    async def test_search_max_results(self, onedrive_connector):
        """Test search respects max_results."""
        mock_response = {"value": []}

        with patch.object(
            onedrive_connector, "_api_request", return_value=mock_response
        ) as mock_request:
            results = []
            async for result in onedrive_connector.search_files("test", max_results=25):
                results.append(result)

            # Check $top param
            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["params"]["$top"] == 25


# =============================================================================
# Delta Sync Tests
# =============================================================================


class TestOneDriveDeltaSync:
    """Test delta-based incremental sync."""

    @pytest.mark.asyncio
    async def test_sync_items_fresh_sync(self, onedrive_connector, sample_onedrive_files):
        """Test syncing items from scratch."""
        state = SyncState(connector_id="onedrive", status=SyncStatus.IDLE)

        # Filter to only supported extensions
        supported_files = [
            f
            for f in sample_onedrive_files
            if any(f["name"].endswith(ext) for ext in SUPPORTED_EXTENSIONS)
        ]
        mock_response = {
            "value": supported_files,
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta?token=new_delta_token",
        }

        with patch.object(onedrive_connector, "_api_request", return_value=mock_response):
            items = []
            async for item in onedrive_connector.sync_items(state):
                items.append(item)

            # Should get files + sync state item
            assert len(items) >= 1

            # Check for sync state item with delta link
            state_items = [i for i in items if i.id == "__sync_state__"]
            assert len(state_items) == 1
            assert "delta_link" in state_items[0].metadata

    @pytest.mark.asyncio
    async def test_sync_items_incremental(self, onedrive_connector, sample_onedrive_files):
        """Test incremental sync with existing delta link."""
        delta_link = "https://graph.microsoft.com/v1.0/me/drive/root/delta?token=existing_token"
        state = SyncState(
            connector_id="onedrive",
            cursor=delta_link,
            status=SyncStatus.IDLE,
        )

        supported_files = [
            f
            for f in sample_onedrive_files
            if any(f["name"].endswith(ext) for ext in SUPPORTED_EXTENSIONS)
        ]
        mock_response = {
            "value": supported_files,
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta?token=new_token",
        }

        with patch.object(
            onedrive_connector, "_api_request", return_value=mock_response
        ) as mock_request:
            items = []
            async for item in onedrive_connector.sync_items(state):
                items.append(item)

            # Should use the delta link endpoint
            call_args = mock_request.call_args[0]
            assert "delta" in call_args[1]

    @pytest.mark.asyncio
    async def test_sync_items_deleted_file(self, onedrive_connector):
        """Test syncing handles deleted files."""
        state = SyncState(
            connector_id="onedrive",
            cursor="https://graph.microsoft.com/v1.0/delta?token=abc",
            status=SyncStatus.IDLE,
        )

        mock_response = {
            "value": [
                {
                    "id": "deleted-file",
                    "name": "deleted.txt",
                    "deleted": {"state": "deleted"},
                }
            ],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta?token=new",
        }

        with patch.object(onedrive_connector, "_api_request", return_value=mock_response):
            items = []
            async for item in onedrive_connector.sync_items(state):
                items.append(item)

            # Should have delete item
            delete_items = [i for i in items if i.metadata.get("action") == "delete"]
            assert len(delete_items) == 1

    @pytest.mark.asyncio
    async def test_sync_items_filters_extensions(self, onedrive_connector):
        """Test sync filters unsupported extensions."""
        state = SyncState(connector_id="onedrive", status=SyncStatus.IDLE)

        mock_response = {
            "value": [
                {
                    "id": "supported",
                    "name": "code.py",
                    "file": {"mimeType": "text/x-python"},
                    "webUrl": "https://onedrive.com/code.py",
                    "lastModifiedDateTime": "2024-01-15T10:00:00Z",
                },
                {
                    "id": "unsupported",
                    "name": "image.png",
                    "file": {"mimeType": "image/png"},
                    "webUrl": "https://onedrive.com/image.png",
                    "lastModifiedDateTime": "2024-01-15T10:00:00Z",
                },
            ],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta?token=abc",
        }

        with patch.object(onedrive_connector, "_api_request", return_value=mock_response):
            items = []
            async for item in onedrive_connector.sync_items(state):
                items.append(item)

            # Should only get .py file (not .png)
            file_items = [i for i in items if i.id != "__sync_state__"]
            assert len(file_items) == 1
            assert file_items[0].title == "code.py"

    @pytest.mark.asyncio
    async def test_sync_items_skips_folders(self, onedrive_connector, sample_onedrive_folders):
        """Test sync skips folder entries."""
        state = SyncState(connector_id="onedrive", status=SyncStatus.IDLE)

        mock_response = {
            "value": sample_onedrive_folders,
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta?token=abc",
        }

        with patch.object(onedrive_connector, "_api_request", return_value=mock_response):
            items = []
            async for item in onedrive_connector.sync_items(state):
                items.append(item)

            # Should only have sync state item, no folders
            file_items = [i for i in items if i.id != "__sync_state__"]
            assert len(file_items) == 0


# =============================================================================
# DateTime Parsing Tests
# =============================================================================


class TestDateTimeParsing:
    """Test datetime parsing utilities."""

    def test_parse_datetime_valid(self, onedrive_connector):
        """Test parsing valid datetime string."""
        result = onedrive_connector._parse_datetime("2024-01-15T10:30:00Z")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_datetime_none(self, onedrive_connector):
        """Test parsing None returns None."""
        result = onedrive_connector._parse_datetime(None)
        assert result is None

    def test_parse_datetime_invalid(self, onedrive_connector):
        """Test parsing invalid string returns None."""
        result = onedrive_connector._parse_datetime("not a date")
        assert result is None


# =============================================================================
# Session Management Tests
# =============================================================================


class TestOneDriveSessionManagement:
    """Test session management."""

    @pytest.mark.asyncio
    async def test_session_creation(self, onedrive_connector):
        """Test session is created on first request."""
        with patch("aiohttp.ClientSession") as MockSession:
            mock_instance = AsyncMock()
            MockSession.return_value = mock_instance

            session = await onedrive_connector._get_session()

            MockSession.assert_called_once()
            assert session == mock_instance

    @pytest.mark.asyncio
    async def test_session_reuse(self, onedrive_connector):
        """Test session is reused on subsequent requests."""
        mock_session = AsyncMock()
        onedrive_connector._session = mock_session

        session = await onedrive_connector._get_session()

        assert session == mock_session

    @pytest.mark.asyncio
    async def test_close_session(self, onedrive_connector):
        """Test session close."""
        mock_session = AsyncMock()
        onedrive_connector._session = mock_session

        await onedrive_connector.close()

        mock_session.close.assert_called_once()
        assert onedrive_connector._session is None


# =============================================================================
# Data Classes Tests
# =============================================================================


class TestOneDriveDataClasses:
    """Test data class behavior."""

    def test_onedrive_file_defaults(self):
        """Test OneDriveFile with defaults."""
        file = OneDriveFile(
            id="file-001",
            name="test.txt",
            mime_type="text/plain",
        )
        assert file.size == 0
        assert file.created_time is None
        assert file.modified_time is None
        assert file.web_url == ""
        assert file.parent_id is None
        assert file.download_url is None
        assert file.shared is False
        assert file.drive_id is None

    def test_onedrive_folder_defaults(self):
        """Test OneDriveFolder with defaults."""
        folder = OneDriveFolder(
            id="folder-001",
            name="Folder",
        )
        assert folder.parent_id is None
        assert folder.path == ""
        assert folder.child_count == 0


# =============================================================================
# Constants Tests
# =============================================================================


class TestOneDriveConstants:
    """Test module constants."""

    def test_supported_extensions(self):
        """Test supported extensions include common types."""
        assert ".txt" in SUPPORTED_EXTENSIONS
        assert ".pdf" in SUPPORTED_EXTENSIONS
        assert ".py" in SUPPORTED_EXTENSIONS
        assert ".md" in SUPPORTED_EXTENSIONS
        assert ".json" in SUPPORTED_EXTENSIONS
        assert ".docx" in SUPPORTED_EXTENSIONS

    def test_office_mimes(self):
        """Test Office MIME type mappings."""
        assert (
            OFFICE_MIMES["application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
            == "docx"
        )
        assert (
            OFFICE_MIMES["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]
            == "xlsx"
        )
        assert (
            OFFICE_MIMES[
                "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            ]
            == "pptx"
        )

    def test_api_endpoints(self):
        """Test API endpoint constants."""
        assert OneDriveConnector.GRAPH_BASE == "https://graph.microsoft.com/v1.0"
        assert OneDriveConnector.AUTH_URL == "https://login.microsoftonline.com"


# =============================================================================
# SSRF Protection Tests
# =============================================================================


class TestSSRFProtection:
    """Test SSRF protection for redirect handling."""

    def test_is_safe_redirect_url_allowed_domains(self):
        """Test that allowed Microsoft domains are accepted."""
        from aragora.connectors.enterprise.documents.onedrive import _is_safe_redirect_url

        # Test various allowed Microsoft domains
        safe_urls = [
            "https://graph.microsoft.com/v1.0/me/drive",
            "https://login.microsoftonline.com/oauth",
            "https://login.live.com/oauth20",
            "https://myaccount.blob.core.windows.net/container/file",
            "https://contoso.sharepoint.com/sites/team",
            "https://onedrive.com/download",
            "https://office.com/files",
            "https://office365.com/download",
            "https://subdomain.sharepoint.com/file",
            "https://tenant.onedrive.com/file",
        ]

        for url in safe_urls:
            is_safe, reason = _is_safe_redirect_url(url)
            assert is_safe, f"URL {url} should be safe but got: {reason}"

    def test_is_safe_redirect_url_blocked_domains(self):
        """Test that non-Microsoft domains are blocked."""
        from aragora.connectors.enterprise.documents.onedrive import _is_safe_redirect_url

        blocked_urls = [
            "https://evil.com/steal-data",
            "https://attacker.io/exfiltrate",
            "https://notmicrosoft.com/fake",
            "https://sharepoint.com.evil.com/phish",
            "https://microsoftfake.com/steal",
        ]

        for url in blocked_urls:
            is_safe, reason = _is_safe_redirect_url(url)
            assert not is_safe, f"URL {url} should be blocked"
            assert "not in allowlist" in reason

    def test_is_safe_redirect_url_private_ips(self):
        """Test that private/internal IPs are blocked."""
        from aragora.connectors.enterprise.documents.onedrive import _is_safe_redirect_url

        private_ip_urls = [
            "https://10.0.0.1/internal",
            "https://192.168.1.1/local",
            "https://172.16.0.1/private",
            "https://127.0.0.1/localhost",
            "https://169.254.169.254/metadata",  # AWS metadata endpoint
            "https://[::1]/ipv6-localhost",
        ]

        for url in private_ip_urls:
            is_safe, reason = _is_safe_redirect_url(url)
            assert not is_safe, f"URL {url} should be blocked"
            assert "Private/internal IP" in reason or "not in allowlist" in reason

    def test_is_safe_redirect_url_localhost(self):
        """Test that localhost variants are blocked."""
        from aragora.connectors.enterprise.documents.onedrive import _is_safe_redirect_url

        localhost_urls = [
            "https://localhost/internal",
            "https://localhost.localdomain/internal",
        ]

        for url in localhost_urls:
            is_safe, reason = _is_safe_redirect_url(url)
            assert not is_safe, f"URL {url} should be blocked"

    def test_is_safe_redirect_url_non_https(self):
        """Test that non-HTTPS schemes are blocked."""
        from aragora.connectors.enterprise.documents.onedrive import _is_safe_redirect_url

        non_https_urls = [
            "http://graph.microsoft.com/file",
            "file:///etc/passwd",
            "ftp://files.sharepoint.com/file",
            "gopher://evil.com/",
        ]

        for url in non_https_urls:
            is_safe, reason = _is_safe_redirect_url(url)
            assert not is_safe, f"URL {url} should be blocked"
            assert "Unsafe scheme" in reason

    def test_is_private_ip_function(self):
        """Test the _is_private_ip helper function."""
        from aragora.connectors.enterprise.documents.onedrive import _is_private_ip

        # Private IPs should return True
        assert _is_private_ip("10.0.0.1") is True
        assert _is_private_ip("192.168.1.1") is True
        assert _is_private_ip("172.16.0.1") is True
        assert _is_private_ip("127.0.0.1") is True
        assert _is_private_ip("169.254.1.1") is True  # Link-local
        assert _is_private_ip("localhost") is True

        # Public IPs should return False
        assert _is_private_ip("8.8.8.8") is False
        assert _is_private_ip("1.1.1.1") is False

        # Hostnames (non-localhost) should return False (domain check happens elsewhere)
        assert _is_private_ip("graph.microsoft.com") is False

    @pytest.mark.asyncio
    async def test_download_file_ssrf_blocked_redirect(self, onedrive_connector):
        """Test that SSRF attempts via redirect are blocked."""
        # Create mock responses: first a redirect to evil domain, then we should never reach second
        redirect_response = MagicMock()
        redirect_response.status = 302
        redirect_response.headers = {"Location": "https://evil.com/steal-data"}

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=redirect_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)

        with patch.object(onedrive_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorAPIError) as exc_info:
                await onedrive_connector.download_file("file-001")

            assert "Blocked unsafe redirect" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_download_file_ssrf_blocked_private_ip(self, onedrive_connector):
        """Test that redirects to private IPs are blocked."""
        redirect_response = MagicMock()
        redirect_response.status = 302
        redirect_response.headers = {"Location": "https://192.168.1.1/internal"}

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=redirect_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)

        with patch.object(onedrive_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorAPIError) as exc_info:
                await onedrive_connector.download_file("file-001")

            assert "Blocked unsafe redirect" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_download_file_ssrf_blocked_http(self, onedrive_connector):
        """Test that redirects to HTTP are blocked."""
        redirect_response = MagicMock()
        redirect_response.status = 302
        redirect_response.headers = {"Location": "http://graph.microsoft.com/file"}

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=redirect_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)

        with patch.object(onedrive_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorAPIError) as exc_info:
                await onedrive_connector.download_file("file-001")

            assert "Blocked unsafe redirect" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_download_file_allowed_redirect(self, onedrive_connector):
        """Test that redirects to allowed domains succeed."""
        # First response: redirect to Azure blob storage
        redirect_response = MagicMock()
        redirect_response.status = 302
        redirect_response.headers = {
            "Location": "https://myaccount.blob.core.windows.net/container/file.txt"
        }

        # Second response: successful download
        success_response = MagicMock()
        success_response.status = 200
        success_response.read = AsyncMock(return_value=b"file content")

        call_count = 0

        def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_cm = MagicMock()
            if call_count == 1:
                mock_cm.__aenter__ = AsyncMock(return_value=redirect_response)
            else:
                mock_cm.__aenter__ = AsyncMock(return_value=success_response)
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            return mock_cm

        mock_session = MagicMock()
        mock_session.get = mock_get

        with patch.object(onedrive_connector, "_get_session", AsyncMock(return_value=mock_session)):
            content = await onedrive_connector.download_file("file-001")

            assert content == b"file content"
            assert call_count == 2  # Initial request + redirect

    @pytest.mark.asyncio
    async def test_download_file_max_redirects(self, onedrive_connector):
        """Test that too many redirects are blocked."""
        from aragora.connectors.enterprise.documents.onedrive import MAX_REDIRECTS

        # Create a redirect response that always redirects
        redirect_response = MagicMock()
        redirect_response.status = 302
        redirect_response.headers = {
            "Location": "https://graph.microsoft.com/v1.0/another/redirect"
        }

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=redirect_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)

        with patch.object(onedrive_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorAPIError) as exc_info:
                await onedrive_connector.download_file("file-001")

            assert "Too many redirects" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_download_file_missing_location_header(self, onedrive_connector):
        """Test that redirect without Location header is handled."""
        redirect_response = MagicMock()
        redirect_response.status = 302
        redirect_response.headers = {}  # No Location header

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=redirect_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)

        with patch.object(onedrive_connector, "_get_session", AsyncMock(return_value=mock_session)):
            with pytest.raises(ConnectorAPIError) as exc_info:
                await onedrive_connector.download_file("file-001")

            assert "missing Location header" in str(exc_info.value)
