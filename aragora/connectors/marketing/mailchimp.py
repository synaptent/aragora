"""
Mailchimp Connector.

Integration with Mailchimp API:
- Audience/list management
- Campaign creation and sending
- Subscriber management
- Email templates
- Automation workflows
- Reporting and analytics
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


class MemberStatus(Enum):
    """Mailchimp subscriber status."""

    SUBSCRIBED = "subscribed"
    UNSUBSCRIBED = "unsubscribed"
    CLEANED = "cleaned"
    PENDING = "pending"
    TRANSACTIONAL = "transactional"


class CampaignStatus(Enum):
    """Mailchimp campaign status."""

    SAVE = "save"
    PAUSED = "paused"
    SCHEDULE = "schedule"
    SENDING = "sending"
    SENT = "sent"


class CampaignType(Enum):
    """Mailchimp campaign types."""

    REGULAR = "regular"
    PLAINTEXT = "plaintext"
    ABSPLIT = "absplit"
    RSS = "rss"
    VARIATE = "variate"


class AutomationStatus(Enum):
    """Mailchimp automation status."""

    SAVE = "save"
    PAUSED = "paused"
    SENDING = "sending"


@dataclass
class MailchimpCredentials:
    """Mailchimp API credentials."""

    api_key: str
    server_prefix: str  # e.g., "us1", "us2", etc.


@dataclass
class AudienceStats:
    """Mailchimp audience statistics."""

    member_count: int = 0
    unsubscribe_count: int = 0
    cleaned_count: int = 0
    member_count_since_send: int = 0
    unsubscribe_count_since_send: int = 0
    cleaned_count_since_send: int = 0
    campaign_count: int = 0
    campaign_last_sent: datetime | None = None
    merge_field_count: int = 0
    avg_sub_rate: float = 0.0
    avg_unsub_rate: float = 0.0
    target_sub_rate: float = 0.0
    open_rate: float = 0.0
    click_rate: float = 0.0
    last_sub_date: datetime | None = None
    last_unsub_date: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "AudienceStats":
        """Create from Mailchimp API response."""
        return cls(
            member_count=data.get("member_count", 0),
            unsubscribe_count=data.get("unsubscribe_count", 0),
            cleaned_count=data.get("cleaned_count", 0),
            member_count_since_send=data.get("member_count_since_send", 0),
            unsubscribe_count_since_send=data.get("unsubscribe_count_since_send", 0),
            cleaned_count_since_send=data.get("cleaned_count_since_send", 0),
            campaign_count=data.get("campaign_count", 0),
            campaign_last_sent=(
                datetime.fromisoformat(data["campaign_last_sent"].replace("Z", "+00:00"))
                if data.get("campaign_last_sent")
                else None
            ),
            merge_field_count=data.get("merge_field_count", 0),
            avg_sub_rate=data.get("avg_sub_rate", 0.0),
            avg_unsub_rate=data.get("avg_unsub_rate", 0.0),
            target_sub_rate=data.get("target_sub_rate", 0.0),
            open_rate=data.get("open_rate", 0.0),
            click_rate=data.get("click_rate", 0.0),
            last_sub_date=(
                datetime.fromisoformat(data["last_sub_date"].replace("Z", "+00:00"))
                if data.get("last_sub_date")
                else None
            ),
            last_unsub_date=(
                datetime.fromisoformat(data["last_unsub_date"].replace("Z", "+00:00"))
                if data.get("last_unsub_date")
                else None
            ),
        )


@dataclass
class Audience:
    """Mailchimp audience (list)."""

    id: str
    name: str
    contact: dict[str, Any] = field(default_factory=dict)
    permission_reminder: str = ""
    campaign_defaults: dict[str, Any] = field(default_factory=dict)
    notify_on_subscribe: str = ""
    notify_on_unsubscribe: str = ""
    date_created: datetime | None = None
    stats: AudienceStats | None = None
    double_optin: bool = False

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Audience":
        """Create from Mailchimp API response."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            contact=data.get("contact", {}),
            permission_reminder=data.get("permission_reminder", ""),
            campaign_defaults=data.get("campaign_defaults", {}),
            notify_on_subscribe=data.get("notify_on_subscribe", ""),
            notify_on_unsubscribe=data.get("notify_on_unsubscribe", ""),
            date_created=(
                datetime.fromisoformat(data["date_created"].replace("Z", "+00:00"))
                if data.get("date_created")
                else None
            ),
            stats=AudienceStats.from_api(data["stats"]) if data.get("stats") else None,
            double_optin=data.get("double_optin", False),
        )


@dataclass
class Member:
    """Mailchimp list member (subscriber)."""

    id: str
    email_address: str
    status: MemberStatus
    email_type: str = "html"
    merge_fields: dict[str, Any] = field(default_factory=dict)
    interests: dict[str, bool] = field(default_factory=dict)
    language: str = ""
    vip: bool = False
    location: dict[str, Any] = field(default_factory=dict)
    marketing_permissions: list[dict[str, Any]] = field(default_factory=list)
    ip_signup: str = ""
    timestamp_signup: datetime | None = None
    ip_opt: str = ""
    timestamp_opt: datetime | None = None
    member_rating: int = 0
    last_changed: datetime | None = None
    email_client: str = ""
    tags_count: int = 0
    tags: list[dict[str, Any]] = field(default_factory=list)
    list_id: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Member":
        """Create from Mailchimp API response."""
        return cls(
            id=data.get("id", ""),
            email_address=data.get("email_address", ""),
            status=MemberStatus(data.get("status", "subscribed")),
            email_type=data.get("email_type", "html"),
            merge_fields=data.get("merge_fields", {}),
            interests=data.get("interests", {}),
            language=data.get("language", ""),
            vip=data.get("vip", False),
            location=data.get("location", {}),
            marketing_permissions=data.get("marketing_permissions", []),
            ip_signup=data.get("ip_signup", ""),
            timestamp_signup=(
                datetime.fromisoformat(data["timestamp_signup"].replace("Z", "+00:00"))
                if data.get("timestamp_signup") and data["timestamp_signup"]
                else None
            ),
            ip_opt=data.get("ip_opt", ""),
            timestamp_opt=(
                datetime.fromisoformat(data["timestamp_opt"].replace("Z", "+00:00"))
                if data.get("timestamp_opt") and data["timestamp_opt"]
                else None
            ),
            member_rating=data.get("member_rating", 0),
            last_changed=(
                datetime.fromisoformat(data["last_changed"].replace("Z", "+00:00"))
                if data.get("last_changed")
                else None
            ),
            email_client=data.get("email_client", ""),
            tags_count=data.get("tags_count", 0),
            tags=data.get("tags", []),
            list_id=data.get("list_id", ""),
        )


@dataclass
class Campaign:
    """Mailchimp email campaign."""

    id: str
    web_id: int
    type: CampaignType
    create_time: datetime | None = None
    archive_url: str = ""
    long_archive_url: str = ""
    status: CampaignStatus = CampaignStatus.SAVE
    emails_sent: int = 0
    send_time: datetime | None = None
    content_type: str = ""
    recipients: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    tracking: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Campaign":
        """Create from Mailchimp API response."""
        return cls(
            id=data.get("id", ""),
            web_id=data.get("web_id", 0),
            type=CampaignType(data.get("type", "regular")),
            create_time=(
                datetime.fromisoformat(data["create_time"].replace("Z", "+00:00"))
                if data.get("create_time")
                else None
            ),
            archive_url=data.get("archive_url", ""),
            long_archive_url=data.get("long_archive_url", ""),
            status=CampaignStatus(data.get("status", "save")),
            emails_sent=data.get("emails_sent", 0),
            send_time=(
                datetime.fromisoformat(data["send_time"].replace("Z", "+00:00"))
                if data.get("send_time")
                else None
            ),
            content_type=data.get("content_type", ""),
            recipients=data.get("recipients", {}),
            settings=data.get("settings", {}),
            tracking=data.get("tracking", {}),
        )


@dataclass
class CampaignReport:
    """Mailchimp campaign report."""

    id: str
    campaign_title: str
    list_id: str
    list_name: str
    subject_line: str
    emails_sent: int = 0
    abuse_reports: int = 0
    unsubscribed: int = 0
    send_time: datetime | None = None
    opens: dict[str, Any] = field(default_factory=dict)
    clicks: dict[str, Any] = field(default_factory=dict)
    bounces: dict[str, Any] = field(default_factory=dict)
    forwards: dict[str, Any] = field(default_factory=dict)
    industry_stats: dict[str, Any] = field(default_factory=dict)

    @property
    def open_rate(self) -> float:
        """Calculate open rate."""
        if self.emails_sent == 0:
            return 0.0
        return (self.opens.get("opens_total", 0) / self.emails_sent) * 100

    @property
    def click_rate(self) -> float:
        """Calculate click rate."""
        if self.emails_sent == 0:
            return 0.0
        return (self.clicks.get("clicks_total", 0) / self.emails_sent) * 100

    @property
    def bounce_rate(self) -> float:
        """Calculate bounce rate."""
        if self.emails_sent == 0:
            return 0.0
        total_bounces = self.bounces.get("hard_bounces", 0) + self.bounces.get("soft_bounces", 0)
        return (total_bounces / self.emails_sent) * 100

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "CampaignReport":
        """Create from Mailchimp API response."""
        return cls(
            id=data.get("id", ""),
            campaign_title=data.get("campaign_title", ""),
            list_id=data.get("list_id", ""),
            list_name=data.get("list_name", ""),
            subject_line=data.get("subject_line", ""),
            emails_sent=data.get("emails_sent", 0),
            abuse_reports=data.get("abuse_reports", 0),
            unsubscribed=data.get("unsubscribed", 0),
            send_time=(
                datetime.fromisoformat(data["send_time"].replace("Z", "+00:00"))
                if data.get("send_time")
                else None
            ),
            opens=data.get("opens", {}),
            clicks=data.get("clicks", {}),
            bounces=data.get("bounces", {}),
            forwards=data.get("forwards", {}),
            industry_stats=data.get("industry_stats", {}),
        )


@dataclass
class Template:
    """Mailchimp email template."""

    id: int
    name: str
    type: str
    category: str = ""
    created_by: str = ""
    date_created: datetime | None = None
    date_edited: datetime | None = None
    active: bool = True
    folder_id: str = ""
    thumbnail: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Template":
        """Create from Mailchimp API response."""
        return cls(
            id=data.get("id", 0),
            name=data.get("name", ""),
            type=data.get("type", ""),
            category=data.get("category", ""),
            created_by=data.get("created_by", ""),
            date_created=(
                datetime.fromisoformat(data["date_created"].replace("Z", "+00:00"))
                if data.get("date_created")
                else None
            ),
            date_edited=(
                datetime.fromisoformat(data["date_edited"].replace("Z", "+00:00"))
                if data.get("date_edited")
                else None
            ),
            active=data.get("active", True),
            folder_id=data.get("folder_id", ""),
            thumbnail=data.get("thumbnail", ""),
        )


@dataclass
class Automation:
    """Mailchimp automation workflow."""

    id: str
    name: str
    status: AutomationStatus
    emails_sent: int = 0
    recipients: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    tracking: dict[str, Any] = field(default_factory=dict)
    trigger_settings: dict[str, Any] = field(default_factory=dict)
    create_time: datetime | None = None
    start_time: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Automation":
        """Create from Mailchimp API response."""
        return cls(
            id=data.get("id", ""),
            name=data.get("settings", {}).get("title", ""),
            status=AutomationStatus(data.get("status", "save")),
            emails_sent=data.get("emails_sent", 0),
            recipients=data.get("recipients", {}),
            settings=data.get("settings", {}),
            tracking=data.get("tracking", {}),
            trigger_settings=data.get("trigger_settings", {}),
            create_time=(
                datetime.fromisoformat(data["create_time"].replace("Z", "+00:00"))
                if data.get("create_time")
                else None
            ),
            start_time=(
                datetime.fromisoformat(data["start_time"].replace("Z", "+00:00"))
                if data.get("start_time")
                else None
            ),
        )


class MailchimpError(Exception):
    """Mailchimp API error."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_type: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


class MailchimpConnector:
    """Mailchimp API connector."""

    def __init__(self, credentials: MailchimpCredentials):
        """Initialize with credentials."""
        self.credentials = credentials
        self.base_url = f"https://{credentials.server_prefix}.api.mailchimp.com/3.0"
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                auth=("anystring", self.credentials.api_key),
                headers={"Content-Type": "application/json"},
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
        url = f"{self.base_url}/{endpoint}"

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
                        "Mailchimp rate limited, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 500 and attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Mailchimp server error %d, retrying in %.1fs (attempt %d/%d)",
                        response.status_code,
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 400:
                    error_data = response.json() if response.content else {}
                    raise MailchimpError(
                        message=error_data.get("detail", f"API error: {response.status_code}"),
                        status_code=response.status_code,
                        error_type=error_data.get("type"),
                    )

                return response.json() if response.content else {}

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Mailchimp request timeout, retrying in %.1fs (attempt %d/%d)",
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
                        "Mailchimp connection error, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
            except MailchimpError:
                raise

        raise MailchimpError(
            message=f"Request failed after {_MAX_RETRIES + 1} attempts: {last_error}",
        )

    # Audience Operations

    async def get_audiences(
        self,
        count: int = 10,
        offset: int = 0,
    ) -> list[Audience]:
        """Get all audiences (lists)."""
        params = {"count": count, "offset": offset}
        data = await self._request("GET", "lists", params=params)
        return [Audience.from_api(a) for a in data.get("lists", [])]

    async def get_audience(self, list_id: str) -> Audience:
        """Get a specific audience by ID."""
        data = await self._request("GET", f"lists/{list_id}")
        return Audience.from_api(data)

    async def create_audience(
        self,
        name: str,
        contact: dict[str, Any],
        permission_reminder: str,
        campaign_defaults: dict[str, Any],
    ) -> Audience:
        """Create a new audience."""
        json_data = {
            "name": name,
            "contact": contact,
            "permission_reminder": permission_reminder,
            "campaign_defaults": campaign_defaults,
        }

        data = await self._request("POST", "lists", json_data=json_data)
        return Audience.from_api(data)

    # Member Operations

    async def get_members(
        self,
        list_id: str,
        status: MemberStatus | None = None,
        count: int = 10,
        offset: int = 0,
    ) -> list[Member]:
        """Get members of an audience."""
        params: dict[str, Any] = {"count": count, "offset": offset}
        if status:
            params["status"] = status.value

        data = await self._request("GET", f"lists/{list_id}/members", params=params)
        return [Member.from_api(m) for m in data.get("members", [])]

    async def get_member(self, list_id: str, subscriber_hash: str) -> Member:
        """Get a specific member."""
        data = await self._request("GET", f"lists/{list_id}/members/{subscriber_hash}")
        return Member.from_api(data)

    async def add_member(
        self,
        list_id: str,
        email_address: str,
        status: MemberStatus = MemberStatus.SUBSCRIBED,
        merge_fields: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> Member:
        """Add a new member to an audience."""
        json_data: dict[str, Any] = {
            "email_address": email_address,
            "status": status.value,
        }

        if merge_fields:
            json_data["merge_fields"] = merge_fields
        if tags:
            json_data["tags"] = tags

        data = await self._request("POST", f"lists/{list_id}/members", json_data=json_data)
        return Member.from_api(data)

    async def update_member(
        self,
        list_id: str,
        subscriber_hash: str,
        status: MemberStatus | None = None,
        merge_fields: dict[str, Any] | None = None,
    ) -> Member:
        """Update a member."""
        json_data: dict[str, Any] = {}

        if status:
            json_data["status"] = status.value
        if merge_fields:
            json_data["merge_fields"] = merge_fields

        data = await self._request(
            "PATCH", f"lists/{list_id}/members/{subscriber_hash}", json_data=json_data
        )
        return Member.from_api(data)

    async def add_member_tags(
        self,
        list_id: str,
        subscriber_hash: str,
        tags: list[str],
    ) -> None:
        """Add tags to a member."""
        json_data = {"tags": [{"name": tag, "status": "active"} for tag in tags]}
        await self._request(
            "POST", f"lists/{list_id}/members/{subscriber_hash}/tags", json_data=json_data
        )

    # Campaign Operations

    async def get_campaigns(
        self,
        status: CampaignStatus | None = None,
        list_id: str | None = None,
        count: int = 10,
        offset: int = 0,
    ) -> list[Campaign]:
        """Get campaigns."""
        params: dict[str, Any] = {"count": count, "offset": offset}
        if status:
            params["status"] = status.value
        if list_id:
            params["list_id"] = list_id

        data = await self._request("GET", "campaigns", params=params)
        return [Campaign.from_api(c) for c in data.get("campaigns", [])]

    async def get_campaign(self, campaign_id: str) -> Campaign:
        """Get a specific campaign."""
        data = await self._request("GET", f"campaigns/{campaign_id}")
        return Campaign.from_api(data)

    async def create_campaign(
        self,
        campaign_type: CampaignType,
        list_id: str,
        subject_line: str,
        from_name: str,
        reply_to: str,
        title: str | None = None,
    ) -> Campaign:
        """Create a new campaign."""
        settings: dict[str, str] = {
            "subject_line": subject_line,
            "from_name": from_name,
            "reply_to": reply_to,
        }
        if title:
            settings["title"] = title

        json_data = {
            "type": campaign_type.value,
            "recipients": {"list_id": list_id},
            "settings": settings,
        }

        data = await self._request("POST", "campaigns", json_data=json_data)
        return Campaign.from_api(data)

    async def set_campaign_content(
        self,
        campaign_id: str,
        html: str | None = None,
        plain_text: str | None = None,
        template_id: int | None = None,
    ) -> None:
        """Set campaign content."""
        json_data: dict[str, Any] = {}

        if html:
            json_data["html"] = html
        if plain_text:
            json_data["plain_text"] = plain_text
        if template_id:
            json_data["template"] = {"id": template_id}

        await self._request("PUT", f"campaigns/{campaign_id}/content", json_data=json_data)

    async def send_campaign(self, campaign_id: str) -> None:
        """Send a campaign immediately."""
        await self._request("POST", f"campaigns/{campaign_id}/actions/send")

    async def schedule_campaign(
        self,
        campaign_id: str,
        schedule_time: datetime,
    ) -> None:
        """Schedule a campaign."""
        json_data = {"schedule_time": schedule_time.isoformat()}
        await self._request(
            "POST", f"campaigns/{campaign_id}/actions/schedule", json_data=json_data
        )

    async def get_campaign_report(self, campaign_id: str) -> CampaignReport:
        """Get campaign report."""
        data = await self._request("GET", f"reports/{campaign_id}")
        return CampaignReport.from_api(data)

    # Template Operations

    async def get_templates(
        self,
        template_type: str | None = None,
        count: int = 10,
        offset: int = 0,
    ) -> list[Template]:
        """Get templates."""
        params: dict[str, Any] = {"count": count, "offset": offset}
        if template_type:
            params["type"] = template_type

        data = await self._request("GET", "templates", params=params)
        return [Template.from_api(t) for t in data.get("templates", [])]

    async def get_template(self, template_id: int) -> Template:
        """Get a specific template."""
        data = await self._request("GET", f"templates/{template_id}")
        return Template.from_api(data)

    # Automation Operations

    async def get_automations(self) -> list[Automation]:
        """Get all automations."""
        data = await self._request("GET", "automations")
        return [Automation.from_api(a) for a in data.get("automations", [])]

    async def get_automation(self, workflow_id: str) -> Automation:
        """Get a specific automation."""
        data = await self._request("GET", f"automations/{workflow_id}")
        return Automation.from_api(data)

    async def start_automation(self, workflow_id: str) -> None:
        """Start an automation."""
        await self._request("POST", f"automations/{workflow_id}/actions/start-all-emails")

    async def pause_automation(self, workflow_id: str) -> None:
        """Pause an automation."""
        await self._request("POST", f"automations/{workflow_id}/actions/pause-all-emails")


def get_mock_audience() -> Audience:
    """Get mock audience for testing."""
    return Audience(
        id="abc123def",
        name="Newsletter Subscribers",
        contact={
            "company": "Test Company",
            "address1": "123 Main St",
            "city": "Test City",
            "state": "TS",
            "zip": "12345",
            "country": "US",
        },
        permission_reminder="You signed up for our newsletter",
        campaign_defaults={
            "from_name": "Test Company",
            "from_email": "newsletter@test.com",
            "subject": "",
            "language": "en",
        },
        date_created=datetime.now(),
        stats=AudienceStats(
            member_count=5000,
            unsubscribe_count=150,
            cleaned_count=50,
            campaign_count=25,
            open_rate=25.5,
            click_rate=3.2,
        ),
        double_optin=True,
    )


def get_mock_campaign() -> Campaign:
    """Get mock campaign for testing."""
    return Campaign(
        id="camp123",
        web_id=12345,
        type=CampaignType.REGULAR,
        create_time=datetime.now(),
        status=CampaignStatus.SENT,
        emails_sent=4500,
        send_time=datetime.now(),
        recipients={"list_id": "abc123def", "segment_text": ""},
        settings={
            "subject_line": "Test Newsletter",
            "from_name": "Test Company",
            "reply_to": "reply@test.com",
        },
        tracking={
            "opens": True,
            "html_clicks": True,
            "text_clicks": True,
        },
    )


def get_mock_report() -> CampaignReport:
    """Get mock campaign report for testing."""
    return CampaignReport(
        id="camp123",
        campaign_title="Test Newsletter",
        list_id="abc123def",
        list_name="Newsletter Subscribers",
        subject_line="Test Newsletter",
        emails_sent=4500,
        abuse_reports=0,
        unsubscribed=15,
        send_time=datetime.now(),
        opens={
            "opens_total": 1800,
            "unique_opens": 1500,
            "open_rate": 33.3,
        },
        clicks={
            "clicks_total": 450,
            "unique_clicks": 350,
            "unique_subscriber_clicks": 300,
            "click_rate": 7.8,
        },
        bounces={
            "hard_bounces": 25,
            "soft_bounces": 50,
            "syntax_errors": 5,
        },
    )
