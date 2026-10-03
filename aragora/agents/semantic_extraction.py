"""Agent-backed LLM-first semantic extraction helpers."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from aragora.agents import base as agent_base
from aragora.utils.json_helpers import extract_json_from_text

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ExtractionProvider:
    agent_type: agent_base.AgentType
    model: str | None = None
    role: str = "critic"
    name: str = "semantic-extractor"
    env_vars: tuple[str, ...] = ()
    disable_web_search: bool = False

    def is_available(self) -> bool:
        return not self.env_vars or any(os.environ.get(env_var) for env_var in self.env_vars)


@dataclass(frozen=True, slots=True)
class ExtractionResult(Generic[T]):
    value: T | None
    source: str
    provider: ExtractionProvider | None = None
    raw_response: str | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.value is not None


def _parse_json_object(raw_response: str) -> dict[str, Any] | None:
    text = extract_json_from_text(str(raw_response or "").strip()).strip()
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _format_provider_error(
    provider: ExtractionProvider,
    category: str,
    detail: str | None = None,
) -> str:
    base = f"{provider.agent_type}:{category}"
    return f"{base}:{detail}" if detail else base


async def extract_json_object_llm_first(
    prompt: str,
    *,
    providers: Sequence[ExtractionProvider],
    normalizer: Callable[[dict[str, Any]], T | None],
    timeout: float | None = None,
    logger: logging.Logger | None = None,
    context: str = "semantic extraction",
) -> ExtractionResult[T]:
    text = str(prompt or "").strip()
    if not text:
        return ExtractionResult(value=None, source="none", error="empty_prompt")

    log = logger or logging.getLogger(__name__)
    available_providers = [provider for provider in providers if provider.is_available()]
    if not available_providers:
        return ExtractionResult(value=None, source="none", error="no_available_providers")

    errors: list[str] = []
    last_provider: ExtractionProvider | None = None
    last_raw_response: str | None = None

    for provider in available_providers:
        last_provider = provider
        try:
            kwargs: dict[str, Any] = {
                "name": provider.name,
                "role": provider.role,
            }
            if provider.model is not None:
                kwargs["model"] = provider.model
            if timeout is not None:
                kwargs["timeout"] = timeout
            agent = agent_base.create_agent(provider.agent_type, **kwargs)
            if provider.disable_web_search and hasattr(agent, "enable_web_search"):
                setattr(agent, "enable_web_search", False)
            raw_response = await agent.generate(text)
        except Exception as exc:
            errors.append(_format_provider_error(provider, "generate_failed", type(exc).__name__))
            log.debug(
                "%s generate failed via %s (%s)",
                context,
                provider.agent_type,
                type(exc).__name__,
            )
            continue

        raw_text = str(raw_response or "").strip()
        last_raw_response = raw_text or None
        parsed = _parse_json_object(raw_text)
        if parsed is None:
            errors.append(_format_provider_error(provider, "invalid_json"))
            log.debug("%s returned non-JSON object via %s", context, provider.agent_type)
            continue

        try:
            value = normalizer(parsed)
        except Exception as exc:
            errors.append(
                _format_provider_error(provider, "normalization_failed", type(exc).__name__)
            )
            log.debug(
                "%s normalization failed via %s (%s)",
                context,
                provider.agent_type,
                type(exc).__name__,
            )
            continue

        if value is None:
            errors.append(_format_provider_error(provider, "normalization_failed"))
            log.debug("%s normalization rejected payload via %s", context, provider.agent_type)
            continue

        return ExtractionResult(
            value=value,
            source=provider.agent_type,
            provider=provider,
            raw_response=raw_text or None,
            error=None,
        )

    return ExtractionResult(
        value=None,
        source=last_provider.agent_type if last_provider else "none",
        provider=last_provider,
        raw_response=last_raw_response,
        error="; ".join(errors[-3:]) if errors else "exhausted_without_result",
    )
