"""
CLI command implementations, split by functional domain.

All public command handlers and functions are re-exported here for convenience.
Imports are deferred via __getattr__ to avoid loading heavy dependencies
(Arena, agents, scipy, etc.) at package import time.
"""

from __future__ import annotations

# Mapping of attribute names to (module_path, attr_name)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # debate
    "get_event_emitter_if_available": (
        "aragora.cli.commands.debate",
        "get_event_emitter_if_available",
    ),
    "parse_agents": ("aragora.cli.commands.debate", "parse_agents"),
    "run_debate": ("aragora.cli.commands.debate", "run_debate"),
    "cmd_ask": ("aragora.cli.commands.debate", "cmd_ask"),
    # stats
    "cmd_stats": ("aragora.cli.commands.stats", "cmd_stats"),
    "cmd_patterns": ("aragora.cli.commands.stats", "cmd_patterns"),
    "cmd_memory": ("aragora.cli.commands.stats", "cmd_memory"),
    "cmd_elo": ("aragora.cli.commands.stats", "cmd_elo"),
    "cmd_cross_pollination": ("aragora.cli.commands.stats", "cmd_cross_pollination"),
    # status
    "cmd_status": ("aragora.cli.commands.status", "cmd_status"),
    "cmd_validate_env": ("aragora.cli.commands.status", "cmd_validate_env"),
    "cmd_doctor": ("aragora.cli.commands.status", "cmd_doctor"),
    "cmd_validate": ("aragora.cli.commands.status", "cmd_validate"),
    # server
    "cmd_serve": ("aragora.cli.commands.server", "cmd_serve"),
    # tools
    "cmd_modes": ("aragora.cli.commands.tools", "cmd_modes"),
    "cmd_templates": ("aragora.cli.commands.tools", "cmd_templates"),
    "cmd_improve": ("aragora.cli.commands.tools", "cmd_improve"),
    "cmd_context": ("aragora.cli.commands.tools", "cmd_context"),
    # delegated
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
    # testfix
    "cmd_testfix": ("aragora.cli.commands.testfix", "cmd_testfix"),
    # skills
    "cmd_skills": ("aragora.cli.commands.skills", "cmd_skills"),
    "add_skills_parser": ("aragora.cli.commands.skills", "add_skills_parser"),
    # nomic loop
    "cmd_nomic": ("aragora.cli.commands.nomic", "cmd_nomic"),
    "add_nomic_parser": ("aragora.cli.commands.nomic", "add_nomic_parser"),
    # workflow engine
    "cmd_workflow": ("aragora.cli.commands.workflow", "cmd_workflow"),
    "add_workflow_parser": ("aragora.cli.commands.workflow", "add_workflow_parser"),
    # receipt verification
    "cmd_receipt": ("aragora.cli.commands.receipt", "cmd_receipt"),
    "cmd_receipt_verify": ("aragora.cli.commands.receipt", "cmd_receipt_verify"),
    "cmd_receipt_inspect": ("aragora.cli.commands.receipt", "cmd_receipt_inspect"),
    "cmd_receipt_export": ("aragora.cli.commands.receipt", "cmd_receipt_export"),
    "setup_receipt_parser": ("aragora.cli.commands.receipt", "setup_receipt_parser"),
    # deployment CLI
    "cmd_deploy": ("aragora.cli.commands.deploy", "cmd_deploy"),
    "add_deploy_parser": ("aragora.cli.commands.deploy", "add_deploy_parser"),
    # memory operations
    "cmd_memory_ops": ("aragora.cli.commands.memory_ops", "cmd_memory_ops"),
    "add_memory_ops_parser": ("aragora.cli.commands.memory_ops", "add_memory_ops_parser"),
    # package publishing
    "cmd_publish": ("aragora.cli.commands.publish", "cmd_publish"),
    "add_publish_parser": ("aragora.cli.commands.publish", "add_publish_parser"),
    # autopilot GTM
    "cmd_autopilot": ("aragora.cli.commands.autopilot", "cmd_autopilot"),
    "add_autopilot_parser": ("aragora.cli.commands.autopilot", "add_autopilot_parser"),
    # coordinate (multi-agent worktree coordination)
    "cmd_coordinate": ("aragora.cli.commands.coordinate", "cmd_coordinate"),
    "add_coordinate_parser": ("aragora.cli.commands.coordinate", "add_coordinate_parser"),
    # pipeline (idea-to-execution pipeline)
    "cmd_pipeline": ("aragora.cli.commands.pipeline", "cmd_pipeline"),
    "add_pipeline_parser": ("aragora.cli.commands.pipeline", "add_pipeline_parser"),
    # consensus detection
    "cmd_consensus": ("aragora.cli.commands.consensus", "cmd_consensus"),
    "cmd_consensus_detect": ("aragora.cli.commands.consensus", "cmd_consensus_detect"),
    "cmd_consensus_status": ("aragora.cli.commands.consensus", "cmd_consensus_status"),
    "add_consensus_parser": ("aragora.cli.commands.consensus", "add_consensus_parser"),
    # triage (inbox trust wedge)
    "cmd_triage": ("aragora.cli.commands.triage", "cmd_triage"),
    "add_triage_parser": ("aragora.cli.commands.triage", "add_triage_parser"),
}

__all__ = list(_LAZY_IMPORTS.keys())


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        from importlib import import_module

        module = import_module(module_path)
        value = getattr(module, attr_name)
        # Cache for subsequent access
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
