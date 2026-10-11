"""Gauntlet decisions for :class:`aragora.core.decision_router.DecisionRouter`.

The core router cannot import this package, so ``aragora.gauntlet`` registers
:func:`route_gauntlet_decision` as the ``gauntlet`` route target when it is imported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aragora.core.decision_models import DecisionResult
from aragora.core.decision_route_hooks import ROUTE_GAUNTLET, register_route_target
from aragora.core.decision_types import DecisionType

if TYPE_CHECKING:
    from aragora.core.decision_models import DecisionRequest
    from aragora.core.decision_router import DecisionRouter


async def route_gauntlet_decision(
    router: DecisionRouter, request: DecisionRequest, span: Any | None
) -> DecisionResult:
    """Run the gauntlet orchestrator over ``request.content``."""
    # The package init loads the orchestrator lazily; keep it off the import path.
    from aragora.agents import get_agents_by_names
    from aragora.gauntlet.orchestrator import (
        GauntletConfig as OrchestratorConfig,
        GauntletOrchestrator,
        Verdict,
    )

    engine = router.gauntlet_engine
    if engine is None:
        agents = get_agents_by_names(request.config.agents) if request.config.agents else []
        engine = GauntletOrchestrator(agents=agents)
        router.gauntlet_engine = engine

    config = OrchestratorConfig(
        input_content=request.content,
        enable_redteam=request.config.enable_adversarial,
        enable_verification=request.config.enable_formal_verification,
        max_duration_seconds=request.config.timeout_seconds,
    )

    if span:
        span.set_attribute("gauntlet.adversarial", request.config.enable_adversarial)
        span.set_attribute(
            "gauntlet.formal_verification", request.config.enable_formal_verification
        )

    gauntlet_result = await engine.run(config=config)

    passed = gauntlet_result.verdict in (Verdict.PASS, Verdict.APPROVED)
    verdict_summary = gauntlet_result.verdict.value if gauntlet_result.verdict else ""

    if span:
        span.set_attribute("gauntlet.passed", passed)
        span.set_attribute("gauntlet.confidence", gauntlet_result.confidence)

    return DecisionResult(
        request_id=request.request_id,
        decision_type=DecisionType.GAUNTLET,
        answer=verdict_summary,
        confidence=gauntlet_result.confidence,
        consensus_reached=passed,
        gauntlet_result=gauntlet_result,
    )


def register_decision_route() -> None:
    """Register :func:`route_gauntlet_decision` with the core decision router."""
    register_route_target(ROUTE_GAUNTLET, route_gauntlet_decision)
