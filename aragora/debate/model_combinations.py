"""
Run the same debate task across multiple model combinations.

This module normalizes model-combination specs, executes one debate per
combination either sequentially or in parallel, and preserves a result for
every combination, including failures.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any, cast

from aragora.agents.spec import AgentSpec
from aragora.config import DEFAULT_ROUNDS
from aragora.core import Environment
from aragora.protocols.debate import DebateProtocol

DEFAULT_TEAM_ROLES: tuple[str, ...] = ("proposer", "critic", "synthesizer")


class ExecutionMode(str, Enum):
    """How to execute combination debates."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


@dataclass
class ModelCombination:
    """One debate team configuration to execute."""

    id: str
    name: str
    agents: list[AgentSpec]
    max_rounds: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "agents": [
                {
                    "provider": agent.provider,
                    "model": agent.model,
                    "persona": agent.persona,
                    "role": agent.role,
                    "name": agent.name,
                }
                for agent in self.agents
            ],
            "max_rounds": self.max_rounds,
            "metadata": self.metadata,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelCombination:
        raw_agents = data.get("agents", data.get("models", data.get("providers")))
        if not isinstance(raw_agents, list) or not raw_agents:
            raise ValueError("model combination requires a non-empty agents list")

        normalized_agents = [_normalize_agent_spec(item) for item in raw_agents]
        combination_id = str(data.get("id") or uuid.uuid4())
        combination_name = str(data.get("name") or _default_combination_name(normalized_agents))

        raw_max_rounds = data.get("max_rounds")
        max_rounds: int | None = None
        if raw_max_rounds is not None:
            try:
                max_rounds = int(raw_max_rounds)
            except (TypeError, ValueError) as exc:
                raise ValueError("max_rounds must be an integer when provided") from exc
            if max_rounds < 1:
                raise ValueError("max_rounds must be at least 1")

        metadata = data.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")

        tags = data.get("tags") or []
        if not isinstance(tags, list):
            raise ValueError("tags must be a list")

        return cls(
            id=combination_id,
            name=combination_name,
            agents=normalized_agents,
            max_rounds=max_rounds,
            metadata=metadata,
            tags=[str(tag) for tag in tags],
        )


@dataclass
class CombinationDebateResult:
    """Outcome of running one combination."""

    combination_id: str
    combination_name: str
    agents: list[dict[str, Any]]
    final_answer: str
    confidence: float
    consensus_reached: bool
    winner: str | None = None
    rounds_used: int = 0
    duration_seconds: float = 0.0
    status: str = "completed"
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.status == "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "combination_id": self.combination_id,
            "combination_name": self.combination_name,
            "agents": self.agents,
            "final_answer": self.final_answer,
            "confidence": self.confidence,
            "consensus_reached": self.consensus_reached,
            "winner": self.winner,
            "rounds_used": self.rounds_used,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class MultiModelDebateResult:
    """Aggregate result for a whole multi-combination execution."""

    execution_id: str
    task: str
    mode: ExecutionMode
    created_at: datetime
    combinations: list[ModelCombination] = field(default_factory=list)
    results: list[CombinationDebateResult] = field(default_factory=list)
    completed_at: datetime | None = None

    @property
    def success_count(self) -> int:
        return sum(1 for result in self.results if result.succeeded)

    @property
    def failure_count(self) -> int:
        return len(self.results) - self.success_count

    def get_result(self, combination_id: str) -> CombinationDebateResult | None:
        for result in self.results:
            if result.combination_id == combination_id:
                return result
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "task": self.task,
            "mode": self.mode.value,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "combinations": [combination.to_dict() for combination in self.combinations],
            "results": [result.to_dict() for result in self.results],
        }


SingleDebateExecutor = Callable[
    [Environment, list[Any], DebateProtocol, ModelCombination], Awaitable[Any]
]
AgentFactory = Callable[[AgentSpec, int], Any]


class MultiModelDebateRunner:
    """Execute one debate task across multiple model combinations."""

    def __init__(
        self,
        debate_executor: SingleDebateExecutor | None = None,
        agent_factory: AgentFactory | None = None,
        max_parallel: int = 3,
    ) -> None:
        self.debate_executor = debate_executor or self._execute_with_arena
        self.agent_factory = agent_factory or self._create_agent_from_spec
        self.max_parallel = max(1, int(max_parallel))

    async def run(
        self,
        task: str,
        combinations: Sequence[ModelCombination | dict[str, Any] | Sequence[Any]],
        *,
        base_context: str = "",
        max_rounds: int = DEFAULT_ROUNDS,
        mode: ExecutionMode | str | None = None,
        on_combination_complete: Callable[[CombinationDebateResult], None] | None = None,
    ) -> MultiModelDebateResult:
        normalized_combinations = parse_model_combinations(combinations)
        execution_mode = self._resolve_mode(mode, len(normalized_combinations))

        result = MultiModelDebateResult(
            execution_id=str(uuid.uuid4()),
            task=task,
            mode=execution_mode,
            created_at=datetime.now(),
            combinations=normalized_combinations,
        )

        if execution_mode is ExecutionMode.SEQUENTIAL:
            for combination in normalized_combinations:
                combination_result = await self._run_combination(
                    task=task,
                    combination=combination,
                    base_context=base_context,
                    default_rounds=max_rounds,
                )
                result.results.append(combination_result)
                if on_combination_complete:
                    on_combination_complete(combination_result)
        else:
            for offset in range(0, len(normalized_combinations), self.max_parallel):
                batch = normalized_combinations[offset : offset + self.max_parallel]
                batch_results = await asyncio.gather(
                    *[
                        self._run_combination(
                            task=task,
                            combination=combination,
                            base_context=base_context,
                            default_rounds=max_rounds,
                        )
                        for combination in batch
                    ]
                )
                result.results.extend(batch_results)
                if on_combination_complete:
                    for combination_result in batch_results:
                        on_combination_complete(combination_result)

        result.completed_at = datetime.now()
        return result

    async def _run_combination(
        self,
        *,
        task: str,
        combination: ModelCombination,
        base_context: str,
        default_rounds: int,
    ) -> CombinationDebateResult:
        started_at = datetime.now()
        resolved_specs = _resolve_combination_roles(combination.agents)

        try:
            debate_rounds = combination.max_rounds or default_rounds
            environment = Environment(task=task, context=base_context, max_rounds=debate_rounds)
            protocol = DebateProtocol(rounds=debate_rounds)
            agents = [
                self.agent_factory(spec, index)
                for index, spec in enumerate(resolved_specs, start=1)
            ]
            debate_result = await self.debate_executor(environment, agents, protocol, combination)
            return self._build_success_result(
                combination=combination,
                resolved_specs=resolved_specs,
                agents=agents,
                debate_result=debate_result,
                started_at=started_at,
            )
        except Exception as exc:  # noqa: BLE001 – intentional catch-all: one combination failure must not abort the batch
            return self._build_failure_result(
                combination=combination,
                resolved_specs=resolved_specs,
                started_at=started_at,
                exc=exc,
            )

    def _build_success_result(
        self,
        *,
        combination: ModelCombination,
        resolved_specs: list[AgentSpec],
        agents: list[Any],
        debate_result: Any,
        started_at: datetime,
    ) -> CombinationDebateResult:
        duration_seconds = (datetime.now() - started_at).total_seconds()
        rounds_used = getattr(debate_result, "rounds_used", getattr(debate_result, "rounds", 0))

        return CombinationDebateResult(
            combination_id=combination.id,
            combination_name=combination.name,
            agents=_serialize_agents(resolved_specs, agents),
            final_answer=str(getattr(debate_result, "final_answer", "")),
            confidence=float(getattr(debate_result, "confidence", 0.0) or 0.0),
            consensus_reached=bool(getattr(debate_result, "consensus_reached", False)),
            winner=_optional_str(getattr(debate_result, "winner", None)),
            rounds_used=int(rounds_used or 0),
            duration_seconds=duration_seconds,
            status="completed",
            metadata={"combination_metadata": combination.metadata},
        )

    def _build_failure_result(
        self,
        *,
        combination: ModelCombination,
        resolved_specs: list[AgentSpec],
        started_at: datetime,
        exc: Exception,
    ) -> CombinationDebateResult:
        duration_seconds = (datetime.now() - started_at).total_seconds()
        return CombinationDebateResult(
            combination_id=combination.id,
            combination_name=combination.name,
            agents=_serialize_agents(resolved_specs, []),
            final_answer="",
            confidence=0.0,
            consensus_reached=False,
            rounds_used=0,
            duration_seconds=duration_seconds,
            status="failed",
            error=str(exc),
            metadata={
                "combination_metadata": combination.metadata,
                "error_type": type(exc).__name__,
            },
        )

    def _resolve_mode(
        self,
        mode: ExecutionMode | str | None,
        combination_count: int,
    ) -> ExecutionMode:
        if mode is None:
            if self.max_parallel > 1 and combination_count > 1:
                return ExecutionMode.PARALLEL
            return ExecutionMode.SEQUENTIAL
        if isinstance(mode, ExecutionMode):
            return mode
        return ExecutionMode(mode.lower())

    async def _execute_with_arena(
        self,
        environment: Environment,
        agents: list[Any],
        protocol: DebateProtocol,
        combination: ModelCombination,
    ) -> Any:
        from aragora.debate.orchestrator import Arena

        arena = Arena(environment, agents, protocol)
        return await arena.run()

    def _create_agent_from_spec(self, spec: AgentSpec, index: int) -> Any:
        from aragora.agents.base import AgentType, create_agent

        role = cast(str, spec.role)
        name = _resolve_agent_name(spec, index)
        return create_agent(
            cast(AgentType, spec.provider),
            name=name,
            role=role,
            model=spec.model,
        )


def parse_model_combinations(
    combinations: Sequence[ModelCombination | dict[str, Any] | Sequence[Any]],
) -> list[ModelCombination]:
    """Normalize supported combination inputs into ModelCombination objects."""

    normalized: list[ModelCombination] = []
    for item in combinations:
        if isinstance(item, ModelCombination):
            normalized.append(item)
        elif isinstance(item, dict):
            normalized.append(ModelCombination.from_dict(item))
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            normalized.append(ModelCombination.from_dict({"agents": list(item)}))
        else:
            raise ValueError("Unsupported model combination format")

    if not normalized:
        raise ValueError("At least one model combination is required")

    return normalized


def _normalize_agent_spec(raw_agent: Any) -> AgentSpec:
    if isinstance(raw_agent, AgentSpec):
        return raw_agent
    if isinstance(raw_agent, str):
        return AgentSpec(provider=raw_agent)
    if isinstance(raw_agent, dict):
        provider = (
            raw_agent.get("provider")
            or raw_agent.get("agent_type")
            or raw_agent.get("type")
            or raw_agent.get("agent")
        )
        if not provider:
            raise ValueError("Agent spec dictionary requires a provider")
        return AgentSpec(
            provider=str(provider),
            model=_optional_str(raw_agent.get("model")),
            persona=_optional_str(raw_agent.get("persona")),
            role=_optional_str(raw_agent.get("role")),
            name=_optional_str(raw_agent.get("name")),
            hierarchy_role=_optional_str(raw_agent.get("hierarchy_role")),
        )
    raise ValueError("Unsupported agent spec format")


def _resolve_combination_roles(agent_specs: Sequence[AgentSpec]) -> list[AgentSpec]:
    resolved: list[AgentSpec] = []
    for index, agent_spec in enumerate(agent_specs):
        if agent_spec.role:
            resolved.append(agent_spec)
            continue

        default_role = DEFAULT_TEAM_ROLES[index] if index < len(DEFAULT_TEAM_ROLES) else "analyst"
        resolved.append(replace(agent_spec, role=default_role))
    return resolved


def _serialize_agents(specs: Sequence[AgentSpec], agents: Sequence[Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for index, spec in enumerate(specs, start=1):
        agent = agents[index - 1] if index - 1 < len(agents) else None
        serialized.append(
            {
                "provider": spec.provider,
                "model": getattr(agent, "model", spec.model),
                "role": spec.role,
                "name": getattr(agent, "name", _resolve_agent_name(spec, index)),
            }
        )
    return serialized


def _resolve_agent_name(spec: AgentSpec, index: int) -> str:
    if spec.name and spec.name not in {spec.provider, f"{spec.provider}_{spec.persona}"}:
        return spec.name
    role = spec.role or "agent"
    return f"{spec.provider}-{role}-{index}"


def _default_combination_name(agent_specs: Sequence[AgentSpec]) -> str:
    return " + ".join(agent.provider for agent in agent_specs)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


__all__ = [
    "CombinationDebateResult",
    "ExecutionMode",
    "ModelCombination",
    "MultiModelDebateResult",
    "MultiModelDebateRunner",
    "parse_model_combinations",
]
