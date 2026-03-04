"""
Debate-related CLI commands and helpers.

Contains the core debate execution logic: agent parsing, debate running,
and the 'ask' command handler.
"""

import argparse
import asyncio
import json
import logging
import math
import os
import signal
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, cast

from aragora.agents.base import AgentType, create_agent
from aragora.agents.spec import AgentSpec
from aragora.config import (
    DEFAULT_AGENTS,
    DEFAULT_CONSENSUS,
    DEFAULT_ROUNDS,
    MAX_AGENTS_PER_DEBATE,
)
from aragora.core import Environment
from aragora.debate.orchestrator import Arena, DebateProtocol
from aragora.memory.store import CritiqueStore
from aragora.modes import ModeRegistry
from aragora.topic_handler import handle_ambiguous_task


logger = logging.getLogger(__name__)

# Default API URL from environment or localhost fallback
DEFAULT_API_URL = os.environ.get("ARAGORA_API_URL", "http://localhost:8080")


class _StrictWallClockTimeout(TimeoutError):
    """Raised when a hard wall-clock timeout expires."""


@contextmanager
def _strict_wall_clock_timeout(timeout_seconds: float):
    """Enforce a hard wall-clock timeout using SIGALRM when available.

    Falls back to a no-op context on platforms/threads where SIGALRM is unavailable.
    """
    if timeout_seconds <= 0:
        yield
        return

    if not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer: tuple[float, float] | None = None

    def _on_timeout(_signum: int, _frame: Any) -> None:
        raise _StrictWallClockTimeout(f"strict wall-clock timeout after {timeout_seconds:.2f}s")

    try:
        signal.signal(signal.SIGALRM, _on_timeout)
        if hasattr(signal, "setitimer") and hasattr(signal, "ITIMER_REAL"):
            previous_timer = signal.getitimer(signal.ITIMER_REAL)
            signal.setitimer(signal.ITIMER_REAL, float(timeout_seconds))
        else:
            signal.alarm(max(1, math.ceil(timeout_seconds)))
        yield
    finally:
        if hasattr(signal, "setitimer") and hasattr(signal, "ITIMER_REAL"):
            signal.setitimer(signal.ITIMER_REAL, 0.0)
        else:
            signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
        if (
            previous_timer is not None
            and hasattr(signal, "setitimer")
            and hasattr(signal, "ITIMER_REAL")
        ):
            remaining, interval = previous_timer
            if remaining > 0 or interval > 0:
                signal.setitimer(signal.ITIMER_REAL, remaining, interval)


def get_event_emitter_if_available(server_url: str = DEFAULT_API_URL) -> Any | None:
    """
    Try to connect to the streaming server for audience participation.
    Returns event emitter if server is available, None otherwise.
    """
    try:
        import urllib.request

        # Quick health check
        with urllib.request.urlopen(f"{server_url}/api/health", timeout=2) as resp:  # noqa: S310 -- local server health check
            status_code = getattr(resp, "status", None) or resp.getcode()
            if status_code == 200:
                # Server is up, try to get emitter
                try:
                    from aragora.server.stream import SyncEventEmitter

                    return SyncEventEmitter()
                except ImportError:
                    pass
    except (OSError, TimeoutError):
        # Server not available - network error, timeout, or connection refused
        pass
    return None


def parse_agents(agents_str: str) -> list[AgentSpec]:
    """Parse agent string using unified AgentSpec.

    Supports both formats:
    - New pipe format: provider|model|persona|role (explicit fields)
    - Legacy colon format: provider:role or provider:persona

    Args:
        agents_str: Comma-separated agent specs

    Returns:
        List of AgentSpec objects with all parsed fields
    """
    from aragora.agents.spec import AgentSpec

    return AgentSpec.coerce_list(agents_str, warn=False)


def _split_agents_list(agents_str: str) -> list[str]:
    """Split comma-separated agents string into a clean list."""
    if not agents_str:
        return []
    return [agent.strip() for agent in agents_str.split(",") if agent.strip()]


def _agent_names_for_graph_matrix(agents_str: str) -> list[str]:
    """Resolve agent names for graph/matrix debates (provider-only)."""
    try:
        specs = parse_agents(agents_str)
        return [spec.provider for spec in specs if spec.provider]
    except (ValueError, AttributeError, TypeError):
        return _split_agents_list(agents_str)


def _agents_payload_for_api(agents_str: str) -> list[Any]:
    """Build API payload for agents (strings or dicts) from CLI input."""
    try:
        specs = parse_agents(agents_str)
    except (ValueError, AttributeError, TypeError):
        return _split_agents_list(agents_str)

    if not specs:
        return []

    advanced = any(
        spec.model or spec.persona or spec.role or spec.name or spec.hierarchy_role
        for spec in specs
    )
    if not advanced:
        return [spec.provider for spec in specs if spec.provider]

    payload: list[dict[str, Any]] = []
    for spec in specs:
        item: dict[str, Any] = {"provider": spec.provider}
        if spec.model:
            item["model"] = spec.model
        if spec.persona:
            item["persona"] = spec.persona
        if spec.role:
            item["role"] = spec.role
        if spec.name:
            item["name"] = spec.name
        if spec.hierarchy_role:
            item["hierarchy_role"] = spec.hierarchy_role
        payload.append(item)
    return payload


def _is_server_available(server_url: str) -> bool:
    """Check if the API server is reachable."""
    try:
        import urllib.request

        with urllib.request.urlopen(f"{server_url}/api/health", timeout=2) as resp:  # noqa: S310 -- local server health check
            status_code = getattr(resp, "status", None) or resp.getcode()
            return status_code == 200
    except (OSError, TimeoutError):
        return False


def _build_api_client(server_url: str, api_key: str | None):
    """Build an AragoraClient for API-backed runs."""
    from aragora.client import AragoraClient

    return AragoraClient(base_url=server_url, api_key=api_key)


def _parse_matrix_scenarios(raw: list[str] | None) -> list[dict[str, Any]]:
    """Parse matrix scenario CLI inputs into structured dicts."""
    scenarios: list[dict[str, Any]] = []
    for item in raw or []:
        value = str(item).strip()
        if not value:
            continue
        if value.startswith("{") or value.startswith("["):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid scenario JSON: {e}")
            if isinstance(parsed, list):
                scenarios.extend([s for s in parsed if isinstance(s, dict)])
            elif isinstance(parsed, dict):
                scenarios.append(parsed)
            else:
                raise ValueError("Scenario JSON must be an object or list of objects")
        else:
            scenarios.append({"name": value})
    return scenarios


def _parse_auto_select_config(raw: str | None) -> dict[str, Any] | None:
    """Parse auto-select config JSON string into a dict."""
    if not raw:
        return None
    value = str(raw).strip()
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid auto-select config JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError("Auto-select config must be a JSON object")
    return parsed


def _append_context_file(context: str, context_file: str) -> str:
    """Read a file and append its content to the context string."""
    from pathlib import Path

    path = Path(context_file)
    if not path.is_file():
        raise ValueError(f"Context file not found: {context_file}")
    content = path.read_text(encoding="utf-8")
    if context:
        return f"{context}\n\n--- Context from {path.name} ---\n{content}"
    return content


def _cleanup_cli_subprocesses_for_timeout() -> dict[str, int]:
    """Best-effort cleanup for CLI subprocesses after timeout."""
    try:
        from aragora.agents.cli_agents import terminate_tracked_cli_processes

        return terminate_tracked_cli_processes()
    except Exception as e:  # noqa: BLE001 - timeout cleanup must never crash CLI
        logger.warning("Failed to clean up tracked CLI subprocesses: %s", e)
        return {"tracked": 0, "terminated": 0, "killed": 0, "remaining": 0}


def _emit_timeout_failure_payload(
    *,
    error_type: str,
    timeout_seconds: int,
    elapsed_seconds: float,
    task: str,
    agents_str: str,
    mode: str | None,
    cleanup: dict[str, int],
) -> None:
    """Emit machine-parseable timeout payload for benchmark/scoring harnesses."""
    task_value = str(task or "")
    payload = {
        "status": "timeout",
        "error_type": error_type,
        "timeout_seconds": int(timeout_seconds),
        "elapsed_seconds": round(max(0.0, float(elapsed_seconds)), 3),
        "task_preview": task_value[:240],
        "task_length": len(task_value),
        "agents": _split_agents_list(agents_str),
        "mode": mode or "default",
        "cleanup": cleanup,
        "final_answer": "",
    }
    encoded = json.dumps(payload, sort_keys=True)
    print(f"ARAGORA_TIMEOUT_JSON={encoded}")

    report_path_raw = os.environ.get("ARAGORA_ASK_TIMEOUT_REPORT_PATH")
    if report_path_raw:
        try:
            Path(report_path_raw).expanduser().write_text(encoded + "\n", encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to write timeout report %s: %s", report_path_raw, e)


def _looks_like_self_improvement_task(task: str) -> bool:
    """Heuristic detection for codebase self-improvement prompts."""
    lowered = (task or "").lower()
    keywords = (
        "improve",
        "improvement",
        "self-improve",
        "self improvement",
        "refactor",
        "codebase",
        "aragora",
        "architecture",
        "module",
        "component",
        "dogfood",
        "pipeline",
        "orchestration",
    )
    return any(token in lowered for token in keywords)


def _parse_document_ids(
    document: str | None,
    documents: str | None,
) -> list[str]:
    """Parse document ID arguments into a list of document IDs."""
    result: list[str] = []
    if document:
        result.append(document.strip())
    if documents:
        for doc in documents.split(","):
            doc = doc.strip()
            if doc and doc not in result:
                result.append(doc)
    return result


def _auto_select_agents_local(task: str, config: dict[str, Any] | None) -> str | None:
    """Run local auto-selection using server selection logic (best-effort)."""
    try:
        from aragora.server.agent_selection import auto_select_agents

        return auto_select_agents(task, config or {})
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Auto-select failed: %s", e)
        return None


def _maybe_add_vertical_specialist_local(
    task: str,
    agents: list[Any],
    enable_verticals: bool,
    vertical_id: str | None,
) -> list[Any]:
    """Optionally inject a vertical specialist into a local debate run."""
    if not enable_verticals:
        return agents

    try:
        import aragora.verticals.specialists  # noqa: F401
        from aragora.verticals.registry import VerticalRegistry
    except ImportError:
        logger.debug("Verticals registry not available; skipping specialist injection")
        return agents

    resolved_vertical = vertical_id or VerticalRegistry.get_for_task(task)
    if not resolved_vertical:
        logger.debug("No matching vertical found for task; skipping specialist injection")
        return agents

    for agent in agents:
        if getattr(agent, "vertical_id", None) == resolved_vertical:
            return agents

    if len(agents) >= MAX_AGENTS_PER_DEBATE:
        logger.info(
            "Skipping vertical specialist (%s): max agents limit reached (%s)",
            resolved_vertical,
            MAX_AGENTS_PER_DEBATE,
        )
        return agents

    try:
        specialist = VerticalRegistry.create_specialist(
            vertical_id=resolved_vertical,
            name=f"{resolved_vertical}_specialist",
            role="critic",
        )
        try:
            specialist.system_prompt = specialist.build_system_prompt()
        except (AttributeError, TypeError, ValueError):
            logger.debug(
                "Failed to build system prompt for specialist %s", resolved_vertical, exc_info=True
            )
        agents.append(specialist)
        print(f"[verticals] Injected specialist: {resolved_vertical}")
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Failed to create vertical specialist %s: %s", resolved_vertical, e)

    return agents


def _print_debate_result(debate: Any, verbose: bool = False) -> None:
    """Print a standard debate result summary."""
    final_answer = None
    dissenting_agents: list[str] = []
    if getattr(debate, "consensus", None):
        final_answer = debate.consensus.final_answer
        dissenting_agents = debate.consensus.dissenting_agents

    print("\n" + "=" * 60)
    print("FINAL ANSWER:")
    print("=" * 60)
    if final_answer:
        print(final_answer)
    else:
        print(f"Debate completed with status: {getattr(debate, 'status', 'unknown')}")

    if verbose and dissenting_agents:
        print("\n" + "-" * 60)
        print("DISSENTING AGENTS:")
        for agent in dissenting_agents:
            print(f"- {agent}")


def _print_graph_result(debate: Any, verbose: bool = False) -> None:
    """Print a graph debate result summary."""
    branches = getattr(debate, "branches", []) or []
    consensus = getattr(debate, "consensus", None)
    status = getattr(debate, "status", "unknown")
    if hasattr(status, "value"):
        status = status.value

    print("\n" + "=" * 60)
    print("GRAPH DEBATE RESULT:")
    print("=" * 60)
    print(f"Status: {status}")
    if getattr(debate, "branch_count", None) is not None:
        print(f"Branches: {getattr(debate, 'branch_count')}")
    else:
        print(f"Branches: {len(branches)}")
    if getattr(debate, "node_count", None) is not None:
        print(f"Nodes: {getattr(debate, 'node_count')}")

    if consensus and consensus.final_answer:
        print("\n" + "-" * 60)
        print("CONSENSUS:")
        print(consensus.final_answer)

    if verbose and branches:
        print("\n" + "-" * 60)
        print("BRANCHES:")
        for branch in branches:
            if isinstance(branch, dict):
                name = branch.get("name", "")
                nodes = branch.get("nodes", []) or []
                branch_id = branch.get("branch_id") or branch.get("id") or ""
            else:
                name = getattr(branch, "name", "")
                nodes = getattr(branch, "nodes", []) or []
                branch_id = getattr(branch, "branch_id", "")
            node_count = len(nodes)
            print(f"- {name or branch_id} ({node_count} nodes)")


def _print_matrix_result(debate: Any, verbose: bool = False) -> None:
    """Print a matrix debate result summary."""
    scenarios = getattr(debate, "scenarios", None) or getattr(debate, "results", None) or []
    conclusions = getattr(debate, "conclusions", None)
    status = getattr(debate, "status", "unknown")
    if hasattr(status, "value"):
        status = status.value

    print("\n" + "=" * 60)
    print("MATRIX DEBATE RESULT:")
    print("=" * 60)
    print(f"Status: {status}")
    print(f"Scenarios: {len(scenarios)}")

    if conclusions:
        if conclusions.universal:
            print("\n" + "-" * 60)
            print("UNIVERSAL CONCLUSIONS:")
            for item in conclusions.universal:
                print(f"- {item}")
        if conclusions.conditional:
            print("\n" + "-" * 60)
            print("CONDITIONAL CONCLUSIONS:")
            for scenario, items in conclusions.conditional.items():
                print(f"{scenario}:")
                for item in items:
                    print(f"- {item}")
        if conclusions.contradictions:
            print("\n" + "-" * 60)
            print("CONTRADICTIONS:")
            for item in conclusions.contradictions:
                print(f"- {item}")
    else:
        universal = getattr(debate, "universal_conclusions", []) or []
        conditional = getattr(debate, "conditional_conclusions", {}) or {}
        if universal:
            print("\n" + "-" * 60)
            print("UNIVERSAL CONCLUSIONS:")
            for item in universal:
                print(f"- {item}")
        if conditional:
            print("\n" + "-" * 60)
            print("CONDITIONAL CONCLUSIONS:")
            if isinstance(conditional, dict):
                for scenario, items in conditional.items():
                    print(f"{scenario}:")
                    for item in items:
                        print(f"- {item}")
            else:
                for item in conditional:
                    if isinstance(item, dict):
                        condition = item.get("condition") or item.get("scenario")
                        conclusion = item.get("conclusion")
                        confidence = item.get("confidence")
                        if condition:
                            print(f"{condition}:")
                        if conclusion:
                            suffix = (
                                f" (confidence {confidence:.2f})" if confidence is not None else ""
                            )
                            print(f"- {conclusion}{suffix}")
                    else:
                        print(f"- {item}")

    if verbose and scenarios:
        print("\n" + "-" * 60)
        print("SCENARIO RESULTS:")
        for scenario in scenarios:
            if isinstance(scenario, dict):
                name = scenario.get("scenario_name") or scenario.get("name", "")
                key_findings = scenario.get("key_findings") or scenario.get("key_claims") or []
                conclusion = scenario.get("conclusion")
            else:
                name = getattr(scenario, "scenario_name", "")
                key_findings = getattr(scenario, "key_findings", []) or []
                conclusion = getattr(scenario, "consensus", None)
                if hasattr(conclusion, "final_answer"):
                    conclusion = conclusion.final_answer

            print(f"- {name}")
            if conclusion:
                print(f"  Conclusion: {conclusion}")
            if key_findings:
                for finding in key_findings:
                    print(f"  {finding}")


def _print_decision_integrity_summary(package: dict[str, Any]) -> None:
    """Print a decision integrity package summary."""
    receipt = package.get("receipt") or {}
    plan = package.get("plan") or package.get("decision_plan") or {}
    receipt_id = package.get("receipt_id") or receipt.get("receipt_id") or receipt.get("id")
    plan_id = package.get("plan_id") or plan.get("id")
    approval = package.get("approval") or {}
    execution = package.get("execution") or package.get("workflow_execution") or {}

    print("\n" + "=" * 60)
    print("DECISION INTEGRITY PACKAGE")
    print("=" * 60)
    if receipt_id:
        print(f"Receipt ID: {receipt_id}")
    if plan_id:
        print(f"Plan ID: {plan_id}")
    if approval:
        status = approval.get("status") or approval.get("approval_status")
        if status:
            print(f"Approval: {status}")
    if execution:
        status = execution.get("status")
        if status:
            print(f"Execution: {status}")


def _run_debate_api(
    server_url: str,
    api_key: str | None,
    task: str,
    agents: list[Any],
    rounds: int,
    consensus: str,
    context: str | None,
    metadata: dict[str, Any],
    auto_select: bool | None,
    auto_select_config: dict[str, Any] | None,
    enable_verticals: bool,
    vertical_id: str | None,
    timeout_seconds: int,
) -> Any:
    """Run a standard debate via API and wait for completion."""
    client = _build_api_client(server_url, api_key)
    return client.debates.run(
        task=task,
        agents=agents,
        rounds=rounds,
        consensus=consensus,
        timeout=timeout_seconds,
        context=context,
        auto_select=auto_select,
        auto_select_config=auto_select_config,
        enable_verticals=enable_verticals,
        vertical_id=vertical_id,
        metadata=metadata,
    )


def _run_graph_debate_api(
    server_url: str,
    api_key: str | None,
    task: str,
    agents: list[str],
    max_rounds: int,
    branch_threshold: float,
    max_branches: int,
    timeout_seconds: int,
    verbose: bool = False,
) -> Any:
    """Run a graph debate via API and wait for completion."""
    from aragora.client.models import DebateStatus

    client = _build_api_client(server_url, api_key)
    response = client.graph_debates.create(
        task=task,
        agents=agents,
        max_rounds=max_rounds,
        branch_threshold=branch_threshold,
        max_branches=max_branches,
    )
    if getattr(response, "graph", None) or getattr(response, "branches", None):
        return response
    debate_id = response.debate_id

    start = time.time()
    while time.time() - start < timeout_seconds:
        debate = client.graph_debates.get(debate_id)
        if debate.status in (
            DebateStatus.COMPLETED,
            DebateStatus.FAILED,
            DebateStatus.CANCELLED,
        ):
            return debate
        if verbose:
            print(f"[graph] {debate_id} status={debate.status}")
        time.sleep(2)

    raise TimeoutError(f"Graph debate {debate_id} did not complete within timeout")


def _run_matrix_debate_api(
    server_url: str,
    api_key: str | None,
    task: str,
    agents: list[str],
    scenarios: list[dict[str, Any]],
    max_rounds: int,
    timeout_seconds: int,
    verbose: bool = False,
) -> Any:
    """Run a matrix debate via API and wait for completion."""
    from aragora.client.models import DebateStatus

    client = _build_api_client(server_url, api_key)
    response = client.matrix_debates.create(
        task=task,
        agents=agents,
        scenarios=scenarios,
        max_rounds=max_rounds,
    )
    if getattr(response, "results", None) or getattr(response, "universal_conclusions", None):
        return response
    matrix_id = response.matrix_id

    start = time.time()
    while time.time() - start < timeout_seconds:
        debate = client.matrix_debates.get(matrix_id)
        if debate.status in (
            DebateStatus.COMPLETED,
            DebateStatus.FAILED,
            DebateStatus.CANCELLED,
        ):
            return debate
        if verbose:
            print(f"[matrix] {matrix_id} status={debate.status}")
        time.sleep(2)

    raise TimeoutError(f"Matrix debate {matrix_id} did not complete within timeout")


def _build_decision_integrity_api(
    server_url: str,
    api_key: str | None,
    debate_id: str,
    *,
    include_context: bool = False,
    plan_strategy: str = "single_task",
    execution_mode: str | None = None,
) -> dict[str, Any]:
    """Build a decision integrity package via API."""
    client = _build_api_client(server_url, api_key)
    return client.debates.decision_integrity(
        debate_id=debate_id,
        include_context=include_context,
        plan_strategy=plan_strategy,
        execution_mode=execution_mode,
    )


def _build_decision_integrity_local(
    result: Any,
    *,
    include_context: bool = False,
    plan_strategy: str = "single_task",
) -> dict[str, Any]:
    """Build a decision integrity package locally from a DebateResult."""
    from aragora.pipeline.decision_integrity import build_decision_integrity_package

    if hasattr(result, "to_dict"):
        debate_payload = result.to_dict()
    else:
        debate_payload = {
            "debate_id": getattr(result, "debate_id", ""),
            "task": getattr(result, "task", ""),
            "final_answer": getattr(result, "final_answer", ""),
            "confidence": getattr(result, "confidence", 0.0),
            "consensus_reached": getattr(result, "consensus_reached", False),
            "rounds_used": getattr(result, "rounds_used", 0),
            "participants": getattr(result, "participants", []),
        }

    package = asyncio.run(
        build_decision_integrity_package(
            debate_payload,
            include_context=include_context,
            plan_strategy=plan_strategy,
        )
    )
    return package.to_dict()


async def run_debate(
    task: str,
    agents_str: str,
    rounds: int = DEFAULT_ROUNDS,  # 9-round format (0-8) default
    consensus: str = DEFAULT_CONSENSUS,  # Judge-based consensus default
    context: str = "",
    learn: bool = True,
    db_path: str = "agora_memory.db",
    enable_audience: bool = True,
    server_url: str = DEFAULT_API_URL,
    protocol_overrides: dict[str, Any] | None = None,
    mode: str | None = None,
    enable_verticals: bool = False,
    vertical_id: str | None = None,
    auto_select: bool = False,
    auto_select_config: dict[str, Any] | None = None,
    codebase_context: bool = False,
    codebase_context_path: str | None = None,
    offline: bool = False,
    **kwargs: Any,
):
    """Run a decision stress-test (debate engine)."""
    from aragora.utils.env import is_offline_mode

    offline = offline or is_offline_mode()
    if offline:
        # Offline mode should be network-free and quiet.
        enable_audience = False
        learn = False

    # Get mode system prompt if specified
    mode_system_prompt = ""
    if mode:
        from aragora.modes import load_builtins

        load_builtins()
        mode_obj = ModeRegistry.get(mode)
        if mode_obj:
            mode_system_prompt = mode_obj.get_system_prompt()
            print(f"[mode] Using '{mode}' mode - {mode_obj.description}")
        else:
            available = ", ".join(ModeRegistry.list_all())
            raise KeyError(f"Mode '{mode}' not found. Available: {available}")

    # Auto-select agents if requested and no explicit list provided
    if auto_select:
        if agents_str and agents_str != DEFAULT_AGENTS:
            print("Warning: --auto-select ignores explicit --agents", file=sys.stderr)
        if not agents_str or agents_str == DEFAULT_AGENTS:
            selected = _auto_select_agents_local(task, auto_select_config)
            if selected:
                agents_str = selected
                print(f"[auto-select] Selected agents: {agents_str}")
            else:
                agents_str = DEFAULT_AGENTS

    if codebase_context and "## CODEBASE INVENTORY" not in context:
        from aragora.debate.codebase_context import build_static_inventory

        inventory = build_static_inventory(codebase_context_path or os.getcwd())
        if inventory:
            context = f"{context}\n\n{inventory}" if context else inventory

    # Parse and create agents
    agent_specs = parse_agents(agents_str)

    # Assign default roles based on position if not explicitly specified
    agents = []
    failed_agents: list[str] = []
    for i, spec in enumerate(agent_specs):
        role = spec.role
        # If role is None (not explicitly specified), assign based on position
        # This ensures diverse debate roles: proposer, critic(s), synthesizer
        if role is None:
            if i == 0:
                role = "proposer"
            elif i == len(agent_specs) - 1 and len(agent_specs) > 1:
                role = "synthesizer"
            else:
                role = "critic"

        try:
            agent = create_agent(
                model_type=cast(AgentType, spec.provider),
                name=spec.name or f"{spec.provider}_{role}",
                role=role,
                model=spec.model,  # Pass model from spec
            )
        except (ValueError, ImportError, RuntimeError) as e:
            failed_agents.append(f"{spec.provider} ({e})")
            continue

        # Apply persona as system prompt if specified
        if spec.persona:
            try:
                from aragora.agents.personas import DEFAULT_PERSONAS

                if spec.persona in DEFAULT_PERSONAS:
                    p = DEFAULT_PERSONAS[spec.persona]
                    traits_str = ", ".join(p.traits) if p.traits else "analytical"
                    persona_prompt = f"You are a {traits_str} agent. {p.description}"
                    if p.top_expertise:
                        top_domains = [d for d, _ in p.top_expertise]
                        persona_prompt += f" Your key areas of expertise: {', '.join(top_domains)}."
                    existing = getattr(agent, "system_prompt", "") or ""
                    agent.system_prompt = f"{persona_prompt}\n\n{existing}".strip()

                    # Apply generation parameters from persona
                    if hasattr(agent, "set_generation_params"):
                        agent.set_generation_params(
                            temperature=p.temperature,
                            top_p=p.top_p,
                            frequency_penalty=p.frequency_penalty,
                        )
                else:
                    # Use persona name as a behavioral hint
                    existing = getattr(agent, "system_prompt", "") or ""
                    agent.system_prompt = (
                        f"You are a {spec.persona} in this debate. "
                        f"Approach arguments from that perspective.\n\n{existing}"
                    ).strip()
            except ImportError:
                pass  # Personas module not available

        # Apply mode system prompt if specified (takes precedence)
        if mode_system_prompt:
            agent.system_prompt = mode_system_prompt

        agents.append(agent)

    if failed_agents:
        print(
            f"Warning: {len(failed_agents)} agent(s) unavailable:",
            file=sys.stderr,
        )
        for fa in failed_agents:
            print(f"  - {fa}", file=sys.stderr)
    if not agents:
        print(
            "Error: No agents available. Set at least one API key.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if len(agents) < 2:
        print(
            f"Warning: Only {len(agents)} agent available. "
            "Multi-agent debate requires 2+ agents for meaningful consensus.",
            file=sys.stderr,
        )

    agents = _maybe_add_vertical_specialist_local(
        task=task,
        agents=agents,
        enable_verticals=enable_verticals,
        vertical_id=vertical_id,
    )

    # Create environment
    env = Environment(
        task=task,
        context=context,
        max_rounds=rounds,
    )

    # Create protocol
    consensus_type = cast(
        Literal[
            "majority",
            "unanimous",
            "judge",
            "none",
            "weighted",
            "supermajority",
            "any",
            "byzantine",
        ],
        consensus,
    )
    protocol = DebateProtocol(
        rounds=rounds,
        consensus=consensus_type,
        **(protocol_overrides or {}),
    )

    # Create memory store
    memory = CritiqueStore(db_path) if learn else None

    # Try to get event emitter for audience participation
    event_emitter = None
    if enable_audience:
        event_emitter = get_event_emitter_if_available(server_url)
        if event_emitter:
            print("[audience] Connected to streaming server - audience participation enabled")

    # Run debate
    auto_explain = kwargs.pop("auto_explain", False)
    # Pop kwargs that are set on Arena post-init, not accepted by __init__
    enable_cartographer = kwargs.pop("enable_cartographer", None)
    enable_introspection = kwargs.pop("enable_introspection", None)
    arena_kwargs: dict[str, Any] = dict(kwargs)
    if offline:
        arena_kwargs.update(
            {
                # Disable subsystems that can initialize adapters / embeddings or
                # attempt network calls in local demo/offline runs.
                "knowledge_mound": None,
                "auto_create_knowledge_mound": False,
                "enable_knowledge_retrieval": False,
                "enable_knowledge_ingestion": False,
                "enable_cross_debate_memory": False,
                # Avoid RLM-based compression and related model calls.
                "use_rlm_limiter": False,
                # Disable ML / quality-gate components that may rely on API agents.
                "enable_ml_delegation": False,
                "enable_quality_gates": False,
                "enable_consensus_estimation": False,
            }
        )

    arena = Arena(
        env,
        agents,
        protocol,
        memory=memory,
        event_emitter=event_emitter,
        **arena_kwargs,
    )

    # Apply post-init configuration flags
    if enable_cartographer is not None:
        setattr(arena, "enable_cartographer", enable_cartographer)  # type: ignore[attr-defined]
    if enable_introspection is not None:
        setattr(arena, "enable_introspection", enable_introspection)

    # Enable auto-explanation if requested
    if auto_explain and hasattr(arena, "extensions") and arena.extensions is not None:
        arena.extensions.auto_explain = True

    result = await arena.run()

    # Store result
    if memory:
        memory.store_debate(result)

    return result


def cmd_ask(args: argparse.Namespace) -> None:
    """Handle 'ask' command."""
    logger.debug("Initial task: '%s', context: '%s'", args.task, args.context)
    task = args.task
    raw_task = task
    context = args.context or ""

    # Ambiguity handling
    if len(task.split()) < 3:
        task_brief = handle_ambiguous_task(task)
        task = task_brief.goal  # type: ignore[attr-defined]  # The core goal is now the task
        context += f"\n\n--- Structured Task Brief (Confidence: {task_brief.confidence:.2f}) ---\n"
        objective = getattr(task_brief, "objective", None)
        if objective:
            context += f"Objective: {objective}\n"
        if task_brief.assumptions:  # type: ignore[attr-defined]
            context += "Assumptions:\n" + "\n".join(f"- {a}" for a in task_brief.assumptions)
        # Non-goals and evaluation_criteria are not in V1, but check defensively
        if getattr(task_brief, "non_goals", []):
            context += "\nNon-Goals:\n" + "\n".join(
                f"- {ng}" for ng in getattr(task_brief, "non_goals", [])
            )
        if getattr(task_brief, "success_criteria", []):
            context += "\nSuccess Criteria:\n" + "\n".join(
                f"- {sc}" for sc in task_brief.success_criteria
            )
        context += "\n--------------------------\n"
        if task_brief.requires_user_confirmation:
            logger.info(
                "This task was interpreted from an ambiguous input and requires confirmation."
            )

    explicit_codebase_context = bool(getattr(args, "codebase_context", False))
    mode_name = str(getattr(args, "mode", "") or "").strip().lower()
    inferred_codebase_context = mode_name == "orchestrator" or _looks_like_self_improvement_task(
        raw_task
    )
    codebase_context_requested = explicit_codebase_context or inferred_codebase_context
    codebase_context_repo: Path | None = None
    if codebase_context_requested:
        from aragora.debate.codebase_context import build_static_inventory
        from aragora.debate.context_engineering import (
            ContextEngineeringConfig,
            build_debate_context_engineering,
        )

        repo_raw = getattr(args, "codebase_context_path", None) or os.getcwd()
        codebase_context_repo = Path(str(repo_raw)).expanduser().resolve()
        if args.verbose and not explicit_codebase_context:
            print(
                "[context-engineering] auto-enabled codebase context"
                f" reason={'mode=orchestrator' if mode_name == 'orchestrator' else 'self-improvement task heuristic'}",
                file=sys.stderr,
            )

        static_inventory = build_static_inventory(
            repo_root=str(codebase_context_repo),
            max_chars=max(
                8_000, int(getattr(args, "codebase_context_inventory_max_chars", 20_000))
            ),
        )
        if static_inventory:
            context = f"{context}\n\n{static_inventory}" if context else static_inventory
            if args.verbose:
                print(
                    f"[context-engineering] static inventory injected chars={len(static_inventory)}",
                    file=sys.stderr,
                )

        cfg = ContextEngineeringConfig(
            task=task,
            repo_path=codebase_context_repo,
            include_tests=not bool(getattr(args, "codebase_context_exclude_tests", False)),
            include_rlm_full_corpus=bool(getattr(args, "codebase_context_rlm", False)),
            include_harness_exploration=bool(getattr(args, "codebase_context_harnesses", False)),
            include_kilocode=bool(getattr(args, "codebase_context_kilocode", False)),
            max_output_chars=max(8_000, int(getattr(args, "codebase_context_max_chars", 80_000))),
            build_timeout_seconds=max(30, int(getattr(args, "codebase_context_timeout", 240))),
            per_explorer_timeout_seconds=max(
                15, min(240, int(getattr(args, "codebase_context_timeout", 240)))
            ),
        )

        if args.verbose:
            print(
                "[context-engineering] building"
                f" repo={codebase_context_repo}"
                f" harnesses={'on' if cfg.include_harness_exploration else 'off'}"
                f" kilocode={'on' if cfg.include_kilocode else 'off'}"
                f" rlm={'on' if cfg.include_rlm_full_corpus else 'off'}"
                f" timeout={cfg.build_timeout_seconds}s",
                file=sys.stderr,
            )

        try:
            engineered = asyncio.run(build_debate_context_engineering(cfg))
        except Exception as e:  # noqa: BLE001 - best-effort pre-debate enrichment
            print(f"[context-engineering] failed: {e}", file=sys.stderr)
        else:
            engineered_context = (engineered.context or "").strip()
            harness_meta = (
                engineered.metadata.get("harnesses", {})
                if isinstance(engineered.metadata, dict)
                else {}
            )
            harness_errors = (
                harness_meta.get("errors", []) if isinstance(harness_meta, dict) else []
            )
            timeout_errors = [
                str(err) for err in harness_errors if "timeout after" in str(err).lower()
            ]
            if timeout_errors:
                print(
                    f"[context-engineering] explorer timeouts={len(timeout_errors)} "
                    f"(per_explorer_timeout={cfg.per_explorer_timeout_seconds}s)",
                    file=sys.stderr,
                )

            if engineered_context:
                if context:
                    context = f"{context}\n\n{engineered_context}"
                else:
                    context = engineered_context
                if args.verbose:
                    duration = engineered.metadata.get("duration_seconds", "n/a")
                    print(
                        f"[context-engineering] injected chars={len(engineered_context)}"
                        f" duration={duration}s",
                        file=sys.stderr,
                    )
                output_path_raw = getattr(args, "codebase_context_out", None)
                if output_path_raw:
                    output_path = Path(str(output_path_raw)).expanduser().resolve()
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(engineered_context, encoding="utf-8")
                    if args.verbose:
                        print(
                            f"[context-engineering] wrote={output_path}",
                            file=sys.stderr,
                        )
            elif args.verbose:
                reason = engineered.metadata.get("error", "empty_context")
                print(
                    f"[context-engineering] no context injected ({reason})",
                    file=sys.stderr,
                )

    agents = args.agents
    rounds = args.rounds
    learn = args.learn
    enable_audience = True
    protocol_overrides: dict[str, Any] = {}

    # Apply cross-pollination feature flags
    if not getattr(args, "calibration", True):
        protocol_overrides["enable_calibration"] = False
    if not getattr(args, "evidence_weighting", True):
        protocol_overrides["enable_evidence_weighting"] = False
    if not getattr(args, "trending", True):
        protocol_overrides["enable_trending_injection"] = False
    # Note: ELO weighting is controlled via WeightCalculatorConfig, passed via protocol

    # Demo mode forces local execution
    force_local = False
    if getattr(args, "demo", False):
        print("Demo mode enabled - using built-in demo agents.")
        # Demo mode is meant to be network-free; align with the global offline flag
        # so subsystems can short-circuit consistently.
        os.environ.setdefault("ARAGORA_OFFLINE", "1")
        agents = "demo,demo,demo"
        rounds = min(args.rounds, 2)
        learn = False
        enable_audience = False
        force_local = True
        protocol_overrides.update(
            {
                "convergence_detection": False,
                "vote_grouping": False,
                "enable_trickster": False,
                "enable_research": False,
                "enable_rhetorical_observer": False,
                "role_rotation": False,
                "role_matching": False,
                # Keep demo/local mode network-free and deterministic.
                "enable_trending_injection": False,
                "enable_llm_question_classification": False,
                "enable_llm_synthesis": False,
            }
        )

    from aragora.utils.env import is_offline_mode

    offline = is_offline_mode()
    if offline:
        enable_audience = False
        learn = False
        protocol_overrides.update(
            {
                "enable_trending_injection": False,
                "enable_llm_question_classification": False,
                "enable_llm_synthesis": False,
                "enable_research": False,
            }
        )

    server_url = getattr(args, "api_url", DEFAULT_API_URL)
    api_key = (
        getattr(args, "api_key", None)
        or os.environ.get("ARAGORA_API_TOKEN")
        or os.environ.get("ARAGORA_API_KEY")
    )

    requested_api = getattr(args, "api", False)
    requested_local = getattr(args, "local", False)
    graph_mode = getattr(args, "graph", False)
    matrix_mode = getattr(args, "matrix", False)
    decision_integrity = bool(getattr(args, "decision_integrity", False))
    auto_select = bool(getattr(args, "auto_select", False))
    try:
        auto_select_config = _parse_auto_select_config(getattr(args, "auto_select_config", None))
    except ValueError as e:
        print(f"Invalid --auto-select-config: {e}", file=sys.stderr)
        raise SystemExit(2)
    if auto_select_config and not auto_select:
        auto_select = True

    enable_verticals = bool(
        getattr(args, "enable_verticals", False) or getattr(args, "vertical", None)
    )
    vertical_id = getattr(args, "vertical", None)
    default_timeout = int(os.environ.get("ARAGORA_ASK_TIMEOUT_SECONDS", "3600"))
    debate_timeout = int(getattr(args, "timeout", default_timeout) or default_timeout)
    protocol_overrides.setdefault("timeout_seconds", debate_timeout)
    protocol_overrides.setdefault(
        "debate_rounds_timeout_seconds",
        max(300, min(debate_timeout - 60, debate_timeout)),
    )

    if force_local or offline:
        requested_local = True
        requested_api = False

    if graph_mode or matrix_mode:
        if requested_local:
            print("Graph/matrix debates require API mode. Remove --local.", file=sys.stderr)
            raise SystemExit(2)
        requested_api = True
        if auto_select:
            # Use local auto-select to choose a team, then pass to graph/matrix APIs
            selected = _auto_select_agents_local(args.task, auto_select_config)
            if selected:
                agents = selected
            else:
                print(
                    "Auto-select failed; provide --agents for graph/matrix debates.",
                    file=sys.stderr,
                )
                raise SystemExit(2)
    if decision_integrity and (graph_mode or matrix_mode):
        print("Decision integrity is only supported for standard debates.", file=sys.stderr)
        raise SystemExit(2)

    di_include_context = bool(getattr(args, "di_include_context", False))
    di_plan_strategy = getattr(args, "di_plan_strategy", "single_task")
    di_execution_mode = getattr(args, "di_execution_mode", None)
    post_consensus_quality = bool(getattr(args, "post_consensus_quality", True))
    upgrade_to_good = bool(getattr(args, "upgrade_to_good", True))
    quality_upgrade_max_loops = max(0, int(getattr(args, "quality_upgrade_max_loops", 2)))
    quality_min_score = float(getattr(args, "quality_min_score", 9.0))
    quality_practical_min_score = float(getattr(args, "quality_practical_min_score", 5.0))
    quality_concretize_max_rounds = max(0, int(getattr(args, "quality_concretize_max_rounds", 3)))
    quality_extra_assessment_rounds = max(
        0, int(getattr(args, "quality_extra_assessment_rounds", 2))
    )
    quality_fail_closed = bool(getattr(args, "quality_fail_closed", False))
    grounding_fail_closed = bool(getattr(args, "grounding_fail_closed", False))
    grounding_min_verified_paths = float(getattr(args, "grounding_min_verified_paths", 0.8))
    if not 0.0 <= grounding_min_verified_paths <= 1.0:
        print(
            "Invalid --grounding-min-verified-paths: expected value in [0.0, 1.0].",
            file=sys.stderr,
        )
        raise SystemExit(2)

    def _assess_and_enforce_grounding(final_answer_text: str) -> None:
        from aragora.debate.repo_grounding import (
            assess_repo_grounding,
            format_path_verification_summary,
        )

        report = assess_repo_grounding(
            str(final_answer_text or ""),
            repo_root=str(codebase_context_repo or Path.cwd()),
        )
        print(format_path_verification_summary(report))

        if not grounding_fail_closed:
            return

        total = len(report.mentioned_paths)
        verified_existing = len(report.existing_paths)
        verified_ratio = (verified_existing / total) if total else 0.0
        if total == 0 or verified_ratio < grounding_min_verified_paths:
            print(
                (
                    "Debate failed grounding gate: verified existing path ratio "
                    f"{verified_ratio:.2f} is below required "
                    f"{grounding_min_verified_paths:.2f} (existing={verified_existing}, total={total})."
                ),
                file=sys.stderr,
            )
            raise SystemExit(1)

    quality_contract = None
    quality_contract_source = "none"
    if post_consensus_quality:
        from aragora.debate.output_quality import (
            build_contract_context_block,
            derive_output_contract_from_task,
            load_output_contract_from_file,
        )

        output_contract_file = getattr(args, "output_contract_file", None)
        required_sections = getattr(args, "required_sections", None)
        task_lower = str(args.task or "").lower()
        has_explicit_task_contract = (
            "output sections" in task_lower
            or "required sections" in task_lower
            or "section headings" in task_lower
        )
        if (
            quality_fail_closed
            and not (isinstance(output_contract_file, str) and output_contract_file.strip())
            and not (isinstance(required_sections, str) and required_sections.strip())
            and not has_explicit_task_contract
        ):
            print(
                "Debate configuration invalid: --quality-fail-closed requires an explicit "
                "output contract. Add explicit output sections to the task or pass "
                "--required-sections/--output-contract-file.",
                file=sys.stderr,
            )
            raise SystemExit(2)

        if isinstance(output_contract_file, str) and output_contract_file.strip():
            try:
                quality_contract = load_output_contract_from_file(output_contract_file.strip())
                quality_contract_source = "file"
            except ValueError as e:
                print(f"Debate configuration invalid: {e}", file=sys.stderr)
                raise SystemExit(2)
        elif isinstance(required_sections, str) and required_sections.strip():
            normalized = ", ".join(
                p.strip() for p in required_sections.strip().split(",") if p.strip()
            )
            quality_contract = derive_output_contract_from_task(f"output sections {normalized}")
            quality_contract_source = "required_sections"
        else:
            quality_contract = derive_output_contract_from_task(
                args.task,
                has_context=bool(getattr(args, "context", None)),
            )
            if quality_contract is None:
                quality_contract_source = "none"
            elif quality_contract.required_sections:
                quality_contract_source = "task"
            else:
                quality_contract_source = "fallback"

        if quality_fail_closed and quality_contract_source == "none":
            print(
                "Debate configuration invalid: --quality-fail-closed requires an explicit "
                "output contract. Add output sections to the task or pass --required-sections "
                "or --output-contract-file.",
                file=sys.stderr,
            )
            raise SystemExit(2)

        if quality_contract is not None:
            contract_block = build_contract_context_block(quality_contract)
            if context:
                context = f"{context}\n\n--- Deterministic Output Contract ---\n{contract_block}\n"
            else:
                context = contract_block
        elif args.verbose:
            print(
                "[quality] contract=none (no explicit output sections detected in task)",
                file=sys.stderr,
            )

    use_api = requested_api
    if not requested_api and not requested_local:
        use_api = _is_server_available(server_url)

    if use_api:
        try:
            if graph_mode:
                graph_agents = _agent_names_for_graph_matrix(agents)
                result = _run_graph_debate_api(
                    server_url=server_url,
                    api_key=api_key,
                    task=args.task,
                    agents=graph_agents,
                    max_rounds=args.graph_rounds,
                    branch_threshold=args.branch_threshold,
                    max_branches=args.max_branches,
                    timeout_seconds=debate_timeout,
                    verbose=args.verbose,
                )
                _print_graph_result(result, verbose=args.verbose)
                return

            if matrix_mode:
                matrix_agents = _agent_names_for_graph_matrix(agents)
                scenarios = _parse_matrix_scenarios(args.scenario)
                result = _run_matrix_debate_api(
                    server_url=server_url,
                    api_key=api_key,
                    task=args.task,
                    agents=matrix_agents,
                    scenarios=scenarios,
                    max_rounds=args.matrix_rounds,
                    timeout_seconds=debate_timeout,
                    verbose=args.verbose,
                )
                _print_matrix_result(result, verbose=args.verbose)
                return

            if auto_select:
                if agents and agents != DEFAULT_AGENTS:
                    print("Warning: --auto-select ignores explicit --agents", file=sys.stderr)
                agents_payload = []
            else:
                agents_payload = _agents_payload_for_api(agents)

            result = _run_debate_api(
                server_url=server_url,
                api_key=api_key,
                task=task,
                agents=agents_payload,
                rounds=rounds,
                consensus=args.consensus,
                context=context or None,
                metadata={},
                auto_select=auto_select,
                auto_select_config=auto_select_config,
                enable_verticals=enable_verticals,
                vertical_id=vertical_id,
                timeout_seconds=debate_timeout,
            )
            _print_debate_result(result, verbose=args.verbose)
            if codebase_context_requested or grounding_fail_closed:
                final_answer = getattr(result, "final_answer", None)
                if not final_answer:
                    consensus = getattr(result, "consensus", None)
                    final_answer = getattr(consensus, "final_answer", "") if consensus else ""
                _assess_and_enforce_grounding(str(final_answer or ""))
            if decision_integrity:
                package = _build_decision_integrity_api(
                    server_url=server_url,
                    api_key=api_key,
                    debate_id=result.debate_id,
                    include_context=di_include_context,
                    plan_strategy=di_plan_strategy,
                    execution_mode=di_execution_mode,
                )
                _print_decision_integrity_summary(package)
            return
        except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
            if requested_api or graph_mode or matrix_mode:
                print(f"API run failed: {e}", file=sys.stderr)
                raise SystemExit(1)
            if _is_server_available(server_url):
                print(f"API run failed: {e}", file=sys.stderr)
                raise SystemExit(1)
            print(
                "Warning: API server unavailable, falling back to local execution.",
                file=sys.stderr,
            )

    explain = getattr(args, "explain", False)

    # Apply preset configuration if specified
    preset_kwargs: dict[str, Any] = {}
    preset_name = getattr(args, "preset", None)
    if preset_name:
        from aragora.debate.presets import get_preset

        preset_kwargs = get_preset(preset_name)
        print(f"[preset] Applied '{preset_name}' configuration preset")

    # Create spectator stream if --spectate is specified
    spectate_kwargs: dict[str, Any] = {}
    if getattr(args, "spectate", False):
        from aragora.spectate.stream import SpectatorStream

        spectate_fmt = getattr(args, "spectate_format", "auto")
        spectate_kwargs["spectator"] = SpectatorStream(enabled=True, format=spectate_fmt)

    # CLI flag overrides for ArenaConfig (explicit flags take precedence over presets)
    cli_config_kwargs: dict[str, Any] = {}
    if hasattr(args, "enable_cartographer"):
        cli_config_kwargs["enable_cartographer"] = args.enable_cartographer
    if hasattr(args, "enable_introspection"):
        cli_config_kwargs["enable_introspection"] = args.enable_introspection
    if codebase_context_requested:
        cli_config_kwargs["enable_codebase_grounding"] = True
        if codebase_context_repo is not None:
            cli_config_kwargs["codebase_path"] = str(codebase_context_repo)
    if bool(getattr(args, "no_context_init_rlm", False)):
        cli_config_kwargs["use_rlm_limiter"] = False
        if args.verbose:
            print(
                "[context-init] disabled RLM limiter via --no-context-init-rlm",
                file=sys.stderr,
            )
    if getattr(args, "auto_execute", False):
        cli_config_kwargs["enable_auto_execution"] = True

    start_time = time.monotonic()

    def _remaining_global_seconds() -> float:
        return max(0.0, float(debate_timeout) - (time.monotonic() - start_time))

    def _quality_upgrade_attempt_timeout(
        *,
        remaining_global_seconds: float,
        providers_remaining: int,
    ) -> int | None:
        """Compute per-provider upgrade timeout within remaining wall-clock budget."""
        if remaining_global_seconds <= 0:
            return None
        # Reserve tail budget for deterministic repairs/finalization + CLI reporting.
        reserved_tail_seconds = 60.0
        usable_seconds = max(0.0, remaining_global_seconds - reserved_tail_seconds)
        if usable_seconds <= 0:
            return None

        slots = max(1, providers_remaining)
        # Keep individual retries bounded; avoid multi-minute single-provider stalls.
        return max(60, min(360, int(usable_seconds / slots)))

    def _quality_gate_passes(report: Any) -> bool:
        return bool(
            report.verdict == "good"
            and report.quality_score_10 >= quality_min_score
            and float(getattr(report, "practicality_score_10", 0.0)) >= quality_practical_min_score
        )

    def _report_rank(report: Any) -> tuple[float, float, float]:
        quality_score = float(getattr(report, "quality_score_10", 0.0))
        practicality_score = float(getattr(report, "practicality_score_10", 0.0))
        defect_penalty = float(len(getattr(report, "defects", []) or []))
        # Fewer defects > higher practicality — prevents rejecting a
        # defect-free repair just because practicality dipped slightly.
        return (quality_score, -defect_penalty, practicality_score)

    def _is_better_report(candidate: Any, incumbent: Any) -> bool:
        return _report_rank(candidate) > _report_rank(incumbent)

    def _build_revision_specs(
        *,
        preferred_providers: list[str] | None = None,
    ) -> list[AgentSpec]:
        ordered_specs: list[AgentSpec] = []
        specs = parse_agents(agents)
        if specs:
            if preferred_providers:
                chosen: set[int] = set()
                for provider_name in preferred_providers:
                    for idx, spec in enumerate(specs):
                        if idx in chosen:
                            continue
                        if spec.provider == provider_name:
                            ordered_specs.append(spec)
                            chosen.add(idx)
                            break
                for idx, spec in enumerate(specs):
                    if idx not in chosen:
                        ordered_specs.append(spec)
            else:
                preferred_order = [len(specs) - 1] + [idx for idx in range(len(specs) - 1)]
                ordered_specs = [specs[idx] for idx in preferred_order if 0 <= idx < len(specs)]

        if preferred_providers:
            seen = {spec.provider for spec in ordered_specs}
            for provider_name in preferred_providers:
                if provider_name in seen:
                    continue
                try:
                    ordered_specs.append(AgentSpec(provider=provider_name, role="synthesizer"))
                    seen.add(provider_name)
                except ValueError:
                    continue

        # Optional OpenRouter fallback for quota/billing/provider outages.
        if os.environ.get("OPENROUTER_API_KEY") and not any(
            spec.provider == "openrouter" for spec in ordered_specs
        ):
            try:
                ordered_specs.append(AgentSpec(provider="openrouter", role="synthesizer"))
            except ValueError:
                pass
        return ordered_specs

    async def _attempt_targeted_revision(
        *,
        prompt: str,
        attempt_num: int,
        stage: str,
        role_hint: str,
        preferred_providers: list[str] | None = None,
    ) -> tuple[str | None, str | None]:
        ordered_specs = _build_revision_specs(preferred_providers=preferred_providers)
        if not ordered_specs:
            return (None, None)

        for idx, spec in enumerate(ordered_specs):
            provider = spec.provider
            per_attempt_timeout = _quality_upgrade_attempt_timeout(
                remaining_global_seconds=_remaining_global_seconds(),
                providers_remaining=len(ordered_specs) - idx,
            )
            if per_attempt_timeout is None:
                logger.warning(
                    "%s_budget_exhausted attempt=%s provider=%s",
                    stage,
                    attempt_num,
                    provider,
                )
                break
            try:
                repair_agent = create_agent(
                    model_type=cast(AgentType, provider),
                    name=f"{stage}_{provider}_{attempt_num}",
                    role="synthesizer",
                    model=spec.model,
                )
                existing = getattr(repair_agent, "system_prompt", "") or ""
                repair_agent.system_prompt = f"{existing}\n\n{role_hint}".strip()
                repaired = await asyncio.wait_for(
                    repair_agent.generate(prompt),
                    timeout=per_attempt_timeout,
                )
                if repaired and repaired.strip():
                    return (repaired.strip(), provider)
            except Exception as e:  # noqa: BLE001 - best-effort repair fallback
                logger.warning("%s_attempt_failed provider=%s error=%s", stage, provider, e)
                continue
        return (None, None)

    async def _attempt_quality_upgrade(
        *,
        current_answer: str,
        defects: list[str],
        attempt_num: int,
    ) -> tuple[str | None, str | None]:
        if quality_contract is None:
            return (None, None)

        from aragora.debate.output_quality import build_upgrade_prompt

        prompt = build_upgrade_prompt(
            task=task,
            contract=quality_contract,
            current_answer=current_answer,
            defects=defects,
        )
        role_hint = (
            "You are a post-consensus quality upgrader. Keep core ideas, "
            "fix defects, and preserve required section order."
        )
        return await _attempt_targeted_revision(
            prompt=prompt,
            attempt_num=attempt_num,
            stage="quality_upgrade",
            role_hint=role_hint,
        )

    async def _post_consensus_quality_pipeline(result: Any) -> Any:
        if not post_consensus_quality or quality_contract is None:
            return result

        from aragora.debate.output_quality import (
            apply_deterministic_quality_repairs,
            build_concretization_prompt,
            finalize_json_payload,
            validate_output_against_contract,
        )

        repo_root = os.getcwd()
        metadata = getattr(result, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
            setattr(result, "metadata", metadata)

        initial_report = validate_output_against_contract(
            result.final_answer,
            quality_contract,
            repo_root=repo_root,
        )
        best_report = initial_report
        best_answer = result.final_answer
        attempts: list[dict[str, Any]] = []
        loops_used = 0
        loops_by_stage = {"quality_upgrade": 0, "concretization": 0, "assessment_upgrade": 0}
        upgraded = False

        if upgrade_to_good and not _quality_gate_passes(initial_report):
            current_answer = result.final_answer
            current_report = initial_report
            for loop_idx in range(1, quality_upgrade_max_loops + 1):
                loops_by_stage["quality_upgrade"] += 1
                loops_used = loop_idx
                repaired, provider = await _attempt_quality_upgrade(
                    current_answer=current_answer,
                    defects=current_report.defects,
                    attempt_num=loop_idx,
                )
                if not repaired:
                    attempts.append(
                        {
                            "stage": "quality_upgrade",
                            "loop": loop_idx,
                            "provider": provider or "none",
                            "status": "no_revision",
                        }
                    )
                    continue

                revised_report = validate_output_against_contract(
                    repaired,
                    quality_contract,
                    repo_root=repo_root,
                )
                accepted = _is_better_report(revised_report, best_report)

                attempts.append(
                    {
                        "stage": "quality_upgrade",
                        "loop": loop_idx,
                        "provider": provider or "unknown",
                        "status": "accepted" if accepted else "rejected",
                        "quality_score_10": revised_report.quality_score_10,
                        "practicality_score_10": revised_report.practicality_score_10,
                        "verdict": revised_report.verdict,
                        "defect_count": len(revised_report.defects),
                    }
                )

                if accepted:
                    best_answer = repaired
                    best_report = revised_report
                    current_answer = repaired
                    current_report = revised_report
                    if _quality_gate_passes(revised_report):
                        upgraded = True
                        break

        if not _quality_gate_passes(best_report):
            deterministic_answer = apply_deterministic_quality_repairs(
                best_answer,
                quality_contract,
                best_report,
                repo_root=repo_root,
            )
            deterministic_report = validate_output_against_contract(
                deterministic_answer,
                quality_contract,
                repo_root=repo_root,
            )
            deterministic_accepted = _is_better_report(deterministic_report, best_report)
            attempts.append(
                {
                    "stage": "deterministic_repair",
                    "loop": loops_used + 1,
                    "provider": "deterministic_repair",
                    "status": "accepted" if deterministic_accepted else "rejected",
                    "quality_score_10": deterministic_report.quality_score_10,
                    "practicality_score_10": deterministic_report.practicality_score_10,
                    "verdict": deterministic_report.verdict,
                    "defect_count": len(deterministic_report.defects),
                }
            )
            if deterministic_accepted:
                best_answer = deterministic_answer
                best_report = deterministic_report
                upgraded = _quality_gate_passes(deterministic_report) or upgraded

        if quality_contract.require_json_payload:
            json_finalized_answer = finalize_json_payload(best_answer, quality_contract)
            json_finalized_report = validate_output_against_contract(
                json_finalized_answer,
                quality_contract,
                repo_root=repo_root,
            )
            json_finalized_accepted = _is_better_report(json_finalized_report, best_report)
            attempts.append(
                {
                    "stage": "deterministic_json_finalizer",
                    "loop": loops_used + 2,
                    "provider": "deterministic_json_finalizer",
                    "status": "accepted" if json_finalized_accepted else "rejected",
                    "quality_score_10": json_finalized_report.quality_score_10,
                    "practicality_score_10": json_finalized_report.practicality_score_10,
                    "verdict": json_finalized_report.verdict,
                    "defect_count": len(json_finalized_report.defects),
                }
            )
            if json_finalized_accepted:
                best_answer = json_finalized_answer
                best_report = json_finalized_report
                upgraded = _quality_gate_passes(json_finalized_report) or upgraded

        if quality_concretize_max_rounds > 0 and not _quality_gate_passes(best_report):
            for round_idx in range(1, quality_concretize_max_rounds + 1):
                loops_by_stage["concretization"] += 1
                loops_used += 1
                concretize_prompt = build_concretization_prompt(
                    task=task,
                    contract=quality_contract,
                    current_answer=best_answer,
                    practicality_score_10=best_report.practicality_score_10,
                    target_practicality_10=quality_practical_min_score,
                    defects=best_report.defects,
                )
                revised, provider = await _attempt_targeted_revision(
                    prompt=concretize_prompt,
                    attempt_num=round_idx,
                    stage="concretization",
                    role_hint=(
                        "You are a concretization specialist. Raise execution practicality by "
                        "turning first-batch tasks into path-grounded, testable actions."
                    ),
                )
                if not revised:
                    attempts.append(
                        {
                            "stage": "concretization",
                            "loop": round_idx,
                            "provider": provider or "none",
                            "status": "no_revision",
                        }
                    )
                    continue
                revised_report = validate_output_against_contract(
                    revised,
                    quality_contract,
                    repo_root=repo_root,
                )
                accepted = _is_better_report(revised_report, best_report)
                attempts.append(
                    {
                        "stage": "concretization",
                        "loop": round_idx,
                        "provider": provider or "unknown",
                        "status": "accepted" if accepted else "rejected",
                        "quality_score_10": revised_report.quality_score_10,
                        "practicality_score_10": revised_report.practicality_score_10,
                        "verdict": revised_report.verdict,
                        "defect_count": len(revised_report.defects),
                    }
                )
                if accepted:
                    best_answer = revised
                    best_report = revised_report
                    if _quality_gate_passes(revised_report):
                        upgraded = True
                        break

        practicality_shortfall = (
            float(getattr(best_report, "practicality_score_10", 0.0)) < quality_practical_min_score
        )
        if quality_extra_assessment_rounds > 0 and practicality_shortfall:
            for round_idx in range(1, quality_extra_assessment_rounds + 1):
                loops_by_stage["assessment_upgrade"] += 1
                loops_used += 1
                preferred_providers = (
                    ["claude", "codex"] if (round_idx % 2 == 1) else ["codex", "claude"]
                )
                assessment_prompt = build_concretization_prompt(
                    task=task,
                    contract=quality_contract,
                    current_answer=best_answer,
                    practicality_score_10=best_report.practicality_score_10,
                    target_practicality_10=quality_practical_min_score,
                    defects=best_report.defects
                    + [
                        f"Raise practicality score to >= {quality_practical_min_score:.2f}.",
                        "Ground owner paths to existing repository files.",
                    ],
                )
                revised, provider = await _attempt_targeted_revision(
                    prompt=assessment_prompt,
                    attempt_num=round_idx,
                    stage="assessment_upgrade",
                    role_hint=(
                        "You are an independent post-consensus assessor. Improve practical value "
                        "without discarding valid consensus details."
                    ),
                    preferred_providers=preferred_providers,
                )
                if not revised:
                    attempts.append(
                        {
                            "stage": "assessment_upgrade",
                            "loop": round_idx,
                            "provider": provider or "none",
                            "status": "no_revision",
                        }
                    )
                    continue

                revised_report = validate_output_against_contract(
                    revised,
                    quality_contract,
                    repo_root=repo_root,
                )
                accepted = _is_better_report(revised_report, best_report)
                attempts.append(
                    {
                        "stage": "assessment_upgrade",
                        "loop": round_idx,
                        "provider": provider or "unknown",
                        "status": "accepted" if accepted else "rejected",
                        "quality_score_10": revised_report.quality_score_10,
                        "practicality_score_10": revised_report.practicality_score_10,
                        "verdict": revised_report.verdict,
                        "defect_count": len(revised_report.defects),
                    }
                )
                if accepted:
                    best_answer = revised
                    best_report = revised_report
                    if _quality_gate_passes(revised_report):
                        upgraded = True
                        break

        result.final_answer = best_answer
        metadata["post_consensus_quality"] = {
            "enabled": True,
            "contract": quality_contract.to_dict(),
            "target_quality_score_10": quality_min_score,
            "target_practicality_score_10": quality_practical_min_score,
            "initial_report": initial_report.to_dict(),
            "final_report": best_report.to_dict(),
            "loops_used": loops_used,
            "loops_by_stage": loops_by_stage,
            "upgraded": upgraded,
            "attempts": attempts,
        }

        if quality_fail_closed and not _quality_gate_passes(best_report):
            raise RuntimeError(
                "Post-consensus quality gate failed after upgrade loops: "
                + "; ".join(best_report.defects[:3])
                + f" (quality={best_report.quality_score_10}, "
                + f"practicality={best_report.practicality_score_10})"
            )

        return result

    async def _run_with_timeout():
        debate_result = await asyncio.wait_for(
            run_debate(
                task=task,
                agents_str=agents,
                rounds=rounds,
                consensus=args.consensus,
                context=context,
                learn=learn,
                db_path=args.db,
                enable_audience=enable_audience,
                server_url=server_url,
                protocol_overrides=protocol_overrides,
                mode=getattr(args, "mode", None),
                enable_verticals=enable_verticals,
                vertical_id=vertical_id,
                auto_select=auto_select,
                auto_select_config=auto_select_config,
                codebase_context=codebase_context_requested,
                codebase_context_path=str(codebase_context_repo) if codebase_context_repo else None,
                offline=offline or force_local,
                auto_explain=explain,
                **preset_kwargs,
                **spectate_kwargs,
                **cli_config_kwargs,
            ),
            timeout=debate_timeout,
        )
        return await _post_consensus_quality_pipeline(debate_result)

    try:
        with _strict_wall_clock_timeout(debate_timeout):
            result = asyncio.run(_run_with_timeout())
    except _StrictWallClockTimeout:
        elapsed = time.monotonic() - start_time
        cleanup = _cleanup_cli_subprocesses_for_timeout()
        _emit_timeout_failure_payload(
            error_type="strict_wall_clock_timeout",
            timeout_seconds=debate_timeout,
            elapsed_seconds=elapsed,
            task=raw_task,
            agents_str=agents,
            mode=getattr(args, "mode", None),
            cleanup=cleanup,
        )
        print(
            f"Debate timed out after {debate_timeout}s (strict wall-clock; elapsed={elapsed:.2f}s)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start_time
        cleanup = _cleanup_cli_subprocesses_for_timeout()
        _emit_timeout_failure_payload(
            error_type="async_wait_for_timeout",
            timeout_seconds=debate_timeout,
            elapsed_seconds=elapsed,
            task=raw_task,
            agents_str=agents,
            mode=getattr(args, "mode", None),
            cleanup=cleanup,
        )
        print(
            f"Debate timed out after {debate_timeout}s (async wait_for; elapsed={elapsed:.2f}s)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except RuntimeError as e:
        print(f"Debate failed quality gate: {e}", file=sys.stderr)
        raise SystemExit(1)

    print("\n" + "=" * 60)
    print("FINAL ANSWER:")
    print("=" * 60)
    print(result.final_answer)
    if codebase_context_requested or grounding_fail_closed:
        _assess_and_enforce_grounding(str(getattr(result, "final_answer", "") or ""))

    quality_meta = None
    if isinstance(getattr(result, "metadata", None), dict):
        quality_meta = result.metadata.get("post_consensus_quality")
    if isinstance(quality_meta, dict):
        final_report = quality_meta.get("final_report", {})
        print(
            f"\n[quality] verdict={final_report.get('verdict', 'unknown')} "
            f"score={final_report.get('quality_score_10', 'n/a')} "
            f"practicality={final_report.get('practicality_score_10', 'n/a')} "
            f"loops={quality_meta.get('loops_used', 0)} "
            f"upgraded={quality_meta.get('upgraded', False)}"
        )
        defects = final_report.get("defects") or []
        if defects and args.verbose:
            for defect in defects[:5]:
                print(f"[quality] defect: {defect}")
    elif post_consensus_quality:
        print("[quality] skipped=no_contract reason=no_explicit_output_contract_detected")

    # Display explanation if --explain was requested
    if explain:
        explanation = getattr(result, "explanation", None)
        if explanation:
            try:
                from aragora.explainability.builder import ExplanationBuilder

                summary = ExplanationBuilder().generate_summary(explanation)
                print("\nWHY THIS ANSWER:")
                print("-" * 40)
                print(summary)
            except (ImportError, AttributeError, TypeError):
                pass

    if result.dissenting_views and args.verbose:
        print("\n" + "-" * 60)
        print("DISSENTING VIEWS:")
        for view in result.dissenting_views:
            print(f"\n{view}")

    if decision_integrity:
        if di_execution_mode and di_execution_mode != "plan_only":
            print(
                "Decision integrity execution is only supported in API mode. "
                "Generating plan-only package.",
                file=sys.stderr,
            )
        package = _build_decision_integrity_local(
            result,
            include_context=di_include_context,
            plan_strategy=di_plan_strategy,
        )
        _print_decision_integrity_summary(package)
