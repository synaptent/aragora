"""
Google Ads Connector.

Integration with Google Ads API:
- Campaigns (search, display, video, shopping)
- Ad groups and ads
- Keywords and targeting
- Bidding strategies
- Reporting and metrics
- Conversions and audiences

Requires Google Ads API credentials and developer token.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import asyncio
import random

import httpx

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0
_MAX_DELAY = 30.0


class CampaignStatus(str, Enum):
    """Campaign status."""

    ENABLED = "ENABLED"
    PAUSED = "PAUSED"
    REMOVED = "REMOVED"


class CampaignType(str, Enum):
    """Campaign advertising channel type."""

    SEARCH = "SEARCH"
    DISPLAY = "DISPLAY"
    SHOPPING = "SHOPPING"
    VIDEO = "VIDEO"
    MULTI_CHANNEL = "MULTI_CHANNEL"
    LOCAL = "LOCAL"
    SMART = "SMART"
    PERFORMANCE_MAX = "PERFORMANCE_MAX"
    DEMAND_GEN = "DEMAND_GEN"


class AdGroupStatus(str, Enum):
    """Ad group status."""

    ENABLED = "ENABLED"
    PAUSED = "PAUSED"
    REMOVED = "REMOVED"


class AdStatus(str, Enum):
    """Ad status."""

    ENABLED = "ENABLED"
    PAUSED = "PAUSED"
    REMOVED = "REMOVED"


class KeywordMatchType(str, Enum):
    """Keyword match type."""

    EXACT = "EXACT"
    PHRASE = "PHRASE"
    BROAD = "BROAD"


class BiddingStrategyType(str, Enum):
    """Bidding strategy types."""

    MANUAL_CPC = "MANUAL_CPC"
    MANUAL_CPM = "MANUAL_CPM"
    MANUAL_CPV = "MANUAL_CPV"
    MAXIMIZE_CONVERSIONS = "MAXIMIZE_CONVERSIONS"
    MAXIMIZE_CONVERSION_VALUE = "MAXIMIZE_CONVERSION_VALUE"
    TARGET_CPA = "TARGET_CPA"
    TARGET_ROAS = "TARGET_ROAS"
    TARGET_SPEND = "TARGET_SPEND"
    TARGET_IMPRESSION_SHARE = "TARGET_IMPRESSION_SHARE"


@dataclass
class GoogleAdsCredentials:
    """Google Ads API credentials."""

    developer_token: str
    client_id: str
    client_secret: str
    refresh_token: str
    customer_id: str  # 10-digit customer ID (no dashes)
    login_customer_id: str | None = None  # For MCC accounts
    access_token: str | None = None
    base_url: str = "https://googleads.googleapis.com/v15"


@dataclass
class Campaign:
    """Google Ads campaign."""

    id: str
    name: str
    status: CampaignStatus
    advertising_channel_type: CampaignType
    budget_amount_micros: int = 0
    start_date: date | None = None
    end_date: date | None = None
    bidding_strategy_type: BiddingStrategyType | None = None
    target_cpa_micros: int | None = None
    target_roas: float | None = None
    optimization_score: float | None = None
    resource_name: str | None = None

    @property
    def budget_amount(self) -> Decimal:
        """Budget in standard currency units."""
        return Decimal(self.budget_amount_micros) / Decimal(1_000_000)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Campaign:
        """Create from API response."""
        campaign = data.get("campaign", data)
        return cls(
            id=campaign.get("id", ""),
            name=campaign.get("name", ""),
            status=CampaignStatus(campaign.get("status", "ENABLED")),
            advertising_channel_type=CampaignType(campaign.get("advertisingChannelType", "SEARCH")),
            budget_amount_micros=int(campaign.get("campaignBudget", {}).get("amountMicros", 0)),
            start_date=_parse_date(campaign.get("startDate")),
            end_date=_parse_date(campaign.get("endDate")),
            bidding_strategy_type=(
                BiddingStrategyType(campaign["biddingStrategyType"])
                if campaign.get("biddingStrategyType")
                else None
            ),
            target_cpa_micros=campaign.get("targetCpa", {}).get("targetCpaMicros"),
            target_roas=campaign.get("targetRoas", {}).get("targetRoas"),
            optimization_score=campaign.get("optimizationScore"),
            resource_name=campaign.get("resourceName"),
        )


@dataclass
class AdGroup:
    """Google Ads ad group."""

    id: str
    name: str
    campaign_id: str
    status: AdGroupStatus
    cpc_bid_micros: int | None = None
    cpm_bid_micros: int | None = None
    target_cpa_micros: int | None = None
    resource_name: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> AdGroup:
        """Create from API response."""
        ad_group = data.get("adGroup", data)
        return cls(
            id=ad_group.get("id", ""),
            name=ad_group.get("name", ""),
            campaign_id=ad_group.get("campaign", "").split("/")[-1],
            status=AdGroupStatus(ad_group.get("status", "ENABLED")),
            cpc_bid_micros=ad_group.get("cpcBidMicros"),
            cpm_bid_micros=ad_group.get("cpmBidMicros"),
            target_cpa_micros=ad_group.get("targetCpaMicros"),
            resource_name=ad_group.get("resourceName"),
        )


@dataclass
class Ad:
    """Google Ads ad."""

    id: str
    ad_group_id: str
    status: AdStatus
    type: str
    final_urls: list[str] = field(default_factory=list)
    headlines: list[str] = field(default_factory=list)
    descriptions: list[str] = field(default_factory=list)
    display_url: str | None = None
    resource_name: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Ad:
        """Create from API response."""
        ad_group_ad = data.get("adGroupAd", data)
        ad = ad_group_ad.get("ad", {})

        headlines = []
        descriptions = []

        # Handle responsive search ads
        if "responsiveSearchAd" in ad:
            rsa = ad["responsiveSearchAd"]
            headlines = [h.get("text", "") for h in rsa.get("headlines", [])]
            descriptions = [d.get("text", "") for d in rsa.get("descriptions", [])]

        return cls(
            id=ad.get("id", ""),
            ad_group_id=ad_group_ad.get("adGroup", "").split("/")[-1],
            status=AdStatus(ad_group_ad.get("status", "ENABLED")),
            type=ad.get("type", ""),
            final_urls=ad.get("finalUrls", []),
            headlines=headlines,
            descriptions=descriptions,
            display_url=ad.get("displayUrl"),
            resource_name=ad_group_ad.get("resourceName"),
        )


@dataclass
class Keyword:
    """Google Ads keyword."""

    id: str
    ad_group_id: str
    text: str
    match_type: KeywordMatchType
    status: str = "ENABLED"
    cpc_bid_micros: int | None = None
    quality_score: int | None = None
    resource_name: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Keyword:
        """Create from API response."""
        criterion = data.get("adGroupCriterion", data)
        keyword = criterion.get("keyword", {})
        return cls(
            id=criterion.get("criterionId", ""),
            ad_group_id=criterion.get("adGroup", "").split("/")[-1],
            text=keyword.get("text", ""),
            match_type=KeywordMatchType(keyword.get("matchType", "BROAD")),
            status=criterion.get("status", "ENABLED"),
            cpc_bid_micros=criterion.get("cpcBidMicros"),
            quality_score=criterion.get("qualityInfo", {}).get("qualityScore"),
            resource_name=criterion.get("resourceName"),
        )


@dataclass
class CampaignMetrics:
    """Campaign performance metrics."""

    campaign_id: str
    campaign_name: str
    impressions: int = 0
    clicks: int = 0
    cost_micros: int = 0
    conversions: float = 0
    conversions_value: float = 0
    ctr: float = 0
    average_cpc_micros: int = 0
    average_cpm_micros: int = 0
    conversion_rate: float = 0
    cost_per_conversion_micros: int = 0

    @property
    def cost(self) -> Decimal:
        """Cost in standard currency units."""
        return Decimal(self.cost_micros) / Decimal(1_000_000)

    @property
    def average_cpc(self) -> Decimal:
        """Average CPC in standard currency units."""
        return Decimal(self.average_cpc_micros) / Decimal(1_000_000)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> CampaignMetrics:
        """Create from API response."""
        campaign = data.get("campaign", {})
        metrics = data.get("metrics", {})
        return cls(
            campaign_id=campaign.get("id", ""),
            campaign_name=campaign.get("name", ""),
            impressions=int(metrics.get("impressions", 0)),
            clicks=int(metrics.get("clicks", 0)),
            cost_micros=int(metrics.get("costMicros", 0)),
            conversions=float(metrics.get("conversions", 0)),
            conversions_value=float(metrics.get("conversionsValue", 0)),
            ctr=float(metrics.get("ctr", 0)),
            average_cpc_micros=int(metrics.get("averageCpc", 0)),
            average_cpm_micros=int(metrics.get("averageCpm", 0)),
            conversion_rate=float(metrics.get("conversionsFromInteractionsRate", 0)),
            cost_per_conversion_micros=int(metrics.get("costPerConversion", 0)),
        )


@dataclass
class SearchTermMetrics:
    """Search term performance."""

    search_term: str
    campaign_id: str
    ad_group_id: str
    impressions: int = 0
    clicks: int = 0
    cost_micros: int = 0
    conversions: float = 0

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> SearchTermMetrics:
        """Create from API response."""
        segments = data.get("segments", {})
        campaign = data.get("campaign", {})
        ad_group = data.get("adGroup", {})
        metrics = data.get("metrics", {})
        return cls(
            search_term=segments.get("searchTermView", {}).get("searchTerm", ""),
            campaign_id=campaign.get("id", ""),
            ad_group_id=ad_group.get("id", ""),
            impressions=int(metrics.get("impressions", 0)),
            clicks=int(metrics.get("clicks", 0)),
            cost_micros=int(metrics.get("costMicros", 0)),
            conversions=float(metrics.get("conversions", 0)),
        )


class GoogleAdsError(Exception):
    """Google Ads API error."""

    def __init__(self, message: str, errors: list | None = None, request_id: str | None = None):
        super().__init__(message)
        self.errors = errors or []
        self.request_id = request_id


class GoogleAdsConnector:
    """
    Google Ads API connector.

    Provides integration with Google Ads for:
    - Campaign management
    - Ad group and ad management
    - Keyword management
    - Performance reporting
    - Conversion tracking
    """

    def __init__(self, credentials: GoogleAdsCredentials):
        self.credentials = credentials
        self._client: httpx.AsyncClient | None = None
        self._access_token: str | None = credentials.access_token
        self._token_expires_at: datetime | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.credentials.base_url,
                timeout=60.0,
            )
        return self._client

    async def _ensure_token(self) -> str:
        """Ensure we have a valid access token."""
        if (
            self._access_token
            and self._token_expires_at
            and datetime.now() < self._token_expires_at
        ):
            return self._access_token

        client = await self._get_client()
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self.credentials.client_id,
                "client_secret": self.credentials.client_secret,
                "refresh_token": self.credentials.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        data = response.json()

        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        from datetime import timedelta

        self._token_expires_at = datetime.now() + timedelta(seconds=expires_in - 60)

        return self._access_token

    def _get_headers(self, token: str) -> dict[str, str]:
        """Get request headers."""
        headers = {
            "Authorization": f"Bearer {token}",
            "developer-token": self.credentials.developer_token,
            "Content-Type": "application/json",
        }
        if self.credentials.login_customer_id:
            headers["login-customer-id"] = self.credentials.login_customer_id
        return headers

    async def _search(self, query: str) -> list[dict[str, Any]]:
        """Execute a Google Ads Query Language (GAQL) search with retry."""
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                token = await self._ensure_token()
                client = await self._get_client()

                response = await client.post(
                    f"/customers/{self.credentials.customer_id}/googleAds:search",
                    headers=self._get_headers(token),
                    json={"query": query},
                )

                if response.status_code == 429 and attempt < _MAX_RETRIES:
                    retry_after = float(
                        response.headers.get("Retry-After", _BASE_DELAY * (2**attempt))
                    )
                    delay = min(retry_after + random.uniform(0, retry_after * 0.3), _MAX_DELAY)
                    logger.warning(
                        "Google Ads rate limited, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 500 and attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Google Ads server error %d, retrying in %.1fs (attempt %d/%d)",
                        response.status_code,
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        error = error_data.get("error", {})
                        raise GoogleAdsError(
                            message=error.get("message", response.text),
                            errors=error.get("details", []),
                            request_id=response.headers.get("request-id"),
                        )
                    except ValueError:
                        raise GoogleAdsError(f"HTTP {response.status_code}: {response.text}")

                return response.json().get("results", [])

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Google Ads request error, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
            except GoogleAdsError:
                raise

        raise GoogleAdsError(f"Request failed after {_MAX_RETRIES + 1} attempts: {last_error}")

    async def _mutate(
        self, operations: list[dict[str, Any]], resource_type: str
    ) -> list[dict[str, Any]]:
        """Execute mutate operations."""
        token = await self._ensure_token()
        client = await self._get_client()

        response = await client.post(
            f"/customers/{self.credentials.customer_id}/{resource_type}:mutate",
            headers=self._get_headers(token),
            json={"operations": operations},
        )

        if response.status_code >= 400:
            try:
                error_data = response.json()
                error = error_data.get("error", {})
                raise GoogleAdsError(
                    message=error.get("message", response.text),
                    errors=error.get("details", []),
                )
            except ValueError:
                raise GoogleAdsError(f"HTTP {response.status_code}: {response.text}")

        return response.json().get("results", [])

    # =========================================================================
    # Campaigns
    # =========================================================================

    async def get_campaigns(
        self,
        status: CampaignStatus | None = None,
        campaign_type: CampaignType | None = None,
    ) -> list[Campaign]:
        """Get all campaigns."""
        query = """
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                campaign.advertising_channel_type,
                campaign.start_date,
                campaign.end_date,
                campaign.bidding_strategy_type,
                campaign.target_cpa.target_cpa_micros,
                campaign.target_roas.target_roas,
                campaign.optimization_score,
                campaign.resource_name,
                campaign_budget.amount_micros
            FROM campaign
        """

        conditions = []
        if status:
            conditions.append(f"campaign.status = '{status.value}'")
        if campaign_type:
            conditions.append(f"campaign.advertising_channel_type = '{campaign_type.value}'")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        results = await self._search(query)
        return [Campaign.from_api(r) for r in results]

    async def get_campaign(self, campaign_id: str) -> Campaign:
        """Get a single campaign."""
        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                campaign.advertising_channel_type,
                campaign.start_date,
                campaign.end_date,
                campaign.bidding_strategy_type,
                campaign.resource_name,
                campaign_budget.amount_micros
            FROM campaign
            WHERE campaign.id = {campaign_id}
        """  # internal query construction
        results = await self._search(query)
        if not results:
            raise GoogleAdsError(f"Campaign {campaign_id} not found")
        return Campaign.from_api(results[0])

    async def update_campaign_status(self, campaign_id: str, status: CampaignStatus) -> bool:
        """Update campaign status (enable/pause)."""
        operations = [
            {
                "update": {
                    "resourceName": f"customers/{self.credentials.customer_id}/campaigns/{campaign_id}",
                    "status": status.value,
                },
                "updateMask": "status",
            }
        ]
        await self._mutate(operations, "campaigns")
        return True

    async def update_campaign_budget(self, campaign_id: str, budget_micros: int) -> bool:
        """Update campaign daily budget."""
        # First get the budget resource name
        query = f"""
            SELECT campaign.campaign_budget
            FROM campaign
            WHERE campaign.id = {campaign_id}
        """  # internal query construction
        results = await self._search(query)
        if not results:
            raise GoogleAdsError(f"Campaign {campaign_id} not found")

        budget_resource = results[0].get("campaign", {}).get("campaignBudget", "")

        operations = [
            {
                "update": {
                    "resourceName": budget_resource,
                    "amountMicros": str(budget_micros),
                },
                "updateMask": "amount_micros",
            }
        ]
        await self._mutate(operations, "campaignBudgets")
        return True

    # =========================================================================
    # Ad Groups
    # =========================================================================

    async def get_ad_groups(self, campaign_id: str | None = None) -> list[AdGroup]:
        """Get ad groups, optionally filtered by campaign."""
        query = """
            SELECT
                ad_group.id,
                ad_group.name,
                ad_group.campaign,
                ad_group.status,
                ad_group.cpc_bid_micros,
                ad_group.cpm_bid_micros,
                ad_group.target_cpa_micros,
                ad_group.resource_name
            FROM ad_group
        """

        if campaign_id:
            query += f" WHERE ad_group.campaign = 'customers/{self.credentials.customer_id}/campaigns/{campaign_id}'"

        results = await self._search(query)
        return [AdGroup.from_api(r) for r in results]

    async def update_ad_group_status(self, ad_group_id: str, status: AdGroupStatus) -> bool:
        """Update ad group status."""
        operations = [
            {
                "update": {
                    "resourceName": f"customers/{self.credentials.customer_id}/adGroups/{ad_group_id}",
                    "status": status.value,
                },
                "updateMask": "status",
            }
        ]
        await self._mutate(operations, "adGroups")
        return True

    # =========================================================================
    # Ads
    # =========================================================================

    async def get_ads(self, ad_group_id: str | None = None) -> list[Ad]:
        """Get ads, optionally filtered by ad group."""
        query = """
            SELECT
                ad_group_ad.ad.id,
                ad_group_ad.ad_group,
                ad_group_ad.status,
                ad_group_ad.ad.type,
                ad_group_ad.ad.final_urls,
                ad_group_ad.ad.display_url,
                ad_group_ad.ad.responsive_search_ad.headlines,
                ad_group_ad.ad.responsive_search_ad.descriptions,
                ad_group_ad.resource_name
            FROM ad_group_ad
        """

        if ad_group_id:
            query += f" WHERE ad_group_ad.ad_group = 'customers/{self.credentials.customer_id}/adGroups/{ad_group_id}'"

        results = await self._search(query)
        return [Ad.from_api(r) for r in results]

    async def update_ad_status(self, ad_group_id: str, ad_id: str, status: AdStatus) -> bool:
        """Update ad status."""
        operations = [
            {
                "update": {
                    "resourceName": f"customers/{self.credentials.customer_id}/adGroupAds/{ad_group_id}~{ad_id}",
                    "status": status.value,
                },
                "updateMask": "status",
            }
        ]
        await self._mutate(operations, "adGroupAds")
        return True

    # =========================================================================
    # Keywords
    # =========================================================================

    async def get_keywords(self, ad_group_id: str) -> list[Keyword]:
        """Get keywords for an ad group."""
        query = f"""
            SELECT
                ad_group_criterion.criterion_id,
                ad_group_criterion.ad_group,
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.status,
                ad_group_criterion.cpc_bid_micros,
                ad_group_criterion.quality_info.quality_score,
                ad_group_criterion.resource_name
            FROM ad_group_criterion
            WHERE ad_group_criterion.ad_group = 'customers/{self.credentials.customer_id}/adGroups/{ad_group_id}'
            AND ad_group_criterion.type = 'KEYWORD'
        """  # internal query construction
        results = await self._search(query)
        return [Keyword.from_api(r) for r in results]

    async def add_keyword(
        self,
        ad_group_id: str,
        text: str,
        match_type: KeywordMatchType,
        cpc_bid_micros: int | None = None,
    ) -> str:
        """Add a keyword to an ad group. Returns the criterion ID."""
        operation: dict[str, Any] = {
            "create": {
                "adGroup": f"customers/{self.credentials.customer_id}/adGroups/{ad_group_id}",
                "keyword": {
                    "text": text,
                    "matchType": match_type.value,
                },
            }
        }

        if cpc_bid_micros:
            operation["create"]["cpcBidMicros"] = str(cpc_bid_micros)

        results = await self._mutate([operation], "adGroupCriteria")
        return results[0].get("resourceName", "").split("~")[-1] if results else ""

    async def update_keyword_bid(
        self, ad_group_id: str, criterion_id: str, cpc_bid_micros: int
    ) -> bool:
        """Update keyword CPC bid."""
        operations = [
            {
                "update": {
                    "resourceName": f"customers/{self.credentials.customer_id}/adGroupCriteria/{ad_group_id}~{criterion_id}",
                    "cpcBidMicros": str(cpc_bid_micros),
                },
                "updateMask": "cpc_bid_micros",
            }
        ]
        await self._mutate(operations, "adGroupCriteria")
        return True

    async def remove_keyword(self, ad_group_id: str, criterion_id: str) -> bool:
        """Remove a keyword."""
        operations = [
            {
                "remove": f"customers/{self.credentials.customer_id}/adGroupCriteria/{ad_group_id}~{criterion_id}"
            }
        ]
        await self._mutate(operations, "adGroupCriteria")
        return True

    # =========================================================================
    # Reporting
    # =========================================================================

    async def get_campaign_performance(
        self,
        start_date: date,
        end_date: date,
        campaign_ids: list[str] | None = None,
    ) -> list[CampaignMetrics]:
        """Get campaign performance metrics."""
        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value,
                metrics.ctr,
                metrics.average_cpc,
                metrics.average_cpm,
                metrics.conversions_from_interactions_rate,
                metrics.cost_per_conversion
            FROM campaign
            WHERE segments.date BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
        """  # internal query construction

        if campaign_ids:
            ids_str = ", ".join(campaign_ids)
            query += f" AND campaign.id IN ({ids_str})"

        results = await self._search(query)
        return [CampaignMetrics.from_api(r) for r in results]

    async def get_search_terms_report(
        self,
        start_date: date,
        end_date: date,
        campaign_id: str | None = None,
        min_impressions: int = 0,
    ) -> list[SearchTermMetrics]:
        """Get search terms performance report."""
        query = f"""
            SELECT
                search_term_view.search_term,
                campaign.id,
                ad_group.id,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions
            FROM search_term_view
            WHERE segments.date BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
            AND metrics.impressions > {min_impressions}
        """  # internal query construction

        if campaign_id:
            query += f" AND campaign.id = {campaign_id}"

        results = await self._search(query)
        return [SearchTermMetrics.from_api(r) for r in results]

    async def get_keyword_performance(
        self,
        start_date: date,
        end_date: date,
        ad_group_id: str,
    ) -> list[dict[str, Any]]:
        """Get keyword performance metrics."""
        query = f"""
            SELECT
                ad_group_criterion.criterion_id,
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.quality_info.quality_score,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.ctr,
                metrics.average_cpc
            FROM keyword_view
            WHERE ad_group_criterion.ad_group = 'customers/{self.credentials.customer_id}/adGroups/{ad_group_id}'
            AND segments.date BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
        """  # internal query construction
        return await self._search(query)

    # =========================================================================
    # Account Info
    # =========================================================================

    async def get_account_info(self) -> dict[str, Any]:
        """Get account information."""
        query = """
            SELECT
                customer.id,
                customer.descriptive_name,
                customer.currency_code,
                customer.time_zone,
                customer.manager
            FROM customer
            LIMIT 1
        """
        results = await self._search(query)
        return results[0] if results else {}

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> GoogleAdsConnector:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


def _parse_date(value: str | None) -> date | None:
    """Parse date string (YYYY-MM-DD)."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def get_mock_campaign() -> Campaign:
    """Get a mock campaign for testing."""
    return Campaign(
        id="12345678901",
        name="Brand Campaign",
        status=CampaignStatus.ENABLED,
        advertising_channel_type=CampaignType.SEARCH,
        budget_amount_micros=50_000_000,  # $50/day
        bidding_strategy_type=BiddingStrategyType.TARGET_CPA,
    )


def get_mock_metrics() -> CampaignMetrics:
    """Get mock campaign metrics for testing."""
    return CampaignMetrics(
        campaign_id="12345678901",
        campaign_name="Brand Campaign",
        impressions=10000,
        clicks=500,
        cost_micros=25_000_000,  # $25
        conversions=50,
        ctr=0.05,
    )
