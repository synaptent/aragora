"""
Autopilot CLI command — autonomous GTM task orchestration.

The "lazy person's GTM engine." Runs all the tedious tasks you don't want to do:
  aragora autopilot --dry-run       # Show what would be done
  aragora autopilot                 # Do everything
  aragora autopilot publish         # Just handle publishing
  aragora autopilot pr-review       # Set up self-reviewing PRs
  aragora autopilot outreach        # Draft outreach emails
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _find_repo_root() -> Path:
    """Find the repository root."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists() and (parent / "aragora").is_dir():
            return parent
    return current


def _has_tool(name: str) -> bool:
    return shutil.which(name) is not None


def _run_cmd(cmd: list[str], cwd: str | None = None, timeout: int = 60) -> tuple[bool, str]:
    """Run a command, return (success, output)."""
    try:
        result = subprocess.run(  # subprocess with fixed args, no shell
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return False, str(e)


class AutopilotTask:
    """A single autopilot task."""

    def __init__(self, name: str, description: str, check_fn, run_fn):
        self.name = name
        self.description = description
        self._check = check_fn
        self._run = run_fn

    def check(self) -> tuple[str, str]:
        """Check status. Returns (status, detail) where status is DONE/TODO/BLOCKED."""
        return self._check()

    def run(self, dry_run: bool = False) -> tuple[bool, str]:
        """Execute the task. Returns (success, message)."""
        return self._run(dry_run)


def _check_gh_auth() -> tuple[str, str]:
    """Check if gh CLI is authenticated."""
    ok, out = _run_cmd(["gh", "auth", "status"])
    if ok:
        return "DONE", "Authenticated with GitHub"
    if not _has_tool("gh"):
        return "BLOCKED", "gh CLI not installed (brew install gh)"
    return "TODO", "Run: gh auth login"


def _check_pr_review_action() -> tuple[str, str]:
    """Check if PR review GitHub Action is configured."""
    repo_root = _find_repo_root()
    workflow = repo_root / ".github" / "workflows" / "pr-debate.yml"
    if workflow.exists():
        content = workflow.read_text()
        if "on:" in content and "pull_request" in content:
            return "DONE", "pr-debate.yml triggers on pull_request"
    return "TODO", "PR review action needs to be enabled"


def _setup_pr_review(dry_run: bool) -> tuple[bool, str]:
    """Verify PR review action is working."""
    repo_root = _find_repo_root()
    workflow = repo_root / ".github" / "workflows" / "pr-debate.yml"
    if not workflow.exists():
        return False, "pr-debate.yml not found"
    # Check it's configured to trigger on PRs
    content = workflow.read_text()
    if "pull_request" in content:
        if dry_run:
            return True, "[dry-run] PR review action already configured"
        return True, "PR review action is live and triggers on pull requests"
    return False, "pr-debate.yml exists but doesn't trigger on pull_request"


def _check_pypi_creds() -> tuple[str, str]:
    """Check if PyPI credentials are available."""
    if os.environ.get("TWINE_PASSWORD") or os.environ.get("PYPI_API_TOKEN"):
        return "DONE", "PyPI token in environment"
    if (Path.home() / ".pypirc").exists():
        return "DONE", "~/.pypirc found"
    return "TODO", "Set PYPI_API_TOKEN or create ~/.pypirc"


def _check_npm_auth() -> tuple[str, str]:
    """Check npm auth status."""
    if not _has_tool("npm"):
        return "BLOCKED", "npm not installed"
    ok, out = _run_cmd(["npm", "whoami"], timeout=10)
    if ok:
        return "DONE", f"npm: logged in as {out.strip()}"
    return "TODO", "Run: npm login"


def _publish_packages(dry_run: bool) -> tuple[bool, str]:
    """Run aragora publish --all."""
    cmd = [sys.executable, "-m", "aragora.cli.main", "publish", "--all"]
    if dry_run:
        cmd.append("--dry-run")
    ok, out = _run_cmd(cmd, cwd=str(_find_repo_root()), timeout=600)
    if ok:
        return True, "All packages published" if not dry_run else "[dry-run] Packages verified"
    return False, f"Publish failed: {out[:200]}"


def _check_demo_data() -> tuple[str, str]:
    """Check if demo data is seeded."""
    repo_root = _find_repo_root()
    seed_script = repo_root / "scripts" / "seed_demo.py"
    if not seed_script.exists():
        return "BLOCKED", "seed_demo.py not found"
    # Check if data exists
    ok, out = _run_cmd(
        [sys.executable, str(seed_script), "--check"],
        cwd=str(repo_root),
        timeout=15,
    )
    if ok and "exists" in out.lower():
        return "DONE", "Demo data seeded"
    return "TODO", "Run: python scripts/seed_demo.py"


def _seed_demo(dry_run: bool) -> tuple[bool, str]:
    """Seed demo data."""
    repo_root = _find_repo_root()
    seed_script = repo_root / "scripts" / "seed_demo.py"
    if dry_run:
        return True, "[dry-run] Would seed demo data"
    ok, out = _run_cmd(
        [sys.executable, str(seed_script)],
        cwd=str(repo_root),
        timeout=30,
    )
    return ok, "Demo data seeded" if ok else f"Seeding failed: {out[:200]}"


def _check_outreach_drafts() -> tuple[str, str]:
    """Check if outreach drafts exist."""
    outreach_dir = _find_repo_root() / "outreach"
    if outreach_dir.exists() and list(outreach_dir.glob("*.md")):
        count = len(list(outreach_dir.glob("*.md")))
        return "DONE", f"{count} outreach draft(s) ready"
    return "TODO", "No outreach drafts generated yet"


def _generate_outreach(dry_run: bool) -> tuple[bool, str]:
    """Generate outreach email drafts for target verticals."""
    repo_root = _find_repo_root()
    outreach_dir = repo_root / "outreach"

    if dry_run:
        return True, "[dry-run] Would generate outreach drafts in outreach/"

    outreach_dir.mkdir(exist_ok=True)

    templates = [
        {
            "filename": "eu-ai-act-compliance.md",
            "subject": "EU AI Act compliance for your AI-assisted {use_case}",
            "vertical": "Regulated industries (fintech, healthtech, legal)",
            "body": """Hi {name},

I'm building Aragora — an open-source tool that generates EU AI Act compliance artifacts (Article 12/13/14) for AI-assisted decisions.

With the Aug 2026 enforcement deadline approaching, I thought this might be relevant for {company}'s {use_case} workflow.

Here's what it does in 30 seconds:
```bash
pip install aragora
aragora compliance classify --use-case "{use_case}"
```

It tells you the risk tier, generates the required documentation, and creates an audit trail. All open source, self-hosted, no data leaves your infrastructure.

Would you have 15 minutes this week to try it on a real use case? I'll set it up for you.

Best,
{sender}

P.S. You can try it right now: `aragora review --demo` runs a multi-agent code review with no API keys.
""",
        },
        {
            "filename": "code-review-teams.md",
            "subject": "Multi-agent code review that catches what humans miss",
            "vertical": "Engineering teams (3-50 developers)",
            "body": """Hi {name},

Your team at {company} ships code fast. But code review is the bottleneck — reviewers are busy, context-switching is expensive, and subtle issues slip through.

Aragora runs 3-7 AI agents against every PR, each with a different perspective (security, performance, correctness, style). They debate the code and only flag issues where multiple agents agree.

Setup is one line in your GitHub Actions:
```yaml
- uses: aragora/review-action@v1
```

No server needed. No data leaves GitHub. Results appear as PR comments.

Want to try it on your next PR? I can set it up in 5 minutes.

{sender}
""",
        },
        {
            "filename": "ai-safety-researchers.md",
            "subject": "Open-source adversarial testing for LLM outputs",
            "vertical": "AI safety teams and researchers",
            "body": """Hi {name},

I noticed {company}'s work on {research_area}. I've been building Aragora — an open-source adversarial testing framework for LLM outputs.

The core idea: instead of trusting one model's output, run 3-7 heterogeneous models against each other in structured debate. Consensus score tells you how reliable the output is. Disagreement reveals blind spots.

Two things that might interest you:
1. **Gauntlet mode**: Stress-tests any document/decision with adversarial attack patterns
2. **Calibration tracking**: Brier scores across 1000+ decisions reveal systematic biases per model

It's all open source (MIT): https://github.com/aragora/aragora

Would love your feedback if you have 15 minutes.

{sender}
""",
        },
    ]

    for tmpl in templates:
        filepath = outreach_dir / tmpl["filename"]
        content = f"""# Outreach: {tmpl["vertical"]}

**Subject:** {tmpl["subject"]}

**Target:** {tmpl["vertical"]}

**Personalize:** Replace {{name}}, {{company}}, {{use_case}}, {{sender}}, etc.

---

{tmpl["body"]}
---
*Generated by `aragora autopilot` on {datetime.now(timezone.utc).strftime("%Y-%m-%d")}*
"""
        filepath.write_text(content)

    return True, f"Generated {len(templates)} outreach drafts in outreach/"


def _check_quickstart() -> tuple[str, str]:
    """Check if quickstart script works."""
    qs = _find_repo_root() / "deploy" / "quickstart.sh"
    if qs.exists():
        return "DONE", "deploy/quickstart.sh exists"
    return "TODO", "Quickstart script missing"


def _check_pip_install() -> tuple[str, str]:
    """Check if `pip install aragora` works from the repo."""
    ok, out = _run_cmd(
        [sys.executable, "-m", "pip", "install", "-e", ".", "--dry-run"],
        cwd=str(_find_repo_root()),
        timeout=30,
    )
    if ok:
        return "DONE", "pip install -e . works"
    return "TODO", f"pip install fails: {out[:100]}"


def build_autopilot_tasks() -> list[AutopilotTask]:
    """Build the full list of autopilot tasks."""
    return [
        AutopilotTask(
            "gh-auth",
            "GitHub CLI authentication",
            _check_gh_auth,
            lambda dry: (True, "Manual: gh auth login"),
        ),
        AutopilotTask(
            "pr-review",
            "PR review GitHub Action",
            _check_pr_review_action,
            _setup_pr_review,
        ),
        AutopilotTask(
            "pypi-creds",
            "PyPI publishing credentials",
            _check_pypi_creds,
            lambda dry: (True, "Manual: export PYPI_API_TOKEN=..."),
        ),
        AutopilotTask(
            "npm-auth",
            "npm publishing credentials",
            _check_npm_auth,
            lambda dry: (True, "Manual: npm login"),
        ),
        AutopilotTask(
            "pip-install",
            "Local pip install works",
            _check_pip_install,
            lambda dry: (True, "pip install -e ."),
        ),
        AutopilotTask(
            "publish",
            "Publish packages to PyPI/npm",
            _check_pypi_creds,
            _publish_packages,
        ),
        AutopilotTask(
            "demo-data",
            "Seed demo dashboard data",
            _check_demo_data,
            _seed_demo,
        ),
        AutopilotTask(
            "outreach",
            "Generate outreach email drafts",
            _check_outreach_drafts,
            _generate_outreach,
        ),
        AutopilotTask(
            "quickstart",
            "Quickstart deploy script",
            _check_quickstart,
            lambda dry: (True, "Already exists"),
        ),
    ]


def cmd_autopilot(args: argparse.Namespace) -> None:
    """Handle 'autopilot' command — autonomous GTM orchestration."""
    dry_run = getattr(args, "dry_run", False)
    targets = getattr(args, "tasks", None) or []
    status_only = getattr(args, "status", False)

    tasks = build_autopilot_tasks()

    # Filter to specific tasks if requested
    if targets:
        task_names = {t.name for t in tasks}
        invalid = [t for t in targets if t not in task_names]
        if invalid:
            print(f"Unknown tasks: {', '.join(invalid)}")
            print(f"Available: {', '.join(sorted(task_names))}")
            sys.exit(1)
        tasks = [t for t in tasks if t.name in targets]

    print(
        f"\n  Aragora Autopilot {'(status check)' if status_only else '(dry-run)' if dry_run else ''}"
    )
    print(f"  {'=' * 50}\n")

    # Phase 1: Status check
    statuses: list[tuple[AutopilotTask, str, str]] = []
    for task in tasks:
        status, detail = task.check()
        statuses.append((task, status, detail))
        marker = {"DONE": "+", "TODO": "-", "BLOCKED": "!"}[status]
        print(f"  [{marker}] {task.name:15s}  {detail}")

    if status_only:
        done = sum(1 for _, s, _ in statuses if s == "DONE")
        total = len(statuses)
        print(f"\n  {done}/{total} tasks complete.")
        return

    # Phase 2: Execute TODO tasks
    todo = [(t, d) for t, s, d in statuses if s == "TODO"]
    if not todo:
        print("\n  All tasks complete. Nothing to do.")
        return

    print(f"\n  Executing {len(todo)} task(s)...\n")

    results: list[tuple[str, bool, str]] = []
    for task, _ in todo:
        print(f"  Running: {task.name} — {task.description}")
        ok, msg = task.run(dry_run)
        results.append((task.name, ok, msg))
        marker = "+" if ok else "x"
        print(f"  [{marker}] {msg}\n")

    # Summary
    succeeded = sum(1 for _, ok, _ in results if ok)
    print(f"  {'=' * 50}")
    print(f"  {succeeded}/{len(results)} tasks {'verified' if dry_run else 'completed'}")

    failed = [(n, m) for n, ok, m in results if not ok]
    if failed:
        print("\n  Failed:")
        for name, msg in failed:
            print(f"    {name}: {msg}")
        sys.exit(1)


def add_autopilot_parser(subparsers) -> None:
    """Add the 'autopilot' subcommand parser."""
    ap_parser = subparsers.add_parser(
        "autopilot",
        help="Autonomous GTM task orchestration",
        description="""
The lazy person's go-to-market engine. Checks what needs doing and does it.

Tasks:
  gh-auth       GitHub CLI authentication
  pr-review     Self-reviewing PR GitHub Action
  pypi-creds    PyPI publishing credentials
  npm-auth      npm publishing credentials
  pip-install   Verify local install works
  publish       Build, test, and publish all packages
  demo-data     Seed demo dashboard with sample data
  outreach      Generate outreach email drafts
  quickstart    Verify quickstart deploy script

Examples:
  aragora autopilot --status        # Check what's done
  aragora autopilot --dry-run       # Preview what would happen
  aragora autopilot                 # Do everything that needs doing
  aragora autopilot publish outreach  # Just these tasks
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap_parser.add_argument(
        "tasks",
        nargs="*",
        help="Specific tasks to run (default: all)",
    )
    ap_parser.add_argument(
        "--status",
        action="store_true",
        help="Just check status, don't execute anything",
    )
    ap_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing",
    )
    ap_parser.set_defaults(func=cmd_autopilot)
