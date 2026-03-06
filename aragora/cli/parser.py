"""
CLI argument parser construction.

Builds the argparse parser with all subcommands and their arguments.
Separated from command implementations for clarity and maintainability.
"""

import argparse
import os

from aragora.config import DEFAULT_AGENTS, DEFAULT_CONSENSUS, DEFAULT_ROUNDS

# Default API URL from environment or localhost fallback
DEFAULT_API_URL = os.environ.get("ARAGORA_API_URL", "http://localhost:8080")
DEFAULT_API_KEY = os.environ.get("ARAGORA_API_KEY")


def _lazy(module_path: str, func_name: str):
    """Create a lazy wrapper that defers command module import to invocation time.

    Instead of importing all command handlers at module load time (which pulls in
    heavy dependencies like Arena, agents, etc.), this defers the import until the
    specific subcommand is actually executed by the user.
    """

    def wrapper(args):
        from importlib import import_module

        return getattr(import_module(module_path), func_name)(args)

    wrapper.__name__ = func_name
    wrapper.__qualname__ = func_name
    return wrapper


def get_version() -> str:
    """Get package version from pyproject.toml or fallback."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("aragora")
    except ImportError:
        # importlib.metadata not available (Python < 3.8)
        return "0.8.0-dev"
    except PackageNotFoundError:
        # Package not installed in editable mode - use dev version
        return "0.8.0-dev"


def build_parser() -> argparse.ArgumentParser:
    """Build and return the complete CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Aragora - Control plane for multi-agent vetted decisionmaking across org knowledge and channels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  aragora ask "Design a rate limiter" --agents grok,anthropic-api,openai-api,deepseek,mistral,gemini,qwen,kimi
  aragora ask "Implement auth" --agents grok,anthropic-api,openai-api,gemini --rounds 9
  aragora stats
  aragora patterns --type security
        """,
    )

    parser.add_argument("--version", "-V", action="version", version=f"aragora {get_version()}")
    parser.add_argument("--db", default="agora_memory.db", help="SQLite database path")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    _add_ask_parser(subparsers)
    _add_stats_parser(subparsers)
    _add_status_parser(subparsers)
    _add_agents_parser(subparsers)
    _add_modes_parser(subparsers)
    _add_patterns_parser(subparsers)
    _add_demo_parser(subparsers)
    _add_templates_parser(subparsers)
    _add_export_parser(subparsers)
    _add_doctor_parser(subparsers)
    _add_validate_parser(subparsers)
    _add_validate_env_parser(subparsers)
    _add_improve_parser(subparsers)
    _add_context_parser(subparsers)
    _add_serve_parser(subparsers)
    _add_init_parser(subparsers)
    _add_setup_parser(subparsers)
    _add_backup_parser(subparsers)
    _add_repl_parser(subparsers)
    _add_config_parser(subparsers)
    _add_replay_parser(subparsers)
    _add_bench_parser(subparsers)
    _add_review_parser(subparsers)
    _add_external_parsers(subparsers)
    _add_badge_parser(subparsers)
    _add_verticals_parser(subparsers)
    _add_memory_parser(subparsers)
    _add_elo_parser(subparsers)
    _add_cross_pollination_parser(subparsers)
    _add_mcp_parser(subparsers)
    _add_marketplace_parser(subparsers)
    _add_skills_parser(subparsers)
    _add_nomic_parser(subparsers)
    _add_workflow_parser(subparsers)
    _add_deploy_parser(subparsers)
    _add_control_plane_parser(subparsers)
    _add_decide_parser(subparsers)
    _add_plans_parser(subparsers)
    _add_testfixer_parser(subparsers)
    _add_computer_use_parser(subparsers)
    _add_connectors_parser(subparsers)
    _add_rbac_parser(subparsers)
    _add_km_parser(subparsers)
    _add_costs_parser(subparsers)
    _add_verify_parser(subparsers)
    _add_healthcare_parser(subparsers)
    _add_quickstart_parser(subparsers)
    _add_receipt_parser(subparsers)
    _add_compliance_parser(subparsers)
    _add_publish_parser(subparsers)
    _add_autopilot_parser(subparsers)
    _add_agent_parser(subparsers)
    _add_analytics_parser(subparsers)
    _add_starter_parser(subparsers)
    _add_handlers_parser(subparsers)
    _add_coordinate_parser(subparsers)
    _add_self_improve_parser(subparsers)
    _add_swarm_parser(subparsers)
    _add_worktree_parser(subparsers)
    _add_outcome_parser(subparsers)
    _add_explain_parser(subparsers)
    _add_playbook_parser(subparsers)
    _add_pipeline_parser(subparsers)
    _add_consensus_parser(subparsers)
    _add_ideacloud_parser(subparsers)
    _add_signing_parser(subparsers)
    _add_inbox_wedge_parser(subparsers)
    _add_triage_parser(subparsers)

    return parser


def _add_ask_parser(subparsers) -> None:
    """Add the 'ask' subcommand parser."""
    ask_parser = subparsers.add_parser("ask", help="Run a decision stress-test (debate engine)")
    ask_parser.add_argument("task", help="The task/question to debate")
    ask_parser.add_argument(
        "--agents",
        "-a",
        default=DEFAULT_AGENTS,
        help=(
            "Comma-separated agents. Formats: "
            "'provider' (auto-assign role), "
            "'provider:role' (e.g., anthropic-api:critic), "
            "'provider:persona' (e.g., anthropic-api:philosopher), "
            "'provider|model|persona|role' (full spec). "
            "Valid roles: proposer, critic, synthesizer, judge. "
            "Also accepts JSON list of dicts with provider/model/persona/role."
        ),
    )
    ask_parser.add_argument(
        "--auto-select",
        action="store_true",
        help="Auto-select an optimal agent team for the task",
    )
    ask_parser.add_argument(
        "--auto-select-config",
        help=(
            "JSON config for auto-selection (e.g. "
            '\'{"min_agents":3,"max_agents":5,"diversity_preference":0.5}\')'
        ),
    )
    ask_parser.add_argument(
        "--rounds",
        "-r",
        type=int,
        default=DEFAULT_ROUNDS,
        help=f"Number of debate rounds (default: {DEFAULT_ROUNDS})",
    )
    ask_parser.add_argument(
        "--consensus",
        "-c",
        choices=["majority", "unanimous", "judge", "hybrid", "none"],
        default=DEFAULT_CONSENSUS,
        help=f"Consensus mechanism (default: {DEFAULT_CONSENSUS})",
    )
    ask_parser.add_argument("--context", help="Additional context for the task")
    ask_parser.add_argument(
        "--codebase-context",
        action="store_true",
        help=(
            "Pre-compute a grounded codebase context block before debate start "
            "(recommended for self-improvement/dogfood runs)"
        ),
    )
    ask_parser.add_argument(
        "--codebase-context-path",
        help="Repository path for codebase context engineering (default: current working directory)",
    )
    ask_parser.add_argument(
        "--codebase-context-harnesses",
        action="store_true",
        help=(
            "Use explorer harnesses (Claude/Codex and optionally KiloCode) "
            "to synthesize existing capabilities"
        ),
    )
    ask_parser.add_argument(
        "--codebase-context-kilocode",
        action="store_true",
        help="Include KiloCode Gemini/Grok explorers when harness mode is enabled",
    )
    ask_parser.add_argument(
        "--codebase-context-rlm",
        action="store_true",
        help="Enable full-corpus RLM summary while building codebase context (slower)",
    )
    ask_parser.add_argument(
        "--codebase-context-max-chars",
        type=int,
        default=80000,
        help="Maximum characters to inject from engineered codebase context (default: 80000)",
    )
    ask_parser.add_argument(
        "--codebase-context-timeout",
        type=int,
        default=240,
        help="Timeout in seconds for codebase context engineering (default: 240)",
    )
    ask_parser.add_argument(
        "--codebase-context-out",
        help="Optional file path to save engineered codebase context before debate execution",
    )
    ask_parser.add_argument(
        "--no-context-init-rlm",
        action="store_true",
        help=(
            "Disable RLM context compression during debate context initialization "
            "(faster and more predictable runtime)"
        ),
    )
    ask_parser.add_argument(
        "--codebase-context-exclude-tests",
        action="store_true",
        help="Exclude test files from codebase context indexing",
    )
    ask_parser.add_argument(
        "--grounding-fail-closed",
        action="store_true",
        help=(
            "Exit non-zero when final output is weakly grounded to existing repository paths "
            "(requires path-check to meet --grounding-min-verified-paths)"
        ),
    )
    ask_parser.add_argument(
        "--grounding-min-verified-paths",
        type=float,
        default=0.8,
        help=(
            "Minimum ratio (0.0-1.0) of existing repo paths required when "
            "--grounding-fail-closed is enabled (default: 0.8)"
        ),
    )
    ask_parser.add_argument(
        "--no-learn", dest="learn", action="store_false", help="Don't store patterns"
    )
    ask_parser.add_argument(
        "--demo",
        action="store_true",
        help="Run with built-in demo agents (no API keys required)",
    )
    ask_parser.add_argument(
        "--mode",
        "-m",
        choices=["architect", "coder", "reviewer", "debugger", "orchestrator"],
        help="Operational mode for agents (architect, coder, reviewer, debugger, orchestrator)",
    )
    ask_parser.add_argument(
        "--enable-verticals",
        action="store_true",
        help="Enable vertical specialists (auto-detected by task)",
    )
    ask_parser.add_argument(
        "--vertical",
        help="Explicit vertical specialist ID to inject (e.g., software, legal, healthcare)",
    )
    run_mode = ask_parser.add_mutually_exclusive_group()
    run_mode.add_argument(
        "--api",
        action="store_true",
        help="Run debate via API server (uses shared storage and audit trails)",
    )
    run_mode.add_argument(
        "--local",
        action="store_true",
        help="Run debate locally without API server (offline/air-gapped mode)",
    )
    ask_parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"API server URL (default: {DEFAULT_API_URL})",
    )
    ask_parser.add_argument(
        "--api-key",
        default=None if DEFAULT_API_KEY is None else DEFAULT_API_KEY,
        help="API key for server authentication (default: ARAGORA_API_KEY)",
    )
    debate_type = ask_parser.add_mutually_exclusive_group()
    debate_type.add_argument(
        "--graph",
        action="store_true",
        help="Run a graph debate with branching (API mode only)",
    )
    debate_type.add_argument(
        "--matrix",
        action="store_true",
        help="Run a matrix debate with scenarios (API mode only)",
    )
    ask_parser.add_argument(
        "--graph-rounds",
        type=int,
        default=5,
        help="Max rounds per graph branch (default: 5)",
    )
    ask_parser.add_argument(
        "--branch-threshold",
        type=float,
        default=0.5,
        help="Divergence threshold for graph branching (0-1, default: 0.5)",
    )
    ask_parser.add_argument(
        "--max-branches",
        type=int,
        default=5,
        help="Maximum graph branches (default: 5)",
    )
    ask_parser.add_argument(
        "--matrix-rounds",
        type=int,
        default=3,
        help="Max rounds per matrix scenario (default: 3)",
    )
    ask_parser.add_argument(
        "--scenario",
        action="append",
        help="Matrix scenario JSON or name (repeatable)",
    )
    ask_parser.add_argument(
        "--decision-integrity",
        action="store_true",
        help="Build decision integrity package (receipt + plan) after debate completes",
    )
    ask_parser.add_argument(
        "--di-include-context",
        action="store_true",
        help="Include memory/knowledge snapshot in decision integrity package",
    )
    ask_parser.add_argument(
        "--di-plan-strategy",
        choices=["single_task", "gemini"],
        default="single_task",
        help="Decision integrity plan strategy (default: single_task)",
    )
    ask_parser.add_argument(
        "--di-execution-mode",
        choices=[
            "plan_only",
            "request_approval",
            "execute",
            "workflow",
            "workflow_execute",
            "execute_workflow",
            "hybrid",
            "computer_use",
        ],
        help="Decision integrity execution mode (API mode only)",
    )
    # Cross-pollination feature flags
    ask_parser.add_argument(
        "--no-elo-weighting",
        dest="elo_weighting",
        action="store_false",
        default=True,
        help="Disable ELO skill-based vote weighting",
    )
    ask_parser.add_argument(
        "--no-calibration",
        dest="calibration",
        action="store_false",
        default=True,
        help="Disable calibration tracking and confidence adjustment",
    )
    ask_parser.add_argument(
        "--no-evidence-weighting",
        dest="evidence_weighting",
        action="store_false",
        default=True,
        help="Disable evidence quality-based consensus weighting",
    )
    ask_parser.add_argument(
        "--no-trending",
        dest="trending",
        action="store_false",
        default=True,
        help="Disable trending topic injection from Pulse",
    )
    ask_parser.add_argument(
        "--explain",
        action="store_true",
        help="Generate and display decision explanation (evidence chains, vote pivots)",
    )
    ask_parser.add_argument(
        "--preset",
        choices=[
            "sme",
            "enterprise",
            "minimal",
            "audit",
            "visual",
            "compliance",
            "research",
            "healthcare",
            "financial",
        ],
        help="Apply a configuration preset (sme, enterprise, minimal, audit, visual, compliance, research, healthcare, financial)",
    )
    ask_parser.add_argument(
        "--spectate",
        action="store_true",
        help="Enable real-time debate visualization in the terminal",
    )
    ask_parser.add_argument(
        "--spectate-format",
        choices=["auto", "ansi", "plain", "json"],
        default="auto",
        help="Spectator output format (default: auto)",
    )
    ask_parser.add_argument(
        "--no-cartographer",
        dest="enable_cartographer",
        action="store_false",
        default=True,
        help="Disable argument graph visualization",
    )
    ask_parser.add_argument(
        "--no-introspection",
        dest="enable_introspection",
        action="store_false",
        default=True,
        help="Disable agent self-awareness in prompts",
    )
    ask_parser.add_argument(
        "--auto-execute",
        action="store_true",
        help="Auto-execute approved plans from debate results",
    )
    ask_parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("ARAGORA_ASK_TIMEOUT_SECONDS", "3600")),
        help="Maximum debate duration in seconds (default: ARAGORA_ASK_TIMEOUT_SECONDS or 3600)",
    )
    ask_parser.add_argument(
        "--no-post-consensus-quality",
        dest="post_consensus_quality",
        action="store_false",
        default=True,
        help="Disable deterministic post-consensus quality validation",
    )
    ask_parser.add_argument(
        "--no-upgrade-to-good",
        dest="upgrade_to_good",
        action="store_false",
        default=True,
        help="Disable automatic quality-repair loop when output fails quality checks",
    )
    ask_parser.add_argument(
        "--quality-upgrade-max-loops",
        type=int,
        default=2,
        help="Maximum repair loops after consensus when quality checks fail (default: 2)",
    )
    ask_parser.add_argument(
        "--quality-min-score",
        type=float,
        default=9.0,
        help="Minimum post-consensus quality score target (0-10, default: 9.0)",
    )
    ask_parser.add_argument(
        "--quality-practical-min-score",
        type=float,
        default=5.0,
        help="Minimum practicality score target for execution readiness (0-10, default: 5.0)",
    )
    ask_parser.add_argument(
        "--quality-fail-closed",
        action="store_true",
        help="Exit non-zero when post-consensus output still fails quality gates after repair loops",
    )
    ask_parser.add_argument(
        "--quality-concretize-max-rounds",
        type=int,
        default=3,
        help="Max post-consensus concretization rounds when output is not practical enough (default: 3)",
    )
    ask_parser.add_argument(
        "--quality-extra-assessment-rounds",
        type=int,
        default=2,
        help=(
            "Additional bounded post-consensus assessment rounds (Claude/Codex-preferred) "
            "when practicality remains below target (default: 2)"
        ),
    )
    ask_parser.add_argument(
        "--required-sections",
        help=(
            "Comma-separated required output section headings for deterministic quality gating "
            "(overrides task-derived contract)."
        ),
    )
    ask_parser.add_argument(
        "--output-contract-file",
        help=(
            "Path to a JSON output contract file for deterministic quality gating "
            "(highest precedence over --required-sections and task-derived contracts)."
        ),
    )
    ask_parser.set_defaults(func=_lazy("aragora.cli.commands.debate", "cmd_ask"))


def _add_stats_parser(subparsers) -> None:
    """Add the 'stats' subcommand parser."""
    stats_parser = subparsers.add_parser("stats", help="Show memory statistics")
    stats_parser.set_defaults(func=_lazy("aragora.cli.commands.stats", "cmd_stats"))


def _add_status_parser(subparsers) -> None:
    """Add the 'status' subcommand parser."""
    status_parser = subparsers.add_parser(
        "status", help="Show environment health and agent availability"
    )
    status_parser.add_argument(
        "--server",
        "-s",
        default=DEFAULT_API_URL,
        help=f"Server URL to check (default: {DEFAULT_API_URL})",
    )
    status_parser.set_defaults(func=_lazy("aragora.cli.commands.status", "cmd_status"))


def _add_agents_parser(subparsers) -> None:
    """Add the 'agents' subcommand parser."""
    agents_parser = subparsers.add_parser(
        "agents",
        help="List available agents and their configuration",
        description="Show all available agent types, their API key requirements, and configuration status.",
    )
    agents_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed descriptions"
    )
    agents_parser.set_defaults(func=_lazy("aragora.cli.commands.delegated", "cmd_agents"))


def _add_modes_parser(subparsers) -> None:
    """Add the 'modes' subcommand parser."""
    modes_parser = subparsers.add_parser(
        "modes",
        help="List available operational modes",
        description="Show all available operational modes (architect, coder, reviewer, etc.) for debates.",
    )
    modes_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show full system prompts"
    )
    modes_parser.set_defaults(func=_lazy("aragora.cli.commands.tools", "cmd_modes"))


def _add_patterns_parser(subparsers) -> None:
    """Add the 'patterns' subcommand parser."""
    patterns_parser = subparsers.add_parser("patterns", help="Show learned patterns")
    patterns_parser.add_argument("--type", "-t", help="Filter by issue type")
    patterns_parser.add_argument("--min-success", type=int, default=1, help="Minimum success count")
    patterns_parser.add_argument("--limit", "-l", type=int, default=10, help="Max patterns to show")
    patterns_parser.set_defaults(func=_lazy("aragora.cli.commands.stats", "cmd_patterns"))


def _add_demo_parser(subparsers) -> None:
    """Add the 'demo' subcommand parser."""
    demo_parser = subparsers.add_parser(
        "demo",
        help="Run a self-contained adversarial debate demo (no API keys needed)",
        description="""
Run a quick adversarial debate using mock agents -- no API keys required.
Shows the full debate lifecycle: proposals, critiques, votes, and a decision receipt.

Examples:
  aragora demo                                         # Default microservices debate
  aragora demo rate-limiter                            # Named demo scenario
  aragora demo --topic "Should we rewrite in Rust?"    # Custom topic
  aragora demo --list                                  # Show available demos
  aragora demo --server                                # Start offline web UI
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    demo_parser.add_argument(
        "name",
        nargs="?",
        help="Demo name (microservices, rate-limiter, auth, cache, kubernetes)",
    )
    demo_parser.add_argument(
        "--topic",
        "-t",
        help="Custom topic to debate (overrides named demo)",
    )
    demo_parser.add_argument(
        "--list",
        dest="list_demos",
        action="store_true",
        help="List available demo scenarios",
    )
    demo_parser.add_argument(
        "--server",
        action="store_true",
        help="Start the server in offline demo mode and show web UI instructions",
    )
    demo_parser.add_argument(
        "--receipt",
        "-r",
        help="Save decision receipt to file (.json, .html, or .md)",
    )
    demo_parser.set_defaults(func=_lazy("aragora.cli.commands.delegated", "cmd_demo"))


def _add_inbox_wedge_parser(subparsers) -> None:
    """Add the inbox trust wedge parser."""
    from aragora.cli.commands.inbox_wedge import add_inbox_wedge_parser

    add_inbox_wedge_parser(subparsers)


def _add_templates_parser(subparsers) -> None:
    """Add the 'templates' subcommand parser."""
    templates_parser = subparsers.add_parser("templates", help="List available debate templates")
    templates_parser.set_defaults(func=_lazy("aragora.cli.commands.tools", "cmd_templates"))


def _add_export_parser(subparsers) -> None:
    """Add the 'export' subcommand parser."""
    export_parser = subparsers.add_parser("export", help="Export debate artifacts")
    export_parser.add_argument("--debate-id", "-d", help="Debate ID to export")
    export_parser.add_argument(
        "--format",
        "-f",
        choices=["html", "json", "md"],
        default="html",
        help="Output format (default: html)",
    )
    export_parser.add_argument(
        "--output",
        "-o",
        default=".",
        help="Output directory (default: current)",
    )
    export_parser.add_argument(
        "--demo",
        action="store_true",
        help="Generate a demo export",
    )
    export_parser.set_defaults(func=_lazy("aragora.cli.commands.delegated", "cmd_export"))


def _add_doctor_parser(subparsers) -> None:
    """Add the 'doctor' subcommand parser."""
    doctor_parser = subparsers.add_parser("doctor", help="Run system health checks")
    doctor_parser.add_argument(
        "--validate", "-v", action="store_true", help="Validate API keys by making test calls"
    )
    doctor_parser.set_defaults(func=_lazy("aragora.cli.commands.status", "cmd_doctor"))


def _add_validate_parser(subparsers) -> None:
    """Add the 'validate' subcommand parser."""
    validate_parser = subparsers.add_parser(
        "validate", help="Validate API keys by making test calls"
    )
    validate_parser.set_defaults(func=_lazy("aragora.cli.commands.status", "cmd_validate"))


def _add_validate_env_parser(subparsers) -> None:
    """Add the 'validate-env' subcommand parser."""
    validate_env_parser = subparsers.add_parser(
        "validate-env",
        help="Validate environment configuration and backend connectivity",
        description=(
            "Validates that the environment is properly configured for production "
            "deployment, including Redis/PostgreSQL connectivity, encryption keys, "
            "and AI provider configuration."
        ),
    )
    validate_env_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed messages"
    )
    validate_env_parser.add_argument(
        "--json", "-j", action="store_true", help="Output results as JSON"
    )
    validate_env_parser.add_argument(
        "--strict", "-s", action="store_true", help="Fail on warnings (for CI/CD enforcement)"
    )
    validate_env_parser.set_defaults(func=_lazy("aragora.cli.commands.status", "cmd_validate_env"))


def _add_improve_parser(subparsers) -> None:
    """Add the 'improve' subcommand parser."""
    improve_parser = subparsers.add_parser(
        "improve",
        help="Self-improvement mode using AutonomousOrchestrator",
        description="""
Run self-improvement on the codebase using the Nomic AutonomousOrchestrator.

The orchestrator decomposes high-level goals into subtasks, routes them to
appropriate agents based on domain expertise, and executes them with
verification and feedback loops.

Examples:
  aragora improve --goal "Improve test coverage" --tracks qa
  aragora improve --goal "Refactor authentication" --dry-run
  aragora improve --goal "Add SDK endpoints" --tracks developer --max-cycles 3
  aragora improve --goal "Security audit" --tracks security --require-approval
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    improve_parser.add_argument(
        "--goal",
        "-g",
        required=True,
        help="The improvement goal to execute (required)",
    )
    improve_parser.add_argument(
        "--tracks",
        "-t",
        help="Comma-separated tracks to focus on (sme, developer, self_hosted, qa, core, security)",
    )
    improve_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview decomposition without executing (uses TaskDecomposer)",
    )
    improve_parser.add_argument(
        "--max-cycles",
        type=int,
        default=5,
        help="Maximum improvement cycles per subtask (default: 5)",
    )
    improve_parser.add_argument(
        "--require-approval",
        action="store_true",
        help="Require human approval at checkpoint gates",
    )
    improve_parser.add_argument(
        "--debate",
        action="store_true",
        help="Use multi-agent debate for goal decomposition (slower but better for abstract goals)",
    )
    improve_parser.add_argument(
        "--max-parallel",
        type=int,
        default=4,
        help="Maximum parallel tasks across all tracks (default: 4)",
    )
    improve_parser.add_argument(
        "--path",
        "-p",
        help="Path to codebase (default: current dir)",
    )
    improve_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed progress and checkpoint information",
    )
    improve_parser.add_argument(
        "--worktree",
        action="store_true",
        help="Use git worktree isolation for each subtask (default when --hardened)",
    )
    improve_parser.add_argument(
        "--hardened",
        action="store_true",
        help="Use HardenedOrchestrator with gauntlet validation, mode enforcement, and worktree isolation",
    )
    improve_parser.add_argument(
        "--spectate",
        action="store_true",
        help="Enable real-time spectate event streaming",
    )
    improve_parser.add_argument(
        "--receipt",
        action="store_true",
        help="Generate DecisionReceipt for each completed subtask",
    )
    improve_parser.add_argument(
        "--budget-limit",
        type=float,
        default=None,
        help="Maximum budget in USD for this improvement run",
    )
    improve_parser.add_argument(
        "--coordinated",
        action="store_true",
        help="Use coordinated pipeline: MetaPlanner -> BranchCoordinator -> merge",
    )
    improve_parser.set_defaults(func=_lazy("aragora.cli.commands.tools", "cmd_improve"))


def _add_context_parser(subparsers) -> None:
    """Add the 'context' subcommand parser."""
    context_parser = subparsers.add_parser(
        "context",
        help="Build codebase context for RLM-powered analysis",
        description=(
            "Indexes the codebase and optionally builds a TRUE RLM context "
            "for deep codebase analysis (up to 10M tokens)."
        ),
    )
    context_parser.add_argument("--path", "-p", help="Path to codebase (default: current dir)")
    context_parser.add_argument(
        "--rlm",
        action="store_true",
        help="Build TRUE RLM context (REPL-based) when available",
    )
    context_parser.add_argument(
        "--full-corpus",
        action="store_true",
        help="Include full-corpus RLM summary (expensive)",
    )
    context_parser.add_argument(
        "--max-bytes",
        type=int,
        help="Max context bytes (overrides env, supports 10M tokens ~40MB)",
    )
    tests_group = context_parser.add_mutually_exclusive_group()
    tests_group.add_argument(
        "--include-tests",
        action="store_true",
        help="Include test files in the index",
    )
    tests_group.add_argument(
        "--exclude-tests",
        action="store_true",
        help="Exclude test files from the index",
    )
    context_parser.add_argument(
        "--summary-out",
        help="Write the debate context summary to a file",
    )
    context_parser.add_argument(
        "--preview",
        action="store_true",
        help="Print a short preview of the context summary",
    )
    context_parser.set_defaults(func=_lazy("aragora.cli.commands.tools", "cmd_context"))


def _add_serve_parser(subparsers) -> None:
    """Add the 'serve' subcommand parser."""
    serve_parser = subparsers.add_parser(
        "serve",
        help="Run live debate server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Production deployment:
    aragora serve --workers 4 --host 0.0.0.0

    Use a load balancer to distribute traffic across workers.
        """,
    )
    serve_parser.add_argument("--ws-port", type=int, default=8765, help="WebSocket port")
    serve_parser.add_argument("--api-port", type=int, default=8080, help="HTTP API port")
    serve_parser.add_argument("--host", default="localhost", help="Host to bind to")
    serve_parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=1,
        help="Number of worker processes (default: 1). For production, use 2-4x CPU cores.",
    )
    serve_parser.add_argument(
        "--demo",
        action="store_true",
        help="Start in demo mode with seed data (no API keys needed, uses SQLite)",
    )
    serve_parser.set_defaults(func=_lazy("aragora.cli.commands.server", "cmd_serve"))


def _add_init_parser(subparsers) -> None:
    """Add the 'init' subcommand parser."""
    init_parser = subparsers.add_parser("init", help="Initialize Aragora project")
    init_parser.add_argument("directory", nargs="?", help="Target directory (default: current)")
    init_parser.add_argument("--force", "-f", action="store_true", help="Overwrite existing files")
    init_parser.add_argument("--no-git", action="store_true", help="Don't modify .gitignore")
    init_parser.add_argument(
        "--ci",
        choices=["github"],
        default=None,
        help="Generate CI workflow (github = GitHub Actions)",
    )
    init_parser.add_argument(
        "--preset",
        choices=["review"],
        default=None,
        help="Configuration preset (review = optimized for code review)",
    )
    init_parser.set_defaults(func=_lazy("aragora.cli.commands.delegated", "cmd_init"))


def _add_setup_parser(subparsers) -> None:
    """Add the 'setup' subcommand parser."""
    setup_parser = subparsers.add_parser(
        "setup",
        help="Interactive setup wizard for API keys and configuration",
        description=(
            "Guides you through configuring Aragora including API keys, "
            "database settings, and optional integrations. Generates a .env file."
        ),
    )
    setup_parser.add_argument(
        "--output", "-o", help="Output directory for .env file (default: current)"
    )
    setup_parser.add_argument(
        "--minimal", "-m", action="store_true", help="Only configure essential settings"
    )
    setup_parser.add_argument("--skip-test", action="store_true", help="Skip API key validation")
    setup_parser.add_argument(
        "-y", "--yes", action="store_true", help="Non-interactive mode (use defaults)"
    )
    setup_parser.set_defaults(func=_lazy("aragora.cli.commands.delegated", "cmd_setup"))


def _add_backup_parser(subparsers) -> None:
    """Add the 'backup' subcommand parser."""
    from aragora.cli.backup import add_backup_subparsers

    add_backup_subparsers(subparsers)


def _add_repl_parser(subparsers) -> None:
    """Add the 'repl' subcommand parser."""
    repl_parser = subparsers.add_parser("repl", help="Interactive debate mode")
    repl_parser.add_argument(
        "--agents",
        "-a",
        default="anthropic-api,openai-api",
        help="Comma-separated agents for debates",
    )
    repl_parser.add_argument(
        "--rounds", "-r", type=int, default=8, help="Debate rounds (default: 8)"
    )
    repl_parser.set_defaults(func=_lazy("aragora.cli.commands.delegated", "cmd_repl"))


def _add_config_parser(subparsers) -> None:
    """Add the 'config' subcommand parser."""
    config_parser = subparsers.add_parser("config", help="Manage configuration")
    config_parser.add_argument(
        "action",
        nargs="?",
        default="show",
        choices=["show", "get", "set", "env", "path"],
        help="Config action",
    )
    config_parser.add_argument("key", nargs="?", help="Config key (for get/set)")
    config_parser.add_argument("value", nargs="?", help="Config value (for set)")
    config_parser.set_defaults(func=_lazy("aragora.cli.commands.delegated", "cmd_config"))


def _add_replay_parser(subparsers) -> None:
    """Add the 'replay' subcommand parser."""
    replay_parser = subparsers.add_parser("replay", help="Replay stored debates")
    replay_parser.add_argument(
        "action", nargs="?", default="list", choices=["list", "show", "play"], help="Replay action"
    )
    replay_parser.add_argument("id", nargs="?", help="Replay ID (for show/play)")
    replay_parser.add_argument("--directory", "-d", help="Replays directory")
    replay_parser.add_argument("--limit", "-n", type=int, default=10, help="Max replays to list")
    replay_parser.add_argument("--speed", "-s", type=float, default=1.0, help="Playback speed")
    replay_parser.set_defaults(func=_lazy("aragora.cli.commands.delegated", "cmd_replay"))


def _add_bench_parser(subparsers) -> None:
    """Add the 'bench' subcommand parser."""
    bench_parser = subparsers.add_parser("bench", help="Benchmark agents")
    bench_parser.add_argument(
        "--agents",
        "-a",
        default="anthropic-api,openai-api",
        help="Comma-separated agents to benchmark",
    )
    bench_parser.add_argument("--iterations", "-n", type=int, default=3, help="Iterations per task")
    bench_parser.add_argument("--task", "-t", help="Custom benchmark task")
    bench_parser.add_argument("--quick", "-q", action="store_true", help="Quick mode (1 iteration)")
    bench_parser.set_defaults(func=_lazy("aragora.cli.commands.delegated", "cmd_bench"))


def _add_review_parser(subparsers) -> None:
    """Add the 'review' subcommand parser (inlined to avoid heavy module import)."""
    parser = subparsers.add_parser(
        "review",
        help="Run AI code review on a diff or PR",
        description="Multi-agent AI code review for pull requests",
    )
    parser.add_argument(
        "pr_url",
        nargs="?",
        help="GitHub PR URL (e.g., https://github.com/owner/repo/pull/123)",
    )
    parser.add_argument("--diff-file", help="Path to diff file (alternative to PR URL or stdin)")
    parser.add_argument(
        "--agents",
        default=DEFAULT_AGENTS,
        help=f"Comma-separated list of agents (default: {DEFAULT_AGENTS})",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=DEFAULT_ROUNDS,
        help=f"Number of debate rounds (default: {DEFAULT_ROUNDS})",
    )
    parser.add_argument(
        "--focus",
        default="security,performance,quality",
        help="Focus areas: security,performance,quality (default: all)",
    )
    parser.add_argument(
        "--output-format",
        choices=["github", "json", "html"],
        default="github",
        help="Output format (default: github)",
    )
    parser.add_argument("--output-dir", help="Directory to save output artifacts")
    parser.add_argument(
        "--sarif",
        nargs="?",
        const="review-results.sarif",
        default=None,
        metavar="PATH",
        help="Export findings as SARIF 2.1.0 (default: review-results.sarif).",
    )
    parser.add_argument(
        "--gauntlet",
        action="store_true",
        default=False,
        help="Run adversarial gauntlet stress-test after review debate.",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        default=False,
        help="CI mode: exit with non-zero code based on findings severity.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run in demo mode (no API keys required, shows sample output)",
    )
    parser.add_argument(
        "--share",
        action="store_true",
        help="Generate a shareable link for this review",
    )
    parser.add_argument(
        "--post-comment",
        action="store_true",
        default=False,
        help="Post review findings as a comment on the GitHub PR. "
        "Requires a PR URL as the first argument and the 'gh' CLI installed.",
    )
    parser.set_defaults(func=_lazy("aragora.cli.review", "cmd_review"))


def _add_external_parsers(subparsers) -> None:
    """Add subcommand parsers that are defined in external modules."""

    # Gauntlet command (adversarial stress-testing)
    from aragora.cli.gauntlet import create_gauntlet_parser

    create_gauntlet_parser(subparsers)

    # Batch command (process multiple debates)
    from aragora.cli.batch import create_batch_parser

    create_batch_parser(subparsers)

    # Billing command
    from aragora.cli.billing import create_billing_parser

    create_billing_parser(subparsers)

    # Audit command (compliance audit logs)
    from aragora.cli.audit import create_audit_parser

    create_audit_parser(subparsers)

    # Document audit command (document analysis)
    from aragora.cli.document_audit import create_document_audit_parser

    create_document_audit_parser(subparsers)

    # Documents command (upload, list, show with folder support)
    from aragora.cli.documents import create_documents_parser

    create_documents_parser(subparsers)

    # Knowledge command (knowledge base operations)
    from aragora.cli.knowledge import create_knowledge_parser

    create_knowledge_parser(subparsers)

    # RLM command (recursive language model operations)
    from aragora.cli.rlm import create_rlm_parser

    create_rlm_parser(subparsers)

    # Template command (workflow template management)
    from aragora.cli.template import create_template_parser

    create_template_parser(subparsers)

    # Security command (encryption, key rotation)
    from aragora.cli.security import create_security_parser

    create_security_parser(subparsers)

    # Tenant command (multi-tenant management)
    from aragora.cli.tenant import create_tenant_parser

    create_tenant_parser(subparsers)

    # OpenClaw command (enterprise gateway management)
    from aragora.cli.openclaw import create_openclaw_parser

    create_openclaw_parser(subparsers)


def _add_badge_parser(subparsers) -> None:
    """Add the 'badge' subcommand parser."""
    badge_parser = subparsers.add_parser(
        "badge",
        help="Generate Aragora badge for your README",
        description="Generate shareable badges to show your project uses Aragora.",
    )
    badge_parser.add_argument(
        "--type",
        "-t",
        choices=["reviewed", "consensus", "gauntlet"],
        default="reviewed",
        help="Badge type: reviewed (blue), consensus (green), gauntlet (orange)",
    )
    badge_parser.add_argument(
        "--style",
        "-s",
        choices=["flat", "flat-square", "for-the-badge", "plastic"],
        default="flat",
        help="Badge style (default: flat)",
    )
    badge_parser.add_argument(
        "--repo",
        "-r",
        help="Link to specific repo (default: aragora repo)",
    )
    badge_parser.set_defaults(func=_lazy("aragora.cli.commands.delegated", "cmd_badge"))


def _add_verticals_parser(subparsers) -> None:
    """Add the 'verticals' subcommand parser for vertical specialists."""
    from aragora.cli.commands.verticals import add_verticals_parser

    add_verticals_parser(subparsers)


def _add_memory_parser(subparsers) -> None:
    """Add the 'memory' subcommand parser with API-backed sub-subcommands."""
    from aragora.cli.commands.memory_ops import add_memory_ops_parser

    add_memory_ops_parser(subparsers)


def _add_elo_parser(subparsers) -> None:
    """Add the 'elo' subcommand parser."""
    elo_parser = subparsers.add_parser(
        "elo",
        help="View ELO ratings, leaderboards, and match history",
        description="Inspect agent skill ratings, match history, and leaderboards.",
    )
    elo_parser.add_argument(
        "action",
        nargs="?",
        default="leaderboard",
        choices=["leaderboard", "history", "matches", "agent"],
        help="Action: leaderboard (default), history, matches, agent",
    )
    elo_parser.add_argument("--agent", "-a", help="Agent name (for history/agent actions)")
    elo_parser.add_argument("--domain", "-d", help="Filter by domain (for leaderboard)")
    elo_parser.add_argument("--limit", "-n", type=int, default=10, help="Max entries to show")
    elo_parser.add_argument("--db", help="Database path (default: from config)")
    elo_parser.set_defaults(func=_lazy("aragora.cli.commands.stats", "cmd_elo"))


def _add_cross_pollination_parser(subparsers) -> None:
    """Add the 'cross-pollination' subcommand parser."""
    xpoll_parser = subparsers.add_parser(
        "cross-pollination",
        aliases=["xpoll"],
        help="Cross-pollination event system diagnostics",
        description="View cross-subsystem event statistics and handler status.",
    )
    xpoll_parser.add_argument(
        "action",
        nargs="?",
        default="stats",
        choices=["stats", "subscribers", "reset"],
        help="Action: stats (default), subscribers, reset",
    )
    xpoll_parser.add_argument(
        "--json",
        "-j",
        action="store_true",
        help="Output in JSON format",
    )
    xpoll_parser.set_defaults(func=_lazy("aragora.cli.commands.stats", "cmd_cross_pollination"))


def _add_mcp_parser(subparsers) -> None:
    """Add the 'mcp-server' subcommand parser."""
    mcp_parser = subparsers.add_parser(
        "mcp-server",
        help="Run the MCP (Model Context Protocol) server",
        description="""
Run the Aragora MCP server for integration with Claude and other MCP clients.

The MCP server exposes Aragora's capabilities as tools:
- run_debate: Run decision stress-tests (debate engine)
- run_gauntlet: Stress-test documents
- list_agents: List available agents
- get_debate: Retrieve debate results

Configure in claude_desktop_config.json:
{
    "mcpServers": {
        "aragora": {
            "command": "aragora",
            "args": ["mcp-server"]
        }
    }
}
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mcp_parser.set_defaults(func=_lazy("aragora.cli.commands.delegated", "cmd_mcp_server"))


def _add_marketplace_parser(subparsers) -> None:
    """Add the 'marketplace' subcommand parser."""
    marketplace_parser = subparsers.add_parser(
        "marketplace",
        help="Manage agent template marketplace",
        description="List, search, import, and export agent templates. Use 'aragora marketplace --help' for subcommands.",
    )
    marketplace_parser.add_argument(
        "subcommand",
        nargs="?",
        help="Subcommand (list, search, get, export, import, categories, rate, use)",
    )
    marketplace_parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Subcommand arguments",
    )
    marketplace_parser.set_defaults(func=_lazy("aragora.cli.commands.delegated", "cmd_marketplace"))


def _add_skills_parser(subparsers) -> None:
    """Add the 'skills' subcommand parser for skill marketplace."""
    from aragora.cli.commands.skills import add_skills_parser

    add_skills_parser(subparsers)


def _add_nomic_parser(subparsers) -> None:
    """Add the 'nomic' subcommand parser for self-improvement loop."""
    from aragora.cli.commands.nomic import add_nomic_parser

    add_nomic_parser(subparsers)


def _add_workflow_parser(subparsers) -> None:
    """Add the 'workflow' subcommand parser for workflow engine."""
    from aragora.cli.commands.workflow import add_workflow_parser

    add_workflow_parser(subparsers)


def _add_deploy_parser(subparsers) -> None:
    """Add the 'deploy' subcommand parser for deployment validation."""
    from aragora.cli.commands.deploy import add_deploy_parser

    add_deploy_parser(subparsers)


def _add_control_plane_parser(subparsers) -> None:
    """Add the 'control-plane' subcommand parser."""
    cp_parser = subparsers.add_parser(
        "control-plane",
        help="Control plane status and management",
        description="""
Aragora Control Plane - orchestrate multi-agent vetted decisionmaking.

Show control plane status, list registered agents, and view connected channels.

Subcommands:
  status   - Show control plane overview (default)
  agents   - List registered agents and their status
  channels - List connected communication channels
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cp_parser.add_argument(
        "subcommand",
        nargs="?",
        default="status",
        choices=["status", "agents", "channels"],
        help="Subcommand (default: status)",
    )
    cp_parser.add_argument(
        "--server",
        default=DEFAULT_API_URL,
        help=f"API server URL (default: {DEFAULT_API_URL})",
    )
    cp_parser.set_defaults(func=_lazy("aragora.cli.commands.delegated", "cmd_control_plane"))


def _add_decide_parser(subparsers) -> None:
    """Add the 'decide' subcommand parser for the full gold path pipeline."""
    decide_parser = subparsers.add_parser(
        "decide",
        help="Run full decision pipeline: debate → plan → execute",
        description="""
Run the full decision pipeline (gold path):

  1. Debate: Multi-agent debate on the task
  2. Plan: Create decision plan from debate outcome
  3. Approve: Get approval (or auto-approve)
  4. Execute: Run the plan tasks
  5. Verify: Check execution results
  6. Learn: Store lessons in Knowledge Mound

Examples:
  aragora decide "Design a rate limiter" --agents grok,anthropic-api,openai-api
  aragora decide "Implement auth" --auto-approve --budget-limit 10.00
  aragora decide "Refactor database" --dry-run  # Create plan but don't execute
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    decide_parser.add_argument("task", help="The task/question to decide on")
    decide_parser.add_argument(
        "--agents",
        "-a",
        default=DEFAULT_AGENTS,
        help="Comma-separated agents for debate",
    )
    decide_parser.add_argument(
        "--auto-select",
        action="store_true",
        help="Auto-select an optimal agent team for the task",
    )
    decide_parser.add_argument(
        "--auto-select-config",
        help=(
            "JSON config for auto-selection (e.g. "
            '\'{"min_agents":3,"max_agents":5,"diversity_preference":0.5}\')'
        ),
    )
    decide_parser.add_argument(
        "--rounds",
        "-r",
        type=int,
        default=DEFAULT_ROUNDS,
        help=f"Number of debate rounds (default: {DEFAULT_ROUNDS})",
    )
    decide_parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Automatically approve plans (skip approval step)",
    )
    decide_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Create plan but don't execute",
    )
    execution_group = decide_parser.add_mutually_exclusive_group()
    execution_group.add_argument(
        "--execution-mode",
        choices=["workflow", "hybrid", "fabric", "computer_use"],
        help="Execution engine for implementation tasks",
    )
    execution_group.add_argument(
        "--hybrid",
        action="store_true",
        help="Use hybrid executor (Claude + Codex)",
    )
    execution_group.add_argument(
        "--computer-use",
        action="store_true",
        help="Use browser-based computer use executor",
    )
    decide_parser.add_argument(
        "--implementation-profile",
        help='JSON implementation profile (e.g. \'{"execution_mode":"fabric","fabric_models":["claude"]}\')',
    )
    decide_parser.add_argument(
        "--fabric-models",
        help="Comma-separated model list for fabric execution",
    )
    decide_parser.add_argument(
        "--channel-targets",
        help="Comma-separated channel targets for execution updates (e.g. slack:#eng,teams:abc)",
    )
    decide_parser.add_argument(
        "--thread-id",
        help="Thread ID to reply within for execution updates",
    )
    decide_parser.add_argument(
        "--thread-id-by-platform",
        help="JSON mapping of platform -> thread ID",
    )
    decide_parser.add_argument(
        "--budget-limit",
        type=float,
        help="Maximum budget for plan execution in USD",
    )
    decide_parser.add_argument(
        "--template",
        help="Workflow template to apply (e.g., sme_decision, code/security-audit)",
    )
    decide_parser.add_argument(
        "--list-templates",
        action="store_true",
        help="List available workflow templates and exit",
    )
    decide_parser.add_argument(
        "--mode",
        "-m",
        choices=["standard", "redteam", "deep_audit", "prober", "architect", "coder", "reviewer"],
        default="standard",
        help="Operational mode for the debate (default: standard)",
    )
    decide_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed progress",
    )
    decide_parser.add_argument(
        "--notify",
        action="store_true",
        help="Send notification on debate completion (Slack/Email/Webhook)",
    )
    decide_parser.add_argument(
        "--preset",
        choices=["sme", "enterprise", "minimal", "audit"],
        help="Apply a configuration preset (sme, enterprise, minimal, audit)",
    )
    decide_parser.add_argument(
        "--spectate",
        action="store_true",
        help="Enable real-time debate visualization in the terminal",
    )
    decide_parser.add_argument(
        "--spectate-format",
        choices=["auto", "ansi", "plain", "json"],
        default="auto",
        help="Spectator output format (default: auto)",
    )
    decide_parser.add_argument(
        "--demo",
        action="store_true",
        help="Run in demo mode with mock agents (no API keys required)",
    )
    decide_parser.set_defaults(func=_lazy("aragora.cli.commands.decide", "cmd_decide"))


def _add_plans_parser(subparsers) -> None:
    """Add the 'plans' subcommand parser for decision plan management."""
    plans_parser = subparsers.add_parser(
        "plans",
        help="Manage decision plans",
        description="""
Manage decision plans created by the 'decide' command or API.

Subcommands:
  list              - List all plans (default)
  show <id>         - Show plan details
  approve <id>      - Approve a pending plan
  reject <id>       - Reject a pending plan
  execute <id>      - Execute an approved plan

Examples:
  aragora plans                          # List plans
  aragora plans list --status pending    # List pending plans
  aragora plans show abc123              # Show plan details
  aragora plans approve abc123           # Approve plan
  aragora plans execute abc123           # Execute plan
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    plans_subparsers = plans_parser.add_subparsers(dest="plans_action")

    # plans list
    list_parser = plans_subparsers.add_parser("list", help="List decision plans")
    list_parser.add_argument(
        "--status",
        "-s",
        choices=[
            "created",
            "awaiting_approval",
            "approved",
            "rejected",
            "executing",
            "completed",
            "failed",
        ],
        help="Filter by status",
    )
    list_parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=20,
        help="Maximum plans to show (default: 20)",
    )
    list_parser.set_defaults(func=_lazy("aragora.cli.commands.decide", "cmd_plans"))

    # plans show
    show_parser = plans_subparsers.add_parser("show", help="Show plan details")
    show_parser.add_argument("plan_id", help="Plan ID (full or prefix)")
    show_parser.set_defaults(func=_lazy("aragora.cli.commands.decide", "cmd_plans_show"))

    # plans approve
    approve_parser = plans_subparsers.add_parser("approve", help="Approve a plan")
    approve_parser.add_argument("plan_id", help="Plan ID to approve")
    approve_parser.add_argument(
        "--reason",
        "-r",
        help="Reason for approval",
    )
    approve_parser.set_defaults(func=_lazy("aragora.cli.commands.decide", "cmd_plans_approve"))

    # plans reject
    reject_parser = plans_subparsers.add_parser("reject", help="Reject a plan")
    reject_parser.add_argument("plan_id", help="Plan ID to reject")
    reject_parser.add_argument(
        "--reason",
        "-r",
        help="Reason for rejection",
    )
    reject_parser.set_defaults(func=_lazy("aragora.cli.commands.decide", "cmd_plans_reject"))

    # plans execute
    execute_parser = plans_subparsers.add_parser("execute", help="Execute a plan")
    execute_parser.add_argument("plan_id", help="Plan ID to execute")
    execute_exec_group = execute_parser.add_mutually_exclusive_group()
    execute_exec_group.add_argument(
        "--execution-mode",
        choices=["workflow", "hybrid", "fabric", "computer_use"],
        help="Execution engine for implementation tasks",
    )
    execute_exec_group.add_argument(
        "--hybrid",
        action="store_true",
        help="Use hybrid executor (Claude + Codex)",
    )
    execute_exec_group.add_argument(
        "--fabric",
        action="store_true",
        help="Use fabric multi-agent execution",
    )
    execute_exec_group.add_argument(
        "--computer-use",
        action="store_true",
        help="Use browser-based computer use executor",
    )
    execute_parser.set_defaults(func=_lazy("aragora.cli.commands.decide", "cmd_plans_execute"))

    # Default behavior when just 'aragora plans' is called
    plans_parser.set_defaults(func=_lazy("aragora.cli.commands.decide", "cmd_plans"))


def _add_testfixer_parser(subparsers) -> None:
    """Add the 'testfixer' subcommand parser (inlined to avoid heavy module import)."""
    parser = subparsers.add_parser(
        "testfixer",
        help="Run automated test-fix loop",
        description="Run automated test-fix loop with multi-agent debate",
    )
    parser.add_argument("repo_path", help="Path to repository")
    parser.add_argument("--test-command", default="pytest tests/ -q --maxfail=1")
    parser.add_argument("--agents", default="codex,claude")
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--min-confidence-auto", type=float, default=0.7)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--attempt-store", default=None)
    parser.add_argument("--require-consensus", action="store_true")
    parser.add_argument("--no-revert", action="store_true")
    parser.add_argument(
        "--require-approval",
        action="store_true",
        help="Require manual approval before applying fixes",
    )
    parser.add_argument("--log-file", default=None, help="Path to log file (or '-' for stderr)")
    parser.add_argument("--log-level", default="info", help="Log level (debug, info, warning)")
    parser.add_argument("--run-id", default=None, help="Optional run id for correlation")
    parser.add_argument(
        "--artifacts-dir",
        default=None,
        help="Directory for per-run artifacts (default: .testfixer/runs)",
    )
    parser.add_argument("--no-diagnostics", action="store_true", help="Disable crash diagnostics")
    parser.add_argument(
        "--llm-analyzer", action="store_true", help="Enable LLM-powered failure analysis"
    )
    parser.add_argument(
        "--analysis-agents",
        default="",
        help="Agent types for analysis (comma-separated, default: --agents)",
    )
    parser.add_argument("--analysis-require-consensus", action="store_true")
    parser.add_argument("--analysis-consensus-threshold", type=float, default=0.7)
    parser.add_argument("--arena-validate", action="store_true", help="Enable Arena validator")
    parser.add_argument("--arena-agents", default="", help="Agent types for Arena validation")
    parser.add_argument("--arena-rounds", type=int, default=2)
    parser.add_argument("--arena-min-confidence", type=float, default=0.6)
    parser.add_argument("--arena-require-consensus", action="store_true")
    parser.add_argument("--arena-consensus-threshold", type=float, default=0.7)
    parser.add_argument(
        "--redteam-validate", action="store_true", help="Enable red team validation"
    )
    parser.add_argument(
        "--redteam-attackers", default="", help="Agent types for red team attackers"
    )
    parser.add_argument("--redteam-defender", default="", help="Agent type for red team defender")
    parser.add_argument("--redteam-rounds", type=int, default=2)
    parser.add_argument("--redteam-attacks-per-round", type=int, default=3)
    parser.add_argument("--redteam-min-robustness", type=float, default=0.6)
    parser.add_argument("--pattern-learning", action="store_true", help="Enable pattern learning")
    parser.add_argument("--pattern-store", default=None, help="Pattern store path")
    parser.add_argument("--generation-timeout-seconds", type=float, default=600.0)
    parser.add_argument("--critique-timeout-seconds", type=float, default=300.0)
    parser.set_defaults(func=_lazy("aragora.cli.commands.testfixer", "cmd_testfixer"))


def _add_computer_use_parser(subparsers) -> None:
    """Add the 'computer-use' subcommand parser."""
    from aragora.cli.commands.computer_use import add_computer_use_parser

    add_computer_use_parser(subparsers)


def _add_connectors_parser(subparsers) -> None:
    """Add the 'connectors' subcommand parser."""
    from aragora.cli.commands.connectors import add_connectors_parser

    add_connectors_parser(subparsers)


def _add_rbac_parser(subparsers) -> None:
    """Add the 'rbac' subcommand parser."""
    from aragora.cli.commands.rbac_ops import add_rbac_ops_parser

    add_rbac_ops_parser(subparsers)


def _add_km_parser(subparsers) -> None:
    """Add the 'km' subcommand parser for Knowledge Mound API operations."""
    from aragora.cli.commands.knowledge import add_knowledge_ops_parser

    add_knowledge_ops_parser(subparsers)


def _add_costs_parser(subparsers) -> None:
    """Add the 'costs' subcommand parser for billing API operations."""
    from aragora.cli.commands.billing_ops import add_billing_ops_parser

    add_billing_ops_parser(subparsers)


def _add_verify_parser(subparsers) -> None:
    """Add the 'verify' subcommand parser for receipt integrity verification."""
    from aragora.cli.commands.verify import create_verify_parser

    create_verify_parser(subparsers)


def _add_healthcare_parser(subparsers) -> None:
    """Add the 'healthcare' subcommand for clinical decision review."""
    from aragora.cli.commands.healthcare import add_healthcare_parser

    add_healthcare_parser(subparsers)


def _add_quickstart_parser(subparsers) -> None:
    """Add the 'quickstart' subcommand parser."""
    from aragora.cli.commands.quickstart import add_quickstart_parser

    add_quickstart_parser(subparsers)


def _add_receipt_parser(subparsers) -> None:
    """Add the 'receipt' subcommand parser for receipt management."""
    from aragora.cli.commands.receipt import add_receipt_parser

    add_receipt_parser(subparsers)


def _add_compliance_parser(subparsers) -> None:
    """Add the 'compliance' subcommand for EU AI Act compliance tools."""
    from aragora.cli.commands.compliance import add_compliance_parser

    add_compliance_parser(subparsers)


def _add_publish_parser(subparsers) -> None:
    """Add the 'publish' subcommand for package publishing."""
    from aragora.cli.commands.publish import add_publish_parser

    add_publish_parser(subparsers)


def _add_autopilot_parser(subparsers) -> None:
    """Add the 'autopilot' subcommand for autonomous GTM tasks."""
    from aragora.cli.commands.autopilot import add_autopilot_parser

    add_autopilot_parser(subparsers)


def _add_agent_parser(subparsers) -> None:
    """Add the 'agent' subcommand for autonomous agent operations."""
    agent_parser = subparsers.add_parser(
        "agent",
        help="Run autonomous agents (DevOps, review, triage)",
        description="""
Run autonomous agents that handle repository operations through
policy-controlled execution. Every action is audited.

Examples:
    aragora agent run devops --repo an0mium/aragora --task health-check
    aragora agent run devops --repo an0mium/aragora --task review-prs --dry-run
    aragora agent run devops --repo an0mium/aragora --mode watch
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    agent_sub = agent_parser.add_subparsers(dest="agent_command")

    run_parser = agent_sub.add_parser("run", help="Run an agent")
    run_parser.add_argument(
        "agent_type",
        choices=["devops"],
        help="Agent type to run",
    )
    run_parser.add_argument(
        "--repo",
        required=True,
        help="GitHub repository (owner/repo format)",
    )
    run_parser.add_argument(
        "--task",
        choices=["review-prs", "triage-issues", "prepare-release", "health-check"],
        help="Specific task to run",
    )
    run_parser.add_argument(
        "--mode",
        choices=["once", "watch"],
        default="once",
        help="Execution mode (default: once)",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without executing",
    )
    run_parser.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Allow destructive operations (publish, tag, merge)",
    )
    run_parser.add_argument(
        "--poll-interval",
        type=int,
        default=300,
        help="Seconds between polls in watch mode",
    )
    run_parser.set_defaults(func=cmd_agent_run)

    agent_parser.set_defaults(func=lambda args: agent_parser.print_help())


def cmd_agent_run(args):
    """Run an autonomous agent."""
    from aragora.agents.devops.agent import (
        DevOpsAgent,
        DevOpsAgentConfig,
        DevOpsTask,
    )

    config = DevOpsAgentConfig(
        repo=args.repo,
        dry_run=args.dry_run,
        allow_destructive=args.allow_destructive,
        poll_interval=args.poll_interval,
    )
    agent = DevOpsAgent(config=config)

    if args.mode == "watch":
        tasks = [DevOpsTask(args.task)] if args.task else None
        agent.watch(tasks=tasks)
        return 0

    if not args.task:
        print("Error: --task is required in 'once' mode")
        return 1

    task = DevOpsTask(args.task)
    result = agent.run_task(task)

    status = "OK" if result.success else "FAILED"
    print(f"\nTask: {result.task} [{status}]")
    print(f"Processed: {result.items_processed}  Skipped: {result.items_skipped}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    if result.errors:
        for err in result.errors:
            print(f"  Error: {err}")

    return 0 if result.success else 1


def _add_analytics_parser(subparsers) -> None:
    """Add the 'analytics' subcommand parser."""
    from aragora.cli.commands.analytics import add_analytics_parser

    add_analytics_parser(subparsers)


def _add_starter_parser(subparsers) -> None:
    """Add the 'starter' subcommand parser for SME Starter Pack."""
    from aragora.cli.commands.starter import add_starter_parser

    add_starter_parser(subparsers)


def _add_handlers_parser(subparsers) -> None:
    """Add the 'handlers' subcommand parser for handler inventory."""
    from aragora.cli.commands.handlers import add_handlers_parser

    add_handlers_parser(subparsers)


def _add_coordinate_parser(subparsers) -> None:
    """Add the 'coordinate' subcommand parser for multi-agent coordination."""
    from aragora.cli.commands.coordinate import add_coordinate_parser

    add_coordinate_parser(subparsers)


def _add_self_improve_parser(subparsers) -> None:
    """Add the 'self-improve' subcommand -- unified hardened pipeline.

    This is the recommended entry point for autonomous self-improvement.
    All hardened flags default to True.
    """
    si_parser = subparsers.add_parser(
        "self-improve",
        help="Run self-improvement pipeline with worktree isolation and validation",
        description="""
Run the full self-improvement pipeline:

  1. MetaPlanner debate -> prioritize goals
  2. TaskDecomposer -> break into subtasks per track
  3. WorktreeManager -> create isolated worktrees per subtask
  4. HardenedOrchestrator -> execute with gauntlet validation + mode enforcement
  5. BranchCoordinator -> merge passing branches, reject failing ones
  6. DecisionReceipt -> generate audit receipts per subtask

Examples:
  aragora self-improve "Make Aragora the best decision platform for SMEs"
  aragora self-improve "Improve test coverage" --tracks qa --budget-limit 5
  aragora self-improve "Harden security" --dry-run
  aragora self-improve "Add docstrings to aragora/resilience/" --budget-limit 1.0
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    si_parser.add_argument(
        "goal",
        help="The improvement goal to execute",
    )
    si_parser.add_argument(
        "--tracks",
        "-t",
        help="Comma-separated tracks (sme, developer, self_hosted, qa, core, security)",
    )
    si_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview decomposition without executing",
    )
    si_parser.add_argument(
        "--max-cycles",
        type=int,
        default=5,
        help="Maximum improvement cycles per subtask (default: 5)",
    )
    si_parser.add_argument(
        "--require-approval",
        action="store_true",
        help="Require human approval at checkpoint gates",
    )
    si_parser.add_argument(
        "--budget-limit",
        type=float,
        default=None,
        help="Maximum budget in USD for this run",
    )
    si_parser.add_argument(
        "--spectate",
        action="store_true",
        default=True,
        help="Enable real-time spectate event streaming (default: on)",
    )
    si_parser.add_argument(
        "--no-spectate",
        dest="spectate",
        action="store_false",
        help="Disable spectate streaming",
    )
    si_parser.add_argument(
        "--receipt",
        action="store_true",
        default=True,
        help="Generate DecisionReceipts (default: on)",
    )
    si_parser.add_argument(
        "--no-receipt",
        dest="receipt",
        action="store_false",
        help="Disable receipt generation",
    )
    si_parser.add_argument(
        "--hierarchical",
        action="store_true",
        help="Use hierarchical planner/worker/judge coordination",
    )
    si_parser.add_argument(
        "--sessions",
        type=int,
        default=None,
        help="Number of parallel sessions (maps to BranchCoordinator parallelism)",
    )
    si_parser.add_argument(
        "--path",
        "-p",
        help="Path to codebase (default: current dir)",
    )
    si_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed progress",
    )
    si_parser.set_defaults(func=_lazy("aragora.cli.commands.self_improve", "cmd_self_improve"))


def _add_worktree_parser(subparsers) -> None:
    """Add the 'worktree' subcommand for multi-agent worktree management."""
    from aragora.cli.commands.worktree import add_worktree_parser

    add_worktree_parser(subparsers)


def _add_outcome_parser(subparsers) -> None:
    """Add the 'outcome' subcommand for decision outcome tracking."""
    from aragora.cli.commands.outcome import add_outcome_parser

    add_outcome_parser(subparsers)


def _add_explain_parser(subparsers) -> None:
    """Add the 'explain' subcommand for decision explanation."""
    from aragora.cli.commands.explain import add_explain_parser

    add_explain_parser(subparsers)


def _add_playbook_parser(subparsers) -> None:
    """Add the 'playbook' subcommand for decision playbooks."""
    from aragora.cli.commands.playbook import add_playbook_parser

    add_playbook_parser(subparsers)


def _add_pipeline_parser(subparsers) -> None:
    """Add the 'pipeline' subcommand for idea-to-execution pipeline."""
    from aragora.cli.commands.pipeline import add_pipeline_parser

    add_pipeline_parser(subparsers)


def _add_consensus_parser(subparsers) -> None:
    """Add the 'consensus' subcommand for consensus detection and analysis."""
    from aragora.cli.commands.consensus import add_consensus_parser

    add_consensus_parser(subparsers)


def _add_ideacloud_parser(subparsers) -> None:
    """Add the 'ideacloud' subcommand group for managing the Idea Cloud."""
    from aragora.ideacloud.cli.commands import add_ideacloud_commands

    add_ideacloud_commands(subparsers)


def _add_signing_parser(subparsers) -> None:
    """Add the 'signing' subcommand for context file signing and verification (G1)."""
    from aragora.cli.commands.signing import add_signing_parser

    add_signing_parser(subparsers)


def _add_inbox_wedge_parser(subparsers) -> None:
    """Add the 'inbox-wedge' subcommand for trust wedge receipts and review."""
    from aragora.cli.commands.inbox_wedge import add_inbox_wedge_parser

    add_inbox_wedge_parser(subparsers)


def _add_triage_parser(subparsers) -> None:
    """Add the 'triage' subcommand for inbox trust wedge."""
    from aragora.cli.commands.triage import add_triage_parser

    add_triage_parser(subparsers)


def _add_swarm_parser(subparsers) -> None:
    """Add the 'swarm' subcommand for swarm commander."""
    swarm_parser = subparsers.add_parser(
        "swarm",
        help="Launch a swarm of AI agents to accomplish a goal",
        description=(
            "Swarm Commander: interrogate -> spec -> dispatch -> merge -> report.\n\n"
            "The swarm will:\n"
            "  1. Ask you questions to understand your goal\n"
            "  2. Break the goal into tasks and dispatch agents\n"
            "  3. Agents work in parallel in isolated worktrees\n"
            "  4. Merge successful changes back to main\n"
            "  5. Report results in plain language"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    swarm_parser.add_argument(
        "swarm_action_or_goal",
        nargs="?",
        help="Action (run/status/reconcile) or your goal in plain language",
    )
    swarm_parser.add_argument(
        "swarm_goal",
        nargs="?",
        help="Goal when using the explicit 'run' action",
    )
    swarm_parser.add_argument(
        "--spec",
        help="Path to a pre-built SwarmSpec YAML file",
    )
    swarm_parser.add_argument(
        "--skip-interrogation",
        action="store_true",
        help="Skip Q&A phase, use goal directly (developer mode)",
    )
    swarm_parser.add_argument(
        "--budget-limit",
        type=float,
        default=50.0,
        help="Maximum budget in USD (default: 50.0)",
    )
    swarm_parser.add_argument(
        "--max-parallel",
        type=int,
        default=20,
        help="Maximum parallel tasks (default: 20)",
    )
    swarm_parser.add_argument(
        "--no-loop",
        action="store_true",
        help="Run once without iterative loop (single-shot mode)",
    )
    swarm_parser.add_argument(
        "--profile",
        choices=["ceo", "cto", "developer", "power-user"],
        default="ceo",
        help="User profile for prompt style and report detail (default: ceo)",
    )
    swarm_parser.add_argument(
        "--from-obsidian",
        metavar="VAULT_PATH",
        help="Read goals from tagged Obsidian notes in the given vault",
    )
    swarm_parser.add_argument(
        "--obsidian-vault",
        metavar="VAULT_PATH",
        help="Write decision receipts to this Obsidian vault",
    )
    swarm_parser.add_argument(
        "--no-obsidian-receipts",
        action="store_true",
        help="Disable writing receipts to Obsidian vault",
    )
    swarm_parser.add_argument(
        "--autonomy",
        choices=["full-auto", "propose", "guided", "metrics"],
        default="propose",
        help="Self-improvement autonomy level (default: propose)",
    )
    swarm_parser.add_argument(
        "--require-approval",
        action="store_true",
        help="Require approval at safety gates",
    )
    swarm_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the spec without executing (interrogation only)",
    )
    swarm_parser.add_argument(
        "--save-spec",
        help="Save the produced spec to a YAML file",
    )
    swarm_parser.add_argument(
        "--target-branch",
        default="main",
        help="Branch to integrate toward (default: main)",
    )
    swarm_parser.add_argument(
        "--concurrency-cap",
        type=int,
        default=8,
        help="Supervisor worker cap, clamped to 8 (default: 8)",
    )
    swarm_parser.add_argument(
        "--managed-dir-pattern",
        default=".worktrees/{agent}-auto",
        help="Managed worktree directory pattern (default: .worktrees/{agent}-auto)",
    )
    swarm_parser.add_argument(
        "--run-id",
        default=None,
        help="Specific supervisor run ID for 'status'",
    )
    swarm_parser.add_argument(
        "--status-limit",
        type=int,
        default=20,
        help="Maximum runs to show in 'status' (default: 20)",
    )
    swarm_parser.add_argument(
        "--refresh-scaling",
        action="store_true",
        help="Top up queued work orders when showing status",
    )
    swarm_parser.add_argument(
        "--no-dispatch",
        action="store_true",
        help="Create or refresh supervisor state without launching worker sessions",
    )
    swarm_parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep reconciling the run until it reaches a stable stop condition",
    )
    swarm_parser.add_argument(
        "--interval-seconds",
        type=float,
        default=5.0,
        help="Reconciler polling interval for --watch or reconcile (default: 5.0)",
    )
    swarm_parser.add_argument(
        "--max-ticks",
        type=int,
        default=None,
        help="Maximum reconcile ticks for --watch",
    )
    swarm_parser.add_argument(
        "--all-runs",
        action="store_true",
        help="Reconcile all open runs instead of requiring --run-id",
    )
    swarm_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output",
    )
    swarm_parser.set_defaults(
        func=lambda args: __import__(
            "aragora.cli.commands.swarm", fromlist=["cmd_swarm"]
        ).cmd_swarm(args)
    )
