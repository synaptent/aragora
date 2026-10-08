"""Read-only OAuth allowance observations, never reviewer admission authority."""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TypeGuard
from uuid import UUID

MAX_BYTES = 65_536
SCHEMA = "claude-capacity-inventory/v1"
Fetch = Callable[[str, str, float], dict[str, Any]]


class QueryError(Exception):
    """A fixed reason code, without upstream response bodies or credentials."""

    def __init__(self, reason: str, status: int | None = None):
        super().__init__(reason)
        self.reason, self.status = reason, status


@dataclass
class Credential:
    label: str
    token: str = field(default="", repr=False)
    expires_at: float | None = None
    state: str = "credential_unknown"
    cached_identity: tuple[str, str] | None = field(default=None, repr=False)


def _object(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("oversized_metadata")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("invalid_metadata")
    return value


def _number(value: Any) -> TypeGuard[int | float]:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _timestamp(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


def _identity(account: Any, organization: Any) -> tuple[str, str] | None:
    if not isinstance(account, str) or not isinstance(organization, str):
        return None
    try:
        return str(UUID(account)), str(UUID(organization))
    except ValueError:
        return None


def _load(label: str, path: Path, *, native: bool) -> Credential:
    result = Credential(label)
    try:
        data = _object(path)
        if not native and data.get("type") != "claude":
            return result
        if native:
            data = data.get("claudeAiOauth", {})
        if not isinstance(data, dict):
            return result
        token = data.get("accessToken" if native else "access_token")
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            return result
        result.token = token
        expiry = data.get("expiresAt") if native else data.get("expired")
        result.expires_at = (
            float(expiry) / 1000 if native and _number(expiry) else _timestamp(expiry)
        )
        result.state = "disabled" if data.get("disabled", False) is not False else "loaded"
        if native:
            try:
                cache_path = path.parent / ".claude.json"
                if not cache_path.exists():
                    cache_path = path.parent.parent / ".claude.json"
                cached = _object(cache_path).get("oauthAccount", {})
                if isinstance(cached, dict):
                    result.cached_identity = _identity(
                        cached.get("accountUuid"), cached.get("organizationUuid")
                    )
            except (OSError, ValueError, RecursionError):
                result.cached_identity = None
    except (OSError, ValueError, OverflowError, RecursionError):
        result.state = "credential_unknown"
    return result


def discover(profile_root: Path, proxy_root: Path) -> list[Credential]:
    """Read only named-profile files and VibeProxy Claude files; never Keychain."""
    profiles = sorted(p for p in profile_root.glob("max-*") if re.fullmatch(r"max-\d{2}", p.name))
    proxy = sorted(proxy_root.glob("claude-*.json"))
    if len(profiles) + len(proxy) > 64:
        raise ValueError("inventory_limit_exceeded")
    return [_load(p.name, p / ".claude" / ".credentials.json", native=True) for p in profiles] + [
        _load("vibeproxy:" + hashlib.sha256(p.name.encode()).hexdigest()[:12], p, native=False)
        for p in proxy
    ]


def oauth_get(token: str, endpoint: str, timeout: float) -> dict[str, Any]:
    """Fixed TLS host, GET-only, no redirects/proxy env, refresh, retry or inference."""
    if endpoint not in {"profile", "usage"}:
        raise ValueError("unsupported_endpoint")
    connection = http.client.HTTPSConnection("api.anthropic.com", timeout=timeout)
    try:
        connection.request(
            "GET",
            "/api/oauth/" + endpoint,
            headers={"Authorization": "Bearer " + token, "anthropic-beta": "oauth-2025-04-20"},
        )
        response = connection.getresponse()
        if response.status != 200:
            reason = {401: "auth_rejected", 403: "permission_denied", 429: "rate_limited"}.get(
                response.status, "http_error"
            )
            raise QueryError(reason, response.status)
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise QueryError("oversized_response")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise QueryError("invalid_response")
        return result
    except TimeoutError:
        raise QueryError("timeout") from None
    except (OSError, http.client.HTTPException):
        raise QueryError("transport_error") from None
    except (ValueError, UnicodeError, RecursionError):
        raise QueryError("invalid_response") from None
    finally:
        connection.close()


def _window(value: Any, now: float, percent: str = "utilization") -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    used, reset = value.get(percent), _timestamp(value.get("resets_at"))
    if (
        not _number(used)
        or not 0 <= used <= 100
        or (value.get("resets_at") is not None and reset is None)
        or (used > 0 and reset is None)
        or (reset is not None and reset <= now)
        or value.get("locked_reason") is not None
    ):
        return None
    return {"used_percent": used, "remaining_percent": 100 - used, "resets_at": reset}


def summarize_usage(usage: dict[str, Any], now: float) -> dict[str, Any]:
    windows: dict[str, Any] = {}
    reasons: set[str] = set()
    keys = {"five_hour", "seven_day"} | {
        k
        for k in usage
        if re.fullmatch(r"seven_day_[a-z_]{1,40}", k) and k != "seven_day_breakdown"
    }
    for key in sorted(keys):
        value = usage.get(key)
        if value is None and key not in {"five_hour", "seven_day"}:
            continue
        window = _window(value, now)
        if window is None:
            reasons.add("invalid_or_locked_window")
        else:
            windows[key] = window
    general = (
        all(windows[k]["remaining_percent"] > 0 for k in ("five_hour", "seven_day"))
        if {"five_hour", "seven_day"} <= windows.keys()
        else None
    )
    limits = usage.get("limits", [])
    if not isinstance(limits, list) or len(limits) > 32:
        reasons.add("unsupported_limits")
        limits = []
    for index, limit in enumerate(limits):
        window = _window(limit, now, "percent")
        if window is None or not isinstance(limit, dict):
            reasons.add("unsupported_limits")
            continue
        kind, scope = limit.get("kind"), limit.get("scope")
        if (
            kind not in ("session", "weekly_all", "weekly_scoped")
            or type(limit.get("is_active")) is not bool
        ):
            reasons.add("unsupported_limits")
        elif limit["is_active"] and window["used_percent"] < 100:
            reasons.add("active_limit_needs_interpretation")
        if (kind == "weekly_scoped" and not isinstance(scope, dict)) or (
            kind != "weekly_scoped" and scope is not None
        ):
            reasons.add("unsupported_limits")
        model = scope.get("model") if isinstance(scope, dict) else None
        display = model.get("display_name") if isinstance(model, dict) else None
        window["model"] = (
            display if display in ("Fable", "Opus", "Sonnet", "Haiku") else "unspecified"
        )
        severity = limit.get("severity")
        window["severity"] = (
            severity if severity in ("normal", "warning", "critical") else "unknown"
        )
        windows[f"limit_{index}"] = window
    restricted = any(w["used_percent"] == 100 for w in windows.values())
    extra = usage.get("extra_usage")
    return {
        "quota_state": "unknown" if reasons else "restricted" if restricted else "available",
        "reason_codes": sorted(reasons),
        "base_window_headroom": general,
        "windows": windows,
        "extra_usage_enabled": extra.get("is_enabled")
        if isinstance(extra, dict) and type(extra.get("is_enabled")) is bool
        else None,
    }


def collect(
    credentials: list[Credential],
    *,
    fetch: Fetch = oauth_get,
    now: Callable[[], float] = time.time,
    clock: Callable[[], float] = time.monotonic,
    timeout: float = 10,
    budget: float = 120,
) -> dict[str, Any]:
    """Deduplicate tokens in memory; report identity-scoped observations, not runnable seats."""
    if (
        not _number(timeout)
        or not 0 < timeout <= 15
        or not _number(budget)
        or not 0 < budget <= 180
    ):
        raise ValueError("invalid_time_budget")
    deadline = clock() + budget
    cache: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for credential in credentials:
        row: dict[str, Any] = {
            "source": credential.label,
            "state": credential.state,
            "credential_expires_at": credential.expires_at,
        }
        expiry = credential.expires_at
        if credential.state != "loaded":
            rows.append(row)
            continue
        if expiry is None or expiry <= now():
            row["state"] = "credential_expired" if expiry is not None else "expiry_unknown"
            rows.append(row)
            continue
        if credential.token not in cache:
            observation: dict[str, Any] = {"state": "unknown"}
            try:
                remaining = min(timeout, deadline - clock())
                if remaining <= 0:
                    raise QueryError("budget_exhausted")
                profile = fetch(credential.token, "profile", remaining)
                account, org = profile.get("account"), profile.get("organization")
                identity = _identity(
                    account.get("uuid") if isinstance(account, dict) else None,
                    org.get("uuid") if isinstance(org, dict) else None,
                )
                if identity is None or not isinstance(org, dict):
                    raise QueryError("identity_unknown")
                observed_at = now()
                observation.update(
                    identity_key=hashlib.sha256(json.dumps(identity).encode()).hexdigest(),
                    identity=identity,
                    organization_type=org.get("organization_type")
                    if org.get("organization_type")
                    in ("claude_max", "claude_pro", "claude_team", "claude_enterprise")
                    else "unknown",
                    observed_at=observed_at,
                    expires_at=min(observed_at + 300, expiry),
                )
                if org.get("subscription_status") != "active":
                    raise QueryError("subscription_not_active")
                remaining = min(timeout, deadline - clock())
                if remaining <= 0:
                    raise QueryError("budget_exhausted")
                observation.update(
                    summarize_usage(fetch(credential.token, "usage", remaining), now())
                )
                observation["state"] = "observed"
            except QueryError as exc:
                observation.update(state=exc.reason, http_status=exc.status)
            cache[credential.token] = observation
        observation = cache[credential.token]
        row.update({k: v for k, v in observation.items() if k != "identity"})
        if "expires_at" in row:
            row["expires_at"] = min(row["expires_at"], expiry)
        identity = observation.get("identity")
        row["cached_identity"] = (
            "unknown"
            if not credential.cached_identity or not identity
            else "matches"
            if credential.cached_identity == identity
            else "mismatch"
        )
        rows.append(row)
    observed_ids = {r["identity_key"] for r in rows if "identity_key" in r}
    return {
        "schema": SCHEMA,
        "generated_at": now(),
        "observations": rows,
        "unique_identities_with_allowance": len(
            observed_ids
            - {
                r["identity_key"]
                for r in rows
                if "identity_key" in r and r.get("quota_state") != "available"
            }
        ),
        "unique_identities_with_base_headroom": len(
            {r["identity_key"] for r in rows if r.get("base_window_headroom") is True}
        ),
        "execution_verified": False,
        "admission_authorized": False,
        "countability_evaluated": False,
        "coverage": "credential files only; native Keychain and CLI credential precedence unverified",
    }
