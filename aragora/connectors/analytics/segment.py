"""
Segment Connector.

Integration with Segment CDP (Customer Data Platform):
- Track events and identify users
- Access source and destination configurations
- Query warehouse data
- Manage audiences and personas
"""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0
_MAX_DELAY = 30.0


class SourceType(Enum):
    """Segment source types."""

    JAVASCRIPT = "javascript"
    PYTHON = "python"
    IOS = "ios"
    ANDROID = "android"
    HTTP = "http"
    CLOUD_APP = "cloud_app"
    SERVER = "server"


class DestinationType(Enum):
    """Common destination types."""

    GOOGLE_ANALYTICS = "Google Analytics"
    MIXPANEL = "Mixpanel"
    AMPLITUDE = "Amplitude"
    FACEBOOK_PIXEL = "Facebook Pixel"
    HUBSPOT = "HubSpot"
    SALESFORCE = "Salesforce"
    BIGQUERY = "BigQuery"
    SNOWFLAKE = "Snowflake"
    REDSHIFT = "Redshift"
    WEBHOOK = "Webhooks"


class EventType(Enum):
    """Segment event types."""

    TRACK = "track"
    IDENTIFY = "identify"
    PAGE = "page"
    SCREEN = "screen"
    GROUP = "group"
    ALIAS = "alias"


@dataclass
class SegmentCredentials:
    """Segment API credentials."""

    write_key: str
    workspace_slug: str | None = None
    access_token: str | None = None  # For Config API


@dataclass
class Source:
    """Segment data source."""

    id: str
    name: str
    slug: str
    source_type: str
    workspace_id: str
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None
    write_key: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Source":
        """Create from Segment API response."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            slug=data.get("slug", ""),
            source_type=data.get("sourceDefinitionId", data.get("source_definition_id", "")),
            workspace_id=data.get("workspaceId", data.get("workspace_id", "")),
            enabled=data.get("enabled", True),
            created_at=(
                datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00"))
                if data.get("createdAt")
                else None
            ),
            updated_at=(
                datetime.fromisoformat(data["updatedAt"].replace("Z", "+00:00"))
                if data.get("updatedAt")
                else None
            ),
            write_key=data.get("writeKey") or data.get("write_key"),
        )


@dataclass
class Destination:
    """Segment destination."""

    id: str
    name: str
    source_id: str
    destination_type: str
    enabled: bool = True
    created_at: datetime | None = None
    settings: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Destination":
        """Create from Segment API response."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            source_id=data.get("sourceId", data.get("source_id", "")),
            destination_type=data.get(
                "destinationDefinitionId", data.get("destination_definition_id", "")
            ),
            enabled=data.get("enabled", True),
            created_at=(
                datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00"))
                if data.get("createdAt")
                else None
            ),
            settings=data.get("settings", {}),
        )


@dataclass
class TrackEvent:
    """Segment track event."""

    user_id: str | None
    anonymous_id: str | None
    event: str
    properties: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime | None = None

    def to_api(self) -> dict[str, Any]:
        """Convert to Segment API format."""
        data: dict[str, Any] = {
            "event": self.event,
            "properties": self.properties,
            "context": self.context,
        }

        if self.user_id:
            data["userId"] = self.user_id
        if self.anonymous_id:
            data["anonymousId"] = self.anonymous_id
        if self.timestamp:
            data["timestamp"] = self.timestamp.isoformat()

        return data


@dataclass
class IdentifyCall:
    """Segment identify call."""

    user_id: str
    anonymous_id: str | None = None
    traits: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime | None = None

    def to_api(self) -> dict[str, Any]:
        """Convert to Segment API format."""
        data: dict[str, Any] = {
            "userId": self.user_id,
            "traits": self.traits,
            "context": self.context,
        }

        if self.anonymous_id:
            data["anonymousId"] = self.anonymous_id
        if self.timestamp:
            data["timestamp"] = self.timestamp.isoformat()

        return data


@dataclass
class PageEvent:
    """Segment page event."""

    user_id: str | None
    anonymous_id: str | None
    name: str | None = None
    category: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime | None = None

    def to_api(self) -> dict[str, Any]:
        """Convert to Segment API format."""
        data: dict[str, Any] = {
            "properties": self.properties,
            "context": self.context,
        }

        if self.user_id:
            data["userId"] = self.user_id
        if self.anonymous_id:
            data["anonymousId"] = self.anonymous_id
        if self.name:
            data["name"] = self.name
        if self.category:
            data["category"] = self.category
        if self.timestamp:
            data["timestamp"] = self.timestamp.isoformat()

        return data


@dataclass
class GroupCall:
    """Segment group call."""

    user_id: str
    group_id: str
    traits: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime | None = None

    def to_api(self) -> dict[str, Any]:
        """Convert to Segment API format."""
        data: dict[str, Any] = {
            "userId": self.user_id,
            "groupId": self.group_id,
            "traits": self.traits,
            "context": self.context,
        }

        if self.timestamp:
            data["timestamp"] = self.timestamp.isoformat()

        return data


@dataclass
class Audience:
    """Segment Personas audience."""

    id: str
    name: str
    space_id: str
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    size: int | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Audience":
        """Create from Segment API response."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            space_id=data.get("spaceId", data.get("space_id", "")),
            description=data.get("description"),
            created_at=(
                datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00"))
                if data.get("createdAt")
                else None
            ),
            updated_at=(
                datetime.fromisoformat(data["updatedAt"].replace("Z", "+00:00"))
                if data.get("updatedAt")
                else None
            ),
            size=data.get("size"),
        )


@dataclass
class Profile:
    """Segment user profile."""

    segment_id: str
    user_id: str | None = None
    anonymous_id: str | None = None
    traits: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Profile":
        """Create from Segment API response."""
        return cls(
            segment_id=data.get("segment_id", ""),
            user_id=data.get("user_id"),
            anonymous_id=data.get("anonymous_id"),
            traits=data.get("traits", {}),
            created_at=(
                datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
            ),
            updated_at=(
                datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None
            ),
        )


class SegmentError(Exception):
    """Segment API error."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_code: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class SegmentConnector:
    """Segment CDP connector."""

    TRACKING_URL = "https://api.segment.io/v1"
    CONFIG_URL = "https://api.segment.com/v1"
    PROFILES_URL = "https://profiles.segment.com/v1"

    def __init__(self, credentials: SegmentCredentials):
        """Initialize with credentials."""
        self.credentials = credentials
        self._tracking_client: httpx.AsyncClient | None = None
        self._config_client: httpx.AsyncClient | None = None
        self._profiles_client: httpx.AsyncClient | None = None

    async def _get_tracking_client(self) -> httpx.AsyncClient:
        """Get tracking API client (uses write key)."""
        if self._tracking_client is None:
            import base64

            auth = base64.b64encode(f"{self.credentials.write_key}:".encode()).decode()
            self._tracking_client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._tracking_client

    async def _get_config_client(self) -> httpx.AsyncClient:
        """Get config API client (uses access token)."""
        if self._config_client is None:
            if not self.credentials.access_token:
                raise SegmentError("Access token required for Config API")
            self._config_client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self.credentials.access_token}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._config_client

    async def _get_profiles_client(self) -> httpx.AsyncClient:
        """Get profiles API client."""
        if self._profiles_client is None:
            if not self.credentials.access_token:
                raise SegmentError("Access token required for Profiles API")
            self._profiles_client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self.credentials.access_token}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._profiles_client

    async def close(self) -> None:
        """Close HTTP clients."""
        if self._tracking_client:
            await self._tracking_client.aclose()
            self._tracking_client = None
        if self._config_client:
            await self._config_client.aclose()
            self._config_client = None
        if self._profiles_client:
            await self._profiles_client.aclose()
            self._profiles_client = None

    async def _tracking_request(
        self,
        endpoint: str,
        json_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Make tracking API request with retry and exponential backoff."""
        client = await self._get_tracking_client()
        url = f"{self.TRACKING_URL}/{endpoint}"

        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await client.post(url, json=json_data)

                if response.status_code == 429 and attempt < _MAX_RETRIES:
                    retry_after = float(
                        response.headers.get("Retry-After", _BASE_DELAY * (2**attempt))
                    )
                    jitter = random.uniform(0, retry_after * 0.3)
                    delay = min(retry_after + jitter, _MAX_DELAY)
                    logger.warning(
                        "Segment tracking rate limited, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 500 and attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Segment tracking server error %d, retrying in %.1fs (attempt %d/%d)",
                        response.status_code,
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 400:
                    error_data = response.json() if response.content else {}
                    raise SegmentError(
                        message=error_data.get("message", f"API error: {response.status_code}"),
                        status_code=response.status_code,
                        error_code=error_data.get("code"),
                    )

                return response.json() if response.content else {"success": True}

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Segment tracking request timeout, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
            except httpx.ConnectError as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Segment tracking connection error, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
            except SegmentError:
                raise

        raise SegmentError(
            message=f"Request failed after {_MAX_RETRIES + 1} attempts: {last_error}",
        )

    async def _config_request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make config API request with retry and exponential backoff."""
        client = await self._get_config_client()
        url = f"{self.CONFIG_URL}/{endpoint}"

        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data,
                )

                if response.status_code == 429 and attempt < _MAX_RETRIES:
                    retry_after = float(
                        response.headers.get("Retry-After", _BASE_DELAY * (2**attempt))
                    )
                    jitter = random.uniform(0, retry_after * 0.3)
                    delay = min(retry_after + jitter, _MAX_DELAY)
                    logger.warning(
                        "Segment config rate limited, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 500 and attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Segment config server error %d, retrying in %.1fs (attempt %d/%d)",
                        response.status_code,
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 400:
                    error_data = response.json() if response.content else {}
                    raise SegmentError(
                        message=error_data.get("message", f"API error: {response.status_code}"),
                        status_code=response.status_code,
                        error_code=error_data.get("code"),
                    )

                return response.json() if response.content else {}

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Segment config request timeout, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
            except httpx.ConnectError as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Segment config connection error, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
            except SegmentError:
                raise

        raise SegmentError(
            message=f"Request failed after {_MAX_RETRIES + 1} attempts: {last_error}",
        )

    async def _profiles_request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make profiles API request with retry and exponential backoff."""
        client = await self._get_profiles_client()
        url = f"{self.PROFILES_URL}/{endpoint}"

        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    params=params,
                )

                if response.status_code == 429 and attempt < _MAX_RETRIES:
                    retry_after = float(
                        response.headers.get("Retry-After", _BASE_DELAY * (2**attempt))
                    )
                    jitter = random.uniform(0, retry_after * 0.3)
                    delay = min(retry_after + jitter, _MAX_DELAY)
                    logger.warning(
                        "Segment profiles rate limited, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 500 and attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Segment profiles server error %d, retrying in %.1fs (attempt %d/%d)",
                        response.status_code,
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 400:
                    error_data = response.json() if response.content else {}
                    raise SegmentError(
                        message=error_data.get("message", f"API error: {response.status_code}"),
                        status_code=response.status_code,
                        error_code=error_data.get("code"),
                    )

                return response.json() if response.content else {}

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Segment profiles request timeout, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
            except httpx.ConnectError as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Segment profiles connection error, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
            except SegmentError:
                raise

        raise SegmentError(
            message=f"Request failed after {_MAX_RETRIES + 1} attempts: {last_error}",
        )

    # Tracking API

    async def track(self, event: TrackEvent) -> bool:
        """Send a track event."""
        await self._tracking_request("track", event.to_api())
        return True

    async def identify(self, identify: IdentifyCall) -> bool:
        """Send an identify call."""
        await self._tracking_request("identify", identify.to_api())
        return True

    async def page(self, page_event: PageEvent) -> bool:
        """Send a page event."""
        await self._tracking_request("page", page_event.to_api())
        return True

    async def group(self, group_call: GroupCall) -> bool:
        """Send a group call."""
        await self._tracking_request("group", group_call.to_api())
        return True

    async def batch(
        self,
        events: list[TrackEvent | IdentifyCall | PageEvent | GroupCall],
    ) -> bool:
        """Send a batch of events."""
        batch_data: dict[str, list[dict[str, Any]]] = {"batch": []}

        for event in events:
            event_data = event.to_api()

            if isinstance(event, TrackEvent):
                event_data["type"] = "track"
            elif isinstance(event, IdentifyCall):
                event_data["type"] = "identify"
            elif isinstance(event, PageEvent):
                event_data["type"] = "page"
            elif isinstance(event, GroupCall):
                event_data["type"] = "group"

            batch_data["batch"].append(event_data)

        await self._tracking_request("batch", batch_data)
        return True

    # Config API (requires access token)

    async def get_sources(self) -> list[Source]:
        """Get all sources in the workspace."""
        if not self.credentials.workspace_slug:
            raise SegmentError("Workspace slug required for Config API")

        data = await self._config_request(
            "GET",
            f"workspaces/{self.credentials.workspace_slug}/sources",
        )
        return [Source.from_api(s) for s in data.get("sources", [])]

    async def get_source(self, source_slug: str) -> Source:
        """Get a specific source."""
        if not self.credentials.workspace_slug:
            raise SegmentError("Workspace slug required for Config API")

        data = await self._config_request(
            "GET",
            f"workspaces/{self.credentials.workspace_slug}/sources/{source_slug}",
        )
        return Source.from_api(data.get("source", data))

    async def get_destinations(self, source_slug: str) -> list[Destination]:
        """Get destinations for a source."""
        if not self.credentials.workspace_slug:
            raise SegmentError("Workspace slug required for Config API")

        data = await self._config_request(
            "GET",
            f"workspaces/{self.credentials.workspace_slug}/sources/{source_slug}/destinations",
        )
        return [Destination.from_api(d) for d in data.get("destinations", [])]

    async def enable_destination(
        self,
        source_slug: str,
        destination_slug: str,
        enabled: bool = True,
    ) -> Destination:
        """Enable or disable a destination."""
        if not self.credentials.workspace_slug:
            raise SegmentError("Workspace slug required for Config API")

        data = await self._config_request(
            "PATCH",
            f"workspaces/{self.credentials.workspace_slug}/sources/{source_slug}/destinations/{destination_slug}",
            json_data={"destination": {"enabled": enabled}},
        )
        return Destination.from_api(data.get("destination", data))

    # Profiles API (requires access token and space)

    async def get_profile(
        self,
        space_id: str,
        user_id: str | None = None,
        anonymous_id: str | None = None,
    ) -> Profile:
        """Get a user profile by user ID or anonymous ID."""
        if not user_id and not anonymous_id:
            raise SegmentError("Either user_id or anonymous_id required")

        if user_id:
            endpoint = f"spaces/{space_id}/collections/users/profiles/user_id:{user_id}/traits"
        else:
            endpoint = (
                f"spaces/{space_id}/collections/users/profiles/anonymous_id:{anonymous_id}/traits"
            )

        data = await self._profiles_request("GET", endpoint)
        return Profile.from_api(data)

    async def get_audiences(self, space_id: str) -> list[Audience]:
        """Get all audiences in a space."""
        data = await self._config_request("GET", f"spaces/{space_id}/audiences")
        return [Audience.from_api(a) for a in data.get("audiences", [])]


def get_mock_source() -> Source:
    """Get mock source for testing."""
    return Source(
        id="src_123",
        name="Website",
        slug="website",
        source_type="javascript",
        workspace_id="ws_456",
        enabled=True,
        write_key="wk_abc123",
        created_at=datetime.now(),
    )


def get_mock_profile() -> Profile:
    """Get mock profile for testing."""
    return Profile(
        segment_id="seg_123",
        user_id="user_456",
        anonymous_id="anon_789",
        traits={
            "email": "test@example.com",
            "name": "Test User",
            "plan": "premium",
            "created_at": "2024-01-01T00:00:00Z",
        },
        created_at=datetime.now(),
    )
