"""
Export functions for Decision Receipts.

Contains the rendering/export logic extracted from the DecisionReceipt class:
- to_markdown -> receipt_to_markdown
- to_html -> receipt_to_html
- to_html_paginated -> receipt_to_html_paginated
- to_sarif -> receipt_to_sarif
- to_csv -> receipt_to_csv

These are called by DecisionReceipt's methods via delegation.
"""

from __future__ import annotations

import hashlib
from html import escape
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .receipt_models import CruxReceipt, DecisionReceipt


def _has_epistemic_limits(receipt: DecisionReceipt) -> bool:
    return bool(
        getattr(receipt, "unverified", None)
        or getattr(receipt, "assumptions", None)
        or getattr(receipt, "falsification", None)
    )


def _render_epistemic_markdown(receipt: DecisionReceipt) -> list[str]:
    if not _has_epistemic_limits(receipt):
        return []
    lines = ["---", "", "## Epistemic Limits", ""]
    if receipt.unverified:
        lines.extend(["### Not verified", ""])
        lines.extend(f"- {item}" for item in receipt.unverified)
        lines.append("")
    if receipt.assumptions:
        lines.extend(["### Assumptions accepted", ""])
        lines.extend(f"- {item}" for item in receipt.assumptions)
        lines.append("")
    if receipt.falsification:
        falsification = receipt.falsification
        lines.extend(["### Falsification check", ""])
        lines.append(f"- **Observation:** {falsification.get('observation', '-')}")
        if falsification.get("owner"):
            lines.append(f"- **Owner:** {falsification['owner']}")
        if falsification.get("source"):
            lines.append(f"- **Source:** {falsification['source']}")
        if falsification.get("check_by"):
            lines.append(f"- **Check by:** {falsification['check_by']}")
        lines.append("")
    return lines


def _render_epistemic_html(receipt: DecisionReceipt) -> str:
    if not _has_epistemic_limits(receipt):
        return ""
    parts = ['<div class="section"><h2>Epistemic Limits</h2>']
    if receipt.unverified:
        parts.append("<h3>Not verified</h3><ul>")
        parts.extend(f"<li>{escape(item)}</li>" for item in receipt.unverified)
        parts.append("</ul>")
    if receipt.assumptions:
        parts.append("<h3>Assumptions accepted</h3><ul>")
        parts.extend(f"<li>{escape(item)}</li>" for item in receipt.assumptions)
        parts.append("</ul>")
    if receipt.falsification:
        falsification = receipt.falsification
        parts.append("<h3>Falsification check</h3>")
        parts.append('<p class="meta">')
        parts.append(
            f"<strong>Observation:</strong> {escape(falsification.get('observation', '-'))}"
        )
        if falsification.get("owner"):
            parts.append(f"<br><strong>Owner:</strong> {escape(falsification['owner'])}")
        if falsification.get("source"):
            parts.append(f"<br><strong>Source:</strong> {escape(falsification['source'])}")
        if falsification.get("check_by"):
            parts.append(f"<br><strong>Check by:</strong> {escape(falsification['check_by'])}")
        parts.append("</p>")
    parts.append("</div>")
    return "".join(parts)


def crux_receipt_to_markdown(receipt: CruxReceipt) -> str:
    """Render a ``CruxReceipt`` as human-readable markdown.

    Headline is "# Crux Map — <question>" (never "# Decision"): the
    deliverable is a map of load-bearing disagreement, not a verdict.
    """
    lines: list[str] = [
        f"# Crux Map — {receipt.question}",
        "",
        f"**Receipt:** `{receipt.receipt_id}`  **Checksum:** `{receipt.checksum}`",
        f"**Debate:** `{receipt.debate_id}`  **Agents:** "
        f"{', '.join(receipt.agents) if receipt.agents else '—'}  "
        f"**Rounds:** {receipt.rounds}",
        "",
        f"**Convergence barrier:** {receipt.convergence_barrier:.3f}  ",
        "*(higher = harder to reach consensus; cruxes below are the "
        "highest-leverage disagreement points)*",
        "",
        "## Cruxes",
        "",
    ]

    if not receipt.cruxes:
        lines.append("_No cruxes met the `crux_finder_min_score` threshold for this debate._")
        lines.append("")
    else:
        for index, crux in enumerate(receipt.cruxes, start=1):
            statement = crux.get("statement", "(unknown claim)")
            lines.append(f"### {index}. {statement}")
            lines.append(f"- **Crux score:** {float(crux.get('crux_score', 0.0)):.3f}")
            lines.append(
                f"- **Influence:** {float(crux.get('influence_score', 0.0)):.3f}"
                f"  |  **Disagreement:** "
                f"{float(crux.get('disagreement_score', 0.0)):.3f}"
                f"  |  **Uncertainty:** "
                f"{float(crux.get('uncertainty_score', 0.0)):.3f}"
            )
            contesting = crux.get("contesting_agents") or []
            lines.append(
                "- **Contesting agents:** "
                + (", ".join(str(a) for a in contesting) if contesting else "—")
            )
            affected = crux.get("affected_claims") or []
            lines.append(f"- **Affected claims:** {len(affected)}")
            lines.append("")

    if receipt.recommended_focus:
        lines.append("## Recommended focus (priority order)")
        lines.append("")
        for rank, claim_id in enumerate(receipt.recommended_focus, start=1):
            lines.append(f"{rank}. `{claim_id}`")
        lines.append("")

    if receipt.counterfactuals:
        lines.append("## Counterfactual validation")
        lines.append("")
        for cf in receipt.counterfactuals:
            condition = cf.get("condition", "(unspecified condition)")
            outcome = cf.get("outcome_change", "(unspecified outcome)")
            likelihood = cf.get("likelihood")
            likelihood_str = (
                f" — likelihood {float(likelihood):.3f}" if likelihood is not None else ""
            )
            lines.append(f"- **{condition}:** {outcome}{likelihood_str}")
        lines.append("")

    if receipt.resolution_strategies:
        lines.append("## Resolution strategies")
        lines.append("")
        for strategy in receipt.resolution_strategies:
            claim_id = strategy.get("claim_id", "—")
            strategy_text = strategy.get("strategy", "(unspecified strategy)")
            impact = strategy.get("likely_impact", "")
            suffix = f" (impact: {impact})" if impact else ""
            lines.append(f"- `{claim_id}`: {strategy_text}{suffix}")
        lines.append("")

    lines.append("---")
    lines.append(f"_Generated by aragora crux-finder mode at {receipt.timestamp}_")
    return "\n".join(lines)


def receipt_to_markdown(
    receipt: DecisionReceipt,
    include_provenance: bool = True,
    include_evidence: bool = True,
) -> str:
    """Generate markdown report with full provenance and evidence links.

    Args:
        receipt: The DecisionReceipt to render
        include_provenance: Include full provenance chain section
        include_evidence: Include evidence hashes for findings

    Returns:
        Markdown formatted decision receipt
    """
    verdict_emoji = {
        "PASS": "✓",
        "CONDITIONAL": "~",
        "FAIL": "✗",
    }.get(receipt.verdict, "?")

    lines = [
        "# Decision Receipt",
        "",
        f"**Receipt ID:** `{receipt.receipt_id}`",
        f"**Gauntlet ID:** `{receipt.gauntlet_id}`",
        f"**Generated:** {receipt.timestamp}",
        "",
        "---",
        "",
        f"## Verdict: [{verdict_emoji}] {receipt.verdict}",
        "",
        f"**Confidence:** {receipt.confidence:.1%}",
        f"**Robustness Score:** {receipt.robustness_score:.1%}",
        "",
        f"> {receipt.verdict_reasoning}",
        "",
    ]

    # Consensus proof section
    if receipt.consensus_proof:
        lines.extend(
            [
                "---",
                "",
                "## Consensus Proof",
                "",
                f"- **Consensus Reached:** {'Yes' if receipt.consensus_proof.reached else 'No'}",
                f"- **Method:** {receipt.consensus_proof.method}",
                f"- **Confidence:** {receipt.consensus_proof.confidence:.1%}",
            ]
        )
        if receipt.consensus_proof.supporting_agents:
            lines.append(
                f"- **Supporting Agents:** {', '.join(receipt.consensus_proof.supporting_agents)}"
            )
        if receipt.consensus_proof.dissenting_agents:
            lines.append(
                f"- **Dissenting Agents:** {', '.join(receipt.consensus_proof.dissenting_agents)}"
            )
        if receipt.consensus_proof.evidence_hash:
            lines.append(f"- **Evidence Hash:** `{receipt.consensus_proof.evidence_hash}`")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## Risk Summary",
            "",
            "| Severity | Count |",
            "|----------|-------|",
            f"| Critical | {receipt.risk_summary.get('critical', 0)} |",
            f"| High | {receipt.risk_summary.get('high', 0)} |",
            f"| Medium | {receipt.risk_summary.get('medium', 0)} |",
            f"| Low | {receipt.risk_summary.get('low', 0)} |",
            f"| **Total** | **{receipt.vulnerabilities_found}** |",
            "",
            "---",
            "",
            "## Validation Coverage",
            "",
            f"- **Attacks Attempted:** {receipt.attacks_attempted}",
            f"- **Attacks Successful:** {receipt.attacks_successful}",
            f"- **Probes Run:** {receipt.probes_run}",
            "",
        ]
    )

    # Cost breakdown section (when available)
    if receipt.cost_summary:
        lines.extend(_render_cost_summary_markdown(receipt.cost_summary))

    if receipt.agent_responses:
        lines.extend(
            [
                "---",
                "",
                "## Agent Responses",
                "",
            ]
        )
        for response in receipt.agent_responses[:12]:
            label = (
                response.llm_label or response.model or response.provider_display or "Unknown LLM"
            )
            lines.append(f"### {response.agent}")
            meta_parts = [f"**LLM:** {label}"]
            if response.role:
                meta_parts.append(f"**Role:** {response.role}")
            if response.round:
                meta_parts.append(f"**Round:** {response.round}")
            lines.append(" | ".join(meta_parts))
            lines.append("")
            text = response.response[:800]
            if len(response.response) > 800:
                text += "..."
            lines.append(text)
            lines.append("")
        if len(receipt.agent_responses) > 12:
            lines.append(
                f"_Showing first 12 of {len(receipt.agent_responses)} recorded responses._"
            )
            lines.append("")

    if receipt.vulnerability_details:
        lines.append("---")
        lines.append("")
        lines.append("## Critical Findings")
        lines.append("")
        for i, vuln in enumerate(receipt.vulnerability_details[:10], 1):
            finding_id = vuln.get("id", f"F-{i:03d}")
            lines.append(f"### [{finding_id}] {vuln.get('title', 'Unknown')}")
            lines.append("")
            lines.append(
                f"**Severity:** {vuln.get('severity', vuln.get('severity_level', 'unknown')).upper()}"
            )
            lines.append(f"**Category:** {vuln.get('category', 'unknown')}")
            if vuln.get("verified"):
                lines.append("**Verified:** Yes")
            if vuln.get("source"):
                lines.append(f"**Source:** {vuln.get('source')}")
            lines.append("")
            lines.append(vuln.get("description", "")[:500])
            if vuln.get("evidence") and include_evidence:
                lines.append("")
                evidence = vuln.get("evidence", "")
                if isinstance(evidence, str) and len(evidence) > 200:
                    evidence = evidence[:200] + "..."
                lines.append(f"**Evidence:** {evidence}")
                # Generate evidence hash for verification
                evidence_str = str(vuln.get("evidence", "") or vuln.get("description", ""))
                evidence_hash = hashlib.sha256(evidence_str.encode()).hexdigest()[:16]
                lines.append(f"**Evidence Hash:** `{evidence_hash}`")
            if vuln.get("mitigation"):
                lines.append("")
                lines.append(f"**Mitigation:** {vuln.get('mitigation')}")
            lines.append("")

    if receipt.dissenting_views:
        lines.append("---")
        lines.append("")
        lines.append("## Dissenting Views")
        lines.append("")
        for view in receipt.dissenting_views[:5]:
            lines.append(f"- {view}")
        lines.append("")

    lines.extend(_render_epistemic_markdown(receipt))

    # Provenance chain section
    if include_provenance and receipt.provenance_chain:
        lines.append("---")
        lines.append("")
        lines.append("## Provenance Chain")
        lines.append("")
        lines.append("| # | Timestamp | Event | Agent | Description | Evidence Hash |")
        lines.append("|---|-----------|-------|-------|-------------|---------------|")
        for i, record in enumerate(receipt.provenance_chain, 1):
            timestamp = record.timestamp[:19] if record.timestamp else "-"
            event = record.event_type or "-"
            agent = record.agent or "-"
            desc = (
                (record.description[:40] + "...")
                if len(record.description) > 40
                else record.description
            )
            evidence_hash = f"`{record.evidence_hash}`" if record.evidence_hash else "-"
            lines.append(f"| {i} | {timestamp} | {event} | {agent} | {desc} | {evidence_hash} |")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## Integrity Verification",
            "",
            "| Field | Hash |",
            "|-------|------|",
            f"| Input | `{receipt.input_hash}` |",
            f"| Artifact | `{receipt.artifact_hash}` |",
            "",
            "To verify this receipt has not been tampered with, the artifact hash",
            "can be recomputed from the receipt contents and compared.",
            "",
            "---",
            "",
            "*Generated by Aragora Gauntlet*",
        ]
    )

    return "\n".join(lines)


def receipt_to_html(
    receipt: DecisionReceipt,
    max_findings: int = 20,
    max_provenance: int = 50,
) -> str:
    """Export as self-contained HTML document.

    Args:
        receipt: The DecisionReceipt to render
        max_findings: Maximum number of findings to include (default 20)
        max_provenance: Maximum provenance records to include (default 50)
    """
    verdict_color = {
        "PASS": "#28a745",
        "CONDITIONAL": "#ffc107",
        "FAIL": "#dc3545",
    }.get(receipt.verdict, "#6c757d")

    # Use list + join for O(n) complexity instead of O(n^2) string concatenation
    findings_parts: list[str] = []
    for vuln in receipt.vulnerability_details[:max_findings]:
        severity = str(vuln.get("severity", "UNKNOWN")).upper()
        severity_color = {
            "CRITICAL": "#dc3545",
            "HIGH": "#fd7e14",
            "MEDIUM": "#ffc107",
            "LOW": "#28a745",
        }.get(severity, "#6c757d")
        title = escape(str(vuln.get("title", "")))
        description = escape(str(vuln.get("description", "")))
        mitigation = vuln.get("mitigation")
        mitigation_html = ""
        if mitigation:
            mitigation_html = f"<p><em>Mitigation: {escape(str(mitigation))}</em></p>"

        findings_parts.append(
            f'<div class="finding" style="border-left: 4px solid {severity_color};">'
            f'<strong style="color: {severity_color};">[{severity}]</strong> {title}'
            f"<p>{description}</p>"
            f"{mitigation_html}"
            "</div>"
        )
    findings_html = "".join(findings_parts)

    risk_summary = receipt.risk_summary or {}
    agent_responses_html = ""
    if receipt.agent_responses:
        response_parts = ['<div class="section"><h2>Agent Responses</h2>']
        for response in receipt.agent_responses[:12]:
            label = (
                response.llm_label or response.model or response.provider_display or "Unknown LLM"
            )
            role = escape(response.role) if response.role else "response"
            round_label = (
                f' <span class="meta">Round {response.round}</span>' if response.round else ""
            )
            response_text = escape(response.response[:1200])
            if len(response.response) > 1200:
                response_text += "..."
            response_parts.append(
                '<div class="finding">'
                f"<strong>{escape(response.agent)}</strong>"
                f' <span class="meta">{escape(label)} · {role}</span>{round_label}'
                f"<p>{response_text}</p>"
                "</div>"
            )
        if len(receipt.agent_responses) > 12:
            response_parts.append(
                f'<p class="meta">Showing first 12 of {len(receipt.agent_responses)} recorded responses.</p>'
            )
        response_parts.append("</div>")
        agent_responses_html = "".join(response_parts)

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Decision Receipt - {escape(receipt.receipt_id)}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #333; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
        .verdict {{ font-size: 22px; font-weight: bold; color: {verdict_color}; margin: 20px 0; padding: 16px; background: #f8f9fa; border-radius: 8px; }}
        .scores {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin: 20px 0; }}
        .score {{ text-align: center; padding: 12px; background: #f8f9fa; border-radius: 8px; }}
        .score-value {{ font-size: 28px; font-weight: bold; color: #333; }}
        .score-label {{ font-size: 12px; color: #666; }}
        .section {{ margin: 24px 0; }}
        .finding {{ margin: 10px 0; padding: 12px; background: #f8f9fa; border-left: 4px solid #ccc; }}
        table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
        th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; }}
        .meta {{ font-size: 13px; color: #666; }}
        code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace; }}
    </style>
</head>
<body>
    <h1>Decision Receipt</h1>
    <p class="meta">
        <strong>Receipt ID:</strong> <code>{escape(receipt.receipt_id)}</code><br>
        <strong>Gauntlet ID:</strong> <code>{escape(receipt.gauntlet_id)}</code><br>
        <strong>Generated:</strong> {escape(receipt.timestamp)}
    </p>

    <div class="verdict">
        VERDICT: {escape(receipt.verdict)}
        <div style="font-size: 14px; font-weight: normal; margin-top: 8px;">
            Confidence: {receipt.confidence:.0%} | Robustness: {receipt.robustness_score:.0%}
        </div>
        {f'<div style="font-size: 13px; font-weight: normal; margin-top: 8px;">{escape(receipt.verdict_reasoning)}</div>' if receipt.verdict_reasoning else ""}
    </div>

    <div class="scores">
        <div class="score">
            <div class="score-value">{receipt.confidence:.0%}</div>
            <div class="score-label">Confidence</div>
        </div>
        <div class="score">
            <div class="score-value">{receipt.robustness_score:.0%}</div>
            <div class="score-label">Robustness</div>
        </div>
    </div>

    <div class="section">
        <h2>Risk Summary</h2>
        <table>
            <tr><th>Severity</th><th>Count</th></tr>
            <tr><td>Critical</td><td>{risk_summary.get("critical", 0)}</td></tr>
            <tr><td>High</td><td>{risk_summary.get("high", 0)}</td></tr>
            <tr><td>Medium</td><td>{risk_summary.get("medium", 0)}</td></tr>
            <tr><td>Low</td><td>{risk_summary.get("low", 0)}</td></tr>
            <tr><td><strong>Total</strong></td><td><strong>{receipt.vulnerabilities_found}</strong></td></tr>
        </table>
    </div>

    <div class="section">
        <h2>Coverage</h2>
        <p class="meta">
            Attacks Attempted: {receipt.attacks_attempted}<br>
            Attacks Successful: {receipt.attacks_successful}<br>
            Probes Run: {receipt.probes_run}
        </p>
    </div>

    {_render_cost_summary_html(receipt.cost_summary)}

    {agent_responses_html}

    <div class="section">
        <h2>Findings</h2>
        {findings_html or '<p class="meta">No findings reported.</p>'}
    </div>

    {_render_epistemic_html(receipt)}

    <div class="section">
        <h2>Integrity</h2>
        <p class="meta">
            Input Hash: <code>{escape(receipt.input_hash[:32])}...</code><br>
            Artifact Hash: <code>{escape(receipt.artifact_hash[:32])}...</code>
        </p>
    </div>
{receipt._signature_verification_html()}
</body>
</html>
"""


def receipt_to_html_paginated(
    receipt: DecisionReceipt,
    findings_per_page: int = 10,
    max_provenance: int = 50,
    provenance_sampling: str = "first_last",
) -> str:
    """Export as paginated HTML document optimized for PDF rendering.

    Uses CSS page breaks and provenance sampling to handle large receipts
    efficiently without memory issues during PDF generation.

    Args:
        receipt: The DecisionReceipt to render
        findings_per_page: Number of findings per page (default 10)
        max_provenance: Maximum provenance records to include (default 50)
        provenance_sampling: Sampling strategy for provenance chain:
            - "all": Include all records up to max_provenance
            - "first_last": Include first and last half (default)
            - "sampled": Evenly sample across the chain

    Returns:
        HTML string with CSS page breaks suitable for PDF rendering
    """
    verdict_color = {
        "PASS": "#28a745",
        "CONDITIONAL": "#ffc107",
        "FAIL": "#dc3545",
    }.get(receipt.verdict, "#6c757d")

    # Sample provenance chain based on strategy
    provenance = receipt._sample_provenance(max_provenance, provenance_sampling)

    # Build findings HTML with page breaks
    findings_parts: list[str] = []
    for i, vuln in enumerate(receipt.vulnerability_details):
        # Add page break before each new page (except first)
        if i > 0 and i % findings_per_page == 0:
            findings_parts.append('<div style="page-break-before: always;"></div>')

        severity = str(vuln.get("severity", "UNKNOWN")).upper()
        severity_color = {
            "CRITICAL": "#dc3545",
            "HIGH": "#fd7e14",
            "MEDIUM": "#ffc107",
            "LOW": "#28a745",
        }.get(severity, "#6c757d")
        title = escape(str(vuln.get("title", "")))
        description = escape(str(vuln.get("description", "")))
        mitigation = vuln.get("mitigation")
        mitigation_html = ""
        if mitigation:
            mitigation_html = f"<p><em>Mitigation: {escape(str(mitigation))}</em></p>"

        findings_parts.append(
            f'<div class="finding" style="border-left: 4px solid {severity_color};">'
            f'<strong style="color: {severity_color};">[{severity}]</strong> {title}'
            f"<p>{description}</p>"
            f"{mitigation_html}"
            "</div>"
        )
    findings_html = "".join(findings_parts)

    # Build provenance HTML
    provenance_parts: list[str] = []
    if provenance:
        provenance_parts.append('<div style="page-break-before: always;"></div>')
        provenance_parts.append('<div class="section"><h2>Provenance Chain</h2>')
        provenance_parts.append(
            "<table><tr><th>#</th><th>Timestamp</th><th>Event</th>"
            "<th>Agent</th><th>Description</th></tr>"
        )
        for i, record in enumerate(provenance, 1):
            timestamp = record.timestamp[:19] if record.timestamp else "-"
            event = record.event_type or "-"
            agent = record.agent or "-"
            desc = escape(record.description[:50]) if record.description else "-"
            provenance_parts.append(
                f"<tr><td>{i}</td><td>{escape(timestamp)}</td>"
                f"<td>{escape(event)}</td><td>{escape(agent)}</td>"
                f"<td>{desc}</td></tr>"
            )
        provenance_parts.append("</table></div>")
    provenance_html = "".join(provenance_parts)

    risk_summary = receipt.risk_summary or {}

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Decision Receipt - {escape(receipt.receipt_id)}</title>
    <style>
        @page {{ margin: 2cm; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #333; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
        .verdict {{ font-size: 22px; font-weight: bold; color: {verdict_color}; margin: 20px 0; padding: 16px; background: #f8f9fa; border-radius: 8px; }}
        .section {{ margin: 24px 0; }}
        .finding {{ margin: 10px 0; padding: 12px; background: #f8f9fa; border-left: 4px solid #ccc; }}
        table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
        th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #eee; font-size: 11px; }}
        th {{ background: #f8f9fa; }}
        .meta {{ font-size: 13px; color: #666; }}
        code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace; }}
    </style>
</head>
<body>
    <h1>Decision Receipt</h1>
    <p class="meta">
        <strong>Receipt ID:</strong> <code>{escape(receipt.receipt_id)}</code><br>
        <strong>Gauntlet ID:</strong> <code>{escape(receipt.gauntlet_id)}</code><br>
        <strong>Generated:</strong> {escape(receipt.timestamp)}
    </p>

    <div class="verdict">
        VERDICT: {escape(receipt.verdict)}
        <div style="font-size: 14px; font-weight: normal; margin-top: 8px;">
            Confidence: {receipt.confidence:.0%} | Robustness: {receipt.robustness_score:.0%}
        </div>
    </div>

    <div class="section">
        <h2>Risk Summary</h2>
        <table>
            <tr><th>Severity</th><th>Count</th></tr>
            <tr><td>Critical</td><td>{risk_summary.get("critical", 0)}</td></tr>
            <tr><td>High</td><td>{risk_summary.get("high", 0)}</td></tr>
            <tr><td>Medium</td><td>{risk_summary.get("medium", 0)}</td></tr>
            <tr><td>Low</td><td>{risk_summary.get("low", 0)}</td></tr>
            <tr><td><strong>Total</strong></td><td><strong>{receipt.vulnerabilities_found}</strong></td></tr>
        </table>
    </div>

    <div class="section">
        <h2>Findings ({len(receipt.vulnerability_details)} total)</h2>
        {findings_html or '<p class="meta">No findings reported.</p>'}
    </div>

    {_render_epistemic_html(receipt)}

    {provenance_html}

    <div class="section">
        <h2>Integrity</h2>
        <p class="meta">
            Input Hash: <code>{escape(receipt.input_hash[:32])}...</code><br>
            Artifact Hash: <code>{escape(receipt.artifact_hash[:32])}...</code>
        </p>
    </div>
{receipt._signature_verification_html()}
</body>
</html>
"""


def receipt_to_sarif(receipt: DecisionReceipt) -> dict:
    """Export as SARIF 2.1.0 format.

    SARIF (Static Analysis Results Interchange Format) is the OASIS standard
    for exchanging static analysis results. This enables interoperability with:
    - GitHub Security (code scanning)
    - Azure DevOps
    - VS Code SARIF Viewer
    - SonarQube
    - DefectDojo

    Args:
        receipt: The DecisionReceipt to export

    Returns:
        SARIF 2.1.0 dictionary
    """
    # Map severity to SARIF levels
    sarif_level_map = {
        "CRITICAL": "error",
        "HIGH": "error",
        "MEDIUM": "warning",
        "LOW": "note",
    }

    # Map severity to SARIF security-severity scores (CVSS-like)
    sarif_severity_map = {
        "CRITICAL": "9.0",
        "HIGH": "7.0",
        "MEDIUM": "4.0",
        "LOW": "1.0",
    }

    # Build rules from unique vulnerability categories
    rules: list[dict[str, Any]] = []
    rule_ids: dict[str, int] = {}

    for idx, vuln in enumerate(receipt.vulnerability_details):
        category = vuln.get("category", "unknown")
        if category not in rule_ids:
            rule_id = f"ARAGORA-{len(rule_ids) + 1:03d}"
            rule_ids[category] = len(rules)
            rules.append(
                {
                    "id": rule_id,
                    "name": category.replace("_", " ").title(),
                    "shortDescription": {"text": f"Aragora Gauntlet: {category}"},
                    "fullDescription": {"text": f"Security finding in category: {category}"},
                    "helpUri": "https://aragora.ai/docs/gauntlet",
                    "properties": {
                        "security-severity": sarif_severity_map.get(
                            str(vuln.get("severity_level", "MEDIUM")).upper(), "4.0"
                        ),
                        "tags": ["security", "aragora", category],
                    },
                }
            )

    # Build results from vulnerability details
    results = []
    for vuln in receipt.vulnerability_details:
        category = vuln.get("category", "unknown")
        severity = str(vuln.get("severity_level", vuln.get("severity", "MEDIUM"))).upper()
        rule_idx = rule_ids.get(category, 0)
        rule_id = rules[rule_idx]["id"] if rule_idx < len(rules) else "ARAGORA-000"

        result = {
            "ruleId": rule_id,
            "ruleIndex": rule_idx,
            "level": sarif_level_map.get(severity, "warning"),
            "message": {"text": vuln.get("description", vuln.get("title", "Finding"))},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": f"input/{receipt.input_hash[:8]}",
                            "uriBaseId": "GAUNTLET_ROOT",
                        }
                    },
                    "logicalLocations": [
                        {
                            "name": vuln.get("title", "Unknown"),
                            "kind": "finding",
                        }
                    ],
                }
            ],
            "fingerprints": {
                "aragora/v1": hashlib.sha256(
                    f"{vuln.get('id', '')}:{vuln.get('title', '')}".encode()
                ).hexdigest()[:32]
            },
            "properties": {
                "gauntlet_id": receipt.gauntlet_id,
                "receipt_id": receipt.receipt_id,
                "category": category,
                "severity": severity,
                "verified": vuln.get("verified", False),
            },
        }

        # Add fix suggestions if mitigation is present
        if vuln.get("mitigation"):
            result["fixes"] = [{"description": {"text": vuln.get("mitigation", "")}}]

        results.append(result)

    # Build SARIF document
    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Aragora Gauntlet",
                        "version": "1.0.0",
                        "informationUri": "https://aragora.ai/gauntlet",
                        "rules": rules,
                        "properties": {
                            "verdict": receipt.verdict,
                            "confidence": receipt.confidence,
                            "robustness_score": receipt.robustness_score,
                        },
                    }
                },
                "results": results,
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "endTimeUtc": receipt.timestamp,
                        "properties": {
                            "gauntlet_id": receipt.gauntlet_id,
                            "receipt_id": receipt.receipt_id,
                            "attacks_attempted": receipt.attacks_attempted,
                            "attacks_successful": receipt.attacks_successful,
                            "probes_run": receipt.probes_run,
                        },
                    }
                ],
                "artifacts": [
                    {
                        "location": {
                            "uri": f"input/{receipt.input_hash[:8]}",
                            "uriBaseId": "GAUNTLET_ROOT",
                        },
                        "hashes": {
                            "sha-256": receipt.input_hash,
                        },
                        "length": -1,
                        "properties": {
                            "summary": receipt.input_summary[:200],
                        },
                    }
                ],
                "properties": {
                    "risk_summary": receipt.risk_summary,
                    "artifact_hash": receipt.artifact_hash,
                    "consensus_proof": (
                        receipt.consensus_proof.to_dict() if receipt.consensus_proof else None
                    ),
                },
            }
        ],
    }

    return sarif


def receipt_to_csv(receipt: DecisionReceipt) -> str:
    """Export findings as CSV format.

    Args:
        receipt: The DecisionReceipt to export

    Returns:
        CSV content with vulnerability details
    """
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(
        [
            "Finding ID",
            "Category",
            "Severity",
            "Title",
            "Description",
            "Mitigation",
            "Verified",
            "Source",
        ]
    )

    # Data rows
    for vuln in receipt.vulnerability_details:
        writer.writerow(
            [
                vuln.get("id", ""),
                vuln.get("category", ""),
                vuln.get("severity_level", vuln.get("severity", "")),
                vuln.get("title", ""),
                vuln.get("description", "")[:500],
                vuln.get("mitigation", ""),
                vuln.get("verified", False),
                vuln.get("source", ""),
            ]
        )

    return output.getvalue()


# ---------------------------------------------------------------------------
# Cost summary rendering helpers
# ---------------------------------------------------------------------------


def _render_cost_summary_markdown(cost_summary: dict[str, Any]) -> list[str]:
    """Render cost_summary dict as Markdown lines.

    Args:
        cost_summary: The cost breakdown dict (from DebateCostSummary.to_dict()
            or the lightweight fallback).

    Returns:
        List of Markdown lines to extend into the receipt.
    """
    lines: list[str] = [
        "---",
        "",
        "## Cost Breakdown",
        "",
        f"- **Total Cost:** ${cost_summary.get('total_cost_usd', '0')}",
    ]

    total_tokens_in = cost_summary.get("total_tokens_in", 0)
    total_tokens_out = cost_summary.get("total_tokens_out", 0)
    if total_tokens_in or total_tokens_out:
        lines.append(f"- **Tokens In:** {total_tokens_in:,}")
        lines.append(f"- **Tokens Out:** {total_tokens_out:,}")
        lines.append(f"- **Total Tokens:** {total_tokens_in + total_tokens_out:,}")

    total_calls = cost_summary.get("total_calls", 0)
    if total_calls:
        lines.append(f"- **API Calls:** {total_calls}")

    lines.append("")

    # Per-agent breakdown table
    per_agent = cost_summary.get("per_agent", {})
    if per_agent:
        lines.extend(
            [
                "### Per-Agent Costs",
                "",
                "| Agent | Cost (USD) | Tokens In | Tokens Out | Calls |",
                "|-------|-----------|-----------|------------|-------|",
            ]
        )
        for _name, agent_data in per_agent.items():
            if isinstance(agent_data, dict):
                agent_name = agent_data.get("agent_name", _name)
                cost = agent_data.get("total_cost_usd", "0")
                t_in = agent_data.get("total_tokens_in", 0)
                t_out = agent_data.get("total_tokens_out", 0)
                calls = agent_data.get("call_count", 0)
                lines.append(f"| {agent_name} | ${cost} | {t_in:,} | {t_out:,} | {calls} |")
        lines.append("")

    # Model usage table
    model_usage = cost_summary.get("model_usage", {})
    if model_usage:
        lines.extend(
            [
                "### Model Usage",
                "",
                "| Provider/Model | Cost (USD) | Calls |",
                "|---------------|-----------|-------|",
            ]
        )
        for key, model_data in model_usage.items():
            if isinstance(model_data, dict):
                provider = model_data.get("provider", "")
                model = model_data.get("model", key)
                cost = model_data.get("total_cost_usd", "0")
                calls = model_data.get("call_count", 0)
                label = f"{provider}/{model}" if provider else model
                lines.append(f"| {label} | ${cost} | {calls} |")
        lines.append("")

    return lines


def _render_cost_summary_html(cost_summary: dict[str, Any] | None) -> str:
    """Render cost_summary dict as an HTML section.

    Args:
        cost_summary: The cost breakdown dict or None.

    Returns:
        HTML string for the cost section (empty string if no data).
    """
    if not cost_summary:
        return ""

    total_cost = escape(str(cost_summary.get("total_cost_usd", "0")))
    total_tokens_in = cost_summary.get("total_tokens_in", 0)
    total_tokens_out = cost_summary.get("total_tokens_out", 0)
    total_calls = cost_summary.get("total_calls", 0)

    parts: list[str] = [
        '<div class="section">',
        "    <h2>Cost Breakdown</h2>",
        "    <table>",
        "        <tr><th>Metric</th><th>Value</th></tr>",
        f"        <tr><td>Total Cost</td><td>${total_cost}</td></tr>",
    ]

    if total_tokens_in or total_tokens_out:
        parts.append(f"        <tr><td>Tokens In</td><td>{total_tokens_in:,}</td></tr>")
        parts.append(f"        <tr><td>Tokens Out</td><td>{total_tokens_out:,}</td></tr>")
        parts.append(
            f"        <tr><td>Total Tokens</td><td>{total_tokens_in + total_tokens_out:,}</td></tr>"
        )

    if total_calls:
        parts.append(f"        <tr><td>API Calls</td><td>{total_calls}</td></tr>")

    parts.extend(["    </table>", ""])

    # Per-agent breakdown
    per_agent = cost_summary.get("per_agent", {})
    if per_agent:
        parts.extend(
            [
                "    <h3>Per-Agent Costs</h3>",
                "    <table>",
                "        <tr><th>Agent</th><th>Cost (USD)</th>"
                "<th>Tokens In</th><th>Tokens Out</th><th>Calls</th></tr>",
            ]
        )
        for _name, agent_data in per_agent.items():
            if isinstance(agent_data, dict):
                agent_name = escape(str(agent_data.get("agent_name", _name)))
                cost = escape(str(agent_data.get("total_cost_usd", "0")))
                t_in = agent_data.get("total_tokens_in", 0)
                t_out = agent_data.get("total_tokens_out", 0)
                calls = agent_data.get("call_count", 0)
                parts.append(
                    f"        <tr><td>{agent_name}</td><td>${cost}</td>"
                    f"<td>{t_in:,}</td><td>{t_out:,}</td><td>{calls}</td></tr>"
                )
        parts.append("    </table>")

    parts.append("</div>")

    return "\n".join(parts)
