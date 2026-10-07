"""Document Explorer - main orchestrator for iterative document exploration.

Coordinates exploration agents to iteratively understand documents through:
- Reading and extracting understanding from chunks
- Generating and answering follow-up questions
- Tracing cross-document references
- Multi-agent verification of findings
- Synthesizing cross-document understanding
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from collections.abc import Callable

from aragora.audit.exploration.session import (
    ExplorationPhase,
    ExplorationResult,
    ExplorationSession,
    Insight,
    Question,
    Reference,
    SynthesizedUnderstanding,
)
from aragora.audit.exploration.memory import ExplorationMemory, MemoryTier
from aragora.audit.exploration.agents import ExplorationAgent, VerifierAgent
from aragora.documents.chunking.strategies import (
    ChunkingStrategy,
    ChunkingStrategyType,
    get_chunking_strategy,
)
from aragora.documents.models import DocumentChunk

logger = logging.getLogger(__name__)


class EventEmitter(Protocol):
    """Protocol for event emission during exploration."""

    async def emit(self, event: str, data: dict[str, Any]) -> None:
        """Emit an exploration event."""
        ...


@dataclass
class ExplorerConfig:
    """Configuration for the document explorer."""

    # Iteration limits
    max_iterations: int = 10
    max_chunks_per_iteration: int = 5
    max_questions_per_iteration: int = 3
    max_references_per_iteration: int = 3

    # Convergence
    convergence_threshold: float = 0.85
    min_iterations: int = 2

    # Chunking
    chunk_size: int = 500
    chunk_overlap: int = 50
    chunking_strategy: ChunkingStrategyType = "semantic"

    # Verification
    enable_verification: bool = True
    verification_threshold: int = 2  # Agents needed to verify

    # Memory
    enable_memory: bool = True
    memory_db_path: Path | None = None

    # Timeouts
    phase_timeout: float = 300.0  # 5 minutes per phase
    total_timeout: float = 1800.0  # 30 minutes total


class DocumentExplorer:
    """Orchestrates iterative document exploration.

    Modeled after Arena's phased execution pattern, enabling:
    - Agent-driven document reading and questioning
    - Iterative understanding refinement
    - Cross-document reference tracing
    - Memory-backed learning across explorations

    Example:
        >>> explorer = DocumentExplorer(
        ...     agents=[ExplorationAgent(name="claude", model="claude-opus-5")],
        ... )
        >>> result = await explorer.explore(
        ...     documents=["doc1.pdf", "doc2.md"],
        ...     objective="Find security vulnerabilities",
        ... )
    """

    def __init__(
        self,
        agents: list[ExplorationAgent],
        config: ExplorerConfig | None = None,
        memory: ExplorationMemory | None = None,
        event_emitter: EventEmitter | None = None,
        document_loader: Callable[[str], str] | None = None,
    ):
        """Initialize the document explorer.

        Args:
            agents: List of exploration agents to use
            config: Explorer configuration
            memory: Optional exploration memory for cross-session learning
            event_emitter: Optional event emitter for progress updates
            document_loader: Optional function to load document content by ID
        """
        if not agents:
            raise ValueError("At least one agent is required")

        self.agents = agents
        self.config = config or ExplorerConfig()
        self.memory = memory
        self.event_emitter = event_emitter
        self.document_loader = document_loader or self._default_document_loader

        # Create memory if enabled and not provided
        if self.config.enable_memory and not self.memory:
            self.memory = ExplorationMemory(db_path=self.config.memory_db_path)

        # Create verifier agent if verification is enabled
        self.verifier = None
        if self.config.enable_verification:
            self.verifier = VerifierAgent()

        # Chunking strategy
        self._chunker: ChunkingStrategy | None = None

        # Chunk storage (populated during document loading)
        self._session_chunks: dict[str, dict[str, DocumentChunk]] = {}

    def _get_chunker(self) -> ChunkingStrategy:
        """Get or create the chunking strategy."""
        if self._chunker is None:
            self._chunker = get_chunking_strategy(
                self.config.chunking_strategy,
                chunk_size=self.config.chunk_size,
                overlap=self.config.chunk_overlap,
            )
        return self._chunker

    def _default_document_loader(self, document_id: str) -> str:
        """Default document loader - reads from filesystem."""
        path = Path(document_id)
        if path.exists():
            return path.read_text()
        raise FileNotFoundError(f"Document not found: {document_id}")

    async def _emit(self, event: str, data: dict[str, Any]) -> None:
        """Emit an event if emitter is configured."""
        if self.event_emitter:
            try:
                await self.event_emitter.emit(event, data)
            except (ValueError, RuntimeError, OSError) as e:
                logger.warning("Failed to emit event %s: %s", event, e)

    async def explore(
        self,
        documents: list[str],
        objective: str,
        initial_questions: list[str] | None = None,
        session: ExplorationSession | None = None,
    ) -> ExplorationResult:
        """Explore documents iteratively to achieve an objective.

        Args:
            documents: List of document IDs or paths to explore
            objective: The exploration objective (what we're trying to understand)
            initial_questions: Optional initial questions to investigate
            session: Optional existing session to resume

        Returns:
            ExplorationResult with insights and synthesized understanding
        """
        # Create or resume session
        if session is None:
            session = ExplorationSession(
                objective=objective,
                document_ids=documents,
                max_iterations=self.config.max_iterations,
            )

        await self._emit(
            "exploration_start",
            {
                "session_id": session.id,
                "objective": objective,
                "documents": documents,
            },
        )

        try:
            # Phase 1: Load and chunk documents
            await self._load_documents(session)

            # Phase 2: Add initial questions
            if initial_questions:
                for q_text in initial_questions:
                    session.add_question(Question(text=q_text, priority=0.8))

            # Phase 3: Iterative exploration loop
            await self._exploration_loop(session)

            # Phase 4: Synthesize understanding
            synthesized = await self._synthesize(session)
            session.synthesized = synthesized

            # Phase 5: Consolidate memory
            if self.memory:
                await self.memory.consolidate_session(session.id)

            session.completed_at = datetime.now(timezone.utc)

        except asyncio.TimeoutError:
            logger.warning("Exploration timed out after %ss", self.config.total_timeout)
            session.completed_at = datetime.now(timezone.utc)
        except (ValueError, RuntimeError, OSError) as e:
            logger.error("Exploration failed: %s", e)
            session.completed_at = datetime.now(timezone.utc)
            raise

        # Build result
        duration = (session.completed_at - session.started_at).total_seconds()
        result = ExplorationResult(
            session_id=session.id,
            objective=objective,
            insights=session.insights,
            synthesized_understanding=session.synthesized,
            questions_answered=len([q for q in session.questions_asked if q.answered]),
            questions_unanswered=len([q for q in session.questions_asked if not q.answered]),
            references_resolved=len([r for r in session.references_traced if r.resolved]),
            chunks_explored=len(session.chunks_explored),
            iterations=session.iteration,
            duration_seconds=duration,
            final_confidence=session.overall_confidence,
        )

        await self._emit("exploration_complete", result.to_dict())
        return result

    async def _load_documents(self, session: ExplorationSession) -> None:
        """Load and chunk documents for exploration."""
        session.current_phase = ExplorationPhase.READ

        await self._emit("phase_start", {"phase": "load", "session_id": session.id})

        chunker = self._get_chunker()

        for doc_id in session.document_ids:
            try:
                content = self.document_loader(doc_id)
                chunks = chunker.chunk(content, document_id=doc_id)

                # Add chunks to pending queue
                for chunk in chunks:
                    chunk_id = f"{doc_id}:{chunk.sequence}"
                    session.chunks_pending.append(chunk_id)

                    # Store chunk for later retrieval
                    if session.id not in self._session_chunks:
                        self._session_chunks[session.id] = {}
                    self._session_chunks[session.id][chunk_id] = chunk

                logger.info("Loaded %s chunks from %s", len(chunks), doc_id)

            except (ValueError, OSError, RuntimeError) as e:
                logger.warning("Failed to load document %s: %s", doc_id, e)

        await self._emit(
            "phase_complete",
            {
                "phase": "load",
                "chunks_loaded": len(session.chunks_pending),
            },
        )

    async def _exploration_loop(self, session: ExplorationSession) -> None:
        """Main exploration loop - read, question, trace, verify."""
        while session.iteration < session.max_iterations:
            session.iteration += 1

            await self._emit(
                "iteration_start",
                {
                    "iteration": session.iteration,
                    "chunks_pending": len(session.chunks_pending),
                    "questions_pending": len(session.questions_pending),
                },
            )

            # Read phase - explore pending chunks
            session.current_phase = ExplorationPhase.READ
            await self._read_phase(session)

            # Question phase - generate and answer questions
            session.current_phase = ExplorationPhase.QUESTION
            await self._question_phase(session)

            # Trace phase - follow references
            session.current_phase = ExplorationPhase.TRACE
            await self._trace_phase(session)

            # Verify phase - multi-agent verification
            if self.config.enable_verification:
                session.current_phase = ExplorationPhase.VERIFY
                await self._verify_phase(session)

            # Check convergence
            if self._check_convergence(session):
                logger.info("Exploration converged at iteration %s", session.iteration)
                break

            await self._emit(
                "iteration_complete",
                {
                    "iteration": session.iteration,
                    "insights": len(session.insights),
                    "confidence": session.overall_confidence,
                },
            )

    async def _read_phase(self, session: ExplorationSession) -> None:
        """Read pending chunks and extract understanding."""
        chunks_to_read = session.chunks_pending[: self.config.max_chunks_per_iteration]

        session_chunks = self._session_chunks.get(session.id, {})
        for chunk_id in chunks_to_read:
            chunk = session_chunks.get(chunk_id)
            if not chunk:
                continue

            # Select agent (round-robin or based on expertise)
            agent = self.agents[session.iteration % len(self.agents)]

            # Read chunk
            understanding = await agent.read_chunk(
                chunk=chunk,
                objective=session.objective,
                prior_context=session.insights[-5:],  # Last 5 insights for context
            )

            # Store understanding
            session.mark_chunk_explored(chunk_id, understanding)

            # Extract insights from key facts
            for fact in understanding.key_facts:
                if understanding.confidence >= self.config.convergence_threshold * 0.5:
                    insight = Insight(
                        title=fact[:50] + "..." if len(fact) > 50 else fact,
                        description=fact,
                        category="fact",
                        confidence=understanding.confidence,
                        evidence_chunks=[chunk_id],
                    )
                    session.add_insight(insight)

                    # Store in memory
                    if self.memory:
                        await self.memory.store_insight(
                            insight,
                            tier=MemoryTier.FAST,
                            session_id=session.id,
                            document_ids=(
                                [chunk.document_id] if hasattr(chunk, "document_id") else []
                            ),
                        )

            # Add questions raised
            for q_text in understanding.questions_raised:
                session.add_question(
                    Question(
                        text=q_text,
                        source_chunk=chunk_id,
                        priority=understanding.confidence,
                    )
                )

            # Add references to trace
            for ref in understanding.references_found:
                session.add_reference(ref)

            await self._emit(
                "chunk_explored",
                {
                    "chunk_id": chunk_id,
                    "facts_extracted": len(understanding.key_facts),
                    "confidence": understanding.confidence,
                },
            )

    async def _question_phase(self, session: ExplorationSession) -> None:
        """Generate and attempt to answer follow-up questions."""
        # Get top questions
        questions = sorted(
            [q for q in session.questions_pending if not q.answered],
            key=lambda q: q.priority,
            reverse=True,
        )[: self.config.max_questions_per_iteration]

        for question in questions:
            # Try to answer from existing understandings
            answer = self._search_for_answer(session, question)

            if answer:
                question.answered = True
                question.answer = answer["text"]
                question.answer_source = answer["source"]
                session.questions_asked.append(question)
                session.questions_pending.remove(question)

                await self._emit(
                    "question_answered",
                    {
                        "question": question.text,
                        "answer": answer["text"][:100],
                    },
                )
            else:
                # Question remains unanswered - may need more exploration
                session.questions_asked.append(question)

    def _search_for_answer(
        self, session: ExplorationSession, question: Question
    ) -> dict[str, str] | None:
        """Search existing understandings for an answer to a question."""
        question_words = set(question.text.lower().split())

        best_match = None
        best_score = 0.0

        for chunk_id, understanding in session.chunk_understandings.items():
            # Search in key facts
            for fact in understanding.key_facts:
                fact_words = set(fact.lower().split())
                overlap = len(question_words & fact_words)
                score = overlap / max(len(question_words), 1)

                if score > best_score and score > 0.3:
                    best_score = score
                    best_match = {"text": fact, "source": chunk_id}

        return best_match

    async def _trace_phase(self, session: ExplorationSession) -> None:
        """Trace cross-document references."""
        references = [r for r in session.references_pending if not r.resolved]
        references = references[: self.config.max_references_per_iteration]

        for reference in references:
            agent = self.agents[0]  # Use primary agent for reference tracing

            # Try to resolve reference
            resolved = await agent.trace_reference(
                reference=reference,
                available_documents=session.document_ids,
                context=self._build_reference_context(session, reference),
            )

            session.references_traced.append(resolved)
            if resolved in session.references_pending:
                session.references_pending.remove(resolved)

            if resolved.resolved:
                await self._emit(
                    "reference_resolved",
                    {
                        "source": reference.source_document,
                        "target": resolved.target_document,
                    },
                )

    def _build_reference_context(self, session: ExplorationSession, reference: Reference) -> str:
        """Build context for reference resolution."""
        context_parts = []

        # Add related understandings
        for chunk_id, understanding in session.chunk_understandings.items():
            if reference.target_description.lower() in understanding.summary.lower():
                context_parts.append(f"[{chunk_id}]: {understanding.summary}")

        return "\n".join(context_parts[:5])

    async def _verify_phase(self, session: ExplorationSession) -> None:
        """Multi-agent verification of findings."""
        if not self.verifier:
            return

        # Verify top unverified insights
        unverified = [i for i in session.insights if not i.verified_by]
        for insight in unverified[:3]:
            # Build verification context
            context = self._build_verification_context(session, insight)

            # Get verification from verifier agent
            result = await self.verifier.verify_insight(insight, context)

            if result["verdict"] == "verified":
                insight.verified_by.append(self.verifier.name)
                insight.confidence = max(insight.confidence, result["confidence"])
            elif result["verdict"] == "disputed":
                insight.disputed_by.append(self.verifier.name)
                insight.confidence = min(insight.confidence, result["confidence"])

            await self._emit(
                "insight_verified",
                {
                    "insight_id": insight.id,
                    "verdict": result["verdict"],
                    "confidence": result["confidence"],
                },
            )

    def _build_verification_context(self, session: ExplorationSession, insight: Insight) -> str:
        """Build context for insight verification."""
        context_parts = []

        # Add evidence from referenced chunks
        for chunk_id in insight.evidence_chunks:
            if chunk_id in session.chunk_understandings:
                u = session.chunk_understandings[chunk_id]
                context_parts.append(
                    f"[{chunk_id}]:\n{u.summary}\nFacts: {', '.join(u.key_facts[:3])}"
                )

        return "\n\n".join(context_parts)

    def _check_convergence(self, session: ExplorationSession) -> bool:
        """Check if exploration has converged."""
        if session.iteration < self.config.min_iterations:
            return False

        # Check if we have enough confidence
        if session.overall_confidence >= self.config.convergence_threshold:
            return True

        # Check if no more pending work
        if (
            not session.chunks_pending
            and not session.questions_pending
            and not session.references_pending
        ):
            return True

        # Check convergence history
        session.convergence_history.append(session.overall_confidence)
        if len(session.convergence_history) >= 3:
            recent = session.convergence_history[-3:]
            # Converged if confidence is stable (not improving much)
            if max(recent) - min(recent) < 0.05:
                return True

        return False

    async def _synthesize(self, session: ExplorationSession) -> SynthesizedUnderstanding:
        """Synthesize final understanding across all explored content."""
        session.current_phase = ExplorationPhase.SYNTHESIZE

        await self._emit("phase_start", {"phase": "synthesize", "session_id": session.id})

        agent = self.agents[0]
        synthesized = await agent.synthesize(
            understandings=list(session.chunk_understandings.values()),
            insights=session.insights,
            objective=session.objective,
        )

        await self._emit(
            "phase_complete",
            {
                "phase": "synthesize",
                "summary_length": len(synthesized.summary),
                "findings_count": len(synthesized.key_findings),
            },
        )

        return synthesized
