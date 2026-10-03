"""Worker dispatch and result-finalization helpers for ``BossLoop``.

This module extracts the high-churn worker execution lifecycle out of the
monolithic ``boss_loop.py`` file while preserving the ``BossLoop`` method
surface for tests and callers. The loop still owns state and policies; this
module owns the mechanics of dispatching bounded work and normalizing the
result back into a ``BossIterationStatus``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aragora.swarm.boss_feed import GitHubIssue
from aragora.swarm.boss_freshness import RunnerFreshnessResult
from aragora.swarm.task_sanitizer import SanitizationOutcome

if TYPE_CHECKING:
    from aragora.swarm.boss_loop import BossIterationStatus, BossLoop

logger = logging.getLogger(__name__)


def _boss_loop_module() -> Any:
    from aragora.swarm import boss_loop as boss_loop_mod

    return boss_loop_mod


def finalize_worker_result(
    loop: "BossLoop",
    *,
    iteration: int,
    timestamp: str,
    runner_freshness: dict[str, Any],
    issue: GitHubIssue,
    issue_dict: dict[str, Any],
    worker_result: dict[str, Any],
    elapsed_seconds: float,
) -> "BossIterationStatus":
    boss_loop_mod = _boss_loop_module()
    BossIterationStatus = boss_loop_mod.BossIterationStatus
    BossStopReason = boss_loop_mod.BossStopReason
    qualify_worker_result_terminal_state = boss_loop_mod._qualify_worker_result_terminal_state

    issue_number = int(issue.number)

    is_decomposed = bool(re.search(r"\[from #\d+\]", issue.title or ""))
    if is_decomposed:
        loop._ticks_spent_on_decomposed_issues += 1

    loop._recent_elapsed.append(elapsed_seconds)
    if len(loop._recent_elapsed) > loop.config.fast_fail_circuit_breaker_window:
        loop._recent_elapsed = loop._recent_elapsed[-loop.config.fast_fail_circuit_breaker_window :]

    if worker_result.get("status") == "running":
        loop._consecutive_failures = 0
        worker_run_id = str(worker_result.get("run_id", "")).strip()
        next_actions = [
            (
                f"Supervisor run {worker_run_id} is active for issue #{issue.number}; "
                "the boss loop returned after this bounded dispatch tick."
            )
            if worker_run_id
            else (
                f"Issue #{issue.number} dispatched successfully; "
                "the boss loop returned after this bounded dispatch tick."
            ),
            "Inspect the active supervisor run before starting another live boss-loop tick.",
        ]
        loop._append_iteration_metrics(
            iteration=iteration,
            issue_number=issue_number,
            worker_result=worker_result,
            elapsed_seconds=elapsed_seconds,
        )
        return BossIterationStatus(
            iteration=iteration,
            run_id=loop.run_id,
            timestamp=timestamp,
            runner_freshness=runner_freshness,
            selected_issue=issue_dict,
            worker_status="running",
            stop_reason=None,
            needs_human_reasons=[],
            next_actions=next_actions,
            elapsed_seconds=elapsed_seconds,
            worker_outcome=str(worker_result.get("outcome", "")).strip() or None,
        )

    issue_resolution = worker_result.get("issue_resolution")
    if (
        isinstance(issue_resolution, dict)
        and str(issue_resolution.get("action", "")).strip() == "closed"
    ):
        loop._completed_issues.append(issue_dict)
        loop._consecutive_failures = 0
        loop._emit_lane_receipt(worker_result, issue_dict, elapsed_seconds)
        loop._log_value_outcome(issue_dict, "completed", elapsed_seconds)
        loop._append_iteration_metrics(
            iteration=iteration,
            issue_number=issue_number,
            worker_result=worker_result,
            elapsed_seconds=elapsed_seconds,
        )
        return BossIterationStatus(
            iteration=iteration,
            run_id=loop.run_id,
            timestamp=timestamp,
            runner_freshness=runner_freshness,
            selected_issue=issue_dict,
            worker_status="completed",
            stop_reason=None,
            needs_human_reasons=[],
            next_actions=["Issue auto-closed as already implemented; proceeding."],
            elapsed_seconds=elapsed_seconds,
            worker_outcome=str(worker_result.get("outcome", "")).strip() or None,
        )

    if worker_result.get("status") == "completed":
        loop._completed_issues.append(issue_dict)
        loop._issue_attempt_counts[issue_number] = max(
            loop._issue_attempt_counts.get(issue_number, 0),
            loop.config.max_retries_per_issue,
        )
        loop._consecutive_failures = 0
        loop._emit_lane_receipt(worker_result, issue_dict, elapsed_seconds)
        loop._log_value_outcome(issue_dict, "completed", elapsed_seconds)
        next_action = (
            loop._published_pr_followup(worker_result)
            or loop._debate_gate_followup(worker_result)
            or "Proceeding to next issue."
        )
        loop._append_iteration_metrics(
            iteration=iteration,
            issue_number=issue_number,
            worker_result=worker_result,
            elapsed_seconds=elapsed_seconds,
        )
        return BossIterationStatus(
            iteration=iteration,
            run_id=loop.run_id,
            timestamp=timestamp,
            runner_freshness=runner_freshness,
            selected_issue=issue_dict,
            worker_status="completed",
            stop_reason=None,
            needs_human_reasons=[],
            next_actions=[next_action],
            elapsed_seconds=elapsed_seconds,
            worker_outcome=str(worker_result.get("outcome", "")).strip() or None,
        )

    if worker_result.get("status") == "needs_human":
        terminal_outcome, normalized_deliverable_type = qualify_worker_result_terminal_state(
            worker_result
        )
        has_deliverable = bool(normalized_deliverable_type)
        worker_outcome_text = str(worker_result.get("outcome", "")).strip().lower()
        has_rejected_deliverable = has_deliverable and worker_outcome_text in {
            "acceptance_gate_failed",
            "merge_gate_failed",
        }
        sanitizer_outcome = str(worker_result.get("sanitizer_outcome", "")).strip().lower()
        raw_deliverable = worker_result.get("deliverable")
        has_untyped_deliverable = isinstance(raw_deliverable, dict) and bool(raw_deliverable)
        pr_url = loop._published_pr_url(worker_result)
        loop._emit_lane_receipt(worker_result, issue_dict, elapsed_seconds)
        if sanitizer_outcome in {
            SanitizationOutcome.DROPPED.value,
            SanitizationOutcome.QUARANTINED.value,
        }:
            loop._issue_attempt_counts[issue_number] = max(
                int(loop._issue_attempt_counts.get(issue_number, 0) or 0),
                loop.config.max_retries_per_issue + 1,
            )
            loop._pending_handoff_prompts.pop(issue_number, None)
        if has_rejected_deliverable:
            loop._failed_issues.append(issue_dict)
            loop._log_value_outcome(issue_dict, "needs_human", elapsed_seconds)
            reasons = [
                str(reason).strip()
                for reason in worker_result.get("reasons", [])
                if str(reason).strip()
            ] or [
                f"Worker returned a {normalized_deliverable_type} deliverable, "
                f"but terminal outcome is {terminal_outcome}."
            ]
            loop._append_iteration_metrics(
                iteration=iteration,
                issue_number=issue_number,
                worker_result=worker_result,
                elapsed_seconds=elapsed_seconds,
            )
            return BossIterationStatus(
                iteration=iteration,
                run_id=loop.run_id,
                timestamp=timestamp,
                runner_freshness=runner_freshness,
                selected_issue=issue_dict,
                worker_status="needs_human",
                stop_reason=BossStopReason.NEEDS_HUMAN.value,
                needs_human_reasons=reasons,
                next_actions=[
                    "Review the rejected deliverable before counting this issue complete."
                ],
                elapsed_seconds=elapsed_seconds,
                worker_outcome=str(worker_result.get("outcome", "")).strip() or None,
            )

        if has_deliverable:
            loop._completed_issues.append(issue_dict)
            loop._consecutive_failures = 0
            loop._issue_attempt_counts[issue_number] = max(
                loop._issue_attempt_counts.get(issue_number, 0),
                loop.config.max_retries_per_issue,
            )
            loop._log_value_outcome(issue_dict, "completed", elapsed_seconds)
            logger.info(
                "boss_loop_terminal_deliverable issue=#%s pr=%s deliverable_type=%s",
                issue_dict.get("number", "?"),
                pr_url or "(pending publish)",
                normalized_deliverable_type,
            )
            loop._append_iteration_metrics(
                iteration=iteration,
                issue_number=issue_number,
                worker_result=worker_result,
                elapsed_seconds=elapsed_seconds,
            )
            next_action = (
                loop._published_pr_followup(worker_result)
                or loop._debate_gate_followup(worker_result)
                or (
                    f"Terminal: deliverable ({normalized_deliverable_type}) for issue "
                    f"#{issue_dict.get('number', '?')}"
                    f"{f' PR {pr_url}' if pr_url else ''}. Proceeding to next issue."
                )
            )
            return BossIterationStatus(
                iteration=iteration,
                run_id=loop.run_id,
                timestamp=timestamp,
                runner_freshness=runner_freshness,
                selected_issue=issue_dict,
                worker_status="completed",
                stop_reason=None,
                needs_human_reasons=[],
                next_actions=[next_action],
                elapsed_seconds=elapsed_seconds,
                worker_outcome=str(worker_result.get("outcome", "")).strip() or None,
            )

        if loop.config.auto_continue_on_needs_human and has_deliverable:
            loop._failed_issues.append(issue_dict)
            loop._consecutive_failures = 0
            logger.info(
                "boss_loop_auto_continue issue=#%s (recoverable deliverable still blocked)",
                issue_dict.get("number", "?"),
            )
            loop._append_iteration_metrics(
                iteration=iteration,
                issue_number=issue_number,
                worker_result=worker_result,
                elapsed_seconds=elapsed_seconds,
            )
            return BossIterationStatus(
                iteration=iteration,
                run_id=loop.run_id,
                timestamp=timestamp,
                runner_freshness=runner_freshness,
                selected_issue=issue_dict,
                worker_status="needs_human",
                stop_reason=None,
                needs_human_reasons=worker_result.get(
                    "reasons",
                    ["Recovered deliverable requires human review before integration."],
                ),
                next_actions=[
                    "Auto-continuing: recovered deliverable is receipt-backed but still blocked on human review."
                ],
                elapsed_seconds=elapsed_seconds,
                worker_outcome=str(worker_result.get("outcome", "")).strip() or None,
            )
        loop._failed_issues.append(issue_dict)
        loop._log_value_outcome(issue_dict, "needs_human", elapsed_seconds)

        issue_num = issue_dict.get("number", 0)
        repair_key = f"repair_{issue_num}"
        repair_count = loop._issue_attempt_counts.get(repair_key, 0)
        reasons = worker_result.get("reasons", [])
        has_verification_failure = any(
            "verification failed" in str(reason).lower()
            or "exit 1" in str(reason).lower()
            or "test" in str(reason).lower()
            for reason in reasons
        )

        if (
            loop.config.auto_continue_on_needs_human
            and has_verification_failure
            and repair_count < loop.config.max_repair_attempts
        ):
            loop._issue_attempt_counts[repair_key] = repair_count + 1
            logger.info(
                "boss_loop_repair issue=#%s attempt=%d/%d (verification failed, dispatching fix)",
                issue_num,
                repair_count + 1,
                loop.config.max_repair_attempts,
            )
            loop._append_iteration_metrics(
                iteration=iteration,
                issue_number=issue_number,
                worker_result=worker_result,
                elapsed_seconds=elapsed_seconds,
            )
            return BossIterationStatus(
                iteration=iteration,
                run_id=loop.run_id,
                timestamp=timestamp,
                runner_freshness=runner_freshness,
                selected_issue=issue_dict,
                worker_status="repairing",
                stop_reason=None,
                needs_human_reasons=[],
                next_actions=[
                    f"Repair attempt {repair_count + 1}/{loop.config.max_repair_attempts} "
                    f"for issue #{issue_num} — fixing verification failures."
                ],
                elapsed_seconds=elapsed_seconds,
                worker_outcome=str(worker_result.get("outcome", "")).strip() or None,
            )

        if loop.config.enable_ping_pong_retry and not has_verification_failure:
            pp_key = f"pingpong_{issue_num}"
            pp_count = loop._issue_attempt_counts.get(pp_key, 0)
            transcript = loop._extract_worker_transcript(worker_result)
            if pp_count < 1 and len(transcript.strip()) > 50:
                loop._issue_attempt_counts[pp_key] = pp_count + 1
                previous_agent = loop._extract_worker_agent(worker_result) or "unknown"
                rotation = list(loop.config.model_rotation or ["claude", "codex"])
                next_agent = rotation[0] if previous_agent == rotation[-1] else rotation[-1]

                from aragora.swarm.ping_pong import build_handoff_prompt

                handoff = build_handoff_prompt(
                    goal=f"[Issue #{issue_num}] {issue_dict.get('title', '')}",
                    previous_transcript=transcript,
                    previous_agent=previous_agent,
                    next_agent=next_agent,
                    round_number=1,
                    files_changed=loop._extract_worker_files_changed(worker_result),
                    remaining_issues=[str(reason) for reason in reasons[:5]],
                )
                loop._pending_handoff_prompts[issue_num] = (handoff, next_agent)
                logger.info(
                    "boss_loop_ping_pong issue=#%s from=%s to=%s transcript_len=%d",
                    issue_num,
                    previous_agent,
                    next_agent,
                    len(transcript),
                )
                loop._append_iteration_metrics(
                    iteration=iteration,
                    issue_number=issue_number,
                    worker_result=worker_result,
                    elapsed_seconds=elapsed_seconds,
                )
                return BossIterationStatus(
                    iteration=iteration,
                    run_id=loop.run_id,
                    timestamp=timestamp,
                    runner_freshness=runner_freshness,
                    selected_issue=issue_dict,
                    worker_status="ping_pong_retry",
                    stop_reason=None,
                    needs_human_reasons=[],
                    next_actions=[
                        f"Ping-pong handoff: {previous_agent} → {next_agent} for issue #{issue_num}"
                    ],
                    elapsed_seconds=elapsed_seconds,
                    worker_outcome=str(worker_result.get("outcome", "")).strip() or None,
                )

        if loop.config.auto_continue_on_needs_human:
            # Only deliverable-less rescue outcomes count toward the failure
            # streak; a skip over a produced-but-untyped deliverable is clean.
            if not raw_deliverable:
                loop._consecutive_failures += 1
            threshold_reason = (
                "Repeated rescue outcomes without a typed deliverable reached "
                f"threshold ({loop.config.max_consecutive_failures})."
            )
            if (
                not raw_deliverable
                and loop._consecutive_failures >= loop.config.max_consecutive_failures
            ):
                logger.warning(
                    "boss_loop_stop issue=#%s "
                    "(needs_human, no typed deliverable, consecutive failure threshold reached)",
                    issue_dict.get("number", "?"),
                )
                loop._append_iteration_metrics(
                    iteration=iteration,
                    issue_number=issue_number,
                    worker_result=worker_result,
                    elapsed_seconds=elapsed_seconds,
                )
                return BossIterationStatus(
                    iteration=iteration,
                    run_id=loop.run_id,
                    timestamp=timestamp,
                    runner_freshness=runner_freshness,
                    selected_issue=issue_dict,
                    worker_status="needs_human",
                    stop_reason=BossStopReason.CONSECUTIVE_FAILURES.value,
                    needs_human_reasons=list(
                        dict.fromkeys(
                            [
                                *worker_result.get("reasons", ["Worker requires human input."]),
                                threshold_reason,
                            ]
                        )
                    ),
                    next_actions=[
                        threshold_reason,
                        "Investigate the rescue streak before resuming the boss loop.",
                    ],
                    elapsed_seconds=elapsed_seconds,
                    worker_outcome=str(worker_result.get("outcome", "")).strip() or None,
                )
            if has_untyped_deliverable:
                logger.warning(
                    "boss_loop_skip issue=#%s (needs_human, untyped deliverable, auto-continue on)",
                    issue_dict.get("number", "?"),
                )
                next_actions = [
                    "Auto-continuing: worker returned a deliverable that still needs human review."
                ]
            else:
                logger.warning(
                    "boss_loop_skip issue=#%s (needs_human, no deliverable, auto-continue on)",
                    issue_dict.get("number", "?"),
                )
                next_actions = ["Skipping to next issue (auto-continue mode)."]
            loop._append_iteration_metrics(
                iteration=iteration,
                issue_number=issue_number,
                worker_result=worker_result,
                elapsed_seconds=elapsed_seconds,
            )
            return BossIterationStatus(
                iteration=iteration,
                run_id=loop.run_id,
                timestamp=timestamp,
                runner_freshness=runner_freshness,
                selected_issue=issue_dict,
                worker_status="needs_human",
                stop_reason=None,
                needs_human_reasons=worker_result.get("reasons", ["Worker requires human input."]),
                next_actions=next_actions,
                elapsed_seconds=elapsed_seconds,
                worker_outcome=str(worker_result.get("outcome", "")).strip() or None,
            )
        next_actions = [
            str(item).strip() for item in worker_result.get("next_actions", []) if str(item).strip()
        ] or ["Review the worker output and decide next steps."]
        loop._append_iteration_metrics(
            iteration=iteration,
            issue_number=issue_number,
            worker_result=worker_result,
            elapsed_seconds=elapsed_seconds,
        )
        return BossIterationStatus(
            iteration=iteration,
            run_id=loop.run_id,
            timestamp=timestamp,
            runner_freshness=runner_freshness,
            selected_issue=issue_dict,
            worker_status="needs_human",
            stop_reason=BossStopReason.NEEDS_HUMAN.value,
            needs_human_reasons=worker_result.get("reasons", ["Worker requires human input."]),
            next_actions=next_actions,
            elapsed_seconds=elapsed_seconds,
            worker_outcome=str(worker_result.get("outcome", "")).strip() or None,
        )

    loop._failed_issues.append(issue_dict)
    loop._consecutive_failures += 1
    loop._emit_lane_receipt(worker_result, issue_dict, elapsed_seconds)
    if loop._consecutive_failures >= loop.config.max_consecutive_failures:
        loop._append_iteration_metrics(
            iteration=iteration,
            issue_number=issue_number,
            worker_result=worker_result,
            elapsed_seconds=elapsed_seconds,
        )
        return BossIterationStatus(
            iteration=iteration,
            run_id=loop.run_id,
            timestamp=timestamp,
            runner_freshness=runner_freshness,
            selected_issue=issue_dict,
            worker_status="failed",
            stop_reason=BossStopReason.CONSECUTIVE_FAILURES.value,
            needs_human_reasons=[
                f"Consecutive failures reached threshold ({loop.config.max_consecutive_failures})."
            ],
            next_actions=[
                "Investigate the last failures before resuming.",
                f"Error: {worker_result.get('error', 'unknown')}",
            ],
            elapsed_seconds=elapsed_seconds,
            error=worker_result.get("error"),
            worker_outcome=str(worker_result.get("outcome", "")).strip() or None,
        )

    loop._append_iteration_metrics(
        iteration=iteration,
        issue_number=issue_number,
        worker_result=worker_result,
        elapsed_seconds=elapsed_seconds,
    )
    return BossIterationStatus(
        iteration=iteration,
        run_id=loop.run_id,
        timestamp=timestamp,
        runner_freshness=runner_freshness,
        selected_issue=issue_dict,
        worker_status="failed",
        stop_reason=None,
        needs_human_reasons=[],
        next_actions=[
            f"Issue #{issue.number} failed (attempt "
            f"{loop._issue_attempt_counts.get(issue_number, 0)}/{loop.config.max_retries_per_issue}). "
            "Will retry with next iteration.",
        ],
        elapsed_seconds=elapsed_seconds,
        error=worker_result.get("error"),
        worker_outcome=str(worker_result.get("outcome", "")).strip() or None,
    )


async def dispatch_issue(
    loop: "BossLoop",
    issue: GitHubIssue,
    freshness: RunnerFreshnessResult,
) -> dict[str, Any]:
    boss_loop_mod = _boss_loop_module()
    TaskSanitizer = boss_loop_mod.TaskSanitizer
    blocked_pre_dispatch_result = boss_loop_mod._blocked_pre_dispatch_result
    compose_issue_dispatch_goal = boss_loop_mod._compose_issue_dispatch_goal
    replace_with_focused_tests = boss_loop_mod._should_replace_with_focused_tests
    check_pre_dispatch_gate = boss_loop_mod.check_pre_dispatch_gate
    discover_focused_tests = boss_loop_mod.discover_focused_tests
    dispatch_bounded_spec = boss_loop_mod.dispatch_bounded_spec
    dispatch_contract_gate = boss_loop_mod.dispatch_contract_gate
    extract_issue_validation_contract = boss_loop_mod.extract_issue_validation_contract

    from aragora.swarm import dispatch_followups as dispatch_followups_mod
    from aragora.swarm.spec import SwarmSpec

    original_issue_body = str(issue.body or "").strip()
    sanitizer = TaskSanitizer(repo_root=Path.cwd())
    sanitization = sanitizer.sanitize(issue.title, original_issue_body)
    sanitized_issue_body = str(sanitization.sanitized_text or "").strip()
    issue_title_text = str(issue.title or "").strip()
    if issue_title_text and sanitized_issue_body.startswith(issue_title_text):
        sanitized_issue_body = sanitized_issue_body[len(issue_title_text) :].strip()
    if not sanitized_issue_body:
        sanitized_issue_body = original_issue_body
    logger.info(
        "task_sanitizer issue=#%s outcome=%s checks=%s",
        issue.number,
        sanitization.outcome.value,
        ",".join(sanitization.checks_failed) if sanitization.checks_failed else "-",
    )

    def with_sanitizer_metadata(result: dict[str, Any]) -> dict[str, Any]:
        result.setdefault("sanitizer_outcome", sanitization.outcome.value)
        result.setdefault("checks_failed", list(sanitization.checks_failed))
        result.setdefault("original_issue_body", original_issue_body)
        result.setdefault("sanitized_issue_body", sanitized_issue_body)
        return result

    if sanitization.outcome in {SanitizationOutcome.DROPPED, SanitizationOutcome.QUARANTINED}:
        if sanitization.outcome is SanitizationOutcome.QUARANTINED:
            from aragora.swarm.rescue_planner import try_quarantine_override

            override = try_quarantine_override(
                issue_number=issue.number,
                issue_title=issue.title,
                sanitization_reason=sanitization.reason,
                checks_failed=list(sanitization.checks_failed),
                issue_body=sanitized_issue_body,
                sanitizer=sanitizer,
            )
            if override is not None:
                sanitization, sanitized_issue_body = override

        if sanitization.outcome in {SanitizationOutcome.DROPPED, SanitizationOutcome.QUARANTINED}:
            loop._apply_sanitizer_issue_lifecycle(issue, sanitization=sanitization)

        if (
            sanitization.outcome in {SanitizationOutcome.DROPPED, SanitizationOutcome.QUARANTINED}
            and "impossible_validation" in sanitization.checks_failed
        ):
            outcome = "verification_target_missing"
            missing_targets_text = sanitization.reason.partition(":")[2].strip()
            if not missing_targets_text:
                missing_targets_text = "unknown targets"
            next_actions = [
                "Refresh the issue's Acceptance Criteria or Test Plan so validation commands reference current repo paths.",
                "Update the Files/Reference section or add explicit work orders before rerunning Boss dispatch.",
            ]
            reasons = [
                f"Issue #{issue.number} references missing validation targets: {missing_targets_text}"
            ]
        else:
            outcome = "sanitation_failed"
            next_actions = (
                [
                    "Rewrite the issue body so it contains a complete bounded task description before redispatch.",
                ]
                if sanitization.outcome is SanitizationOutcome.DROPPED
                else [
                    "Narrow the write scope, validation targets, or task breakdown before redispatch.",
                ]
            )
            reasons = [
                (
                    f"Issue #{issue.number} was {sanitization.outcome.value} by task sanitizer: "
                    f"{sanitization.reason}"
                )
            ]
        return with_sanitizer_metadata(
            {
                "status": "needs_human",
                "outcome": outcome,
                "reasons": reasons,
                "next_actions": next_actions,
            }
        )

    refinement: dict[str, Any] = {}
    refined_prompt = ""
    pending_handoff = loop._pending_handoff_prompts.get(issue.number)
    if pending_handoff is not None:
        refined_prompt = str(pending_handoff[0]).strip()

    try:
        from aragora.swarm.prompt_refiner import build_refinement_worker_env, refine_worker_prompt

        refinement = await refine_worker_prompt(
            issue.title,
            sanitized_issue_body,
            repo_path=Path.cwd(),
        )
        refinement_worker_env = build_refinement_worker_env(refinement)
        if refinement.get("context_gathered"):
            if pending_handoff is None:
                refined_prompt = str(refinement.get("refined_prompt", "")).strip()
            logger.info(
                "Refined prompt for #%s: %d relevant files, %d test patterns",
                issue.number,
                len(refinement.get("files_to_change", [])),
                len(refinement.get("test_patterns", [])),
            )
    except Exception as exc:
        logger.debug("Prompt refinement skipped: %s", exc)
        refinement_worker_env = {}

    body_lines = [str(line).strip() for line in sanitized_issue_body.splitlines()]
    scope_hints = list(
        dict.fromkeys(
            [
                *[
                    str(path).strip()
                    for path in refinement.get("files_to_change", [])
                    if str(path).strip()
                ],
                *SwarmSpec.infer_file_scope_hints(sanitized_issue_body),
            ]
        )
    )
    constraints = list(
        dict.fromkeys(
            [
                *SwarmSpec.infer_constraints(body_lines),
                *[
                    str(item).strip()
                    for item in refinement.get("constraints", [])
                    if str(item).strip()
                ],
            ]
        )
    )
    goal = compose_issue_dispatch_goal(
        issue.number,
        issue.title,
        issue_body=sanitized_issue_body,
        refined_prompt=refined_prompt,
    )
    if "git add -A && git commit" not in goal:
        goal += (
            "\n\n## CRITICAL: You MUST commit your changes\n"
            "After making changes, run:\n"
            "```\ngit add -A && git commit -m 'fix: description of changes'\n```\n"
            "If you do not commit, your work will be lost."
        )

    spec = SwarmSpec(
        raw_goal=goal,
        refined_goal=goal,
        constraints=constraints,
        budget_limit_usd=loop.config.budget_limit_usd,
        file_scope_hints=scope_hints,
        requires_approval=True,
        interrogation_turns=0,
        user_expertise="developer",
    )

    if loop.config.use_micro_decomposition and scope_hints:
        try:
            from aragora.swarm.micro_decomposer import build_micro_work_orders

            validation_contract_raw = extract_issue_validation_contract(sanitized_issue_body)
            micro_orders = build_micro_work_orders(
                goal=goal,
                file_scope_hints=scope_hints,
                acceptance_criteria=list(validation_contract_raw)
                if validation_contract_raw
                else None,
                constraints=constraints,
                repo_root=Path.cwd(),
            )
            if micro_orders:
                spec.work_orders = micro_orders
                spec.file_scope_hints = []
                logger.info(
                    "Micro-decomposed issue #%s into %d work orders",
                    issue.number,
                    len(micro_orders),
                )
        except Exception as exc:
            logger.debug("Micro-decomposition skipped: %s", exc)

    validation_contract = extract_issue_validation_contract(sanitized_issue_body)
    if validation_contract and loop.config.use_focused_verification:
        focused_tests = discover_focused_tests(Path.cwd())
        focused: list[str] = []
        for criterion in validation_contract:
            if replace_with_focused_tests(criterion):
                if focused_tests:
                    test_list = " ".join(focused_tests[:20])
                    focused.append(f"python -m pytest --timeout=30 -x -q {test_list}")
                else:
                    focused.append(criterion)
            else:
                focused.append(criterion)
        spec.acceptance_criteria = focused
    elif validation_contract:
        spec.acceptance_criteria = list(validation_contract)

    # PR-1 of #7209 must run before the validation-contract early exit:
    # rev-4 corpus members can be sparse precisely because the corpus row
    # carries the missing bounded scope, constraints, and acceptance shape.
    spec = dispatch_followups_mod.maybe_upgrade_dispatch_spec(
        issue=issue,
        spec=spec,
        sanitized_issue_body=sanitized_issue_body,
        repo_root=Path.cwd(),
    )

    if loop.config.require_validation_contract and not bool(
        getattr(spec, "acceptance_criteria", None)
    ):
        return with_sanitizer_metadata(
            blocked_pre_dispatch_result(
                reasons=[
                    f"Issue #{issue.number} lacks an explicit validation contract or acceptance criteria."
                ],
                next_actions=[
                    "Add an Acceptance Criteria, Validation, Definition of Done, or Test Plan section to the issue body.",
                    "Include at least one concrete verification step such as a pytest command or observable success criterion.",
                ],
                failure_classes=["contract_missing"],
                notes="Issue body missing explicit validation contract or acceptance criteria.",
                required_evidence=["acceptance_criteria", "validation_command"],
            )
        )

    repo_slug = loop._repo_slug_for_issue(issue)
    prior_session_state = loop._session_state_for_issue(issue.number, repo_slug=repo_slug)
    loop._attach_issue_handoff_metadata(spec, issue, session_state=prior_session_state)

    try:
        resume_context = prior_session_state.resume_context() if prior_session_state else ""
        if resume_context:
            spec.raw_goal = (
                f"{spec.raw_goal}\n\n## Resume Context (from prior attempt)\n{resume_context}"
            )
    except Exception as exc:
        logger.debug("boss_loop_resume_context_load_failed: #%s: %s", issue.number, exc)

    gate = await check_pre_dispatch_gate(
        sanitized_issue_body,
        repo_root=Path.cwd(),
        use_llm=loop.config.use_llm_pre_dispatch_gate,
    )
    logger.info(
        "pre_dispatch_gate issue=#%s method=%s pass=%s sanitation=%s missing=%s",
        issue.number,
        gate["method"],
        gate["pass"],
        gate["sanitation_ok"],
        gate.get("unresolved_missing", []),
    )
    if not gate["sanitation_ok"]:
        return with_sanitizer_metadata(
            {
                "status": "needs_human",
                "outcome": "sanitation_failed",
                "reasons": [
                    f"Issue #{issue.number} failed sanitation: {gate.get('sanitation_reason', 'unknown')}"
                ],
                "next_actions": ["Rewrite the issue body with a clear task description."],
            }
        )
    if gate.get("unresolved_missing"):
        if gate.get("missing_targets") and not gate["unresolved_missing"]:
            logger.info(
                "boss_loop_missing_validation_targets_allowed issue=#%s targets=%s",
                issue.number,
                ", ".join(gate["missing_targets"]),
            )
        else:
            targets_text = ", ".join(gate["unresolved_missing"])
            return with_sanitizer_metadata(
                {
                    "status": "needs_human",
                    "outcome": "verification_target_missing",
                    "reasons": [
                        f"Issue #{issue.number} references missing validation targets: {targets_text}"
                    ],
                    "next_actions": [
                        "Refresh the issue's Acceptance Criteria or Test Plan so pytest points at current repo paths.",
                        "Update the Files/Reference section or add explicit work orders before rerunning Boss dispatch.",
                    ],
                }
            )

    spec = dispatch_followups_mod.maybe_upgrade_dispatch_spec(
        issue=issue,
        spec=spec,
        sanitized_issue_body=sanitized_issue_body,
        repo_root=Path.cwd(),
    )
    if not spec.is_dispatch_bounded():
        try:
            upgraded = dispatch_followups_mod.upgrade_unbounded_spec(
                spec,
                issue_number=int(issue.number),
                issue_title=str(issue.title or ""),
                issue_body=sanitized_issue_body,
                repo_root=Path.cwd(),
                metrics_path=Path(
                    loop.config.metrics_jsonl_path or ".aragora/overnight/boss_metrics.jsonl"
                ),
                llm_client=None,
            )
        except dispatch_followups_mod.SpecUpgraderUnavailable:
            upgraded = None
        if upgraded is not None:
            spec = upgraded
    if not spec.is_dispatch_bounded():
        return with_sanitizer_metadata(
            blocked_pre_dispatch_result(
                reasons=[
                    f"Issue #{issue.number} is not safely dispatchable: {spec.dispatch_gate_reason()}"
                ],
                next_actions=[
                    "Add file-scope hints, constraints, acceptance criteria, or explicit work orders before dispatch.",
                ],
                failure_classes=["contract_missing"],
                notes=str(spec.dispatch_gate_reason() or "").strip()
                or "Issue is not safely dispatchable.",
                required_evidence=["file_scope", "acceptance_criteria", "work_order"],
            )
        )
    if not loop.config.dispatch_enabled:
        return with_sanitizer_metadata(
            {
                "status": "needs_human",
                "outcome": "preview_only",
                "reasons": [
                    f"No-dispatch preview only for issue #{issue.number}; supervised execution was intentionally skipped."
                ],
                "next_actions": [
                    "Review the selected issue and derived validation contract.",
                    "Rerun without --no-dispatch to execute the bounded Boss loop lane.",
                ],
            }
        )

    requested_target_agent = (
        str(pending_handoff[1]).strip().lower()
        if pending_handoff is not None and str(pending_handoff[1]).strip()
        else loop._requested_target_agent_for_issue(
            issue.number,
            repo_slug=loop._repo_slug_for_issue(issue),
        )
    )

    backbone_run_id = None
    runtime = None
    try:
        from aragora.pipeline.backbone_contracts import RunLedger
        from aragora.pipeline.backbone_runtime import BackboneRuntime

        runtime = BackboneRuntime()
        ledger = RunLedger(
            run_id=f"boss-{loop.run_id}-issue{issue.number}",
            entrypoint="boss_loop",
            status="dispatching",
            metadata={"issue_number": issue.number, "issue_title": issue.title},
        )
        runtime.create_run(ledger)
        backbone_run_id = ledger.run_id
    except Exception as exc:
        logger.debug(
            "Boss backbone ledger create failed for issue #%d: %s",
            issue.number,
            str(exc),
        )

    claimed_runner_id: str | None = None
    selected_runner, claimed_runner_id = loop._claim_runner_for_dispatch(
        freshness,
        requested_target_agent=requested_target_agent,
    )
    if selected_runner is None:
        selected_runner = loop._selected_runner_for_dispatch(
            freshness,
            requested_target_agent=requested_target_agent,
        )

    gate_result = dispatch_contract_gate(
        loop,
        issue,
        spec,
        selected_runner,
        requested_target_agent,
        refinement_worker_env,
        claimed_runner_id,
    )
    if gate_result is not None:
        # Seam B: attempt one drift-feedback upgrade and re-enter the gate once
        # before terminating with ``blocked_not_dispatch_bounded``.
        # ``dispatch_contract_gate`` released ``claimed_runner_id`` on failure;
        # clear our handle so we don't double-release.
        claimed_runner_id = None
        upgraded_spec_on_drift = dispatch_followups_mod.maybe_upgrade_on_contract_drift(
            gate_result=gate_result,
            spec=spec,
            issue_number=int(issue.number),
            issue_title=str(issue.title or ""),
            issue_body=sanitized_issue_body,
            repo_root=Path.cwd(),
            metrics_path=Path(
                loop.config.metrics_jsonl_path or ".aragora/overnight/boss_metrics.jsonl"
            ),
            llm_client=None,
        )
        if upgraded_spec_on_drift is not None:
            spec = upgraded_spec_on_drift
            selected_runner, claimed_runner_id = loop._claim_runner_for_dispatch(
                freshness,
                requested_target_agent=requested_target_agent,
            )
            if selected_runner is None:
                selected_runner = loop._selected_runner_for_dispatch(
                    freshness,
                    requested_target_agent=requested_target_agent,
                )
            gate_result = dispatch_contract_gate(
                loop,
                issue,
                spec,
                selected_runner,
                requested_target_agent,
                refinement_worker_env,
                claimed_runner_id,
            )
            if gate_result is not None:
                claimed_runner_id = None
        if gate_result is not None:
            return with_sanitizer_metadata(gate_result)

    try:
        result = await dispatch_bounded_spec(
            spec,
            target_branch=loop.config.target_branch,
            budget_limit_usd=loop.config.budget_limit_usd,
            max_ticks=loop.config.dispatch_max_ticks,
            wait_for_completion=True,
            default_target_agent=requested_target_agent,
            default_reviewer_agent=loop.config.default_reviewer_agent,
            use_managed_session_script=False,
            selected_runner=selected_runner,
            worker_env=refinement_worker_env or None,
            allow_claude_dangerously_skip_permissions=loop.config.allow_claude_dangerously_skip_permissions,
            allow_codex_full_auto=loop.config.allow_codex_full_auto,
            execution_mode=loop.config.execution_mode,
        )
    finally:
        if claimed_runner_id:
            loop._release_runner_claim(claimed_runner_id)

    if backbone_run_id and runtime is not None:
        try:
            runtime.update_run(
                backbone_run_id,
                status=boss_loop_mod._backbone_dispatch_status(result),
                execution_id=result.get("run_id"),
                receipt_id=result.get("receipt_id"),
            )
        except Exception as exc:
            logger.debug(
                "Boss backbone ledger dispatch update failed for issue #%d: %s",
                issue.number,
                str(exc),
            )
    if pending_handoff is not None:
        dispatch_started = boss_loop_mod._dispatch_result_started(result)
        if result.get("status") != "failed" or dispatch_started:
            loop._pending_handoff_prompts.pop(issue.number, None)
    result = with_sanitizer_metadata(result)
    result["receipt_metadata"] = loop._receipt_metadata_for_result(
        result,
        issue=issue,
        freshness=freshness,
        selected_runner=selected_runner,
        requested_target_agent=requested_target_agent,
    )
    dispatch_status = boss_loop_mod._backbone_dispatch_status(result)
    result = loop._postprocess_issue_result(issue, result)
    postprocess_metadata = loop._apply_postprocess_metadata(result)
    loop._record_session_attempt(
        issue,
        result,
        selected_runner=selected_runner,
        requested_target_agent=requested_target_agent,
    )
    if (
        backbone_run_id
        and runtime is not None
        and (
            boss_loop_mod._backbone_dispatch_status(result) != dispatch_status
            or bool(postprocess_metadata)
        )
    ):
        try:
            runtime.update_run(
                backbone_run_id,
                status=boss_loop_mod._backbone_dispatch_status(result),
                execution_id=result.get("run_id"),
                receipt_id=result.get("receipt_id"),
                metadata={"boss_postprocess": postprocess_metadata} if postprocess_metadata else {},
            )
        except Exception as exc:
            logger.debug(
                "Boss backbone ledger postprocess update failed for issue #%d: %s",
                issue.number,
                str(exc),
            )
    if result.get("status") == "failed":
        error = str(result.get("error", "")).strip()
        if error:
            logger.warning("Boss dispatch failed for issue #%d: %s", issue.number, error)
    # v1.3 acceptance-criteria binding gate — reject deliverables that do not
    # satisfy the spec's acceptance criteria before they become a PR.  This
    # happens BEFORE the conductor annotation so that downstream classification
    # reflects the gate verdict.
    try:
        result = dispatch_followups_mod.enforce_acceptance_binding(
            issue_number=int(issue.number),
            issue_body=sanitized_issue_body,
            spec=spec,
            worker_result=result,
            metrics_path=Path(
                loop.config.metrics_jsonl_path or ".aragora/overnight/boss_metrics.jsonl"
            ),
        )
    except Exception as exc:  # noqa: BLE001 — acceptance gate must never crash dispatch
        logger.warning(
            "acceptance_gate_unavailable issue=#%s error=%s",
            issue.number,
            exc,
        )
    result = dispatch_followups_mod.annotate_result_with_conductor(
        issue_number=issue.number,
        result=result,
        repo_root=Path.cwd(),
    )
    return result
