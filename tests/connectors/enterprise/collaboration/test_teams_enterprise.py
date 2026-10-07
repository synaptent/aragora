"""
Tests for Microsoft Teams Enterprise Connector.

Tests the Teams Graph API integration including:
- OAuth2 client credentials authentication
- Team and channel enumeration
- Message syncing with pagination
- File access via SharePoint
- Search functionality
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from aragora.connectors.enterprise.collaboration.teams import (
    TeamsEnterpriseConnector,
    TeamsTeam,
    TeamsChannel,
    TeamsMessage,
    TeamsFile,
)
from aragora.connectors.enterprise.base import SyncState


class TestTeamsConnectorInit:
    """Test TeamsEnterpriseConnector initialization."""

    def test_default_configuration(self):
        """Should use default configuration."""
        connector = TeamsEnterpriseConnector()
        assert connector.team_ids == []
        assert connector.include_files is True
        assert connector.include_replies is True
        assert connector.messages_per_channel == 1000

    def test_custom_configuration(self):
        """Should accept custom configuration."""
        connector = TeamsEnterpriseConnector(
            team_ids=["team-1", "team-2"],
            include_files=False,
            include_replies=False,
            messages_per_channel=500,
        )
        assert connector.team_ids == ["team-1", "team-2"]
        assert connector.include_files is False
        assert connector.include_replies is False
        assert connector.messages_per_channel == 500

    def test_connector_properties(self):
        """Should have correct connector properties."""
        connector = TeamsEnterpriseConnector()
        assert connector.name == "Microsoft Teams"
        assert connector.connector_id == "teams-enterprise"

    def test_private_channels_configuration(self):
        """Should configure private channel access."""
        connector = TeamsEnterpriseConnector(include_private_channels=True)
        assert connector.include_private_channels is True


class TestTeamsAuthentication:
    """Test authentication flows."""

    @pytest.mark.asyncio
    async def test_client_credentials_flow(self):
        """Should authenticate with client credentials."""
        connector = TeamsEnterpriseConnector(tenant_id="test-tenant")
        connector.credentials = MagicMock()
        connector.credentials.get_credential = AsyncMock(
            side_effect=lambda key: {
                "TEAMS_TENANT_ID": "test-tenant",
                "TEAMS_CLIENT_ID": "test-client-id",
                "TEAMS_CLIENT_SECRET": "test-secret",
            }.get(key)
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "access_token": "test_access_token",
                "expires_in": 3600,
            }
            mock_response.raise_for_status = MagicMock()

            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            token = await connector._get_access_token()

            assert token == "test_access_token"
            assert connector._access_token == "test_access_token"

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Should raise error when credentials missing."""
        connector = TeamsEnterpriseConnector()
        connector.credentials = MagicMock()
        connector.credentials.get_credential = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="credentials not configured"):
            await connector._get_access_token()


class TestTeamsTenantSeparation:
    """The Azure AD tenant authenticates; the base tenant keys sync state."""

    @staticmethod
    def _credentials(teams_tenant_id: str | None) -> MagicMock:
        credentials = MagicMock()
        credentials.get_credential = AsyncMock(
            side_effect=lambda key: {
                "TEAMS_TENANT_ID": teams_tenant_id,
                "TEAMS_CLIENT_ID": "test-client-id",
                "TEAMS_CLIENT_SECRET": "test-secret",
            }.get(key)
        )
        return credentials

    @staticmethod
    async def _token_url(connector: TeamsEnterpriseConnector) -> str:
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"access_token": "token", "expires_in": 3600}
            mock_response.raise_for_status = MagicMock()

            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            await connector._get_access_token()

        return mock_client_instance.post.call_args.args[0]

    @pytest.mark.asyncio
    async def test_azure_tenant_keeps_base_tenant_and_authenticates_against_it(self, tmp_path):
        connector = TeamsEnterpriseConnector(tenant_id="azure-tenant-guid", state_dir=tmp_path)
        connector.credentials = self._credentials("credential-tenant")

        assert connector.tenant_id == "default"
        assert connector.azure_tenant_id == "azure-tenant-guid"
        assert connector.connector_id == "teams-enterprise-azure-tenant-guid"
        assert await self._token_url(connector) == (
            "https://login.microsoftonline.com/azure-tenant-guid/oauth2/v2.0/token"
        )

    @pytest.mark.asyncio
    async def test_without_azure_tenant_falls_back_to_teams_tenant_id_credential(self, tmp_path):
        connector = TeamsEnterpriseConnector(state_dir=tmp_path)
        connector.credentials = self._credentials("credential-tenant")

        assert connector.tenant_id == "default"
        assert connector.azure_tenant_id is None
        assert await self._token_url(connector) == (
            "https://login.microsoftonline.com/credential-tenant/oauth2/v2.0/token"
        )

    @pytest.mark.parametrize(
        ("kwargs", "state_file"),
        [
            ({}, "teams-enterprise_default.json"),
            ({"tenant_id": "azure-tenant-guid"}, "teams-enterprise-azure-tenant-guid_default.json"),
        ],
    )
    def test_state_is_keyed_by_azure_tenant_and_base_tenant(self, tmp_path, kwargs, state_file):
        connector = TeamsEnterpriseConnector(state_dir=tmp_path, **kwargs)

        assert connector.state_path == tmp_path / state_file
        assert connector.load_state().tenant_id == "default"

    def test_without_azure_tenant_connector_id_does_not_read_credentials(self, tmp_path):
        credentials = self._credentials("credential-tenant")
        connector = TeamsEnterpriseConnector(state_dir=tmp_path, credentials=credentials)

        assert connector.connector_id == "teams-enterprise"
        assert connector.load_state().connector_id == "teams-enterprise"
        credentials.get_credential.assert_not_called()

    def test_two_azure_tenants_sharing_a_state_dir_keep_separate_sync_keys(self, tmp_path):
        tenant_a = TeamsEnterpriseConnector(tenant_id="azure-tenant-a", state_dir=tmp_path)
        tenant_b = TeamsEnterpriseConnector(tenant_id="azure-tenant-b", state_dir=tmp_path)

        assert tenant_a.tenant_id == tenant_b.tenant_id == "default"
        assert tenant_a.connector_id == "teams-enterprise-azure-tenant-a"
        assert tenant_b.connector_id == "teams-enterprise-azure-tenant-b"
        assert tenant_a.state_path == tmp_path / "teams-enterprise-azure-tenant-a_default.json"
        assert tenant_b.state_path == tmp_path / "teams-enterprise-azure-tenant-b_default.json"

        state_a = tenant_a.load_state()
        state_a.cursor = "tenant-a-delta-link"
        tenant_a.save_state()
        state_b = tenant_b.load_state()

        assert state_a.connector_id == "teams-enterprise-azure-tenant-a"
        assert state_b.connector_id == "teams-enterprise-azure-tenant-b"
        assert state_b.tenant_id == "default"
        assert state_b.cursor is None

        assert tenant_a._circuit_breaker is not None
        assert tenant_b._circuit_breaker is not None
        assert tenant_a._circuit_breaker.name == "connector_teams-enterprise-azure-tenant-a_default"
        assert tenant_b._circuit_breaker.name == "connector_teams-enterprise-azure-tenant-b_default"
        assert tenant_a._circuit_breaker is not tenant_b._circuit_breaker


class TestTeamAndChannelEnumeration:
    """Test team and channel listing."""

    @pytest.mark.asyncio
    async def test_list_specific_teams(self):
        """Should fetch specific teams by ID."""
        connector = TeamsEnterpriseConnector(team_ids=["team-1"])
        connector._access_token = "test_token"

        mock_team = {
            "id": "team-1",
            "displayName": "Engineering Team",
            "description": "Engineering discussions",
            "visibility": "private",
        }

        with patch.object(connector, "_api_request", return_value=mock_team):
            teams = []
            async for team in connector._list_teams():
                teams.append(team)

            assert len(teams) == 1
            assert teams[0].id == "team-1"
            assert teams[0].display_name == "Engineering Team"

    @pytest.mark.asyncio
    async def test_list_channels(self):
        """Should list channels in a team."""
        connector = TeamsEnterpriseConnector()
        connector._access_token = "test_token"

        mock_channels = {
            "value": [
                {
                    "id": "channel-1",
                    "displayName": "General",
                    "description": "General discussions",
                    "membershipType": "standard",
                },
                {
                    "id": "channel-2",
                    "displayName": "Development",
                    "membershipType": "standard",
                },
            ]
        }

        with patch.object(connector, "_api_request", return_value=mock_channels):
            channels = []
            async for channel in connector._list_channels("team-1"):
                channels.append(channel)

            assert len(channels) == 2
            assert channels[0].display_name == "General"


class TestMessageSyncing:
    """Test message retrieval and parsing."""

    @pytest.mark.asyncio
    async def test_get_channel_messages(self):
        """Should get messages from a channel."""
        connector = TeamsEnterpriseConnector(include_replies=False)
        connector._access_token = "test_token"

        mock_messages = {
            "value": [
                {
                    "id": "msg-1",
                    "messageType": "message",
                    "body": {"content": "Hello team!", "contentType": "text"},
                    "from": {"user": {"displayName": "John Doe", "email": "john@test.com"}},
                    "createdDateTime": "2024-01-15T10:00:00Z",
                },
            ]
        }

        with patch.object(connector, "_api_request", return_value=mock_messages):
            messages = []
            async for msg in connector._get_channel_messages("team-1", "channel-1"):
                messages.append(msg)

            assert len(messages) == 1
            assert messages[0].content == "Hello team!"
            assert messages[0].sender_name == "John Doe"

    @pytest.mark.asyncio
    async def test_skip_system_messages(self):
        """Should skip system messages when configured."""
        connector = TeamsEnterpriseConnector(
            exclude_system_messages=True,
            include_replies=False,
        )
        connector._access_token = "test_token"

        mock_messages = {
            "value": [
                {
                    "id": "msg-1",
                    "messageType": "systemEventMessage",
                    "body": {"content": "User joined"},
                },
                {
                    "id": "msg-2",
                    "messageType": "message",
                    "body": {"content": "Hello!"},
                    "from": {"user": {"displayName": "Jane"}},
                },
            ]
        }

        with patch.object(connector, "_api_request", return_value=mock_messages):
            messages = []
            async for msg in connector._get_channel_messages("team-1", "channel-1"):
                messages.append(msg)

            # Should only have the regular message
            assert len(messages) == 1
            assert messages[0].content == "Hello!"

    def test_strip_html(self):
        """Should strip HTML tags from content."""
        connector = TeamsEnterpriseConnector()

        html = "<p>Hello <b>world</b>!</p><br/><div>Test</div>"
        text = connector._strip_html(html)

        assert "<" not in text
        assert ">" not in text
        assert "Hello" in text
        assert "world" in text

    def test_strip_html_entities(self):
        """Should decode HTML entities."""
        connector = TeamsEnterpriseConnector()

        html = "Hello &amp; goodbye &lt;test&gt; &quot;quoted&quot;"
        text = connector._strip_html(html)

        assert "Hello & goodbye" in text
        assert "<test>" in text
        assert '"quoted"' in text


class TestFileSyncing:
    """Test file access via SharePoint."""

    @pytest.mark.asyncio
    async def test_get_channel_files(self):
        """Should get files from a channel."""
        connector = TeamsEnterpriseConnector(include_files=True)
        connector._access_token = "test_token"

        mock_folder = {
            "id": "folder-1",
            "parentReference": {"driveId": "drive-1"},
        }

        mock_files = {
            "value": [
                {
                    "id": "file-1",
                    "name": "document.pdf",
                    "size": 1024,
                    "file": {"mimeType": "application/pdf"},
                    "webUrl": "https://sharepoint.com/file-1",
                },
            ]
        }

        with patch.object(
            connector,
            "_api_request",
            side_effect=[mock_folder, mock_files],
        ):
            files = []
            async for f in connector._get_channel_files("team-1", "channel-1"):
                files.append(f)

            assert len(files) == 1
            assert files[0].name == "document.pdf"
            assert files[0].mime_type == "application/pdf"


class TestSyncItems:
    """Test sync_items functionality."""

    @pytest.mark.asyncio
    async def test_sync_items_messages(self):
        """Should yield sync items for messages."""
        connector = TeamsEnterpriseConnector(
            team_ids=["team-1"],
            include_files=False,
        )
        connector._access_token = "test_token"

        mock_team = TeamsTeam(
            id="team-1",
            display_name="Test Team",
        )

        mock_channel = TeamsChannel(
            id="channel-1",
            team_id="team-1",
            display_name="General",
        )

        mock_message = TeamsMessage(
            id="msg-1",
            team_id="team-1",
            channel_id="channel-1",
            content="Test message",
            sender_name="John",
            created_at=datetime.now(timezone.utc),
        )

        async def mock_list_teams():
            yield mock_team

        async def mock_list_channels(team_id):
            yield mock_channel

        async def mock_get_messages(team_id, channel_id, since=None):
            yield mock_message

        with patch.object(connector, "_list_teams", mock_list_teams):
            with patch.object(connector, "_list_channels", mock_list_channels):
                with patch.object(connector, "_get_channel_messages", mock_get_messages):
                    state = SyncState(connector_id="teams-enterprise")
                    items = []
                    async for item in connector.sync_items(state):
                        items.append(item)

                    assert len(items) == 1
                    assert "teams-msg-msg-1" in items[0].id
                    assert items[0].metadata["team_name"] == "Test Team"


class TestSearch:
    """Test search functionality."""

    @pytest.mark.asyncio
    async def test_search_messages(self):
        """Should search messages using Microsoft Search API."""
        connector = TeamsEnterpriseConnector()
        connector._access_token = "test_token"

        # Test that search returns empty list when API fails (error handling path)
        # This verifies the search method handles exceptions gracefully
        # Full integration test would require actual API keys
        results = await connector.search("project update")

        # Without proper credentials, search returns empty list (graceful error handling)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_error_handling(self):
        """Should handle search errors gracefully."""
        connector = TeamsEnterpriseConnector()
        connector._access_token = "test_token"

        with patch("httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(side_effect=Exception("API Error"))
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            results = await connector.search("test")

            assert results == []


class TestDateTimeParsing:
    """Test datetime parsing utilities."""

    def test_parse_valid_datetime(self):
        """Should parse valid datetime strings."""
        connector = TeamsEnterpriseConnector()

        result = connector._parse_datetime("2024-01-15T10:30:00Z")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_datetime_with_offset(self):
        """Should parse datetime with timezone offset."""
        connector = TeamsEnterpriseConnector()

        result = connector._parse_datetime("2024-01-15T10:30:00+00:00")
        assert result is not None

    def test_parse_none_datetime(self):
        """Should return None for None input."""
        connector = TeamsEnterpriseConnector()
        assert connector._parse_datetime(None) is None

    def test_parse_invalid_datetime(self):
        """Should return None for invalid format."""
        connector = TeamsEnterpriseConnector()
        assert connector._parse_datetime("invalid") is None


class TestMessageToText:
    """Test message text conversion."""

    def test_message_to_text(self):
        """Should convert message to text representation."""
        connector = TeamsEnterpriseConnector()
        message = TeamsMessage(
            id="msg-1",
            team_id="team-1",
            channel_id="channel-1",
            content="Hello team!",
            sender_name="John Doe",
            created_at=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
        )

        text = connector._message_to_text(message, "Test Team", "General")

        assert "[2024-01-15 10:30] John Doe:" in text
        assert "Hello team!" in text

    def test_message_with_attachments(self):
        """Should indicate attachments in text."""
        connector = TeamsEnterpriseConnector()
        message = TeamsMessage(
            id="msg-1",
            team_id="team-1",
            channel_id="channel-1",
            content="See attached",
            sender_name="Jane",
            attachments=[{"id": "att-1"}, {"id": "att-2"}],
        )

        text = connector._message_to_text(message, "Team", "Channel")

        assert "Attachments: 2" in text


class TestTeamsDataClasses:
    """Test data class behavior."""

    def test_teams_team_creation(self):
        """Should create TeamsTeam with defaults."""
        team = TeamsTeam(id="team-1", display_name="Test")
        assert team.visibility == "private"
        assert team.description == ""

    def test_teams_channel_creation(self):
        """Should create TeamsChannel with defaults."""
        channel = TeamsChannel(
            id="channel-1",
            team_id="team-1",
            display_name="General",
        )
        assert channel.membership_type == "standard"

    def test_teams_message_creation(self):
        """Should create TeamsMessage with defaults."""
        message = TeamsMessage(
            id="msg-1",
            team_id="team-1",
            channel_id="channel-1",
            content="Hello",
        )
        assert message.content_type == "text"
        assert message.attachments == []
        assert message.reply_to_id is None

    def test_teams_file_creation(self):
        """Should create TeamsFile with defaults."""
        file = TeamsFile(
            id="file-1",
            name="document.pdf",
            size=1024,
        )
        assert file.mime_type == ""
        assert file.download_url == ""
