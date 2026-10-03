"""
CLI argument parser construction.

Builds the argparse parser with all subcommands and their arguments.
Separated from command implementations for clarity and maintainability.
"""

import argparse
import os

from aragora.cli._mission_parser import add_mission_parser
from aragora.config import DEFAULT_AGENTS, DEFAULT_CONSENSUS, DEFAULT_ROUNDS

DEFAULT_CAMPAIGN_MANIFEST = ".aragora/campaign_manifest.yaml"

# Default API URL from environment or localhost fallback
DEFAULT_API_URL = os.environ.get("ARAGORA_API_URL", "http://localhost:8080")
DEFAULT_API_KEY = os.environ.get("ARAGORA_API_KEY")

# Commands shown prominently in --help.  Everything else is "advanced".
CORE_COMMANDS: frozenset[str] = frozenset(
    {
        "quickstart",
        "ask",
        "decide",
        "consensus",
        "serve",
        "triage",
    }
)


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


class _GroupedCommandsParser(argparse.ArgumentParser):
    """ArgumentParser that groups subcommands into core / advanced."""

    def format_help(self) -> str:
        formatter = self._get_formatter()
        formatter.add_usage(self.usage, self._actions, self._mutually_exclusive_groups)
        if self.description:
            formatter.add_text(self.description)

        subparser_action = None
        for action in self._actions:
            if isinstance(action, argparse._SubParsersAction):
                subparser_action = action
            else:
                formatter.add_arguments([action])

        if subparser_action is not None:
            core: list[tuple[str, str]] = []
            advanced: list[tuple[str, str]] = []
            for choice, _parser in (subparser_action.choices or {}).items():
                help_text = ""
                for sub_action in subparser_action._choices_actions:
                    if sub_action.dest == choice:
                        help_text = sub_action.help or ""
                        break
                entry = (choice, help_text)
                (core if choice in CORE_COMMANDS else advanced).append(entry)

            if core:
                formatter.start_section("core commands")
                for name, help_text in sorted(core):
                    formatter.add_text(f"  {name:<20}{help_text}")
                formatter.end_section()
            if advanced:
                formatter.start_section("advanced commands")
                for name, help_text in sorted(advanced):
                    formatter.add_text(f"  {name:<20}{help_text}")
                formatter.end_section()

        if self.epilog:
            formatter.add_text(self.epilog)
        return formatter.format_help()


def build_parser() -> argparse.ArgumentParser:
    """Build and return the complete CLI argument parser."""
    parser = _GroupedCommandsParser(
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
    _add_api_key_parser(subparsers)
    _add_secrets_parser(subparsers)
    _add_replay_parser(subparsers)
    _add_bench_parser(subparsers)
    _add_review_parser(subparsers)
    _add_review_pr_parser(subparsers)
    _add_review_local_parser(subparsers)
    _add_review_queue_parser(subparsers)
    _add_codebase_audit_parser(subparsers)
    _add_external_parsers(subparsers)
    _add_badge_parser(subparsers)
    _add_verticals_parser(subparsers)
    _add_memory_parser(subparsers)
    _add_elo_parser(subparsers)
    _add_cross_pollination_parser(subparsers)
    _add_mcp_parser(subparsers)
    _add_marketplace_parser(subparsers)
    _add_skills_parser(subparsers)
    add_mission_parser(subparsers, _lazy)
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
    _add_tasks_parser(subparsers)
    _add_work_parser(subparsers)
    _add_worktree_parser(subparsers)
    _add_outcome_parser(subparsers)
    _add_explain_parser(subparsers)
    _add_playbook_parser(subparsers)
    _add_pipeline_parser(subparsers)
    _add_consensus_parser(subparsers)
    _add_ideacloud_parser(subparsers)
    _add_signing_parser(subparsers)
    _add_inbox_wedge_parser(subparsers)
    _add_codex_parser(subparsers)
    _add_factory_parser(subparsers)
    _add_triage_parser(subparsers)
    _add_ralph_parser(subparsers)
    _add_assess_parser(subparsers)
    _add_spec_parser(subparsers)
    _add_crux_parser(subparsers)
    _add_idea_parser(subparsers)
    _add_build_parser(subparsers)
    _add_essay_parser(subparsers)

    # AGT-* / DIC-* operator surfaces (read-only)
    _add_metrics_parser(subparsers)
    _add_markets_parser(subparsers)
    _add_calibration_parser(subparsers)
    _add_cruxset_parser(subparsers)
    _add_crux_followup_parser(subparsers)
    _add_proof_units_parser(subparsers)  # DIC-19 / #6030
    _add_genealogy_parser(subparsers)  # DIC-24 / #6218
    _add_coherence_scan_parser(subparsers)  # DIC-26 / #6220
    _add_truth_map_parser(subparsers)  # DIC-18 / #6028
    _add_decay_monitor_parser(subparsers)  # DIC-20 / #6031
    _add_epistemic_check_parser(subparsers)  # DIC-14 / #6024

    # DIC-27: operator crux arbitration surface
    _add_crux_arbitrate_parser(subparsers)

    # DIC-28: proactive crux gardening operator surface
    _add_crux_garden_parser(subparsers)

    return parser


# ---------------------------------------------------------------------------
# AGT-* operator subparsers — added as part of AGT-06 / AGT-04 / AGT-01 follow-up
# ---------------------------------------------------------------------------


def _add_metrics_parser(subparsers) -> None:
    """Add the 'metrics' subcommand group with 'viah' and 'status' verbs."""
    metrics_parser = subparsers.add_parser(
        "metrics",
        help="AGT-06: read VIAH and other operator metrics",
        description="Operator-readable metrics derived from the ShiftLedger.",
    )
    metrics_sub = metrics_parser.add_subparsers(dest="metrics_cmd")
    viah = metrics_sub.add_parser(
        "viah",
        help="Print verifiable improvements per agent-hour from the ShiftLedger",
    )
    viah.add_argument(
        "--ledger-path",
        default=None,
        help="Path to the ShiftLedger JSONL (default: aragora.swarm.shift_ledger.DEFAULT_LEDGER_PATH)",
    )
    viah.add_argument(
        "--window-hours",
        type=float,
        default=168.0,
        help="Rolling window over which to compute VIAH (default: 168 = 7 days)",
    )
    viah.add_argument(
        "--cruxes-correctly-detected",
        type=int,
        default=0,
        help="Sidecar count of cruxes correctly detected pre-resolution (AGT-05)",
    )
    viah.add_argument(
        "--predictions-above-brier-threshold",
        type=int,
        default=0,
        help="Sidecar count of predictions with Brier below the calibration threshold (AGT-05)",
    )
    viah.add_argument(
        "--failed-claims-promoted-without-repair",
        type=int,
        default=0,
        help="Sidecar count of failed claims promoted without bounded repair (AGT-05)",
    )
    viah.add_argument("--json", action="store_true", help="Emit the report as JSON")
    viah.set_defaults(func=_lazy("aragora.cli.commands.agt_metrics", "cmd_metrics_viah"))

    status = metrics_sub.add_parser(
        "status",
        help=("Print VIAH operator-truth Markdown report (gated: ARAGORA_VIAH_TREND_ENABLED=1)"),
    )
    status.add_argument(
        "--ledger-path",
        default=None,
        help="Path to the ShiftLedger JSONL (default: DEFAULT_LEDGER_PATH)",
    )
    status.add_argument(
        "--weeks",
        type=int,
        default=4,
        help="Number of rolling weeks to include in the trend table (default: 4)",
    )
    status.add_argument(
        "--output",
        default=None,
        help="Write the Markdown report to this file path instead of stdout",
    )
    status.set_defaults(func=_lazy("aragora.cli.commands.agt_metrics", "cmd_metrics_status"))


def _add_work_parser(subparsers) -> None:
    """Add the read-only Aragora-native work board commands."""

    def _nonnegative_int(raw: str) -> int:
        value = int(raw)
        if value < 0:
            raise argparse.ArgumentTypeError("must be >= 0")
        return value

    work = subparsers.add_parser(
        "work",
        help="Inspect the read-only Aragora work board",
        description=(
            "Read-only Agent Flywheel kernel over PRs, automation, broker runs, "
            "beads/convoys, and missions. This command never claims, launches, "
            "closes, or mutates work."
        ),
    )

    def _work_parent_help(_args: argparse.Namespace) -> int:
        work.print_help()
        return 2

    # Running ``aragora work`` with no subcommand prints help and exits cleanly
    # (mirrors the sibling ``codex`` parser) instead of raising AttributeError
    # when main.py dispatches args.func.
    work.set_defaults(func=_work_parent_help)
    work_sub = work.add_subparsers(dest="work_cmd")

    def add_common(p) -> None:
        p.add_argument("--repo", default=".", help="Repository root to inspect (default: cwd)")
        p.add_argument("--json", action="store_true", help="Emit stable JSON")

    def add_limit(p) -> None:
        p.add_argument(
            "--limit",
            type=_nonnegative_int,
            default=None,
            help="Maximum number of records to emit while preserving the total count",
        )

    list_cmd = work_sub.add_parser("list", help="List normalized work items")
    add_common(list_cmd)
    list_cmd.add_argument(
        "--scope",
        choices=("current", "all"),
        default="current",
        help="current excludes terminal/historical noise; all includes context records",
    )
    add_limit(list_cmd)
    list_cmd.set_defaults(func=_lazy("aragora.cli.commands.work_board", "cmd_work_list"))

    show_cmd = work_sub.add_parser("show", help="Show one normalized work item")
    add_common(show_cmd)
    show_cmd.add_argument("work_id", help="Work item id, e.g. pr:7210")
    show_cmd.set_defaults(func=_lazy("aragora.cli.commands.work_board", "cmd_work_show"))

    graph_cmd = work_sub.add_parser("graph", help="Show the work dependency/context graph")
    add_common(graph_cmd)
    graph_cmd.add_argument("work_id", nargs="?", help="Optional root work item id")
    graph_cmd.set_defaults(func=_lazy("aragora.cli.commands.work_board", "cmd_work_graph"))

    robot_cmd = work_sub.add_parser(
        "robot",
        help="Rank current work into read-only actionable recommendations",
    )
    add_common(robot_cmd)
    add_limit(robot_cmd)
    robot_cmd.set_defaults(func=_lazy("aragora.cli.commands.work_board", "cmd_work_robot"))


def _add_markets_parser(subparsers) -> None:
    """Add the 'markets' subcommand group with list, predict, create, and resolve verbs."""
    markets_parser = subparsers.add_parser(
        "markets",
        help="AGT-04: inspect and interact with synthetic GitHub prediction markets",
        description="Operator surface for the synthetic-market store.",
    )
    markets_sub = markets_parser.add_subparsers(dest="markets_cmd")
    lst = markets_sub.add_parser(
        "list",
        help="List markets in the given store directory",
    )
    lst.add_argument(
        "--store-dir",
        default=".aragora_markets",
        help="Path to the synthetic-market JSONL store directory (default: .aragora_markets)",
    )
    lst.add_argument("--json", action="store_true", help="Emit the listing as JSON")
    lst.set_defaults(func=_lazy("aragora.cli.commands.agt_markets", "cmd_markets_list"))

    pred = markets_sub.add_parser(
        "predict",
        help="Record an agent prediction (position) on an open market",
        description=(
            "Write a MarketPosition to the store for the given market. "
            "The market must exist and must not yet be resolved."
        ),
    )
    pred.add_argument("--market-id", required=True, help="Market ID to predict on")
    pred.add_argument("--agent", required=True, help="Agent ID making the prediction")
    pred.add_argument(
        "--probability",
        required=True,
        type=float,
        metavar="FLOAT",
        help="Predicted P(YES) in [0, 1]",
    )
    pred.add_argument(
        "--stake",
        required=True,
        type=int,
        metavar="INT",
        help="Stake in internal credits [1..100]",
    )
    pred.add_argument("--rationale", default="", help="Optional free-text rationale")
    pred.add_argument(
        "--store-dir",
        default=".aragora_markets",
        help="Path to the synthetic-market JSONL store directory (default: .aragora_markets)",
    )
    pred.add_argument("--json", action="store_true", help="Emit the saved position as JSON")
    pred.set_defaults(func=_lazy("aragora.cli.commands.agt_markets", "cmd_markets_predict"))

    _store_arg = dict(
        default=".aragora_markets", help="JSONL store directory (default: .aragora_markets)"
    )
    create = markets_sub.add_parser(
        "create", help="Create a new synthetic GitHub prediction market"
    )
    create.add_argument(
        "--type",
        required=True,
        choices=["pr_merge", "issue_close", "ci_pass"],
        help="Question type",
    )
    create.add_argument("--repo", required=True, help="Repository in owner/name format")
    create.add_argument(
        "--number",
        type=int,
        metavar="INT",
        help="PR/issue number (required for pr_merge and issue_close)",
    )
    create.add_argument("--ref", metavar="REF", help="Git ref (required for ci_pass)")
    create.add_argument(
        "--window-days",
        type=int,
        metavar="INT",
        help="Resolution window in days (default: 7 for pr/ci, 30 for issues)",
    )
    create.add_argument("--store-dir", **_store_arg)
    create.add_argument("--json", action="store_true", help="Emit created market as JSON")
    create.set_defaults(func=_lazy("aragora.cli.commands.agt_markets", "cmd_markets_create"))

    resolve = markets_sub.add_parser("resolve", help="Manually resolve a market (operator action)")
    resolve.add_argument("market_id", help="Market ID to resolve")
    resolve.add_argument(
        "--outcome", required=True, choices=["yes", "no", "inconclusive"], help="Resolution outcome"
    )
    resolve.add_argument("--evidence", default="", help="Optional free-text rationale")
    resolve.add_argument("--store-dir", **_store_arg)
    resolve.add_argument("--json", action="store_true", help="Emit resolution event as JSON")
    resolve.set_defaults(func=_lazy("aragora.cli.commands.agt_markets", "cmd_markets_resolve"))


def _add_calibration_parser(subparsers) -> None:
    """Add the 'calibration' subcommand group.

    AGT-03.3 calibration consumer surface: reads positions and
    resolutions from the synthetic-market store and reports per-agent
    rolling-window Brier scores.
    """
    calib_parser = subparsers.add_parser(
        "calibration",
        help="AGT-03.3: per-agent rolling-window Brier reports from market data",
        description=(
            "Read-only operator surface for prediction-market calibration. "
            "Computes per-agent Brier scores (mean, stake-weighted, "
            "time-decayed) over a rolling window using positions and "
            "resolutions recorded in the synthetic-market store."
        ),
    )
    calib_sub = calib_parser.add_subparsers(dest="calibration_cmd")

    report = calib_sub.add_parser(
        "report",
        help="Print per-agent Brier breakdown over a rolling window",
    )
    report.add_argument(
        "--store-dir",
        default=".aragora_markets",
        help="Path to the synthetic-market JSONL store directory (default: .aragora_markets)",
    )
    report.add_argument(
        "--agent",
        default=None,
        help="Restrict the report to a single agent_id (default: all agents)",
    )
    report.add_argument(
        "--window-days",
        type=float,
        default=90.0,
        help="Rolling window in days (default: 90 per the AGT-03 plan)",
    )
    report.add_argument(
        "--half-life-days",
        type=float,
        default=30.0,
        help="Exponential time-decay half-life in days (default: 30)",
    )
    report.add_argument(
        "--since",
        default=None,
        help=(
            "Absolute start date (YYYY-MM-DD) for the rolling window. "
            "When provided, overrides --window-days for reproducible "
            "round-after-round comparisons."
        ),
    )
    report.add_argument("--json", action="store_true", help="Emit the report as JSON")
    report.add_argument(
        "--markdown",
        action="store_true",
        help="Emit the report as a docs-pasteable Markdown table",
    )
    report.set_defaults(
        func=_lazy("aragora.cli.commands.agt_calibration", "cmd_calibration_report")
    )

    leaderboard = calib_sub.add_parser(
        "leaderboard",
        help="Rank agents by Brier score (lower = better calibrated)",
    )
    leaderboard.add_argument(
        "--store-dir",
        default=".aragora_markets",
        help="Path to the synthetic-market JSONL store directory (default: .aragora_markets)",
    )
    leaderboard.add_argument(
        "--window-days",
        type=float,
        default=90.0,
        help="Rolling window in days (default: 90 per the AGT-03 plan)",
    )
    leaderboard.add_argument(
        "--half-life-days",
        type=float,
        default=30.0,
        help="Exponential time-decay half-life in days (default: 30)",
    )
    leaderboard.add_argument(
        "--min-scored",
        type=int,
        default=5,
        help=(
            "Minimum scored positions required to appear on the leaderboard "
            "(default: 5; agents below the floor are excluded but visible "
            "in --json output)"
        ),
    )
    leaderboard.add_argument(
        "--sort-by",
        choices=("decayed", "mean", "stake_weighted"),
        default="decayed",
        help="Brier flavor used for ranking (default: decayed)",
    )
    leaderboard.add_argument(
        "--since",
        default=None,
        help=(
            "Absolute start date (YYYY-MM-DD) for the rolling window. "
            "When provided, overrides --window-days for reproducible "
            "round-after-round comparisons."
        ),
    )
    leaderboard.add_argument("--json", action="store_true", help="Emit the leaderboard as JSON")
    leaderboard.add_argument(
        "--markdown",
        action="store_true",
        help="Emit the leaderboard as a docs-pasteable Markdown table",
    )
    leaderboard.set_defaults(
        func=_lazy("aragora.cli.commands.agt_calibration", "cmd_calibration_leaderboard")
    )


def _add_cruxset_parser(subparsers) -> None:
    """Add the 'cruxset' subcommand group with a 'show' verb."""
    cruxset_parser = subparsers.add_parser(
        "cruxset",
        help="AGT-01: inspect CruxSet payloads emitted by the debate path",
        description="Read-only operator surface for CruxSet artifacts.",
    )
    cruxset_sub = cruxset_parser.add_subparsers(dest="cruxset_cmd")
    show = cruxset_sub.add_parser(
        "show",
        help="Pretty-print a CruxSet from a JSON file or stdin (use '-' for stdin)",
    )
    show.add_argument(
        "source",
        nargs="?",
        default="-",
        help="Path to a CruxSet JSON file, or '-' to read from stdin (default: stdin)",
    )
    show.add_argument(
        "--json",
        action="store_true",
        help="Re-emit the (verified) CruxSet as JSON instead of pretty-printing",
    )
    show.set_defaults(func=_lazy("aragora.cli.commands.agt_cruxset", "cmd_cruxset_show"))


def _add_proof_units_parser(subparsers) -> None:
    """Add the 'proof-units' subcommand for DIC-19 constraint graph surface.

    Flag-gated: ARAGORA_PROOF_UNIT_SCAN_ENABLED must be set.
    Live queue effect: none (read-only operator report).
    """
    p = subparsers.add_parser(
        "proof-units",
        help="DIC-19: inspect proof-carrying code unit constraint graph",
        description=(
            "Read-only operator surface for the proof-carrying code unit constraint graph. "
            "Requires ARAGORA_PROOF_UNIT_SCAN_ENABLED=1."
        ),
    )
    p.add_argument(
        "--proof-units-dir",
        dest="proof_units_dir",
        default=None,
        help="Directory containing proof-unit YAML manifests (default: docs/status/proof_units)",
    )
    p.add_argument(
        "--impact-of",
        dest="impact_of",
        nargs="+",
        metavar="CLAIM_ID",
        default=None,
        help="Show units impacted by these claim IDs",
    )
    p.add_argument(
        "--multi-hop",
        dest="multi_hop",
        action="store_true",
        default=False,
        help="Include transitively impacted units via dependency edges",
    )
    p.add_argument(
        "--json",
        dest="json",
        action="store_true",
        default=False,
        help="Emit JSON output",
    )
    p.set_defaults(func=_lazy("aragora.cli.commands.dic19_proof_units", "cmd_proof_units"))


def _add_genealogy_parser(subparsers) -> None:
    """Add the 'genealogy' subcommand group (DIC-24 / #6218).

    Flag-gated: ARAGORA_GENEALOGY_ENABLED must be set.
    Live queue effect: none (read-only operator report).
    """
    gp = subparsers.add_parser(
        "genealogy",
        help="DIC-24: inspect epistemic genealogy ledger for proof-carrying code units",
        description=(
            "Read-only operator surface for the epistemic genealogy ledger. "
            "Requires ARAGORA_GENEALOGY_ENABLED=1."
        ),
    )
    gp_sub = gp.add_subparsers(dest="genealogy_cmd")
    show = gp_sub.add_parser("show", help="Show lineage for one proof-carrying code unit")
    show.add_argument("code_unit_id", help="The code_unit_id to look up")
    show.add_argument(
        "--store-file",
        dest="store_file",
        default=".aragora_genealogy.jsonl",
        help="Path to the genealogy JSONL store (default: .aragora_genealogy.jsonl)",
    )
    show.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    show.set_defaults(func=_lazy("aragora.cli.commands.dic24_genealogy", "cmd_genealogy_show"))


def _add_coherence_scan_parser(subparsers) -> None:
    """Add the 'coherence-scan' subcommand (DIC-26 / #6220).

    Flag-gated: ARAGORA_COHERENCE_MONITOR_ENABLED must be set.
    Live queue effect: none (read-only operator report).
    """
    p = subparsers.add_parser(
        "coherence-scan",
        help="DIC-26: scan a belief ledger for contradictions, evidence conflicts, and confidence rot",
        description=(
            "Read-only operator surface for the belief coherence monitor. "
            "Requires ARAGORA_COHERENCE_MONITOR_ENABLED=1."
        ),
    )
    p.add_argument(
        "--input",
        required=True,
        metavar="JSON",
        help="Path to a JSON file containing a list of BeliefEntry dicts",
    )
    p.add_argument(
        "--contradiction-gap",
        dest="contradiction_gap",
        type=float,
        default=0.5,
        metavar="FLOAT",
        help="Confidence gap threshold for contradiction detection (default: 0.5)",
    )
    p.add_argument(
        "--min-confidence",
        dest="min_confidence",
        type=float,
        default=0.3,
        metavar="FLOAT",
        help="Minimum confidence threshold for rot detection (default: 0.3)",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    p.set_defaults(func=_lazy("aragora.cli.commands.dic26_coherence", "cmd_coherence_scan"))


def _add_truth_map_parser(subparsers) -> None:
    """Add the 'truth-map' subcommand (DIC-18 / #6028).

    Flag-gated: ARAGORA_TRUTH_MAP_ENABLED must be set.
    Live queue effect: none (read-only operator report).
    """
    p = subparsers.add_parser(
        "truth-map",
        help="DIC-18: read-only organizational truth map of claim and crux status",
        description=(
            "Reads DIC-13 claim manifests, verifies them (dry-run), and emits "
            "a read-only report of claim and crux health. "
            "Requires ARAGORA_TRUTH_MAP_ENABLED=1."
        ),
    )
    p.add_argument(
        "--claims-dir",
        dest="claims_dir",
        default="docs/status/claims",
        metavar="PATH",
        help="Directory of *.yaml claim manifests (default: docs/status/claims)",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    p.set_defaults(func=_lazy("aragora.cli.commands.dic18_truth_map", "cmd_truth_map"))


def _add_decay_monitor_parser(subparsers) -> None:
    """Add the 'decay-monitor' subcommand (DIC-20 / #6031).

    Flag-gated: ARAGORA_DECAY_MONITOR_ENABLED must be set.
    Live queue effect: none (read-only operator report).
    """
    p = subparsers.add_parser(
        "decay-monitor",
        help="DIC-20: report epistemic decay for proof-carrying code units",
        description=(
            "Read-only decay assessment over proof-carrying code units. "
            "Requires ARAGORA_DECAY_MONITOR_ENABLED=1."
        ),
    )
    p.add_argument(
        "--units-dir",
        dest="units_dir",
        default=".aragora_proof_units",
        metavar="DIR",
        help="Directory of proof-unit YAML manifests (default: .aragora_proof_units)",
    )
    p.add_argument(
        "--claim-results",
        dest="claim_results",
        default=None,
        metavar="JSONL",
        help="Optional JSONL/JSON file of ClaimResult dicts (DIC-14 verifier output)",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    p.set_defaults(func=_lazy("aragora.cli.commands.dic20_decay_monitor", "cmd_decay_monitor"))


def _add_crux_arbitrate_parser(subparsers) -> None:
    """Add the 'crux-arbitrate' subcommand for DIC-27 operator arbitration."""
    p = subparsers.add_parser(
        "crux-arbitrate",
        help="DIC-27: resolve persistent cruxes as reversible signed arbitration receipts",
        description=(
            "Load a JSON file of PersistentCrux records and either inspect "
            "which ones qualify for arbitration (--dry-run) or create a signed "
            "CruxArbitration record (requires ARAGORA_CRUX_ARBITRATION_ENABLED=1)."
        ),
    )
    p.add_argument(
        "--input",
        required=True,
        metavar="JSON",
        help="Path to a JSON file containing a PersistentCrux or list of PersistentCrux dicts",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List qualifying/non-qualifying cruxes without creating an arbitration record",
    )
    p.add_argument(
        "--crux-id",
        metavar="ID",
        help="ID of the crux to arbitrate (required in live mode)",
    )
    p.add_argument(
        "--side",
        choices=["accept", "reject", "defer", "split"],
        help="Operator's chosen side (required in live mode)",
    )
    p.add_argument(
        "--rationale",
        metavar="TEXT",
        help="Short operator rationale for the decision (required in live mode)",
    )
    p.add_argument(
        "--operator",
        default="operator",
        metavar="NAME",
        help="Operator identifier recorded in the arbitration (default: 'operator')",
    )
    p.add_argument(
        "--expires-days",
        type=int,
        default=90,
        metavar="N",
        help="Days until this arbitration expires (default: 90)",
    )
    p.add_argument(
        "--evidence",
        nargs="*",
        metavar="CITATION",
        help="Optional evidence citations (URLs, doc paths) to attach to the arbitration",
    )
    p.add_argument(
        "--output",
        metavar="PATH",
        help="Write the arbitration JSON to this file in addition to stdout",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit output as JSON instead of human-readable text",
    )
    p.set_defaults(func=_lazy("aragora.cli.commands.crux_arbitrate", "cmd_crux_arbitrate"))


def _add_crux_garden_parser(subparsers) -> None:
    """DIC-28: proactive crux gardening operator surface (issue #6222).

    Flag-gated: ARAGORA_CRUX_GARDENING_ENABLED. Live queue effect: none.
    """
    p = subparsers.add_parser(
        "crux-garden",
        help="DIC-28: proactive re-examination of cruxes for staleness and contradictions",
        description=(
            "Load a JSONL or JSON-array of CruxReceipt dicts and run a gardening pass. "
            "Report-only; no debates started, no issues created. "
            "Requires ARAGORA_CRUX_GARDENING_ENABLED=1."
        ),
    )
    p.add_argument(
        "--input",
        required=True,
        help="Path to a JSONL or JSON-array file of CruxReceipt dicts.",
    )
    p.add_argument("--json", action="store_true", help="Emit report as JSON.")
    p.set_defaults(func=_lazy("aragora.cli.commands.dic28_crux_garden", "cmd_crux_garden"))


def _add_epistemic_check_parser(subparsers) -> None:
    """Add the 'epistemic-check' subcommand for DIC-14 claim verification."""
    p = subparsers.add_parser(
        "epistemic-check",
        help="DIC-14: verify executable claim manifests and emit a status report",
        description=(
            "Load *.yaml claim manifests from docs/status/claims/ (or a path you\n"
            "supply) and verify each claim via the DIC-14 ClaimVerifier.  Outputs\n"
            "a human-readable table or JSON.  No queue mutation, no issue creation.\n\n"
            "Read-only by default: manifest-provided verification commands are NOT\n"
            "executed unless you pass --execute (command-kind claims are reported\n"
            "UNSUPPORTED). Only pass --execute for manifests you trust.\n\n"
            "Requires ARAGORA_EPISTEMIC_CLAIMS_ENABLED=1 to execute; otherwise exits\n"
            "0 with an informational message."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "path",
        nargs="?",
        default=None,
        metavar="PATH",
        help=("YAML manifest file or directory of manifests. Defaults to docs/status/claims/"),
    )
    p.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit machine-readable JSON (schema_version, results, summary)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help=(
            "Skip command execution; return UNSUPPORTED for command-kind claims. "
            "This is already the DEFAULT behavior — the flag is accepted for "
            "explicitness and backward compatibility."
        ),
    )
    p.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help=(
            "Opt in to running manifest-provided verification commands as "
            "subprocesses. Off by default: command-kind claims are skipped "
            "(reported UNSUPPORTED) unless this flag is set. Only pass --execute "
            "for manifests you trust, since commands run with your shell privileges."
        ),
    )
    p.add_argument(
        "--repo-root",
        default=None,
        metavar="DIR",
        help="Repository root for resolving relative evidence paths (defaults to cwd)",
    )
    p.set_defaults(func=_lazy("aragora.cli.commands.epistemic_check", "cmd_epistemic_check"))


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
        "--compare-against",
        action="append",
        default=[],
        help=(
            "Additional comma-separated agent/model combinations to run against the same task. "
            "The baseline combo is --agents, and Aragora will score each run and pick the best "
            "result automatically. Repeatable. Local standard debates only."
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
        "--demo", action="store_true", help="Run with built-in demo agents (no API keys required)"
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
        default=None,
        help=f"API server URL (default: {DEFAULT_API_URL}); passing the flag "
        "explicitly opts in to that server even if it does not identify as Aragora",
    )
    ask_parser.add_argument(
        "--api-key",
        default=None if DEFAULT_API_KEY is None else DEFAULT_API_KEY,
        help="API key for server authentication (default: ARAGORA_API_KEY)",
    )
    debate_type = ask_parser.add_mutually_exclusive_group()
    debate_type.add_argument(
        "--graph", action="store_true", help="Run a graph debate with branching (API mode only)"
    )
    debate_type.add_argument(
        "--matrix", action="store_true", help="Run a matrix debate with scenarios (API mode only)"
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
        "--crux-cards",
        action="store_true",
        help="Attach crux cards (load-bearing disagreements) to the receipt; local-only",
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
        "status", help="Show environment health, agent availability, or founder ops status"
    )
    from aragora.cli.commands.founder_status import add_founder_status_arguments

    add_founder_status_arguments(status_parser, default_api_url=DEFAULT_API_URL)
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
    demo_parser.add_argument(
        "--offline",
        action="store_true",
        help="Force offline mode with mock agents (no API keys used)",
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
        "validate",
        help="Run a full health check, including live API-key validation",
        description=(
            "Run Aragora's health check (Environment, Packages, API Keys, "
            "Storage, and Server sections) with live API-key validation enabled. "
            "Configured provider keys are probed against the provider where "
            "possible; a key that cannot be verified is reported as present but "
            "unverified rather than as a passing check. Exits 0 only when all "
            "checks pass."
        ),
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
    validate_env_parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run a tiny live provider answer smoke test for selected agents",
    )
    validate_env_parser.add_argument(
        "--agents",
        default="",
        help="Comma-separated agents to smoke-test, for example: gemini,grok",
    )
    validate_env_parser.add_argument(
        "--smoke-timeout",
        type=float,
        default=20.0,
        help="Per-agent smoke-test timeout in seconds",
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


def _add_api_key_parser(subparsers) -> None:
    """Add the `api-key` subcommand parser."""
    api_key_parser = subparsers.add_parser(
        "api-key",
        help="Manage LLM API keys",
        description="Securely store, inspect, and validate LLM API keys.",
    )
    api_key_parser.set_defaults(func=_lazy("aragora.cli.commands.api_key", "cmd_api_key"))

    api_key_subparsers = api_key_parser.add_subparsers(dest="api_key_command")

    set_parser = api_key_subparsers.add_parser("set", help="Store an LLM API key securely")
    set_parser.add_argument("provider", help="Provider name (for example: openai, anthropic)")
    set_parser.add_argument(
        "key",
        nargs="?",
        help="API key value (omit to enter it securely via a hidden prompt)",
    )

    api_key_subparsers.add_parser("list", help="List configured LLM API keys")

    validate_parser = api_key_subparsers.add_parser(
        "validate", help="Validate a configured provider key"
    )
    validate_parser.add_argument("provider", help="Provider name to validate")


def _add_secrets_parser(subparsers) -> None:
    """Add the `secrets` subcommand parser."""
    secrets_parser = subparsers.add_parser(
        "secrets",
        help="Inspect AWS Secrets Manager-backed secret presence",
        description="Presence-only secret health checks and process bootstrap helpers.",
    )
    secrets_parser.set_defaults(
        func=_lazy("aragora.cli.commands.secrets", "cmd_secrets"),
        parser=secrets_parser,
    )
    secrets_subparsers = secrets_parser.add_subparsers(dest="secrets_command")

    health_parser = secrets_subparsers.add_parser(
        "health",
        help="Report secret source status without printing values",
    )
    health_parser.add_argument(
        "--name",
        action="append",
        help="Secret name to check; repeat for multiple names",
    )
    health_parser.add_argument(
        "--require-all",
        action="store_true",
        help="Exit non-zero when any requested secret is missing or strict-blocked",
    )
    health_parser.add_argument("--json", action="store_true", help="Emit JSON output")
    health_parser.set_defaults(func=_lazy("aragora.cli.commands.secrets", "cmd_secrets_health"))

    hydrate_parser = secrets_subparsers.add_parser(
        "hydrate",
        help="Hydrate this process env from Secrets Manager and report key names only",
    )
    hydrate_parser.add_argument(
        "--name",
        action="append",
        help="Secret name to hydrate; repeat for multiple names",
    )
    hydrate_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing environment values in this process",
    )
    hydrate_parser.add_argument("--json", action="store_true", help="Emit JSON output")
    hydrate_parser.set_defaults(func=_lazy("aragora.cli.commands.secrets", "cmd_secrets_hydrate"))


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
        "--emit-odr",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help="Emit a verifiable Open Decision Receipt (default: review.odr.json, or inside "
        "--output-dir when set); place after the PR URL or pass a PATH; failed write exits 3",
    )
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
        help="CI mode: exit code by findings severity (1=critical, 2=high; 3=ODR write failure).",
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


def _add_review_pr_parser(subparsers) -> None:
    """Add the PR review/fix loop parser without importing its heavy runtime."""
    parser = subparsers.add_parser(
        "review-pr",
        help="Review a live GitHub PR head and optionally run a fixer loop",
        description=(
            "Fetch the current remote PR head, run a reviewer against that truth source, "
            "persist structured findings, and optionally dispatch a fixer in a detached worktree."
        ),
    )
    parser.add_argument("pr", help="PR number or GitHub PR URL")
    parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repo slug override (owner/name). Defaults to the current repo context.",
    )
    parser.add_argument(
        "--reviewer",
        default="claude",
        help="Preferred review model/provider (default: claude)",
    )
    parser.add_argument(
        "--fixer",
        default=None,
        help="Optional fixer model/provider to run after blocking findings (for example: codex)",
    )
    parser.add_argument(
        "--auto-rerun",
        action="store_true",
        help="Re-review the PR head automatically after a successful fixer push",
    )
    parser.add_argument(
        "--artifact-dir",
        default=None,
        help="Directory for run artifacts (default: .aragora/review-pr under repo root)",
    )
    parser.add_argument(
        "--keep-worktree",
        action="store_true",
        help="Keep the detached fixer worktree instead of removing it after the run",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Print the final run summary as JSON",
    )
    parser.add_argument(
        "--no-publish-review",
        dest="publish_review",
        action="store_false",
        help="Persist artifacts without posting any GitHub review output.",
    )
    parser.set_defaults(publish_review=True)
    parser.set_defaults(func=_lazy("aragora.cli.commands.review_pr", "cmd_review_pr"))

    # Audit command (compliance audit logs)
    from aragora.cli.audit import create_audit_parser

    create_audit_parser(subparsers)

    # Document audit command (document analysis)
    from aragora.cli.document_audit import create_document_audit_parser

    create_document_audit_parser(subparsers)


def _add_review_local_parser(subparsers) -> None:
    """Register the offline local-diff review parser without heavy imports."""
    parser = subparsers.add_parser(
        "review-local",
        help="Run a non-OpenAI (Claude Max pool) review on a LOCAL diff, no GitHub required",
        description=(
            "Read a local diff (file or stdin), route it to a non-worker reviewer family "
            "(default: claude via the Max profile pool), and write a review receipt. Works "
            "fully offline so OpenAI/codex sessions can attach a heterogeneous, non-OpenAI "
            "verdict even when GitHub is degraded."
        ),
    )
    parser.add_argument(
        "--diff",
        default="-",
        help="Path to a unified diff, or - to read from stdin (default: -)",
    )
    parser.add_argument(
        "--spec",
        default=None,
        help="Optional path to spec/context text to include in the review prompt",
    )
    parser.add_argument("--title", default=None, help="Optional short title for the change")
    parser.add_argument(
        "--worker-model",
        dest="worker_model",
        default="codex",
        help="Model family that produced the change (excluded from review; default: codex)",
    )
    parser.add_argument(
        "--review-model",
        "--reviewer",
        dest="reviewer",
        default="claude",
        help="Preferred non-worker review family (default: claude)",
    )
    parser.add_argument(
        "--artifact-dir",
        default=None,
        help="Directory for run artifacts (default: .aragora/review-local under repo root)",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Print the review result as JSON",
    )
    parser.set_defaults(func=_lazy("aragora.cli.commands.review_pr", "cmd_review_local"))


def _add_review_queue_parser(subparsers) -> None:
    """Register review-queue lazily so unrelated CLI paths stay lightweight."""
    parser = subparsers.add_parser(
        "review-queue",
        help="PR review queue + advisory packets + human settlement",
        description=(
            "Build a prioritized queue of open PRs, generate an advisory packet, "
            "or record an explicit human settlement action."
        ),
    )
    queue_subparsers = parser.add_subparsers(dest="review_queue_command")

    build_parser = queue_subparsers.add_parser(
        "build",
        help="Build prioritized review queue from open PRs",
    )
    build_parser.add_argument("--limit", type=int, default=100, help="Max PRs to fetch")
    build_parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repo slug override (owner/name). Defaults to current repo context.",
    )
    build_parser.add_argument(
        "--ready-only",
        action="store_true",
        help="Show only ready_now lane",
    )
    build_parser.add_argument(
        "--include-parked",
        action="store_true",
        help="Include parked lane",
    )
    build_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output as JSON",
    )
    build_parser.set_defaults(func=_lazy("aragora.cli.commands.review_queue", "cmd_review_queue"))

    packet_parser = queue_subparsers.add_parser(
        "packet",
        help="Generate advisory review packet for one PR",
    )
    packet_parser.add_argument("pr", help="PR number")
    packet_parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repo slug override (owner/name). Defaults to current repo context.",
    )
    packet_parser.add_argument(
        "--execute-reviewers",
        action="store_true",
        help="Attempt one bounded live heterogeneous reviewer pass.",
    )
    packet_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output as JSON",
    )
    packet_parser.set_defaults(func=_lazy("aragora.cli.commands.review_queue", "cmd_review_queue"))

    run_parser = queue_subparsers.add_parser(
        "run",
        help="Interactively settle a prioritized PR queue",
    )
    run_parser.add_argument("--limit", type=int, default=30, help="Max PRs to walk")
    run_parser.add_argument(
        "--ready-only",
        action="store_true",
        help="Restrict the session to ready_now items",
    )
    run_parser.add_argument(
        "--include-parked",
        action="store_true",
        help="Include parked items in the session",
    )
    run_parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repo slug override (owner/name). Defaults to current repo context.",
    )
    run_parser.set_defaults(func=_lazy("aragora.cli.commands.review_queue", "cmd_review_queue"))

    act_parser = queue_subparsers.add_parser(
        "act",
        help="Settle one PR with a human action",
    )
    act_parser.add_argument("pr", help="PR number")
    act_parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repo slug override (owner/name). Defaults to current repo context.",
    )
    action_group = act_parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument("--approve", action="store_true", help="Post a human APPROVE review")
    action_group.add_argument(
        "--request-changes",
        action="store_true",
        help="Post a human REQUEST_CHANGES review",
    )
    action_group.add_argument("--defer", action="store_true", help="Leave a human defer comment")
    act_parser.add_argument("--reason", default="", help="One-line human reason")
    act_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output settlement receipt as JSON",
    )
    act_parser.set_defaults(func=_lazy("aragora.cli.commands.review_queue", "cmd_review_queue"))

    # Route through the shared registration helper (argparse-only import) so
    # this surface and the standalone review-queue CLI cannot drift apart:
    # an inline copy here repeatedly lost flags the helper registers (e.g.
    # --post-github-status), leaving documented commands unexecutable.
    from aragora.cli.commands.review_queue_parsers import add_record_settlement_parser

    add_record_settlement_parser(queue_subparsers)
    queue_subparsers.choices["record-settlement"].set_defaults(
        func=_lazy("aragora.cli.commands.review_queue", "cmd_review_queue")
    )

    evidence_lint_parser = queue_subparsers.add_parser(
        "evidence-lint",
        help="Dry-run whether a proposed evidence comment will count for model quorum",
        description=(
            "Lint a proposed PR comment against the same current-head evidence "
            "parsers used by review-queue merge-packet. This is read-only."
        ),
    )
    evidence_lint_parser.add_argument("--pr", required=True, help="PR number the evidence targets")
    evidence_lint_parser.add_argument(
        "--head-sha",
        required=True,
        help="Exact PR head SHA the proposed comment must cite.",
    )
    evidence_lint_parser.add_argument(
        "--head-committed-at",
        default="",
        help="Optional current head committedDate for stricter current-head grounding.",
    )
    body_group = evidence_lint_parser.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body", help="Proposed evidence comment body to lint")
    body_group.add_argument("--body-file", help="Read proposed evidence comment body from file")
    evidence_lint_parser.add_argument(
        "--author",
        default="local",
        help="GitHub author login to simulate for the proposed comment.",
    )
    evidence_lint_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output as JSON",
    )
    evidence_lint_parser.set_defaults(
        func=_lazy("aragora.cli.commands.review_queue", "cmd_review_queue")
    )

    collect_evidence_parser = queue_subparsers.add_parser(
        "collect-evidence",
        help="Run genuine model reviewers, lint their evidence, post only if tier allows",
        description=(
            "Run >=2 genuine heterogeneous model reviewers against a PR's exact head, "
            "compose evidence comments the quorum parsers recognize, and validate each "
            "with evidence-lint before posting. Only Tier 0-2 PRs auto-post (with "
            "--apply); Tier 3-4 always prepare evidence for operator settlement. "
            "Defaults to a dry run that posts nothing."
        ),
    )
    collect_evidence_parser.add_argument(
        "--pr", required=True, type=int, help="PR number to collect evidence for"
    )
    collect_evidence_parser.add_argument(
        "--repo", default="", help="owner/name of the target repo (default: current gh context)"
    )
    collect_evidence_parser.add_argument(
        "--reviewers",
        nargs="+",
        default=None,
        help="reviewer model families to run (default: claude grok)",
    )
    collect_evidence_parser.add_argument(
        "--author",
        default=None,
        help="GitHub login to simulate for evidence-lint (default: gh authenticated user)",
    )
    collect_evidence_parser.add_argument(
        "--apply",
        action="store_true",
        help="Post evidence for Tier 0-2 PRs (Tier 3-4 always prepare-only).",
    )
    collect_evidence_parser.add_argument(
        "--reviewer-timeout",
        dest="reviewer_timeout",
        type=float,
        default=None,
        help="Per-reviewer timeout in seconds for this invocation.",
    )
    collect_evidence_parser.add_argument(
        "--overall-timeout",
        dest="overall_timeout",
        type=float,
        default=None,
        help="Overall reviewer orchestration timeout in seconds for this invocation.",
    )
    collect_evidence_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
    )
    collect_evidence_parser.set_defaults(
        func=_lazy("aragora.cli.commands.review_queue", "cmd_review_queue")
    )

    lint_comment_parser = queue_subparsers.add_parser(
        "lint-comment",
        help="Dry-run whether a proposed reviewer comment will count before posting",
        description=(
            "Lint a proposed PR reviewer comment against the same current-head evidence "
            "parsers used by review-queue merge-packet. This is read-only."
        ),
    )
    lint_comment_parser.add_argument("--pr", required=True, help="PR number the comment targets")
    lint_comment_parser.add_argument(
        "--head",
        "--head-sha",
        dest="head_sha",
        required=True,
        help="Exact PR head SHA the proposed comment must cite.",
    )
    lint_comment_parser.add_argument(
        "--head-committed-at",
        default="",
        help="Optional current head committedDate for stricter current-head grounding.",
    )
    lint_body_group = lint_comment_parser.add_mutually_exclusive_group(required=True)
    lint_body_group.add_argument("--body", help="Proposed reviewer comment body to lint")
    lint_body_group.add_argument(
        "--body-file",
        help="Read proposed reviewer comment body from file",
    )
    lint_comment_parser.add_argument(
        "--author",
        default="local",
        help="GitHub author login to simulate for the proposed comment.",
    )
    lint_comment_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output as JSON",
    )
    lint_comment_parser.set_defaults(
        func=_lazy("aragora.cli.commands.review_queue", "cmd_review_queue")
    )

    baseline_parser = queue_subparsers.add_parser(
        "baseline",
        help="Measure empirical invalidation baseline from on-disk stores (#6375)",
        description=(
            "Read the auto-handle calibration store and settlement receipts, "
            "compute the empirical invalidation baseline, and propose an "
            "auto-handle invalidation threshold. This command is read-only."
        ),
    )
    baseline_parser.add_argument(
        "--window-days",
        type=int,
        default=30,
        help="Measurement-window width in days (default: 30).",
    )
    baseline_parser.add_argument(
        "--min-samples",
        type=int,
        default=50,
        help="Minimum human-settled sample size before using the measured baseline.",
    )
    baseline_parser.add_argument(
        "--safety-margin",
        type=float,
        default=0.5,
        help="Multiplier applied to the baseline when deriving the threshold.",
    )
    baseline_parser.add_argument(
        "--minimum-meaningful-rate",
        type=float,
        default=0.01,
        help="Floor below which threshold drift is indistinguishable from sample noise.",
    )
    baseline_parser.add_argument(
        "--placeholder-value",
        type=float,
        default=0.05,
        help="Threshold to use below the sample-size floor (default: 0.05).",
    )
    baseline_parser.add_argument(
        "--calibration-db",
        default=None,
        help="Override the auto-handle calibration store path.",
    )
    baseline_parser.add_argument(
        "--review-queue-root",
        default=None,
        help="Override the review-queue root used for settlement receipts.",
    )
    baseline_parser.add_argument(
        "--json",
        action="store_true",
        help="Output the BaselineMeasurement + ThresholdProposal as JSON.",
    )
    baseline_parser.set_defaults(
        func=_lazy("aragora.cli.commands.review_queue", "cmd_review_queue")
    )

    merge_packet_parser = queue_subparsers.add_parser(
        "merge-packet",
        help="Print a model-quorum merge authorization packet for a PR batch",
    )
    merge_packet_parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Max open PRs to inspect when --pr is not supplied",
    )
    merge_packet_parser.add_argument(
        "--pr",
        action="append",
        default=[],
        help="Specific PR number/ref to include. Repeatable. Defaults to open queue.",
    )
    merge_packet_parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repo slug override (owner/name). Defaults to current repo context.",
    )
    merge_packet_parser.add_argument(
        "--review-queue-root",
        default=None,
        help="Override the review-queue store root used for settlement receipt lookups.",
    )
    merge_packet_parser.add_argument(
        "--execute-reviewers",
        action="store_true",
        help="Attempt live heterogeneous reviewer execution for each packet.",
    )
    merge_packet_parser.add_argument(
        "--ignore-own-quorum-check",
        action="store_true",
        help=(
            "Diagnostic only: exclude the aragora-merge-quorum check (any state) from "
            "the packet's check gating so out-of-CI callers can observe the real "
            "model-quorum state instead of short-circuiting on a stale self-failure. "
            "The enforcing CI gate never sets this; it does not weaken the gate."
        ),
    )
    merge_packet_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output as JSON",
    )
    merge_packet_parser.set_defaults(
        func=_lazy("aragora.cli.commands.review_queue", "cmd_review_queue")
    )

    conductor_parser = queue_subparsers.add_parser(
        "conductor",
        help="Build an owner-aware queue conductor packet and next prompt",
        description=(
            "Read-only queue conductor that combines open PR metadata, required checks, "
            "branch owner lookup, operator steering, merge-packet status, head-change "
            "detection, and supersession hints into one JSON packet plus one next prompt."
        ),
    )
    conductor_parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Max open PRs to inspect when --pr is not supplied",
    )
    conductor_parser.add_argument(
        "--pr",
        action="append",
        default=[],
        help="Specific PR number/ref to include. Repeatable. Defaults to open queue.",
    )
    conductor_parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repo slug override (owner/name). Defaults to current repo context.",
    )
    conductor_parser.add_argument(
        "--review-queue-root",
        default=None,
        help="Override the review-queue store root used for settlement receipt lookups.",
    )
    conductor_parser.add_argument(
        "--owner-timeout-seconds",
        type=float,
        default=8.0,
        help="Timeout for owner and steering helper lookup. Timeout means preserve/no-mutate.",
    )
    conductor_parser.add_argument(
        "--mode",
        choices=("queue", "ready-boundary"),
        default="queue",
        help=(
            "Conductor routing mode. ready-boundary emits mark-ready authorization "
            "classification for draft PRs that are otherwise ready."
        ),
    )
    conductor_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output as JSON",
    )
    conductor_parser.set_defaults(
        func=_lazy("aragora.cli.commands.review_queue", "cmd_review_queue")
    )

    # Round 30g phase A: observe-outcomes (dry-run-by-default; --write opt-in).
    observe_parser = queue_subparsers.add_parser(
        "observe-outcomes",
        help=(
            "Observe post-settlement invalidation signals from GitHub timeline "
            "events and (optionally) write them back into receipt v2 outcome "
            "fields. Dry-run by default."
        ),
        description=(
            "Round 30g phase A. Iterates settled receipts in a bounded window, "
            "fetches GitHub timeline events with bounded fanout, and computes "
            "the canonical v2 outcome signals via "
            "aragora.review.settlement_outcome.observe_outcome. Default mode is "
            "read-only; --write opts in to in-place mutation of receipt JSON. "
            "Scope: this command observes outcomes; it does NOT close #6375, "
            "does NOT replace the placeholder 5% threshold, and does NOT "
            "unblock H2. Operator caution: --write mutates audit-record receipt "
            "JSON in place; do not run this in unattended CI loops."
        ),
    )
    observe_parser.add_argument(
        "--window-days",
        type=int,
        default=14,
        help="Observation window in days (default: 14).",
    )
    observe_parser.add_argument(
        "--max-receipts",
        type=int,
        default=20,
        help="Max receipts to inspect (default: 20). Bounds the GitHub fanout.",
    )
    observe_parser.add_argument(
        "--per-receipt-event-cap",
        type=int,
        default=100,
        help="Max timeline events per receipt (default: 100).",
    )
    observe_parser.add_argument(
        "--review-queue-root",
        default=None,
        help="Override the review-queue store root for settlement receipts.",
    )
    observe_parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "OPT-IN: actually write v2 outcome fields back into audit-record "
            "receipt JSON in place. Default is dry-run preview only. Do not "
            "run this in unattended CI loops; treat each --write invocation as "
            "a discrete operator decision."
        ),
    )
    observe_parser.add_argument(
        "--json",
        action="store_true",
        help="Output the run summary as JSON.",
    )
    observe_parser.set_defaults(func=_lazy("aragora.cli.commands.review_queue", "cmd_review_queue"))

    # Operational health surface — read-only, network-free.
    health_parser = queue_subparsers.add_parser(
        "health",
        help="Report freshness across review-queue + proof-loop write surfaces",
        description=(
            "Read-only, network-free check of the write-side daemons that close the "
            "proof loop: settlement receipts, briefs, boss-metrics ledger, automation "
            "receipts, boss-loop log, watchdog log, B0 publication, and TW-03 rescue "
            "ledger. Exits 1 if any surface is stale or missing. Designed to surface "
            "silent failures within seconds, not 13 days."
        ),
    )
    health_parser.add_argument(
        "--repo-root",
        default=None,
        help="Override repo root used for status doc + overnight lookups.",
    )
    health_parser.add_argument(
        "--review-queue-root",
        default=None,
        help="Override the review-queue store root.",
    )
    health_parser.add_argument(
        "--overnight-root",
        default=None,
        help="Override the .aragora/overnight directory.",
    )
    health_parser.add_argument(
        "--automation-receipts-root",
        default=None,
        help="Override the .aragora/automation-receipts directory.",
    )
    health_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output the report as JSON.",
    )
    health_parser.set_defaults(func=_lazy("aragora.cli.commands.review_queue", "cmd_review_queue"))

    # Edge-triggered alerter that runs the health check, records state, and
    # writes one JSON event whenever the set of stale/missing surfaces changes.
    # Designed for periodic launchd execution.
    alert_parser = queue_subparsers.add_parser(
        "health-alert",
        help="Edge-triggered alerter: writes an event when proof-loop health changes state",
        description=(
            "Runs the same checks as 'review-queue health', persists state under "
            ".aragora/proof-loop-alerts/, and writes one JSON event per state "
            "transition (opens, set-change, recovers). Designed to be invoked on "
            "a schedule (e.g. launchd every 15 minutes) without producing repeat "
            "alerts while a surface stays stale. Exits 1 if any surface is "
            "currently stale or missing so launchd can surface failure."
        ),
    )
    alert_parser.add_argument(
        "--repo-root",
        default=None,
        help="Override repo root used for status doc + overnight + state lookups.",
    )
    alert_parser.add_argument(
        "--review-queue-root",
        default=None,
        help="Override the review-queue store root.",
    )
    alert_parser.add_argument(
        "--overnight-root",
        default=None,
        help="Override the .aragora/overnight directory.",
    )
    alert_parser.add_argument(
        "--automation-receipts-root",
        default=None,
        help="Override the .aragora/automation-receipts directory.",
    )
    alert_parser.add_argument(
        "--state-dir",
        default=None,
        help="Override the alert state directory (default: <repo>/.aragora/proof-loop-alerts).",
    )
    alert_parser.add_argument(
        "--heartbeat",
        action="store_true",
        help="Emit a heartbeat event even when state is unchanged (useful for liveness checks).",
    )
    alert_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output the result as JSON (kind, paths, alerting surfaces).",
    )
    alert_parser.set_defaults(func=_lazy("aragora.cli.commands.review_queue", "cmd_review_queue"))


def _add_codebase_audit_parser(subparsers) -> None:
    """Add the staged repository codebase audit parser."""
    parser = subparsers.add_parser(
        "codebase-audit",
        help="Run a staged repo audit with triage, threat-surface ranking, and deep audit",
        description=(
            "Run a deterministic staged repo audit that first filters bespoke code, "
            "then ranks trust boundaries, then optionally runs Deep Audit against the "
            "highest-risk files."
        ),
    )
    parser.add_argument(
        "repo",
        nargs="?",
        default=".",
        help="Repository root to audit (default: current directory)",
    )
    parser.add_argument(
        "--agents",
        default=DEFAULT_AGENTS,
        help=f"Comma-separated deep-audit agents (default: {DEFAULT_AGENTS})",
    )
    parser.add_argument(
        "--top-files",
        type=int,
        default=12,
        help="Number of highest-risk files to rank and carry into deep audit (default: 12)",
    )
    parser.add_argument(
        "--max-dirs",
        type=int,
        default=25,
        help="Max directories to include in the triage map (default: 25)",
    )
    parser.add_argument(
        "--max-preview-chars",
        type=int,
        default=4000,
        help="Max characters per file preview in the threat-surface stage (default: 4000)",
    )
    parser.add_argument(
        "--max-file-chars",
        type=int,
        default=12000,
        help="Max characters per file forwarded into deep audit context (default: 12000)",
    )
    parser.add_argument(
        "--artifact-dir",
        default=None,
        help="Directory for audit artifacts (default: .aragora/codebase-audit/<timestamp>)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the LLM deep-audit stage and only emit staged artifacts",
    )
    parser.add_argument(
        "--disable-research",
        action="store_true",
        help="Disable Deep Audit web research and use only the selected audit agents",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the final run summary as JSON",
    )
    parser.set_defaults(func=_lazy("aragora.cli.commands.codebase_audit", "cmd_codebase_audit"))

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
        "--spec",
        help="Spec JSON file (from 'aragora spec --output'). Skips debate; creates plan directly from spec.",
    )
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
    aragora agent run devops --repo synaptent/aragora --task health-check
    aragora agent run devops --repo synaptent/aragora --task review-prs --dry-run
    aragora agent run devops --repo synaptent/aragora --mode watch
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


def _add_triage_parser(subparsers) -> None:
    """Add the 'triage' subcommand for inbox trust wedge."""
    from aragora.cli.commands.triage import add_triage_parser

    add_triage_parser(subparsers)


def _add_codex_parser(subparsers) -> None:
    """Add the 'codex' read-only inspector commands for Codex Desktop state."""

    def parent_help(p: argparse.ArgumentParser):
        def _cmd_parent_help(_args):
            p.print_help()
            return 2

        return _cmd_parent_help

    codex = subparsers.add_parser(
        "codex",
        help="Read-only inspector for Codex Desktop local state",
        description=(
            "Surface Codex Desktop sessions/threads from ~/.codex/ as redacted, "
            "read-only data. Never writes to ~/.codex/ and consumes no AI "
            "provider keys. The sessions brief command may query GitHub/repo "
            "state for queue context unless --repo-root '' disables it."
        ),
    )
    codex.set_defaults(func=parent_help(codex))
    codex_sub = codex.add_subparsers(dest="codex_cmd")

    sessions = codex_sub.add_parser(
        "sessions",
        help="Inspect Codex Desktop sessions/threads",
        description="List, brief, summarize, or tail Codex Desktop sessions (read-only).",
    )
    sessions.set_defaults(func=parent_help(sessions))
    sessions_sub = sessions.add_subparsers(dest="codex_sessions_cmd")

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--codex-home",
            default=None,
            help="Override Codex Desktop home dir (default: $ARAGORA_CODEX_HOME or ~/.codex)",
        )
        p.add_argument("--json", action="store_true", help="Emit JSON instead of a table")

    list_cmd = sessions_sub.add_parser("list", help="List threads updated within --since window")
    add_common(list_cmd)
    list_cmd.add_argument(
        "--since",
        default="4h",
        help="Time window (e.g. 30m, 4h, 1d, 90s). Default: 4h.",
    )
    list_cmd.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived threads (default: exclude)",
    )
    list_cmd.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of threads to return (default: 50, 0 = no limit)",
    )
    list_cmd.set_defaults(
        func=_lazy("aragora.cli.commands.codex_sessions", "cmd_codex_sessions_list")
    )

    brief_cmd = sessions_sub.add_parser(
        "brief",
        help="Brief recent sessions and route conservative next prompts",
        description=(
            "Build redacted Codex Desktop session briefings from local JSONL/session "
            "metadata, then classify each session into pause/watch/review/settle/"
            "repair/paste-needed. Raw transcript text is not emitted."
        ),
    )
    add_common(brief_cmd)
    brief_cmd.add_argument(
        "--since",
        default="4h",
        help="Time window (e.g. 30m, 4h, 1d, 90s). Default: 4h.",
    )
    brief_cmd.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived threads (default: exclude)",
    )
    brief_cmd.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of threads to brief (default: 50, 0 = no limit)",
    )
    brief_cmd.add_argument(
        "--include-last-turns",
        type=int,
        default=0,
        help="Include this many recent safe turn summaries, never raw transcript text.",
    )
    brief_cmd.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact prompt-router rows instead of full briefing objects.",
    )
    brief_cmd.add_argument(
        "--awaiting-prompts",
        action="store_true",
        help="Return only sessions whose redacted signal suggests an operator prompt is needed.",
    )
    brief_cmd.add_argument(
        "--group-by",
        choices=("cwd", "branch", "title"),
        default=None,
        help="Group returned session ids by cwd, branch, or title.",
    )
    brief_cmd.add_argument(
        "--session",
        default=None,
        help="Restrict to one thread id or id prefix; returns paste-needed if invisible.",
    )
    brief_cmd.add_argument(
        "--repo-root",
        default=".",
        help="Repo root used for queue/lane context (default: current directory; '' disables).",
    )
    brief_cmd.set_defaults(
        func=_lazy("aragora.cli.commands.codex_sessions", "cmd_codex_sessions_brief")
    )

    show_cmd = sessions_sub.add_parser(
        "show",
        help="Summarize one session by thread id (or 8+ char prefix) or rollout path",
    )
    add_common(show_cmd)
    show_cmd.add_argument(
        "target",
        help="Thread id, id prefix (>=8 chars), or path to a rollout JSONL file",
    )
    show_cmd.add_argument(
        "--full",
        action="store_true",
        help=(
            "Write the full redacted transcript. Default writes to a file under "
            ".aragora/codex_sessions/<id>.jsonl; use --out - to force stdout."
        ),
    )
    show_cmd.add_argument(
        "--out",
        default="",
        help=(
            "Output destination for --full. '-' for stdout, '' (default) for "
            ".aragora/codex_sessions/<id>.jsonl, or an explicit path outside "
            "the Codex Desktop home."
        ),
    )
    show_cmd.add_argument(
        "--max-events",
        type=int,
        default=2000,
        help="Max events to scan when summarizing (default: 2000; ignored when --full).",
    )
    show_cmd.set_defaults(
        func=_lazy("aragora.cli.commands.codex_sessions", "cmd_codex_sessions_show")
    )

    tail_cmd = sessions_sub.add_parser(
        "tail",
        help="Poll active sessions and print new redacted events as they arrive",
    )
    add_common(tail_cmd)
    tail_cmd.add_argument(
        "--since",
        default="4h",
        help="Time window selecting which sessions to watch (default: 4h)",
    )
    tail_cmd.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Polling interval in seconds (default: 5.0)",
    )
    tail_cmd.add_argument(
        "--from-start",
        action="store_true",
        help="On startup, replay all events from each active session (default: tail-only).",
    )
    tail_cmd.set_defaults(
        func=_lazy("aragora.cli.commands.codex_sessions", "cmd_codex_sessions_tail")
    )

    insights = codex_sub.add_parser(
        "insights",
        help="Analyze Codex Desktop activity (patterns, anomalies, digests)",
        description=(
            "Read-only analysis over the inspector: aggregate patterns, detect "
            "anomalies (runaway / stuck / over-budget), cross-reference work, "
            "and emit signed daily digest receipts."
        ),
    )
    insights_sub = insights.add_subparsers(dest="codex_insights_cmd")

    def add_insights_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--codex-home",
            default=None,
            help="Override Codex Desktop home dir (default: $ARAGORA_CODEX_HOME or ~/.codex)",
        )
        p.add_argument("--json", action="store_true", help="Emit JSON instead of text")
        p.add_argument(
            "--since",
            default="4h",
            help="Time window (e.g. 30m, 4h, 1d). Default: 4h.",
        )
        p.add_argument(
            "--include-archived",
            action="store_true",
            help="Include archived threads (default: exclude)",
        )

    summary_cmd = insights_sub.add_parser(
        "summary",
        help="Aggregate session patterns (models, tool calls, durations, abandoned count)",
    )
    add_insights_common(summary_cmd)
    summary_cmd.set_defaults(
        func=_lazy("aragora.cli.commands.codex_insights", "cmd_codex_insights_summary")
    )

    anomalies_cmd = insights_sub.add_parser(
        "anomalies",
        help="Flag stuck / runaway / over-budget sessions",
    )
    add_insights_common(anomalies_cmd)
    anomalies_cmd.add_argument(
        "--token-cap",
        type=int,
        default=100_000,
        help="Flag sessions with tokens_used >= this value (default: 100000)",
    )
    anomalies_cmd.add_argument(
        "--runaway-tool-calls",
        type=int,
        default=200,
        help="Flag sessions with >= this many tool calls in the scanned window (default: 200)",
    )
    anomalies_cmd.add_argument(
        "--stuck-turn-minutes",
        type=int,
        default=5,
        help="Flag sessions whose last event is a turn_start silent for > N minutes (default: 5)",
    )
    anomalies_cmd.set_defaults(
        func=_lazy("aragora.cli.commands.codex_insights", "cmd_codex_insights_anomalies")
    )

    crossref_cmd = insights_sub.add_parser(
        "crossref",
        help="Map sessions to PR/issue references found in their metadata",
    )
    add_insights_common(crossref_cmd)
    crossref_cmd.set_defaults(
        func=_lazy("aragora.cli.commands.codex_insights", "cmd_codex_insights_crossref")
    )

    digest_cmd = insights_sub.add_parser(
        "digest",
        help="Build (and optionally persist + KM-ingest) a full daily digest",
    )
    add_insights_common(digest_cmd)
    digest_cmd.add_argument(
        "--emit-receipt",
        action="store_true",
        help="Write the digest JSON to .aragora/codex_insights/digest-<ts>.json",
    )
    digest_cmd.add_argument(
        "--receipt-dir",
        default=None,
        help="Override receipt output directory (default: .aragora/codex_insights/)",
    )
    digest_cmd.add_argument(
        "--ingest-km",
        action="store_true",
        help="After --emit-receipt, ingest into Aragora KM via 'aragora km store' (best-effort)",
    )
    digest_cmd.set_defaults(
        func=_lazy("aragora.cli.commands.codex_insights", "cmd_codex_insights_digest")
    )


def _add_factory_parser(subparsers) -> None:
    """Add the 'factory' read-only inspector commands for Factory/Droid metadata."""

    def parent_help(p: argparse.ArgumentParser):
        def _cmd_parent_help(_args):
            p.print_help()
            return 2

        return _cmd_parent_help

    factory = subparsers.add_parser(
        "factory",
        help="Read-only inspector for Factory/Droid local session metadata",
        description=(
            "Surface Factory/Droid sessions from ~/.factory/ as redacted, read-only "
            "metadata. Raw transcripts, prompts, logs, and history are not read."
        ),
    )
    factory.set_defaults(func=parent_help(factory))
    factory_sub = factory.add_subparsers(dest="factory_cmd")

    sessions = factory_sub.add_parser(
        "sessions",
        help="Inspect Factory/Droid session metadata",
        description="Brief Factory/Droid sessions from local metadata (read-only).",
    )
    sessions.set_defaults(func=parent_help(sessions))
    sessions_sub = sessions.add_subparsers(dest="factory_sessions_cmd")

    brief_cmd = sessions_sub.add_parser(
        "brief",
        help="Brief recent Factory/Droid sessions and route conservative next prompts",
        description=(
            "Build redacted Factory/Droid session briefings from local metadata. "
            "Raw transcript text, prompt logs, history, and session logs are not emitted."
        ),
    )
    brief_cmd.add_argument(
        "--factory-home",
        default=None,
        help="Factory home directory (default: ~/.factory).",
    )
    brief_cmd.add_argument(
        "--since",
        default="4h",
        help="Time window (e.g. 30m, 4h, 1d, 90s). Default: 4h.",
    )
    brief_cmd.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of sessions to brief (default: 50, 0 = no limit).",
    )
    brief_cmd.add_argument(
        "--session",
        default=None,
        help="Restrict to one Factory/Droid session id or id prefix.",
    )
    brief_cmd.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact prompt-router rows instead of full briefing objects.",
    )
    brief_cmd.add_argument(
        "--repo-root",
        default=".",
        help="Repo root used for queue/lane context (default: current directory; '' disables).",
    )
    brief_cmd.add_argument("--json", action="store_true", help="Emit JSON output.")
    brief_cmd.set_defaults(
        func=_lazy("aragora.cli.commands.factory_sessions", "cmd_factory_sessions_brief")
    )


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
        help=(
            "Action (run/preflight/status/shift-status/harness-status/reconcile/campaign/initiative/"
            "integrator/tranche/coord/assign/claim-pr/report/findings/merge-arbiter/dispatch) or "
            "your goal in plain language"
        ),
    )
    swarm_parser.add_argument(
        "swarm_goal",
        nargs="?",
        help="Goal or subaction when using explicit actions",
    )
    swarm_parser.add_argument(
        "swarm_campaign_target",
        nargs="?",
        help="Campaign or initiative subtarget such as a project id for review/promotion",
    )
    swarm_parser.add_argument(
        "--spec",
        help="Path to a pre-built SwarmSpec YAML file",
    )
    swarm_parser.add_argument(
        "--runbook",
        default=None,
        help=("Runbook name or path for 'swarm dispatch' (default: .aragora/runbooks/<name>.yaml)"),
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
        choices=[
            "full-auto",
            "propose",
            "guided",
            "metrics",
            "adaptive",
            "fire_and_forget",
            "checkpoint",
            "spectator",
        ],
        default="propose",
        help="Autonomy mode for swarm and tranche flows (default: propose)",
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
        "--ping-pong",
        action="store_true",
        dest="ping_pong",
        help="On needs_human retry, dispatch to alternate agent with handoff context",
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
        "--skip-publication",
        action="store_true",
        help="For 'swarm preflight', skip push/PR steps and validate the worker locally only",
    )
    swarm_parser.add_argument(
        "--contract",
        default=None,
        help="For 'swarm preflight', load a JSON worker contract for contract-aware validation",
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
        "--readiness",
        default=None,
        help="Optional integrator readiness filter (for 'integrator' view)",
    )
    swarm_parser.add_argument(
        "--lane-id",
        default=None,
        help="Integrator lane id for 'integrator' actions",
    )
    swarm_parser.add_argument(
        "--receipt-id",
        default=None,
        help="Explicit completion receipt id for 'integrator' actions",
    )
    swarm_parser.add_argument(
        "--lease-id",
        default=None,
        help="Explicit lease id for 'integrator' actions",
    )
    swarm_parser.add_argument(
        "--lane-branch",
        default=None,
        help="Explicit lane branch for 'integrator supersede' or lane resolution",
    )
    swarm_parser.add_argument(
        "--decided-by",
        default="cli-integrator",
        help="Integrator actor recorded on merge/archive decisions (default: cli-integrator)",
    )
    swarm_parser.add_argument(
        "--rationale",
        default="",
        help="Integrator rationale for merge/archive/supersede actions",
    )
    swarm_parser.add_argument(
        "--session-id",
        default=None,
        help="Coordination session id for claim/report actions (defaults from env or pid)",
    )
    swarm_parser.add_argument(
        "--assigned-by",
        default=None,
        help="Actor recorded for 'swarm assign' (defaults from env or pid)",
    )
    swarm_parser.add_argument(
        "--directive-status",
        default="active",
        choices=["active", "standby", "blocked", "done"],
        help="Directive status for 'swarm assign' (default: active)",
    )
    swarm_parser.add_argument(
        "--scope",
        action="append",
        default=None,
        help="Shared scope item for coordination actions (repeatable)",
    )
    swarm_parser.add_argument(
        "--constraint",
        action="append",
        default=None,
        help="Constraint for 'swarm assign' (repeatable)",
    )
    swarm_parser.add_argument(
        "--claim-intent",
        default=None,
        help="Intent text for 'swarm claim-pr'",
    )
    swarm_parser.add_argument(
        "--ttl-minutes",
        type=int,
        default=30,
        help="Claim TTL in minutes for 'swarm claim-pr' (default: 30)",
    )
    swarm_parser.add_argument(
        "--kind",
        default=None,
        choices=["finding", "blocker", "handoff", "status"],
        help="Finding kind for 'swarm report' and optional filter for 'swarm findings'",
    )
    swarm_parser.add_argument(
        "--pr",
        type=int,
        default=None,
        help="Optional PR number attached to a coordination finding",
    )
    swarm_parser.add_argument(
        "--new-pr-url",
        default=None,
        help="Replacement PR URL for 'integrator supersede'",
    )
    swarm_parser.add_argument(
        "--status-limit",
        type=int,
        default=20,
        help="Maximum runs to show in 'status' (default: 20)",
    )
    swarm_parser.add_argument(
        "--shift-ledger",
        default=None,
        help=(
            "Ledger path for 'swarm shift-status' "
            "(default: .aragora/proof_first_shift/shift_ledger.jsonl)"
        ),
    )
    swarm_parser.add_argument(
        "--max-age-hours",
        type=float,
        default=24.0,
        help="Ledger lookback window for 'swarm shift-status' (default: 24)",
    )
    swarm_parser.add_argument(
        "--findings-limit",
        type=int,
        default=10,
        help="Maximum coordination findings to show in 'status', 'coord', or 'findings' (default: 10)",
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
        "--interval",
        "--interval-seconds",
        dest="interval_seconds",
        type=float,
        default=5.0,
        help="Reconciler polling interval for --watch or reconcile (default: 5.0)",
    )
    swarm_parser.add_argument(
        "--driver",
        action="store_true",
        help="Claim driver mode for tranche watch and allow autonomous advancement",
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
    swarm_parser.add_argument(
        "--dispatch-only",
        action="store_true",
        help="Only provision worktrees and create work orders (don't spawn workers)",
    )
    swarm_parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Spawn workers but don't wait for completion (fire-and-forget)",
    )
    # Boss-loop specific options
    swarm_parser.add_argument(
        "--freshness-ttl",
        type=float,
        default=3600.0,
        dest="freshness_ttl",
        help="Runner freshness TTL in seconds for boss-loop (default: 3600)",
    )
    swarm_parser.add_argument(
        "--boss-repo",
        type=str,
        default=None,
        help="GitHub repo (owner/repo) for boss-loop issue feed (default: current repo)",
    )
    swarm_parser.add_argument(
        "--boss-label-filter",
        type=str,
        default=None,
        help="Only consider issues with this label in boss-loop (deprecated: use --label)",
    )
    swarm_parser.add_argument(
        "--label",
        action="append",
        default=None,
        dest="labels",
        help="Only consider issues with ALL specified labels (repeatable: --label P0 --label queue-eligible)",
    )
    swarm_parser.add_argument(
        "--boss-issue-number",
        type=int,
        default=None,
        help="Target one specific GitHub issue number in boss-loop instead of selecting from the feed",
    )
    swarm_parser.add_argument(
        "--boss-issue-list",
        default=None,
        help="Comma-separated GitHub issue numbers for boss-loop scoped dispatch",
    )
    swarm_parser.add_argument(
        "--audit-ref",
        default=None,
        help="For 'swarm audit-issues', run validations from a temporary detached worktree at this git ref (for example: origin/main)",
    )
    swarm_parser.add_argument(
        "--max-consecutive-failures",
        type=int,
        default=3,
        help="Stop boss-loop or tranche queue after N consecutive hard failures (default: 3)",
    )
    swarm_parser.add_argument(
        "--branch-prefix",
        dest="boss_branch_prefix",
        type=str,
        default=None,
        help="Comma-separated branch prefixes for merge-arbiter (default: boss-harvest)",
    )
    swarm_parser.add_argument(
        "--boss-max-parallel-dispatches",
        type=int,
        default=1,
        help="Maximum boss-loop issues to dispatch concurrently in one tick (default: 1)",
    )
    swarm_parser.add_argument(
        "--boss-auto-update",
        action="store_true",
        help="Auto-update boss-loop by pulling origin/target-branch and restarting when behind.",
    )
    swarm_parser.add_argument(
        "--boss-auto-update-interval",
        type=int,
        default=10,
        help="Check for boss-loop auto-update every N iterations (default: 10).",
    )
    swarm_parser.add_argument(
        "--allow-missing-validation-contract",
        action="store_true",
        help="Allow boss-loop dispatch even when the issue body lacks explicit validation criteria",
    )
    swarm_parser.add_argument(
        "--boss-llm-pre-dispatch-gate",
        action="store_true",
        help=(
            "Opt in to LLM-assisted boss-loop issue parsing before dispatch. "
            "Default is deterministic regex-only parsing."
        ),
    )
    swarm_parser.add_argument(
        "--no-suitable-issue-keepalive",
        action="store_true",
        dest="no_suitable_issue_keepalive",
        help=(
            "Opt in to long-running boss-loop: when no eligible issues are found, "
            "log and sleep for --interval-seconds before retrying instead of exiting. "
            "Use this to keep the boss-loop process alive for the full --max-hours window "
            "(e.g. when launchd ThrottleInterval gaps would otherwise interfere). "
            "Default off, preserving short-lived clean-exit lifecycle."
        ),
    )
    swarm_parser.add_argument(
        "--source-file",
        help="Campaign planner or initiative rationale input markdown/text file",
    )
    swarm_parser.add_argument(
        "--initiative-dir",
        default=None,
        help="Local initiative artifact directory for 'swarm initiative' commands",
    )
    swarm_parser.add_argument(
        "--feature-flag",
        default=None,
        help="Feature flag name to persist on an initiative plan",
    )
    swarm_parser.add_argument(
        "--dependency",
        action="append",
        default=None,
        help="Dependency to persist on an initiative plan (repeatable)",
    )
    swarm_parser.add_argument(
        "--validation",
        action="append",
        default=None,
        help="Validation command to persist on an initiative plan (repeatable)",
    )
    swarm_parser.add_argument(
        "--milestone",
        action="append",
        default=None,
        help="Milestone title to persist on an initiative plan (repeatable)",
    )
    swarm_parser.add_argument(
        "--checkpoint",
        action="append",
        default=None,
        help="Checkpoint title to persist on an initiative plan (repeatable)",
    )
    swarm_parser.add_argument(
        "--issue-list",
        help="Comma-separated GitHub issue numbers for campaign planning",
    )
    swarm_parser.add_argument(
        "--github-query",
        help="GitHub issue search query for campaign planning",
    )
    swarm_parser.add_argument(
        "--planner-model",
        default="claude",
        help="Planner model for campaign planning (default: claude)",
    )
    swarm_parser.add_argument(
        "--planner-strategy",
        default="heuristic",
        choices=("heuristic", "model"),
        help="Planner strategy for campaign planning/execution (default: heuristic)",
    )
    swarm_parser.add_argument(
        "--worker-model",
        default="claude",
        help="Worker model for campaign or boss-loop execution (default: claude)",
    )
    swarm_parser.add_argument(
        "--review-model",
        default="codex",
        help="Review model for campaign or boss-loop cross-check/review (default: codex)",
    )
    swarm_parser.add_argument(
        "--runner-type",
        default=None,
        help="Runner type for 'swarm runner' actions (for example: claude, codex, gemini-cli)",
    )
    swarm_parser.add_argument(
        "--claude-runner-profiles",
        default=None,
        help="Comma-separated Claude profiles to discover/register and prefer for boss-loop routing",
    )
    swarm_parser.add_argument(
        "--runner-rotation-interval",
        type=float,
        default=1800.0,
        help="Seconds before a recently used runner profile becomes preferred again (default: 1800)",
    )
    swarm_parser.add_argument(
        "--probe-limit",
        type=int,
        default=None,
        help="Maximum runners to live-probe for 'swarm runner probe' or 'swarm runner maintain'",
    )
    swarm_parser.add_argument(
        "--allow-same-model-review",
        action="store_true",
        help="Allow worker and reviewer to use the same model for experiment runs",
    )
    swarm_parser.add_argument(
        "--experiment-id",
        default=None,
        help="Optional experiment identifier for campaign benchmark runs",
    )
    swarm_parser.add_argument(
        "--experiment-label",
        default=None,
        help="Optional human-readable experiment label for campaign benchmark runs",
    )
    swarm_parser.add_argument(
        "--manifest",
        default=DEFAULT_CAMPAIGN_MANIFEST,
        help="Campaign, initiative, or tranche manifest path (default: .aragora/campaign_manifest.yaml)",
    )
    swarm_parser.add_argument(
        "--queue",
        default=None,
        help="Queue manifest path for 'swarm tranche run-queue', 'reconcile-queue', and 'harvest-queue'",
    )
    swarm_parser.add_argument(
        "--execute-merge",
        action="store_true",
        help="For 'swarm tranche harvest-queue', execute merges for PRs whose GitHub gate disposition is merge_now",
    )
    swarm_parser.add_argument(
        "--allow-admin",
        action="store_true",
        help="Allow admin merge fallback for eligible harvest-queue merges when GitHub reports a policy/admin override candidate",
    )
    swarm_parser.add_argument(
        "--max-parallel-lanes",
        type=int,
        choices=[1, 2],
        default=1,
        help=(
            "Maximum tranche lanes 'swarm tranche run-queue' may dispatch concurrently (default: 1)"
        ),
    )
    swarm_parser.add_argument(
        "--sources",
        default=None,
        help="Queue source manifest path for 'swarm tranche compile-queue'",
    )
    swarm_parser.add_argument(
        "--output",
        default=None,
        help="Output path for campaign planning (defaults to --manifest)",
    )
    swarm_parser.add_argument(
        "--intake",
        default=None,
        help="Intake bundle YAML/JSON input for 'swarm tranche submit' (use - for stdin)",
    )
    swarm_parser.add_argument(
        "--from-prompts",
        default=None,
        help="Prompt-pack YAML/JSON input for 'swarm tranche plan'",
    )
    swarm_parser.add_argument(
        "--all-ready",
        action="store_true",
        help="Operate on all ready, claimable tranche lanes instead of one lane",
    )
    swarm_parser.add_argument(
        "--all-completed",
        action="store_true",
        help="Operate on all completed tranche lanes instead of one lane",
    )
    swarm_parser.add_argument(
        "--all-mergeable",
        action="store_true",
        help="Operate on all mergeable tranche lanes instead of one lane",
    )
    swarm_parser.add_argument(
        "--owner-agent",
        default=None,
        help="Owner agent recorded for tranche prepare/run (defaults to lane target agent)",
    )
    swarm_parser.add_argument(
        "--owner-session-id",
        default=None,
        help="Owner session id recorded for tranche prepare/run artifacts",
    )
    swarm_parser.add_argument(
        "--skip-review",
        action="store_true",
        help="Skip cross-model tranche review after a completed lane run",
    )
    swarm_parser.add_argument(
        "--allow-claude-write",
        action="store_true",
        help=(
            "Allow tranche runs to pass --dangerously-skip-permissions to Claude "
            "workers (required for non-interactive edits)"
        ),
    )
    swarm_parser.add_argument(
        "--rounds",
        type=int,
        default=2,
        help="Maximum bounded rounds for tranche design-review (default: 2)",
    )
    swarm_parser.add_argument(
        "--tier",
        choices=("auto", "1", "2", "3"),
        default="auto",
        help="Review tier for tranche review (default: auto)",
    )
    swarm_parser.add_argument(
        "--approve",
        action="store_true",
        help="Allow tranche integrate to record and execute the recommended integration action",
    )
    swarm_parser.add_argument(
        "--max-hours",
        type=float,
        default=12.0,
        help="Maximum wall-clock hours for tranche queue execution (default: 12.0)",
    )
    swarm_parser.add_argument(
        "--max-parallel-ready-projects",
        type=int,
        default=1,
        help="Maximum dependency-independent campaign projects to run per execute (default: 1)",
    )
    swarm_parser.set_defaults(
        func=lambda args: __import__(
            "aragora.cli.commands.swarm", fromlist=["cmd_swarm"]
        ).cmd_swarm(args)
    )


def _add_tasks_parser(subparsers) -> None:
    """Add the public tasks command."""
    from aragora.cli.commands.tasks import add_tasks_parser

    add_tasks_parser(subparsers)


def _add_ralph_parser(subparsers) -> None:
    """Add the 'ralph' subcommand for the campaign supervisor."""
    ralph_parser = subparsers.add_parser(
        "ralph",
        help="Ralph campaign supervisor — autonomous incident commander",
        description=(
            "Ralph campaign supervisor: run, classify, repair, merge, resume.\n\n"
            "Actions:\n"
            "  campaign-supervisor start   Start a new supervisor run\n"
            "  campaign-supervisor step    Advance one step\n"
            "  campaign-supervisor status  Show current state\n"
            "  campaign-supervisor stop    Gracefully stop\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ralph_parser.add_argument(
        "ralph_action",
        nargs="?",
        default="campaign-supervisor",
        help="Action: campaign-supervisor (default)",
    )
    ralph_parser.add_argument(
        "ralph_subaction",
        nargs="?",
        default="status",
        help="Subaction: start, step, status, stop, resume (default: status)",
    )
    ralph_parser.add_argument(
        "--manifest",
        help="Path to campaign manifest (for start)",
    )
    ralph_parser.add_argument(
        "--state",
        default=".aragora/supervisor_state.yaml",
        help="Path to supervisor state file (default: .aragora/supervisor_state.yaml)",
    )
    ralph_parser.add_argument(
        "--merge-policy",
        default="manual_review_required",
        choices=["manual_review_required", "admin_merge_allowed"],
        help="PR merge policy (default: manual_review_required)",
    )
    ralph_parser.add_argument(
        "--max-repair-attempts",
        type=int,
        default=2,
        help="Max automatic repair attempts per blocker (default: 2)",
    )
    ralph_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output JSON instead of human-readable text",
    )
    ralph_parser.set_defaults(
        func=lambda args: __import__(
            "aragora.cli.commands.ralph", fromlist=["cmd_ralph"]
        ).cmd_ralph(args)
    )


def _add_assess_parser(subparsers) -> None:
    """Add the 'assess' subcommand for canonical repository assessment."""
    p = subparsers.add_parser("assess", help="Run canonical repository assessment")
    p.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )
    p.add_argument(
        "--save",
        action="store_true",
        help="Persist assessment to strategic memory store",
    )
    p.add_argument(
        "--diff",
        action="store_true",
        help="Show delta from previous assessment",
    )
    p.set_defaults(func=_lazy("aragora.cli.commands.assess", "cmd_assess"))


def _add_spec_parser(subparsers) -> None:
    """Add the 'spec' subcommand for prompt-to-specification pipeline."""
    spec_parser = subparsers.add_parser(
        "spec",
        help="Transform a vague idea into a structured specification",
        description="""
Transform a vague idea or task description into a structured specification
through AI-powered decomposition, interrogation, research, and spec building.

Examples:
  aragora spec "Make our onboarding flow better"
  aragora spec "Add dark mode" --depth thorough --profile cto
  aragora spec "Improve test coverage" --format json --output spec.json
  aragora spec "Publish H1-01 rev-4 benchmark result" --to-mission /tmp/mission.yaml
  aragora spec "Design a rate limiter" --dry-run
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    spec_parser.add_argument("prompt", help="The idea or task to turn into a spec")
    spec_parser.add_argument(
        "--depth",
        choices=["quick", "thorough", "exhaustive"],
        default="quick",
        help="Interrogation depth (default: quick)",
    )
    spec_parser.add_argument(
        "--profile",
        choices=["founder", "cto", "business", "team"],
        default="founder",
        help="User profile for autonomy defaults (default: founder)",
    )
    spec_parser.add_argument(
        "--skip-research",
        action="store_true",
        help="Skip the research phase",
    )
    spec_parser.add_argument(
        "--skip-interrogation",
        action="store_true",
        help="Skip clarifying questions",
    )
    spec_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    spec_parser.add_argument(
        "--output",
        "-o",
        help="Save spec to file",
    )
    spec_parser.add_argument(
        "--to-mission",
        help="Write a goal-conductor mission YAML file from the generated spec, without dispatching agents.",
    )
    spec_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview pipeline steps without executing",
    )
    spec_parser.add_argument(
        "--orchestrator",
        action="store_true",
        help="Route through UnifiedOrchestrator for full backbone tracking",
    )
    spec_parser.set_defaults(func=_lazy("aragora.cli.commands.spec", "cmd_spec"))


def _add_crux_parser(subparsers) -> None:
    """Add the 'crux' subcommand for crux-finder debate mode."""
    crux_parser = subparsers.add_parser(
        "crux",
        help="Find load-bearing disagreements on a question (crux-finder debate)",
        description="""
Run a debate in crux-finder mode. Instead of producing a verdict, aragora
emits a signed map of the 3–5 disagreements that, if resolved, would most
change the answer. Backed by the same belief-network machinery as `ask`,
but the deliverable is a CruxReceipt, not a DecisionReceipt.

Examples:
  aragora crux "Should we adopt feature X?"
  aragora crux "Is this migration safe?" --top-k 3 --min-score 0.4
  aragora crux "Do we need rate limiting?" --format json --receipt crux.json
  aragora crux "Should we ship?" --dry-run
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    crux_parser.add_argument("question", help="The contested question to map")
    crux_parser.add_argument(
        "--agents",
        "-a",
        default=None,
        help="Comma-separated agent list (default: claude,codex)",
    )
    crux_parser.add_argument(
        "--rounds",
        "-r",
        type=int,
        default=3,
        help="Number of debate rounds (default: 3)",
    )
    crux_parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Maximum cruxes to return (default: 5)",
    )
    crux_parser.add_argument(
        "--min-score",
        type=float,
        default=0.3,
        help="Minimum crux score threshold (default: 0.3)",
    )
    crux_parser.add_argument(
        "--no-counterfactuals",
        action="store_true",
        help="Skip counterfactual validation of each crux",
    )
    crux_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format for stdout (default: markdown)",
    )
    crux_parser.add_argument(
        "--receipt",
        help="Write the signed CruxReceipt JSON to the given path",
    )
    crux_parser.add_argument(
        "--output",
        "-o",
        help="Write the rendered output (markdown or json) to the given path",
    )
    crux_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview parameters without running the debate",
    )
    crux_parser.set_defaults(func=_lazy("aragora.cli.commands.crux", "cmd_crux"))


def _add_crux_followup_parser(subparsers) -> None:
    """Add the 'crux-followup' subcommand for DIC-17 follow-up proposals."""
    from aragora.epistemic.followup import DEFAULT_CRUX_LOAD_BEARING_THRESHOLD

    p = subparsers.add_parser(
        "crux-followup",
        help="Generate DIC-17 follow-up proposals from a CruxSet (flag-gated filing)",
        description="""
Read a signed CruxSet JSON file and emit bounded DIC-17 FollowupProposals for
load-bearing cruxes above --threshold.  Default: dry-run (print proposals only).
Filing via --file-issues requires ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED=1.

Examples:
  aragora crux-followup cruxset.json
  aragora crux-followup cruxset.json --threshold 0.7 --json
  aragora crux-followup cruxset.json --file-issues --repo owner/repo
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("cruxset_file", help="Path to CruxSet JSON file (- for stdin)")
    p.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_CRUX_LOAD_BEARING_THRESHOLD,
        help=f"Minimum load_bearing_score for a crux to qualify (default: {DEFAULT_CRUX_LOAD_BEARING_THRESHOLD})",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=5,
        dest="top_k",
        help="Maximum proposals to emit (default: 5)",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable text")
    p.add_argument(
        "--file-issues",
        action="store_true",
        dest="file_issues",
        help="Print gh issue create commands for proposals (requires ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED=1)",
    )
    p.add_argument(
        "--repo",
        default="",
        help="GitHub repo (owner/name) for --file-issues",
    )
    p.set_defaults(func=_lazy("aragora.cli.commands.crux_followup", "cmd_crux_followup"))


def _add_build_parser(subparsers) -> None:
    """Add the 'build' subcommand parser."""
    build_parser = subparsers.add_parser(
        "build",
        help="Turn a vague idea into executed, reviewed, merged code",
    )
    build_parser.add_argument("idea", nargs="?", help="Your idea in plain language")
    build_parser.add_argument("--from-file", help="Read idea from a file")
    build_parser.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    build_parser.add_argument(
        "--skip-clarify", action="store_true", help="Skip clarification questions"
    )
    build_parser.add_argument(
        "--max-tasks", type=int, default=5, help="Maximum tasks to create (default: 5)"
    )
    build_parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repository for issue creation and dispatch (default: synaptent/aragora)",
    )
    build_parser.add_argument(
        "--worker-model",
        default="claude",
        help="Preferred worker model for dispatched boss-loop tasks (default: claude)",
    )
    build_parser.add_argument(
        "--review-model",
        default="codex",
        help="Preferred reviewer model for dispatched boss-loop tasks (default: codex)",
    )
    build_parser.add_argument(
        "--risk",
        choices=("low", "medium", "high"),
        default="medium",
        help="Risk level to stamp onto generated queue items (default: medium)",
    )
    build_parser.add_argument(
        "--merge-class",
        choices=("manual", "low_risk"),
        default="manual",
        help="Merge class to stamp onto generated queue items (default: manual)",
    )
    build_parser.add_argument(
        "--autonomy-mode",
        choices=("full-auto", "checkpoint", "adaptive", "fire_and_forget"),
        default="full-auto",
        help="Autonomy mode to stamp onto generated queue items and dispatch (default: full-auto)",
    )
    build_parser.add_argument("--json", action="store_true", help="Output as JSON")
    build_parser.set_defaults(func=_lazy("aragora.cli.commands.build", "cmd_build"))


def _add_idea_parser(subparsers) -> None:
    """Add the 'idea' subcommand parser."""
    idea_parser = subparsers.add_parser(
        "idea",
        help="Clarify a vague idea into a structured initiative brief",
    )
    sub = idea_parser.add_subparsers(dest="idea_command")

    intake_parser = sub.add_parser(
        "intake",
        help="Turn a founder note or vague brief into a machine-readable initiative brief",
    )
    intake_parser.add_argument("idea", nargs="?", help="Idea in plain language")
    intake_parser.add_argument("--from-file", help="Read idea text from a file")
    intake_parser.add_argument(
        "--skip-clarify",
        action="store_true",
        help="Skip clarification questions and use the conductor's default assumptions",
    )
    intake_parser.add_argument(
        "--priority",
        choices=("low", "medium", "high", "critical"),
        default="medium",
        help="Sequencing priority to assign to the initiative brief (default: medium)",
    )
    intake_parser.add_argument(
        "--track",
        choices=("1", "2", "3", "4", "5", "6", "7"),
        default="1",
        help="Roadmap track label to stamp onto persisted artifacts (default: 1)",
    )
    intake_parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repository for optional issue creation (default: synaptent/aragora)",
    )
    intake_parser.add_argument(
        "--risk",
        choices=("low", "medium", "high"),
        default="medium",
        help="Risk level to stamp onto the initiative brief (default: medium)",
    )
    intake_parser.add_argument(
        "--merge-class",
        choices=("manual", "low_risk"),
        default="manual",
        help="Merge class to stamp onto persisted artifacts (default: manual)",
    )
    intake_parser.add_argument(
        "--autonomy-mode",
        choices=("full-auto", "checkpoint", "adaptive", "fire_and_forget"),
        default="checkpoint",
        help="Autonomy mode to stamp onto the initiative brief (default: checkpoint)",
    )
    intake_parser.add_argument(
        "--worker-model",
        default="claude",
        help="Preferred worker model for eventual execution planning (default: claude)",
    )
    intake_parser.add_argument(
        "--review-model",
        default="codex",
        help="Preferred reviewer model for eventual execution planning (default: codex)",
    )
    intake_parser.add_argument(
        "--create-issue",
        action="store_true",
        help="Persist the initiative brief as a GitHub issue",
    )
    intake_parser.add_argument("--json", action="store_true", help="Output as JSON")

    triage_parser = sub.add_parser(
        "triage",
        help="Decompose an initiative into structured founder handoffs and queue-ready tasks",
    )
    triage_parser.add_argument("idea", nargs="?", help="Idea in plain language")
    triage_parser.add_argument("--from-file", help="Read idea text from a file")
    triage_parser.add_argument(
        "--skip-clarify",
        action="store_true",
        help="Skip clarification questions and use the conductor's default assumptions",
    )
    triage_parser.add_argument(
        "--priority",
        choices=("low", "medium", "high", "critical"),
        default="medium",
        help="Sequencing priority to assign to generated handoffs (default: medium)",
    )
    triage_parser.add_argument(
        "--track",
        choices=("1", "2", "3", "4", "5", "6", "7"),
        default="1",
        help="Roadmap track label to stamp onto persisted artifacts (default: 1)",
    )
    triage_parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repository for optional issue creation (default: synaptent/aragora)",
    )
    triage_parser.add_argument(
        "--max-tasks",
        type=int,
        default=4,
        help="Maximum founder handoffs to emit (default: 4)",
    )
    triage_parser.add_argument(
        "--risk",
        choices=("low", "medium", "high"),
        default="medium",
        help="Default risk level to stamp onto generated handoffs (default: medium)",
    )
    triage_parser.add_argument(
        "--merge-class",
        choices=("manual", "low_risk"),
        default="manual",
        help="Default merge class to stamp onto generated handoffs (default: manual)",
    )
    triage_parser.add_argument(
        "--autonomy-mode",
        choices=("full-auto", "checkpoint", "adaptive", "fire_and_forget"),
        default="checkpoint",
        help="Default autonomy mode for generated handoffs (default: checkpoint)",
    )
    triage_parser.add_argument(
        "--worker-model",
        default="claude",
        help="Preferred worker model for generated handoffs (default: claude)",
    )
    triage_parser.add_argument(
        "--review-model",
        default="codex",
        help="Preferred reviewer model for generated handoffs (default: codex)",
    )
    triage_parser.add_argument(
        "--create-issues",
        action="store_true",
        help="Persist generated handoffs as boss-ready GitHub issues",
    )
    triage_parser.add_argument("--json", action="store_true", help="Output as JSON")

    review_parser = sub.add_parser(
        "review",
        help="Apply founder-review checks to generated handoffs and emit follow-up tasks",
    )
    review_parser.add_argument("idea", nargs="?", help="Idea in plain language")
    review_parser.add_argument("--from-file", help="Read idea text from a file")
    review_parser.add_argument(
        "--skip-clarify",
        action="store_true",
        help="Skip clarification questions and use the conductor's default assumptions",
    )
    review_parser.add_argument(
        "--priority",
        choices=("low", "medium", "high", "critical"),
        default="medium",
        help="Sequencing priority to assign to generated handoffs (default: medium)",
    )
    review_parser.add_argument(
        "--track",
        choices=("1", "2", "3", "4", "5", "6", "7"),
        default="1",
        help="Roadmap track label to stamp onto persisted artifacts (default: 1)",
    )
    review_parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repository for optional issue creation (default: synaptent/aragora)",
    )
    review_parser.add_argument(
        "--max-tasks",
        type=int,
        default=4,
        help="Maximum founder handoffs to review (default: 4)",
    )
    review_parser.add_argument(
        "--risk",
        choices=("low", "medium", "high"),
        default="medium",
        help="Default risk level to stamp onto generated handoffs (default: medium)",
    )
    review_parser.add_argument(
        "--merge-class",
        choices=("manual", "low_risk"),
        default="manual",
        help="Default merge class to stamp onto generated handoffs (default: manual)",
    )
    review_parser.add_argument(
        "--autonomy-mode",
        choices=("full-auto", "checkpoint", "adaptive", "fire_and_forget"),
        default="checkpoint",
        help="Default autonomy mode for generated handoffs (default: checkpoint)",
    )
    review_parser.add_argument(
        "--worker-model",
        default="claude",
        help="Preferred worker model for generated handoffs (default: claude)",
    )
    review_parser.add_argument(
        "--review-model",
        default="codex",
        help="Preferred reviewer model for founder review output (default: codex)",
    )
    review_parser.add_argument(
        "--create-issues",
        action="store_true",
        help="Persist founder-review follow-up tasks as boss-ready GitHub issues",
    )
    review_parser.add_argument("--json", action="store_true", help="Output as JSON")

    idea_parser.set_defaults(func=_lazy("aragora.cli.commands.idea", "cmd_idea"))


def _add_essay_parser(subparsers) -> None:
    """Add the 'essay' subcommand with 'refine' and 'score' sub-subcommands."""
    essay_parser = subparsers.add_parser(
        "essay",
        help="Refine raw ideas into a polished essay or score an existing draft",
        description=(
            "Essay Refinement Pipeline: extract -> draft -> evaluate -> synthesize -> polish.\n\n"
            "Subcommands:\n"
            "  refine  Run the full multi-model refinement pipeline on raw ideas\n"
            "  score   Evaluate an existing draft across 7 quality dimensions"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    essay_parser.set_defaults(func=_lazy("aragora.cli.commands.essay", "essay_command"))

    essay_sub = essay_parser.add_subparsers(dest="essay_subcommand")

    # ── refine subcommand ──────────────────────────────────────────────────
    refine_parser = essay_sub.add_parser(
        "refine",
        help="Run the essay refinement pipeline on raw ideas",
    )
    refine_parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Path to a file containing raw ideas / brainstorm notes",
    )
    refine_parser.add_argument(
        "--output",
        "-o",
        help="Write the final essay to this file",
    )
    refine_parser.add_argument(
        "--rounds",
        "-r",
        type=int,
        default=3,
        help="Maximum refinement iterations (default: 3)",
    )
    refine_parser.add_argument(
        "--models",
        "-m",
        help="Comma-separated list of model identifiers for parallel drafting",
    )
    refine_parser.add_argument(
        "--target-words",
        type=int,
        default=1200,
        dest="target_words",
        help="Approximate word count for the final essay (default: 1200)",
    )
    refine_parser.add_argument(
        "--voice-notes",
        dest="voice_notes",
        help="Stylistic guidance forwarded to drafting and synthesis prompts",
    )
    refine_parser.add_argument(
        "--rubric",
        help="Path to a YAML rubric file (uses built-in rubric if omitted)",
    )
    refine_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract thesis and outline only; skip drafting and scoring",
    )
    refine_parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a previously interrupted pipeline run",
    )
    refine_parser.set_defaults(func=_lazy("aragora.cli.commands.essay", "essay_command"))

    # ── score subcommand ───────────────────────────────────────────────────
    score_parser = essay_sub.add_parser(
        "score",
        help="Evaluate an existing draft across 7 quality dimensions",
    )
    score_parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Path to an existing essay draft file",
    )
    score_parser.add_argument(
        "--rubric",
        help="Path to a YAML rubric file (uses built-in rubric if omitted)",
    )
    score_parser.add_argument(
        "--models",
        "-m",
        help="Comma-separated model identifiers; first model is used as judge",
    )
    score_parser.set_defaults(func=_lazy("aragora.cli.commands.essay", "essay_command"))
