"""
Google Analytics Connector.

Integration with Google Analytics Data API (GA4):
- Run reports (dimensions, metrics)
- Real-time data
- Metadata (available dimensions and metrics)
- Audience exports
- Custom dimensions

Requires Google service account or OAuth2 credentials.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import asyncio
import random

import httpx

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0
_MAX_DELAY = 30.0


class MetricAggregation(str, Enum):
    """Metric aggregation types."""

    TOTAL = "TOTAL"
    MINIMUM = "MINIMUM"
    MAXIMUM = "MAXIMUM"
    COUNT = "COUNT"


class OrderType(str, Enum):
    """Report ordering type."""

    ALPHANUMERIC = "ALPHANUMERIC"
    CASE_INSENSITIVE_ALPHANUMERIC = "CASE_INSENSITIVE_ALPHANUMERIC"
    NUMERIC = "NUMERIC"


@dataclass
class GoogleAnalyticsCredentials:
    """Google Analytics API credentials."""

    access_token: str | None = None
    property_id: str = ""  # GA4 property ID (e.g., "properties/123456789")
    base_url: str = "https://analyticsdata.googleapis.com/v1beta"


@dataclass
class Dimension:
    """Report dimension."""

    name: str
    expression: str | None = None

    def to_api(self) -> dict[str, Any]:
        """Convert to API format."""
        result: dict[str, Any] = {"name": self.name}
        if self.expression:
            result["dimensionExpression"] = {"concatenate": {"dimensionNames": [self.expression]}}
        return result


@dataclass
class Metric:
    """Report metric."""

    name: str
    expression: str | None = None

    def to_api(self) -> dict[str, Any]:
        """Convert to API format."""
        result: dict[str, Any] = {"name": self.name}
        if self.expression:
            result["expression"] = self.expression
        return result


@dataclass
class DateRange:
    """Report date range."""

    start_date: str  # YYYY-MM-DD or relative (e.g., "7daysAgo", "yesterday", "today")
    end_date: str
    name: str | None = None

    def to_api(self) -> dict[str, Any]:
        """Convert to API format."""
        result: dict[str, Any] = {
            "startDate": self.start_date,
            "endDate": self.end_date,
        }
        if self.name:
            result["name"] = self.name
        return result


@dataclass
class FilterExpression:
    """Report filter expression."""

    field_name: str
    string_filter: dict[str, Any] | None = None
    in_list_filter: dict[str, Any] | None = None
    numeric_filter: dict[str, Any] | None = None
    between_filter: dict[str, Any] | None = None

    def to_api(self) -> dict[str, Any]:
        """Convert to API format."""
        filter_dict: dict[str, Any] = {"fieldName": self.field_name}
        if self.string_filter:
            filter_dict["stringFilter"] = self.string_filter
        elif self.in_list_filter:
            filter_dict["inListFilter"] = self.in_list_filter
        elif self.numeric_filter:
            filter_dict["numericFilter"] = self.numeric_filter
        elif self.between_filter:
            filter_dict["betweenFilter"] = self.between_filter
        return {"filter": filter_dict}


@dataclass
class DimensionHeader:
    """Dimension header in response."""

    name: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> DimensionHeader:
        return cls(name=data.get("name", ""))


@dataclass
class MetricHeader:
    """Metric header in response."""

    name: str
    type: str = "TYPE_INTEGER"

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> MetricHeader:
        return cls(
            name=data.get("name", ""),
            type=data.get("type", "TYPE_INTEGER"),
        )


@dataclass
class Row:
    """Report data row."""

    dimension_values: list[str]
    metric_values: list[str | float]

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Row:
        return cls(
            dimension_values=[d.get("value", "") for d in data.get("dimensionValues", [])],
            metric_values=[m.get("value", "") for m in data.get("metricValues", [])],
        )


@dataclass
class ReportResponse:
    """GA4 report response."""

    dimension_headers: list[DimensionHeader] = field(default_factory=list)
    metric_headers: list[MetricHeader] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    row_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    property_quota: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ReportResponse:
        return cls(
            dimension_headers=[
                DimensionHeader.from_api(d) for d in data.get("dimensionHeaders", [])
            ],
            metric_headers=[MetricHeader.from_api(m) for m in data.get("metricHeaders", [])],
            rows=[Row.from_api(r) for r in data.get("rows", [])],
            row_count=data.get("rowCount", len(data.get("rows", []))),
            metadata=data.get("metadata", {}),
            property_quota=data.get("propertyQuota", {}),
        )

    def to_dataframe_dict(self) -> dict[str, list[Any]]:
        """Convert to dictionary format suitable for pandas DataFrame."""
        result: dict[str, list[Any]] = {}

        # Add dimension columns
        for i, header in enumerate(self.dimension_headers):
            result[header.name] = [
                row.dimension_values[i] if i < len(row.dimension_values) else None
                for row in self.rows
            ]

        # Add metric columns
        for i, m_header in enumerate(self.metric_headers):
            result[m_header.name] = [
                row.metric_values[i] if i < len(row.metric_values) else None for row in self.rows
            ]

        return result


@dataclass
class RealTimeReport:
    """Real-time report response."""

    dimension_headers: list[DimensionHeader] = field(default_factory=list)
    metric_headers: list[MetricHeader] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    row_count: int = 0

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> RealTimeReport:
        return cls(
            dimension_headers=[
                DimensionHeader.from_api(d) for d in data.get("dimensionHeaders", [])
            ],
            metric_headers=[MetricHeader.from_api(m) for m in data.get("metricHeaders", [])],
            rows=[Row.from_api(r) for r in data.get("rows", [])],
            row_count=data.get("rowCount", len(data.get("rows", []))),
        )


class GoogleAnalyticsError(Exception):
    """Google Analytics API error."""

    def __init__(
        self, message: str, status_code: int | None = None, error_details: dict | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_details = error_details or {}


class GoogleAnalyticsConnector:
    """
    Google Analytics Data API (GA4) connector.

    Provides integration with GA4 for:
    - Running standard reports
    - Real-time data access
    - Metadata exploration
    - Batch reporting
    """

    def __init__(self, credentials: GoogleAnalyticsCredentials):
        self.credentials = credentials
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if self.credentials.access_token:
                headers["Authorization"] = f"Bearer {self.credentials.access_token}"

            self._client = httpx.AsyncClient(
                base_url=self.credentials.base_url,
                headers=headers,
                timeout=60.0,
            )
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict | None = None,
    ) -> dict[str, Any]:
        """Make API request with retry and exponential backoff."""
        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await client.request(method, path, json=json_data)

                if response.status_code == 429 and attempt < _MAX_RETRIES:
                    retry_after = float(
                        response.headers.get("Retry-After", _BASE_DELAY * (2**attempt))
                    )
                    jitter = random.uniform(0, retry_after * 0.3)
                    delay = min(retry_after + jitter, _MAX_DELAY)
                    logger.warning(
                        "Google Analytics rate limited, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 500 and attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Google Analytics server error %d, retrying in %.1fs (attempt %d/%d)",
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
                        raise GoogleAnalyticsError(
                            message=error.get("message", response.text),
                            status_code=response.status_code,
                            error_details=error,
                        )
                    except ValueError:
                        raise GoogleAnalyticsError(
                            f"HTTP {response.status_code}: {response.text}", response.status_code
                        )

                return response.json()

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2**attempt) + random.uniform(0, 1), _MAX_DELAY)
                    logger.warning(
                        "Google Analytics request timeout, retrying in %.1fs (attempt %d/%d)",
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
                        "Google Analytics connection error, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
            except GoogleAnalyticsError:
                raise

        raise GoogleAnalyticsError(
            f"Request failed after {_MAX_RETRIES + 1} attempts: {last_error}",
            status_code=None,
        )

    # =========================================================================
    # Reports
    # =========================================================================

    async def run_report(
        self,
        dimensions: list[str | Dimension],
        metrics: list[str | Metric],
        date_ranges: list[DateRange] | None = None,
        dimension_filter: FilterExpression | None = None,
        metric_filter: FilterExpression | None = None,
        order_bys: list[dict[str, Any]] | None = None,
        limit: int = 10000,
        offset: int = 0,
        keep_empty_rows: bool = False,
        return_property_quota: bool = False,
    ) -> ReportResponse:
        """
        Run a report.

        dimensions: List of dimension names (e.g., ["city", "country"]) or Dimension objects
        metrics: List of metric names (e.g., ["activeUsers", "sessions"]) or Metric objects
        """
        # Convert string dimensions/metrics to objects
        dim_list = [d if isinstance(d, Dimension) else Dimension(name=d) for d in dimensions]
        metric_list = [m if isinstance(m, Metric) else Metric(name=m) for m in metrics]

        # Default to last 28 days if no date range
        if not date_ranges:
            date_ranges = [DateRange(start_date="28daysAgo", end_date="today")]

        request_body: dict[str, Any] = {
            "dimensions": [d.to_api() for d in dim_list],
            "metrics": [m.to_api() for m in metric_list],
            "dateRanges": [dr.to_api() for dr in date_ranges],
            "limit": limit,
            "offset": offset,
            "keepEmptyRows": keep_empty_rows,
            "returnPropertyQuota": return_property_quota,
        }

        if dimension_filter:
            request_body["dimensionFilter"] = dimension_filter.to_api()
        if metric_filter:
            request_body["metricFilter"] = metric_filter.to_api()
        if order_bys:
            request_body["orderBys"] = order_bys

        data = await self._request(
            "POST",
            f"/{self.credentials.property_id}:runReport",
            json_data=request_body,
        )
        return ReportResponse.from_api(data)

    async def run_pivot_report(
        self,
        dimensions: list[str | Dimension],
        metrics: list[str | Metric],
        pivots: list[dict[str, Any]],
        date_ranges: list[DateRange] | None = None,
    ) -> ReportResponse:
        """Run a pivot report."""
        dim_list = [d if isinstance(d, Dimension) else Dimension(name=d) for d in dimensions]
        metric_list = [m if isinstance(m, Metric) else Metric(name=m) for m in metrics]

        if not date_ranges:
            date_ranges = [DateRange(start_date="28daysAgo", end_date="today")]

        request_body: dict[str, Any] = {
            "dimensions": [d.to_api() for d in dim_list],
            "metrics": [m.to_api() for m in metric_list],
            "dateRanges": [dr.to_api() for dr in date_ranges],
            "pivots": pivots,
        }

        data = await self._request(
            "POST",
            f"/{self.credentials.property_id}:runPivotReport",
            json_data=request_body,
        )
        return ReportResponse.from_api(data)

    async def batch_run_reports(
        self,
        requests: list[dict[str, Any]],
    ) -> list[ReportResponse]:
        """Run multiple reports in a batch."""
        data = await self._request(
            "POST",
            f"/{self.credentials.property_id}:batchRunReports",
            json_data={"requests": requests},
        )
        return [ReportResponse.from_api(r) for r in data.get("reports", [])]

    # =========================================================================
    # Real-time
    # =========================================================================

    async def run_realtime_report(
        self,
        dimensions: list[str | Dimension] | None = None,
        metrics: list[str | Metric] | None = None,
        dimension_filter: FilterExpression | None = None,
        metric_filter: FilterExpression | None = None,
        limit: int = 10000,
        minute_ranges: list[dict[str, Any]] | None = None,
    ) -> RealTimeReport:
        """
        Run a real-time report.

        Default returns active users in the last 30 minutes.
        """
        # Default dimensions and metrics for real-time
        if not dimensions:
            dimensions = ["country"]
        if not metrics:
            metrics = ["activeUsers"]

        dim_list = [d if isinstance(d, Dimension) else Dimension(name=d) for d in dimensions]
        metric_list = [m if isinstance(m, Metric) else Metric(name=m) for m in metrics]

        request_body: dict[str, Any] = {
            "dimensions": [d.to_api() for d in dim_list],
            "metrics": [m.to_api() for m in metric_list],
            "limit": limit,
        }

        if dimension_filter:
            request_body["dimensionFilter"] = dimension_filter.to_api()
        if metric_filter:
            request_body["metricFilter"] = metric_filter.to_api()
        if minute_ranges:
            request_body["minuteRanges"] = minute_ranges

        data = await self._request(
            "POST",
            f"/{self.credentials.property_id}:runRealtimeReport",
            json_data=request_body,
        )
        return RealTimeReport.from_api(data)

    # =========================================================================
    # Metadata
    # =========================================================================

    async def get_metadata(self) -> dict[str, Any]:
        """Get available dimensions and metrics for the property."""
        data = await self._request(
            "GET",
            f"/{self.credentials.property_id}/metadata",
        )
        return data

    async def get_available_dimensions(self) -> list[dict[str, Any]]:
        """Get list of available dimensions."""
        metadata = await self.get_metadata()
        return metadata.get("dimensions", [])

    async def get_available_metrics(self) -> list[dict[str, Any]]:
        """Get list of available metrics."""
        metadata = await self.get_metadata()
        return metadata.get("metrics", [])

    # =========================================================================
    # Convenience methods
    # =========================================================================

    async def get_page_views(
        self,
        start_date: str = "28daysAgo",
        end_date: str = "today",
        page_path: str | None = None,
    ) -> ReportResponse:
        """Get page views report."""
        dimensions: list[str | Dimension] = ["pagePath", "pageTitle"]
        metrics: list[str | Metric] = ["screenPageViews", "averageSessionDuration", "bounceRate"]

        dimension_filter = None
        if page_path:
            dimension_filter = FilterExpression(
                field_name="pagePath",
                string_filter={"matchType": "CONTAINS", "value": page_path},
            )

        return await self.run_report(
            dimensions=dimensions,
            metrics=metrics,
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimension_filter=dimension_filter,
            order_bys=[{"metric": {"metricName": "screenPageViews"}, "desc": True}],
        )

    async def get_traffic_sources(
        self,
        start_date: str = "28daysAgo",
        end_date: str = "today",
    ) -> ReportResponse:
        """Get traffic sources report."""
        return await self.run_report(
            dimensions=["sessionSource", "sessionMedium"],
            metrics=["sessions", "totalUsers", "bounceRate"],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            order_bys=[{"metric": {"metricName": "sessions"}, "desc": True}],
        )

    async def get_user_demographics(
        self,
        start_date: str = "28daysAgo",
        end_date: str = "today",
    ) -> ReportResponse:
        """Get user demographics report."""
        return await self.run_report(
            dimensions=["country", "city"],
            metrics=["activeUsers", "sessions", "engagedSessions"],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            order_bys=[{"metric": {"metricName": "activeUsers"}, "desc": True}],
        )

    async def get_device_breakdown(
        self,
        start_date: str = "28daysAgo",
        end_date: str = "today",
    ) -> ReportResponse:
        """Get device category breakdown."""
        return await self.run_report(
            dimensions=["deviceCategory"],
            metrics=["activeUsers", "sessions", "screenPageViews"],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        )

    async def get_active_users_now(self) -> int:
        """Get current active users count."""
        report = await self.run_realtime_report(
            dimensions=[],
            metrics=["activeUsers"],
        )
        if report.rows:
            return int(report.rows[0].metric_values[0])
        return 0

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> GoogleAnalyticsConnector:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


def get_mock_report() -> ReportResponse:
    """Get a mock report for testing."""
    return ReportResponse(
        dimension_headers=[DimensionHeader(name="country"), DimensionHeader(name="city")],
        metric_headers=[MetricHeader(name="activeUsers", type="TYPE_INTEGER")],
        rows=[
            Row(dimension_values=["United States", "New York"], metric_values=["1000"]),
            Row(dimension_values=["United Kingdom", "London"], metric_values=["500"]),
        ],
        row_count=2,
    )
