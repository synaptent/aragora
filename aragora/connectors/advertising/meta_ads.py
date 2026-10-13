"""
Meta Ads Connector (Facebook/Instagram).

Integration with Meta Marketing API:
- Ad accounts
- Campaigns
- Ad sets
- Ads and creatives
- Audiences (custom, lookalike)
- Reporting and insights
- Conversions API

Requires Meta Business access token.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0
_MAX_DELAY = 30.0


class CampaignObjective(str, Enum):
    """Campaign objectives."""

    OUTCOME_AWARENESS = "OUTCOME_AWARENESS"
    OUTCOME_ENGAGEMENT = "OUTCOME_ENGAGEMENT"
    OUTCOME_LEADS = "OUTCOME_LEADS"
    OUTCOME_SALES = "OUTCOME_SALES"
    OUTCOME_APP_PROMOTION = "OUTCOME_APP_PROMOTION"
    OUTCOME_TRAFFIC = "OUTCOME_TRAFFIC"


class CampaignStatus(str, Enum):
    """Campaign status."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETED = "DELETED"
    ARCHIVED = "ARCHIVED"


class AdSetStatus(str, Enum):
    """Ad set status."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETED = "DELETED"
    ARCHIVED = "ARCHIVED"


class AdStatus(str, Enum):
    """Ad status."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETED = "DELETED"
    ARCHIVED = "ARCHIVED"


class BillingEvent(str, Enum):
    """Billing event types."""

    IMPRESSIONS = "IMPRESSIONS"
    LINK_CLICKS = "LINK_CLICKS"
    POST_ENGAGEMENT = "POST_ENGAGEMENT"
    THRUPLAY = "THRUPLAY"


class OptimizationGoal(str, Enum):
    """Optimization goals."""

    IMPRESSIONS = "IMPRESSIONS"
    REACH = "REACH"
    LINK_CLICKS = "LINK_CLICKS"
    LANDING_PAGE_VIEWS = "LANDING_PAGE_VIEWS"
    CONVERSIONS = "CONVERSIONS"
    LEAD_GENERATION = "LEAD_GENERATION"
    APP_INSTALLS = "APP_INSTALLS"
    THRUPLAY = "THRUPLAY"
    VALUE = "VALUE"


class Placement(str, Enum):
    """Ad placements."""

    FACEBOOK_FEED = "facebook_feed"
    FACEBOOK_STORIES = "facebook_stories"
    FACEBOOK_REELS = "facebook_reels"
    INSTAGRAM_FEED = "instagram_feed"
    INSTAGRAM_STORIES = "instagram_stories"
    INSTAGRAM_REELS = "instagram_reels"
    AUDIENCE_NETWORK = "audience_network"
    MESSENGER = "messenger"


@dataclass
class MetaAdsCredentials:
    """Meta Marketing API credentials."""

    access_token: str
    app_id: str | None = None
    app_secret: str | None = None
    ad_account_id: str = ""  # Format: act_XXXXXXXXX
    base_url: str = "https://graph.facebook.com/v18.0"


@dataclass
class AdAccount:
    """Meta ad account."""

    id: str
    name: str
    account_status: int
    currency: str
    timezone_name: str
    amount_spent: int = 0  # In cents
    balance: int = 0
    spend_cap: int = 0
    business_id: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> AdAccount:
        """Create from API response."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            account_status=data.get("account_status", 0),
            currency=data.get("currency", "USD"),
            timezone_name=data.get("timezone_name", ""),
            amount_spent=int(data.get("amount_spent", 0)),
            balance=int(data.get("balance", 0)),
            spend_cap=int(data.get("spend_cap", 0)),
            business_id=data.get("business", {}).get("id"),
        )


@dataclass
class Campaign:
    """Meta ad campaign."""

    id: str
    name: str
    objective: CampaignObjective
    status: CampaignStatus
    daily_budget: int | None = None  # In cents
    lifetime_budget: int | None = None
    budget_remaining: int | None = None
    buying_type: str = "AUCTION"
    special_ad_categories: list[str] = field(default_factory=list)
    created_time: datetime | None = None
    updated_time: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Campaign:
        """Create from API response."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            objective=CampaignObjective(data.get("objective", "OUTCOME_AWARENESS")),
            status=CampaignStatus(data.get("status", "PAUSED")),
            daily_budget=int(data["daily_budget"]) if data.get("daily_budget") else None,
            lifetime_budget=int(data["lifetime_budget"]) if data.get("lifetime_budget") else None,
            budget_remaining=(
                int(data["budget_remaining"]) if data.get("budget_remaining") else None
            ),
            buying_type=data.get("buying_type", "AUCTION"),
            special_ad_categories=data.get("special_ad_categories", []),
            created_time=_parse_datetime(data.get("created_time")),
            updated_time=_parse_datetime(data.get("updated_time")),
        )


@dataclass
class AdSet:
    """Meta ad set."""

    id: str
    name: str
    campaign_id: str
    status: AdSetStatus
    daily_budget: int | None = None
    lifetime_budget: int | None = None
    bid_amount: int | None = None
    billing_event: BillingEvent = BillingEvent.IMPRESSIONS
    optimization_goal: OptimizationGoal = OptimizationGoal.IMPRESSIONS
    targeting: dict[str, Any] = field(default_factory=dict)
    start_time: datetime | None = None
    end_time: datetime | None = None
    created_time: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> AdSet:
        """Create from API response."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            campaign_id=data.get("campaign_id", ""),
            status=AdSetStatus(data.get("status", "PAUSED")),
            daily_budget=int(data["daily_budget"]) if data.get("daily_budget") else None,
            lifetime_budget=int(data["lifetime_budget"]) if data.get("lifetime_budget") else None,
            bid_amount=int(data["bid_amount"]) if data.get("bid_amount") else None,
            billing_event=BillingEvent(data.get("billing_event", "IMPRESSIONS")),
            optimization_goal=OptimizationGoal(data.get("optimization_goal", "IMPRESSIONS")),
            targeting=data.get("targeting", {}),
            start_time=_parse_datetime(data.get("start_time")),
            end_time=_parse_datetime(data.get("end_time")),
            created_time=_parse_datetime(data.get("created_time")),
        )


@dataclass
class Ad:
    """Meta ad."""

    id: str
    name: str
    adset_id: str
    campaign_id: str
    status: AdStatus
    creative_id: str | None = None
    tracking_specs: list[dict[str, Any]] = field(default_factory=list)
    created_time: datetime | None = None
    updated_time: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Ad:
        """Create from API response."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            adset_id=data.get("adset_id", ""),
            campaign_id=data.get("campaign_id", ""),
            status=AdStatus(data.get("status", "PAUSED")),
            creative_id=data.get("creative", {}).get("id"),
            tracking_specs=data.get("tracking_specs", []),
            created_time=_parse_datetime(data.get("created_time")),
            updated_time=_parse_datetime(data.get("updated_time")),
        )


@dataclass
class AdCreative:
    """Ad creative."""

    id: str
    name: str
    title: str | None = None
    body: str | None = None
    image_url: str | None = None
    video_id: str | None = None
    call_to_action_type: str | None = None
    link_url: str | None = None
    object_story_spec: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> AdCreative:
        """Create from API response."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            title=data.get("title"),
            body=data.get("body"),
            image_url=data.get("image_url"),
            video_id=data.get("video_id"),
            call_to_action_type=data.get("call_to_action_type"),
            link_url=data.get("link_url"),
            object_story_spec=data.get("object_story_spec", {}),
        )


@dataclass
class AdInsights:
    """Ad performance insights."""

    campaign_id: str | None = None
    campaign_name: str | None = None
    adset_id: str | None = None
    adset_name: str | None = None
    ad_id: str | None = None
    ad_name: str | None = None
    impressions: int = 0
    reach: int = 0
    clicks: int = 0
    spend: Decimal = Decimal("0")
    cpc: Decimal = Decimal("0")
    cpm: Decimal = Decimal("0")
    ctr: float = 0
    frequency: float = 0
    conversions: int = 0
    cost_per_conversion: Decimal = Decimal("0")
    actions: list[dict[str, Any]] = field(default_factory=list)
    date_start: date | None = None
    date_stop: date | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> AdInsights:
        """Create from API response."""
        return cls(
            campaign_id=data.get("campaign_id"),
            campaign_name=data.get("campaign_name"),
            adset_id=data.get("adset_id"),
            adset_name=data.get("adset_name"),
            ad_id=data.get("ad_id"),
            ad_name=data.get("ad_name"),
            impressions=int(data.get("impressions", 0)),
            reach=int(data.get("reach", 0)),
            clicks=int(data.get("clicks", 0)),
            spend=Decimal(data.get("spend", "0")),
            cpc=Decimal(data.get("cpc", "0")),
            cpm=Decimal(data.get("cpm", "0")),
            ctr=float(data.get("ctr", 0)),
            frequency=float(data.get("frequency", 0)),
            actions=data.get("actions", []),
            date_start=_parse_date(data.get("date_start")),
            date_stop=_parse_date(data.get("date_stop")),
        )


@dataclass
class CustomAudience:
    """Custom audience."""

    id: str
    name: str
    description: str | None = None
    subtype: str = "CUSTOM"
    approximate_count: int = 0
    data_source: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> CustomAudience:
        """Create from API response."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description"),
            subtype=data.get("subtype", "CUSTOM"),
            approximate_count=int(data.get("approximate_count", 0)),
            data_source=data.get("data_source", {}),
        )


class MetaAdsError(Exception):
    """Meta Ads API error."""

    def __init__(self, message: str, code: int | None = None, error_subcode: int | None = None):
        super().__init__(message)
        self.code = code
        self.error_subcode = error_subcode


class MetaAdsConnector:
    """
    Meta Marketing API connector.

    Provides integration with Meta Ads for:
    - Campaign management
    - Ad set and ad management
    - Audience targeting
    - Performance reporting
    - Conversion tracking
    """

    def __init__(self, credentials: MetaAdsCredentials):
        self.credentials = credentials
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.credentials.base_url,
                timeout=60.0,
            )
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_data: dict | None = None,
    ) -> dict[str, Any]:
        """Make API request with retry and exponential backoff."""
        client = await self._get_client()

        # Add access token to params
        if params is None:
            params = {}
        params["access_token"] = self.credentials.access_token

        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await client.request(method, path, params=params, json=json_data)

                if response.status_code == 429 and attempt < _MAX_RETRIES:
                    retry_after = float(
                        response.headers.get("Retry-After", _BASE_DELAY * (2**attempt))
                    )
                    jitter = random.uniform(0, retry_after * 0.3)
                    delay = min(retry_after + jitter, _MAX_DELAY)
                    logger.warning(
                        "Meta Ads rate limited, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 500 and attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Meta Ads server error %d, retrying in %.1fs (attempt %d/%d)",
                        response.status_code,
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                data = response.json()

                if "error" in data:
                    error = data["error"]
                    raise MetaAdsError(
                        message=error.get("message", "Unknown error"),
                        code=error.get("code"),
                        error_subcode=error.get("error_subcode"),
                    )

                return data

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Meta Ads request timeout, retrying in %.1fs (attempt %d/%d)",
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
                        "Meta Ads connection error, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
            except MetaAdsError:
                raise

        raise MetaAdsError(
            message=f"Request failed after {_MAX_RETRIES + 1} attempts: {last_error}",
        )

    # =========================================================================
    # Ad Account
    # =========================================================================

    async def get_ad_account(self) -> AdAccount:
        """Get ad account details."""
        fields = (
            "id,name,account_status,currency,timezone_name,amount_spent,balance,spend_cap,business"
        )
        data = await self._request(
            "GET", f"/{self.credentials.ad_account_id}", params={"fields": fields}
        )
        return AdAccount.from_api(data)

    async def get_ad_accounts(self, business_id: str) -> list[AdAccount]:
        """Get all ad accounts for a business."""
        fields = "id,name,account_status,currency,timezone_name"
        data = await self._request(
            "GET",
            f"/{business_id}/owned_ad_accounts",
            params={"fields": fields},
        )
        return [AdAccount.from_api(acc) for acc in data.get("data", [])]

    # =========================================================================
    # Campaigns
    # =========================================================================

    async def get_campaigns(
        self,
        status: CampaignStatus | None = None,
        limit: int = 100,
    ) -> list[Campaign]:
        """Get campaigns for the ad account."""
        fields = "id,name,objective,status,daily_budget,lifetime_budget,budget_remaining,buying_type,special_ad_categories,created_time,updated_time"
        params: dict[str, Any] = {"fields": fields, "limit": limit}

        if status:
            params["filtering"] = (
                f'[{{"field":"status","operator":"EQUAL","value":"{status.value}"}}]'
            )

        data = await self._request(
            "GET", f"/{self.credentials.ad_account_id}/campaigns", params=params
        )
        return [Campaign.from_api(c) for c in data.get("data", [])]

    async def get_campaign(self, campaign_id: str) -> Campaign:
        """Get a single campaign."""
        fields = "id,name,objective,status,daily_budget,lifetime_budget,budget_remaining,buying_type,special_ad_categories,created_time,updated_time"
        data = await self._request("GET", f"/{campaign_id}", params={"fields": fields})
        return Campaign.from_api(data)

    async def create_campaign(
        self,
        name: str,
        objective: CampaignObjective,
        status: CampaignStatus = CampaignStatus.PAUSED,
        daily_budget: int | None = None,
        lifetime_budget: int | None = None,
        special_ad_categories: list[str] | None = None,
    ) -> Campaign:
        """Create a new campaign."""
        params: dict[str, Any] = {
            "name": name,
            "objective": objective.value,
            "status": status.value,
            "special_ad_categories": special_ad_categories or [],
        }

        if daily_budget:
            params["daily_budget"] = daily_budget
        if lifetime_budget:
            params["lifetime_budget"] = lifetime_budget

        data = await self._request(
            "POST", f"/{self.credentials.ad_account_id}/campaigns", params=params
        )
        return await self.get_campaign(data["id"])

    async def update_campaign(
        self,
        campaign_id: str,
        name: str | None = None,
        status: CampaignStatus | None = None,
        daily_budget: int | None = None,
    ) -> Campaign:
        """Update a campaign."""
        params: dict[str, Any] = {}
        if name:
            params["name"] = name
        if status:
            params["status"] = status.value
        if daily_budget:
            params["daily_budget"] = daily_budget

        await self._request("POST", f"/{campaign_id}", params=params)
        return await self.get_campaign(campaign_id)

    async def delete_campaign(self, campaign_id: str) -> bool:
        """Delete (archive) a campaign."""
        await self._request("POST", f"/{campaign_id}", params={"status": "DELETED"})
        return True

    # =========================================================================
    # Ad Sets
    # =========================================================================

    async def get_ad_sets(
        self,
        campaign_id: str | None = None,
        limit: int = 100,
    ) -> list[AdSet]:
        """Get ad sets."""
        fields = "id,name,campaign_id,status,daily_budget,lifetime_budget,bid_amount,billing_event,optimization_goal,targeting,start_time,end_time,created_time"

        if campaign_id:
            path = f"/{campaign_id}/adsets"
        else:
            path = f"/{self.credentials.ad_account_id}/adsets"

        data = await self._request("GET", path, params={"fields": fields, "limit": limit})
        return [AdSet.from_api(a) for a in data.get("data", [])]

    async def get_ad_set(self, adset_id: str) -> AdSet:
        """Get a single ad set."""
        fields = "id,name,campaign_id,status,daily_budget,lifetime_budget,bid_amount,billing_event,optimization_goal,targeting,start_time,end_time,created_time"
        data = await self._request("GET", f"/{adset_id}", params={"fields": fields})
        return AdSet.from_api(data)

    async def create_ad_set(
        self,
        name: str,
        campaign_id: str,
        daily_budget: int,
        optimization_goal: OptimizationGoal,
        billing_event: BillingEvent,
        targeting: dict[str, Any],
        status: AdSetStatus = AdSetStatus.PAUSED,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        bid_amount: int | None = None,
    ) -> AdSet:
        """Create a new ad set."""
        params: dict[str, Any] = {
            "name": name,
            "campaign_id": campaign_id,
            "daily_budget": daily_budget,
            "optimization_goal": optimization_goal.value,
            "billing_event": billing_event.value,
            "targeting": str(targeting),
            "status": status.value,
        }

        if start_time:
            params["start_time"] = start_time.isoformat()
        if end_time:
            params["end_time"] = end_time.isoformat()
        if bid_amount:
            params["bid_amount"] = bid_amount

        data = await self._request(
            "POST", f"/{self.credentials.ad_account_id}/adsets", params=params
        )
        return await self.get_ad_set(data["id"])

    async def update_ad_set_status(self, adset_id: str, status: AdSetStatus) -> AdSet:
        """Update ad set status."""
        await self._request("POST", f"/{adset_id}", params={"status": status.value})
        return await self.get_ad_set(adset_id)

    # =========================================================================
    # Ads
    # =========================================================================

    async def get_ads(
        self,
        adset_id: str | None = None,
        limit: int = 100,
    ) -> list[Ad]:
        """Get ads."""
        fields = (
            "id,name,adset_id,campaign_id,status,creative,tracking_specs,created_time,updated_time"
        )

        if adset_id:
            path = f"/{adset_id}/ads"
        else:
            path = f"/{self.credentials.ad_account_id}/ads"

        data = await self._request("GET", path, params={"fields": fields, "limit": limit})
        return [Ad.from_api(a) for a in data.get("data", [])]

    async def get_ad(self, ad_id: str) -> Ad:
        """Get a single ad."""
        fields = (
            "id,name,adset_id,campaign_id,status,creative,tracking_specs,created_time,updated_time"
        )
        data = await self._request("GET", f"/{ad_id}", params={"fields": fields})
        return Ad.from_api(data)

    async def update_ad_status(self, ad_id: str, status: AdStatus) -> Ad:
        """Update ad status."""
        await self._request("POST", f"/{ad_id}", params={"status": status.value})
        return await self.get_ad(ad_id)

    # =========================================================================
    # Insights / Reporting
    # =========================================================================

    async def get_insights(
        self,
        level: str = "campaign",
        date_preset: str | None = None,
        time_range: dict[str, str] | None = None,
        fields: list[str] | None = None,
        breakdowns: list[str] | None = None,
        filtering: list[dict[str, Any]] | None = None,
    ) -> list[AdInsights]:
        """
        Get ad insights/performance data.

        level: account, campaign, adset, ad
        date_preset: today, yesterday, this_month, last_month, this_quarter, last_7d, last_14d, last_28d, last_30d, last_90d
        """
        if not fields:
            fields = [
                "campaign_id",
                "campaign_name",
                "adset_id",
                "adset_name",
                "ad_id",
                "ad_name",
                "impressions",
                "reach",
                "clicks",
                "spend",
                "cpc",
                "cpm",
                "ctr",
                "frequency",
                "actions",
            ]

        params: dict[str, Any] = {
            "fields": ",".join(fields),
            "level": level,
        }

        if date_preset:
            params["date_preset"] = date_preset
        elif time_range:
            params["time_range"] = str(time_range)
        else:
            params["date_preset"] = "last_7d"

        if breakdowns:
            params["breakdowns"] = ",".join(breakdowns)
        if filtering:
            params["filtering"] = str(filtering)

        data = await self._request(
            "GET",
            f"/{self.credentials.ad_account_id}/insights",
            params=params,
        )
        return [AdInsights.from_api(i) for i in data.get("data", [])]

    async def get_campaign_insights(
        self,
        campaign_id: str,
        date_preset: str = "last_7d",
    ) -> list[AdInsights]:
        """Get insights for a specific campaign."""
        fields = "impressions,reach,clicks,spend,cpc,cpm,ctr,frequency,actions"
        data = await self._request(
            "GET",
            f"/{campaign_id}/insights",
            params={"fields": fields, "date_preset": date_preset},
        )
        return [AdInsights.from_api(i) for i in data.get("data", [])]

    # =========================================================================
    # Audiences
    # =========================================================================

    async def get_custom_audiences(self, limit: int = 100) -> list[CustomAudience]:
        """Get custom audiences."""
        fields = "id,name,description,subtype,approximate_count,data_source"
        data = await self._request(
            "GET",
            f"/{self.credentials.ad_account_id}/customaudiences",
            params={"fields": fields, "limit": limit},
        )
        return [CustomAudience.from_api(a) for a in data.get("data", [])]

    async def create_custom_audience(
        self,
        name: str,
        subtype: str = "CUSTOM",
        description: str | None = None,
        customer_file_source: str | None = None,
    ) -> CustomAudience:
        """Create a custom audience."""
        params: dict[str, Any] = {
            "name": name,
            "subtype": subtype,
        }
        if description:
            params["description"] = description
        if customer_file_source:
            params["customer_file_source"] = customer_file_source

        data = await self._request(
            "POST",
            f"/{self.credentials.ad_account_id}/customaudiences",
            params=params,
        )
        return CustomAudience(id=data["id"], name=name, subtype=subtype)

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> MetaAdsConnector:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _parse_date(value: str | None) -> date | None:
    """Parse date string."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def get_mock_campaign() -> Campaign:
    """Get a mock campaign for testing."""
    return Campaign(
        id="23456789012345678",
        name="Summer Sale Campaign",
        objective=CampaignObjective.OUTCOME_SALES,
        status=CampaignStatus.ACTIVE,
        daily_budget=5000,  # $50/day
    )


def get_mock_insights() -> AdInsights:
    """Get mock insights for testing."""
    return AdInsights(
        campaign_id="23456789012345678",
        campaign_name="Summer Sale Campaign",
        impressions=50000,
        reach=35000,
        clicks=2500,
        spend=Decimal("250.00"),
        ctr=0.05,
    )
