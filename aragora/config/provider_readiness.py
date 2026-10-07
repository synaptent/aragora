"""Provider credential discovery shared by CLI bootstrap surfaces.

This module intentionally stops at configuration discovery. Live provider
preflights are slower and can mutate rate-limit state, so doctor/validate-env
report configured-vs-missing here and leave live-answer proof to explicit
smoke tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import shutil
import subprocess
from typing import Iterable


@dataclass(frozen=True)
class ProviderCredentialSpec:
    """A provider and the environment variables that can configure it."""

    provider: str
    display_name: str
    env_vars: tuple[str, ...]


@dataclass(frozen=True)
class ProviderCredentialStatus:
    """Credential discovery result for one provider."""

    provider: str
    display_name: str
    configured: bool
    available_via: str | None
    checked_env_vars: tuple[str, ...]
    status: str
    message: str


@dataclass(frozen=True)
class ProviderReadinessReport:
    """Credential discovery report after env/dotenv/secret hydration."""

    providers: tuple[ProviderCredentialStatus, ...]
    hydrated_env_vars: tuple[str, ...]
    dotenv_paths: tuple[str, ...]
    discovery_errors: tuple[str, ...]

    @property
    def configured_providers(self) -> tuple[str, ...]:
        return tuple(status.provider for status in self.providers if status.configured)

    @property
    def any_configured(self) -> bool:
        return bool(self.configured_providers)


PROVIDER_CREDENTIAL_SPECS: tuple[ProviderCredentialSpec, ...] = (
    ProviderCredentialSpec("anthropic", "Anthropic", ("ANTHROPIC_API_KEY",)),
    ProviderCredentialSpec("openai", "OpenAI", ("OPENAI_API_KEY",)),
    ProviderCredentialSpec("openrouter", "OpenRouter", ("OPENROUTER_API_KEY",)),
    ProviderCredentialSpec("gemini", "Google Gemini", ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
    ProviderCredentialSpec("xai", "xAI/Grok", ("XAI_API_KEY", "GROK_API_KEY")),
    ProviderCredentialSpec("mistral", "Mistral", ("MISTRAL_API_KEY",)),
    ProviderCredentialSpec("deepseek", "DeepSeek", ("DEEPSEEK_API_KEY",)),
    ProviderCredentialSpec("kimi", "Moonshot Kimi", ("KIMI_API_KEY",)),
    ProviderCredentialSpec("tinker", "Tinker", ("TINKER_API_KEY",)),
)

LOCAL_OR_DEMO_AGENT_TYPES = frozenset({"demo", "mock", "ollama", "lm-studio", "local"})

CLI_AGENT_COMMANDS: dict[str, tuple[str, ...]] = {
    "claude": ("claude",),
    "codex": ("codex",),
    "openai": ("openai",),
    "gemini-cli": ("gemini",),
    "grok-cli": ("grok",),
    "qwen-cli": ("qwen",),
    "deepseek-cli": ("deepseek",),
    "kilocode": ("kilocode",),
}


def _cli_command_available(command: str) -> bool:
    """Return true when a CLI command is discoverable from normal agent shells."""

    if shutil.which(command):
        return True

    shell = os.environ.get("SHELL") or "/bin/zsh"
    try:
        result = subprocess.run(  # noqa: S603 - command is an argv list from static agent metadata
            [shell, "-lc", f"command -v {shlex.quote(command)}"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


AGENT_PROVIDER_ALIASES: dict[str, tuple[str, ...]] = {
    "anthropic-api": ("anthropic", "openrouter"),
    "claude": ("anthropic", "openrouter"),
    "openai-api": ("openai", "openrouter"),
    "openai": ("openai",),
    "codex": ("openai", "openrouter"),
    "gpt": ("openai", "openrouter"),
    "gemini": ("gemini",),
    "gemini-api": ("gemini",),
    "grok": ("xai",),
    "grok-api": ("xai",),
    "mistral": ("mistral", "openrouter"),
    "mistral-api": ("mistral", "openrouter"),
    "codestral": ("mistral",),
    "deepseek": ("deepseek", "openrouter"),
    "deepseek-r1": ("deepseek", "openrouter"),
    "deepseek-v3": ("deepseek", "openrouter"),
    "deepseek-v4-pro": ("deepseek", "openrouter"),
    "llama": ("openrouter",),
    "llama4-maverick": ("openrouter",),
    "llama4-scout": ("openrouter",),
    "qwen": ("openrouter",),
    "qwen-max": ("openrouter",),
    "qwen-3.5": ("openrouter",),
    "yi": ("openrouter",),
    "kimi": ("openrouter",),
    "kimi-legacy": ("kimi",),
    "kimi-thinking": ("openrouter",),
    "sonar": ("openrouter",),
    "command-r": ("openrouter",),
    "jamba": ("openrouter",),
    "openrouter": ("openrouter",),
    "tinker": ("tinker",),
    "tinker-llama": ("tinker",),
    "tinker-qwen": ("tinker",),
    "tinker-deepseek": ("tinker",),
}


def _nonempty_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _load_dotenv_paths(paths: Iterable[Path] | None = None) -> tuple[str, ...]:
    """Best-effort dotenv loading without making python-dotenv mandatory."""

    candidates = tuple(
        paths
        or (
            Path.cwd() / ".env",
            Path.cwd() / ".env.local",
            Path.home() / ".aragora" / ".env",
        )
    )
    existing = tuple(path for path in candidates if path.exists())
    if not existing:
        return ()

    try:
        from dotenv import load_dotenv
    except ImportError:
        return ()

    loaded: list[str] = []
    for path in existing:
        if load_dotenv(path, override=False):
            loaded.append(str(path))
    return tuple(loaded)


def _hydrate_from_secret_loaders(env_vars: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        from aragora.config.secrets import hydrate_env_from_secrets
    except ImportError as exc:
        return (), (f"secret loader unavailable: {exc}",)

    try:
        hydrated = hydrate_env_from_secrets(names=env_vars, overwrite=False)
    except Exception as exc:  # noqa: BLE001 - diagnostics must not crash on secret backends
        return (), (f"secret loader failed: {type(exc).__name__}: {exc}",)
    return tuple(sorted(hydrated)), ()


def discover_provider_credentials(
    *,
    hydrate: bool = True,
    load_dotenv: bool = True,
) -> ProviderReadinessReport:
    """Discover configured provider credentials through the canonical bootstrap path."""

    dotenv_paths: tuple[str, ...] = ()
    if load_dotenv:
        dotenv_paths = _load_dotenv_paths()

    env_vars = sorted({env_var for spec in PROVIDER_CREDENTIAL_SPECS for env_var in spec.env_vars})
    hydrated: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    missing_env_vars = [env_var for env_var in env_vars if not _nonempty_env(env_var)]
    if hydrate and missing_env_vars:
        hydrated, errors = _hydrate_from_secret_loaders(missing_env_vars)

    statuses: list[ProviderCredentialStatus] = []
    for spec in PROVIDER_CREDENTIAL_SPECS:
        available_via = next((env_var for env_var in spec.env_vars if _nonempty_env(env_var)), None)
        if available_via:
            statuses.append(
                ProviderCredentialStatus(
                    provider=spec.provider,
                    display_name=spec.display_name,
                    configured=True,
                    available_via=available_via,
                    checked_env_vars=spec.env_vars,
                    status="configured",
                    message="credential configured; live provider answer not checked",
                )
            )
        else:
            statuses.append(
                ProviderCredentialStatus(
                    provider=spec.provider,
                    display_name=spec.display_name,
                    configured=False,
                    available_via=None,
                    checked_env_vars=spec.env_vars,
                    status="missing_config",
                    message=f"set one of: {', '.join(spec.env_vars)}",
                )
            )

    return ProviderReadinessReport(
        providers=tuple(statuses),
        hydrated_env_vars=hydrated,
        dotenv_paths=dotenv_paths,
        discovery_errors=errors,
    )


def agent_provider_options(agent_type: str) -> tuple[str, ...]:
    """Return provider credential names that can satisfy an agent type."""

    normalized = str(agent_type or "").strip().lower()
    if normalized in LOCAL_OR_DEMO_AGENT_TYPES:
        return ()
    if "/" in normalized:
        return ("openrouter",)
    return AGENT_PROVIDER_ALIASES.get(normalized, (normalized,))


def agent_type_has_configured_provider(
    agent_type: str,
    report: ProviderReadinessReport | None = None,
) -> bool:
    """Check whether an agent type is usable under the discovered credentials."""

    normalized = str(agent_type or "").strip().lower()
    if normalized in LOCAL_OR_DEMO_AGENT_TYPES:
        return True

    options = agent_provider_options(agent_type)
    report = report or discover_provider_credentials()
    configured = set(report.configured_providers)
    if options and any(provider in configured for provider in options):
        return True

    cli_commands = CLI_AGENT_COMMANDS.get(normalized, ())
    if cli_commands:
        return any(_cli_command_available(command) for command in cli_commands)

    return not options


def format_provider_bootstrap_error(report: ProviderReadinessReport) -> str:
    """Human-readable error shared by ask/doctor/validate-env surfaces."""

    checked = sorted(
        {env_var for status in report.providers for env_var in status.checked_env_vars}
    )
    lines = [
        "No usable AI provider credential was discovered.",
        "Checked env, .env files, and configured secret loaders.",
        "Set one of: " + ", ".join(checked),
        "Then run: aragora validate-env --smoke --agents <agent> --verbose",
    ]
    if report.discovery_errors:
        lines.append("Credential loader notes: " + "; ".join(report.discovery_errors))
    return "\n".join(lines)
