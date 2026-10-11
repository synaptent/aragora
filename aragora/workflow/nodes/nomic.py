"""
Nomic Loop Step for executing self-improvement cycles within workflows.

Wraps the NomicStateMachine and phase implementations to enable:
- Self-improvement as a workflow step
- Phase-selective execution
- Integration with workflow checkpointing
- Human approval gates for code changes
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from collections.abc import Sequence

from aragora.workflow.step import BaseStep, WorkflowContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Type-only imports for phase classes - using Any at runtime since these may not be available
_PhaseType = Any  # Type alias for phase instances


class NomicLoopStep(BaseStep):
    """
    Workflow step that executes Nomic Loop phases.

    Wraps the NomicStateMachine for self-improvement cycles within workflows.
    Can run a subset of phases or the full cycle.

    Config options:
        cycles: int - Number of nomic cycles to run (default: 1)
        phases: list[str] - Phases to execute (default: all 6)
            Available: context, debate, design, implement, verify, commit
        workspace_id: str - Workspace for knowledge storage
        enable_code_execution: bool - Allow code changes (default: False)
        require_approval: bool - Require human approval for changes (default: True)
        checkpoint_dir: str - Directory for nomic checkpoints
        timeout_seconds: float - Timeout per phase (default: 300)
        recovery_enabled: bool - Enable automatic recovery (default: True)
        max_retries: int - Maximum retries per phase (default: 3)
        agents: list[str] - Agent types for debate (default: ["claude", "gpt4"])

    Usage:
        step = NomicLoopStep(
            name="Self-Improvement Cycle",
            config={
                "cycles": 1,
                "phases": ["context", "debate", "design"],
                "workspace_id": "my_workspace",
                "enable_code_execution": False,
            }
        )
        result = await step.execute(context)
    """

    # Available phases in order
    ALL_PHASES = ["context", "debate", "design", "implement", "verify", "commit"]

    def __init__(self, name: str, config: dict[str, Any] | None = None):
        super().__init__(name, config)
        self._state_machine = None
        self._current_phase_idx = 0
        self._cycle_count = 0

    async def execute(self, context: WorkflowContext) -> Any:
        """Execute the nomic loop step."""
        config = {**self._config, **context.current_step_config}

        # Extract configuration
        cycles = config.get("cycles", 1)
        phases = config.get("phases", self.ALL_PHASES)
        workspace_id = config.get("workspace_id", context.get_input("workspace_id", "default"))
        enable_code_execution = config.get("enable_code_execution", False)
        require_approval = config.get("require_approval", True)
        recovery_enabled = config.get("recovery_enabled", True)
        from aragora.config.settings import get_settings

        agents = config.get("agents", get_settings().agent.default_agent_list)

        # Validate phases
        phases = [p for p in phases if p in self.ALL_PHASES]
        if not phases:
            logger.warning("No valid phases specified, using all phases")
            phases = self.ALL_PHASES

        logger.info(
            "NomicLoopStep '%s' starting: cycles=%s, phases=%s, workspace=%s",
            self.name,
            cycles,
            phases,
            workspace_id,
        )

        try:
            from aragora.agents import create_agent
            from aragora.core_types import Environment
            from aragora.debate.orchestrator import Arena
            from aragora.protocols.debate import DebateProtocol
            from aragora.nomic import NomicState, create_nomic_state_machine
            from aragora.nomic.handlers import (
                create_commit_handler,
                create_context_handler,
                create_debate_handler,
                create_design_handler,
                create_implement_handler,
                create_verify_handler,
            )
            from aragora.nomic.phases import (
                CommitPhase,
                ContextPhase,
                DebateConfig,
                DebatePhase,
                DesignConfig,
                DesignPhase,
                ImplementPhase,
                VerifyPhase,
            )
            from aragora.implement import create_single_task_plan, generate_implement_plan
            from aragora.config.settings import DebateSettings

            def _normalize_agents(value: Any) -> list[str]:
                if isinstance(value, str):
                    return [v.strip() for v in value.split(",") if v.strip()]
                if isinstance(value, Sequence):
                    return [str(v).strip() for v in value if str(v).strip()]
                return []

            def _find_agent(agent_list: list[Any], names: set[str]) -> Any | None:
                for agent in agent_list:
                    name = str(getattr(agent, "name", "")).lower()
                    if name in names:
                        return agent
                return None

            agent_types = _normalize_agents(agents)
            agent_instances: list[Any] = []
            for agent_type in agent_types:
                try:
                    from aragora.agents.base import AgentType as AgentTypeLiteral

                    agent_instances.append(create_agent(cast(AgentTypeLiteral, agent_type)))
                except (ImportError, RuntimeError, ValueError, TypeError, OSError) as exc:
                    logger.warning("Failed to create agent %s: %s", agent_type, exc)

            claude_agent = _find_agent(agent_instances, {"claude", "anthropic-api"})
            if claude_agent is None:
                try:
                    claude_agent = create_agent("claude")
                except (ImportError, RuntimeError, ValueError, TypeError, OSError) as exc:
                    logger.debug("Failed to create claude agent: %s", exc)
                    claude_agent = None

            codex_agent = _find_agent(agent_instances, {"codex", "openai-api"})
            if codex_agent is None:
                try:
                    codex_agent = create_agent("codex")
                except (ImportError, RuntimeError, ValueError, TypeError, OSError) as exc:
                    logger.debug("Failed to create codex agent: %s", exc)
                    codex_agent = None

            if not enable_code_execution:
                phases = [p for p in phases if p in ("context", "debate", "design")]

            repo_path = Path(
                config.get("repo_path") or context.get_input("repo_path") or Path.cwd()
            )

            debate_config: DebateConfig
            try:
                from aragora.nomic.debate_profile import NomicDebateProfile

                profile = NomicDebateProfile.from_env()
                debate_config = profile.to_debate_config()
            except (ImportError, RuntimeError, ValueError, TypeError, OSError) as exc:
                logger.debug("Failed to load debate profile, using defaults: %s", exc)
                debate_config = DebateConfig(rounds=DebateSettings().default_rounds)

            if debate_rounds := config.get("debate_rounds"):
                debate_config.rounds = int(debate_rounds)
            if config.get("consensus_mechanism"):
                debate_config.consensus_mode = str(config.get("consensus_mechanism"))

            async def _generate_implement_plan(design: str, repo: Path):
                try:
                    return await generate_implement_plan(design, repo)
                except (RuntimeError, ValueError, TypeError, OSError, ConnectionError) as exc:
                    logger.warning("Plan generation failed, using fallback: %s", exc)
                    return create_single_task_plan(design, repo)

            results: list[dict[str, Any]] = []
            for cycle in range(cycles):
                self._cycle_count = cycle + 1
                logger.info("Starting nomic cycle %s/%s", cycle + 1, cycles)

                machine = create_nomic_state_machine(
                    checkpoint_dir=config.get("checkpoint_dir"),
                    enable_checkpoints=recovery_enabled,
                    enable_metrics=True,
                )

                context_phase = ContextPhase(
                    aragora_path=repo_path,
                    claude_agent=claude_agent,
                    codex_agent=codex_agent,
                    cycle_count=self._cycle_count,
                    log_fn=logger.info,
                )
                debate_phase = DebatePhase(
                    aragora_path=repo_path,
                    agents=agent_instances,
                    arena_factory=lambda *args, **kwargs: Arena(*args, **kwargs),
                    environment_factory=lambda *args, **kwargs: Environment(*args, **kwargs),
                    protocol_factory=lambda *args, **kwargs: DebateProtocol(*args, **kwargs),
                    config=debate_config,
                    cycle_count=self._cycle_count,
                    log_fn=logger.info,
                )
                design_phase = DesignPhase(
                    aragora_path=repo_path,
                    agents=agent_instances,
                    arena_factory=lambda *args, **kwargs: Arena(*args, **kwargs),
                    environment_factory=lambda *args, **kwargs: Environment(*args, **kwargs),
                    protocol_factory=lambda *args, **kwargs: DebateProtocol(*args, **kwargs),
                    config=DesignConfig(),
                    cycle_count=self._cycle_count,
                    log_fn=logger.info,
                )

                executor: Any = None
                if config.get("use_gastown_executor", True):
                    try:
                        from aragora.nomic.convoy_executor import GastownConvoyExecutor

                        implementers = [a for a in agent_instances if a is not None]
                        for extra in (claude_agent, codex_agent):
                            if extra and extra not in implementers:
                                implementers.append(extra)

                        executor = GastownConvoyExecutor(
                            repo_path=repo_path,
                            implementers=implementers,
                            reviewers=implementers,
                            log_fn=logger.info,
                        )
                    except (ImportError, RuntimeError, ValueError, TypeError, OSError) as exc:
                        logger.warning("Failed to initialize GastownConvoyExecutor: %s", exc)
                        executor = None

                if executor is None:
                    try:
                        from aragora.nomic.implement_executor import ConvoyImplementExecutor

                        implementer_names = [
                            getattr(a, "name", "") for a in agent_instances if a is not None
                        ]

                        def _agent_factory(name: str):
                            for agent in agent_instances:
                                if getattr(agent, "name", "") == name:
                                    return agent
                            return agent_instances[0] if agent_instances else None

                        executor = ConvoyImplementExecutor(
                            aragora_path=repo_path,
                            agents=[n for n in implementer_names if n],
                            agent_factory=_agent_factory if agent_instances else None,
                            max_parallel=4,
                            enable_cross_check=True,
                            log_fn=logger.info,
                        )
                    except (ImportError, RuntimeError, ValueError, TypeError, OSError) as exc:
                        logger.warning("Failed to initialize ConvoyImplementExecutor: %s", exc)
                        executor = None

                implement_phase = ImplementPhase(
                    aragora_path=repo_path,
                    plan_generator=_generate_implement_plan,
                    executor=executor,
                    cycle_count=self._cycle_count,
                    log_fn=logger.info,
                )
                verify_phase = VerifyPhase(
                    aragora_path=repo_path,
                    codex=codex_agent,
                    cycle_count=self._cycle_count,
                    log_fn=logger.info,
                )
                commit_phase = CommitPhase(
                    aragora_path=repo_path,
                    require_human_approval=require_approval,
                    auto_commit=bool(config.get("auto_commit", False)) and not require_approval,
                    cycle_count=self._cycle_count,
                    log_fn=logger.info,
                )

                if "context" in phases:
                    machine.register_handler(
                        NomicState.CONTEXT, create_context_handler(context_phase)
                    )
                if "debate" in phases:
                    machine.register_handler(NomicState.DEBATE, create_debate_handler(debate_phase))
                if "design" in phases:
                    machine.register_handler(NomicState.DESIGN, create_design_handler(design_phase))
                if "implement" in phases:
                    machine.register_handler(
                        NomicState.IMPLEMENT, create_implement_handler(implement_phase)
                    )
                if "verify" in phases:
                    machine.register_handler(
                        NomicState.VERIFY, create_verify_handler(verify_phase, repo_path=repo_path)
                    )
                if "commit" in phases:
                    machine.register_handler(NomicState.COMMIT, create_commit_handler(commit_phase))

                await machine.start(
                    config={
                        "workflow_id": context.workflow_id,
                        "cycle": cycle + 1,
                    }
                )

                phase_results = {
                    "context": machine.context.context_result,
                    "debate": machine.context.debate_result,
                    "design": machine.context.design_result,
                    "implement": machine.context.implement_result,
                    "verify": machine.context.verify_result,
                    "commit": machine.context.commit_result,
                }

                cycle_result: dict[str, Any] = {
                    "cycle": cycle + 1,
                    "phases": {},
                    "success": machine.current_state == NomicState.COMPLETED,
                }

                for phase_name, result in phase_results.items():
                    if phase_name not in phases or result is None:
                        continue
                    cycle_result["phases"][phase_name] = {
                        "success": bool(result.get("success", True)),
                        "result": result,
                    }
                    context.set_state(f"nomic_{phase_name}_result", result)

                if machine.context.errors:
                    cycle_result["success"] = False
                    cycle_result["errors"] = machine.context.errors

                results.append(cycle_result)

                if not cycle_result["success"] and not config.get("continue_on_failure", False):
                    break

            return {
                "cycles_completed": len(results),
                "cycles_requested": cycles,
                "all_successful": all(r["success"] for r in results),
                "results": results,
                "phases_executed": phases,
                "workspace_id": workspace_id,
            }

        except ImportError as e:
            logger.error("Failed to import nomic module: %s", e)
            return {
                "success": False,
                "error": f"Nomic module not available: {e}",
            }

    def _build_phase_context(
        self,
        workflow_context: WorkflowContext,
        cycle_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Build context dict for phase execution."""
        return {
            "workflow_id": workflow_context.workflow_id,
            "workflow_inputs": workflow_context.inputs,
            "workflow_state": workflow_context.state,
            "previous_phases": cycle_result.get("phases", {}),
            "cycle_number": cycle_result.get("cycle", 1),
        }

    async def checkpoint(self) -> dict[str, Any]:
        """Save nomic step state for checkpointing."""
        return {
            "current_phase_idx": self._current_phase_idx,
            "cycle_count": self._cycle_count,
        }

    async def restore(self, state: dict[str, Any]) -> None:
        """Restore nomic step state from checkpoint."""
        self._current_phase_idx = state.get("current_phase_idx", 0)
        self._cycle_count = state.get("cycle_count", 0)

    def validate_config(self) -> bool:
        """Validate nomic step configuration."""
        phases = self._config.get("phases", self.ALL_PHASES)
        if phases:
            invalid_phases = [p for p in phases if p not in self.ALL_PHASES]
            if invalid_phases:
                logger.warning("Invalid phases in config: %s", invalid_phases)
                return False
        return True
