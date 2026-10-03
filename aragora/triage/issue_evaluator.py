"""Heterogeneous panel evaluation for an individual issue.

This module is the core of the triage calibration system. It assembles a
locked prompt rubric, runs the prompt against a panel of frontier agents
in parallel, parses each model's structured response, aggregates verdicts,
and returns an audit-ready receipt.

The panel and rubric are intentionally decoupled from the CLI so the
library can be reused from notebooks or future Arena integrations.

Receipt-equivalence (per Codex's review)
----------------------------------------
Even though this bypasses ``aragora.debate.Arena`` for speed, every model
invocation persists:
    prompt, model id, raw response, parsed verdict, confidence, cost,
    latency, dissent.
That preserves the auditable-heterogeneous-deliberation differentiator
without paying the full Arena boot cost per issue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Sequence

from aragora.triage.evidence import IssueEvidence
from aragora.triage.receipts import IssueDebateReceipt

logger = logging.getLogger(__name__)

VERDICT_CATEGORIES: tuple[str, ...] = (
    "keep",
    "refine",
    "consolidate",
    "close-obsolete",
    "close-duplicate",
    "close-malformed",
    "flag-for-human",
)

AUTOMATION_VALUE_VALUES: tuple[str, ...] = (
    "valuable",
    "neutral",
    "noise",
    "n/a",
)

CONFIDENCE_CLASSES: tuple[str, ...] = (
    "easy-call",
    "needs-spot-check",
    "do-not-act-without-human",
)

PANEL_PROMPT_RUBRIC = """You are one of three independent frontier models evaluating a single
GitHub issue for the Aragora repository as part of a calibration audit.

The standard is SUBSTANTIVE VALUE, not authorship. Automation-generated
issues can be excellent. Human-generated issues can be noise. Judge what
is actually in front of you.

The founder reading your verdict may NOT already know whether this
issue is good. Your job is not just to label it -- it is to TEACH the
founder how you reached the verdict, with concrete evidence anchors and
clear inspection guidance. A non-expert reviewer should be able to
trust or challenge your recommendation by reading what you wrote.

Output a strict JSON object with this exact shape (no prose outside the
JSON, no markdown fences):

{
  "verdict": "<one of: keep | refine | consolidate | close-obsolete | close-duplicate | close-malformed | flag-for-human>",
  "confidence": <float 0.0-1.0>,
  "confidence_class": "<one of: easy-call | needs-spot-check | do-not-act-without-human>",
  "automation_value": "<one of: valuable | neutral | noise | n/a>",
  "rationale": "<3-6 sentences citing concrete evidence>",
  "suggested_action": "<one actionable sentence the founder can do>",
  "evidence_used": ["<list of specific evidence anchors you relied on: e.g. 'body para 2', 'broken file ref aragora/foo.py', 'dup candidate #6371'>"],
  "what_to_inspect": "<2-3 sentences naming what the founder should look at to trust or challenge this verdict; cite file paths, issue numbers, or sections of the body>",
  "safety_note": "<one sentence: why is acting on this verdict SAFE, or what could go wrong if you act on it>",
  "refined_title": "<optional, only when verdict=refine: a tighter title you would rewrite the issue to>",
  "refined_body_outline": "<optional, only when verdict=refine: a short bullet outline (3-5 lines) of what the rewritten issue body should cover>",
  "consolidate_with": <optional, only when verdict in (consolidate, close-duplicate): integer issue number this should merge into>
}

Verdicts:
- keep: substantively valuable, leave open as-is.
- refine: valuable but needs scope tightening, repro steps, or an owner.
- consolidate: should be merged with a referenced/related issue.
- close-obsolete: referenced code/feature/file no longer exists in HEAD.
- close-duplicate: exact duplicate of an existing issue.
- close-malformed: empty body, template only, no actionable content.
- flag-for-human: you are uncertain or the panel may legitimately
  disagree; defer to a human reviewer.

Confidence classes (your self-assessment of how risky it is to act on
your verdict without further human review):
- easy-call: evidence is unambiguous; safe to act on without spot-check.
- needs-spot-check: evidence is mostly clear but a quick human glance
  is wise before acting.
- do-not-act-without-human: ambiguity, missing context, or potential
  for false-positive close; require explicit human review.

Automation value (orthogonal to verdict):
- valuable: automation produced something worth keeping or refining.
  This is an EXPLICIT POSITIVE outcome -- automation authorship is not
  a strike against the issue.
- neutral: automation contribution neither strengthens nor weakens.
- noise: automation produced low-signal output that wastes attention.
- n/a: issue is not automation-generated.

You MUST ground your verdict in the evidence block below:
- If referenced files are broken in HEAD, weight `close-obsolete` more.
- If duplicate candidates exist above similarity 0.55, weight
  `close-duplicate` or `consolidate`; cite the candidate number in
  `consolidate_with`.
- If the body is empty or template-only, weight `close-malformed`.
- If the issue describes a real-but-undefined problem, lean `refine`
  and provide a `refined_title` + `refined_body_outline`.
- If you cannot decide between two verdicts without more information,
  use `flag-for-human` with `do-not-act-without-human`.

Return ONLY the JSON object. No prose, no fences, no preamble."""


@dataclass(frozen=True)
class PanelMember:
    """One participant in the triage panel."""

    agent_type: str
    model_id: str
    estimated_input_cost_per_1k: float
    estimated_output_cost_per_1k: float
    role: str = "critic"
    nickname: str | None = None


DEFAULT_PANEL: tuple[PanelMember, ...] = (
    PanelMember(
        agent_type="anthropic-api",
        model_id="claude-opus-5",
        # Opus 5 is $5/$25 per MTok (catalog 2026-07-24). The previous
        # 0.015/0.075 here were stale Opus 4.1-era ($15/$75) rates.
        estimated_input_cost_per_1k=0.005,
        estimated_output_cost_per_1k=0.025,
        nickname="opus",
    ),
    PanelMember(
        agent_type="openai-api",
        model_id="gpt-4.1",
        estimated_input_cost_per_1k=0.005,
        estimated_output_cost_per_1k=0.020,
        nickname="gpt",
    ),
    PanelMember(
        agent_type="gemini",
        model_id="gemini-3.1-pro-preview",
        estimated_input_cost_per_1k=0.003,
        estimated_output_cost_per_1k=0.012,
        nickname="gemini",
    ),
)


@dataclass
class PerModelVerdict:
    """Parsed verdict for a single model invocation."""

    panel_member: PanelMember
    verdict: str
    confidence: float
    automation_value: str
    rationale: str
    suggested_action: str
    evidence_used: list[str]
    raw_response: str
    prompt_chars: int
    response_chars: int
    cost_usd: float
    latency_seconds: float
    confidence_class: str = "needs-spot-check"
    what_to_inspect: str = ""
    safety_note: str = ""
    refined_title: str = ""
    refined_body_outline: str = ""
    consolidate_with: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.panel_member.model_id,
            "agent_type": self.panel_member.agent_type,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "confidence_class": self.confidence_class,
            "automation_value": self.automation_value,
            "rationale": self.rationale,
            "suggested_action": self.suggested_action,
            "evidence_used": list(self.evidence_used),
            "what_to_inspect": self.what_to_inspect,
            "safety_note": self.safety_note,
            "refined_title": self.refined_title,
            "refined_body_outline": self.refined_body_outline,
            "consolidate_with": self.consolidate_with,
            "raw_response": self.raw_response,
            "prompt_chars": self.prompt_chars,
            "response_chars": self.response_chars,
            "cost_usd": round(self.cost_usd, 6),
            "latency_seconds": round(self.latency_seconds, 3),
            "error": self.error,
        }


@dataclass
class FounderRecommendation:
    """Founder-facing recommendation distilled from the panel."""

    action: str
    safety: str
    inspect: str
    refined_title: str = ""
    refined_body_outline: str = ""
    consolidate_with: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "safety": self.safety,
            "inspect": self.inspect,
            "refined_title": self.refined_title,
            "refined_body_outline": self.refined_body_outline,
            "consolidate_with": self.consolidate_with,
        }


@dataclass
class AggregateVerdict:
    """Aggregated panel verdict + dissent metadata."""

    verdict: str
    confidence: float
    consensus: str
    rationale: str
    automation_value: str
    suggested_action: str
    confidence_class: str = "needs-spot-check"
    recommendation: FounderRecommendation | None = None
    notes: list[str] = field(default_factory=list)


def build_panel(
    agent_types: Sequence[str] | None = None,
    *,
    base: Sequence[PanelMember] = DEFAULT_PANEL,
) -> list[PanelMember]:
    """Return a panel filtered to the requested agent types (default = all)."""
    if not agent_types:
        return list(base)
    requested = {at.strip() for at in agent_types if at.strip()}
    panel = [member for member in base if member.agent_type in requested]
    missing = requested - {m.agent_type for m in panel}
    if missing:
        raise ValueError(
            f"Unknown agent types for triage panel: {sorted(missing)}. "
            f"Allowed: {sorted({m.agent_type for m in base})}"
        )
    if len(panel) < 2:
        raise ValueError(
            f"Triage panel requires at least 2 heterogeneous models; got {len(panel)}."
        )
    return panel


def build_panel_prompt(evidence: IssueEvidence) -> str:
    """Assemble the locked rubric + evidence block prompt sent to each model."""
    issue = evidence.issue
    file_lines = (
        "\n".join(
            f"  - {ref['path']} (exists_in_head={ref['exists_in_head']})"
            for ref in evidence.referenced_files
        )
        or "  - (none detected)"
    )
    related_lines = (
        "\n".join(
            f"  - #{ref['number']} state={ref.get('state', '?')} title={ref.get('title', '')[:80]}"
            for ref in evidence.referenced_issues
        )
        or "  - (none resolved)"
    )
    dup_lines = (
        "\n".join(
            f"  - #{cand['number']} similarity={cand['similarity']} "
            f"title={cand.get('title', '')[:80]}"
            for cand in evidence.duplicate_candidates
        )
        or "  - (none above threshold)"
    )
    body_excerpt = (issue.body or "").strip()
    if len(body_excerpt) > 4000:
        body_excerpt = body_excerpt[:4000] + "\n[... truncated ...]"

    labels_joined = ", ".join(issue.labels) or "(none)"
    head_label = evidence.repo_head_sha or "?"
    if evidence.notes:
        newline = "\n- "
        notes_block = "- " + newline.join(evidence.notes)
    else:
        notes_block = "(none)"

    evidence_block = f"""ISSUE
- number: #{issue.number}
- title: {issue.title}
- author: {issue.author} (automation_origin={evidence.is_automation_generated})
- labels: {labels_joined}
- state: {issue.state}
- created_at: {issue.created_at}
- updated_at: {issue.updated_at}
- url: {issue.url}

BODY
{body_excerpt or "(empty)"}

REFERENCED FILES (resolved against HEAD {head_label})
{file_lines}

REFERENCED ISSUES / PRS
{related_lines}

DUPLICATE CANDIDATES (title-shingle Jaccard, threshold 0.40)
{dup_lines}

NOTES
{notes_block}"""

    return f"{PANEL_PROMPT_RUBRIC}\n\nEVIDENCE BLOCK:\n{evidence_block}\n"


_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_model_response(raw: str) -> dict[str, Any]:
    """Best-effort parse of a model's JSON triage response.

    Returns a normalized dict with the rubric fields. Raises ValueError
    if the response cannot be coerced into the expected shape.
    """
    if not raw or not raw.strip():
        raise ValueError("empty response")
    candidate = raw.strip()
    fence_match = _JSON_FENCE_PATTERN.search(candidate)
    if fence_match:
        candidate = fence_match.group(1)
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"unparseable JSON response: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("response is not a JSON object")

    verdict = str(parsed.get("verdict", "")).strip()
    if verdict not in VERDICT_CATEGORIES:
        raise ValueError(f"verdict '{verdict}' not in {VERDICT_CATEGORIES}")
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"non-numeric confidence: {parsed.get('confidence')!r}") from exc
    confidence = max(0.0, min(1.0, confidence))

    automation_value = str(parsed.get("automation_value", "n/a")).strip()
    if automation_value not in AUTOMATION_VALUE_VALUES:
        automation_value = "n/a"

    rationale = str(parsed.get("rationale", "")).strip()
    suggested = str(parsed.get("suggested_action", "")).strip()
    evidence_used_raw = parsed.get("evidence_used", []) or []
    if isinstance(evidence_used_raw, str):
        evidence_used = [evidence_used_raw]
    else:
        evidence_used = [str(item) for item in evidence_used_raw][:20]

    confidence_class = str(parsed.get("confidence_class", "")).strip()
    if confidence_class not in CONFIDENCE_CLASSES:
        confidence_class = _infer_confidence_class(confidence)

    what_to_inspect = str(parsed.get("what_to_inspect", "")).strip()
    safety_note = str(parsed.get("safety_note", "")).strip()
    refined_title = str(parsed.get("refined_title", "")).strip()
    refined_body_outline = str(parsed.get("refined_body_outline", "")).strip()
    consolidate_with_raw = parsed.get("consolidate_with")
    consolidate_with: int | None = None
    if consolidate_with_raw is not None:
        try:
            consolidate_with = int(consolidate_with_raw)
        except (TypeError, ValueError):
            consolidate_with = None

    return {
        "verdict": verdict,
        "confidence": confidence,
        "confidence_class": confidence_class,
        "automation_value": automation_value,
        "rationale": rationale,
        "suggested_action": suggested,
        "evidence_used": evidence_used,
        "what_to_inspect": what_to_inspect,
        "safety_note": safety_note,
        "refined_title": refined_title,
        "refined_body_outline": refined_body_outline,
        "consolidate_with": consolidate_with,
    }


def _infer_confidence_class(confidence: float) -> str:
    """Fallback confidence_class derivation when a model omits the field."""
    if confidence >= 0.8:
        return "easy-call"
    if confidence >= 0.6:
        return "needs-spot-check"
    return "do-not-act-without-human"


def aggregate_verdicts(
    per_model: Sequence[PerModelVerdict],
) -> AggregateVerdict:
    """Combine per-model verdicts into a single panel verdict with dissent.

    Aggregation rules:
    - Drop verdicts that errored.
    - If all valid verdicts agree on the category -> consensus = unanimous.
    - If a strict majority agrees -> consensus = majority.
    - Otherwise consensus = split; pick the highest-confidence verdict
      and surface dissent in the rationale; flag for human if all
      verdicts disagree and average confidence < 0.55.
    - Automation value is taken from the majority; ties default to
      ``neutral`` when at least one valid verdict, ``n/a`` otherwise.
    """
    valid = [pm for pm in per_model if pm.error is None]
    if not valid:
        errors = "; ".join(f"{pm.panel_member.model_id}:{pm.error}" for pm in per_model)
        return AggregateVerdict(
            verdict="flag-for-human",
            confidence=0.0,
            consensus="unclear",
            rationale=f"All panel members failed: {errors}",
            automation_value="n/a",
            suggested_action="Re-run triage when models are reachable.",
            confidence_class="do-not-act-without-human",
            recommendation=FounderRecommendation(
                action="Do not act. Re-run after restoring panel reachability.",
                safety="UNSAFE to act: no model returned a parseable verdict.",
                inspect="Inspect run logs and provider auth state before re-running.",
            ),
        )

    verdict_counts = Counter(pm.verdict for pm in valid)
    top_verdict, top_count = verdict_counts.most_common(1)[0]
    distinct = len(verdict_counts)
    total = len(valid)

    if distinct == 1:
        consensus = "unanimous"
    elif top_count > total / 2:
        consensus = "majority"
    else:
        consensus = "split"

    if consensus == "split":
        valid_sorted = sorted(valid, key=lambda pm: pm.confidence, reverse=True)
        chosen = valid_sorted[0]
        avg_conf = sum(pm.confidence for pm in valid) / total
        if avg_conf < 0.55:
            verdict = "flag-for-human"
            rationale = (
                f"Panel split ({dict(verdict_counts)}) with low average confidence "
                f"({avg_conf:.2f}); deferring to human reviewer."
            )
        else:
            verdict = chosen.verdict
            rationale = (
                f"Panel split ({dict(verdict_counts)}); highest-confidence verdict "
                f"({chosen.panel_member.model_id} at {chosen.confidence:.2f}) selected: "
                f"{chosen.rationale}"
            )
        suggested = chosen.suggested_action
    else:
        winners = [pm for pm in valid if pm.verdict == top_verdict]
        verdict = top_verdict
        avg_conf = sum(pm.confidence for pm in winners) / len(winners)
        rationale_segments = [
            f"{pm.panel_member.model_id} ({pm.confidence:.2f}): {pm.rationale}" for pm in winners
        ]
        rationale = " | ".join(rationale_segments)
        suggested = winners[0].suggested_action

    automation_counts = Counter(pm.automation_value for pm in valid)
    automation_top, _automation_count = automation_counts.most_common(1)[0]
    if (
        len(automation_counts) > 1
        and automation_counts.most_common(2)[0][1] == automation_counts.most_common(2)[1][1]
    ):
        automation_top = "neutral" if any(pm.automation_value != "n/a" for pm in valid) else "n/a"

    confidence = sum(pm.confidence for pm in valid) / total
    confidence_class = _aggregate_confidence_class(consensus, confidence, valid)
    recommendation = _build_recommendation(
        verdict=verdict,
        confidence_class=confidence_class,
        consensus=consensus,
        valid=valid,
        verdict_counts=verdict_counts,
        suggested=suggested,
    )

    return AggregateVerdict(
        verdict=verdict,
        confidence=round(confidence, 3),
        consensus=consensus,
        rationale=rationale,
        automation_value=automation_top,
        suggested_action=suggested,
        confidence_class=confidence_class,
        recommendation=recommendation,
        notes=[f"verdict_counts={dict(verdict_counts)}"],
    )


def _aggregate_confidence_class(
    consensus: str,
    avg_confidence: float,
    valid: Sequence[PerModelVerdict],
) -> str:
    """Derive a single confidence class from per-model classes + consensus.

    Rules (deliberately conservative -- when in doubt, escalate):
    - any model said `do-not-act-without-human` -> do-not-act-without-human
    - consensus split -> do-not-act-without-human (panel disagrees)
    - unanimous + avg conf >= 0.8 + every model said easy-call -> easy-call
    - majority + avg conf >= 0.7 + no dissenter said do-not-act -> needs-spot-check
    - otherwise -> needs-spot-check
    """
    per_model_classes = [pm.confidence_class for pm in valid]
    if "do-not-act-without-human" in per_model_classes:
        return "do-not-act-without-human"
    if consensus == "split":
        return "do-not-act-without-human"
    if (
        consensus == "unanimous"
        and avg_confidence >= 0.8
        and all(cls == "easy-call" for cls in per_model_classes)
    ):
        return "easy-call"
    return "needs-spot-check"


def _build_recommendation(
    *,
    verdict: str,
    confidence_class: str,
    consensus: str,
    valid: Sequence[PerModelVerdict],
    verdict_counts: Counter[str],
    suggested: str,
) -> FounderRecommendation:
    """Distill a single founder-facing recommendation from the panel."""
    inspect_pieces: list[str] = []
    safety_pieces: list[str] = []
    refined_title = ""
    refined_body_outline = ""
    consolidate_with: int | None = None

    for pm in valid:
        if pm.verdict != verdict:
            continue
        if pm.what_to_inspect:
            inspect_pieces.append(f"[{pm.panel_member.model_id}] {pm.what_to_inspect}")
        if pm.safety_note:
            safety_pieces.append(f"[{pm.panel_member.model_id}] {pm.safety_note}")
        if not refined_title and pm.refined_title:
            refined_title = pm.refined_title
        if not refined_body_outline and pm.refined_body_outline:
            refined_body_outline = pm.refined_body_outline
        if consolidate_with is None and pm.consolidate_with is not None:
            consolidate_with = pm.consolidate_with

    if not inspect_pieces:
        inspect_pieces.append(
            "Read the issue body, then check whether the referenced code still exists."
        )
    if not safety_pieces:
        if confidence_class == "easy-call":
            safety_pieces.append("Panel unanimous and high-confidence; action is reversible.")
        elif confidence_class == "needs-spot-check":
            safety_pieces.append("Panel mostly aligned but a quick human glance is wise.")
        else:
            safety_pieces.append(
                "Panel disagrees or confidence is low; DO NOT act without human review."
            )

    action_descriptions = {
        "keep": "Leave the issue open as-is.",
        "refine": "Rewrite the issue with the suggested title and outline; keep it open.",
        "consolidate": "Merge into the suggested target issue and close this one.",
        "close-obsolete": "Close: referenced code/feature no longer exists in HEAD.",
        "close-duplicate": "Close: duplicate of the cited target issue.",
        "close-malformed": "Close: no actionable content.",
        "flag-for-human": "Do not act automatically. Triage manually.",
    }
    action = action_descriptions.get(verdict, suggested or "Manual review.")

    if confidence_class == "do-not-act-without-human":
        action = f"DO NOT ACT WITHOUT HUMAN REVIEW. Tentative verdict: {verdict}. {action}"

    return FounderRecommendation(
        action=action,
        safety=" ".join(safety_pieces),
        inspect=" ".join(inspect_pieces),
        refined_title=refined_title,
        refined_body_outline=refined_body_outline,
        consolidate_with=consolidate_with,
    )


def estimate_cost_usd(
    *,
    panel: Sequence[PanelMember],
    issue_count: int,
    avg_prompt_chars: int = 4500,
    avg_response_chars: int = 1500,
) -> dict[str, Any]:
    """Project total cost for a triage run before any model is called.

    Token estimate uses the 4-chars-per-token heuristic. Returns a dict
    with per-model and total projections suitable for printing as a
    pre-run summary.
    """
    prompt_tokens = max(1, avg_prompt_chars // 4)
    response_tokens = max(1, avg_response_chars // 4)
    per_call: dict[str, dict[str, float]] = {}
    total_cost = 0.0
    for member in panel:
        input_cost = prompt_tokens / 1000 * member.estimated_input_cost_per_1k
        output_cost = response_tokens / 1000 * member.estimated_output_cost_per_1k
        per_call_cost = input_cost + output_cost
        total_for_member = per_call_cost * issue_count
        per_call[member.model_id] = {
            "per_issue_usd": round(per_call_cost, 5),
            "issues": issue_count,
            "subtotal_usd": round(total_for_member, 4),
        }
        total_cost += total_for_member
    return {
        "panel": [m.model_id for m in panel],
        "issues": issue_count,
        "avg_prompt_chars": avg_prompt_chars,
        "avg_response_chars": avg_response_chars,
        "per_model": per_call,
        "total_usd": round(total_cost, 4),
    }


def _estimate_per_call_cost(
    member: PanelMember,
    *,
    prompt_chars: int,
    response_chars: int,
) -> float:
    prompt_tokens = max(1, prompt_chars // 4)
    response_tokens = max(1, response_chars // 4)
    return (
        prompt_tokens / 1000 * member.estimated_input_cost_per_1k
        + response_tokens / 1000 * member.estimated_output_cost_per_1k
    )


AgentGenerator = Callable[[PanelMember, str], Awaitable[str]]


async def evaluate_issue(
    evidence: IssueEvidence,
    *,
    panel: Sequence[PanelMember] = DEFAULT_PANEL,
    generator: AgentGenerator,
    timeout_seconds: float = 60.0,
    now_iso: str | None = None,
) -> IssueDebateReceipt:
    """Run the panel against a single issue and return an audit receipt.

    Args:
        evidence: Pre-model evidence assembled by
            :func:`aragora.triage.evidence.gather_evidence`.
        panel: Heterogeneous panel members.
        generator: Async callable ``(member, prompt) -> raw_response``.
            Production wires this to ``aragora.agents.create_agent(...).generate``.
            Tests inject a deterministic stub.
        timeout_seconds: Per-model deadline.
        now_iso: Timestamp override for deterministic receipts in tests.

    Returns:
        ``IssueDebateReceipt`` with per-model rows and the aggregated verdict.
    """
    started = now_iso or datetime.now(timezone.utc).isoformat()
    started_monotonic = time.monotonic()
    prompt = build_panel_prompt(evidence)

    async def _call_member(member: PanelMember) -> PerModelVerdict:
        member_start = time.monotonic()
        raw = ""
        error: str | None = None
        try:
            raw = await asyncio.wait_for(generator(member, prompt), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            error = "timeout"
        except (RuntimeError, ValueError, ConnectionError, OSError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        latency = time.monotonic() - member_start
        parsed: dict[str, Any] = {
            "verdict": "flag-for-human",
            "confidence": 0.0,
            "confidence_class": "do-not-act-without-human",
            "automation_value": "n/a",
            "rationale": "",
            "suggested_action": "",
            "evidence_used": [],
            "what_to_inspect": "",
            "safety_note": "",
            "refined_title": "",
            "refined_body_outline": "",
            "consolidate_with": None,
        }
        if error is None:
            try:
                parsed = parse_model_response(raw)
            except ValueError as exc:
                error = f"parse_error: {exc}"
        cost = _estimate_per_call_cost(
            member,
            prompt_chars=len(prompt),
            response_chars=len(raw),
        )
        return PerModelVerdict(
            panel_member=member,
            verdict=parsed["verdict"],
            confidence=parsed["confidence"],
            confidence_class=parsed.get("confidence_class", "needs-spot-check"),
            automation_value=parsed["automation_value"],
            rationale=parsed["rationale"],
            suggested_action=parsed["suggested_action"],
            evidence_used=parsed["evidence_used"],
            what_to_inspect=parsed.get("what_to_inspect", ""),
            safety_note=parsed.get("safety_note", ""),
            refined_title=parsed.get("refined_title", ""),
            refined_body_outline=parsed.get("refined_body_outline", ""),
            consolidate_with=parsed.get("consolidate_with"),
            raw_response=raw,
            prompt_chars=len(prompt),
            response_chars=len(raw),
            cost_usd=cost,
            latency_seconds=latency,
            error=error,
        )

    tasks = [_call_member(member) for member in panel]
    per_model = await asyncio.gather(*tasks)
    aggregate = aggregate_verdicts(per_model)
    finished = datetime.now(timezone.utc).isoformat() if now_iso is None else now_iso
    total_cost = sum(pm.cost_usd for pm in per_model)
    recommendation_payload = (
        aggregate.recommendation.to_dict() if aggregate.recommendation else None
    )
    receipt = IssueDebateReceipt(
        issue_number=evidence.issue.number,
        issue_title=evidence.issue.title,
        issue_url=evidence.issue.url,
        issue_author=evidence.issue.author,
        is_automation_generated=evidence.is_automation_generated,
        panel=[member.model_id for member in panel],
        prompt=prompt,
        per_model=[pm.to_dict() for pm in per_model],
        aggregate_verdict=aggregate.verdict,
        aggregate_confidence=aggregate.confidence,
        aggregate_consensus=aggregate.consensus,
        aggregation_rationale=aggregate.rationale,
        confidence_class=aggregate.confidence_class,
        recommendation=recommendation_payload,
        automation_value=aggregate.automation_value,
        suggested_action=aggregate.suggested_action,
        evidence=evidence.to_dict(),
        started_at=started,
        finished_at=finished,
        cost_usd=round(total_cost, 6),
        latency_seconds=round(time.monotonic() - started_monotonic, 3),
        notes=list(aggregate.notes),
    )
    return receipt
