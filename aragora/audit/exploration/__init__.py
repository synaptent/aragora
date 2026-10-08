"""Agent-driven iterative document exploration.

This module provides Claude Code/Codex-style iterative exploration for
document auditing. Instead of static pattern matching, agents read documents,
ask follow-up questions, trace references, and build understanding iteratively.

Key Components:
    - DocumentExplorer: Main orchestrator for exploration sessions
    - ExplorationSession: Tracks exploration state and insights
    - ExplorationAgent: CLIAgent extension for document exploration
    - ExplorationMemory: ContinuumMemory adapter for cross-session learning
    - QueryGenerator: Generates follow-up questions based on understanding gaps

Example:
    >>> from aragora.audit.exploration import DocumentExplorer, ExplorationAgent
    >>> explorer = DocumentExplorer(
    ...     agents=[ExplorationAgent(name="claude", model="claude-opus-5")],
    ... )
    >>> result = await explorer.explore(
    ...     documents=["doc1.pdf", "doc2.md"],
    ...     objective="Find security vulnerabilities",
    ... )
    >>> for insight in result.insights:
    ...     print(f"{insight.title}: {insight.description}")
"""

from aragora.audit.exploration.session import (
    ExplorationSession,
    ExplorationPhase,
    ExplorationResult,
    Insight,
    Question,
    Reference,
    ChunkUnderstanding,
    SynthesizedUnderstanding,
)
from aragora.audit.exploration.memory import (
    ExplorationMemory,
    MemoryTier,
)
from aragora.audit.exploration.agents import (
    ExplorationAgent,
    ExplorationMode,
)
from aragora.audit.exploration.explorer import DocumentExplorer
from aragora.audit.exploration.query_gen import QueryGenerator

__all__ = [
    # Core classes
    "DocumentExplorer",
    "ExplorationSession",
    "ExplorationAgent",
    "ExplorationMemory",
    "QueryGenerator",
    # Data types
    "ExplorationPhase",
    "ExplorationResult",
    "ExplorationMode",
    "MemoryTier",
    "Insight",
    "Question",
    "Reference",
    "ChunkUnderstanding",
    "SynthesizedUnderstanding",
]
