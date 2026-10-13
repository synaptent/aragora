"""
Evidence refresh module for debate rounds.

Handles refreshing evidence based on claims made during debate rounds.
This module is extracted from debate_rounds.py for better modularity.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.core import Critique
    from aragora.debate.context import DebateContext

logger = logging.getLogger(__name__)

# Timeout for async callbacks (evidence refresh can be slow).
# Reduced from 30s to 10s for interactive latency -- if evidence refresh
# takes longer than 10s, the debate continues without the extra evidence.
DEFAULT_CALLBACK_TIMEOUT = 10.0


async def _with_callback_timeout(
    coro,
    timeout: float = DEFAULT_CALLBACK_TIMEOUT,
    default=None,
):
    """Execute coroutine with timeout, returning default on timeout.

    This prevents debates from stalling indefinitely when callbacks
    like evidence refresh hang.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Callback timed out after %ss, using default: %s", timeout, default)
        return default


class EvidenceRefresher:
    """
    Refreshes evidence based on claims made in proposals and critiques.

    This class extracts factual claims from proposals and critiques,
    then searches for new evidence to support or refute those claims.
    The fresh evidence is injected into the context for the revision phase.

    Usage:
        refresher = EvidenceRefresher(
            refresh_callback=arena._refresh_evidence,
            hooks=arena.hooks,
            notify_spectator=arena._notify_spectator,
        )
        await refresher.refresh_for_round(ctx, round_num, partial_critiques)
    """

    def __init__(
        self,
        refresh_callback: Callable | None = None,
        hooks: dict | None = None,
        notify_spectator: Callable | None = None,
        timeout: float = DEFAULT_CALLBACK_TIMEOUT,
        skill_registry=None,
        enable_skills: bool = False,
    ):
        """
        Initialize the evidence refresher.

        Args:
            refresh_callback: Async callback for refreshing evidence.
                              Signature: (text: str, ctx: DebateContext, round: int) -> int
            hooks: Dictionary of event hooks
            notify_spectator: Callback for spectator notifications
            timeout: Timeout in seconds for refresh operations
            skill_registry: Optional SkillRegistry for skill-based evidence
            enable_skills: Whether to invoke skills for evidence refresh
        """
        self._refresh_evidence = refresh_callback
        self.hooks = hooks or {}
        self._notify_spectator = notify_spectator
        self._timeout = timeout
        self.skill_registry = skill_registry
        self.enable_skills = enable_skills

    async def refresh_for_round(
        self,
        ctx: DebateContext,
        round_num: int,
        partial_critiques: list[Critique],
    ) -> int:
        """
        Refresh evidence based on claims made in the current round.

        Extracts factual claims from proposals and critiques, then
        searches for new evidence to support or refute those claims.
        The fresh evidence is injected into the context for the revision phase.

        Args:
            ctx: The DebateContext with proposals and critiques
            round_num: Current round number
            partial_critiques: List of critiques from current/recent rounds

        Returns:
            Number of new evidence snippets found, or 0 if refresh was skipped
        """
        if not self._refresh_evidence:
            return 0

        # Only refresh evidence every other round to avoid API overload
        if round_num % 2 == 0:
            return 0

        try:
            # Collect text from proposals and recent critiques
            texts_to_analyze = []

            # Add proposal content
            for agent_name, proposal in ctx.proposals.items():
                if proposal:
                    texts_to_analyze.append(proposal[:2000])  # Limit per proposal

            # Add recent critique content
            for critique in partial_critiques[-5:]:  # Last 5 critiques
                critique_text = (
                    critique.to_prompt() if hasattr(critique, "to_prompt") else str(critique)
                )
                texts_to_analyze.append(critique_text[:1000])

            if not texts_to_analyze:
                return 0

            combined_text = "\n".join(texts_to_analyze)

            # Call the refresh callback with timeout protection
            refreshed = await _with_callback_timeout(
                self._refresh_evidence(combined_text, ctx, round_num),
                timeout=self._timeout,
                default=0,  # Return 0 snippets on timeout
            )

            # Also invoke skills for evidence refresh if enabled
            skill_snippets = 0
            if self.enable_skills and self.skill_registry:
                skill_snippets = await self._refresh_with_skills(combined_text, ctx)
                if skill_snippets:
                    logger.info(
                        "skill_evidence_refreshed round=%s new_snippets=%s",
                        round_num,
                        skill_snippets,
                    )

            total_refreshed = (refreshed or 0) + skill_snippets

            if total_refreshed:
                logger.info(
                    "evidence_refreshed round=%s new_snippets=%s", round_num, total_refreshed
                )

                # Notify spectator
                if self._notify_spectator:
                    self._notify_spectator(
                        "evidence",
                        details=f"Refreshed evidence: {total_refreshed} new sources",
                        metric=total_refreshed,
                        agent="system",
                    )

                # Emit evidence refresh event
                if "on_evidence_refresh" in self.hooks:
                    self.hooks["on_evidence_refresh"](
                        round_num=round_num,
                        new_snippets=total_refreshed,
                    )

            return total_refreshed

        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.warning("Evidence refresh failed for round %s: %s", round_num, e)
            return 0

    async def _refresh_with_skills(
        self,
        text: str,
        ctx: DebateContext,
    ) -> int:
        """Refresh evidence using skills for claim-specific searches.

        Args:
            text: Combined text from proposals and critiques
            ctx: The DebateContext

        Returns:
            Number of new evidence snippets from skills
        """
        if not self.skill_registry or not self.enable_skills:
            return 0

        try:
            from aragora.reasoning.evidence_collector import EvidenceSnippet
            from aragora.types.skills import SkillCapability, SkillContext, SkillStatus

            # Create skill execution context
            skill_ctx = SkillContext(
                user_id="debate-system",
                permissions=["debate:evidence"],
                config={"source": "evidence_refresh", "text_length": len(text)},
            )

            # Find debate-compatible skills
            debate_skills = []
            for manifest in self.skill_registry.list_skills():
                if SkillCapability.EXTERNAL_API in manifest.capabilities:
                    if "debate" in manifest.tags:
                        debate_skills.append(manifest)
                    elif manifest.name in ("web_search", "search", "research"):
                        debate_skills.append(manifest)

            if not debate_skills:
                return 0

            # Extract key claims/queries from text (simple heuristic)
            # Use first 500 chars as a focused query
            query = text[:500] if len(text) > 500 else text

            snippets_added = 0
            for skill_manifest in debate_skills[:2]:  # Limit to 2 skills per refresh
                try:
                    result = await asyncio.wait_for(
                        self.skill_registry.invoke(
                            skill_manifest.name,
                            {"query": query},
                            skill_ctx,
                        ),
                        timeout=8.0,  # Shorter timeout for refresh
                    )

                    if result.status == SkillStatus.SUCCESS and result.data:
                        snippet = EvidenceSnippet(
                            content=str(result.data)[:2000],
                            source=f"skill:{skill_manifest.name}",
                            relevance=0.65,  # Slightly lower relevance for refresh
                            metadata={
                                "skill": skill_manifest.name,
                                "refresh": True,
                            },
                        )

                        # Add to evidence pack if exists
                        if ctx.evidence_pack:
                            ctx.evidence_pack.snippets.append(snippet)
                            snippets_added += 1

                except asyncio.TimeoutError:
                    logger.debug("[skills] Refresh timeout for %s", skill_manifest.name)
                except Exception as e:  # noqa: BLE001 - phase isolation
                    logger.debug("[skills] Refresh error for %s: %s", skill_manifest.name, e)

            return snippets_added

        except ImportError as e:
            logger.debug("[skills] Refresh skipped (missing imports): %s", e)
            return 0
        except Exception as e:  # noqa: BLE001 - phase isolation
            logger.warning("[skills] Refresh error: %s", e)
            return 0
