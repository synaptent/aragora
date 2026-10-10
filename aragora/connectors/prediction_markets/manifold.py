"""Manifold Markets read-only adapter (AGT-03 Phase 1).

Phase 1: read-only — discover markets, fetch a market, fetch its
resolution. No write access (no prediction submission, no betting).
The downstream integration into the AGT-05 reputation flow consumes
the resolution events this adapter produces.

API: https://docs.manifold.markets/api

This adapter:
- Uses Manifold's public REST API; no auth required for reads.
- Has no implicit network calls — every method takes an explicit
  ``http_client`` callable that returns ``(status_code, body_text)``.
  Callers wire in ``httpx``, ``urllib``, or a stub for tests.
- Maps Manifold's market shape to a normalized
  :class:`ManifoldMarket` and Manifold's resolution to a
  :class:`ManifoldResolution`. The :func:`manifold_to_market_resolution`
  helper bridges into the AGT-04 :class:`aragora.markets.types.
  ResolutionEvent` shape so the same downstream pipeline (settle_claim,
  Brier scoring, reputation deltas) works for both internal synthetic
  GitHub markets and external Manifold markets.

Out of scope for this PR (deferred to AGT-03 Phase 2 / Phase 3):
- Prediction submission (bot-policy compliance + API-key handling)
- Per-agent Brier score wiring (lives in AGT-05)
- Real-money venues (Kalshi, Polymarket) — see venue-stack plan
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from aragora.connectors.prediction_markets.stake_caps import StabilityRecord, StakeCapSchedule

logger = logging.getLogger(__name__)

MANIFOLD_API_BASE = "https://api.manifold.markets/v0"

# Per AGT-03 plan: avoid markets with <30-day resolution windows in
# initial calibration phase (noise reduction)
DEFAULT_MIN_WINDOW_DAYS = 30


class ManifoldError(RuntimeError):
    """Raised when a Manifold API call fails or returns an unexpected shape."""


# An HTTP client is any callable: (method, url, headers) -> (status_code, body_text).
# Keeping this thin lets callers inject httpx, urllib, or a deterministic test stub.
HttpClient = Callable[..., tuple[int, str]]


@dataclass(frozen=True)
class ManifoldMarket:
    """Normalized Manifold market view.

    Mirrors the Manifold "FullMarket" shape selectively. Only the fields
    we need for AGT-03 read-only flows are surfaced; the rest stays in
    ``raw`` for downstream consumers that need it.
    """

    market_id: str
    slug: str
    question: str
    creator_username: str
    created_time_ms: int
    close_time_ms: int | None
    resolution: str | None
    is_resolved: bool
    outcome_type: str
    total_liquidity: int | None = None  # mana; used by ManifoldBetAdapter for liquidity-cap checks
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api_payload(cls, payload: dict[str, Any]) -> "ManifoldMarket":
        market_id = str(payload.get("id") or "").strip()
        if not market_id:
            raise ManifoldError("Manifold market payload missing 'id'")
        raw_liq = payload.get("totalLiquidity")
        return cls(
            market_id=market_id,
            slug=str(payload.get("slug") or ""),
            question=str(payload.get("question") or ""),
            creator_username=str(payload.get("creatorUsername") or ""),
            created_time_ms=int(payload.get("createdTime") or 0),
            close_time_ms=(
                int(payload["closeTime"]) if payload.get("closeTime") is not None else None
            ),
            resolution=(
                str(payload["resolution"]) if payload.get("resolution") is not None else None
            ),
            is_resolved=bool(payload.get("isResolved")),
            outcome_type=str(payload.get("outcomeType") or "BINARY"),
            total_liquidity=int(raw_liq) if raw_liq is not None else None,
            raw=dict(payload),
        )


@dataclass(frozen=True)
class ManifoldResolution:
    """Normalized Manifold resolution event.

    ``outcome`` follows the same ternary shape as
    :class:`aragora.markets.types.ResolutionEvent` so the AGT-05 settlement
    flow can consume it without further normalization.
    """

    market_id: str
    outcome: str  # "yes" | "no" | "inconclusive"
    resolved_at_ms: int | None
    raw: dict[str, Any] = field(default_factory=dict)


def _normalize_outcome(resolution_field: str | None) -> str:
    """Map Manifold's resolution string to our ternary outcome shape."""
    if resolution_field is None:
        return "inconclusive"
    lowered = str(resolution_field).strip().upper()
    if lowered in {"YES"}:
        return "yes"
    if lowered in {"NO"}:
        return "no"
    if lowered in {"CANCEL", "MKT", "CHOOSE_ONE", "CHOOSE_MULTIPLE"}:
        # MKT (probability-weighted) and multi-choice resolutions are
        # not binary YES/NO outcomes; the AGT-05 layer treats them as
        # inconclusive for binary-Brier purposes.
        return "inconclusive"
    return "inconclusive"


@dataclass
class ManifoldAdapter:
    """Read-only adapter to the Manifold Markets API.

    Parameters:
        http_client: callable that performs HTTP calls. Signature:
            ``http_client(method: str, url: str, headers: dict) -> (int, str)``.
            Required — no default network access.
        api_base: override the base URL for testing.
        min_window_days: filter out markets with very short resolution
            windows from :meth:`discover_unresolved_markets` (default 30).
    """

    http_client: HttpClient
    api_base: str = MANIFOLD_API_BASE
    min_window_days: int = DEFAULT_MIN_WINDOW_DAYS

    def _get(self, path: str) -> Any:
        url = f"{self.api_base.rstrip('/')}/{path.lstrip('/')}"
        try:
            status, body = self.http_client("GET", url, {"Accept": "application/json"})
        except Exception as exc:  # noqa: BLE001 - adapter wraps all transport errors
            raise ManifoldError(f"manifold transport error for {path}: {exc}") from exc
        if status >= 400:
            raise ManifoldError(f"manifold {path} returned HTTP {status}: {body[:200]}")
        try:
            return json.loads(body or "null")
        except json.JSONDecodeError as exc:
            raise ManifoldError(f"manifold {path} returned non-JSON: {exc}") from exc

    # ------------------------------------------------------------------
    # Market discovery
    # ------------------------------------------------------------------

    def fetch_market(self, market_id: str) -> ManifoldMarket:
        """Fetch a single market by id."""
        if not market_id:
            raise ManifoldError("market_id is required")
        payload = self._get(f"market/{market_id}")
        if not isinstance(payload, dict):
            raise ManifoldError(f"manifold market/{market_id} returned non-object payload")
        return ManifoldMarket.from_api_payload(payload)

    def fetch_market_by_slug(self, slug: str) -> ManifoldMarket:
        """Fetch a single market by slug."""
        if not slug:
            raise ManifoldError("slug is required")
        payload = self._get(f"slug/{slug}")
        if not isinstance(payload, dict):
            raise ManifoldError(f"manifold slug/{slug} returned non-object payload")
        return ManifoldMarket.from_api_payload(payload)

    def list_markets(self, *, limit: int = 50, before: str | None = None) -> list[ManifoldMarket]:
        """List recent markets (Manifold's pagination is `before=<market_id>`)."""
        if limit < 1 or limit > 1000:
            raise ManifoldError("limit must be in [1, 1000]")
        path = f"markets?limit={int(limit)}"
        if before:
            path += f"&before={before}"
        payload = self._get(path)
        if not isinstance(payload, list):
            raise ManifoldError("manifold markets endpoint returned non-list payload")
        out: list[ManifoldMarket] = []
        for entry in payload:
            if isinstance(entry, dict):
                try:
                    out.append(ManifoldMarket.from_api_payload(entry))
                except ManifoldError:
                    logger.debug("skipping malformed manifold market entry")
        return out

    def discover_unresolved_markets(
        self,
        *,
        limit: int = 50,
        now_ms: int | None = None,
    ) -> list[ManifoldMarket]:
        """List unresolved markets whose close time is sufficiently far out.

        Filters per the AGT-03 plan: BINARY only, not yet resolved,
        close time at least :attr:`min_window_days` away.
        """
        markets = self.list_markets(limit=limit)
        reference_ms = (
            now_ms if now_ms is not None else int(datetime.now(tz=UTC).timestamp() * 1000)
        )
        threshold_ms = self.min_window_days * 24 * 3600 * 1000
        out: list[ManifoldMarket] = []
        for market in markets:
            if market.is_resolved:
                continue
            if market.outcome_type.upper() != "BINARY":
                continue
            if market.close_time_ms is None:
                continue
            if market.close_time_ms - reference_ms < threshold_ms:
                continue
            out.append(market)
        return out

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def fetch_resolution(self, market_id: str) -> ManifoldResolution | None:
        """Return the resolution event for a market, or None if unresolved."""
        market = self.fetch_market(market_id)
        if not market.is_resolved:
            return None
        return ManifoldResolution(
            market_id=market.market_id,
            outcome=_normalize_outcome(market.resolution),
            resolved_at_ms=market.raw.get("resolutionTime"),
            raw={"resolution": market.resolution, "outcomeType": market.outcome_type},
        )


def manifold_to_market_resolution(
    resolution: ManifoldResolution,
    *,
    resolved_at: datetime | None = None,
):
    """Bridge from a Manifold resolution to the AGT-04 ResolutionEvent shape.

    Lazily imports :mod:`aragora.markets.types` so this connector can
    be used without requiring the markets module to be loaded.
    """
    from aragora.markets.types import ResolutionEvent as MarketResolution

    when = resolved_at
    if when is None and resolution.resolved_at_ms:
        when = datetime.fromtimestamp(resolution.resolved_at_ms / 1000.0, tz=UTC)

    if resolution.outcome == "yes":
        return MarketResolution.yes(
            market_id=resolution.market_id,
            resolution_source="manifold",
            evidence=dict(resolution.raw),
            resolved_at=when,
        )
    if resolution.outcome == "no":
        return MarketResolution.no(
            market_id=resolution.market_id,
            resolution_source="manifold",
            evidence=dict(resolution.raw),
            resolved_at=when,
        )
    return MarketResolution.inconclusive(
        market_id=resolution.market_id,
        resolution_source="manifold",
        evidence=dict(resolution.raw),
        resolved_at=when,
    )


# ---------------------------------------------------------------------------
# Write path — AGT-03 Phase 2
# Gated behind ARAGORA_MANIFOLD_WRITE_ENABLED (default off).
# ---------------------------------------------------------------------------

MANIFOLD_WRITE_FLAG = "ARAGORA_MANIFOLD_WRITE_ENABLED"

# Stake caps per the AGT-03 plan.
DEFAULT_PER_MARKET_CAP_MANA = 50  # mana; rises to 200 after 30d stable behaviour
DEFAULT_PER_DAY_CAP_MANA = 1000  # mana total across all markets per UTC calendar day
DEFAULT_LIQUIDITY_FRACTION_CAP = 0.05  # never >5% of a market's total liquidity in one bet


def manifold_write_enabled() -> bool:
    """Return True when ARAGORA_MANIFOLD_WRITE_ENABLED is set to a truthy value."""
    raw = str(os.environ.get(MANIFOLD_WRITE_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ManifoldBetResult:
    """Result of a successful prediction-submission call."""

    bet_id: str
    market_id: str
    stake_mana: int
    probability: float
    outcome: str  # "YES" | "NO"


@dataclass
class ManifoldBetAdapter(ManifoldAdapter):
    """Write-capable Manifold adapter (AGT-03 Phase 2).

    Gated behind ARAGORA_MANIFOLD_WRITE_ENABLED (default off).
    Enforces per-market (50 mana), per-day (1 000 mana), and
    liquidity-fraction (5%) caps before each API call.

    With ``cap_schedule`` set, the per-market cap comes from
    :class:`StakeCapSchedule` (50 → 200 mana after 30 stable days, itself
    gated behind ARAGORA_MANIFOLD_CAP_GRADUATION_ENABLED); unset, unchanged.
    """

    api_key: str = ""
    per_market_cap_mana: int = DEFAULT_PER_MARKET_CAP_MANA
    per_day_cap_mana: int = DEFAULT_PER_DAY_CAP_MANA
    liquidity_fraction_cap: float = DEFAULT_LIQUIDITY_FRACTION_CAP
    cap_schedule: StakeCapSchedule | None = None
    stability_record: StabilityRecord = field(default_factory=StabilityRecord)
    _market_stakes: dict[str, int] = field(default_factory=dict)
    _daily_stakes: dict[str, int] = field(default_factory=dict)

    def _require_write_enabled(self) -> None:
        if not manifold_write_enabled():
            raise ManifoldError(
                f"manifold write path is disabled; set {MANIFOLD_WRITE_FLAG}=1 to enable"
            )

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        url = f"{self.api_base.rstrip('/')}/{path.lstrip('/')}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Key {self.api_key}",
        }
        try:
            status, response = self.http_client("POST", url, headers, json.dumps(body))
        except Exception as exc:  # noqa: BLE001
            raise ManifoldError(f"manifold write transport error for {path}: {exc}") from exc
        if status >= 400:
            raise ManifoldError(f"manifold POST {path} returned HTTP {status}: {response[:200]}")
        try:
            return json.loads(response or "null")
        except json.JSONDecodeError as exc:
            raise ManifoldError(f"manifold POST {path} returned non-JSON: {exc}") from exc

    def _effective_per_market_cap(self, *, now: datetime | None = None) -> int:
        if self.cap_schedule is None:
            return self.per_market_cap_mana
        return self.cap_schedule.effective_per_market_cap(self.stability_record, now=now)

    def _enforce_caps(
        self,
        market_id: str,
        stake_mana: int,
        *,
        market_liquidity: int | None = None,
        now: datetime | None = None,
    ) -> None:
        market_staked = self._market_stakes.get(market_id, 0)
        per_market_cap = self._effective_per_market_cap(now=now)
        if market_staked + stake_mana > per_market_cap:
            raise ManifoldError(
                f"per-market cap exceeded for {market_id}: "
                f"already_staked={market_staked}, requested={stake_mana}, "
                f"cap={per_market_cap}"
            )
        today = (now or datetime.now(tz=UTC)).date().isoformat()
        day_staked = self._daily_stakes.get(today, 0)
        if day_staked + stake_mana > self.per_day_cap_mana:
            raise ManifoldError(
                f"per-day cap exceeded: staked_today={day_staked}, "
                f"requested={stake_mana}, cap={self.per_day_cap_mana}"
            )
        if market_liquidity is not None and market_liquidity > 0:
            fraction = stake_mana / market_liquidity
            if fraction > self.liquidity_fraction_cap:
                raise ManifoldError(
                    f"liquidity fraction cap exceeded: stake={stake_mana}, "
                    f"liquidity={market_liquidity}, fraction={fraction:.2%}, "
                    f"cap={self.liquidity_fraction_cap:.2%}"
                )

    def place_bet(
        self,
        market_id: str,
        *,
        probability: float,
        stake_mana: int,
        outcome: str = "YES",
        now: datetime | None = None,
    ) -> ManifoldBetResult:
        """Submit a prediction bet. Checks all caps before the API call.

        Stake counters are only updated after a successful response.
        """
        self._require_write_enabled()
        if not market_id:
            raise ManifoldError("market_id is required")
        if not 0.0 < probability < 1.0:
            raise ManifoldError(f"probability must be strictly in (0, 1): {probability}")
        if stake_mana < 1:
            raise ManifoldError(f"stake_mana must be >= 1: {stake_mana}")
        if outcome not in ("YES", "NO"):
            raise ManifoldError(f"outcome must be 'YES' or 'NO': {outcome!r}")

        market = self.fetch_market(market_id)
        try:
            self._enforce_caps(
                market_id,
                stake_mana,
                market_liquidity=market.total_liquidity,
                now=now,
            )

            payload = self._post(
                "bet",
                {
                    "contractId": market_id,
                    "amount": stake_mana,
                    "outcome": outcome,
                },
            )

            bet_id = str(payload.get("id") or payload.get("betId") or "").strip()
            if not bet_id:
                raise ManifoldError(f"manifold bet response missing 'id' / 'betId': {payload!r}")
        except ManifoldError:
            # Cap violations and write failures count against stability
            # for cap graduation; caller-side validation errors above do not.
            self.stability_record.record_incident(now=now)
            raise

        today = (now or datetime.now(tz=UTC)).date().isoformat()
        self._market_stakes[market_id] = self._market_stakes.get(market_id, 0) + stake_mana
        self._daily_stakes[today] = self._daily_stakes.get(today, 0) + stake_mana
        self.stability_record.record_bet(now=now)

        return ManifoldBetResult(
            bet_id=bet_id,
            market_id=market_id,
            stake_mana=stake_mana,
            probability=probability,
            outcome=outcome,
        )


__all__ = [
    "DEFAULT_MIN_WINDOW_DAYS",
    "DEFAULT_PER_DAY_CAP_MANA",
    "DEFAULT_PER_MARKET_CAP_MANA",
    "MANIFOLD_API_BASE",
    "MANIFOLD_WRITE_FLAG",
    "ManifoldAdapter",
    "ManifoldBetAdapter",
    "ManifoldBetResult",
    "ManifoldError",
    "ManifoldMarket",
    "ManifoldResolution",
    "manifold_to_market_resolution",
    "manifold_write_enabled",
]
