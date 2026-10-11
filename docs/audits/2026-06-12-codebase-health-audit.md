# Codebase Health Audit — 2026-06-12

**Head:** `a5cf5fc70b` | **Epic:** #8257 | **Program plan:** [`docs/superpowers/plans/2026-06-12-codebase-health-program.md`](../superpowers/plans/2026-06-12-codebase-health-program.md) | **Machine-readable baseline:** [`2026-06-12-codebase-health-baseline.json`](2026-06-12-codebase-health-baseline.json)

## Method

Three independent measured passes against the working tree at head, conducted 2026-06-12:

1. **Architecture & code quality** — scale measurement, god-file census, import-layering analysis, five-file quality sampling, redundancy scan, lint/type-config review.
2. **Tests & CI reality** — claim verification against `docs/METRICS.md`, three-file test-quality sampling, skip-density count, full workflow inventory, canceller-config review.
3. **External utility** — packaging review, onboarding-path walkthrough, interface census, differentiation analysis vs. comparable OSS.

Every headline number is reproducible: the exact command for each lives in the baseline JSON. Where this document and the baseline disagree, **the baseline command is authoritative** (narrative numbers from the assessment passes occasionally used slightly different filters).

## Scorecard

| Dimension | Score | One-line evidence |
|---|---|---|
| File-level code quality | 8/10 | Sampled modules typed, documented, pattern-consistent (`rbac/checker.py`, `config/settings.py`, `gauntlet/receipt_models.py`) |
| Macro-architecture | 4/10 | `server/` = 475K LOC imported by 180 outside files; 155 circular-workaround files; duplicate subsystems |
| Test suite | 7/10 | 220,821 test functions, claims verified to 0.2%; real assertions; ~73% of files mock-reliant |
| CI & governance | 7/10 | 86 workflows; ratchets/quorum genuinely work; canceller masks failures; process weight high |
| Packaging & onboarding | 3/10 | 3 PyPI names, 0 console entry points, INSTALL.md contradicts pyproject |
| Differentiation | 9/10 | Signed receipts + dissent + calibration from adversarial debate; no OSS comparable ships this layer |

**Verdict:** file-level quality is genuinely good and the governance machinery (quorum, drift ratchets, receipts, evidence loops) measurably works. The machinery was never pointed at macro-architecture, packaging, or the outsider's first hour. The remediation program points the repo's own proven shrink-only-baseline pattern at exactly those three surfaces.

---

## Finding 1 — Layering: the delivery layer is a de facto shared library

**Issue:** #8259 (Wave 1) | **Baseline keys:** `server_import_outside`, `type_checking_files`, `circular_mention_files`, `loc_server`, `mutual_import_cycles`, `server_imported_by`, `handlers_flat_root`

- `aragora/server/` is 475,621 LOC, 24.4% of the package (1,031 files).
- **180 files outside `server/` import `aragora.server`.** Worst case is top-level in the core engine: `aragora/debate/orchestrator.py:40` does `from aragora.server.metrics import ACTIVE_DEBATES`.
- `aragora/core/decision_router.py` lazily imports `aragora.server.documents` and `aragora.server.decision_integrity_utils` inside functions as an explicit circular workaround.
- 910 files (~22%) need `if TYPE_CHECKING:` guards; 155 files carry circular-import mentions. There is no enforced layering: the intended core → debate → delivery direction is violated and nothing stops new violations.
- **Graph metrics now pinned (P0):** `scripts/ci/measure_import_graph.py` (grimp, with TYPE_CHECKING-guarded imports excluded — they are type-only and not runtime cycles) pins the three previously-unmeasured numbers into the baseline JSON under the update-BOTH rule: mutual import cycles (140; 183 if TYPE_CHECKING imports are included), distinct top-level packages importing `aragora.server` (48), and flat handler files in `aragora/server/handlers/` (187, cross-checked against `ls aragora/server/handlers/*.py | wc -l`). The cycle count is ratcheted shrink-only via `measure_import_graph.py --check` against `scripts/baselines/import_cycles_baseline.json` (any growth fails). Targets: cycles <30, `server` imported-by <=5, handlers flat-root <20 (P4b).

**Remediation:** freeze the offender list as a shrink-only CI baseline (the `tests/server/test_route_collisions.py` pattern: new entries fail, resolved-but-not-removed entries fail). First substantive shrink: move `ACTIVE_DEBATES` and sibling metrics to `aragora/observability/`, re-export from `server.metrics` for compat.

**Definition of done:** baseline test green in CI; `debate/orchestrator.py` has no module-level `aragora.server` import; `server_import_outside` strictly decreases.

## Finding 2 — Gate rigor: quality rests on convention, not gates

**Issue:** #8261 (Wave 2) | **Baseline keys:** `mypy_check_untyped_defs_packages`, `ruff_strict_enrolled_packages`

- mypy config: `ignore_missing_imports=true`, `follow_imports="silent"`, `check_untyped_defs=false` — untyped function bodies are never type-checked anywhere.
- ruff: per-file-ignores neutralize `BLE001` (blind except) and `G004` (f-string logging) for the entire `aragora/*` tree; `E402`/`E501` ignored globally. The effective gate is roughly pyflakes plus basic pycodestyle.
- The irony: sampled code is well-typed anyway (`rbac/checker.py` 1,216 lines fully annotated; `config/settings.py` pydantic-settings with constraints), so ratcheting is cheap — the gates lag the code.
- Precedent exists: the mypy-baseline-ratchet workflow already enforces a no-regression floor.

**Remediation:** per-package enrollment lists that can only grow — enrolled packages get `check_untyped_defs=true` and lose the `BLE001`/`G004` ignores. Seed with 3 verified-clean packages.

- **Enrollment seeded (P6):** `mypy_check_untyped_defs_packages` 0 → 7 and `ruff_strict_enrolled_packages` 0 → 7. A grow-only `[[tool.mypy.overrides]]` entry in `pyproject.toml` sets `check_untyped_defs = true` for `aragora.caching`, `aragora.events`, `aragora.protocols`, `aragora.resilience`, `aragora.shared`, `aragora.types` and `aragora.utils` (foundation and infrastructure layers). Measured on origin/main `66c804cb4f`: each package has zero `.mypy-baseline` entries, no `BLE001`/`G004` per-file-ignores (the package-wide ignore was removed in #10491), and no `check_untyped_defs` errors under mypy 2.1.0 and 2.4.0 in both the CI changed-file form (`--follow-imports=skip`) and the full-tree form. Of the other 68 packages without baseline entries or carve-outs, 67 were also clean; `aragora/audit/exploration/memory.py` has 2 errors.

## Finding 3 — Duplicate subsystems

**Issue:** #8264 (Wave 3) | **Related:** #8259 baseline

- `aragora/telemetry/` is a pure re-export shim of `aragora/observability/` (~50 names, zero logic).
- Two streaming homes: `aragora/streaming/` and `aragora/connectors/enterprise/streaming/` (acknowledged in CLAUDE.md itself).
- Three memory surfaces — `memory/`, `knowledge/`, supermemory (referenced in ~50 files) — bridged ad hoc despite `MemoryGateway` existing exactly for unified access.
- Vocabulary collision: `aragora/routing/` (provider routing, 13 modules) vs `aragora/core/decision_router.py` + `core/routing_rules.py` (decision routing).
- Cause: breadth-first autonomous growth — each loop iteration added a module rather than refactoring one. Same pattern at file scale: `debate/orchestrator.py` (1,270 lines) fronts 14 `orchestrator_*.py` siblings totaling ~7,900 LOC — a god class decomposed by file-splitting, not abstraction. Largest files: `cli/parser.py` 5,316; `swarm/boss_loop.py` 5,178; `cli/commands/review_queue.py` 5,113.

## Finding 4 — Tests: substance with a depth caveat

**No issue (healthy).** | **Baseline keys:** `test_fns`, `test_files_py`, `mock_test_files`, `tests_collect_total`

- `docs/METRICS.md` claims verified within 0.2% (220,821 measured test functions; metrics pipeline is auto-generated, CI-checked by `metrics-drift.yml`, with anti-self-reference invariant tests).
- Skip/xfail density ~1% of files. Flaky-retry plugin explicitly disabled (`-p no:rerunfailures`) — an anti-flake-masking choice.
- Sampled tests assert real semantics: `tests/server/test_route_collisions.py` enumerates the live handler registry with a frozen shrink-only baseline; `tests/debate/test_consensus.py` asserts exact computed values; `tests/gauntlet/test_crux_receipt.py` asserts checksum stability and single-field mutation sensitivity.
- Caveats: ~73% of test files are mock-reliant; only ~750 parametrize decorators across 220K functions — the headline count overstates depth.
- **Collection floor pinned (P1):** `tests_collect_total` = 228385 (`PYTHONPATH=.:aragora-debate/src python3 -m pytest --collect-only -q tests/`, measured on origin/main `f9e49d9336`, rc=0, no collection errors) records the pre-migration pytest collection total under the update-BOTH rule. The P1 tests-root→subdir migration is rename-only, so the collect-only total must never drop below this floor (VAL-P1-009 path B).

## Finding 5 — CI: real governance, real weight, one real bug

**Issue:** #8265 (Wave 3, prepare/park — workflows are approval-required) | **Baseline keys:** `workflows`, `cancel_in_progress_workflows`

- 86 workflows including genuinely novel gates: merge quorum (+retrigger), admission controller, metrics/module-tier/contract drift, docs consistency, mypy ratchet, SDK parity, release readiness, self-dogfooding review lanes.
- **The canceller masks real failures.** Live case (2026-06-12): on PR #8220, `Tests` and `Contract Drift Governance` sat terminal-`cancelled` and only surfaced as FAILED on attempt 2 after manual rerun. Mechanism documented in `docs/governance/PR_RUN_CANCELLATION_DIAGNOSIS.md`. Cancelled governance-relevant runs on ready PRs must never be terminal.
- Overlapping/legacy lanes inflate the count; target ≥15% reduction via a keep/merge/delete inventory.

## Finding 6 — Security defaults caught by the repo's own evidence loop

**Issue:** #8260 (Wave 1, Tier 3 park) | **Source:** two-family review evidence for PR #8163 (`.aragora/prepared-evidence/pr-8163.json`)

- `aragora/server/handlers/metrics/handler.py` (~124-148): with `ARAGORA_METRICS_TOKEN` unset, `/metrics` is fully public (only rate-limited) — agent performance and tenant tier breakdowns world-readable.
- `aragora/server/handlers/auth/handler.py` (~920-945): `POST /api/auth/revoke` gates on `session.revoke` and revokes **any** token in the request body without caller-ownership verification — a session-DoS primitive for any `session.revoke` holder.

**Remediation:** fail closed without the token (explicit dev opt-out env + startup warning); ownership check or distinct admin permission for arbitrary-token revocation.

## Finding 7 — Packaging: the first thing an outsider verifies is broken

**Issue:** #8263 (Wave 3, decision-gated) | **Baseline keys:** `pypi_names`, `console_entry_points`

- Root `pyproject.toml` builds **`aragora-debate`** v2.9.0 shipping only `aragora`, `aragora.core`, `aragora.debate` — no `[project.scripts]`, no CLI, no server.
- `INSTALL.md` documents `pip install -e .` then `aragora serve` — impossible with the built package.
- Three PyPI names in play: `aragora` (README badge), `aragora-debate` (root build), `aragora-sdk` (`sdk/python`).
- The wedge itself is reachable: zero-key mock-agent demo produces an actual receipt in <5 minutes; one key gives the real-model path. The packaging contradiction is what erodes trust before a user gets there.
- **Decision gate:** run an Aragora debate (dogfood) on one-name-full-package vs. minimal-wedge-split (receipts + offline verifier, aligning with ODR-3 #8226) and attach the decision receipt to #8263 before implementing.

## Finding 8 — Docs: volume without a canonical path

**Issue:** #8262 (Wave 2) | **Baseline keys:** `docs_md`, `selfhost_guides`

- 925 markdown files under `docs/`; 5 self-hosting guides; quickstart health-check pins `"version": "2.6.3"` against a 2.9.0 package; `INSTALL.md` shows 4 API keys where the quickstart needs 1 (and a zero-key demo exists).
- Remediation: one canonical quickstart + one self-hosting guide, rest archived with redirect stubs; version strings covered by the existing Version Alignment / Docs Consistency checks so drift fails CI.

## Finding 9 — Repo-root hygiene

**Issue:** #8258 (Wave 1) | **Baseline key:** `root_clutter`

11 non-project files at repo root (10 unrelated game screenshots + a strategy `.docx`), plus research markdown. Trivial fix, outsized first-impression payoff.

---

## What is genuinely strong (do not break)

- **The differentiated wedge:** cryptographically signed decision receipts with dissent trails, per-domain ELO/Brier calibration, and hollow-consensus detection from heterogeneous-model adversarial debate. AutoGen/CrewAI/LangGraph orchestrate; Guardrails checks outputs; nothing comparable ships this governance/audit layer. The ODR program (#8223) is productizing it — it has right-of-way over this program on any conflict.
- **The metrics pipeline:** self-checking, drift-gated, accurate to 0.2% — the model every claim in this audit follows.
- **The evidence loop:** Finding 6 was produced by the repo's own two-family review machinery, which is the strongest possible argument for it.

## How future sessions use this document

1. **Re-measure** any number with its pinned command from the baseline JSON (repo root). The baseline is the source of truth; this narrative explains why each number matters.
2. **Claim work** through the program plan's wave structure and the epic's sequencing rules — never from this document directly. Check `.aragora/run-20260610/lanes/` (or the current run's registry) and the steering mailbox first, per `AGENTS.md`.
3. **Ratchet, don't aspire:** every fix that can be expressed as a shrink-only or grow-only baseline check should be (HEALTH-2 and HEALTH-4 build the harnesses). A finding without a falsifiable definition of done is not done.
4. **Honor right-of-way:** the ODR program (`docs/superpowers/plans/2026-06-11-odr-program.md`) owns gauntlet/receipt surfaces while in flight.
