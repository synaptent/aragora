# aragora/debate/taint.py
"""
Trust-tier taint analysis for debate proposals.

G2 security roadmap item: taint propagates from untrusted context sources
(retrieved docs, config files) through proposals into the consensus receipt.
"""

from __future__ import annotations

from typing import Any


def compute_taint_analysis(
    tainted_proposals: list[str],
    total_proposals: int,
    taint_sources: list[str] | None = None,
) -> dict[str, Any]:
    """Compute taint level and recommendation from proposal taint data.

    Args:
        tainted_proposals: List of proposal IDs with trust_tier != "standard"
        total_proposals: Total number of proposals in the debate
        taint_sources: Optional list of taint source strings for the report

    Returns:
        Dict with taint_level, tainted_proposal_count, trust_score, sources,
        recommendation.
    """
    taint_count = len(tainted_proposals)
    sources = taint_sources or []

    if total_proposals == 0:
        trust_score = 1.0
    else:
        trust_score = (total_proposals - taint_count) / total_proposals

    if trust_score >= 0.9:
        taint_level = "none"
        recommendation = "proceed"
    elif trust_score >= 0.7:
        taint_level = "low"
        recommendation = "proceed"
    elif trust_score >= 0.5:
        taint_level = "medium"
        recommendation = "review before acting"
    else:
        taint_level = "high"
        recommendation = "human approval required"

    return {
        "taint_level": taint_level,
        "tainted_proposal_count": taint_count,
        "trust_score": round(trust_score, 4),
        "sources": sources,
        "recommendation": recommendation,
    }


def mark_proposal_tainted(
    metadata: dict[str, Any],
) -> tuple[str, str | None]:
    """Derive trust_tier and taint_source from a proposal's metadata dict.

    Returns:
        (trust_tier, taint_source) — "untrusted" if metadata indicates
        retrieved or config-file context, "standard" otherwise.
    """
    source_type = metadata.get("source_type", "")
    if source_type in ("retrieved", "config_file", "memory_file"):
        return "untrusted", source_type
    return "standard", None
