"""
Natural Language Query Interface.

Enables asking natural language questions about uploaded documents
with AI-powered answer synthesis and source citations.

Usage:
    from aragora.analysis.nl_query import DocumentQueryEngine, QueryConfig

    engine = await DocumentQueryEngine.create()
    result = await engine.query(
        question="What contracts mention exclusivity clauses?",
        workspace_id="ws_123",
        document_ids=["doc1", "doc2"]  # Optional: limit scope
    )

    print(result.answer)
    for citation in result.citations:
        print(f"  - {citation.document_id}: {citation.snippet}")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any
from collections.abc import AsyncIterator
from uuid import uuid4

from aragora.utils.cache_registry import register_lru_cache

if TYPE_CHECKING:
    from aragora.agents.base import AgentType

# Map model config strings to AgentType identifiers
_MODEL_TO_AGENT_TYPE: dict[str, AgentType] = {
    "claude-opus-5": "anthropic-api",
    "claude-opus-4-8": "anthropic-api",
    "claude-opus-4-7": "anthropic-api",
    "claude-opus-4": "anthropic-api",
    "claude-haiku-4": "anthropic-api",
    # Legacy model names (backwards compat)
    "claude-3.5-sonnet": "anthropic-api",
    "claude-3-opus": "anthropic-api",
    "claude-3-sonnet": "anthropic-api",
    "gpt-4": "openai-api",
    "gpt-4-turbo": "openai-api",
    "gpt-4o": "openai-api",
    "gemini-3.1-pro-preview": "gemini",
    "gemini-1.5-flash": "gemini",
    "gemini-1.5-pro": "gemini",
    "gemini-2.0-flash": "gemini",
}

logger = logging.getLogger(__name__)


class QueryMode(str, Enum):
    """Query processing modes."""

    FACTUAL = "factual"  # Direct fact extraction
    ANALYTICAL = "analytical"  # Analysis and reasoning
    COMPARATIVE = "comparative"  # Compare across documents
    SUMMARY = "summary"  # Summarize content
    EXTRACTIVE = "extractive"  # Extract specific information


class AnswerConfidence(str, Enum):
    """Confidence level in the generated answer."""

    HIGH = "high"  # Strong evidence, clear answer
    MEDIUM = "medium"  # Moderate evidence, likely answer
    LOW = "low"  # Weak evidence, uncertain
    NONE = "none"  # No relevant information found


@dataclass
class QueryConfig:
    """Configuration for document querying."""

    # Search parameters
    max_chunks: int = 10  # Maximum chunks to retrieve
    min_relevance: float = 0.3  # Minimum relevance score
    vector_weight: float = 0.7  # Weight for semantic vs keyword search

    # Answer generation
    max_answer_length: int = 500  # Maximum answer length in words
    include_quotes: bool = True  # Include direct quotes in answer
    require_citations: bool = True  # Always cite sources

    # Model selection
    model: str = "claude-opus-5"  # Primary model for answer generation
    fallback_model: str = "gemini-3-flash-preview"  # Fallback if primary fails

    # Query enhancement
    expand_query: bool = True  # Generate query variations
    detect_intent: bool = True  # Detect question type/intent

    # Multi-turn context
    enable_context: bool = True  # Use conversation history
    max_context_turns: int = 3  # Maximum turns to include


@dataclass
class Citation:
    """A citation to source material."""

    document_id: str
    document_name: str
    chunk_id: str
    snippet: str  # Relevant excerpt
    page: int | None = None
    relevance_score: float = 0.0
    heading_context: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "document_id": self.document_id,
            "document_name": self.document_name,
            "chunk_id": self.chunk_id,
            "snippet": self.snippet,
            "page": self.page,
            "relevance_score": self.relevance_score,
            "heading_context": self.heading_context,
        }


@dataclass
class QueryResult:
    """Result of a natural language query."""

    query_id: str
    question: str
    answer: str
    confidence: AnswerConfidence
    citations: list[Citation]
    query_mode: QueryMode
    chunks_searched: int
    chunks_relevant: int
    processing_time_ms: int
    model_used: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query_id": self.query_id,
            "question": self.question,
            "answer": self.answer,
            "confidence": self.confidence.value,
            "citations": [c.to_dict() for c in self.citations],
            "query_mode": self.query_mode.value,
            "chunks_searched": self.chunks_searched,
            "chunks_relevant": self.chunks_relevant,
            "processing_time_ms": self.processing_time_ms,
            "model_used": self.model_used,
            "metadata": self.metadata,
        }

    @property
    def has_answer(self) -> bool:
        """Check if a meaningful answer was found."""
        return self.confidence != AnswerConfidence.NONE and bool(self.answer)


@dataclass
class StreamingChunk:
    """A chunk of streaming response."""

    text: str
    is_final: bool = False
    citations: list[Citation] = field(default_factory=list)


# =============================================================================
# Cached Query Mode Detection
# =============================================================================


@register_lru_cache
@lru_cache(maxsize=512)
def _expand_query_cached(question: str) -> tuple[str, str]:
    """Cached query expansion - returns (original, keyword_query).

    Args:
        question: The original question string

    Returns:
        Tuple of (original question, keyword-focused query)
    """
    # Remove question words and punctuation to create keyword-focused version
    keyword_query = question.lower()
    for word in [
        "what",
        "where",
        "when",
        "why",
        "how",
        "which",
        "who",
        "is",
        "are",
        "does",
        "do",
        "?",
    ]:
        keyword_query = keyword_query.replace(word, " ")
    keyword_query = " ".join(keyword_query.split())

    return (question, keyword_query)


@register_lru_cache
@lru_cache(maxsize=512)
def _detect_query_mode_cached(question_lower: str) -> str:
    """Cached query mode detection based on keyword patterns.

    Args:
        question_lower: Lowercase question string (truncated to 500 chars)

    Returns:
        QueryMode value string
    """
    # Summary indicators
    if any(word in question_lower for word in ["summarize", "summary", "overview", "main points"]):
        return QueryMode.SUMMARY.value

    # Comparison indicators
    if any(
        word in question_lower for word in ["compare", "difference", "versus", "vs", "contrast"]
    ):
        return QueryMode.COMPARATIVE.value

    # Analysis indicators
    if any(
        word in question_lower for word in ["why", "analyze", "explain", "implications", "impact"]
    ):
        return QueryMode.ANALYTICAL.value

    # Extraction indicators
    if any(word in question_lower for word in ["list", "extract", "find all", "identify"]):
        return QueryMode.EXTRACTIVE.value

    # Default to factual
    return QueryMode.FACTUAL.value


class DocumentQueryEngine:
    """
    Natural language query engine for document analysis.

    Combines hybrid search with LLM-powered answer synthesis
    to answer questions about document content with citations.
    """

    def __init__(
        self,
        config: QueryConfig | None = None,
        searcher: Any | None = None,  # HybridSearcher
    ):
        """
        Initialize the query engine.

        Args:
            config: Query configuration
            searcher: Hybrid searcher instance (created if not provided)
        """
        self.config = config or QueryConfig()
        self._searcher = searcher
        self._conversation_history: dict[str, list[dict]] = {}

    @classmethod
    async def create(
        cls,
        config: QueryConfig | None = None,
    ) -> DocumentQueryEngine:
        """
        Create a query engine with default components.

        Args:
            config: Query configuration

        Returns:
            Configured DocumentQueryEngine
        """
        try:
            from aragora.documents.indexing.hybrid_search import create_hybrid_searcher

            searcher = await create_hybrid_searcher()
        except (ImportError, RuntimeError, OSError) as e:
            logger.warning("Could not create hybrid searcher: %s", e)
            searcher = None

        return cls(config=config, searcher=searcher)

    async def query(
        self,
        question: str,
        workspace_id: str | None = None,
        document_ids: list[str] | None = None,
        conversation_id: str | None = None,
    ) -> QueryResult:
        """
        Answer a natural language question about documents.

        Args:
            question: The question to answer
            workspace_id: Optional workspace scope
            document_ids: Optional document IDs to search within
            conversation_id: Optional ID for multi-turn context

        Returns:
            QueryResult with answer and citations
        """
        start_time = time.time()
        query_id = f"query_{uuid4().hex[:12]}"

        # Detect query mode/intent
        query_mode = (
            self._detect_query_mode(question) if self.config.detect_intent else QueryMode.FACTUAL
        )

        # Expand query for better retrieval
        expanded_queries = self._expand_query(question) if self.config.expand_query else [question]

        # Search for relevant chunks
        all_results = []
        for q in expanded_queries:
            results = await self._search_chunks(
                query=q,
                document_ids=document_ids,
            )
            all_results.extend(results)

        # Deduplicate and rank
        unique_results = self._deduplicate_results(all_results)
        relevant_results = [
            r for r in unique_results if r.combined_score >= self.config.min_relevance
        ]

        # Get conversation context if enabled
        context_messages = []
        if self.config.enable_context and conversation_id:
            context_messages = self._get_conversation_context(conversation_id)

        # Generate answer
        if relevant_results:
            answer, citations, confidence, model_used = await self._generate_answer(
                question=question,
                results=relevant_results[: self.config.max_chunks],
                query_mode=query_mode,
                context_messages=context_messages,
            )
        else:
            answer = (
                "I couldn't find relevant information in the documents to answer this question."
            )
            citations = []
            confidence = AnswerConfidence.NONE
            model_used = "none"

        # Store in conversation history
        if conversation_id:
            self._add_to_history(conversation_id, question, answer)

        processing_time = int((time.time() - start_time) * 1000)

        return QueryResult(
            query_id=query_id,
            question=question,
            answer=answer,
            confidence=confidence,
            citations=citations,
            query_mode=query_mode,
            chunks_searched=len(all_results),
            chunks_relevant=len(relevant_results),
            processing_time_ms=processing_time,
            model_used=model_used,
            metadata={
                "workspace_id": workspace_id,
                "document_ids": document_ids,
                "expanded_queries": expanded_queries,
            },
        )

    async def query_stream(
        self,
        question: str,
        workspace_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> AsyncIterator[StreamingChunk]:
        """
        Stream the answer to a question.

        Args:
            question: The question to answer
            workspace_id: Optional workspace scope
            document_ids: Optional document IDs to search within

        Yields:
            StreamingChunk objects with partial answer text
        """
        # Search for relevant chunks first
        results = await self._search_chunks(
            query=question,
            document_ids=document_ids,
        )
        relevant_results = [r for r in results if r.combined_score >= self.config.min_relevance]

        if not relevant_results:
            yield StreamingChunk(
                text="I couldn't find relevant information in the documents to answer this question.",
                is_final=True,
                citations=[],
            )
            return

        # Build citations
        citations = self._build_citations(relevant_results[: self.config.max_chunks])

        # Stream the answer
        async for text_chunk in self._stream_answer(
            question=question,
            results=relevant_results[: self.config.max_chunks],
        ):
            yield StreamingChunk(text=text_chunk, is_final=False)

        # Final chunk with citations
        yield StreamingChunk(text="", is_final=True, citations=citations)

    async def summarize_documents(
        self,
        document_ids: list[str],
        focus: str | None = None,
    ) -> QueryResult:
        """
        Summarize one or more documents.

        Args:
            document_ids: Documents to summarize
            focus: Optional focus area for the summary

        Returns:
            QueryResult with summary
        """
        question = "Provide a comprehensive summary of these documents"
        if focus:
            question += f", focusing on {focus}"

        return await self.query(
            question=question,
            document_ids=document_ids,
        )

    async def compare_documents(
        self,
        document_ids: list[str],
        aspects: list[str] | None = None,
    ) -> QueryResult:
        """
        Compare multiple documents.

        Args:
            document_ids: Documents to compare (2+)
            aspects: Optional specific aspects to compare

        Returns:
            QueryResult with comparison
        """
        if len(document_ids) < 2:
            raise ValueError("Need at least 2 documents to compare")

        aspect_str = ", ".join(aspects) if aspects else "key points, differences, and similarities"
        question = f"Compare these documents focusing on: {aspect_str}"

        return await self.query(
            question=question,
            document_ids=document_ids,
        )

    async def extract_information(
        self,
        document_ids: list[str],
        extraction_template: dict[str, str],
    ) -> dict[str, QueryResult]:
        """
        Extract structured information from documents.

        Args:
            document_ids: Documents to extract from
            extraction_template: Dict mapping field names to extraction queries

        Returns:
            Dict mapping field names to QueryResults
        """
        results = {}

        for field_name, query in extraction_template.items():
            result = await self.query(
                question=query,
                document_ids=document_ids,
            )
            results[field_name] = result

        return results

    def _detect_query_mode(self, question: str) -> QueryMode:
        """Detect the type/intent of the question.

        Uses cached detection for performance on repeated queries.
        Truncates to 500 chars to bound cache key size.
        """
        # Truncate to bound cache key size and lowercase
        question_key = question.lower()[:500]
        mode_value = _detect_query_mode_cached(question_key)
        return QueryMode(mode_value)

    def _expand_query(self, question: str) -> list[str]:
        """Generate query variations for better retrieval."""
        # Use cached expansion for the string transformation
        original, keyword_query = _expand_query_cached(question)
        queries = [original]

        if keyword_query and keyword_query != question.lower():
            queries.append(keyword_query)

        return queries[: self.config.max_context_turns + 1]  # Limit expansions

    async def _search_chunks(
        self,
        query: str,
        document_ids: list[str] | None = None,
    ) -> list[Any]:  # list[HybridResult]
        """Search for relevant chunks using hybrid search."""
        if self._searcher is None:
            logger.warning("No searcher available, returning empty results")
            return []

        try:
            results = await self._searcher.search(
                query=query,
                limit=self.config.max_chunks * 2,  # Get more for deduplication
                document_ids=document_ids,
                vector_weight=self.config.vector_weight,
            )
            return results
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Search failed: %s", e)
            return []

    def _deduplicate_results(self, results: list[Any]) -> list[Any]:
        """Remove duplicate chunks, keeping highest scores."""
        seen: dict[str, Any] = {}
        for result in results:
            chunk_id = result.chunk_id
            if chunk_id not in seen or result.combined_score > seen[chunk_id].combined_score:
                seen[chunk_id] = result

        return sorted(seen.values(), key=lambda x: x.combined_score, reverse=True)

    async def _generate_answer(
        self,
        question: str,
        results: list[Any],
        query_mode: QueryMode,
        context_messages: list[dict],
    ) -> tuple[str, list[Citation], AnswerConfidence, str]:
        """Generate an answer using an LLM."""
        # Build context from search results
        context_parts = []
        for i, result in enumerate(results, 1):
            source_info = f"[Source {i}: {result.document_id}"
            if result.start_page:
                source_info += f", page {result.start_page}"
            source_info += "]"

            context_parts.append(f"{source_info}\n{result.content}\n")

        context = "\n".join(context_parts)

        # Build the prompt
        prompt = self._build_answer_prompt(question, context, query_mode)

        # Try to generate answer
        try:
            answer, model_used = await self._call_llm(prompt, context_messages)
        except (ImportError, RuntimeError, OSError, ValueError) as e:
            logger.error("LLM call failed: %s", e)
            answer = "I encountered an error while generating the answer."
            model_used = "error"

        # Build citations
        citations = self._build_citations(results)

        # Assess confidence
        confidence = self._assess_confidence(answer, results)

        return answer, citations, confidence, model_used

    def _build_answer_prompt(
        self,
        question: str,
        context: str,
        query_mode: QueryMode,
    ) -> str:
        """Build the prompt for answer generation."""
        mode_instructions = {
            QueryMode.FACTUAL: "Provide a direct, factual answer based on the sources. Be precise and concise.",
            QueryMode.ANALYTICAL: "Analyze the information and provide insights. Explain the reasoning and implications.",
            QueryMode.COMPARATIVE: "Compare and contrast the information across sources. Highlight similarities and differences.",
            QueryMode.SUMMARY: "Provide a comprehensive summary of the key points from all sources.",
            QueryMode.EXTRACTIVE: "Extract and list the specific information requested. Be thorough and organized.",
        }

        instruction = mode_instructions.get(query_mode, mode_instructions[QueryMode.FACTUAL])

        prompt = f"""You are a helpful assistant answering questions about documents.

{instruction}

IMPORTANT RULES:
1. Only use information from the provided sources
2. If the sources don't contain the answer, say so clearly
3. Cite sources using [Source N] notation when referencing specific information
4. Do not make up or infer information not in the sources
5. Keep your answer under {self.config.max_answer_length} words

SOURCES:
{context}

QUESTION: {question}

ANSWER:"""

        return prompt

    async def _call_llm(
        self,
        prompt: str,
        context_messages: list[dict],
    ) -> tuple[str, str]:
        """Call an LLM to generate the answer."""
        # Try primary model
        try:
            from aragora.agents import create_agent

            agent_type = _MODEL_TO_AGENT_TYPE.get(self.config.model, "anthropic-api")
            agent = create_agent(agent_type, model=self.config.model)
            if agent:
                # Build prompt with context if available
                if context_messages:
                    # Format context messages into prompt
                    context_str = "\n".join(
                        f"{msg.get('role', 'user')}: {msg.get('content', '')}"
                        for msg in context_messages
                    )
                    full_prompt = f"Previous conversation:\n{context_str}\n\n{prompt}"
                else:
                    full_prompt = prompt
                response = await agent.generate(full_prompt)
                return response, self.config.model
        except (ImportError, RuntimeError, OSError, ValueError) as e:
            logger.warning("Primary model failed: %s, trying fallback", e)

        # Try fallback model
        try:
            from aragora.agents import create_agent

            fallback_type = _MODEL_TO_AGENT_TYPE.get(self.config.fallback_model, "gemini")
            agent = create_agent(fallback_type, model=self.config.fallback_model)
            if agent:
                response = await agent.generate(prompt)
                return response, self.config.fallback_model
        except (ImportError, RuntimeError, OSError, ValueError) as e:
            logger.error("Fallback model also failed: %s", e)

        # Last resort: return error message
        return "Unable to generate answer due to model unavailability.", "none"

    async def _stream_answer(
        self,
        question: str,
        results: list[Any],
    ) -> AsyncIterator[str]:
        """Stream the answer generation."""
        # Build context
        context_parts = []
        for i, result in enumerate(results, 1):
            context_parts.append(f"[Source {i}]\n{result.content}\n")

        context = "\n".join(context_parts)
        prompt = self._build_answer_prompt(question, context, QueryMode.FACTUAL)

        try:
            from aragora.agents import create_agent

            agent_type = _MODEL_TO_AGENT_TYPE.get(self.config.model, "anthropic-api")
            agent = create_agent(agent_type, model=self.config.model)
            if agent and hasattr(agent, "generate_stream"):
                async for chunk in agent.generate_stream(prompt):
                    yield chunk
            else:
                # Fallback to non-streaming
                response = await agent.generate(prompt) if agent else "No model available."
                yield response
        except (ImportError, RuntimeError, OSError, ValueError) as e:
            logger.error("Streaming failed: %s", e)
            yield f"Error generating answer: {str(e)}"

    def _build_citations(self, results: list[Any]) -> list[Citation]:
        """Build citation objects from search results."""
        citations = []

        for result in results:
            # Get snippet (first 200 chars of content)
            snippet = result.content[:200]
            if len(result.content) > 200:
                snippet += "..."

            citations.append(
                Citation(
                    document_id=result.document_id,
                    document_name=result.document_id,  # Would need doc metadata for actual name
                    chunk_id=result.chunk_id,
                    snippet=snippet,
                    page=result.start_page if result.start_page else None,
                    relevance_score=result.combined_score,
                    heading_context=result.heading_context,
                )
            )

        return citations

    def _assess_confidence(
        self,
        answer: str,
        results: list[Any],
    ) -> AnswerConfidence:
        """Assess confidence in the generated answer."""
        if not results:
            return AnswerConfidence.NONE

        # Check if answer indicates uncertainty
        uncertainty_phrases = [
            "i couldn't find",
            "no information",
            "not mentioned",
            "unable to",
            "don't have",
            "cannot determine",
        ]

        answer_lower = answer.lower()
        if any(phrase in answer_lower for phrase in uncertainty_phrases):
            return AnswerConfidence.LOW

        # Check relevance scores
        avg_relevance = sum(r.combined_score for r in results) / len(results)
        max_relevance = max(r.combined_score for r in results)

        if max_relevance > 0.8 and avg_relevance > 0.5:
            return AnswerConfidence.HIGH
        elif max_relevance > 0.5:
            return AnswerConfidence.MEDIUM
        else:
            return AnswerConfidence.LOW

    def _get_conversation_context(self, conversation_id: str) -> list[dict]:
        """Get recent conversation history for context."""
        if conversation_id not in self._conversation_history:
            return []

        history = self._conversation_history[conversation_id]
        return history[-self.config.max_context_turns * 2 :]  # Question + answer pairs

    def _add_to_history(
        self,
        conversation_id: str,
        question: str,
        answer: str,
    ) -> None:
        """Add a Q&A pair to conversation history."""
        if conversation_id not in self._conversation_history:
            self._conversation_history[conversation_id] = []

        self._conversation_history[conversation_id].extend(
            [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ]
        )

        # Trim to max history
        max_entries = self.config.max_context_turns * 2
        if len(self._conversation_history[conversation_id]) > max_entries:
            self._conversation_history[conversation_id] = self._conversation_history[
                conversation_id
            ][-max_entries:]

    def clear_conversation(self, conversation_id: str) -> None:
        """Clear conversation history for a given ID."""
        if conversation_id in self._conversation_history:
            del self._conversation_history[conversation_id]


# Convenience functions


async def query_documents(
    question: str,
    document_ids: list[str] | None = None,
    config: QueryConfig | None = None,
) -> QueryResult:
    """
    Quick function to query documents.

    Args:
        question: The question to answer
        document_ids: Optional document IDs to search within
        config: Optional query configuration

    Returns:
        QueryResult with answer and citations
    """
    engine = await DocumentQueryEngine.create(config=config)
    return await engine.query(question=question, document_ids=document_ids)


async def summarize_document(
    document_id: str,
    focus: str | None = None,
) -> QueryResult:
    """
    Quick function to summarize a document.

    Args:
        document_id: Document to summarize
        focus: Optional focus area

    Returns:
        QueryResult with summary
    """
    engine = await DocumentQueryEngine.create()
    return await engine.summarize_documents(document_ids=[document_id], focus=focus)


__all__ = [
    "DocumentQueryEngine",
    "QueryConfig",
    "QueryResult",
    "QueryMode",
    "AnswerConfidence",
    "Citation",
    "StreamingChunk",
    "query_documents",
    "summarize_document",
]
