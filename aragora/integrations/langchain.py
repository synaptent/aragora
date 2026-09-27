"""
LangChain integration for Aragora.

Provides LangChain-compatible tools and components for multi-agent decision making:
- AragoraTool: LangChain Tool for running debates
- AragoraRetriever: LangChain Retriever for knowledge queries
- AragoraCallbackHandler: Callback handler for debate events
- AragoraChain: Custom chain for debate workflows

Usage with LangChain:
    from aragora.integrations.langchain import AragoraTool, AragoraRetriever

    # As a tool
    tool = AragoraTool(api_base="https://api.aragora.ai", api_key="your-key")
    result = tool.run("Should we use microservices or monolith?")

    # As a retriever
    retriever = AragoraRetriever(api_base="https://api.aragora.ai", api_key="your-key")
    docs = retriever.get_relevant_documents("database architecture patterns")
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import field
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)

from aragora.config.settings import get_settings

_LANGCHAIN_DEFAULTS = get_settings()
_DEFAULT_LC_AGENTS = _LANGCHAIN_DEFAULTS.agents.default_agent_list
_DEFAULT_LC_ROUNDS = _LANGCHAIN_DEFAULTS.debate.default_rounds

# =============================================================================
# LangChain Compatibility Layer
# =============================================================================
# These classes provide a compatibility layer that works whether or not
# LangChain is installed. If LangChain is available, they inherit from
# the actual LangChain base classes.

from langchain_core.tools import BaseTool
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks.manager import (
    CallbackManagerForToolRun,
    AsyncCallbackManagerForToolRun,
    CallbackManagerForRetrieverRun,
    AsyncCallbackManagerForRetrieverRun,
)
from pydantic import BaseModel, Field

LANGCHAIN_AVAILABLE = True  # Kept for backwards compatibility

# =============================================================================
# Aragora Tool Input Schema
# =============================================================================


class AragoraToolInput(BaseModel):
    """Input schema for Aragora tool."""

    question: str = Field(description="The question or topic for the multi-agent debate")
    agents: list[str] | None = Field(
        default=None,
        description="List of agent types to use (e.g., ['claude', 'gpt', 'gemini'])",
    )
    rounds: int | None = Field(default=_DEFAULT_LC_ROUNDS, description="Number of debate rounds")
    consensus_threshold: float | None = Field(
        default=0.8, description="Confidence threshold for consensus (0-1)"
    )
    include_evidence: bool | None = Field(
        default=True, description="Whether to search for and include evidence"
    )


# =============================================================================
# Aragora Tool
# =============================================================================


class AragoraTool(BaseTool):
    """
    LangChain Tool for running Aragora multi-agent debates.

    This tool allows LangChain agents to leverage Aragora's multi-agent
    decision-making capabilities for complex reasoning tasks.

    Example:
        tool = AragoraTool(
            api_base="https://api.aragora.ai",
            api_key="your-key"
        )
        result = tool.run("What database should we use for high-traffic analytics?")
    """

    name: str = "aragora_debate"
    description: str = (
        "Run a multi-agent debate to get a well-reasoned answer to complex questions. "
        "Use this tool when you need multiple AI perspectives to analyze a problem, "
        "evaluate trade-offs, or make important decisions. The tool returns a "
        "synthesized answer with confidence level and supporting reasoning."
    )

    # Configuration
    api_base: str = "https://api.aragora.ai"
    api_key: str = ""
    default_agents: list[str] = field(default_factory=lambda: list(_DEFAULT_LC_AGENTS))
    default_rounds: int = _DEFAULT_LC_ROUNDS
    timeout_seconds: float = 120.0

    # Internal state
    _session: Any = None

    def __init__(
        self,
        api_base: str = "https://api.aragora.ai",
        api_key: str = "",
        default_agents: list[str] | None = None,
        default_rounds: int = _DEFAULT_LC_ROUNDS,
        timeout_seconds: float = 120.0,
        **kwargs,
    ):
        """Initialize the Aragora tool.

        Args:
            api_base: Base URL for Aragora API
            api_key: API key for authentication
            default_agents: Default list of agents to use
            default_rounds: Default number of debate rounds
            timeout_seconds: Request timeout in seconds
        """
        super().__init__(**kwargs)
        self.api_base = api_base
        self.api_key = api_key
        self.default_agents = default_agents or list(_DEFAULT_LC_AGENTS)
        self.default_rounds = default_rounds
        self.timeout_seconds = timeout_seconds

    args_schema: type[BaseModel] = AragoraToolInput

    def _run(
        self,
        question: str,
        agents: list[str] | None = None,
        rounds: int | None = None,
        consensus_threshold: float = 0.8,
        include_evidence: bool = True,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        """Run a synchronous debate.

        Args:
            question: The question to debate
            agents: List of agents to use
            rounds: Number of debate rounds
            consensus_threshold: Confidence threshold for consensus
            include_evidence: Whether to include evidence
            run_manager: LangChain callback manager

        Returns:
            JSON string with debate result
        """
        return asyncio.run(
            self._arun(
                question=question,
                agents=agents,
                rounds=rounds,
                consensus_threshold=consensus_threshold,
                include_evidence=include_evidence,
            )
        )

    async def _arun(
        self,
        question: str,
        agents: list[str] | None = None,
        rounds: int | None = None,
        consensus_threshold: float = 0.8,
        include_evidence: bool = True,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        """Run an asynchronous debate.

        Args:
            question: The question to debate
            agents: List of agents to use
            rounds: Number of debate rounds
            consensus_threshold: Confidence threshold for consensus
            include_evidence: Whether to include evidence
            run_manager: LangChain async callback manager

        Returns:
            JSON string with debate result
        """
        from aragora.observability.http_client_pool import get_http_pool

        agents = agents or self.default_agents
        rounds = rounds or self.default_rounds

        payload = {
            "question": question,
            "agents": agents,
            "rounds": rounds,
            "consensus_threshold": consensus_threshold,
            "include_evidence": include_evidence,
        }

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            pool = get_http_pool()
            async with pool.get_session("langchain_tool") as client:
                response = await client.post(
                    f"{self.api_base}/api/debates",
                    json=payload,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 200:
                    result = response.json()
                    return self._format_result(result)
                else:
                    error = response.text
                    return json.dumps(
                        {
                            "error": f"API error: {response.status_code}",
                            "details": error,
                        }
                    )
        except asyncio.TimeoutError:
            return json.dumps(
                {
                    "error": "Debate timed out",
                    "timeout_seconds": self.timeout_seconds,
                }
            )
        except (ConnectionError, TimeoutError, OSError) as e:
            return json.dumps(
                {
                    "error": f"Debate connection error ({type(e).__name__}): {e}",
                }
            )
        except (RuntimeError, ValueError, TypeError) as e:
            return json.dumps(
                {
                    "error": f"Failed to run debate ({type(e).__name__}): {e}",
                }
            )

    def _format_result(self, result: dict[str, Any]) -> str:
        """Format the debate result as a readable string."""
        formatted = {
            "answer": result.get("final_answer", "No answer reached"),
            "confidence": result.get("confidence", 0),
            "consensus_reached": result.get("consensus_reached", False),
            "rounds_used": result.get("rounds_used", 0),
            "participants": result.get("participants", []),
        }

        # Include key reasoning points if available
        if "reasoning" in result:
            formatted["key_points"] = result["reasoning"][:3]  # Top 3 points

        return json.dumps(formatted, indent=2)


# =============================================================================
# Aragora Retriever
# =============================================================================


class AragoraRetriever(BaseRetriever):
    """
    LangChain Retriever for querying Aragora's Knowledge Mound.

    This retriever allows LangChain RAG pipelines to leverage Aragora's
    knowledge base for context retrieval.

    Example:
        retriever = AragoraRetriever(
            api_base="https://api.aragora.ai",
            api_key="your-key"
        )
        docs = retriever.get_relevant_documents("database scaling patterns")
    """

    api_base: str = "https://api.aragora.ai"
    api_key: str = ""
    top_k: int = 5
    min_confidence: float = 0.0
    include_metadata: bool = True

    def __init__(
        self,
        api_base: str = "https://api.aragora.ai",
        api_key: str = "",
        top_k: int = 5,
        min_confidence: float = 0.0,
        include_metadata: bool = True,
        **kwargs,
    ):
        """Initialize the Aragora retriever.

        Args:
            api_base: Base URL for Aragora API
            api_key: API key for authentication
            top_k: Number of documents to retrieve
            min_confidence: Minimum confidence threshold
            include_metadata: Whether to include document metadata
        """
        super().__init__(**kwargs)
        self.api_base = api_base
        self.api_key = api_key
        self.top_k = top_k
        self.min_confidence = min_confidence
        self.include_metadata = include_metadata

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        """Retrieve relevant documents synchronously.

        This is the required abstract method for LangChain BaseRetriever.
        LangChain's get_relevant_documents() routes here automatically.

        Args:
            query: The search query.
            run_manager: LangChain callback manager (not used in this implementation).
        """
        return asyncio.run(self._fetch_documents(query))

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: AsyncCallbackManagerForRetrieverRun,
    ) -> list[Document]:
        """Retrieve relevant documents asynchronously.

        Args:
            query: The search query.
            run_manager: LangChain async callback manager (not used in this implementation).
        """
        return await self._fetch_documents(query)

    async def _fetch_documents(self, query: str) -> list[Document]:
        """Internal method to fetch documents from the API."""
        from aragora.observability.http_client_pool import get_http_pool

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        params = {
            "query": query,
            "limit": self.top_k,
            "min_confidence": self.min_confidence,
        }

        try:
            pool = get_http_pool()
            async with pool.get_session("langchain_retriever") as client:
                response = await client.get(
                    f"{self.api_base}/api/knowledge/search",
                    params=params,
                    headers=headers,
                    timeout=30,
                )
                if response.status_code == 200:
                    result = response.json()
                    return self._convert_to_documents(result.get("nodes", []))
                else:
                    logger.warning("Knowledge search failed: %s", response.status_code)
                    return []
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.error("Knowledge retrieval connection error: %s: %s", type(e).__name__, e)
            return []
        except (RuntimeError, ValueError, TypeError) as e:
            logger.error("Failed to retrieve documents: %s: %s", type(e).__name__, e)
            return []

    def _convert_to_documents(self, nodes: list[dict[str, Any]]) -> list[Document]:
        """Convert Aragora knowledge nodes to LangChain Documents."""
        documents = []

        for node in nodes:
            content = node.get("content", "")

            metadata = {}
            if self.include_metadata:
                metadata = {
                    "node_id": node.get("id", ""),
                    "node_type": node.get("node_type", ""),
                    "confidence": node.get("confidence", 0),
                    "created_at": node.get("created_at", ""),
                    "topics": node.get("topics", []),
                    "source": "aragora_knowledge_mound",
                }

            documents.append(Document(page_content=content, metadata=metadata))

        return documents


# =============================================================================
# Aragora Callback Handler
# =============================================================================


class AragoraCallbackHandler(BaseCallbackHandler):
    """
    LangChain Callback Handler for Aragora debate events.

    This handler allows monitoring and logging of Aragora operations
    within LangChain workflows.

    Example:
        handler = AragoraCallbackHandler(
            on_debate_start=lambda d: print(f"Started: {d['debate_id']}")
        )
    """

    def __init__(
        self,
        on_debate_start: Callable[[dict], None] | None = None,
        on_debate_end: Callable[[dict], None] | None = None,
        on_consensus: Callable[[dict], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        verbose: bool = False,
    ):
        """Initialize the callback handler.

        Args:
            on_debate_start: Callback for debate start events
            on_debate_end: Callback for debate end events
            on_consensus: Callback for consensus events
            on_error: Callback for error events (receives BaseException)
            verbose: Whether to log debug information
        """
        super().__init__()
        self._on_debate_start = on_debate_start
        self._on_debate_end = on_debate_end
        self._on_consensus = on_consensus
        self._on_error = on_error
        self.verbose = verbose

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs,
    ) -> None:
        """Called when a tool starts running."""
        if serialized.get("name") == "aragora_debate":
            if self.verbose:
                logger.info("Aragora debate starting: %s...", input_str[:100])
            if self._on_debate_start:
                self._on_debate_start({"input": input_str})

    def on_tool_end(
        self,
        output: str,
        **kwargs,
    ) -> None:
        """Called when a tool finishes running."""
        if self.verbose:
            logger.info("Aragora debate completed: %s...", output[:100])
        if self._on_debate_end:
            try:
                result = json.loads(output)
                self._on_debate_end(result)
            except json.JSONDecodeError:
                self._on_debate_end({"raw_output": output})

    def on_tool_error(
        self,
        error: BaseException,
        **kwargs: Any,
    ) -> Any:
        """Called when a tool errors.

        Args:
            error: The exception that occurred.
            **kwargs: Additional keyword arguments from LangChain.

        Returns:
            Any value (unused, for compatibility with base class).
        """
        if self.verbose:
            logger.error("Aragora debate error: %s", error)
        if self._on_error:
            self._on_error(error)


# =============================================================================
# Aragora Chain Builder
# =============================================================================


def create_aragora_chain(
    api_base: str = "https://api.aragora.ai",
    api_key: str = "",
    llm: Any = None,
    include_knowledge: bool = True,
    verbose: bool = False,
) -> Any:
    """
    Create a LangChain chain that incorporates Aragora debate capabilities.

    This is a helper function that creates a simple chain combining
    Aragora tools with an LLM for pre/post processing.

    Args:
        api_base: Base URL for Aragora API
        api_key: API key for authentication
        llm: LangChain LLM to use for processing
        include_knowledge: Whether to include knowledge retrieval
        verbose: Whether to enable verbose logging

    Returns:
        A LangChain chain incorporating Aragora capabilities

    Raises:
        ImportError: If LangChain is not installed
    """
    if not LANGCHAIN_AVAILABLE:
        raise ImportError(
            "LangChain is required for create_aragora_chain. "
            "Install it with: pip install langchain langchain-core"
        )

    from langchain.agents import AgentExecutor, create_tool_calling_agent
    from langchain_core.prompts import ChatPromptTemplate

    # Create tools - use BaseTool type to allow mixing AragoraTool and retriever Tool
    tools: list[BaseTool] = [
        AragoraTool(api_base=api_base, api_key=api_key),
    ]

    # Add retriever as a tool if requested
    if include_knowledge:
        retriever = AragoraRetriever(api_base=api_base, api_key=api_key)
        from langchain.tools.retriever import create_retriever_tool

        retriever_tool = create_retriever_tool(
            retriever,
            "aragora_knowledge",
            "Search Aragora's knowledge base for relevant information and past debate insights.",
        )
        tools.append(retriever_tool)

    # Create prompt
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "You are an intelligent assistant with access to Aragora's multi-agent "
                    "decision-making system. Use the aragora_debate tool for complex questions "
                    "that benefit from multiple AI perspectives. Use the aragora_knowledge tool "
                    "to search for relevant background information."
                ),
            ),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )

    # Create agent
    if llm is None:
        raise ValueError("An LLM must be provided to create_aragora_chain")

    agent = create_tool_calling_agent(llm, tools, prompt)

    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=verbose,
        callbacks=[AragoraCallbackHandler(verbose=verbose)],
    )


# =============================================================================
# Utility Functions
# =============================================================================


def is_langchain_available() -> bool:
    """Check if LangChain is installed and available."""
    return LANGCHAIN_AVAILABLE


def get_langchain_version() -> str | None:
    """Get the installed LangChain version, if available."""
    if not LANGCHAIN_AVAILABLE:
        return None
    try:
        import langchain_core

        return getattr(langchain_core, "__version__", "unknown")
    except Exception:  # noqa: BLE001 - Version check fallback
        return None


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "AragoraTool",
    "AragoraRetriever",
    "AragoraCallbackHandler",
    "AragoraToolInput",
    "create_aragora_chain",
    "is_langchain_available",
    "get_langchain_version",
    "LANGCHAIN_AVAILABLE",
]
