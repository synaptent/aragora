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
2. Repo-config pass: if none changed, prints
   `no python changes; repo-config mypy pass skipped`; otherwise runs
   `mypy --pretty <files...>` using the repo's existing config (plus a short
   remediation hint on failure).
3. Pre-push hook parity: always runs the repo's own pre-push hook with
   `pre-commit run typecheck-changed --hook-stage pre-push --all-files --verbose`.
   The hook plans `origin/main...HEAD` (whatever `--diff-base` says) and runs
   CI's changed-file form, `mypy --ignore-missing-imports --follow-imports=skip
   --show-error-codes`, on the changed `aragora/**.py` files, or
   `scripts/test_tiers.sh typecheck` when config files force a full run. It
   uses the mypy version and stub packages pinned in `.pre-commit-config.yaml`.
4. Exits with the repo-config pass's mypy exit code if it failed, otherwise
   with the hook's exit code. It exits 2 if `mypy` or `pre-commit` is missing.

Neither pass subsumes the other, so the preflight requires both. With
`--follow-imports=skip` the hook cannot see attributes that only an unchanged
base class initializes and reports them as `[has-type]`; the repo config
(`follow_imports = "silent"`) resolves them. In the other direction, the
repo-config pass follows imports and reports errors such as `[arg-type]`
against unchanged modules, which the hook treats as `Any`. The hook's stub
set can also change verdicts relative to a project virtualenv that has the
runtime packages installed. Running the hook itself keeps the preflight in
step with what `git push` will enforce.

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

## Tests

`tests/scripts/test_preflight_mypy.py` covers the script with PATH shims. Its
real-hook fixtures run the actual hook and mypy only when
`PREFLIGHT_MYPY_HOOK_INTEGRATION=1` is set, because pre-commit may need
network access to build the hook environment the first time.
