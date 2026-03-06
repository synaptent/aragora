"""
Stream event types and data classes.

Defines the types of events emitted during debates and nomic loop execution,
along with the dataclasses for representing events and audience messages.

This module is part of the shared events layer, accessible to all packages
(CLI, debate, memory, server) without creating circular dependencies.
"""

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass


class StreamEventType(Enum):
    """Types of events emitted during debates and nomic loop execution."""

    # Debate events
    DEBATE_START = "debate_start"
    ROUND_START = "round_start"
    AGENT_MESSAGE = "agent_message"
    CRITIQUE = "critique"
    VOTE = "vote"
    CONSENSUS = "consensus"
    SYNTHESIS = "synthesis"  # Explicit synthesis event for guaranteed delivery
    DEBATE_END = "debate_end"

    # Quick preview events (shown in first 5 seconds of debate initialization)
    QUICK_CLASSIFICATION = "quick_classification"  # Haiku classification of question type/domain
    AGENT_PREVIEW = "agent_preview"  # Agent roles, stances, and brief descriptions
    CONTEXT_PREVIEW = "context_preview"  # Pulse/trending summary, research status

    # Token streaming events (for real-time response display)
    TOKEN_START = "token_start"  # noqa: S105 -- enum value (agent begins generating response)
    TOKEN_DELTA = "token_delta"  # noqa: S105 -- enum value (incremental tokens received)
    TOKEN_END = "token_end"  # noqa: S105 -- enum value (agent finished generating response)

    # Reasoning visibility events (real-time agent reasoning)
    AGENT_THINKING = "agent_thinking"  # Agent's internal reasoning chain
    AGENT_REASONING = "agent_reasoning"  # Partial chain-of-thought streaming
    AGENT_EVIDENCE = "agent_evidence"  # Sources/references being considered
    AGENT_CONFIDENCE = "agent_confidence"  # Current confidence level update

    # Live debate experience (argument quality + intervention)
    ARGUMENT_STRENGTH = "argument_strength"  # Real-time quality scores for arguments
    CRUX_IDENTIFIED = "crux_identified"  # Key disagreement point detected
    INTERVENTION_WINDOW = "intervention_window"  # User can interject at this point
    INTERVENTION_APPLIED = "intervention_applied"  # User intervention was applied

    # Nomic loop events
    CYCLE_START = "cycle_start"
    CYCLE_END = "cycle_end"
    PHASE_START = "phase_start"
    PHASE_END = "phase_end"
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"
    TASK_RETRY = "task_retry"
    VERIFICATION_START = "verification_start"
    VERIFICATION_RESULT = "verification_result"
    COMMIT = "commit"
    BACKUP_CREATED = "backup_created"
    BACKUP_RESTORED = "backup_restored"
    ERROR = "error"
    PHASE_TIMEOUT = "phase_timeout"  # Phase timed out - sent to WebSocket clients
    LOG_MESSAGE = "log_message"

    # Multi-loop management events
    LOOP_REGISTER = "loop_register"  # New loop instance started
    LOOP_UNREGISTER = "loop_unregister"  # Loop instance ended
    LOOP_LIST = "loop_list"  # List of active loops (sent on connect)

    # Audience participation events
    USER_VOTE = "user_vote"  # Audience member voted
    USER_SUGGESTION = "user_suggestion"  # Audience member submitted suggestion
    AUDIENCE_SUMMARY = "audience_summary"  # Clustered audience input summary
    AUDIENCE_METRICS = "audience_metrics"  # Vote counts, histograms, conviction distribution
    AUDIENCE_DRAIN = "audience_drain"  # Audience events processed by arena

    # Memory/learning events
    MEMORY_RECALL = "memory_recall"  # Historical context retrieved from memory
    INSIGHT_EXTRACTED = "insight_extracted"  # New insight extracted from debate
    MEMORY_STORED = "memory_stored"  # New memory stored in ContinuumMemory
    MEMORY_RETRIEVED = "memory_retrieved"  # Memory retrieved from any tier

    # Ranking/leaderboard events (debate consensus feature)
    MATCH_RECORDED = "match_recorded"  # ELO match recorded, leaderboard updated
    LEADERBOARD_UPDATE = "leaderboard_update"  # Periodic leaderboard snapshot
    GROUNDED_VERDICT = "grounded_verdict"  # Evidence-backed verdict with citations
    MOMENT_DETECTED = "moment_detected"  # Significant narrative moment detected
    AGENT_ELO_UPDATED = "agent_elo_updated"  # Individual agent ELO change
    AGENT_CALIBRATION_CHANGED = "agent_calibration_changed"  # Agent calibration updated
    AGENT_FALLBACK_TRIGGERED = "agent_fallback_triggered"  # Agent fell back to alternate provider

    # Knowledge Mound events (cross-pollination)
    KNOWLEDGE_INDEXED = "knowledge_indexed"  # Document/chunk indexed in Knowledge Mound
    KNOWLEDGE_QUERIED = "knowledge_queried"  # Knowledge Mound semantic search executed
    MOUND_UPDATED = "mound_updated"  # Knowledge Mound structure updated
    KNOWLEDGE_STALE = "knowledge_stale"  # Knowledge item detected as stale
    KM_BATCH = "km_batch"  # Batched KM events for efficient WebSocket transmission

    # Belief Network events (bidirectional KM integration)
    BELIEF_CONVERGED = "belief_converged"  # Belief network propagation converged
    CRUX_DETECTED = "crux_detected"  # Crux claim identified in debate

    # KM Adapter sync events (bidirectional tracking)
    KM_ADAPTER_FORWARD_SYNC = "km_adapter_forward_sync"  # Data synced to KM from source
    KM_ADAPTER_REVERSE_QUERY = "km_adapter_reverse_query"  # Reverse flow query executed
    KM_ADAPTER_VALIDATION = "km_adapter_validation"  # KM validation feedback received

    # RLM events (bidirectional KM integration)
    RLM_COMPRESSION_COMPLETE = "rlm_compression_complete"  # RLM finished compression

    # Claim verification events
    CLAIM_VERIFICATION_RESULT = "claim_verification_result"  # Claim verification outcome
    FORMAL_VERIFICATION_RESULT = (
        "formal_verification_result"  # Formal proof verification (Lean4/Z3)
    )

    # Memory tier events
    MEMORY_TIER_PROMOTION = "memory_tier_promotion"  # Memory promoted to faster tier
    MEMORY_TIER_DEMOTION = "memory_tier_demotion"  # Memory demoted to slower tier

    # Graph debate events (branching/merging visualization)
    GRAPH_NODE_ADDED = "graph_node_added"  # New node added to debate graph
    GRAPH_BRANCH_CREATED = "graph_branch_created"  # New branch created
    GRAPH_BRANCH_MERGED = "graph_branch_merged"  # Branches merged/synthesized

    # Argument cartography events
    GRAPH_UPDATE = "graph_update"  # ArgumentCartographer graph state update

    # Position tracking events
    FLIP_DETECTED = "flip_detected"  # Agent position reversal detected

    # Feature integration events (data flow from backends to panels)
    TRAIT_EMERGED = "trait_emerged"  # New agent trait detected by PersonaLaboratory
    RISK_WARNING = "risk_warning"  # Domain risk identified
    EVIDENCE_FOUND = "evidence_found"  # Supporting evidence collected
    CALIBRATION_UPDATE = "calibration_update"  # Confidence calibration updated
    GENESIS_EVOLUTION = "genesis_evolution"  # Agent population evolved
    TRAINING_DATA_EXPORTED = "training_data_exported"  # Training data emitted for Tinker
    SELECTION_FEEDBACK = "selection_feedback"  # Selection weight adjustments from performance
    MEMORY_COORDINATION = "memory_coordination"  # Coordinated memory transaction status

    # Rhetorical analysis events
    RHETORICAL_OBSERVATION = "rhetorical_observation"  # Rhetorical pattern detected

    # Trickster/hollow consensus events
    HOLLOW_CONSENSUS = "hollow_consensus"  # Hollow consensus detected
    TRICKSTER_INTERVENTION = "trickster_intervention"  # Trickster challenge injected

    # Human intervention breakpoint events
    BREAKPOINT = "breakpoint"  # Human intervention breakpoint triggered
    BREAKPOINT_RESOLVED = "breakpoint_resolved"  # Breakpoint resolved with guidance

    # Inbox → Debate trigger events
    INBOX_ITEM_FLAGGED = "inbox_item_flagged"  # High-priority inbox item flagged for debate
    INBOX_DEBATE_TRIGGERED = "inbox_debate_triggered"  # Auto-debate triggered from inbox item
    INBOX_DEBATE_COMPLETED = "inbox_debate_completed"  # Debate result linked back to inbox item

    # Progress/heartbeat events (for detecting stalled debates)
    HEARTBEAT = "heartbeat"  # Periodic progress indicator
    AGENT_ERROR = "agent_error"  # Agent encountered an error (but debate continues)
    PHASE_PROGRESS = "phase_progress"  # Progress within a phase (e.g., 3/8 agents complete)

    # Mood/sentiment events (Real-Time Debate Drama)
    MOOD_DETECTED = "mood_detected"  # Agent emotional state analyzed
    MOOD_SHIFT = "mood_shift"  # Significant mood change detected
    DEBATE_ENERGY = "debate_energy"  # Overall debate intensity level

    # Capability probe events (Adversarial Testing)
    PROBE_START = "probe_start"  # Probe session started for agent
    PROBE_RESULT = "probe_result"  # Individual probe result
    PROBE_COMPLETE = "probe_complete"  # All probes complete, report ready

    # Deep Audit events (Intensive Multi-Round Analysis)
    AUDIT_START = "audit_start"  # Deep audit session started
    AUDIT_ROUND = "audit_round"  # Audit round completed (1-6)
    AUDIT_FINDING = "audit_finding"  # Individual finding discovered
    AUDIT_CROSS_EXAM = "audit_cross_exam"  # Cross-examination phase
    AUDIT_VERDICT = "audit_verdict"  # Final audit verdict ready

    # Telemetry events (Cognitive Firewall)
    TELEMETRY_THOUGHT = "telemetry_thought"  # Agent thought process (may be redacted)
    TELEMETRY_CAPABILITY = "telemetry_capability"  # Agent capability verification result
    TELEMETRY_REDACTION = "telemetry_redaction"  # Content was redacted (notification only)
    TELEMETRY_DIAGNOSTIC = "telemetry_diagnostic"  # Internal diagnostic info (dev only)

    # Gauntlet events (Adversarial Validation)
    GAUNTLET_START = "gauntlet_start"  # Gauntlet stress-test started
    GAUNTLET_PHASE = "gauntlet_phase"  # Phase transition (redteam, probe, audit, etc.)
    GAUNTLET_AGENT_ACTIVE = "gauntlet_agent_active"  # Agent became active
    GAUNTLET_ATTACK = "gauntlet_attack"  # Red-team attack executed
    GAUNTLET_FINDING = "gauntlet_finding"  # New finding discovered
    GAUNTLET_PROBE = "gauntlet_probe"  # Capability probe result
    GAUNTLET_VERIFICATION = "gauntlet_verification"  # Formal verification result
    GAUNTLET_RISK = "gauntlet_risk"  # Risk assessment update
    GAUNTLET_PROGRESS = "gauntlet_progress"  # Progress update (percentage, etc.)
    GAUNTLET_VERDICT = "gauntlet_verdict"  # Final verdict determined
    GAUNTLET_COMPLETE = "gauntlet_complete"  # Gauntlet stress-test completed

    # Phase 2: Workflow Builder Events
    WORKFLOW_CREATED = "workflow_created"  # New workflow definition created
    WORKFLOW_UPDATED = "workflow_updated"  # Workflow definition updated
    WORKFLOW_DELETED = "workflow_deleted"  # Workflow definition deleted

    WORKFLOW_START = "workflow_start"  # Workflow execution started
    WORKFLOW_STEP_START = "workflow_step_start"  # Step execution started
    WORKFLOW_STEP_PROGRESS = "workflow_step_progress"  # Step progress update
    WORKFLOW_STEP_COMPLETE = "workflow_step_complete"  # Step execution completed
    WORKFLOW_STEP_FAILED = "workflow_step_failed"  # Step execution failed
    WORKFLOW_STEP_SKIPPED = "workflow_step_skipped"  # Step was skipped

    WORKFLOW_TRANSITION = "workflow_transition"  # Transitioning between steps
    WORKFLOW_CHECKPOINT = "workflow_checkpoint"  # Checkpoint created
    WORKFLOW_RESUMED = "workflow_resumed"  # Workflow resumed from checkpoint

    WORKFLOW_HUMAN_APPROVAL_REQUIRED = "workflow_human_approval_required"  # Waiting for human
    WORKFLOW_HUMAN_APPROVAL_RECEIVED = "workflow_human_approval_received"  # Human responded
    WORKFLOW_HUMAN_APPROVAL_TIMEOUT = "workflow_human_approval_timeout"  # Approval timed out

    WORKFLOW_DEBATE_START = "workflow_debate_start"  # Debate step starting
    WORKFLOW_DEBATE_ROUND = "workflow_debate_round"  # Debate round completed
    WORKFLOW_DEBATE_COMPLETE = "workflow_debate_complete"  # Debate step finished

    WORKFLOW_MEMORY_READ = "workflow_memory_read"  # Knowledge Mound query executed
    WORKFLOW_MEMORY_WRITE = "workflow_memory_write"  # Knowledge stored in Mound

    WORKFLOW_COMPLETE = "workflow_complete"  # Workflow execution completed
    WORKFLOW_FAILED = "workflow_failed"  # Workflow execution failed
    WORKFLOW_TERMINATED = "workflow_terminated"  # Workflow manually terminated

    WORKFLOW_METRICS = "workflow_metrics"  # Workflow execution metrics

    # Voice/Transcription events (Speech-to-Text and Text-to-Speech)
    VOICE_START = "voice_start"  # Voice input session started
    VOICE_CHUNK = "voice_chunk"  # Audio chunk received
    VOICE_TRANSCRIPT = "voice_transcript"  # Real-time transcription segment
    VOICE_END = "voice_end"  # Voice input session ended
    VOICE_RESPONSE = "voice_response"  # TTS audio response being sent to client
    VOICE_RESPONSE_START = "voice_response_start"  # TTS synthesis started
    VOICE_RESPONSE_END = "voice_response_end"  # TTS synthesis completed
    TRANSCRIPTION_QUEUED = "transcription_queued"  # File transcription job queued
    TRANSCRIPTION_STARTED = "transcription_started"  # Transcription processing began
    TRANSCRIPTION_PROGRESS = "transcription_progress"  # Transcription progress update
    TRANSCRIPTION_COMPLETE = "transcription_complete"  # Transcription finished
    TRANSCRIPTION_FAILED = "transcription_failed"  # Transcription error

    # Phase 5: Autonomous Operations Events
    # 5.1 Approval Flow events
    APPROVAL_REQUESTED = "approval_requested"  # New approval request created
    APPROVAL_APPROVED = "approval_approved"  # Request was approved
    APPROVAL_REJECTED = "approval_rejected"  # Request was rejected
    APPROVAL_TIMEOUT = "approval_timeout"  # Request timed out
    APPROVAL_AUTO_APPROVED = "approval_auto_approved"  # Low-risk auto-approved

    # 5.1 Rollback events
    ROLLBACK_POINT_CREATED = "rollback_point_created"  # Backup point created
    ROLLBACK_EXECUTED = "rollback_executed"  # Rollback was performed

    # 5.1 Verification events (improvement cycle)
    IMPROVEMENT_CYCLE_START = "improvement_cycle_start"  # Self-improvement started
    IMPROVEMENT_CYCLE_VERIFIED = "improvement_cycle_verified"  # Verification passed
    IMPROVEMENT_CYCLE_FAILED = "improvement_cycle_failed"  # Verification failed
    IMPROVEMENT_CYCLE_COMPLETE = "improvement_cycle_complete"  # Cycle completed

    # 5.2 Continuous Learning events
    LEARNING_EVENT = "learning_event"  # Generic learning event
    ELO_UPDATED = "elo_updated"  # ELO rating changed
    PATTERN_DISCOVERED = "pattern_discovered"  # New pattern extracted
    CALIBRATION_UPDATED = "calibration_updated"  # Agent calibration changed
    KNOWLEDGE_DECAYED = "knowledge_decayed"  # Knowledge confidence reduced

    # 5.3 Alert events
    ALERT_CREATED = "alert_created"  # New alert generated
    ALERT_ACKNOWLEDGED = "alert_acknowledged"  # Alert was acknowledged
    ALERT_RESOLVED = "alert_resolved"  # Alert was resolved
    ALERT_ESCALATED = "alert_escalated"  # Alert severity escalated

    # 5.3 Trigger events
    TRIGGER_ADDED = "trigger_added"  # Scheduled trigger added
    TRIGGER_REMOVED = "trigger_removed"  # Scheduled trigger removed
    TRIGGER_EXECUTED = "trigger_executed"  # Scheduled trigger fired
    TRIGGER_SCHEDULER_START = "trigger_scheduler_start"  # Scheduler started
    TRIGGER_SCHEDULER_STOP = "trigger_scheduler_stop"  # Scheduler stopped

    # 5.3 Monitoring events
    TREND_DETECTED = "trend_detected"  # Trend detected in metrics
    ANOMALY_DETECTED = "anomaly_detected"  # Anomaly detected in metrics
    METRIC_RECORDED = "metric_recorded"  # Metric value recorded

    # Explainability Events (real-time explanation generation)
    EXPLAINABILITY_STARTED = "explainability_started"  # Explanation generation started
    EXPLAINABILITY_FACTORS = "explainability_factors"  # Contributing factors computed
    EXPLAINABILITY_COUNTERFACTUAL = "explainability_counterfactual"  # Counterfactual generated
    EXPLAINABILITY_PROVENANCE = "explainability_provenance"  # Provenance chain built
    EXPLAINABILITY_NARRATIVE = "explainability_narrative"  # Narrative explanation ready
    EXPLAINABILITY_COMPLETE = "explainability_complete"  # Full explanation ready

    # Argument Map Events (visualization graph updates)
    ARGUMENT_MAP_UPDATED = "argument_map_updated"  # Debate argument graph exported

    # Compliance Artifact Events
    COMPLIANCE_ARTIFACT_GENERATED = (
        "compliance_artifact_generated"  # EU AI Act artifact bundle generated
    )

    # Notification-driven Events
    BUDGET_ALERT = "budget_alert"  # Budget threshold exceeded
    COST_ANOMALY = "cost_anomaly"  # Cost deviation detected
    COMPLIANCE_FINDING = "compliance_finding"  # Compliance finding reported

    # Workflow Template Events (template execution updates)
    TEMPLATE_EXECUTION_STARTED = "template_execution_started"  # Template execution began
    TEMPLATE_EXECUTION_PROGRESS = "template_execution_progress"  # Execution progress update
    TEMPLATE_EXECUTION_STEP = "template_execution_step"  # Individual step completed
    TEMPLATE_EXECUTION_COMPLETE = "template_execution_complete"  # Execution finished
    TEMPLATE_EXECUTION_FAILED = "template_execution_failed"  # Execution failed
    TEMPLATE_INSTANTIATED = "template_instantiated"  # New template created from pattern

    # Gauntlet Receipt Events (receipt lifecycle updates)
    RECEIPT_GENERATED = "receipt_generated"  # New receipt generated
    RECEIPT_VERIFIED = "receipt_verified"  # Receipt integrity verified
    RECEIPT_EXPORTED = "receipt_exported"  # Receipt exported to format
    RECEIPT_SHARED = "receipt_shared"  # Receipt share link created
    RECEIPT_INTEGRITY_FAILED = "receipt_integrity_failed"  # Receipt integrity check failed

    # KM Resilience Events (real-time resilience status)
    KM_CIRCUIT_BREAKER_STATE = "km_circuit_breaker_state"  # Circuit breaker state changed
    KM_RETRY_EXHAUSTED = "km_retry_exhausted"  # All retries exhausted
    KM_CACHE_INVALIDATED = "km_cache_invalidated"  # Cache was invalidated
    KM_INTEGRITY_ERROR = "km_integrity_error"  # Integrity error detected

    # Connector Webhook Events (external service notifications)
    CONNECTOR_WEBHOOK_RECEIVED = "connector_webhook_received"  # Webhook received from connector
    CONNECTOR_DOCUSIGN_ENVELOPE_STATUS = (
        "connector_docusign_envelope_status"  # DocuSign envelope status changed
    )
    CONNECTOR_DOCUSIGN_ENVELOPE_COMPLETED = (
        "connector_docusign_envelope_completed"  # Envelope fully signed
    )
    CONNECTOR_PAGERDUTY_INCIDENT = "connector_pagerduty_incident"  # PagerDuty incident event
    CONNECTOR_PAGERDUTY_INCIDENT_RESOLVED = (
        "connector_pagerduty_incident_resolved"  # Incident resolved
    )
    CONNECTOR_PLAID_TRANSACTION_SYNC = "connector_plaid_transaction_sync"  # New transactions synced
    CONNECTOR_QBO_WEBHOOK = "connector_qbo_webhook"  # QuickBooks webhook received

    # TestFixer Events (autonomous test repair)
    TESTFIXER_FAILURE_DETECTED = "testfixer_failure_detected"  # Test failure discovered
    TESTFIXER_ANALYSIS_COMPLETE = "testfixer_analysis_complete"  # Failure analysis done
    TESTFIXER_FIX_PROPOSED = "testfixer_fix_proposed"  # Fix candidate generated
    TESTFIXER_FIX_APPLIED = "testfixer_fix_applied"  # Fix applied to codebase
    TESTFIXER_FIX_REVERTED = "testfixer_fix_reverted"  # Fix reverted (failed verification)
    TESTFIXER_ITERATION_COMPLETE = "testfixer_iteration_complete"  # One fix cycle done
    TESTFIXER_LOOP_COMPLETE = "testfixer_loop_complete"  # Full fix loop finished
    TESTFIXER_PATTERN_LEARNED = "testfixer_pattern_learned"  # New fix pattern learned

    # Genesis/Fractal Events (agent evolution and recursive debates)
    AGENT_BIRTH = "agent_birth"  # New agent genome created
    AGENT_DEATH = "agent_death"  # Agent genome retired from population
    AGENT_EVOLUTION = "agent_evolution"  # Agent genome mutated/evolved
    FRACTAL_START = "fractal_start"  # Fractal sub-debate spawned
    FRACTAL_SPAWN = "fractal_spawn"  # Child fractal created from parent
    FRACTAL_MERGE = "fractal_merge"  # Fractal results merged back to parent
    FRACTAL_COMPLETE = "fractal_complete"  # Fractal debate chain completed
    LINEAGE_BRANCH = "lineage_branch"  # Agent lineage tree branched
    POPULATION_UPDATE = "population_update"  # Population state changed
    GENERATION_ADVANCE = "generation_advance"  # New generation in evolutionary cycle
    TENSION_DETECTED = "tension_detected"  # Unresolved tension found in debate
    TENSION_RESOLVED = "tension_resolved"  # Previously detected tension resolved

    # RLM/Query Events (recursive language model processing)
    QUERY_START = "query_start"  # RLM query processing started
    QUERY_COMPLETE = "query_complete"  # RLM query processing finished
    NODE_EXAMINED = "node_examined"  # RLM node visited during traversal
    LEVEL_ENTERED = "level_entered"  # RLM entered new recursion level
    FINAL_ANSWER = "final_answer"  # RLM produced final answer
    PARTIAL_ANSWER = "partial_answer"  # RLM intermediate partial result
    ITERATION_START = "iteration_start"  # RLM iteration loop started
    ITERATION_COMPLETE = "iteration_complete"  # RLM iteration loop completed

    # Confidence/Feedback Events (real-time confidence tracking)
    CONFIDENCE_UPDATE = "confidence_update"  # Debate confidence score changed
    FEEDBACK_GENERATED = "feedback_generated"  # Post-debate feedback produced

    # Meta-Learning Events (self-tuning hyperparameters)
    META_LEARNING_EVALUATED = "meta_learning_evaluated"  # Learning efficiency evaluated
    META_LEARNING_ADJUSTED = "meta_learning_adjusted"  # Hyperparameters auto-tuned

    # Pipeline Execution Events (decision plan lifecycle)
    PLAN_EXECUTING = "plan_executing"  # Plan execution started
    PLAN_COMPLETED = "plan_completed"  # Plan execution completed successfully
    PLAN_FAILED = "plan_failed"  # Plan execution failed

    # TestFixer Batch Events (batch processing lifecycle)
    TESTFIXER_BATCH_STARTED = "testfixer_batch_started"  # Batch fix loop started
    TESTFIXER_BATCH_COMPLETE = "testfixer_batch_complete"  # Batch fix loop finished
    TESTFIXER_BUG_CHECK = "testfixer_bug_check"  # Post-fix bug check result
    TESTFIXER_IMPACT_CHECK = "testfixer_impact_check"  # Cross-test impact analysis result

    # Pipeline (Idea-to-Execution) Events
    PIPELINE_STARTED = "pipeline_started"  # Full pipeline run started
    PIPELINE_STAGE_STARTED = "pipeline_stage_started"  # Individual stage began
    PIPELINE_STAGE_COMPLETED = "pipeline_stage_completed"  # Individual stage finished
    PIPELINE_GRAPH_UPDATED = "pipeline_graph_updated"  # React Flow graph update
    PIPELINE_GOAL_EXTRACTED = "pipeline_goal_extracted"  # Goal extracted from debate
    PIPELINE_WORKFLOW_GENERATED = "pipeline_workflow_generated"  # Workflow generated
    PIPELINE_STEP_PROGRESS = "pipeline_step_progress"  # Step-level progress
    PIPELINE_NODE_ADDED = "pipeline_node_added"  # Individual node added to canvas
    PIPELINE_TRANSITION_PENDING = "pipeline_transition_pending"  # Human approval gate
    PIPELINE_COMPLETED = "pipeline_completed"  # Full pipeline completed
    PIPELINE_FAILED = "pipeline_failed"  # Pipeline failed

    # Interrogation events (decomposition → questioning → crystallization)
    INTERROGATION_STARTED = "interrogation_started"  # Interrogation session started
    INTERROGATION_QUESTION = "interrogation_question"  # Question posed to agent
    INTERROGATION_ANSWER = "interrogation_answer"  # Agent answered a question
    INTERROGATION_CRYSTALLIZED = "interrogation_crystallized"  # Insights crystallized

    # Notification delivery events (unified telemetry for Epic #293)
    NOTIFICATION_SENT = "notification_sent"  # Notification delivered successfully
    NOTIFICATION_FAILED = "notification_failed"  # Notification delivery failed
    NOTIFICATION_RETRIED = "notification_retried"  # Failed notification retried
    NOTIFICATION_CIRCUIT_OPENED = "notification_circuit_opened"  # Channel circuit breaker opened
    NOTIFICATION_CIRCUIT_CLOSED = "notification_circuit_closed"  # Channel circuit breaker closed


@dataclass
class StreamEvent:
    """A single event in the debate stream.

    Includes distributed tracing fields for correlation across services,
    consistent with DebateEvent in aragora.debate.event_bus.
    """

    type: StreamEventType
    data: dict
    timestamp: float = field(default_factory=time.time)
    round: int = 0
    agent: str = ""
    loop_id: str = ""  # For multi-loop tracking
    seq: int = 0  # Global sequence number for ordering
    agent_seq: int = 0  # Per-agent sequence number for token ordering
    task_id: str = ""  # Unique task identifier for concurrent outputs from same agent
    # Distributed tracing fields for correlation across services
    correlation_id: str = ""  # Links related events across service boundaries
    trace_id: str = ""  # OpenTelemetry-style trace identifier
    span_id: str = ""  # Current operation span

    def __post_init__(self) -> None:
        """Auto-populate tracing fields from current context if not provided."""
        if not self.correlation_id and not self.trace_id:
            try:
                # Lazy import to avoid circular dependency with server layer
                from aragora.server.middleware.tracing import get_trace_id, get_span_id

                trace_id = get_trace_id()
                if isinstance(trace_id, str) and trace_id:
                    self.trace_id = trace_id
                    span_id = get_span_id()
                    if isinstance(span_id, str) and span_id:
                        self.span_id = span_id
                    self.correlation_id = self.trace_id
            except ImportError:
                pass

    def to_dict(self) -> dict:
        result = {
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp,
            "round": self.round,
            "agent": self.agent,
            "seq": self.seq,
            "agent_seq": self.agent_seq,
        }
        if self.loop_id:
            result["loop_id"] = self.loop_id
        if self.task_id:
            result["task_id"] = self.task_id
        # Include tracing fields if present
        if self.correlation_id:
            result["correlation_id"] = self.correlation_id
        if self.trace_id:
            result["trace_id"] = self.trace_id
        if self.span_id:
            result["span_id"] = self.span_id
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class AudienceMessage:
    """A message from an audience member (vote or suggestion)."""

    type: str  # "vote" or "suggestion"
    loop_id: str  # Associated nomic loop
    payload: dict  # Message content (e.g., {"choice": "option1"} for votes)
    timestamp: float = field(default_factory=time.time)
    user_id: str = ""  # Optional user identifier


@runtime_checkable
class EventEmitter(Protocol):
    """Abstract interface for event emitters.

    This protocol allows different layers to depend on the emitter
    interface without depending on specific implementations like
    SyncEventEmitter in the server layer.
    """

    def emit(self, event: StreamEvent) -> None:
        """Emit an event."""
        ...

    def set_loop_id(self, loop_id: str) -> None:
        """Set the current loop ID for emitted events."""
        ...


__all__ = [
    "StreamEventType",
    "StreamEvent",
    "AudienceMessage",
    "EventEmitter",
]
