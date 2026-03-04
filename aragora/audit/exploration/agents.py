"""Exploration agents for iterative document understanding.

Extends CLIAgent to provide document exploration capabilities,
mimicking Claude Code's iterative codebase exploration pattern.
"""

from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from aragora.agents.cli_agents import CLIAgent
from aragora.core import Message
from aragora.core_types import AgentRole
from aragora.documents.models import DocumentChunk

from aragora.audit.exploration.session import (
    ChunkUnderstanding,
    Insight,
    Question,
    Reference,
    SynthesizedUnderstanding,
)

logger = logging.getLogger(__name__)


class ExplorationMode(str, Enum):
    """Mode of exploration for different purposes."""

    DEEP_READ = "deep_read"  # Thorough reading, extract all facts and relationships
    SCAN = "scan"  # Quick scan for specific patterns or keywords
    CROSS_REFERENCE = "cross_reference"  # Find connections to other documents
    VERIFY = "verify"  # Verify claims against evidence
    SUMMARIZE = "summarize"  # Produce high-level summary


@dataclass
class ExplorationConfig:
    """Configuration for exploration agent behavior."""

    max_facts_per_chunk: int = 10
    max_questions_per_chunk: int = 5
    max_references_per_chunk: int = 5
    extract_entities: bool = True
    extract_relationships: bool = True
    confidence_threshold: float = 0.5
    response_format: str = "json"  # json or text


class ExplorationAgent(CLIAgent):
    """Agent specialized for iterative document exploration.

    Wraps Claude Code or Codex to explore documents iteratively,
    extracting understanding, generating questions, and tracing references.

    Key capabilities:
    - Read document chunks and extract structured understanding
    - Generate follow-up questions about unclear sections
    - Trace cross-document references
    - Verify findings through multi-agent debate
    - Synthesize cross-document understanding

    Example:
        >>> agent = ExplorationAgent(name="claude_explorer", model="claude-sonnet-4")
        >>> understanding = await agent.read_chunk(chunk, context=[])
        >>> questions = await agent.generate_questions(understanding)
    """

    # Exploration-specific prompts
    READ_CHUNK_PROMPT = """You are analyzing a document chunk to extract understanding.

## Document: {document_id}
## Chunk: {chunk_id}
## Exploration Objective: {objective}

## Prior Context:
{prior_context}

## Chunk Content:
{content}

Extract the following in JSON format:
{{
    "summary": "Brief summary of this chunk (1-2 sentences)",
    "key_facts": ["List of key facts extracted"],
    "entities": ["Named entities mentioned"],
    "relationships": [["entity1", "relation", "entity2"], ...],
    "references": [
        {{"text": "reference text", "target": "what it references"}}
    ],
    "questions": ["Questions raised by this content"],
    "confidence": 0.0-1.0
}}

Focus on facts relevant to: {objective}
"""

    GENERATE_QUESTIONS_PROMPT = """Based on this document understanding, generate follow-up questions.

## Current Understanding:
{understanding}

## Questions Already Asked:
{asked_questions}

## Exploration Objective: {objective}

Generate 3-5 NEW questions that would help achieve the objective.
Focus on:
- Clarifying ambiguous statements
- Finding evidence for claims
- Resolving apparent contradictions
- Tracing unclear references

Return JSON array:
[
    {{"text": "Question text", "type": "clarification|evidence|contradiction|reference", "priority": 0.0-1.0}}
]
"""

    TRACE_REFERENCE_PROMPT = """You need to trace a reference to its source.

## Reference Found:
Source document: {source_document}
Reference text: "{reference_text}"
Points to: {target_description}

## Available Documents:
{available_documents}

## Search Context:
{context}

Find where this reference points to. Return JSON:
{{
    "resolved": true|false,
    "target_document": "document ID if found",
    "target_location": "section/chunk description",
    "resolution_notes": "How you resolved it or why you couldn't",
    "confidence": 0.0-1.0
}}
"""

    SYNTHESIZE_PROMPT = """Synthesize understanding across multiple document chunks.

## Exploration Objective: {objective}

## Chunk Understandings:
{understandings}

## Insights Gathered:
{insights}

Create a synthesized understanding. Return JSON:
{{
    "summary": "Overall synthesis (2-3 paragraphs)",
    "key_findings": [
        {{"title": "...", "description": "...", "confidence": 0.0-1.0, "evidence": ["chunk_ids..."]}}
    ],
    "document_relationships": [["doc1", "relation", "doc2"], ...],
    "contradictions": [
        {{"statement1": "...", "source1": "...", "statement2": "...", "source2": "..."}}
    ],
    "gaps": ["Knowledge gaps that remain"],
    "confidence": 0.0-1.0
}}
"""

    VERIFY_INSIGHT_PROMPT = """Verify whether this insight is accurate based on the evidence.

## Insight to Verify:
Title: {title}
Description: {description}
Claimed evidence: {evidence}

## Full Context:
{context}

Determine if this insight is:
1. VERIFIED - Evidence strongly supports it
2. DISPUTED - Evidence contradicts it
3. UNCERTAIN - Insufficient evidence

Return JSON:
{{
    "verdict": "verified|disputed|uncertain",
    "reasoning": "Your reasoning",
    "supporting_evidence": ["Evidence that supports"],
    "contradicting_evidence": ["Evidence that contradicts"],
    "confidence": 0.0-1.0
}}
"""

    def __init__(
        self,
        name: str,
        model: str = "claude-sonnet-4",
        role: AgentRole = "analyst",
        timeout: int = 120,
        config: ExplorationConfig | None = None,
        **kwargs,
    ):
        """Initialize exploration agent.

        Args:
            name: Agent identifier
            model: Model to use (claude-sonnet-4, gpt-5.3-codex, etc.)
            role: Agent role (explorer, verifier)
            timeout: Operation timeout in seconds
            config: Exploration configuration
            **kwargs: Additional CLIAgent arguments
        """
        super().__init__(name=name, model=model, role=role, timeout=timeout, **kwargs)
        self.config = config or ExplorationConfig()

    async def read_chunk(
        self,
        chunk: DocumentChunk,
        objective: str,
        prior_context: list[Insight] = None,
        mode: ExplorationMode = ExplorationMode.DEEP_READ,
    ) -> ChunkUnderstanding:
        """Read a document chunk and extract understanding.

        Args:
            chunk: The document chunk to read
            objective: The exploration objective
            prior_context: Previously gathered insights for context
            mode: Exploration mode (deep_read, scan, etc.)

        Returns:
            Structured understanding of the chunk
        """
        # Format prior context
        context_str = ""
        if prior_context:
            context_str = "\n".join(
                f"- {insight.title}: {insight.description[:100]}..."
                for insight in prior_context[:5]
            )

        # Build prompt
        prompt = self.READ_CHUNK_PROMPT.format(
            document_id=chunk.document_id if hasattr(chunk, "document_id") else "unknown",
            chunk_id=chunk.id if hasattr(chunk, "id") else "unknown",
            objective=objective,
            prior_context=context_str or "None yet",
            content=chunk.content,
        )

        # Generate response
        try:
            response = await self.generate(prompt)
            data = self._parse_json_response(response)

            # Parse references
            references = []
            for ref_data in data.get("references", []):
                references.append(
                    Reference(
                        source_document=(
                            chunk.document_id if hasattr(chunk, "document_id") else "unknown"
                        ),
                        source_chunk=chunk.id if hasattr(chunk, "id") else "unknown",
                        source_text=ref_data.get("text", ""),
                        target_description=ref_data.get("target", ""),
                    )
                )

            return ChunkUnderstanding(
                chunk_id=chunk.id if hasattr(chunk, "id") else "unknown",
                document_id=chunk.document_id if hasattr(chunk, "document_id") else "unknown",
                summary=data.get("summary", ""),
                key_facts=data.get("key_facts", [])[: self.config.max_facts_per_chunk],
                entities=data.get("entities", []) if self.config.extract_entities else [],
                relationships=(
                    [tuple(r) for r in data.get("relationships", [])]
                    if self.config.extract_relationships
                    else []
                ),
                references_found=references[: self.config.max_references_per_chunk],
                questions_raised=data.get("questions", [])[: self.config.max_questions_per_chunk],
                confidence=data.get("confidence", 0.5),
            )
        except (ValueError, KeyError, TypeError, RuntimeError) as e:
            logger.warning("[%s] Failed to parse chunk understanding: %s", self.name, e)
            return ChunkUnderstanding(
                chunk_id=chunk.id if hasattr(chunk, "id") else "unknown",
                document_id=chunk.document_id if hasattr(chunk, "document_id") else "unknown",
                summary=f"Error reading chunk: {e}",
                confidence=0.0,
            )

    async def generate_questions(
        self,
        understanding: ChunkUnderstanding,
        objective: str,
        asked_questions: list[Question] = None,
    ) -> list[Question]:
        """Generate follow-up questions based on current understanding.

        Args:
            understanding: Current chunk understanding
            objective: Exploration objective
            asked_questions: Questions already asked (to avoid duplicates)

        Returns:
            List of new questions to investigate
        """
        # Format understanding
        understanding_str = f"""
Summary: {understanding.summary}
Key facts: {", ".join(understanding.key_facts[:5])}
Questions from chunk: {", ".join(understanding.questions_raised[:3])}
Confidence: {understanding.confidence}
"""

        # Format asked questions
        asked_str = "None yet"
        if asked_questions:
            asked_str = "\n".join(f"- {q.text}" for q in asked_questions[:10])

        prompt = self.GENERATE_QUESTIONS_PROMPT.format(
            understanding=understanding_str,
            asked_questions=asked_str,
            objective=objective,
        )

        try:
            response = await self.generate(prompt)
            data = self._parse_json_response(response)

            questions = []
            for q_data in data[: self.config.max_questions_per_chunk]:
                questions.append(
                    Question(
                        text=q_data.get("text", ""),
                        question_type=q_data.get("type", "clarification"),
                        priority=q_data.get("priority", 0.5),
                        source_chunk=understanding.chunk_id,
                    )
                )
            return questions
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.warning("[%s] Failed to generate questions: %s", self.name, e)
            return []

    async def trace_reference(
        self,
        reference: Reference,
        available_documents: list[str],
        context: str = "",
    ) -> Reference:
        """Trace a reference to its source location.

        Args:
            reference: The reference to trace
            available_documents: List of available document IDs
            context: Additional context for resolution

        Returns:
            Updated reference with resolution information
        """
        prompt = self.TRACE_REFERENCE_PROMPT.format(
            source_document=reference.source_document,
            reference_text=reference.source_text,
            target_description=reference.target_description,
            available_documents=", ".join(available_documents),
            context=context or "None provided",
        )

        try:
            response = await self.generate(prompt)
            data = self._parse_json_response(response)

            reference.resolved = data.get("resolved", False)
            reference.target_document = data.get("target_document")
            reference.target_chunk = data.get("target_location")
            reference.resolution_notes = data.get("resolution_notes", "")
            return reference
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.warning("[%s] Failed to trace reference: %s", self.name, e)
            reference.resolution_notes = f"Error: {e}"
            return reference

    async def synthesize(
        self,
        understandings: list[ChunkUnderstanding],
        insights: list[Insight],
        objective: str,
    ) -> SynthesizedUnderstanding:
        """Synthesize understanding across multiple chunks.

        Args:
            understandings: List of chunk understandings
            insights: List of insights gathered
            objective: Exploration objective

        Returns:
            Synthesized cross-document understanding
        """
        # Format understandings
        understandings_str = "\n\n".join(
            f"[{u.document_id}:{u.chunk_id}]\n{u.summary}\nFacts: {', '.join(u.key_facts[:3])}"
            for u in understandings[:10]
        )

        # Format insights
        insights_str = "\n".join(
            f"- {i.title}: {i.description[:100]}... (confidence: {i.confidence})"
            for i in insights[:10]
        )

        prompt = self.SYNTHESIZE_PROMPT.format(
            objective=objective,
            understandings=understandings_str or "None yet",
            insights=insights_str or "None yet",
        )

        try:
            response = await self.generate(prompt)
            data = self._parse_json_response(response)

            # Parse key findings into Insights
            key_findings = []
            for finding in data.get("key_findings", []):
                key_findings.append(
                    Insight(
                        title=finding.get("title", ""),
                        description=finding.get("description", ""),
                        confidence=finding.get("confidence", 0.5),
                        evidence_chunks=finding.get("evidence", []),
                        category="finding",
                    )
                )

            return SynthesizedUnderstanding(
                summary=data.get("summary", ""),
                key_findings=key_findings,
                document_relationships=[tuple(r) for r in data.get("document_relationships", [])],
                contradictions=data.get("contradictions", []),
                gaps=data.get("gaps", []),
                confidence=data.get("confidence", 0.5),
            )
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.warning("[%s] Failed to synthesize: %s", self.name, e)
            return SynthesizedUnderstanding(
                summary=f"Error synthesizing: {e}",
                confidence=0.0,
            )

    async def verify_insight(
        self,
        insight: Insight,
        context: str,
    ) -> dict[str, Any]:
        """Verify an insight against available evidence.

        Args:
            insight: The insight to verify
            context: Document context for verification

        Returns:
            Verification result with verdict and reasoning
        """
        prompt = self.VERIFY_INSIGHT_PROMPT.format(
            title=insight.title,
            description=insight.description,
            evidence=", ".join(insight.evidence_chunks),
            context=context,
        )

        try:
            response = await self.generate(prompt)
            data = self._parse_json_response(response)
            return {
                "verdict": data.get("verdict", "uncertain"),
                "reasoning": data.get("reasoning", ""),
                "supporting_evidence": data.get("supporting_evidence", []),
                "contradicting_evidence": data.get("contradicting_evidence", []),
                "confidence": data.get("confidence", 0.5),
            }
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.warning("[%s] Failed to verify insight: %s", self.name, e)
            return {
                "verdict": "uncertain",
                "reasoning": f"Error: {e}",
                "confidence": 0.0,
            }

    def _parse_json_response(self, response: str) -> Any:
        """Parse JSON from agent response.

        Handles common issues like markdown code blocks and trailing text.
        """
        # Remove markdown code blocks
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        elif response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()

        # Try to find JSON in the response
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from text
            import re

            json_match = re.search(r"[\[{].*[\]}]", response, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError as e:
                    logger.debug("Failed to parse JSON data: %s", e)
            raise ValueError(f"Could not parse JSON from response: {response[:200]}...")


class VerifierAgent(ExplorationAgent):
    """Agent specialized for verifying exploration findings.

    Uses adversarial prompting to challenge findings and ensure accuracy.
    """

    def __init__(
        self,
        name: str = "verifier",
        model: str = "gpt-4-turbo",
        **kwargs,
    ):
        super().__init__(name=name, model=model, role="critic", **kwargs)
        self.system_prompt = """You are a critical verifier. Your job is to:
1. Challenge claims and findings
2. Look for contradictions and errors
3. Demand evidence for assertions
4. Rate confidence accurately (don't over-estimate)

Be skeptical but fair. Accept findings only with strong evidence."""

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response using the verifier's skeptical perspective.

        Uses OpenRouter fallback mechanism for API-based generation.
        """
        full_prompt = self._build_full_prompt(prompt, context)
        # Prepend system prompt for verifier behavior
        verifier_prompt = f"{self.system_prompt}\n\n{full_prompt}"
        return await self._generate_with_fallback(
            ["echo", "Using API fallback"],  # Dummy command to trigger fallback
            verifier_prompt,
            context,
        )
