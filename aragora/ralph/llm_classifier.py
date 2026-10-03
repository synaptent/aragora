"""LLM-powered blocker classification for campaign supervision.

Replaces keyword/regex matching with frontier LLM calls for nuanced
classification of campaign blockers, scope violations, and merge readiness.
Falls back to keyword-based classification on LLM failure.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from aragora.agents.base import AgentType
from aragora.ralph.classifier import BlockerKind

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClassificationVerdict:
    """Result of LLM blocker classification."""

    kind: BlockerKind
    confidence: float
    reasoning: str


@dataclass(frozen=True, slots=True)
class ScopeVerdict:
    """Result of LLM scope adjudication."""

    justified_paths: list[str]
    rejected_paths: list[str]
    reasoning: str


@dataclass(frozen=True, slots=True)
class MergeVerdict:
    """Result of LLM merge readiness evaluation."""

    ready: bool
    blocking_issues: list[str]
    advisory_issues: list[str]
    reasoning: str


class LLMBlockerClassifier:
    """Frontier-LLM-powered blocker classification.

    Uses ``create_agent()`` from ``aragora.agents.base`` to invoke Claude
    or OpenRouter for nuanced classification that keyword matching cannot
    provide.  Each method returns a structured verdict dataclass.  On LLM
    failure, callers fall back to existing keyword-based logic.
    """

    def __init__(self, *, model: AgentType = "anthropic-api", timeout: float = 30.0) -> None:
        self.model = model
        self.timeout = timeout

    # ------------------------------------------------------------------
    # 1. Blocker classification
    # ------------------------------------------------------------------

    async def classify_blocker(
        self,
        manifest_dict: dict[str, Any],
        stop_reason: str,
    ) -> ClassificationVerdict:
        """Classify a campaign blocker using frontier LLM reasoning.

        Builds a diagnostic prompt from the manifest state and asks the LLM
        to return a structured ``BlockerKind`` with confidence and reasoning.
        On any failure, returns ``UNKNOWN`` at zero confidence so the caller
        can fall back to keyword classification.
        """
        prompt = self._build_classify_prompt(manifest_dict, stop_reason)
        try:
            from aragora.agents.base import create_agent

            agent = create_agent(self.model, name="ralph-blocker-classifier", role="critic")
            raw = await agent.generate(prompt)
            return self._parse_classify_response(raw)
        except Exception:
            logger.debug("LLM classify_blocker failed, returning UNKNOWN", exc_info=True)
            return ClassificationVerdict(
                kind=BlockerKind.UNKNOWN, confidence=0.0, reasoning="LLM call failed"
            )

    def _build_classify_prompt(self, manifest_dict: dict[str, Any], stop_reason: str) -> str:
        kind_descriptions = "\n".join(
            f"- {k.value}: deterministic={k.is_deterministic}" for k in BlockerKind
        )
        projects = manifest_dict.get("projects", [])
        diagnostics: list[str] = []
        for proj in projects:
            status = proj.get("status", "unknown")
            outcome = proj.get("last_run_outcome", "unknown")
            pid = proj.get("project_id", "?")
            diagnostics.append(f"Project {pid}: status={status}, outcome={outcome}")
            review = proj.get("review", {})
            if isinstance(review, dict):
                for finding in review.get("findings", []):
                    diagnostics.append(f"  finding: {str(finding)[:300]}")
                raw = review.get("raw_review", {})
                if isinstance(raw, dict):
                    for k, v in raw.items():
                        if v:
                            diagnostics.append(f"  raw_review.{k}: {str(v)[:200]}")
            for attempt in proj.get("attempt_history", []):
                if not isinstance(attempt, dict):
                    continue
                fd = attempt.get("failure_detail")
                if fd:
                    diagnostics.append(f"  failure_detail: {str(fd)[:300]}")
                for b in attempt.get("blockers", []):
                    if str(b).strip():
                        diagnostics.append(f"  blocker: {str(b)[:200]}")
        diag_text = "\n".join(diagnostics) if diagnostics else "(no project diagnostics)"

        return f"""You are a campaign diagnostics classifier for an AI development orchestration system.

Given the campaign state below, classify the root-cause blocker into exactly ONE of these kinds:

{kind_descriptions}

Campaign stop_reason: {stop_reason}

Project diagnostics:
{diag_text}

Return ONLY a JSON object (no markdown fences):
{{"kind": "<BlockerKind value>", "confidence": <0.0-1.0>, "reasoning": "<one sentence>"}}

Rules:
- scope_false_positive: Worker edited files that are semantically related to the task (test files, __init__.py, config) but weren't in declared scope. The planner's scope was too narrow, not a real violation.
- reviewer_auth_or_billing_failure: Review failed due to billing, credits, auth, rate limits, or API key issues.
- infra_failure: Network errors, SSL failures, binary exec errors, permission denied.
- worker_context_overflow: Context length exceeded, prompt too long.
- reviewer_missing_diff_context: Deliverable created but reviewer couldn't verify because diff was missing or review was blocked.
- worker_clean_exit_no_effect: Worker exited but produced no useful deliverable (stall pattern).
- budget_exhaustion: Campaign ran out of budget.
- campaign_runtime_timeout_config: Timeout but some progress was made.
- receipt_emission_gap: Terminal project without receipt.
- manifest_identifier_collision: Duplicate file scope hints.
- unknown: Cannot determine root cause."""

    @staticmethod
    def _parse_classify_response(raw: str) -> ClassificationVerdict:
        text = str(raw or "").strip()
        parsed: dict[str, Any] = {}
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                except (json.JSONDecodeError, ValueError):
                    pass
        if not isinstance(parsed, dict) or "kind" not in parsed:
            return ClassificationVerdict(
                kind=BlockerKind.UNKNOWN,
                confidence=0.1,
                reasoning=f"Could not parse LLM response: {text[:200]}",
            )
        kind_str = str(parsed["kind"]).strip()
        try:
            kind = BlockerKind(kind_str)
        except ValueError:
            return ClassificationVerdict(
                kind=BlockerKind.UNKNOWN,
                confidence=0.1,
                reasoning=f"Unknown blocker kind from LLM: {kind_str}",
            )
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
        reasoning = str(parsed.get("reasoning", ""))
        return ClassificationVerdict(kind=kind, confidence=confidence, reasoning=reasoning)

    # ------------------------------------------------------------------
    # 2. Scope adjudication
    # ------------------------------------------------------------------

    async def adjudicate_scope(
        self,
        task_description: str,
        declared_scope: list[str],
        changed_paths: list[str],
        violations: list[dict[str, Any]],
    ) -> ScopeVerdict:
        """Adjudicate whether out-of-scope file edits are semantically justified.

        Called after glob matching finds violations.  The LLM sees the task
        context and decides if each violation is a genuine scope breach or a
        planner oversight (e.g., test companion files, __init__.py updates).

        Fail-closed: on any error, all violations stand.
        """
        out_of_scope_paths = [
            str(v.get("path", "")) for v in violations if str(v.get("path", "")).strip()
        ]
        if not out_of_scope_paths:
            return ScopeVerdict(justified_paths=[], rejected_paths=[], reasoning="no violations")

        prompt = self._build_scope_prompt(
            task_description, declared_scope, changed_paths, out_of_scope_paths
        )
        try:
            from aragora.agents.base import create_agent

            agent = create_agent(self.model, name="ralph-scope-adjudicator", role="critic")
            raw = await agent.generate(prompt)
            return self._parse_scope_response(raw, out_of_scope_paths)
        except Exception:
            logger.debug("LLM adjudicate_scope failed, fail-closed", exc_info=True)
            return ScopeVerdict(
                justified_paths=[],
                rejected_paths=list(out_of_scope_paths),
                reasoning="LLM call failed — fail-closed, all violations stand",
            )

    @staticmethod
    def _build_scope_prompt(
        task_description: str,
        declared_scope: list[str],
        changed_paths: list[str],
        out_of_scope_paths: list[str],
        *,
        repo_root: str | None = None,
    ) -> str:
        # Build optional repository structure context
        repo_structure_section = ""
        if repo_root:
            try:
                import os

                entries = sorted(os.listdir(repo_root))
                top_level = [e for e in entries if not e.startswith(".")][:30]
                if top_level:
                    repo_structure_section = (
                        "\nRepository top-level directories/files:\n" + json.dumps(top_level) + "\n"
                    )
            except OSError:
                pass

        return f"""You are a file-scope adjudicator for an AI development orchestration system.

A worker was given this task:
{task_description}

Declared file scope (glob patterns the worker was allowed to edit):
{json.dumps(declared_scope)}

All files the worker actually changed:
{json.dumps(changed_paths)}

Files flagged as OUT OF SCOPE by glob matching:
{json.dumps(out_of_scope_paths)}
{repo_structure_section}
For each out-of-scope file, decide if the edit is JUSTIFIED or REJECTED.

Justified means: the file is semantically related to the task even though it wasn't in the declared scope. Common justified cases:

1. **Dependency/lock files**: If the task involves adding, updating, or removing dependencies, changes to dependency manifests and lock files are almost always justified:
   - Python: requirements.txt, requirements-dev.txt, pyproject.toml, setup.cfg, setup.py, poetry.lock, Pipfile, Pipfile.lock
   - JavaScript/TypeScript: package.json, package-lock.json, yarn.lock, pnpm-lock.yaml
   - Rust: Cargo.toml, Cargo.lock
   - Go: go.mod, go.sum
   - Ruby: Gemfile, Gemfile.lock

2. **Test file companions**: Test files that correspond to implementation files are justified — e.g., tests/foo/test_bar.py accompanying src/foo/bar.py or aragora/foo/bar.py. The standard pattern is a mirrored directory structure under tests/.

3. **Package init files**: __init__.py files that need export updates when new modules are added or public APIs change.

4. **Configuration files**: Project-level config that the implementation depends on (e.g., tsconfig.json, .eslintrc, mypy.ini, pytest.ini).

5. **Documentation files**: Docs directly related to the change (e.g., updating API docs when an endpoint changes).

Rejected means: the file is genuinely unrelated to the declared task scope.

Return ONLY a JSON object (no markdown fences):
{{"justified_paths": ["path1", ...], "rejected_paths": ["path2", ...], "reasoning": "explanation"}}

Every path from the out-of-scope list must appear in exactly one of justified_paths or rejected_paths."""

    @staticmethod
    def _parse_scope_response(raw: str, fallback_rejected: list[str]) -> ScopeVerdict:
        text = str(raw or "").strip()
        parsed: dict[str, Any] = {}
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                except (json.JSONDecodeError, ValueError):
                    pass
        if not isinstance(parsed, dict):
            return ScopeVerdict(
                justified_paths=[],
                rejected_paths=list(fallback_rejected),
                reasoning=f"Could not parse LLM scope response: {text[:200]}",
            )
        justified = [str(p) for p in parsed.get("justified_paths", []) if str(p).strip()]
        rejected = [str(p) for p in parsed.get("rejected_paths", []) if str(p).strip()]
        reasoning = str(parsed.get("reasoning", ""))
        # Any path not in either list → rejected (fail-closed)
        accounted = set(justified) | set(rejected)
        for path in fallback_rejected:
            if path not in accounted:
                rejected.append(path)
        return ScopeVerdict(justified_paths=justified, rejected_paths=rejected, reasoning=reasoning)

    # ------------------------------------------------------------------
    # 3. Merge readiness evaluation
    # ------------------------------------------------------------------

    async def evaluate_merge_readiness(
        self,
        acceptance_criteria: list[str],
        verification_results: list[dict[str, Any]],
        changed_paths: list[str],
        diff_summary: str,
    ) -> MergeVerdict:
        """Evaluate whether a deliverable is ready to merge.

        Called after the deterministic merge gate fails.  The LLM evaluates
        whether the failure is a genuine blocking issue or cosmetic noise
        (pre-existing test failures, deprecation warnings, etc.).

        Fail-closed: on any error, returns not-ready.
        """
        prompt = self._build_merge_prompt(
            acceptance_criteria, verification_results, changed_paths, diff_summary
        )
        try:
            from aragora.agents.base import create_agent

            agent = create_agent(self.model, name="ralph-merge-evaluator", role="critic")
            raw = await agent.generate(prompt)
            return self._parse_merge_response(raw)
        except Exception:
            logger.debug("LLM evaluate_merge_readiness failed, fail-closed", exc_info=True)
            return MergeVerdict(
                ready=False,
                blocking_issues=["LLM evaluation failed — fail-closed"],
                advisory_issues=[],
                reasoning="LLM call failed",
            )

    @staticmethod
    def _build_merge_prompt(
        acceptance_criteria: list[str],
        verification_results: list[dict[str, Any]],
        changed_paths: list[str],
        diff_summary: str,
    ) -> str:
        criteria_text = "\n".join(f"- {c}" for c in acceptance_criteria) or "(none specified)"
        results_text = json.dumps(verification_results, indent=2, default=str)
        paths_text = "\n".join(f"- {p}" for p in changed_paths) or "(none)"
        return f"""You are a merge readiness evaluator for an AI development orchestration system.

A worker completed a task. The deterministic merge gate flagged issues. Evaluate whether the deliverable is actually ready to merge or has genuine blocking problems.

Acceptance criteria:
{criteria_text}

Verification results (test commands and their outcomes):
{results_text}

Changed files:
{paths_text}

Diff summary:
{diff_summary[:2000]}

Distinguish between:
- BLOCKING issues: Real test failures caused by this change, missing acceptance criteria, broken functionality
- ADVISORY issues: Pre-existing failures, deprecation warnings, cosmetic issues, unrelated test noise

Return ONLY a JSON object (no markdown fences):
{{"ready": true/false, "blocking_issues": ["..."], "advisory_issues": ["..."], "reasoning": "explanation"}}

Set ready=true ONLY if there are zero blocking issues."""

    @staticmethod
    def _parse_merge_response(raw: str) -> MergeVerdict:
        text = str(raw or "").strip()
        parsed: dict[str, Any] = {}
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                except (json.JSONDecodeError, ValueError):
                    pass
        if not isinstance(parsed, dict):
            return MergeVerdict(
                ready=False,
                blocking_issues=[f"Could not parse LLM merge response: {text[:200]}"],
                advisory_issues=[],
                reasoning="Parse failure",
            )
        return MergeVerdict(
            ready=bool(parsed.get("ready", False)),
            blocking_issues=[str(i) for i in parsed.get("blocking_issues", []) if str(i).strip()],
            advisory_issues=[str(i) for i in parsed.get("advisory_issues", []) if str(i).strip()],
            reasoning=str(parsed.get("reasoning", "")),
        )

    # ------------------------------------------------------------------
    # 4. Run outcome classification
    # ------------------------------------------------------------------

    async def classify_run_outcome(
        self,
        run_dict: dict[str, Any],
    ) -> RunOutcomeVerdict:
        """Classify a terminal supervisor run into an outcome category.

        Replaces keyword matching on JSON-dumped run state with LLM reasoning.
        Fail-closed: returns "blocked" on any error.
        """
        prompt = self._build_run_outcome_prompt(run_dict)
        try:
            from aragora.agents.base import create_agent

            agent = create_agent(self.model, name="ralph-run-outcome-classifier", role="critic")
            raw = await agent.generate(prompt)
            return self._parse_run_outcome_response(raw)
        except Exception:
            logger.debug("LLM classify_run_outcome failed, returning blocked", exc_info=True)
            return RunOutcomeVerdict(outcome="blocked", reasoning="LLM call failed")

    @staticmethod
    def _build_run_outcome_prompt(run_dict: dict[str, Any]) -> str:
        summary = json.dumps(run_dict, indent=2, default=str)[:3000]
        return f"""You are a supervisor run outcome classifier for an AI development orchestration system.

Given the run state below, classify the outcome into exactly ONE of these categories:
- deliverable_created: Worker produced commits or branch changes that can be used
- pr_adopted: Worker adopted an existing PR
- clean_exit_no_deliverable: Worker exited cleanly but produced nothing useful
- needs_human: Worker needs human intervention, no salvageable output
- timeout: Worker timed out
- crash: Worker crashed (non-zero exit, traceback, fatal error)
- blocked: Worker was blocked by external factors

Run state:
{summary}

Return ONLY a JSON object (no markdown fences):
{{"outcome": "<category>", "reasoning": "<one sentence>"}}"""

    @staticmethod
    def _parse_run_outcome_response(raw: str) -> RunOutcomeVerdict:
        text = str(raw or "").strip()
        parsed = _extract_json(text)
        if not isinstance(parsed, dict) or "outcome" not in parsed:
            return RunOutcomeVerdict(
                outcome="blocked", reasoning=f"Could not parse LLM response: {text[:200]}"
            )
        valid_outcomes = {
            "deliverable_created",
            "pr_adopted",
            "clean_exit_no_deliverable",
            "needs_human",
            "timeout",
            "crash",
            "blocked",
        }
        outcome = str(parsed["outcome"]).strip()
        if outcome not in valid_outcomes:
            return RunOutcomeVerdict(
                outcome="blocked", reasoning=f"Unknown outcome from LLM: {outcome}"
            )
        return RunOutcomeVerdict(outcome=outcome, reasoning=str(parsed.get("reasoning", "")))

    # ------------------------------------------------------------------
    # 5. Capacity failure detection
    # ------------------------------------------------------------------

    async def detect_capacity_failure(
        self,
        stdout: str,
        stderr: str,
        agent_name: str,
    ) -> CapacityVerdict:
        """Detect whether worker failure is due to billing/quota/capacity issues.

        Replaces keyword pattern matching on worker output with LLM reasoning.
        Fail-closed: returns is_capacity=False on error (no false positives).
        """
        combined = "\n".join(part for part in (stdout, stderr) if part).strip()
        if not combined:
            return CapacityVerdict(is_capacity=False, detail="", reasoning="no output")

        prompt = self._build_capacity_prompt(combined, agent_name)
        try:
            from aragora.agents.base import create_agent

            agent = create_agent(self.model, name="ralph-capacity-detector", role="critic")
            raw = await agent.generate(prompt)
            return self._parse_capacity_response(raw, combined)
        except Exception:
            logger.debug("LLM detect_capacity_failure failed", exc_info=True)
            return CapacityVerdict(is_capacity=False, detail="", reasoning="LLM call failed")

    @staticmethod
    def _build_capacity_prompt(combined_output: str, agent_name: str) -> str:
        truncated = combined_output[:2000]
        return f"""You are a failure triage classifier for an AI development orchestration system.

A worker ({agent_name}) failed. Determine if the failure is due to billing, quota, rate limiting, or capacity exhaustion — vs. a bug, timeout, or other issue.

Worker output:
{truncated}

Return ONLY a JSON object (no markdown fences):
{{"is_capacity": true/false, "reasoning": "<one sentence>"}}

is_capacity=true means: credit balance too low, quota exceeded, rate limited, billing issue, payment required, insufficient credits.
is_capacity=false means: any other failure (bugs, timeouts, permission errors, crashes)."""

    @staticmethod
    def _parse_capacity_response(raw: str, combined_output: str) -> CapacityVerdict:
        text = str(raw or "").strip()
        parsed = _extract_json(text)
        if not isinstance(parsed, dict):
            return CapacityVerdict(is_capacity=False, detail="", reasoning="parse failure")
        is_capacity = bool(parsed.get("is_capacity", False))
        return CapacityVerdict(
            is_capacity=is_capacity,
            detail=combined_output if is_capacity else "",
            reasoning=str(parsed.get("reasoning", "")),
        )

    # ------------------------------------------------------------------
    # 6. Spec inference (track hints, constraints, acceptance criteria)
    # ------------------------------------------------------------------

    async def infer_spec_fields(
        self,
        user_messages: list[str],
        raw_goal: str,
    ) -> SpecInferenceVerdict:
        """Infer track hints, constraints, and acceptance criteria from user input.

        Replaces keyword matching for track detection, constraint extraction,
        and acceptance criteria extraction with a single LLM call.
        Fail-closed: returns empty fields on error.
        """
        prompt = self._build_spec_inference_prompt(user_messages, raw_goal)
        try:
            from aragora.agents.base import create_agent

            agent = create_agent(self.model, name="ralph-spec-inference", role="critic")
            raw = await agent.generate(prompt)
            return self._parse_spec_inference_response(raw)
        except Exception:
            logger.debug("LLM infer_spec_fields failed", exc_info=True)
            return SpecInferenceVerdict(
                track_hints=[], constraints=[], acceptance_criteria=[], reasoning="LLM call failed"
            )

    @staticmethod
    def _build_spec_inference_prompt(user_messages: list[str], raw_goal: str) -> str:
        messages_text = "\n---\n".join(user_messages[:10]) if user_messages else "(none)"
        return f"""You are a requirements analyst for an AI development orchestration system.

Given the user's goal and conversation, extract structured spec fields.

Goal: {raw_goal}

User messages:
{messages_text[:3000]}

Extract:
1. track_hints: Which work tracks apply? Options: qa, security, developer, sme, self_hosted. Only include tracks clearly relevant to the goal.
2. constraints: Things the user said should NOT be done, or boundaries to respect. Extract full sentences.
3. acceptance_criteria: How will we know the work is done? Extract full sentences describing success conditions.

Return ONLY a JSON object (no markdown fences):
{{"track_hints": ["track1", ...], "constraints": ["constraint1", ...], "acceptance_criteria": ["criterion1", ...], "reasoning": "<brief explanation>"}}"""

    @staticmethod
    def _parse_spec_inference_response(raw: str) -> SpecInferenceVerdict:
        text = str(raw or "").strip()
        parsed = _extract_json(text)
        if not isinstance(parsed, dict):
            return SpecInferenceVerdict(
                track_hints=[],
                constraints=[],
                acceptance_criteria=[],
                reasoning=f"Could not parse: {text[:200]}",
            )
        valid_tracks = {"qa", "security", "developer", "sme", "self_hosted"}
        track_hints = [
            str(t) for t in parsed.get("track_hints", []) if str(t).strip() in valid_tracks
        ]
        constraints = [str(c) for c in parsed.get("constraints", []) if str(c).strip()]
        criteria = [str(c) for c in parsed.get("acceptance_criteria", []) if str(c).strip()]
        return SpecInferenceVerdict(
            track_hints=track_hints,
            constraints=constraints,
            acceptance_criteria=criteria,
            reasoning=str(parsed.get("reasoning", "")),
        )


# ------------------------------------------------------------------
# Additional verdict dataclasses
# ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunOutcomeVerdict:
    """Result of LLM run outcome classification."""

    outcome: str
    reasoning: str


@dataclass(frozen=True, slots=True)
class CapacityVerdict:
    """Result of LLM capacity failure detection."""

    is_capacity: bool
    detail: str
    reasoning: str


@dataclass(frozen=True, slots=True)
class SpecInferenceVerdict:
    """Result of LLM spec field inference."""

    track_hints: list[str]
    constraints: list[str]
    acceptance_criteria: list[str]
    reasoning: str


# ------------------------------------------------------------------
# Shared JSON extraction helper
# ------------------------------------------------------------------


def _extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON extraction from LLM response text."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                pass
    return None
