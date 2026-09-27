"""Generic local runner registration and Boss routing helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import errno
import getpass
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from typing import Any

from aragora.rbac.models import AuthorizationContext
from aragora.swarm.worker_launcher import LaunchConfig

UTC = timezone.utc
VERIFIED_AUTH_MODES = {"chatgpt_login", "api_key", "subscription"}
DEFAULT_RUNNER_STALE_AFTER_SECONDS = 3600
DEFAULT_RUNNER_CLAIM_TTL_SECONDS = 8 * 3600
DEFAULT_RUNNER_ROTATION_INTERVAL_SECONDS = 1800.0
DEFAULT_RUNNER_PROBE_TTL_SECONDS = 3600
RUNNER_PROBE_TOKEN = "ARAGORA_RUNNER_PROBE_OK"
RUNNER_PROBE_FIELD_KEYS = (
    "probe_status",
    "probe_checked_at",
    "probe_detail",
    "probe_latency_seconds",
    "probe_ttl_seconds",
)


@dataclass(frozen=True, slots=True)
class RunnerTypeSpec:
    runner_type: str
    cli_name: str
    path_attr: str | None
    auth_probe: tuple[str, ...] | None
    env_auth_keys: tuple[str, ...]
    default_cost_class: str
    priority_weight: int
    supports_review: bool = True
    supports_login_status: bool = True


RUNNER_TYPE_SPECS: dict[str, RunnerTypeSpec] = {
    "claude": RunnerTypeSpec(
        runner_type="claude",
        cli_name="claude",
        path_attr="claude_path",
        auth_probe=("login", "status"),
        env_auth_keys=("ANTHROPIC_API_KEY",),
        default_cost_class="subscription",
        priority_weight=100,
    ),
    "codex": RunnerTypeSpec(
        runner_type="codex",
        cli_name="codex",
        path_attr="codex_path",
        auth_probe=("login", "status"),
        env_auth_keys=("OPENAI_API_KEY",),
        default_cost_class="subscription",
        priority_weight=80,
    ),
    "gemini-cli": RunnerTypeSpec(
        runner_type="gemini-cli",
        cli_name="gemini",
        path_attr=None,
        auth_probe=None,
        env_auth_keys=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        default_cost_class="api",
        priority_weight=50,
        supports_review=False,
        supports_login_status=False,
    ),
    "openai": RunnerTypeSpec(
        runner_type="openai",
        cli_name="openai",
        path_attr=None,
        auth_probe=None,
        env_auth_keys=("OPENAI_API_KEY",),
        default_cost_class="api",
        priority_weight=45,
        supports_review=False,
        supports_login_status=False,
    ),
    "grok-cli": RunnerTypeSpec(
        runner_type="grok-cli",
        cli_name="grok",
        path_attr=None,
        auth_probe=None,
        env_auth_keys=("XAI_API_KEY", "GROK_API_KEY"),
        default_cost_class="api",
        priority_weight=40,
        supports_review=False,
        supports_login_status=False,
    ),
}


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _env_flag_int(env: dict[str, str], key: str, default: int) -> int:
    raw = str(env.get(key, "")).strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_pid(value: Any) -> int | None:
    pid = _optional_int(value, 0)
    return pid if pid > 0 else None


def _normalized_runner_type(value: str | None) -> str:
    runner_type = _text(value).lower()
    return runner_type or "codex"


def _runner_type_spec(value: str | None) -> RunnerTypeSpec:
    runner_type = _normalized_runner_type(value)
    spec = RUNNER_TYPE_SPECS.get(runner_type)
    if spec is None:
        raise ValueError(f"Unsupported runner type: {runner_type!r}")
    return spec


@dataclass(slots=True)
class RunnerInspection:
    runner_id: str
    runner_type: str
    availability: str
    available: bool
    auth_mode: str
    command_path: str | None = None
    version: str | None = None
    status_summary: str | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    owner_binding: dict[str, Any] = field(default_factory=dict)
    registered: bool = False
    registry_path: str | None = None
    registered_at: str | None = None
    heartbeat_at: str | None = None
    freshness_status: str = "unknown"
    stale_after_seconds: int = DEFAULT_RUNNER_STALE_AFTER_SECONDS
    next_action: str | None = None
    cost_class: str = "local"
    priority_weight: int = 0
    codex_path: str | None = None  # legacy compatibility for older callers/tests
    profile: str | None = None
    probe_status: str | None = None
    probe_checked_at: str | None = None
    probe_detail: str | None = None
    probe_latency_seconds: float | None = None
    probe_ttl_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.command_path is None and self.codex_path is not None:
            self.command_path = self.codex_path
        if (
            self.codex_path is None
            and self.runner_type == "codex"
            and self.command_path is not None
        ):
            self.codex_path = self.command_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner_id": self.runner_id,
            "runner_type": self.runner_type,
            "availability": self.availability,
            "available": self.available,
            "auth_mode": self.auth_mode,
            "command_path": self.command_path,
            "codex_path": self.codex_path,
            "version": self.version,
            "status_summary": self.status_summary,
            "capabilities": dict(self.capabilities),
            "owner_binding": dict(self.owner_binding),
            "registered": self.registered,
            "registry_path": self.registry_path,
            "registered_at": self.registered_at,
            "heartbeat_at": self.heartbeat_at,
            "freshness_status": self.freshness_status,
            "stale_after_seconds": self.stale_after_seconds,
            "next_action": self.next_action,
            "cost_class": self.cost_class,
            "priority_weight": self.priority_weight,
            "profile": self.profile,
            "probe_status": self.probe_status,
            "probe_checked_at": self.probe_checked_at,
            "probe_detail": self.probe_detail,
            "probe_latency_seconds": self.probe_latency_seconds,
            "probe_ttl_seconds": self.probe_ttl_seconds,
        }


CodexRunnerInspection = RunnerInspection


@dataclass(slots=True)
class RunnerProbeResult:
    runner_id: str
    runner_type: str
    status: str
    checked_at: str
    detail: str | None = None
    latency_seconds: float | None = None
    profile: str | None = None
    ttl_seconds: int = DEFAULT_RUNNER_PROBE_TTL_SECONDS

    def to_runner_fields(self) -> dict[str, Any]:
        return {
            "probe_status": self.status,
            "probe_checked_at": self.checked_at,
            "probe_detail": self.detail,
            "probe_latency_seconds": self.latency_seconds,
            "probe_ttl_seconds": self.ttl_seconds,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner_id": self.runner_id,
            "runner_type": self.runner_type,
            "profile": self.profile,
            **self.to_runner_fields(),
        }


@dataclass(slots=True)
class BossRoutingDecision:
    owner_binding: dict[str, Any]
    selected_runner_ids: list[str] = field(default_factory=list)
    selected_runners: list[dict[str, Any]] = field(default_factory=list)
    selection_basis: str = ""
    blocked_reason: str | None = None
    rejected_runner_ids: list[str] = field(default_factory=list)
    next_action: str | None = None
    requested_runner_type: str | None = None
    fallback_reason: str | None = None

    @property
    def is_blocked(self) -> bool:
        return bool(self.blocked_reason)

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_binding": dict(self.owner_binding),
            "selected_runner_ids": list(self.selected_runner_ids),
            "selected_runners": [dict(item) for item in self.selected_runners],
            "selection_basis": self.selection_basis,
            "blocked_reason": self.blocked_reason,
            "rejected_runner_ids": list(self.rejected_runner_ids),
            "next_action": self.next_action,
            "requested_runner_type": self.requested_runner_type,
            "fallback_reason": self.fallback_reason,
        }


class CLIRunnerInspector:
    """Inspect local CLI runner availability and auth state truthfully."""

    def __init__(
        self,
        *,
        runner_type: str = "codex",
        config: LaunchConfig | None = None,
        env: dict[str, str] | None = None,
        profile: str | None = None,
        repo_root: str | Path | None = None,
    ) -> None:
        self.config = config or LaunchConfig()
        self.env = dict(os.environ if env is None else env)
        self.spec = _runner_type_spec(runner_type)
        self.profile = _text(profile) or None
        self.repo_root = Path(repo_root or Path.cwd()).resolve()

    def inspect(self) -> RunnerInspection:
        command_name = self._command_name()
        base_command_path = shutil.which(command_name)
        command_path = self._launch_command_path(base_command_path)
        runner_id = self._runner_id(command_path, command_name=command_name)
        owner = owner_binding_from_env(self.env)
        stale_after_seconds = self._stale_after_seconds()

        if not base_command_path or not command_path:
            return RunnerInspection(
                runner_id=runner_id,
                runner_type=self.spec.runner_type,
                availability="unavailable",
                available=False,
                auth_mode="unavailable",
                command_path=None,
                version=None,
                status_summary=None,
                capabilities=self._capabilities(False, None),
                owner_binding=owner,
                freshness_status="unavailable",
                stale_after_seconds=stale_after_seconds,
                next_action=self._next_action(
                    available=False,
                    auth_mode="unavailable",
                    owner_binding=owner,
                ),
                cost_class=self.spec.default_cost_class,
                priority_weight=self.spec.priority_weight,
                profile=self.profile,
            )

        version_result = self._version_result(base_command_path)
        help_result = self._help_result(base_command_path)
        auth_result = self._auth_result(base_command_path)

        help_text = "\n".join(
            part for part in (help_result.get("stdout", ""), help_result.get("stderr", "")) if part
        ).strip()
        auth_text = "\n".join(
            part for part in (auth_result.get("stdout", ""), auth_result.get("stderr", "")) if part
        ).strip()

        available = bool(
            help_result.get("returncode") == 0
            or version_result.get("returncode") == 0
            or help_text
            or version_result.get("stdout")
            or version_result.get("stderr")
        )
        if not available:
            return RunnerInspection(
                runner_id=runner_id,
                runner_type=self.spec.runner_type,
                availability="unavailable",
                available=False,
                auth_mode="unavailable",
                command_path=command_path,
                version=None,
                status_summary=None,
                capabilities=self._capabilities(False, None),
                owner_binding=owner,
                freshness_status="unavailable",
                stale_after_seconds=stale_after_seconds,
                next_action=self._next_action(
                    available=False,
                    auth_mode="unavailable",
                    owner_binding=owner,
                ),
                cost_class=self.spec.default_cost_class,
                priority_weight=self.spec.priority_weight,
                profile=self.profile,
            )

        auth_mode = self._classify_auth_mode(auth_text)
        version = self._first_line(
            version_result.get("stdout") or version_result.get("stderr") or ""
        )
        return RunnerInspection(
            runner_id=runner_id,
            runner_type=self.spec.runner_type,
            availability="available",
            available=True,
            auth_mode=auth_mode,
            command_path=command_path,
            version=version or None,
            status_summary=self._status_summary(auth_text) or None,
            capabilities=self._capabilities(True, help_text),
            owner_binding=owner,
            freshness_status=self._inspection_freshness(available=True, auth_mode=auth_mode),
            stale_after_seconds=stale_after_seconds,
            next_action=self._next_action(
                available=True,
                auth_mode=auth_mode,
                owner_binding=owner,
            ),
            cost_class=self._cost_class(auth_mode),
            priority_weight=self.spec.priority_weight,
            profile=self.profile,
        )

    def _command_name(self) -> str:
        attr = self.spec.path_attr
        if attr and hasattr(self.config, attr):
            return str(getattr(self.config, attr))
        return self.spec.cli_name

    def _auth_result(self, command_path: str) -> dict[str, Any]:
        if self.spec.runner_type == "claude" and self.profile:
            script = self._claude_profile_script()
            if script is None:
                return {"returncode": 1, "stdout": "", "stderr": "claude_profile.sh not found"}
            return self._run_command([script, "status", self.profile])
        if self.spec.auth_probe:
            return self._run_command([command_path, *self.spec.auth_probe])
        return {
            "returncode": 0
            if any(_text(self.env.get(key)) for key in self.spec.env_auth_keys)
            else 1,
            "stdout": "",
            "stderr": "",
        }

    def _capabilities(self, available: bool, help_text: str | None) -> dict[str, Any]:
        text = (help_text or "").lower()
        supports_exec = available and (
            "exec" in text or self.spec.runner_type in {"claude", "codex"}
        )
        supports_review = available and ("review" in text or self.spec.supports_review)
        max_parallel_key = (
            f"ARAGORA_{self.spec.runner_type.upper().replace('-', '_')}_RUNNER_MAX_CONCURRENCY"
        )
        return {
            "supports_exec": supports_exec,
            "supports_review": supports_review,
            "supports_login_status": available and self.spec.supports_login_status,
            "max_parallel_lanes": _env_flag_int(self.env, max_parallel_key, 1),
            "active_lanes": _env_flag_int(self.env, f"{max_parallel_key}_ACTIVE", 0),
        }

    def _classify_auth_mode(self, auth_text: str) -> str:
        lowered = auth_text.lower()
        if self.spec.runner_type == "codex":
            if "chatgpt" in lowered and "logged in" in lowered:
                return "chatgpt_login"
            if "api key" in lowered and "logged in" in lowered:
                return "api_key"
            return "unknown"
        if self.spec.runner_type == "claude":
            if "api key" in lowered and ("logged in" in lowered or "authenticated" in lowered):
                return "api_key"
            if (
                "logged in" in lowered
                or "subscription" in lowered
                or "max" in lowered
                or "pro" in lowered
            ):
                return "subscription"
            return "unknown"
        if any(_text(self.env.get(key)) for key in self.spec.env_auth_keys):
            return "api_key"
        return "unknown"

    def _cost_class(self, auth_mode: str) -> str:
        if auth_mode == "api_key":
            return "api"
        if auth_mode in {"chatgpt_login", "subscription"}:
            return "subscription"
        return self.spec.default_cost_class

    def _stale_after_seconds(self) -> int:
        return _env_flag_int(
            self.env,
            "ARAGORA_RUNNER_STALE_AFTER_SECONDS",
            DEFAULT_RUNNER_STALE_AFTER_SECONDS,
        )

    @staticmethod
    def _inspection_freshness(*, available: bool, auth_mode: str) -> str:
        if not available:
            return "unavailable"
        if auth_mode not in VERIFIED_AUTH_MODES:
            return "unknown"
        return "fresh"

    @staticmethod
    def _first_line(text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
        return ""

    @classmethod
    def _status_summary(cls, text: str) -> str:
        first = cls._first_line(text)
        if not first.startswith("{"):
            return first
        try:
            payload = json.loads(first if len(text.splitlines()) == 1 else text)
        except ValueError:
            return first
        if not isinstance(payload, dict):
            return first
        parts = []
        if "loggedIn" in payload:
            parts.append(f"loggedIn={payload.get('loggedIn')}")
        auth_method = _text(payload.get("authMethod"))
        if auth_method:
            parts.append(f"authMethod={auth_method}")
        subscription = _text(payload.get("subscriptionType"))
        if subscription:
            parts.append(f"subscriptionType={subscription}")
        return " ".join(parts) or first

    def _runner_id(self, command_path: str | None, *, command_name: str) -> str:
        identity = f"{self.spec.runner_type}:{platform.node()}:{command_path or command_name}"
        if self.profile:
            identity = f"{identity}:{self.profile}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
        return f"{self.spec.runner_type}-runner-{digest}"

    def _launch_command_path(self, base_command_path: str | None) -> str | None:
        if self.spec.runner_type == "claude" and self.profile:
            return self._claude_profile_script()
        return base_command_path

    def _version_result(self, base_command_path: str) -> dict[str, Any]:
        return self._run_command([base_command_path, "--version"])

    def _help_result(self, base_command_path: str) -> dict[str, Any]:
        return self._run_command([base_command_path, "--help"])

    def _claude_profile_script(self) -> str | None:
        script = (self._canonical_repo_root() / "scripts" / "claude_profile.sh").resolve()
        if not script.exists():
            return None
        return str(script)

    def _canonical_repo_root(self) -> Path:
        common_git_dir = self._git_common_dir(self.repo_root)
        if common_git_dir is not None and common_git_dir.name == ".git":
            return common_git_dir.parent.resolve()
        return self.repo_root

    @staticmethod
    def _git_common_dir(repo_root: Path) -> Path | None:
        dot_git = repo_root / ".git"
        if dot_git.is_dir():
            return dot_git.resolve()
        if not dot_git.is_file():
            return None
        try:
            text = dot_git.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not text.startswith("gitdir:"):
            return None
        gitdir = text.split(":", 1)[1].strip()
        resolved = (dot_git.parent / gitdir).resolve()
        if not resolved.is_dir():
            return None
        commondir_file = resolved / "commondir"
        if commondir_file.is_file():
            try:
                commondir = commondir_file.read_text(encoding="utf-8").strip()
            except OSError:
                commondir = ""
            if commondir:
                common = (resolved / commondir).resolve()
                if common.is_dir():
                    return common
        return resolved

    @staticmethod
    def _run_command(command: list[str]) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return {"returncode": 1, "stdout": "", "stderr": ""}
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

    def _next_action(
        self, *, available: bool, auth_mode: str, owner_binding: dict[str, Any]
    ) -> str:
        runner_label = self.spec.runner_type
        if self.profile:
            runner_label = f"{runner_label}:{self.profile}"
        if not available:
            return f"Install the {runner_label} CLI or add `{self._command_name()}` to PATH before registering this runner."
        if auth_mode == "unknown":
            return f"Confirm the local {runner_label} CLI login state before relying on this runner for routed work."
        if not owner_binding.get("user_id"):
            return (
                "Set `ARAGORA_USER_ID` and optional `ARAGORA_WORKSPACE_ID` before registering this "
                "runner to an Aragora owner context."
            )
        return (
            "Runner is eligible for future Boss-mode routing under the bound Aragora owner context."
        )


class CodexRunnerInspector(CLIRunnerInspector):
    def __init__(
        self, *, config: LaunchConfig | None = None, env: dict[str, str] | None = None
    ) -> None:
        super().__init__(runner_type="codex", config=config, env=env)


class ClaudeRunnerInspector(CLIRunnerInspector):
    def __init__(
        self,
        *,
        config: LaunchConfig | None = None,
        env: dict[str, str] | None = None,
        profile: str | None = None,
        repo_root: str | Path | None = None,
    ) -> None:
        super().__init__(
            runner_type="claude",
            config=config,
            env=env,
            profile=profile,
            repo_root=repo_root,
        )


def make_runner_inspector(
    runner_type: str,
    *,
    config: LaunchConfig | None = None,
    env: dict[str, str] | None = None,
    profile: str | None = None,
    repo_root: str | Path | None = None,
) -> CLIRunnerInspector:
    normalized = _normalized_runner_type(runner_type)
    if normalized == "codex":
        return CodexRunnerInspector(config=config, env=env)
    if normalized == "claude":
        return ClaudeRunnerInspector(config=config, env=env, profile=profile, repo_root=repo_root)
    return CLIRunnerInspector(
        runner_type=normalized,
        config=config,
        env=env,
        profile=profile,
        repo_root=repo_root,
    )


def configured_claude_runner_profiles(env: dict[str, str] | None = None) -> list[str]:
    values = dict(os.environ if env is None else env)
    raw = _text(values.get("ARAGORA_CLAUDE_RUNNER_PROFILES"))
    if not raw:
        raw = _text(values.get("ARAGORA_CLAUDE_REVIEW_PROFILES"))
    if not raw:
        return []
    profiles: list[str] = []
    for item in raw.split(","):
        normalized = _text(item)
        if normalized and normalized not in profiles:
            profiles.append(normalized)
    return profiles


def discover_runner_inspections(
    runner_type: str,
    *,
    config: LaunchConfig | None = None,
    env: dict[str, str] | None = None,
    repo_root: str | Path | None = None,
    profiles: set[str] | list[str] | tuple[str, ...] | None = None,
) -> list[RunnerInspection]:
    normalized = _normalized_runner_type(runner_type)
    if normalized == "claude":
        explicit_profiles: list[str] = []
        if profiles is not None:
            candidates = sorted(profiles) if isinstance(profiles, set) else list(profiles)
            for item in candidates:
                normalized_profile = _text(item)
                if normalized_profile and normalized_profile not in explicit_profiles:
                    explicit_profiles.append(normalized_profile)
        else:
            explicit_profiles = configured_claude_runner_profiles(env)
        if explicit_profiles:
            return [
                make_runner_inspector(
                    normalized,
                    config=config,
                    env=env,
                    profile=profile,
                    repo_root=repo_root,
                ).inspect()
                for profile in explicit_profiles
            ]
    return [
        make_runner_inspector(
            normalized,
            config=config,
            env=env,
            repo_root=repo_root,
        ).inspect()
    ]


def refresh_discovered_runners(
    runner_type: str,
    *,
    registry: LocalRunnerRegistry,
    owner_context: AuthorizationContext | None,
    config: LaunchConfig | None = None,
    env: dict[str, str] | None = None,
    repo_root: str | Path | None = None,
    profiles: set[str] | list[str] | tuple[str, ...] | None = None,
) -> list[RunnerInspection]:
    if owner_context is None:
        return []
    inspections = discover_runner_inspections(
        runner_type,
        config=config,
        env=env,
        repo_root=repo_root,
        profiles=profiles,
    )
    for inspection in inspections:
        registry.refresh(
            inspection,
            owner_context=owner_context,
        )
    return inspections


def prioritized_probe_candidates(
    *,
    registry: LocalRunnerRegistry,
    runner_type: str,
    discovered_inspections: list[RunnerInspection],
    owner_context: AuthorizationContext | None,
    selected_runners: list[dict[str, Any]] | None = None,
) -> list[RunnerInspection]:
    inspection_by_id = {
        _text(inspection.runner_id): inspection
        for inspection in discovered_inspections
        if _text(inspection.runner_id)
    }
    selected_ids = {
        _text(item.get("runner_id"))
        for item in selected_runners or []
        if isinstance(item, dict) and _text(item.get("runner_id"))
    }
    registrations = [item for item in registry.list_registrations() if isinstance(item, dict)]
    raw_failed_ids: list[str] = []
    selected_unverified_ids: list[str] = []
    other_unverified_ids: list[str] = []

    def _append_unique(target: list[str], runner_id: object) -> None:
        normalized = _text(runner_id)
        if not normalized or normalized not in inspection_by_id:
            return
        if (
            normalized in raw_failed_ids
            or normalized in selected_unverified_ids
            or normalized in other_unverified_ids
        ):
            return
        target.append(normalized)

    for item in registrations:
        if _text(item.get("runner_type")) != runner_type:
            continue
        if owner_context is not None and not registry._is_owner_compatible(
            item,
            owner_context=owner_context,
        ):
            continue
        runner_id = item.get("runner_id")
        raw_probe_status = _text(item.get("probe_status")).lower()
        live_probe_status = registry._probe_status(item)
        if raw_probe_status == "failed":
            _append_unique(raw_failed_ids, runner_id)
            continue
        if live_probe_status == "passed":
            continue
        if _text(runner_id) in selected_ids:
            _append_unique(selected_unverified_ids, runner_id)
        else:
            _append_unique(other_unverified_ids, runner_id)

    ordered_ids = [*selected_unverified_ids, *raw_failed_ids, *other_unverified_ids]
    return [inspection_by_id[item] for item in ordered_ids]


def probe_runner_execution(
    inspection: RunnerInspection,
    *,
    repo_root: str | Path | None = None,
    timeout_seconds: float = 30.0,
) -> RunnerProbeResult:
    checked_at = _utcnow()
    ttl_seconds = DEFAULT_RUNNER_PROBE_TTL_SECONDS

    if inspection.runner_type not in {"claude", "codex"}:
        return RunnerProbeResult(
            runner_id=inspection.runner_id,
            runner_type=inspection.runner_type,
            status="unsupported",
            checked_at=checked_at,
            detail="Active exec probe is currently implemented for Claude and Codex runners only.",
            profile=inspection.profile,
            ttl_seconds=ttl_seconds,
        )

    command = _probe_command_for_inspection(inspection, repo_root=repo_root)
    if not command:
        return RunnerProbeResult(
            runner_id=inspection.runner_id,
            runner_type=inspection.runner_type,
            status="failed",
            checked_at=checked_at,
            detail=(
                f"No runnable {inspection.runner_type.capitalize()} probe command could be "
                "constructed for this runner."
            ),
            profile=inspection.profile,
            ttl_seconds=ttl_seconds,
        )

    try:
        started = datetime.now(UTC)
        proc = subprocess.run(
            command,
            cwd=str(Path(repo_root or Path.cwd()).resolve()),
            text=True,
            input=_probe_stdin_for_inspection(inspection),
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        latency_seconds = max(0.0, (datetime.now(UTC) - started).total_seconds())
    except subprocess.TimeoutExpired:
        return RunnerProbeResult(
            runner_id=inspection.runner_id,
            runner_type=inspection.runner_type,
            status="failed",
            checked_at=checked_at,
            detail=f"Probe timed out after {timeout_seconds:.0f}s.",
            latency_seconds=timeout_seconds,
            profile=inspection.profile,
            ttl_seconds=ttl_seconds,
        )
    except (FileNotFoundError, OSError) as exc:
        return RunnerProbeResult(
            runner_id=inspection.runner_id,
            runner_type=inspection.runner_type,
            status="failed",
            checked_at=checked_at,
            detail=f"Probe launch failed: {exc}",
            profile=inspection.profile,
            ttl_seconds=ttl_seconds,
        )

    combined = "\n".join(part for part in (proc.stdout, proc.stderr) if part).strip()
    if proc.returncode == 0 and RUNNER_PROBE_TOKEN in combined:
        return RunnerProbeResult(
            runner_id=inspection.runner_id,
            runner_type=inspection.runner_type,
            status="passed",
            checked_at=checked_at,
            detail="Live prompt probe succeeded.",
            latency_seconds=latency_seconds,
            profile=inspection.profile,
            ttl_seconds=ttl_seconds,
        )

    return RunnerProbeResult(
        runner_id=inspection.runner_id,
        runner_type=inspection.runner_type,
        status="failed",
        checked_at=checked_at,
        detail=_probe_failure_detail(combined, returncode=proc.returncode),
        latency_seconds=latency_seconds,
        profile=inspection.profile,
        ttl_seconds=ttl_seconds,
    )


def _probe_command_for_inspection(
    inspection: RunnerInspection,
    *,
    repo_root: str | Path | None = None,
) -> list[str] | None:
    prompt = f"Reply with exactly: {RUNNER_PROBE_TOKEN}"
    if inspection.runner_type == "claude":
        if inspection.profile:
            script = _text(inspection.command_path)
            if not script:
                candidate = (
                    Path(repo_root or Path.cwd()) / "scripts" / "claude_profile.sh"
                ).resolve()
                script = str(candidate) if candidate.exists() else ""
            if not script:
                return None
            return [script, "exec", inspection.profile, "--", "claude", "-p", prompt]
        command_path = _text(inspection.command_path) or "claude"
        return [command_path, "-p", prompt]
    if inspection.runner_type == "codex":
        command_path = _text(inspection.command_path) or _text(inspection.codex_path) or "codex"
        return [command_path, "exec", "-"]
    return None


def _probe_stdin_for_inspection(inspection: RunnerInspection) -> str | None:
    if inspection.runner_type != "codex":
        return None
    return f"Reply with exactly: {RUNNER_PROBE_TOKEN}\n"


def _probe_failure_detail(text: str, *, returncode: int) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        lowered = line.lower()
        if any(
            marker in lowered
            for marker in (
                "authentication",
                "oauth",
                "expired",
                "401",
                "error",
                "failed",
                "invalid_token",
                "protected-resource",
            )
        ):
            return f"Probe failed (exit {returncode}): {line[:240]}"
    for line in lines:
        if line.startswith("Using profile home:") or line.startswith("Command:"):
            continue
        return f"Probe failed (exit {returncode}): {line[:240]}"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return f"Probe failed (exit {returncode}): {stripped[:240]}"
    return f"Probe failed (exit {returncode})."


def _probe_next_action(
    inspection: RunnerInspection,
    probe: RunnerProbeResult,
) -> str | None:
    runner_type = _text(getattr(inspection, "runner_type", ""))
    profile = _text(getattr(inspection, "profile", "")) or None
    command_path = _text(getattr(inspection, "command_path", ""))
    if probe.status == "passed":
        return "Runner execution probe passed. Boss-mode routing can prefer this runner."
    if probe.status != "failed":
        return None

    detail = _text(probe.detail).lower()
    if runner_type == "claude" and profile:
        script = command_path
        if not script:
            candidate = (Path.cwd() / "scripts" / "claude_profile.sh").resolve()
            if candidate.exists():
                script = str(candidate)
        if any(marker in detail for marker in ("oauth", "authenticate", "401", "expired")):
            if script:
                return f"Refresh the local Claude profile login: {script} login {profile}"
            return f"Refresh the local Claude profile login for {profile}."
        return (
            "Re-probe this Claude profile after local inspection: "
            f"ARAGORA_CLAUDE_RUNNER_PROFILES={profile} python3 -m aragora.cli.main "
            "swarm runner probe --runner-type claude --json"
        )
    if runner_type == "codex":
        if any(
            marker in detail
            for marker in ("oauth", "authenticate", "401", "expired", "invalid_token", "protected")
        ):
            executable = command_path or "codex"
            return f"Refresh the local Codex login and re-run the probe: {executable} login"
        return (
            "Re-run the local Codex runner probe after fixing the underlying Codex runner issue: "
            "python3 -m aragora.cli.main swarm runner probe --runner-type codex --json"
        )
    return "Re-run the local runner probe after fixing the underlying runner issue."


def _inspection_payload(inspection: RunnerInspection) -> dict[str, Any]:
    to_dict = getattr(inspection, "to_dict", None)
    if callable(to_dict):
        inspection_payload = to_dict()
        if isinstance(inspection_payload, dict):
            return dict(inspection_payload)
    payload: dict[str, Any] = {}
    for key in (
        "runner_id",
        "runner_type",
        "profile",
        "available",
        "availability",
        "auth_mode",
        "command_path",
        "codex_path",
        "owner_binding",
        "capabilities",
        "cost_class",
        "priority_weight",
        "status_summary",
        "freshness_status",
        "stale_after_seconds",
    ):
        value = getattr(inspection, key, None)
        if value is not None:
            payload[key] = value
    return payload


class LocalRunnerRegistry:
    """Minimal local registry for user-owned CLI runners."""

    def __init__(self, *, path: str | Path | None = None) -> None:
        raw = (
            path
            or os.environ.get("ARAGORA_RUNNER_REGISTRY_PATH")
            or "~/.aragora/swarm_runners.json"
        )
        self.path = Path(raw).expanduser()

    def register(
        self,
        inspection: RunnerInspection,
        *,
        owner_context: AuthorizationContext | None,
    ) -> RunnerInspection:
        registry_path = str(self.path)
        runner_label = inspection.runner_type
        if not inspection.available:
            inspection.registered = False
            inspection.registry_path = registry_path
            inspection.next_action = inspection.next_action or (
                f"Restore local {runner_label} runner availability before registering this runner."
            )
            return inspection
        if inspection.auth_mode == "unknown":
            inspection.registered = False
            inspection.registry_path = registry_path
            inspection.next_action = (
                f"Registration blocked: {runner_label} auth mode is unknown. Confirm the local "
                f"{runner_label} login state before registering this runner for Boss-mode routing."
            )
            return inspection
        if owner_context is None:
            inspection.registered = False
            inspection.registry_path = registry_path
            inspection.next_action = (
                "Set `ARAGORA_USER_ID` and optional `ARAGORA_WORKSPACE_ID` before registering this "
                "runner to an Aragora owner context."
            )
            return inspection

        records = self._load()
        now = _utcnow()
        freshness_status = self._freshness_for_inspection(inspection)
        existing = next(
            (
                dict(item)
                for item in records.get("registrations", [])
                if isinstance(item, dict) and item.get("runner_id") == inspection.runner_id
            ),
            None,
        )
        entry = self._preserve_probe_fields(
            existing,
            {
                **inspection.to_dict(),
                "owner_binding": owner_binding_from_context(owner_context),
                "registered": True,
                "registered_at": now,
                "heartbeat_at": now,
                "freshness_status": freshness_status,
                "updated_at": now,
            },
        )
        records["registrations"] = [
            item
            for item in records.get("registrations", [])
            if isinstance(item, dict) and item.get("runner_id") != inspection.runner_id
        ]
        records["registrations"].append(entry)
        self._save(records)

        inspection.owner_binding = owner_binding_from_context(owner_context)
        inspection.registered = True
        inspection.registry_path = registry_path
        inspection.registered_at = now
        inspection.heartbeat_at = now
        inspection.freshness_status = freshness_status
        inspection.next_action = (
            "Runner registered. Future Boss-mode routing can target this owner-bound runner."
        )
        return inspection

    def heartbeat(
        self,
        inspection: RunnerInspection,
        *,
        owner_context: AuthorizationContext | None,
    ) -> RunnerInspection:
        registry_path = str(self.path)
        inspection.registry_path = registry_path
        if owner_context is None:
            inspection.registered = False
            inspection.next_action = (
                "Set `ARAGORA_USER_ID` and `ARAGORA_WORKSPACE_ID` before refreshing a runner "
                "heartbeat for Boss-mode routing."
            )
            return inspection

        records = self._load()
        registrations = [
            dict(item) for item in records.get("registrations", []) if isinstance(item, dict)
        ]
        existing = next(
            (
                item
                for item in registrations
                if item.get("runner_id") == inspection.runner_id
                and self._is_owner_compatible(item, owner_context=owner_context)
            ),
            None,
        )
        if existing is None:
            inspection.registered = False
            inspection.next_action = (
                "Register this runner for the current Aragora user/workspace context before "
                "refreshing its heartbeat."
            )
            return inspection

        now = _utcnow()
        freshness_status = self._freshness_for_inspection(inspection)
        owner_binding = owner_binding_from_context(owner_context)
        claimed_lanes = self._normalized_claimed_lanes(existing, inspection=inspection)
        updated_entry = self._preserve_probe_fields(
            existing,
            {
                **existing,
                **inspection.to_dict(),
                "registered": True,
                "owner_binding": owner_binding,
                "registered_at": existing.get("registered_at"),
                "heartbeat_at": now,
                "claimed_lanes": claimed_lanes,
                "freshness_status": freshness_status,
                "updated_at": now,
            },
        )
        if claimed_lanes <= 0:
            updated_entry["claim_owner_host"] = None
            updated_entry["claim_owner_pid"] = None
        records["registrations"] = [
            updated_entry if item.get("runner_id") == inspection.runner_id else item
            for item in registrations
        ]
        self._save(records)

        inspection.owner_binding = owner_binding
        inspection.registered = True
        inspection.registered_at = _text(existing.get("registered_at")) or None
        inspection.heartbeat_at = now
        inspection.freshness_status = freshness_status
        inspection.next_action = self._heartbeat_next_action(
            freshness_status, runner_type=inspection.runner_type
        )
        return inspection

    def refresh(
        self,
        inspection: RunnerInspection,
        *,
        owner_context: AuthorizationContext | None,
    ) -> RunnerInspection:
        if owner_context is None:
            inspection.registered = False
            inspection.registry_path = str(self.path)
            inspection.next_action = (
                "Set `ARAGORA_USER_ID` and optional `ARAGORA_WORKSPACE_ID` before refreshing this "
                "runner in the local registry."
            )
            return inspection
        existing = next(
            (
                item
                for item in self.list_registrations()
                if _text(item.get("runner_id")) == _text(inspection.runner_id)
                and self._is_owner_compatible(item, owner_context=owner_context)
            ),
            None,
        )
        if existing is None:
            return self.register(inspection, owner_context=owner_context)
        return self.heartbeat(inspection, owner_context=owner_context)

    def record_probe(
        self,
        inspection: RunnerInspection,
        probe: RunnerProbeResult,
        *,
        owner_context: AuthorizationContext | None,
    ) -> dict[str, Any]:
        runner_payload = {
            **_inspection_payload(inspection),
            **probe.to_runner_fields(),
            "next_action": _probe_next_action(inspection, probe),
        }
        if owner_context is None:
            return runner_payload

        records = self._load()
        registrations = [
            dict(item) for item in records.get("registrations", []) if isinstance(item, dict)
        ]
        updated = False
        for index, item in enumerate(registrations):
            if item.get("runner_id") != inspection.runner_id:
                continue
            if not self._is_owner_compatible(item, owner_context=owner_context):
                continue
            registrations[index] = {
                **item,
                **probe.to_runner_fields(),
                "next_action": _probe_next_action(inspection, probe) or item.get("next_action"),
                "updated_at": _utcnow(),
            }
            runner_payload = dict(registrations[index])
            updated = True
            break

        if updated:
            records["registrations"] = registrations
            self._save(records)

        return runner_payload

    def list_registrations(self) -> list[dict[str, Any]]:
        records = self._load()
        registrations = [
            dict(item) for item in records.get("registrations", []) if isinstance(item, dict)
        ]
        valid_registrations: list[dict[str, Any]] = []
        dedupe_indexes: dict[tuple[str, ...], int] = {}
        pruned = False
        for item in registrations:
            if self._invalid_registration_reason(item) is not None:
                pruned = True
                continue
            dedupe_key = self._registration_dedupe_key(item)
            if dedupe_key is not None:
                existing_index = dedupe_indexes.get(dedupe_key)
                if existing_index is not None:
                    pruned = True
                    current = valid_registrations[existing_index]
                    if self._prefer_registration(item, over=current):
                        valid_registrations[existing_index] = item
                    continue
                dedupe_indexes[dedupe_key] = len(valid_registrations)
            valid_registrations.append(item)
        if pruned:
            records["registrations"] = valid_registrations
            self._save(records)
        return valid_registrations

    def resolve_boss_routing(
        self,
        *,
        owner_context: AuthorizationContext | None,
        requested_runner_type: str | None = None,
        allowed_profiles: set[str] | None = None,
        rotation_interval_seconds: float = DEFAULT_RUNNER_ROTATION_INTERVAL_SECONDS,
    ) -> BossRoutingDecision:
        owner_binding = owner_binding_from_context(owner_context)
        requested = (
            _normalized_runner_type(requested_runner_type) if requested_runner_type else None
        )
        allowed_profile_set = {item for item in (allowed_profiles or set()) if _text(item)}
        selection_basis = (
            "registered=true, freshness_status=fresh, availability=available, auth_mode verified, "
            "owner_binding compatible, live probe healthy, capacity available, ordered by "
            "requested runner type, probe health, priority_weight, cost preference, and "
            "rotation-aware profile balancing"
        )
        if owner_context is None or not _text(owner_context.user_id):
            return BossRoutingDecision(
                owner_binding=owner_binding,
                selection_basis=selection_basis,
                blocked_reason="missing_owner_context",
                next_action=(
                    "Set `ARAGORA_USER_ID` and `ARAGORA_WORKSPACE_ID` before running Boss mode so "
                    "Aragora can route only onto authorized registered runners."
                ),
                requested_runner_type=requested,
            )

        eligible: list[dict[str, Any]] = []
        rejected_runner_ids: list[str] = []
        saw_compatible_nonfresh = False
        saw_requested_type = False
        saw_requested_capacity_exhausted = False
        now = datetime.now(UTC)
        for runner in self.list_registrations():
            runner_type = _text(runner.get("runner_type"))
            if allowed_profile_set and runner_type == "claude":
                runner_profile = _text(runner.get("profile"))
                if runner_profile not in allowed_profile_set:
                    runner_id = _text(runner.get("runner_id"))
                    if runner_id:
                        rejected_runner_ids.append(runner_id)
                    continue
            if self._is_owner_compatible(runner, owner_context=owner_context):
                runner_freshness = self._freshness_status(runner)
                if requested and runner_type == requested:
                    saw_requested_type = True
                    if bool(runner.get("registered")) and runner_freshness != "fresh":
                        saw_compatible_nonfresh = True
                    elif bool(runner.get("registered")):
                        capabilities = dict(runner.get("capabilities") or {})
                        max_parallel = int(capabilities.get("max_parallel_lanes") or 1)
                        if self._effective_active_lanes(runner) >= max_parallel:
                            saw_requested_capacity_exhausted = True
                elif (
                    not requested and bool(runner.get("registered")) and runner_freshness != "fresh"
                ):
                    saw_compatible_nonfresh = True
            if not self._is_runner_eligible(runner, owner_context=owner_context):
                runner_id = _text(runner.get("runner_id"))
                if runner_id:
                    rejected_runner_ids.append(runner_id)
                continue
            eligible.append(self._runner_summary(runner))

        if not eligible:
            blocked_reason = (
                "no_fresh_registered_runners"
                if saw_compatible_nonfresh
                else "no_eligible_registered_runners"
            )
            next_action = (
                "Refresh the heartbeat for an available registered runner in this exact Aragora "
                "user/workspace context before running Boss mode."
                if saw_compatible_nonfresh
                else "Register an available runner for this exact Aragora user/workspace context "
                "before running Boss mode."
            )
            if requested and saw_requested_capacity_exhausted and not saw_compatible_nonfresh:
                next_action = (
                    f"Free capacity on the registered {requested} runner for this exact Aragora "
                    "user/workspace context or register another available runner of that type "
                    "before running Boss mode."
                )
            return BossRoutingDecision(
                owner_binding=owner_binding,
                selection_basis=selection_basis,
                blocked_reason=blocked_reason,
                rejected_runner_ids=sorted(set(rejected_runner_ids)),
                next_action=next_action,
                requested_runner_type=requested,
            )

        eligible.sort(
            key=lambda item: (
                0 if requested and item["runner_type"] == requested else 1,
                self._probe_rank(item.get("probe_status")),
                -int(item.get("priority_weight", 0)),
                self._cost_rank(_text(item.get("cost_class"))),
                self._rotation_rank(
                    item,
                    now=now,
                    rotation_interval_seconds=rotation_interval_seconds,
                ),
                int(item.get("claimed_lanes", 0)),
                int(item.get("selection_count", 0)),
                self._last_selected_sort_key(item),
                -int(item.get("available_capacity", 0)),
                _text(item.get("runner_id")),
            )
        )

        fallback_reason = None
        if requested and eligible and eligible[0]["runner_type"] != requested:
            fallback_reason = (
                "requested_runner_type_unavailable"
                if saw_requested_type
                else "requested_runner_type_not_registered"
            )

        return BossRoutingDecision(
            owner_binding=owner_binding,
            selected_runner_ids=[item["runner_id"] for item in eligible],
            selected_runners=eligible,
            selection_basis=selection_basis,
            rejected_runner_ids=sorted(set(rejected_runner_ids)),
            next_action="Boss mode will route only through the selected registered runner set.",
            requested_runner_type=requested,
            fallback_reason=fallback_reason,
        )

    def claim_runner(
        self,
        runner_id: str,
        *,
        owner_context: AuthorizationContext | None,
    ) -> dict[str, Any] | None:
        normalized_runner_id = _text(runner_id)
        if not normalized_runner_id:
            return None
        records = self._load()
        registrations = [
            dict(item) for item in records.get("registrations", []) if isinstance(item, dict)
        ]
        updated_entry: dict[str, Any] | None = None
        for item in registrations:
            if _text(item.get("runner_id")) != normalized_runner_id:
                continue
            if owner_context is not None and not self._is_owner_compatible(
                item,
                owner_context=owner_context,
            ):
                return None
            claimed_lanes = _optional_int(item.get("claimed_lanes"))
            max_parallel = int(dict(item.get("capabilities") or {}).get("max_parallel_lanes") or 1)
            if self._effective_active_lanes(item) >= max_parallel:
                return None
            updated_entry = {
                **item,
                "claimed_lanes": claimed_lanes + 1,
                "claim_owner_host": platform.node() or None,
                "claim_owner_pid": os.getpid(),
                "last_selected_at": _utcnow(),
                "selection_count": _optional_int(item.get("selection_count")) + 1,
            }
            break
        if updated_entry is None:
            return None
        records["registrations"] = [
            updated_entry if _text(item.get("runner_id")) == normalized_runner_id else item
            for item in registrations
        ]
        self._save(records)
        return self._runner_summary(updated_entry)

    def release_runner_claim(
        self,
        runner_id: str,
        *,
        owner_context: AuthorizationContext | None = None,
    ) -> dict[str, Any] | None:
        normalized_runner_id = _text(runner_id)
        if not normalized_runner_id:
            return None
        records = self._load()
        registrations = [
            dict(item) for item in records.get("registrations", []) if isinstance(item, dict)
        ]
        updated_entry: dict[str, Any] | None = None
        for item in registrations:
            if _text(item.get("runner_id")) != normalized_runner_id:
                continue
            if owner_context is not None and not self._is_owner_compatible(
                item,
                owner_context=owner_context,
            ):
                return None
            next_claimed_lanes = max(0, _optional_int(item.get("claimed_lanes")) - 1)
            updated_entry = {
                **item,
                "claimed_lanes": next_claimed_lanes,
                "claim_owner_host": _text(item.get("claim_owner_host")) or None,
                "claim_owner_pid": _optional_pid(item.get("claim_owner_pid")),
            }
            if next_claimed_lanes <= 0:
                updated_entry["claim_owner_host"] = None
                updated_entry["claim_owner_pid"] = None
            break
        if updated_entry is None:
            return None
        records["registrations"] = [
            updated_entry if _text(item.get("runner_id")) == normalized_runner_id else item
            for item in registrations
        ]
        self._save(records)
        return self._runner_summary(updated_entry)

    def _runner_summary(self, runner: dict[str, Any]) -> dict[str, Any]:
        capabilities = dict(runner.get("capabilities") or {})
        max_parallel = int(capabilities.get("max_parallel_lanes") or 1)
        claimed_lanes = _optional_int(runner.get("claimed_lanes"))
        active_lanes = self._effective_active_lanes(runner)
        probe_status = self._probe_status(runner)
        return {
            "runner_id": _text(runner.get("runner_id")),
            "runner_type": _text(runner.get("runner_type")),
            "profile": _text(runner.get("profile")) or None,
            "auth_mode": _text(runner.get("auth_mode")),
            "cost_class": _text(runner.get("cost_class")) or "local",
            "priority_weight": int(runner.get("priority_weight") or 0),
            "freshness_status": self._freshness_status(runner),
            "heartbeat_at": _text(runner.get("heartbeat_at")) or None,
            "stale_after_seconds": int(
                runner.get("stale_after_seconds") or DEFAULT_RUNNER_STALE_AFTER_SECONDS
            ),
            "owner_binding": dict(runner.get("owner_binding") or {}),
            "capabilities": capabilities,
            "claimed_lanes": claimed_lanes,
            "claim_owner_host": _text(runner.get("claim_owner_host")) or None,
            "claim_owner_pid": _optional_pid(runner.get("claim_owner_pid")),
            "selection_count": _optional_int(runner.get("selection_count")),
            "last_selected_at": _text(runner.get("last_selected_at")) or None,
            "available_capacity": max(0, max_parallel - active_lanes),
            "active_lanes": active_lanes,
            "command_path": _text(runner.get("command_path") or runner.get("codex_path")) or None,
            "probe_status": probe_status,
            "probe_checked_at": (
                _text(runner.get("probe_checked_at")) or None if probe_status else None
            ),
            "probe_detail": _text(runner.get("probe_detail")) or None if probe_status else None,
            "probe_latency_seconds": (
                runner.get("probe_latency_seconds") if probe_status else None
            ),
            "probe_ttl_seconds": (
                int(runner.get("probe_ttl_seconds") or DEFAULT_RUNNER_PROBE_TTL_SECONDS)
                if probe_status
                else None
            ),
        }

    def _is_runner_eligible(
        self,
        runner: dict[str, Any],
        *,
        owner_context: AuthorizationContext,
    ) -> bool:
        if not bool(runner.get("registered")):
            return False
        if _text(runner.get("availability")) != "available" or not bool(
            runner.get("available", True)
        ):
            return False
        if _text(runner.get("auth_mode")) not in VERIFIED_AUTH_MODES:
            return False
        if self._freshness_status(runner) != "fresh":
            return False
        if not self._is_owner_compatible(runner, owner_context=owner_context):
            return False
        if self._probe_status(runner) == "failed":
            return False
        capabilities = dict(runner.get("capabilities") or {})
        max_parallel = int(capabilities.get("max_parallel_lanes") or 1)
        active_lanes = self._effective_active_lanes(runner)
        if active_lanes >= max_parallel:
            return False
        return True

    def _invalid_registration_reason(self, runner: dict[str, Any]) -> str | None:
        command_path = _text(runner.get("command_path") or runner.get("codex_path"))
        if not command_path:
            return None
        if not self._command_path_exists(command_path):
            return "missing_command_executable"
        return None

    @staticmethod
    def _registration_dedupe_key(runner: dict[str, Any]) -> tuple[str, ...] | None:
        runner_type = _text(runner.get("runner_type"))
        profile = _text(runner.get("profile"))
        if runner_type == "claude" and profile:
            owner_binding = dict(runner.get("owner_binding") or {})
            return (
                "claude_profile",
                profile,
                _text(owner_binding.get("user_id")),
                _text(owner_binding.get("workspace_id")),
                _text(owner_binding.get("org_id")),
            )
        return None

    def _prefer_registration(
        self,
        candidate: dict[str, Any],
        *,
        over: dict[str, Any],
    ) -> bool:
        return self._registration_rank(candidate) < self._registration_rank(over)

    def _registration_rank(self, runner: dict[str, Any]) -> tuple[int, int, float, float, str]:
        command_path = _text(runner.get("command_path") or runner.get("codex_path"))
        return (
            self._command_path_stability_rank(command_path),
            self._dedupe_probe_rank(self._probe_status(runner)),
            -self._timestamp_rank(_text(runner.get("probe_checked_at"))),
            -self._timestamp_rank(_text(runner.get("heartbeat_at"))),
            _text(runner.get("runner_id")),
        )

    @staticmethod
    def _command_path_stability_rank(command_path: str) -> int:
        normalized = _text(command_path)
        if not normalized:
            return 1
        marker = f"{os.sep}.worktrees{os.sep}"
        if marker in normalized or (
            os.altsep and f"{os.altsep}.worktrees{os.altsep}" in normalized
        ):
            return 1
        return 0

    @staticmethod
    def _dedupe_probe_rank(status: Any) -> int:
        normalized = _text(status).lower()
        if normalized == "passed":
            return 0
        if normalized == "failed":
            return 1
        return 2

    def _timestamp_rank(self, value: str) -> float:
        parsed = self._parse_timestamp(value)
        if parsed is None:
            return 0.0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()

    @staticmethod
    def _command_path_exists(command_path: str) -> bool:
        normalized = _text(command_path)
        if not normalized:
            return False
        if (
            Path(normalized).is_absolute()
            or os.sep in normalized
            or (os.altsep and os.altsep in normalized)
        ):
            return Path(normalized).exists()
        return shutil.which(normalized) is not None

    @staticmethod
    def _effective_active_lanes(runner: dict[str, Any]) -> int:
        capabilities = dict(runner.get("capabilities") or {})
        base_active = _optional_int(capabilities.get("active_lanes") or runner.get("active_lanes"))
        return base_active + _optional_int(runner.get("claimed_lanes"))

    @staticmethod
    def _last_selected_sort_key(runner: dict[str, Any]) -> float:
        value = _text(runner.get("last_selected_at"))
        if not value:
            return 0.0
        parsed = LocalRunnerRegistry._parse_timestamp(value)
        if parsed is None:
            return 0.0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()

    @staticmethod
    def _rotation_rank(
        runner: dict[str, Any],
        *,
        now: datetime,
        rotation_interval_seconds: float,
    ) -> tuple[int, float]:
        value = _text(runner.get("last_selected_at"))
        if not value:
            return (0, 0.0)
        parsed = LocalRunnerRegistry._parse_timestamp(value)
        if parsed is None:
            return (0, 0.0)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        age_seconds = max(0.0, (now - parsed).total_seconds())
        hot = 1 if age_seconds < rotation_interval_seconds else 0
        return (hot, -age_seconds)

    @staticmethod
    def _is_owner_compatible(
        runner: dict[str, Any],
        *,
        owner_context: AuthorizationContext,
    ) -> bool:
        owner_binding = dict(runner.get("owner_binding") or {})
        if _text(owner_binding.get("user_id")) != _text(owner_context.user_id):
            return False

        runner_workspace = _text(owner_binding.get("workspace_id"))
        context_workspace = _text(owner_context.workspace_id)
        if runner_workspace != context_workspace:
            return False

        runner_org = _text(owner_binding.get("org_id"))
        context_org = _text(owner_context.org_id)
        if runner_org and context_org and runner_org != context_org:
            return False

        return True

    @staticmethod
    def _freshness_for_inspection(inspection: RunnerInspection) -> str:
        if not inspection.available:
            return "unavailable"
        if inspection.auth_mode not in VERIFIED_AUTH_MODES:
            return "unknown"
        return "fresh"

    def _freshness_status(self, runner: dict[str, Any]) -> str:
        if _text(runner.get("availability")) != "available" or not bool(
            runner.get("available", True)
        ):
            return "unavailable"
        if _text(runner.get("auth_mode")) not in VERIFIED_AUTH_MODES:
            return "unknown"

        heartbeat_at = _text(runner.get("heartbeat_at"))
        if not heartbeat_at:
            return "stale"
        heartbeat_dt = self._parse_timestamp(heartbeat_at)
        if heartbeat_dt is None:
            return "unknown"

        stale_after_seconds = int(
            runner.get("stale_after_seconds") or DEFAULT_RUNNER_STALE_AFTER_SECONDS
        )
        age_seconds = max(0.0, (datetime.now(UTC) - heartbeat_dt).total_seconds())
        if age_seconds > stale_after_seconds:
            return "stale"
        return "fresh"

    def _normalized_claimed_lanes(
        self,
        runner: dict[str, Any],
        *,
        inspection: RunnerInspection | None = None,
    ) -> int:
        claimed_lanes = _optional_int(runner.get("claimed_lanes"))
        if claimed_lanes <= 0:
            return 0
        inspection_payload = inspection.to_dict() if inspection is not None else {}
        if self._effective_active_lanes(inspection_payload) > 0:
            return claimed_lanes
        if claimed_lanes == 1 and self._claim_owner_process_is_dead(runner):
            return 0
        last_selected_at = self._parse_timestamp(_text(runner.get("last_selected_at")))
        if last_selected_at is None:
            return claimed_lanes
        if last_selected_at.tzinfo is None:
            last_selected_at = last_selected_at.replace(tzinfo=UTC)
        claim_ttl_seconds = int(runner.get("claim_ttl_seconds") or DEFAULT_RUNNER_CLAIM_TTL_SECONDS)
        age_seconds = max(0.0, (datetime.now(UTC) - last_selected_at).total_seconds())
        if age_seconds > claim_ttl_seconds:
            return 0
        return claimed_lanes

    @staticmethod
    def _claim_owner_process_is_dead(runner: dict[str, Any]) -> bool:
        claim_owner_pid = _optional_pid(runner.get("claim_owner_pid"))
        if claim_owner_pid is None:
            return False
        claim_owner_host = _text(runner.get("claim_owner_host"))
        local_host = _text(platform.node())
        if claim_owner_host and local_host and claim_owner_host != local_host:
            return False
        try:
            os.kill(claim_owner_pid, 0)
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                return True
            return False
        return False

    def _probe_status(self, runner: dict[str, Any]) -> str | None:
        status = _text(runner.get("probe_status")).lower() or None
        if not status:
            return None
        checked_at = _text(runner.get("probe_checked_at"))
        if not checked_at:
            return None
        checked_dt = self._parse_timestamp(checked_at)
        if checked_dt is None:
            return None
        if checked_dt.tzinfo is None:
            checked_dt = checked_dt.replace(tzinfo=UTC)
        ttl_seconds = int(runner.get("probe_ttl_seconds") or DEFAULT_RUNNER_PROBE_TTL_SECONDS)
        age_seconds = max(0.0, (datetime.now(UTC) - checked_dt).total_seconds())
        if age_seconds > ttl_seconds:
            return None
        return status

    @staticmethod
    def _probe_rank(status: Any) -> int:
        normalized = _text(status).lower()
        if normalized == "passed":
            return 0
        if normalized == "failed":
            return 2
        return 1

    @staticmethod
    def _preserve_probe_fields(
        existing: dict[str, Any] | None,
        updated: dict[str, Any],
    ) -> dict[str, Any]:
        if not existing:
            return updated
        merged = dict(updated)
        for key in RUNNER_PROBE_FIELD_KEYS:
            if merged.get(key) is None and existing.get(key) is not None:
                merged[key] = existing.get(key)
        return merged

    @staticmethod
    def _heartbeat_next_action(freshness_status: str, *, runner_type: str) -> str:
        if freshness_status == "fresh":
            return (
                "Runner heartbeat refreshed. Boss mode can route work to this runner while the "
                "heartbeat remains fresh."
            )
        if freshness_status == "unavailable":
            return (
                f"Runner heartbeat recorded an unavailable {runner_type} runner. Restore the local "
                "CLI before relying on Boss-mode routing."
            )
        return (
            "Runner heartbeat recorded a non-fresh state. Confirm local availability and auth "
            "before relying on Boss-mode routing."
        )

    @staticmethod
    def _cost_rank(cost_class: str) -> int:
        ranks = {"subscription": 0, "local": 1, "api": 2}
        return ranks.get(cost_class, 3)

    @staticmethod
    def _parse_timestamp(value: str) -> datetime | None:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"registrations": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"registrations": []}
        registrations = data.get("registrations", [])
        if not isinstance(registrations, list):
            registrations = []
        return {"registrations": registrations}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, indent=2, sort_keys=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f"{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(payload)
                temp_path = Path(handle.name)
            temp_path.replace(self.path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)


def authorization_context_from_env(
    env: dict[str, str] | None = None,
) -> AuthorizationContext | None:
    values = dict(os.environ if env is None else env)
    user_id = _text(values.get("ARAGORA_USER_ID") or values.get("ARAGORA_ACTOR_ID"))
    if not user_id:
        return None
    workspace_id = (
        _text(values.get("ARAGORA_WORKSPACE_ID") or values.get("ARAGORA_WORKSPACE")) or None
    )
    org_id = _text(values.get("ARAGORA_ORG_ID")) or None
    email = _text(values.get("ARAGORA_USER_EMAIL")) or None
    role = _text(values.get("ARAGORA_ROLE"))
    roles = {role} if role else set()
    return AuthorizationContext(
        user_id=user_id,
        user_email=email,
        org_id=org_id,
        workspace_id=workspace_id,
        roles=roles,
    )


def _repo_workspace_id(repo_root: Path | None) -> str | None:
    candidate = (repo_root or Path.cwd()).resolve()
    common_dir_proc = subprocess.run(
        ["git", "-C", str(candidate), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        text=True,
        capture_output=True,
        check=False,
    )
    if common_dir_proc.returncode == 0 and common_dir_proc.stdout.strip():
        common_dir = Path(common_dir_proc.stdout.strip()).resolve()
        if common_dir.name == ".git" and common_dir.parent.name.strip():
            return common_dir.parent.name.strip()

    proc = subprocess.run(
        ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        candidate = Path(proc.stdout.strip()).resolve()
    name = candidate.name.strip()
    return name or None


def authorization_context_with_defaults(
    repo_root: Path | None = None,
    env: dict[str, str] | None = None,
) -> AuthorizationContext | None:
    values = dict(os.environ if env is None else env)
    context = authorization_context_from_env(values)
    if context is not None and _text(context.user_id):
        if _text(context.workspace_id):
            return context
        workspace_id = _repo_workspace_id(repo_root)
        if not workspace_id:
            return context
        return AuthorizationContext(
            user_id=context.user_id,
            user_email=context.user_email,
            org_id=context.org_id,
            workspace_id=workspace_id,
            roles=set(context.roles),
        )

    user_id = _text(values.get("USER") or values.get("USERNAME"))
    if not user_id:
        try:
            user_id = _text(getpass.getuser())
        except (OSError, KeyError):
            user_id = ""
    if not user_id:
        return context

    workspace_id = _text(
        values.get("ARAGORA_WORKSPACE_ID") or values.get("ARAGORA_WORKSPACE")
    ) or _repo_workspace_id(repo_root)
    org_id = _text(values.get("ARAGORA_ORG_ID")) or None
    email = _text(values.get("ARAGORA_USER_EMAIL")) or None
    role = _text(values.get("ARAGORA_ROLE"))
    roles = {role} if role else set()
    return AuthorizationContext(
        user_id=user_id,
        user_email=email,
        org_id=org_id,
        workspace_id=workspace_id or None,
        roles=roles,
    )


def owner_binding_from_context(context: AuthorizationContext | None) -> dict[str, Any]:
    if context is None:
        return {"user_id": None, "workspace_id": None, "org_id": None}
    return {
        "user_id": context.user_id,
        "workspace_id": context.workspace_id,
        "org_id": context.org_id,
    }


def owner_binding_from_env(env: dict[str, str] | None = None) -> dict[str, Any]:
    return owner_binding_from_context(authorization_context_from_env(env))
