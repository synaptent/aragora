"""Pure helpers for the Claude profile-pool verify snapshot.

``scripts/claude_pool_verify.py`` live-probes each profile and writes
``.aragora/claude_pool_health.json``. That snapshot is the *verify-backed* health
source consumed by:
  - ``aragora/swarm/review_routing.py`` (skip unhealthy review profiles), and
  - ``aragora/agents/claude_profile_pool.py`` (skip unhealthy debate profiles).

``claude auth status`` is deliberately not used for liveness: it reports
``loggedIn: true`` even for expired/revoked tokens. Only a real completion probe
distinguishes a usable profile, so this module classifies *probe output*.

Snapshot shape (matches the format both consumers parse)::

    {"generated_at": "...Z", "healthy": 2, "total": 13,
     "profiles": [{"name": "max-01", "email": "a@x", "state": "ok"}, ...]}
"""

from __future__ import annotations

import json
import re

# States consumers treat as unusable (mirror review_routing._UNHEALTHY_PROFILE_STATES).
UNHEALTHY_STATES = {"expired", "not_configured", "unauthenticated", "logged_out"}

_AUTH_FAILURE_MARKERS = (
    r"\b401\b",
    "invalid authentication",
    r"invalid (?:x-api-key|api key)",
    "failed to authenticate",
    "unauthorized",
    r"(?:oauth .*)?token.*expir",
)
_NOT_CONFIGURED_MARKERS = (
    "no such file",
    "not logged in",
    "no credentials",
    "claude_profile.sh not found",
)


_REASON_PATTERNS = (
    ("auth_missing", "|".join(_NOT_CONFIGURED_MARKERS)),
    ("auth_revoked", r"(?:oauth .*)?(?:token|credential).*revoked"),
    ("auth_expired", "|".join(_AUTH_FAILURE_MARKERS)),
    (
        "quota_exhausted",
        r"you['’]re out of usage credits|\b429\b|rate[ _-]?limit|"
        r"quota (?:exceeded|exhausted)|insufficient credits|"
        r"(?:you(?: have|['’]ve)? )?hit your (?:usage|session) limit|credit balance is too low",
    ),
    ("transport_timeout", r"(?:request |connection )?(?:timed? out|timeout)"),
    ("service_unavailable", r"\b50[0234]\b|service unavailable|overloaded|internal server error"),
    (
        "invalid_response",
        r"(?:(?:i['’]m )?sorry[, .]*(?:but )?)?(?:i (?:cannot|can['’]t|am unable)|refus(?:al|ed))",
    ),
)
REASON_CODES = frozenset({"ok", "unknown_failure", *(reason for reason, _ in _REASON_PATTERNS)})


def _plain_probe_reason(text: str, failed: bool = False) -> str:
    text = text.strip().lower()
    if not text:
        return "invalid_response"
    any_failure = failed
    for line in text.splitlines():
        line = line.strip()
        line_failed = failed or bool(re.match(r"(?:api error|error\b|failed\b|http\b)", line))
        match = re.search if line_failed else re.match
        for reason, pattern in _REASON_PATTERNS:
            if match(pattern, line):
                return reason
        any_failure = any_failure or line_failed
    return "unknown_failure" if any_failure else "ok"


def classify_probe_reason(
    stdout: str, returncode: int | None = None, timed_out: bool = False
) -> str:
    if timed_out:
        return "transport_timeout"
    text = (stdout or "").strip()
    failed = returncode not in (None, 0)
    lines = text.splitlines()
    json_start = next(
        (index for index, line in enumerate(lines) if line.lstrip().startswith(("{", "["))),
        None,
    )
    if json_start is not None:
        if json_start:
            preamble_reason = _plain_probe_reason("\n".join(lines[:json_start]))
            if preamble_reason not in ("ok", "unknown_failure"):
                return preamble_reason
            failed = failed or preamble_reason == "unknown_failure"
        try:
            payload = json.loads("\n".join(lines[json_start:]))
        except (ValueError, RecursionError):
            return "invalid_response"
        if not isinstance(payload, dict):
            return "invalid_response"
        if "is_error" in payload and not isinstance(payload["is_error"], bool):
            return "invalid_response"
        structured_error = (
            payload.get("is_error") is True
            or "error" in payload
            or bool(payload.get("errors"))
            or payload.get("type") == "error"
            or str(payload.get("subtype", "")).startswith("error")
        )
        if structured_error:
            failed = True
            text = json.dumps(
                [payload.get(key) for key in ("result", "error", "errors")], ensure_ascii=False
            )
        else:
            if (
                payload.get("type") != "result"
                or payload.get("is_error") is not False
                or payload.get("subtype") not in (None, "success")
            ):
                return "invalid_response"
            result = payload.get("result")
            if not isinstance(result, str):
                return "invalid_response"
            text = result
    return _plain_probe_reason(text, failed)


def classify_probe(stdout: str, *, returncode: int | None = None, timed_out: bool = False) -> str:
    """Map a completion-probe result to a health state.

    - ``ok``: the probe produced real model output.
    - ``expired``: an auth failure (401 / invalid / expired token) — the common
      revoked/expired case.
    - ``not_configured``: the profile has no usable credentials at all.
    - ``unauthenticated``: timed out or produced no output (treated as unusable).
    """
    reason = classify_probe_reason(stdout, returncode=returncode, timed_out=timed_out)
    if reason == "transport_timeout":
        return "unauthenticated"
    if reason == "auth_missing":
        return "not_configured"
    if reason in ("auth_expired", "auth_revoked"):
        return "expired"
    if not (stdout or "").strip():
        # No output and not a recognized error: cannot confirm liveness.
        return "unauthenticated"
    if returncode not in (None, 0):
        return "expired"
    return "ok" if reason == "ok" else "unauthenticated"


def is_healthy(state: str) -> bool:
    return state == "ok"


def build_snapshot(records: list[dict], *, generated_at: str) -> dict:
    """Build the snapshot dict from per-profile ``{name,email,state}`` records."""
    profiles = [
        {
            "name": str(r.get("name", "")),
            "email": str(r.get("email", "") or ""),
            "state": str(r.get("state", "unauthenticated")),
        }
        for r in records
    ]
    for profile, record in zip(profiles, records):
        if profile["state"] not in UNHEALTHY_STATES | {"ok"}:
            profile["state"] = "unauthenticated"
        if "reason_code" in record:
            reason = record["reason_code"]
            profile["reason_code"] = (
                reason if isinstance(reason, str) and reason in REASON_CODES else "unknown_failure"
            )
            if profile["reason_code"] != "ok" and is_healthy(profile["state"]):
                profile["state"] = "unauthenticated"
            elif profile["reason_code"] == "ok" and not is_healthy(profile["state"]):
                profile["reason_code"] = "unknown_failure"
    healthy = sum(1 for p in profiles if is_healthy(p["state"]))
    return {
        "generated_at": generated_at,
        "healthy": healthy,
        "total": len(profiles),
        "profiles": profiles,
    }
