"""
OpenAI API agent with OpenRouter fallback support.

Supports web search tool for web-capable responses when URLs
or web-related keywords are detected in the prompt.
"""

import logging
import re

from aragora.agents.api_agents.base import APIAgent
from aragora.core_types import AgentRole
from aragora.agents.api_agents.common import get_primary_api_key
from aragora.agents.api_agents.openai_compatible import OpenAICompatibleMixin
from aragora.agents.registry import AgentRegistry

logger = logging.getLogger(__name__)

# Pre-compiled patterns that indicate web search would be helpful
# Compiled at module load time for performance (avoids recompilation on each call)
_WEB_SEARCH_PATTERNS = [
    re.compile(r"https?://", re.IGNORECASE),  # URLs
    re.compile(r"github\.com", re.IGNORECASE),  # GitHub repos
    re.compile(r"\brepo\b", re.IGNORECASE),  # Repository mentions
    re.compile(r"\bwebsite\b", re.IGNORECASE),  # Website mentions
    re.compile(r"\bweb\s*page\b", re.IGNORECASE),  # Web page mentions
    re.compile(r"\bonline\b", re.IGNORECASE),  # Online content
    re.compile(r"\blatest\s+(news|updates?|release|releases|version|versions)\b", re.IGNORECASE),
    re.compile(r"\bcurrent\s+(events|status|market|prices?|pricing)\b", re.IGNORECASE),
    re.compile(r"\brecent\s+(news|developments|changes|updates?|articles?)\b", re.IGNORECASE),
    re.compile(r"\bnews\b", re.IGNORECASE),  # News
    re.compile(r"\barticle\b", re.IGNORECASE),  # Articles
]


@AgentRegistry.register(
    "openai-api",
    default_model="gpt-5.3",
    default_name="openai-api",
    agent_type="API",
    env_vars="OPENAI_API_KEY",
    accepts_api_key=True,
)
class OpenAIAPIAgent(OpenAICompatibleMixin, APIAgent):
    """Agent that uses OpenAI API directly.

    Includes automatic fallback to OpenRouter when OpenAI quota is exceeded (429 error).
    The fallback uses the same GPT model via OpenRouter's API.

    Supports web search tool for web-capable responses when URLs or web-related
    keywords are detected in the prompt.

    Uses OpenAICompatibleMixin for standard OpenAI API implementation.
    """

    OPENROUTER_MODEL_MAP = {
        "gpt-5.3": "openai/gpt-5.3",
        "gpt-5.3-chat-latest": "openai/gpt-5.3-chat",
        "gpt-5.3-codex": "openai/gpt-5.3-codex",
        "gpt-4.1": "openai/gpt-4.1",
        "gpt-4.1-mini": "openai/gpt-4.1-mini",
        "gpt-4.1-nano": "openai/gpt-4.1-nano",
        "gpt-4o": "openai/gpt-4o",
        "gpt-4o-mini": "openai/gpt-4o-mini",
        "gpt-4-turbo": "openai/gpt-4-turbo",
        "gpt-4": "openai/gpt-4",
        "gpt-3.5-turbo": "openai/gpt-3.5-turbo",
        "gpt-4o-search-preview": "openai/gpt-4o",  # Search model fallback
        "o3": "openai/o3",
        "o3-mini": "openai/o3-mini",
    }
    DEFAULT_FALLBACK_MODEL = "openai/gpt-5.3"

    def __init__(
        self,
        name: str = "openai-api",
        model: str = "gpt-5.3",
        role: AgentRole = "proposer",
        timeout: int = 120,
        api_key: str | None = None,
        enable_fallback: bool | None = None,  # None = use config setting
    ) -> None:
        super().__init__(
            name=name,
            model=model,
            role=role,
            timeout=timeout,
            api_key=api_key
            or get_primary_api_key("OPENAI_API_KEY", allow_openrouter_fallback=True),
            base_url="https://api.openai.com/v1",
        )
        self.agent_type = "openai"
        # Use config setting if not explicitly provided
        if enable_fallback is None:
            from aragora.agents.fallback import get_default_fallback_enabled

            self.enable_fallback = get_default_fallback_enabled()
        else:
            self.enable_fallback = enable_fallback
        self._fallback_agent = None
        self.enable_web_search = True  # Enable web search tool by default
        self._current_prompt = ""  # Track current prompt for web search detection

    def _needs_web_search(self, prompt: str) -> bool:
        """Detect if the prompt would benefit from web search.

        Returns True if the prompt contains URLs, GitHub references,
        or keywords indicating need for current/web information.
        """
        if not self.enable_web_search:
            return False

        # Use pre-compiled patterns for performance
        for pattern in _WEB_SEARCH_PATTERNS:
            if pattern.search(prompt):
                return True
        return False

    def _build_messages(self, full_prompt: str) -> list[dict]:
        """Build messages and track prompt for web search detection."""
        # Store prompt for _build_extra_payload to use
        self._current_prompt = full_prompt
        return super()._build_messages(full_prompt)

    def _build_extra_payload(self) -> dict | None:
        """Add web search tool if prompt indicates web content is needed."""
        if self._needs_web_search(self._current_prompt):
            logger.info("[%s] Enabling web search tool for web content", self.name)
            return {
                "tools": [
                    {
                        "type": "web_search",
                        "web_search": {},
                    }
                ]
            }
        return None


__all__ = ["OpenAIAPIAgent"]
