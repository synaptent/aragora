"""
Prometheus Metrics Export for Aragora.

Generates Prometheus-format metrics output from all metric modules.
"""

from __future__ import annotations

import logging

from .agents import AGENT_LATENCY, AGENT_REQUESTS, AGENT_TOKENS
from .api import ACTIVE_DEBATES, API_LATENCY, API_REQUESTS, WEBSOCKET_CONNECTIONS
from .billing import (
    BILLING_REVENUE,
    PAYMENT_FAILURES,
    SUBSCRIPTION_ACTIVE,
    SUBSCRIPTION_EVENTS,
    USAGE_DEBATES,
    USAGE_TOKENS,
)
from .debate import (
    AGENT_ERRORS,
    AGENT_PARTICIPATION,
    CIRCUIT_BREAKERS_OPEN,
    CONSENSUS_QUALITY,
    CONSENSUS_REACHED,
    DEBATE_CONFIDENCE,
    DEBATE_DURATION,
    DEBATES_TOTAL,
    EXECUTION_GATE_BLOCK_REASONS,
    EXECUTION_GATE_CONTEXT_TAINT,
    EXECUTION_GATE_CORRELATED_RISK,
    EXECUTION_GATE_DECISIONS,
    EXECUTION_GATE_MODEL_FAMILY_DIVERSITY,
    EXECUTION_GATE_PROVIDER_DIVERSITY,
    EXECUTION_GATE_RECEIPT_VERIFICATION,
    LAST_DEBATE_TIMESTAMP,
)
from .knowledge_mound import (
    KNOWLEDGE_ACCESS_GRANTS,
    KNOWLEDGE_FEDERATION_LATENCY,
    KNOWLEDGE_FEDERATION_NODES,
    KNOWLEDGE_FEDERATION_REGIONS,
    KNOWLEDGE_FEDERATION_SYNCS,
    KNOWLEDGE_GLOBAL_FACTS,
    KNOWLEDGE_GLOBAL_QUERIES,
    KNOWLEDGE_SHARED_ITEMS,
    KNOWLEDGE_SHARES,
    KNOWLEDGE_VISIBILITY_CHANGES,
)
from .security import AUTH_FAILURES, RATE_LIMIT_HITS, SECURITY_VIOLATIONS

logger = logging.getLogger(__name__)


def _format_labels(labels: dict) -> str:
    """Format labels for Prometheus output."""
    if not labels:
        return ""
    parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
    return "{" + ",".join(parts) + "}"


def generate_metrics() -> str:
    """Generate Prometheus-format metrics output.

    This combines:
    1. Built-in server metrics (billing, API, agent)
    2. Nomic loop metrics
    3. Observability metrics from aragora.observability.metrics (if available)
    """
    lines = []

    # All metrics to export
    counters = [
        SUBSCRIPTION_EVENTS,
        USAGE_DEBATES,
        USAGE_TOKENS,
        BILLING_REVENUE,
        PAYMENT_FAILURES,
        API_REQUESTS,
        AGENT_REQUESTS,
        AGENT_TOKENS,
        # Security metrics
        AUTH_FAILURES,
        RATE_LIMIT_HITS,
        SECURITY_VIOLATIONS,
        # Business metrics
        DEBATES_TOTAL,
        CONSENSUS_REACHED,
        AGENT_ERRORS,
        AGENT_PARTICIPATION,
        EXECUTION_GATE_DECISIONS,
        EXECUTION_GATE_BLOCK_REASONS,
        EXECUTION_GATE_RECEIPT_VERIFICATION,
        EXECUTION_GATE_CONTEXT_TAINT,
        EXECUTION_GATE_CORRELATED_RISK,
        # Knowledge Mound metrics
        KNOWLEDGE_VISIBILITY_CHANGES,
        KNOWLEDGE_ACCESS_GRANTS,
        KNOWLEDGE_SHARES,
        KNOWLEDGE_GLOBAL_FACTS,
        KNOWLEDGE_GLOBAL_QUERIES,
        KNOWLEDGE_FEDERATION_SYNCS,
        KNOWLEDGE_FEDERATION_NODES,
    ]

    gauges = [
        SUBSCRIPTION_ACTIVE,
        ACTIVE_DEBATES,
        WEBSOCKET_CONNECTIONS,
        # Business metrics
        CONSENSUS_QUALITY,
        CIRCUIT_BREAKERS_OPEN,
        LAST_DEBATE_TIMESTAMP,
        # Knowledge Mound metrics
        KNOWLEDGE_SHARED_ITEMS,
        KNOWLEDGE_FEDERATION_REGIONS,
    ]

    histograms = [
        API_LATENCY,
        AGENT_LATENCY,
        # Business metrics
        DEBATE_DURATION,
        DEBATE_CONFIDENCE,
        EXECUTION_GATE_PROVIDER_DIVERSITY,
        EXECUTION_GATE_MODEL_FAMILY_DIVERSITY,
        # Knowledge Mound metrics
        KNOWLEDGE_FEDERATION_LATENCY,
    ]

    # Add nomic loop metrics if available
    try:
        from aragora.nomic.metrics import (
            NOMIC_CIRCUIT_BREAKERS_OPEN,
            NOMIC_CURRENT_PHASE,
            NOMIC_CYCLES_IN_PROGRESS,
            NOMIC_CYCLES_TOTAL,
            NOMIC_ERRORS,
            NOMIC_PHASE_DURATION,
            NOMIC_PHASE_LAST_TRANSITION,
            NOMIC_PHASE_TRANSITIONS,
            NOMIC_RECOVERY_DECISIONS,
            NOMIC_RETRIES,
        )

        counters.extend(
            [
                NOMIC_PHASE_TRANSITIONS,
                NOMIC_CYCLES_TOTAL,
                NOMIC_ERRORS,
                NOMIC_RECOVERY_DECISIONS,
                NOMIC_RETRIES,
            ]
        )
        gauges.extend(
            [
                NOMIC_CURRENT_PHASE,
                NOMIC_CYCLES_IN_PROGRESS,
                NOMIC_PHASE_LAST_TRANSITION,
                NOMIC_CIRCUIT_BREAKERS_OPEN,
            ]
        )
        histograms.append(NOMIC_PHASE_DURATION)
    except ImportError:
        # Nomic metrics not available
        pass

    # Export counters
    for counter in counters:
        lines.append(f"# HELP {counter.name} {counter.help}")
        lines.append(f"# TYPE {counter.name} counter")
        for labels, value in counter.collect():
            lines.append(f"{counter.name}{_format_labels(labels)} {value}")
        lines.append("")

    # Export gauges
    for gauge in gauges:
        lines.append(f"# HELP {gauge.name} {gauge.help}")
        lines.append(f"# TYPE {gauge.name} gauge")
        for labels, value in gauge.collect():
            lines.append(f"{gauge.name}{_format_labels(labels)} {value}")
        lines.append("")

    # Export histograms
    for histogram in histograms:
        lines.append(f"# HELP {histogram.name} {histogram.help}")
        lines.append(f"# TYPE {histogram.name} histogram")
        for labels, data in histogram.collect():
            for bucket, count in data["buckets"]:
                bucket_labels = {**labels, "le": str(bucket)}
                lines.append(f"{histogram.name}_bucket{_format_labels(bucket_labels)} {count}")
            inf_labels = {**labels, "le": "+Inf"}
            lines.append(f"{histogram.name}_bucket{_format_labels(inf_labels)} {data['count']}")
            lines.append(f"{histogram.name}_sum{_format_labels(labels)} {data['sum']}")
            lines.append(f"{histogram.name}_count{_format_labels(labels)} {data['count']}")
        lines.append("")

    # Include observability metrics if prometheus_client is available
    try:
        from prometheus_client import REGISTRY, generate_latest

        observability_metrics = generate_latest(REGISTRY).decode("utf-8")
        if observability_metrics.strip():
            lines.append("# Observability metrics (from prometheus_client)")
            lines.append(observability_metrics)
    except ImportError:
        # prometheus_client not installed, skip observability metrics
        pass
    except (ValueError, TypeError) as e:
        # Metric value or type errors during collection
        logger.warning("Error collecting observability metrics (value/type): %s", e)
        lines.append(f"# Error collecting observability metrics: {e}")
    except OSError as e:
        # I/O errors during metric collection
        logger.warning("Error collecting observability metrics (I/O): %s", e)
        lines.append(f"# Error collecting observability metrics: {e}")
    except RuntimeError as e:
        # Runtime errors (e.g., registry state issues)
        logger.warning("Error collecting observability metrics (runtime): %s", e)
        lines.append(f"# Error collecting observability metrics: {e}")

    return "\n".join(lines)


__all__ = [
    "generate_metrics",
]
