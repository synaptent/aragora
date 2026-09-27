"""
Control Plane metrics for Aragora server.

Extracted from prometheus.py for maintainability.
Provides metrics for task scheduling, agent registry, and queue management.
"""

from aragora.observability.prometheus import (
    PROMETHEUS_AVAILABLE,
    _simple_metrics,
)

# Import metric definitions when prometheus is available
if PROMETHEUS_AVAILABLE:
    from aragora.observability.prometheus import (
        CONTROL_PLANE_AGENT_HEALTH,
        CONTROL_PLANE_AGENT_LATENCY,
        CONTROL_PLANE_AGENTS_REGISTERED,
        CONTROL_PLANE_CLAIM_LATENCY,
        CONTROL_PLANE_DEAD_LETTER_QUEUE,
        CONTROL_PLANE_QUEUE_DEPTH,
        CONTROL_PLANE_TASK_DURATION,
        CONTROL_PLANE_TASK_RETRIES,
        CONTROL_PLANE_TASK_STATUS,
        CONTROL_PLANE_TASKS_TOTAL,
        # Deliberation metrics
        DELIBERATION_DURATION,
        DELIBERATION_SLA_COMPLIANCE,
        DELIBERATION_CONSENSUS_CONFIDENCE,
        DELIBERATION_ROUNDS,
        DELIBERATION_AGENTS,
        DELIBERATION_TOTAL,
        AGENT_UTILIZATION,
        POLICY_DECISIONS,
    )


def record_control_plane_task_submitted(task_type: str, priority: str) -> None:
    """Record a task submitted to the control plane.

    Args:
        task_type: Type of task (e.g., debate, document_processing, audit)
        priority: Task priority (low, normal, high, urgent)
    """
    if PROMETHEUS_AVAILABLE:
        CONTROL_PLANE_TASKS_TOTAL.labels(task_type=task_type, priority=priority).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_control_plane_tasks_total",
            {"task_type": task_type, "priority": priority},
        )


def record_control_plane_task_status(status: str, count: int) -> None:
    """Record the count of tasks by status.

    Args:
        status: Task status (pending, running, completed, failed, cancelled)
        count: Number of tasks in this status
    """
    if PROMETHEUS_AVAILABLE:
        CONTROL_PLANE_TASK_STATUS.labels(status=status).set(count)
    else:
        _simple_metrics.set_gauge(
            "aragora_control_plane_task_status_count",
            count,
            {"status": status},
        )


def record_control_plane_task_completed(
    task_type: str, outcome: str, duration_seconds: float
) -> None:
    """Record a task completion.

    Args:
        task_type: Type of task
        outcome: Task outcome (completed, failed, timeout)
        duration_seconds: Time to complete the task
    """
    if PROMETHEUS_AVAILABLE:
        CONTROL_PLANE_TASK_DURATION.labels(task_type=task_type, outcome=outcome).observe(
            duration_seconds
        )
    else:
        _simple_metrics.observe_histogram(
            "aragora_control_plane_task_duration_seconds",
            duration_seconds,
            {"task_type": task_type, "outcome": outcome},
        )


def record_control_plane_queue_depth(priority: str, depth: int) -> None:
    """Record the queue depth by priority.

    Args:
        priority: Task priority
        depth: Number of tasks in queue
    """
    if PROMETHEUS_AVAILABLE:
        CONTROL_PLANE_QUEUE_DEPTH.labels(priority=priority).set(depth)
    else:
        _simple_metrics.set_gauge(
            "aragora_control_plane_queue_depth",
            depth,
            {"priority": priority},
        )


def record_control_plane_agents(status: str, count: int) -> None:
    """Record the count of agents by status.

    Args:
        status: Agent status (available, busy, offline)
        count: Number of agents in this status
    """
    if PROMETHEUS_AVAILABLE:
        CONTROL_PLANE_AGENTS_REGISTERED.labels(status=status).set(count)
    else:
        _simple_metrics.set_gauge(
            "aragora_control_plane_agents_registered",
            count,
            {"status": status},
        )


def record_control_plane_agent_health(agent_id: str, health_value: int) -> None:
    """Record agent health status.

    Args:
        agent_id: Agent identifier
        health_value: Health value (0=unhealthy, 1=degraded, 2=healthy)
    """
    if PROMETHEUS_AVAILABLE:
        CONTROL_PLANE_AGENT_HEALTH.labels(agent_id=agent_id).set(health_value)
    else:
        _simple_metrics.set_gauge(
            "aragora_control_plane_agent_health",
            health_value,
            {"agent_id": agent_id},
        )


def record_control_plane_agent_latency(agent_id: str, latency_seconds: float) -> None:
    """Record agent health check latency.

    Args:
        agent_id: Agent identifier
        latency_seconds: Health check latency in seconds
    """
    if PROMETHEUS_AVAILABLE:
        CONTROL_PLANE_AGENT_LATENCY.labels(agent_id=agent_id).observe(latency_seconds)
    else:
        _simple_metrics.observe_histogram(
            "aragora_control_plane_agent_latency_seconds",
            latency_seconds,
            {"agent_id": agent_id},
        )


def record_control_plane_task_retry(task_type: str, reason: str) -> None:
    """Record a task retry.

    Args:
        task_type: Type of task being retried
        reason: Retry reason (timeout, error, capability_mismatch)
    """
    if PROMETHEUS_AVAILABLE:
        CONTROL_PLANE_TASK_RETRIES.labels(task_type=task_type, reason=reason).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_control_plane_task_retries_total",
            {"task_type": task_type, "reason": reason},
        )


def record_control_plane_dead_letter_queue(size: int) -> None:
    """Record the size of the dead letter queue.

    Args:
        size: Number of tasks in dead letter queue
    """
    if PROMETHEUS_AVAILABLE:
        CONTROL_PLANE_DEAD_LETTER_QUEUE.set(size)
    else:
        _simple_metrics.set_gauge("aragora_control_plane_dead_letter_queue_size", size)


def record_control_plane_claim_latency(priority: str, latency_seconds: float) -> None:
    """Record task claim latency.

    Args:
        priority: Task priority
        latency_seconds: Time to claim the task
    """
    if PROMETHEUS_AVAILABLE:
        CONTROL_PLANE_CLAIM_LATENCY.labels(priority=priority).observe(latency_seconds)
    else:
        _simple_metrics.observe_histogram(
            "aragora_control_plane_claim_latency_seconds",
            latency_seconds,
            {"priority": priority},
        )


# =============================================================================
# Deliberation Metrics Recording Functions
# =============================================================================


def record_deliberation_complete(
    duration_seconds: float,
    status: str,
    consensus_reached: bool,
    confidence: float,
    round_count: int,
    agent_count: int,
) -> None:
    """Record deliberation completion metrics.

    Args:
        duration_seconds: Total deliberation time
        status: Outcome status (completed, failed, timeout)
        consensus_reached: Whether consensus was achieved
        confidence: Consensus confidence score (0.0-1.0)
        round_count: Number of rounds executed
        agent_count: Number of participating agents
    """
    consensus_str = "yes" if consensus_reached else "no"
    if status == "completed":
        outcome = "consensus" if consensus_reached else "no_consensus"
    elif status in {"failed", "timeout"}:
        outcome = status
    else:
        outcome = status
    if PROMETHEUS_AVAILABLE:
        DELIBERATION_DURATION.labels(status=status, consensus_reached=consensus_str).observe(
            duration_seconds
        )
        DELIBERATION_CONSENSUS_CONFIDENCE.observe(confidence)
        DELIBERATION_ROUNDS.labels(outcome=outcome).observe(round_count)
        DELIBERATION_AGENTS.observe(agent_count)
        DELIBERATION_TOTAL.labels(outcome=outcome).inc()
    else:
        _simple_metrics.observe_histogram(
            "aragora_deliberation_duration_seconds",
            duration_seconds,
            {"status": status, "consensus_reached": consensus_str},
        )
        _simple_metrics.observe_histogram(
            "aragora_consensus_confidence",
            confidence,
        )
        _simple_metrics.observe_histogram(
            "aragora_deliberation_rounds",
            round_count,
            {"outcome": outcome},
        )
        _simple_metrics.observe_histogram(
            "aragora_deliberation_agents",
            agent_count,
        )
        _simple_metrics.inc_counter(
            "aragora_deliberation_total",
            {"outcome": outcome},
        )


def record_deliberation_sla(level: str) -> None:
    """Record SLA compliance level.

    Args:
        level: SLA compliance level (compliant, warning, critical, violated)
    """
    if PROMETHEUS_AVAILABLE:
        DELIBERATION_SLA_COMPLIANCE.labels(level=level).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_deliberation_sla_total",
            {"level": level},
        )


def record_agent_utilization(agent_id: str, utilization_ratio: float) -> None:
    """Record agent utilization ratio.

    Args:
        agent_id: Agent identifier
        utilization_ratio: Busy time / total time ratio (0.0-1.0)
    """
    if PROMETHEUS_AVAILABLE:
        AGENT_UTILIZATION.labels(agent_id=agent_id).set(utilization_ratio)
    else:
        _simple_metrics.set_gauge(
            "aragora_agent_utilization_ratio",
            utilization_ratio,
            {"agent_id": agent_id},
        )


def record_policy_decision(decision: str, policy_type: str) -> None:
    """Record policy decision outcome.

    Args:
        decision: Decision outcome (allow, deny, warn)
        policy_type: Type of policy evaluated (agent_restriction, region_restriction, etc.)
    """
    if PROMETHEUS_AVAILABLE:
        POLICY_DECISIONS.labels(decision=decision, policy_type=policy_type).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_policy_decisions_total",
            {"decision": decision, "policy_type": policy_type},
        )


__all__ = [
    # Control plane task metrics
    "record_control_plane_task_submitted",
    "record_control_plane_task_status",
    "record_control_plane_task_completed",
    "record_control_plane_queue_depth",
    "record_control_plane_agents",
    "record_control_plane_agent_health",
    "record_control_plane_agent_latency",
    "record_control_plane_task_retry",
    "record_control_plane_dead_letter_queue",
    "record_control_plane_claim_latency",
    # Deliberation metrics
    "record_deliberation_complete",
    "record_deliberation_sla",
    "record_agent_utilization",
    "record_policy_decision",
]
