"""CLI command for inbox triage: the trust wedge entry point.

Usage::

    aragora triage run --batch 5
    aragora triage run --batch 5 --auto-approve
    aragora triage status
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logger = logging.getLogger(__name__)


def add_triage_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'triage' subcommand."""
    parser = subparsers.add_parser(
        "triage",
        help="Inbox triage via adversarial debate with receipt-gated actions",
        description=(
            "Run the inbox trust wedge: fetch unread Gmail, debate triage\n"
            "actions adversarially, persist signed receipts, and execute\n"
            "approved actions (archive/star/label/ignore).\n\n"
            "Commands:\n"
            "  run     Fetch and triage unread emails\n"
            "  status  Show triage session status\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="triage_command")

    run_p = sub.add_parser("run", help="Fetch and triage unread emails")
    run_p.add_argument(
        "--batch",
        type=int,
        default=5,
        help="Number of unread messages to fetch (default: 5)",
    )
    run_p.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve safe actions (archive/star/ignore) when confidence >= 0.85",
    )
    run_p.add_argument(
        "--provider",
        default="gmail",
        choices=["gmail"],
        help="Email provider (default: gmail)",
    )

    sub.add_parser("status", help="Show triage session status")

    parser.set_defaults(func=cmd_triage)


def cmd_triage(args: argparse.Namespace) -> None:
    """Dispatch triage subcommands."""
    command = getattr(args, "triage_command", None)
    if command == "run":
        batch = getattr(args, "batch", 5)
        auto_approve = getattr(args, "auto_approve", False)
        asyncio.run(_run_triage(batch_size=batch, auto_approve=auto_approve))
    elif command == "status":
        _show_status()
    else:
        print("Usage: aragora triage {run,status}")
        sys.exit(1)


async def _run_triage(batch_size: int, auto_approve: bool) -> None:
    """Run the inbox triage pipeline."""
    try:
        from aragora.inbox.triage_runner import InboxTriageRunner
    except ImportError:
        print("Error: inbox triage module not available", file=sys.stderr)
        sys.exit(1)

    # Build Gmail connector
    gmail = _get_gmail_connector()
    if gmail is None:
        print(
            "Error: Gmail not configured. Set GMAIL_CLIENT_ID and "
            "GMAIL_CLIENT_SECRET environment variables, then run "
            "'aragora triage run' again.",
            file=sys.stderr,
        )
        sys.exit(1)

    runner = InboxTriageRunner(gmail_connector=gmail)
    print(f"Fetching up to {batch_size} unread messages...")

    decisions = await runner.run_triage(
        batch_size=batch_size,
        auto_approve=auto_approve,
    )

    if not decisions:
        print("No messages to triage.")
        return

    # If not auto-approving, enter CLI review loop
    if not auto_approve:
        try:
            from aragora.inbox.cli_review import CLIReviewLoop

            loop = CLIReviewLoop()
            for decision in decisions:
                loop.review(decision)
        except ImportError:
            # CLI review not available — print summary
            _print_decisions(decisions)
    else:
        _print_decisions(decisions)


def _get_gmail_connector():
    """Build and return an authenticated GmailConnector, or None."""
    import os

    if not (
        os.environ.get("GMAIL_CLIENT_ID")
        or os.environ.get("GOOGLE_GMAIL_CLIENT_ID")
        or os.environ.get("GOOGLE_CLIENT_ID")
    ):
        return None

    try:
        from aragora.connectors.enterprise.communication.gmail import GmailConnector

        connector = GmailConnector()
        return connector
    except ImportError:
        logger.warning("GmailConnector not available")
        return None


def _print_decisions(decisions: list) -> None:
    """Print triage decisions as a summary table."""
    print(f"\n{'─' * 60}")
    print(f"{'Action':<10} {'Confidence':>10}  {'Subject'}")
    print(f"{'─' * 60}")

    for d in decisions:
        action = getattr(d, "final_action", "?")
        confidence = getattr(d, "confidence", 0.0)
        intent = getattr(d, "intent", None)
        subject = "(unknown)"
        if intent and hasattr(intent, "_subject"):
            subject = intent._subject
        elif intent:
            subject = getattr(intent, "message_id", "?")

        bar = "█" * int(confidence * 10)
        print(f"{action:<10} {confidence:>8.1%} {bar:<10}  {subject[:40]}")

    print(f"{'─' * 60}")
    print(f"Total: {len(decisions)} decisions")

    from aragora.inbox.trust_wedge import ReceiptState

    approved = sum(
        1 for d in decisions if getattr(d, "receipt_state", None) == ReceiptState.APPROVED.value
    )
    executed = sum(
        1 for d in decisions if getattr(d, "receipt_state", None) == ReceiptState.EXECUTED.value
    )
    if approved or executed:
        print(f"  Approved: {approved}  Executed: {executed}")


def _show_status() -> None:
    """Show triage configuration status."""
    import os

    print("Inbox Triage Status")
    print(f"{'─' * 40}")

    # Gmail config
    has_gmail = bool(
        os.environ.get("GMAIL_CLIENT_ID")
        or os.environ.get("GOOGLE_GMAIL_CLIENT_ID")
        or os.environ.get("GOOGLE_CLIENT_ID")
    )
    print(f"  Gmail configured:     {'yes' if has_gmail else 'NO'}")

    # Signing key
    from pathlib import Path

    key_path = Path.home() / ".aragora" / "signing.key"
    print(f"  Durable signing key:  {'yes' if key_path.exists() else 'NO'}")

    # OpenRouter
    has_openrouter = bool(os.environ.get("OPENROUTER_API_KEY"))
    print(f"  OpenRouter fallback:  {'yes' if has_openrouter else 'NO'}")

    # Provider keys
    providers = {
        "Anthropic": "ANTHROPIC_API_KEY",
        "OpenAI": "OPENAI_API_KEY",
        "Gemini": "GEMINI_API_KEY",
    }
    for name, var in providers.items():
        status = "yes" if os.environ.get(var) else "no"
        print(f"  {name + ' key:':<22}{status}")
