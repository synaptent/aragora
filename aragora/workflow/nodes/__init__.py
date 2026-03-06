"""
Workflow Node Types for the Visual Workflow Builder.

Phase 2 step implementations for the Enterprise Control Plane:
- HumanCheckpointStep: Human approval gates with checklists
- MemoryReadStep / MemoryWriteStep: Knowledge Mound integration
- DebateStep: Execute Aragora debates as workflow steps
- DecisionStep: Conditional branching based on expressions
- TaskStep: Generic task execution with flexible configuration
- ConnectorStep: First-class connector integration (100+ connectors)
- NomicLoopStep: Self-improvement cycle execution
- KnowledgePipelineStep: Document ingestion and processing
- GauntletStep: Adversarial validation and compliance checking
- KnowledgePruningStep: Automatic knowledge maintenance (pruning, dedup, decay)
- ContentExtractionStep: Structured data extraction (entities, relationships, schemas)
- HarnessStep: External code analysis harness integration (Claude Code, Codex)
- CreateTicketStep / SendSummaryStep: Action fulfillment for debate results
"""

from aragora.workflow.nodes.human_checkpoint import HumanCheckpointStep
from aragora.workflow.nodes.memory import MemoryReadStep, MemoryWriteStep
from aragora.workflow.nodes.debate import DebateStep
from aragora.workflow.nodes.decision import DecisionStep
from aragora.workflow.nodes.task import TaskStep
from aragora.workflow.nodes.connector import (
    ConnectorStep,
    ConnectorMetadata,
    ConnectorOperation,
    create_connector,
    get_connector_metadata,
    list_connectors,
    register_connector,
)
from aragora.workflow.nodes.nomic import NomicLoopStep
from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep
from aragora.workflow.nodes.gauntlet import GauntletStep
from aragora.workflow.nodes.knowledge_pruning import (
    KnowledgePruningStep,
    KnowledgeDedupStep,
    ConfidenceDecayStep,
)
from aragora.workflow.nodes.openclaw import OpenClawActionStep, OpenClawSessionStep
from aragora.workflow.nodes.implementation import ImplementationStep, VerificationStep
from aragora.workflow.nodes.computer_use import ComputerUseTaskStep
from aragora.workflow.nodes.content_extraction import ContentExtractionStep
from aragora.workflow.nodes.harness import HarnessStep
from aragora.workflow.nodes.code_implementation import CodeImplementationTask
from aragora.workflow.nodes.action_fulfillment import CreateTicketStep, SendSummaryStep

from aragora.workflow.step import WorkflowStep


def register_step_type(type_name: str, step_class: type[WorkflowStep]) -> None:
    """Register a step type with the global workflow engine.

    This is a convenience function that delegates to WorkflowEngine.register_step_type().

    Args:
        type_name: Name for the step type
        step_class: Class implementing WorkflowStep
    """
    from aragora.workflow.engine import get_workflow_engine

    engine = get_workflow_engine()
    engine.register_step_type(type_name, step_class)


__all__ = [
    "HumanCheckpointStep",
    "MemoryReadStep",
    "MemoryWriteStep",
    "DebateStep",
    "DecisionStep",
    "TaskStep",
    "ConnectorStep",
    "ConnectorMetadata",
    "ConnectorOperation",
    "create_connector",
    "get_connector_metadata",
    "list_connectors",
    "register_connector",
    "NomicLoopStep",
    "KnowledgePipelineStep",
    "GauntletStep",
    "KnowledgePruningStep",
    "KnowledgeDedupStep",
    "ConfidenceDecayStep",
    "OpenClawActionStep",
    "OpenClawSessionStep",
    "ComputerUseTaskStep",
    "ContentExtractionStep",
    "ImplementationStep",
    "VerificationStep",
    "HarnessStep",
    "CodeImplementationTask",
    "CreateTicketStep",
    "SendSummaryStep",
    "register_step_type",
]
