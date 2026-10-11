"""
Shared receipt formatting utilities for CLI commands.

Provides HTML and Markdown rendering for debate results and decision receipts,
used by both `aragora quickstart` and `aragora receipt` commands.
"""

from __future__ import annotations

from html import escape
from typing import Any


def receipt_to_html(data: dict[str, Any]) -> str:
    """Convert a debate result or receipt dict to a styled HTML document.

    Renders a self-contained HTML page with:
    - Verdict banner with color-coded status
    - Confidence and agent summary
    - Consensus proof section (if present)
    - Dissent and provenance details
    - Timing and metadata

    Args:
        data: Receipt dict with keys like question, verdict, confidence,
              agents, summary, dissent, consensus_proof, provenance_chain,
              elapsed_seconds, etc.

    Returns:
        Complete HTML document string.
    """
    question = escape(str(data.get("question", data.get("input_summary", "N/A"))))
    verdict = data.get("verdict", "N/A")
    confidence = data.get("confidence", 0)
    agents = data.get("agents", [])
    summary = escape(
        str(data.get("summary", data.get("verdict_reasoning", "No summary available.")))
    )
    dissent = data.get("dissent", data.get("dissenting_views", []))
    rounds = data.get("rounds", data.get("probes_run", 0))
    mode = data.get("mode", "")
    elapsed = data.get("elapsed_seconds")
    consensus_proof = data.get("consensus_proof")
    provenance_chain = data.get("provenance_chain", [])
    artifact_hash = data.get("artifact_hash", "")
    receipt_id = data.get("receipt_id", "")

    # Color-code verdict
    verdict_upper = str(verdict).upper()
    if verdict_upper in ("PASS", "CONSENSUS", "APPROVED"):
        verdict_color = "#059669"
        verdict_bg = "#ecfdf5"
    elif verdict_upper in ("FAIL", "REJECTED"):
        verdict_color = "#dc2626"
        verdict_bg = "#fef2f2"
    else:
        verdict_color = "#d97706"
        verdict_bg = "#fffbeb"

    # Agent badges
    agent_badges = ""
    for agent in agents:
        agent_name = escape(str(agent))
        agent_badges += f'<span class="agent-badge">{agent_name}</span> '

    # Dissent section
    dissent_html = ""
    if dissent:
        dissent_items = ""
        for d in dissent:
            if isinstance(d, dict):
                agent = escape(str(d.get("agent", "?")))
                reason = escape(str(d.get("reason", "N/A")))
                dissent_items += f"<li><strong>{agent}:</strong> {reason}</li>"
            else:
                dissent_items += f"<li>{escape(str(d))}</li>"
        dissent_html = f"""
    <div class="section">
        <h2>Dissenting Views</h2>
        <ul>{dissent_items}</ul>
    </div>"""

    # Consensus proof section
    consensus_html = ""
    if consensus_proof:
        cp = consensus_proof if isinstance(consensus_proof, dict) else {}
        reached = cp.get("reached", False)
        cp_confidence = cp.get("confidence", 0)
        supporting = cp.get("supporting_agents", [])
        dissenting_agents = cp.get("dissenting_agents", [])
        method = cp.get("method", "majority")

        status_icon = "&#x2714;" if reached else "&#x2718;"
        status_color = "#059669" if reached else "#dc2626"
        status_text = "Reached" if reached else "Not Reached"

        supporting_list = ", ".join(escape(str(a)) for a in supporting) or "None"
        dissenting_list = ", ".join(escape(str(a)) for a in dissenting_agents) or "None"

        consensus_html = f"""
    <div class="section consensus-proof">
        <h2>Consensus Proof</h2>
        <div class="consensus-status" style="color: {status_color};">
            <span style="font-size: 1.2em;">{status_icon}</span> {status_text}
        </div>
        <table class="meta-table">
            <tr><td>Method</td><td>{escape(str(method))}</td></tr>
            <tr><td>Confidence</td><td>{cp_confidence:.0%}</td></tr>
            <tr><td>Supporting</td><td>{supporting_list}</td></tr>
            <tr><td>Dissenting</td><td>{dissenting_list}</td></tr>
        </table>
    </div>"""

    # Provenance chain section
    provenance_html = ""
    if provenance_chain:
        rows = ""
        for record in provenance_chain[:20]:  # Limit to 20 entries
            if isinstance(record, dict):
                ts = escape(str(record.get("timestamp", "")))
                event = escape(str(record.get("event_type", "")))
                agent = escape(str(record.get("agent", "") or ""))
                desc = escape(str(record.get("description", "")))
                rows += f"<tr><td>{ts}</td><td>{event}</td><td>{agent}</td><td>{desc}</td></tr>"
        if rows:
            provenance_html = f"""
    <div class="section">
        <h2>Provenance Chain</h2>
        <table class="provenance-table">
            <thead><tr><th>Timestamp</th><th>Event</th><th>Agent</th><th>Description</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>"""

    # Timing info
    timing_html = ""
    if elapsed is not None:
        timing_html = f'<p class="timing">Completed in {elapsed:.1f}s</p>'

    # Integrity hash
    hash_html = ""
    if artifact_hash:
        hash_html = (
            f'<p class="hash">Artifact hash: <code>{escape(artifact_hash[:16])}...</code></p>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Decision Receipt — {question[:60]}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        max-width: 780px;
        margin: 0 auto;
        padding: 2em 1.5em;
        color: #1a1a1a;
        background: #fafafa;
        line-height: 1.6;
    }}
    .header {{
        border-bottom: 3px solid #2563eb;
        padding-bottom: 1em;
        margin-bottom: 1.5em;
    }}
    .header h1 {{
        font-size: 1.5em;
        color: #2563eb;
        margin-bottom: 0.3em;
    }}
    .header .subtitle {{
        color: #6b7280;
        font-size: 0.9em;
    }}
    .verdict-banner {{
        background: {verdict_bg};
        border: 2px solid {verdict_color};
        border-radius: 12px;
        padding: 1.2em 1.5em;
        margin-bottom: 1.5em;
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 0.5em;
    }}
    .verdict-text {{
        font-size: 1.6em;
        font-weight: 700;
        color: {verdict_color};
    }}
    .confidence {{
        font-size: 1.1em;
        color: {verdict_color};
        font-weight: 600;
    }}
    .question {{
        background: #f3f4f6;
        border-radius: 8px;
        padding: 1em 1.2em;
        margin-bottom: 1.5em;
        font-size: 1.05em;
    }}
    .question strong {{ color: #374151; }}
    .meta-row {{
        display: flex;
        gap: 1.5em;
        flex-wrap: wrap;
        margin-bottom: 1.5em;
    }}
    .meta-item {{
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 0.6em 1em;
        font-size: 0.9em;
    }}
    .meta-item strong {{ color: #6b7280; font-size: 0.85em; display: block; }}
    .agent-badge {{
        display: inline-block;
        background: #dbeafe;
        color: #1d4ed8;
        border-radius: 999px;
        padding: 0.2em 0.8em;
        font-size: 0.85em;
        font-weight: 500;
        margin: 0.15em 0;
    }}
    .section {{
        margin-bottom: 1.5em;
    }}
    .section h2 {{
        font-size: 1.1em;
        color: #374151;
        margin-bottom: 0.6em;
        padding-bottom: 0.3em;
        border-bottom: 1px solid #e5e7eb;
    }}
    .section p, .section ul {{
        color: #4b5563;
    }}
    .section ul {{ padding-left: 1.5em; }}
    .section li {{ margin-bottom: 0.4em; }}
    .consensus-proof {{
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 1em 1.2em;
    }}
    .consensus-status {{
        font-weight: 700;
        font-size: 1.1em;
        margin-bottom: 0.6em;
    }}
    .meta-table {{
        width: 100%;
        border-collapse: collapse;
    }}
    .meta-table td {{
        padding: 0.3em 0.5em;
        border-bottom: 1px solid #f3f4f6;
        font-size: 0.9em;
    }}
    .meta-table td:first-child {{
        font-weight: 600;
        color: #6b7280;
        width: 120px;
    }}
    .provenance-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.85em;
    }}
    .provenance-table th {{
        background: #f9fafb;
        text-align: left;
        padding: 0.5em;
        border-bottom: 2px solid #e5e7eb;
        color: #6b7280;
        font-weight: 600;
    }}
    .provenance-table td {{
        padding: 0.4em 0.5em;
        border-bottom: 1px solid #f3f4f6;
    }}
    .timing {{
        color: #9ca3af;
        font-size: 0.85em;
        margin-top: 1em;
    }}
    .hash {{
        color: #9ca3af;
        font-size: 0.8em;
    }}
    .hash code {{
        background: #f3f4f6;
        padding: 0.1em 0.4em;
        border-radius: 4px;
        font-size: 0.95em;
    }}
    .footer {{
        margin-top: 2em;
        padding-top: 1em;
        border-top: 1px solid #e5e7eb;
        color: #9ca3af;
        font-size: 0.8em;
        text-align: center;
    }}
</style>
</head>
<body>
    <div class="header">
        <h1>Aragora Decision Receipt</h1>
        <div class="subtitle">{escape(receipt_id) if receipt_id else "Quickstart debate result"}</div>
    </div>

    <div class="verdict-banner">
        <span class="verdict-text">{escape(str(verdict))}</span>
        <span class="confidence">{confidence:.0%} confidence</span>
    </div>

    <div class="question">
        <strong>Question:</strong> {question}
    </div>

    <div class="meta-row">
        <div class="meta-item"><strong>Rounds</strong> {rounds}</div>
        <div class="meta-item"><strong>Agents</strong> {agent_badges}</div>
        {f'<div class="meta-item"><strong>Mode</strong> {escape(mode)}</div>' if mode else ""}
    </div>

    <div class="section">
        <h2>Summary</h2>
        <p>{summary}</p>
    </div>
    {consensus_html}
    {dissent_html}
    {provenance_html}
    {timing_html}
    {hash_html}

    <div class="footer">
        Generated by <strong>Aragora</strong> — The Decision Integrity Platform
    </div>
</body>
</html>"""


def receipt_to_markdown(data: dict[str, Any]) -> str:
    """Convert a debate result or receipt dict to Markdown.

    Args:
        data: Receipt dict with keys like question, verdict, confidence,
              agents, summary, dissent, consensus_proof, etc.

    Returns:
        Markdown string.
    """
    question = data.get("question", data.get("input_summary", "N/A"))
    verdict = data.get("verdict", "N/A")
    confidence = data.get("confidence", 0)
    agents = data.get("agents", [])
    summary = data.get("summary", data.get("verdict_reasoning", "No summary available."))
    dissent = data.get("dissent", data.get("dissenting_views", []))
    rounds = data.get("rounds", data.get("probes_run", 0))
    elapsed = data.get("elapsed_seconds")
    consensus_proof = data.get("consensus_proof")
    artifact_hash = data.get("artifact_hash", "")
    receipt_id = data.get("receipt_id", "")

    lines = [
        f"# Decision Receipt: {question}",
        "",
        f"**Verdict:** {verdict}",
        f"**Confidence:** {confidence:.0%}",
        f"**Rounds:** {rounds}",
        f"**Agents:** {', '.join(str(a) for a in agents)}",
    ]

    if receipt_id:
        lines.append(f"**Receipt ID:** {receipt_id}")
    if elapsed is not None:
        lines.append(f"**Elapsed:** {elapsed:.1f}s")

    lines += ["", "## Summary", "", str(summary)]

    # Consensus proof
    if consensus_proof:
        cp = consensus_proof if isinstance(consensus_proof, dict) else {}
        reached = cp.get("reached", False)
        method = cp.get("method", "majority")
        supporting = cp.get("supporting_agents", [])
        dissenting_agents = cp.get("dissenting_agents", [])

        lines += [
            "",
            "## Consensus Proof",
            "",
            f"- **Status:** {'Reached' if reached else 'Not reached'}",
            f"- **Method:** {method}",
            f"- **Supporting:** {', '.join(str(a) for a in supporting) or 'None'}",
            f"- **Dissenting:** {', '.join(str(a) for a in dissenting_agents) or 'None'}",
        ]

    # Dissent
    lines += ["", "## Dissent", ""]
    if dissent:
        for d in dissent:
            if isinstance(d, dict):
                lines.append(f"- **{d.get('agent', '?')}:** {d.get('reason', 'N/A')}")
            else:
                lines.append(f"- {d}")
    else:
        lines.append("No dissent recorded.")

    if artifact_hash:
        lines += ["", f"**Artifact hash:** `{artifact_hash[:16]}...`"]

    lines += ["", "---", "*Generated by Aragora — The Decision Integrity Platform*"]

    return "\n".join(lines)
