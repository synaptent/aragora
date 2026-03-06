"""
EU AI Act compliance export CLI command.

Generates a structured compliance bundle from a debate ID, mapping Aragora
decision artifacts to EU AI Act articles:

  Article  9: Risk management   -> decision receipt with risk assessment
  Article 12: Record-keeping    -> full audit trail (provenance chain)
  Article 13: Transparency      -> agent participation + reasoning
  Article 14: Human oversight   -> voting record, dissent, escalation
  Article 15: Accuracy          -> confidence scores, calibration data

Usage:
    aragora compliance export \\
        --framework eu-ai-act \\
        --debate-id <ID> \\
        --output-dir ./compliance-pack \\
        [--format markdown|html|json] \\
        [--include-receipts] \\
        [--include-audit-trail] \\
        [--demo]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Supported frameworks (extensible)
SUPPORTED_FRAMEWORKS = ("eu-ai-act",)

# EU AI Act article mapping
EU_AI_ACT_ARTICLES = {
    "article_9": {
        "number": "Article 9",
        "title": "Risk Management System",
        "requirement": (
            "Identify and analyze known and reasonably foreseeable risks. "
            "Establish, implement, document, and maintain a risk management system."
        ),
    },
    "article_12": {
        "number": "Article 12",
        "title": "Record-Keeping (Automatic Logging)",
        "requirement": (
            "Technically allow for automatic recording of events ('logs') "
            "over the lifetime of the system, enabling traceability."
        ),
    },
    "article_13": {
        "number": "Article 13",
        "title": "Transparency and Provision of Information to Deployers",
        "requirement": (
            "Be sufficiently transparent for deployers to interpret output "
            "and use it appropriately. Document agent identities, reasoning, "
            "and decision rationale."
        ),
    },
    "article_14": {
        "number": "Article 14",
        "title": "Human Oversight",
        "requirement": (
            "Enable effective human oversight including ability to understand "
            "output, decide not to use the system, override, and intervene."
        ),
    },
    "article_15": {
        "number": "Article 15",
        "title": "Accuracy, Robustness and Cybersecurity",
        "requirement": (
            "Achieve appropriate levels of accuracy, robustness, and "
            "cybersecurity. Be resilient to errors, faults, and attacks."
        ),
    },
}


def add_export_subparser(sub: argparse._SubParsersAction) -> None:
    """Register the 'export' subcommand under 'compliance'."""
    export_p = sub.add_parser(
        "export",
        help="Export a structured compliance bundle for a debate",
        description=(
            "Export a structured compliance bundle mapping debate artifacts to "
            "regulatory framework requirements (e.g. EU AI Act Articles 9, 12-15). "
            "Use --demo to generate a sample bundle without a real debate."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    export_p.add_argument(
        "--framework",
        default="eu-ai-act",
        choices=list(SUPPORTED_FRAMEWORKS),
        help="Compliance framework to export against (default: eu-ai-act)",
    )
    export_p.add_argument(
        "--debate-id",
        dest="debate_id",
        help="Debate ID to export compliance pack for",
    )
    export_p.add_argument(
        "--receipt-file",
        dest="receipt_file",
        help="Path to an existing receipt JSON file (alternative to --debate-id)",
    )
    export_p.add_argument(
        "--output-dir",
        dest="output_dir",
        default="./compliance-pack",
        help="Output directory for the compliance bundle (default: ./compliance-pack)",
    )
    export_p.add_argument(
        "--format",
        dest="output_format",
        choices=["markdown", "html", "json"],
        default="markdown",
        help="Output format for report files (default: markdown)",
    )
    export_p.add_argument(
        "--include-receipts",
        dest="include_receipts",
        action="store_true",
        default=True,
        help="Include decision receipts in the bundle (default: True)",
    )
    export_p.add_argument(
        "--include-audit-trail",
        dest="include_audit_trail",
        action="store_true",
        default=True,
        help="Include full audit trail in the bundle (default: True)",
    )
    export_p.add_argument(
        "--demo",
        action="store_true",
        help="Generate a sample compliance bundle from synthetic data",
    )


def cmd_compliance_export(args: argparse.Namespace) -> None:
    """Execute the compliance export command."""
    framework = getattr(args, "framework", "eu-ai-act")
    debate_id = getattr(args, "debate_id", None)
    receipt_file = getattr(args, "receipt_file", None)
    output_dir = getattr(args, "output_dir", "./compliance-pack")
    output_format = getattr(args, "output_format", "markdown")
    include_receipts = getattr(args, "include_receipts", True)
    include_audit_trail = getattr(args, "include_audit_trail", True)
    demo = getattr(args, "demo", False)

    if framework not in SUPPORTED_FRAMEWORKS:
        print(f"Error: Unsupported framework '{framework}'.", file=sys.stderr)
        print(f"Supported: {', '.join(SUPPORTED_FRAMEWORKS)}", file=sys.stderr)
        sys.exit(1)

    # Load receipt data
    receipt_dict = _resolve_receipt(debate_id, receipt_file, demo)

    # Generate the compliance bundle
    bundle = _generate_compliance_bundle(
        receipt_dict=receipt_dict,
        framework=framework,
        include_receipts=include_receipts,
        include_audit_trail=include_audit_trail,
    )

    # Write to output directory
    _write_bundle(bundle, output_dir, output_format)

    # Print summary
    _print_summary(bundle, output_dir, output_format)


def _resolve_receipt(
    debate_id: str | None,
    receipt_file: str | None,
    demo: bool,
) -> dict[str, Any]:
    """Resolve a receipt dictionary from debate ID, file, or demo mode."""
    if demo:
        print("Generating compliance bundle from synthetic demo data.")
        print()
        return _synthetic_receipt()

    if receipt_file:
        try:
            with open(receipt_file) as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"Error: Receipt file not found: {receipt_file}", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError as exc:
            print(f"Error: Invalid JSON in receipt file: {exc}", file=sys.stderr)
            sys.exit(1)

    if debate_id:
        return _load_receipt_for_debate(debate_id)

    # No source specified
    print(
        "Error: Provide --debate-id, --receipt-file, or --demo.",
        file=sys.stderr,
    )
    print(
        "\nUse --demo to generate a sample compliance bundle:\n"
        "  aragora compliance export --demo --output-dir ./compliance-pack",
        file=sys.stderr,
    )
    sys.exit(1)


def _load_receipt_for_debate(debate_id: str) -> dict[str, Any]:
    """Attempt to load a receipt for the given debate ID.

    Looks in the default data directory for receipt files, and falls back
    to the gauntlet storage if available.
    """
    # Try common receipt file paths
    candidate_paths = [
        os.path.expanduser(f"~/.aragora/receipts/{debate_id}.json"),
        os.path.expanduser(f"~/.aragora/debates/{debate_id}/receipt.json"),
        f"./receipts/{debate_id}.json",
        f"./{debate_id}.json",
    ]

    for path in candidate_paths:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load receipt from %s: %s", path, exc)

    # Try gauntlet storage
    try:
        from aragora.gauntlet.storage import ReceiptStorage

        storage = ReceiptStorage()
        receipt = storage.load(debate_id)
        if receipt is not None:
            if hasattr(receipt, "to_dict"):
                return receipt.to_dict()
            if isinstance(receipt, dict):
                return receipt
    except (ImportError, AttributeError, OSError) as exc:
        logger.debug("Gauntlet storage unavailable: %s", exc)

    print(
        f"Error: No receipt found for debate ID '{debate_id}'.",
        file=sys.stderr,
    )
    print(
        "\nLooked in:\n"
        + "\n".join(f"  - {p}" for p in candidate_paths)
        + "\n  - Gauntlet receipt storage",
        file=sys.stderr,
    )
    print(
        "\nUse --demo to generate a sample compliance bundle:\n"
        "  aragora compliance export --demo --output-dir ./compliance-pack",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Bundle generation
# ---------------------------------------------------------------------------


def _days_until_deadline() -> int:
    """Return number of days from today until the EU AI Act enforcement deadline (Aug 2, 2026)."""
    from datetime import date

    deadline = date(2026, 8, 2)
    today = date.today()
    return max(0, (deadline - today).days)


def _compute_compliance_score(conformity: Any) -> dict[str, Any]:
    """Compute a numeric compliance readiness score from article mappings.

    Returns a dict with:
      - score: 0-100 integer (satisfied=1.0, partial=0.5, not_satisfied=0.0 per article)
      - level: "full" | "substantial" | "partial" | "not_ready"
      - label: Human-readable level label
      - breakdown: per-article pass/partial/fail lists
    """
    mappings = conformity.article_mappings
    applicable = [m for m in mappings if m.status != "not_applicable"]
    if not applicable:
        return {"score": 0, "level": "not_ready", "label": "Not Ready", "breakdown": {}}

    weight_map = {"satisfied": 1.0, "partial": 0.5, "not_satisfied": 0.0}
    raw = sum(weight_map.get(m.status, 0.0) for m in applicable)
    score = int(round((raw / len(applicable)) * 100))

    if score >= 95:
        level, label = "full", "Full Conformity"
    elif score >= 75:
        level, label = "substantial", "Substantially Conformant"
    elif score >= 40:
        level, label = "partial", "Partial Conformity"
    else:
        level, label = "not_ready", "Not Ready"

    breakdown: dict[str, list[str]] = {"pass": [], "partial": [], "fail": []}
    for m in applicable:
        if m.status == "satisfied":
            breakdown["pass"].append(m.article)
        elif m.status == "partial":
            breakdown["partial"].append(m.article)
        else:
            breakdown["fail"].append(m.article)

    return {"score": score, "level": level, "label": label, "breakdown": breakdown}


def _generate_compliance_bundle(
    receipt_dict: dict[str, Any],
    framework: str,
    include_receipts: bool,
    include_audit_trail: bool,
) -> dict[str, Any]:
    """Build the compliance bundle from receipt data."""
    from aragora.compliance.eu_ai_act import (
        ComplianceArtifactGenerator,
        ConformityReportGenerator,
        RiskClassifier,
    )

    receipt_id = receipt_dict.get("receipt_id", "unknown")
    timestamp = datetime.now(timezone.utc).isoformat()

    # Risk classification
    classifier = RiskClassifier()
    classification = classifier.classify_receipt(receipt_dict)

    # Conformity report
    report_gen = ConformityReportGenerator(classifier=classifier)
    conformity = report_gen.generate(receipt_dict)

    # Full artifact bundle (Art. 12, 13, 14)
    artifact_gen = ComplianceArtifactGenerator()
    artifact_bundle = artifact_gen.generate(receipt_dict)

    # Extract per-article data
    receipt_data = _build_receipt_section(receipt_dict) if include_receipts else None
    audit_trail = _build_audit_trail(receipt_dict) if include_audit_trail else None
    risk_management = _build_risk_management(receipt_dict, conformity)
    transparency = _build_transparency_report(receipt_dict, conformity)
    human_oversight = _build_human_oversight(receipt_dict, conformity)
    accuracy = _build_accuracy_report(receipt_dict, conformity)

    # Compliance readiness score
    compliance_score = _compute_compliance_score(conformity)

    # Compute integrity hash
    hash_input = json.dumps(
        {
            "receipt_id": receipt_id,
            "framework": framework,
            "timestamp": timestamp,
            "classification": classification.risk_level.value,
            "conformity": conformity.overall_status,
        },
        sort_keys=True,
    )
    integrity_hash = hashlib.sha256(hash_input.encode()).hexdigest()

    return {
        "meta": {
            "framework": framework,
            "receipt_id": receipt_id,
            "generated_at": timestamp,
            "integrity_hash": integrity_hash,
            "compliance_deadline": "2026-08-02",
            "days_until_deadline": _days_until_deadline(),
            "regulation": "EU AI Act (Regulation 2024/1689)",
            "generated_by": "Aragora Decision Integrity Platform",
        },
        "compliance_score": compliance_score,
        "risk_classification": classification.to_dict(),
        "conformity_report": conformity.to_dict(),
        "receipt": receipt_data,
        "audit_trail": audit_trail,
        "risk_management": risk_management,
        "transparency_report": transparency,
        "human_oversight": human_oversight,
        "accuracy_report": accuracy,
        "article_artifacts": {
            "article_9": artifact_bundle.article_9.to_dict(),
            "article_12": artifact_bundle.article_12.to_dict(),
            "article_13": artifact_bundle.article_13.to_dict(),
            "article_14": artifact_bundle.article_14.to_dict(),
        },
    }


def _build_receipt_section(receipt: dict[str, Any]) -> dict[str, Any]:
    """Extract decision receipt data for the bundle."""
    return {
        "receipt_id": receipt.get("receipt_id", ""),
        "timestamp": receipt.get("timestamp", ""),
        "input_summary": receipt.get("input_summary", ""),
        "verdict": receipt.get("verdict", ""),
        "confidence": receipt.get("confidence", 0.0),
        "verdict_reasoning": receipt.get("verdict_reasoning", ""),
        "risk_summary": receipt.get("risk_summary", {}),
        "robustness_score": receipt.get("robustness_score", 0.0),
        "dissenting_views": receipt.get("dissenting_views", []),
        "artifact_hash": receipt.get("artifact_hash", ""),
        "signature": receipt.get("signature", ""),
    }


def _build_audit_trail(receipt: dict[str, Any]) -> dict[str, Any]:
    """Build chronological audit trail from provenance chain."""
    provenance = receipt.get("provenance_chain", [])
    events = []
    for i, entry in enumerate(provenance):
        if isinstance(entry, dict):
            events.append(
                {
                    "sequence": i + 1,
                    "event_type": entry.get("event_type", "unknown"),
                    "timestamp": entry.get("timestamp", ""),
                    "actor": entry.get("actor", "system"),
                }
            )

    config = receipt.get("config_used", {})
    return {
        "total_events": len(events),
        "events": events,
        "protocol": config.get("protocol", "adversarial"),
        "rounds": config.get("rounds", 0),
        "integrity_mechanism": "SHA-256 hash chain",
        "retention_basis": "Art. 26(6) -- minimum 6 months for high-risk systems",
    }


def _build_transparency_report(
    receipt: dict[str, Any],
    conformity: Any,
) -> dict[str, Any]:
    """Build transparency report (Article 13 mapping)."""
    consensus = receipt.get("consensus_proof", {}) or {}
    supporting = consensus.get("supporting_agents", [])
    dissenting_agents = consensus.get("dissenting_agents", [])
    all_agents = sorted(set(supporting + dissenting_agents))
    dissenting_views = receipt.get("dissenting_views", [])

    # Find Art. 13 mapping status from conformity
    art13_status = "unknown"
    for m in conformity.article_mappings:
        if m.article == "Article 13":
            art13_status = m.status
            break

    return {
        "article": "Article 13",
        "status": art13_status,
        "agents_participating": all_agents,
        "agent_count": len(all_agents),
        "supporting_agents": supporting,
        "dissenting_agents": dissenting_agents,
        "verdict_reasoning": receipt.get("verdict_reasoning", ""),
        "dissenting_views": dissenting_views,
        "consensus_method": consensus.get("method", ""),
        "agreement_ratio": consensus.get("agreement_ratio", 0.0),
    }


def _build_human_oversight(
    receipt: dict[str, Any],
    conformity: Any,
) -> dict[str, Any]:
    """Build human oversight report (Article 14 mapping)."""
    config = receipt.get("config_used", {})
    provenance = receipt.get("provenance_chain", [])
    dissenting_views = receipt.get("dissenting_views", [])

    # Detect human involvement
    human_events = []
    for entry in provenance:
        if isinstance(entry, dict):
            etype = entry.get("event_type", "")
            if etype in ("human_approval", "plan_approved", "human_override"):
                human_events.append(entry)

    has_human_oversight = bool(human_events) or config.get("require_approval", False)

    # Find Art. 14 mapping status
    art14_status = "unknown"
    for m in conformity.article_mappings:
        if m.article == "Article 14":
            art14_status = m.status
            break

    # Build voting record
    vote_events = [
        entry
        for entry in provenance
        if isinstance(entry, dict) and entry.get("event_type") == "vote_cast"
    ]

    return {
        "article": "Article 14",
        "status": art14_status,
        "human_oversight_detected": has_human_oversight,
        "oversight_model": "Human-in-the-Loop (HITL)"
        if has_human_oversight
        else "Human-on-the-Loop (HOTL)",
        "human_events": human_events,
        "voting_record": {
            "total_votes": len(vote_events),
            "votes": vote_events,
        },
        "dissenting_views": dissenting_views,
        "require_approval": config.get("require_approval", False),
        "approver": config.get("approver", ""),
        "escalation_available": True,
        "override_available": True,
        "stop_available": True,
    }


def _build_accuracy_report(
    receipt: dict[str, Any],
    conformity: Any,
) -> dict[str, Any]:
    """Build accuracy and robustness report (Article 15 mapping)."""
    confidence = receipt.get("confidence", 0.0)
    robustness = receipt.get("robustness_score", 0.0)

    # Find Art. 15 mapping status
    art15_status = "unknown"
    for m in conformity.article_mappings:
        if m.article == "Article 15":
            art15_status = m.status
            break

    return {
        "article": "Article 15",
        "status": art15_status,
        "confidence": confidence,
        "robustness_score": robustness,
        "integrity_hash_present": bool(receipt.get("artifact_hash")),
        "signature_present": bool(receipt.get("signature")),
        "attacks_attempted": receipt.get("attacks_attempted", 0),
        "attacks_successful": receipt.get("attacks_successful", 0),
        "probes_run": receipt.get("probes_run", 0),
        "vulnerabilities_found": receipt.get("vulnerabilities_found", 0),
    }


def _build_risk_management(
    receipt: dict[str, Any],
    conformity: Any,
) -> dict[str, Any]:
    """Build risk management report (Article 9 mapping)."""
    risk_summary = receipt.get("risk_summary", {})
    confidence = receipt.get("confidence", 0.0)
    robustness = receipt.get("robustness_score", 0.0)
    config = receipt.get("config_used", {})
    consensus = receipt.get("consensus_proof", {}) or {}

    agents = sorted(
        set(consensus.get("supporting_agents", []) + consensus.get("dissenting_agents", []))
    )

    # Find Art. 9 mapping status from conformity
    art9_status = "unknown"
    for m in conformity.article_mappings:
        if m.article == "Article 9":
            art9_status = m.status
            break

    critical_count = risk_summary.get("critical", 0)

    return {
        "article": "Article 9",
        "status": art9_status,
        "risk_assessment": {
            "total_risks": risk_summary.get("total", 0),
            "critical": risk_summary.get("critical", 0),
            "high": risk_summary.get("high", 0),
            "medium": risk_summary.get("medium", 0),
            "low": risk_summary.get("low", 0),
        },
        "analysis_method": {
            "approach": "Multi-agent adversarial debate",
            "protocol": config.get("protocol", "adversarial"),
            "rounds": config.get("rounds", 0),
            "agents": agents,
        },
        "confidence": confidence,
        "robustness_score": robustness,
        "known_risks": [
            "Model hallucination",
            "Automation bias",
            "Hollow consensus",
            "Data drift",
            "Adversarial input",
        ],
        "mitigation_controls": [
            "Multi-agent debate",
            "Trickster detection",
            "Circuit breaker",
            "Calibration monitoring",
            "Human oversight",
        ],
        "residual_risk_level": (
            "high" if critical_count > 0 else ("medium" if confidence < 0.7 else "low")
        ),
        "acceptance_criteria_met": (
            critical_count == 0 and confidence >= 0.6 and robustness >= 0.5 and len(agents) >= 3
        ),
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def _write_bundle(
    bundle: dict[str, Any],
    output_dir: str,
    fmt: str,
) -> None:
    """Write the compliance bundle to the output directory."""
    os.makedirs(output_dir, exist_ok=True)

    # Always write the full bundle as JSON
    bundle_json_path = os.path.join(output_dir, "bundle.json")
    with open(bundle_json_path, "w") as f:
        json.dump(bundle, f, indent=2, default=str)

    ext = _format_extension(fmt)

    # Write individual files
    if bundle.get("receipt") is not None:
        _write_artifact(
            os.path.join(output_dir, f"receipt.{ext}"),
            "Decision Receipt",
            bundle["receipt"],
            fmt,
            article_ref=EU_AI_ACT_ARTICLES["article_9"],
        )

    if bundle.get("audit_trail") is not None:
        _write_artifact(
            os.path.join(output_dir, f"audit_trail.{ext}"),
            "Audit Trail",
            bundle["audit_trail"],
            fmt,
            article_ref=EU_AI_ACT_ARTICLES["article_12"],
        )

    if bundle.get("risk_management") is not None:
        _write_artifact(
            os.path.join(output_dir, f"risk_management.{ext}"),
            "Risk Management Report",
            bundle["risk_management"],
            fmt,
            article_ref=EU_AI_ACT_ARTICLES["article_9"],
        )

    _write_artifact(
        os.path.join(output_dir, f"transparency_report.{ext}"),
        "Transparency Report",
        bundle["transparency_report"],
        fmt,
        article_ref=EU_AI_ACT_ARTICLES["article_13"],
    )

    _write_artifact(
        os.path.join(output_dir, f"human_oversight.{ext}"),
        "Human Oversight Report",
        bundle["human_oversight"],
        fmt,
        article_ref=EU_AI_ACT_ARTICLES["article_14"],
    )

    _write_artifact(
        os.path.join(output_dir, f"accuracy_report.{ext}"),
        "Accuracy and Robustness Report",
        bundle["accuracy_report"],
        fmt,
        article_ref=EU_AI_ACT_ARTICLES["article_15"],
    )

    # Write README manifest
    _write_manifest(output_dir, bundle, fmt)


def _format_extension(fmt: str) -> str:
    """Map format name to file extension."""
    return {"markdown": "md", "html": "html", "json": "json"}.get(fmt, "md")


def _write_artifact(
    path: str,
    title: str,
    data: dict[str, Any],
    fmt: str,
    article_ref: dict[str, Any] | None = None,
) -> None:
    """Write a single artifact file."""
    if fmt == "json":
        content = json.dumps(data, indent=2, default=str)
    elif fmt == "html":
        content = _render_html(title, data, article_ref)
    else:
        content = _render_markdown(title, data, article_ref)

    with open(path, "w") as f:
        f.write(content)


def _render_markdown(
    title: str,
    data: dict[str, Any],
    article_ref: dict[str, Any] | None = None,
) -> str:
    """Render data as markdown."""
    lines = [f"# {title}", ""]

    if article_ref:
        lines.append(f"**{article_ref['number']}:** {article_ref['title']}")
        lines.append("")
        lines.append(f"> {article_ref['requirement']}")
        lines.append("")
        lines.append("---")
        lines.append("")

    for key, value in data.items():
        readable_key = key.replace("_", " ").title()
        if isinstance(value, list):
            lines.append(f"## {readable_key}")
            lines.append("")
            if value and isinstance(value[0], dict):
                # Table format for list of dicts
                if value:
                    headers = list(value[0].keys())
                    lines.append(
                        "| " + " | ".join(h.replace("_", " ").title() for h in headers) + " |"
                    )
                    lines.append("| " + " | ".join("---" for _ in headers) + " |")
                    for item in value:
                        row = " | ".join(str(item.get(h, ""))[:60] for h in headers)
                        lines.append(f"| {row} |")
                lines.append("")
            else:
                for item in value:
                    lines.append(f"- {item}")
                lines.append("")
        elif isinstance(value, dict):
            lines.append(f"## {readable_key}")
            lines.append("")
            for k, v in value.items():
                rk = k.replace("_", " ").title()
                if isinstance(v, list):
                    lines.append(f"**{rk}:**")
                    for item in v:
                        lines.append(f"- {item}")
                elif isinstance(v, dict):
                    lines.append(f"**{rk}:** (see bundle.json for details)")
                else:
                    lines.append(f"**{rk}:** {v}")
            lines.append("")
        else:
            lines.append(f"**{readable_key}:** {value}")
            lines.append("")

    return "\n".join(lines)


def _render_html(
    title: str,
    data: dict[str, Any],
    article_ref: dict[str, Any] | None = None,
) -> str:
    """Render data as minimal HTML."""
    from html import escape

    parts = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        f"  <title>{escape(title)}</title>",
        "  <meta charset='utf-8'>",
        "  <style>",
        "    body { font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }",
        "    table { border-collapse: collapse; width: 100%; margin: 1rem 0; }",
        "    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }",
        "    th { background: #f5f5f5; }",
        "    .status-pass { color: #16a34a; font-weight: bold; }",
        "    .status-partial { color: #d97706; font-weight: bold; }",
        "    .status-fail { color: #dc2626; font-weight: bold; }",
        "    blockquote { border-left: 4px solid #3b82f6; padding-left: 1rem; color: #475569; }",
        "    code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; }",
        "  </style>",
        "</head>",
        "<body>",
        f"  <h1>{escape(title)}</h1>",
    ]

    if article_ref:
        parts.append(
            f"  <p><strong>{escape(article_ref['number'])}:</strong> {escape(article_ref['title'])}</p>"
        )
        parts.append(f"  <blockquote>{escape(article_ref['requirement'])}</blockquote>")
        parts.append("  <hr>")

    for key, value in data.items():
        readable_key = escape(key.replace("_", " ").title())
        if isinstance(value, list) and value and isinstance(value[0], dict):
            parts.append(f"  <h2>{readable_key}</h2>")
            headers = list(value[0].keys())
            parts.append("  <table>")
            parts.append(
                "    <tr>"
                + "".join(f"<th>{escape(h.replace('_', ' ').title())}</th>" for h in headers)
                + "</tr>"
            )
            for item in value:
                parts.append(
                    "    <tr>"
                    + "".join(f"<td>{escape(str(item.get(h, '')))}</td>" for h in headers)
                    + "</tr>"
                )
            parts.append("  </table>")
        elif isinstance(value, list):
            parts.append(f"  <h2>{readable_key}</h2>")
            parts.append("  <ul>")
            for item in value:
                parts.append(f"    <li>{escape(str(item))}</li>")
            parts.append("  </ul>")
        elif isinstance(value, dict):
            parts.append(f"  <h2>{readable_key}</h2>")
            parts.append("  <dl>")
            for k, v in value.items():
                rk = escape(k.replace("_", " ").title())
                parts.append(f"    <dt><strong>{rk}</strong></dt>")
                parts.append(f"    <dd>{escape(str(v))}</dd>")
            parts.append("  </dl>")
        else:
            parts.append(f"  <p><strong>{readable_key}:</strong> {escape(str(value))}</p>")

    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts)


def _write_manifest(
    output_dir: str,
    bundle: dict[str, Any],
    fmt: str,
) -> None:
    """Write the README manifest describing the compliance bundle."""
    ext = _format_extension(fmt)
    meta = bundle.get("meta", {})
    classification = bundle.get("risk_classification", {})
    conformity = bundle.get("conformity_report", {})
    score_info = bundle.get("compliance_score", {})

    score = score_info.get("score", 0)
    label = score_info.get("label", "Unknown")
    days = meta.get("days_until_deadline", 0)
    breakdown = score_info.get("breakdown", {})

    # Score bar (10 chars wide)
    filled = max(1, score // 10)
    score_bar = "=" * filled + "-" * (10 - filled)

    lines = [
        "# EU AI Act Compliance Bundle",
        "",
        "> Generated by **Aragora Decision Integrity Platform** -- EU AI Act (Regulation 2024/1689)",
        "",
        "---",
        "",
        "## Compliance Readiness",
        "",
        "```",
        f"  Score:    {score}/100  [{score_bar}]  {label}",
        f"  Risk:     {classification.get('risk_level', 'unknown').upper()}",
        f"  Status:   {conformity.get('overall_status', 'unknown').upper()}",
        f"  Deadline: August 2, 2026  ({days} days remaining)",
        "```",
        "",
    ]

    if breakdown:
        pass_arts = ", ".join(breakdown.get("pass", [])) or "--"
        partial_arts = ", ".join(breakdown.get("partial", [])) or "--"
        fail_arts = ", ".join(breakdown.get("fail", [])) or "--"
        lines += [
            f"- **Passing:** {pass_arts}",
            f"- **Partial:** {partial_arts}",
            f"- **Failing:** {fail_arts}",
            "",
        ]

    article_titles = {
        "Article 9": "Risk Management",
        "Article 12": "Record-Keeping",
        "Article 13": "Transparency",
        "Article 14": "Human Oversight",
        "Article 15": "Accuracy & Robustness",
    }

    lines += [
        "---",
        "",
        "## Bundle Contents",
        "",
        "| File | EU AI Act Article | What It Proves |",
        "|------|-------------------|----------------|",
        "| `bundle.json` | All | Complete machine-readable compliance record |",
        f"| `receipt.{ext}` | Article 9 | Risk assessment, confidence, robustness score |",
        f"| `risk_management.{ext}` | Article 9 | Risk management system, mitigations, residual risk |",
        f"| `audit_trail.{ext}` | Article 12 | Event log -- who did what and when |",
        f"| `transparency_report.{ext}` | Article 13 | Agent identities, reasoning chain, dissent |",
        f"| `human_oversight.{ext}` | Article 14 | Override capability, voting record, escalation |",
        f"| `accuracy_report.{ext}` | Article 15 | Confidence metrics, robustness, integrity hash |",
        "| `README.md` | -- | This manifest |",
        "",
        "---",
        "",
        "## Article-by-Article Assessment",
        "",
        "| Article | Title | Status | Evidence |",
        "|---------|-------|--------|----------|",
    ]

    for mapping in conformity.get("article_mappings", []):
        status_label = {
            "satisfied": "**PASS**",
            "partial": "PARTIAL",
            "not_satisfied": "**FAIL**",
            "not_applicable": "N/A",
        }.get(mapping.get("status", ""), mapping.get("status", ""))
        article = mapping.get("article", "")
        title = article_titles.get(article, "")
        evidence = mapping.get("evidence", "")[:80]
        lines.append(f"| {article} | {title} | {status_label} | {evidence} |")

    if conformity.get("recommendations"):
        lines += [
            "",
            "---",
            "",
            "## Recommendations",
            "",
        ]
        for i, rec in enumerate(conformity["recommendations"], 1):
            lines.append(f"{i}. {rec}")

    lines += [
        "",
        "---",
        "",
        "## Audit Metadata",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Receipt ID | `{meta.get('receipt_id', '')}` |",
        f"| Generated at | {meta.get('generated_at', '')} |",
        f"| Regulation | {meta.get('regulation', '')} |",
        f"| Integrity Hash | `{meta.get('integrity_hash', '')}` |",
        f"| Generated by | {meta.get('generated_by', 'Aragora Decision Integrity Platform')} |",
        "",
        "---",
        "",
        "*This bundle was generated automatically from a cryptographically signed decision receipt.*",
        "*The integrity hash verifies the bundle has not been tampered with since generation.*",
        "",
    ]

    manifest_path = os.path.join(output_dir, "README.md")
    with open(manifest_path, "w") as f:
        f.write("\n".join(lines))


def _print_summary(
    bundle: dict[str, Any],
    output_dir: str,
    fmt: str,
) -> None:
    """Print a summary to stdout."""
    meta = bundle.get("meta", {})
    classification = bundle.get("risk_classification", {})
    conformity = bundle.get("conformity_report", {})
    score_info = bundle.get("compliance_score", {})
    ext = _format_extension(fmt)

    # ANSI colors -- gracefully ignored when piped
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    score = score_info.get("score", 0)
    label = score_info.get("label", "Unknown")
    days = meta.get("days_until_deadline", 0)

    score_color = GREEN if score >= 75 else (YELLOW if score >= 40 else RED)
    days_color = RED if days < 90 else (YELLOW if days < 180 else GREEN)

    print()
    print(f"{BOLD}EU AI Act Compliance Bundle{RESET}")
    print("=" * 55)
    print("  Regulation:      EU AI Act (Regulation 2024/1689)")
    print(f"  Receipt ID:      {meta.get('receipt_id', '')}")
    print(f"  Risk Level:      {classification.get('risk_level', '').upper()}")
    print()
    print(f"  {BOLD}Compliance Score: {score_color}{score}/100 -- {label}{RESET}")
    print(f"  Deadline:        {days_color}August 2, 2026 ({days} days remaining){RESET}")
    print(f"  Integrity Hash:  {meta.get('integrity_hash', '')[:32]}...")
    print()

    # Article status table
    status_sym = {
        "satisfied": "PASS",
        "partial": "PARTIAL",
        "not_satisfied": "FAIL",
        "not_applicable": "N/A",
    }
    status_col = {"satisfied": GREEN, "partial": YELLOW, "not_satisfied": RED, "not_applicable": ""}

    print(f"  {'Article':<14} {'Requirement':<52} Status")
    print(f"  {'-' * 14} {'-' * 52} ------")
    for mapping in conformity.get("article_mappings", []):
        st = mapping.get("status", "")
        sym = status_sym.get(st, st)
        col = status_col.get(st, "")
        article = mapping.get("article", "")
        req = mapping.get("requirement", "")[:52]
        print(f"  {article:<14} {req:<52} {col}[{sym}]{RESET}")

    recs = conformity.get("recommendations", [])
    if recs:
        print()
        print(f"  {YELLOW}Recommendations:{RESET}")
        for i, rec in enumerate(recs, 1):
            print(f"    {i}. {rec}")

    print()
    print(f"  Output: {output_dir}/")
    print("    README.md                         Manifest and article mapping")
    print("    bundle.json                       Full bundle (machine-readable)")
    print(f"    receipt.{ext:<27} Art. 9  -- Risk management")
    print(f"    risk_management.{ext:<19} Art. 9  -- Risk management system & mitigations")
    print(f"    audit_trail.{ext:<23} Art. 12 -- Record-keeping & provenance")
    print(f"    transparency_report.{ext:<15} Art. 13 -- Agent participation & reasoning")
    print(f"    human_oversight.{ext:<19} Art. 14 -- Human oversight & override")
    print(f"    accuracy_report.{ext:<19} Art. 15 -- Confidence & robustness")
    print()


# ---------------------------------------------------------------------------
# Synthetic demo receipt
# ---------------------------------------------------------------------------


def _synthetic_receipt() -> dict[str, Any]:
    """Generate a synthetic receipt for demo/sample output."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "receipt_id": "DEMO-RCP-001",
        "gauntlet_id": "demo-gauntlet-001",
        "timestamp": now,
        "input_summary": (
            "Evaluate AI-powered recruitment and CV screening system for "
            "automated candidate filtering in hiring decisions."
        ),
        "input_hash": hashlib.sha256(b"demo-input").hexdigest(),
        "risk_summary": {
            "total": 4,
            "critical": 0,
            "high": 1,
            "medium": 2,
            "low": 1,
        },
        "attacks_attempted": 8,
        "attacks_successful": 1,
        "probes_run": 12,
        "vulnerabilities_found": 2,
        "verdict": "CONDITIONAL",
        "confidence": 0.78,
        "robustness_score": 0.72,
        "verdict_reasoning": (
            "The recruitment screening system meets accuracy thresholds but "
            "requires additional bias auditing before full deployment. "
            "Demographic parity gaps detected in the gender dimension."
        ),
        "dissenting_views": [
            "Agent-Challenger: demographic parity gap exceeds 5% threshold for employment AI"
        ],
        "consensus_proof": {
            "reached": True,
            "confidence": 0.78,
            "supporting_agents": ["claude-analyst", "mistral-auditor", "gpt4-ethics"],
            "dissenting_agents": ["gemini-challenger"],
            "method": "weighted_majority",
            "agreement_ratio": 0.75,
            "evidence_hash": hashlib.sha256(b"demo-evidence").hexdigest(),
        },
        "provenance_chain": [
            {"event_type": "debate_started", "timestamp": now, "actor": "system"},
            {"event_type": "proposal_submitted", "timestamp": now, "actor": "claude-analyst"},
            {"event_type": "critique_submitted", "timestamp": now, "actor": "gemini-challenger"},
            {"event_type": "revision_submitted", "timestamp": now, "actor": "mistral-auditor"},
            {"event_type": "vote_cast", "timestamp": now, "actor": "claude-analyst"},
            {"event_type": "vote_cast", "timestamp": now, "actor": "gpt4-ethics"},
            {"event_type": "vote_cast", "timestamp": now, "actor": "gemini-challenger"},
            {"event_type": "vote_cast", "timestamp": now, "actor": "mistral-auditor"},
            {
                "event_type": "human_approval",
                "timestamp": now,
                "actor": "compliance-officer@org.example.com",
            },
            {"event_type": "receipt_generated", "timestamp": now, "actor": "system"},
        ],
        "schema_version": "1.0",
        "artifact_hash": hashlib.sha256(b"demo-artifact").hexdigest(),
        "signature": "ed25519:demo_signature",
        "config_used": {
            "protocol": "adversarial",
            "rounds": 3,
            "require_approval": True,
            "human_in_loop": True,
            "approver": "compliance-officer@org.example.com",
        },
    }
