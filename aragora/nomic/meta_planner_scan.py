"""Scan-mode prioritization for ``MetaPlanner``.

``MetaPlanner`` (``aragora.nomic.meta_planner``) inherits these methods: with
``MetaPlannerConfig.scan_mode`` it ranks goals from local codebase signals (git log,
untested modules, past regressions, pytest failures, lint, TODO comments, user feedback
and the improvement queue) without any LLM call. Import the planner from
``aragora.nomic.meta_planner``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aragora.nomic.meta_planner_models import MetaPlannerConfig, PrioritizedGoal
from aragora.nomic.meta_planner_utils import gather_file_excerpts
from aragora.nomic.types import Track

# The facade's logger name, so log filters and caplog assertions keyed on
# "aragora.nomic.meta_planner" still see records from the moved methods.
logger = logging.getLogger("aragora.nomic.meta_planner")


class MetaPlannerScanMixin:
    """Codebase-signal goal prioritization inherited by ``MetaPlanner``."""

    config: MetaPlannerConfig

    if TYPE_CHECKING:

        def _heuristic_prioritize(
            self,
            objective: str,
            available_tracks: list[Track],
        ) -> list[PrioritizedGoal]: ...

        def _infer_track(self, description: str, available_tracks: list[Track]) -> Track: ...

        def _rerank_with_business_context(
            self, goals: list[PrioritizedGoal]
        ) -> list[PrioritizedGoal]: ...

    async def _scan_prioritize(
        self,
        objective: str | None,
        available_tracks: list[Track],
        enrich_goals: bool = False,
    ) -> list[PrioritizedGoal]:
        """Prioritize from codebase signals without any LLM calls.

        Gathers eight signal sources:
        1. ``git log`` — recently changed files mapped to tracks
        2. ``CodebaseIndexer`` — untested modules
        3. ``OutcomeTracker`` — past regression patterns
        4. ``.pytest_cache`` — last-run test failures
        5. ``ruff`` — lint violations
        6. ``grep`` — TODO/FIXME/HACK comments
        7. ``FeedbackStore`` — user NPS score (low NPS boosts user-facing tracks)
        8. ``ImprovementQueue`` — feedback goals from prior cycles

        Each signal contributes a candidate goal. Goals are ranked by signal
        count (more signals = higher priority).

        When *objective* is None (self-directing mode), the scan produces
        goals purely from codebase signals without any human-supplied context.

        Args:
            objective: High-level objective (used to seed descriptions).
                       None for fully self-directing mode.
            available_tracks: Tracks that can receive work.

        Returns:
            List of PrioritizedGoal sorted by priority.
        """
        import subprocess

        # Default objective label for self-directing mode
        effective_objective = objective or "self-directed codebase improvement"

        track_signals: dict[str, list[str]] = {t.value: [] for t in available_tracks}

        # Signal 1: Recent git changes → map files to tracks
        try:
            git_result = subprocess.run(
                ["git", "log", "--oneline", "--name-only", "-20"],  # noqa: S607 -- fixed command
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.config.repo_path,
            )
            if git_result.returncode == 0:
                for line in git_result.stdout.splitlines():
                    line = line.strip()
                    if not line or line[0].isalnum() and " " in line:
                        continue  # Skip commit messages
                    track = self._file_to_track(line, available_tracks)
                    if track and track.value in track_signals:
                        track_signals[track.value].append(f"recent_change: {line}")
        except (subprocess.TimeoutExpired, OSError):
            pass

        # Signal 2: Untested modules from CodebaseIndexer
        try:
            import os

            if os.environ.get("PYTEST_CURRENT_TEST"):
                raise RuntimeError("skip in tests")

            from aragora.nomic.codebase_indexer import CodebaseIndexer

            indexer = CodebaseIndexer(repo_path=self.config.repo_path, max_modules=50)
            await indexer.index()
            for module in indexer._modules:
                test_paths = indexer._test_map.get(str(module.path), [])
                if not test_paths:
                    track = self._file_to_track(str(module.path), available_tracks)
                    if track and track.value in track_signals:
                        track_signals[track.value].append(f"untested: {module.path}")
        except (ImportError, RuntimeError, ValueError, OSError):
            pass

        # Signal 3: Past regression patterns
        try:
            from aragora.nomic.outcome_tracker import NomicOutcomeTracker

            regressions = NomicOutcomeTracker.get_regression_history(limit=10)
            for reg in regressions:
                for metric in reg.get("regressed_metrics", []):
                    # Map regression metrics to tracks
                    if "test" in metric.lower() or "coverage" in metric.lower():
                        if Track.QA.value in track_signals:
                            track_signals[Track.QA.value].append(f"regression: {metric}")
                    elif "token" in metric.lower():
                        if Track.CORE.value in track_signals:
                            track_signals[Track.CORE.value].append(f"regression: {metric}")
        except (ImportError, RuntimeError, ValueError, OSError):
            pass

        # Signal 4: pytest last-run failures
        try:
            import json as _json
            from pathlib import Path as _P

            lastfailed_path = _P(self.config.repo_path) / ".pytest_cache/v/cache/lastfailed"
            if lastfailed_path.exists():
                failed = _json.loads(lastfailed_path.read_text())
                for node_id in list(failed.keys())[:20]:
                    # Extract file path from node ID (e.g. "tests/foo.py::TestBar::test_baz")
                    test_file = node_id.split("::")[0] if "::" in node_id else node_id
                    track = self._file_to_track(test_file, available_tracks)
                    if track and track.value in track_signals:
                        track_signals[track.value].append(f"test_failure: {node_id}")
        except (OSError, ValueError, _json.JSONDecodeError):
            pass

        # Signal 5: ruff lint violations
        try:
            ruff_result = subprocess.run(
                ["ruff", "check", "--quiet", "--output-format=concise", "."],  # noqa: S607 -- fixed command
                capture_output=True,
                text=True,
                timeout=15,
                cwd=self.config.repo_path,
            )
            if ruff_result.stdout:
                for i, line in enumerate(ruff_result.stdout.splitlines()):
                    if i >= 20:
                        break
                    # Format: "path/to/file.py:42:1 E501 ..."
                    parts = line.split(":", 1)
                    if parts:
                        track = self._file_to_track(parts[0], available_tracks)
                        if track and track.value in track_signals:
                            track_signals[track.value].append(f"lint: {line.strip()[:100]}")
        except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
            pass

        # Signal 6: TODO/FIXME/HACK comments
        try:
            todo_result = subprocess.run(
                ["grep", "-rn", r"TODO\|FIXME\|HACK", ".", "--include=*.py", "-l"],  # noqa: S607 -- fixed command
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.config.repo_path,
            )
            if todo_result.returncode == 0 and todo_result.stdout:
                for i, filepath in enumerate(todo_result.stdout.splitlines()):
                    if i >= 10:
                        break
                    filepath = filepath.strip()
                    if filepath:
                        track = self._file_to_track(filepath, available_tracks)
                        if track and track.value in track_signals:
                            track_signals[track.value].append(f"todo: {filepath}")
        except (subprocess.TimeoutExpired, OSError):
            pass

        # Signal 7: User feedback (NPS score from FeedbackStore)
        try:
            from aragora.server.handlers.sme.feedback import FeedbackStore

            fb_store = FeedbackStore()
            nps = fb_store.get_nps_summary(days=30)
            if nps and nps.get("response_count", 0) > 0:
                nps_score = nps.get("nps_score", 0)
                if nps_score < 30:  # Below "good" threshold
                    if Track.SME.value in track_signals:
                        track_signals[Track.SME.value].append(
                            f"low_nps: score={nps_score} ({nps.get('response_count', 0)} responses)"
                        )
                    if Track.DEVELOPER.value in track_signals:
                        track_signals[Track.DEVELOPER.value].append(
                            f"low_nps: score={nps_score} (detractors={nps.get('detractor_pct', 0):.0f}%)"
                        )
        except (ImportError, RuntimeError, OSError, ValueError):
            pass

        # Signal 8: ImprovementQueue (feedback goals from prior cycles)
        try:
            from aragora.nomic.feedback_orchestrator import ImprovementQueue

            queue = ImprovementQueue.load()
            for queued_goal in queue.goals[:10]:
                track_name = getattr(queued_goal, "track", None)
                if isinstance(track_name, Track):
                    track_name = track_name.value
                elif track_name is not None and hasattr(track_name, "value"):
                    track_name = track_name.value
                else:
                    track_name = str(track_name) if track_name else None

                if track_name and track_name in track_signals:
                    source = getattr(queued_goal, "source", "feedback")
                    desc = getattr(queued_goal, "description", "")[:100]
                    track_signals[track_name].append(f"feedback_queue[{source}]: {desc}")
        except ImportError:
            pass
        except (RuntimeError, ValueError, OSError):
            pass

        # Signal 9: StrategicScanner deep codebase analysis
        strategic_assessment = None
        try:
            from aragora.nomic.strategic_scanner import StrategicScanner

            scanner = StrategicScanner()
            strategic_assessment = scanner.scan(objective=effective_objective)
            for finding in strategic_assessment.findings[:15]:
                track_name = finding.track
                if track_name in track_signals:
                    track_signals[track_name].append(
                        f"strategic[{finding.category}]: {finding.description[:100]}"
                    )
            logger.info(
                "scan_mode_strategic_findings count=%d",
                len(strategic_assessment.findings),
            )
        except ImportError:
            pass
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("StrategicScanner skipped: %s", exc)

        # Persist strategic assessment for cross-session learning
        if strategic_assessment is not None:
            try:
                from aragora.nomic.strategic_memory import StrategicMemoryStore

                mem_store = StrategicMemoryStore()
                mem_store.save(strategic_assessment)
            except (ImportError, RuntimeError, OSError, ValueError) as exc:
                logger.debug("Strategic memory persistence skipped: %s", exc)

        # Signal 10: Pipeline Goal Canvas — approved but unexecuted goals
        try:
            from aragora.pipeline.plan_store import get_plan_store as _get_plan_store

            _pstore = _get_plan_store()
            # Query plan store for approved, unexecuted items
            pipeline_goals = _pstore.get_recent_outcomes(limit=10) if _pstore else []
            for pg in (pipeline_goals or [])[:10]:
                pg_data = pg if isinstance(pg, dict) else getattr(pg, "__dict__", {})
                track_name = pg_data.get("track", "core")
                if track_name in track_signals:
                    track_signals[track_name].append(
                        f"pipeline_goal: {(pg_data.get('label') or pg_data.get('description') or '')[:100]}"
                    )
            if pipeline_goals:
                logger.info(
                    "scan_mode_pipeline_goals count=%d",
                    len(pipeline_goals),
                )
        except ImportError:
            pass
        except (RuntimeError, ValueError, OSError, TypeError, AttributeError) as exc:
            logger.debug("Pipeline Goal Canvas scan skipped: %s", exc)

        # Signal 11: Feedback-generated goals from previous cycles (SQLite queue)
        try:
            from aragora.nomic.feedback_orchestrator import ImprovementQueue as FeedbackQueue

            queue = FeedbackQueue()
            queued_goals = queue.pop(limit=10)
            if queued_goals:
                for qg in queued_goals:
                    track = self._infer_track(qg.goal, available_tracks)
                    if track and track.value in track_signals:
                        track_signals[track.value].append(
                            f"feedback_goal[{qg.source}]: {qg.goal[:100]}"
                        )
                logger.info("scan_feedback_goals", extra={"count": len(queued_goals)})
        except ImportError:
            pass
        except (RuntimeError, ValueError, OSError, TypeError) as exc:
            logger.warning("feedback_queue_unavailable: %s", exc)

        # Signal 12: NextStepsRunner for TODOs, test failures, dep issues
        try:
            from aragora.compat.openclaw.next_steps_runner import NextStepsRunner

            runner = NextStepsRunner(repo_path=self.config.repo_path)
            scan_result = runner.scan() if hasattr(runner, "scan") else None
            if scan_result and hasattr(scan_result, "steps"):
                for step in scan_result.steps[:10]:
                    track = self._infer_track(getattr(step, "title", str(step)), available_tracks)
                    if track and track.value in track_signals:
                        priority = getattr(step, "priority", "medium")
                        category = getattr(step, "category", "misc")
                        track_signals[track.value].append(
                            f"next_step[{category}/{priority}]: "
                            f"{getattr(step, 'title', str(step))[:100]}"
                        )
                logger.info(
                    "scan_next_steps",
                    extra={"count": len(scan_result.steps)},
                )
        except ImportError:
            pass
        except (RuntimeError, ValueError, OSError, TypeError) as exc:
            logger.warning("next_steps_runner_unavailable: %s", exc)

        # Build goals from signals, ranked by signal count
        ranked = sorted(
            track_signals.items(),
            key=lambda kv: len(kv[1]),
            reverse=True,
        )

        goals: list[PrioritizedGoal] = []
        for priority, (track_name, signals) in enumerate(ranked, start=1):
            if not signals:
                continue

            try:
                track = Track(track_name)
            except ValueError:
                continue

            # Build a description from the top signals
            top_signals = signals[:3]
            signal_summary = "; ".join(top_signals)
            description = (
                f"[{effective_objective[:40]}] {track_name}: "
                f"{len(signals)} signals ({signal_summary})"
            )

            # Enrich with file excerpts for grounded execution
            excerpts = self._gather_file_excerpts(top_signals)
            if excerpts:
                excerpt_text = "\n".join(f"--- {p} ---\n{s[:500]}" for p, s in excerpts.items())
                description += f"\n\nRelevant source:\n{excerpt_text}"

            # Opt-in: single cheap LLM call to enrich signal-based description
            agent = getattr(self, "_agent", None)
            if enrich_goals and agent is not None:
                try:
                    enriched = await agent.generate(
                        f"Expand this into a concrete task description "
                        f"(1-2 sentences):\n{description[:500]}",
                        max_tokens=100,
                    )
                    if enriched and len(enriched.strip()) > 20:
                        description = enriched.strip()
                except (RuntimeError, ValueError, TypeError, AttributeError):
                    pass  # Keep original description on any failure

            goals.append(
                PrioritizedGoal(
                    id=f"scan_{priority - 1}",
                    track=track,
                    description=description[:2000],
                    rationale=f"Scan mode: {len(signals)} codebase signals detected",
                    estimated_impact="high" if len(signals) >= 5 else "medium",
                    priority=priority,
                )
            )

        if not goals:
            logger.info("scan_mode_no_signals falling back to heuristic")
            return self._heuristic_prioritize(objective or "", available_tracks)

        # Re-rank goals using business context
        if self.config.use_business_context:
            goals = self._rerank_with_business_context(goals)

        logger.info(
            "scan_mode_complete goals=%d signals=%d",
            len(goals),
            sum(len(s) for s in track_signals.values()),
        )
        return goals[: self.config.max_goals]

    def _file_to_track(self, filepath: str, available_tracks: list[Track]) -> Track | None:
        """Map a file path to a development track."""
        fp = filepath.lower()
        mapping = {
            Track.QA: ["tests/", "test_", "conftest"],
            Track.SME: ["dashboard", "frontend", "live/", "workspace"],
            Track.DEVELOPER: ["sdk", "client", "aragora_sdk/"],
            Track.SELF_HOSTED: ["deploy/", "docker", "k8s", "kubernetes"],
            Track.SECURITY: ["security/", "auth/", "rbac/", "encryption"],
            Track.CORE: ["debate/", "agents/", "memory/", "consensus"],
        }
        for track, patterns in mapping.items():
            if track in available_tracks and any(p in fp for p in patterns):
                return track
        return available_tracks[0] if available_tracks else None

    def _gather_file_excerpts(
        self,
        signals: list[str],
        max_files: int = 3,
        max_chars_per_file: int = 1500,
        max_total_chars: int = 5000,
    ) -> dict[str, str]:
        """Extract file paths from signal strings and read excerpts."""
        return gather_file_excerpts(
            signals,
            max_files,
            max_chars_per_file,
            max_total_chars,
            Path(self.config.repo_path),
        )


__all__ = ["MetaPlannerScanMixin"]
