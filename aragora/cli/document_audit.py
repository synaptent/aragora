"""
Aragora Document Audit CLI.

Commands for auditing documents using multi-agent analysis.

Usage:
    aragora document-audit upload --input ./docs/
    aragora document-audit scan --input ./docs/ --type security
    aragora document-audit status --session abc123
    aragora document-audit report --session abc123 --output report.json
"""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from aragora.config.model_pins import GEMINI_31_PRO_DIRECT


def cmd_upload(args: argparse.Namespace) -> int:
    """Upload documents for processing."""
    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Error: Path not found: {input_path}")
        return 1

    print("\n" + "=" * 60)
    print("ARAGORA DOCUMENT UPLOAD")
    print("=" * 60)

    # Collect files
    if input_path.is_file():
        files = [input_path]
    else:
        patterns = ["*.pdf", "*.docx", "*.txt", "*.md", "*.json", "*.xlsx", "*.csv"]
        files = []
        for pattern in patterns:
            files.extend(input_path.glob(f"**/{pattern}" if args.recursive else pattern))

    if not files:
        print(f"\nNo supported files found in {input_path}")
        return 1

    print(f"\nFound {len(files)} files to upload:")
    for f in files[:10]:
        print(f"  - {f.name}")
    if len(files) > 10:
        print(f"  ... and {len(files) - 10} more")

    # Run upload
    async def do_upload():
        try:
            from aragora.documents.ingestion.batch_processor import BatchProcessor, BatchJob

            processor = BatchProcessor()

            # Create batch job
            job = BatchJob(
                files=[str(f) for f in files],
                chunking_strategy=args.chunking or "auto",
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
            )

            print(f"\nProcessing {len(files)} files...")

            def on_progress(processed: int, total: int):
                pct = (processed / total) * 100
                bar = "#" * int(pct / 5) + "-" * (20 - int(pct / 5))
                print(f"\r  [{bar}] {processed}/{total} ({pct:.1f}%)", end="", flush=True)

            result = await processor.process(job, on_progress=on_progress)

            print("\n\nUpload complete:")
            print(f"  Documents: {result.documents_processed}")
            print(f"  Chunks: {result.chunks_created}")
            print(f"  Tokens: {result.total_tokens:,}")
            print(f"  Errors: {len(result.errors)}")

            if result.errors:
                print("\nErrors:")
                for error in result.errors[:5]:
                    print(f"  - {error}")

            return 0

        except ImportError:
            print("\nDocument processing not available. Install dependencies:")
            print("  pip install unstructured[all-docs] tiktoken")
            return 1

    return asyncio.run(do_upload())


def cmd_scan(args: argparse.Namespace) -> int:
    """Scan documents for issues."""
    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Error: Path not found: {input_path}")
        return 1

    print("\n" + "=" * 60)
    print("ARAGORA DOCUMENT AUDIT")
    print("=" * 60)

    audit_types = (
        args.type.split(",")
        if args.type != "all"
        else ["security", "compliance", "consistency", "quality"]
    )
    print(f"\nAudit types: {', '.join(audit_types)}")
    print(f"Model: {args.model}")

    # Run scan
    async def do_scan():
        try:
            from aragora.audit.document_auditor import DocumentAuditor, AuditConfig

            config = AuditConfig(
                primary_model=args.model,
                min_confidence=args.confidence,
                require_confirmation=not args.no_verify,
            )

            auditor = DocumentAuditor(config=config)

            # Collect files and get document IDs (simplified - in practice would upload first)
            if input_path.is_file():
                doc_ids = [str(input_path)]
            else:
                patterns = ["*.pdf", "*.docx", "*.txt", "*.md"]
                doc_ids = []
                for pattern in patterns:
                    doc_ids.extend(
                        str(f)
                        for f in input_path.glob(f"**/{pattern}" if args.recursive else pattern)
                    )

            if not doc_ids:
                print(f"\nNo supported files found in {input_path}")
                return 1

            print(f"\nScanning {len(doc_ids)} documents...")

            def on_finding(finding):
                sev = finding.severity.value.upper()
                color = {
                    "critical": "\033[91m",
                    "high": "\033[93m",
                    "medium": "\033[33m",
                    "low": "\033[36m",
                    "info": "\033[37m",
                }.get(finding.severity.value, "")
                reset = "\033[0m"
                print(f"  {color}[{sev}]{reset} {finding.title}")

            def on_progress(session_id: str, progress: float, phase: str):
                pct = progress * 100
                bar = "#" * int(pct / 5) + "-" * (20 - int(pct / 5))
                print(f"\r  [{bar}] {pct:.1f}% - {phase}", end="", flush=True)

            # Create and run audit session
            auditor.on_finding = on_finding
            auditor.on_progress = on_progress

            session = await auditor.create_session(
                document_ids=doc_ids,
                audit_types=audit_types,
                model=args.model,
            )

            print(f"Session: {session.id}")
            print("\nFindings:\n")

            session = await auditor.run_audit(session.id)

            print("\n\nAudit complete:")
            print(f"  Status: {session.status.value}")
            print(
                f"  Duration: {session.duration_seconds:.1f}s" if session.duration_seconds else ""
            )
            print(f"  Findings: {len(session.findings)}")

            if session.findings:
                print("\nSummary by severity:")
                for sev, count in session.findings_by_severity.items():
                    print(f"  {sev}: {count}")

            if args.output:
                output_path = Path(args.output)
                with open(output_path, "w") as f:
                    json.dump(
                        {
                            "session": session.to_dict(),
                            "findings": [finding.to_dict() for finding in session.findings],
                        },
                        f,
                        indent=2,
                    )
                print(f"\nReport saved to: {output_path}")

            # Exit with error code if critical/high findings
            critical_high = sum(
                1 for f in session.findings if f.severity.value in ("critical", "high")
            )
            return 1 if critical_high > 0 and args.fail_on_findings else 0

        except ImportError as e:
            print(f"\nDocument auditing not available: {e}")
            return 1

    return asyncio.run(do_scan())


def cmd_status(args: argparse.Namespace) -> int:
    """Check audit session status."""
    print("\n" + "=" * 60)
    print("ARAGORA AUDIT STATUS")
    print("=" * 60)

    async def do_status():
        try:
            from aragora.audit.document_auditor import get_document_auditor

            auditor = get_document_auditor()
            session = auditor.get_session(args.session)

            if not session:
                print(f"\nSession not found: {args.session}")
                return 1

            print(f"\nSession: {session.id}")
            print(f"Name: {session.name}")
            print(f"Status: {session.status.value}")
            print(f"Progress: {session.progress * 100:.1f}%")
            print(f"Phase: {session.current_phase}")
            print(f"Documents: {len(session.document_ids)}")
            print(f"Findings: {len(session.findings)}")

            if session.findings_by_severity:
                print("\nFindings by severity:")
                for sev, count in session.findings_by_severity.items():
                    print(f"  {sev}: {count}")

            if session.errors:
                print(f"\nErrors: {len(session.errors)}")
                for error in session.errors[:5]:
                    print(f"  - {error}")

            return 0

        except ImportError:
            print("\nDocument auditing not available.")
            return 1

    return asyncio.run(do_status())


def cmd_report(args: argparse.Namespace) -> int:
    """Generate audit report."""
    print("\n" + "=" * 60)
    print("ARAGORA AUDIT REPORT")
    print("=" * 60)

    async def do_report():
        try:
            from aragora.audit.document_auditor import get_document_auditor

            auditor = get_document_auditor()
            session = auditor.get_session(args.session)

            if not session:
                print(f"\nSession not found: {args.session}")
                return 1

            # Build report
            report = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "session": session.to_dict(),
                "findings": [f.to_dict() for f in session.findings],
                "summary": {
                    "total_findings": len(session.findings),
                    "by_severity": session.findings_by_severity,
                    "by_type": {},
                    "by_document": {},
                },
            }

            # Aggregate by type and document
            for finding in session.findings:
                t = finding.audit_type.value
                d = finding.document_id
                report["summary"]["by_type"][t] = report["summary"]["by_type"].get(t, 0) + 1
                report["summary"]["by_document"][d] = report["summary"]["by_document"].get(d, 0) + 1

            output_path = Path(args.output)

            if args.format == "json":
                with open(output_path, "w") as f:
                    json.dump(report, f, indent=2)
            elif args.format == "markdown":
                md = _generate_markdown_report(report)
                with open(output_path, "w") as f:
                    f.write(md)
            elif args.format == "html":
                html = _generate_html_report(report)
                with open(output_path, "w") as f:
                    f.write(html)

            print(f"\nReport generated: {output_path}")
            print(f"  Total findings: {len(session.findings)}")

            return 0

        except ImportError:
            print("\nDocument auditing not available.")
            return 1

    return asyncio.run(do_report())


def _generate_markdown_report(report: dict) -> str:
    """Generate markdown audit report."""
    lines = [
        "# Document Audit Report",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Summary",
        "",
        f"- **Total Findings**: {report['summary']['total_findings']}",
        f"- **Documents Audited**: {len(report['session']['document_ids'])}",
        f"- **Duration**: {report['session'].get('duration_seconds', 'N/A')}s",
        "",
        "### By Severity",
        "",
    ]

    for sev, count in report["summary"]["by_severity"].items():
        lines.append(f"- {sev.title()}: {count}")

    lines.extend(
        [
            "",
            "### By Type",
            "",
        ]
    )

    for t, count in report["summary"]["by_type"].items():
        lines.append(f"- {t.title()}: {count}")

    lines.extend(
        [
            "",
            "## Findings",
            "",
        ]
    )

    for finding in report["findings"]:
        sev = finding["severity"].upper()
        lines.extend(
            [
                f"### [{sev}] {finding['title']}",
                "",
                f"**Category**: {finding['category']}",
                f"**Confidence**: {finding['confidence'] * 100:.0f}%",
                "",
                f"{finding['description']}",
                "",
                "**Evidence**:",
                "```",
                f"{finding['evidence_text']}",
                "```",
                "",
                f"**Recommendation**: {finding['recommendation']}",
                "",
                "---",
                "",
            ]
        )

    return "\n".join(lines)


def _generate_html_report(report: dict) -> str:
    """Generate HTML audit report."""
    severity_colors = {
        "critical": "#dc2626",
        "high": "#ea580c",
        "medium": "#ca8a04",
        "low": "#0891b2",
        "info": "#6b7280",
    }

    findings_html = ""
    for finding in report["findings"]:
        sev = finding["severity"]
        color = severity_colors.get(sev, "#6b7280")
        findings_html += f"""
        <div class="finding" style="border-left: 4px solid {color};">
            <h3><span class="severity" style="background: {color};">{sev.upper()}</span> {finding["title"]}</h3>
            <p><strong>Category:</strong> {finding["category"]} | <strong>Confidence:</strong> {finding["confidence"] * 100:.0f}%</p>
            <p>{finding["description"]}</p>
            <div class="evidence"><pre>{finding["evidence_text"]}</pre></div>
            <p><strong>Recommendation:</strong> {finding["recommendation"]}</p>
        </div>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Document Audit Report</title>
    <style>
        body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 0 auto; padding: 2rem; }}
        h1 {{ color: #0f172a; }}
        .summary {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin: 2rem 0; }}
        .stat {{ background: #f1f5f9; padding: 1rem; border-radius: 8px; }}
        .stat-value {{ font-size: 2rem; font-weight: bold; }}
        .finding {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1rem; margin: 1rem 0; }}
        .severity {{ color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; }}
        .evidence {{ background: #f8fafc; padding: 1rem; border-radius: 4px; overflow-x: auto; }}
        pre {{ margin: 0; white-space: pre-wrap; }}
    </style>
</head>
<body>
    <h1>Document Audit Report</h1>
    <p>Generated: {report["generated_at"]}</p>

    <div class="summary">
        <div class="stat">
            <div class="stat-value">{report["summary"]["total_findings"]}</div>
            <div>Total Findings</div>
        </div>
        <div class="stat">
            <div class="stat-value">{len(report["session"]["document_ids"])}</div>
            <div>Documents</div>
        </div>
        <div class="stat">
            <div class="stat-value">{report["session"].get("duration_seconds", "N/A")}s</div>
            <div>Duration</div>
        </div>
    </div>

    <h2>Findings</h2>
    {findings_html}
</body>
</html>"""


def create_document_audit_parser(subparsers: argparse._SubParsersAction) -> None:
    """Create document-audit subcommand parser."""
    parser = subparsers.add_parser(
        "document-audit",
        help="Audit documents using multi-agent analysis",
        description="""
Audit documents for security vulnerabilities, compliance issues,
inconsistencies, and quality problems using multi-agent AI analysis.

Examples:
    aragora document-audit upload --input ./docs/
    aragora document-audit scan --input ./docs/ --type security
    aragora document-audit status --session abc123
    aragora document-audit report --session abc123 --output report.md
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subcommands = parser.add_subparsers(dest="action")

    # Upload command
    upload_parser = subcommands.add_parser("upload", help="Upload documents for processing")
    upload_parser.add_argument("--input", "-i", required=True, help="Input file or directory")
    upload_parser.add_argument(
        "--recursive", "-r", action="store_true", help="Process subdirectories"
    )
    upload_parser.add_argument(
        "--chunking",
        choices=["auto", "semantic", "sliding", "recursive", "fixed"],
        help="Chunking strategy",
    )
    upload_parser.add_argument(
        "--chunk-size", type=int, default=512, help="Target chunk size in tokens"
    )
    upload_parser.add_argument(
        "--chunk-overlap", type=int, default=50, help="Overlap between chunks"
    )
    upload_parser.set_defaults(func=cmd_upload)

    # Scan command
    scan_parser = subcommands.add_parser("scan", help="Scan documents for issues")
    scan_parser.add_argument("--input", "-i", required=True, help="Input file or directory")
    scan_parser.add_argument(
        "--recursive", "-r", action="store_true", help="Process subdirectories"
    )
    scan_parser.add_argument(
        "--type",
        "-t",
        default="all",
        help="Audit types: all,security,compliance,consistency,quality",
    )
    scan_parser.add_argument(
        "--model", "-m", default=GEMINI_31_PRO_DIRECT, help="Primary model for scanning"
    )
    scan_parser.add_argument(
        "--confidence", type=float, default=0.7, help="Minimum confidence threshold"
    )
    scan_parser.add_argument(
        "--no-verify", action="store_true", help="Skip multi-agent verification"
    )
    scan_parser.add_argument("--output", "-o", help="Output file for findings")
    scan_parser.add_argument(
        "--fail-on-findings", action="store_true", help="Exit with error if findings found"
    )
    scan_parser.set_defaults(func=cmd_scan)

    # Status command
    status_parser = subcommands.add_parser("status", help="Check audit session status")
    status_parser.add_argument("--session", "-s", required=True, help="Session ID")
    status_parser.set_defaults(func=cmd_status)

    # Report command
    report_parser = subcommands.add_parser("report", help="Generate audit report")
    report_parser.add_argument("--session", "-s", required=True, help="Session ID")
    report_parser.add_argument("--output", "-o", required=True, help="Output file")
    report_parser.add_argument(
        "--format", "-f", choices=["json", "markdown", "html"], default="json", help="Report format"
    )
    report_parser.set_defaults(func=cmd_report)

    # Default to help
    parser.set_defaults(func=lambda args: parser.print_help())


def main(args: argparse.Namespace) -> int:
    """Main entry point for document-audit commands."""
    if hasattr(args, "func"):
        return args.func(args)
    return 0


__all__ = ["create_document_audit_parser", "main"]
