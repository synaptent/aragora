"""
Environment status and validation CLI commands.

Contains commands for checking environment health, validating API keys,
and verifying backend connectivity.
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

# Default API URL from environment or localhost fallback
DEFAULT_API_URL = os.environ.get("ARAGORA_API_URL", "http://localhost:8080")
_PROVIDER_SMOKE_PROMPT = "Reply with exactly: ok"
_PROVIDER_SMOKE_FAILURE_MARKERS = (
    "a wild bug appeared",
    "agent timed out",
    "connection failed",
    "encountered an error",
    "error generating proposal",
    "fatal exception",
    "invalid api key",
    "permission denied",
    "rate limit",
    "unauthorized",
)


def _split_agent_list(raw_agents: str | None) -> list[str]:
    return [agent.strip() for agent in str(raw_agents or "").split(",") if agent.strip()]


def _provider_smoke_response_ok(response: Any) -> bool:
    normalized = str(response or "").strip().lower()
    if not normalized:
        return False
    if any(marker in normalized for marker in _PROVIDER_SMOKE_FAILURE_MARKERS):
        return False
    return normalized in {"ok", "ok.", '"ok"', "'ok'", "okay"}


async def _run_provider_smoke(agent_type: str, *, timeout_seconds: float) -> dict[str, Any]:
    """Run one tiny direct agent call without building a debate arena."""

    from aragora.agents.base import AgentType, create_agent

    try:
        agent = create_agent(
            cast(AgentType, agent_type),
            name=f"validate_env_{agent_type.replace('-', '_')}",
            role="proposer",
            timeout=timeout_seconds,
        )
        response = await asyncio.wait_for(
            agent.generate(_PROVIDER_SMOKE_PROMPT),
            timeout=max(1.0, timeout_seconds),
        )
    except Exception as exc:  # noqa: BLE001 - live provider smoke must report failures clearly
        return {
            "status": "error",
            "agent": agent_type,
            "message": f"{type(exc).__name__}: {exc}",
            "action": "check credentials, CLI auth, provider quota, and network access",
        }

    preview = str(response or "").strip().replace("\n", " ")[:160]
    if _provider_smoke_response_ok(response):
        return {
            "status": "ok",
            "agent": agent_type,
            "message": "live provider answered the tiny smoke prompt",
            "response_preview": preview,
        }
    return {
        "status": "error",
        "agent": agent_type,
        "message": "live provider returned an unexpected or placeholder response",
        "response_preview": preview,
        "action": "rerun with --verbose and inspect provider/agent configuration",
    }


async def _run_provider_smoke_checks(
    agents: list[str],
    *,
    timeout_seconds: float,
    credential_report: Any,
) -> dict[str, Any]:
    from aragora.config.provider_readiness import (
        agent_provider_options,
        agent_type_has_configured_provider,
    )

    results: list[dict[str, Any]] = []
    for agent in agents:
        if not agent_type_has_configured_provider(agent, credential_report):
            options = agent_provider_options(agent)
            required = ", ".join(options) if options else agent
            results.append(
                {
                    "status": "error",
                    "agent": agent,
                    "message": f"no configured credential or CLI path for {agent}",
                    "action": f"configure one of: {required}",
                }
            )
            continue
        results.append(await _run_provider_smoke(agent, timeout_seconds=timeout_seconds))

    failed = [result for result in results if result.get("status") != "ok"]
    return {
        "status": "ok" if not failed else "error",
        "agents": results,
    }


def cmd_status(args: argparse.Namespace) -> int:
    """Handle 'status' command - show environment health and agent availability."""
    if bool(getattr(args, "founder", False)):
        from aragora.cli.commands.founder_status import cmd_founder_status

        return cmd_founder_status(args)
    if bool(getattr(args, "json", False)):
        print("error: status --json requires --founder", file=sys.stderr)
        return 2

    import shutil

    from aragora.config.provider_readiness import discover_provider_credentials

    print("\nAragora Environment Status")
    print("=" * 60)

    # Check API keys
    print("\n\U0001f4e1 API Keys:")
    readiness = discover_provider_credentials()
    for provider in readiness.providers:
        if provider.configured:
            print(f"  \u2713 {provider.display_name}: configured via {provider.available_via}")
        else:
            print(f"  \u2717 {provider.display_name}: not set")

    # Check CLI tools
    print("\n\U0001f527 CLI Tools:")
    cli_tools = [
        ("claude", "Claude Code CLI"),
        ("codex", "OpenAI Codex CLI"),
        ("gemini", "Gemini CLI"),
        ("grok", "Grok CLI"),
    ]
    for cmd, name in cli_tools:
        path = shutil.which(cmd)
        if path:
            print(f"  \u2713 {name}: {path}")
        else:
            print(f"  \u2717 {name}: not installed")

    # Check server health
    print("\n\U0001f310 Server Status:")
    server_url = args.server if hasattr(args, "server") else DEFAULT_API_URL
    try:
        from aragora.security.safe_http import SSRFValidationError, safe_get
    except ImportError:
        print(f"  \u2717 Server not reachable at {server_url}")
    else:
        try:
            resp = safe_get(f"{server_url}/api/health", timeout=2)
            if resp.status_code == 200:
                print(f"  \u2713 Server running at {server_url}")
            else:
                print(f"  \u26a0 Server returned status {resp.status_code}")
        except (
            OSError,
            TimeoutError,
            ConnectionError,
            RuntimeError,
            SSRFValidationError,
        ):
            # SSRFValidationError (incl. SSRFBlockedError) fires on the default
            # localhost URL, which safe_get rejects as an SSRF target. Treat it
            # the same as any other unreachable-server failure rather than
            # crashing with an uncaught traceback.
            print(f"  \u2717 Server not reachable at {server_url}")

    # Check database
    print("\n\U0001f4be Databases:")
    from aragora.persistence.db_config import DatabaseType, get_db_path

    db_paths = [
        (get_db_path(DatabaseType.CONTINUUM_MEMORY), "Memory store"),
        (get_db_path(DatabaseType.INSIGHTS), "Insights store"),
        (get_db_path(DatabaseType.ELO), "ELO rankings"),
    ]
    for db_path, name in db_paths:
        if Path(db_path).exists():
            size_mb = Path(db_path).stat().st_size / (1024 * 1024)
            print(f"  \u2713 {name}: {size_mb:.1f} MB")
        else:
            print(f"  \u2717 {name}: not found")

    # Show nomic loop state if available
    from aragora.persistence.db_config import get_nomic_dir

    nomic_state = get_nomic_dir() / "nomic_state.json"
    if nomic_state.exists():
        print("\n\U0001f504 Nomic Loop:")
        try:
            import json

            with open(nomic_state) as f:
                state = json.load(f)
            total_cycles = state.get("total_cycles", 0)
            last_cycle = state.get("last_cycle_timestamp", "unknown")
            print(f"  Total cycles: {total_cycles}")
            print(f"  Last run: {last_cycle}")
        except OSError as e:
            logger.warning("Could not read nomic state file: %s", e)
            print(f"  \u26a0 Could not read state: {e}")
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Invalid nomic state file format: %s", e)
            print(f"  \u26a0 Could not read state: {e}")

    print("\n" + "=" * 60)
    print("Run 'aragora ask' to start a debate or 'aragora serve' to start the server")
    return 0


def cmd_doctor(args: argparse.Namespace) -> None:
    """Handle 'doctor' command - run system health checks."""
    from aragora.cli.doctor import main as doctor_main

    sys.exit(doctor_main(validate_keys=getattr(args, "validate", False)))


def cmd_validate(_: argparse.Namespace) -> None:
    """Handle 'validate' command - validate API keys."""
    # run_validate doesn't exist; reuse doctor main for now
    from aragora.cli.doctor import main as doctor_main

    sys.exit(doctor_main(validate_keys=True))


def cmd_validate_env(args: argparse.Namespace) -> None:
    """Handle 'validate-env' command - validate environment and backend connectivity."""

    verbose = getattr(args, "verbose", False)
    json_output = getattr(args, "json", False)
    strict = getattr(args, "strict", False)
    smoke = bool(getattr(args, "smoke", False))
    smoke_agents = _split_agent_list(getattr(args, "agents", ""))
    smoke_timeout = float(getattr(args, "smoke_timeout", 20.0) or 20.0)

    async def run_validation() -> dict:
        """Run all environment validations."""
        import os

        results: dict[str, Any] = {
            "valid": True,
            "checks": {},
            "errors": [],
            "warnings": [],
        }

        # 1. Environment mode
        env = os.environ.get("ARAGORA_ENV", "development")
        is_production = env == "production"
        results["checks"]["environment"] = {
            "status": "ok",
            "value": env,
            "is_production": is_production,
        }

        # 2. Check distributed state requirement
        try:
            from aragora.config.distributed import is_distributed_state_required

            distributed_required = is_distributed_state_required()
        except ImportError:
            distributed_required = False

        results["checks"]["distributed_state"] = {
            "status": "ok" if not distributed_required else "required",
            "required": distributed_required,
            "reason": (
                "ARAGORA_MULTI_INSTANCE=true or ARAGORA_ENV=production"
                if distributed_required
                else "single instance mode"
            ),
        }

        # 3. Encryption key
        encryption_key = os.environ.get("ARAGORA_ENCRYPTION_KEY")
        if encryption_key:
            key_len = len(encryption_key) // 2  # hex string
            results["checks"]["encryption"] = {
                "status": "ok",
                "configured": True,
                "key_length_bytes": key_len,
            }
        elif is_production:
            results["checks"]["encryption"] = {
                "status": "error",
                "configured": False,
                "message": "ARAGORA_ENCRYPTION_KEY required in production",
            }
            results["errors"].append("Encryption key not configured")
            results["valid"] = False
        else:
            results["checks"]["encryption"] = {
                "status": "warning",
                "configured": False,
                "message": "Encryption key not set (optional in development)",
            }
            results["warnings"].append("Encryption key not configured")

        # 4. Redis connectivity
        try:
            from aragora.server.startup import (
                is_connectivity_skipped,
                validate_redis_connectivity,
            )

            redis_ok, redis_msg = await validate_redis_connectivity(timeout_seconds=5.0)
            if redis_ok and is_connectivity_skipped(redis_msg):
                # No backend configured: the connectivity probe was skipped, so
                # do NOT report a validated connection (would mislead humans/CI).
                results["checks"]["redis"] = {
                    "status": "skip",
                    "connected": False,
                    "skipped": True,
                    "message": redis_msg,
                }
            elif redis_ok:
                results["checks"]["redis"] = {
                    "status": "ok",
                    "connected": True,
                    "message": redis_msg,
                }
            elif distributed_required:
                results["checks"]["redis"] = {
                    "status": "error",
                    "connected": False,
                    "message": redis_msg,
                }
                results["errors"].append(f"Redis: {redis_msg}")
                results["valid"] = False
            else:
                results["checks"]["redis"] = {
                    "status": "warning",
                    "connected": False,
                    "message": redis_msg,
                }
                results["warnings"].append(f"Redis: {redis_msg}")
        except ImportError as e:
            results["checks"]["redis"] = {
                "status": "skip",
                "message": f"Startup module not available: {e}",
            }

        # 5. PostgreSQL connectivity
        try:
            from aragora.server.startup import (
                is_connectivity_skipped,
                validate_database_connectivity,
            )

            db_ok, db_msg = await validate_database_connectivity(timeout_seconds=5.0)
            require_database = os.environ.get("ARAGORA_REQUIRE_DATABASE", "").lower() in (
                "true",
                "1",
                "yes",
            )

            if db_ok and is_connectivity_skipped(db_msg):
                # No backend configured: the connectivity probe was skipped, so
                # do NOT report a validated connection (would mislead humans/CI).
                results["checks"]["postgresql"] = {
                    "status": "skip",
                    "connected": False,
                    "skipped": True,
                    "message": db_msg,
                }
            elif db_ok:
                results["checks"]["postgresql"] = {
                    "status": "ok",
                    "connected": True,
                    "message": db_msg,
                }
            elif require_database:
                results["checks"]["postgresql"] = {
                    "status": "error",
                    "connected": False,
                    "message": db_msg,
                }
                results["errors"].append(f"PostgreSQL: {db_msg}")
                results["valid"] = False
            else:
                results["checks"]["postgresql"] = {
                    "status": "info",
                    "connected": False,
                    "message": db_msg,
                }
        except ImportError as e:
            results["checks"]["postgresql"] = {
                "status": "skip",
                "message": f"Startup module not available: {e}",
            }

        # 6. AI provider check
        from aragora.config.provider_readiness import (
            discover_provider_credentials,
            format_provider_bootstrap_error,
        )

        provider_report = discover_provider_credentials()
        provider_validation = []
        provider_validation_errors = []
        if provider_report.any_configured:
            from aragora.cli.api_keys import get_supported_provider_names, validate_provider_key

            supported_validation_providers = set(get_supported_provider_names())
            for provider in provider_report.providers:
                if not provider.configured:
                    continue
                validation_provider = "grok" if provider.provider == "xai" else provider.provider
                if validation_provider not in supported_validation_providers:
                    provider_validation.append(
                        {
                            "provider": provider.provider,
                            "remote_status": "skipped",
                            "is_valid": True,
                            "message": "live validation not supported for this provider",
                        }
                    )
                    continue
                report = validate_provider_key(validation_provider)
                provider_validation.append(
                    {
                        "provider": provider.provider,
                        "remote_status": report.remote_status,
                        "is_valid": report.is_valid,
                        "message": report.message,
                    }
                )
                if not report.is_valid:
                    provider_validation_errors.append(f"{provider.provider}: {report.message}")

            results["checks"]["ai_providers"] = {
                "status": "error" if provider_validation_errors else "ok",
                "configured": list(provider_report.configured_providers),
                "hydrated_env_vars": list(provider_report.hydrated_env_vars),
                "dotenv_paths": list(provider_report.dotenv_paths),
                "validation": provider_validation,
            }
            if provider_validation_errors:
                results["errors"].extend(provider_validation_errors)
                results["valid"] = False
        else:
            results["checks"]["ai_providers"] = {
                "status": "error",
                "configured": [],
                "message": format_provider_bootstrap_error(provider_report),
                "discovery_errors": list(provider_report.discovery_errors),
            }
            results["errors"].append("No AI provider configured")
            results["valid"] = False

        # 7. Optional live provider smoke check.
        if smoke:
            if not smoke_agents:
                results["checks"]["ai_provider_smoke"] = {
                    "status": "error",
                    "message": "Pass --agents with at least one agent, e.g. --agents gemini",
                }
                results["errors"].append("No AI provider smoke agents selected")
                results["valid"] = False
            else:
                smoke_result = await _run_provider_smoke_checks(
                    smoke_agents,
                    timeout_seconds=smoke_timeout,
                    credential_report=provider_report,
                )
                results["checks"]["ai_provider_smoke"] = smoke_result
                if smoke_result["status"] != "ok":
                    failed = [
                        str(item.get("agent"))
                        for item in smoke_result["agents"]
                        if item.get("status") != "ok"
                    ]
                    results["errors"].append("AI provider smoke failed for: " + ", ".join(failed))
                    results["valid"] = False

        # 8. JWT secret check
        jwt_secret = os.environ.get("JWT_SECRET") or os.environ.get("ARAGORA_JWT_SECRET")
        if jwt_secret:
            results["checks"]["jwt_secret"] = {
                "status": "ok",
                "configured": True,
            }
        elif is_production:
            results["checks"]["jwt_secret"] = {
                "status": "warning",
                "configured": False,
                "message": "JWT secret not set - using derived key",
            }
            results["warnings"].append("JWT secret not configured")
        else:
            results["checks"]["jwt_secret"] = {
                "status": "info",
                "configured": False,
            }

        return results

    # Run the async validation
    results = asyncio.run(run_validation())

    # Determine final validity (strict mode treats warnings as errors)
    is_valid = results["valid"]
    if strict and results["warnings"]:
        is_valid = False

    # Output
    if json_output:
        import json

        results["strict_mode"] = strict
        results["final_valid"] = is_valid
        print(json.dumps(results, indent=2))
        sys.exit(0 if is_valid else 1)

    # Pretty output
    print("\n" + "=" * 60)
    print("ARAGORA ENVIRONMENT VALIDATION")
    print("=" * 60 + "\n")

    def status_icon(status: str) -> str:
        icons = {
            "ok": "\u2713",  # checkmark
            "error": "\u2717",  # X
            "warning": "!",
            "info": "-",
            "skip": "?",
            "required": "\u2713",
        }
        return icons.get(status, "?")

    for check_name, check_data in results["checks"].items():
        status = check_data.get("status", "unknown")
        icon = status_icon(status)

        # Format check name
        display_name = check_name.replace("_", " ").title()

        # Build detail string
        details = []
        if "value" in check_data:
            details.append(check_data["value"])
        if "configured" in check_data:
            if isinstance(check_data["configured"], list):
                details.append(", ".join(check_data["configured"]))
            elif check_data["configured"]:
                details.append("configured")
        if "connected" in check_data and check_data["connected"]:
            details.append("connected")
        if check_data.get("skipped"):
            details.append("not configured, skipped")
        if "message" in check_data and verbose:
            details.append(check_data["message"])

        detail_str = f" ({', '.join(details)})" if details else ""

        # Color based on status (using ANSI codes)
        if status == "ok":
            print(f"  {icon} {display_name}{detail_str}")
        elif status == "error":
            print(f"  {icon} {display_name}: FAILED{detail_str}")
        elif status == "warning":
            print(f"  {icon} {display_name}: WARNING{detail_str}")
        else:
            print(f"  {icon} {display_name}{detail_str}")

    print()

    if results["errors"]:
        print("Errors:")
        for error in results["errors"]:
            print(f"  - {error}")
        print()

    if results["warnings"]:
        print("Warnings:")
        for warning in results["warnings"]:
            print(f"  - {warning}")
        print()

    # Determine final status
    failed = not results["valid"]
    if strict and results["warnings"]:
        failed = True

    if failed:
        if strict and results["warnings"] and results["valid"]:
            print("Result: VALIDATION FAILED (strict mode - warnings treated as errors)")
        else:
            print("Result: VALIDATION FAILED - fix errors before production deployment")
    else:
        print("Result: All production requirements met")

    print()
    sys.exit(1 if failed else 0)
