"""PR Watch Daemon - autonomous GitHub PR polling with multi-agent review."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class WatcherConfig:
    """Configuration for the PR watch daemon."""

    repos: list[str] = field(default_factory=list)
    poll_interval_seconds: int = 120
    startup_delay_seconds: int = 5
    agents: str = "anthropic-api,openai-api"
    rounds: int = 2
    dry_run: bool = False
    gauntlet: bool = False
    skip_drafts: bool = True
    skip_labels: list[str] = field(default_factory=lambda: ["wip", "do-not-review"])
    only_labels: list[str] = field(default_factory=list)
    max_diff_size_kb: int = 50
    max_reviews_per_hour: int = 10
    max_concurrent_reviews: int = 2
    state_file: str = ""
    policy_file: str | None = None

    @classmethod
    def from_env(cls) -> WatcherConfig:
        """Create config from ``ARAGORA_WATCH_*`` environment variables."""

        def _bool(key: str, default: bool) -> bool:
            val = os.environ.get(key, "").lower()
            if val in ("1", "true", "yes"):
                return True
            if val in ("0", "false", "no"):
                return False
            return default

        def _int(key: str, default: int) -> int:
            try:
                return int(os.environ.get(key, default))
            except ValueError:
                return default

        def _csv(key: str, default: list[str] | None = None) -> list[str]:
            raw = os.environ.get(key, "")
            if not raw:
                return list(default) if default else []
            return [s.strip() for s in raw.split(",") if s.strip()]

        return cls(
            repos=_csv("ARAGORA_WATCH_REPOS"),
            poll_interval_seconds=_int("ARAGORA_WATCH_POLL_INTERVAL", 120),
            agents=os.environ.get("ARAGORA_WATCH_AGENTS", "anthropic-api,openai-api"),
            rounds=_int("ARAGORA_WATCH_ROUNDS", 2),
            dry_run=_bool("ARAGORA_WATCH_DRY_RUN", False),
            gauntlet=_bool("ARAGORA_WATCH_GAUNTLET", False),
            skip_drafts=_bool("ARAGORA_WATCH_SKIP_DRAFTS", True),
            skip_labels=_csv("ARAGORA_WATCH_SKIP_LABELS", ["wip", "do-not-review"]),
            max_reviews_per_hour=_int("ARAGORA_WATCH_MAX_REVIEWS_PER_HOUR", 10),
            state_file=os.environ.get("ARAGORA_WATCH_STATE_FILE", ""),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WatcherConfig:
        """Create config from a plain dictionary."""
        return cls(
            **{
                k: data[k]
                for k in (
                    "repos",
                    "poll_interval_seconds",
                    "startup_delay_seconds",
                    "agents",
                    "rounds",
                    "dry_run",
                    "gauntlet",
                    "skip_drafts",
                    "skip_labels",
                    "only_labels",
                    "max_diff_size_kb",
                    "max_reviews_per_hour",
                    "max_concurrent_reviews",
                    "state_file",
                    "policy_file",
                )
                if k in data
            }
        )


# ---------------------------------------------------------------------------
# Per-PR tracked state
# ---------------------------------------------------------------------------


@dataclass
class PRState:
    """Tracked state for a single reviewed PR."""

    repo: str
    pr_number: int
    head_sha: str
    review_id: str | None = None
    findings_count: int = 0
    critical_count: int = 0
    reviewed_at: float = 0.0
    consecutive_errors: int = 0
    last_error: str | None = None


# ---------------------------------------------------------------------------
# JSON file-based state persistence
# ---------------------------------------------------------------------------


class StateStore:
    """Persist watcher state as a JSON file with atomic writes."""

    def __init__(self, path: str | None = None) -> None:
        self._path = Path(path) if path else Path.home() / ".aragora" / "pr-watcher-state.json"
        self._state: dict[str, PRState] = {}
        self._load()

    def needs_review(self, repo: str, pr_number: int, head_sha: str) -> bool:
        """Return True when the PR is new or has new commits."""
        entry = self._state.get(f"{repo}#{pr_number}")
        return entry is None or entry.head_sha != head_sha

    def mark_reviewed(
        self,
        repo: str,
        pr_number: int,
        head_sha: str,
        review_id: str | None,
        findings_count: int,
        critical_count: int,
    ) -> None:
        self._state[f"{repo}#{pr_number}"] = PRState(
            repo=repo,
            pr_number=pr_number,
            head_sha=head_sha,
            review_id=review_id,
            findings_count=findings_count,
            critical_count=critical_count,
            reviewed_at=time.time(),
        )
        self._save()

    def mark_error(self, repo: str, pr_number: int, error: str) -> None:
        key = f"{repo}#{pr_number}"
        entry = self._state.get(key)
        if entry is None:
            entry = PRState(repo=repo, pr_number=pr_number, head_sha="")
            self._state[key] = entry
        entry.consecutive_errors += 1
        entry.last_error = error
        self._save()

    def cleanup(self, max_age_hours: int = 168) -> int:
        """Remove entries older than *max_age_hours*. Returns count removed."""
        cutoff = time.time() - max_age_hours * 3600
        before = len(self._state)
        self._state = {
            k: v for k, v in self._state.items() if v.reviewed_at > cutoff or v.reviewed_at == 0.0
        }
        removed = before - len(self._state)
        if removed:
            self._save()
        return removed

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for key, obj in raw.items():
                self._state[key] = PRState(**obj)
        except (json.JSONDecodeError, OSError, TypeError, KeyError) as exc:
            logger.warning("Failed to load state file %s: %s", self._path, exc)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps({k: v.__dict__ for k, v in self._state.items()}, indent=2),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(self._path))
        except OSError as exc:
            logger.warning("Failed to save state file: %s", exc)


# ---------------------------------------------------------------------------
# Runtime metrics
# ---------------------------------------------------------------------------


@dataclass
class WatcherMetrics:
    """Runtime metrics for the daemon."""

    polls_completed: int = 0
    prs_discovered: int = 0
    reviews_started: int = 0
    reviews_completed: int = 0
    reviews_failed: int = 0
    reviews_skipped: int = 0
    start_time: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        uptime = time.time() - self.start_time if self.start_time else 0.0
        return {
            "polls_completed": self.polls_completed,
            "prs_discovered": self.prs_discovered,
            "reviews_started": self.reviews_started,
            "reviews_completed": self.reviews_completed,
            "reviews_failed": self.reviews_failed,
            "reviews_skipped": self.reviews_skipped,
            "uptime_seconds": uptime,
        }


# ---------------------------------------------------------------------------
# Core daemon
# ---------------------------------------------------------------------------


class PRWatchDaemon:
    """Autonomous polling daemon that watches repos for PRs and reviews them."""

    def __init__(self, config: WatcherConfig) -> None:
        self._config = config
        self._store = StateStore(config.state_file or None)
        self._runner: Any = None  # lazy PRReviewRunner
        self._semaphore = asyncio.Semaphore(config.max_concurrent_reviews)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._metrics = WatcherMetrics()
        self._reviews_this_hour: list[float] = []

    def start(self) -> None:
        """Create the background daemon task."""
        if self._task and not self._task.done():
            logger.warning("Daemon already running")
            return
        self._stop_event.clear()
        self._metrics = WatcherMetrics(start_time=time.time())
        self._task = asyncio.create_task(self._daemon_loop())
        logger.info("PR watch daemon started for repos=%s", self._config.repos)

    async def stop(self, graceful: bool = True) -> None:
        """Signal the daemon to stop and optionally wait for it."""
        self._stop_event.set()
        if self._task and not self._task.done():
            if graceful:
                try:
                    await asyncio.wait_for(self._task, timeout=30.0)
                except asyncio.TimeoutError:
                    logger.warning("Graceful stop timed out, cancelling")
                    self._task.cancel()
            else:
                self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PR watch daemon stopped")

    def get_status(self) -> dict[str, Any]:
        running = self._task is not None and not self._task.done()
        return {
            "running": running,
            "config": {
                "repos": self._config.repos,
                "poll_interval_seconds": self._config.poll_interval_seconds,
                "dry_run": self._config.dry_run,
            },
            "metrics": self._metrics.to_dict(),
        }

    # -- daemon loop --

    async def _daemon_loop(self) -> None:
        delay = self._config.startup_delay_seconds
        if delay > 0:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                return
            except asyncio.TimeoutError:
                pass

        while not self._stop_event.is_set():
            try:
                await self._poll_all_repos()
            except asyncio.CancelledError:
                raise
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                logger.error("Poll error: %s", exc, exc_info=True)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._config.poll_interval_seconds,
                )
                break
            except asyncio.TimeoutError:
                pass

    # -- polling --

    async def _poll_all_repos(self) -> None:
        for repo in self._config.repos:
            if self._stop_event.is_set():
                break
            try:
                await self._poll_repo(repo)
            except asyncio.CancelledError:
                raise
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                logger.error("Error polling %s: %s", repo, exc)
        self._metrics.polls_completed += 1

    async def _poll_repo(self, repo: str) -> None:
        if not _REPO_RE.match(repo):
            logger.warning("Invalid repo format, skipping: %s", repo)
            return

        prs = self._list_open_prs(repo)
        if prs is None:
            return

        for pr in prs:
            if self._stop_event.is_set():
                break

            pr_number: int = pr["number"]
            head_sha: str = pr.get("headRefOid", "")
            is_draft: bool = pr.get("isDraft", False)
            labels: list[str] = [
                lbl.get("name", "") if isinstance(lbl, dict) else str(lbl)
                for lbl in pr.get("labels", [])
            ]

            if self._config.skip_drafts and is_draft:
                self._metrics.reviews_skipped += 1
                continue
            if any(lbl in self._config.skip_labels for lbl in labels):
                self._metrics.reviews_skipped += 1
                continue
            if self._config.only_labels and not any(
                lbl in self._config.only_labels for lbl in labels
            ):
                self._metrics.reviews_skipped += 1
                continue

            self._metrics.prs_discovered += 1

            if not self._store.needs_review(repo, pr_number, head_sha):
                continue
            if not self._can_review():
                logger.debug("Hourly rate limit reached, stopping poll")
                break

            async with self._semaphore:
                await self._review_pr(repo, pr_number, head_sha)

    def _list_open_prs(self, repo: str) -> list[dict[str, Any]] | None:
        """Run ``gh pr list`` and return parsed JSON, or None on failure."""
        try:
            result = subprocess.run(
                [
                    "gh",
                    "pr",
                    "list",
                    "--repo",
                    repo,
                    "--state",
                    "open",
                    "--limit",
                    "50",
                    "--json",
                    "number,headRefOid,isDraft,labels,updatedAt,title",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.warning("gh pr list failed for %s: %s", repo, result.stderr.strip())
                return None
            return json.loads(result.stdout)  # type: ignore[no-any-return]
        except FileNotFoundError:
            logger.error("gh CLI not found")
            return None
        except subprocess.TimeoutExpired:
            logger.warning("gh pr list timed out for %s", repo)
            return None
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to parse PR list for %s: %s", repo, exc)
            return None

    # -- reviewing --

    async def _review_pr(self, repo: str, pr_number: int, head_sha: str) -> None:
        pr_url = f"https://github.com/{repo}/pull/{pr_number}"
        logger.info("Reviewing %s (sha=%s)", pr_url, head_sha[:8])
        self._metrics.reviews_started += 1

        try:
            runner = self._get_runner()
            result = await runner.review_pr(pr_url)

            review_id = result.receipt.review_id if result.receipt else None
            self._store.mark_reviewed(
                repo,
                pr_number,
                head_sha,
                review_id,
                len(result.findings),
                result.critical_count,
            )
            self._reviews_this_hour.append(time.time())
            self._metrics.reviews_completed += 1
            logger.info(
                "Review complete: %s -- %d findings (%d critical)",
                pr_url,
                len(result.findings),
                result.critical_count,
            )
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            self._store.mark_error(repo, pr_number, str(exc))
            self._metrics.reviews_failed += 1
            logger.error("Review failed for %s: %s", pr_url, exc)

    def _get_runner(self) -> Any:
        """Lazy-import and cache the PRReviewRunner."""
        if self._runner is None:
            from aragora.compat.openclaw.pr_review_runner import PRReviewRunner

            kwargs: dict[str, Any] = {
                "dry_run": self._config.dry_run,
                "agents": self._config.agents,
                "rounds": self._config.rounds,
                "gauntlet": self._config.gauntlet,
            }
            if self._config.policy_file:
                self._runner = PRReviewRunner.from_policy_file(
                    self._config.policy_file,
                    **kwargs,
                )
            else:
                self._runner = PRReviewRunner(**kwargs)
        return self._runner

    def _can_review(self) -> bool:
        now = time.time()
        self._reviews_this_hour = [t for t in self._reviews_this_hour if t > now - 3600]
        return len(self._reviews_this_hour) < self._config.max_reviews_per_hour


# ---------------------------------------------------------------------------
# Async entry point with signal handling
# ---------------------------------------------------------------------------


async def run_daemon(config: WatcherConfig) -> None:
    """Run the daemon until SIGTERM / SIGINT."""
    daemon = PRWatchDaemon(config)
    daemon.start()

    loop = asyncio.get_running_loop()

    def _on_signal() -> None:
        logger.info("Signal received, stopping daemon")
        asyncio.ensure_future(daemon.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            pass  # Windows

    if daemon._task:
        try:
            await daemon._task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Watch GitHub repos for PRs and run multi-agent reviews",
    )
    parser.add_argument("--repo", action="append", default=[], help="owner/repo (repeatable)")
    parser.add_argument("--poll-interval", type=int, default=120, help="Seconds between polls")
    parser.add_argument("--dry-run", action="store_true", help="Analyze without posting comments")
    parser.add_argument("--agents", default="anthropic-api,openai-api", help="Agent list")
    parser.add_argument("--rounds", type=int, default=2, help="Debate rounds")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    env_config = WatcherConfig.from_env()
    repos = args.repo or env_config.repos
    if not repos:
        parser.error("At least one --repo is required (or set ARAGORA_WATCH_REPOS)")

    config = WatcherConfig(
        repos=repos,
        poll_interval_seconds=args.poll_interval,
        agents=args.agents,
        rounds=args.rounds,
        dry_run=args.dry_run or env_config.dry_run,
        gauntlet=env_config.gauntlet,
        skip_drafts=env_config.skip_drafts,
        skip_labels=env_config.skip_labels,
        max_reviews_per_hour=env_config.max_reviews_per_hour,
        state_file=env_config.state_file,
        policy_file=env_config.policy_file,
    )
    asyncio.run(run_daemon(config))


if __name__ == "__main__":
    main()
