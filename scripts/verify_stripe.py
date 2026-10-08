#!/usr/bin/env python3
"""
Stripe Configuration Verification Script.

Checks that all Stripe configuration is correct and functional.
Run this after setup_stripe.sh to verify everything works.
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment
from dotenv import load_dotenv

load_dotenv()
load_dotenv("/etc/aragora/.env")


def check_env_var(name: str, prefix: str | None = None, required: bool = True) -> tuple[bool, str]:
    """Check if environment variable is set and valid."""
    value = os.environ.get(name, "")

    if not value:
        if required:
            return False, "NOT SET"
        return True, "not set (optional)"

    if prefix and not value.startswith(prefix):
        return False, f"invalid prefix (expected {prefix}...)"

    # Mask sensitive values
    if "SECRET" in name or "KEY" in name:
        display = f"{value[:12]}...{value[-4:]}" if len(value) > 20 else f"{value[:8]}..."
    else:
        display = value

    return True, display


def check_stripe_api() -> tuple[bool, str]:
    """Test Stripe API connectivity."""
    try:
        import stripe

        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

        if not stripe.api_key:
            return False, "No API key configured"

        # Try to list products (minimal API call)
        products = stripe.Product.list(limit=1)
        return True, f"Connected ({len(products.data)} products found)"
    except stripe.error.AuthenticationError:
        return False, "Invalid API key"
    except stripe.error.APIConnectionError:
        return False, "Cannot connect to Stripe API"
    except Exception as e:
        return False, f"Error: {e}"


def check_webhook_endpoint() -> tuple[bool, str]:
    """Check webhook endpoint configuration."""
    try:
        import stripe

        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

        if not stripe.api_key:
            return False, "No API key"

        endpoints = stripe.WebhookEndpoint.list(limit=10)

        # Look for our endpoint
        target_url = "api.aragora.ai"
        for ep in endpoints.data:
            if target_url in ep.url:
                status = ep.status
                events = len(ep.enabled_events)
                return True, f"{ep.url} ({status}, {events} events)"

        return False, f"No endpoint found for {target_url}"
    except Exception as e:
        return False, f"Error: {e}"


def check_prices() -> tuple[bool, str]:
    """Verify price IDs exist in Stripe."""
    try:
        import stripe

        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

        if not stripe.api_key:
            return False, "No API key"

        prices = {
            "STARTER": os.environ.get("STRIPE_PRICE_STARTER", ""),
            "PROFESSIONAL": os.environ.get("STRIPE_PRICE_PROFESSIONAL", ""),
            "ENTERPRISE": os.environ.get("STRIPE_PRICE_ENTERPRISE", ""),
        }

        valid = 0
        invalid = []

        for tier, price_id in prices.items():
            if not price_id:
                invalid.append(f"{tier}: not set")
                continue

            try:
                price = stripe.Price.retrieve(price_id)
                valid += 1
            except stripe.error.InvalidRequestError:
                invalid.append(f"{tier}: {price_id} not found")

        if invalid:
            return False, f"{valid}/3 valid, issues: {', '.join(invalid)}"

        return True, "All 3 price IDs valid"
    except Exception as e:
        return False, f"Error: {e}"


def check_payout_settings() -> tuple[bool, str]:
    """Check payout/bank account configuration."""
    try:
        import stripe

        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

        if not stripe.api_key:
            return False, "No API key"

        account = stripe.Account.retrieve()

        # Check if payouts are enabled
        payouts_enabled = account.payouts_enabled
        charges_enabled = account.charges_enabled

        if not payouts_enabled:
            return False, "Payouts not enabled (complete verification)"

        if not charges_enabled:
            return False, "Charges not enabled (complete verification)"

        # Check external accounts (bank accounts)
        external = account.external_accounts
        if external and external.data:
            bank = external.data[0]
            bank_name = bank.get("bank_name", "Unknown")
            last4 = bank.get("last4", "****")
            return True, f"Payouts enabled → {bank_name} ****{last4}"

        return False, "No bank account connected"
    except Exception as e:
        return False, f"Error: {e}"


def check_database() -> tuple[bool, str]:
    """Check UserStore database is accessible."""
    try:
        from aragora.storage import UserStore

        db_path = Path.home() / ".nomic" / "users.db"
        if not db_path.exists():
            # Check alternative location
            db_path = Path("/var/lib/aragora/users.db")

        if not db_path.exists():
            return True, "Database will be created on first use"

        store = UserStore(db_path)
        # Quick test
        store.get_user_by_id("test-nonexistent")
        store.close()

        return True, f"Connected ({db_path})"
    except Exception as e:
        return False, f"Error: {e}"


def main():
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║           ARAGORA STRIPE VERIFICATION                    ║")
    print("╚═══════════════════════════════════════════════════════════╝")
    print()

    checks = [
        (
            "Environment Variables",
            [
                ("STRIPE_SECRET_KEY", lambda: check_env_var("STRIPE_SECRET_KEY", "sk_")),
                ("STRIPE_PUBLISHABLE_KEY", lambda: check_env_var("STRIPE_PUBLISHABLE_KEY", "pk_")),
                ("STRIPE_WEBHOOK_SECRET", lambda: check_env_var("STRIPE_WEBHOOK_SECRET", "whsec_")),
                ("STRIPE_PRICE_STARTER", lambda: check_env_var("STRIPE_PRICE_STARTER", "price_")),
                (
                    "STRIPE_PRICE_PROFESSIONAL",
                    lambda: check_env_var("STRIPE_PRICE_PROFESSIONAL", "price_"),
                ),
                (
                    "STRIPE_PRICE_ENTERPRISE",
                    lambda: check_env_var("STRIPE_PRICE_ENTERPRISE", "price_"),
                ),
            ],
        ),
        (
            "Stripe API",
            [
                ("API Connection", check_stripe_api),
                ("Webhook Endpoint", check_webhook_endpoint),
                ("Price IDs", check_prices),
                ("Payout Settings", check_payout_settings),
            ],
        ),
        (
            "Database",
            [
                ("UserStore", check_database),
            ],
        ),
    ]

    all_passed = True

    for section, items in checks:
        print(f"═══ {section} {'═' * (55 - len(section))}")
        for name, check_fn in items:
            try:
                passed, message = check_fn()
            except Exception as e:
                passed, message = False, f"Exception: {e}"

            status = "✓" if passed else "✗"
            color = "\033[92m" if passed else "\033[91m"
            reset = "\033[0m"

            print(f"  {color}{status}{reset} {name}: {message}")

            if not passed:
                all_passed = False
        print()

    print("═══════════════════════════════════════════════════════════")
    if all_passed:
        print("✓ All checks passed! Stripe is ready for production.")
        print()
        print("Next steps:")
        print("  1. Make a test purchase at https://aragora.ai")
        print("  2. Verify payment appears in Stripe Dashboard")
        print("  3. Wait 2 days for first payout to bank")
    else:
        print("✗ Some checks failed. Please fix the issues above.")
        print()
        print("Common fixes:")
        print("  - Run ./scripts/setup_stripe.sh to configure")
        print("  - Check Stripe Dashboard for correct values")
        print("  - Complete business verification if payouts disabled")
    print()

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
