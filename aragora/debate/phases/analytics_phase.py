"""
Analytics phase for debate orchestration.

This module extracts the analytics logic (Phases 4-6) from the
Arena._run_inner() method, handling post-consensus processing:
- Pattern tracking (success/failure)
- Metrics recording
- Insight extraction
- Agent relationship updates
- Uncertainty quantification
- Disagreement report generation
- Grounded verdict creation
- Formal verification (Z3/Lean)
- Belief network analysis
- Recording finalization
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.core import DebateResult
    from aragora.debate.context import DebateContext

logger = logging.getLogger(__name__)

# Lazy import for uncertainty estimation
_uncertainty_estimator = None


def get_uncertainty_estimator():
    """Lazy-load the uncertainty estimator to avoid circular imports."""
    global _uncertainty_estimator
    if _uncertainty_estimator is None:
        try:
            from aragora.uncertainty.estimator import ConfidenceEstimator

            _uncertainty_estimator = ConfidenceEstimator()
        except ImportError:
            logger.debug("Uncertainty estimator not available")
    return _uncertainty_estimator


class AnalyticsPhase:
    """
    Executes post-consensus analytics and reporting.

    This class encapsulates the analytics logic that was previously
    in the arena between consensus resolution and feedback loops.

    Usage:
        analytics = AnalyticsPhase(
            memory=arena.memory,
            insight_store=arena.insight_store,
            recorder=arena.recorder,
            event_emitter=arena.event_emitter,
            hooks=arena.hooks,
        )
        await analytics.execute(ctx)
    """

    def __init__(
        self,
        memory: Any = None,
        insight_store: Any = None,
        recorder: Any = None,
        event_emitter: Any = None,
        hooks: dict | None = None,
        loop_id: str | None = None,
        # Callbacks for orchestrator methods
        notify_spectator: Callable | None = None,
        update_agent_relationships: Callable | None = None,
        generate_disagreement_report: Callable | None = None,
        create_grounded_verdict: Callable | None = None,
        verify_claims_formally: Callable | None = None,
        format_conclusion: Callable | None = None,
    ):
        """
        Initialize the analytics phase.

        Args:
            memory: Optional CritiqueStore for pattern tracking
            insight_store: Optional InsightStore for insight extraction
            recorder: Optional ReplayRecorder for finalization
            event_emitter: Optional EventEmitter for WebSocket events
            hooks: Optional hooks dict for events
            loop_id: Optional loop ID for event correlation
            notify_spectator: Callback for spectator notifications
            update_agent_relationships: Callback to update relationships
            generate_disagreement_report: Callback to generate report
            create_grounded_verdict: Callback to create verdict
            verify_claims_formally: Async callback for Z3 verification
            format_conclusion: Callback to format conclusion
        """
        self.memory = memory
        self.insight_store = insight_store
        self.recorder = recorder
        self.event_emitter = event_emitter
        self.hooks = hooks or {}
        self.loop_id = loop_id

        # Callbacks
        self._notify_spectator = notify_spectator
        self._update_agent_relationships = update_agent_relationships
        self._generate_disagreement_report = generate_disagreement_report
        self._create_grounded_verdict = create_grounded_verdict
        self._verify_claims_formally = verify_claims_formally
        self._format_conclusion = format_conclusion

    async def execute(self, ctx: DebateContext) -> None:
        """
        Execute analytics phase.

        Args:
            ctx: The DebateContext with completed debate
        """
        # Check for cancellation before analytics
        if ctx.cancellation_token and ctx.cancellation_token.is_cancelled:
            from aragora.debate.cancellation import DebateCancelled

            raise DebateCancelled(ctx.cancellation_token.reason)

        if not ctx.result:
            logger.warning("AnalyticsPhase called without result")
            return

        result = ctx.result

        # 1. Track failed patterns
        self._track_failed_patterns(result)

        # 2. Set duration
        result.duration_seconds = time.time() - ctx.start_time

        # 3. Record metrics
        self._record_metrics(ctx)

        # 4. Emit consensus event
        self._emit_consensus_event(result)

        # 5. Emit debate end event
        self._emit_debate_end_event(result)

        # 6. Notify spectator of debate end
        self._notify_debate_end(result)

        # 7. Extract and store insights
        await self._extract_insights(result)

        # 8. Determine winner and update relationships
        self._determine_winner(ctx)
        self._update_relationships(ctx)

        # 8.5. Uncertainty quantification
        await self._analyze_uncertainty(ctx)

        # 9. Generate disagreement report
        self._generate_disagreement(ctx)

        # 10. Generate grounded verdict
        await self._generate_verdict(ctx)

        # 11. Formal verification
        await self._verify_formally(result)

        # 12. Belief network analysis
        self._analyze_beliefs(result)

        # 13. Log completion
        self._log_completion(ctx)

        # 14. Finalize recording
        self._finalize_recording(ctx)

        # 15. Trigger POST_DEBATE hook if hook_manager is available
        if ctx.hook_manager:
            try:
                await ctx.hook_manager.trigger("post_debate", ctx=ctx, result=result)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("POST_DEBATE hook failed: %s", e)

    def _track_failed_patterns(self, result: DebateResult) -> None:
        """Track failed patterns for balanced learning."""
        if not self.memory or result.consensus_reached:
            return

        for critique in result.critiques:
            if critique.severity >= 0.5:
                try:
                    # Get content from critique
                    content = getattr(critique, "content", "")
                    if not content:
                        content = critique.reasoning[:200] if hasattr(critique, "reasoning") else ""

                    self.memory.fail_pattern(
                        issue_text=content[:200],
                        issue_type=getattr(critique, "category", "general"),
                    )
                except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                    logger.debug("Failed to record pattern failure: %s", e)

    def _record_metrics(self, ctx: DebateContext) -> None:
        """Record debate metrics for observability."""
        try:
            from aragora.observability.prometheus import record_debate_completed

            result = ctx.result
            record_debate_completed(
                duration_seconds=result.duration_seconds,
                rounds_used=result.rounds_used,
                outcome="consensus" if result.consensus_reached else "no_consensus",
                agent_count=len(ctx.agents),
            )
        except ImportError:
            logger.debug("Metrics recording not available")
        except Exception as e:  # noqa: BLE001 - phase isolation
            logger.debug("Metrics recording failed: %s", e)

    def _emit_consensus_event(self, result: DebateResult) -> None:
        """Emit consensus event."""
        if "on_consensus" not in self.hooks:
            return

        self.hooks["on_consensus"](
            reached=result.consensus_reached,
            confidence=result.confidence,
            answer=result.final_answer,
        )

    def _emit_debate_end_event(self, result: DebateResult) -> None:
        """Emit debate end event."""
        if "on_debate_end" not in self.hooks:
            return

        self.hooks["on_debate_end"](
            duration=result.duration_seconds,
            rounds=result.rounds_used,
        )

    def _notify_debate_end(self, result: DebateResult) -> None:
        """Notify spectator of debate end."""
        if not self._notify_spectator:
            return

        self._notify_spectator(
            "debate_end",
            details=f"Complete in {result.duration_seconds:.1f}s",
            metric=result.confidence,
        )

    async def _extract_insights(self, result: DebateResult) -> None:
        """Extract and store insights."""
        if not self.insight_store:
            return

        try:
            # Import insight extractor
            try:
                from aragora.insights.extractor import InsightExtractor

                extractor = InsightExtractor()
            except ImportError:
                logger.debug("InsightExtractor not available")
                return

            insights = await extractor.extract(result)
            stored_count = await self.insight_store.store_debate_insights(insights)

            if stored_count > 0:
                logger.info(
                    "insights_extracted total=%s stored=%s", insights.total_insights, stored_count
                )
                if self._notify_spectator:
                    self._notify_spectator(
                        "insight_extracted",
                        details=f"{insights.total_insights} insights extracted",
                        metric=stored_count,
                    )
        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.warning("insight_extraction_failed error=%s", e)

    def _determine_winner(self, ctx: DebateContext) -> None:
        """Determine winner from vote tally."""
        if not ctx.vote_tally:
            return

        try:
            winner_agent = max(ctx.vote_tally.items(), key=lambda x: x[1])[0]
            ctx.winner_agent = winner_agent
            ctx.result.winner = winner_agent
        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.debug("Winner determination failed: %s", e)

    def _update_relationships(self, ctx: DebateContext) -> None:
        """Update agent relationships for grounded personas."""
        if not self._update_agent_relationships:
            return

        result = ctx.result
        debate_id = getattr(result, "id", None) or ctx.env.task[:50]

        self._update_agent_relationships(
            debate_id=debate_id,
            participants=[a.name for a in ctx.agents],
            winner=ctx.winner_agent,
            votes=result.votes,
        )

    async def _analyze_uncertainty(self, ctx: DebateContext) -> None:
        """Analyze uncertainty and disagreement in debate results.

        Uses the uncertainty estimator to:
        - Calculate collective confidence with proper calibration
        - Identify disagreement cruxes
        - Classify disagreement types
        - Emit uncertainty_analysis event for frontend

        This enriches the debate result with calibrated confidence metrics
        and helps identify follow-up debate topics.
        """
        estimator = get_uncertainty_estimator()
        if not estimator:
            return

        result = ctx.result
        if not result.votes:
            return

        try:
            # Build proposals dict from messages
            proposals = {}
            for msg in result.messages:
                if msg.role == "response" and msg.agent not in proposals:
                    proposals[msg.agent] = msg.content[:500]  # Truncate for analysis

            # Analyze disagreement
            metrics = estimator.analyze_disagreement(
                votes=result.votes,
                messages=result.messages,
                proposals=proposals,
            )

            # Attach uncertainty metrics to result (using setattr for optional attributes)
            setattr(result, "uncertainty_metrics", metrics.to_dict())

            # Update result confidence with calibrated value
            if metrics.collective_confidence > 0:
                setattr(result, "calibrated_confidence", metrics.collective_confidence)

            # Log uncertainty analysis
            logger.info(
                f"uncertainty_analysis confidence={metrics.collective_confidence:.2f} "
                f"disagreement={metrics.disagreement_type} cruxes={len(metrics.cruxes)}"
            )

            # Emit event for frontend
            if self.event_emitter:
                self.event_emitter.emit(
                    "uncertainty_analysis",
                    {
                        "loop_id": self.loop_id,
                        "collective_confidence": metrics.collective_confidence,
                        "confidence_interval": metrics.confidence_interval,
                        "disagreement_type": metrics.disagreement_type,
                        "cruxes": [c.to_dict() for c in metrics.cruxes],
                        "calibration_quality": metrics.calibration_quality,
                    },
                )

            # Notify spectator
            if self._notify_spectator and metrics.cruxes:
                self._notify_spectator(
                    "uncertainty_detected",
                    details=f"{len(metrics.cruxes)} cruxes identified",
                    metric=metrics.collective_confidence,
                )

        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.warning("uncertainty_analysis_failed error=%s", e)

    def _generate_disagreement(self, ctx: DebateContext) -> None:
        """Generate disagreement report."""
        if not self._generate_disagreement_report:
            return

        result = ctx.result
        result.disagreement_report = self._generate_disagreement_report(
            votes=result.votes,
            critiques=result.critiques,
            winner=ctx.winner_agent,
        )

        if result.disagreement_report:
            if result.disagreement_report.unanimous_critiques:
                logger.debug(
                    "disagreement_unanimous_critiques count=%s",
                    len(result.disagreement_report.unanimous_critiques),
                )
            if result.disagreement_report.split_opinions:
                logger.debug(
                    "disagreement_split_opinions count=%s",
                    len(result.disagreement_report.split_opinions),
                )

    async def _generate_verdict(self, ctx: DebateContext) -> None:
        """Generate grounded verdict."""
        if not self._create_grounded_verdict:
            return

        result = ctx.result
        result.grounded_verdict = self._create_grounded_verdict(result)

        if result.grounded_verdict:
            logger.info(f"grounding_score score={result.grounded_verdict.grounding_score:.0%}")
            if result.grounded_verdict.claims:
                logger.debug("grounding_claims count=%s", len(result.grounded_verdict.claims))

            self._emit_grounded_verdict_event(result)

    def _emit_grounded_verdict_event(self, result: DebateResult) -> None:
        """Emit grounded verdict event for frontend."""
        if not self.event_emitter or not result.grounded_verdict:
            return

        try:
            from aragora.events.types import StreamEvent, StreamEventType

            self.event_emitter.emit(
                StreamEvent(
                    type=StreamEventType.GROUNDED_VERDICT,
                    data=result.grounded_verdict.to_dict(),
                    loop_id=self.loop_id or "unknown",
                )
            )
        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.debug("Failed to emit grounded verdict event: %s", e)

    async def _verify_formally(self, result: DebateResult) -> None:
        """Perform formal Z3 verification for decidable claims."""
        if not self._verify_claims_formally:
            return

        try:
            await self._verify_claims_formally(result)
        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.debug("Formal verification failed: %s", e)

    def _analyze_beliefs(self, result: DebateResult) -> None:
        """Run belief network analysis for debate cruxes."""
        if not result.grounded_verdict or not result.grounded_verdict.claims:
            return

        try:
            # Try to import belief network
            try:
                from aragora.reasoning.belief import BeliefNetwork, BeliefPropagationAnalyzer

                network = BeliefNetwork()
            except ImportError:
                return

            # Add claims from grounded verdict
            for claim in result.grounded_verdict.claims[:20]:
                claim_id = getattr(claim, "claim_id", str(hash(claim.statement[:50])))
                network.add_claim(
                    claim_id=claim_id,
                    statement=claim.statement,
                    author=getattr(claim, "author", "unknown"),
                    initial_confidence=getattr(claim, "confidence", 0.5),
                )

            # Create analyzer and identify cruxes (top_k=5 roughly corresponds to 0.6 threshold)
            analyzer = BeliefPropagationAnalyzer(network)
            cruxes = analyzer.identify_debate_cruxes(top_k=5)
            setattr(result, "belief_cruxes", cruxes)

            if cruxes:
                logger.debug("belief_cruxes_identified count=%s", len(cruxes))
                for crux in cruxes[:3]:
                    logger.debug(
                        f"belief_crux claim={crux.get('claim', 'unknown')[:60]} "
                        f"uncertainty={crux.get('uncertainty', 0):.2f}"
                    )
        except (RuntimeError, AttributeError, ImportError) as e:  # noqa: BLE001
            logger.debug("Belief analysis failed: %s", e)

    def _log_completion(self, ctx: DebateContext) -> None:
        """Log completion and formatted conclusion."""
        result = ctx.result
        logger.info(
            f"debate_completed duration={result.duration_seconds:.1f}s "
            f"rounds={result.rounds_used} consensus={result.consensus_reached}"
        )

        if self._format_conclusion:
            conclusion = self._format_conclusion(result)
            logger.debug("debate_conclusion length=%s", len(conclusion))

    def _finalize_recording(self, ctx: DebateContext) -> None:
        """Finalize replay recording."""
        if not self.recorder:
            return

        try:
            result = ctx.result
            verdict = result.final_answer[:100] if result.final_answer else "incomplete"
            self.recorder.finalize(verdict, ctx.vote_tally)
        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.warning("Recorder finalize error: %s", e)
