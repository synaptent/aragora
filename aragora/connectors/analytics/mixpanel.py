"""
Mixpanel Connector.

Integration with Mixpanel Analytics API:
- Events (track, query)
- User profiles (engage API)
- Reports (insights, funnels, retention)
- Exports (raw data)
- Cohorts

Requires Mixpanel project token and API secret.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import random
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0
_MAX_DELAY = 30.0


class Unit(str, Enum):
    """Time unit for reports."""

    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class EventType(str, Enum):
    """Event type filters."""

    GENERAL = "general"
    UNIQUE = "unique"
    AVERAGE = "average"


@dataclass
class MixpanelCredentials:
    """Mixpanel API credentials."""

    project_token: str
    api_secret: str
    project_id: str | None = None  # Required for some API endpoints
    service_account_username: str | None = None
    service_account_secret: str | None = None
    data_residency: str = "US"  # US or EU

    @property
    def base_url(self) -> str:
        if self.data_residency == "EU":
            return "https://eu.mixpanel.com"
        return "https://mixpanel.com"

    @property
    def data_url(self) -> str:
        if self.data_residency == "EU":
            return "https://data-eu.mixpanel.com"
        return "https://data.mixpanel.com"

    @property
    def basic_auth(self) -> str:
        """Get Basic auth header for API secret."""
        credentials = f"{self.api_secret}:"
        return base64.b64encode(credentials.encode()).decode()


@dataclass
class Event:
    """Mixpanel event."""

    event: str
    properties: dict[str, Any] = field(default_factory=dict)
    time: datetime | None = None

    def to_api(self) -> dict[str, Any]:
        """Convert to API format for tracking."""
        props = dict(self.properties)
        if self.time:
            props["time"] = int(self.time.timestamp())
        return {
            "event": self.event,
            "properties": props,
        }


@dataclass
class UserProfile:
    """Mixpanel user profile."""

    distinct_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    first_seen: datetime | None = None
    last_seen: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> UserProfile:
        """Create from API response."""
        results = data.get("$properties", data)
        return cls(
            distinct_id=data.get("$distinct_id", ""),
            properties=results,
            first_seen=_parse_datetime(results.get("$created")),
            last_seen=_parse_datetime(results.get("$last_seen")),
        )


@dataclass
class InsightResult:
    """Mixpanel insights query result."""

    series: dict[str, list[Any]] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> InsightResult:
        """Create from API response."""
        series_data = data.get("series", {})
        return cls(
            series=series_data,
            labels=list(series_data.keys()),
            dates=data.get("dates", []),
        )


@dataclass
class FunnelResult:
    """Funnel analysis result."""

    steps: list[dict[str, Any]] = field(default_factory=list)
    overall_conversion_rate: float = 0.0

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> FunnelResult:
        """Create from API response."""
        meta = data.get("meta", {})
        return cls(
            steps=data.get("data", {}).get("steps", []),
            overall_conversion_rate=meta.get("overall_conversion_rate", 0.0),
        )


@dataclass
class RetentionResult:
    """Retention analysis result."""

    data: list[dict[str, Any]] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> RetentionResult:
        """Create from API response."""
        return cls(
            data=data.get("data", []),
            dates=data.get("dates", []),
        )


@dataclass
class Cohort:
    """Mixpanel cohort."""

    id: int
    name: str
    description: str | None = None
    count: int = 0
    created: datetime | None = None
    data_group_id: int | None = None
    project_id: int | None = None
    is_visible: bool = True

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Cohort:
        """Create from API response."""
        return cls(
            id=data.get("id", 0),
            name=data.get("name", ""),
            description=data.get("description"),
            count=data.get("count", 0),
            created=_parse_datetime(data.get("created")),
            data_group_id=data.get("data_group_id"),
            project_id=data.get("project_id"),
            is_visible=data.get("is_visible", True),
        )


class MixpanelError(Exception):
    """Mixpanel API error."""

    def __init__(
        self, message: str, status_code: int | None = None, error_details: dict | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_details = error_details or {}


class MixpanelConnector:
    """
    Mixpanel Analytics API connector.

    Provides integration with Mixpanel for:
    - Event tracking
    - User profile management
    - Reports (insights, funnels, retention)
    - Data exports
    """

    def __init__(self, credentials: MixpanelCredentials):
        self.credentials = credentials
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=60.0,
            )
        return self._client

    async def _request(
        self,
        method: str,
        url: str,
        params: dict | None = None,
        json_data: dict | list | None = None,
        use_service_account: bool = False,
    ) -> dict[str, Any] | list[Any]:
        """Make API request with retry and exponential backoff."""
        client = await self._get_client()

        headers = dict(client.headers)
        if use_service_account and self.credentials.service_account_username:
            auth = f"{self.credentials.service_account_username}:{self.credentials.service_account_secret}"
            headers["Authorization"] = f"Basic {base64.b64encode(auth.encode()).decode()}"
        else:
            headers["Authorization"] = f"Basic {self.credentials.basic_auth}"

        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_data,
                    headers=headers,
                )

                if response.status_code == 429 and attempt < _MAX_RETRIES:
                    retry_after = float(
                        response.headers.get("Retry-After", _BASE_DELAY * (2**attempt))
                    )
                    jitter = random.uniform(0, retry_after * 0.3)
                    delay = min(retry_after + jitter, _MAX_DELAY)
                    logger.warning(
                        "Mixpanel rate limited, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 500 and attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Mixpanel server error %d, retrying in %.1fs (attempt %d/%d)",
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
                        raise MixpanelError(
                            message=error_data.get("error", response.text),
                            status_code=response.status_code,
                            error_details=error_data,
                        )
                    except ValueError:
                        raise MixpanelError(
                            f"HTTP {response.status_code}: {response.text}", response.status_code
                        )

                return response.json()

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Mixpanel request timeout, retrying in %.1fs (attempt %d/%d)",
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
                        "Mixpanel connection error, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
            except MixpanelError:
                raise

        raise MixpanelError(
            f"Request failed after {_MAX_RETRIES + 1} attempts: {last_error}",
            status_code=None,
        )

    # =========================================================================
    # Event Tracking
    # =========================================================================

    async def track(
        self,
        event: str,
        distinct_id: str,
        properties: dict[str, Any] | None = None,
        time: datetime | None = None,
    ) -> bool:
        """Track a single event."""
        props = properties or {}
        props["distinct_id"] = distinct_id
        props["token"] = self.credentials.project_token

        if time:
            props["time"] = int(time.timestamp())

        event_data = {"event": event, "properties": props}

        url = f"{self.credentials.base_url}/track"
        data = await self._request("POST", url, json_data=[event_data])

        return data.get("status", 0) == 1 if isinstance(data, dict) else True

    async def track_batch(self, events: list[Event], distinct_id: str) -> bool:
        """Track multiple events in a batch."""
        batch = []
        for event in events:
            props = dict(event.properties)
            props["distinct_id"] = distinct_id
            props["token"] = self.credentials.project_token
            if event.time:
                props["time"] = int(event.time.timestamp())
            batch.append({"event": event.event, "properties": props})

        url = f"{self.credentials.base_url}/track"
        data = await self._request("POST", url, json_data=batch)

        return data.get("status", 0) == 1 if isinstance(data, dict) else True

    async def import_events(
        self,
        events: list[Event],
    ) -> dict[str, Any]:
        """Import historical events (uses import endpoint)."""
        batch = [e.to_api() for e in events]

        url = f"{self.credentials.base_url}/import"
        params = {"project_id": self.credentials.project_id}

        data = await self._request(
            "POST", url, params=params, json_data=batch, use_service_account=True
        )
        return data if isinstance(data, dict) else {"status": "ok"}

    # =========================================================================
    # User Profiles (Engage)
    # =========================================================================

    async def set_user_profile(
        self,
        distinct_id: str,
        properties: dict[str, Any],
    ) -> bool:
        """Set user profile properties."""
        profile_data = {
            "$token": self.credentials.project_token,
            "$distinct_id": distinct_id,
            "$set": properties,
        }

        url = f"{self.credentials.base_url}/engage"
        data = await self._request("POST", url, json_data=[profile_data])

        return data.get("status", 0) == 1 if isinstance(data, dict) else True

    async def set_user_profile_once(
        self,
        distinct_id: str,
        properties: dict[str, Any],
    ) -> bool:
        """Set user profile properties only if not already set."""
        profile_data = {
            "$token": self.credentials.project_token,
            "$distinct_id": distinct_id,
            "$set_once": properties,
        }

        url = f"{self.credentials.base_url}/engage"
        data = await self._request("POST", url, json_data=[profile_data])

        return data.get("status", 0) == 1 if isinstance(data, dict) else True

    async def increment_user_property(
        self,
        distinct_id: str,
        property_name: str,
        amount: int | float = 1,
    ) -> bool:
        """Increment a numeric user property."""
        profile_data = {
            "$token": self.credentials.project_token,
            "$distinct_id": distinct_id,
            "$add": {property_name: amount},
        }

        url = f"{self.credentials.base_url}/engage"
        data = await self._request("POST", url, json_data=[profile_data])

        return data.get("status", 0) == 1 if isinstance(data, dict) else True

    async def append_to_user_list(
        self,
        distinct_id: str,
        property_name: str,
        values: list[Any],
    ) -> bool:
        """Append values to a list property."""
        profile_data = {
            "$token": self.credentials.project_token,
            "$distinct_id": distinct_id,
            "$union": {property_name: values},
        }

        url = f"{self.credentials.base_url}/engage"
        data = await self._request("POST", url, json_data=[profile_data])

        return data.get("status", 0) == 1 if isinstance(data, dict) else True

    async def delete_user_profile(self, distinct_id: str) -> bool:
        """Delete a user profile."""
        profile_data = {
            "$token": self.credentials.project_token,
            "$distinct_id": distinct_id,
            "$delete": "",
        }

        url = f"{self.credentials.base_url}/engage"
        data = await self._request("POST", url, json_data=[profile_data])

        return data.get("status", 0) == 1 if isinstance(data, dict) else True

    # =========================================================================
    # Insights / Queries
    # =========================================================================

    async def query_insights(
        self,
        event: str,
        from_date: date,
        to_date: date,
        unit: Unit = Unit.DAY,
        event_type: EventType = EventType.GENERAL,
        where: str | None = None,
        group_by: list[str] | None = None,
    ) -> InsightResult:
        """Query insights for an event."""
        params: dict[str, Any] = {
            "project_id": self.credentials.project_id,
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "event": event,
            "unit": unit.value,
            "type": event_type.value,
        }

        if where:
            params["where"] = where
        if group_by:
            params["on"] = f'properties["{group_by[0]}"]'

        url = f"{self.credentials.data_url}/api/2.0/insights"
        data = await self._request("GET", url, params=params, use_service_account=True)

        return InsightResult.from_api(data if isinstance(data, dict) else {})

    async def query_events(
        self,
        from_date: date,
        to_date: date,
        event: str | None = None,
        where: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query raw events data."""
        params: dict[str, Any] = {
            "project_id": self.credentials.project_id,
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "limit": limit,
        }

        if event:
            params["event"] = f'["{event}"]'
        if where:
            params["where"] = where

        url = f"{self.credentials.data_url}/api/2.0/export"
        data = await self._request("GET", url, params=params, use_service_account=True)

        return data if isinstance(data, list) else []

    async def get_event_names(
        self,
        event_type: str = "general",
        limit: int = 255,
    ) -> list[str]:
        """Get list of event names in the project."""
        params: dict[str, Any] = {
            "project_id": self.credentials.project_id,
            "type": event_type,
            "limit": limit,
        }

        url = f"{self.credentials.data_url}/api/2.0/events/names"
        data = await self._request("GET", url, params=params, use_service_account=True)

        return data if isinstance(data, list) else []

    async def get_event_properties(
        self,
        event: str,
        limit: int = 255,
    ) -> list[str]:
        """Get list of properties for an event."""
        params: dict[str, Any] = {
            "project_id": self.credentials.project_id,
            "event": event,
            "limit": limit,
        }

        url = f"{self.credentials.data_url}/api/2.0/events/properties"
        data = await self._request("GET", url, params=params, use_service_account=True)

        return data if isinstance(data, list) else []

    # =========================================================================
    # Funnels
    # =========================================================================

    async def query_funnel(
        self,
        funnel_id: int,
        from_date: date,
        to_date: date,
        unit: Unit = Unit.DAY,
        where: str | None = None,
    ) -> FunnelResult:
        """Query a saved funnel."""
        params: dict[str, Any] = {
            "project_id": self.credentials.project_id,
            "funnel_id": funnel_id,
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "unit": unit.value,
        }

        if where:
            params["where"] = where

        url = f"{self.credentials.data_url}/api/2.0/funnels"
        data = await self._request("GET", url, params=params, use_service_account=True)

        return FunnelResult.from_api(data if isinstance(data, dict) else {})

    async def list_funnels(self) -> list[dict[str, Any]]:
        """List all saved funnels."""
        params = {"project_id": self.credentials.project_id}

        url = f"{self.credentials.data_url}/api/2.0/funnels/list"
        data = await self._request("GET", url, params=params, use_service_account=True)

        return data if isinstance(data, list) else []

    # =========================================================================
    # Retention
    # =========================================================================

    async def query_retention(
        self,
        from_date: date,
        to_date: date,
        born_event: str,
        retention_event: str | None = None,
        unit: Unit = Unit.DAY,
        retention_type: str = "compounded",
        born_where: str | None = None,
        retention_where: str | None = None,
    ) -> RetentionResult:
        """Query retention data."""
        params: dict[str, Any] = {
            "project_id": self.credentials.project_id,
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "born_event": born_event,
            "unit": unit.value,
            "retention_type": retention_type,
        }

        if retention_event:
            params["event"] = retention_event
        if born_where:
            params["born_where"] = born_where
        if retention_where:
            params["where"] = retention_where

        url = f"{self.credentials.data_url}/api/2.0/retention"
        data = await self._request("GET", url, params=params, use_service_account=True)

        return RetentionResult.from_api(data if isinstance(data, dict) else {})

    # =========================================================================
    # Cohorts
    # =========================================================================

    async def list_cohorts(self) -> list[Cohort]:
        """List all cohorts."""
        params = {"project_id": self.credentials.project_id}

        url = f"{self.credentials.data_url}/api/2.0/cohorts/list"
        data = await self._request("GET", url, params=params, use_service_account=True)

        cohorts = data if isinstance(data, list) else []
        return [Cohort.from_api(c) for c in cohorts]

    async def get_cohort(self, cohort_id: int) -> list[dict[str, Any]]:
        """Get users in a cohort."""
        params: dict[str, Any] = {
            "project_id": self.credentials.project_id,
            "id": cohort_id,
        }

        url = f"{self.credentials.data_url}/api/2.0/engage"
        data = await self._request("GET", url, params=params, use_service_account=True)

        return data.get("results", []) if isinstance(data, dict) else []

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> MixpanelConnector:
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


def get_mock_event() -> Event:
    """Get a mock event for testing."""
    return Event(
        event="Button Clicked",
        properties={
            "button_name": "Sign Up",
            "page": "/home",
        },
        time=datetime.now(),
    )


def get_mock_insight_result() -> InsightResult:
    """Get a mock insight result for testing."""
    return InsightResult(
        series={"Button Clicked": [100, 150, 200, 180, 220]},
        labels=["Button Clicked"],
        dates=["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
    )
