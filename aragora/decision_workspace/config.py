"""Decision workspace settings, read from the environment on every call.

Every setting fails closed: no configured agents means intake is refused, and
an unreadable limit falls back to its default rather than to "unlimited".
"""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ENV_AGENTS = "ARAGORA_WORKSPACE_AGENTS"
ENV_MAX_DOCUMENTS = "ARAGORA_WORKSPACE_MAX_DOCUMENTS"
ENV_MAX_FILE_BYTES = "ARAGORA_WORKSPACE_MAX_FILE_BYTES"
ENV_MAX_PASTED_CHARS = "ARAGORA_WORKSPACE_MAX_PASTED_CHARS"
ENV_CONTEXT_CHAR_BUDGET = "ARAGORA_WORKSPACE_CONTEXT_CHAR_BUDGET"
ENV_DECISION_BUDGET_USD = "ARAGORA_DECISION_BUDGET_USD"
ENV_RUN_TIMEOUT_SECONDS = "ARAGORA_WORKSPACE_RUN_TIMEOUT_SECONDS"

DEFAULT_MAX_DOCUMENTS = 10
DEFAULT_MAX_FILE_BYTES = 1_048_576
DEFAULT_MAX_PASTED_CHARS = 204_800
DEFAULT_CONTEXT_CHAR_BUDGET = 24_000
DEFAULT_DECISION_BUDGET_USD = 1.00
DEFAULT_RUN_TIMEOUT_SECONDS = 600

AGENTS_NOT_CONFIGURED_MESSAGE = (
    f"No agents are configured for the decision workspace. Set {ENV_AGENTS} to a "
    "comma-separated list of agent specs (for example 'openai-api|gpt-5.5,grok')."
)

_warned: set[tuple[str, str]] = set()


@dataclass(frozen=True, slots=True)
class AgentOption:
    """One agent the workspace offers, as configured."""

    spec: str
    provider: str
    model: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {"spec": self.spec, "provider": self.provider, "model": self.model}


@dataclass(frozen=True, slots=True)
class AgentOptions:
    """The offered agents, or why none can be offered."""

    agents: tuple[AgentOption, ...]
    error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.agents) and self.error is None

    @property
    def specs(self) -> tuple[str, ...]:
        return tuple(option.spec for option in self.agents)


@dataclass(frozen=True, slots=True)
class WorkspaceLimits:
    """Per-decision intake limits."""

    max_documents: int
    max_file_bytes: int
    max_pasted_chars: int


def agent_options(env: Mapping[str, str] | None = None) -> AgentOptions:
    """Parse ``ARAGORA_WORKSPACE_AGENTS``.

    Entries are comma-separated agent specs (``provider|model|persona|role``
    or a bare provider), trimmed, with blanks and repeats dropped. A single
    entry that is not a valid agent spec disables the whole list, so a typo
    never silently narrows the panel.
    """
    from aragora.agents.spec import AgentSpec

    source = os.environ if env is None else env
    raw = source.get(ENV_AGENTS, "") or ""
    entries: list[str] = []
    for part in raw.split(","):
        entry = part.strip()
        if entry and entry not in entries:
            entries.append(entry)
    if not entries:
        return AgentOptions(agents=(), error=AGENTS_NOT_CONFIGURED_MESSAGE)

    options: list[AgentOption] = []
    for entry in entries:
        try:
            spec = AgentSpec.parse(entry, _warn=False)
        except ValueError as exc:
            _warn_once(ENV_AGENTS, entry, "invalid agent spec %r in %s: %s", entry, ENV_AGENTS, exc)
            return AgentOptions(
                agents=(),
                error=(
                    f"{ENV_AGENTS} contains an invalid agent spec '{entry}', so no "
                    "agents are offered. Fix the entry and restart the server."
                ),
            )
        options.append(AgentOption(spec=entry, provider=spec.provider, model=spec.model))
    return AgentOptions(agents=tuple(options))


def workspace_limits(env: Mapping[str, str] | None = None) -> WorkspaceLimits:
    """Read the intake limits; a missing, non-integer or non-positive value uses the default."""
    source = os.environ if env is None else env
    return WorkspaceLimits(
        max_documents=_positive_int(source, ENV_MAX_DOCUMENTS, DEFAULT_MAX_DOCUMENTS),
        max_file_bytes=_positive_int(source, ENV_MAX_FILE_BYTES, DEFAULT_MAX_FILE_BYTES),
        max_pasted_chars=_positive_int(source, ENV_MAX_PASTED_CHARS, DEFAULT_MAX_PASTED_CHARS),
    )


def context_char_budget(env: Mapping[str, str] | None = None) -> int:
    """Characters of passage text a decision's debate may receive."""
    source = os.environ if env is None else env
    return _positive_int(source, ENV_CONTEXT_CHAR_BUDGET, DEFAULT_CONTEXT_CHAR_BUDGET)


def decision_budget_usd(env: Mapping[str, str] | None = None) -> float:
    """Model spend cap per decision (actual plus estimated), in USD."""
    source = os.environ if env is None else env
    raw = (source.get(ENV_DECISION_BUDGET_USD, "") or "").strip()
    if not raw:
        return DEFAULT_DECISION_BUDGET_USD
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if not math.isfinite(value) or value <= 0:
        _warn_once(
            ENV_DECISION_BUDGET_USD,
            raw,
            "%s=%r is not a positive amount; using %.2f",
            ENV_DECISION_BUDGET_USD,
            raw,
            DEFAULT_DECISION_BUDGET_USD,
        )
        return DEFAULT_DECISION_BUDGET_USD
    return value


def run_timeout_seconds(env: Mapping[str, str] | None = None) -> int:
    """Deadline for one decision run (debate plus synthesis), in seconds."""
    source = os.environ if env is None else env
    return _positive_int(source, ENV_RUN_TIMEOUT_SECONDS, DEFAULT_RUN_TIMEOUT_SECONDS)


def _positive_int(source: Mapping[str, str], name: str, default: int) -> int:
    raw = (source.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        _warn_once(name, raw, "%s=%r is not a positive integer; using %d", name, raw, default)
        return default
    return value


def _warn_once(name: str, value: str, message: str, *args: object) -> None:
    key = (name, value)
    if key in _warned:
        return
    _warned.add(key)
    logger.warning(message, *args)


__all__ = [
    "AGENTS_NOT_CONFIGURED_MESSAGE",
    "AgentOption",
    "AgentOptions",
    "DEFAULT_CONTEXT_CHAR_BUDGET",
    "DEFAULT_DECISION_BUDGET_USD",
    "DEFAULT_MAX_DOCUMENTS",
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MAX_PASTED_CHARS",
    "DEFAULT_RUN_TIMEOUT_SECONDS",
    "ENV_AGENTS",
    "ENV_CONTEXT_CHAR_BUDGET",
    "ENV_DECISION_BUDGET_USD",
    "ENV_MAX_DOCUMENTS",
    "ENV_MAX_FILE_BYTES",
    "ENV_MAX_PASTED_CHARS",
    "ENV_RUN_TIMEOUT_SECONDS",
    "WorkspaceLimits",
    "agent_options",
    "context_char_budget",
    "decision_budget_usd",
    "run_timeout_seconds",
    "workspace_limits",
]
