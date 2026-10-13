"""
Aragora Billing CLI.

Commands for managing billing, usage, and subscription status.
API-first design - no UI needed.

Usage:
    aragora billing status
    aragora billing usage --month 2026-01
    aragora billing subscribe --plan pro
"""

import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

DEFAULT_API_URL = os.environ.get("ARAGORA_API_URL", "http://localhost:8080")


def get_api_token() -> str | None:
    """Get API token from environment."""
    return os.environ.get("ARAGORA_API_TOKEN") or os.environ.get("ARAGORA_API_KEY")


def api_request(
    method: str,
    path: str,
    data: dict[str, Any] | None = None,
    server_url: str = DEFAULT_API_URL,
) -> dict[str, Any]:
    """Make API request."""
    url = f"{server_url.rstrip('/')}{path}"
    token = get_api_token()

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        payload = json.dumps(data).encode("utf-8") if data is not None else None
        # CLI server URL
        req = urllib.request.Request(url, data=payload, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:  # CLI server URL
            body = resp.read() or b"{}"
            result: dict[str, Any] = json.loads(body)
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API error ({e.code}): {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection error: {e}")


def cmd_status(args: argparse.Namespace) -> int:
    """Show billing/subscription status."""
    print("\n" + "=" * 60)
    print("ARAGORA BILLING STATUS")
    print("=" * 60)

    try:
        # Try API first
        result = api_request("GET", "/api/billing/status", server_url=args.server)

        plan = result.get("plan", {})
        usage = result.get("current_usage", {})
        limits = result.get("limits", {})

        print(f"\nPlan: {plan.get('name', 'Unknown')}")
        print(f"Status: {plan.get('status', 'Unknown')}")
        if plan.get("billing_period_end"):
            print(f"Period ends: {plan.get('billing_period_end')}")

        print("\nUsage this period:")
        print(f"  Debates: {usage.get('debates', 0)} / {limits.get('debates', 'unlimited')}")
        token_limit = limits.get("tokens", "unlimited")
        # A numeric limit gets thousands separators; an unlimited (string) limit
        # is rendered verbatim, since ':,' is invalid on strings.
        token_limit_str = (
            f"{token_limit:,}" if isinstance(token_limit, (int, float)) else token_limit
        )
        print(f"  Tokens: {usage.get('tokens', 0):,} / {token_limit_str}")
        cost = usage.get("cost_usd", "0")
        print(f"  Cost: ${float(cost):.2f}")

        # Show overages if any
        overages = result.get("overages", {})
        if overages.get("debates", 0) > 0 or overages.get("tokens", 0) > 0:
            print("\n⚠️  Overages:")
            if overages.get("debates", 0) > 0:
                print(f"  Debates: {overages['debates']} extra")
            if overages.get("tokens", 0) > 0:
                print(f"  Tokens: {overages['tokens']:,} extra")

        return 0

    except RuntimeError as e:
        if "Connection" in str(e):
            # Fall back to local usage tracking
            return cmd_status_local(args)
        print(f"\nError: {e}")
        return 1


def cmd_status_local(args: argparse.Namespace) -> int:
    """Show local usage when server not available."""
    try:
        from aragora.billing.usage import UsageTracker

        tracker = UsageTracker()
        org_id = os.environ.get("ARAGORA_ORG_ID", "default")
        summary = tracker.get_summary(org_id)

        print("\n(Local usage data - server not connected)")
        print(f"\nOrganization: {org_id}")
        print(f"Period: {summary.period_start.date()} to {summary.period_end.date()}")
        print(f"\nDebates: {summary.total_debates}")
        print(f"API calls: {summary.total_api_calls}")
        print(f"Agent calls: {summary.total_agent_calls}")
        print(f"Total tokens: {summary.total_tokens_in + summary.total_tokens_out:,}")
        print(f"Total cost: ${summary.total_cost_usd:.4f}")

        if summary.cost_by_provider:
            print("\nCost by provider:")
            for provider, cost in sorted(
                summary.cost_by_provider.items(), key=lambda x: -float(x[1])
            ):
                print(f"  {provider}: ${float(cost):.4f}")

        return 0

    except (ImportError, OSError, RuntimeError, ValueError) as e:
        print(f"\nError reading local usage: {e}")
        return 1


def cmd_usage(args: argparse.Namespace) -> int:
    """Show detailed usage for a period."""
    print("\n" + "=" * 60)
    print("ARAGORA USAGE REPORT")
    print("=" * 60)

    # Parse month parameter
    if args.month:
        try:
            year, month = map(int, args.month.split("-"))
            period_start = datetime(year, month, 1)
            if month == 12:
                period_end = datetime(year + 1, 1, 1)
            else:
                period_end = datetime(year, month + 1, 1)
        except ValueError:
            print(f"\nError: Invalid month format '{args.month}'. Use YYYY-MM.")
            return 1
    else:
        # Default to current month
        now = datetime.now()
        period_start = datetime(now.year, now.month, 1)
        period_end = now

    print(f"\nPeriod: {period_start.date()} to {period_end.date()}")

    try:
        # Try API
        result = api_request(
            "GET",
            f"/api/billing/usage?start={period_start.isoformat()}&end={period_end.isoformat()}",
            server_url=args.server,
        )

        usage = result.get("usage", result)

        print(f"\nDebates: {usage.get('total_debates', 0)}")
        print(f"API calls: {usage.get('total_api_calls', 0)}")
        print(f"Agent calls: {usage.get('total_agent_calls', 0)}")
        print(f"Tokens in: {usage.get('total_tokens_in', 0):,}")
        print(f"Tokens out: {usage.get('total_tokens_out', 0):,}")
        print(f"Total cost: ${float(usage.get('total_cost_usd', '0')):.4f}")

        # Provider breakdown
        by_provider = usage.get("cost_by_provider", {})
        if by_provider:
            print("\nCost by provider:")
            for provider, cost in sorted(by_provider.items(), key=lambda x: -float(x[1])):
                print(f"  {provider}: ${float(cost):.4f}")

        # Daily breakdown
        by_day = usage.get("debates_by_day", {})
        if by_day and args.verbose:
            print("\nDebates by day:")
            for day, count in sorted(by_day.items()):
                bar = "█" * min(count, 50)
                print(f"  {day}: {count:3d} {bar}")

        return 0

    except RuntimeError as e:
        if "Connection" in str(e):
            return cmd_usage_local(args, period_start, period_end)
        print(f"\nError: {e}")
        return 1


def cmd_usage_local(args: argparse.Namespace, period_start: datetime, period_end: datetime) -> int:
    """Show local usage when server not available."""
    try:
        from aragora.billing.usage import UsageTracker

        tracker = UsageTracker()
        org_id = os.environ.get("ARAGORA_ORG_ID", "default")
        summary = tracker.get_summary(org_id, period_start, period_end)

        print("\n(Local usage data - server not connected)")
        print(f"\nDebates: {summary.total_debates}")
        print(f"API calls: {summary.total_api_calls}")
        print(f"Agent calls: {summary.total_agent_calls}")
        print(f"Tokens in: {summary.total_tokens_in:,}")
        print(f"Tokens out: {summary.total_tokens_out:,}")
        print(f"Total cost: ${summary.total_cost_usd:.4f}")

        if summary.cost_by_provider:
            print("\nCost by provider:")
            for provider, cost in sorted(
                summary.cost_by_provider.items(), key=lambda x: -float(x[1])
            ):
                print(f"  {provider}: ${float(cost):.4f}")

        if summary.debates_by_day and args.verbose:
            print("\nDebates by day:")
            for day, count in sorted(summary.debates_by_day.items()):
                bar = "█" * min(count, 50)
                print(f"  {day}: {count:3d} {bar}")

        return 0

    except (ImportError, OSError, RuntimeError, ValueError) as e:
        print(f"\nError reading local usage: {e}")
        return 1


def cmd_subscribe(args: argparse.Namespace) -> int:
    """Subscribe to a plan or update subscription."""
    print("\n" + "=" * 60)
    print("ARAGORA SUBSCRIPTION")
    print("=" * 60)

    plan = args.plan

    try:
        result = api_request(
            "POST",
            "/api/billing/subscribe",
            data={"plan": plan},
            server_url=args.server,
        )

        if result.get("checkout_url"):
            print("\nTo complete subscription, visit:")
            print(f"  {result['checkout_url']}")
            print("\n(Or use --open to open in browser)")

            if args.open:
                import webbrowser

                webbrowser.open(result["checkout_url"])

        elif result.get("success"):
            print(f"\nSuccessfully subscribed to {plan} plan!")

        return 0

    except RuntimeError as e:
        print(f"\nError: {e}")
        return 1


def cmd_portal(args: argparse.Namespace) -> int:
    """Open billing portal."""
    print("\n" + "=" * 60)
    print("ARAGORA BILLING PORTAL")
    print("=" * 60)

    try:
        result = api_request("POST", "/api/billing/portal", server_url=args.server)

        portal_url = result.get("url")
        if portal_url:
            print("\nBilling portal URL:")
            print(f"  {portal_url}")

            if not args.no_open:
                import webbrowser

                webbrowser.open(portal_url)
                print("\n(Opened in browser)")

        return 0

    except RuntimeError as e:
        print(f"\nError: {e}")
        return 1


def cmd_invoices(args: argparse.Namespace) -> int:
    """List invoices."""
    print("\n" + "=" * 60)
    print("ARAGORA INVOICES")
    print("=" * 60)

    try:
        result = api_request(
            "GET", f"/api/billing/invoices?limit={args.limit}", server_url=args.server
        )

        invoices = result.get("invoices", [])

        if not invoices:
            print("\nNo invoices found.")
            return 0

        print(f"\n{'Date':<12} {'Amount':>10} {'Status':<10} {'ID'}")
        print("-" * 60)

        for inv in invoices:
            date = inv.get("date", "")[:10]
            # Coalesce an explicit JSON null (not just a missing key) to 0 cents.
            amount = (inv.get("amount") or 0) / 100  # cents to dollars
            status = inv.get("status", "unknown")
            inv_id = inv.get("id", "")[:20]
            print(f"{date:<12} ${amount:>9.2f} {status:<10} {inv_id}")

        return 0

    except RuntimeError as e:
        print(f"\nError: {e}")
        return 1


def create_billing_parser(subparsers: argparse._SubParsersAction) -> None:
    """Create billing subcommand parser."""
    billing_parser = subparsers.add_parser(
        "billing",
        help="Manage billing, usage, and subscriptions",
        description="""
Manage your Aragora billing and usage.

Examples:
    aragora billing status              # Show current plan and usage
    aragora billing usage               # Show this month's usage
    aragora billing usage --month 2026-01  # Show specific month
    aragora billing subscribe --plan pro   # Subscribe to Pro plan
    aragora billing portal              # Open billing portal
    aragora billing invoices            # List invoices
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    billing_subparsers = billing_parser.add_subparsers(dest="billing_action")

    # Status
    status_parser = billing_subparsers.add_parser("status", help="Show billing status")
    status_parser.add_argument("--server", "-s", default=DEFAULT_API_URL, help="API server URL")
    status_parser.set_defaults(func=cmd_status)

    # Usage
    usage_parser = billing_subparsers.add_parser("usage", help="Show usage details")
    usage_parser.add_argument("--month", "-m", help="Month to show (YYYY-MM)")
    usage_parser.add_argument("--verbose", "-v", action="store_true", help="Show daily breakdown")
    usage_parser.add_argument("--server", "-s", default=DEFAULT_API_URL, help="API server URL")
    usage_parser.set_defaults(func=cmd_usage)

    # Subscribe
    subscribe_parser = billing_subparsers.add_parser("subscribe", help="Subscribe to a plan")
    subscribe_parser.add_argument(
        "--plan",
        "-p",
        required=True,
        choices=["free", "pro", "team", "enterprise"],
        help="Plan to subscribe to",
    )
    subscribe_parser.add_argument(
        "--open", "-o", action="store_true", help="Open checkout in browser"
    )
    subscribe_parser.add_argument("--server", "-s", default=DEFAULT_API_URL, help="API server URL")
    subscribe_parser.set_defaults(func=cmd_subscribe)

    # Portal
    portal_parser = billing_subparsers.add_parser("portal", help="Open billing management portal")
    portal_parser.add_argument(
        "--no-open", action="store_true", help="Don't open browser automatically"
    )
    portal_parser.add_argument("--server", "-s", default=DEFAULT_API_URL, help="API server URL")
    portal_parser.set_defaults(func=cmd_portal)

    # Invoices
    invoices_parser = billing_subparsers.add_parser("invoices", help="List invoices")
    invoices_parser.add_argument(
        "--limit", "-n", type=int, default=10, help="Number of invoices to show"
    )
    invoices_parser.add_argument("--server", "-s", default=DEFAULT_API_URL, help="API server URL")
    invoices_parser.set_defaults(func=cmd_invoices)

    # Default to status
    billing_parser.set_defaults(func=cmd_billing_default)


def cmd_billing_default(args: argparse.Namespace) -> int:
    """Default billing command (show status)."""
    if not hasattr(args, "billing_action") or args.billing_action is None:
        args.server = getattr(args, "server", DEFAULT_API_URL)
        return cmd_status(args)
    return 0


def main(args: argparse.Namespace) -> int:
    """Main entry point for billing commands."""
    if hasattr(args, "func"):
        ret: int = args.func(args)
        return ret
    return cmd_billing_default(args)


__all__ = ["create_billing_parser", "main"]
