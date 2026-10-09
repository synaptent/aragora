"""
LangChain Tools for Aragora.

Provides LangChain-compatible Tool implementations for:
- Running debates with multiple AI agents
- Querying the Knowledge Mound
- Getting decisions with audit trails

These tools can be used with LangChain agents, chains, and workflows.

Usage:
    from aragora.integrations.langchain import AragoraDebateTool

    tool = AragoraDebateTool(
        aragora_url="http://localhost:8080",
        api_token="your-token",
    )

    # Synchronous
    result = tool.run("Should we adopt microservices?")

    # Asynchronous
    result = await tool.arun("Should we adopt microservices?")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any


from aragora.utils.async_utils import run_async

logger = logging.getLogger(__name__)


# Stub classes defined at module level for consistent typing
class _BaseToolStub:
    """Stub BaseTool when LangChain not installed."""

    name: str = ""
    description: str = ""

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class _BaseModelStub:
    """Stub BaseModel when pydantic not available via LangChain."""

    pass


def _FieldStub(*args: Any, **kwargs: Any) -> Any:
    """Stub Field when pydantic not available via LangChain."""
    return kwargs.get("default", None)


# LangChain imports with fallback.
#
# ``BaseTool`` and ``BaseModel`` are used as BASE CLASSES and in annotations
# below. A module-level name assigned in more than one branch is a
# *variable* to mypy, not a type alias, so every such use reported
# "Variable ... is not valid as a type" / "Invalid base class" (8 errors,
# none of them baselined). Binding each name exactly once under
# ``TYPE_CHECKING`` -- to the local stub, whose shape the subclasses below
# are written against -- makes them real type aliases for static analysis
# while leaving the runtime binding (the ``else`` branch) untouched.
if TYPE_CHECKING:
    BaseTool = _BaseToolStub
    BaseModel = _BaseModelStub
    Field = _FieldStub
    AsyncCallbackManagerForToolRun = Any
    CallbackManagerForToolRun = Any
    LANGCHAIN_AVAILABLE = True
else:
    try:
        try:
            from langchain_core.tools import BaseTool as _LCBaseTool
        except ImportError:
            from langchain.tools import BaseTool as _LCBaseTool
        try:
            from langchain_core.callbacks.manager import (
                AsyncCallbackManagerForToolRun as _LCAsyncCBManager,
                CallbackManagerForToolRun as _LCCBManager,
            )
        except ImportError:
            from langchain.callbacks.manager import (
                AsyncCallbackManagerForToolRun as _LCAsyncCBManager,
                CallbackManagerForToolRun as _LCCBManager,
            )
        from pydantic import BaseModel as _PydanticBaseModel, Field as _PydanticField

        BaseTool = _LCBaseTool
        BaseModel = _PydanticBaseModel
        Field = _PydanticField
        AsyncCallbackManagerForToolRun = _LCAsyncCBManager
        CallbackManagerForToolRun = _LCCBManager
        LANGCHAIN_AVAILABLE = True
    except ImportError:
        LANGCHAIN_AVAILABLE = False

        # Stubs replace LangChain/pydantic types when the optional dependency
        # is not installed. The type mismatches are unavoidable since stubs
        # are not subclasses of the real library types.
        BaseTool = _BaseToolStub
        BaseModel = _BaseModelStub
        Field = _FieldStub
        AsyncCallbackManagerForToolRun = None
        CallbackManagerForToolRun = None


def get_langchain_version() -> str | None:
    """Get the LangChain version if available."""
    try:
        import langchain

        return getattr(langchain, "__version__", "unknown")
    except ImportError:
        return None


class AragoraToolInput(BaseModel):
    """Input schema for Aragora debate tool (compatible API)."""

    question: str = Field(description="The question or task to debate")
    agents: list[str] | None = Field(
        default=None,
        description="List of agents to participate",
    )
    rounds: int = Field(
        default=3,
        description="Number of debate rounds",
    )
    consensus_threshold: float = Field(
        default=0.8,
        description="Threshold for consensus (0.0-1.0)",
    )
    include_evidence: bool = Field(
        default=True,
        description="Whether to include evidence in response",
    )


class AragoraDebateInput(BaseModel):
    """Input schema for Aragora debate tool."""

    task: str = Field(description="The question or task to debate")
    agents: list[str] | None = Field(
        default=None,
        description="List of agents to participate (e.g., ['claude', 'gpt-4']). If not specified, uses defaults.",
    )
    max_rounds: int | None = Field(
        default=None,
        description="Maximum debate rounds (default: 5)",
    )


class AragoraDebateTool(BaseTool):
    """
    LangChain Tool for running Aragora debates.

    This tool runs a multi-agent debate on a given question or task
    and returns the consensus answer with confidence score.

    Example:
        tool = AragoraDebateTool(aragora_url="http://localhost:8080")
        result = tool.run("What's the best database for our use case?")
        # Returns: "Based on debate with 85% consensus: PostgreSQL is recommended..."
    """

    name: str = "aragora_debate"
    description: str = (
        "Run a multi-agent AI debate to get a well-reasoned answer. "
        "Use this when you need multiple perspectives on a complex question. "
        "The debate reaches consensus through structured argumentation."
    )
    args_schema: type[BaseModel] = AragoraDebateInput

    # Configuration
    aragora_url: str = "http://localhost:8080"
    api_token: str | None = None
    default_agents: list[str] = ["claude", "gpt-4", "gemini"]
    default_max_rounds: int = 5
    timeout_seconds: float = 120.0

    def __init__(
        self,
        aragora_url: str = "http://localhost:8080",
        api_token: str | None = None,
        **kwargs: Any,
    ):
        """
        Initialize the Aragora debate tool.

        Args:
            aragora_url: Base URL for Aragora API
            api_token: Optional API token for authentication
            **kwargs: Additional BaseTool arguments
        """
        super().__init__(**kwargs)
        self.aragora_url = aragora_url
        self.api_token = api_token

    def _run(
        self,
        task: str,
        agents: list[str] | None = None,
        max_rounds: int | None = None,
        run_manager: CallbackManagerForToolRun | None = None,  # type: ignore[valid-type]
    ) -> str:
        """Run the debate synchronously."""

        return run_async(self._arun(task, agents, max_rounds, None))

    async def _arun(
        self,
        task: str,
        agents: list[str] | None = None,
        max_rounds: int | None = None,
        run_manager: AsyncCallbackManagerForToolRun | None = None,  # type: ignore[valid-type]
    ) -> str:
        """Run the debate asynchronously."""
        import httpx

        agents = agents or self.default_agents
        max_rounds = max_rounds or self.default_max_rounds

        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        payload = {
            "task": task,
            "agents": agents,
            "max_rounds": max_rounds,
        }

        try:
            from aragora.security.safe_http import async_safe_post

            response = await async_safe_post(
                f"{self.aragora_url}/api/debate/start",
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            result = response.json()

            # Format result for LangChain
            if result.get("consensus_reached"):
                return (
                    f"Debate consensus ({result.get('confidence', 0):.0%} confidence): "
                    f"{result.get('final_answer', 'No answer')}"
                )
            else:
                return f"No consensus reached after {result.get('rounds', max_rounds)} rounds."

        except (ConnectionError, TimeoutError, OSError, httpx.HTTPError) as e:
            logger.error("[AragoraDebateTool] connection error: %s: %s", type(e).__name__, e)
            return f"Error running debate (connection): {e}"
        except (RuntimeError, ValueError, TypeError) as e:
            logger.error("[AragoraDebateTool] error: %s: %s", type(e).__name__, e)
            return f"Error running debate: {e}"


class AragoraKnowledgeInput(BaseModel):
    """Input schema for Aragora knowledge tool."""

    query: str = Field(description="Search query for the knowledge base")
    limit: int | None = Field(
        default=5,
        description="Maximum number of results to return",
    )


class AragoraKnowledgeTool(BaseTool):
    """
    LangChain Tool for querying Aragora Knowledge Mound.

    This tool searches the organization's knowledge base for relevant
    information, documents, and past debate conclusions.

    Example:
        tool = AragoraKnowledgeTool(aragora_url="http://localhost:8080")
        result = tool.run("previous decisions about database migrations")
    """

    name: str = "aragora_knowledge"
    description: str = (
        "Search the organization's knowledge base for relevant information. "
        "Use this to find documents, past decisions, and institutional knowledge. "
        "Returns the most relevant results with confidence scores."
    )
    args_schema: type[BaseModel] = AragoraKnowledgeInput

    # Configuration
    aragora_url: str = "http://localhost:8080"
    api_token: str | None = None
    timeout_seconds: float = 30.0

    def __init__(
        self,
        aragora_url: str = "http://localhost:8080",
        api_token: str | None = None,
        **kwargs: Any,
    ):
        """Initialize the knowledge tool."""
        super().__init__(**kwargs)
        self.aragora_url = aragora_url
        self.api_token = api_token

    def _run(
        self,
        query: str,
        limit: int | None = 5,
        run_manager: CallbackManagerForToolRun | None = None,  # type: ignore[valid-type]
    ) -> str:
        """Run the query synchronously."""

        return run_async(self._arun(query, limit, None))

    async def _arun(
        self,
        query: str,
        limit: int | None = 5,
        run_manager: AsyncCallbackManagerForToolRun | None = None,  # type: ignore[valid-type]
    ) -> str:
        """Run the query asynchronously."""
        import httpx

        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(
                    f"{self.aragora_url}/api/v1/knowledge/search",
                    params={"q": query, "limit": limit},
                    headers=headers,
                )
                response.raise_for_status()
                result = response.json()

            # Format results for LangChain
            items = result.get("items", [])
            if not items:
                return f"No knowledge found for: {query}"

            formatted = []
            for i, item in enumerate(items, 1):
                confidence = item.get("confidence", 0)
                title = item.get("title", "Untitled")
                content = item.get("content", "")[:200]
                formatted.append(f"{i}. [{confidence:.0%}] {title}: {content}...")

            return "\n".join(formatted)

        except (ConnectionError, TimeoutError, OSError, httpx.HTTPError) as e:
            logger.error("[AragoraKnowledgeTool] connection error: %s: %s", type(e).__name__, e)
            return f"Error querying knowledge (connection): {e}"
        except (RuntimeError, ValueError, TypeError) as e:
            logger.error("[AragoraKnowledgeTool] error: %s: %s", type(e).__name__, e)
            return f"Error querying knowledge: {e}"


class AragoraDecisionInput(BaseModel):
    """Input schema for Aragora decision tool."""

    question: str = Field(description="The decision question")
    options: list[str] | None = Field(
        default=None,
        description="List of options to choose from (optional)",
    )


class AragoraDecisionTool(BaseTool):
    """
    LangChain Tool for making decisions with Aragora.

    This tool uses multi-agent debate to make a decision and generates
    an auditable decision receipt.

    Example:
        tool = AragoraDecisionTool(aragora_url="http://localhost:8080")
        result = tool.run("Should we approve this budget increase?")
    """

    name: str = "aragora_decision"
    description: str = (
        "Make a decision using multi-agent deliberation. "
        "Use this for important decisions that need audit trails. "
        "Returns a decision with rationale and confidence."
    )
    args_schema: type[BaseModel] = AragoraDecisionInput

    # Configuration
    aragora_url: str = "http://localhost:8080"
    api_token: str | None = None
    timeout_seconds: float = 120.0

    def __init__(
        self,
        aragora_url: str = "http://localhost:8080",
        api_token: str | None = None,
        **kwargs: Any,
    ):
        """Initialize the decision tool."""
        super().__init__(**kwargs)
        self.aragora_url = aragora_url
        self.api_token = api_token

    def _run(
        self,
        question: str,
        options: list[str] | None = None,
        run_manager: CallbackManagerForToolRun | None = None,  # type: ignore[valid-type]
    ) -> str:
        """Run the decision synchronously."""

        return run_async(self._arun(question, options, None))

    async def _arun(
        self,
        question: str,
        options: list[str] | None = None,
        run_manager: AsyncCallbackManagerForToolRun | None = None,  # type: ignore[valid-type]
    ) -> str:
        """Run the decision asynchronously."""
        import httpx

        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        payload: dict[str, Any] = {"question": question}
        if options:
            payload["options"] = options

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.aragora_url}/api/v1/decisions/make",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                result = response.json()

            # Format decision for LangChain
            decision = result.get("decision", "Unknown")
            confidence = result.get("confidence", 0)
            rationale = result.get("rationale", "No rationale provided")
            receipt_id = result.get("receipt_id", "N/A")

            return (
                f"Decision: {decision} ({confidence:.0%} confidence)\n"
                f"Rationale: {rationale}\n"
                f"Receipt ID: {receipt_id}"
            )

        except (ConnectionError, TimeoutError, OSError, httpx.HTTPError) as e:
            logger.error("[AragoraDecisionTool] connection error: %s: %s", type(e).__name__, e)
            return f"Error making decision (connection): {e}"
        except (RuntimeError, ValueError, TypeError) as e:
            logger.error("[AragoraDecisionTool] error: %s: %s", type(e).__name__, e)
            return f"Error making decision: {e}"


# Convenience function to get all tools
def get_aragora_tools(
    aragora_url: str = "http://localhost:8080",
    api_token: str | None = None,
) -> list[BaseTool]:
    """
    Get all Aragora LangChain tools.

    Args:
        aragora_url: Base URL for Aragora API
        api_token: Optional API token

    Returns:
        List of configured Aragora tools
    """
    return [
        AragoraDebateTool(aragora_url=aragora_url, api_token=api_token),
        AragoraKnowledgeTool(aragora_url=aragora_url, api_token=api_token),
        AragoraDecisionTool(aragora_url=aragora_url, api_token=api_token),
    ]
