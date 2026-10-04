"""
Legacy Decision Receipt model for export/backward compatibility.

Canonical contract for new integrations: ``aragora.receipts.DecisionReceipt``
(implemented by ``aragora.gauntlet.receipt.DecisionReceipt``).

Decision Receipt - Audit-ready compliance artifacts.

Generates structured receipts from Gauntlet stress-tests:
- Verdict with confidence and risk level
- Findings with severity and mitigations
- Dissenting views and unresolved tensions
- Verified claims with proof hashes
- Complete audit trail for compliance

"Every high-stakes decision deserves a paper trail."
"""

from __future__ import annotations

import hashlib
import html as html_mod
import importlib
import io
import json
import textwrap
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aragora.core_types import Verdict

if TYPE_CHECKING:
    from aragora.core_types import DebateResult
    from aragora.export.audit_trail import AuditTrail
    from aragora.gauntlet import OrchestratorResult as GauntletResult  # Full orchestrator result


def agent_display_names(agents: Any) -> list[str]:
    """Readable names for the entries of ``agents_involved``.

    Gauntlet receipts store plain agent names, but debate receipts store one
    mapping per agent (``name``, ``model``, ``provider``, ``role``).
    """
    names: list[str] = []
    for agent in agents or []:
        if isinstance(agent, dict):
            label = agent.get("name") or agent.get("agent") or agent.get("model")
            names.append(str(label) if label else str(agent))
        else:
            names.append(str(agent))
    return names


@dataclass
class ReceiptFinding:
    """Simplified finding for receipt export."""

    id: str
    severity: str  # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    category: str
    title: str
    description: str
    mitigation: str | None = None
    source: str = ""
    verified: bool = False


@dataclass
class ReceiptDissent:
    """Simplified dissent record for receipt export."""

    agent: str
    type: str
    severity: float
    reasons: list[str]
    alternative: str | None = None


@dataclass
class ReceiptVerification:
    """Verification result for receipt export.

    The optional DIC-16 provenance fields (``claim_id``, ``crux_id``,
    ``evidence_ids``, ``verification_status``, ``source_receipt_id``) are
    backwards-compatible additions. Existing callers that construct
    ``ReceiptVerification`` without these fields continue to work unchanged.
    """

    claim: str
    verified: bool
    method: str
    proof_hash: str | None = None
    # DIC-16: epistemic provenance — all optional for backwards compat
    claim_id: str | None = None
    crux_id: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    verification_status: str | None = None  # "pass"|"fail"|"stale"|"unsupported"|"error"|"open"
    source_receipt_id: str | None = None


def _coerce_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float coercion for legacy receipt fields."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    """Best-effort int coercion for legacy receipt fields."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _render_cost_summary_markdown(cost_summary: dict[str, Any] | None) -> list[str]:
    """Render a legacy cost summary section for Markdown exports."""
    if not cost_summary:
        return []

    lines = [
        "---",
        "",
        "## Cost Breakdown",
        "",
        f"- **Total Cost:** ${cost_summary.get('total_cost_usd', '0')}",
        f"- **Tokens In:** {cost_summary.get('total_tokens_in', 0)}",
        f"- **Tokens Out:** {cost_summary.get('total_tokens_out', 0)}",
        f"- **Total Calls:** {cost_summary.get('total_calls', 0)}",
        "",
    ]

    per_agent = cost_summary.get("per_agent") or {}
    if per_agent:
        lines.extend(
            [
                "### Per-Agent Costs",
                "",
                "| Agent | Cost (USD) | Tokens In | Tokens Out | Calls |",
                "|-------|------------|-----------|------------|-------|",
            ]
        )
        for agent_name, payload in per_agent.items():
            if not isinstance(payload, dict):
                continue
            lines.append(
                f"| {agent_name} | ${payload.get('total_cost_usd', '0')} | "
                f"{payload.get('total_tokens_in', 0)} | {payload.get('total_tokens_out', 0)} | "
                f"{payload.get('call_count', 0)} |"
            )
        lines.append("")

    model_usage = cost_summary.get("model_usage") or {}
    if model_usage:
        lines.extend(
            [
                "### Model Usage",
                "",
                "| Model | Cost (USD) | Calls |",
                "|-------|------------|-------|",
            ]
        )
        for model_name, payload in model_usage.items():
            if not isinstance(payload, dict):
                continue
            lines.append(
                f"| {model_name} | ${payload.get('total_cost_usd', '0')} | "
                f"{payload.get('call_count', 0)} |"
            )
        lines.append("")

    return lines


def _render_cost_summary_html(cost_summary: dict[str, Any] | None) -> str:
    """Render a legacy cost summary section for HTML exports."""
    if not cost_summary:
        return ""

    esc = html_mod.escape
    per_agent_rows = ""
    for agent_name, payload in (cost_summary.get("per_agent") or {}).items():
        if not isinstance(payload, dict):
            continue
        per_agent_rows += (
            "<tr>"
            f"<td>{esc(str(agent_name))}</td>"
            f"<td>${esc(str(payload.get('total_cost_usd', '0')))}</td>"
            f"<td>{esc(str(payload.get('total_tokens_in', 0)))}</td>"
            f"<td>{esc(str(payload.get('total_tokens_out', 0)))}</td>"
            f"<td>{esc(str(payload.get('call_count', 0)))}</td>"
            "</tr>"
        )

    model_usage_rows = ""
    for model_name, payload in (cost_summary.get("model_usage") or {}).items():
        if not isinstance(payload, dict):
            continue
        model_usage_rows += (
            "<tr>"
            f"<td>{esc(str(model_name))}</td>"
            f"<td>${esc(str(payload.get('total_cost_usd', '0')))}</td>"
            f"<td>{esc(str(payload.get('call_count', 0)))}</td>"
            "</tr>"
        )

    per_agent_html = ""
    if per_agent_rows:
        per_agent_html = f"""
        <h3>Per-Agent Costs</h3>
        <table>
            <tr><th>Agent</th><th>Cost (USD)</th><th>Tokens In</th><th>Tokens Out</th><th>Calls</th></tr>
            {per_agent_rows}
        </table>
        """

    model_usage_html = ""
    if model_usage_rows:
        model_usage_html = f"""
        <h3>Model Usage</h3>
        <table>
            <tr><th>Model</th><th>Cost (USD)</th><th>Calls</th></tr>
            {model_usage_rows}
        </table>
        """

    return f"""
    <div class="section">
        <h2>Cost Breakdown</h2>
        <p><strong>Total Cost:</strong> ${esc(str(cost_summary.get("total_cost_usd", "0")))}</p>
        <p><strong>Tokens In:</strong> {esc(str(cost_summary.get("total_tokens_in", 0)))}</p>
        <p><strong>Tokens Out:</strong> {esc(str(cost_summary.get("total_tokens_out", 0)))}</p>
        <p><strong>Total Calls:</strong> {esc(str(cost_summary.get("total_calls", 0)))}</p>
        {per_agent_html}
        {model_usage_html}
    </div>
    """


def _paginate_pdf_text(
    text: str, line_width: int = 96, lines_per_page: int = 58
) -> list[list[str]]:
    """Wrap fallback PDF text into page-sized chunks."""
    safe_text = text.encode("ascii", errors="replace").decode("ascii")
    wrapped_lines: list[str] = []
    for raw_line in safe_text.replace("\r\n", "\n").split("\n"):
        expanded = raw_line.expandtabs(4)
        if not expanded:
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(
            textwrap.wrap(
                expanded,
                width=line_width,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
                drop_whitespace=False,
            )
            or [""]
        )

    if not wrapped_lines:
        wrapped_lines = [""]

    return [
        wrapped_lines[i : i + lines_per_page] for i in range(0, len(wrapped_lines), lines_per_page)
    ]


def _build_minimal_pdf(text: str) -> bytes:
    """Build a minimal valid PDF with the given text content."""
    safe_text = text.encode("ascii", errors="replace").decode("ascii")

    pdf_lines = []
    for line in safe_text.split("\n"):
        while len(line) > 80:
            pdf_lines.append(line[:80])
            line = line[80:]
        pdf_lines.append(line)

    stream_lines = ["BT", "/F1 10 Tf"]
    y = 750
    for line in pdf_lines:
        if y < 50:
            break
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_lines.append(f"1 0 0 1 50 {y} Tm")
        stream_lines.append(f"({escaped}) Tj")
        y -= 14
    stream_lines.append("ET")
    stream_content = "\n".join(stream_lines)

    objects: list[str] = []
    objects.append("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj")
    objects.append("2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj")
    objects.append(
        "3 0 obj\n<< /Type /Page /Parent 2 0 R "
        "/MediaBox [0 0 612 792] "
        "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj"
    )
    objects.append(
        f"4 0 obj\n<< /Length {len(stream_content)} >>\nstream\n{stream_content}\nendstream\nendobj"
    )
    objects.append("5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>\nendobj")

    pdf_parts = ["%PDF-1.4\n"]
    offsets = []
    for obj in objects:
        offsets.append(len("".join(pdf_parts)))
        pdf_parts.append(obj + "\n")

    xref_offset = len("".join(pdf_parts))
    pdf_parts.append("xref\n")
    pdf_parts.append(f"0 {len(objects) + 1}\n")
    pdf_parts.append("0000000000 65535 f \n")
    for offset in offsets:
        pdf_parts.append(f"{offset:010d} 00000 n \n")

    pdf_parts.append("trailer\n")
    pdf_parts.append(f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n")
    pdf_parts.append("startxref\n")
    pdf_parts.append(f"{xref_offset}\n")
    pdf_parts.append("%%EOF\n")

    return "".join(pdf_parts).encode("ascii")


def _build_text_fallback_pdf(
    text: str,
    *,
    receipt_id: str,
    include_header_footer: bool,
) -> bytes:
    """Render a readable fallback PDF without WeasyPrint native libraries."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        return _build_minimal_pdf(text)

    pages = _paginate_pdf_text(text)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    header_id = receipt_id[:16] + ("..." if len(receipt_id) > 16 else "")

    for page_number, page_lines in enumerate(pages, start=1):
        if include_header_footer:
            pdf.setFont("Helvetica-Bold", 11)
            pdf.drawString(40, height - 32, "Decision Receipt")
            pdf.setFont("Courier", 9)
            pdf.drawRightString(width - 40, height - 32, header_id)

        text_object = pdf.beginText(40, height - (56 if include_header_footer else 40))
        text_object.setFont("Courier", 9.5)
        text_object.setLeading(12)
        for line in page_lines:
            text_object.textLine(line)
        pdf.drawText(text_object)

        if include_header_footer:
            pdf.setFont("Helvetica", 9)
            pdf.drawCentredString(width / 2, 24, f"Page {page_number} of {len(pages)}")
            pdf.drawRightString(width - 40, 24, "Generated by Aragora")

        if page_number != len(pages):
            pdf.showPage()

    pdf.save()
    return buffer.getvalue()


def _load_weasyprint() -> Any:
    """Load WeasyPrint lazily so tests can patch only this import seam."""
    return importlib.import_module("weasyprint")


@dataclass
class DecisionReceipt:
    """
    Audit-ready decision receipt from a Gauntlet stress-test.

    This is the primary compliance artifact - a self-contained record
    of the validation process that can be stored, audited, and referenced.

    Attributes:
        receipt_id: Unique identifier for this receipt
        timestamp: When the decision was made
        input_summary: Brief description of what was tested
        verdict: Final recommendation (APPROVED, REJECTED, etc.)
        confidence: 0-1 confidence in the verdict
        risk_level: Overall risk classification

        findings: All findings from the stress-test
        mitigations: Recommended mitigations
        dissenting_views: Agents who disagreed
        unresolved_tensions: Issues not fully resolved

        verified_claims: Claims that were formally verified
        unverified_claims: Claims that could not be verified

        agents_involved: Which agents participated
        rounds_completed: How many rounds of analysis
        duration_seconds: Total analysis time
        checksum: Integrity hash for tamper detection
    """

    # Identifiers
    receipt_id: str
    gauntlet_id: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Input context
    input_summary: str = ""
    input_type: str = "spec"

    # Schema version for forward compatibility
    schema_version: str = "1.0"

    # Core verdict - uses Verdict enum values; accepts plain strings for backward compat
    verdict: str = Verdict.NEEDS_REVIEW.value.upper()  # See aragora.core_types.Verdict
    confidence: float = 0.0
    risk_level: str = "MEDIUM"  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    risk_score: float = 0.0

    # Scores
    robustness_score: float = 0.0
    coverage_score: float = 0.0
    verification_coverage: float = 0.0

    # Findings
    findings: list[ReceiptFinding] = field(default_factory=list)
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0

    # Mitigations
    mitigations: list[str] = field(default_factory=list)

    # Dissent & tensions
    dissenting_views: list[ReceiptDissent] = field(default_factory=list)
    unresolved_tensions: list[str] = field(default_factory=list)

    # Verification
    verified_claims: list[ReceiptVerification] = field(default_factory=list)
    unverified_claims: list[str] = field(default_factory=list)

    # Audit metadata
    agents_involved: list[str] = field(default_factory=list)
    rounds_completed: int = 0
    duration_seconds: float = 0.0

    # Cross-reference to audit trail (bidirectional link)
    audit_trail_id: str | None = None

    # Integrity
    checksum: str = ""

    # Cost/usage data (optional, populated if cost tracking enabled)
    cost_usd: float = 0.0
    tokens_used: int = 0
    budget_limit_usd: float | None = None
    cost_summary: dict[str, Any] | None = None

    def __post_init__(self):
        if not self.checksum:
            self.checksum = self._compute_checksum()

    def _compute_checksum(self) -> str:
        """Compute integrity checksum."""
        content = json.dumps(
            {
                "receipt_id": self.receipt_id,
                "verdict": self.verdict,
                "confidence": self.confidence,
                "findings_count": len(self.findings),
                "critical_count": self.critical_count,
                "timestamp": self.timestamp,
                "audit_trail_id": self.audit_trail_id,
            },
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def verify_integrity(self) -> bool:
        """Verify the receipt hasn't been tampered with."""
        return self.checksum == self._compute_checksum()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "receipt_id": self.receipt_id,
            "gauntlet_id": self.gauntlet_id,
            "timestamp": self.timestamp,
            "input_summary": self.input_summary,
            "input_type": self.input_type,
            "schema_version": self.schema_version,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "robustness_score": self.robustness_score,
            "coverage_score": self.coverage_score,
            "verification_coverage": self.verification_coverage,
            "findings": [asdict(f) for f in self.findings],
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
            "mitigations": self.mitigations,
            "dissenting_views": [asdict(d) for d in self.dissenting_views],
            "unresolved_tensions": self.unresolved_tensions,
            "verified_claims": [asdict(v) for v in self.verified_claims],
            "unverified_claims": self.unverified_claims,
            "agents_involved": self.agents_involved,
            "rounds_completed": self.rounds_completed,
            "duration_seconds": self.duration_seconds,
            "audit_trail_id": self.audit_trail_id,
            "checksum": self.checksum,
            "cost_usd": self.cost_usd,
            "tokens_used": self.tokens_used,
            "budget_limit_usd": self.budget_limit_usd,
            "cost_summary": self.cost_summary,
        }

    def to_json(self, indent: int = 2) -> str:
        """Export as JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_markdown(self) -> str:
        """Export as Markdown document."""
        lines = [
            "# Decision Receipt",
            "",
            f"**Receipt ID:** `{self.receipt_id}`",
            f"**Gauntlet ID:** `{self.gauntlet_id}`",
            f"**Generated:** {self.timestamp}",
            f"**Checksum:** `{self.checksum}`",
            "",
            "---",
            "",
            "## Verdict",
            "",
            f"### {self.verdict}",
            "",
            f"**Confidence:** {self.confidence:.0%}",
            f"**Risk Level:** {self.risk_level}",
            f"**Risk Score:** {self.risk_score:.0%}",
            "",
            "### Scores",
            "",
            "| Metric | Score |",
            "|--------|-------|",
            f"| Robustness | {self.robustness_score:.0%} |",
            f"| Coverage | {self.coverage_score:.0%} |",
            f"| Verification | {self.verification_coverage:.0%} |",
            "",
            "---",
            "",
            "## Input",
            "",
            f"**Type:** {self.input_type}",
            "",
            "```",
            self.input_summary[:1000] + ("..." if len(self.input_summary) > 1000 else ""),
            "```",
            "",
            "---",
            "",
            "## Findings Summary",
            "",
            "| Severity | Count |",
            "|----------|-------|",
            f"| Critical | {self.critical_count} |",
            f"| High | {self.high_count} |",
            f"| Medium | {self.medium_count} |",
            f"| Low | {self.low_count} |",
            f"| **Total** | **{len(self.findings)}** |",
            "",
        ]

        # Critical findings
        critical = [f for f in self.findings if f.severity == "CRITICAL"]
        if critical:
            lines.extend(
                [
                    "### Critical Issues",
                    "",
                ]
            )
            for f in critical:
                lines.extend(
                    [
                        f"#### {f.title}",
                        "",
                        f.description,
                        "",
                        f"**Source:** {f.source}",
                    ]
                )
                if f.mitigation:
                    lines.append(f"**Mitigation:** {f.mitigation}")
                if f.verified:
                    lines.append("**Status:** Formally verified")
                lines.append("")

        # High findings
        high = [f for f in self.findings if f.severity == "HIGH"]
        if high:
            lines.extend(
                [
                    "### High-Severity Issues",
                    "",
                ]
            )
            for f in high:
                lines.extend(
                    [
                        f"- **{f.title}**: {f.description[:200]}{'...' if len(f.description) > 200 else ''}",
                    ]
                )
            lines.append("")

        # Mitigations
        if self.mitigations:
            lines.extend(
                [
                    "---",
                    "",
                    "## Recommended Mitigations",
                    "",
                ]
            )
            for m in self.mitigations:
                lines.append(f"- {m}")
            lines.append("")

        lines.extend(_render_cost_summary_markdown(self.cost_summary))

        # Dissenting views
        if self.dissenting_views:
            lines.extend(
                [
                    "---",
                    "",
                    "## Dissenting Views",
                    "",
                ]
            )
            for d in self.dissenting_views:
                lines.extend(
                    [
                        f"### {d.agent}",
                        f"**Type:** {d.type}",
                        f"**Severity:** {d.severity:.0%}",
                        "",
                        "**Reasons:**",
                    ]
                )
                for r in d.reasons:
                    lines.append(f"- {r}")
                if d.alternative:
                    lines.append(f"\n**Alternative view:** {d.alternative}")
                lines.append("")

        # Unresolved tensions
        if self.unresolved_tensions:
            lines.extend(
                [
                    "---",
                    "",
                    "## Unresolved Tensions",
                    "",
                ]
            )
            for t in self.unresolved_tensions:
                lines.append(f"- {t}")
            lines.append("")

        # Verification results
        if self.verified_claims or self.unverified_claims:
            lines.extend(
                [
                    "---",
                    "",
                    "## Verification Results",
                    "",
                    f"**Coverage:** {self.verification_coverage:.0%}",
                    "",
                ]
            )

            if self.verified_claims:
                lines.append("### Verified Claims")
                lines.append("")
                for v in self.verified_claims:
                    status = "VERIFIED" if v.verified else "REFUTED"
                    lines.append(
                        f"- [{status}] {v.claim[:100]}{'...' if len(v.claim) > 100 else ''}"
                    )
                    if v.proof_hash:
                        lines.append(f"  - Proof: `{v.proof_hash}`")
                lines.append("")

            if self.unverified_claims:
                lines.append("### Unverified Claims")
                lines.append("")
                for c in self.unverified_claims[:10]:
                    lines.append(f"- {c[:100]}{'...' if len(c) > 100 else ''}")
                if len(self.unverified_claims) > 10:
                    lines.append(f"- ... and {len(self.unverified_claims) - 10} more")
                lines.append("")

        # Audit trail
        lines.extend(
            [
                "---",
                "",
                "## Audit Trail",
                "",
                f"**Agents:** {', '.join(agent_display_names(self.agents_involved))}",
                f"**Rounds:** {self.rounds_completed}",
                f"**Duration:** {self.duration_seconds:.1f}s",
                "",
                "---",
                "",
                "*This receipt was generated by Aragora Gauntlet.*",
                f"*Integrity checksum: `{self.checksum}`*",
            ]
        )

        return "\n".join(lines)

    def to_html(self) -> str:
        """Export as self-contained HTML document."""
        _verdict_colors = {
            Verdict.APPROVED.value: "#28a745",
            Verdict.APPROVED_WITH_CONDITIONS.value: "#ffc107",
            Verdict.NEEDS_REVIEW.value: "#fd7e14",
            Verdict.REJECTED.value: "#dc3545",
        }
        verdict_color = _verdict_colors.get(self.verdict.lower() if self.verdict else "", "#6c757d")

        findings_html = ""
        for f in self.findings:
            severity_color = {
                "CRITICAL": "#dc3545",
                "HIGH": "#fd7e14",
                "MEDIUM": "#ffc107",
                "LOW": "#28a745",
            }.get(f.severity, "#6c757d")

            esc = html_mod.escape
            findings_html += f"""
            <div class="finding" style="border-left: 4px solid {severity_color}; padding: 10px; margin: 10px 0; background: #f8f9fa;">
                <strong style="color: {severity_color};">[{esc(f.severity)}]</strong> {esc(f.title)}
                <p>{esc(f.description)}</p>
                {f"<p><em>Mitigation: {esc(f.mitigation)}</em></p>" if f.mitigation else ""}
            </div>
            """

        cost_summary_html = _render_cost_summary_html(self.cost_summary)
        esc = html_mod.escape
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Decision Receipt - {esc(self.receipt_id)}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #333; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
        .verdict {{ font-size: 24px; font-weight: bold; color: {verdict_color}; margin: 20px 0; padding: 20px; background: #f8f9fa; border-radius: 8px; }}
        .scores {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin: 20px 0; }}
        .score {{ text-align: center; padding: 15px; background: #f8f9fa; border-radius: 8px; }}
        .score-value {{ font-size: 32px; font-weight: bold; color: #333; }}
        .score-label {{ font-size: 14px; color: #666; }}
        .section {{ margin: 30px 0; }}
        .finding {{ margin: 10px 0; padding: 10px; background: #f8f9fa; border-left: 4px solid #ccc; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; }}
        .checksum {{ font-family: monospace; font-size: 12px; color: #666; }}
        .meta {{ font-size: 14px; color: #666; }}
    </style>
</head>
<body>
    <h1>Decision Receipt</h1>
    <p class="meta">
        <strong>Receipt ID:</strong> <code>{esc(self.receipt_id)}</code><br>
        <strong>Generated:</strong> {esc(str(self.timestamp))}<br>
        <strong>Input Type:</strong> {esc(self.input_type)}
    </p>

    <div class="verdict">
        VERDICT: {esc(self.verdict)}
        <div style="font-size: 16px; font-weight: normal; margin-top: 10px;">
            Confidence: {self.confidence:.0%} | Risk Level: {esc(self.risk_level)}
        </div>
    </div>

    <div class="scores">
        <div class="score">
            <div class="score-value">{self.robustness_score:.0%}</div>
            <div class="score-label">Robustness</div>
        </div>
        <div class="score">
            <div class="score-value">{self.coverage_score:.0%}</div>
            <div class="score-label">Coverage</div>
        </div>
        <div class="score">
            <div class="score-value">{self.verification_coverage:.0%}</div>
            <div class="score-label">Verification</div>
        </div>
    </div>

    <div class="section">
        <h2>Findings Summary</h2>
        <table>
            <tr><th>Severity</th><th>Count</th></tr>
            <tr><td style="color: #dc3545;">Critical</td><td>{self.critical_count}</td></tr>
            <tr><td style="color: #fd7e14;">High</td><td>{self.high_count}</td></tr>
            <tr><td style="color: #ffc107;">Medium</td><td>{self.medium_count}</td></tr>
            <tr><td style="color: #28a745;">Low</td><td>{self.low_count}</td></tr>
        </table>
    </div>

    <div class="section">
        <h2>All Findings</h2>
        {findings_html if findings_html else "<p>No findings.</p>"}
    </div>

    {cost_summary_html}

    <div class="section">
        <h2>Audit Trail</h2>
        <p><strong>Agents:</strong> {esc(", ".join(agent_display_names(self.agents_involved)))}</p>
        <p><strong>Duration:</strong> {self.duration_seconds:.1f}s</p>
        <p><strong>Rounds:</strong> {self.rounds_completed}</p>
    </div>

    <hr>
    <p class="checksum">
        Integrity Checksum: <code>{esc(self.checksum)}</code><br>
        Generated by Aragora Gauntlet
    </p>
</body>
</html>"""

    def to_pdf(self, include_header_footer: bool = True) -> bytes:
        """Export as PDF document with professional formatting.

        Prefers WeasyPrint when its Python package and native libraries are
        available. Falls back to a readable text PDF when they are not.

        Args:
            include_header_footer: Whether to include page headers and footers

        Returns:
            PDF bytes
        """
        try:
            # weasyprint does not ship type stubs; import dynamically
            _weasyprint: Any = _load_weasyprint()
            HTML = _weasyprint.HTML
            CSS = _weasyprint.CSS

            pdf_styles = """
            @page {
                size: A4;
                margin: 2cm 1.5cm 2.5cm 1.5cm;
            }
            """

            if include_header_footer:
                pdf_styles += f"""
                @page {{
                    @top-left {{
                        content: "Decision Receipt";
                        font-size: 10px;
                        color: #666;
                    }}
                    @top-right {{
                        content: "{self.receipt_id[:16]}...";
                        font-size: 10px;
                        color: #666;
                        font-family: monospace;
                    }}
                    @bottom-center {{
                        content: "Page " counter(page) " of " counter(pages);
                        font-size: 10px;
                        color: #666;
                    }}
                    @bottom-right {{
                        content: "Generated by Aragora";
                        font-size: 9px;
                        color: #999;
                    }}
                }}
                """

            pdf_styles += """
            body {
                font-size: 11pt;
                line-height: 1.4;
            }
            h1 { font-size: 18pt; page-break-after: avoid; }
            h2 { font-size: 14pt; page-break-after: avoid; margin-top: 20pt; }
            .verdict { page-break-inside: avoid; }
            .finding { page-break-inside: avoid; }
            .scores { page-break-inside: avoid; }
            table { page-break-inside: avoid; }
            """

            html_content = self.to_html()
            html_doc = HTML(string=html_content)
            css_doc = CSS(string=pdf_styles)
            return html_doc.write_pdf(stylesheets=[css_doc])
        except (ImportError, OSError):
            return _build_text_fallback_pdf(
                self.to_markdown(),
                receipt_id=self.receipt_id,
                include_header_footer=include_header_footer,
            )

    def to_csv(self) -> str:
        """Export findings as CSV format.

        Returns:
            CSV string with findings data
        """
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(
            [
                "Receipt ID",
                "Timestamp",
                "Verdict",
                "Confidence",
                "Risk Level",
                "Finding ID",
                "Severity",
                "Title",
                "Description",
                "Mitigation",
                "Category",
            ]
        )

        # Write one row per finding
        for f in self.findings:
            writer.writerow(
                [
                    self.receipt_id,
                    self.timestamp,
                    self.verdict,
                    f"{self.confidence:.2f}",
                    self.risk_level,
                    f.id,
                    f.severity,
                    f.title,
                    f.description,
                    f.mitigation or "",
                    f.category,
                ]
            )

        # If no findings, write a summary row
        if not self.findings:
            writer.writerow(
                [
                    self.receipt_id,
                    self.timestamp,
                    self.verdict,
                    f"{self.confidence:.2f}",
                    self.risk_level,
                    "",
                    "",
                    "No findings",
                    "",
                    "",
                    "",
                ]
            )

        return output.getvalue()

    def to_sarif(self) -> dict[str, Any]:
        """Export as SARIF 2.1.0 format.

        SARIF (Static Analysis Results Interchange Format) is the OASIS standard
        for exchanging static analysis results. This enables interoperability with:
        - GitHub Security (code scanning)
        - Azure DevOps
        - VS Code SARIF Viewer
        - SonarQube
        - DefectDojo

        Returns:
            SARIF 2.1.0 compliant dictionary
        """
        import hashlib

        # Map severity to SARIF levels
        sarif_level_map = {
            "CRITICAL": "error",
            "HIGH": "error",
            "MEDIUM": "warning",
            "LOW": "note",
            "critical": "error",
            "high": "error",
            "medium": "warning",
            "low": "note",
        }

        # Map severity to SARIF security-severity scores (CVSS-like)
        sarif_severity_map = {
            "CRITICAL": "9.0",
            "HIGH": "7.0",
            "MEDIUM": "4.0",
            "LOW": "1.0",
            "critical": "9.0",
            "high": "7.0",
            "medium": "4.0",
            "low": "1.0",
        }

        # Build rules from unique finding categories
        rules: list[dict[str, Any]] = []
        rule_ids: dict[str, int] = {}

        for finding in self.findings:
            category = finding.category or "general"
            if category not in rule_ids:
                rule_id = f"ARAGORA-{len(rule_ids) + 1:03d}"
                rule_ids[category] = len(rules)
                rules.append(
                    {
                        "id": rule_id,
                        "name": category.replace("_", " ").replace("-", " ").title(),
                        "shortDescription": {"text": f"Aragora Decision Receipt: {category}"},
                        "fullDescription": {"text": f"Finding in category: {category}"},
                        "helpUri": "https://aragora.ai/docs/receipts",
                        "properties": {
                            "security-severity": sarif_severity_map.get(finding.severity, "4.0"),
                            "tags": ["decision", "aragora", category],
                        },
                    }
                )

        # Build results from findings
        results = []
        for finding in self.findings:
            category = finding.category or "general"
            severity = finding.severity or "MEDIUM"
            rule_idx = rule_ids.get(category, 0)
            rule_id = rules[rule_idx]["id"] if rule_idx < len(rules) else "ARAGORA-000"

            # Create unique fingerprint for the finding
            fingerprint_input = f"{finding.title}:{finding.description}:{finding.source}"
            fingerprint = hashlib.sha256(fingerprint_input.encode()).hexdigest()[:32]

            result: dict[str, Any] = {
                "ruleId": rule_id,
                "ruleIndex": rule_idx,
                "level": sarif_level_map.get(severity, "warning"),
                "message": {"text": finding.description or finding.title},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": f"receipt/{self.receipt_id[:8]}",
                                "uriBaseId": "RECEIPT_ROOT",
                            }
                        },
                        "logicalLocations": [
                            {
                                "name": finding.title,
                                "kind": "finding",
                            }
                        ],
                    }
                ],
                "fingerprints": {"aragora/v1": fingerprint},
                "properties": {
                    "receipt_id": self.receipt_id,
                    "category": category,
                    "severity": severity,
                    "source": finding.source,
                    "verified": finding.verified,
                },
            }

            # Add mitigation if present
            if finding.mitigation:
                result["fixes"] = [{"description": {"text": finding.mitigation}}]

            results.append(result)

        # Build SARIF document
        sarif: dict[str, Any] = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "Aragora Decision Receipt",
                            "version": "1.0.0",
                            "informationUri": "https://aragora.ai/receipts",
                            "rules": rules,
                            "properties": {
                                "verdict": self.verdict,
                                "confidence": self.confidence,
                                "risk_level": self.risk_level,
                            },
                        }
                    },
                    "results": results,
                    "invocations": [
                        {
                            "executionSuccessful": True,
                            "endTimeUtc": self.timestamp,
                            "properties": {
                                "receipt_id": self.receipt_id,
                                "gauntlet_id": self.gauntlet_id,
                                "input_summary": self.input_summary[:200]
                                if self.input_summary
                                else None,
                            },
                        }
                    ],
                    "properties": {
                        "summary": self.input_summary,
                        "risk_level": self.risk_level,
                        "verified_claims_count": len(self.verified_claims),
                        "dissenting_views_count": len(self.dissenting_views),
                    },
                }
            ],
        }

        return sarif

    def to_sarif_json(self, indent: int = 2) -> str:
        """Export as SARIF JSON string."""
        return json.dumps(self.to_sarif(), indent=indent)

    def save(self, path: Path, format: str = "json") -> Path:
        """
        Save receipt to file.

        Args:
            path: Output path (extension will be adjusted if needed)
            format: Output format ("json", "md", "html", "csv", "sarif", "pdf")

        Returns:
            Path to saved file
        """
        if format == "json":
            output_path = path.with_suffix(".json")
            output_path.write_text(self.to_json())
        elif format == "md" or format == "markdown":
            output_path = path.with_suffix(".md")
            output_path.write_text(self.to_markdown())
        elif format == "html":
            output_path = path.with_suffix(".html")
            output_path.write_text(self.to_html())
        elif format == "csv":
            output_path = path.with_suffix(".csv")
            output_path.write_text(self.to_csv())
        elif format == "sarif":
            output_path = path.with_suffix(".sarif.json")
            output_path.write_text(self.to_sarif_json())
        elif format == "pdf":
            output_path = path.with_suffix(".pdf")
            output_path.write_bytes(self.to_pdf())
        else:
            raise ValueError(
                f"Unknown format: {format}. Supported: json, md, html, csv, sarif, pdf"
            )

        return output_path

    @classmethod
    def from_json(cls, json_str: str) -> DecisionReceipt:
        """Load receipt from JSON string."""
        data = json.loads(json_str)

        # Convert nested dicts back to dataclasses
        findings = [ReceiptFinding(**f) for f in data.pop("findings", [])]
        dissenting_views = [ReceiptDissent(**d) for d in data.pop("dissenting_views", [])]
        verified_claims = [ReceiptVerification(**v) for v in data.pop("verified_claims", [])]

        return cls(
            findings=findings,
            dissenting_views=dissenting_views,
            verified_claims=verified_claims,
            **data,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionReceipt:
        """Load receipt from dictionary.

        Args:
            data: Dictionary representation of the receipt

        Returns:
            DecisionReceipt instance
        """
        # Make a copy to avoid mutating the input
        data = dict(data)

        # Convert nested dicts back to dataclasses
        findings = [ReceiptFinding(**f) for f in data.pop("findings", [])]
        dissenting_views = [ReceiptDissent(**d) for d in data.pop("dissenting_views", [])]
        verified_claims = [ReceiptVerification(**v) for v in data.pop("verified_claims", [])]

        return cls(
            findings=findings,
            dissenting_views=dissenting_views,
            verified_claims=verified_claims,
            **data,
        )

    def sign(self, backend: Any | None = None) -> SignedDecisionReceipt:
        """
        Sign this receipt cryptographically for tamper-evidence.

        Args:
            backend: Signing backend to use. Defaults to HMAC-SHA256 from env.

        Returns:
            SignedDecisionReceipt with signature and metadata

        Example:
            signed = receipt.sign()
            is_valid = signed.verify()
            signed_json = signed.to_json()
        """
        from aragora.gauntlet.signing import HMACSigner, ReceiptSigner

        signer = ReceiptSigner(backend or HMACSigner.from_env())
        signed = signer.sign(self.to_dict())

        return SignedDecisionReceipt(
            receipt=self,
            signature=signed.signature,
            signature_algorithm=signed.signature_metadata.algorithm,
            signature_key_id=signed.signature_metadata.key_id,
            signed_at=signed.signature_metadata.timestamp,
        )

    @classmethod
    def load(cls, path: Path) -> DecisionReceipt:
        """Load receipt from file."""
        return cls.from_json(path.read_text())

    @classmethod
    def from_debate_result(
        cls,
        result: DebateResult,
        include_cost: bool = True,
        cost_data: dict[str, Any] | None = None,
        cost_summary: dict[str, Any] | None = None,
    ) -> DecisionReceipt:
        """
        Generate a DecisionReceipt from a standard DebateResult.

        Unlike from_gauntlet_result which uses full Gauntlet stress-test data,
        this creates a receipt from a regular debate for audit purposes.

        Args:
            result: The DebateResult from a completed debate
            include_cost: Whether to include cost data in the receipt
            cost_data: Optional dict with cost_usd, tokens_used, budget_limit_usd
            cost_summary: Optional rich breakdown dict with per-agent/model totals

        Returns:
            DecisionReceipt suitable for audit trail

        Example:
            result = await arena.run()
            receipt = DecisionReceipt.from_debate_result(result)
            receipt.save(Path("./receipts/debate.json"), format="json")
        """
        from datetime import timezone

        receipt_id = f"rcpt_{uuid.uuid4().hex[:12]}"

        # Map confidence to verdict (use canonical Verdict enum values)
        if result.confidence >= 0.9:
            verdict = Verdict.APPROVED.value
        elif result.confidence >= 0.7:
            verdict = Verdict.APPROVED_WITH_CONDITIONS.value
        elif result.confidence >= 0.5:
            verdict = Verdict.NEEDS_REVIEW.value
        else:
            verdict = Verdict.REJECTED.value
        verdict = verdict.upper()

        # Map confidence to risk (inverse relationship)
        risk_score = 1.0 - result.confidence
        if risk_score < 0.3:
            risk_level = "LOW"
        elif risk_score < 0.6:
            risk_level = "MEDIUM"
        elif risk_score < 0.8:
            risk_level = "HIGH"
        else:
            risk_level = "CRITICAL"

        # Extract cost data from result or provided cost_data
        cost_usd = 0.0
        tokens_used = 0
        budget_limit_usd = None
        normalized_cost_summary: dict[str, Any] | None = None

        if include_cost:
            if isinstance(cost_summary, dict):
                normalized_cost_summary = cost_summary
            elif isinstance(cost_data, dict) and (
                "per_agent" in cost_data
                or "per_round" in cost_data
                or "model_usage" in cost_data
                or "total_cost_usd" in cost_data
            ):
                normalized_cost_summary = cost_data
            elif isinstance(getattr(result, "cost_summary", None), dict):
                normalized_cost_summary = result.cost_summary

            if normalized_cost_summary:
                cost_usd = _coerce_float(normalized_cost_summary.get("total_cost_usd"), 0.0)
                tokens_used = _coerce_int(
                    normalized_cost_summary.get("total_tokens_in")
                ) + _coerce_int(normalized_cost_summary.get("total_tokens_out"))
            elif cost_data:
                cost_usd = _coerce_float(cost_data.get("cost_usd"), 0.0)
                tokens_used = _coerce_int(cost_data.get("tokens_used"), 0)
                budget_limit_usd = cost_data.get("budget_limit_usd")
            elif hasattr(result, "total_cost_usd"):
                cost_usd = _coerce_float(getattr(result, "total_cost_usd", 0.0), 0.0)
                tokens_used = _coerce_int(getattr(result, "total_tokens", 0), 0)
                budget_limit_usd = getattr(result, "budget_limit_usd", None)

        # Convert critiques to findings (high severity by default)
        findings = []
        for critique in result.critiques:
            for idx, issue in enumerate(critique.issues):
                findings.append(
                    ReceiptFinding(
                        id=f"crit_{critique.agent}_{idx}",
                        severity=(
                            "HIGH"
                            if critique.severity >= 7
                            else "MEDIUM"
                            if critique.severity >= 4
                            else "LOW"
                        ),
                        category="critique",
                        title=f"Critique from {critique.agent}",
                        description=issue,
                        mitigation=(
                            critique.suggestions[idx] if idx < len(critique.suggestions) else None
                        ),
                        source=critique.agent,
                        verified=False,
                    )
                )

        # Count findings by severity
        critical_count = len([f for f in findings if f.severity == "CRITICAL"])
        high_count = len([f for f in findings if f.severity == "HIGH"])
        medium_count = len([f for f in findings if f.severity == "MEDIUM"])
        low_count = len([f for f in findings if f.severity == "LOW"])

        # Convert dissenting views
        dissents = []
        for view in result.dissenting_views:
            dissents.append(
                ReceiptDissent(
                    agent="unknown",  # Dissenting views are strings in DebateResult
                    type="dissent",
                    severity=0.5,
                    reasons=[view],
                    alternative=None,
                )
            )

        return cls(
            receipt_id=receipt_id,
            gauntlet_id=result.debate_id or result.id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            input_summary=result.task[:500] if result.task else "",
            input_type="debate",
            verdict=verdict,
            confidence=result.confidence,
            risk_level=risk_level,
            risk_score=risk_score,
            robustness_score=result.confidence,  # Use confidence as proxy
            coverage_score=1.0 if result.consensus_reached else 0.5,
            verification_coverage=0.0,  # No formal verification in regular debates
            findings=findings,
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count,
            mitigations=[],  # No structured mitigations in regular debates
            dissenting_views=dissents,
            unresolved_tensions=[],
            verified_claims=[],
            unverified_claims=[],
            agents_involved=result.participants,
            rounds_completed=result.rounds_completed,
            duration_seconds=result.duration_seconds,
            cost_usd=cost_usd,
            tokens_used=tokens_used,
            budget_limit_usd=budget_limit_usd,
            cost_summary=normalized_cost_summary,
        )


class DecisionReceiptGenerator:
    """
    Generates Decision Receipts from Gauntlet results.

    Transforms the detailed GauntletResult into a clean,
    audit-ready DecisionReceipt.
    """

    @staticmethod
    def from_gauntlet_result(result: GauntletResult) -> DecisionReceipt:
        """
        Generate a DecisionReceipt from a GauntletResult.

        Args:
            result: The GauntletResult to convert

        Returns:
            A DecisionReceipt ready for export
        """

        # Convert findings
        findings = []
        for f in result.all_findings:
            findings.append(
                ReceiptFinding(
                    id=f.finding_id,
                    severity=f.severity_level,
                    category=f.category,
                    title=f.title,
                    description=f.description,
                    mitigation=f.mitigation,
                    source=f.source,
                    verified=f.verified,
                )
            )

        # Convert dissenting views
        dissents = []
        for d in result.dissenting_views:
            dissents.append(
                ReceiptDissent(
                    agent=d.agent,
                    type=d.dissent_type,
                    severity=d.severity,
                    reasons=d.reasons,
                    alternative=d.alternative_view,
                )
            )

        # Convert verified claims
        verified = []
        for v in result.verified_claims:
            verified.append(
                ReceiptVerification(
                    claim=v.claim,
                    verified=v.verified,
                    method=v.verification_method,
                    proof_hash=v.proof_hash,
                )
            )

        # Extract mitigations from findings
        mitigations = list(set(f.mitigation for f in result.all_findings if f.mitigation))

        # Determine risk level from score
        if result.risk_score >= 0.8:
            risk_level = "CRITICAL"
        elif result.risk_score >= 0.6:
            risk_level = "HIGH"
        elif result.risk_score >= 0.3:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        # Determine rounds from sub-results
        rounds = 0
        if result.audit_verdict:
            rounds = len(result.audit_verdict.findings)
        if result.redteam_result:
            rounds = max(rounds, len(result.redteam_result.rounds))

        return DecisionReceipt(
            receipt_id=str(uuid.uuid4()),
            gauntlet_id=result.gauntlet_id,
            timestamp=result.created_at,
            input_summary=result.input_summary,
            input_type=result.input_type.value,
            verdict=result.verdict.value.upper(),
            confidence=result.confidence,
            risk_level=risk_level,
            risk_score=result.risk_score,
            robustness_score=result.robustness_score,
            coverage_score=result.coverage_score,
            verification_coverage=result.verification_coverage,
            findings=findings,
            critical_count=len(result.critical_findings),
            high_count=len(result.high_findings),
            medium_count=len(result.medium_findings),
            low_count=len(result.low_findings),
            mitigations=mitigations,
            dissenting_views=dissents,
            unresolved_tensions=[t.description for t in result.unresolved_tensions],
            verified_claims=verified,
            unverified_claims=result.unverified_claims,
            agents_involved=result.agents_involved,
            rounds_completed=rounds,
            duration_seconds=result.duration_seconds,
        )


def generate_decision_receipt(result: GauntletResult) -> DecisionReceipt:
    """
    Convenience function to generate a DecisionReceipt.

    Args:
        result: GauntletResult from a Gauntlet stress-test

    Returns:
        DecisionReceipt ready for export

    Example:
        result = await run_gauntlet(spec, agents)
        receipt = generate_decision_receipt(result)
        receipt.save(Path("./receipts/decision.html"), format="html")
    """
    return DecisionReceiptGenerator.from_gauntlet_result(result)


def link_receipt_to_trail(
    receipt: DecisionReceipt,
    trail: AuditTrail,
) -> tuple[DecisionReceipt, AuditTrail]:
    """
    Link a DecisionReceipt and AuditTrail bidirectionally.

    Creates cross-references between the receipt and trail for:
    - Compliance auditing (trace from receipt to full event log)
    - Evidence chain verification (trace from events to final decision)

    After linking, both checksums are recomputed to include the link.

    Args:
        receipt: The DecisionReceipt to link
        trail: The AuditTrail to link

    Returns:
        Tuple of (updated_receipt, updated_trail)

    Example:
        receipt = generate_decision_receipt(result)
        trail = generate_audit_trail(result)
        receipt, trail = link_receipt_to_trail(receipt, trail)
        # Now receipt.audit_trail_id == trail.trail_id
        # And trail.receipt_id == receipt.receipt_id
    """
    # Establish bidirectional links
    receipt.audit_trail_id = trail.trail_id
    trail.receipt_id = receipt.receipt_id

    # Recompute checksums to include the links
    receipt.checksum = receipt._compute_checksum()
    # Note: trail.checksum is a property, automatically recomputed

    return receipt, trail


@dataclass
class SignedDecisionReceipt:
    """
    A cryptographically signed decision receipt.

    Provides tamper-evidence and non-repudiation for compliance:
    - Signature proves the receipt hasn't been modified
    - Key ID identifies the signing authority
    - Timestamp records when the signature was created

    Example:
        receipt = generate_decision_receipt(result)
        signed = receipt.sign()

        # Later verification
        if signed.verify():
            print("Receipt is authentic")
    """

    receipt: DecisionReceipt
    signature: str  # Base64-encoded signature
    signature_algorithm: str
    signature_key_id: str
    signed_at: str  # ISO timestamp

    def verify(self, backend: Any | None = None) -> bool:
        """
        Verify the signature is valid.

        Args:
            backend: Signing backend to use for verification.
                     Must have same key as signing backend.

        Returns:
            True if signature is valid, False otherwise
        """
        from aragora.gauntlet.signing import (
            HMACSigner,
            ReceiptSigner,
            SignatureMetadata,
            SignedReceipt,
        )

        signer = ReceiptSigner(backend or HMACSigner.from_env())

        # Reconstruct the SignedReceipt for verification
        signed = SignedReceipt(
            receipt_data=self.receipt.to_dict(),
            signature=self.signature,
            signature_metadata=SignatureMetadata(
                algorithm=self.signature_algorithm,
                timestamp=self.signed_at,
                key_id=self.signature_key_id,
            ),
        )

        return signer.verify(signed)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "receipt": self.receipt.to_dict(),
            "signature": self.signature,
            "signature_metadata": {
                "algorithm": self.signature_algorithm,
                "key_id": self.signature_key_id,
                "signed_at": self.signed_at,
            },
        }

    def to_json(self, indent: int = 2) -> str:
        """Export as JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignedDecisionReceipt:
        """Load from dictionary."""
        receipt = DecisionReceipt.from_dict(data["receipt"])
        meta = data["signature_metadata"]

        return cls(
            receipt=receipt,
            signature=data["signature"],
            signature_algorithm=meta["algorithm"],
            signature_key_id=meta["key_id"],
            signed_at=meta["signed_at"],
        )

    @classmethod
    def from_json(cls, json_str: str) -> SignedDecisionReceipt:
        """Load from JSON string."""
        return cls.from_dict(json.loads(json_str))
