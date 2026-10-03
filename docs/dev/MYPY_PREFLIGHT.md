# Mypy Preflight (`scripts/preflight_mypy.sh`)

## Rationale

CI runs mypy against the files changed on each PR. When a lane lands many edits
across packages, surfacing those errors on the GitHub side is slow and noisy. A
local preflight that mirrors CI's "changed files only" gate — using the same
mypy configuration already declared in `pyproject.toml` — catches the easy
regressions before push, without adding a new config or pinning a hook into
everyone's git workflow.

## Command

```bash
# Default: diff against origin/main
scripts/preflight_mypy.sh

# Target another base (e.g. a fork's main, or a feature branch)
scripts/preflight_mypy.sh --diff-base origin/release-2026.05
```

The script:

1. Resolves the changed `*.py` files via `git diff --name-only <base>...HEAD`.
2. If none, prints `no python changes; mypy preflight skipped` and exits 0.
3. Otherwise runs `mypy --pretty <files...>` using the repo's existing config
   and exits with mypy's exit code (plus a short remediation hint on failure).

The gate selects files from **committed state only** — python edits outside
the committed diff (staged, unstaged, or untracked) are never type-checked
(the script prints a stderr warning naming them), so run it after committing.

## Integration suggestion

Call it from Phase 2 (verification) of any lane that touches Python:

```bash
scripts/preflight_mypy.sh || {
    echo "mypy preflight failed — fix before pushing" >&2
    exit 1
}
```

A future lane may wire this into `pre-push` (see the project README for opt-in
hook installation guidance); that wiring is intentionally out of scope here.
