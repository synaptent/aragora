# P5: `aragora/cli/commands/review_queue.py` split design (Tier 4)

Status: design and Tier-4 preapproval artifact. This is not an
implementation, and merging it authorizes nothing. Measured on `origin/main`
at `d4c9f6c7d5` (2026-10-07). Every count below came from a command in §11 or
from the cited lines at that commit.

`aragora/cli/commands/review_queue.py` is Tier 4 (`TIER_4_PREFIXES`, line
276): it holds the merge-quorum gate that evaluates the PRs that change it.
The split therefore follows the Tier-4 rule:

1. The operator preapproves this design before any implementation PR opens.
2. Each implementation PR is its own Tier-4 PR with exact-head operator
   settlement (`python3 scripts/settle_tier4_pr.py --check --pr <N> --head <SHA>`
   before any merge mutation).
3. A lane may prepare a step, but it parks at the settlement boundary and never
   self-merges.

This document refreshes
`docs/superpowers/plans/2026-06-13-review-queue-decomposition-plan.md`. That
plan was written when the file had about 5,293 lines, before
`review_queue_rest_fallback.py`, `review_queue_render.py`,
`review_queue_unstable.py` and `review_queue_comment_verdicts.py` landed, and
before the Contract Drift Governance (CDG) authority closure existed. Its
guardrails still apply: a pure refactor, characterization tests first, one
cohesive unit per PR, and operator settlement per PR. Where the two documents
disagree, this one is current.

## 1. Goal and non-goals

Goal: split the 5,913-line module into a facade under 2,000 lines plus
cohesive `review_queue_*.py` units, each under 2,000 lines, with no behavior
change. The CLI surface, the packet, quorum, settlement and receipt JSON, the
tier classification and the exit codes all stay identical.

Non-goals:

- No gate-semantic change. This includes the three PR #10039 r2 advisories in
  §8, which this design records as constraints, not as fixes.
- No move of the tier constants, the matcher or the classifier during the
  mechanical split. Moving them is the separately approved step in §7.
- No change to `aragora/cli/parser.py`. It has its own design in
  `docs/architecture/P5_CLI_PARSER_SPLIT_DESIGN.md`.
- No conductor redesign. `review_queue_conductor.py` (1,593 lines, Tier 2,
  imported lazily at line 1083) stays as it is.

## 2. Current shape (measured)

| Lines | Region | Representative symbols |
|---|---|---|
| 1-311 | imports, constants, tier policy | `HIGH_RISK_*`, `TIER_2_PREFIXES`, `TIER_3_*`, CDG constants (259-263), `TIER_4_PREFIXES` (264-300), merge-quorum names (304-306) |
| 314-368 | small helpers, lane constants | `resolve_repo_root`, `LANE_ORDER`, `ADVISORY_NOTE` |
| 371-514 | dataclasses | `QueueItem`, `ReviewPacket`, `SettlementReceipt`, `RecordedSettlementResult` |
| 520-992 | argparse registration | `add_review_queue_parser` (473 lines) |
| 995-1638 | dispatch and command handlers | `cmd_review_queue`, `_cmd_*` |
| 1644-1806 | settlement status post, queue build | `_post_human_settlement_status`, `_build_queue`, `_classify_pr` |
| 1809-2467 | check surfaces | `_summarize_checks`, `_fetch_required_pr_check_surface`, `_summarize_required_pr_checks`, `_rollup_check_matches_required`, `_rollup_non_green_diagnostics`, `_build_check_surface_diagnostics`, `_status_check_identity`, `_is_current_merge_quorum_self_check` |
| 2470-3263 | packets | `_build_packet` (551 lines), `_build_merge_authorization_packet`, `_explicit_merged_pr_merge_packet_entry` |
| 3266-3922 | quorum and tier | `_advisory_settle_review_signals`, `_build_model_review_quorum` (493 lines), `_classify_model_review_tier` (3863-3892), `_tier_requirement` (3895-3922) |
| 3925-4198 | settlement trust | `_has_recorded_*_settlement`, `_trusted_settlement_creator`, `_human_settlement_status_creator_verified`, `_has_tier_four_human_preapproval_comment` |
| 4201-5229 | evidence, reviewer identity, model family | `_lint_evidence_comment`, `_normalize_model_family`, `_resolve_model_review_identity`, `_dissenting_views_from_comments`, `_infer_model_reviewer_from_text` |
| 5232-5312 | path predicates, small parsers | `_matches_prefix`, `_is_docs_tests_or_status_path`, `_is_high_risk_path`, `_parse_pr_number` |
| 5315-5728 | receipts and settle | `_packet_sha`, `_settle_packet`, `_record_external_settlement` |
| 5731-5913 | renderers | `_render_*`, `_fmt_rate` |

Existing siblings (lines, tier): `review_queue_comment_verdicts.py` (418, 4),
`review_queue_conductor.py` (1,593, 2), `review_queue_parsers.py` (136, 4),
`review_queue_render.py` (303, 4), `review_queue_rest_fallback.py` (498, 4),
`review_queue_transport.py` (461, 4), `review_queue_unstable.py` (470, 4).

Consumers: 27 test modules import the module. The eight
`tests/cli/commands/test_review_queue*.py` files hold 11,609 lines. Non-test
importers include `aragora/cli/main.py`, `aragora/cli/parser.py` (lazily),
`aragora/review/*`, `aragora/approvals/settlement_inbox.py`,
`aragora/cli/commands/founder_status.py`, `aragora/triage/event_source.py`,
`aragora/server/handlers/governance/review_queue.py`,
`review_queue_conductor.py`, `review_queue_render.py`,
`review_queue_unstable.py`, `scripts/tier4_merge_train.py`,
`scripts/generate_contract_drift_inventory.py` and
`scripts/build_disagreement_atlas.py`.

## 3. Invariants every split PR must hold

**I1. One public import path.** `aragora.cli.commands.review_queue` keeps every
name that any module or test reads today. The facade re-exports each moved
name, so `review_queue.X is review_queue_<unit>.X`. No name is removed.

**I2. Monkeypatch seams stay effective.** Tests patch names on the facade
module object. At this commit the string targets include
`aragora.cli.commands.review_queue._gh_json` (86 occurrences),
`_fetch_required_pr_check_surface` (14), `_build_packet` (9), `_build_queue`
(8), `_explicit_merged_pr_merge_packet_entry` (7) and
`_build_merge_authorization_packet` (5). Direct `setattr` targets include
`_trusted_settlement_creator` (11), `_human_settlement_status_creator_verified`
(6), `_record_external_settlement` (4), `_require_clean_worktree` and
`_has_successful_status_context`. A plain move breaks these patches without
any error: the moved caller resolves the name in its own module, so the patch
on the facade no longer intercepts the call. A test could then reach live
`gh`, or pass for the wrong reason.

Rule: moved code calls every name in the seam set S through the facade at call
time, using the existing precedent `review_queue_unstable._review_queue_backend()`
(`review_queue_unstable.py:109-113`, a function-local import of the facade).
Names outside S may be imported directly. S is computed by the census command
in §11 at each PR's base, not maintained by hand. Moving patch targets to the
units is a later cleanup and never shares a PR with a move.

**I3. Tier-4 registration and the authority closure.** At this commit:

- A new path such as `aragora/cli/commands/review_queue_checks.py` classifies
  as Tier 2 (`_classify_model_review_tier` returns
  `(2, "tier_2_live_automation", ...)`), because `TIER_4_PREFIXES` lists files
  exactly, not by glob.
- The inventory generator adds every module the classifier loads at runtime to
  the authority closure as `classifier_runtime_import`
  (`scripts/generate_contract_drift_inventory.py:3341-3354`).
- `tests/governance/test_contract_drift_measurement_authority_tier.py::test_quorum_evidence_module_imports_do_not_resolve_below_tier4`
  (lines 316-391) fails if a closure member imports, at module level, a path
  that is outside the closure, below Tier 4, or matched by a different rule than
  the merge-train mirror.
- `test_classifier_and_merge_train_constants_match` (lines 224-247) requires
  `SERIALIZED_TIER4_PREFIXES == TIER_4_PREFIXES` and equal dependency tuples.

Rule: the PR that creates a new `review_queue_<unit>.py` also adds that path,
in sorted position, to `CONTRACT_DRIFT_AUTHORITY_DEPENDENCY_PREFIXES`
(`review_queue.py:263`, a single line under `# fmt: off`) and to its mirror in
`scripts/tier4_merge_train.py` (tuple starting at line 440). Without this, moved
gate code would drop to Tier 2 and the closure test would fail. A step that only
extends an already registered sibling (`review_queue_parsers.py`,
`review_queue_render.py`) needs no new registration. This adds entries to an
existing tuple. It does not change any matcher or classification rule.

**I4. The CODEOWNERS pin follows the code.** `.github/CODEOWNERS:84` pins
`/aragora/cli/commands/review_queue*.py` to `@scarmani`. Every unit is a flat
`review_queue_<unit>.py` file in the same directory. Converting the module into
a `review_queue/` package is rejected: it would escape the glob and break the
`__file__` check in I5.

**I5. Path-keyed and source-text consumers stay valid.**

- `scripts/generate_contract_drift_inventory.py` sets `POLICY_MODULE` and
  `POLICY_PATH` (lines 53-54). Its child process refuses a policy module whose
  `__file__` is not `aragora/cli/commands/review_queue.py` (lines 373-376), and it
  reads `TIER_4_PREFIXES`, `_matches_prefix`, `_classify_model_review_tier` and
  the CDG constants as module attributes (lines 405-471).
- `test_authority_constants_and_tuple_shape_remain_exact` (governance test,
  lines 477-490) parses the source of `review_queue.py` for a literal,
  single-line assignment of `CONTRACT_DRIFT_AUTHORITY_PREFIXES`.
- `scripts/tier4_merge_train.py:64-66` names
  `aragora.cli.commands.review_queue.CONTRACT_DRIFT_AUTHORITY_PREFIXES` as the
  canonical source, and governance test lines 235-238 pin that string.
- The historical-ref governance tests (lines 493-, 554-, 594-) read pinned SHAs
  and are not affected by later moves.

Consequence: during the mechanical split, lines 1-311 (constants and tier
policy), `_classify_model_review_tier`, `_matches_prefix` and
`_is_docs_tests_or_status_path` stay in the facade byte for byte. Only the step
in §7 may move them.

**I6. File-size ratchet.** `scripts/ci/check_file_sizes.py` fails any new
`aragora/**/*.py` file over 2,000 lines that is not in
`scripts/baselines/file_size_baseline.json`. It checks presence only: the listed
`review_queue.py` entry is 5,293 while the file is 5,913. Every unit stays under
2,000 lines. The last step shrinks the baseline (`--freeze` is shrink-only) and
removes the entry once the facade is under 2,000 lines.

**I7. Lazy and light imports.** `aragora/cli/parser.py` registers `review-queue`
without importing the facade (`tests/cli/test_parser_lazy_review_pr.py:73-104`
and the test after it). `parser.py:2254` imports
`review_queue_parsers.add_record_settlement_parser` at registration time, so
`review_queue_parsers.py` stays stdlib-only. Importing the facade must not
eagerly load the helpers blocked in
`tests/cli/commands/test_review_queue_import_boundaries.py`. Units keep heavy
imports function-local, exactly as the moved code has them today.

**I8. Registration parity, including today's divergence.** Both registrations
expose the same 14 subcommands (measured). Seven of them (`act`, `build`,
`conductor`, `evidence-lint`, `lint-comment`, `merge-packet`, `packet`) differ
only in the `--json` destination: `json_output` in `parser.py` and `json` in
`add_review_queue_parser`. The handlers read both, for example
`getattr(args, "json", False) or getattr(args, "json_output", False)` at
`review_queue.py:1044`. Moving `add_review_queue_parser` keeps both
destinations exactly as they are. Unifying them is a behavior change outside
this design. `tests/cli/commands/test_review_queue_parser_parity.py` stays
green.

**I9. Back-imports keep resolving.** `review_queue_conductor.py:21` and
`review_queue_unstable.py` read names from the facade. Those names stay
re-exported.

**I10. No import cycles at module level.** Units import leaf helpers
(`review_queue_transport`, the models unit) at module level and reach the
facade only lazily (I2). The facade imports units at module level. No unit
imports the facade at module level.

## 4. Target modules

| Step | Module | Moves (current lines) | Approx. lines after | New path | Risk |
|---|---|---|---|---|---|
| 2 | `review_queue_models.py` | dataclasses 371-514 | 150 | yes | low |
| 3 | `review_queue_render.py` (existing) | renderers 5731-5913 | 303 -> 490 | no | low |
| 4 | `review_queue_parsers.py` (existing) | `add_review_queue_parser` 520-992 | 136 -> 615 | no | low (parity, I8) |
| 5 | `review_queue_checks.py` | check surfaces 1809-2467 | 660 | yes | medium: gate input; holds P3-2 and part of P3-3 |
| 6 | `review_queue_settlement.py` | 1644-1698, 3925-4198, 5315-5728 | 750 | yes | high: settlement trust and receipts |
| 7 | `review_queue_evidence.py` | 4201-5229 | 1,030 | yes | high: reviewer identity and family recognizer |
| 8 | `review_queue_packet.py` | 1701-1806, 2470-3263 | 900 | yes | high: holds P3-1 and P3-3 |
| 9 | `review_queue_quorum.py` | 3266-3860, `_tier_requirement` 3895-3922 | 630 | yes | highest: the gate core |

The facade keeps lines 1-368 (constants, tier policy, small helpers), the
dispatch block 995-1638, `_classify_model_review_tier`, the path predicates
5232-5312 and the re-export block. That comes to about 1,300 lines, under the
ratchet.

Approximate sizes are derived from the line ranges. Each step PR states the
measured sizes at its own base.

## 5. Migration order

One Tier-4 PR per step, one open step at a time. Each step rebases the facade,
so steps never run in parallel.

| Step | Content | Gate |
|---|---|---|
| 0 | This design, then operator preapproval | Tier 0 doc; preapproval recorded by the operator |
| 1 | Characterization tests only (§6, C-1 to C-4), no production code | `tests/` only, so it classifies Tier 0, but it runs only after preapproval because it is part of the approved plan |
| 2-9 | One unit per PR, in the order of §4 (subdivided if the size decision below requires it) | Tier 4, exact-head settlement per PR |
| 10 | Shrink `file_size_baseline.json`; optional removal of now-unused facade imports | Tier 4 (touches the facade) |
| later | §7 policy-module extraction | separate operator approval, then Tier 4 |

The order moves leaf units first (models, render, parsers) to prove the
re-export, seam (I2) and registration (I3) discipline on low-risk code. The
read-only check surfaces follow, then settlement and evidence, then the packet
builder, and the quorum last.

Each step PR contains only:

1. The moved code, byte-identical except for rewriting calls to S names as
   `_review_queue_backend().<name>(...)`.
2. The facade re-export lines for every moved name.
3. For a new path, the two dependency-tuple entries from I3.

The PR description includes an AST comparison of every moved function before
and after the move, with the seam rewrites listed. Any other difference
disqualifies the PR as a split step.

### PR size and the 800-line cap

Mission PRs are capped at 800 changed lines, as measured by
`git diff --numstat origin/main...HEAD` with deleted lines counted. A move
counts twice: once deleted from the facade and once added to the unit. The
split moves about 4,750 lines (the ranges in §4), which is about 9,500 changed
lines in total.
Under the cap, a unit larger than about 380 lines must land over several PRs,
one cohesive function group per PR. That means at least 12 Tier-4 PRs instead
of the 8 move steps in §4.

Three single functions exceed the cap on their own:

- `_build_packet`: 551 lines, about 1,100 changed lines
- `_build_model_review_quorum`: 493 lines, about 990 changed lines
- `add_review_queue_parser`: 473 lines, about 950 changed lines

Splitting them first would be a restructuring rather than a move, which is
exactly the kind of change this design excludes. The operator therefore
decides at preapproval:

- **(a) Pure-move exception (recommended).** A step PR may exceed 800 changed
  lines only by moved lines. The PR proves this with the AST comparison above,
  and every other line counts against the cap. The steps in §4 apply as
  written.
- **(b) No exception.** Steps are subdivided to fit 800 changed lines. The three
  functions above stay in the facade, so the facade ends at about 2,800 lines
  and keeps its entry in the size baseline. The split's goal is then not met.

### Overlap census before each step

Before a step opens, its lane re-runs the open-PR overlap census (§11). A step
does not start while another open PR touches the lines it moves, unless that
PR's owner agrees to rebase afterwards. At 2026-10-07T04:27Z, these open PRs
touched `review_queue.py`: #10177 (draft), #9992 (draft) and #9011. These
touched `review_queue_unstable.py`: #9512 and #9011.

## 6. Test strategy

**C-1 Public surface.** A fixture records the sorted non-dunder names of
`dir(review_queue)` at the step-1 base. Every step asserts that no name is
missing and that each moved name is the same object as in its unit.

**C-2 Behavior corpus.** Golden JSON (sorted keys) of `ReviewPacket.to_dict()`
from `_build_packet`, of `_build_merge_authorization_packet` and
`_build_model_review_quorum`, and of `_classify_model_review_tier` over every
`TIER_4_PREFIXES` entry plus Tier 0-3 samples. All inputs are mocked GitHub
payloads. The corpus covers the nine `reporting_case` variants in
`tests/cli/commands/test_review_queue.py:232-363`, merged and settled states,
draft, parked label, conflicting merge state, the direct check-run fallback,
REST-fallback metadata, and the five §8 boundary inputs. Each step must keep
the corpus byte-equal. Volatile fields (`generated_at`, `packet_sha`) are
normalized by the test, not by production code.

**C-3 Seams.** An AST test asserts that no unit binds a name in S at import
time (`from ... import <S name>`), and that every moved call to an S name goes
through `_review_queue_backend()`. The existing patch-based tests are the
behavioral proof and must pass unchanged.

**C-4 CLI surface.** The `--help` output of `aragora review-queue` and of every
subcommand, from both registrations, stays byte-identical. The parity test and
the lazy-import tests (I7, I8) stay green.

Per-step run set:

- `tests/cli/commands/test_review_queue*.py`
- `tests/cli/test_parser_lazy_review_pr.py`
- `tests/governance/test_contract_drift_measurement_authority_tier.py`
- `tests/scripts/test_tier4_merge_train.py`
- `tests/scripts/test_generate_contract_drift_inventory.py`
- the 27 importer test modules (§11)
- `make lint` and the format check

Step 1 adds C-1 to C-4 and changes nothing else.

## 7. Deferred: CDG authority tuple into a policy module (separate approval)

Current state: `CONTRACT_DRIFT_AUTHORITY_PREFIXES` is a single-line literal
tuple of 8 authority roots at `review_queue.py:262`, inside the `# fmt: off`
block (lines 261-301). It sits next to `CONTRACT_DRIFT_AUTHORITY_POLICY_VERSION`
(259), `CONTRACT_DRIFT_AUTHORITY_TIER` (260),
`CONTRACT_DRIFT_AUTHORITY_DEPENDENCY_PREFIXES` (263, 105 entries, also a single
line) and `TIER_4_PREFIXES` (264-300, 123 entries). `scripts/tier4_merge_train.py`
mirrors the constants (lines 62-89, and the tuple starting at line 440).

Eventual extraction, after its own operator approval and as its own Tier-4 PR:
move the cohesive tier-policy block into
`aragora/cli/commands/review_queue_tier_policy.py` (the name matches the I4
glob). The block is `HIGH_RISK_*`, `TIER_2_PREFIXES`, `TIER_3_PREFIXES`,
`TIER_3_TITLE_KEYWORDS`, the four CDG constants, `TIER_4_PREFIXES`,
`_matches_prefix`, `_is_docs_tests_or_status_path` and
`_classify_model_review_tier`. That block has no other in-module dependencies.
`_tier_requirement` is quorum policy, not path policy, and moves with the quorum
unit instead. The facade re-exports every moved name.

Must not change:

- The tuple contents and order (8 roots, equal to `EXPECTED_AUTHORITY_PREFIXES`
  in the governance test) and its single-line literal form.
- The order of `TIER_4_PREFIXES` and its equality with `SERIALIZED_TIER4_PREFIXES`.
- Matcher semantics: an exact match, or a prefix match only for legacy
  `TIER_2_PREFIXES` entries and `/`-terminated directories (`review_queue.py:5232-5234`).
- The classification result for every path and title.
- The inventory serialization (`authority_roots`, `authority_tier`,
  `policy_version`, `tier4_prefixes`).
- The CLI parser, dispatch, handlers and settlement.

Must update in the same PR, because these consumers are keyed to the current
location:

- Register `review_queue_tier_policy.py` in both dependency tuples (I3). The
  facade imports it at module level, so it becomes a closure member.
- Repoint `test_authority_constants_and_tuple_shape_remain_exact` from
  `review_queue.py` to the policy file. It parses source text, so a re-export
  does not satisfy it. The historical-ref tests stay as they are.
- Keep the generator's `POLICY_MODULE` and `POLICY_PATH` and the merge-train
  `CONTRACT_DRIFT_AUTHORITY_CANONICAL_SOURCE` pointing at the facade. Attribute
  reads keep working through the re-exports, and the facade file still exists,
  so the generator and the merge train need no change. Repointing them would
  enlarge the authority diff for no behavioral gain.

Status: the extraction is not a current CDG blocker and owns no validation
assertion. This design does not start it. It needs its own operator approval in
addition to the preapproval of the split.

## 8. PR #10039 r2 advisories: design constraints, not fixes

PR #10039 (merged as `bd84a0fdc8`, r2 head `43fede845e`) left three P3 notes
from its Claude review. Their membership, failure and pending assignments were
frozen, and no cure was authorized. This design owns them only as constraints
on the split:

1. The split preserves current behavior exactly.
2. Characterization fixtures pin that behavior before code moves.
3. Any behavioral repair requires a separate operator adjudication and its own
   Tier-4 PR, never inside a move step.

This document does not resolve them. They remain open debt.

The observations below came from mocked `_build_packet` runs using the existing
`in_job_advisory_inputs` fixture (`tests/cli/commands/test_review_queue.py:122-200`)
at `d4c9f6c7d5`. They describe that fixture, not every live PR.

### P3-1: truthful unavailable reason paired with the frozen `approve_candidate` enum

Behavior:

1. `_build_packet` fetches the required PR check surface only when the rollup
   has failures or pending checks, or when the current merge-quorum self-check
   was excluded (lines 2598-2603).
2. If the surface reports `available: False`, the code sets
   `required_has_failures = False` and `required_has_pending = True`
   (2614-2617). It sets `gate_blocked_reason` to "GitHub required PR checks
   surface is unavailable; merge-packet cannot distinguish required checks from
   non-required PR rollup checks." (2693-2697) and leaves the required gate
   unselected (2796-2804).
3. `required_has_pending` is not folded into `has_pending`. When the only
   non-green rollup row was the excluded current merge-quorum self-check,
   `has_failures` and `has_pending` are both false. The recommendation ladder
   (2888-2915) then falls through to `approve_candidate`, and the reason
   becomes that blocker text (2920-2921).

Observed:

- `machine_recommendation = "approve_candidate"`, with the unavailable reason
- `risk_flags = []`
- quorum `status = "needs_model_review_quorum"`,
  `verdict = "collect_model_quorum_before_merge"`
- `admin_squash_allowed = False`

Already pinned by the `unavailable` case of
`test_required_check_reporting_preserves_gate_results` and
`test_required_check_reporting_is_truthful` (lines 284-363).

Split boundary: this code moves in step 8 (`review_queue_packet.py`). C-2 keeps
the full packet and quorum JSON for this input byte-equal.

### P3-2: bare check-name required-membership matching across workflows

Behavior: `_rollup_check_matches_required` (lines 2109-2125) counts a rollup row
as required if its identity (`check-run:<workflow>:<name>` or
`status-context:<name>`, lines 2390-2397) matches a required identity, or if its
bare `name`/`context` equals any required name. A non-required check from
another workflow that shares a required check's name is therefore treated as
required. There are two consumers:

- `_rollup_non_green_diagnostics` (2128-2182) leaves such a check out of
  `non_required_non_green_*` and the runner-noise lists. That in turn removes
  the "non-required PR checks are non-green" reason suffix (2918-2919) and its
  risk flag (2872-2880).
- `review_queue_unstable.py:315-318` declines the cancelled-context path when a
  cancelled check matches a required one. The bare-name match makes that
  refusal broader.

The required-gate selection in `_build_packet` reads the required surface's own
buckets, not this matcher.

Observed, comparing a failing `Optional Shadow Lint / lint` row with a control
row named `shadow-lint`:

- Gate outcomes are identical: required gate selected, quorum `satisfied`,
  `admin_squash_allowed = True`.
- The collision case reports `non_required_non_green_count = 0` and no risk
  flag.
- The control reports a count of 1, the sample, the reason suffix and the risk
  flag.

Not pinned today. Step 1 adds both inputs to C-2.

Split boundary: the matcher moves in step 5 (`review_queue_checks.py`) and must
stay reachable as `review_queue._rollup_check_matches_required`, because
`review_queue_unstable` calls it through the facade backend.

### P3-3: pending rollup with a failed required surface leaves `has_failures` false

Behavior:

1. `has_failures` comes only from the rollup summary (`_summarize_checks`,
   lines 1809-1862).
2. When the rollup still shows a required row in progress while the required
   surface already reports it failed, the rollup gives `has_failures = False`
   and `has_pending = True`. The required surface gives
   `required_has_failures = True` and `required_has_pending = False`.
3. `gate_blocked_reason` becomes "branch-protection required checks are
   failing (...)" (2708-2711).
4. Lines 2737-2746 then clear `has_pending`, because the required surface has no
   pending checks. Nothing sets `has_failures`, so the ladder skips
   `repair_first` and reaches `approve_candidate` with the failing reason.

Observed:

- Skew input: `machine_recommendation = "approve_candidate"`,
  `checks_summary = "1 pending / 6 total"`, `risk_flags = []`, quorum
  `needs_model_review_quorum` / `collect_model_quorum_before_merge`,
  `admin_squash_allowed = False`.
- Control, where both surfaces report the failure: `repair_first`, risk flag
  "checks failing (1 failing / 6 total)", quorum `repair_or_wait` /
  `not_ready_for_settlement`, `admin_squash_allowed = False`.

Not pinned today. Step 1 adds both inputs to C-2.

Split boundary: `_summarize_checks` moves in step 5 and the assignments in step
8. Both keep this behavior.

### What a later adjudication would need to decide (not proposed here)

These are questions for a separate operator adjudication. They are not
proposals.

- Whether a populated `gate_blocked_reason` should change the recommendation
  enum.
- Whether required membership should match on identity only.
- Whether a required-surface failure should set `has_failures`.

Each answer changes gate output and the C-2 fixtures, so it lands as its own
Tier-4 PR, before or after the split, never inside a move step.

## 9. Rollback

Every step is a move plus re-exports, so a revert of the step PR restores the
previous state exactly. The dependency-tuple entries revert in the same commit.
No data, receipts or settlement formats change, so no migration needs undoing.

## 10. Preapproval checklist for the operator

- [ ] Module boundaries and order in §4 and §5
- [ ] PR size: (a) pure-move exception to the 800-line cap, or (b) no exception (§5)
- [ ] Seam rule I2 (facade late binding) instead of moving patch targets
- [ ] Registration rule I3: dependency-tuple entries added in each step PR
- [ ] Policy-module extraction (§7) kept out of the split and approved separately
- [ ] §8 behaviors preserved and pinned; no repair without a separate adjudication

## 11. Reproduction

```bash
# Line counts and structure
wc -l aragora/cli/commands/review_queue*.py tests/cli/commands/test_review_queue*.py
rg -n "^def |^class " aragora/cli/commands/review_queue.py

# Tier of a candidate new unit path (expect 2 today)
python3 -c "from aragora.cli.commands import review_queue as rq; \
print(rq._classify_model_review_tier(['aragora/cli/commands/review_queue_checks.py']))"

# Monkeypatch seam census (string targets and setattr targets)
rg -o --no-filename "aragora\.cli\.commands\.review_queue\.[A-Za-z_]+" tests | sort | uniq -c | sort -rn
rg -U -o --no-filename "setattr\(\s*(rq|review_queue),\s*\"[A-Za-z_]+\"" tests \
  | grep -o '"[A-Za-z_]*"' | sort | uniq -c | sort -rn

# Importer test modules
rg -l "aragora\.cli\.commands\.review_queue\b|from aragora\.cli\.commands import review_queue\b" tests

# Open-PR overlap census (filenames only)
gh pr list --repo synaptent/aragora --state open --limit 200 --json number,files \
  --jq '.[] | select(any(.files[]; .path | startswith("aragora/cli/commands/review_queue"))) | .number'

# File-size ratchet
python3 scripts/ci/check_file_sizes.py --json
```
