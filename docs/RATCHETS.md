# Ratchets: shrink-only quality baselines

A **ratchet** is a quality gate that starts at today's count and may only go
down. It lets a gate land on a codebase with existing debt without turning
`main` red: every pre-existing finding is recorded in a committed baseline,
new findings fail the check, and the baseline can only shrink. This is the
Layer 1 mechanism of the readiness architecture; every later per-app gate
(ruff naming/complexity, vulture, deptry, jscpd, mypy, ESLint, golangci-lint,
TODO/FIXME) is wired through it. **Do not invent a second baseline mechanism.**

## The runner: `scripts/ci/check_tool_baseline.py`

Stdlib-only Python (runs in CI before project dependencies are installed).

```
usage: check_tool_baseline.py --tool NAME --baseline PATH [--update]
                              [--allow-grow --reason TEXT] [--report-json PATH]
                              [--cwd DIR] -- <command...>
```

| Flag | Meaning |
|---|---|
| `--tool NAME` | Which parser to apply to the command's stdout (see [Supported parsers](#supported-parsers)). |
| `--baseline PATH` | The baseline JSON to compare against; created by `--update` when absent. |
| `--update` | Rewrite the baseline to the current finding set. **Shrink-only** (see below). |
| `--allow-grow` | With `--update`, permit the baseline to grow. Requires `--reason`. |
| `--reason TEXT` | Why growth is acceptable; recorded in the baseline's `growth_log`. |
| `--report-json PATH` | Write a machine-readable report (tool, baseline path, new finding keys, counts, exit code). |
| `--cwd DIR` | Run the command there; finding paths are made relative to it (default: current directory). |
| `-- <command...>` | Everything after the `--` separator is the tool command line, run verbatim inside `--cwd`. |

The runner runs the command, strips colour codes, parses stdout with the
`--tool` parser, keys each finding, counts occurrences per key, and compares the
counts against the baseline. A key whose count exceeds its baselined count is a
**new finding**. Keys in the baseline that no longer occur are **resolved** and
never fail the run.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | No new findings. Prints `<tool>: 0 new findings (<n> baselined, <m> resolved)` plus a second line with both `len(findings)` (keys) and `sum(counts)` (occurrences) for the current run and the baseline. |
| `1` | New findings. Each key is printed as `NEW <key>  (<path>:<line>: <message>)`, followed by the baseline path and both remedies (`--update`, `--update --allow-grow --reason "<why>"`). Also returned when `--update` refuses to grow the baseline. |
| `2` | Baseline problem: corrupt JSON, wrong shape (missing `tool`/`findings`, wrong `version`), `tool` mismatch between the file and `--tool`, missing file without `--update`, unknown `--tool`; or an argparse usage error (e.g. `--allow-grow` without `--reason`). |
| `3` | The tool failed to run (not found, `OSError`), exited non-zero with **no parseable findings** (a usage error, a crash), or exited with a code outside its **clean and findings exit codes** however many findings parsed (a crash part-way leaves a truncated set). This is never interpreted as "zero findings", and the baseline is never rewritten in this state, even with `--update`. |

Each tool has two exit-code sets: the clean codes (`clean_exit_codes` in the
parser registry) and the findings codes (`FINDINGS_EXIT_CODES` in the runner),
both taken from the tool's documentation and listed in the
[Supported parsers](#supported-parsers) table. A findings code *with* parseable
findings is the normal case (ruff and mypy exit 1 when they report something).
Any other code fails the run with exit `3` even when findings parsed: ruff or
eslint exiting 2 on a config error, grep exiting 2 on an unreadable file, or
golangci-lint exiting 3 after partial JSON would otherwise pass as a subset of
the baseline, and `--update` would shrink it from the crashed run. A findings
code with **no** findings is still a crash. For `--tool todo`, grep's exit 1 on
zero matches is a clean run with zero findings (exit 0), not a crash.

### Finding keys

Every finding is keyed as `<path>::<symbol>::<rule>`:

- `path` is POSIX and **relative to `--cwd`** (never absolute, never `./`-prefixed), so baselines are machine-independent and CI matches local runs.
- `symbol` is either a symbol name the tool reports, or a 12-hex-digit SHA-256 prefix of the offending source line's stripped content. `ruff`, `mypy`, `eslint`, and `golangci-lint` keys use the **line-content hash** (not the enclosing symbol) so two findings of the same rule inside one function do not collide.
- `rule` is the tool's code (`F401`, `arg-type`, `TODO`).

Line numbers are never part of the key, so a pure line shift (inserting code
above a baselined finding) never surfaces as a new finding. Editing the
offending line itself does produce a new key: that is the point at which the
contributor is expected to fix the finding.

### Baseline file format

```json
{
  "tool": "ruff",
  "version": 1,
  "generated_at": "2026-09-04T03:55:45Z",
  "findings": {
    "aragora/cli/main.py::de2abade832c::N806": 1
  },
  "growth_log": [
    {"at": "2026-09-04T03:55:45Z", "reason": "adopting module X", "added": 3}
  ]
}
```

`findings` maps key to occurrence count with keys serialised in sorted order.
`growth_log` is present only after an `--allow-grow` update. Baselines are
**generated by the tool, never hand-edited**.

**What "count" means.** Wherever a PR body, `docs/TECH_DEBT.md`, or a
readiness report states a baseline's count, it means `len(findings)` (the
number of keys), not `sum(counts)` (occurrences). The runner prints both so the
figures can be cross-checked.

### The shrink-only rule

`--update` rewrites the baseline **only if the current set is a subset of the
baselined set** (equal or smaller). If the current run contains any key not in
the baseline, or a higher count for an existing key, `--update` prints the new
findings, prints a `REFUSED` line explaining the rule, exits 1, and leaves the
file byte-identical.

To grow a baseline intentionally (adopting a new module, raising a tool's
scope), pass `--update --allow-grow --reason "<why>"`. `--allow-grow` without
`--reason` is a usage error (exit 2). The reason and the number of added keys
are appended to `growth_log` in the file, so growth is visible in the diff and
in review.

`--update` is idempotent: when the finding set is unchanged it skips the rewrite
entirely (including `generated_at`), so re-running a regeneration command never
churns committed baselines. Creating a baseline that does not exist yet is not
growth.

### Baseline location and naming

Baselines live in `scripts/baselines/` and are named

```
scripts/baselines/<app>-<tool>[-<variant>].json
```

where `<app>` is one of `root`, `debate`, `verify`, `live`, `docs`, `vscode`,
`operator`, `<tool>` is the `--tool` name, and the optional `<variant>`
distinguishes several baselines of the same tool for one app, e.g.
`root-ruff-naming.json` vs `root-ruff-complexity.json`. The base form
`<app>-<tool>.json` is used when there is only one.

The 18 pre-existing files in `scripts/baselines/` (e.g.
`file_size_baseline.json`, `mypy_full_baseline.json`) predate this framework
and keep their own formats; a file is a ratchet baseline in this sense only
when its top-level JSON has a string `tool` and an object `findings`.

## Supported parsers

Parsers live in `scripts/ci/tool_baseline_parsers.py`. Each is a pure function
`parse(stdout: str) -> list[Finding]` registered with `@register("<tool>", ...)`;
adding a parser is a one-function change and the runner's `--help`, this list,
and `docs/TECH_DEBT.md` follow.

The eight M1 parsers (`python scripts/ci/check_tool_baseline.py --help` lists
the same names). The command column is what the runner expects to find on the
tool's **stdout**; run it from `--cwd` so reported paths stay relative.

| `--tool` | Command it expects (stdout) | Key form `<path>::<symbol>::<rule>` | Exit codes: clean / findings |
|---|---|---|---|
| `ruff` | `ruff check <paths> [--select ...] --output-format concise` | symbol = line-content hash; rule = ruff code (`F401`, `N806`) | `0` / `1` (`2` = invalid configuration or options, internal error) |
| `vulture` | `vulture <paths> [--min-confidence N]` (text: `path:line: unused <kind> '<name>' (NN% confidence)`) | symbol = the reported name; rule = `unused-<kind>` (`unused-import`, `unused-function`, …); unnamed findings such as `unreachable code` hash the message | `0` / `3` (vulture exits `3` when it reports dead code; `1` = invalid input, `2` = invalid arguments) |
| `deptry` | `deptry <root> --json-output /dev/stdout` (the human report goes to stderr) | symbol = module name; rule = `DEP001`..`DEP004`; `pyproject.toml` findings have no line | `0` / `1` (`2` = usage error) |
| `jscpd` | `sh -c 'jscpd --reporters json --output DIR --silent . >/dev/null; cat DIR/jscpd-report.json'` — the `json` reporter only writes `DIR/jscpd-report.json`, never stdout, so the wired command must `cat` it; scan `.` from `--cwd` so `firstFile.name` is relative | path = `firstFile.name`; symbol = hash of the duplicated `fragment`; rule = `clone`. A third copy of the same fragment raises the count | `0` / `1` (`1` only when over `--threshold` or with `--exitCode 1`; by default clones exit `0`) |
| `mypy` | `mypy [--ignore-missing-imports] <paths>` (text output; `error`/`warning` lines, notes ignored) | symbol = line-content hash; rule = `[code]` (`arg-type`, `return-value`) | `0` / `1` (`2` = crash or fatal error) |
| `eslint` | `eslint -f json <paths>` (`filePath` is absolute; the runner makes it relative to `--cwd`) | symbol = line-content hash; rule = `ruleId` (a fatal parse error with `ruleId: null` is `fatal`) | `0` / `1` (`2` = configuration problem or internal error) |
| `golangci-lint` | `golangci-lint run --output.json.path stdout --show-stats=false ./...` (v2 JSON schema: `{"Issues":[{"FromLinter","Text","SourceLines","Pos":{"Filename","Line"}}],"Report":…}`; without `--show-stats=false` a text stats block follows the JSON on stdout and only the first JSON object is read) | symbol = line-content hash (taken from `SourceLines[0]`, or read from the file when absent); rule = `FromLinter` (`errcheck`, `revive`) | `0` / `1` (the default `--issues-exit-code`; `3` = failure, `4` = timeout, `5`+ other errors) |
| `todo` | `grep -rn --include='*.py' -E 'TODO\|FIXME' .` | symbol = matched-line hash; rule = the marker word (`TODO`, `FIXME`, `XXX`, `HACK`) | `0`, `1` (no matches) / `0` (`2` = an error such as an unreadable file, even after matches) |

Two key families follow from the table:

- **Line-keyed tools** (`ruff`, `mypy`, `eslint`, `golangci-lint`): the parser
  reports a line number and the runner hashes that source line's stripped
  content from `--cwd`, so two findings of the same rule in one function keep
  distinct keys and a pure line shift changes nothing.
- **Symbol-keyed tools** (`vulture`, `deptry`, `jscpd`, `todo`): the tool's own
  output already names the thing (a dead symbol, an unused module, a duplicated
  fragment, a matched comment line), so the parser fills the symbol itself and
  the runner never opens the source file.

Every parser has a captured real-output fixture under
`tests/ci/fixtures/tool_baseline/` and at least one test id naming it in
`tests/ci/test_check_tool_baseline.py`; a later milestone that adds a parser
(e.g. `knip`) must add both, plus its documented findings exit codes in
`FINDINGS_EXIT_CODES` (without an entry the runner accepts only the clean
codes).

## Contributor flow

When a ratchet fails on your PR (exit 1), the output already contains
everything you need: the finding key, the baseline path, and both remedies.

1. **Fix or baseline.** The default is to fix the finding. Baseline it only when
   fixing is genuinely out of scope for the change, and say so in the PR.
2. **Regenerate with `--update`**, using the exact command that is wired for that
   baseline (the Make target that runs the check, with `--update` appended, or
   the per-baseline command listed below). Never hand-edit a baseline file.
   Shrinking is always allowed; growth needs `--update --allow-grow --reason "<why>"`.
3. **Commit the baseline change together with the fix** in the same commit, so
   the gate and the code stay in sync at every revision.
4. **Never regenerate a baseline you did not touch.** `--update` is idempotent,
   so running every wired regeneration command on a clean checkout of `main`
   must leave `git status --porcelain` empty; a diff there means a baseline is
   stale and should be fixed in its own commit.

### Wired baselines and their regeneration commands

At M1 no repository baseline is wired yet: this section is vacuous until M2
(`m2-python-core-gates`) lands the first root ratchets in
`make readiness-lint-root`. Each later milestone appends its baselines here,
one row per file, in the form:

| Baseline | Wired in | Regeneration command |
|---|---|---|
| _(none yet)_ | | |

The convention for every row: the regeneration command is the wired check
command plus `--update`, run from the repository root, e.g.

```bash
python scripts/ci/check_tool_baseline.py --tool ruff \
  --baseline scripts/baselines/root-ruff-naming.json --update \
  -- ruff check aragora --select N --output-format concise
```

`docs/TECH_DEBT.md` (created in M2) carries a `## Ratchets` table with one row
per baseline (Tool | Baseline file | Current count | Owner | Regeneration
command), where the count is `len(findings)`.

## Related mechanisms

Two entries below are intentionally placeholders: the mechanism is designed but
lands in a later feature, which replaces the marked comment in place.

- **ESLint bulk suppressions (M5) — placeholder, filled by `m5-frontend-quality`.**
  <!-- PLACEHOLDER (m5-frontend-quality): the JS apps use
  ESLint's native `eslint-suppressions.json` (`eslint --suppress-all` to create,
  `eslint --prune-suppressions` to shrink) for `naming-convention` and `complexity`
  instead of this runner; document the files, the prune command, and the
  shrink-only expectation here. -->
- **mypy override-count ratchet (M2).** `scripts/ci/check_mypy_overrides.py`
  enforces a shrink-only count of `[[tool.mypy.overrides]]` entries; documented
  when it lands.
- **TODO/FIXME ratchet (M2).** `scripts/ci/check_todo_ratchet.py` wraps this
  runner with `--tool todo` and a fixed scan scope; documented when it lands.
- **Dependency cooldown (uv).** See [Dependency release age](#dependency-release-age)
  below: `scripts/ci/uv_lock_with_cooldown.sh` is the only place the uv
  cooldown applies, and the Dependabot relock in `dependabot-uv-lock.yml` runs
  it.

## Dependency release age

Three controls keep freshly published dependency versions out of the tree for
a few days (supply-chain cooldown). None of them changes what CI installs:
install steps always run against the committed lockfiles (`uv sync --frozen`
/ `--locked`, `npm ci`).

### npm: `min-release-age=3`

Every JS app directory (`aragora/live`, `docs-site`, `ide/vscode-aragora`,
`ide/vscode-aragora/webview-ui`, `sdk/typescript`) carries `min-release-age=3`
in its own `.npmrc`; npm ≥ 11.9 refuses versions published less than three
days ago when resolving. npm reads project config only from the nearest
`package.json` prefix (no parent merge), so the key must live in each app; the
root `.npmrc` is advisory and exists for future root-level packages. Probe from
an app directory with `npm config get min-release-age` (prints `3` on npm ≥ 12;
npm 11.x prints `null` because its config flattener rewrites the key into
`before` before `config get` reads it) or, on any supporting npm, with
`npm config get before` (a timestamp three days ago proves the key is in
effect) and `npm config list` (the project section shows the raw line).

### uv: `scripts/ci/uv_lock_with_cooldown.sh` (two-step flow)

`exclude-newer` is never written into `uv.lock` or `pyproject.toml`: a lock
produced with `--exclude-newer` carries an `[options] exclude-newer = ...`
table, and plain `uv lock --check` (the BLOCKING step in `security-gate.yml`)
fails on such a lock. The cooldown therefore applies only when *regenerating*
the lock, through this script, and CI never sets `UV_EXCLUDE_NEWER` in a job
that runs `uv lock --check`. `dependabot-uv-lock.yml` relocks through this
script and then runs plain `uv lock --check` on the result.

Run it from the workspace root (it operates on `pyproject.toml` + `uv.lock` in
`$PWD`; every uv call inside runs with `UV_EXCLUDE_NEWER` unset):

```bash
bash scripts/ci/uv_lock_with_cooldown.sh
```

Flow:

1. Prints `exclude-newer cutoff: <YYYY-MM-DDTHH:MM:SSZ>` (UTC now minus exactly
   7 days; a full RFC 3339 timestamp because uv reads a bare date as the next
   local midnight).
2. Runs `uv lock --exclude-newer <cutoff>` from the original lock (the
   cooled-down resolution). If no resolution satisfies the cooldown, it
   restores the original lock and exits `4`; nothing is relocked without the
   cooldown.
3. Runs plain `uv lock` from the original lock into a temp copy (the plain
   resolution). It serves only the comparison in step 6 and is never kept.
4. Copies the cooled-down lock back and re-runs plain `uv lock` on top of it:
   uv keeps the cooled-down pins as preferences and drops only the `[options]`
   tables, so the committed lock passes plain `uv lock --check`. The script then
   verifies that the final `uv.lock` carries no `exclude-newer` and pins exactly
   the cooled-down versions.
5. Compares the final lock with the **original** lock in PEP 440 order (with
   `python3`; a forked package is compared on its lowest and highest
   version). The cutoff also filters versions the original lock already pins,
   so a package released less than 7 days ago would roll back: typically a
   lock-only (transitive) security bump from a
   [manual security relock](#manual-security-relock), which nothing in
   `pyproject.toml` protects. If any package of the original lock would get a
   lower version, the script prints `downgraded: <name> <original> -> <cooled>`
   for each, restores the original lock and exits `5`. A downgraded lock is
   never kept.
6. Compares package versions between the two resolutions and prints
   `held back: <name> <plain> -> <cooled>` for each difference.

Exit codes: `0` when the two resolutions agree (lock regenerated); `2` when
packages were held back (listed and reported; `uv.lock` holds the verified
cooled-down resolution); `3` when `uv` is not on `PATH` (nothing touched); `4`
when no resolution satisfies the cooldown (no unrestricted fallback); `5` when
the cooled-down resolution would downgrade a package of the original lock
(listed as `downgraded:`); `1` on any other failure, including a final lock that
drifted from the cooled-down resolution, a version the downgrade check cannot
order, or bad usage. On `4`, `5` and `1` the original `uv.lock` is restored
byte-for-byte. Temp copies live under `/tmp/aragora-readiness/`.

#### Dependabot relock

The `Regenerate uv.lock` step of `.github/workflows/dependabot-uv-lock.yml`
relocks only through this script. It takes the helper from `origin/main`
(`git show origin/main:scripts/ci/uv_lock_with_cooldown.sh` into
`$RUNNER_TEMP`), so the reviewed main copy runs even on a Dependabot branch cut
before the helper existed, installs uv in the `pyproject.toml` range
(`uv>=0.11.19,<0.12`), and writes the cutoff, the helper exit code and any
`held back:` or `downgraded:` lines to the job summary. By helper exit code:

- `0`: the regenerated lock is committed to the Dependabot branch.
- `2`: the cooled-down lock is committed; the held-back packages are listed in
  the job summary, the step log and a `::warning::`.
- `4`: the job fails with an `::error::` that points here and commits nothing.
  Dependabot's own `cooldown` does not apply to security updates, so a security
  PR that needs a release younger than 7 days ends here; see the next section.
- `5`: the job fails with an `::error::` that points here and commits nothing
  (no `git add`, no push); the job summary lists each package with its original
  and cooled-down version. The branch's lock already holds a release younger
  than 7 days, usually from a manual security relock.
- anything else: the job fails and commits nothing.

There is no unrestricted fallback: the step never runs a bare `uv lock`. After a
relock it still runs the `uv.lock`-only diff guard and plain `uv lock --check`.

#### Manual security relock

When a security fix needs a release younger than the cooldown (for example a
Dependabot security PR whose relock job failed with exit `4`), a human relocks
on a local branch:

```bash
bash scripts/ci/uv_lock_with_cooldown.sh --allow-package <name>
```

Repeat `--allow-package` for each package the resolver names, and for each
package a run lists as `downgraded:` (exit `5`: a package already in the lock
whose locked release is younger than 7 days). Only the named
packages may be newer than the cutoff (`--exclude-newer-package`); every other
package, including any new dependency of a named one, keeps the 7-day cooldown,
and the committed lock still carries no `exclude-newer`. Commit only `uv.lock`
(and the manifest bump), and state in the PR body the advisory ID, every lifted
package with its version and release date, and the helper output.

Never run it in CI or a workflow: the option has no environment-variable form,
and a reviewer of a workflow change rejects any `--allow-package` under
`.github/`. The Dependabot relock job is not rerun for that PR; the human-made
lock replaces it. A human push of the manually relocked lock to a Dependabot
branch does re-trigger the job (its `uv.lock` path filter), which then fails
until the lifted package is 7 days old: with exit `4` when the bumped manifest
requires the version the cooldown excludes, and with exit `5` when the lifted
package is lock-only (nothing in `pyproject.toml` pins it, so the cooled-down
resolution would roll it back). That failure is expected: the job commits
nothing and the human-made lock stands.

### Dependabot cooldown

`.github/dependabot.yml` sets `cooldown: {default-days: 7, semver-major-days: 14}`
on every ecosystem entry (pip, npm ×5, gomod, github-actions). This is the
enforced control: Dependabot does not propose a version until it is at least a
week old (two weeks for major bumps).
