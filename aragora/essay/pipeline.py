"""EssayRefinementPipeline -- end-to-end multi-model essay orchestration."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from aragora.agents.base import AgentType, create_agent
from aragora.essay.prompts import (
    build_drafting_prompt,
    build_extraction_prompt,
    build_polish_prompt,
)
from aragora.essay.rubric import EssayScore, evaluate_essay, load_rubric
from aragora.essay.synthesizer import EssaySynthesizer

logger = logging.getLogger(__name__)


@dataclass
class EssayRefinementPipeline:
    """Orchestrate extraction, parallel drafting, evaluation, synthesis, and polish.

    Parameters
    ----------
    models:
        Agent types used for parallel drafting (one draft per model).
    target_words:
        Approximate word count for the final essay.
    max_rounds:
        Maximum refinement iterations.
    quality_threshold:
        Overall score (0-1) at which refinement stops early.
    voice_notes:
        Optional stylistic guidance forwarded to drafting / synthesis prompts.
    rubric_path:
        Path to a YAML rubric file.  ``None`` uses the built-in default.
    """

    models: list[AgentType] = field(
        default_factory=lambda: ["anthropic-api", "openai-api", "gemini"]
    )
    target_words: int = 1200
    max_rounds: int = 3
    quality_threshold: float = 0.8
    voice_notes: str = ""
    rubric_path: str | None = None

    # ── Public API ────────────────────────────────────────────────────────

    async def run(
        self,
        raw_ideas: str,
        *,
        dry_run: bool = False,
        max_rounds: int | None = None,
    ) -> dict[str, Any]:
        """Execute the full essay refinement pipeline.

        Parameters
        ----------
        raw_ideas:
            Unstructured notes or brainstorm text.
        dry_run:
            When ``True``, stop after extraction (no drafting/scoring).
        max_rounds:
            Override ``self.max_rounds`` for this invocation.

        Returns
        -------
        dict
            Keys depend on *dry_run*:
            - dry_run: ``thesis``, ``outline``, ``raw_extraction``
            - full: ``final_essay``, ``final_score``, ``thesis``, ``outline``,
              ``rounds_used``, ``critique_history``
        """
        rounds = max_rounds if max_rounds is not None else self.max_rounds
        rubric = load_rubric(self.rubric_path)

        # Phase 1 -- extraction
        extraction = await self._extract_ideas(raw_ideas)
        thesis = extraction["thesis"]
        outline = extraction["outline"]

        if dry_run:
            return extraction

        # Phase 2 -- parallel drafting
        draft_dicts = await self._parallel_draft(thesis, outline)
        draft_model_names = [d["model"] for d in draft_dicts]

        # Phase 3+4 -- evaluate / synthesize loop
        critique_history: list[str] = []
        all_scores: list[dict[str, Any]] = []
        all_critiques: list[dict[str, str]] = []
        round_details: list[dict[str, Any]] = []
        current_draft = ""
        rounds_used = 1

        for round_idx in range(1, rounds + 1):
            if round_idx == 1:
                # First iteration: evaluate all drafts, synthesize best
                scores, critiques, raw = await self._evaluate_drafts(draft_dicts, rubric)
                critique_history.extend(c["text"] if isinstance(c, dict) else c for c in critiques)
                all_scores.extend(raw)
                all_critiques.extend(
                    c if isinstance(c, dict) else {"evaluator": "", "text": c} for c in critiques
                )

                # Store per-draft scores
                for i, dd in enumerate(draft_dicts):
                    dd["scores"] = [scores[i]] if i < len(scores) else []

                round_detail: dict[str, Any] = {
                    "round": round_idx,
                    "scores": [s.to_dict() for s in scores],
                    "critiques": list(critiques),
                    "draft_before": "",
                }
                current_draft = await self._synthesize(
                    draft_dicts,
                    scores,
                    critiques,
                    model_names=draft_model_names,
                )
                round_detail["draft_after"] = current_draft[:200] + "..."
                round_details.append(round_detail)
            else:
                # Subsequent: evaluate current draft, check threshold
                scores, critiques, raw = await self._evaluate_drafts([current_draft], rubric)
                critique_history.extend(c["text"] if isinstance(c, dict) else c for c in critiques)
                all_scores.extend(raw)
                all_critiques.extend(
                    c if isinstance(c, dict) else {"evaluator": "", "text": c} for c in critiques
                )

                round_detail = {
                    "round": round_idx,
                    "scores": [s.to_dict() for s in scores],
                    "critiques": list(critiques),
                    "draft_before": current_draft[:200] + "...",
                }

                if scores and scores[0].overall >= self.quality_threshold:
                    round_detail["draft_after"] = current_draft[:200] + "..."
                    round_details.append(round_detail)
                    break

                current_draft = await self._synthesize(
                    [current_draft],
                    scores,
                    critiques,
                )
                round_detail["draft_after"] = current_draft[:200] + "..."
                round_details.append(round_detail)

            rounds_used = round_idx

        # Phase 5 -- polish
        final_essay = await self._polish(current_draft)

        # Phase 6 -- final score (different model to avoid self-evaluation bias)
        final_score = await self._final_score(final_essay, rubric)

        return {
            "final_essay": final_essay,
            "final_score": final_score,
            "thesis": thesis,
            "outline": outline,
            "rounds_used": rounds_used,
            "critique_history": critique_history,
            # New fields
            "drafts": draft_dicts,
            "all_scores": all_scores,
            "all_critiques": all_critiques,
            "round_details": round_details,
        }

    # ── Private helpers ───────────────────────────────────────────────────

    async def _extract_ideas(self, raw_ideas: str) -> dict[str, Any]:
        """Use an LLM to extract a thesis and outline from *raw_ideas*."""
        agent = create_agent(self.models[0], name="extractor", role="proposer")
        prompt = build_extraction_prompt(raw_ideas, target_words=self.target_words)
        response = await agent.generate(prompt)

        thesis = ""
        outline = ""

        # Parse "THESIS:" line
        thesis_match = re.search(r"(?i)\*?\*?thesis\*?\*?[:\s]+(.+)", response)
        if thesis_match:
            thesis = thesis_match.group(1).strip()

        # Parse outline: everything after "OUTLINE:" header
        outline_match = re.search(r"(?i)\*?\*?outline\*?\*?[:\s]*\n([\s\S]+)", response)
        if outline_match:
            outline = outline_match.group(1).strip()

        return {
            "thesis": thesis,
            "outline": outline,
            "raw_extraction": response,
        }

    async def _parallel_draft(self, thesis: str, outline: str) -> list[dict[str, Any]]:
        """Create one draft per model in parallel.

        Returns a list of dicts with keys ``text``, ``model``, and ``model_index``.
        """

        async def _draft_one(model_type: AgentType, idx: int) -> dict[str, Any]:
            agent = create_agent(model_type, name=f"drafter-{idx}", role="proposer")
            prompt = build_drafting_prompt(
                thesis,
                outline,
                target_words=self.target_words,
                voice_notes=self.voice_notes,
            )
            text = await agent.generate(prompt)
            return {"text": text, "model": model_type, "model_index": idx}

        tasks = [_draft_one(m, i) for i, m in enumerate(self.models)]
        return list(await asyncio.gather(*tasks))

    async def _evaluate_drafts(
        self,
        drafts: Sequence[str | dict[str, Any]],
        rubric: dict[str, Any],
    ) -> tuple[list[EssayScore], list[dict[str, str]], list[dict[str, Any]]]:
        """Evaluate each draft with multiple models and return aggregated results.

        Each model in ``self.models[:3]`` evaluates every draft.  Scores are
        averaged per draft across evaluators.

        Returns
        -------
        tuple
            ``(aggregated_scores, all_critiques, raw_scores)`` where
            *aggregated_scores* is one ``EssayScore`` per draft (averaged
            across evaluators), *all_critiques* is a list of dicts with
            ``evaluator`` and ``text``, and *raw_scores* is every individual
            score entry with ``draft_index``, ``evaluator``, and ``score``.
        """
        evaluator_models = self.models[:3]

        raw_scores: list[dict[str, Any]] = []
        all_critiques: list[dict[str, str]] = []

        for model in evaluator_models:
            judge = create_agent(model, name=f"judge-{model}", role="critic")
            for i, draft in enumerate(drafts):
                if isinstance(draft, str):
                    draft_text = draft
                else:
                    draft_text = draft["text"]
                score = await evaluate_essay(
                    draft_text,
                    judge,
                    rubric=rubric,
                    model_name=model,
                )
                raw_scores.append(
                    {
                        "draft_index": i,
                        "evaluator": model,
                        "score": score,
                    }
                )
                all_critiques.extend(
                    {"evaluator": model, "text": note} for note in score.severity_notes
                )
                all_critiques.extend({"evaluator": model, "text": sug} for sug in score.suggestions)

        # Aggregate: average score per draft across evaluators
        from collections import defaultdict

        per_draft: dict[int, list[EssayScore]] = defaultdict(list)
        for entry in raw_scores:
            per_draft[entry["draft_index"]].append(entry["score"])

        aggregated: list[EssayScore] = []
        dim_fields = [
            "thesis_clarity",
            "argument_coherence",
            "evidence_grounding",
            "rhetorical_force",
            "concision",
            "factual_accuracy",
            "originality",
        ]
        for draft_idx in range(len(drafts)):
            scores_for_draft = per_draft.get(draft_idx, [])
            if not scores_for_draft:
                aggregated.append(EssayScore())
                continue
            n = len(scores_for_draft)
            kwargs: dict[str, Any] = {}
            for dim in dim_fields:
                kwargs[dim] = sum(getattr(s, dim) for s in scores_for_draft) / n
            # Merge qualitative feedback from all evaluators
            kwargs["severity_notes"] = []
            kwargs["suggestions"] = []
            for s in scores_for_draft:
                kwargs["severity_notes"].extend(s.severity_notes)
                kwargs["suggestions"].extend(s.suggestions)
            kwargs["weakest_paragraph"] = scores_for_draft[0].weakest_paragraph
            kwargs["strongest_paragraph"] = scores_for_draft[0].strongest_paragraph
            kwargs["factual_claims_to_verify"] = []
            for s in scores_for_draft:
                kwargs["factual_claims_to_verify"].extend(s.factual_claims_to_verify)
            agg = EssayScore(**kwargs)
            aggregated.append(agg)

        return aggregated, all_critiques, raw_scores

    async def _synthesize(
        self,
        drafts: list[str] | list[dict[str, Any]],
        scores: list[EssayScore],
        critiques: list[str] | list[dict[str, str]],
        *,
        model_names: list[str] | None = None,
    ) -> str:
        """Merge drafts into a single improved essay via EssaySynthesizer."""
        synth_model = self.models[0]
        agent = create_agent(synth_model, name="synthesizer", role="synthesizer")
        synthesizer = EssaySynthesizer(agent)

        # Normalise draft dicts to plain strings
        draft_texts = [d["text"] if isinstance(d, dict) else d for d in drafts]

        # Normalise attributed critiques to plain strings
        critique_texts = [c["text"] if isinstance(c, dict) else c for c in critiques]

        # Derive model names from draft dicts when not explicitly provided
        if model_names is None:
            model_names = [d.get("model", "") if isinstance(d, dict) else "" for d in drafts]

        return await synthesizer.synthesize(
            draft_texts,
            scores,
            critique_texts,
            target_words=self.target_words,
            voice_notes=self.voice_notes,
            model_names=model_names,
        )

    async def _polish(self, draft: str) -> str:
        """Final style polish pass."""
        agent = create_agent(self.models[0], name="polisher", role="proposer")
        prompt = build_polish_prompt(
            draft,
            target_words=self.target_words,
            voice_notes=self.voice_notes,
        )
        return await agent.generate(prompt)

    async def _final_score(
        self,
        essay: str,
        rubric: dict[str, Any],
    ) -> EssayScore:
        """Score the final essay using a DIFFERENT model to avoid self-eval bias."""
        # Pick the last model (different from synthesizer which uses models[0])
        judge_model = self.models[-1] if len(self.models) > 1 else self.models[0]
        judge = create_agent(judge_model, name="final-judge", role="critic")
        return await evaluate_essay(essay, judge, rubric=rubric)
