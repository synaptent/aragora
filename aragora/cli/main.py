#!/usr/bin/env python3
"""
Aragora CLI - Control Plane for Multi-Agent Deliberation

Orchestrate multi-agent vetted decisionmaking across your organization's knowledge and channels.

Usage:
    aragora ask "Design a rate limiter" --agents grok,anthropic-api,openai-api,deepseek,mistral,gemini,qwen,kimi --rounds 9
    aragora ask "Implement auth system" --agents grok,anthropic-api,openai-api,gemini --rounds 9
    aragora stats

Environment Variables:
    ARAGORA_API_URL: API server URL (default: http://localhost:8080)

This module serves as the entry point for the CLI. All command implementations
have been split into submodules under aragora.cli.commands/ for maintainability:

    - aragora.cli.commands.debate   : Debate execution (run_debate, cmd_ask, parse_agents)
    - aragora.cli.commands.stats    : Statistics and data inspection (cmd_stats, cmd_patterns, etc.)
    - aragora.cli.commands.status   : Environment health and validation (cmd_status, cmd_validate_env)
    - aragora.cli.commands.server   : Server management (cmd_serve)
    - aragora.cli.commands.tools    : Modes, templates, improve, context commands
    - aragora.cli.commands.delegated: Thin wrappers delegating to other cli modules
    - aragora.cli.parser            : Argument parser construction (build_parser)
"""

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Default API URL from environment or localhost fallback
DEFAULT_API_URL = os.environ.get("ARAGORA_API_URL", "http://localhost:8080")

# ---------------------------------------------------------------------------
# Re-exports for backwards compatibility
#
# Heavy imports (debate engine, agents, memory, full parser construction) are
# deferred via __getattr__ to avoid loading unrelated stacks on every CLI
# invocation.
# ---------------------------------------------------------------------------

_STARTUP_SECRET_HYDRATION_EXEMPTIONS = frozenset(
    {
        ("review-queue", "record-settlement"),
    }
)

# Lazy re-export mapping: name -> (module, attr)
_LAZY_REEXPORTS: dict[str, tuple[str, str]] = {
    "build_parser": ("aragora.cli.parser", "build_parser"),
    "get_version": ("aragora.cli.parser", "get_version"),
    # From aragora.cli.commands.debate
    "get_event_emitter_if_available": (
        "aragora.cli.commands.debate",
        "get_event_emitter_if_available",
    ),
    "parse_agents": ("aragora.cli.commands.debate", "parse_agents"),
    "run_debate": ("aragora.cli.commands.debate", "run_debate"),
    "cmd_ask": ("aragora.cli.commands.debate", "cmd_ask"),
    # From aragora.cli.commands.stats
    "cmd_stats": ("aragora.cli.commands.stats", "cmd_stats"),
    "cmd_patterns": ("aragora.cli.commands.stats", "cmd_patterns"),
    "cmd_memory": ("aragora.cli.commands.stats", "cmd_memory"),
    "cmd_elo": ("aragora.cli.commands.stats", "cmd_elo"),
    "cmd_cross_pollination": ("aragora.cli.commands.stats", "cmd_cross_pollination"),
    # From aragora.cli.commands.status
    "cmd_status": ("aragora.cli.commands.status", "cmd_status"),
    "cmd_validate_env": ("aragora.cli.commands.status", "cmd_validate_env"),
    "cmd_doctor": ("aragora.cli.commands.status", "cmd_doctor"),
    "cmd_validate": ("aragora.cli.commands.status", "cmd_validate"),
    # From aragora.cli.commands.server
    "cmd_serve": ("aragora.cli.commands.server", "cmd_serve"),
    # From aragora.cli.commands.tools
    "cmd_modes": ("aragora.cli.commands.tools", "cmd_modes"),
    "cmd_templates": ("aragora.cli.commands.tools", "cmd_templates"),
    "cmd_improve": ("aragora.cli.commands.tools", "cmd_improve"),
    "cmd_context": ("aragora.cli.commands.tools", "cmd_context"),
    # From aragora.cli.commands.delegated
    "cmd_agents": ("aragora.cli.commands.delegated", "cmd_agents"),
    "cmd_demo": ("aragora.cli.commands.delegated", "cmd_demo"),
    "cmd_export": ("aragora.cli.commands.delegated", "cmd_export"),
    "cmd_init": ("aragora.cli.commands.delegated", "cmd_init"),
    "cmd_setup": ("aragora.cli.commands.delegated", "cmd_setup"),
    "cmd_repl": ("aragora.cli.commands.delegated", "cmd_repl"),
    "cmd_config": ("aragora.cli.commands.delegated", "cmd_config"),
    "cmd_replay": ("aragora.cli.commands.delegated", "cmd_replay"),
    "cmd_bench": ("aragora.cli.commands.delegated", "cmd_bench"),
    "cmd_review": ("aragora.cli.commands.delegated", "cmd_review"),
    "cmd_gauntlet": ("aragora.cli.commands.delegated", "cmd_gauntlet"),
    "cmd_badge": ("aragora.cli.commands.delegated", "cmd_badge"),
    "cmd_billing": ("aragora.cli.commands.delegated", "cmd_billing"),
    "cmd_mcp_server": ("aragora.cli.commands.delegated", "cmd_mcp_server"),
    "cmd_marketplace": ("aragora.cli.commands.delegated", "cmd_marketplace"),
    "cmd_control_plane": ("aragora.cli.commands.delegated", "cmd_control_plane"),
    # From aragora.cli.commands.testfix
    "cmd_testfix": ("aragora.cli.commands.testfix", "cmd_testfix"),
    # Essential objects used by other modules (e.g., aragora.cli.batch)
    "AgentSpec": ("aragora.agents.spec", "AgentSpec"),
    "CritiqueStore": ("aragora.memory.store", "CritiqueStore"),
    "create_agent": ("aragora.agents.base", "create_agent"),
    "Arena": ("aragora.debate.orchestrator", "Arena"),
    "DebateProtocol": ("aragora.debate.orchestrator", "DebateProtocol"),
    "Environment": ("aragora.core", "Environment"),
    "DEFAULT_AGENTS": ("aragora.config", "DEFAULT_AGENTS"),
    "DEFAULT_CONSENSUS": ("aragora.config", "DEFAULT_CONSENSUS"),
    "DEFAULT_ROUNDS": ("aragora.config", "DEFAULT_ROUNDS"),
}


def __getattr__(name: str) -> object:
    if name in _LAZY_REEXPORTS:
        module_path, attr_name = _LAZY_REEXPORTS[name]
        import importlib

        mod = importlib.import_module(module_path)
        val = getattr(mod, attr_name)
        globals()[name] = val
        return val
    raise AttributeError(f"module 'aragora.cli.main' has no attribute {name!r}")


def _should_hydrate_startup_secrets(args: object) -> bool:
    """Return whether this CLI command should hydrate provider secrets."""
    command = str(getattr(args, "command", "") or "")
    if not command:
        return False
    review_queue_command = str(getattr(args, "review_queue_command", "") or "")
    return (command, review_queue_command) not in _STARTUP_SECRET_HYDRATION_EXEMPTIONS


def _hydrate_startup_secrets() -> None:
    try:
        from aragora.config.secrets import hydrate_env_from_secrets

        # Secrets Manager is authoritative when enabled. Hydrate only this
        # process so legacy provider CLIs can read env vars without writing
        # keys to disk or the parent shell.
        hydrate_env_from_secrets(overwrite=True)
    except (AttributeError, ImportError, OSError, RuntimeError, ValueError) as exc:
        logger.warning("Could not hydrate AWS-managed API keys: %s", exc)

    try:
        from aragora.cli.api_keys import hydrate_env_from_secure_store

        # Local secure-store keys are a dev fallback and must not override AWS.
        hydrate_env_from_secure_store(overwrite=False)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        logger.warning("Could not hydrate stored API keys: %s", exc)


def _try_review_queue_fast_path(argv: list[str]) -> int | None:
    """Run review-queue commands without initializing the full CLI surface."""
    if not argv or argv[0] != "review-queue":
        return None

    import argparse

    from aragora.cli.commands.review_queue import add_review_queue_parser

    parser = argparse.ArgumentParser(prog="aragora")
    subparsers = parser.add_subparsers(dest="command")
    add_review_queue_parser(subparsers)
    args = parser.parse_args(argv)
    if getattr(args, "command", None) is None:
        parser.print_help()
        return 0

    log_level = logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING
    logging.basicConfig(level=log_level, format="%(levelname)s %(name)s: %(message)s")

    result = args.func(args)
    if isinstance(result, int):
        return result
    return 0


def main() -> int:
    fast_result = _try_review_queue_fast_path(sys.argv[1:])
    if fast_result is not None:
        return fast_result

    from aragora.server.startup.event_subscribers import register_webhook_store

    register_webhook_store()

    # Register built-in modes here (not at module level) to avoid import-time cost
    from aragora.modes import register_all_builtins
    from aragora.cli.parser import build_parser

    register_all_builtins()

    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    # Configure logging level based on --verbose flag.
    # Without --verbose, only ERROR+ messages reach stderr so that
    # transient rate-limit retries, circuit-breaker state changes, and
    # fallback routing messages stay hidden during normal operation.
    log_level = logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING
    logging.basicConfig(level=log_level, format="%(levelname)s %(name)s: %(message)s")
    # Suppress noisy/dangerous third-party debug logs — botocore dumps
    # full Secrets Manager responses (including plaintext secrets) at DEBUG.
    for noisy_logger in ("botocore", "boto3", "urllib3", "s3transfer"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    if _should_hydrate_startup_secrets(args):
        _hydrate_startup_secrets()

    result = args.func(args)
    if isinstance(result, int):
        return result
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
