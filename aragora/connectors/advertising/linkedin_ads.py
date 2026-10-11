"""
LinkedIn Ads Connector.

Integration with LinkedIn Marketing API for B2B advertising:
- Campaign management (Sponsored Content, Message Ads, Text Ads)
- Audience targeting (job titles, industries, companies)
- Lead Gen Forms
- Conversion tracking
- Analytics and reporting
"""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0
_MAX_DELAY = 30.0


class CampaignStatus(Enum):
    """LinkedIn campaign status."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"
    CANCELED = "CANCELED"
    DRAFT = "DRAFT"
    PENDING_DELETION = "PENDING_DELETION"


class CampaignType(Enum):
    """LinkedIn campaign types."""

    TEXT_AD = "TEXT_AD"
    SPONSORED_UPDATES = "SPONSORED_UPDATES"
    SPONSORED_INMAILS = "SPONSORED_INMAILS"
    DYNAMIC = "DYNAMIC"


class ObjectiveType(Enum):
    """LinkedIn campaign objectives."""

    BRAND_AWARENESS = "BRAND_AWARENESS"
    WEBSITE_VISITS = "WEBSITE_VISITS"
    ENGAGEMENT = "ENGAGEMENT"
    VIDEO_VIEWS = "VIDEO_VIEWS"
    LEAD_GENERATION = "LEAD_GENERATION"
    WEBSITE_CONVERSIONS = "WEBSITE_CONVERSIONS"
    JOB_APPLICANTS = "JOB_APPLICANTS"
    TALENT_LEADS = "TALENT_LEADS"


class AdFormat(Enum):
    """LinkedIn ad formats."""

    SINGLE_IMAGE = "SINGLE_IMAGE_AD"
    CAROUSEL = "CAROUSEL_IMAGE_AD"
    VIDEO = "VIDEO_AD"
    TEXT = "TEXT_AD"
    SPOTLIGHT = "SPOTLIGHT_AD"
    MESSAGE = "MESSAGE_AD"
    CONVERSATION = "CONVERSATION_AD"
    EVENT = "EVENT_AD"
    DOCUMENT = "DOCUMENT_AD"


class BidStrategy(Enum):
    """LinkedIn bidding strategies."""

    MANUAL_CPC = "MANUAL_CPC"
    MANUAL_CPM = "MANUAL_CPM"
    MAXIMUM_DELIVERY = "MAXIMUM_DELIVERY"
    COST_CAP = "COST_CAP"


@dataclass
class LinkedInAdsCredentials:
    """LinkedIn Marketing API credentials."""

    access_token: str
    ad_account_id: str
    client_id: str | None = None
    client_secret: str | None = None
    refresh_token: str | None = None


@dataclass
class CampaignGroup:
    """LinkedIn campaign group (account-level container)."""

    id: str
    name: str
    status: CampaignStatus
    account_id: str
    total_budget: float | None = None
    run_schedule_start: datetime | None = None
    run_schedule_end: datetime | None = None
    created_at: datetime | None = None
    last_modified_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "CampaignGroup":
        """Create from LinkedIn API response."""
        return cls(
            id=str(data.get("id", "")),
            name=data.get("name", ""),
            status=CampaignStatus(data.get("status", "DRAFT")),
            account_id=data.get("account", "").split(":")[-1] if data.get("account") else "",
            total_budget=(
                data.get("totalBudget", {}).get("amount") if data.get("totalBudget") else None
            ),
            run_schedule_start=(
                datetime.fromisoformat(data["runSchedule"]["start"])
                if data.get("runSchedule", {}).get("start")
                else None
            ),
            run_schedule_end=(
                datetime.fromisoformat(data["runSchedule"]["end"])
                if data.get("runSchedule", {}).get("end")
                else None
            ),
            created_at=(
                datetime.fromtimestamp(data["createdAt"] / 1000) if data.get("createdAt") else None
            ),
            last_modified_at=(
                datetime.fromtimestamp(data["lastModifiedAt"] / 1000)
                if data.get("lastModifiedAt")
                else None
            ),
        )


@dataclass
class Campaign:
    """LinkedIn advertising campaign."""

    id: str
    name: str
    status: CampaignStatus
    campaign_group_id: str
    account_id: str
    campaign_type: CampaignType
    objective_type: ObjectiveType
    daily_budget: float | None = None
    total_budget: float | None = None
    bid_strategy: BidStrategy | None = None
    bid_amount: float | None = None
    targeting_criteria: dict[str, Any] = field(default_factory=dict)
    run_schedule_start: datetime | None = None
    run_schedule_end: datetime | None = None
    created_at: datetime | None = None
    last_modified_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Campaign":
        """Create from LinkedIn API response."""
        return cls(
            id=str(data.get("id", "")),
            name=data.get("name", ""),
            status=CampaignStatus(data.get("status", "DRAFT")),
            campaign_group_id=(
                data.get("campaignGroup", "").split(":")[-1] if data.get("campaignGroup") else ""
            ),
            account_id=data.get("account", "").split(":")[-1] if data.get("account") else "",
            campaign_type=CampaignType(data.get("type", "SPONSORED_UPDATES")),
            objective_type=ObjectiveType(data.get("objectiveType", "WEBSITE_VISITS")),
            daily_budget=(
                data.get("dailyBudget", {}).get("amount") if data.get("dailyBudget") else None
            ),
            total_budget=(
                data.get("totalBudget", {}).get("amount") if data.get("totalBudget") else None
            ),
            bid_strategy=(
                BidStrategy(data["optimizationTargetType"])
                if data.get("optimizationTargetType")
                else None
            ),
            bid_amount=data.get("unitCost", {}).get("amount") if data.get("unitCost") else None,
            targeting_criteria=data.get("targetingCriteria", {}),
            run_schedule_start=(
                datetime.fromisoformat(data["runSchedule"]["start"])
                if data.get("runSchedule", {}).get("start")
                else None
            ),
            run_schedule_end=(
                datetime.fromisoformat(data["runSchedule"]["end"])
                if data.get("runSchedule", {}).get("end")
                else None
            ),
            created_at=(
                datetime.fromtimestamp(data["createdAt"] / 1000) if data.get("createdAt") else None
            ),
            last_modified_at=(
                datetime.fromtimestamp(data["lastModifiedAt"] / 1000)
                if data.get("lastModifiedAt")
                else None
            ),
        )


@dataclass
class Creative:
    """LinkedIn ad creative."""

    id: str
    campaign_id: str
    status: str
    ad_format: AdFormat
    reference: str  # URN reference to underlying content
    call_to_action: str | None = None
    landing_page_url: str | None = None
    created_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Creative":
        """Create from LinkedIn API response."""
        return cls(
            id=str(data.get("id", "")),
            campaign_id=data.get("campaign", "").split(":")[-1] if data.get("campaign") else "",
            status=data.get("status", ""),
            ad_format=AdFormat(data.get("type", "SINGLE_IMAGE_AD")),
            reference=data.get("reference", ""),
            call_to_action=(
                data.get("callToAction", {}).get("action") if data.get("callToAction") else None
            ),
            landing_page_url=(
                data.get("callToAction", {}).get("destinationUrl")
                if data.get("callToAction")
                else None
            ),
            created_at=(
                datetime.fromtimestamp(data["createdAt"] / 1000) if data.get("createdAt") else None
            ),
        )


@dataclass
class AdAnalytics:
    """LinkedIn ad analytics/metrics."""

    campaign_id: str
    start_date: date
    end_date: date
    impressions: int = 0
    clicks: int = 0
    cost: float = 0.0
    conversions: int = 0
    leads: int = 0
    video_views: int = 0
    video_completions: int = 0
    engagement: int = 0  # Likes, comments, shares
    follows: int = 0
    ctr: float = 0.0
    cpc: float = 0.0
    cpm: float = 0.0
    conversion_rate: float = 0.0
    cost_per_lead: float = 0.0

    @classmethod
    def from_api(
        cls, data: dict[str, Any], campaign_id: str, start_date: date, end_date: date
    ) -> "AdAnalytics":
        """Create from LinkedIn API response."""
        impressions = data.get("impressions", 0)
        clicks = data.get("clicks", 0)
        cost = float(data.get("costInLocalCurrency", 0))
        conversions = data.get("externalWebsiteConversions", 0)
        leads = data.get("oneClickLeads", 0) + data.get("leadGenerationMailContactInfoShares", 0)

        return cls(
            campaign_id=campaign_id,
            start_date=start_date,
            end_date=end_date,
            impressions=impressions,
            clicks=clicks,
            cost=cost,
            conversions=conversions,
            leads=leads,
            video_views=data.get("videoViews", 0),
            video_completions=data.get("videoCompletions", 0),
            engagement=data.get("totalEngagements", 0),
            follows=data.get("follows", 0),
            ctr=(clicks / impressions * 100) if impressions > 0 else 0.0,
            cpc=(cost / clicks) if clicks > 0 else 0.0,
            cpm=(cost / impressions * 1000) if impressions > 0 else 0.0,
            conversion_rate=(conversions / clicks * 100) if clicks > 0 else 0.0,
            cost_per_lead=(cost / leads) if leads > 0 else 0.0,
        )


@dataclass
class LeadGenForm:
    """LinkedIn Lead Gen Form."""

    id: str
    name: str
    status: str
    account_id: str
    headline: str
    description: str | None = None
    privacy_policy_url: str | None = None
    thank_you_message: str | None = None
    questions: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "LeadGenForm":
        """Create from LinkedIn API response."""
        return cls(
            id=str(data.get("id", "")),
            name=data.get("name", ""),
            status=data.get("status", ""),
            account_id=data.get("account", "").split(":")[-1] if data.get("account") else "",
            headline=data.get("headline", {}).get("text", ""),
            description=data.get("description", {}).get("text"),
            privacy_policy_url=data.get("privacyPolicy", {}).get("url"),
            thank_you_message=data.get("thankYouMessage", {}).get("message"),
            questions=data.get("questions", []),
            created_at=(
                datetime.fromtimestamp(data["createdAt"] / 1000) if data.get("createdAt") else None
            ),
        )


@dataclass
class Lead:
    """LinkedIn lead from Lead Gen Form."""

    id: str
    form_id: str
    campaign_id: str
    created_at: datetime
    form_response: dict[str, Any] = field(default_factory=dict)
    member_urn: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Lead":
        """Create from LinkedIn API response."""
        return cls(
            id=str(data.get("id", "")),
            form_id=(
                data.get("leadGenFormUrn", "").split(":")[-1] if data.get("leadGenFormUrn") else ""
            ),
            campaign_id=(
                data.get("sponsoredCampaign", "").split(":")[-1]
                if data.get("sponsoredCampaign")
                else ""
            ),
            created_at=(
                datetime.fromtimestamp(data["submittedAt"] / 1000)
                if data.get("submittedAt")
                else datetime.now()
            ),
            form_response=data.get("formResponse", {}),
            member_urn=data.get("owner"),
        )


@dataclass
class AudienceSegment:
    """LinkedIn audience segment for targeting."""

    id: str
    name: str
    segment_type: str
    account_id: str
    matched_count: int | None = None
    status: str | None = None
    created_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "AudienceSegment":
        """Create from LinkedIn API response."""
        return cls(
            id=str(data.get("id", "")),
            name=data.get("name", ""),
            segment_type=data.get("type", ""),
            account_id=data.get("account", "").split(":")[-1] if data.get("account") else "",
            matched_count=data.get("matchedMemberCount"),
            status=data.get("status"),
            created_at=(
                datetime.fromtimestamp(data["createdAt"] / 1000) if data.get("createdAt") else None
            ),
        )


class LinkedInAdsError(Exception):
    """LinkedIn Ads API error."""

    def __init__(self, message: str, status_code: int | None = None, error_code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class LinkedInAdsConnector:
    """LinkedIn Marketing API connector."""

    BASE_URL = "https://api.linkedin.com/v2"
    REST_URL = "https://api.linkedin.com/rest"

    def __init__(self, credentials: LinkedInAdsCredentials):
        """Initialize with credentials."""
        self.credentials = credentials
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self.credentials.access_token}",
                    "X-Restli-Protocol-Version": "2.0.0",
                    "LinkedIn-Version": "202401",
                    "Content-Type": "application/json",
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
        use_rest_api: bool = True,
    ) -> dict[str, Any]:
        """Make API request with retry and exponential backoff."""
        client = await self._get_client()
        base_url = self.REST_URL if use_rest_api else self.BASE_URL
        url = f"{base_url}/{endpoint}"

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
                        "LinkedIn Ads rate limited, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 500 and attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "LinkedIn Ads server error %d, retrying in %.1fs (attempt %d/%d)",
                        response.status_code,
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 400:
                    error_data = response.json() if response.content else {}
                    raise LinkedInAdsError(
                        message=error_data.get("message", f"API error: {response.status_code}"),
                        status_code=response.status_code,
                        error_code=error_data.get("code"),
                    )

                if response.status_code == 204 or not response.content:
                    return {}

                return response.json()

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "LinkedIn Ads request timeout, retrying in %.1fs (attempt %d/%d)",
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
                        "LinkedIn Ads connection error, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
            except LinkedInAdsError:
                raise

        raise LinkedInAdsError(
            message=f"Request failed after {_MAX_RETRIES + 1} attempts: {last_error}",
        )

    # Campaign Group Operations

    async def get_campaign_groups(
        self,
        status: CampaignStatus | None = None,
    ) -> list[CampaignGroup]:
        """Get all campaign groups for the ad account."""
        params = {
            "q": "search",
            "search": f"(account:(values:List(urn:li:sponsoredAccount:{self.credentials.ad_account_id})))",
        }

        if status:
            params["search"] += f"(status:(values:List({status.value})))"

        response = await self._request(
            "GET",
            "adCampaignGroups",
            params=params,
        )

        return [CampaignGroup.from_api(item) for item in response.get("elements", [])]

    async def create_campaign_group(
        self,
        name: str,
        status: CampaignStatus = CampaignStatus.DRAFT,
        total_budget: float | None = None,
        run_schedule_start: datetime | None = None,
        run_schedule_end: datetime | None = None,
    ) -> CampaignGroup:
        """Create a new campaign group."""
        data: dict[str, Any] = {
            "account": f"urn:li:sponsoredAccount:{self.credentials.ad_account_id}",
            "name": name,
            "status": status.value,
        }

        if total_budget is not None:
            data["totalBudget"] = {
                "currencyCode": "USD",
                "amount": str(total_budget),
            }

        if run_schedule_start:
            data["runSchedule"] = {"start": run_schedule_start.isoformat()}
            if run_schedule_end:
                data["runSchedule"]["end"] = run_schedule_end.isoformat()

        response = await self._request("POST", "adCampaignGroups", json_data=data)
        return CampaignGroup.from_api(response)

    # Campaign Operations

    async def get_campaigns(
        self,
        status: CampaignStatus | None = None,
        campaign_group_id: str | None = None,
    ) -> list[Campaign]:
        """Get campaigns for the ad account."""
        params = {
            "q": "search",
            "search": f"(account:(values:List(urn:li:sponsoredAccount:{self.credentials.ad_account_id})))",
        }

        if status:
            params["search"] += f"(status:(values:List({status.value})))"

        if campaign_group_id:
            params["search"] += (
                f"(campaignGroup:(values:List(urn:li:sponsoredCampaignGroup:{campaign_group_id})))"
            )

        response = await self._request("GET", "adCampaigns", params=params)
        return [Campaign.from_api(item) for item in response.get("elements", [])]

    async def get_campaign(self, campaign_id: str) -> Campaign:
        """Get a specific campaign by ID."""
        response = await self._request("GET", f"adCampaigns/{campaign_id}")
        return Campaign.from_api(response)

    async def create_campaign(
        self,
        name: str,
        campaign_group_id: str,
        campaign_type: CampaignType,
        objective_type: ObjectiveType,
        daily_budget: float,
        bid_strategy: BidStrategy = BidStrategy.MAXIMUM_DELIVERY,
        bid_amount: float | None = None,
        targeting_criteria: dict[str, Any] | None = None,
        status: CampaignStatus = CampaignStatus.DRAFT,
    ) -> Campaign:
        """Create a new campaign."""
        data: dict[str, Any] = {
            "account": f"urn:li:sponsoredAccount:{self.credentials.ad_account_id}",
            "campaignGroup": f"urn:li:sponsoredCampaignGroup:{campaign_group_id}",
            "name": name,
            "type": campaign_type.value,
            "objectiveType": objective_type.value,
            "status": status.value,
            "dailyBudget": {
                "currencyCode": "USD",
                "amount": str(daily_budget),
            },
            "optimizationTargetType": bid_strategy.value,
        }

        if bid_amount is not None:
            data["unitCost"] = {
                "currencyCode": "USD",
                "amount": str(bid_amount),
            }

        if targeting_criteria:
            data["targetingCriteria"] = targeting_criteria

        response = await self._request("POST", "adCampaigns", json_data=data)
        return Campaign.from_api(response)

    async def update_campaign_status(
        self,
        campaign_id: str,
        status: CampaignStatus,
    ) -> Campaign:
        """Update campaign status."""
        data = {"patch": {"$set": {"status": status.value}}}
        response = await self._request(
            "POST",
            f"adCampaigns/{campaign_id}",
            json_data=data,
        )
        return Campaign.from_api(response)

    # Creative Operations

    async def get_creatives(self, campaign_id: str) -> list[Creative]:
        """Get creatives for a campaign."""
        params = {
            "q": "search",
            "search": f"(campaign:(values:List(urn:li:sponsoredCampaign:{campaign_id})))",
        }

        response = await self._request("GET", "adCreatives", params=params)
        return [Creative.from_api(item) for item in response.get("elements", [])]

    async def create_creative(
        self,
        campaign_id: str,
        ad_format: AdFormat,
        reference: str,
        call_to_action: str | None = None,
        landing_page_url: str | None = None,
    ) -> Creative:
        """Create a new ad creative."""
        data: dict[str, Any] = {
            "campaign": f"urn:li:sponsoredCampaign:{campaign_id}",
            "type": ad_format.value,
            "reference": reference,
        }

        if call_to_action and landing_page_url:
            data["callToAction"] = {
                "action": call_to_action,
                "destinationUrl": landing_page_url,
            }

        response = await self._request("POST", "adCreatives", json_data=data)
        return Creative.from_api(response)

    # Analytics Operations

    async def get_campaign_analytics(
        self,
        campaign_ids: list[str],
        start_date: date,
        end_date: date,
        granularity: str = "ALL",  # ALL, DAILY, MONTHLY
    ) -> list[AdAnalytics]:
        """Get analytics for campaigns."""
        campaign_urns = ",".join([f"urn:li:sponsoredCampaign:{cid}" for cid in campaign_ids])

        params = {
            "q": "analytics",
            "pivot": "CAMPAIGN",
            "dateRange": f"(start:(year:{start_date.year},month:{start_date.month},day:{start_date.day}),end:(year:{end_date.year},month:{end_date.month},day:{end_date.day}))",
            "timeGranularity": granularity,
            "campaigns": f"List({campaign_urns})",
            "fields": "impressions,clicks,costInLocalCurrency,externalWebsiteConversions,oneClickLeads,leadGenerationMailContactInfoShares,videoViews,videoCompletions,totalEngagements,follows",
        }

        response = await self._request(
            "GET",
            "adAnalytics",
            params=params,
            use_rest_api=False,
        )

        results = []
        for item in response.get("elements", []):
            campaign_id = item.get("pivotValue", "").split(":")[-1]
            results.append(AdAnalytics.from_api(item, campaign_id, start_date, end_date))

        return results

    async def get_account_analytics(
        self,
        start_date: date,
        end_date: date,
    ) -> AdAnalytics:
        """Get analytics for the entire ad account."""
        params = {
            "q": "analytics",
            "pivot": "ACCOUNT",
            "dateRange": f"(start:(year:{start_date.year},month:{start_date.month},day:{start_date.day}),end:(year:{end_date.year},month:{end_date.month},day:{end_date.day}))",
            "accounts": f"List(urn:li:sponsoredAccount:{self.credentials.ad_account_id})",
            "fields": "impressions,clicks,costInLocalCurrency,externalWebsiteConversions,oneClickLeads,leadGenerationMailContactInfoShares,videoViews,videoCompletions,totalEngagements,follows",
        }

        response = await self._request(
            "GET",
            "adAnalytics",
            params=params,
            use_rest_api=False,
        )

        elements = response.get("elements", [{}])
        return AdAnalytics.from_api(
            elements[0] if elements else {},
            self.credentials.ad_account_id,
            start_date,
            end_date,
        )

    # Lead Gen Operations

    async def get_lead_gen_forms(self) -> list[LeadGenForm]:
        """Get lead gen forms for the ad account."""
        params = {
            "q": "account",
            "account": f"urn:li:sponsoredAccount:{self.credentials.ad_account_id}",
        }

        response = await self._request("GET", "leadGenForms", params=params)
        return [LeadGenForm.from_api(item) for item in response.get("elements", [])]

    async def get_leads(
        self,
        form_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[Lead]:
        """Get leads submitted to a form."""
        params = {
            "q": "form",
            "form": f"urn:li:leadGenForm:{form_id}",
        }

        if start_time:
            params["submittedAtRange"] = f"(start:{int(start_time.timestamp() * 1000)}"
            if end_time:
                params["submittedAtRange"] += f",end:{int(end_time.timestamp() * 1000)})"
            else:
                params["submittedAtRange"] += ")"

        response = await self._request("GET", "leadGenFormResponses", params=params)
        return [Lead.from_api(item) for item in response.get("elements", [])]

    # Audience Operations

    async def get_audience_segments(self) -> list[AudienceSegment]:
        """Get audience segments (matched audiences)."""
        params = {
            "q": "account",
            "account": f"urn:li:sponsoredAccount:{self.credentials.ad_account_id}",
        }

        response = await self._request("GET", "dmpSegments", params=params)
        return [AudienceSegment.from_api(item) for item in response.get("elements", [])]

    async def get_targeting_facets(self) -> dict[str, Any]:
        """Get available targeting facets (job titles, industries, etc.)."""
        response = await self._request(
            "GET",
            "adTargetingFacets",
            params={"q": "targetingFacets"},
        )
        return response

    # Conversion Tracking

    async def get_conversions(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Get conversion events."""
        params = {
            "q": "account",
            "account": f"urn:li:sponsoredAccount:{self.credentials.ad_account_id}",
            "dateRange": f"(start:(year:{start_date.year},month:{start_date.month},day:{start_date.day}),end:(year:{end_date.year},month:{end_date.month},day:{end_date.day}))",
        }

        response = await self._request("GET", "conversionTrackingPixels", params=params)
        return response.get("elements", [])


def get_mock_campaign() -> Campaign:
    """Get mock campaign for testing."""
    return Campaign(
        id="123456789",
        name="Test B2B Campaign",
        status=CampaignStatus.ACTIVE,
        campaign_group_id="987654321",
        account_id="111222333",
        campaign_type=CampaignType.SPONSORED_UPDATES,
        objective_type=ObjectiveType.LEAD_GENERATION,
        daily_budget=100.0,
        total_budget=3000.0,
        bid_strategy=BidStrategy.MAXIMUM_DELIVERY,
        targeting_criteria={
            "include": {
                "and": [
                    {"or": {"urn:li:adTargetingFacet:titles": ["12345", "67890"]}},
                    {"or": {"urn:li:adTargetingFacet:industries": ["1", "2"]}},
                ]
            }
        },
        created_at=datetime.now(),
    )


def get_mock_analytics() -> AdAnalytics:
    """Get mock analytics for testing."""
    return AdAnalytics(
        campaign_id="123456789",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        impressions=50000,
        clicks=1250,
        cost=2500.0,
        conversions=75,
        leads=45,
        video_views=0,
        video_completions=0,
        engagement=320,
        follows=15,
        ctr=2.5,
        cpc=2.0,
        cpm=50.0,
        conversion_rate=6.0,
        cost_per_lead=55.56,
    )
