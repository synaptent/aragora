"""Reference agent implementations for common LLM providers.

Install the optional dependency for your provider::

    pip install aragora-debate[anthropic]   # Claude
    pip install aragora-debate[openai]      # GPT-4 / o-series
    pip install aragora-debate[all]         # Both

Usage::

    from aragora_debate.agents import ClaudeAgent, OpenAIAgent

    agents = [
        ClaudeAgent("analyst", model="claude-sonnet-4-5-20250929"),
        OpenAIAgent("challenger", model="gpt-4o"),
    ]
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from functools import partial
from typing import Any, ParamSpec, TypeVar, cast

from aragora_debate._resilience import CircuitBreaker, retry, with_timeout
from aragora_debate.types import Agent, Critique, Message, Vote

logger = logging.getLogger(__name__)
_P = ParamSpec("_P")
_T = TypeVar("_T")


async def _call_sdk(
    breaker: CircuitBreaker, operation: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs
) -> _T:
    """Retry timed SDK attempts; every failed attempt counts toward the breaker."""
    timed = with_timeout()

    @retry()
    async def attempt() -> _T:
        async def invoke() -> _T:
            return await timed(partial(operation, *args, **kwargs))

        return await breaker.call(invoke)

    return await attempt()


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def _format_context(context: list[Message] | None) -> str:
    """Format debate context into a readable conversation history."""
    if not context:
        return ""
    lines = []
    for m in context:
        lines.append(f"[{m.role} | {m.agent} | round {m.round}]\n{m.content}")
    return "\n\n".join(lines)


_CRITIQUE_SYSTEM = """\
You are a critical reviewer in a structured adversarial debate.
Analyze the proposal for weaknesses, missing evidence, logical gaps,
and unstated assumptions. Be specific and constructive.

Respond with a JSON object:
{
  "issues": ["issue1", "issue2"],
  "suggestions": ["suggestion1", "suggestion2"],
  "severity": 5.0,
  "reasoning": "overall assessment"
}
"""

_VOTE_SYSTEM = """\
You are a judge in a structured adversarial debate.
Review the proposals and vote for the strongest one.

Respond with a JSON object:
{
  "choice": "agent_name",
  "confidence": 0.85,
  "reasoning": "why this proposal is strongest"
}
"""


def _parse_json_from_text(text: str) -> dict[str, Any]:
    """Extract a JSON object from LLM output that may contain markdown fences."""
    # Try direct parse first
    try:
        return cast(dict[str, Any], json.loads(text))
    except json.JSONDecodeError:
        pass
    # Strip markdown code fences
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return cast(dict[str, Any], json.loads(match.group(1)))
        except json.JSONDecodeError:
            pass
    # Try to find any JSON object
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return cast(dict[str, Any], json.loads(match.group(0)))
        except json.JSONDecodeError:
            pass
    return {}


# ---------------------------------------------------------------------------
# Claude agent (Anthropic)
# ---------------------------------------------------------------------------


class ClaudeAgent(Agent):
    """Debate agent powered by Anthropic's Claude models.

    Requires ``anthropic`` package and ``ANTHROPIC_API_KEY`` env var.

    Args:
        name: Agent display name (e.g. ``"analyst"``).
        model: Anthropic model ID.  Defaults to ``claude-sonnet-4-5-20250929``.
        api_key: Anthropic API key.  Falls back to ``ANTHROPIC_API_KEY`` env var.
        max_tokens: Maximum tokens per response.
        temperature: Sampling temperature (0-1).
    """

    def __init__(
        self,
        name: str,
        model: str = "claude-sonnet-4-5-20250929",
        *,
        api_key: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, model=model, **kwargs)
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "anthropic package required: pip install aragora-debate[anthropic]"
            ) from exc
        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
            max_retries=0,
        )
        self._breaker = CircuitBreaker()
        self._max_tokens = max_tokens
        self._temperature = temperature

    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        history = _format_context(context)
        full_prompt = prompt
        if history:
            full_prompt = f"## Debate history\n\n{history}\n\n## Your task\n\n{prompt}"
        system = (
            self.system_prompt
            or "You are a thoughtful debater. Make a clear, well-reasoned proposal."
        )
        if self.stance != "neutral":
            system += f"\n\nYou are arguing from a {self.stance} stance."
        msg = await _call_sdk(
            self._breaker,
            self._client.messages.create,
            model=self.model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system=system,
            messages=[{"role": "user", "content": full_prompt}],
        )
        return cast(str, msg.content[0].text)

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        history = _format_context(context)
        prompt = f"## Task\n{task}\n\n## Proposal by {target_agent or 'another agent'}\n{proposal}"
        if history:
            prompt = f"## Debate history\n{history}\n\n{prompt}"
        prompt += "\n\nProvide your critique as JSON."
        msg = await _call_sdk(
            self._breaker,
            self._client.messages.create,
            model=self.model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system=_CRITIQUE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        data = _parse_json_from_text(msg.content[0].text)
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal,
            issues=data.get("issues", ["(could not parse critique)"]),
            suggestions=data.get("suggestions", []),
            severity=float(data.get("severity", 5.0)),
            reasoning=data.get("reasoning", msg.content[0].text),
        )

    async def vote(
        self,
        proposals: dict[str, str],
        task: str,
    ) -> Vote:
        lines = [f"## Task\n{task}\n\n## Proposals\n"]
        for agent_name, content in proposals.items():
            lines.append(f"### {agent_name}\n{content}\n")
        lines.append("Vote for the strongest proposal as JSON.")
        msg = await _call_sdk(
            self._breaker,
            self._client.messages.create,
            model=self.model,
            max_tokens=512,
            temperature=0.3,
            system=_VOTE_SYSTEM,
            messages=[{"role": "user", "content": "\n".join(lines)}],
        )
        data = _parse_json_from_text(msg.content[0].text)
        choice = data.get("choice", "")
        # Validate choice is a real agent
        if choice not in proposals:
            # Fuzzy match
            for name in proposals:
                if name.lower() in choice.lower() or choice.lower() in name.lower():
                    choice = name
                    break
            else:
                choice = list(proposals.keys())[0]
        return Vote(
            agent=self.name,
            choice=choice,
            confidence=float(data.get("confidence", 0.5)),
            reasoning=data.get("reasoning", msg.content[0].text),
        )


# ---------------------------------------------------------------------------
# OpenAI agent (GPT-4, o-series)
# ---------------------------------------------------------------------------


class OpenAIAgent(Agent):
    """Debate agent powered by OpenAI models.

    Requires ``openai`` package and ``OPENAI_API_KEY`` env var.

    Args:
        name: Agent display name (e.g. ``"challenger"``).
        model: OpenAI model ID.  Defaults to ``gpt-4o``.
        api_key: OpenAI API key.  Falls back to ``OPENAI_API_KEY`` env var.
        max_tokens: Maximum tokens per response.
        temperature: Sampling temperature (0-2).
    """

    def __init__(
        self,
        name: str,
        model: str = "gpt-4o",
        *,
        api_key: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, model=model, **kwargs)
        try:
            import openai
        except ImportError as exc:
            raise ImportError(
                "openai package required: pip install aragora-debate[openai]"
            ) from exc
        self._client = openai.OpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            max_retries=0,
        )
        self._breaker = CircuitBreaker()
        self._max_tokens = max_tokens
        self._temperature = temperature

    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        history = _format_context(context)
        full_prompt = prompt
        if history:
            full_prompt = f"## Debate history\n\n{history}\n\n## Your task\n\n{prompt}"
        system = (
            self.system_prompt
            or "You are a thoughtful debater. Make a clear, well-reasoned proposal."
        )
        if self.stance != "neutral":
            system += f"\n\nYou are arguing from a {self.stance} stance."
        resp = await _call_sdk(
            self._breaker,
            self._client.chat.completions.create,
            model=self.model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": full_prompt},
            ],
        )
        return resp.choices[0].message.content or ""

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        history = _format_context(context)
        prompt = f"## Task\n{task}\n\n## Proposal by {target_agent or 'another agent'}\n{proposal}"
        if history:
            prompt = f"## Debate history\n{history}\n\n{prompt}"
        prompt += "\n\nProvide your critique as JSON."
        resp = await _call_sdk(
            self._breaker,
            self._client.chat.completions.create,
            model=self.model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[
                {"role": "system", "content": _CRITIQUE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
        text = resp.choices[0].message.content or ""
        data = _parse_json_from_text(text)
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal,
            issues=data.get("issues", ["(could not parse critique)"]),
            suggestions=data.get("suggestions", []),
            severity=float(data.get("severity", 5.0)),
            reasoning=data.get("reasoning", text),
        )

    async def vote(
        self,
        proposals: dict[str, str],
        task: str,
    ) -> Vote:
        lines = [f"## Task\n{task}\n\n## Proposals\n"]
        for agent_name, content in proposals.items():
            lines.append(f"### {agent_name}\n{content}\n")
        lines.append("Vote for the strongest proposal as JSON.")
        resp = await _call_sdk(
            self._breaker,
            self._client.chat.completions.create,
            model=self.model,
            max_tokens=512,
            temperature=0.3,
            messages=[
                {"role": "system", "content": _VOTE_SYSTEM},
                {"role": "user", "content": "\n".join(lines)},
            ],
        )
        text = resp.choices[0].message.content or ""
        data = _parse_json_from_text(text)
        choice = data.get("choice", "")
        if choice not in proposals:
            for name in proposals:
                if name.lower() in choice.lower() or choice.lower() in name.lower():
                    choice = name
                    break
            else:
                choice = list(proposals.keys())[0]
        return Vote(
            agent=self.name,
            choice=choice,
            confidence=float(data.get("confidence", 0.5)),
            reasoning=data.get("reasoning", text),
        )


# ---------------------------------------------------------------------------
# Mistral agent
# ---------------------------------------------------------------------------


class MistralAgent(Agent):
    """Debate agent powered by Mistral AI models.

    Requires ``mistralai`` package and ``MISTRAL_API_KEY`` env var.

    Args:
        name: Agent display name.
        model: Mistral model ID.  Defaults to ``mistral-large-latest``.
        api_key: Mistral API key.  Falls back to ``MISTRAL_API_KEY`` env var.
        max_tokens: Maximum tokens per response.
        temperature: Sampling temperature (0-1).
    """

    def __init__(
        self,
        name: str,
        model: str = "mistral-large-latest",
        *,
        api_key: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, model=model, **kwargs)
        try:
            from mistralai import Mistral
        except ImportError as exc:
            raise ImportError(
                "mistralai package required: pip install aragora-debate[mistral]"
            ) from exc
        self._client = Mistral(
            api_key=api_key or os.environ.get("MISTRAL_API_KEY", ""),
        )
        self._breaker = CircuitBreaker()
        self._max_tokens = max_tokens
        self._temperature = temperature

    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        history = _format_context(context)
        full_prompt = prompt
        if history:
            full_prompt = f"## Debate history\n\n{history}\n\n## Your task\n\n{prompt}"
        system = (
            self.system_prompt
            or "You are a thoughtful debater. Make a clear, well-reasoned proposal."
        )
        if self.stance != "neutral":
            system += f"\n\nYou are arguing from a {self.stance} stance."
        resp = await _call_sdk(
            self._breaker,
            self._client.chat.complete,
            model=self.model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": full_prompt},
            ],
        )
        return resp.choices[0].message.content or ""

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        history = _format_context(context)
        prompt = f"## Task\n{task}\n\n## Proposal by {target_agent or 'another agent'}\n{proposal}"
        if history:
            prompt = f"## Debate history\n{history}\n\n{prompt}"
        prompt += "\n\nProvide your critique as JSON."
        resp = await _call_sdk(
            self._breaker,
            self._client.chat.complete,
            model=self.model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[
                {"role": "system", "content": _CRITIQUE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
        text = resp.choices[0].message.content or ""
        data = _parse_json_from_text(text)
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal,
            issues=data.get("issues", ["(could not parse critique)"]),
            suggestions=data.get("suggestions", []),
            severity=float(data.get("severity", 5.0)),
            reasoning=data.get("reasoning", text),
        )

    async def vote(
        self,
        proposals: dict[str, str],
        task: str,
    ) -> Vote:
        lines = [f"## Task\n{task}\n\n## Proposals\n"]
        for agent_name, content in proposals.items():
            lines.append(f"### {agent_name}\n{content}\n")
        lines.append("Vote for the strongest proposal as JSON.")
        resp = await _call_sdk(
            self._breaker,
            self._client.chat.complete,
            model=self.model,
            max_tokens=512,
            temperature=0.3,
            messages=[
                {"role": "system", "content": _VOTE_SYSTEM},
                {"role": "user", "content": "\n".join(lines)},
            ],
        )
        text = resp.choices[0].message.content or ""
        data = _parse_json_from_text(text)
        choice = data.get("choice", "")
        if choice not in proposals:
            for name in proposals:
                if name.lower() in choice.lower() or choice.lower() in name.lower():
                    choice = name
                    break
            else:
                choice = list(proposals.keys())[0]
        return Vote(
            agent=self.name,
            choice=choice,
            confidence=float(data.get("confidence", 0.5)),
            reasoning=data.get("reasoning", text),
        )


# ---------------------------------------------------------------------------
# Gemini agent (Google)
# ---------------------------------------------------------------------------


class GeminiAgent(Agent):
    """Debate agent powered by Google's Gemini models.

    Requires ``google-genai`` package and ``GEMINI_API_KEY`` env var.

    Args:
        name: Agent display name.
        model: Gemini model ID.  Defaults to ``gemini-3.1-pro-preview``.
        api_key: Gemini API key.  Falls back to ``GEMINI_API_KEY`` env var.
        max_tokens: Maximum tokens per response.
        temperature: Sampling temperature (0-2).
    """

    def __init__(
        self,
        name: str,
        model: str = "gemini-3.1-pro-preview",
        *,
        api_key: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, model=model, **kwargs)
        try:
            from google import genai
        except ImportError as exc:
            raise ImportError(
                "google-genai package required: pip install aragora-debate[gemini]"
            ) from exc
        key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._client = genai.Client(api_key=key)
        self._breaker = CircuitBreaker()
        self._max_tokens = max_tokens
        self._temperature = temperature

    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        from google.genai import types

        history = _format_context(context)
        full_prompt = prompt
        if history:
            full_prompt = f"## Debate history\n\n{history}\n\n## Your task\n\n{prompt}"
        system = (
            self.system_prompt
            or "You are a thoughtful debater. Make a clear, well-reasoned proposal."
        )
        if self.stance != "neutral":
            system += f"\n\nYou are arguing from a {self.stance} stance."
        resp = await _call_sdk(
            self._breaker,
            self._client.models.generate_content,
            model=self.model,
            contents=full_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=self._max_tokens,
                temperature=self._temperature,
            ),
        )
        return resp.text or ""

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        from google.genai import types

        history = _format_context(context)
        prompt = f"## Task\n{task}\n\n## Proposal by {target_agent or 'another agent'}\n{proposal}"
        if history:
            prompt = f"## Debate history\n{history}\n\n{prompt}"
        prompt += "\n\nProvide your critique as JSON."
        resp = await _call_sdk(
            self._breaker,
            self._client.models.generate_content,
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_CRITIQUE_SYSTEM,
                max_output_tokens=self._max_tokens,
                temperature=self._temperature,
            ),
        )
        text = resp.text or ""
        data = _parse_json_from_text(text)
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal,
            issues=data.get("issues", ["(could not parse critique)"]),
            suggestions=data.get("suggestions", []),
            severity=float(data.get("severity", 5.0)),
            reasoning=data.get("reasoning", text),
        )

    async def vote(
        self,
        proposals: dict[str, str],
        task: str,
    ) -> Vote:
        from google.genai import types

        lines = [f"## Task\n{task}\n\n## Proposals\n"]
        for agent_name, content in proposals.items():
            lines.append(f"### {agent_name}\n{content}\n")
        lines.append("Vote for the strongest proposal as JSON.")
        resp = await _call_sdk(
            self._breaker,
            self._client.models.generate_content,
            model=self.model,
            contents="\n".join(lines),
            config=types.GenerateContentConfig(
                system_instruction=_VOTE_SYSTEM,
                max_output_tokens=512,
                temperature=0.3,
            ),
        )
        text = resp.text or ""
        data = _parse_json_from_text(text)
        choice = data.get("choice", "")
        if choice not in proposals:
            for name in proposals:
                if name.lower() in choice.lower() or choice.lower() in name.lower():
                    choice = name
                    break
            else:
                choice = list(proposals.keys())[0]
        return Vote(
            agent=self.name,
            choice=choice,
            confidence=float(data.get("confidence", 0.5)),
            reasoning=data.get("reasoning", text),
        )
