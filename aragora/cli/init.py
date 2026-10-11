"""
Aragora init command - Project scaffolding.

Creates a new Aragora project with configuration files, directory structure,
and optional CI integration.

Usage:
    aragora init                    # Initialize in current directory
    aragora init --ci github        # Also generate GitHub Actions workflow
    aragora init --preset review    # Configure for code review workflow
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_CONFIG = """\
# Aragora Configuration
# Docs: https://github.com/synaptent/aragora

# Agents for debates and reviews
# Uses whichever API keys are available in your environment
agents:
  - anthropic-api
  - openai-api

# Code review settings (aragora review)
review:
  focus:
    - security
    - performance
    - quality
  fail_on_critical: false
  rounds: 2

# Debate settings (aragora ask)
debate:
  rounds: 3
  consensus: majority
  enable_memory: true

# Server settings (aragora serve)
server:
  http_port: 8080
  ws_port: 8765
"""

REVIEW_CONFIG = """\
# Aragora Configuration - Code Review Preset
# Docs: https://github.com/synaptent/aragora

# Agents for code review (uses available API keys)
agents:
  - anthropic-api
  - openai-api

# Code review settings
review:
  focus:
    - security
    - performance
    - quality
    - correctness
  fail_on_critical: true
  rounds: 2

# Gauntlet (adversarial stress testing)
gauntlet:
  profiles:
    - security
    - compliance
  output_format: sarif
"""

GITHUB_ACTIONS_WORKFLOW = """\
# Aragora AI Code Review
# Docs: https://github.com/synaptent/aragora
name: Aragora Review

on:
  pull_request:
    types: [opened, synchronize]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: synaptent/aragora@486a10d835be5da00df488b5bef6c1e708da8f10
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
          post-comment: true
          fail-on-critical: false
"""

GITIGNORE_CONTENT = """\
# Aragora data
.aragora/
*.db
*.db-journal
*.db-wal
*.db-shm

# Environment
.env
.env.local

# Python
__pycache__/
*.pyc
.venv/
"""


def _gitignore_has_entry(existing: str, entry: str) -> bool:
    """Return True if ``entry`` is already an active (non-comment) line.

    Compares against stripped, non-comment lines so that a substring match
    inside a comment or a longer path does not falsely suppress a needed entry.
    """
    for line in existing.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == entry:
            return True
    return False


def _detect_api_keys() -> list[str]:
    """Detect which API keys are available in the environment."""
    key_map = {
        "ANTHROPIC_API_KEY": "anthropic-api",
        "OPENAI_API_KEY": "openai-api",
        "GEMINI_API_KEY": "gemini",
        "XAI_API_KEY": "grok",
        "MISTRAL_API_KEY": "mistral",
        "OPENROUTER_API_KEY": "openrouter",
    }
    found = []
    for env_var, agent_name in key_map.items():
        if os.environ.get(env_var):
            found.append(agent_name)
    return found


def init_project(
    directory: str | None = None,
    force: bool = False,
    with_git: bool = True,
    ci: str | None = None,
    preset: str | None = None,
) -> dict:
    """Initialize a new Aragora project.

    Args:
        directory: Target directory (default: current directory)
        force: Overwrite existing files
        with_git: Add .gitignore entries
        ci: CI provider to generate workflow for ("github" or None)
        preset: Configuration preset ("review" or None for default)

    Returns:
        Dict with created files and directories
    """
    target = Path(directory) if directory else Path.cwd()
    created: dict[str, list[str]] = {"files": [], "directories": []}
    warnings: list[str] = []

    # Create data directory
    data_dir = target / ".aragora"
    if not data_dir.exists():
        data_dir.mkdir(parents=True)
        created["directories"].append(str(data_dir))

    # Select config based on preset
    config_content = REVIEW_CONFIG if preset == "review" else DEFAULT_CONFIG

    # Create config file
    config_file = target / ".aragora.yaml"
    if not config_file.exists() or force:
        config_file.write_text(config_content)
        created["files"].append(str(config_file))
    elif preset == "review" and "Code Review Preset" not in config_file.read_text():
        # Config exists but does not match the requested preset and --force was
        # not supplied. Writing is gated by not-exists-or-force, so the preset
        # would otherwise be silently dropped. Surface this to the user instead
        # of printing a misleading success.
        warnings.append(
            f"{config_file} already exists; the 'review' preset was NOT applied. "
            "Re-run with --force to overwrite it."
        )

    # Create/update .gitignore
    if with_git:
        gitignore = target / ".gitignore"
        if gitignore.exists():
            existing = gitignore.read_text()
            # Add each required ignore entry that is genuinely missing. A single
            # substring test on ".aragora/" is too coarse: if that token already
            # appears (a prior init, a pre-existing entry, or even a comment),
            # the whole block — including the .env secret-ignore entries — was
            # being skipped, risking accidental credential commits.
            missing = [
                line
                for line in GITIGNORE_CONTENT.splitlines()
                if line.strip()
                and not line.lstrip().startswith("#")
                and not _gitignore_has_entry(existing, line.strip())
            ]
            if missing:
                with gitignore.open("a") as f:
                    if not existing.endswith("\n"):
                        f.write("\n")
                    f.write("\n# Aragora\n")
                    f.write("\n".join(missing) + "\n")
                created["files"].append(str(gitignore) + " (updated)")
        else:
            gitignore.write_text(GITIGNORE_CONTENT)
            created["files"].append(str(gitignore))

    # Create traces directory
    traces_dir = data_dir / "traces"
    if not traces_dir.exists():
        traces_dir.mkdir()
        created["directories"].append(str(traces_dir))

    # Generate CI workflow
    if ci == "github":
        workflows_dir = target / ".github" / "workflows"
        if not workflows_dir.exists():
            workflows_dir.mkdir(parents=True)
            created["directories"].append(str(workflows_dir))

        workflow_file = workflows_dir / "aragora-review.yml"
        if not workflow_file.exists() or force:
            workflow_file.write_text(GITHUB_ACTIONS_WORKFLOW)
            created["files"].append(str(workflow_file))

    if warnings:
        created["warnings"] = warnings

    return created


def cmd_init(args) -> None:
    """Handle 'init' command."""
    print("\nInitializing Aragora project...")

    result = init_project(
        directory=getattr(args, "directory", None),
        force=getattr(args, "force", False),
        with_git=not getattr(args, "no_git", False),
        ci=getattr(args, "ci", None),
        preset=getattr(args, "preset", None),
    )

    if result["directories"]:
        print("\nCreated directories:")
        for d in result["directories"]:
            print(f"  - {d}")

    if result["files"]:
        print("\nCreated files:")
        for f in result["files"]:
            print(f"  - {f}")

    if result.get("warnings"):
        print("\nWarnings:")
        for w in result["warnings"]:
            print(f"  ! {w}")

    # Detect available API keys
    detected = _detect_api_keys()
    if detected:
        print(f"\nDetected API keys: {', '.join(detected)}")
    else:
        print("\nNo API keys detected. Set at least one:")
        print("  export ANTHROPIC_API_KEY=your-key")
        print("  export OPENAI_API_KEY=your-key")

    print("\nAragora project initialized!")
    print("\n" + "=" * 60)
    print("  GOLDEN PATH: Install -> Demo -> Decision Receipt")
    print("=" * 60)
    print()
    print("  Quick start (no API keys needed):")
    print("    aragora starter              # Guided onboarding flow")
    print("    aragora demo                 # Quick offline debate")
    print("    aragora quickstart --demo    # Zero-to-receipt in 60s")
    print()
    if detected:
        print("  Go live with real agents:")
        print('    aragora decide "Your question"  # Full decision pipeline')
        print('    aragora ask "Your question"     # Debate only')
        print()
    else:
        print("  To go live, add API keys then:")
        print('    aragora decide "Your question"  # Full decision pipeline')
        print()
    print("  System check:")
    print("    aragora doctor               # Environment health")
    print("    aragora setup                # Interactive setup wizard")

    if not getattr(args, "ci", None):
        print("\n  CI integration:")
        print("    aragora init --ci github")
