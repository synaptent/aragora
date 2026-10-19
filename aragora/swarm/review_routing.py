from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import ssl
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aragora.agents.base import create_agent
from aragora.agents.errors.exceptions import CLISubprocessError
from aragora.config.secrets import get_secret_presence, is_secret_presence_available

logger = logging.getLogger(__name__)

# grok precedes openrouter so that when codex (the usual distinct counter) is
# unavailable, the next default fallback is a provider whose family still COUNTS
# toward the heterogeneous merge quorum (claude/codex/grok/factory). openrouter
# does not count, so leaving it as the only fallback turned codex into a single
# point of failure for quorum. grok stays key-gated: if XAI_API_KEY/GROK_API_KEY
# is unset its preflight fails and routing falls through to openrouter as before,
# so this is non-breaking when grok is not configured.
DEFAULT_REVIEW_PROVIDER_ORDER = ("codex", "claude", "grok", "openrouter")
DEFAULT_CLAUDE_REVIEW_PROFILES = tuple(f"max-{index:02d}" for index in range(1, 14))
DEFAULT_POOL_HEALTH_TTL_SECONDS = 3600.0
_POOL_HEALTH_RELATIVE_PATH = ".aragora/claude_pool_health.json"
_UNHEALTHY_PROFILE_STATES = {"expired", "not_configured", "unauthenticated", "logged_out"}
_BILLING_MARKERS = ("credit balance", "billing", "payment required", "purchase credits")
_DIRECT_API_PROVIDER_KEYS = {
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "grok": ("XAI_API_KEY", "GROK_API_KEY"),
}
_SUPPORTED_REVIEW_PROVIDERS = frozenset(
    (*DEFAULT_REVIEW_PROVIDER_ORDER, *_DIRECT_API_PROVIDER_KEYS)
)
_MODEL_FAMILY_OVERRIDES = {
    "anthropic-api": "claude",
    "claude": "claude",
    "codex": "codex",
    "gemini-cli": "gemini",
    "google": "gemini",
    "grok-cli": "grok",
    "openai": "codex",
    "openai-api": "codex",
    "openrouter": "openrouter",
    "x-ai": "grok",
    "xai": "grok",
}


@dataclass(slots=True)
class ReviewCandidate:
    provider: str
    label: str
    profile: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "provider": self.provider,
            "label": self.label,
        }
        if self.profile:
            payload["profile"] = self.profile
        return payload


CandidateBlocker = Callable[[ReviewCandidate], dict[str, Any] | None]


class ReviewRoutingError(RuntimeError):
    def __init__(
        self,
        attempts: list[dict[str, Any]],
        *,
        category: str = "unavailable",
        public_message: str | None = None,
    ) -> None:
        self.attempts = attempts
        self.category = str(category or "unavailable").strip() or "unavailable"
        self.public_message = str(public_message or "").strip() or _review_routing_public_message(
            self.category
        )
        super().__init__(self.public_message)


def resolve_review_candidates(
    *,
    worker_model: str,
    preferred_review_model: str,
    repo_root: Path | None = None,
    rotate: bool = False,
    start_index: int | None = None,
) -> list[ReviewCandidate]:
    worker_family = _model_family(worker_model)
    preferred_family = _model_family(preferred_review_model)
    configured_order = _review_provider_order()
    families: list[str] = []

    if (
        preferred_family
        and preferred_family in _SUPPORTED_REVIEW_PROVIDERS
        and preferred_family != worker_family
    ):
        families.append(preferred_family)
    for provider in configured_order:
        if provider == worker_family and provider != "openrouter":
            continue
        if provider not in families:
            families.append(provider)

    claude_profiles = _ordered_claude_review_profiles(
        repo_root=repo_root, rotate=rotate, start_index=start_index
    )
    candidates: list[ReviewCandidate] = []
    for provider in families:
        if provider == "claude":
            for profile in claude_profiles:
                candidates.append(
                    ReviewCandidate(
                        provider="claude",
                        label=f"claude:{profile}",
                        profile=profile,
                    )
                )
            continue
        candidates.append(ReviewCandidate(provider=provider, label=provider))
    return candidates


def preflight_review_candidate(
    candidate: ReviewCandidate,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    if candidate.provider == "codex":
        return _cli_preflight("codex")
    if candidate.provider == "claude":
        return _claude_profile_preflight(candidate, repo_root=repo_root)
    if candidate.provider == "openrouter":
        return _openrouter_preflight()
    if candidate.provider in _DIRECT_API_PROVIDER_KEYS:
        return _direct_api_provider_preflight(candidate.provider)
    return {
        "ok": False,
        "detail": f"Unsupported review provider: {candidate.provider}",
    }


async def generate_review_response(
    prompt: str,
    *,
    worker_model: str,
    preferred_review_model: str,
    repo_root: Path,
    candidate_blocker: CandidateBlocker | None = None,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for candidate in resolve_review_candidates(
        worker_model=worker_model,
        preferred_review_model=preferred_review_model,
        repo_root=repo_root,
        rotate=_review_rotate_enabled(),
    ):
        preflight = preflight_review_candidate(candidate, repo_root=repo_root)
        if not preflight.get("ok", False):
            attempt = {
                "candidate": candidate.label,
                "stage": "preflight",
                "detail": str(preflight.get("detail", "unavailable")).strip() or "unavailable",
            }
            preflight_kind = str(preflight.get("kind", "")).strip()
            if preflight_kind:
                attempt["kind"] = preflight_kind
            attempts.append(attempt)
            continue
        blocked = candidate_blocker(candidate) if candidate_blocker else None
        if blocked:
            attempts.append(
                {
                    "candidate": candidate.label,
                    "stage": "route_guard",
                    "kind": "blocked_nonreviewable",
                    "detail": str(blocked.get("title", "candidate blocked")).strip()
                    or "candidate blocked",
                }
            )
            return {
                "candidate": candidate.to_dict(),
                "response": "",
                "attempts": attempts,
                "blocked": dict(blocked),
            }
        try:
            response = await _run_review_candidate(candidate, prompt, repo_root=repo_root)
        except CLISubprocessError as exc:
            logger.warning("review candidate %s failed: %s", candidate.label, exc)
            attempts.append(
                _failure_attempt(
                    candidate.label,
                    stage="generate",
                    exc=exc,
                )
            )
            continue
        except Exception as exc:  # noqa: BLE001 - reviewer backends are external; fall through to next candidate
            logger.warning("review candidate %s failed: %s", candidate.label, exc)
            attempts.append(
                _failure_attempt(
                    candidate.label,
                    stage="generate",
                    exc=exc,
                )
            )
            continue
        attempts.append(
            {
                "candidate": candidate.label,
                "stage": "generate",
                "detail": "ok",
            }
        )
        return {
            "candidate": candidate.to_dict(),
            "response": response,
            "attempts": attempts,
        }
    raise ReviewRoutingError(
        attempts,
        category=_review_routing_category(attempts),
    )


async def _run_review_candidate(
    candidate: ReviewCandidate,
    prompt: str,
    *,
    repo_root: Path,
) -> str:
    if candidate.provider == "claude":
        return await _run_claude_profile_candidate(candidate, prompt, repo_root=repo_root)
    if candidate.provider == "codex":
        agent = create_agent(
            "codex",
            name="campaign-review",
            role="critic",
            enable_fallback=False,
        )
        return await agent.generate(prompt)
    if candidate.provider == "openrouter":
        agent = create_agent(
            "openrouter",
            name="campaign-review",
            role="critic",
            enable_fallback=False,
        )
        return await agent.generate(prompt)
    if candidate.provider == "gemini":
        agent = create_agent(
            "gemini",
            name="campaign-review",
            role="critic",
            enable_fallback=False,
        )
        return await agent.generate(prompt)
    if candidate.provider == "grok":
        agent = create_agent(
            "grok",
            name="campaign-review",
            role="critic",
            enable_fallback=False,
        )
        return await agent.generate(prompt)
    raise RuntimeError(f"Unsupported review provider: {candidate.provider}")


def _cli_preflight(command_name: str) -> dict[str, Any]:
    if shutil.which(command_name):
        return {"ok": True, "detail": f"{command_name} is available"}
    return {"ok": False, "detail": f"{command_name} CLI not found on PATH"}


def _claude_profile_preflight(candidate: ReviewCandidate, *, repo_root: Path) -> dict[str, Any]:
    script = _claude_profile_script(repo_root)
    if script is None:
        return {"ok": False, "detail": "claude_profile.sh not found"}
    if not candidate.profile:
        return {"ok": False, "detail": "Claude review profile is missing"}
    if not shutil.which("claude"):
        return {"ok": False, "detail": "claude CLI not found on PATH"}

    # ``status`` only reports the locally cached login flag, which stays "true"
    # even after the subscription token has expired. Prefer a verify-backed
    # health snapshot (or a live probe) so expired profiles are skipped instead
    # of wasting a full generate attempt on every dead profile in the pool.
    mode = _review_probe_mode()
    if mode in {"snapshot", "live"}:
        health = _load_pool_health(repo_root)
        state = health.get(candidate.profile) if health else None
        if state in _UNHEALTHY_PROFILE_STATES:
            return {
                "ok": False,
                "kind": "claude_unauthenticated",
                "detail": (
                    f"{candidate.label} token is {state} "
                    "(scripts/claude_profiles_bootstrap.sh login)"
                ),
            }
        if state == "ok":
            return {"ok": True, "detail": f"{candidate.label} verified (snapshot)"}
        if mode == "live":
            return _claude_live_probe(candidate, script=script, repo_root=repo_root)
        # snapshot mode with no fresh signal falls back to the local status check

    result = subprocess.run(
        [str(script), "status", candidate.profile],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode == 0:
        return {"ok": True, "detail": f"{candidate.label} authenticated"}
    detail = (result.stderr or result.stdout or "").strip()
    return {
        "ok": False,
        "kind": "claude_unauthenticated",
        "detail": detail or f"{candidate.label} is unavailable",
    }


def _openrouter_preflight() -> dict[str, Any]:
    if not is_secret_presence_available(get_secret_presence("OPENROUTER_API_KEY")):
        return {"ok": False, "detail": "OPENROUTER_API_KEY is not configured"}
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection(("openrouter.ai", 443), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname="openrouter.ai"):
                pass
    except OSError as exc:
        return {"ok": False, "detail": f"OpenRouter TLS check failed: {exc}"}
    return {"ok": True, "detail": "OpenRouter API key and TLS look healthy"}


def _direct_api_provider_preflight(provider: str) -> dict[str, Any]:
    key_names = _DIRECT_API_PROVIDER_KEYS[provider]
    for key_name in key_names:
        if is_secret_presence_available(get_secret_presence(key_name)):
            return {"ok": True, "detail": f"{provider} API key is configured"}
    return {"ok": False, "detail": f"{' or '.join(key_names)} is not configured"}


def _claude_profile_script(repo_root: Path) -> Path | None:
    script = (repo_root / "scripts" / "claude_profile.sh").resolve()
    return script if script.exists() else None


def _review_probe_mode() -> str:
    raw = str(os.environ.get("ARAGORA_CLAUDE_REVIEW_PROBE", "")).strip().lower()
    if raw in {"snapshot", "live", "status"}:
        return raw
    return "snapshot"


def _pool_health_path(repo_root: Path) -> Path:
    override = str(os.environ.get("ARAGORA_CLAUDE_POOL_HEALTH_FILE", "")).strip()
    if override:
        return Path(override).expanduser()
    return repo_root / _POOL_HEALTH_RELATIVE_PATH


def _pool_health_ttl_seconds() -> float:
    raw = str(os.environ.get("ARAGORA_CLAUDE_POOL_HEALTH_TTL", "")).strip()
    if not raw:
        return DEFAULT_POOL_HEALTH_TTL_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_POOL_HEALTH_TTL_SECONDS
    return value if value >= 0 else DEFAULT_POOL_HEALTH_TTL_SECONDS


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load_pool_health(repo_root: Path) -> dict[str, str] | None:
    """Return ``{profile_name: state}`` from a fresh verify-backed snapshot.

    Returns ``None`` when the snapshot is missing, malformed, or older than the
    configured TTL so callers fall back to a best-effort local status check.
    """
    path = _pool_health_path(repo_root)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    ttl = _pool_health_ttl_seconds()
    if ttl > 0:
        generated_at = _parse_timestamp(payload.get("generated_at"))
        if generated_at is None:
            return None
        age = (datetime.now(timezone.utc) - generated_at).total_seconds()
        if age > ttl:
            return None
    states: dict[str, str] = {}
    for entry in payload.get("profiles", []) or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        state = str(entry.get("state", "")).strip().lower()
        if name and state:
            states[name] = state
    return states or None


def _claude_live_probe(
    candidate: ReviewCandidate, *, script: Path, repo_root: Path
) -> dict[str, Any]:
    profile = candidate.profile or ""
    if not profile:
        return {"ok": False, "detail": "Claude review profile is missing"}
    try:
        result = subprocess.run(
            [str(script), "exec", profile, "--", "claude", "-p", "ok"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "kind": "claude_unauthenticated",
            "detail": f"{candidate.label} live probe timed out",
        }
    if result.returncode == 0:
        return {"ok": True, "detail": f"{candidate.label} live-probe ok"}
    detail = (result.stderr or result.stdout or "").strip()
    return {
        "ok": False,
        "kind": "claude_unauthenticated",
        "detail": detail[:200] or f"{candidate.label} live probe failed",
    }


async def _run_claude_profile_candidate(
    candidate: ReviewCandidate,
    prompt: str,
    *,
    repo_root: Path,
) -> str:
    script = _claude_profile_script(repo_root)
    if script is None:
        raise CLISubprocessError("claude_profile.sh not found", agent_name=candidate.label)
    if not candidate.profile:
        raise CLISubprocessError("Claude review profile is missing", agent_name=candidate.label)
    proc = await asyncio.create_subprocess_exec(
        str(script),
        "exec",
        candidate.profile,
        "--",
        "claude",
        "--print",
        "-p",
        "-",
        cwd=str(repo_root),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(prompt.encode("utf-8")), timeout=300)
    stdout_text = stdout.decode(errors="replace")
    stderr_text = stderr.decode(errors="replace")
    if proc.returncode != 0:
        raise CLISubprocessError(
            message=f"Claude profile command failed for {candidate.label}",
            agent_name=candidate.label,
            returncode=proc.returncode,
            stderr=(stderr_text or stdout_text).strip()[:500] or None,
        )
    response = _strip_claude_profile_wrapper(stdout_text)
    if not response:
        raise CLISubprocessError(
            message=f"Claude profile command returned empty output for {candidate.label}",
            agent_name=candidate.label,
            returncode=proc.returncode,
            stderr=stderr_text.strip()[:500] or None,
        )
    return response


def _strip_claude_profile_wrapper(output: str) -> str:
    lines = []
    for line in output.splitlines():
        if line.startswith("Using profile home:"):
            continue
        if line.startswith("Command:"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _candidate_failure_detail(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, CLISubprocessError):
        raw = str(exc.stderr or exc).strip().lower()
        if any(marker in raw for marker in _BILLING_MARKERS):
            return ("billing_exhausted", "Reviewer credits are exhausted.")
        return ("cli_failure", "Reviewer CLI command failed.")
    kind = exc.__class__.__name__
    detail = str(exc).strip()
    if detail and detail != kind:
        return (kind, f"{kind}: {detail}")
    return (kind, kind)


def _failure_attempt(candidate: str, *, stage: str, exc: Exception) -> dict[str, Any]:
    kind, detail = _candidate_failure_detail(exc)
    return {
        "candidate": candidate,
        "stage": stage,
        "kind": kind,
        "detail": detail,
    }


def _review_routing_category(attempts: list[dict[str, Any]]) -> str:
    kinds = [str(item.get("kind", "")).strip() for item in attempts]
    if "billing_exhausted" in kinds:
        return "billing_exhausted"
    has_claude_unauth = "claude_unauthenticated" in kinds
    tried_non_claude = any(
        not str(item.get("candidate", "")).strip().startswith("claude") for item in attempts
    )
    if has_claude_unauth and not tried_non_claude:
        return "claude_pool_unauthenticated"
    return "unavailable"


def _review_routing_public_message(category: str) -> str:
    if category == "billing_exhausted":
        return "Reviewer capacity is exhausted. Check the active reviewer account and available credits."
    if category == "claude_pool_unauthenticated":
        return (
            "No authenticated Claude Max review profile is available. "
            "Re-login with: scripts/claude_profiles_bootstrap.sh login "
            "(then refresh: scripts/claude_profiles_bootstrap.sh verify --json)."
        )
    return "No configured review candidate succeeded. Check logs for detail."


def _review_provider_order() -> list[str]:
    raw = str(os.environ.get("ARAGORA_REVIEW_PROVIDER_ORDER", "")).strip()
    if not raw:
        return list(DEFAULT_REVIEW_PROVIDER_ORDER)
    result: list[str] = []
    for item in raw.split(","):
        normalized = str(item).strip().lower()
        if normalized and normalized not in result:
            result.append(normalized)
    return result or list(DEFAULT_REVIEW_PROVIDER_ORDER)


def _claude_review_profiles() -> list[str]:
    raw = str(os.environ.get("ARAGORA_CLAUDE_REVIEW_PROFILES", "")).strip()
    if not raw:
        return list(DEFAULT_CLAUDE_REVIEW_PROFILES)
    result: list[str] = []
    for item in raw.split(","):
        normalized = str(item).strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result or list(DEFAULT_CLAUDE_REVIEW_PROFILES)


def _review_rotate_enabled() -> bool:
    raw = str(os.environ.get("ARAGORA_CLAUDE_REVIEW_ROTATE", "")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _ordered_claude_review_profiles(
    *,
    repo_root: Path | None,
    rotate: bool,
    start_index: int | None,
) -> list[str]:
    """Healthy-first, rotated ordering of the Claude Max review profiles.

    When a fresh health snapshot exists, known-unhealthy profiles are dropped so
    reviews are spread only across usable subscriptions. Rotation advances a
    persisted cursor so each review starts on a different subscription instead of
    always hammering the first profile.
    """
    profiles = _claude_review_profiles()
    if repo_root is not None:
        health = _load_pool_health(repo_root)
        if health:
            filtered = [p for p in profiles if health.get(p) not in _UNHEALTHY_PROFILE_STATES]
            if filtered:
                profiles = filtered
    if rotate and len(profiles) > 1:
        if start_index is not None:
            offset = start_index % len(profiles)
        elif repo_root is not None and repo_root.exists():
            offset = _next_pool_cursor(repo_root, len(profiles))
        else:
            offset = 0
        if offset:
            profiles = profiles[offset:] + profiles[:offset]
    return profiles


def _next_pool_cursor(repo_root: Path, modulo: int) -> int:
    """Return the current rotation offset and advance the persisted cursor."""
    if modulo <= 0:
        return 0
    path = repo_root / ".aragora" / "claude_pool_cursor.json"
    current = 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        current = int(data.get("index", 0))
    except (OSError, ValueError, TypeError):
        current = 0
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"index": (current + 1) % modulo}), encoding="utf-8")
    except OSError:
        pass
    return current % modulo


def _model_family(model_type: str) -> str:
    normalized = str(model_type or "").strip().lower()
    if normalized in _MODEL_FAMILY_OVERRIDES:
        return _MODEL_FAMILY_OVERRIDES[normalized]
    if normalized.startswith("claude"):
        return "claude"
    if normalized.startswith("gpt-"):
        return "codex"
    return normalized
