"""
Utility functions for the MetaPlanner.

Standalone helpers extracted from MetaPlanner for reuse and testability.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aragora.agents.failure_semantics import looks_like_agent_failure_response
from aragora.nomic.types import Track
from aragora.utils.error_sanitizer import sanitize_error

if TYPE_CHECKING:
    from aragora.nomic.meta_planner import PrioritizedGoal

logger = logging.getLogger(__name__)


# ── Track descriptions for LLM classification ────────────────────────
_TRACK_DESCRIPTIONS: dict[Track, str] = {
    Track.SME: "End-user features: dashboard, onboarding, billing, UI/UX, admin panels, workspace management, customer-facing pages",
    Track.DEVELOPER: "Developer experience: SDKs, APIs, documentation, client libraries, OpenAPI specs, webhooks, TypeScript/Python packages",
    Track.SELF_HOSTED: "Infrastructure & ops: Docker, Kubernetes, deployment, CI/CD, runners, monitoring, Prometheus, scaling, cloud, servers",
    Track.QA: "Testing & quality: pytest, E2E tests, coverage, benchmarks, Playwright, regression, fixtures, test infrastructure",
    Track.CORE: "Core platform: debate engine, agents, consensus, Arena, memory, pipeline orchestration, Nomic loop, knowledge mound, resilience, architecture, integration",
    Track.SECURITY: "Security: authentication, RBAC, encryption, OWASP, vulnerability scanning, OIDC/SAML, MFA, secrets, anomaly detection",
}


def infer_track(description: str, available_tracks: list[Track]) -> Track:
    """Infer track from goal description.

    Uses LLM semantic classification as the primary method, falling back
    to keyword scoring when LLM is unavailable (no API keys, import
    failures, or network errors).

    Args:
        description: Goal description text
        available_tracks: List of tracks to choose from

    Returns:
        Best matching Track
    """
    # Try LLM-based classification first
    try:
        result = _infer_track_llm(description, available_tracks)
        if result is not None:
            return result
    except (ImportError, ValueError, TypeError, RuntimeError, OSError, TimeoutError):
        logger.debug("LLM track classification unavailable, using keyword fallback")

    # Keyword-based fallback
    return _infer_track_keywords(description, available_tracks)


def _infer_track_llm(description: str, available_tracks: list[Track]) -> Track | None:
    """Classify track using a frontier LLM for semantic understanding.

    Makes a single cheap LLM call to classify the goal. Returns None if
    the LLM is unavailable or the response can't be parsed.
    """
    from aragora.agents import create_agent
    from aragora.agents.base import AgentType

    # Build the classification prompt
    track_options = "\n".join(
        f"- {t.value}: {_TRACK_DESCRIPTIONS.get(t, t.value)}" for t in available_tracks
    )

    prompt = (
        f"Classify this development goal into exactly one track.\n\n"
        f"Goal: {description}\n\n"
        f"Available tracks:\n{track_options}\n\n"
        f"Reply with ONLY the track name (e.g., 'core' or 'sme'). "
        f"Nothing else."
    )

    # Try cheapest available agent
    agent = None
    for agent_type in ("anthropic-api", "openai-api", "deepseek"):
        try:
            agent = create_agent(AgentType(agent_type))  # type: ignore[arg-type]
            if agent is not None:
                break
        except (ImportError, ValueError, TypeError):
            continue

    if agent is None:
        return None

    # Run the single-shot classification
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already in async context — can't nest asyncio.run
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                response = pool.submit(asyncio.run, agent.generate(prompt)).result(timeout=15)
        else:
            response = asyncio.run(agent.generate(prompt))
    except (RuntimeError, OSError, TimeoutError):
        logger.debug("LLM classification call failed")
        return None

    # Parse response — expect a single track name
    response_clean = response.strip().lower().replace("_", "_")
    track_map = {t.value: t for t in available_tracks}
    if response_clean in track_map:
        return track_map[response_clean]

    # Fuzzy match: check if any track name appears in the response
    for value, track in track_map.items():
        if value in response_clean:
            return track

    logger.debug("Could not parse LLM track response: %s", response_clean)
    return None


def _infer_track_keywords(description: str, available_tracks: list[Track]) -> Track:
    """Fallback: infer track using scored keyword matching.

    Scores each available track by counting keyword hits. Returns the
    track with the highest score, falling back to CORE for unclassifiable goals.
    """
    desc_lower = description.lower()

    track_keywords: dict[Track, list[str]] = {
        Track.SME: [
            "dashboard",
            "user",
            "ui",
            "frontend",
            "workspace",
            "admin",
            "onboarding",
            "billing",
            "subscription",
            "customer",
            "tenant",
            "landing",
            "ux",
        ],
        Track.DEVELOPER: [
            "sdk",
            "api",
            "documentation",
            "client",
            "package",
            "openapi",
            "swagger",
            "webhook",
            "endpoint",
            "schema",
            "typescript",
            "library",
            "integration",
        ],
        Track.SELF_HOSTED: [
            "docker",
            "deploy",
            "backup",
            "ops",
            "kubernetes",
            "helm",
            "terraform",
            "ansible",
            "infrastructure",
            "cloud",
            "scaling",
            "monitoring",
            "prometheus",
            "grafana",
            "container",
            "k8s",
            "ci/cd",
            "runner",
            "fleet",
            "ci",
            "server",
            "instance",
            "region",
            "load balancer",
            "fleet",
            "node",
            "cluster",
            "autoscaling",
            "workload",
            "runner",
            "self hosted",
        ],
        Track.QA: [
            "test",
            "coverage",
            "e2e",
            "playwright",
            "pytest",
            "regression",
            "benchmark",
            "fixture",
            "assertion",
            "flaky",
            "snapshot",
        ],
        Track.CORE: [
            "debate",
            "agent",
            "consensus",
            "arena",
            "memory",
            "pipeline",
            "orchestrat",
            "nomic",
            "canvas",
            "provenance",
            "knowledge",
            "mound",
            "resilience",
            "circuit",
            "event",
            "stream",
            "unified",
            "bridge",
            "integrate",
            "loop",
            "cycle",
            "subsystem",
            "module",
            "refactor",
            "architecture",
            "workitem",
            "testfixer",
            "quality gate",
            "handoff",
            "control plane",
            "closed loop",
        ],
        Track.SECURITY: [
            "security",
            "auth",
            "vuln",
            "secret",
            "owasp",
            "encrypt",
            "csrf",
            "xss",
            "injection",
            "rbac",
            "permission",
            "oidc",
            "saml",
            "mfa",
            "token",
            "anomaly",
            "receipt",
            "signature",
            "sandbox",
            "trust",
            "adversarial",
        ],
    }

    # Score each track by counting keyword hits
    scores: dict[Track, int] = {}
    for track, keywords in track_keywords.items():
        if track in available_tracks:
            score = sum(1 for kw in keywords if kw in desc_lower)
            if score > 0:
                scores[track] = score

    if scores:
        return max(scores, key=scores.get)  # type: ignore[arg-type]

    # Default to CORE for unclassifiable goals
    if Track.CORE in available_tracks:
        return Track.CORE
    return available_tracks[0] if available_tracks else Track.DEVELOPER


def build_goal(
    goal_dict: dict[str, Any],
    priority: int,
    available_tracks: list[Track],
) -> "PrioritizedGoal":
    """Build a PrioritizedGoal from parsed data.

    Args:
        goal_dict: Dict with keys: description, track (optional), rationale, impact
        priority: Zero-based priority index
        available_tracks: Available tracks for inference

    Returns:
        PrioritizedGoal instance
    """
    from aragora.nomic.meta_planner import PrioritizedGoal

    # Default track based on keywords if not explicitly set
    track = goal_dict.get("track")
    if not track:
        track = infer_track(goal_dict["description"], available_tracks)

    return PrioritizedGoal(
        id=f"goal_{priority}",
        track=track,
        description=goal_dict["description"],
        rationale=goal_dict.get("rationale", ""),
        estimated_impact=goal_dict.get("impact", "medium"),
        priority=priority + 1,
    )


def proposal_failure_provenance(
    debate_result: Any,
    expected_proposers: list[str] | None = None,
) -> list[dict[str, str]]:
    """Project structured proposal failures into a sanitized, stable order."""
    failures = getattr(debate_result, "agent_failures", None)
    if not isinstance(failures, dict):
        return []

    ordered_agents = list(dict.fromkeys(expected_proposers or []))
    ordered_agents.extend(sorted(name for name in failures if name not in ordered_agents))
    provenance: list[dict[str, str]] = []
    for agent in ordered_agents:
        records = failures.get(agent, [])
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict) or record.get("phase") != "proposal":
                continue
            provenance.append(
                {
                    "agent": str(agent),
                    "phase": "proposal",
                    "error_type": str(record.get("error_type") or "exception"),
                    "message": sanitize_error(str(record.get("message") or "unknown error"), 160),
                }
            )
    return provenance


def _parse_goal_text(
    text: str,
    available_tracks: list[Track],
) -> list["PrioritizedGoal"]:
    """Parse one substantive response without invoking a heuristic fallback."""
    goals: list["PrioritizedGoal"] = []
    current_goal: dict[str, Any] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if re.match(r"^[\d]+[\.\)]\s+", line) or re.match(r"^[-*]\s+", line):
            if current_goal.get("description"):
                goals.append(build_goal(current_goal, len(goals), available_tracks))
            current_goal = {
                "description": re.sub(r"^[\d]+[\.\)]\s+|^[-*]\s+", "", line),
                "track": None,
                "rationale": "",
                "impact": "medium",
            }
        elif current_goal:
            for track in Track:
                if track.value.lower() in line.lower():
                    current_goal["track"] = track
                    break
            if "high" in line.lower() and "impact" in line.lower():
                current_goal["impact"] = "high"
            elif "low" in line.lower() and "impact" in line.lower():
                current_goal["impact"] = "low"
            if "because" in line.lower() or "rationale" in line.lower():
                current_goal["rationale"] = line

    if current_goal.get("description"):
        goals.append(build_goal(current_goal, len(goals), available_tracks))
    return goals


def parse_goals_from_debate(
    debate_result: Any,
    available_tracks: list[Track],
    objective: str,
    max_goals: int,
    heuristic_fallback: Any,
    expected_proposers: list[str] | None = None,
) -> list["PrioritizedGoal"]:
    """Parse prioritized goals from debate consensus.

    Args:
        debate_result: Result from Arena.run()
        available_tracks: Available development tracks
        objective: Original planning objective
        max_goals: Maximum number of goals to return
        heuristic_fallback: Callable to use as fallback (objective, tracks) -> goals

    Returns:
        List of PrioritizedGoal instances
    """
    proposals = getattr(debate_result, "proposals", None)
    proposal_map = proposals if isinstance(proposals, dict) else {}
    expected = list(dict.fromkeys(expected_proposers or []))
    if not expected:
        participants = getattr(debate_result, "participants", None)
        if isinstance(participants, (list, tuple)):
            expected = [str(name) for name in participants if str(name)]
    if not expected:
        expected = [str(name) for name in proposal_map]

    substantive = [
        name
        for name in expected
        if name in proposal_map and not looks_like_agent_failure_response(proposal_map[name])
    ]
    failures = proposal_failure_provenance(debate_result, expected)
    degraded = bool(failures) or bool(expected and len(substantive) != len(expected))

    consensus_text = ""
    final_answer = getattr(debate_result, "final_answer", None)
    if isinstance(final_answer, str) and final_answer.strip():
        consensus_text = final_answer
    elif hasattr(debate_result, "consensus") and debate_result.consensus:
        consensus_text = str(debate_result.consensus)
    elif getattr(debate_result, "final_response", None):
        consensus_text = str(debate_result.final_response)
    elif hasattr(debate_result, "responses") and debate_result.responses:
        consensus_text = str(debate_result.responses[-1])

    goals: list["PrioritizedGoal"] = []
    decision_source = "debate_consensus"
    if substantive and (degraded or not consensus_text):
        decision_source = "surviving_proposals"
        for agent in substantive:
            text = str(proposal_map[agent]).strip()
            parsed = _parse_goal_text(text, available_tracks)
            if not parsed:
                first_line = next(
                    (line.strip("# ") for line in text.splitlines() if line.strip()), text
                )
                parsed = [
                    build_goal(
                        {"description": first_line, "rationale": f"Proposal from {agent}"},
                        0,
                        available_tracks,
                    )
                ]
            goals.extend(parsed)
    elif consensus_text and not degraded:
        goals = _parse_goal_text(consensus_text, available_tracks)

    if not goals:
        decision_source = "heuristic_fallback"
        goals = heuristic_fallback(objective, available_tracks)

    unique: list["PrioritizedGoal"] = []
    seen: set[str] = set()
    for goal in goals:
        key = re.sub(r"[^a-z0-9]+", " ", goal.description.casefold()).strip()
        if key in seen:
            continue
        seen.add(key)
        goal.id = f"goal_{len(unique)}"
        goal.priority = len(unique) + 1
        unique.append(goal)

    metadata = {
        "decision_source": decision_source,
        "degraded": degraded,
        "expected_proposers": expected,
        "substantive_proposers": substantive,
        "failure_provenance": failures,
    }
    for goal in unique[:max_goals]:
        goal.metadata = dict(metadata)

    return unique[:max_goals]


def build_debate_topic(
    objective: str,
    tracks: list[Track],
    constraints: list[str],
    context: Any,
) -> str:
    """Build the debate topic string for meta-planning.

    Args:
        objective: High-level business objective
        tracks: Available development tracks
        constraints: Planning constraints
        context: PlanningContext with issues, failures, learnings, etc.

    Returns:
        Formatted debate topic string
    """
    track_names = ", ".join(t.value for t in tracks)

    topic = f"""You are planning improvements for the Aragora project.

OBJECTIVE: {objective}

AVAILABLE TRACKS (domains you can work on):
{track_names}

Track descriptions:
- SME: Small business features, dashboard, user workspace
- Developer: SDKs, API, documentation
- Self-Hosted: Docker, deployment, backup/restore
- QA: Tests, CI/CD, code quality
- Core: Debate engine, agents, memory (requires approval)
- Security: Vulnerability scanning, auth hardening, secrets, OWASP compliance

CONSTRAINTS:
{chr(10).join(f"- {c}" for c in constraints) if constraints else "- None specified"}

"""
    candidate_goals = getattr(context, "candidate_goals", None)
    if candidate_goals:
        topic += f"""
CANDIDATE GOALS (externally supplied — evaluate and rank ALL of these against the objective;
reject candidates that do not survive scrutiny and say why):
{chr(10).join(f"{i}. {goal}" for i, goal in enumerate(candidate_goals, 1))}
"""

    if context.recent_issues:
        topic += f"""
RECENT ISSUES:
{chr(10).join(f"- {issue}" for issue in context.recent_issues[:5])}
"""

    if context.recent_changes:
        topic += f"""
RECENT CHANGES TO RE-ASSESS:
{chr(10).join(f"- {change}" for change in context.recent_changes[:5])}
"""

    if context.test_failures:
        topic += f"""
FAILING TESTS:
{chr(10).join(f"- {failure}" for failure in context.test_failures[:5])}
"""

    # Add CI feedback
    if context.ci_failures:
        topic += f"""
CI FAILURES (recent CI pipeline failures to address):
{chr(10).join(f"- {f}" for f in context.ci_failures[:5])}
"""

    if context.ci_flaky_tests:
        topic += f"""
FLAKY TESTS (intermittent CI failures to stabilize):
{chr(10).join(f"- {t}" for t in context.ci_flaky_tests[:5])}
"""

    # Add historical learnings (cross-cycle learning)
    if context.past_successes_to_build_on:
        topic += f"""
PAST SUCCESSES TO BUILD ON (from similar cycles):
{chr(10).join(f"- {s}" for s in context.past_successes_to_build_on[:5])}
"""

    if context.past_failures_to_avoid:
        topic += f"""
PAST FAILURES TO AVOID (learn from these mistakes):
{chr(10).join(f"- {f}" for f in context.past_failures_to_avoid[:5])}
"""

    # Add codebase metrics for data-driven planning
    if context.metric_snapshot:
        snap = context.metric_snapshot
        metric_lines = ["CODEBASE METRICS (current state):"]
        if snap.get("files_count"):
            metric_lines.append(f"- Python files: {snap['files_count']}")
        if snap.get("total_lines"):
            metric_lines.append(f"- Total lines: {snap['total_lines']:,}")
        if snap.get("tests_passed") or snap.get("tests_failed"):
            passed = snap.get("tests_passed", 0)
            failed = snap.get("tests_failed", 0)
            total = passed + failed + snap.get("tests_errors", 0)
            rate = passed / total if total > 0 else 0
            metric_lines.append(f"- Tests: {passed}/{total} passing ({rate:.0%} pass rate)")
        if snap.get("lint_errors"):
            metric_lines.append(f"- Lint errors: {snap['lint_errors']}")
        if snap.get("test_coverage") is not None:
            metric_lines.append(f"- Test coverage: {snap['test_coverage']:.0%}")
        if len(metric_lines) > 1:
            topic += "\n" + "\n".join(metric_lines) + "\n"

    # Inject GoalExtractor decomposition for structured goal hints
    try:
        from aragora.goals.extractor import GoalExtractor

        extractor = GoalExtractor()
        goal_graph = extractor.extract_from_raw_ideas([objective])
        if goal_graph and hasattr(goal_graph, "goals") and goal_graph.goals:
            topic += "\nPRE-EXTRACTED GOALS (from GoalExtractor, use as starting points):\n"
            for g in goal_graph.goals[:5]:
                title = getattr(g, "title", str(g))
                desc = getattr(g, "description", "")
                smart = getattr(g, "smart_score", None)
                smart_str = f" [SMART={smart:.1f}]" if smart is not None else ""
                topic += f"- {title}{smart_str}: {desc[:120]}\n"
    except ImportError:
        pass
    except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
        logger.debug("GoalExtractor injection skipped: %s", exc)

    # Inject relevant deliberation templates to ground abstract objectives
    try:
        from aragora.deliberation.templates.registry import match_templates

        matched = match_templates(objective, limit=3)
        if matched:
            topic += "\nRELEVANT DELIBERATION TEMPLATES (use these as inspiration):\n"
            for tmpl in matched:
                topic += (
                    f"- {tmpl.name}: {tmpl.description} "
                    f"(category={tmpl.category.value}, "
                    f"tags={', '.join(tmpl.tags[:4])})\n"
                )
    except ImportError:
        pass

    topic += """
YOUR TASK:
Propose 3-5 specific improvement goals that would best achieve the objective.
For each goal, specify:
1. Which track it belongs to
2. A clear, actionable description
3. Why this should be prioritized (rationale)
4. Expected impact: high, medium, or low

Format your response as a numbered list with clear structure.
Consider dependencies and order goals by priority.
"""
    if context.past_failures_to_avoid:
        topic += """
IMPORTANT: Avoid repeating past failures listed above. Learn from history.
"""
    return topic


def build_repository_planning_topic(
    objective: str,
    repository_name: str,
    repository_id: str,
    commit_sha: str,
    pack_reference: str,
    roadmap_paths: list[str],
    context_entry_files: list[str],
    evaluation_criteria: list[tuple[str, str]],
    context_markdown: str,
    max_goals: int,
) -> str:
    """Build the repository-neutral, evidence-bearing planning prompt."""
    criteria = "\n".join(
        f"- {item_id}: {description}" for item_id, description in evaluation_criteria
    )
    roadmaps = "\n".join(f"- {path}" for path in roadmap_paths) or "- None configured"
    entries = "\n".join(f"- {path}" for path in context_entry_files) or "- None configured"
    criterion_example = ", ".join(f'"{item_id}": 0.0' for item_id, _ in evaluation_criteria)
    return f"""Plan the next repository improvements using only the commit-addressed context below.

REPOSITORY NAME: {repository_name}
REPOSITORY ID: {repository_id}
COMMIT: {commit_sha}
CONTEXT PACK: {pack_reference}
OBJECTIVE: {objective}

ROADMAP FILES:
{roadmaps}

CONTEXT ENTRY FILES:
{entries}

EVALUATION CRITERIA (score every goal from 0.0 to 1.0):
{criteria}

Return one JSON object and no prose. It must have a `goals` array containing at most
{max_goals} objects. Every goal must contain `description`, `rationale`,
`estimated_impact` (high, medium, or low), `criterion_scores`, and
`evidence_paths`. Evidence paths must be concrete repository-relative paths present
in the context pack. Use this exact shape:
{{
  "goals": [
    {{
      "description": "actionable improvement",
      "rationale": "why this advances the objective",
      "estimated_impact": "high",
      "criterion_scores": {{{criterion_example}}},
      "evidence_paths": ["path/from/manifest"]
    }}
  ]
}}

COMMIT-ADDRESSED CONTEXT:
{context_markdown}
"""


def gather_file_excerpts(
    signals: list[str],
    max_files: int = 3,
    max_chars_per_file: int = 1500,
    max_total_chars: int = 5000,
    repo_root: Path = Path("."),
) -> dict[str, str]:
    """Extract file paths from signal strings and read excerpts.

    Provides real source code context to ground goals instead of
    relying solely on signal labels.

    Args:
        signals: Signal strings like ``"recent_change: aragora/foo.py"``.
        max_files: Maximum number of files to read.
        max_chars_per_file: Max characters per file excerpt.
        max_total_chars: Max total characters across all excerpts.

    Returns:
        Dict mapping file path to truncated content.
    """
    # Extract file paths from signal strings
    path_re = re.compile(
        r"(?:^|:\s)([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.(?:py|ts|tsx|js|jsx|go|rs|java))"
    )
    paths: list[str] = []
    for sig in signals:
        match = path_re.search(sig)
        if match and match.group(1) not in paths:
            paths.append(match.group(1))
        if len(paths) >= max_files:
            break

    result: dict[str, str] = {}
    total = 0
    for path in paths:
        try:
            content = (repo_root / path).read_text(errors="replace")[:max_chars_per_file]
            if total + len(content) > max_total_chars:
                content = content[: max_total_chars - total]
            if content:
                result[path] = content
                total += len(content)
            if total >= max_total_chars:
                break
        except OSError:
            continue

    return result
