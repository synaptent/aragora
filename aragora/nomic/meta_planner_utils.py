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

from aragora.nomic.types import Track

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
    except Exception:
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
    except Exception:
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


def parse_goals_from_debate(
    debate_result: Any,
    available_tracks: list[Track],
    objective: str,
    max_goals: int,
    heuristic_fallback: Any,
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
    goals = []

    # Get consensus text from debate result
    consensus_text = ""
    if hasattr(debate_result, "consensus") and debate_result.consensus:
        consensus_text = str(debate_result.consensus)
    elif hasattr(debate_result, "final_response"):
        consensus_text = str(debate_result.final_response)
    elif hasattr(debate_result, "responses") and debate_result.responses:
        consensus_text = str(debate_result.responses[-1])

    if not consensus_text:
        return heuristic_fallback(objective, available_tracks)

    # Parse numbered items from the consensus
    lines = consensus_text.split("\n")
    current_goal: dict[str, Any] = {}
    goal_id = 0

    for line in lines:
        line = line.strip()

        # Detect numbered items (1., 2., etc.) or bullet points
        if re.match(r"^[\d]+[\.\)]\s+", line) or re.match(r"^[-*]\s+", line):
            # Save previous goal if exists
            if current_goal.get("description"):
                goals.append(build_goal(current_goal, goal_id, available_tracks))
                goal_id += 1

            # Start new goal
            current_goal = {
                "description": re.sub(r"^[\d]+[\.\)]\s+|^[-*]\s+", "", line),
                "track": None,
                "rationale": "",
                "impact": "medium",
            }

        elif current_goal:
            # Parse track from line
            for track in Track:
                if track.value.lower() in line.lower():
                    current_goal["track"] = track
                    break

            # Parse impact
            if "high" in line.lower() and "impact" in line.lower():
                current_goal["impact"] = "high"
            elif "low" in line.lower() and "impact" in line.lower():
                current_goal["impact"] = "low"

            # Accumulate rationale
            if "because" in line.lower() or "rationale" in line.lower():
                current_goal["rationale"] = line

    # Don't forget last goal
    if current_goal.get("description"):
        goals.append(build_goal(current_goal, goal_id, available_tracks))

    # Limit to max goals
    goals = goals[:max_goals]

    # If no goals parsed, fall back to heuristics
    if not goals:
        return heuristic_fallback(objective, available_tracks)

    return goals


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
    if context.recent_issues:
        topic += f"""
RECENT ISSUES:
{chr(10).join(f"- {issue}" for issue in context.recent_issues[:5])}
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


def gather_file_excerpts(
    signals: list[str],
    max_files: int = 3,
    max_chars_per_file: int = 1500,
    max_total_chars: int = 5000,
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
    path_re = re.compile(r"(?:aragora|tests|scripts)/\S+\.py")
    paths: list[str] = []
    for sig in signals:
        match = path_re.search(sig)
        if match and match.group() not in paths:
            paths.append(match.group())
        if len(paths) >= max_files:
            break

    result: dict[str, str] = {}
    total = 0
    for path in paths:
        try:
            content = Path(path).read_text(errors="replace")[:max_chars_per_file]
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
