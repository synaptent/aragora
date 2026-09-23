"""CLI command for inbox triage: the trust wedge entry point.

Usage::

    aragora triage run --batch 5
    aragora triage run --batch 5 --auto-approve
    aragora triage run --dry-run
    aragora triage auth
    aragora triage status
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import warnings
from enum import Enum
from typing import Any, cast

logger = logging.getLogger(__name__)


def _load_local_dotenv() -> None:
    """Best-effort dotenv loading for local founder runs."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
        load_dotenv("/etc/aragora/.env")
    except (ImportError, OSError) as exc:
        logger.debug("dotenv loading unavailable, skipping: %s", exc)
        return


def _get_secret_fallback(name: str) -> str:
    """Resolve a secret via Aragora's secret loader when available."""
    try:
        from aragora.config.secrets import SecretNotFoundError, get_secret

        return str(get_secret(name) or "")
    except SecretNotFoundError as exc:
        # Strict-secrets / production posture: a CRITICAL_SECRET absent from
        # AWS Secrets Manager raises rather than falling back to env. For
        # read-only diagnostics ("is this key configured?") that simply means
        # "not available" -- degrade to "" instead of crashing the command.
        logger.debug("Secret %s not available in strict mode: %s", name, exc)
        return ""
    except (ImportError, OSError, ValueError) as exc:
        logger.debug("Secret fallback for %s unavailable: %s", name, exc)
        return ""


def _parse_bool_env(name: str) -> bool | None:
    """Parse a conventional boolean environment variable."""
    value = os.environ.get(name)
    if value is None:
        return None

    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _should_use_remote_gmail_oauth_secrets() -> bool:
    """Use remote secret fallback only when explicitly enabled or clearly non-local."""
    use_aws = _parse_bool_env("ARAGORA_USE_SECRETS_MANAGER")
    if use_aws is not None:
        return use_aws

    env = os.environ.get("ARAGORA_ENV", "").strip().lower()
    return env in {"production", "prod", "staging", "stage"}


def _resolve_first_env_value(candidates: tuple[str, ...]) -> str:
    """Return the first populated environment variable in priority order."""
    for name in candidates:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def _resolve_gmail_oauth_credentials(
    *, allow_secret_fallback: bool | None = None
) -> tuple[str, str]:
    """Resolve Gmail OAuth client credentials from env/dotenv and optional remote secrets."""
    _load_local_dotenv()

    client_id_candidates = (
        "GMAIL_CLIENT_ID",
        "GOOGLE_GMAIL_CLIENT_ID",
        "GOOGLE_CLIENT_ID",
    )
    client_secret_candidates = (
        "GMAIL_CLIENT_SECRET",
        "GOOGLE_GMAIL_CLIENT_SECRET",
        "GOOGLE_CLIENT_SECRET",
    )

    if allow_secret_fallback is None:
        allow_secret_fallback = _should_use_remote_gmail_oauth_secrets()

    client_id = _resolve_first_env_value(client_id_candidates)
    if not client_id and allow_secret_fallback:
        for name in client_id_candidates:
            value = _get_secret_fallback(name)
            if value:
                client_id = value
                os.environ.setdefault("GMAIL_CLIENT_ID", value)
                break

    client_secret = _resolve_first_env_value(client_secret_candidates)
    if not client_secret and allow_secret_fallback:
        for name in client_secret_candidates:
            value = _get_secret_fallback(name)
            if value:
                client_secret = value
                os.environ.setdefault("GMAIL_CLIENT_SECRET", value)
                break

    return client_id, client_secret


def _action_value(action: object) -> str:
    if isinstance(action, Enum):
        return str(action.value)
    return str(action)


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
            "  auth    Authenticate with Gmail via OAuth\n"
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
    run_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview triage decisions without executing Gmail actions",
    )
    run_p.add_argument(
        "--page-token",
        default=None,
        help="Continue from a Gmail nextPageToken returned by a prior dry-run",
    )

    sub.add_parser("auth", help="Authenticate with Gmail via OAuth")
    sub.add_parser("status", help="Show triage session status")

    queue_p = sub.add_parser("queue", help="Show prioritized review queue")
    queue_p.add_argument("--limit", type=int, default=20, help="Max items (default: 20)")
    queue_p.add_argument("--all", action="store_true", help="Include already-reviewed items")

    label_p = sub.add_parser("label", help="Fast-label triage decisions (g/b/s)")
    label_p.add_argument("--batch", type=int, default=20, help="Number of decisions to label")
    label_p.add_argument("receipt_id", nargs="?", help="Label a single receipt by ID")

    digest_p = sub.add_parser("digest", help="Show daily triage digest")
    digest_p.add_argument("--hours", type=float, default=24.0, help="Lookback window in hours")
    digest_p.add_argument("--json", action="store_true", help="Output as JSON")

    audit_p = sub.add_parser("audit", help="Adversarial audit of recent triage decisions")
    audit_p.add_argument("--batch", type=int, default=20, help="Number of decisions to audit")
    audit_p.add_argument("--hours", type=float, default=24.0, help="Lookback window")
    audit_p.add_argument(
        "--dry-run", action="store_true", help="Show audit prompt without calling LLM"
    )

    cal_p = sub.add_parser("calibrate", help="Show calibration metrics from feedback")
    cal_p.add_argument("--json", action="store_true", help="Output as JSON")

    parser.set_defaults(func=cmd_triage)


def cmd_triage(args: argparse.Namespace) -> None:
    """Dispatch triage subcommands."""
    command = getattr(args, "triage_command", None)
    if command == "run":
        batch = getattr(args, "batch", 5)
        auto_approve = getattr(args, "auto_approve", False)
        dry_run = getattr(args, "dry_run", False)
        page_token = getattr(args, "page_token", None)
        asyncio.run(
            _run_triage(
                batch_size=batch,
                auto_approve=auto_approve,
                dry_run=dry_run,
                page_token=page_token,
            )
        )
    elif command == "auth":
        asyncio.run(_run_gmail_auth())
    elif command == "status":
        _show_status()
    elif command == "queue":
        _show_review_queue(
            limit=getattr(args, "limit", 20),
            include_reviewed=getattr(args, "all", False),
        )
    elif command == "label":
        _run_fast_label(
            batch=getattr(args, "batch", 20),
            single_receipt_id=getattr(args, "receipt_id", None),
        )
    elif command == "digest":
        _show_digest(
            hours=getattr(args, "hours", 24.0),
            as_json=getattr(args, "json", False),
        )
    elif command == "audit":
        asyncio.run(
            _run_audit(
                batch=getattr(args, "batch", 20),
                hours=getattr(args, "hours", 24.0),
                dry_run=getattr(args, "dry_run", False),
            )
        )
    elif command == "calibrate":
        _show_calibration(as_json=getattr(args, "json", False))
    else:
        print("Usage: aragora triage {run,auth,status,queue,label,digest,audit,calibrate}")
        sys.exit(1)


async def _initialize_triage_storage() -> None:
    """Initialize event-loop-bound PostgreSQL infrastructure for CLI triage.

    This mirrors server startup: create the shared pool inside the active event
    loop so stores used by debate hooks do not fall back to SQLite purely
    because triage is running from the CLI.
    """
    try:
        from aragora.server.startup.database import init_postgres_pool

        await init_postgres_pool()
    except (ImportError, OSError, RuntimeError) as exc:
        logger.debug("Triage storage initialization skipped: %s", exc)


async def _shutdown_triage_storage() -> None:
    """Best-effort shutdown for triage-owned database resources."""
    try:
        from aragora.server.startup.database import close_postgres_pool

        await close_postgres_pool()
    except (ImportError, OSError, RuntimeError) as exc:
        logger.debug("Triage shared-pool shutdown skipped: %s", exc)

    try:
        from aragora.observability.http_client_pool import close_http_pool

        await close_http_pool()
    except (ImportError, OSError, RuntimeError) as exc:
        logger.debug("Triage HTTP client pool shutdown skipped: %s", exc)

    try:
        from aragora.agents.api_agents.common import close_shared_connector

        await close_shared_connector()
    except (ImportError, OSError, RuntimeError) as exc:
        logger.debug("Triage API connector shutdown skipped: %s", exc)

    try:
        from aragora.storage.connection_factory import close_all_pools

        await close_all_pools()
    except (ImportError, OSError, RuntimeError) as exc:
        logger.debug("Triage connection-factory shutdown skipped: %s", exc)

    try:
        from aragora.events.dispatcher import shutdown_dispatcher

        shutdown_dispatcher(wait=True)
    except (ImportError, OSError, RuntimeError) as exc:
        logger.debug("Triage dispatcher shutdown skipped: %s", exc)

    try:
        from aragora.storage.webhook_config_store import reset_webhook_config_store

        reset_webhook_config_store()
    except (ImportError, OSError, RuntimeError) as exc:
        logger.debug("Triage webhook config reset skipped: %s", exc)

    try:
        from aragora.inbox.trust_wedge import (
            reset_inbox_trust_wedge_service,
            reset_inbox_trust_wedge_store,
        )

        reset_inbox_trust_wedge_service()
        reset_inbox_trust_wedge_store()
    except (ImportError, OSError, RuntimeError) as exc:
        logger.debug("Triage trust wedge reset skipped: %s", exc)

    # Give async transports a brief chance to finish their close callbacks
    # before the triage event loop shuts down.
    await asyncio.sleep(0.05)


async def _run_triage(
    batch_size: int,
    auto_approve: bool,
    dry_run: bool = False,
    page_token: str | None = None,
) -> None:
    """Run the inbox triage pipeline."""
    try:
        from aragora.inbox.triage_runner import InboxTriageRunner
        from aragora.inbox.triage_diagnostics import TriageRunDiagnostics
    except ImportError:
        print("Error: inbox triage module not available", file=sys.stderr)
        sys.exit(1)

    profile = os.getenv("ARAGORA_TRIAGE_PROFILE", "staged_v1")
    verbose = logging.getLogger().isEnabledFor(logging.DEBUG)
    diagnostics = TriageRunDiagnostics(
        profile=profile,
        batch_size=batch_size,
        auto_approve=auto_approve and not dry_run,
        dry_run=dry_run,
        verbose=verbose,
        diagnostics_dir=os.getenv("ARAGORA_TRIAGE_DIAGNOSTICS_DIR"),
    )
    warnings.filterwarnings(
        "ignore",
        message=r"resource_tracker: There appear to be \d+ leaked semaphore objects to clean up at shutdown",
        category=UserWarning,
        module=r"multiprocessing\.resource_tracker",
    )

    with diagnostics.activate(), diagnostics.capture_logging():
        decisions = []
        try:
            await _initialize_triage_storage()

            gmail = _get_gmail_connector()
            if gmail is None:
                print(
                    "Error: Gmail not configured. Run 'aragora triage auth' first,\n"
                    "or set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET environment variables.",
                    file=sys.stderr,
                )
                sys.exit(1)
            await _sync_gmail_connector_to_token_store(gmail)

            from aragora.inbox.trust_wedge import get_inbox_trust_wedge_service

            wedge_service = get_inbox_trust_wedge_service()
            runner = InboxTriageRunner(
                gmail_connector=gmail,
                wedge_service=wedge_service,
                diagnostics=diagnostics,
                profile=profile,
            )

            if dry_run:
                print(
                    f"[DRY RUN] Fetching up to {batch_size} unread messages "
                    "(no actions will be executed)..."
                )
            else:
                print(f"Fetching up to {batch_size} unread messages...")

            decisions = await runner.run_triage(
                batch_size=batch_size,
                auto_approve=auto_approve and not dry_run,
                page_token=page_token,
            )
            meta = diagnostics.finalize(decisions)

            if not decisions:
                print("No messages to triage.")
                _print_run_footer(decisions, meta, diagnostics)
                return

            if dry_run:
                print("\n[DRY RUN] Proposed triage decisions (no actions executed):")
                _print_decisions(decisions)
                _print_run_footer(
                    decisions,
                    meta,
                    diagnostics,
                    next_page_token=getattr(runner, "next_page_token", None),
                )
                _print_wedge_receipt_handoffs(decisions)
                return

            _print_decisions(decisions)
            _print_run_footer(
                decisions,
                meta,
                diagnostics,
                next_page_token=getattr(runner, "next_page_token", None),
            )

            if not auto_approve:
                try:
                    from aragora.inbox.cli_review import CLIReviewLoop

                    loop = CLIReviewLoop(review_fn=wedge_service.review_receipt)
                    loop.review_batch(decisions)
                except ImportError as exc:
                    logger.debug(
                        "CLIReviewLoop not available, skipping interactive review: %s", exc
                    )
                    return
        finally:
            await _shutdown_triage_storage()


async def _run_gmail_auth() -> None:
    """Run interactive Gmail OAuth flow from CLI."""
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from pathlib import Path
    from urllib.parse import parse_qs, urlparse

    client_id, client_secret = _resolve_gmail_oauth_credentials()

    if not client_id or not client_secret:
        print(
            "Error: Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET environment\n"
            "variables before running 'aragora triage auth'.\n"
            "\n"
            "Get these from: https://console.cloud.google.com/apis/credentials",
            file=sys.stderr,
        )
        sys.exit(1)

    redirect_uri = "http://localhost:8089/callback"
    auth_code_holder: dict[str, str] = {}

    class _OAuthCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            qs = parse_qs(urlparse(self.path).query)
            code = qs.get("code", [None])[0]
            if code:
                auth_code_holder["code"] = code
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>Authenticated! You can close this tab.</h2></body></html>"
                )
            else:
                self.send_response(400)
                self.end_headers()
                error = qs.get("error", ["unknown"])[0]
                auth_code_holder["error"] = error
                self.wfile.write(f"OAuth error: {error}".encode())

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    try:
        from aragora.connectors.enterprise.communication.gmail import GmailConnector

        connector = GmailConnector()
    except ImportError:
        print("Error: GmailConnector not available", file=sys.stderr)
        sys.exit(1)

    auth_url = connector.get_oauth_url(redirect_uri)
    print("Opening browser for Gmail authorization...")
    print(f"\nIf the browser doesn't open, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", 8089), _OAuthCallbackHandler)
    print("Waiting for authorization callback on localhost:8089...")
    server.handle_request()
    server.server_close()

    if "error" in auth_code_holder:
        print(f"OAuth failed: {auth_code_holder['error']}", file=sys.stderr)
        sys.exit(1)

    code = auth_code_holder.get("code")
    if not code:
        print("No authorization code received.", file=sys.stderr)
        sys.exit(1)

    success = await connector.authenticate(code=code, redirect_uri=redirect_uri)
    if not success:
        print("Failed to exchange authorization code for tokens.", file=sys.stderr)
        sys.exit(1)
    await _sync_gmail_connector_to_token_store(connector)

    refresh_token = getattr(connector, "_refresh_token", None)
    if refresh_token:
        token_path = Path.home() / ".aragora" / "gmail_refresh_token"
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(refresh_token)
        token_path.chmod(0o600)
        print("\nGmail authenticated successfully!")
        print(f"Refresh token saved to: {token_path}")
        print("\nYou can now run: aragora triage run --dry-run")
    else:
        print("\nAuthenticated but no refresh token received.")
        print("Try re-running 'aragora triage auth'.")


def _get_gmail_connector():
    """Build and return an authenticated GmailConnector, or None."""
    from pathlib import Path

    client_id, client_secret = _resolve_gmail_oauth_credentials()
    if not (client_id and client_secret):
        return None

    try:
        from aragora.connectors.enterprise.communication.gmail import GmailConnector

        connector = GmailConnector()

        refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "").strip()
        if not refresh_token:
            token_file = Path.home() / ".aragora" / "gmail_refresh_token"
            if token_file.exists():
                refresh_token = token_file.read_text().strip()

        if refresh_token:
            connector._refresh_token = refresh_token

        return connector
    except ImportError:
        logger.warning("GmailConnector not available")
        return None


async def _sync_gmail_connector_to_token_store(connector: object | None) -> None:
    """Mirror CLI Gmail auth state into the durable Gmail token store."""
    refresh_token = str(getattr(connector, "_refresh_token", "") or "").strip()
    if not refresh_token:
        return

    try:
        from aragora.storage.gmail_token_store import (
            EncryptionError,
            GmailUserState,
            get_gmail_token_store,
        )

        user_id = str(getattr(connector, "user_id", "") or "me")
        store = get_gmail_token_store()
        existing = await store.get(user_id)
        state = existing or GmailUserState(user_id=user_id)
        state.refresh_token = refresh_token
        state.access_token = str(getattr(connector, "_access_token", "") or state.access_token)
        state.token_expiry = getattr(connector, "_token_expiry", None) or state.token_expiry
        await store.save(state)
    except (EncryptionError, ImportError, OSError, RuntimeError) as exc:
        logger.debug("Gmail token-store sync skipped: %s", exc)


def _print_decisions(decisions: list) -> None:
    """Print triage decisions as a summary table."""
    print(f"\n{'─' * 60}")
    print(f"{'Action':<10} {'Confidence':>10}  {'Status':<10} {'Subject'}")
    print(f"{'─' * 60}")

    for d in decisions:
        action = _action_value(getattr(d, "final_action", "?"))
        confidence = getattr(d, "confidence", 0.0)
        blocked = bool(getattr(d, "blocked_by_policy", False))
        status = "blocked" if blocked else str(getattr(d, "receipt_state", "created"))
        intent = getattr(d, "intent", None)
        subject = "(unknown)"
        if intent and hasattr(intent, "_subject"):
            subject = intent._subject
        elif intent:
            subject = getattr(intent, "message_id", "?")

        bar = "█" * int(confidence * 10)
        print(f"{action:<10} {confidence:>8.1%} {bar:<10}  {status:<10} {subject[:29]}")

    print(f"{'─' * 60}")
    print(f"Total: {len(decisions)} decisions")
    receipt_ids = []
    for decision in decisions:
        receipt_id = getattr(decision, "receipt_id", None)
        if receipt_id and receipt_id not in receipt_ids:
            receipt_ids.append(receipt_id)
    if receipt_ids:
        print("Inspect receipts:")
        for receipt_id in receipt_ids:
            print(f"  aragora receipt show {receipt_id}")

    from aragora.inbox.trust_wedge import ReceiptState

    approved = sum(
        1 for d in decisions if getattr(d, "receipt_state", None) == ReceiptState.APPROVED.value
    )
    executed = sum(
        1 for d in decisions if getattr(d, "receipt_state", None) == ReceiptState.EXECUTED.value
    )
    if approved or executed:
        print(f"  Approved: {approved}  Executed: {executed}")


def _print_run_footer(
    decisions: list,
    meta: dict[str, object],
    diagnostics: object,
    *,
    next_page_token: str | None = None,
) -> None:
    """Print a compact diagnostics-aware run footer."""
    message_suppressed = int(
        cast(
            Any,
            meta.get(
                "message_suppressed_diagnostics_count",
                meta.get("suppressed_diagnostics_count", 0),
            ),
        )
    )
    global_suppressed = int(cast(Any, meta.get("global_suppressed_diagnostics_count", 0)))
    summary_parts = [
        f"processed={len(decisions)}",
        f"fast={meta.get('fast_tier_count', 0)}",
        f"escalated={meta.get('escalated_count', 0)}",
        f"blocked={meta.get('blocked_count', 0)}",
        f"suppressed={message_suppressed}",
    ]
    if global_suppressed:
        summary_parts.append(f"global_diag={global_suppressed}")
    print("Run summary: " + " ".join(summary_parts))
    if getattr(diagnostics, "has_degraded_or_blocking", lambda: False)():
        print(f"Diagnostics: {meta.get('artifact_dir')}")
    if next_page_token:
        print(f"Next page token: {next_page_token}")


def _print_wedge_receipt_handoffs(decisions: list) -> None:
    """Print inbox trust wedge inspect handles for created receipts."""
    receipt_ids: list[str] = []
    seen: set[str] = set()
    for decision in decisions:
        receipt_id = str(getattr(decision, "receipt_id", "") or "").strip()
        if not receipt_id or receipt_id in seen:
            continue
        seen.add(receipt_id)
        receipt_ids.append(receipt_id)

    if not receipt_ids:
        return

    print("\nInspect inbox receipts:")
    for receipt_id in receipt_ids:
        print(f"  aragora inbox-wedge show {receipt_id}")
    print("\nReview inbox receipts:")
    for receipt_id in receipt_ids:
        print(f"  aragora inbox-wedge review {receipt_id} --choice <approve|reject|edit|skip>")


def _show_status() -> None:
    """Show triage configuration status and dogfood metrics."""
    print("Inbox Triage Status")
    print(f"{'─' * 40}")

    client_id, client_secret = _resolve_gmail_oauth_credentials()
    has_gmail = bool(client_id and client_secret)
    print(f"  Gmail configured:     {'yes' if has_gmail else 'NO'}")

    from pathlib import Path

    key_path = Path.home() / ".aragora" / "signing.key"
    print(f"  Durable signing key:  {'yes' if key_path.exists() else 'NO'}")

    token_path = Path.home() / ".aragora" / "gmail_refresh_token"
    print(f"  Gmail refresh token:  {'yes' if token_path.exists() else 'NO'}")

    has_openrouter = bool(
        os.environ.get("OPENROUTER_API_KEY") or _get_secret_fallback("OPENROUTER_API_KEY")
    )
    print(f"  OpenRouter fallback:  {'yes' if has_openrouter else 'NO'}")

    providers = {
        "Anthropic": "ANTHROPIC_API_KEY",
        "OpenAI": "OPENAI_API_KEY",
        "Gemini": "GEMINI_API_KEY",
    }
    for name, var in providers.items():
        status = "yes" if _get_secret_fallback(var) else "no"
        print(f"  {name + ' key:':<22}{status}")

    _show_dogfood_metrics()


def _show_dogfood_metrics() -> None:
    """Show aggregate dogfood metrics from the trust wedge DB."""
    import json
    import sqlite3

    try:
        from aragora.config import resolve_db_path
    except ImportError:
        logger.debug("resolve_db_path not available, skipping dogfood metrics")
        return

    db_path = resolve_db_path(
        os.environ.get("ARAGORA_INBOX_TRUST_WEDGE_DB", "inbox_trust_wedge.db")
    )
    if not os.path.exists(db_path):
        return

    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        logger.debug("Cannot open dogfood DB: %s", exc)
        return

    try:
        total = conn.execute("SELECT count(*) FROM inbox_trust_receipts").fetchone()[0]
        if total == 0:
            return

        print(f"\n{'─' * 40}")
        print("Dogfood Metrics")
        print(f"{'─' * 40}")
        print(f"  Total receipts:       {total}")

        # State breakdown
        rows = conn.execute(
            "SELECT state, count(*) as cnt FROM inbox_trust_receipts GROUP BY state ORDER BY cnt DESC"
        ).fetchall()
        for row in rows:
            print(f"    {row['state'] or 'unknown':<20} {row['cnt']}")

        # Action breakdown
        rows = conn.execute(
            "SELECT action, count(*) as cnt FROM inbox_trust_receipts GROUP BY action ORDER BY cnt DESC"
        ).fetchall()
        print("\n  Actions:")
        for row in rows:
            print(f"    {row['action'] or 'unknown':<20} {row['cnt']}")

        # Confidence stats from decision_json
        decision_rows = conn.execute(
            "SELECT decision_json FROM inbox_trust_receipts WHERE decision_json IS NOT NULL"
        ).fetchall()
        confidences: list[float] = []
        latencies: list[float] = []
        fast_count = 0
        escalated_count = 0
        blocked_count = 0
        for row in decision_rows:
            try:
                d = json.loads(row["decision_json"])
                if not isinstance(d, dict):
                    continue
                conf = d.get("confidence")
                if conf is not None:
                    confidences.append(float(conf))
                lat = d.get("latency_seconds")
                if lat is not None:
                    latencies.append(float(lat))
                tier = str(d.get("execution_tier", "")).strip().lower()
                if tier == "fast":
                    fast_count += 1
                elif tier == "escalated":
                    escalated_count += 1
                if d.get("blocked_by_policy"):
                    blocked_count += 1
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.debug("Skipping malformed receipt metadata: %s", exc)
                continue

        if confidences:
            avg_conf = sum(confidences) / len(confidences)
            print(f"\n  Avg confidence:       {avg_conf:.1%}")
        if latencies:
            avg_lat = sum(latencies) / len(latencies)
            print(f"  Avg latency:          {avg_lat:.1f}s")
        if fast_count or escalated_count:
            print(f"  Fast decisions:       {fast_count}")
            print(f"  Escalated:            {escalated_count}")
        if blocked_count:
            print(f"  Blocked by policy:    {blocked_count}")

        # Date range
        date_row = conn.execute(
            "SELECT min(created_at) as first, max(created_at) as last FROM inbox_trust_receipts"
        ).fetchone()
        if date_row["first"]:
            first_date = str(date_row["first"])[:10]
            last_date = str(date_row["last"])[:10]
            print(f"\n  Date range:           {first_date} → {last_date}")

        # Override rate (human edits)
        override_count = conn.execute(
            "SELECT count(*) FROM inbox_trust_receipts WHERE review_choice IS NOT NULL "
            "AND review_choice NOT IN ('auto_approve', '')"
        ).fetchone()[0]
        if total > 0:
            override_pct = (override_count / total) * 100
            print(f"  Human overrides:      {override_count} ({override_pct:.1f}%)")

    except sqlite3.Error as exc:
        logger.debug("Error reading dogfood metrics: %s", exc)
    finally:
        conn.close()


def _get_store():
    """Get the InboxTrustWedgeStore singleton."""
    from aragora.inbox.trust_wedge import InboxTrustWedgeStore

    return InboxTrustWedgeStore()


def _show_review_queue(*, limit: int = 20, include_reviewed: bool = False) -> None:
    """Show prioritized review queue."""
    store = _get_store()
    items = store.list_review_queue(limit=limit, include_reviewed=include_reviewed)
    if not items:
        print("Review queue is empty.")
        return

    print(f"\nTriage Review Queue ({len(items)} items)")
    print(f"{'─' * 75}")
    print(f"{'#':<4} {'Conf':>5} {'Tier':<10} {'Action':<8} {'Subject':<30} {'Receipt ID':<10}")
    print(f"{'─' * 75}")
    for i, item in enumerate(items, 1):
        conf = item.get("confidence", 0.0)
        tier = item.get("execution_tier", "") or ""
        action = item.get("action", "")
        subject = (item.get("subject", "") or "")[:29]
        rid = (item.get("receipt_id", "") or "")[:8]
        blocked = " BLK" if item.get("blocked") else ""
        print(f"{i:<4} {conf:>4.0%}{blocked} {tier:<10} {action:<8} {subject:<30} {rid}")
    print(f"{'─' * 75}")
    print(f"\nLabel these: aragora triage label --batch {len(items)}")


def _run_fast_label(*, batch: int = 20, single_receipt_id: str | None = None) -> None:
    """Fast g/b/s labeling loop."""
    store = _get_store()
    items: list[dict[str, object]]

    if single_receipt_id:
        items = [{"receipt_id": single_receipt_id}]
        envelope = store.get_receipt(single_receipt_id)
        if envelope is None:
            print(f"Receipt not found: {single_receipt_id}")
            return
        # Build display dict from envelope
        intent = envelope.intent
        decision = envelope.decision
        items = [
            {
                "receipt_id": single_receipt_id,
                "action": str(getattr(intent, "action", "")),
                "confidence": float(cast(Any, getattr(decision, "confidence", 0.0)) or 0.0),
                "subject": str(getattr(intent, "_subject", "")),
                "sender": str(getattr(intent, "_sender", "")),
                "rationale": str(getattr(intent, "synthesized_rationale", "")),
                "blocked": bool(cast(Any, getattr(decision, "blocked_by_policy", False))),
            }
        ]
    else:
        items = store.list_review_queue(limit=batch)

    if not items:
        print("No items to label. Run some triage first: aragora triage run --batch 20")
        return

    print(f"\nFast Label ({len(items)} items) — [g]ood / [b]ad / [s]kip / [q]uit")
    print(f"{'─' * 70}")

    labeled = {"good": 0, "bad": 0, "skip": 0}
    for i, item in enumerate(items, 1):
        conf = float(cast(Any, item.get("confidence", 0.0) or 0.0))
        action = str(item.get("action", "?"))
        subject = str(item.get("subject", "") or "")[:40]
        sender = str(item.get("sender", "") or "")[:25]
        rationale = str(item.get("rationale", "") or "")[:60]
        rid = str(item.get("receipt_id", ""))

        print(f"\n[{i}/{len(items)}] {action:<8} {conf:>4.0%}  {sender}")
        print(f"         {subject}")
        if rationale:
            print(f"         {rationale}")

        while True:
            try:
                choice = input("  [g]ood / [b]ad / [s]kip / [q]uit > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "q"
            if choice in ("g", "good"):
                store.record_feedback(rid, label="good")
                labeled["good"] += 1
                break
            elif choice in ("b", "bad"):
                store.record_feedback(rid, label="bad")
                labeled["bad"] += 1
                break
            elif choice in ("s", "skip"):
                store.record_feedback(rid, label="skip")
                labeled["skip"] += 1
                break
            elif choice in ("q", "quit"):
                total = sum(labeled.values())
                print(
                    f"\nLabeled {total}/{len(items)}: {labeled['good']} good, {labeled['bad']} bad, {labeled['skip']} skip"
                )
                return
            else:
                print("  Enter g, b, s, or q")

    total = sum(labeled.values())
    print(f"\n{'─' * 70}")
    print(
        f"Labeled {total}/{len(items)}: {labeled['good']} good, {labeled['bad']} bad, {labeled['skip']} skip"
    )

    stats = store.get_feedback_stats()
    if stats["total"] > 0:
        print(
            f"Overall accuracy: {stats['accuracy']:.1%} ({stats['good']} good / {stats['good'] + stats['bad']} judged)"
        )


def _show_digest(*, hours: float = 24.0, as_json: bool = False) -> None:
    """Show daily triage digest."""
    store = _get_store()
    data = store.get_digest_data(since_hours=hours)

    if as_json:
        import json as json_mod

        # Remove items list for compact JSON output
        compact = {k: v for k, v in data.items() if k != "items"}
        print(json_mod.dumps(compact, indent=2, default=str))
        return

    total = data["total"]
    if total == 0:
        print(f"No triage activity in the last {hours:.0f}h.")
        return

    print(f"\nTriage Digest (last {hours:.0f}h)")
    print(f"{'═' * 50}")
    print(f"Processed: {total}")

    by_action = data.get("by_action", {})
    if by_action:
        parts = [f"{a}: {c}" for a, c in sorted(by_action.items(), key=lambda x: -x[1])]
        print(f"Actions:   {', '.join(parts)}")

    blocked = data.get("blocked_count", 0)
    if blocked:
        print(f"Blocked:   {blocked}")

    avg_conf = data.get("avg_confidence", 0.0)
    avg_lat = data.get("avg_latency_seconds", 0.0)
    cost = data.get("total_cost_usd", 0.0)
    print(f"\nAvg confidence: {avg_conf:.1%}")
    if avg_lat > 0:
        print(f"Avg latency:    {avg_lat:.1f}s")
    if cost > 0:
        print(f"Total cost:     ${cost:.4f}")

    by_domain = data.get("by_domain", {})
    if by_domain:
        print("\nTop sender domains:")
        for domain, count in list(by_domain.items())[:10]:
            print(f"  {domain:<35} {count}")

    # Show blocked items for review
    blocked_items = [item for item in data.get("items", []) if item.get("blocked")]
    if blocked_items:
        print("\nBlocked (review needed):")
        for item in blocked_items:
            subject = (item.get("subject", "") or "")[:50]
            sender = item.get("sender", "")
            print(f"  - {subject} ({sender})")

    feedback = data.get("feedback", {})
    if any(feedback.values()):
        print(
            f"\nFeedback: {feedback.get('good', 0)} good, {feedback.get('bad', 0)} bad, {feedback.get('skip', 0)} skip"
        )

    print(f"{'═' * 50}")


async def _run_audit(*, batch: int = 20, hours: float = 24.0, dry_run: bool = False) -> None:
    """Run adversarial audit of recent triage decisions."""
    store = _get_store()
    data = store.get_digest_data(since_hours=hours)
    items = data.get("items", [])[:batch]

    if not items:
        print(f"No triage activity in the last {hours:.0f}h to audit.")
        return

    from aragora.inbox.triage_instrumentation import build_audit_prompt, run_skeptical_audit

    prompt = build_audit_prompt(items)

    if dry_run:
        print("[DRY RUN] Audit prompt:\n")
        print(prompt)
        print(f"\n({len(items)} decisions would be audited)")
        return

    print(f"Auditing {len(items)} triage decisions...")
    verdicts = await run_skeptical_audit(items, store=store)

    if not verdicts:
        print("Audit produced no results (LLM call may have failed).")
        return

    print(f"\nAudit Results ({len(verdicts)} reviewed)")
    print(f"{'─' * 70}")
    good = sum(1 for v in verdicts if v.label == "good")
    bad = sum(1 for v in verdicts if v.label == "bad")
    shrug = sum(1 for v in verdicts if v.label == "skip")

    for v in verdicts:
        if v.label == "bad":
            marker = "BAD "
        elif v.label == "skip":
            marker = " ?  "
        else:
            marker = " OK "
        subject = (v.subject or "")[:35]
        print(f"  [{marker}] {v.action:<8} {v.confidence:>4.0%}  {subject}")
        if v.rationale and v.label != "good":
            print(f"         {v.rationale[:65]}")

    print(f"{'─' * 70}")
    print(f"Results: {good} good, {bad} bad, {shrug} uncertain")


def _show_calibration(*, as_json: bool = False) -> None:
    """Show calibration metrics from feedback labels."""
    store = _get_store()
    stats = store.get_feedback_stats()

    if stats["total"] < 5:
        print(f"Need at least 5 labeled decisions for calibration (have {stats['total']}).")
        print("Run: aragora triage label")
        return

    from aragora.inbox.triage_instrumentation import (
        compute_triage_calibration,
        suggest_threshold_adjustment,
    )

    cal = compute_triage_calibration(store)

    if as_json:
        import json as json_mod

        print(json_mod.dumps(cal, indent=2, default=str))
        return

    print(f"\nTriage Calibration ({cal['total_labeled']} labeled decisions)")
    print(f"{'═' * 55}")
    print(f"Overall accuracy: {cal['overall_accuracy']:.1%}")
    print(f"Brier score:      {cal['overall_brier']:.3f} (lower is better)")
    print(f"ECE:              {cal['ece']:.3f}")

    buckets = cal.get("buckets", [])
    if buckets:
        print(f"\n{'Bucket':<12} {'Count':>6} {'Accuracy':>9} {'Brier':>7} {'Good':>5} {'Bad':>5}")
        print(f"{'─' * 55}")
        for b in buckets:
            print(
                f"{b['bucket_key']:<12} {b['total']:>6} "
                f"{b['accuracy']:>8.1%} {b['brier_score']:>7.3f} "
                f"{b['good']:>5} {b['bad']:>5}"
            )

    suggestion = suggest_threshold_adjustment(cal)
    if suggestion:
        print(f"\n{suggestion}")
