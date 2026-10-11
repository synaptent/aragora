"""
Deployment CLI commands.

Provides CLI access to deployment validation and security configuration.
Commands:
- gt deploy validate - Validate deployment readiness
- gt deploy secrets - Generate security secrets
- gt deploy status - Show deployment status summary
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import secrets
import sys
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def cmd_deploy(args: argparse.Namespace) -> None:
    """Handle 'deploy' command - dispatch to subcommands."""
    subcommand = getattr(args, "deploy_command", None)

    if subcommand == "validate":
        asyncio.run(_cmd_validate(args))
    elif subcommand == "secrets":
        _cmd_secrets(args)
    elif subcommand == "status":
        asyncio.run(_cmd_status(args))
    elif subcommand == "start":
        _cmd_start(args)
    elif subcommand == "stop":
        _cmd_stop(args)
    else:
        # Default: show help
        print("\nUsage: aragora deploy <command>")
        print("\nCommands:")
        print("  start                Start services with Docker Compose (one-command deploy)")
        print("  stop                 Stop running services")
        print("  validate             Validate deployment readiness")
        print("  secrets              Generate security secrets")
        print("  status               Show deployment status summary")
        print("\nOptions for 'start':")
        print(
            "  --profile <profile>  Deployment profile: simple, sme, production (default: simple)"
        )
        print("  --setup              Run interactive setup before starting")
        print("  --no-wait            Don't wait for health checks")
        print("  --dry-run            Show what would be done without executing")
        print("\nOptions for 'validate':")
        print("  --strict             Fail on critical issues (exit code 1)")
        print("  --production         Check production-specific requirements")
        print("  --json               Output as JSON")
        print("\nOptions for 'secrets':")
        print("  --type <type>        Secret type: jwt, encryption, api_token, all")
        print("  --output <file>      Write to file instead of stdout")
        print("  --format <format>    Output format: env, json, plain")


async def _cmd_validate(args: argparse.Namespace) -> None:
    """Validate deployment readiness."""
    strict = getattr(args, "strict", False)
    production = getattr(args, "production", False)
    as_json = getattr(args, "json", False)

    try:
        from aragora.ops.deployment_validator import (
            validate_deployment,
            DeploymentNotReadyError,
            Severity,
        )

        if not as_json:
            print("\nValidating deployment...")
            print("=" * 60)

        env_backup: str | None = None
        env_set = False
        if production:
            env_backup = os.environ.get("ARAGORA_ENV")
            os.environ["ARAGORA_ENV"] = "production"
            env_set = True

        try:
            result = await validate_deployment(strict=strict)
        except DeploymentNotReadyError as e:
            result = e.result
        finally:
            if env_set:
                if env_backup is None:
                    os.environ.pop("ARAGORA_ENV", None)
                else:
                    os.environ["ARAGORA_ENV"] = env_backup

        if as_json:
            print(json.dumps(result.to_dict(), indent=2, default=str))
            if not result.ready:
                sys.exit(1)
            return

        # Display results
        status = "READY" if result.ready else "NOT READY"
        live = "LIVE" if result.live else "NOT LIVE"

        print(f"\n  Status:     {status}")
        print(f"  Live:       {live}")
        print(f"  Duration:   {result.validation_duration_ms:.0f}ms")

        # Group issues by severity
        critical = [i for i in result.issues if i.severity == Severity.CRITICAL]
        warnings = [i for i in result.issues if i.severity == Severity.WARNING]
        info = [i for i in result.issues if i.severity == Severity.INFO]

        if critical:
            print(f"\n  CRITICAL ISSUES ({len(critical)}):")
            for issue in critical:
                print(f"    [-] {issue.component}: {issue.message}")
                if issue.suggestion:
                    print(f"        Suggestion: {issue.suggestion}")

        if warnings:
            print(f"\n  WARNINGS ({len(warnings)}):")
            for issue in warnings:
                print(f"    [!] {issue.component}: {issue.message}")
                if issue.suggestion:
                    print(f"        Suggestion: {issue.suggestion}")

        if info and not as_json:
            print(f"\n  INFO ({len(info)}):")
            for issue in info[:5]:  # Limit to 5
                print(f"    [i] {issue.component}: {issue.message}")
            if len(info) > 5:
                print(f"    ... and {len(info) - 5} more")

        # Component health
        print("\n  COMPONENTS:")
        for comp in result.components:
            status_icon = {
                "healthy": "+",
                "degraded": "!",
                "unhealthy": "-",
                "unknown": "?",
            }.get(comp.status.value, "?")
            latency = f" ({comp.latency_ms:.0f}ms)" if comp.latency_ms else ""
            print(f"    [{status_icon}] {comp.name}: {comp.status.value}{latency}")

        print()

        if not result.ready and strict:
            print("Deployment validation FAILED (--strict mode)")
            sys.exit(1)

    except ImportError as e:
        print(f"\nError: Failed to import deployment validator: {e}")
        sys.exit(1)
    except (OSError, RuntimeError, ValueError) as e:
        logger.exception("Validation failed")
        print(f"\nError: {e}")
        sys.exit(1)


def _cmd_secrets(args: argparse.Namespace) -> None:
    """Generate security secrets."""
    secret_type = getattr(args, "type", "all")
    output_file = getattr(args, "output", None)
    output_format = getattr(args, "format", "env")

    generated: dict[str, str] = {}

    # Generate requested secrets
    if secret_type in ("jwt", "all"):
        # JWT secret: 64 character hex string (256 bits)
        jwt_secret = secrets.token_hex(32)
        generated["ARAGORA_JWT_SECRET"] = jwt_secret

    if secret_type in ("encryption", "all"):
        # Encryption key: 32 bytes base64 encoded (for AES-256)
        import base64

        encryption_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        generated["ARAGORA_ENCRYPTION_KEY"] = encryption_key

    if secret_type in ("api_token", "all"):
        # API token: URL-safe token
        api_token = secrets.token_urlsafe(32)
        generated["ARAGORA_API_TOKEN"] = api_token

    if secret_type in ("session", "all"):
        # Session secret: 48 bytes hex
        session_secret = secrets.token_hex(24)
        generated["ARAGORA_SESSION_SECRET"] = session_secret

    if not generated:
        print(f"\nError: Unknown secret type: {secret_type}")
        print("Valid types: jwt, encryption, api_token, session, all")
        return

    # Format output
    if output_format == "env":
        lines = [f"{k}={v}" for k, v in generated.items()]
        output = "\n".join(lines) + "\n"
    elif output_format == "json":
        output = json.dumps(generated, indent=2)
    else:  # plain
        output = "\n".join(generated.values())

    # Write or print
    if output_file:
        with open(output_file, "w") as f:
            f.write(output)
        print(f"\nSecrets written to: {output_file}")
        print(f"  Generated {len(generated)} secret(s)")
        print("\nIMPORTANT: Keep this file secure and add to .gitignore!")
    else:
        if output_format == "env":
            print("\n# Generated secrets - add to .env file")
            print("# KEEP SECURE - DO NOT COMMIT TO VERSION CONTROL")
            print()
        print(output)

        if output_format == "env":
            print("\nUsage:")
            print("  1. Add these to your .env file")
            print("  2. Ensure .env is in .gitignore")
            print("  3. For production, use a secrets manager instead")


def _cmd_start(args: argparse.Namespace) -> None:
    """Start services with Docker Compose (one-command deploy)."""
    import shutil
    import subprocess

    profile = getattr(args, "profile", "simple")
    run_setup = getattr(args, "setup", False)
    no_wait = getattr(args, "no_wait", False)
    dry_run = getattr(args, "dry_run", False)

    # Map profile to compose file
    compose_files = {
        "simple": "docker-compose.simple.yml",
        "sme": "docker-compose.sme.yml",
        "production": "docker-compose.production.yml",
        "dev": "docker-compose.dev.yml",
    }

    if profile not in compose_files:
        print(f"\nError: Unknown profile '{profile}'")
        print(f"Valid profiles: {', '.join(compose_files.keys())}")
        sys.exit(1)

    compose_file = compose_files[profile]

    # Find project root (where docker-compose files are)
    project_root = _find_project_root()
    if not project_root:
        print("\nError: Could not find project root (no docker-compose files found)")
        print("Make sure you're running from the Aragora project directory.")
        sys.exit(1)

    compose_path = os.path.join(project_root, compose_file)
    if not os.path.exists(compose_path):
        print(f"\nError: Compose file not found: {compose_path}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print(f"ARAGORA DEPLOY - {profile.upper()} PROFILE")
    print("=" * 60)

    # Check prerequisites
    print("\n[1/5] Checking prerequisites...")

    # Check Docker
    docker_cmd = shutil.which("docker")
    if not docker_cmd:
        print("  [-] Docker not found. Please install Docker first.")
        print("      https://docs.docker.com/get-docker/")
        sys.exit(1)
    print("  [+] Docker found")

    # Check Docker Compose
    compose_cmd = _get_compose_command()
    if not compose_cmd:
        print("  [-] Docker Compose not found. Please install Docker Compose.")
        sys.exit(1)
    print(f"  [+] Docker Compose found ({' '.join(compose_cmd)})")

    # Check if Docker is running
    try:
        result = subprocess.run(
            ["docker", "info"],  # fixed command
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            print("  [-] Docker daemon is not running. Please start Docker.")
            sys.exit(1)
        print("  [+] Docker daemon running")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("  [-] Could not connect to Docker daemon")
        sys.exit(1)

    # Check/create .env file
    print("\n[2/5] Checking environment configuration...")
    env_path = os.path.join(project_root, ".env")
    env_example = os.path.join(
        project_root, ".env.starter" if profile == "simple" else ".env.example"
    )

    if not os.path.exists(env_path):
        if run_setup:
            print("  [!] No .env file found. Running setup...")
            if dry_run:
                print("  [DRY-RUN] Would run interactive setup")
            else:
                # Run setup command
                try:
                    from aragora.cli.setup import run_setup as run_interactive_setup

                    run_interactive_setup(output_path=env_path)
                except ImportError:
                    print("  [-] Setup module not available. Creating from template...")
                    if os.path.exists(env_example):
                        shutil.copy(env_example, env_path)
                        print(f"  [+] Created .env from {os.path.basename(env_example)}")
                        print("  [!] Please edit .env and add your API keys")
                    else:
                        print("  [-] No .env template found")
                        sys.exit(1)
        elif os.path.exists(env_example):
            print(f"  [!] No .env file. Creating from {os.path.basename(env_example)}...")
            if not dry_run:
                shutil.copy(env_example, env_path)
            print("  [+] Created .env (edit to add API keys)")
        else:
            print("  [-] No .env file and no template found.")
            print("      Run with --setup flag to configure interactively.")
            sys.exit(1)
    else:
        print("  [+] .env file exists")

    # Validate minimum configuration
    if not dry_run:
        _validate_env_config(env_path, profile)

    # Build/pull images
    print(f"\n[3/5] Preparing Docker images ({compose_file})...")
    if dry_run:
        print(f"  [DRY-RUN] Would run: {' '.join(compose_cmd)} -f {compose_file} pull")
    else:
        print("  Pulling images (this may take a few minutes)...")
        result = subprocess.run(  # subprocess with fixed args, no shell
            [*compose_cmd, "-f", compose_file, "pull"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Pull may fail for local-only images, that's OK
            logger.debug("Pull output: %s", result.stderr)
        print("  [+] Images ready")

    # Start services
    print("\n[4/5] Starting services...")
    if dry_run:
        print(f"  [DRY-RUN] Would run: {' '.join(compose_cmd)} -f {compose_file} up -d")
    else:
        result = subprocess.run(  # subprocess with fixed args, no shell
            [*compose_cmd, "-f", compose_file, "up", "-d"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"  [-] Failed to start services: {result.stderr}")
            sys.exit(1)
        print("  [+] Services started")

    # Wait for health checks
    if not no_wait and not dry_run:
        print("\n[5/5] Waiting for services to be healthy...")
        _wait_for_health(compose_cmd, compose_file, project_root)
    else:
        print("\n[5/5] Skipping health check wait")

    # Print success message
    print("\n" + "=" * 60)
    print("DEPLOYMENT COMPLETE")
    print("=" * 60)

    port = "8080"
    if profile == "production":
        port = "443"

    print(f"""
Services are running. Access points:

  API:        http://localhost:{port}/api/health
  Swagger:    http://localhost:{port}/api/docs
""")

    if profile in ("sme", "production"):
        print("""  Grafana:    http://localhost:3001
  Prometheus: http://localhost:9090
""")

    print(
        f"""Next steps:
  1. Verify health:  curl http://localhost:8080/api/health
  2. Start a debate: aragora ask "Your question here"
  3. View logs:       docker compose -f {compose_file} logs -f

To stop services:
  aragora deploy stop --profile {profile}
"""
    )


def _cmd_stop(args: argparse.Namespace) -> None:
    """Stop running services."""
    import subprocess

    profile = getattr(args, "profile", "simple")
    remove_volumes = getattr(args, "volumes", False)

    compose_files = {
        "simple": "docker-compose.simple.yml",
        "sme": "docker-compose.sme.yml",
        "production": "docker-compose.production.yml",
        "dev": "docker-compose.dev.yml",
    }

    compose_file = compose_files.get(profile, "docker-compose.simple.yml")
    project_root = _find_project_root()

    if not project_root:
        print("\nError: Could not find project root")
        sys.exit(1)

    compose_cmd = _get_compose_command()
    if not compose_cmd:
        print("\nError: Docker Compose not found")
        sys.exit(1)

    print(f"\nStopping services ({profile} profile)...")

    cmd = [*compose_cmd, "-f", compose_file, "down"]
    if remove_volumes:
        cmd.append("-v")
        print("  (including volumes)")

    # subprocess with fixed args, no shell
    result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"\nError stopping services: {result.stderr}")
        sys.exit(1)

    print("\nServices stopped successfully.")


def _find_project_root() -> str | None:
    """Find the project root directory (where docker-compose files are)."""
    # Start from current directory and walk up
    current = os.getcwd()
    for _ in range(10):  # Max 10 levels up
        if os.path.exists(os.path.join(current, "docker-compose.yml")):
            return current
        if os.path.exists(os.path.join(current, "docker-compose.simple.yml")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def _get_compose_command() -> list[str] | None:
    """Get the Docker Compose command (v2 or v1)."""
    import shutil
    import subprocess

    # Try docker compose (v2)
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],  # fixed command
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return ["docker", "compose"]
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug("Subprocess execution failed: %s", e)

    # Try docker-compose (v1)
    if shutil.which("docker-compose"):
        return ["docker-compose"]

    return None


def _validate_env_config(env_path: str, profile: str) -> None:
    """Validate minimum required environment configuration."""
    warnings: list[str] = []

    # Read .env file
    env_vars: dict[str, str] = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env_vars[key.strip()] = value.strip().strip('"').strip("'")

    # Check for at least one AI API key
    ai_keys = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"]
    has_ai_key = any(env_vars.get(k) for k in ai_keys)
    if not has_ai_key:
        warnings.append(
            "No AI API key set (ANTHROPIC_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY)"
        )

    # Profile-specific requirements
    if profile in ("sme", "production"):
        if not env_vars.get("POSTGRES_PASSWORD"):
            warnings.append("POSTGRES_PASSWORD not set (required for SME/production)")

    if profile == "production":
        if not env_vars.get("ARAGORA_JWT_SECRET"):
            warnings.append("ARAGORA_JWT_SECRET not set (run: aragora deploy secrets)")
        if not env_vars.get("ARAGORA_ENCRYPTION_KEY"):
            warnings.append("ARAGORA_ENCRYPTION_KEY not set (run: aragora deploy secrets)")

    if warnings:
        print("  [!] Configuration warnings:")
        for warning in warnings:
            print(f"      - {warning}")


def _wait_for_health(compose_cmd: list[str], compose_file: str, project_root: str) -> None:
    """Wait for services to be healthy."""
    import time

    max_wait = 120  # seconds
    start = time.time()

    while time.time() - start < max_wait:
        # Check health endpoint
        try:
            import urllib.request

            req = urllib.request.Request(  # hardcoded localhost health check
                "http://localhost:8080/api/health",
                headers={"User-Agent": "aragora-deploy"},
            )
            # hardcoded localhost health check
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    print("  [+] Health check passed")
                    return
        except (OSError, ValueError):
            logger.debug("Health check attempt failed", exc_info=True)

        # Show progress
        elapsed = int(time.time() - start)
        print(f"  Waiting for services... ({elapsed}s)", end="\r")
        time.sleep(2)

    print("\n  [!] Services may not be fully ready yet")
    print(f"      Check logs: docker compose -f {compose_file} logs")


async def _cmd_status(args: argparse.Namespace) -> None:
    """Show deployment status summary."""
    as_json = getattr(args, "json", False)

    try:
        import os
        from aragora.config.settings import get_settings

        settings = get_settings()
        env = os.environ.get("ARAGORA_ENV", "development")

        # Collect status information
        status: dict[str, Any] = {
            "environment": env,
            "timestamp": datetime.now().isoformat(),
            "config": {},
            "secrets": {},
            "services": {},
        }

        # Config status
        status["config"]["server_host"] = getattr(settings, "server_host", "localhost")
        status["config"]["server_port"] = getattr(settings, "server_port", 8000)
        status["config"]["debug"] = getattr(settings, "debug", False)

        # Secrets status (presence only, not values)
        env_vars = [
            "ARAGORA_JWT_SECRET",
            "ARAGORA_API_TOKEN",
            "ARAGORA_ENCRYPTION_KEY",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
        ]
        for var in env_vars:
            value = os.environ.get(var)
            if value:
                # Show partial for security
                status["secrets"][var] = f"***{value[-4:]}" if len(value) > 4 else "***"
            else:
                status["secrets"][var] = None

        # Service connectivity
        status["services"]["database"] = (
            "configured"
            if os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_URL")
            else "sqlite"
        )
        status["services"]["redis"] = (
            "configured" if os.environ.get("REDIS_URL") else "not configured"
        )

        if as_json:
            print(json.dumps(status, indent=2))
            return

        print("\n" + "=" * 60)
        print("DEPLOYMENT STATUS")
        print("=" * 60)

        print(f"\n  Environment:  {status['environment']}")
        print(
            f"  Server:       {status['config']['server_host']}:{status['config']['server_port']}"
        )
        print(f"  Debug:        {status['config']['debug']}")

        print("\n  Secrets:")
        for name, value in status["secrets"].items():
            icon = "+" if value else "-"
            display = value if value else "not set"
            print(f"    [{icon}] {name}: {display}")

        print("\n  Services:")
        for name, value in status["services"].items():
            icon = "+" if value != "not configured" else "-"
            print(f"    [{icon}] {name}: {value}")

        print()

    except (OSError, ConnectionError, RuntimeError, ValueError) as e:
        print(f"\nError getting status: {e}")


def add_deploy_parser(subparsers: Any) -> None:
    """Add deploy subparser to CLI."""
    dp = subparsers.add_parser(
        "deploy",
        help="Deployment validation and configuration",
        description="Validate deployment readiness and manage security configuration",
    )
    dp.set_defaults(func=cmd_deploy)

    dp_sub = dp.add_subparsers(dest="deploy_command")

    # Start (one-command deploy)
    start_p = dp_sub.add_parser(
        "start",
        help="Start services with Docker Compose (one-command deploy)",
        description="Starts Aragora services using the specified profile. "
        "This is the recommended way to deploy Aragora.",
    )
    start_p.add_argument(
        "--profile",
        "-p",
        choices=["simple", "sme", "production", "dev"],
        default="simple",
        help="Deployment profile (default: simple)",
    )
    start_p.add_argument(
        "--setup",
        "-s",
        action="store_true",
        help="Run interactive setup before starting",
    )
    start_p.add_argument(
        "--no-wait",
        action="store_true",
        help="Don't wait for health checks to pass",
    )
    start_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing",
    )

    # Stop
    stop_p = dp_sub.add_parser("stop", help="Stop running services")
    stop_p.add_argument(
        "--profile",
        "-p",
        choices=["simple", "sme", "production", "dev"],
        default="simple",
        help="Profile to stop (default: simple)",
    )
    stop_p.add_argument(
        "--volumes",
        "-v",
        action="store_true",
        help="Also remove volumes (data will be lost)",
    )

    # Validate
    validate_p = dp_sub.add_parser("validate", help="Validate deployment readiness")
    validate_p.add_argument("--strict", action="store_true", help="Fail on critical issues")
    validate_p.add_argument(
        "--production", action="store_true", help="Check production requirements"
    )
    validate_p.add_argument("--json", action="store_true", help="Output as JSON")

    # Secrets
    secrets_p = dp_sub.add_parser("secrets", help="Generate security secrets")
    secrets_p.add_argument(
        "--type",
        choices=["jwt", "encryption", "api_token", "session", "all"],
        default="all",
        help="Secret type to generate (default: all)",
    )
    secrets_p.add_argument("--output", "-o", help="Output file path")
    secrets_p.add_argument(
        "--format",
        choices=["env", "json", "plain"],
        default="env",
        help="Output format (default: env)",
    )

    # Status
    status_p = dp_sub.add_parser("status", help="Show deployment status")
    status_p.add_argument("--json", action="store_true", help="Output as JSON")
