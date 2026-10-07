# P5: `aragora/cli/parser.py` split design (Tier 4)

Status: design and Tier-4 preapproval artifact. This is not an
implementation, and merging it authorizes nothing. Measured on `origin/main`
at `d4c9f6c7d5` (2026-10-07); the code is unchanged at `22185087c7`, the base
of this document's PR. Every count below came from a command in §11 or from
the cited lines at that commit.

`aragora/cli/parser.py` is Tier 4 (`TIER_4_PREFIXES`, explicit entry at
`aragora/cli/commands/review_queue.py:285`). The comment above that entry
(lines 277-284) gives the reason: the parser is the registration surface for
every `aragora` subcommand, and a new or changed registration can expose
tier-relevant behavior on the merge-authority CLI. The split therefore follows
the Tier-4 rule:

1. The operator preapproves this design before any implementation PR opens.
2. Each implementation PR is its own Tier-4 PR with exact-head operator
   settlement (`python3 scripts/settle_tier4_pr.py --check --pr <N> --head <SHA>`
   before any merge mutation).
3. A lane may prepare a step, but it parks at the settlement boundary and never
   self-merges.

The companion design for `aragora/cli/commands/review_queue.py` is
`docs/architecture/P5_REVIEW_QUEUE_SPLIT_DESIGN.md`. The two splits share one
edit point (§3, P3) and must be sequenced against each other.

## 1. Goal and non-goals

Goal: split the 5,363-line module into a facade under 2,000 lines plus
cohesive registration modules, each under 2,000 lines, with no behavior
change. Every command, alias, argument, default, help string, `func` binding
and the registration order stay identical.

Non-goals:

- No change to any command handler. Registration code moves; handlers stay
  where they are.
- No unification of the two review-queue registrations (§3, P7). They differ
  today, and unifying them is a behavior change.
- No change to `_mission_parser.py`, which already lives outside the facade.
- No change to `aragora/cli/main.py`, CODEOWNERS or the CI workflows.

## 2. Current shape (measured)

| Lines | Region | Contents |
|---|---|---|
| 1-30 | header | imports (`argparse`, `os`, `add_mission_parser`, three `aragora.config` defaults), `DEFAULT_CAMPAIGN_MANIFEST`, `DEFAULT_API_URL` and `DEFAULT_API_KEY` (environment reads at import), `CORE_COMMANDS` |
| 33-106 | infrastructure | `_lazy` (deferred handler import), `get_version`, `_GroupedCommandsParser` (core/advanced help grouping) |
| 109-235 | `build_parser` | 99 registration calls: 98 `_add_*` helpers plus `add_mission_parser(subparsers, _lazy)` |
| 238-941 | AGT/DIC operator surfaces | `metrics`, `work`, `markets`, `calibration`, `cruxset`, `proof-units`, `genealogy`, `coherence-scan`, `truth-map`, `decay-monitor`, `crux-arbitrate`, `crux-garden`, `epistemic-check` |
| 944-1914 | core and admin commands | `_add_ask_parser` (944-1340, 397 lines) and 24 small helpers |
| 1917-2843 | review family | `review`, external parsers, `review-pr`, `review-local`, `_add_review_queue_parser` (2138-2710, 573 lines), `codebase-audit`, `badge` |
| 2846-3717 | platform and decision commands | 41 helpers, including `_add_decide_parser` (151), `_add_plans_parser` (105), `_add_self_improve_parser` (105), and `_add_agent_parser` with its handler `cmd_agent_run` (3422-3519) |
| 3720-4791 | automation | `_add_codex_parser` (281), `_add_factory_parser` (72), `_add_swarm_parser` (4077-4723, 647 lines), `tasks`, `ralph` |
| 4794-5363 | ideation | `assess`, `spec`, `crux`, `crux-followup`, `build`, `_add_idea_parser` (210), `essay` |

The parser registers 111 top-level choices: 110 commands plus the `xpoll`
alias. It makes 97 `_lazy(...)` calls. No `_add_*` helper calls another
helper. The helpers read only these module-level names: `_lazy` (60 helpers),
`argparse` (20), the six `DEFAULT_*` constants (seven helpers), `os` (only
`_add_ask_parser`, for `ARAGORA_ASK_TIMEOUT_SECONDS` at line 1271) and
`cmd_agent_run` (only `_add_agent_parser`).

Precedent: `aragora/cli/_mission_parser.py` (116 lines) was extracted earlier
"to keep that module under its LOC ratchet". It receives `_lazy` as an argument
and is already registered as Tier 4.

Consumers:

- 92 `from aragora.cli.parser import build_parser` statements in 35 files:
  32 test files, `aragora/cli/main.py` (line 194, inside a function),
  `scripts/generate_cli_reference.py` and `scripts/generate_capability_matrix.py`.
- `aragora/cli/main.py:56-57` lists `build_parser` and `get_version` in
  `_LAZY_REEXPORTS`.
- `tests/cli/test_cli_main.py` imports the module as `cli_parser`, calls
  `cli_parser._add_plans_parser(subparsers)` at line 332, and patches
  `aragora.cli.parser.build_parser` at lines 609 and 683.
  `tests/cli/test_status_validate_env.py` also imports the module object.
- No test or module patches `_lazy`, the `DEFAULT_*` constants or any helper,
  and nothing reloads the module.

## 3. Invariants every split PR must hold

**P1. One public import path.** `aragora.cli.parser` keeps every name it has
today: `build_parser`, `get_version`, `_lazy`, `CORE_COMMANDS`,
`_GroupedCommandsParser`, the six `DEFAULT_*` names, `add_mission_parser`,
`cmd_agent_run` and all 98 `_add_*` helpers. The facade imports each moved
helper by name, so `parser._add_x_parser is _parser_<group>._add_x_parser`.
Names the facade no longer uses itself are re-exported with the redundant
alias form (`from m import name as name`), which ruff and mypy treat as an
explicit re-export. No name is removed.

**P2. `build_parser` stays in the facade, unchanged in order.** It keeps every
registration call, in the same order, as a bare-name call whose first argument
is `subparsers`. Three consumers depend on this:

- `scripts/generate_cli_reference.py` walks `top._choices_actions`
  (`_extract_commands`, lines 55-77), so registration order is the order of
  `docs/CLI_REFERENCE.md`. CI runs `--check`, which compares the file byte for
  byte (`test.yml:157`, `docs-build.yml:116`, `capability-gap.yml:89`).
- `scripts/generate_capability_matrix.py::_count_cli_commands_static`
  (lines 76-112) parses the source of `parser.py` and looks up `build_parser`
  among its top-level functions. If it is not defined there, the count is 0
  (lines 88-90). It then counts only calls in `build_parser` of the form
  `name(subparsers, ...)`. It finds each helper either as a function in
  `parser.py` or through a `from <module> import <name>` statement that it
  resolves by reading source (`_find_imported_helper`, lines 115-133). It does
  not follow `module.attr(...)` calls, and it counts a delegate helper as one
  command. So each moved helper is from-imported by name and called directly
  from `build_parser`; no group-level "register everything" wrapper is
  introduced. `tests/scripts/test_generate_capability_matrix.py::test_static_cli_count_matches_runtime_parser`
  asserts static count == runtime count (111 == 111 today), and
  `scripts/check_capability_matrix_sync.py` runs in the same three workflows.

**P3. Tier-4 registration and the authority closure.** At this commit:

- `aragora/cli/parser.py` is a member of the Contract Drift Governance
  authority closure. Building the manifest at the design head with
  `generate_contract_drift_inventory.build_authority_manifest` gives 126
  members, and `parser.py` is reached from `aragora/cli/main.py` and
  `scripts/generate_capability_matrix.py`. `aragora/cli/_mission_parser.py` is
  a member only because `parser.py` imports it at module level.
- The closure scan reads function bodies only for executable members.
  `parser.py` is not one, so its function-local imports stay outside the
  closure; its module-level imports are inside it.
- A new path such as `aragora/cli/_parser_review.py` classifies as Tier 2
  (`_classify_model_review_tier` returns `(2, "tier_2_live_automation", ...)`),
  because `TIER_4_PREFIXES` lists files exactly, not by glob.
- `tests/governance/test_contract_drift_measurement_authority_tier.py::test_quorum_evidence_module_imports_do_not_resolve_below_tier4`
  (lines 316-391) fails if a closure member imports, at module level, a path
  that is outside the closure, below Tier 4, or matched by a different rule in
  the merge-train mirror.

Rule: the PR that creates a new registration module adds that path, in sorted
position, to `CONTRACT_DRIFT_AUTHORITY_DEPENDENCY_PREFIXES`
(`review_queue.py:263`, a single line under `# fmt: off`) and to its mirror in
`scripts/tier4_merge_train.py` (tuple starting at line 440). That one entry
per tuple is enough: `TIER_4_PREFIXES` unpacks the dependency tuple
(`review_queue.py:269`), and the merge train splices the same tuple into
`SERIALIZED_TIER4_PREFIXES` (`tier4_merge_train.py:550-554`). A local probe
that inserts `aragora/cli/_parser_review.py` into a copy of the tuple
classifies that path as `(4, "tier_4_preapproval_required")`. This adds entries
to an existing tuple; it does not change any matcher or classification rule.

The registration modules stay Tier 4 for the same reason `parser.py` is: they
are the registration surface. The closure test enforces this automatically,
because `parser.py` imports every one of them at module level (P4).

Coordination: the review_queue split edits the same single-line tuple. Steps
of the two splits that add entries never run at the same time; each rebases
on the other.

**P4. Module-level imports stay light.** Each registration module imports at
module level only `argparse`, `os` (where `_add_ask_parser` needs it), names
from `aragora.config` (already a closure member) and the shared leaf module
from step 2. Every import a moved helper makes today inside its body stays
inside its body. A module-level import of any other repository module would
pull that module into the authority closure and fail the closure test unless
it is also Tier 4, and it would also defeat the lazy CLI. The existing guards
are the five tests in `tests/cli/test_parser_lazy_review_pr.py` (review-pr,
triage status, and three review-queue cases, which also assert
`args.func.__name__ == "cmd_review_queue"`), and step 1 adds a stricter one
(§6, C-4).

**P5. Shared names move to one leaf module.** The moved helpers need `_lazy`
and the `DEFAULT_*` constants. They cannot import them from `parser.py`,
because `parser.py` imports the registration modules at module level and that
would be an import cycle. Step 2 therefore moves `_lazy`,
`DEFAULT_CAMPAIGN_MANIFEST`, `DEFAULT_API_URL` and `DEFAULT_API_KEY` byte for
byte into `aragora/cli/_parser_common.py`, and the facade re-exports them. The
two environment reads still run once, when `parser.py` is first imported,
because the facade imports the leaf at module level. `DEFAULT_AGENTS`,
`DEFAULT_CONSENSUS` and `DEFAULT_ROUNDS` keep coming from `aragora.config`.

The only observable difference of this move is `__module__` on the wrappers
that `_lazy` returns: it becomes `aragora.cli._parser_common`. Their
`__name__` and `__qualname__` are set explicitly and do not change. Nothing
reads `__module__` of `args.func` today: `main.py` only calls
`args.func(args)` (lines 177 and 219), and the lazy tests read `__name__`.

**P6. File-size ratchet.** `scripts/ci/check_file_sizes.py` fails any new
`aragora/**/*.py` file over 2,000 lines that is not in
`scripts/baselines/file_size_baseline.json`. The `parser.py` entry is 5,372;
the file is 5,363. Every new module stays under 2,000 lines. The last step
shrinks the baseline (`--freeze` is shrink-only) and removes the entry once the
facade is under 2,000 lines.

**P7. The review-queue registration keeps today's divergence.**
`_add_review_queue_parser` (parser.py) and `add_review_queue_parser`
(review_queue.py) register the same 14 subcommands. Seven of them (`act`,
`build`, `conductor`, `evidence-lint`, `lint-comment`, `merge-packet`,
`packet`) differ only in the `--json` destination: `json_output` here, `json`
in the standalone parser. Handlers read both. The move keeps both exactly as
they are, and `tests/cli/commands/test_review_queue_parser_parity.py` stays
green. `_add_review_queue_parser` keeps its function-local import of
`review_queue_parsers.add_record_settlement_parser` (line 2254).

**P8. Handlers stay put.** `cmd_agent_run` (3483-3519) is a command handler
that happens to live in `parser.py`, bound directly by `_add_agent_parser`.
Both stay in the facade; moving a handler is outside a registration split.

**P9. CODEOWNERS is out of scope.** `.github/CODEOWNERS:84` pins only
`/aragora/cli/commands/review_queue*.py`. There is no entry for `parser.py` or
`_mission_parser.py` today, and the split does not add one. Whether the
registration surface should get an owner pin is an operator choice for a
separate Tier-1 PR (§10).

## 4. Target modules

| Step | Module | Helpers moved | Approx. lines | Largest helper |
|---|---|---|---|---|
| 2 | `_parser_common.py` | `_lazy`, three `DEFAULT_*` constants | 30 | - |
| 3 | `_parser_admin.py` | `doctor`, `validate`, `validate-env`, `improve`, `context`, `serve`, `init`, `setup`, `backup`, `repl`, `config`, `api-key`, `secrets` (13) | 420 | `improve` 101 |
| 4 | `_parser_decision.py` | `decide`, `plans`, `quickstart`, `receipt`, `compliance`, `publish`, `autopilot`, `outcome`, `explain`, `consensus` (10) | 330 | `decide` 151 |
| 5 | `_parser_platform.py` | the remaining 30 platform helpers from lines 2846-3717 except `_add_agent_parser` | 470 | `self-improve` 105 |
| 6 | `_parser_ideation.py` | `assess`, `spec`, `build`, `idea`, `essay` (5) | 460 | `idea` 210 |
| 7 | `_parser_epistemic.py` | the 13 AGT/DIC operator helpers plus `crux` and `crux-followup` (15) | 830 | `calibration` 119 |
| 8 | `_parser_core.py` | `ask`, `stats`, `status`, `agents`, `modes`, `patterns`, `demo`, `inbox-wedge`, `templates`, `export`, `replay`, `bench` (12) | 580 | `ask` 397 |
| 9 | `_parser_automation.py` | `codex`, `factory`, `swarm`, `tasks`, `ralph` (5) | 1,090 | `swarm` 647 |
| 10 | `_parser_review.py` | `review`, external parsers, `review-pr`, `review-local`, `review-queue`, `codebase-audit`, `badge` (7) | 940 | `review-queue` 573 |

All modules live flat in `aragora/cli/`, next to `_mission_parser.py`. A
package directory would need a new directory-prefix rule in the dependency
tuple, which today lists only files.

The facade keeps lines 1-235 (minus the moved names), `_add_agent_parser`,
`cmd_agent_run` and the import block for the moved helpers (one name per line
after `ruff format`). That comes to about 460 lines.

Approximate sizes are derived from the line ranges. Each step PR states the
measured sizes at its own base.

## 5. Migration order

One Tier-4 PR per step, one open step at a time. Each step edits the facade's
import block and `build_parser` stays untouched, so steps never run in
parallel.

| Step | Content | Gate |
|---|---|---|
| 0 | This design, then operator preapproval | Tier 0 doc; preapproval recorded by the operator |
| 1 | Characterization tests only (§6, C-1 to C-4), no production code | `tests/` only, so it classifies Tier 0, but it runs only after preapproval because it is part of the approved plan |
| 2 | `_parser_common.py` leaf | Tier 4, exact-head settlement |
| 3-10 | One registration module per PR, in the order of §4 (subdivided if the size decision below requires it) | Tier 4, exact-head settlement per PR |
| 11 | Shrink or remove the `parser.py` entry in `file_size_baseline.json` | computed tier, normally after step 10 |

The order moves small, low-traffic groups first to prove the import, closure
and counter discipline. The two groups that hold the operator surfaces go
last: automation (swarm, codex, factory) and then review, which holds the
merge-authority `review-queue` registration.

Each step PR contains only:

1. The moved helpers, byte-identical.
2. The facade import lines for every moved name, and the removal of the moved
   definitions.
3. For a new module, the two dependency-tuple entries from P3.

The PR description includes an AST comparison of every moved function before
and after the move. Any other difference disqualifies the PR as a split step.

### PR size and the 800-line cap

Mission PRs are capped at 800 changed lines, as measured by
`git diff --numstat origin/main...HEAD` with deleted lines counted. A move
counts twice. All steps together move about 4,830 lines, about 9,700 changed
lines. Two helpers exceed the cap on their own as pure moves:

- `_add_swarm_parser`: 647 lines, about 1,300 changed lines
- `_add_review_queue_parser`: 573 lines, about 1,150 changed lines

`_add_ask_parser` (397 lines) is at the edge. Moved alone into an existing
module, it measures about 800 changed lines.

The operator decides at preapproval:

- **(a) Pure-move exception (recommended).** A step PR may exceed 800 changed
  lines only by moved lines. The PR proves this with the AST comparison above,
  and every other line counts against the cap. The steps in §4 apply as
  written, and the facade ends at about 460 lines.
- **(b) No exception.** Steps are subdivided to fit 800 changed lines. A
  packing estimate from the helper sizes gives about 15 Tier-4 PRs instead of
  9, because most groups need two or three PRs once blank lines, imports and
  the module header are counted. The swarm and review-queue helpers stay in
  the facade, and `_add_ask_parser` moves alone into `_parser_core.py` after
  that module exists. The facade then ends at about 1,700 lines, under the
  ratchet. If the measured `ask` PR exceeds 800 changed lines, `ask` stays too,
  the facade ends at about 2,080 lines, and the baseline entry stays, shrunk.

### Overlap census before each step

Before a step opens, its lane re-runs the open-PR overlap census (§11). A step
does not start while another open PR touches the helpers it moves, unless that
PR's owner agrees to rebase afterwards. At 2026-10-07T04:27Z, these open PRs
touched `aragora/cli/parser.py`: #10377 (draft), #10057 and #9697.

## 6. Test strategy

**C-1 Public surface.** A fixture records the sorted non-dunder names of
`dir(aragora.cli.parser)` at the step-1 base, leaving out module objects
(`argparse`, `os`). Every step asserts that no name is missing and that each
moved name is the same object as in its module.

**C-2 Parser tree.** A golden JSON dump of the whole parser built by
`build_parser()`: for every parser and subparser, recursively, the action
list in order with `option_strings`, `dest`, `default`, `type` name,
`choices`, `nargs`, `required`, `help`, `metavar`, and for each leaf the
`func.__name__` from `set_defaults`. Top-level choices are recorded in
`_choices_actions` order with their aliases. Five defaults are read from the
environment once, at import: `DEFAULT_API_URL` and `DEFAULT_API_KEY`
(`parser.py:17-18`) and `DEFAULT_ROUNDS`, `DEFAULT_CONSENSUS` and
`DEFAULT_AGENTS` (`aragora/config/legacy.py:267-269,318`). An in-process
`monkeypatch.setenv` does not reach them when an earlier test in the same
pytest process already imported the module. The test therefore builds the dump
in a fresh subprocess, as C-4 does, with `ARAGORA_API_URL`, `ARAGORA_API_KEY`,
`ARAGORA_DEFAULT_ROUNDS`, `ARAGORA_DEFAULT_CONSENSUS`,
`ARAGORA_DEFAULT_AGENTS` and `ARAGORA_ASK_TIMEOUT_SECONDS` (read when
`build_parser()` runs) pinned in the child environment. Each step must keep
the dump byte-equal.

**C-3 Help text.** `format_help()` of the root parser (core and advanced
sections) and of every top-level command stays byte-identical.
`generate_cli_reference.py --check` and the capability-matrix tests (P2) stay
green.

**C-4 Import footprint.** In a fresh subprocess, `import aragora.cli.parser`
followed by `build_parser()` records the set of loaded `aragora.*` modules.
Each step asserts that the set equals the step-1 set plus the registration
modules created so far. This catches a handler import that slipped to module
level, which the five targeted lazy tests (P4) would miss for other commands.

Per-step run set:

- `tests/cli/` (it holds the parser tests, the lazy tests and C-1 to C-4)
- `tests/cli/commands/test_review_queue_parser_parity.py`
- `tests/scripts/test_generate_capability_matrix.py`
- `tests/governance/test_contract_drift_measurement_authority_tier.py`
- `tests/scripts/test_tier4_merge_train.py`
- `python3 scripts/generate_cli_reference.py --check` and
  `python3 scripts/check_capability_matrix_sync.py`
- `make lint` and the format check

Step 1 adds C-1, C-2 and C-4 (C-3 extends existing checks) and changes nothing
else.

## 7. Rollback

Every step is a move plus imports, so a revert of the step PR restores the
previous state exactly. The dependency-tuple entries revert in the same commit.
No command, argument, data or receipt format changes, so nothing needs
migrating back.

## 8. Relation to the review_queue split

- Shared edit point: the dependency tuple and its merge-train mirror (P3).
- `_add_review_queue_parser` here and `add_review_queue_parser` in
  `review_queue.py` are separate code. The review_queue design moves the
  latter into `review_queue_parsers.py`; this design moves the former into
  `_parser_review.py`. Neither unifies them (P7).
- `tests/cli/test_parser_lazy_review_pr.py` guards both designs: the
  `review-queue` registration must not import the review_queue facade.

## 9. Open decisions for the operator

These are choices, not proposals for this split:

- The PR-size option in §5.
- Whether to add a CODEOWNERS pin for `parser.py`, `_mission_parser.py` and
  `_parser_*.py` in a separate Tier-1 PR (P9).
- Whether to unify the two review-queue registrations later, as its own
  behavior-change PR (P7).

## 10. Preapproval checklist for the operator

- [ ] Module boundaries and order in §4 and §5
- [ ] PR size: (a) pure-move exception to the 800-line cap, or (b) no exception (§5)
- [ ] Leaf module rule P5 (`_parser_common.py`) and re-export rule P1
- [ ] Registration rule P3: dependency-tuple entries added in each step PR, sequenced with the review_queue split
- [ ] Handlers, the review-queue `--json` divergence and CODEOWNERS left unchanged (P7-P9)

## 11. Reproduction

```bash
# Line counts and structure
wc -l aragora/cli/parser.py aragora/cli/_mission_parser.py
rg -n "^def |^class " aragora/cli/parser.py

# Tier of a candidate new module path (expect 2 today)
python3 -c "from aragora.cli.commands import review_queue as rq; \
print(rq._classify_model_review_tier(['aragora/cli/_parser_review.py']))"

# Runtime and static command counts (expect 111 and 111)
PYTHONPATH=. python3 -c "import sys; sys.path.insert(0, 'scripts'); \
import generate_capability_matrix as g; from pathlib import Path; r = Path('.').resolve(); \
print(g._count_cli_commands(r), g._count_cli_commands_static(r))"

# Consumers
rg -c "from aragora\.cli\.parser import build_parser" tests aragora scripts
rg -n "cli_parser\.|aragora\.cli\.parser\.[A-Za-z_]+" tests

# CLI reference and capability matrix checks
python3 scripts/generate_cli_reference.py --check
python3 scripts/check_capability_matrix_sync.py

# Open-PR overlap census (filenames only)
gh pr list --repo synaptent/aragora --state open --limit 200 --json number,files \
  --jq '.[] | select(any(.files[]; .path == "aragora/cli/parser.py" or (.path | startswith("aragora/cli/_parser_")))) | .number'

# File-size ratchet
python3 scripts/ci/check_file_sizes.py --json
```
