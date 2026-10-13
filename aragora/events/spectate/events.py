"""
Centralized event type constants for Spectator Mode.
Prevents typos and ensures consistency across the codebase.
"""


class SpectatorEvents:
    """String constants for all spectator event types."""

    # Debate lifecycle
    DEBATE_START = "debate_start"
    DEBATE_END = "debate_end"

    # Round lifecycle
    ROUND_START = "round_start"
    ROUND_END = "round_end"

    # Agent actions
    PROPOSAL = "proposal"
    CRITIQUE = "critique"
    REFINE = "refine"
    VOTE = "vote"
    JUDGE = "judge"

    # Consensus/convergence
    CONSENSUS = "consensus"
    CONVERGENCE = "convergence"
    CONVERGED = "converged"
    EARLY_STOP = "early_stop"

    # Memory/Learning
    MEMORY_RECALL = "memory_recall"

    # Human-in-the-loop breakpoints
    BREAKPOINT = "breakpoint"
    BREAKPOINT_RESOLVED = "breakpoint_resolved"

    # Pipeline lifecycle
    PIPELINE_STARTED = "pipeline.started"
    PIPELINE_STAGE_STARTED = "pipeline.stage_started"
    PIPELINE_STAGE_COMPLETED = "pipeline.stage_completed"
    PIPELINE_COMPLETED = "pipeline.completed"
    PIPELINE_FAILED = "pipeline.failed"

    # Self-improvement lifecycle
    ORCHESTRATION_STARTED = "orchestration_started"
    ORCHESTRATION_COMPLETED = "orchestration_completed"
    COORDINATED_STARTED = "coordinated_started"
    PLANNING_COMPLETED = "planning_completed"
    GOAL_DECOMPOSED = "goal_decomposed"

    # Assignment lifecycle
    ASSIGNMENT_STARTED = "assignment_started"
    ASSIGNMENT_COMPLETED = "assignment_completed"
    ASSIGNMENT_FAILED = "assignment_failed"

    # Worktree and merge
    WORKTREE_CREATED = "worktree_created"
    MERGE_STARTED = "merge_started"
    MERGE_COMPLETED = "merge_completed"
    AUTO_COMMITTED = "auto_committed"

    # Validation gates
    GAUNTLET_STARTED = "gauntlet_started"
    GAUNTLET_RESULT = "gauntlet_result"
    GAUNTLET_RETRY = "gauntlet_retry"
    OUTPUT_VALIDATED = "output_validated"
    REVIEW_GATE_RESULT = "review_gate_result"
    SANDBOX_VALIDATED = "sandbox_validated"
    MERGE_GATE_RESULT = "merge_gate_result"

    # Budget and metrics
    BUDGET_UPDATE = "budget_update"
    METRICS_DELTA = "metrics_delta"

    # Agent coordination
    WORK_STOLEN = "work_stolen"
    CROSS_REVIEW_COMPLETED = "cross_review_completed"
    DEBUG_LOOP_FIXED = "debug_loop_fixed"
    COMPUTER_USE_STARTED = "computer_use_started"
    COMPUTER_USE_COMPLETED = "computer_use_completed"

    # Knowledge and feedback
    FEEDBACK_RECORDED = "feedback_recorded"
    KM_CONTRADICTIONS_DETECTED = "km_contradictions_detected"
    REGRESSION_DETECTED = "regression_detected"

    # Pipeline agent execution (Mission Control)
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    AGENT_PROGRESS = "agent_progress"
    PIPELINE_AGENT_ASSIGNED = "pipeline_agent_assigned"
    PIPELINE_AGENT_COMPLETED = "pipeline_agent_completed"
    PIPELINE_AGENT_FAILED = "pipeline_agent_failed"
    DIFF_PREVIEW = "diff_preview"

    # Live debate experience (real-time reasoning + intervention)
    AGENT_THINKING = "agent_thinking"
    AGENT_REASONING = "agent_reasoning"
    ARGUMENT_STRENGTH = "argument_strength"
    CRUX_IDENTIFIED = "crux_identified"
    INTERVENTION_WINDOW = "intervention_window"
    INTERVENTION_APPLIED = "intervention_applied"

    # System
    SYSTEM = "system"
    ERROR = "error"


# Icon and color mappings for visual styling
# Format: (emoji_icon, ansi_color_code)
EVENT_STYLES: dict[str, tuple[str, str]] = {
    SpectatorEvents.DEBATE_START: ("🎬", "\033[95m"),  # Magenta
    SpectatorEvents.DEBATE_END: ("🏁", "\033[95m"),
    SpectatorEvents.ROUND_START: ("⏱️", "\033[96m"),  # Cyan
    SpectatorEvents.ROUND_END: ("✓", "\033[96m"),
    SpectatorEvents.PROPOSAL: ("💡", "\033[94m"),  # Blue
    SpectatorEvents.CRITIQUE: ("🔍", "\033[91m"),  # Red
    SpectatorEvents.REFINE: ("✨", "\033[94m"),
    SpectatorEvents.VOTE: ("🗳️", "\033[93m"),  # Yellow
    SpectatorEvents.JUDGE: ("⚖️", "\033[93m"),
    SpectatorEvents.CONSENSUS: ("🤝", "\033[92m"),  # Green
    SpectatorEvents.CONVERGENCE: ("📊", "\033[92m"),
    SpectatorEvents.CONVERGED: ("🎉", "\033[92m"),
    SpectatorEvents.EARLY_STOP: ("⏹️", "\033[93m"),  # Yellow - early termination
    SpectatorEvents.MEMORY_RECALL: ("🧠", "\033[94m"),  # Blue - memory retrieval
    SpectatorEvents.BREAKPOINT: ("⚠️", "\033[33m"),  # Yellow/orange - needs attention
    SpectatorEvents.BREAKPOINT_RESOLVED: ("✅", "\033[32m"),  # Green - resolved
    SpectatorEvents.PIPELINE_STARTED: ("🚀", "\033[95m"),  # Magenta - pipeline kickoff
    SpectatorEvents.PIPELINE_STAGE_STARTED: ("▶️", "\033[96m"),  # Cyan - stage begin
    SpectatorEvents.PIPELINE_STAGE_COMPLETED: ("✅", "\033[92m"),  # Green - stage done
    SpectatorEvents.PIPELINE_COMPLETED: ("🏁", "\033[92m"),  # Green - pipeline done
    SpectatorEvents.PIPELINE_FAILED: ("❌", "\033[91m"),  # Red - pipeline failure
    # Self-improvement lifecycle
    SpectatorEvents.ORCHESTRATION_STARTED: ("🚀", "\033[95m"),  # Magenta
    SpectatorEvents.ORCHESTRATION_COMPLETED: ("🏁", "\033[95m"),
    SpectatorEvents.COORDINATED_STARTED: ("🔀", "\033[95m"),
    SpectatorEvents.PLANNING_COMPLETED: ("📋", "\033[96m"),  # Cyan
    SpectatorEvents.GOAL_DECOMPOSED: ("🧩", "\033[96m"),
    # Assignment lifecycle
    SpectatorEvents.ASSIGNMENT_STARTED: ("▶️", "\033[94m"),  # Blue
    SpectatorEvents.ASSIGNMENT_COMPLETED: ("✅", "\033[92m"),  # Green
    SpectatorEvents.ASSIGNMENT_FAILED: ("❌", "\033[91m"),  # Red
    # Worktree and merge
    SpectatorEvents.WORKTREE_CREATED: ("🌳", "\033[92m"),
    SpectatorEvents.MERGE_STARTED: ("🔗", "\033[93m"),  # Yellow
    SpectatorEvents.MERGE_COMPLETED: ("🔗", "\033[92m"),
    SpectatorEvents.AUTO_COMMITTED: ("💾", "\033[92m"),
    # Validation gates
    SpectatorEvents.GAUNTLET_STARTED: ("🛡️", "\033[93m"),
    SpectatorEvents.GAUNTLET_RESULT: ("🛡️", "\033[92m"),
    SpectatorEvents.GAUNTLET_RETRY: ("🔄", "\033[93m"),
    SpectatorEvents.OUTPUT_VALIDATED: ("🔍", "\033[92m"),
    SpectatorEvents.REVIEW_GATE_RESULT: ("📝", "\033[93m"),
    SpectatorEvents.SANDBOX_VALIDATED: ("📦", "\033[92m"),
    SpectatorEvents.MERGE_GATE_RESULT: ("🚧", "\033[93m"),
    # Budget and metrics
    SpectatorEvents.BUDGET_UPDATE: ("💰", "\033[93m"),
    SpectatorEvents.METRICS_DELTA: ("📊", "\033[96m"),
    # Agent coordination
    SpectatorEvents.WORK_STOLEN: ("🏃", "\033[94m"),
    SpectatorEvents.CROSS_REVIEW_COMPLETED: ("👀", "\033[94m"),
    SpectatorEvents.DEBUG_LOOP_FIXED: ("🔧", "\033[92m"),
    SpectatorEvents.COMPUTER_USE_STARTED: ("🖥️", "\033[96m"),
    SpectatorEvents.COMPUTER_USE_COMPLETED: ("🖥️", "\033[92m"),
    # Knowledge and feedback
    SpectatorEvents.FEEDBACK_RECORDED: ("📝", "\033[92m"),
    SpectatorEvents.KM_CONTRADICTIONS_DETECTED: ("⚡", "\033[91m"),
    SpectatorEvents.REGRESSION_DETECTED: ("📉", "\033[91m"),
    # Pipeline agent execution (Mission Control)
    SpectatorEvents.APPROVAL_REQUESTED: ("🔔", "\033[93m"),  # Yellow - needs attention
    SpectatorEvents.APPROVAL_GRANTED: ("✅", "\033[92m"),  # Green
    SpectatorEvents.APPROVAL_REJECTED: ("🚫", "\033[91m"),  # Red
    SpectatorEvents.AGENT_PROGRESS: ("📊", "\033[96m"),  # Cyan
    SpectatorEvents.PIPELINE_AGENT_ASSIGNED: ("🤖", "\033[94m"),  # Blue
    SpectatorEvents.PIPELINE_AGENT_COMPLETED: ("✅", "\033[92m"),  # Green
    SpectatorEvents.PIPELINE_AGENT_FAILED: ("❌", "\033[91m"),  # Red
    SpectatorEvents.DIFF_PREVIEW: ("📄", "\033[96m"),  # Cyan
    # Live debate experience
    SpectatorEvents.AGENT_THINKING: ("🧠", "\033[96m"),  # Cyan - thinking
    SpectatorEvents.AGENT_REASONING: ("💭", "\033[94m"),  # Blue - reasoning chain
    SpectatorEvents.ARGUMENT_STRENGTH: ("📏", "\033[93m"),  # Yellow - quality score
    SpectatorEvents.CRUX_IDENTIFIED: ("🎯", "\033[91m"),  # Red - key disagreement
    SpectatorEvents.INTERVENTION_WINDOW: ("✋", "\033[33m"),  # Yellow/orange - user can act
    SpectatorEvents.INTERVENTION_APPLIED: ("📌", "\033[92m"),  # Green - applied
    # System
    SpectatorEvents.SYSTEM: ("⚙️", "\033[0m"),
    SpectatorEvents.ERROR: ("❌", "\033[91m"),
}

# ASCII fallbacks for non-UTF8 environments
EVENT_ASCII: dict[str, str] = {
    SpectatorEvents.DEBATE_START: "[START]",
    SpectatorEvents.DEBATE_END: "[END]",
    SpectatorEvents.ROUND_START: "[ROUND]",
    SpectatorEvents.ROUND_END: "[/ROUND]",
    SpectatorEvents.PROPOSAL: "[PROPOSE]",
    SpectatorEvents.CRITIQUE: "[CRITIQUE]",
    SpectatorEvents.REFINE: "[REFINE]",
    SpectatorEvents.VOTE: "[VOTE]",
    SpectatorEvents.JUDGE: "[JUDGE]",
    SpectatorEvents.CONSENSUS: "[CONSENSUS]",
    SpectatorEvents.CONVERGENCE: "[CONVERGE]",
    SpectatorEvents.CONVERGED: "[DONE]",
    SpectatorEvents.EARLY_STOP: "[EARLY_STOP]",
    SpectatorEvents.MEMORY_RECALL: "[MEMORY]",
    SpectatorEvents.BREAKPOINT: "[BREAK]",
    SpectatorEvents.BREAKPOINT_RESOLVED: "[RESOLVED]",
    SpectatorEvents.PIPELINE_STARTED: "[PIPE_START]",
    SpectatorEvents.PIPELINE_STAGE_STARTED: "[STAGE_START]",
    SpectatorEvents.PIPELINE_STAGE_COMPLETED: "[STAGE_DONE]",
    SpectatorEvents.PIPELINE_COMPLETED: "[PIPE_DONE]",
    SpectatorEvents.PIPELINE_FAILED: "[PIPE_FAIL]",
    # Self-improvement lifecycle
    SpectatorEvents.ORCHESTRATION_STARTED: "[ORCH_START]",
    SpectatorEvents.ORCHESTRATION_COMPLETED: "[ORCH_DONE]",
    SpectatorEvents.COORDINATED_STARTED: "[COORD_START]",
    SpectatorEvents.PLANNING_COMPLETED: "[PLAN_DONE]",
    SpectatorEvents.GOAL_DECOMPOSED: "[DECOMPOSED]",
    # Assignment lifecycle
    SpectatorEvents.ASSIGNMENT_STARTED: "[ASSIGN]",
    SpectatorEvents.ASSIGNMENT_COMPLETED: "[ASSIGN_OK]",
    SpectatorEvents.ASSIGNMENT_FAILED: "[ASSIGN_FAIL]",
    # Worktree and merge
    SpectatorEvents.WORKTREE_CREATED: "[WORKTREE]",
    SpectatorEvents.MERGE_STARTED: "[MERGE]",
    SpectatorEvents.MERGE_COMPLETED: "[MERGED]",
    SpectatorEvents.AUTO_COMMITTED: "[COMMIT]",
    # Validation gates
    SpectatorEvents.GAUNTLET_STARTED: "[GAUNTLET]",
    SpectatorEvents.GAUNTLET_RESULT: "[GAUNTLET_OK]",
    SpectatorEvents.GAUNTLET_RETRY: "[GAUNTLET_RETRY]",
    SpectatorEvents.OUTPUT_VALIDATED: "[OUTPUT_OK]",
    SpectatorEvents.REVIEW_GATE_RESULT: "[REVIEW]",
    SpectatorEvents.SANDBOX_VALIDATED: "[SANDBOX]",
    SpectatorEvents.MERGE_GATE_RESULT: "[GATE]",
    # Budget and metrics
    SpectatorEvents.BUDGET_UPDATE: "[BUDGET]",
    SpectatorEvents.METRICS_DELTA: "[METRICS]",
    # Agent coordination
    SpectatorEvents.WORK_STOLEN: "[STEAL]",
    SpectatorEvents.CROSS_REVIEW_COMPLETED: "[XREVIEW]",
    SpectatorEvents.DEBUG_LOOP_FIXED: "[DEBUGFIX]",
    SpectatorEvents.COMPUTER_USE_STARTED: "[CU_START]",
    SpectatorEvents.COMPUTER_USE_COMPLETED: "[CU_DONE]",
    # Knowledge and feedback
    SpectatorEvents.FEEDBACK_RECORDED: "[FEEDBACK]",
    SpectatorEvents.KM_CONTRADICTIONS_DETECTED: "[CONFLICT]",
    SpectatorEvents.REGRESSION_DETECTED: "[REGRESS]",
    # Pipeline agent execution (Mission Control)
    SpectatorEvents.APPROVAL_REQUESTED: "[APPROVE?]",
    SpectatorEvents.APPROVAL_GRANTED: "[APPROVED]",
    SpectatorEvents.APPROVAL_REJECTED: "[REJECTED]",
    SpectatorEvents.AGENT_PROGRESS: "[PROGRESS]",
    SpectatorEvents.PIPELINE_AGENT_ASSIGNED: "[AGENT_ASSIGN]",
    SpectatorEvents.PIPELINE_AGENT_COMPLETED: "[AGENT_DONE]",
    SpectatorEvents.PIPELINE_AGENT_FAILED: "[AGENT_FAIL]",
    SpectatorEvents.DIFF_PREVIEW: "[DIFF]",
    # Live debate experience
    SpectatorEvents.AGENT_THINKING: "[THINKING]",
    SpectatorEvents.AGENT_REASONING: "[REASONING]",
    SpectatorEvents.ARGUMENT_STRENGTH: "[STRENGTH]",
    SpectatorEvents.CRUX_IDENTIFIED: "[CRUX]",
    SpectatorEvents.INTERVENTION_WINDOW: "[INTERVENE?]",
    SpectatorEvents.INTERVENTION_APPLIED: "[INTERVENED]",
    # System
    SpectatorEvents.SYSTEM: "[SYS]",
    SpectatorEvents.ERROR: "[ERR]",
}
