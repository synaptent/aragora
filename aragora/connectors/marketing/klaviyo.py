"""
Klaviyo Connector.

Integration with Klaviyo API:
- List and segment management
- Profile (subscriber) management
- Campaign creation and analytics
- Flow (automation) management
- Event tracking
- SMS marketing
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


class ProfileSubscriptionStatus(Enum):
    """Klaviyo profile subscription status."""

    SUBSCRIBED = "SUBSCRIBED"
    UNSUBSCRIBED = "UNSUBSCRIBED"
    NEVER_SUBSCRIBED = "NEVER_SUBSCRIBED"


class CampaignStatus(Enum):
    """Klaviyo campaign status."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENT = "sent"
    CANCELLED = "cancelled"


class MessageChannel(Enum):
    """Klaviyo message channels."""

    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


class FlowStatus(Enum):
    """Klaviyo flow status."""

    DRAFT = "draft"
    MANUAL = "manual"
    LIVE = "live"


class SegmentType(Enum):
    """Klaviyo segment types."""

    STATIC = "static"
    DYNAMIC = "dynamic"


@dataclass
class KlaviyoCredentials:
    """Klaviyo API credentials."""

    api_key: str  # Private API key


@dataclass
class KlaviyoList:
    """Klaviyo list."""

    id: str
    name: str
    created: datetime | None = None
    updated: datetime | None = None
    profile_count: int | None = None
    opt_in_process: str = "single_opt_in"

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "KlaviyoList":
        """Create from Klaviyo API response."""
        attributes = data.get("attributes", {})
        return cls(
            id=data.get("id", ""),
            name=attributes.get("name", ""),
            created=(
                datetime.fromisoformat(attributes["created"].replace("Z", "+00:00"))
                if attributes.get("created")
                else None
            ),
            updated=(
                datetime.fromisoformat(attributes["updated"].replace("Z", "+00:00"))
                if attributes.get("updated")
                else None
            ),
            profile_count=attributes.get("profile_count"),
            opt_in_process=attributes.get("opt_in_process", "single_opt_in"),
        )


@dataclass
class Segment:
    """Klaviyo segment."""

    id: str
    name: str
    definition: dict[str, Any] = field(default_factory=dict)
    segment_type: SegmentType = SegmentType.DYNAMIC
    created: datetime | None = None
    updated: datetime | None = None
    profile_count: int | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Segment":
        """Create from Klaviyo API response."""
        attributes = data.get("attributes", {})
        return cls(
            id=data.get("id", ""),
            name=attributes.get("name", ""),
            definition=attributes.get("definition", {}),
            segment_type=SegmentType(attributes.get("segment_type", "dynamic")),
            created=(
                datetime.fromisoformat(attributes["created"].replace("Z", "+00:00"))
                if attributes.get("created")
                else None
            ),
            updated=(
                datetime.fromisoformat(attributes["updated"].replace("Z", "+00:00"))
                if attributes.get("updated")
                else None
            ),
            profile_count=attributes.get("profile_count"),
        )


@dataclass
class Profile:
    """Klaviyo profile (subscriber)."""

    id: str
    email: str | None = None
    phone_number: str | None = None
    external_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    organization: str | None = None
    title: str | None = None
    image: str | None = None
    location: dict[str, Any] = field(default_factory=dict)
    properties: dict[str, Any] = field(default_factory=dict)
    created: datetime | None = None
    updated: datetime | None = None
    subscriptions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Profile":
        """Create from Klaviyo API response."""
        attributes = data.get("attributes", {})
        location = attributes.get("location", {})
        return cls(
            id=data.get("id", ""),
            email=attributes.get("email"),
            phone_number=attributes.get("phone_number"),
            external_id=attributes.get("external_id"),
            first_name=attributes.get("first_name"),
            last_name=attributes.get("last_name"),
            organization=attributes.get("organization"),
            title=attributes.get("title"),
            image=attributes.get("image"),
            location=location if location else {},
            properties=attributes.get("properties", {}),
            created=(
                datetime.fromisoformat(attributes["created"].replace("Z", "+00:00"))
                if attributes.get("created")
                else None
            ),
            updated=(
                datetime.fromisoformat(attributes["updated"].replace("Z", "+00:00"))
                if attributes.get("updated")
                else None
            ),
            subscriptions=attributes.get("subscriptions", {}),
        )


@dataclass
class Campaign:
    """Klaviyo campaign."""

    id: str
    name: str
    status: CampaignStatus
    channel: MessageChannel
    audiences: dict[str, Any] = field(default_factory=dict)
    send_options: dict[str, Any] = field(default_factory=dict)
    tracking_options: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    scheduled_at: datetime | None = None
    sent_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Campaign":
        """Create from Klaviyo API response."""
        attributes = data.get("attributes", {})
        return cls(
            id=data.get("id", ""),
            name=attributes.get("name", ""),
            status=CampaignStatus(attributes.get("status", "draft")),
            channel=MessageChannel(attributes.get("channel", "email")),
            audiences=attributes.get("audiences", {}),
            send_options=attributes.get("send_options", {}),
            tracking_options=attributes.get("tracking_options", {}),
            created_at=(
                datetime.fromisoformat(attributes["created_at"].replace("Z", "+00:00"))
                if attributes.get("created_at")
                else None
            ),
            updated_at=(
                datetime.fromisoformat(attributes["updated_at"].replace("Z", "+00:00"))
                if attributes.get("updated_at")
                else None
            ),
            scheduled_at=(
                datetime.fromisoformat(attributes["scheduled_at"].replace("Z", "+00:00"))
                if attributes.get("scheduled_at")
                else None
            ),
            sent_at=(
                datetime.fromisoformat(attributes["sent_at"].replace("Z", "+00:00"))
                if attributes.get("sent_at")
                else None
            ),
        )


@dataclass
class CampaignMessage:
    """Klaviyo campaign message content."""

    id: str
    campaign_id: str
    channel: MessageChannel
    label: str = ""
    content: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "CampaignMessage":
        """Create from Klaviyo API response."""
        attributes = data.get("attributes", {})
        return cls(
            id=data.get("id", ""),
            campaign_id=attributes.get("campaign_id", ""),
            channel=MessageChannel(attributes.get("channel", "email")),
            label=attributes.get("label", ""),
            content=attributes.get("content", {}),
            created_at=(
                datetime.fromisoformat(attributes["created_at"].replace("Z", "+00:00"))
                if attributes.get("created_at")
                else None
            ),
            updated_at=(
                datetime.fromisoformat(attributes["updated_at"].replace("Z", "+00:00"))
                if attributes.get("updated_at")
                else None
            ),
        )


@dataclass
class Flow:
    """Klaviyo flow (automation)."""

    id: str
    name: str
    status: FlowStatus
    trigger_type: str = ""
    created: datetime | None = None
    updated: datetime | None = None
    archived: bool = False

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Flow":
        """Create from Klaviyo API response."""
        attributes = data.get("attributes", {})
        return cls(
            id=data.get("id", ""),
            name=attributes.get("name", ""),
            status=FlowStatus(attributes.get("status", "draft")),
            trigger_type=attributes.get("trigger_type", ""),
            created=(
                datetime.fromisoformat(attributes["created"].replace("Z", "+00:00"))
                if attributes.get("created")
                else None
            ),
            updated=(
                datetime.fromisoformat(attributes["updated"].replace("Z", "+00:00"))
                if attributes.get("updated")
                else None
            ),
            archived=attributes.get("archived", False),
        )


@dataclass
class FlowAction:
    """Klaviyo flow action (step in a flow)."""

    id: str
    flow_id: str
    action_type: str
    status: str = "draft"
    settings: dict[str, Any] = field(default_factory=dict)
    created: datetime | None = None
    updated: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "FlowAction":
        """Create from Klaviyo API response."""
        attributes = data.get("attributes", {})
        return cls(
            id=data.get("id", ""),
            flow_id=attributes.get("flow_id", ""),
            action_type=attributes.get("action_type", ""),
            status=attributes.get("status", "draft"),
            settings=attributes.get("settings", {}),
            created=(
                datetime.fromisoformat(attributes["created"].replace("Z", "+00:00"))
                if attributes.get("created")
                else None
            ),
            updated=(
                datetime.fromisoformat(attributes["updated"].replace("Z", "+00:00"))
                if attributes.get("updated")
                else None
            ),
        )


@dataclass
class Metric:
    """Klaviyo metric (event type)."""

    id: str
    name: str
    integration: dict[str, Any] = field(default_factory=dict)
    created: datetime | None = None
    updated: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Metric":
        """Create from Klaviyo API response."""
        attributes = data.get("attributes", {})
        return cls(
            id=data.get("id", ""),
            name=attributes.get("name", ""),
            integration=attributes.get("integration", {}),
            created=(
                datetime.fromisoformat(attributes["created"].replace("Z", "+00:00"))
                if attributes.get("created")
                else None
            ),
            updated=(
                datetime.fromisoformat(attributes["updated"].replace("Z", "+00:00"))
                if attributes.get("updated")
                else None
            ),
        )


@dataclass
class Event:
    """Klaviyo event."""

    id: str
    metric_id: str
    profile_id: str
    timestamp: datetime
    event_properties: dict[str, Any] = field(default_factory=dict)
    datetime_str: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Event":
        """Create from Klaviyo API response."""
        attributes = data.get("attributes", {})
        relationships = data.get("relationships", {})
        return cls(
            id=data.get("id", ""),
            metric_id=relationships.get("metric", {}).get("data", {}).get("id", ""),
            profile_id=relationships.get("profile", {}).get("data", {}).get("id", ""),
            timestamp=(
                datetime.fromisoformat(attributes["timestamp"].replace("Z", "+00:00"))
                if attributes.get("timestamp")
                else datetime.now()
            ),
            event_properties=attributes.get("event_properties", {}),
            datetime_str=attributes.get("datetime", ""),
        )


@dataclass
class Template:
    """Klaviyo email template."""

    id: str
    name: str
    editor_type: str = "CODE"
    html: str = ""
    text: str = ""
    created: datetime | None = None
    updated: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Template":
        """Create from Klaviyo API response."""
        attributes = data.get("attributes", {})
        return cls(
            id=data.get("id", ""),
            name=attributes.get("name", ""),
            editor_type=attributes.get("editor_type", "CODE"),
            html=attributes.get("html", ""),
            text=attributes.get("text", ""),
            created=(
                datetime.fromisoformat(attributes["created"].replace("Z", "+00:00"))
                if attributes.get("created")
                else None
            ),
            updated=(
                datetime.fromisoformat(attributes["updated"].replace("Z", "+00:00"))
                if attributes.get("updated")
                else None
            ),
        )


@dataclass
class CampaignRecipientEstimation:
    """Klaviyo campaign recipient estimation."""

    id: str
    estimated_recipient_count: int = 0

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "CampaignRecipientEstimation":
        """Create from Klaviyo API response."""
        attributes = data.get("attributes", {})
        return cls(
            id=data.get("id", ""),
            estimated_recipient_count=attributes.get("estimated_recipient_count", 0),
        )


class KlaviyoError(Exception):
    """Klaviyo API error."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_id: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_id = error_id


class KlaviyoConnector:
    """Klaviyo API connector."""

    BASE_URL = "https://a.klaviyo.com/api"
    API_REVISION = "2024-10-15"

    def __init__(self, credentials: KlaviyoCredentials):
        """Initialize with credentials."""
        self.credentials = credentials
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Klaviyo-API-Key {self.credentials.api_key}",
                    "revision": self.API_REVISION,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make API request with retry and exponential backoff."""
        client = await self._get_client()
        url = f"{self.BASE_URL}/{endpoint}"

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
                        "Klaviyo rate limited, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 500 and attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Klaviyo server error %d, retrying in %.1fs (attempt %d/%d)",
                        response.status_code,
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 400:
                    error_data = response.json() if response.content else {}
                    errors = error_data.get("errors", [{}])
                    raise KlaviyoError(
                        message=errors[0].get("detail", f"API error: {response.status_code}"),
                        status_code=response.status_code,
                        error_id=errors[0].get("id"),
                    )

                return response.json() if response.content else {}

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Klaviyo request timeout, retrying in %.1fs (attempt %d/%d)",
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
                        "Klaviyo connection error, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
            except KlaviyoError:
                raise

        raise KlaviyoError(
            message=f"Request failed after {_MAX_RETRIES + 1} attempts: {last_error}",
        )

    async def _paginated_request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:
        """Make paginated API request."""
        results = []
        page_cursor = None
        pages = 0

        while pages < max_pages:
            request_params = params.copy() if params else {}
            if page_cursor:
                request_params["page[cursor]"] = page_cursor

            data = await self._request("GET", endpoint, params=request_params)
            results.extend(data.get("data", []))

            links = data.get("links", {})
            next_link = links.get("next")
            if not next_link:
                break

            # Extract cursor from next link
            import urllib.parse

            parsed = urllib.parse.urlparse(next_link)
            query_params = urllib.parse.parse_qs(parsed.query)
            page_cursor = query_params.get("page[cursor]", [None])[0]
            if not page_cursor:
                break

            pages += 1

        return results

    # List Operations

    async def get_lists(self) -> list[KlaviyoList]:
        """Get all lists."""
        data = await self._paginated_request("lists")
        return [KlaviyoList.from_api(item) for item in data]

    async def get_list(self, list_id: str) -> KlaviyoList:
        """Get a specific list by ID."""
        data = await self._request("GET", f"lists/{list_id}")
        return KlaviyoList.from_api(data.get("data", {}))

    async def create_list(self, name: str) -> KlaviyoList:
        """Create a new list."""
        json_data = {
            "data": {
                "type": "list",
                "attributes": {"name": name},
            }
        }

        data = await self._request("POST", "lists", json_data=json_data)
        return KlaviyoList.from_api(data.get("data", {}))

    async def add_profiles_to_list(
        self,
        list_id: str,
        profile_ids: list[str],
    ) -> None:
        """Add profiles to a list."""
        json_data = {"data": [{"type": "profile", "id": pid} for pid in profile_ids]}
        await self._request("POST", f"lists/{list_id}/relationships/profiles", json_data=json_data)

    async def remove_profiles_from_list(
        self,
        list_id: str,
        profile_ids: list[str],
    ) -> None:
        """Remove profiles from a list."""
        json_data = {"data": [{"type": "profile", "id": pid} for pid in profile_ids]}
        await self._request(
            "DELETE", f"lists/{list_id}/relationships/profiles", json_data=json_data
        )

    # Segment Operations

    async def get_segments(self) -> list[Segment]:
        """Get all segments."""
        data = await self._paginated_request("segments")
        return [Segment.from_api(item) for item in data]

    async def get_segment(self, segment_id: str) -> Segment:
        """Get a specific segment by ID."""
        data = await self._request("GET", f"segments/{segment_id}")
        return Segment.from_api(data.get("data", {}))

    async def get_segment_profiles(
        self,
        segment_id: str,
        page_size: int = 20,
    ) -> list[Profile]:
        """Get profiles in a segment."""
        params = {"page[size]": page_size}
        data = await self._paginated_request(f"segments/{segment_id}/profiles", params=params)
        return [Profile.from_api(item) for item in data]

    # Profile Operations

    async def get_profiles(
        self,
        page_size: int = 20,
        filter_query: str | None = None,
    ) -> list[Profile]:
        """Get profiles."""
        params: dict[str, Any] = {"page[size]": page_size}
        if filter_query:
            params["filter"] = filter_query

        data = await self._paginated_request("profiles", params=params)
        return [Profile.from_api(item) for item in data]

    async def get_profile(self, profile_id: str) -> Profile:
        """Get a specific profile by ID."""
        data = await self._request("GET", f"profiles/{profile_id}")
        return Profile.from_api(data.get("data", {}))

    async def get_profile_by_email(self, email: str) -> Profile | None:
        """Get a profile by email address."""
        params = {"filter": f'equals(email,"{email}")'}
        data = await self._request("GET", "profiles", params=params)
        profiles = data.get("data", [])
        return Profile.from_api(profiles[0]) if profiles else None

    async def create_profile(
        self,
        email: str | None = None,
        phone_number: str | None = None,
        external_id: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> Profile:
        """Create a new profile."""
        attributes: dict[str, Any] = {}

        if email:
            attributes["email"] = email
        if phone_number:
            attributes["phone_number"] = phone_number
        if external_id:
            attributes["external_id"] = external_id
        if first_name:
            attributes["first_name"] = first_name
        if last_name:
            attributes["last_name"] = last_name
        if properties:
            attributes["properties"] = properties

        json_data = {
            "data": {
                "type": "profile",
                "attributes": attributes,
            }
        }

        data = await self._request("POST", "profiles", json_data=json_data)
        return Profile.from_api(data.get("data", {}))

    async def update_profile(
        self,
        profile_id: str,
        email: str | None = None,
        phone_number: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> Profile:
        """Update a profile."""
        attributes: dict[str, Any] = {}

        if email:
            attributes["email"] = email
        if phone_number:
            attributes["phone_number"] = phone_number
        if first_name:
            attributes["first_name"] = first_name
        if last_name:
            attributes["last_name"] = last_name
        if properties:
            attributes["properties"] = properties

        json_data = {
            "data": {
                "type": "profile",
                "id": profile_id,
                "attributes": attributes,
            }
        }

        data = await self._request("PATCH", f"profiles/{profile_id}", json_data=json_data)
        return Profile.from_api(data.get("data", {}))

    async def subscribe_profile(
        self,
        list_id: str,
        email: str | None = None,
        phone_number: str | None = None,
        channels: list[str] | None = None,
    ) -> None:
        """Subscribe a profile to email/SMS."""
        if not channels:
            channels = ["email"] if email else ["sms"]

        subscriptions = []
        if "email" in channels and email:
            subscriptions.append(
                {
                    "type": "profile-subscription-bulk-create-job",
                    "attributes": {
                        "profiles": {
                            "data": [
                                {
                                    "type": "profile",
                                    "attributes": {"email": email},
                                }
                            ]
                        },
                        "list_id": list_id,
                    },
                }
            )

        for sub in subscriptions:
            await self._request(
                "POST", "profile-subscription-bulk-create-jobs", json_data={"data": sub}
            )

    # Campaign Operations

    async def get_campaigns(
        self,
        channel: MessageChannel | None = None,
    ) -> list[Campaign]:
        """Get campaigns."""
        params = {}
        if channel:
            params["filter"] = f'equals(messages.channel,"{channel.value}")'

        data = await self._paginated_request("campaigns", params=params)
        return [Campaign.from_api(item) for item in data]

    async def get_campaign(self, campaign_id: str) -> Campaign:
        """Get a specific campaign by ID."""
        data = await self._request("GET", f"campaigns/{campaign_id}")
        return Campaign.from_api(data.get("data", {}))

    async def create_campaign(
        self,
        name: str,
        channel: MessageChannel = MessageChannel.EMAIL,
        list_ids: list[str] | None = None,
        segment_ids: list[str] | None = None,
    ) -> Campaign:
        """Create a new campaign."""
        audiences: dict[str, Any] = {"included": [], "excluded": []}

        if list_ids:
            audiences["included"].extend([{"type": "list", "id": lid} for lid in list_ids])
        if segment_ids:
            audiences["included"].extend([{"type": "segment", "id": sid} for sid in segment_ids])

        json_data = {
            "data": {
                "type": "campaign",
                "attributes": {
                    "name": name,
                    "channel": channel.value,
                    "audiences": audiences,
                },
            }
        }

        data = await self._request("POST", "campaigns", json_data=json_data)
        return Campaign.from_api(data.get("data", {}))

    async def send_campaign(self, campaign_id: str) -> None:
        """Send a campaign immediately."""
        json_data = {
            "data": {
                "type": "campaign-send-job",
                "id": campaign_id,
            }
        }
        await self._request("POST", "campaign-send-jobs", json_data=json_data)

    async def schedule_campaign(
        self,
        campaign_id: str,
        send_time: datetime,
    ) -> None:
        """Schedule a campaign."""
        json_data = {
            "data": {
                "type": "campaign",
                "id": campaign_id,
                "attributes": {
                    "send_options": {
                        "datetime": send_time.isoformat(),
                    },
                },
            }
        }
        await self._request("PATCH", f"campaigns/{campaign_id}", json_data=json_data)

    # Flow Operations

    async def get_flows(self) -> list[Flow]:
        """Get all flows."""
        data = await self._paginated_request("flows")
        return [Flow.from_api(item) for item in data]

    async def get_flow(self, flow_id: str) -> Flow:
        """Get a specific flow by ID."""
        data = await self._request("GET", f"flows/{flow_id}")
        return Flow.from_api(data.get("data", {}))

    async def update_flow_status(
        self,
        flow_id: str,
        status: FlowStatus,
    ) -> Flow:
        """Update flow status."""
        json_data = {
            "data": {
                "type": "flow",
                "id": flow_id,
                "attributes": {"status": status.value},
            }
        }
        data = await self._request("PATCH", f"flows/{flow_id}", json_data=json_data)
        return Flow.from_api(data.get("data", {}))

    async def get_flow_actions(self, flow_id: str) -> list[FlowAction]:
        """Get actions in a flow."""
        data = await self._paginated_request(f"flows/{flow_id}/flow-actions")
        return [FlowAction.from_api(item) for item in data]

    # Event/Metric Operations

    async def get_metrics(self) -> list[Metric]:
        """Get all metrics (event types)."""
        data = await self._paginated_request("metrics")
        return [Metric.from_api(item) for item in data]

    async def get_events(
        self,
        profile_id: str | None = None,
        metric_id: str | None = None,
        page_size: int = 50,
    ) -> list[Event]:
        """Get events."""
        params: dict[str, Any] = {"page[size]": page_size}

        filters = []
        if profile_id:
            filters.append(f'equals(profile_id,"{profile_id}")')
        if metric_id:
            filters.append(f'equals(metric_id,"{metric_id}")')
        if filters:
            params["filter"] = ",".join(filters)

        data = await self._paginated_request("events", params=params)
        return [Event.from_api(item) for item in data]

    async def create_event(
        self,
        event_name: str,
        profile_email: str | None = None,
        profile_phone: str | None = None,
        profile_id: str | None = None,
        properties: dict[str, Any] | None = None,
        time: datetime | None = None,
        value: float | None = None,
        unique_id: str | None = None,
    ) -> None:
        """Create an event (track)."""
        profile_data: dict[str, Any] = {}
        if profile_email:
            profile_data["$email"] = profile_email
        if profile_phone:
            profile_data["$phone_number"] = profile_phone
        if profile_id:
            profile_data["$id"] = profile_id

        attributes: dict[str, Any] = {
            "metric": {"data": {"type": "metric", "attributes": {"name": event_name}}},
            "profile": {"data": {"type": "profile", "attributes": profile_data}},
        }

        if properties:
            attributes["properties"] = properties
        if time:
            attributes["time"] = time.isoformat()
        if value is not None:
            attributes["value"] = value
        if unique_id:
            attributes["unique_id"] = unique_id

        json_data = {
            "data": {
                "type": "event",
                "attributes": attributes,
            }
        }

        await self._request("POST", "events", json_data=json_data)

    # Template Operations

    async def get_templates(self) -> list[Template]:
        """Get all templates."""
        data = await self._paginated_request("templates")
        return [Template.from_api(item) for item in data]

    async def get_template(self, template_id: str) -> Template:
        """Get a specific template by ID."""
        data = await self._request("GET", f"templates/{template_id}")
        return Template.from_api(data.get("data", {}))

    async def create_template(
        self,
        name: str,
        html: str,
        text: str = "",
    ) -> Template:
        """Create a new template."""
        json_data = {
            "data": {
                "type": "template",
                "attributes": {
                    "name": name,
                    "editor_type": "CODE",
                    "html": html,
                    "text": text,
                },
            }
        }

        data = await self._request("POST", "templates", json_data=json_data)
        return Template.from_api(data.get("data", {}))


def get_mock_list() -> KlaviyoList:
    """Get mock list for testing."""
    return KlaviyoList(
        id="abc123",
        name="Newsletter Subscribers",
        created=datetime.now(),
        profile_count=15000,
        opt_in_process="double_opt_in",
    )


def get_mock_profile() -> Profile:
    """Get mock profile for testing."""
    return Profile(
        id="prof_123",
        email="test@example.com",
        first_name="Test",
        last_name="User",
        phone_number="+15551234567",
        properties={
            "plan": "premium",
            "lifetime_value": 500.0,
        },
        created=datetime.now(),
        subscriptions={
            "email": {"marketing": {"consent": "SUBSCRIBED"}},
            "sms": {"marketing": {"consent": "SUBSCRIBED"}},
        },
    )


def get_mock_campaign() -> Campaign:
    """Get mock campaign for testing."""
    return Campaign(
        id="camp_123",
        name="Summer Sale Announcement",
        status=CampaignStatus.SENT,
        channel=MessageChannel.EMAIL,
        audiences={
            "included": [{"type": "list", "id": "abc123"}],
            "excluded": [],
        },
        created_at=datetime.now(),
        sent_at=datetime.now(),
    )
