"""PR review protocol schema + types.

This module defines the packet shape and role catalog for PR reviews
(:class:`PRReviewProtocolPacket`, :class:`PRReviewBinding`,
:data:`REVIEW_ROLES`, slot catalog). It is a **schema module** — it
does not itself invoke reviewers or produce the active ensemble state.

Two-state model
---------------
The protocol now operates with two distinct status values:

* :data:`PROTOCOL_STATUS` (module-level) — the *fallback default* for
  packets constructed without explicit status. Remains
  ``"metadata_heuristic"`` to accurately label packets that emerge
  from this schema module alone without an active ensemble run.

* Per-packet ``status`` field — set by the **active realization** when
  real reviewers execute. The :mod:`aragora.pdb` path (worker +
  real_invoker + invoker_factory + response_parser + protocol)
  invokes Claude, GPT, Gemini, Grok, DeepSeek, Kimi, Qwen, and
  Mistral, populates ``dissenting_views`` with per-lens votes, and
  emits packets with status reflecting the real heterogeneous
  ensemble execution.

The test contract (:mod:`tests.pdb.test_protocol`) explicitly verifies
this distinction: when PDB runs, the resulting packet's status is
*different* from :data:`PROTOCOL_STATUS`, precisely so that callers
can tell a fallback/heuristic packet apart from a real
heterogeneous-ensemble run.

Active realization status (as of 2026-04-22):
    PR #6404 wired Claude + GPT ProviderInvoker; PR #6425 completed
    Phase B with gemini/grok/deepseek/kimi/qwen/mistral slots; PR #6421
    shipped the single-PR dogfood CLI. Packets emitted via
    :mod:`aragora.pdb.protocol` carry a status reflecting the real
    ensemble run, not the fallback.

See also: ``docs/THESIS.md`` § Implementation gaps, issue #6374.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence, cast

from aragora.review.protocol import DissentPosition, Recommendation
from aragora.review.provider_slots import (
    ProviderSlotAvailabilitySummary,
    ProviderSlotDefinition,
    ProviderSlotResolution,
    ProviderSlotResolver,
)
from aragora.review.reviewer_output import ReviewerOutput, validate_reviewer_outputs

PROTOCOL_VERSION = "pr_review_protocol.v1"
# Fallback default for packets constructed without explicit status.
# Packets produced by the active aragora.pdb ensemble path carry their
# own status that differs from this value — see module docstring.
PROTOCOL_STATUS = "metadata_heuristic"
EXECUTED_PROTOCOL_STATUS = "heterogeneous_ensemble_v1"
FALLBACK_PROTOCOL_STATUS = "metadata_heuristic_fallback"

RECOMMEND_APPROVE = "approve_candidate"
RECOMMEND_APPROVE_WITH_FOLLOWUPS = "approve_with_followups"
RECOMMEND_ATTENTION = "needs_human_attention"
RECOMMEND_REPAIR = "repair_first"

REVIEW_ROLES: tuple[str, ...] = (
    "logic_reviewer",
    "security_reviewer",
    "maintainability_reviewer",
    "skeptic",
    "synthesizer",
)

MIN_EXECUTED_REVIEWERS = 3
MAX_EXECUTED_REVIEWERS = 3
LIVE_REVIEW_TIMEOUT_SECONDS = 60.0
MAX_LIVE_DIFF_CHARS = 16_000


def create_agent(*args: Any, **kwargs: Any) -> Any:
    """Lazily construct live reviewer agents while preserving monkeypatch seam."""

    from aragora.agents.base import create_agent as _create_agent

    return _create_agent(*args, **kwargs)


_SLOT_CATALOG: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    ("logic", "logic_reviewer", "core", "claude", ("claude", "anthropic-api")),
    ("security", "security_reviewer", "core", "gpt", ("codex", "openai-api", "openai")),
    (
        "maintainability",
        "maintainability_reviewer",
        "heterodox",
        "gemini",
        ("gemini-cli", "gemini"),
    ),
    ("skeptic", "skeptic", "heterodox", "grok", ("grok-cli", "grok")),
    ("regulatory", "skeptic", "regulatory", "mistral", ("mistral-api", "mistral")),
)


@dataclass(slots=True)
class PRReviewBinding:
    repo: str
    pr_number: int
    base_sha: str
    head_sha: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PRReviewFinding:
    finding_id: str
    category: str
    severity: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    source: str = PROTOCOL_STATUS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PRReviewProtocolPacket:
    protocol_version: str
    status: str
    binding: PRReviewBinding
    review_roles: list[str]
    provider_slots: list[ProviderSlotResolution]
    availability_summary: ProviderSlotAvailabilitySummary
    recommendation_class: str
    recommendation_reason: str
    confidence: float
    confidence_basis: str
    dissent_summary: str
    dissenting_views: list[dict[str, Any]]
    validation_summary: dict[str, Any]
    top_findings: list[PRReviewFinding]
    cost_estimate: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "protocol_version": self.protocol_version,
            "status": self.status,
            "binding": self.binding.to_dict(),
            "review_roles": list(self.review_roles),
            "provider_slots": [slot.to_packet_dict() for slot in self.provider_slots],
            "availability_summary": self.availability_summary.to_dict(),
            "recommendation_class": self.recommendation_class,
            "recommendation_reason": self.recommendation_reason,
            "confidence": round(float(self.confidence), 2),
            "confidence_basis": self.confidence_basis,
            "dissent_summary": self.dissent_summary,
            "dissenting_views": list(self.dissenting_views),
            "validation_summary": dict(self.validation_summary),
            "top_findings": [finding.to_dict() for finding in self.top_findings],
            "cost_estimate": dict(self.cost_estimate),
        }
        return payload


@dataclass(frozen=True, slots=True)
class PRReviewerExecutionFailure:
    slot_id: str
    review_role: str
    provider: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PRReviewProtocol:
    protocol_version: str = PROTOCOL_VERSION
    review_roles: tuple[str, ...] = REVIEW_ROLES
    provider_slots: tuple[ProviderSlotDefinition, ...] = field(default_factory=tuple)

    @classmethod
    def default(cls) -> PRReviewProtocol:
        return cls(
            provider_slots=tuple(
                ProviderSlotDefinition(
                    slot_id=slot_id,
                    review_role=review_role,
                    lens=lens,
                    family=family,
                    candidates=candidates,
                )
                for slot_id, review_role, lens, family, candidates in _SLOT_CATALOG
            )
        )

    def resolve_provider_slots(self) -> list[ProviderSlotResolution]:
        return ProviderSlotResolver().resolve_slots(self.provider_slots)

    def metadata_provider_slots(
        self,
    ) -> tuple[list[ProviderSlotResolution], ProviderSlotAvailabilitySummary]:
        """Return packet-shaped slot metadata without probing provider availability.

        Merge-packet readiness uses this protocol object as advisory metadata.
        It must not import/register every agent implementation unless live
        reviewers are actually being executed.
        """

        provider_slots = [
            ProviderSlotResolution(
                slot_id=slot.slot_id,
                review_role=slot.review_role,
                lens=slot.lens,
                family=slot.family,
                selected_provider=None,
                status="not_probed",
                detail="provider availability not probed for metadata-only packet",
                candidates=list(slot.candidates),
            )
            for slot in self.provider_slots
        ]
        core_slots = [slot for slot in self.provider_slots if slot.lens == "core"]
        availability_summary = ProviderSlotAvailabilitySummary(
            total_slots=len(self.provider_slots),
            resolved_slots=0,
            unresolved_slots=[slot.slot_id for slot in self.provider_slots],
            core_slots_total=len(core_slots),
            core_slots_resolved=0,
            available_families=[],
            unresolved_families=sorted({slot.family for slot in self.provider_slots}),
            opt_in_slots=[],
            degraded=True,
        )
        return provider_slots, availability_summary

    def execute_live_reviewers(
        self,
        *,
        repo: str,
        pr_number: int,
        title: str,
        base_sha: str,
        head_sha: str,
        checks_summary: str,
        changed_files: list[str],
        diff_text: str,
        machine_recommendation: str,
        machine_recommendation_reason: str,
    ) -> tuple[list[ReviewerOutput], list[PRReviewerExecutionFailure]]:
        import asyncio

        return asyncio.run(
            self._execute_live_reviewers_async(
                repo=repo,
                pr_number=pr_number,
                title=title,
                base_sha=base_sha,
                head_sha=head_sha,
                checks_summary=checks_summary,
                changed_files=changed_files,
                diff_text=diff_text,
                machine_recommendation=machine_recommendation,
                machine_recommendation_reason=machine_recommendation_reason,
            )
        )

    async def _execute_live_reviewers_async(
        self,
        *,
        repo: str,
        pr_number: int,
        title: str,
        base_sha: str,
        head_sha: str,
        checks_summary: str,
        changed_files: list[str],
        diff_text: str,
        machine_recommendation: str,
        machine_recommendation_reason: str,
    ) -> tuple[list[ReviewerOutput], list[PRReviewerExecutionFailure]]:
        import asyncio

        resolutions = self.resolve_provider_slots()
        selected: list[ProviderSlotResolution] = []
        failures: list[PRReviewerExecutionFailure] = []
        for slot in resolutions:
            if len(selected) >= MAX_EXECUTED_REVIEWERS:
                break
            if not slot.selected_provider:
                failures.append(
                    PRReviewerExecutionFailure(
                        slot_id=slot.slot_id,
                        review_role=slot.review_role,
                        provider="",
                        reason=slot.detail,
                    )
                )
                continue
            selected.append(slot)
        if not selected:
            return ([], failures)

        results = await asyncio.gather(
            *[
                self._execute_single_reviewer(
                    slot=slot,
                    repo=repo,
                    pr_number=pr_number,
                    title=title,
                    base_sha=base_sha,
                    head_sha=head_sha,
                    checks_summary=checks_summary,
                    changed_files=changed_files,
                    diff_text=diff_text,
                    machine_recommendation=machine_recommendation,
                    machine_recommendation_reason=machine_recommendation_reason,
                )
                for slot in selected
            ]
        )
        outputs: list[ReviewerOutput] = []
        for output, failure in results:
            if output is not None:
                outputs.append(output)
            if failure is not None:
                failures.append(failure)
        return (outputs, failures)

    async def _execute_single_reviewer(
        self,
        *,
        slot: ProviderSlotResolution,
        repo: str,
        pr_number: int,
        title: str,
        base_sha: str,
        head_sha: str,
        checks_summary: str,
        changed_files: list[str],
        diff_text: str,
        machine_recommendation: str,
        machine_recommendation_reason: str,
    ) -> tuple[ReviewerOutput | None, PRReviewerExecutionFailure | None]:
        provider = slot.selected_provider or ""
        if not provider:
            return (
                None,
                PRReviewerExecutionFailure(
                    slot_id=slot.slot_id,
                    review_role=slot.review_role,
                    provider="",
                    reason="provider slot is unresolved",
                ),
            )
        started = time.perf_counter()
        try:
            import asyncio

            agent = create_agent(
                cast(Any, provider),
                name=f"pr_review_{slot.slot_id}",
                role="critic",
                timeout=LIVE_REVIEW_TIMEOUT_SECONDS,
            )
            prompt = self._build_live_review_prompt(
                slot=slot,
                repo=repo,
                pr_number=pr_number,
                title=title,
                base_sha=base_sha,
                head_sha=head_sha,
                checks_summary=checks_summary,
                changed_files=changed_files,
                diff_text=diff_text,
                machine_recommendation=machine_recommendation,
                machine_recommendation_reason=machine_recommendation_reason,
            )
            raw = await asyncio.wait_for(
                agent.generate(prompt, context=None),
                timeout=LIVE_REVIEW_TIMEOUT_SECONDS,
            )
            payload = self._extract_reviewer_payload(raw)
            payload.update(
                {
                    "reviewer_id": f"{provider}:{slot.slot_id}",
                    "slot_id": slot.slot_id,
                    "provider": provider,
                    "lens": slot.lens,
                    "family": slot.family,
                    "round_index": 1,
                    "latency_ms": max(int((time.perf_counter() - started) * 1000), 0),
                }
            )
            parsed = ReviewerOutput.from_dict(payload)
            normalized = ReviewerOutput(
                reviewer_id=f"{provider}:{slot.slot_id}",
                slot_id=slot.slot_id,
                provider=provider,
                lens=slot.lens,
                family=slot.family,
                recommendation_class=parsed.recommendation_class,
                confidence=parsed.confidence,
                summary=parsed.summary,
                top_findings=parsed.top_findings,
                evidence_refs=parsed.evidence_refs,
                risk_flags=parsed.risk_flags,
                open_questions=parsed.open_questions,
                round_index=1,
                latency_ms=max(int((time.perf_counter() - started) * 1000), 0),
                cost_usd=parsed.cost_usd,
                schema_version=parsed.schema_version,
            )
            normalized.validate()
            return (normalized, None)
        except Exception as exc:  # pragma: no cover - exercised via tests through failure surface
            return (
                None,
                PRReviewerExecutionFailure(
                    slot_id=slot.slot_id,
                    review_role=slot.review_role,
                    provider=provider,
                    reason=str(exc),
                ),
            )

    def build_packet(
        self,
        *,
        repo: str,
        pr_number: int,
        title: str,
        base_sha: str,
        head_sha: str,
        mergeable: str,
        review_decision: str,
        checks_summary: str,
        has_failures: bool,
        has_pending: bool,
        additions: int,
        deletions: int,
        changed_files: int,
        labels: list[str],
        high_risk_paths: list[str],
        validation_commands: list[str],
        machine_recommendation: str,
        machine_recommendation_reason: str,
        reviewer_outputs: Sequence[ReviewerOutput] | None = None,
        execution_failures: Sequence[PRReviewerExecutionFailure] | None = None,
    ) -> PRReviewProtocolPacket:
        has_live_reviewer_results = bool(reviewer_outputs or execution_failures)
        if has_live_reviewer_results:
            slot_resolver = ProviderSlotResolver()
            provider_slots = slot_resolver.resolve_slots(self.provider_slots)
            availability_summary = slot_resolver.summarize(provider_slots)
        else:
            provider_slots, availability_summary = self.metadata_provider_slots()
        findings = self._build_findings(
            has_failures=has_failures,
            has_pending=has_pending,
            mergeable=mergeable,
            additions=additions,
            deletions=deletions,
            labels=labels,
            high_risk_paths=high_risk_paths,
            checks_summary=checks_summary,
            title=title,
        )
        validation_summary = {
            "checks_summary": checks_summary,
            "has_failures": has_failures,
            "has_pending": has_pending,
            "mergeable": mergeable,
            "review_decision": review_decision,
            "validation_commands": list(validation_commands),
            "changed_files": changed_files,
            "diffstat": {
                "additions": additions,
                "deletions": deletions,
            },
        }
        normalized_failures = list(execution_failures or [])
        valid_outputs: tuple[ReviewerOutput, ...] = ()
        if reviewer_outputs:
            try:
                validate_reviewer_outputs(reviewer_outputs)
                valid_outputs = tuple(reviewer_outputs)
            except ValueError as exc:
                normalized_failures.append(
                    PRReviewerExecutionFailure(
                        slot_id="validation",
                        review_role="validation",
                        provider="protocol",
                        reason=str(exc),
                    )
                )

        if len(valid_outputs) >= MIN_EXECUTED_REVIEWERS:
            return self._build_executed_packet(
                repo=repo,
                pr_number=pr_number,
                base_sha=base_sha,
                head_sha=head_sha,
                provider_slots=provider_slots,
                availability_summary=availability_summary,
                reviewer_outputs=valid_outputs,
                validation_summary=validation_summary,
            )

        packet = self._build_metadata_packet(
            repo=repo,
            pr_number=pr_number,
            base_sha=base_sha,
            head_sha=head_sha,
            provider_slots=provider_slots,
            availability_summary=availability_summary,
            findings=findings,
            validation_summary=validation_summary,
            machine_recommendation=machine_recommendation,
            machine_recommendation_reason=machine_recommendation_reason,
            has_pending=has_pending,
        )
        if valid_outputs or normalized_failures:
            self._annotate_fallback_packet(
                packet,
                provider_slots=provider_slots,
                reviewer_outputs=valid_outputs,
                execution_failures=normalized_failures,
            )
        return packet

    def _build_metadata_packet(
        self,
        *,
        repo: str,
        pr_number: int,
        base_sha: str,
        head_sha: str,
        provider_slots: list[ProviderSlotResolution],
        availability_summary: ProviderSlotAvailabilitySummary,
        findings: list[PRReviewFinding],
        validation_summary: dict[str, Any],
        machine_recommendation: str,
        machine_recommendation_reason: str,
        has_pending: bool,
    ) -> PRReviewProtocolPacket:
        confidence = self._confidence_for(
            machine_recommendation=machine_recommendation,
            findings=findings,
            has_pending=has_pending,
        )
        slot_count = max(len(provider_slots), 1)
        cost_estimate = {
            "currency": "USD",
            "low": round(slot_count * 0.6, 2),
            "high": round(slot_count * 1.0, 2),
            "basis": "bounded heterogeneous metadata-first protocol",
        }
        if machine_recommendation == RECOMMEND_APPROVE:
            dissent_summary = "No heterogeneous dissent recorded yet; packet is metadata-derived."
        else:
            dissent_summary = (
                "No heterogeneous dissent recorded yet; recommendation is driven by metadata risk "
                "signals pending full protocol execution."
            )
        return PRReviewProtocolPacket(
            protocol_version=self.protocol_version,
            status=PROTOCOL_STATUS,
            binding=PRReviewBinding(
                repo=repo,
                pr_number=pr_number,
                base_sha=base_sha,
                head_sha=head_sha,
            ),
            review_roles=list(self.review_roles),
            provider_slots=provider_slots,
            availability_summary=availability_summary,
            recommendation_class=machine_recommendation,
            recommendation_reason=machine_recommendation_reason,
            confidence=confidence,
            confidence_basis=PROTOCOL_STATUS,
            dissent_summary=dissent_summary,
            dissenting_views=[],
            validation_summary=validation_summary,
            top_findings=findings[:5],
            cost_estimate=cost_estimate,
        )

    def _build_executed_packet(
        self,
        *,
        repo: str,
        pr_number: int,
        base_sha: str,
        head_sha: str,
        provider_slots: list[ProviderSlotResolution],
        availability_summary: ProviderSlotAvailabilitySummary,
        reviewer_outputs: Sequence[ReviewerOutput],
        validation_summary: dict[str, Any],
    ) -> PRReviewProtocolPacket:
        (
            recommendation_class,
            recommendation_reason,
            confidence,
            confidence_basis,
        ) = self._recommendation_from_outputs(reviewer_outputs)
        dissenting_views = self._dissenting_views_from_outputs(
            reviewer_outputs,
            provider_slots=provider_slots,
            final_recommendation=recommendation_class,
        )
        packet_validation = dict(validation_summary)
        packet_validation["reviewer_execution"] = {
            "status": EXECUTED_PROTOCOL_STATUS,
            "reviewer_count": len(reviewer_outputs),
            "reviewer_ids": [output.reviewer_id for output in reviewer_outputs],
            "providers": [output.provider for output in reviewer_outputs],
            "dissent_count": len(dissenting_views),
        }
        total_cost = round(sum(output.cost_usd for output in reviewer_outputs), 6)
        return PRReviewProtocolPacket(
            protocol_version=self.protocol_version,
            status=EXECUTED_PROTOCOL_STATUS,
            binding=PRReviewBinding(
                repo=repo,
                pr_number=pr_number,
                base_sha=base_sha,
                head_sha=head_sha,
            ),
            review_roles=list(self.review_roles),
            provider_slots=provider_slots,
            availability_summary=availability_summary,
            recommendation_class=recommendation_class,
            recommendation_reason=recommendation_reason,
            confidence=confidence,
            confidence_basis=confidence_basis,
            dissent_summary=self._dissent_summary_from_outputs(
                reviewer_outputs,
                dissenting_views=dissenting_views,
            ),
            dissenting_views=dissenting_views,
            validation_summary=packet_validation,
            top_findings=self._build_findings_from_outputs(reviewer_outputs)[:5],
            cost_estimate={
                "currency": "USD",
                "low": round(total_cost, 2),
                "high": round(total_cost, 2),
                "basis": "executed heterogeneous reviewer outputs",
            },
        )

    def _annotate_fallback_packet(
        self,
        packet: PRReviewProtocolPacket,
        *,
        provider_slots: list[ProviderSlotResolution],
        reviewer_outputs: Sequence[ReviewerOutput],
        execution_failures: Sequence[PRReviewerExecutionFailure],
    ) -> None:
        partial_dissent = self._dissenting_views_from_outputs(
            reviewer_outputs,
            provider_slots=provider_slots,
            final_recommendation=packet.recommendation_class,
        )
        failure_reason = "insufficient_live_reviews"
        if not reviewer_outputs and execution_failures:
            failure_reason = "execution_failed"
        packet.status = f"{FALLBACK_PROTOCOL_STATUS}_{failure_reason}"
        packet.confidence_basis = packet.status
        packet.dissenting_views = partial_dissent
        if partial_dissent:
            packet.dissent_summary = (
                "Partial live reviewer execution captured dissent, but not enough valid "
                "heterogeneous reviewer outputs were available to upgrade the protocol status."
            )
        else:
            packet.dissent_summary = (
                "Live reviewer execution did not yield a complete bounded panel; falling back "
                "to metadata-derived recommendation."
            )
        packet.validation_summary = {
            **packet.validation_summary,
            "reviewer_execution": {
                "status": packet.status,
                "partial_reviewer_count": len(reviewer_outputs),
                "failure_count": len(execution_failures),
                "failures": [failure.to_dict() for failure in execution_failures],
            },
        }

    def _build_findings(
        self,
        *,
        has_failures: bool,
        has_pending: bool,
        mergeable: str,
        additions: int,
        deletions: int,
        labels: list[str],
        high_risk_paths: list[str],
        checks_summary: str,
        title: str,
    ) -> list[PRReviewFinding]:
        findings: list[PRReviewFinding] = []
        if has_failures:
            findings.append(
                PRReviewFinding(
                    finding_id="validation-failing",
                    category="validation",
                    severity="high",
                    summary="CI is failing on the current PR head.",
                    evidence=[checks_summary],
                )
            )
        if mergeable == "CONFLICTING":
            findings.append(
                PRReviewFinding(
                    finding_id="merge-conflict",
                    category="mergeability",
                    severity="high",
                    summary="PR has merge conflicts against the base branch.",
                    evidence=[mergeable],
                )
            )
        if high_risk_paths:
            findings.append(
                PRReviewFinding(
                    finding_id="high-risk-paths",
                    category="risk_surface",
                    severity="medium" if not has_failures else "high",
                    summary="PR touches high-consequence paths that warrant direct human review.",
                    evidence=high_risk_paths[:5],
                )
            )
        if additions + deletions > 500:
            findings.append(
                PRReviewFinding(
                    finding_id="large-diff",
                    category="change_size",
                    severity="medium",
                    summary="Diff size exceeds the bounded fast-review threshold.",
                    evidence=[f"+{additions}/-{deletions}"],
                )
            )
        if has_pending:
            findings.append(
                PRReviewFinding(
                    finding_id="checks-pending",
                    category="validation",
                    severity="medium",
                    summary="Not all required validation has completed yet.",
                    evidence=[checks_summary],
                )
            )
        if labels:
            parked = [
                label for label in labels if label in {"stale", "do-not-merge", "wip", "blocked"}
            ]
            if parked:
                findings.append(
                    PRReviewFinding(
                        finding_id="parked-label",
                        category="workflow_state",
                        severity="medium",
                        summary="PR carries a parked label and should remain in a human-attention lane.",
                        evidence=parked,
                    )
                )
        if not findings:
            findings.append(
                PRReviewFinding(
                    finding_id="bounded-green",
                    category="summary",
                    severity="low",
                    summary="No blocking metadata signals detected for this PR.",
                    evidence=[title, checks_summary],
                )
            )
        return findings

    def _build_findings_from_outputs(
        self, reviewer_outputs: Sequence[ReviewerOutput]
    ) -> list[PRReviewFinding]:
        findings: list[PRReviewFinding] = []
        for output in reviewer_outputs:
            for index, finding in enumerate(output.top_findings[:2], start=1):
                evidence = list(finding.evidence)
                for file_path in finding.files:
                    if file_path not in evidence:
                        evidence.append(file_path)
                findings.append(
                    PRReviewFinding(
                        finding_id=f"{output.slot_id}-{index}",
                        category=finding.category.value,
                        severity=finding.severity.value,
                        summary=finding.claim,
                        evidence=evidence[:5],
                        source=output.reviewer_id,
                    )
                )
        if not findings:
            findings.append(
                PRReviewFinding(
                    finding_id="reviewer-output-missing",
                    category="validation",
                    severity="medium",
                    summary="Live reviewers executed but returned no structured findings.",
                    evidence=["reviewer execution returned empty findings"],
                    source=EXECUTED_PROTOCOL_STATUS,
                )
            )
        return findings

    def _recommendation_from_outputs(
        self, reviewer_outputs: Sequence[ReviewerOutput]
    ) -> tuple[str, str, float, str]:
        totals = dict.fromkeys(Recommendation, 0.0)
        counts = dict.fromkeys(Recommendation, 0)
        for output in reviewer_outputs:
            weight = max(float(output.confidence), 0.05)
            totals[output.recommendation_class] += weight
            counts[output.recommendation_class] += 1
        ordered = sorted(totals.items(), key=lambda item: item[1], reverse=True)
        winner, winner_weight = ordered[0]
        runner_up_weight = ordered[1][1] if len(ordered) > 1 else 0.0
        average_confidence = sum(output.confidence for output in reviewer_outputs) / max(
            len(reviewer_outputs), 1
        )
        split_margin = winner_weight - runner_up_weight
        if split_margin < 0.15 and counts[winner] < len(reviewer_outputs):
            confidence = max(0.25, round(average_confidence - 0.15, 2))
            return (
                RECOMMEND_ATTENTION,
                (
                    "executed panel split across reviewer recommendations; keep this in the "
                    "human-attention lane"
                ),
                confidence,
                f"{EXECUTED_PROTOCOL_STATUS}.split_panel",
            )
        dissent_count = len(reviewer_outputs) - counts[winner]
        confidence = max(
            0.2,
            min(
                0.98, round(average_confidence - ((dissent_count / len(reviewer_outputs)) * 0.1), 2)
            ),
        )
        reason = (
            f"{counts[winner]}/{len(reviewer_outputs)} executed reviewers recommend {winner.value}"
        )
        if dissent_count:
            reason += f"; {dissent_count} reviewer(s) dissent"
        return (winner.value, reason, confidence, EXECUTED_PROTOCOL_STATUS)

    def _dissenting_views_from_outputs(
        self,
        reviewer_outputs: Sequence[ReviewerOutput],
        *,
        provider_slots: Sequence[ProviderSlotResolution],
        final_recommendation: str,
    ) -> list[dict[str, Any]]:
        views: list[dict[str, Any]] = []
        for output in reviewer_outputs:
            if output.recommendation_class.value == final_recommendation:
                continue
            role = self._role_for_slot(output.slot_id, provider_slots)
            entry: dict[str, Any] = {
                "agent": output.reviewer_id,
                "position": self._dissent_position_for(output.recommendation_class.value).value,
                "reason": output.summary,
            }
            if role:
                entry["role"] = role
            views.append(entry)
        return views

    def _dissent_summary_from_outputs(
        self,
        reviewer_outputs: Sequence[ReviewerOutput],
        *,
        dissenting_views: Sequence[dict[str, Any]],
    ) -> str:
        if not dissenting_views:
            return "Executed heterogeneous reviewers were unanimous on the current PR head."
        return (
            f"Executed heterogeneous reviewers recorded {len(dissenting_views)} dissenting "
            f"view(s) across {len(reviewer_outputs)} reviewer outputs."
        )

    def _role_for_slot(
        self, slot_id: str, provider_slots: Sequence[ProviderSlotResolution]
    ) -> str | None:
        for slot in provider_slots:
            if slot.slot_id == slot_id:
                return slot.review_role
        return None

    def _dissent_position_for(self, recommendation_class: str) -> DissentPosition:
        if recommendation_class == RECOMMEND_APPROVE:
            return DissentPosition.APPROVE
        if recommendation_class == RECOMMEND_REPAIR:
            return DissentPosition.REQUEST_CHANGES
        return DissentPosition.DEFER

    def _build_live_review_prompt(
        self,
        *,
        slot: ProviderSlotResolution,
        repo: str,
        pr_number: int,
        title: str,
        base_sha: str,
        head_sha: str,
        checks_summary: str,
        changed_files: list[str],
        diff_text: str,
        machine_recommendation: str,
        machine_recommendation_reason: str,
    ) -> str:
        changed_files_text = (
            "\n".join(f"- {path}" for path in changed_files[:25]) or "- (none listed)"
        )
        truncated_diff = diff_text.strip()
        if len(truncated_diff) > MAX_LIVE_DIFF_CHARS:
            truncated_diff = truncated_diff[:MAX_LIVE_DIFF_CHARS] + "\n...[diff truncated]..."
        return (
            "You are one reviewer in Aragora's bounded heterogeneous PR review protocol.\n"
            "Return JSON only. No prose before or after the JSON.\n\n"
            f"Role: {slot.review_role}\n"
            f"Slot id: {slot.slot_id}\n"
            f"Lens: {slot.lens}\n"
            f"Family: {slot.family}\n"
            f"Provider: {slot.selected_provider}\n"
            f"Repo: {repo}\n"
            f"PR: #{pr_number}\n"
            f"Title: {title}\n"
            f"Base SHA: {base_sha}\n"
            f"Head SHA: {head_sha}\n"
            f"Checks summary: {checks_summary}\n"
            f"Current metadata recommendation: {machine_recommendation}\n"
            f"Reason: {machine_recommendation_reason}\n\n"
            "Changed files:\n"
            f"{changed_files_text}\n\n"
            "Diff excerpt:\n"
            f"{truncated_diff}\n\n"
            "Return a JSON object with this exact schema shape:\n"
            "{\n"
            '  "schema_version": "reviewer_output.v1",\n'
            '  "reviewer_id": "set to any non-empty placeholder; caller will overwrite",\n'
            '  "slot_id": "set to any non-empty placeholder; caller will overwrite",\n'
            '  "provider": "set to any non-empty placeholder; caller will overwrite",\n'
            '  "lens": "set to any non-empty placeholder; caller will overwrite",\n'
            '  "family": "set to any non-empty placeholder; caller will overwrite",\n'
            '  "recommendation_class": "approve_candidate | approve_with_followups | needs_human_attention | repair_first",\n'
            '  "confidence": 0.0,\n'
            '  "summary": "1-2 sentence reviewer summary",\n'
            '  "top_findings": [\n'
            "    {\n"
            '      "category": "logic | security | maintainability | skeptic | validation",\n'
            '      "severity": "low | medium | high",\n'
            '      "claim": "specific issue or bounded-green claim",\n'
            '      "evidence": ["short evidence string"],\n'
            '      "files": ["repo/path.py"]\n'
            "    }\n"
            "  ],\n"
            '  "evidence_refs": [\n'
            "    {\n"
            '      "kind": "file",\n'
            '      "path": "repo/path.py",\n'
            '      "line_range": [10, 20],\n'
            '      "quote": "short excerpt"\n'
            "    }\n"
            "  ],\n"
            '  "risk_flags": [],\n'
            '  "open_questions": [],\n'
            '  "round_index": 1,\n'
            '  "latency_ms": 0,\n'
            '  "cost_usd": 0.0\n'
            "}\n"
            "If you do not see a concrete defect, return one validation or bounded-green finding "
            "instead of an empty findings array. Ground all claims in the diff or changed files."
        )

    def _extract_reviewer_payload(self, raw_text: str) -> dict[str, Any]:
        text = str(raw_text or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise ValueError("reviewer output did not contain a JSON object") from None
            payload = json.loads(text[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("reviewer output JSON must be an object")
        return payload

    def _confidence_for(
        self,
        *,
        machine_recommendation: str,
        findings: list[PRReviewFinding],
        has_pending: bool,
    ) -> float:
        if machine_recommendation == RECOMMEND_REPAIR:
            base = 0.9
        elif machine_recommendation == RECOMMEND_APPROVE:
            base = 0.72
        else:
            base = 0.58
        medium_or_higher = sum(1 for finding in findings if finding.severity in {"medium", "high"})
        penalty = min(0.18, medium_or_higher * 0.04)
        if has_pending and machine_recommendation != RECOMMEND_REPAIR:
            penalty += 0.04
        return max(0.15, min(0.98, round(base - penalty, 2)))


def default_pr_review_protocol() -> PRReviewProtocol:
    return PRReviewProtocol.default()


__all__ = [
    "EXECUTED_PROTOCOL_STATUS",
    "FALLBACK_PROTOCOL_STATUS",
    "PRReviewBinding",
    "PRReviewFinding",
    "PRReviewerExecutionFailure",
    "PRReviewProtocol",
    "PRReviewProtocolPacket",
    "ProviderSlotAvailabilitySummary",
    "PROTOCOL_STATUS",
    "PROTOCOL_VERSION",
    "ProviderSlotDefinition",
    "ProviderSlotResolution",
    "RECOMMEND_APPROVE",
    "RECOMMEND_ATTENTION",
    "RECOMMEND_REPAIR",
    "REVIEW_ROLES",
    "default_pr_review_protocol",
]
