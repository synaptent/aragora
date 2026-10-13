#!/usr/bin/env python3
"""
Load testing framework for Aragora API endpoints.

Sends concurrent HTTP requests to key API endpoints, measures latency
(p50, p95, p99), throughput, and error rates. Supports configurable
concurrency levels and duration. Generates a JSON report.

Usage:
    # Run against local server with defaults (10 concurrent, 30s)
    python scripts/load_test.py

    # Custom concurrency and duration
    python scripts/load_test.py --concurrency 50 --duration 60

    # Target a remote server
    python scripts/load_test.py --base-url https://api.aragora.example.com

    # Save report to file
    python scripts/load_test.py --output report.json

    # Target specific endpoints only
    python scripts/load_test.py --endpoints /api/v1/health /api/v1/slo/status

Environment Variables:
    ARAGORA_LOAD_TEST_BASE_URL: Override base URL (same as --base-url)
    ARAGORA_API_TOKEN: Bearer token for authenticated endpoints
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Default endpoints to test
DEFAULT_ENDPOINTS = [
    "/api/v1/health",
    "/api/v1/slo/status",
    "/api/v1/slo/budget",
    "/api/v1/slos/status",
    "/api/v1/slos/targets",
]


@dataclass
class RequestResult:
    """Result of a single HTTP request."""

    endpoint: str
    status_code: int
    latency_ms: float
    success: bool
    error: str | None = None
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class EndpointStats:
    """Aggregated statistics for a single endpoint."""

    endpoint: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def error_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.failed_requests / self.total_requests

    @property
    def throughput_rps(self) -> float:
        """Requests per second (computed externally based on duration)."""
        return 0.0  # Computed in report generation

    def percentile(self, pct: float) -> float:
        """Calculate percentile of latency values."""
        if not self.latencies_ms:
            return 0.0
        sorted_vals = sorted(self.latencies_ms)
        idx = (pct / 100.0) * (len(sorted_vals) - 1)
        lower = int(idx)
        upper = min(lower + 1, len(sorted_vals) - 1)
        frac = idx - lower
        return sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac

    def to_dict(self, duration_seconds: float) -> dict[str, Any]:
        """Convert to dictionary for JSON report."""
        rps = self.total_requests / max(duration_seconds, 0.001)
        return {
            "endpoint": self.endpoint,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "error_rate": round(self.error_rate, 6),
            "throughput_rps": round(rps, 2),
            "latency_ms": {
                "p50": round(self.percentile(50), 2),
                "p95": round(self.percentile(95), 2),
                "p99": round(self.percentile(99), 2),
                "min": round(min(self.latencies_ms), 2) if self.latencies_ms else 0.0,
                "max": round(max(self.latencies_ms), 2) if self.latencies_ms else 0.0,
                "avg": (
                    round(sum(self.latencies_ms) / len(self.latencies_ms), 2)
                    if self.latencies_ms
                    else 0.0
                ),
            },
        }


@dataclass
class LoadTestReport:
    """Complete load test report."""

    base_url: str
    concurrency: int
    duration_seconds: float
    actual_duration_seconds: float
    endpoints: list[dict[str, Any]]
    summary: dict[str, Any]
    started_at: str
    completed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "concurrency": self.concurrency,
            "target_duration_seconds": self.duration_seconds,
            "actual_duration_seconds": round(self.actual_duration_seconds, 2),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "endpoints": self.endpoints,
            "summary": self.summary,
        }


async def _send_request(
    session: Any,
    base_url: str,
    endpoint: str,
    headers: dict[str, str],
) -> RequestResult:
    """Send a single HTTP GET request and measure latency.

    Args:
        session: aiohttp ClientSession
        base_url: Base URL for the server
        endpoint: API endpoint path
        headers: HTTP headers to include

    Returns:
        RequestResult with latency and status information
    """
    url = f"{base_url}{endpoint}"
    start = time.monotonic()
    try:
        async with session.get(url, headers=headers, timeout=30) as response:
            # Read the body to ensure we measure full response time
            await response.read()
            elapsed_ms = (time.monotonic() - start) * 1000
            return RequestResult(
                endpoint=endpoint,
                status_code=response.status,
                latency_ms=elapsed_ms,
                success=response.status < 500,
            )
    except Exception as e:  # noqa: BLE001
        elapsed_ms = (time.monotonic() - start) * 1000
        return RequestResult(
            endpoint=endpoint,
            status_code=0,
            latency_ms=elapsed_ms,
            success=False,
            error=str(type(e).__name__),
        )


async def _worker(
    session: Any,
    base_url: str,
    endpoints: list[str],
    headers: dict[str, str],
    results: list[RequestResult],
    stop_event: asyncio.Event,
) -> None:
    """Worker coroutine that sends requests in a loop until stopped.

    Cycles through all endpoints, recording results into the shared list.
    """
    idx = 0
    while not stop_event.is_set():
        endpoint = endpoints[idx % len(endpoints)]
        idx += 1
        result = await _send_request(session, base_url, endpoint, headers)
        results.append(result)


async def run_load_test(
    base_url: str,
    endpoints: list[str],
    concurrency: int = 10,
    duration_seconds: float = 30.0,
    auth_token: str | None = None,
) -> LoadTestReport:
    """Run a load test against the specified endpoints.

    Args:
        base_url: Base URL of the target server (e.g. http://localhost:8080)
        endpoints: List of API endpoint paths to test
        concurrency: Number of concurrent workers
        duration_seconds: How long to run the test (seconds)
        auth_token: Optional Bearer token for authentication

    Returns:
        LoadTestReport with aggregated results
    """
    try:
        import aiohttp
    except ImportError:
        logger.error("aiohttp is required for load testing. Install with: pip install aiohttp")
        raise SystemExit(1)

    headers: dict[str, str] = {"Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    results: list[RequestResult] = []
    stop_event = asyncio.Event()
    started_at = datetime.now(timezone.utc)

    logger.info(
        "Starting load test: %d concurrent workers, %ds duration, %d endpoints",
        concurrency,
        duration_seconds,
        len(endpoints),
    )

    start_time = time.monotonic()

    async with aiohttp.ClientSession() as session:
        # Launch workers
        workers = [
            asyncio.create_task(_worker(session, base_url, endpoints, headers, results, stop_event))
            for _ in range(concurrency)
        ]

        # Wait for the specified duration
        await asyncio.sleep(duration_seconds)
        stop_event.set()

        # Give workers a moment to finish in-flight requests
        await asyncio.sleep(0.5)

        # Cancel any remaining workers
        for w in workers:
            if not w.done():
                w.cancel()

        # Wait for all workers to complete
        await asyncio.gather(*workers, return_exceptions=True)

    actual_duration = time.monotonic() - start_time
    completed_at = datetime.now(timezone.utc)

    # Aggregate results per endpoint
    stats_by_endpoint: dict[str, EndpointStats] = {}
    for result in results:
        if result.endpoint not in stats_by_endpoint:
            stats_by_endpoint[result.endpoint] = EndpointStats(endpoint=result.endpoint)
        stats = stats_by_endpoint[result.endpoint]
        stats.total_requests += 1
        stats.latencies_ms.append(result.latency_ms)
        if result.success:
            stats.successful_requests += 1
        else:
            stats.failed_requests += 1

    # Build endpoint reports
    endpoint_reports = [stats.to_dict(actual_duration) for stats in stats_by_endpoint.values()]

    # Build summary
    all_latencies = [r.latency_ms for r in results]
    total_requests = len(results)
    total_successful = sum(1 for r in results if r.success)
    total_failed = total_requests - total_successful

    def _percentile(values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        idx = (pct / 100.0) * (len(sorted_vals) - 1)
        lower = int(idx)
        upper = min(lower + 1, len(sorted_vals) - 1)
        frac = idx - lower
        return sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac

    summary: dict[str, Any] = {
        "total_requests": total_requests,
        "successful_requests": total_successful,
        "failed_requests": total_failed,
        "error_rate": round(total_failed / max(total_requests, 1), 6),
        "throughput_rps": round(total_requests / max(actual_duration, 0.001), 2),
        "latency_ms": {
            "p50": round(_percentile(all_latencies, 50), 2),
            "p95": round(_percentile(all_latencies, 95), 2),
            "p99": round(_percentile(all_latencies, 99), 2),
            "min": round(min(all_latencies), 2) if all_latencies else 0.0,
            "max": round(max(all_latencies), 2) if all_latencies else 0.0,
            "avg": (round(sum(all_latencies) / len(all_latencies), 2) if all_latencies else 0.0),
        },
    }

    report = LoadTestReport(
        base_url=base_url,
        concurrency=concurrency,
        duration_seconds=duration_seconds,
        actual_duration_seconds=actual_duration,
        endpoints=endpoint_reports,
        summary=summary,
        started_at=started_at.isoformat(),
        completed_at=completed_at.isoformat(),
    )

    logger.info(
        "Load test complete: %d requests, %.1f rps, p95=%.1fms, p99=%.1fms, error_rate=%.4f",
        total_requests,
        summary["throughput_rps"],
        summary["latency_ms"]["p95"],
        summary["latency_ms"]["p99"],
        summary["error_rate"],
    )

    return report


def main() -> None:
    """CLI entry point for the load testing tool."""
    parser = argparse.ArgumentParser(
        description="Aragora API Load Testing Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("ARAGORA_LOAD_TEST_BASE_URL", "http://localhost:8080"),
        help="Base URL of the target server (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Number of concurrent workers (default: 10)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Test duration in seconds (default: 30)",
    )
    parser.add_argument(
        "--endpoints",
        nargs="+",
        default=None,
        help="Specific endpoints to test (default: built-in set)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output file for JSON report (default: stdout)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("ARAGORA_API_TOKEN"),
        help="Bearer token for authentication",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    endpoints = args.endpoints or DEFAULT_ENDPOINTS

    # Run the load test
    report = asyncio.run(
        run_load_test(
            base_url=args.base_url,
            endpoints=endpoints,
            concurrency=args.concurrency,
            duration_seconds=args.duration,
            auth_token=args.token,
        )
    )

    # Output report
    report_json = json.dumps(report.to_dict(), indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(report_json)
            f.write("\n")
        logger.info("Report written to %s", args.output)
    else:
        print(report_json)

    # Exit with error code if error rate exceeds 1%
    if report.summary["error_rate"] > 0.01:
        logger.warning(
            "Error rate %.2f%% exceeds 1%% threshold",
            report.summary["error_rate"] * 100,
        )
        sys.exit(1)

    # Exit with error code if p95 exceeds 500ms
    if report.summary["latency_ms"]["p95"] > 500:
        logger.warning(
            "p95 latency %.1fms exceeds 500ms SLO target",
            report.summary["latency_ms"]["p95"],
        )
        sys.exit(2)

    # Exit with error code if p99 exceeds 2000ms
    if report.summary["latency_ms"]["p99"] > 2000:
        logger.warning(
            "p99 latency %.1fms exceeds 2000ms SLO target",
            report.summary["latency_ms"]["p99"],
        )
        sys.exit(3)


if __name__ == "__main__":
    main()
