"""
Aragora Setup Wizard - Interactive configuration tool.

Guides users through initial setup including:
- API key configuration
- Database configuration (SQLite/PostgreSQL migration)
- Integration setup (Slack, Teams, Stripe)
- OAuth configuration
- .env file generation
- Connectivity and health check verification
"""

from __future__ import annotations

import os
import secrets as secrets_mod
import sys
from pathlib import Path
from typing import Any

from aragora.config.secrets import get_secret_presence, is_secret_presence_available


class SetupError(Exception):
    """Raised when setup cannot complete (e.g. no API key resolvable).

    Distinct from a user-cancelled setup (which exits 0). The CLI entry point
    maps this to a non-zero exit code so non-interactive callers can detect
    failure instead of receiving a silent success.
    """


def _local_env_value(name: str) -> str:
    return os.environ.get(name, "")


# Provider keys that, if resolvable by any path (env, .env, or AWS Secrets
# Manager), satisfy the "at least one API key" requirement.
_PROVIDER_SECRET_NAMES = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "MISTRAL_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
)


def _managed_secret_present(name: str) -> bool:
    try:
        presence = get_secret_presence(name)
        return is_secret_presence_available(presence) and presence.source != "env"
    except Exception:  # noqa: BLE001 - presence probe must never fail setup
        return False


def _managed_provider_key_present() -> bool:
    """Return True if any provider key is resolvable from managed custody."""
    return any(_managed_secret_present(name) for name in _PROVIDER_SECRET_NAMES)


def _prompt(message: str, default: str | None = None, secret: bool = False) -> str:
    """Prompt user for input with optional default and secret mode."""
    suffix = f" [{default}]" if default else ""
    try:
        if secret:
            import getpass

            value = getpass.getpass(f"{message}{suffix}: ")
        else:
            value = input(f"{message}{suffix}: ")
        return value.strip() or (default or "")
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        sys.exit(0)


def _confirm(message: str, default: bool = True) -> bool:
    """Ask for yes/no confirmation."""
    suffix = " [Y/n]" if default else " [y/N]"
    try:
        response = input(f"{message}{suffix}: ").strip().lower()
        if not response:
            return default
        return response in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        sys.exit(0)


def _print_header(text: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


def _print_step(step: int, total: int, text: str) -> None:
    """Print a step indicator."""
    print(f"\n[{step}/{total}] {text}")
    print("-" * 40)


def _test_api_key(provider: str, key: str) -> tuple[bool, str]:
    """Test an API key by making a minimal request."""
    if not key:
        return False, "No key provided"

    try:
        if provider == "anthropic":
            from aragora.security.safe_http import safe_post

            response = safe_post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "Hi"}],
                },
                timeout=10.0,
            )
            if response.status_code == 200:
                return True, "Valid"
            elif response.status_code == 401:
                return False, "Invalid key"
            else:
                return False, f"Error: {response.status_code}"

        elif provider == "openai":
            from aragora.security.safe_http import safe_get

            response = safe_get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=10.0,
            )
            if response.status_code == 200:
                return True, "Valid"
            elif response.status_code == 401:
                return False, "Invalid key"
            else:
                return False, f"Error: {response.status_code}"

        elif provider == "openrouter":
            from aragora.security.safe_http import safe_get

            response = safe_get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=10.0,
            )
            if response.status_code == 200:
                return True, "Valid"
            elif response.status_code == 401:
                return False, "Invalid key"
            else:
                return False, f"Error: {response.status_code}"

        else:
            return True, "Stored (not validated)"

    except ImportError:
        return True, "Stored (httpx not installed for validation)"
    except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
        return False, f"Connection error: {str(e)[:50]}"


def _generate_env_content(config: dict[str, Any]) -> str:
    """Generate .env file content from config."""
    lines = [
        "# Aragora Configuration",
        "# Generated by aragora setup",
        "",
        "# =============================================================================",
        "# API Keys (at least one required)",
        "# =============================================================================",
        "",
    ]

    # Required keys
    if config.get("anthropic_key"):
        lines.append(f"ANTHROPIC_API_KEY={config['anthropic_key']}")
    else:
        lines.append("# ANTHROPIC_API_KEY=your-key-here")

    if config.get("openai_key"):
        lines.append(f"OPENAI_API_KEY={config['openai_key']}")
    else:
        lines.append("# OPENAI_API_KEY=your-key-here")

    lines.append("")

    # Optional provider keys
    lines.append("# Optional provider keys")
    if config.get("openrouter_key"):
        lines.append(f"OPENROUTER_API_KEY={config['openrouter_key']}")
    else:
        lines.append("# OPENROUTER_API_KEY=your-key-here  # Fallback on rate limits")

    if config.get("mistral_key"):
        lines.append(f"MISTRAL_API_KEY={config['mistral_key']}")
    if config.get("gemini_key"):
        lines.append(f"GEMINI_API_KEY={config['gemini_key']}")
    if config.get("xai_key"):
        lines.append(f"XAI_API_KEY={config['xai_key']}")

    lines.append("")

    # Server configuration
    lines.extend(
        [
            "# =============================================================================",
            "# Server Configuration",
            "# =============================================================================",
            "",
            f"ARAGORA_HTTP_PORT={config.get('http_port', 8080)}",
            f"ARAGORA_WS_PORT={config.get('ws_port', 8765)}",
            "",
        ]
    )

    # Database configuration
    if config.get("database_mode") == "postgres":
        lines.extend(
            [
                "# Database (PostgreSQL)",
                f"DATABASE_URL={config.get('database_url', 'postgresql://localhost:5432/aragora')}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "# Database (SQLite - default)",
                "# DATABASE_URL=sqlite:///aragora.db",
                "",
            ]
        )

    # Redis configuration
    if config.get("redis_url"):
        lines.extend(
            [
                "# Redis (optional - for caching/sessions)",
                f"REDIS_URL={config['redis_url']}",
                "",
            ]
        )

    # Security
    if config.get("encryption_key"):
        lines.extend(
            [
                "# Security",
                f"ARAGORA_ENCRYPTION_KEY={config['encryption_key']}",
                "",
            ]
        )

    # Integrations
    has_integrations = any(
        config.get(k)
        for k in [
            "slack_client_id",
            "slack_client_secret",
            "slack_token",
            "teams_client_id",
            "teams_client_secret",
            "teams_tenant_id",
            "github_token",
            "telegram_token",
            "stripe_secret_key",
        ]
    )
    if has_integrations:
        lines.extend(
            [
                "# =============================================================================",
                "# Integrations",
                "# =============================================================================",
                "",
            ]
        )

        # Slack OAuth
        if config.get("slack_client_id"):
            lines.append("# Slack OAuth Configuration")
            lines.append(f"SLACK_CLIENT_ID={config['slack_client_id']}")
            lines.append(f"SLACK_CLIENT_SECRET={config.get('slack_client_secret', '')}")
            if config.get("slack_signing_secret"):
                lines.append(f"SLACK_SIGNING_SECRET={config['slack_signing_secret']}")
            if config.get("slack_token"):
                lines.append(f"SLACK_BOT_TOKEN={config['slack_token']}")
            lines.append("")
        elif config.get("slack_token"):
            lines.append(f"SLACK_BOT_TOKEN={config['slack_token']}")
            lines.append("")

        # Teams OAuth
        if config.get("teams_client_id"):
            lines.append("# Microsoft Teams Configuration")
            lines.append(f"TEAMS_CLIENT_ID={config['teams_client_id']}")
            lines.append(f"TEAMS_CLIENT_SECRET={config.get('teams_client_secret', '')}")
            if config.get("teams_tenant_id"):
                lines.append(f"TEAMS_TENANT_ID={config['teams_tenant_id']}")
            if config.get("teams_bot_id"):
                lines.append(f"TEAMS_BOT_ID={config['teams_bot_id']}")
            lines.append("")

        # GitHub
        if config.get("github_token"):
            lines.append(f"GITHUB_TOKEN={config['github_token']}")
            lines.append("")

        # Telegram
        if config.get("telegram_token"):
            lines.append(f"TELEGRAM_BOT_TOKEN={config['telegram_token']}")
            lines.append("")

        # Stripe Billing
        if config.get("stripe_secret_key"):
            lines.append("# Stripe Billing Configuration")
            lines.append(f"STRIPE_SECRET_KEY={config['stripe_secret_key']}")
            if config.get("stripe_publishable_key"):
                lines.append(f"STRIPE_PUBLISHABLE_KEY={config['stripe_publishable_key']}")
            if config.get("stripe_webhook_secret"):
                lines.append(f"STRIPE_WEBHOOK_SECRET={config['stripe_webhook_secret']}")
            if config.get("stripe_price_id"):
                lines.append(f"STRIPE_PRICE_ID={config['stripe_price_id']}")
            lines.append("")

    return "\n".join(lines)


def _run_health_checks(config: dict[str, Any]) -> None:
    """Run health check verification after setup."""
    print("\n  Running health checks...")
    checks_passed = 0
    checks_total = 0

    # Check 1: Database connectivity
    checks_total += 1
    if config.get("database_mode") == "postgres":
        db_url = config.get("database_url", "")
        print("    Checking PostgreSQL connectivity...", end=" ", flush=True)
        try:
            import psycopg2

            # Parse connection string
            conn = psycopg2.connect(db_url)
            conn.close()
            print("OK")
            checks_passed += 1
        except ImportError:
            print("SKIP (psycopg2 not installed)")
            checks_passed += 1  # Not a failure, just not testable
        except (OSError, ConnectionError, RuntimeError) as e:
            print(f"FAILED ({str(e)[:40]})")
    else:
        print("    Checking SQLite availability...", end=" ", flush=True)
        try:
            import sqlite3

            conn = sqlite3.connect(":memory:")
            conn.close()
            print("OK")
            checks_passed += 1
        except (OSError, RuntimeError) as e:
            print(f"FAILED ({e})")

    # Check 2: Redis connectivity (if configured)
    if config.get("redis_url"):
        checks_total += 1
        print("    Checking Redis connectivity...", end=" ", flush=True)
        try:
            import redis

            r = redis.from_url(config["redis_url"])
            r.ping()
            print("OK")
            checks_passed += 1
        except ImportError:
            print("SKIP (redis not installed)")
            checks_passed += 1
        except (OSError, ConnectionError, RuntimeError) as e:
            print(f"FAILED ({str(e)[:40]})")

    # Check 3: Stripe API (if configured)
    if config.get("stripe_secret_key"):
        checks_total += 1
        print("    Checking Stripe API...", end=" ", flush=True)
        try:
            from aragora.security.safe_http import safe_get

            response = safe_get(
                "https://api.stripe.com/v1/balance",
                headers={"Authorization": f"Bearer {config['stripe_secret_key']}"},
                timeout=10.0,
            )
            if response.status_code == 200:
                print("OK")
                checks_passed += 1
            elif response.status_code == 401:
                print("FAILED (invalid key)")
            else:
                print(f"FAILED (HTTP {response.status_code})")
        except ImportError:
            print("SKIP (httpx not installed)")
            checks_passed += 1
        except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
            print(f"FAILED ({str(e)[:40]})")

    # Check 4: Required Python packages
    checks_total += 1
    print("    Checking required packages...", end=" ", flush=True)
    missing_packages = []
    for pkg in ["httpx", "pydantic", "aiohttp"]:
        try:
            __import__(pkg)
        except ImportError:
            missing_packages.append(pkg)
    if missing_packages:
        print(f"MISSING: {', '.join(missing_packages)}")
    else:
        print("OK")
        checks_passed += 1

    # Summary
    print(f"\n    Health checks: {checks_passed}/{checks_total} passed")
    if checks_passed < checks_total:
        print("    Some checks failed - review the output above.")


def run_setup(
    output_path: str | None = None,
    minimal: bool = False,
    skip_test: bool = False,
    non_interactive: bool = False,
) -> dict[str, Any]:
    """Run the interactive setup wizard.

    Args:
        output_path: Path to write .env file (default: current directory)
        minimal: Only configure essential settings
        skip_test: Skip API key validation
        non_interactive: Use defaults without prompting

    Returns:
        Configuration dictionary
    """
    config: dict[str, Any] = {}

    _print_header("Aragora Setup Wizard")
    print("This wizard will help you configure Aragora.")
    print("Press Ctrl+C at any time to cancel.\n")

    total_steps = 3 if minimal else 5

    # Step 1: API Keys
    _print_step(1, total_steps, "API Keys Configuration")
    print("Aragora requires at least one AI provider API key.\n")

    # Anthropic
    existing_anthropic = _local_env_value("ANTHROPIC_API_KEY")
    if existing_anthropic:
        print(f"  Found existing ANTHROPIC_API_KEY: {existing_anthropic[:8]}...")
        # In non-interactive mode, adopt the key already present in the env so
        # setup can complete with defaults. Interactively, confirm first.
        if non_interactive or _confirm("  Use existing key?"):
            config["anthropic_key"] = existing_anthropic
        else:
            config["anthropic_key"] = _prompt("  Anthropic API Key", secret=True)
    elif _managed_secret_present("ANTHROPIC_API_KEY"):
        print("  ANTHROPIC_API_KEY is configured via managed custody; not copying to .env.")
        config["anthropic_key"] = ""
    else:
        config["anthropic_key"] = (
            _prompt("  Anthropic API Key (recommended)", secret=True) if not non_interactive else ""
        )

    # OpenAI
    existing_openai = _local_env_value("OPENAI_API_KEY")
    if existing_openai:
        print(f"  Found existing OPENAI_API_KEY: {existing_openai[:8]}...")
        if non_interactive or _confirm("  Use existing key?"):
            config["openai_key"] = existing_openai
        else:
            config["openai_key"] = _prompt("  OpenAI API Key", secret=True)
    elif _managed_secret_present("OPENAI_API_KEY"):
        print("  OPENAI_API_KEY is configured via managed custody; not copying to .env.")
        config["openai_key"] = ""
    else:
        config["openai_key"] = (
            _prompt("  OpenAI API Key", secret=True) if not non_interactive else ""
        )

    # Optional provider keys already present in the environment are adopted in
    # non-interactive mode so they are persisted to .env alongside the primary
    # keys. (Interactive flows configure these via the integrations steps.)
    if non_interactive:
        for env_name, config_key in (
            ("OPENROUTER_API_KEY", "openrouter_key"),
            ("MISTRAL_API_KEY", "mistral_key"),
            ("GEMINI_API_KEY", "gemini_key"),
            ("XAI_API_KEY", "xai_key"),
        ):
            existing_optional = _local_env_value(env_name)
            if existing_optional:
                print(f"  Found existing {env_name}: {existing_optional[:8]}...")
                config[config_key] = existing_optional

    # Check we have at least one resolvable provider key.
    has_any_key = any(
        config.get(k)
        for k in (
            "anthropic_key",
            "openai_key",
            "openrouter_key",
            "mistral_key",
            "gemini_key",
            "xai_key",
        )
    )
    # A provider key may also be resolvable through managed custody, in which
    # case it is NOT written to .env but still counts as configured.
    key_resolvable = has_any_key or _managed_provider_key_present()

    if not key_resolvable:
        print("\n  Warning: No API keys configured. Aragora requires at least one.")
        if non_interactive:
            # Non-interactive setup cannot prompt for a key. Signal failure
            # clearly instead of returning a keyless config with a zero exit
            # code (which would be a silent failure).
            raise SetupError(
                "No API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY in "
                "the environment (or AWS Secrets Manager) before running "
                "non-interactive setup."
            )
        if _confirm("  Continue anyway?", default=False):
            pass
        else:
            print("  Please provide at least one API key.")
            return config

    # Optional: OpenRouter (fallback)
    if not minimal and not non_interactive:
        if _confirm("\n  Configure OpenRouter for fallback? (recommended)"):
            config["openrouter_key"] = _prompt("  OpenRouter API Key", secret=True)

    # Step 2: Test API Keys
    if not skip_test and (config.get("anthropic_key") or config.get("openai_key")):
        _print_step(2, total_steps, "Testing API Keys")

        if config.get("anthropic_key"):
            print("  Testing Anthropic key...", end=" ", flush=True)
            success, msg = _test_api_key("anthropic", config["anthropic_key"])
            print(f"{'OK' if success else 'FAILED'} ({msg})")

        if config.get("openai_key"):
            print("  Testing OpenAI key...", end=" ", flush=True)
            success, msg = _test_api_key("openai", config["openai_key"])
            print(f"{'OK' if success else 'FAILED'} ({msg})")

        if config.get("openrouter_key"):
            print("  Testing OpenRouter key...", end=" ", flush=True)
            success, msg = _test_api_key("openrouter", config["openrouter_key"])
            print(f"{'OK' if success else 'FAILED'} ({msg})")
    else:
        _print_step(2, total_steps, "Skipping API Key Tests")

    # Step 3: Server Configuration
    _print_step(3, total_steps, "Server Configuration")

    if non_interactive:
        config["http_port"] = 8080
        config["ws_port"] = 8765
        config["database_mode"] = "sqlite"
    else:
        config["http_port"] = int(_prompt("  HTTP Port", "8080") or 8080)
        config["ws_port"] = int(_prompt("  WebSocket Port", "8765") or 8765)

        print("\n  Database options:")
        print("    1. SQLite (simple, no setup required)")
        print("    2. PostgreSQL (production-ready, requires setup)")
        db_choice = _prompt("  Select database [1/2]", "1")
        if db_choice == "2":
            config["database_mode"] = "postgres"
            config["database_url"] = _prompt(
                "  PostgreSQL URL", "postgresql://localhost:5432/aragora"
            )
        else:
            config["database_mode"] = "sqlite"

    if not minimal and not non_interactive:
        # Step 4: Integrations (optional)
        _print_step(4, total_steps, "Integrations (Optional)")
        print("  Configure integrations to connect Aragora with external services.\n")

        # Slack OAuth Configuration
        if _confirm("  Configure Slack integration?", default=False):
            print("\n    Slack OAuth Setup")
            print("    -----------------")
            print("    To set up Slack OAuth, you'll need to create a Slack app at:")
            print("    https://api.slack.com/apps\n")
            print("    Options:")
            print("      1. Full OAuth (recommended for production)")
            print("      2. Simple bot token (for development)")
            slack_mode = _prompt("    Select mode [1/2]", "2")

            if slack_mode == "1":
                config["slack_client_id"] = _prompt("    Slack Client ID")
                config["slack_client_secret"] = _prompt("    Slack Client Secret", secret=True)
                config["slack_signing_secret"] = _prompt("    Slack Signing Secret", secret=True)
                print("\n    Configure OAuth redirect URL in Slack app settings:")
                print("    https://your-domain/api/v1/oauth/slack/callback\n")
            else:
                config["slack_token"] = _prompt("    Slack Bot Token (xoxb-...)", secret=True)

        # Teams OAuth Configuration
        if _confirm("  Configure Microsoft Teams integration?", default=False):
            print("\n    Microsoft Teams Setup")
            print("    ----------------------")
            print("    To set up Teams, you'll need:")
            print("    1. Azure AD app registration (https://portal.azure.com)")
            print("    2. Bot Framework registration (https://dev.botframework.com)\n")

            config["teams_client_id"] = _prompt("    Azure AD Client ID")
            config["teams_client_secret"] = _prompt("    Azure AD Client Secret", secret=True)
            config["teams_tenant_id"] = _prompt(
                "    Azure Tenant ID (or 'common' for multi-tenant)", "common"
            )
            config["teams_bot_id"] = _prompt("    Bot Framework Bot ID (optional)")

            print("\n    Configure redirect URL in Azure AD:")
            print("    https://your-domain/api/v1/oauth/teams/callback\n")

        # Stripe Billing Configuration
        if _confirm("  Configure Stripe billing?", default=False):
            print("\n    Stripe Billing Setup")
            print("    ---------------------")
            print("    To enable billing, you'll need a Stripe account at:")
            print("    https://dashboard.stripe.com\n")

            config["stripe_secret_key"] = _prompt("    Stripe Secret Key (sk_...)", secret=True)
            config["stripe_publishable_key"] = _prompt("    Stripe Publishable Key (pk_...)")
            config["stripe_webhook_secret"] = _prompt(
                "    Stripe Webhook Secret (whsec_...)", secret=True
            )

            print("\n    Configure webhook endpoint in Stripe:")
            print("    https://your-domain/api/v1/billing/stripe/webhook\n")

        # Other integrations
        if _confirm("  Configure GitHub integration?", default=False):
            config["github_token"] = _prompt("    GitHub Token", secret=True)

        if _confirm("  Configure Telegram integration?", default=False):
            config["telegram_token"] = _prompt("    Telegram Bot Token", secret=True)

        # Step 5: Security
        _print_step(5, total_steps, "Security Configuration")

        if _confirm("  Generate encryption key for secrets?", default=True):
            config["encryption_key"] = secrets_mod.token_hex(32)
            print(f"    Generated key: {config['encryption_key'][:16]}...")

    # Generate .env file
    _print_header("Generating Configuration")

    env_content = _generate_env_content(config)
    target_path = Path(output_path) if output_path else Path.cwd()
    env_file_path = target_path / ".env"
    env_file: Path | None = env_file_path

    # Check for existing file
    if env_file_path.exists():
        print(f"  Existing .env file found at: {env_file_path}")
        if non_interactive:
            backup = env_file_path.with_suffix(".env.backup")
            env_file_path.rename(backup)
            print(f"  Backed up to: {backup}")
        elif _confirm("  Overwrite existing .env file?", default=False):
            backup = env_file_path.with_suffix(".env.backup")
            env_file_path.rename(backup)
            print(f"  Backed up to: {backup}")
        else:
            print("  Skipping .env file generation.")
            env_file = None

    if env_file:
        env_file.write_text(env_content)
        print(f"  Created: {env_file}")

    # Summary
    _print_header("Setup Complete!")

    print("Configuration summary:")
    print(f"  - Anthropic API: {'Configured' if config.get('anthropic_key') else 'Not set'}")
    print(f"  - OpenAI API: {'Configured' if config.get('openai_key') else 'Not set'}")
    print(f"  - OpenRouter: {'Configured' if config.get('openrouter_key') else 'Not set'}")
    print(f"  - Database: {config.get('database_mode', 'sqlite').upper()}")
    print(f"  - HTTP Port: {config.get('http_port', 8080)}")

    integrations = []
    if config.get("slack_token") or config.get("slack_client_id"):
        integrations.append("Slack")
    if config.get("teams_client_id"):
        integrations.append("Teams")
    if config.get("stripe_secret_key"):
        integrations.append("Stripe")
    if config.get("github_token"):
        integrations.append("GitHub")
    if config.get("telegram_token"):
        integrations.append("Telegram")
    if integrations:
        print(f"  - Integrations: {', '.join(integrations)}")

    # Health check verification (optional)
    if not non_interactive and _confirm("\n  Run health check verification?", default=True):
        _run_health_checks(config)

    print("\nNext steps:")
    print("  1. Review .env file and adjust settings if needed")
    print("  2. Start the server: aragora serve")
    print("  3. Run a debate: aragora ask 'Your question here'")
    if config.get("slack_client_id"):
        print("  4. Install Slack app: https://your-domain/api/v1/oauth/slack/install")
    if config.get("teams_client_id"):
        print("  5. Deploy Teams app: see docs/integrations/TEAMS_SETUP.md")
    print("\nFor more help, run: aragora --help")

    return config


def cmd_setup(args) -> None:
    """Handle 'setup' command."""
    try:
        run_setup(
            output_path=getattr(args, "output", None),
            minimal=getattr(args, "minimal", False),
            skip_test=getattr(args, "skip_test", False),
            non_interactive=getattr(args, "yes", False),
        )
    except SetupError as exc:
        print(f"\nSetup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
