# Changelog


## [Unreleased]

_Post-v2.10.0 changes land here until the next stable tag._


## [2.10.0] - 2026-09-04

_1,862 commits on `main` since `v2.9.0` (2026-04-25), counted at the release PR's base `b512e13055`, grouped by conventional-commit type: feat 287, fix 784, docs 321, chore 180, test 88, refactor 63, ci 33, perf 1 (the remaining 105 carry no conventional-commit prefix). This is the first release cut under the Receipt-First mission: the headline is that the dissent-preserving Decision Receipt is now producible, signable and verifiable end to end (`aragora review` → ODR export → Ed25519 signature → `aragora-verify`), and that merge-gate disagreement is published as a dataset (Disagreement Atlas v1). No breaking changes to the public Python API; `aragora/__version__.py` is the single canonical version, `scripts/check_version_alignment.py --fix` fanned it out to every manifest and doc spot it tracks (the tracked set grew during review; `python3 scripts/check_version_alignment.py` lists it). `README.md`, `docs/status/metrics/catalog.toml`, the four npm `package-lock.json` roots (including the `../../sdk/typescript` link entry in `aragora/live`), `uv.lock`, every `aragora==X.Y.Z` install command in `docs/deployment/UPGRADE_ROADMAP.md` and this file's Unreleased line were first aligned by hand and are now in the tracked set too: every spot that states the current version or release date is tracked, so a bump is `aragora/__version__.py` plus `--fix`. Release history (this entry, `### v2.10.0 Behavioral Changes` in the upgrade roadmap, prior release notes) is content and is deliberately untracked. The checker also holds every version-plus-date spot (the `docs/STATUS.md` release line, the `UPGRADE_ROADMAP.md` support matrix) to `RELEASE_DATE`, fails on a tracked pattern or manifest that matches nothing, and keeps the support matrix bounded by folding older `Supported` series into one range row. The release PR also removes the stale `docs/plans/2026-04-30-round-briefing.md` (a round briefing for PRs that merged in April 2026, no inbound references) because the docs page count sits at its ceiling and the new `docs/releases/v2.10.0.md` page must be net-zero._

### Added
- **Open Decision Receipt (ODR) pipeline:** ODR v1.0 contract and quorum→receipt bridge (#8667); in-package verification engine `odr_verify` (#8389); Ed25519 detached signing for ODR exports (#8542) and signing of configured exports (#9080); public signing key served at `/.well-known` and `/api/v2` (#8809); `aragora review` emits ODR receipts (#9343); receipts bind planning evidence in schema 1.3 (#9758); calibration-report endpoint with auditable confidence provenance in receipts (#8290).
- **`aragora-verify` standalone offline verifier** (#8388) with a one-click PyPI publish workflow (#8693) and a post-publish public-install check (#8945).
- **GitHub Action emits a verifiable Decision Receipt as a PR artifact** (#8669); `emit-receipt`, `receipt-reviewers` and `openrouter-api-key` inputs.
- **Disagreement Atlas v1:** merge-gate disagreement dataset with adjudication, `scripts/build_disagreement_atlas.py`, `docs/atlas/` summary + manifest (#9951, closes #9950).
- **Receipt-first scoreboard** `scripts/receipt_first_scoreboard.py` — ten exit metrics and six guardrails, offline cache, `--json/--markdown/--post/--parked-file` (#9968); fixed harness metrics scoreboard (#9852).
- **Crux cards** behind `enable_crux_cards` — receipts name the load-bearing dissent (#9414), exposed via `--crux-cards` (#9506); epistemic tags, action affordances and dissent-protected situation envelopes (#9944).
- **Merge quorum and settlement:** tier quorum (Tier 0-2 settles on one western-frontier signal) (#8507); default reviewer pair claude + openai (#8745); opt-in severity-gated dissent (#8574) and advisory-dissent settlement (#8729); Review Adjudicator core (#8749); `settle_pr` tier-aware settlement orchestrator (#8511); operator-advisory settlement relief valve (#9203); PR-keyed round budgets (#8635, #9056); Tier-4 merge-train (#8414); `--skew-auto-resolve` (#8750); unattended Tier 0-2 auto-merge on green quorum (#8503, #8767); cross-provider CLI reviewers grok-build + antigravity (#8483); VibeProxy Claude quorum transport (#9483) with conditionally countable evidence and grok verdict retry (#9770); grok reviewer 4.5 with Tier 3-4 counting narrowed to frontier Western families (#9205).
- **Model transports and catalog:** VibeProxy-first Fable transport (#9408) and exact OpenAI routing (#9477); canonical model catalog (#9355) with router pricing (#9364, #9374) and decision-stakes router (#9322); subscription-CLI fleet with cheap-tier cost routing and fail-closed budget cap (#8481); OpenRouter Fusion as a flagged, budget-capped agent (#8444, #8446, #8515); GPT-5.6 Sol + Claude Fable 5 (#9075), Claude Opus 5 (#9588), Kimi K3 (#9778) and Qwen 3.8 Max (#9783) runtime defaults; GLM/MiniMax + Tencent/ByteDance reviewers (#9078).
- **Native mission engine:** MissionSpec + WorkItem contracts (#8465), relay executor (#8486), orchestrator (#8484), Mission CLI (#8485), control loop (#8655), intake→decomposition bridge (#8766); evidence-bearing repository planning (#9759), commit-addressed context packs (#9757), generic repository profiles (#9756).
- **Governance tooling:** contract-drift authority roots (#9406), trusted authority bootstrap (#9659) and accepted corrective authority (#9645); Boundary 2 module-edge enforcement (#9787); truthful method-aware route-core operation plane (#9717) with mounted-FastAPI-router evidence (#9728); live workflow state verifier (#9745); charter-compliance checker (#8968); import-graph metrics tool with shrink-only mutual-cycle ratchet (#8331) and `--list-cycles` (#9970); repo-root allowlist checker (#8369).
- **Outcome-backed evaluation program:** corpus integrity (#9890), scorer/analysis/cost/holdout contracts and ledgers (#9900, #9904, #9905, #9909), source packets (#9913), frozen benchmark conditions and prompt contract (#9917, #9923), preflight (#9926), credentialless roster (#9928), development batch planner (#9936); Ground-Truth Integrity benchmark (#7877); source-linked quorum proof (#9225).
- **EU AI Act:** Art. 14 human-oversight attestation and oversight-pack generator (#9417).
- **Packaging:** root distribution installable as `aragora` (#8517); lazy connector imports so the base install runs `aragora ask` (#8522).
- **Automation and ops:** X bookmark/like research-intake pipeline (#9859); harvest engine (#8768); steering conductor cycle (#8982), founder decision queue (#8944), terminal mailbox ack flow (#8943); nightly pristine-main health run with halt-file (#9058); cancelled-run guardian (#9133) and receipted retrigger (#8849); AWS reinstatement package (#9412); Stage-Gate Conductor drift-issue dedup (#9544); bounded Claude Fable 5 consult + `consult-fable` skill (#8796).

### Changed
- Concurrent quorum reviewers with App-token read routing (#8426).
- Import-cycle repairs bringing `mutual_import_cycles` from 144 to 138 (ceiling 140): `gauntlet.odr_export↔odr_signing` (#9971), `debate.security_debate↔security_response` (#9972), `missions.orchestrator↔missions.swarm` (#9973), `nomic.dev_coordination.core↔dev_leases/dev_receipts` routed through the facade (#9974), `observability.middleware.tracing↔otel_bridge` via a shared `trace_state` leaf (#9975).
- Contract-drift paydown batches removing phantom SDK endpoint pairs from both SDKs (#9969, #9976).
- Reviewer output normalization so low-cost models reliably count (#8499); reviewer transport hardening with Anthropic-API fallback and two-tier timeouts (#8673).
- Billing model tiers and token pricing recalibrated to the v4.1 index (#8478); documented long-context tier pricing (#9656).

### Fixed
- Receipts never mint PASS/APPROVED from zero evidence (#9306); `demo --receipt` writes one receipt file and the banner names it (#9377); debate receipt reasoning no longer truncated at 2,000 chars (#9517).
- `aragora-verify`: explicit sdist include list so local venvs never break `python -m build` (#8812); cryptography floor raised to `>=48.0.1` (#8970).
- Swarm: derive diagnostic western-frontier advice from genuine reviewer signals (#9710); dev receipt helper types preserved (#9219); terminal mailbox receipts advisory-only.
- Governance: release claim bound to publication-time-knowable identity [Tier 4] (#9709); squash binding conformed to VAL-CDG-018 semantic-delta witnesses [Tier 4] (#9707).
- 784 `fix:` commits in total across CI lanes, quorum collection, automation funnels, lane coordination, docs truthfulness and the frontend; see `git log --format='%s' v2.9.0..v2.10.0 | grep -E '^fix[(:]'` (787 with a bare `^fix` match).

### Security
- aiohttp floor bumped to `>=3.14.3` with refreshed `uv.lock` CVE pins (#9714); Dependabot sweeps across `aragora/live`, `docs-site`, `examples/sveltekit` and `ide/vscode-aragora` (dompurify, postcss, fast-uri, undici, mermaid, recharts and others).
- `aragora-verify` dependency policy enforced in CI [Tier 4] (#9785).

### CI
- `aragora-verify` PyPI publish workflow (#8693) and post-publish install verification (#8945); PR funnel transport (#8312) with shared PR-state cache (#8339); 33 `ci:` commits in total.

### Documentation
- 321 `docs:` commits: ODR spec draft, `docs/atlas/`, GitHub Action receipt setup, governance and settlement playbooks, model-catalog and pricing references, release/status truth surfaces. Release notes: `docs/releases/v2.10.0.md`.

### Tests and refactors
- 88 `test:` and 63 `refactor:` commits, including the import-cycle repairs above and the outcome-backed evaluation fixtures.


## [2.9.0] - 2026-04-25

_Promoted from `v2.9.0-rc.1` after the chronic-red CI sweep, the npm vulnerability flush, and the self-hosted runner Docker provisioning. All six chronic-red CI workflows fixed; 19 of 19 Dependabot alerts addressed; secret scanning migrated to TruffleHog. Detailed readiness record at `docs/archive/status/2026-04-25-rc1-to-stable-receipt.md`._

### Added (post-rc.1)
- **Mode 3 brief severity counts (#6505 / #6506):** `ReviewBrief` now carries `findings_severity_counts` — aggregate `{high, medium, low}` counts derived from each slot's top findings — and surfaces it in the stored brief JSON. Operators can now distinguish "1 high-severity blocker" from "5 low-severity editorial comments" without reading every finding. Legacy callers that omit the new `build_brief` kwarg get an empty map rather than a crash.
- **`Recommendation.APPROVE_WITH_FOLLOWUPS` verdict class (#6505 / #6510):** Fourth brief recommendation for the "real findings but none are blockers" case. `ReviewBrief.recommendation` can now emit `approve_with_followups` (string value); downstream triage classifies it in the approve family.
- **Mode 3 advocate lens slot (#6514):** Ninth panel slot with `lens: advocate` argues the STRONGEST case FOR the PR, counterweighting the seven skeptical lenses. Optional (`required: false`) so an absent Anthropic key degrades gracefully.
- **Lane 1b rubric replay (#6552):** Replayed all 17 rc.1-window briefs through the post-#6505 rubric. 3/17 downgraded from `repair_first` to `approve_with_followups` — first observed evidence that the severity gate produces meaningful verdict variance.

### Changed (post-rc.1)
- **Mode 3 verdict severity gate (#6505 / #6510):** `REPAIR_FIRST` is now downgraded to `APPROVE_WITH_FOLLOWUPS` when the aggregated severity map reports zero `high` findings. Fixes the calibration bias identified in `docs/archive/status/2026-04-24-mode3-rc1-calibration.md` where 8 skeptical lenses all looking for problems always produced `REPAIR_FIRST` regardless of severity. Legacy callers without severity data preserve the old three-class behavior. `APPROVE_CANDIDATE` and `NEEDS_HUMAN_ATTENTION` paths are untouched.
- **Mode 3 panel budget ceiling 8.00 → 10.00 USD (#6514):** Accommodates the ninth advocate slot at the conservative estimator rate. Real-world per-brief cost stays ~$0.18.

### Fixed (chronic-red CI sweep, 2026-04-24 → 2026-04-25)
- **Load Tests (#6554):** Switched runner `aragora` self-hosted → `ubuntu-latest`. Self-hosted runner image lacked Docker, which the `services: redis` block requires. 4+ nights chronic-red.
- **Nightly Full Matrix Pre-release Gates (#6555):** Added `bandit>=1.7,<2.0` to `pyproject.toml [dev]` extra. `pre_release_check.py --category security` invokes `bandit` but it wasn't in any declared extra.
- **Nightly Full Matrix Regression Matrices, Security Pentest Aragora Scanner (#6560):** Switched install from a legacy `pip install -e` extras command listing nonexistent extras (`research`, `code-intel`, `monitoring`) to `bash scripts/ci_install_project.sh --extras dev,test`. The pyproject's empty `dependencies = []` means raw extras-based installs miss core deps (httpx, pydantic, fastapi).
- **E2E Tests Python (#6563):** Same install-pattern unification as #6560.
- **Coverage Gate (#6556):** Bumped `timeout-minutes: 30 → 90`. Full-suite-under-coverage on 215k tests exceeds 30 min serially.
- **Integration Tests (#6562):** Repaired `MockAgent` fixture (added `system_prompt` + Vote-shape return values) to match current Arena API. Bumped route-collision known-bound `60 → 61` (one new accidental collision; underlying handler consolidation tracked for v2.10).
- **Security Pentest pip-audit (#6559):** Added `--ignore-vuln CVE-2026-3219` to pip-audit. CVE is on the pip binary in the CI image, not the Aragora runtime; pip 26.0.1 IS the latest published version (no upstream fix exists yet).
- **Security Pentest Secret Scanning (#6567 → #6576):** First made `gitleaks-action@v2` `continue-on-error: true` (#6567). Then in #6576 fully migrated CI secret-scanning to TruffleHog (`trufflesecurity/trufflehog@main` with `--only-verified`) in both `security.yml` and `lint.yml`. gitleaks-action requires a paid `GITLEAKS_LICENSE` for organization accounts; TruffleHog is free, well-maintained, and `--only-verified` mode produces zero false positives. Local pre-commit still uses the gitleaks binary (free for individual use).
- **Integration Tests `webhook_configs` schema (#6575):** Aligned `aragora/db/schema/postgres_schema.sql` with `PostgresWebhookConfigStore.INITIAL_SCHEMA` (`user_id`, `workspace_id`, `active`, `events_json`, `description`, `last_delivery_at`, `last_delivery_status`, `delivery_count`). Added migration `v20260424000000_align_webhook_configs_schema.py` (idempotent ALTER TABLE; preserves `org_id → workspace_id`, `is_active → active`, `events → events_json` data). Closes the four `TestPostgresWebhookConfigStore` UndefinedColumnError test failures.
- **Load Tests back to self-hosted (#6577):** Reverted #6554 after Docker 25.0.14 was provisioned on the AL2023 self-hosted runner `i-0aae2ccd2f68b94d2` (`ip-172-31-24-39`) via AWS Systems Manager. The workflow now targets the narrower `aws-vpc-loadtest` label, runs k6 through Docker instead of AL2023-incompatible `apt-get`, sends the required `aragora-v1` WebSocket subprotocol, and uses the CI dependency bootstrap for the memory stress job. Documentation: `docs/operations/SELF_HOSTED_RUNNER_DOCKER.md`.
- **Route collision accounting (#6579):** Deduplicated handler collision owners by `(path, attr_name)` and ratcheted the known collision bound `61 → 51`, clearing the v2.9.0 baseline for the post-release route-consolidation waves.

### Security
- **Trivy action bump (#6557):** `aquasecurity/trivy-action 0.28.0 → 0.35.0`. Closes 2× CRITICAL CVE-2026-33634 in the prior version.
- **17 npm Dependabot alerts → 0 (#6558):** Combined npm `overrides` sweep across 5 projects (aragora/live, sdk/typescript, examples/sveltekit, ide/vscode-aragora, ide/vscode-aragora/webview-ui, docs-site). Patched packages: lodash, picomatch, postcss, serialize-javascript, uuid, vite, yaml, cookie, brace-expansion, ajv, qs, minimatch. Verified post-merge: every project reports `npm audit: found 0 vulnerabilities`.

### Documentation
- **Release prep checklist progress (#6493):** 8 of 10 acceptance criteria addressed directly; the 48h/main-nightly evidence criteria remain pending until the next scheduled observation. Readiness receipt (`docs/archive/status/2026-04-25-rc1-to-stable-receipt.md`) captures the rc.1 → stable readiness arc.
- **Mode 3 calibration sample N≥20:** 20 briefs total ($2.71 + $0.66 = $3.37 cumulative API spend); rubric-replay (#6552) shows 3/17 downgrades on the post-fix path.
- **Architecture reconciliation (#6580):** Updated the source and docs-site architecture narratives to match the current package layout, handler scale, operation count, and strict-mypy baseline before cutting the stable tag.


## [v2.9.0-rc.1] - 2026-04-24

### Highlights

- **Mode 3 heterogeneous PR review operational.** 8-provider panel (Claude + GPT core, Gemini / Grok / DeepSeek / Kimi / Qwen heterodox, Mistral regulatory), end-to-end regression-tested on the shipped path, ~95% precision on the calibration sample to date. Settlement ledger at `docs/archive/status/2026-04-21-thesis-settlement-session.md`.
- **Dialectical Runtime Synthesis Layer (DIC-series) underway.** Executable claim manifest (DIC-13), proof-carrying code unit scanner with flag gate (DIC-19), proactive crux gardening (DIC-28), operator crux arbitration (DIC-27), and agent bridge handler landed behind feature gates.
- **Triage auto-handle calibration gate integrated.** Low-risk `fire_and_forget` and `admin_merge_allowed` paths now consult an outcome-history SQLite store and surface drift alerts before gating merges.
- **Mac runner fleet hardened.** Canonical `docs/runners/FLEET.md`, daily headcount monitor, TIME_WAIT LaunchAgent + weekly GH Actions check, SSM deploy pinned to workflow SHA.
- **CI advisory gate bottlenecks reduced.** `test-fast` split into targeted shards, draft-PR gating tightened, timeouts rationalized.

### Added
- **Mode 3 end-to-end regression test (#6471):** Locks in the shipped 8-provider panel topology against accidental reversion. Replaces the old dev-only Mode 2 assertion.
- **Agent bridge handler (#6465):** Wires autonomous-navigation agent bridge into the handler registry with CLI-resume transport. Live smoke harness available via `scripts/agent_bridge_live_smoke.py` (opt-in).
- **AGT-05 ReputationStore (#6490):** Per-agent JSONL-backed reputation ledger — tracks task outcomes, calibration deltas, and drift signals. Foundation piece for the agent-civilization substrate.
- **DIC-13 ExecutableClaim manifest (#6456):** Typed manifest model + flag-gated directory scanner. Establishes the claim-schema landing site for DIC-14/25/26 to build on.
- **DIC-19 ProofCarryingCodeUnit scanner (#6472):** Flag-gated scanner + package export. Separates concerns between proof-unit discovery and verification.
- **DIC-28 proactive crux gardening (#6459):** Scheduled re-examination of resolved and outstanding cruxes with explicit `insufficient_evidence` status distinguishing "not evaluated" from "healthy". Boundary-only env reads via `GardeningConfig`.
- **Auto-handle calibration SQLite store (#6468):** Outcome-history store with transactional `record_outcome` (BEGIN IMMEDIATE wrapping), WAL mode enforcement, schema versioning, and extracted fingerprint helpers. Used by the triage calibration gate.
- **Triage auto-handle calibration integration (#6448):** Drift gating on low-risk merge paths. Backed by rolling outcome windows and per-path thresholds.
- **Canonical runner fleet documentation (#6476, #6486):** `docs/runners/FLEET.md` enumerates the 12-runner roster (3 Hetzner + 6 EC2 + 3 Mac + 1 Mac Studio). TIME_WAIT monitor (`scripts/runners/mac_timewait_check.sh`) under LaunchAgent surfaces TCP-port exhaustion before it drops a runner.
- **Rolling-window triage metrics (#6373):** New `aragora.triage` package and
  `GET /api/v1/review-queue/triage-metrics` endpoint emit the four Commitment-5
  metrics named in `docs/THESIS.md` (escalation rate, auto-handle override
  rate, human-override-outcome correlation, time-per-settlement median+p95)
  over rolling 7-day and 30-day windows, with advisory drift detection and
  ETag support. Pure-function aggregator in `aragora/triage/metrics.py` is
  testable with synthetic event sequences; the on-disk adapter in
  `aragora/triage/event_source.py` reads existing settlement receipts without
  modifying their schema. Legacy `/api/v1/review-queue/stats` (daily counters)
  remains unchanged.
- **205K+ test suite:** Test count grew from 129K to 205K+; 19,776 handler tests across 130+ files
- **Oracle stream observability:** Added TTFT/phase/stall metrics collection, dashboard wiring, and stream-recovery E2E coverage for Oracle flows
- **Main branch discipline workflow:** Added CI guard to flag direct pushes to `main` without associated PRs (supports explicit emergency override tag)
- **PR flow helper scripts:** Added `scripts/start_feature_branch.sh` and `scripts/open_pr.sh` plus Makefile targets (`branch-start`, `pr-open`) for branch-first contribution flow
- **`@handle_errors` decorator:** All 193 handler write methods (POST/PUT/PATCH/DELETE) across 130 files now have the decorator as outermost wrapper, catching unhandled exceptions with sanitized responses
- **Self-improvement E2E tests:** 66 tests validating assess→goals→execute pipeline against real codebase
- **Deployment readiness tests:** API key validation wired into `/readyz/dependencies` endpoint
- **Memory load tests:** Dedup engine at 1000+ items, gateway fan-out, retention gate batch processing
- **Connector live tests:** Integration tests for QuickBooks, SendGrid, Twilio, Instagram, Trello (skip without API keys)
- **Benchmark test tier:** `@pytest.mark.benchmark` tests in nightly CI for 10x scale validation
- **SDK expansion:** 13 new TypeScript namespaces and 6 new Python namespaces (184 Python / 183 TypeScript total)
- **Idea-to-Execution pipeline:** 4-stage pipeline (Ideas → Goals → Workflows → Orchestration) with KM persistence, spectate events, and fractal canvas navigator
- **Shoggoth Oracle:** Interactive 3D avatar page with three consultation modes, multi-model tentacle debates, and ElevenLabs TTS integration
- **Compliance artifact generation:** EU AI Act, SOC 2, and HIPAA compliance artifact generation via REST API and CLI
- **Coordination handler:** Cross-workspace federated execution with RBAC enforcement
- **Provenance UI panel:** Rich node drill-down with provenance chain visualization
- **Knowledge extraction by default:** Knowledge extraction enabled by default in debate outcomes; outcome feedback auto-wired
- **Pipeline node-level events:** Execution start/complete/fail events emitted during idea-to-execution stages
- **Graph/Matrix E2E tests:** End-to-end tests for graph and matrix debate APIs with KM contradiction wiring
- **Vertical evaluation context:** Vertical-specific evaluation criteria injected into agent prompts during debates
- **Performance targets guide:** Hardware profiles, throughput expectations, latency targets, and tuning knobs documentation
- **Compliance bundle:** Unified compliance entry point linking SOC 2, GDPR, HIPAA, EU AI Act, and data residency artifacts

### Changed
- **CI advisory gate split (#6479):** `test-fast` decomposed into targeted shards to avoid the previous 45-minute cap on the `core` shard; advisory gate cycle times reduced, draft-PR gating tightened.
- **Exception elimination:** All bare `except Exception: pass` handlers eliminated across the entire codebase; 130+ files narrowed to specific exception types
- **Contract drift governance artifacts:** Refreshed contract drift backlog + issue plan snapshots and weekly burndown targets to current baseline
- **str(e) sanitization:** All handler/auth/security/client/middleware `str(e)` leaks replaced with static messages and `logger.warning("...: %s", e)` pattern
- **f-string logging conversion:** 1,664 files converted from f-string to %-formatting in logger calls for security and performance
- **CLI lazy loading:** All re-exports in `aragora/cli/main.py` lazy-loaded via `__getattr__`; module import time reduced from 13.4s to 0.7s (19x speedup)
- **Heavy mode lazy loading:** `aragora/modes/__init__.py` lazy-loads deep_audit, redteam, and prober submodules that pull scipy/numpy
- **MetaPlanner refactoring:** Extracted utility functions into `meta_planner_utils.py`; Track enum moved to `types` module
- **Nomic orchestrator extraction:** Autonomous orchestrator split into focused modules
- **Deprecated ranking adapter imports:** Migrated 21 deprecated `ranking_adapter` imports
- **Risk scorer:** Generic basenames (`__init__.py`, `.env`) now require full-path matching to reduce false positives
- **Helm chart metadata:** Added `kubeVersion` to kubernetes, multi-region, and operator charts; fixed operator URLs
- **asyncio modernization:** `asyncio.get_event_loop().run_until_complete()` replaced with `asyncio.run()` across 13 test files (94 replacements)

### Fixed
- **PDB provider call bounding (#6462):** Mode 3 execution no longer fans out unbounded provider calls; concurrency and timeout caps enforced at the protocol boundary.
- **Secure deploy SHA race (#6483):** SSM-based secure deploys are now pinned to the triggering workflow SHA rather than `origin/main`, closing a short window where a concurrent merge could deploy a different commit than the one that passed checks.
- **Nightly test pollution (#6466):** Four standing nightly failures traced to xdist worker pollution; isolated via per-worker fixture ordering. Underlying failures tracked separately in #6464.
- **API contract alignment:** Cost handler (7 endpoints) and usage dashboard (6 endpoints) now return `{"data": {...}}` wrapper matching frontend hook expectations
- **StructuredLogger.exception():** Now accepts `*args` for `%s` formatting, matching stdlib logging API
- **CLI startup:** `aragora serve --demo` now works end-to-end; server starts in ~14s
- **OpenAPI spec drift:** Regenerated spec, SDK types, and capability matrix for CI compliance
- **Handler routing:** Fixed 10 `extract_path_param` off-by-one index bugs; fixed gastown dashboard `strip_version_prefix` path comparison
- **Mock pollution guard:** Autouse fixture prevents `MagicMock.side_effect` descriptor corruption across test sessions
- **SAST scanner hangs:** Autouse fixture mocks scanner to prevent filesystem walking during handler tests
- **Frontend Turbopack:** Inline style for dynamic CSS color fixes Turbopack build; merged route groups fix
- **Test isolation:** 17 unnecessary test skips removed; month-boundary bug fixed; PostgreSQL env var isolation added
- **Connector registry:** Sort stability fixed for deterministic CI
- **Risk scorer blending:** Fixed score blending logic for protected file detection
- **Read-only PostgreSQL replicas:** Server startup and handler init resilient to read-only replicas
- **Contradiction scan:** Query failures handled gracefully; KM detection mocked in tests
- **Pipeline wiring:** `pipelineId` returned from `executePipeline`; `useCostsBreakdown` disambiguated

### Security
- **RBAC enforcement:** Added `require_permission` to benchmarking, outcomes, playbooks, and coordination handlers
- **Sentinel config:** Rate limit and feedback test hardening
- **Broad exception narrowing:** 9 additional broad exceptions narrowed in handlers with 369 new handler tests
- **f-string logging:** Eliminated format-string injection risk across 1,664 files
- **MCP error sanitization:** `str(e)` leaks in MCP tools and connectors replaced with safe messages

### Deprecated
- **Arena individual params:** `supermemory`, `knowledge`, `evolution`, and `ML` parameters now emit deprecation warnings; use `SupermemoryConfig`, `KnowledgeConfig`, `EvolutionConfig`, and `MLConfig` objects instead

---

## [v2.8.1-rc.1] - 2026-02-25

### Changed
- **SDK cross-parity regression fix:** TypeScript `SMEAPI.getWorkflow()` now uses a direct request fallback path while preserving legacy client compatibility, ensuring `/api/v1/sme/workflows/{workflow_id}` is discoverable by strict cross-SDK parity checks.
- **Release-candidate gate hardening:** Release flow now includes strict SDK parity and cross-SDK parity checks as first-class release blockers.

### Validation
- **Release-candidate full gate (green):**
  - debate/orchestrator/workflow: `345 passed`
  - handlers/OpenClaw: `328 passed`
  - observability/logging: `158 passed`
  - SDK parity/contracts: `75 passed`
  - RLM priority: `36 passed`
  - live hook suites: `39 passed`
- **Strict parity gates (green):**
  - `python scripts/check_sdk_parity.py --strict --baseline scripts/baselines/check_sdk_parity.json --budget scripts/baselines/check_sdk_parity_budget.json`
  - `python scripts/check_cross_sdk_parity.py --strict --baseline scripts/baselines/cross_sdk_parity.json`
  - `npm --prefix sdk/typescript run typecheck`

---

## [2.8.0] - 2026-02-16

### Added
- **LiftMode Shopify + Zendesk deployment:** Enabled Shopify order sync and Zendesk ticket sync in `deploy/liftmode/` with auto-connect, credential prompts, and expanded daily briefing with orders and tickets sections
- **LiftMode smoke tests:** 14 tests validating briefing pipeline (inbox, orders, tickets), setup.sh JSON builder, and dry-run mode
- **Workspace admin UI:** Settings tab with workspace info editing, access/security toggles (MFA, debate approval, self-signup), activity feed tab, and pending invites management
- **TypeScript SDK parity:** Added `features.ts` and `vector-index.ts` namespaces, closing the Python/TypeScript SDK gap (158/158 namespaces)
- **SDK cost estimation:** Added `estimate_cost` method to Python and TypeScript debate SDKs
- **HardenedOrchestrator:** Gold path wiring with canary tokens, spectate events, work stealing, and OpenClaw computer-use integration
- **HierarchicalCoordinator:** Planner/Worker/Judge multi-agent coordination cycle with revision loops (70 tests)
- **ParallelOrchestrator:** Concurrent task execution with semaphore-based concurrency limits
- **SemanticConflictDetector:** Cross-branch semantic conflict detection for parallel development
- **Docker quickstart:** `docker-compose.quickstart.yml` for zero-config offline demo (no API keys needed)
- **Dashboard in self-hosted:** Dashboard service added to production `deploy/self-hosted/docker-compose.yml`
- **Batch claim verification example:** `examples/batch_verify_claims.py` for concurrent claim verification
- **Cross-cycle learning:** Calibration-weighted agent selection across Nomic self-improvement cycles
- **RLM deep integration:** Three-tier Recursive Language Model integration across debate, memory, and knowledge subsystems (182 new tests)
- **Business decision templates:** Pre-built deliberation templates for hiring, vendor selection, budget allocation, and strategy decisions
- **Budget-aware team selection:** Arena team selector now factors per-debate cost estimates into agent selection, with configurable budget caps
- **CLI `--template` and `--mode` flags:** The `decide` command supports `--template` for pre-built decision workflows and `--mode` for operational presets
- **CLI `--spectate` and `--preset` arguments:** Real-time debate observation and quick-start configuration from the command line
- **Cross-debate knowledge manager:** Injects prior claims and institutional knowledge from previous debates into new sessions
- **EU AI Act compliance REST API:** Expose Article 12/13/14 compliance artifacts via HTTP endpoints with SDK support in Python and TypeScript
- **Cross-pollination audit and compliance drift monitor:** Detect compliance drift across workspaces with automated cross-pollination auditing
- **SME enhancement sprint:** Cross-pollination templates, SME-specific KPIs, integration health monitoring, and improved dashboard experience
- **Expanded workflow engine:** Decision template support with 7-node DAG for SME workflows, webhook dispatch bridge, and fallback strategies
- **40+ new handler endpoints:** Comprehensive server-side coverage for analytics, billing, orchestration, skills, feedback, and pipeline lifecycle
- **Auto-explain and budget runway:** Automatic explanation generation for debate outcomes, cost estimation improvements, and budget runway tracking
- **Notification system expansion:** Budget alerts, cost anomaly notifications, circuit breaker state notifications, and per-debate budget coordination
- **Email triage rules engine:** Configurable email triage with priority classification and routing rules
- **Pipeline lifecycle events:** Execution start/complete/fail events for decision pipeline stages with feedback handlers
- **Event schema expansion:** New event types for cross-subscriber coordination and startup health checks
- **Selection feedback loop:** `SelectionFeedbackLoop` wired into `TeamSelector` scoring and Arena cost tracking with health registry integration
- **Agent feedback handler:** Dedicated handler for agent performance feedback with debate integration tests
- **Memory tier events:** Event emission on memory tier transitions with workflow fallback strategies
- **Autotuner wiring:** Budget-aware autotuner connected to argument graph endpoint and Knowledge Mound workflow storage
- **Circuit breaker expansion:** 120 new tests covering circuit breaker patterns across debate, pipeline, and handler subsystems
- **Progressive navigation:** New UI navigation mode with landing page call-to-action for improved onboarding
- **Financial and legal vertical demos:** Example scripts demonstrating vertical-specific debate configurations for finance and legal use cases
- **Privacy anonymization protocol flag:** Debate presets now support `enable_anonymization` for PII-safe debates
- **Billing CLI operations:** New CLI commands for billing management with demo mode improvements
- **Transcription handler coverage:** Full test coverage for audio transcription endpoints

### Changed
- **Exception handler narrowing:** 130+ files narrowed from `except Exception` to specific exception types across server/, debate/, control_plane/, and workflow/; error messages sanitized to prevent information leakage
- **CI workflow consolidation:** Deprecated 2 legacy publish workflows (`publish-sdk.yml`, `publish-python-sdk.yml`) in favor of canonical versions with multi-version matrix testing, dry-run support, and concurrency controls
- **LiftMode setup.sh:** Fixed Python JSON builder injection vulnerability (bare `if '$VAR':` → `sys.argv` pairs), fixed 3 OAuth URLs (`/api/v2/` → `/api/v1/`)
- **TypeScript SDK methods:** 37 HTTP method verb corrections (GET/POST/DELETE/PATCH alignment with server endpoints)
- **Frontend sidebar:** Simplified to 5 items in simple mode; Knowledge, Agents, Analytics, Documents, Leaderboard gated behind `minMode: 'standard'`
- **Deployment docs:** `deploy/README.md` rewritten with "which deployment should I use?" decision table; main README deployment section streamlined
- **SDK voice namespace:** Removed stale voice namespace and re-wired into sync/async clients with proper gateway methods
- **SDK parity:** Added missing methods for analytics, skills, voice, `getAgentCosts`, and `getCostAnomalies` to `AragoraClient`
- **TypeScript SDK namespaces:** Expanded belief, pulse, and OpenAPI namespaces for TypeScript SDK
- **Analytics dashboard:** Extended billing routes and cost breakdown endpoints
- **Handler path parsing:** Corrected `extract_path_param` segment indexes across 6 handlers; fixed gastown dashboard versioned path stripping
- **Repository DELETE path:** Fixed path parsing for repository deletion endpoints (+ 222 handler tests)
- **Narrowed exception handlers:** Replaced broad `except Exception` with specific types across debate, memory, knowledge, events, and workflow modules
- **IterableTTLCache:** Added `__len__` and `clear()` methods for proper cache lifecycle management
- **OpenAPI spec:** Regenerated with 369 missing TypeScript SDK endpoint stubs re-added; eliminated SDK contract drift (py=0, ts=0)
- **Skip baseline:** Reduced from ~190 to current level through systematic removal of vestigial skip guards across JWT, Z3, WhatsApp, evolution, and relationship tests

### Fixed
- **Handler routing bugs:** Fixed 10 `extract_path_param` off-by-one index bugs and 1 `strip_version_prefix` path comparison bug across handler files
- **SpectatorStream.emit():** Fixed API call to use `details` string parameter instead of `data` dict
- **StructuredLogger args:** Fixed `logger.warning()` calls passing positional args to structured logger (requires f-string)
- **Orchestration test exceptions:** Updated tests to raise specific exception types matching narrowed handler catches
- **Prometheus metric re-registration:** Prevent duplicate metric registration errors on server restart
- **Revoked token detection:** Optimized `_decrypt_token` to short-circuit on revoked tokens in storage layer
- **Persistence timestamps:** Fixed timezone-aware datetime handling to prevent comparison errors in receipt verification
- **Cost anomaly budget enforcement:** Budget limits now properly enforced on cost anomaly detection
- **Trace context type checks:** Hardened type validation for distributed trace context propagation
- **Compliance monitor cleanup:** Fixed consensus stress test improvements and monitor lifecycle
- **Cost/breakdown stub:** Re-added missing response stub for analytics dashboard cost breakdown endpoint
- **Webhook delivery isolation:** Fixed test isolation for webhook delivery and secrets rotation
- **Operator compilation:** Added generated DeepCopy methods for CRD types and missing `resource` import for Go compilation
- **Frontend API proxy:** Added Cloudflare Pages Function proxy for `/api/*` routes
- **EC2 deployment:** Fixed deployment to target ALL EC2 instances, not just the first per environment
- **aragora-debate packaging:** Packaging hygiene fixes for sdist readiness
- **Memory store:** Fixed prior claims context test cleanup and memory store lifecycle
- **Gauntlet determinism:** Cancellation and timeout tests now deterministic instead of timing-dependent

### Security
- **RBAC enforcement:** Added permission decorators to 8 previously unprotected handler endpoints (4+4 batches)
- **RBAC mutation handlers:** Enforcement added to 5 mutation handlers with 8 read-only endpoints allowlisted
- **Backend Dockerfile hardening:** Non-root user, minimal layers, and security-focused self-hosted configuration
- **Trivy scan:** Made config scan non-blocking on all branches to prevent false-positive CI failures

### Infrastructure
- **SSM-based health check:** Deployment health checks migrated from HTTP polling to AWS SSM commands
- **PyPI publishing:** Switched from OIDC trusted publishing to API token authentication
- **OpenAPI regeneration pipeline:** Automated spec + types regeneration integrated into CI
- **Ruff formatting:** Applied formatting across 232 files with 18 violations fixed; removed unused imports and variables
- **SDK contract drift:** Eliminated drift to py=0, ts=0, missing=1 baseline

### Tests
- **179 handler tests:** New coverage for workflow_templates, marketplace, and moderation handlers
- **135 handler subsystem tests:** Coverage for interface, registry, and metrics subsystems
- **132+ handler infrastructure tests:** Generic rate limiter cleanup and infrastructure test expansion
- **120 circuit breaker tests:** Expanded coverage across debate and pipeline subsystems
- **222 handler tests:** Added alongside repository DELETE path fix
- **E2E smoke test:** Gauntlet receipt channel routing end-to-end validation
- **Centralized RBAC bypass:** Unified E2E conftest auth bypass, simplifying receipt, MFA, and tournament test setup
- **Test isolation improvements:** Fixed rate limiter pollution, encryption singleton cross-contamination, env variable leakage, and SyncStore stale DB issues across dozens of test files

---

## [v2.7.4] - 2026-02-14

### Added
- **LiftMode deployment configuration:** Production deployment support for LiftMode infrastructure
- **185 Python SDK endpoint methods:** Closed coverage gaps across stable endpoint surface
- **SDK namespace expansion:** Python SDK devops, routing, oauth_wizard, rbac, and repository namespaces; TypeScript parity across 9 handler namespaces plus admin, agents, and receipts
- **A/B debate quality benchmark pipeline:** Evaluation framework for comparing debate quality across configurations

### Changed
- **Exception handler narrowing:** Replaced 70+ broad `except Exception` catches with specific types across security, CLI, metrics, verticals, knowledge, debate, config, skills, documents, rules, and nomic modules
- **OpenAPI spec:** Added 119 missing handler routes (drift reduced from 120 to 1); corrected HTTP methods across 56 TypeScript SDK namespaces
- **SDK pruning:** Removed 1,888 lines of stale SDK methods; pruned stale TypeScript namespace methods
- **Timezone-aware datetimes:** Sync models now use timezone-aware datetimes to prevent comparison errors

### Fixed
- **Session store hardening:** Token index fixes, config validator improvements, SAML auth edge cases, and admin handler robustness
- **RLM dependency:** Replaced git URL dependency with PyPI version; removed non-PyPI rlm from extras
- **Gauntlet datetime mismatch:** Fixed timezone mismatch in gauntlet timestamp comparisons
- **Empty bearer token validation:** Reject empty bearer tokens instead of passing them through
- **CrewAI/Asana logger conflicts:** Renamed `process` and `name` extra keys to avoid Python `LogRecord` attribute conflicts
- **RLM empty source_nodes:** Guard against empty `source_nodes` in `_compress_level` to prevent crashes
- **success_response deprecation:** Now correctly emits `DeprecationWarning` as documented
- **Docker:** Restored `node:20-alpine` base for Next.js >= 20.9.0 requirement; fixed package-lock.json copy issues
- **CI stability:** Added `ARAGORA_OFFLINE` env to prevent network calls in tests; increased debate shard timeout to 35 minutes; widened test reruns for flaky isolation issues

### Security
- **Pentest findings:** Addressed remaining findings H-2, M-1 through M-4 from security assessment
- **Test auth hook:** Tightened to only bypass auth on fallback paths, preventing accidental auth bypass in production code paths

---

## [v2.7.3] - 2026-02-13

### Fixed
- **Session store token index:** Fixed token indexing in session store for correct lookup behavior
- **Security nosec annotations:** Added targeted `# nosec` annotations for verified false positives
- **Version alignment:** Bumped version to 2.7.3 across all package sources

---

## [v2.7.2] - 2026-02-13

### Added
- **OpenClaw next-steps scanner:** Automated scanner that identifies actionable next steps from PR reviews, with TypeScript SDK namespace expansion
- **SDK 100% parity:** Closed remaining SDK parity gaps between Python and TypeScript clients
- **GitHub issue templates:** Standardized bug report and feature request templates
- **Nightly CI:** Added nightly CI workflow for extended test suite execution
- **Zero-config guarantee specification:** Documented the "just works" promise for default configurations

### Changed
- **CLI lazy imports:** Inlined testfixer parser to eliminate 2.3-second import cascade; lazy imports for CLI parser modules
- **RBAC default-deny:** Middleware now defaults to deny instead of allow for unrecognized routes
- **Cloudflare Pages:** Replaced Vercel config with Cloudflare Pages headers and redirects

### Fixed
- **Auth and permission checks:** Added to plans and consensus handlers that were previously unprotected
- **SDK parity checker:** Improved wildcard prefix matching for more accurate parity reporting
- **Grafana dashboards:** Corrected volume path in production Docker Compose
- **Frontend Dockerfile:** Resolved local SDK path reference in Docker build context
- **Test collection:** Added `__init__.py` to 54 test subdirectories to prevent pytest collection errors
- **PyPI publishing:** Stabilized between API token and trusted publishing approaches
- **SDK integrations:** Added `get_slack_status` and fixed v1 API paths in integrations namespace

---

## [v2.7.1] - 2026-02-13

### Added
- **SARIF export for PR review runner:** OpenClaw review runner now exports findings in SARIF 2.1.0 format for GitHub integration
- **SDK namespace expansion:** Added autonomous, computer_use, workflow, gmail, learning, shared_inbox, audit, graph debates, workspace, and security debate methods across Python and TypeScript SDKs
- **Docker zero-install quickstart:** Step-by-step guide for running Aragora with zero local dependencies
- **A/B debate quality benchmark:** Evaluation pipeline for comparing debate configurations

### Changed
- **SDK pruning:** Removed stale SDK methods and test files that duplicated the main test suite; pruned stale TypeScript integrations namespace methods
- **OpenAPI cleanup:** Removed 86 orphaned routes from OpenAPI spec

### Fixed
- **Consensus quorum:** Fixed quorum calculation in synthesis `final_answer` and receipt handler improvements
- **Password validation:** Simplified validation logic and fixed stream server test subscriptions
- **Finetuning adapter:** Ensured adapter save directory exists before writing configuration
- **Demo Dockerfile:** Removed reference to nonexistent `setup.cfg` in COPY instruction
- **Silent exceptions:** Added logging for previously silent exceptions in executor and server modules

### Security
- **XSS in password reset:** Fixed cross-site scripting vulnerability in password reset email templates
- **Insecure password blocking:** Production environments now reject commonly-used insecure passwords
- **Lockout warning:** Account lockout warnings only shown in production mode

---

## [v2.7.0] - 2026-02-13

This is a major release consolidating 4+ months of development across the entire platform.

### Added
- **External agent gateway:** Secure orchestration gateway for external AI agents with SSRF safeguards, CSRF middleware, and expanded CORS configuration
- **OpenClaw gateway:** Standardized HTTP client pooling, deployment configs, full test suite, and Phase 3 production hardening with device runtime
- **ERC-8004 blockchain integration:** Agent identity and reputation registries on-chain, with control plane integration and Proof of Calibration
- **OAuth account linking:** Microsoft, Apple, and OIDC provider account linking support
- **Supermemory:** Cross-session external memory connector and Knowledge Mound adapter
- **Decision integrity pipeline:** Full pipeline from `DecisionMemo` through `PatchPlan` to PR generation with unified routing, evidence context, and knowledge connectors
- **Computer use execution mode:** `computer_use` execution mode for workflow approval overrides
- **Agent learning modules:** Curriculum learning, power sampling, and continual learning with Nested Learning paradigm
- **n8n/Linear/Obsidian integrations:** MCP server tools for external tool integration
- **Workspace invitations:** Email-based invitation management for workspace collaboration
- **Bot handler enhancements:** Search, recent, and receipt commands for Telegram and WhatsApp; attachment forwarding to DecisionRouter
- **Spectate Mode UI:** Real-time debate observation components
- **Moderation Dashboard:** Content safety monitoring interface
- **Argument Cartography:** Visualization components for argument mapping and logic flows
- **Sandbox Code Execution UI:** Interface for Docker-based safe code execution
- **Marketplace page:** UI component for skill and template marketplace browsing
- **Context budgeter:** Token estimation, truncation, and scaling for prompt construction
- **FastAPI v2 migration:** Receipts, gauntlet, and agents endpoints migrated to FastAPI v2
- **Tiered handler loading:** Selective handler loading for lightweight startup profiles
- **Leader election tests:** Distributed coordination testing with RBAC hardening and CNPG backups
- **Redis cluster support:** Rate limiting infrastructure with Redis cluster backend
- **LangExtract KM adapter:** Knowledge Mound adapter for LangChain extraction results (350 LOC, 35 tests)
- **Self-improvement pipeline:** Gold path from design through implementation to verification
- **Server `--offline` flag:** Sets `ARAGORA_OFFLINE` + `DEMO_MODE` + SQLite backend for air-gapped operation
- **Vertical weight profiles:** 7 domain-specific profiles (healthcare HIPAA/clinical, financial audit/risk, legal contract/due diligence, compliance SOX)
- **Vertical rubrics:** Domain-specific rubric sets for healthcare, financial, and legal verticals
- **Skill malware scanner:** AST-based static analysis with CLI (`aragora skills scan`), severity levels (SAFE/SUSPICIOUS/DANGEROUS)
- **Verified-only marketplace:** Publisher enforcement requiring security scan before marketplace listing
- **Review-to-receipt bridge:** `DecisionReceipt.from_review_result()` for audit trail generation from code reviews
- **SARIF and Gauntlet CLI flags:** `--sarif` for SARIF 2.1.0 export, `--gauntlet` for adversarial stress-testing on `aragora review`
- **Autonomous PR code review runner:** OpenClaw-powered automated PR review with multi-agent code analysis
- **Full-stack demo compose:** Docker Compose with frontend and PR reviewer setup
- **One-click demo deployment:** Self-contained Docker Compose for instant evaluation
- **Alertmanager wiring:** Queue SLO alerts routed to alertmanager
- **12+ Python SDK namespaces:** Added orgs, tenants, policies, codebase, costs, decisions, onboarding, notifications, gmail, explainability, and more
- **TypeScript SDK pagination:** Pagination support and error handling improvements
- **API stability tracking:** Stability manifest covering 80.6% of endpoints (829/1029)
- **Grafana reference dashboards:** 3 dashboards covering business metrics, SLO, and infrastructure
- **E2E server smoke tests:** Real HTTP endpoint testing with comprehensive validation

### Changed
- **Arena config objects:** Individual supermemory/knowledge/evolution/ML params deprecated in favor of `SupermemoryConfig`, `KnowledgeConfig`, `EvolutionConfig`, `MLConfig` config groups
- **Arena `create()` classmethod:** New factory method with deprecation warnings for legacy parameter style
- **Debate defaults centralized:** All debate entrypoints share unified default configuration
- **Exception handler hygiene:** Eliminated ALL bare `except Exception: pass` handlers across the entire codebase; replaced with specific exception types and proper logging
- **Connector timeout guards:** 50+ `while True` loops bounded with `for _page in range(_MAX_PAGES)` across 31 connector files
- **SDK pruning:** Removed 2,952+ lines of stale SDK methods across 8 namespaces; pruned methods without backend route coverage
- **942 unused imports removed:** Codebase-wide cleanup via automated analysis
- **Nomic Loop depth limits:** `max_depth=3` enforced on task decomposer to prevent runaway recursion
- **Handler store migration:** 9 handler stores migrated to `LazyStoreFactory`/`LazyStore` pattern
- **V1 API sunset preparation:** Deprecation enforcer middleware, versioned router, and migration guide
- **Fast-first speed policy:** New debate speed policy prioritizing time-to-first-result
- **Knowledge Mound adapter enforcement:** `adapter_name` enforced via `__init_subclass__` (Phase 2)
- **Nomic stores async IO:** Migrated to async file I/O for bead and convoy stores
- **OpenAPI spec:** Expanded to 2,234 operations across 1,867 paths with 97+ SDK-covered endpoints in stability manifest
- **Skip baseline reduction:** From 425 to under 200 through systematic skip guard removal and xfail conversion
- **File decomposition:** Split type_protocols, notifications/service, integration_store, and usage_metering into focused modules

### Fixed
- **Login form rendering:** Render directly at `/login` instead of redirecting
- **Prometheus metrics:** Safe registration preventing duplicates across all metrics modules
- **Redis ConnectionError:** Caught `redis.exceptions.ConnectionError` in all fallback handlers and config validator
- **Circular imports:** TYPE_CHECKING guards added for control_plane/testfixer and SDK deprecation chains
- **Flaky leader election:** Singleton `_regional_leader_election` reset fixture prevents cross-test pollution
- **CLI review bug:** Local `import json` inside `elif` branch no longer shadows module-level import in SARIF export
- **Skill registry:** `replace=True` now correctly clears old `_validation_warnings`
- **OAuth token leak:** Fixed token exposure in URL parameters
- **Frontend login:** Proper OAuth error handling and login form UX improvements
- **Cloudflare Pages:** Added `/docs` redirect and sitemap.xml for SEO
- **Version alignment:** All package versions synchronized across Python, TypeScript, and docs-site packages

### Security
- **RBAC fail-closed guards:** Added to 17+ handler modules including bots, connectors, Slack user management, workflows, and codebase security
- **JWT fail-closed validation:** Strengthened validation behavior in authentication module
- **CSRF middleware:** Added with expanded CORS configuration
- **CSP headers:** Enhanced Content Security Policy with security audit scripts
- **OpenClaw audit findings:** Closed all 13 findings (F01-F11) including auth, key management, and rate limiting
- **3 MEDIUM findings fixed:** F05, F06, F08 from security assessment
- **API key rotation:** Rotation mechanism with RBAC CI verification
- **Hardened auth defaults:** Environment variable defaults, token validation dev mode fallbacks, and traceback suppression
- **Path validation and SSRF:** Hardened path validation and SSRF checks across gateway endpoints
- **Approval enforcement:** Unified with audit trail tracking

### Infrastructure
- **Kubernetes operator:** Go operator with CRD types, DeepCopy methods, and dependency management
- **Docker Compose stacks:** Full-stack demo, self-hosted production, and one-click evaluation configurations
- **Lightsail SSH deployment:** AWS Lightsail deployment workflow for production
- **Helm security scan:** Added dependency build before Trivy scan
- **CI security pipeline:** 6-job workflow (CodeQL, Bandit, Scanner, dependency audit, RBAC, secrets)
- **Randomized test ordering:** CI runs with 3 seeds (12345, 54321, 99999) to detect order-dependent failures
- **Offline smoke CI:** Test suite runs in offline mode to verify air-gapped operation
- **Agent registry sync:** CI gate for agent count consistency
- **K8s consolidation:** `deploy/k8s/` merged into `deploy/kubernetes/`
- **Direnv setup:** `.envrc` for automatic secret loading with documented `.env` safety model
- **PyPI readiness:** `aragora-debate` v0.2.0 built, twine-checked, with publishing workflow

### Tests
- **136,000+ tests** across 3,000+ test files (up from 129,000+)
- **1,500+ control plane tests** passing
- **4,300+ Knowledge Mound tests** passing
- **1,000+ Pulse tests** passing
- **Skip baseline reduced:** From 425 to under 200 through systematic analysis
- **Dead code deletion:** 17 modules (9,673 lines) + 10 orchestrator shims (638 lines) removed
- **Wired-in modules:** 10 previously test-only modules now exported from package `__init__.py`

### aragora-debate v0.2.0
- Evidence quality analysis (regex-based citation, data, reasoning detection)
- Hollow consensus detection (detects agents agreeing without substantive evidence)
- Convergence tracking (`difflib.SequenceMatcher` for proposal similarity)
- Evidence-powered trickster (challenge injection on hollow consensus)
- Cross-proposal analysis (shared evidence, contradictions, evidence gaps)
- Event/callback system (sync+async `EventEmitter`, 10 event types)
- Mistral and Gemini provider agents (optional deps)
- Reference Claude and OpenAI agents with integration guide
- High-level `Debate` API and `MockAgent` for testing
- CLI `--trickster` and `--convergence` flags

---

## [Pre-v0.2.0] - 2026-02-09

### Features
- Knowledge Mound: compliance, debate, and workflow adapters with factory registration
- Security Debate API: multi-agent vulnerability debate at `/api/v1/audit/security/debate`
- Security Audit Scheduling: cron-based security scans with debate on critical findings
- CI Security Pipeline: 6-job workflow (CodeQL, Bandit, Aragora Scanner, dependency audit, RBAC, secrets)
- Server handlers: auth, payments, SLO monitoring, selection role assignment improvements
- Privacy: deletion verification callbacks for GDPR compliance
- TestFixer: automated test failure analysis, Hegelian debate-based fix proposals, and retry loop orchestrator
- Secrets Manager: AWS Secrets Manager integration with secure key rotation and clipboard clearing

### Improvements
- OpenClaw handler refactoring with shared base class (promoted to STABLE)
- Decision system modularization (routing, models, integrity packages)
- Generic store abstraction layer
- Gauntlet worker ELO feedback integration
- Secrets Manager preferred over .env across codebase (embeddings, semantic store, agent filter)

### Testing
- 135+ new tests across security, scheduler, validators, and handler modules
- 231 new TestFixer tests covering runner, analyzer, proposer, orchestrator, store, and agent generator
- Context strategy and similarity backend coverage
- RBAC handler enforcement expansion
- Privacy deletion callback tests

### Code Quality
- F-string logger anti-patterns fixed across handler and worker files
- OTel instrumentation for Nomic Loop phase transitions
- Documentation updated (STATUS.md, API_REFERENCE.md)

---

## [v2.4.1] - 2026-01-31

### Security

- **XXE Prevention:** Replace unsafe `xml.etree.ElementTree` with `defusedxml.ElementTree` in Microsoft Ads connector and document parser
- **HMAC Strength:** Use full 256-bit HMAC-SHA256 signatures instead of truncated 64-bit signatures in token signing
- **PII Masking:** Mask email addresses in authentication logs (login, password reset, MFA, API keys) - now logs `user_id` instead of `email`
- **Input Validation:** Add type validation after JSON deserialization in MCP workflow and control plane tools
- **Thread Safety:** Add threading.Lock for thread-safe initialization of error monitoring singleton

### Testing

- Fix MockContent classes in streaming tests to support `iter_chunks_with_timeout()` compatibility

---

## [v2.4.0] - 2026-01-25

### Features

- **tests:** add CDC → Knowledge Mound integration coverage
- **bots:** defer API base validation to runtime initialization for bot clients
- **control-plane:** improve error handling for agent/task retrieval
- **sdk:** add Python SDK resources for orgs, tenants, policies, codebase, costs, decisions, onboarding, notifications, gmail, and explainability

### Bug Fixes

- **client:** fix Python SDK payloads for billing + RBAC endpoints
- **knowledge:** align knowledge search parameter key (`q`)
- **plugins:** preserve legacy Sunset header behavior when paths are normalized
- **costs:** avoid resetting per-debate cost tracking during initialization

### Maintenance

- **versioning:** align package versions to 2.4.0
- **typing:** tighten optional import and context manager annotations

---

## [v2.2.0] - 2026-01-24

### Features

- **release:** bump runtime version to 2.2.0 across core packages
- **cli:** add guided `aragora setup` wizard for self-hosted configuration
- **ui:** add Decision Inbox filters and receipt deep links
- **integrations:** route Slack/Teams receipt links to UI when `ARAGORA_PUBLIC_URL` is set
- **costs:** wire cost dashboard components to backend API base
- **docs:** add 2.2.0 status entry for SME + developer focus

### Bug Fixes

- **receipts:** fix export flow for gauntlet-backed receipts and checksum verification

### Maintenance

- **live:** update PyPI version label on the about page

---

## [v2.1.15] - 2026-01-24

### Features

- **connectors:** enforce abstract property pattern for connector identification
- **auth:** improve AuthContext with better error handling and session management
- **live:** add production-ready Playwright configuration

### Bug Fixes

- **connectors:** remove class-level defaults that shadowed abstract properties
- **tests:** fix flaky timing test with tolerance for CI variability
- **tests:** fix circuit breaker test with explicit threshold configuration
- **chat:** fix router path handling for unified inbox
- **sdk:** fix version mismatch in sdk/python (2.2.0 → 2.1.15)

### CI/CD

- **version:** add version alignment validation job to CI
- **scripts:** add `check_version_alignment.py` for cross-package version validation

### Documentation

- **backlog:** add Q1 2026 backlog with 60+ issues across 6 sprints
- **planning:** create Sprint 1-6 milestones and track issues in GitHub

### Maintenance

- Consolidate E2E test files into single comprehensive spec
- Update docs-site Docusaurus configuration

---

## [v2.1.11] - 2026-01-23

### Features

- **km:** add comprehensive resilience patterns and SLO monitoring (75fda39)
  - ResilientPostgresStore with retry logic and health monitoring
  - Cache invalidation strategies (TTL, LRU, event-based)
  - SLO alerting with Prometheus metrics integration
- **sdk:** bring TypeScript SDK to parity with Python SDK v2.1.13 (fe55070)
- **knowledge-mound:** add Phase A2 improvements (2c5140d)
- **redteam:** complete steelman/strawman and defense execution (a69e241)

### Bug Fixes

- **types:** resolve remaining mypy type errors (57496ce, ffcd800, a2cca8a)
  - Zero mypy errors across 1,792 source files
  - Fixed MRO issues in OpenAI-compatible agent mixins
  - Fixed handler signature overrides and ServerContext typing
  - Fixed Path to str conversions for data_dir parameters
- **auth:** fix handler paths to use normalized (non-versioned) paths (6847518)
- **ui:** remove mock data fallbacks from inbox components (4bd4383)
- **storage:** use run_async for PostgreSQL store initialization (fd2d20b, 1a60cde)
- **tests:** update SMTP test to expect timeout parameter (377d93f)

### Tests

- Add Playwright e2e tests for auth flow and console error detection (1dd2a87)

### Maintenance

- chore: code quality fixes and type improvements (ffcd800)
- fix(v2.1.15): production hardening and storage consolidation (9a99537)
- chore(sdk): consolidate Python SDKs and align versions (b22972d)

## [v2.1.10] - 2026-01-23

### Features

- implement Phase 2-4 enterprise features (ecb1c85)
- implement Phase 1 foundation features (498312a)
- add Redis-backed cache for inbox handler (production-ready) (ab902e0)
- implement inbox prioritizer integration for reprioritize endpoint (04403d2)
- add new feature handlers, tests, and documentation updates (19da741)
- workflow enhancements and documentation updates (b77d94a)
- add connectors, services, and inbox components (4a845a4)
- add CodebaseUnderstandingAgent tests and fix bugs (d6c07a0)
- comprehensive updates across codebase (711216c)
- add thread-safety and resilience test coverage (0e0f0ad)
- add production hardening and performance optimizations (a3e96ee)
- add developer experience improvements (22949d8)
- add marketplace server handlers and CLI commands (2f75ad7)
- add agent template marketplace and simplify SDK generator (3873ec4)
- Regional sync, auto curation, and audit store improvements (cae555b)
- Nomic phase improvements, legacy API compat, and UI enhancements (fa09c43)
- Multi-region support, nomic gates, runbooks, and tests (647b9e3)
- enhance RLM factory with mode selection and add memory profiler (86f81dd)
- add explicit column lists and task decomposition (3b5c43a)
- add circuit breaker support to chat connectors and pattern-based agent selection (967c944)
- **accounting:** add usage event emission for cost tracking (a7d9b5d)
- **accounting:** add circuit breaker protection to invoice processor and AP automation (ffea34e)
- **accounting:** add LLM-powered expense categorization (1d7b47e)
- **accounting:** implement actual QBO API calls in expense tracker (291caab)
- **accounting:** add handlers, OCR implementation, and tests (1f3b7fc)
- **accounting:** add Gusto payroll connector (633126d)
- **accounting:** add Plaid connector and reconciliation service (53b1e28)
- **accounting:** add QuickBooks Online connector (0ddb1b0)
- **admin:** add full CRUD support to persona editor (441e3f2)
- **agents:** add test generation agent and workflow templates (4ecc281)
- **agents:** update agents, auth, and connectors (4a5faf6)
- **analysis:** add three new bug detection patterns (2521fee)
- **analysis:** add secrets scanner and update models (b915b5e)
- **analysis:** add bug detector and codebase understanding agent (cea784b)
- **analysis:** add call graph analysis module (e89875e)
- **analysis:** add code intelligence with tree-sitter AST parsing (9befeeb)
- **analysis:** add codebase security analysis module (0a055fe)
- **analytics:** add debate analytics module (a1b1eeb)
- **analytics:** add deliberation analytics endpoints and debate store (b546dea)
- **analytics:** add flip detection analytics endpoints (ae8de8e)
- **analytics:** add token usage analytics endpoints (43a27a4)
- **api:** add OpenAPI specs for codebase analysis endpoints (1ba7ffd)
- **api:** add OpenAPI endpoints for control plane and decisions (75159b5)
- **api:** Wire RLM streaming and Knowledge Mound curation endpoints (d83a629)
- **ar:** add email integration for payment reminders and invoices (3f0c6c0)
- **audit:** add dependency analyzer and codebase auditor (976dbed)
- **audit:** add AI Systems Auditor for LLM/ML security (5fc7b68)
- **auth:** add login links to sidebar, header, and inbox page (202fa3f)
- **billing:** add enterprise metering service (417e6e8)
- **cache:** add Redis backend for export cache (030bb27)
- **chat:** add resilient HTTP request helper to chat connector base (80b682e)
- **checkpoint:** add ARAGORA_DB_BACKEND support to checkpoint store (4e535d5)
- **cli:** add control-plane command and update SDK descriptions (bd9e943)
- **cli:** add validate-env command and enhance health endpoint (029537f)
- **code-review:** implement GitHub PR integration (84c4847)
- **codebase:** add SAST scanner and code intelligence API (e2f82bd)
- **coding:** add smart test generator module (a931dc4)
- **coding:** add documentation generator and refactoring workflows (7ebbf26)
- **connectors:** add legal/devops exports and tests (c3a549a)
- **connectors:** complete Teams and Discord chat connector methods (944e77b)
- **connectors:** add email sync infrastructure (dfd6a70)
- **connectors:** add Xero accounting connector and sync version (c35136c)
- **connectors:** add marketplace connectors foundation (ad3d891)
- **connectors:** add Monday.com enterprise connector (0310fbb)
- **connectors:** add calendar, payments, and shipping integrations (d8d82b1)
- **connectors:** add e-commerce platform integrations (b5094bc)
- **connectors:** add PagerDuty and DocuSign integrations (c2a6b53)
- **connectors:** add Outlook email connector (b6013cc)
- **connectors:** add Salesforce CRM and Teams enterprise connectors (04a14e0)
- **connectors:** add circuit breaker to Gmail connector (33d878d)
- **connectors:** expand document format support (fc33121)
- **connectors:** add health scoring endpoint (fd33139)
- **context:** add channel context auto-fetch for deliberations (28987fc)
- **control-plane:** implement SME gap remediation (33daa4c)
- **control-plane:** add enterprise control plane enhancements (6dc0e75)
- **control-plane:** enhance handler with deliberation chaining (3d75baf)
- **control-plane:** add deliberation chaining for multi-step workflows (4f38a7a)
- **control-plane:** enhance control plane page and orchestration handlers (ff44519)
- **control-plane:** add WebSocket streaming, channels, deliberation tracker, and audit log (2f3ca66)
- **control-plane:** add fleet status, activity feed, and deliberation integration (df05a2d)
- **control-plane:** Add regional leader election for multi-region deployments (94f4e70)
- **control-plane:** add regional task routing and claim methods (83c2209)
- **control-plane:** centralize distributed state checking (2d5686d)
- **core:** enhance memory coordination and debate subsystems (f6ec501)
- **db:** add PostgreSQL schema and improve Gmail analyzers (ae3eeea)
- **debate:** enhance identity debate with more agents and better context (8c2908c)
- **debate:** add pattern selection telemetry and cross-cycle learning (a25e252)
- **deploy:** enable PostgreSQL backend for production EC2 (6d8dd9b)
- **deploy:** add Helm charts and systemd configuration (7f6312d)
- **deploy:** add multi-region deployment configuration (93783bf)
- **deploy:** enhance PostgreSQL and multi-instance deployment (2567a74)
- **docs:** add control plane documentation and identity module (6141817)
- **durability:** add multi-instance requirements for marketplace store (066e85b)
- **email:** add email intelligence services (5c308d9)
- **email:** add email debate service and API handlers (beb4158)
- **email:** add smart categorization and batch operations (c4da3a6)
- **embeddings:** add exception hierarchy and circuit breaker support (4269351)
- **events:** implement connector webhook event emission (dc2b576)
- **expense-tracker:** add circuit breaker protection (5959566)
- **export:** add batch export with SSE progress streaming (e118fb6)
- **github:** add PR review API handler (d85740a)
- **handlers:** add legal and devops HTTP handlers (4acb634)
- **handlers:** add streaming response support and memory coordinator improvements (8d116d2)
- **handlers:** wire services to Phase 2 handlers (0d0e3ec)
- **handlers:** graduate 11 handlers to STABLE status (47a5653)
- **handlers:** graduate Phase A handlers to stable (5a2a320)
- **hardening:** add resilience documentation and failure path tests (#18) (ab1a96b)
- **http:** Add async timeout wrappers to aiohttp sessions (33078fa)
- **ide:** enhance VSCode extension with Kilocode-style features (df990ea)
- **ide:** enhance VS Code extension with control plane views (c8ca372)
- **ide:** add IDE integrations (8bc6945)
- **inbox:** add multi-account inbox and smart email processing (9ec6bcf)
- **inbox:** add unified command center for email triage (dcf9382)
- **inbox:** add follow-up tracker and snooze recommender services (7539fee)
- **inbox:** add shared inbox management for teams (6495446)
- **inbox:** add intelligent inbox feature with email detail modal (968d807)
- **infra:** update integrations, storage, ranking, and core modules (6b36060)
- **integration:** wire email services with handlers, persistence, UI, and tests (cd64ae4)
- **integrations:** add platform resilience and observability (6192a67)
- **km:** enhance bidirectional adapters and operations (09d263f)
- **km:** add production hardening with input validation and resource limits (fa8f93c)
- **km:** implement Phase 3 store adapters for dedup/prune ops (f7c6c82)
- **knowledge-mound:** integrate Phase A2 mixins into facade (afc2efb)
- **knowledge-mound:** implement Phase A2 operations (c037a27)
- **modules:** update MCP, ML, workflow, and supporting modules (2138714)
- **mound:** add Phase A2 HTTP handlers for Knowledge Mound (e472fdf)
- **nomic:** add feature development agent and approval workflow (ccb0362)
- **nomic:** add task decomposition integration tests and gmail handlers (e6d753f)
- **oauth:** add Microsoft, Apple, and OIDC providers (1b0c149)
- **observability:** add PostgreSQL audit logging backend (d713b23)
- **observability:** wire up circuit breaker metrics to prometheus (59bb54a)
- **observability:** add tracing to workflow engine and consolidate debate logging (34e2179)
- **observability:** add structured logging to control plane (cd3c5ad)
- **openapi:** add OpenAPI endpoint schemas for email and accounting (279d722)
- **ops:** Add deployment validation tooling (04d7ccf)
- **orchestration:** add unified orchestration API for control plane positioning (f15b7b9)
- **perf:** integrate DebatePerformanceMonitor with round tracking (e23d627)
- **phase2:** add codebase security handlers and OpenAPI specs (7c7760d)
- **platform:** add platform health endpoint and helper functions (1b59ec7)
- **positioning:** establish "control plane for multi-agent deliberation" identity (c149a87)
- **qbo:** add retry logic with exponential backoff (29a6035)
- **queue:** add DLQ management and job cleanup endpoints (20e5268)
- **resilience:** emit metrics on circuit breaker state transitions (033e940)
- **rlm:** prioritize TRUE RLM over compression fallback (7548c82)
- **rlm:** add production hardening with resource limits and timeouts (2f6df4a)
- **routing:** wire channel handlers through DecisionRouter (4a5c1f2)
- **scripts:** add SQLite to Supabase migration script (20ad941)
- **scripts:** add code intelligence benchmark script (69b798c)
- **scripts:** add code intelligence demo script (937ace0)
- **scripts:** add Gmail Takeout analyzer for AP users (ddcccb0)
- **sdk:** update TypeScript SDK and packages (605b0c1)
- **security:** add Phase 3 intelligence features (35a4f96)
- **security:** add threat intelligence service (e90a50b)
- **security:** add secrets scanning API endpoints (5a6a054)
- **security:** add SOC2 compliance schedulers and anomaly detection (208045d)
- **security:** add SecuritySettings for SOC 2 compliance (0d0b51c)
- **security:** wire RBAC middleware into request flow (74f9f6d)
- **server:** add Gmail, Outlook, shared inbox, and cost visibility handlers (97e4be2)
- **server:** register Phase 2 handlers in aiohttp server (5c887da)
- **server:** wire up email services and dependency analysis handlers (8b860a5)
- **server:** update handlers and middleware (d2a2ad5)
- **server:** Add API versioning migration script (bea1439)
- **services:** enhance email prioritization and sender history services (556be3e)
- **slack:** add reactions, channel/user discovery, modals, and pinned messages (147f038)
- **slo:** extend SLOs for RLM, workflow, control plane, and bots (364bcce)
- **soc2:** add comprehensive SOC 2 compliance modules (6c2db11)
- **storage:** add database persistence layer for accounting (ff0c4a5)
- **storage:** Add PostgreSQL backend support for storage stores (031ccfd)
- **stream:** add usage stream emitter for cost tracking (c1a21ae)
- **teams:** add rate limiting to Teams bot handler (c901a7b)
- **telegram:** add rich media and inline query support (03bd91f)
- **test:** add comprehensive test extra dependencies (b05fc80)
- **tests:** add control plane E2E tests and fix observability signatures (7e660bc)
- **tools:** add GitHub handlers to API docs generation (88e0362)
- **tracing:** add distributed trace propagation to HTTP clients (f727d74)
- **typing:** add strict mypy to core workflow modules (7952a61)
- **ui:** add accounting dashboard and inbox components (86aadf9)
- **ui:** restructure audit pages and add shared inbox (0de356a)
- **ui:** improve connectors, uncertainty pages and add inbox components (8e1ce7c)
- **ui:** add multi-agent code review workflow (e375af9)
- **ui:** add cost visibility dashboard (10f6ca9)
- **ui:** add one-click security scan wizard (48e25c2)
- **ui:** add inbox triage UI components (f034f69)
- **ui:** add command center dashboard (78fab8e)
- **ui:** add codebase security dashboard and inbox multi-agent analysis (1653d84)
- **ui:** add Receipt Delivery UI for channel distribution (dfb6de9)
- **ui:** add Connector Health dashboard enhancements (72f2029)
- **ui:** add Knowledge Quality metrics to KnowledgeExplorer (9f4b6b5)
- **ui:** extend business questions and add control plane components (faf400a)
- **ui:** add deliberations section to support control plane positioning (e64c40b)
- **ui:** make debate input the primary view with ASCII art hero (3e7a3cd)
- **ui:** update components and pages (5bcec25)
- **ui:** add SSR-safe theme system with context provider (e378c1e)
- **ui:** add security admin panel and enterprise tests (004940b)
- **ui:** add Nomic loop admin control panel (a2ec35f)
- **ui:** expose Belief Network visualization to standard users (dff9400)
- **ui/api:** add audit trail components and API to support control plane positioning (9cc366a)
- **workflow:** add ConnectorStep for workflow-connector integration (8e2b735)
- **workflow:** add invoice and expense processing workflow templates (24df5b1)
- **workflow:** add code review workflow templates (bbc4ef2)
- **workflow:** add PR review workflow template (d2f8048)
- **workflow:** add security scanner and feature implementation templates (9c0432c)
- **workflow:** harden engine with timeouts, LRU cache, and auto-recovery (f535635)
- **workflows:** wire connectors into workflow templates (0b0870a)

### Bug Fixes

- Return JSON instead of HTML for server errors (b641393)
- update and skip PagerDuty tests for new dataclass structure (d789495)
- wrap useSearchParams in Suspense for admin/users page (8836a90)
- complete TODO comments across codebase (2b6de83)
- wrap useSearchParams in Suspense for static export (18c3adc)
- update OnCallSchedule test to use User object (8a5842c)
- add Authorization header to debate API calls (45f6197)
- add missing methods to audit log SQLiteBackend (e1342d8)
- ensure retry_after is at least 1 second (92e68f4)
- fix DecisionRequest API usage in deliberation (b5f477e)
- fix import names in cross_platform_analytics handler (10e0949)
- resolve mypy errors in audit log and user store (3d9215f)
- resolve mypy errors in server handlers (2792623)
- resolve mypy errors in trackers and connectors (63e570c)
- resolve mypy errors in services and connectors (400a08d)
- add missing lib/utils.ts for cn() helper (59e1682)
- use correct endpoint for user profile in OAuth flow (5de1639)
- resolve mypy errors in walmart and shipstation connectors (46fbdbf)
- resolve mypy type annotation errors across services and connectors (a02b515)
- use window.location directly for OAuth callback params (4d21b3e)
- resolve mypy type errors across multiple modules (263a392)
- use query params instead of URL fragments for OAuth tokens (4af3b3b)
- improve email handler thread safety and async patterns (9b5a762)
- type annotations and test improvements (2e1bf3b)
- handler improvements and documentation updates (09c5a57)
- handler return types and documentation updates (000ed95)
- correct path parsing indices for v1 API routes (07b212b)
- correct path segment indices in extract_path_param usages (b00d668)
- correct decision handler path parsing and update tests (73d8a1c)
- update handler test paths to use /api/v1/ prefix (4489db6)
- update RLM handler path parsing for /api/v1/ routes (45b587d)
- update all handler tests to use /api/v1/ routes (37a55ac)
- update Code Intelligence tests and fix call_graph SourceLocation usage (ca238e3)
- update evidence handler tests to use /api/v1/ paths (bc860dd)
- update broadcast handler path parsing for /api/v1/ routes (b98c299)
- correct path parsing for /api/v1/ routes in debate handlers (8d8ca3a)
- force template loading before baseline count in test_categories (dd9e1c6)
- update docstrings and add triage rules panel (584ade1)
- update graph debates tests to use /api/v1/debates routes (4ab6a7e)
- update handler routes to v1 and fix deliberations import bug (ac6553f)
- add contents write permission for release creation (86c495a)
- add missing validate_string function to validation module (ff9f917)
- correct type ignore codes for sqlite row access (665e310)
- thread-safe config read and type annotations (5de09af)
- add thread-safety to email handlers and expand TypeScript API (01d277f)
- add type ignores and improve k8s graceful shutdown (5f6171c)
- cleanup pending changes across codebase (bdb68c0)
- Add missing columns to SELECT explicit column lists (d9c95a2)
- Replace SELECT * with explicit columns in UsageRepository (0fc7f27)
- Add logging to silent exception handlers (454449c)
- mock aiohttp in status command test (4ccd9e9)
- **a11y:** add ARIA attributes to UI components (9e1c600)
- **api:** add non-v1 health routes for frontend compatibility (e1d8479)
- **api:** continue fixing versioned API path issues in handlers (eb9389e)
- **api:** update handlers and tests to use versioned API paths (/api/v1/) (e2a489a)
- **auth:** add v1 routes to auth exemption for OAuth flow (a15d67d)
- **auth:** add redirect from /login to /auth/login (acd6689)
- **benchmarks:** correct mock configurations for 1000x speedup (e15131f)
- **billing:** use timezone-aware datetime defaults in Organization (b1ae46b)
- **build:** remove dynamic audit/[id] route for static export (18a307a)
- **build:** replace dynamicParams with generateStaticParams for static export (3e08abe)
- **build:** fix type errors for static export (a600e4b)
- **ci:** add code-intel dependency to release workflow tests (c2c3a9d)
- **ci:** resolve test failures in repositories and E2E tests (33deaf6)
- **ci:** address security and type safety issues (bfa1359)
- **ci:** update Node.js 18->20 and fix port conflicts in workflows (f0c2d3d)
- **ci:** add credential check for Vercel deployment (3cc6c4a)
- **ci:** improve CI/CD workflows robustness (28e14c8)
- **cleanup:** ensure embedding cache cleaned up on all exit paths (5f76504)
- **code-reviewer:** implement pattern-based reviewers with Agent ABC compliance (ad38eee)
- **codebase-agent:** implement Agent ABC abstract methods for specialist agents (4a18b11)
- **connectors:** formatting and reliability improvements (04d7408)
- **core:** improve formatters, debate config, and analysis tools (41f36e2)
- **core:** add security check for OIDC and type annotations (1ca478f)
- **debates:** update _extract_debate_id for v1 routes and fix test paths (6efb9d1)
- **debates:** update export URL parsing for v1 API routes (69033b4)
- **deploy:** resolve EC2-1 crash and frontend TypeScript errors (df31e4e)
- **distributed:** add distributed state checks to middleware (ea7c1ba)
- **distributed:** improve distributed state error handling (6c732ba)
- **docs:** regenerate openapi.json with correct schema generator (3d2caf7)
- **email:** add thread-safety to remove_vip handler (f3ec725)
- **frontend:** add auth checks to prevent 401 errors (6a53a8a)
- **gauntlet:** properly encode JSON body in RFC 7807 error responses (a12800b)
- **handlers:** add missing can_handle methods to feature handlers (81d08ee)
- **handlers:** add missing can_handle method to AdvertisingHandler (b4a199f)
- **handlers:** improve auth, inbox, and feature handlers (214c7fb)
- **hero:** improve auth error message with login link (8c1ea01)
- **lint:** eliminate all ESLint warnings (6257bed)
- **lint:** reduce ESLint warnings from 129 to 22 (a9156d1)
- **lint:** reduce ESLint warnings in test files (e8eabff)
- **oauth:** add shared OAUTH_JWT_SECRET across EC2 instances (1ef036f)
- **oauth:** improve state validation fallback and add debug logging (7963436)
- **oauth:** add JWT-based state store for multi-instance deployments (4b269e6)
- **oauth:** support non-v1 OAuth callback routes (1d1b4c4)
- **oauth:** Enable Google OAuth with Next.js API rewrites (be7c8af)
- **scripts:** handle string message IDs in Gmail analyzer (92a4d30)
- **sdk:** correct repository URL to match GitHub org (31de13b)
- **security:** extend SAML env check to staging and improve validation (873c910)
- **security:** enforce encryption in production and add RBAC to notifications (e168792)
- **server:** dependency analysis and OpenAPI helper updates (48e5d0e)
- **services:** add resilience improvements and connection pooling (d4e312c)
- **storage:** handle float timestamps in user datetime fields (a0a6ee3)
- **test:** use AsyncMock for async generate_sbom method (c39ae0c)
- **test:** fix API versioning and establish performance baseline (fbd7627)
- **test:** skip Redis revocation test when redis not installed (54efaac)
- **tests:** fix test failures and add slow markers (b01aba1)
- **tests:** skip entire TestExplainabilityBatchJobPersistence class (7a22d91)
- **tests:** skip batch job memory test that references removed internal API (799e52f)
- **tests:** skip slow comprehensive scan test that times out in CI (9e740c4)
- **tests:** skip test_create_envelope needing async mock fix (cf90c06)
- **tests:** skip DocuSign tests needing async mock fixes (d15d9e4)
- **tests:** correct CodeAnalystAgent role expectation (41b615a)
- **tests:** correct SLARequirement import in control plane e2e tests (3f26ecc)
- **tests:** add missing connector categories to valid set (c829a58)
- **tests:** rename duplicate test files in features directory (b99057f)
- **tests:** rename duplicate test_codebase_audit.py to avoid pytest conflict (6ca9e28)
- **tests:** use caplog instead of mock for RLM factory logging test (d262b7f)
- **tests:** increase single_round_max_sec SLO to 12s (ac8104b)
- **tests:** update advertising connector tests for raw cent values (fcf5ee6)
- **tests:** update code_reviewer tests for current API (c19cf4f)
- **tests:** update API workflow tests to use /api/v1/ routes (7a7a0c1)
- **tests:** address skipped tests from issue #19 (1351c31)
- **tests:** update all debates handler tests to use v1 API routes (9179e76)
- **tests:** update debates handler tests to use v1 API routes (c166ae2)
- **tests:** update Slack connector and debate rounds tests (f4fe7b1)
- **tests:** skip entire calibration database test module (7329951)
- **tests:** skip FetchAll tests - sqlite3.Row comparison issue (942ba4e)
- **tests:** skip FetchOne tests - sqlite3.Row comparison issue (cb724b3)
- **tests:** skip calibration database transaction tests - Row comparison issue (a62ee99)
- **tests:** skip audio engine integration tests - fail in CI (7a416f4)
- **tests:** skip EdgeTTS tests - fail in CI environment (1ec951d)
- **tests:** skip billing URL encoding test - @ vs %40 difference (748d0b4)
- **tests:** skip AutonomicExecutor critique tests - mock issue in CI (a183946)
- **tests:** skip SAML production test - error message format changed (31a22be)
- **tests:** skip AuditStore event logging tests - empty results in CI (07b64d9)
- **tests:** skip LegalAuditor test class - API changed (aa8cb81)
- **tests:** skip arena builder tracking test with mock issue (061dd55)
- **tests:** skip postgres pool resilience tests on Python < 3.11 (30c46f8)
- **tests:** skip arena builder event hooks test (0be6542)
- **tests:** unskip 3 tests with outdated skip reasons (1b9a7e8)
- **tests:** skip OpenRouter test with changed default role (33a422c)
- **tests:** skip ML search test that fails in CI (e4dfd89)
- **tests:** skip ML embed test that fails in CI (6887a32)
- **tests:** skip false positive SQL injection test (091da9d)
- **tests:** mock Redis store in mark_result_sent test (90b7ccd)
- **tests:** skip flaky RLM logging test (b53bb45)
- **tests:** skip rate limit test with missing export (a31c5a3)
- **tests:** improve test stability and fix flaky tests (7babd9f)
- **tests:** skip migration test for unimplemented --alembic flag (039d9b2)
- **tests:** use temp directory for marketplace test and add --alembic flag (a7747f9)
- **tests:** update route count and skip unimplemented multi-tenant tests (96affce)
- **tests:** update analytics dashboard routes count assertion (fcef5a8)
- **tests:** enable Discord connector tests with correct httpx mocking (9cb7887)
- **tests:** skip discord test module + regenerate API docs (f45fdb5)
- **tests:** update Teams connector tests for _http_request refactor (7296939)
- **tests:** fix Discord connector tests by using correct mock methods (513570c)
- **tests:** fix 3 of 4 skipped TODO tests and add audit documentation (bdd6d8f)
- **tests:** skip entire Discord send message test class (4b2d5a9)
- **tests:** skip discord mock test with AsyncMock comparison issue (2a65e1e)
- **tests:** skip entire SSO test module due to API changes (590cd77)
- **tests:** fix enterprise SSO tests with proper config (f05dcd4)
- **tests:** skip learning efficiency test with negative result (559ac75)
- **tests:** skip SSO tests with config issue (139a2da)
- **tests:** skip entire stress test class on CI (803ae75)
- **tests:** skip flaky performance test on CI (e534cdc)
- **tests:** skip pruning test with mock issue (63e696b)
- **tests:** skip e2e debate test with Arena env issue (3fb5ea6)
- **tests:** skip another flaky visibility test (07078e6)
- **tests:** skip control plane workflow tests when redis unavailable (923ec80)
- **tests:** skip flaky grant_access_with_expiry test (fd72bf7)
- **tests:** skip all tfidf tests when scikit-learn unavailable (47dc3f0)
- **tests:** Fix regional sync tests for mock state store requirement (ad6aae4)
- **tests:** update RLM limiter tests for new default (250df9d)
- **tests:** Update gauntlet stress tests for correct config params (b7d05af)
- **tests:** skip tfidf test when scikit-learn unavailable (734b9b6)
- **tests:** update durability test to expect DistributedStateError (c6db555)
- **tests:** handle timezone-naive datetimes in DR test (e1ac85a)
- **tests:** correct import path in test_auth_v2.py (6a5f7a9)
- **tests:** correct import path for User/Workspace classes (89c5e68)
- **tests:** handle missing google-auth library in CI (fe4b958)
- **tests:** add tolerance to flaky RPO timing test (2d6014f)
- **tests:** use unique circuit breaker names in degradation test (22fab1b)
- **types:** resolve batch of mypy type errors (71ae248)
- **types:** update intervention handler return types to HandlerResult (e1c8b66)
- **types:** resolve mypy type errors in core modules (fc4c19a)
- **types:** fix inbox_command.py type errors (75348ec)
- **types:** add type ignore comments to reduce mypy errors from 307 to 102 (06be49f)
- **types:** add missing properties to ApiCloudFile interface (2a443eb)
- **types:** resolve all @typescript-eslint/no-explicit-any errors (da6d070)
- **types:** add type: ignore comments for mixin method calls (30b0ea6)
- **types:** add type ignores for dict access in connectors handler (390be23)
- **types:** add type ignores for table attribute access in document connector (9c6c7f5)
- **types:** add type ignores for lazy-loaded optional attributes (747923f)
- **types:** add type ignores for override and attr-defined errors (98c22fc)
- **types:** add type ignores for conditional type assignments (bfba8a5)
- **types:** replace callable with Callable[..., Any] (2f150aa)
- **types:** use enum values instead of strings for typed lists (62e94a3)
- **types:** add type annotations for untyped variables (5510299)
- **types:** add type ignore comments for lazy imports (ee51728)
- **types:** add missing methods to EncryptionService and JobQueue (fdde836)
- **types:** correct all status_code= to status= in cross_pollination (6d62137)
- **types:** correct error_response parameter and remove unused import (78d2ec0)
- **types:** resolve mypy errors in 5 modules (6ab5107)
- **ui:** wrap provenance page with Suspense for useSearchParams (e6b7a90)
- **ui:** improve type safety and add quality tab to knowledge explorer (8472490)
- **ui:** resolve ESLint warnings across components, hooks, and tests (154b42e)
- **ui:** correct UploadFile property access in FileUploader (8fd677c)
- **whatsapp:** correct respond_to_interaction return type (4d6c5f9)
- **workflow:** add transitions to marketing templates (f759111)

### Performance Improvements

- replace SELECT * with explicit columns in snooze_store (b6cb99c)
- fix slow database queries across storage modules (b589622)
- **ci:** parallelize test suite with xdist and category splits (5dfbf4c)

### Code Refactoring

- replace deprecated datetime.utcnow() with datetime.now(timezone.utc) (a5e85a9)
- rename auth_v2.py to user_auth.py for clarity (5f0c9b6)
- **client:** modularize SDK with separate API classes (f90dd91)
- **discord:** use HTTP helper for update_message (63b210c)
- **discord:** use shared HTTP request helper (2c4cab1)
- **events:** Extract handler mixins from cross_subscribers (0a48bbe)
- **landing:** update hero tagline and reduce font size (e57d4a0)
- **storage:** Enhance share_store with backend abstraction (65ec77f)
- **storage:** Complete decision_result_store backend support (0a33f04)
- **storage:** Improve decision_result_store parameter handling (5d3308a)
- **teams:** use shared HTTP request helper (fd3736e)

### Documentation

- sync API documentation (52e08ed)
- sync OpenAPI spec with latest handlers (3fd2750)
- regenerate OpenAPI spec for v2.1.10 release (0ed44d2)
- regenerate API documentation for v2.1.10 release (af58c48)
- add schema migrations and rollback strategy section (f4cbd67)
- regenerate OpenAPI specs for v2.1.10 release (4847f4a)
- comprehensive documentation updates (080e707)
- regenerate API documentation for release (82bde08)
- add comprehensive accounting & financial automation documentation (0edea80)
- add accounting connector guides and inbox user documentation (2b431de)
- update documentation and add bug detector module (b08d89d)
- update API documentation and endpoints (421f224)
- update documentation site with new features and examples (3249308)
- update documentation for new features (4ef3be5)
- update documentation for audit-GitHub bridge and Outlook handlers (a50e85d)
- update documentation for Phase 2 features (baaf1c2)
- add coding assistance and PR review documentation (2e99552)
- add codebase analysis and email prioritization guides (1a7c7a7)
- reorganize and clean up documentation (8a30477)
- update positioning to control plane for multi-agent deliberation (ba4afad)
- update positioning to "control plane for multi-agent deliberation" (298acca)
- update STATUS.md with v2.1.11 type safety release notes (c1f5de2)
- update CHANGELOG for vscode-v0.1.0 (03e07cc)
- add documentation site and integration guides (4dc1a30)
- add ADR 016 for marketplace architecture (98c4c24)
- add marketplace documentation and ADR (0f2454a)
- add SOC2 compliance documentation (75ddf71)
- regenerate API docs (2f926d6)
- Add ops module to architecture documentation (dc94116)
- add incident runbooks and demo seeding script (5f2a5e8)
- Update skipped test reasons to reference actual implementations (2b7fc4b)
- add updated enterprise control plane feasibility study (b457e25)
- Update architecture with extracted modules and PostgreSQL stores (fb201f4)
- add channel production readiness audit results (5597868)
- add security env vars to ENVIRONMENT.md (2473b78)
- **about:** enhance hero description with approved positioning (ffabf96)
- **about:** update platform stats to current values (8df6854)
- **api:** update Postman collection with new endpoints (21e89ab)
- **api:** update OpenAPI specs and Postman collection (f7cf061)
- **observability:** add platform integration metrics documentation (d0b537a)
- **security:** update pentest scope documentation (c816aa0)
- **security:** add penetration testing requirements documentation (27f112b)

### Tests

- add feature handler tests for transcription, gmail_labels, rlm (a37b731)
- add feature handler tests for codebase_audit, unified_inbox, connectors, pulse (9b57de4)
- add feature handler tests for advertising, CRM, ecommerce, support, analytics (f3bc363)
- add multi-tenant isolation tests for accounting services (01d2ec7)
- add failure scenario tests for accounting services (bd30684)
- add email connector and invoice processor tests (58868dd)
- fix dependency analysis tests for HandlerResult response format (5ca1c4e)
- skip call graph tests when networkx not installed (57dfd4c)
- skip TestGraphDebatesHandlerInit (route versioning - see #19) (f370331)
- skip entire leaderboard test module (route versioning - see #19) (d089328)
- skip TestLeaderboardView (route changed to /api/v1/leaderboard-view) (de02890)
- skip TestLeaderboardViewHandlerInit (route changed to /api/v1/leaderboard-view) (a4f877d)
- skip entire calibration_handler test module (multiple CI failures) (f2d016b)
- skip test_can_handle_debates_list (can_handle returns False in CI) (47d6e5a)
- skip TestCalibrationHandlerInit (can_handle returns False for calibration routes) (2981467)
- skip TestSecurityHardeningVerification (security routes not handled in CI) (9996048)
- skip TestOAuthFlow (can_handle returns False for OAuth routes) (87ad6d1)
- skip test_memory_handler_rate_limits (rate limiter not triggering in CI) (525d23b)
- skip TestHandlerPathCoverage (OpenAPI spec vs handler sync issue) (7b4afb2)
- skip test_accepts_without_jwt_library (fail-closed behavior change) (45ccb8e)
- skip test_database_pool_reuses_connections (string vs int comparison) (c59ceed)
- fix Teams connector tests for replies and search (b519e99)
- update gsheets and replay handler tests (e7c65c7)
- update Salesforce and debate rounds tests (2d210bf)
- add load testing scenarios and connector tests (77465e3)
- update protocol tests for new 8-round defaults (926502b)
- skip TestCalibrationWeighting (weight returns 1.0 vs expected >1.0) (fc5cfa3)
- add comprehensive tests for RLM and Genesis modules (4d4c1a3)
- fix multi-tenant tests to match actual API (acc7db9)
- add comprehensive tests for marketplace module (6ad2936)
- remove outdated skip decorators from working tests (d26f1b9)
- add Debate Engine E2E tests (af13feb)
- add cross-feature integration tests for nomic loop (22d5cd8)
- improve benchmark test performance and add embedding service tests (d898dfc)
- add comprehensive E2E security tests (4a1a2a8)
- **accounting:** enhance accounting test coverage (0b7a13c)
- **chaos:** add comprehensive chaos testing suite (1a4dc4e)
- **connectors:** add comprehensive accounting connector tests (9ed14d4)
- **control-plane:** Add tests for regional leader election (99dac08)
- **e2e:** enable debate lifecycle tests for implemented features (8ef34a1)
- **email:** add comprehensive email handler unit tests (c5acf2e)
- **gauntlet:** Add stress tests for adversarial validation (eef9959)
- **handlers:** add usage metering handler tests (3a407b7)
- **handlers:** add tests for critique, routing, and explainability handlers (0c994c5)
- **inbox:** add multi-account integration tests (1bd1f4d)
- **knowledge:** add comprehensive Phase A2 mound ops tests (35cc7ba)
- **ml:** add ML router integration tests (f62dc84)
- **queue:** add DLQ endpoint tests (54576d5)
- **resilience:** add comprehensive end-to-end resilience integration tests (041b174)
- **rlm:** add comprehensive training pipeline integration tests (ec0efc8)

### Maintenance

- Fix DebatesHandler path normalization for version-stripped paths (1a28340)
- Fix POST /api/debates endpoint - check normalized paths (7794a38)
- maintenance updates across codebase (f7ecc30)
- regenerate API docs with latest handlers (aabf0a5)
- regenerate docs with correct export scripts (938cb99)
- regenerate OpenAPI specs with all handlers (243a478)
- Enable OAuth debug mode to show actual error details (5dbac2e)
- Add detailed logging to OAuth callback for debugging (ecf4359)
- Fix systemd env config formatting in deploy workflow (32f859d)
- Fix OAuth callback redirect and add JWT state debugging (5383b5d)
- fix docs sync and test base formatting (d3b1a9b)
- update GitHub OpenAPI schema (5fd4f4a)
- add remaining OpenAPI endpoints and fix tests (1502436)
- update templates, docs, and add PII redactor service (211ed6f)
- Fix OAuth login URLs to use API_BASE_URL (2b1590a)
- Fix OAuth to use API_BASE_URL from config (3116f3a)
- Fix mypy type errors in marketplace, parser, and scheduler (d5c3288)
- fix imports and mock patterns (44038e9)
- fix type annotations and remove unused prop (2105128)
- remove CORS debug logging (43692d9)
- change CORS logging to INFO level for production visibility (feac627)
- add CORS logging to diagnose missing headers (a4a138f)
- docs/test: add ML router integration tests and pentest docs (e5d63ee)
- SDK refactor and knowledge mound test mock fixes (8a89294)
- Add dynamic port selection for Gmail OAuth callback (9bdd400)
- type ignores and landing page copy updates (16d5814)
- Fix StructuredLogger calls in orchestrator.py (cb23a3d)
- Add AWS Secrets Manager support for Gmail OAuth credentials (087fd04)
- Add checkpoint/resume integration tests (e2d073a)
- Add regional sync tests and final decision store cleanup (8242244)
- minor updates to nomic debate phase and postgres store (d12275c)
- minor updates to webhook registry and e2e tests (11f75ab)
- Add PostgresEloDatabase integration tests and update docs (e2bd9be)
- remove duplicate test_auth_v2.py (1736636)
- Extract reusable components from debate_rounds.py (13a713b)
- Extract reusable components from debate_rounds.py (29b30b0)
- Add PostgresContinuumMemory integration tests (62f7a93)
- bump version to 2.1.10 (2d11107)
- **accounting:** export all accounting connectors (0bad087)
- **analysis:** update codebase module exports (da45492)
- **deps:** Bump testing group (pytest, coverage, etc.) (119bbb5)
- **deps:** Update websockets to <17.0 (252f3a4)
- **deps:** Update elevenlabs to <3.0 (ca53e7a)
- **deps:** Update redis to <8.0 (6d3c058)
- **deps:** Update black to <26.0 (c143e1f)
- **deps:** Update pytest-asyncio to <2.0 (914e772)
- **enterprise:** lock RBAC defaults and add production guards (836064f)
- **eslint:** migrate to flat config for ESLint 9 compatibility (83817c9)
- **frontend:** update hooks and components (1380cac)
- **frontend:** fix remaining workflow builder imports (7eb52df)
- **frontend:** prefix unused parameter with underscore (1424cf7)
- **frontend:** fix remaining unused imports in workflow components (32baf82)
- **frontend:** remove unused imports from React components (620b416)
- **frontend:** fix linting issues in TypeScript tests and pages (7f1754b)
- **infra:** update Dockerfile and Discord marketplace config (2a4d60d)
- **oauth:** add logging to callback page (fa5383b)
- **observability:** Export memory profiling utilities in __all__ (b41a3e4)
- **types:** fix type annotations and unused imports (59974a2)
- **types:** add type: ignore for cross-pollination handler (e679b0b)
- **types:** add type: ignore comments for integration handlers (3215cc0)
- **types:** add type: ignore comments for handlers and adapters (2e6f5b9)
- **types:** add type: ignore comments for dynamic method calls (a745f12)
- **types:** continue fixing mypy Module import errors (3d4dfb9)
- **types:** fix more mypy Module import errors (4989b55)
- **types:** continue reducing mypy Module errors (7e782fc)
- **types:** continue batch fixing Module import errors (313a188)
- **types:** fix more mypy Module import errors (0f16541)
- **types:** continue batch fixing mypy Module import errors (a665386)
- **types:** batch fix more mypy Module import errors (3f04eef)
- **types:** continue reducing mypy Module import errors (eba066a)
- **types:** continue reducing mypy Module import errors (b50ac66)
- **types:** batch fix module import mypy errors (adfec66)
- **types:** continue mypy error reduction in connectors and ML (3b042fb)
- **types:** fix federation.py mixin attribute access errors (40415e3)
- **types:** continue mypy error reduction (c89dc91)
- **types:** reduce mypy errors with type annotations and ignores (4e3968f)

### CI/CD

- add Python SDK and VS Code extension publish workflows (4820f4e)
- add deployment workflows (3aa0abc)
- increase test job timeout to 40 minutes (75d317e)

### Code Style

- apply ruff formatting and fix syntax error (f1793ed)
- format job_queue_store.py (83f5dfe)
- **hero:** reduce hero text font sizes by ~4pt (b384e01)

### Contributors

- an0mium
- dependabot[bot]
- github-actions[bot]


## [vscode-v0.1.0] - 2026-01-22

### Features

- add thread-safety and resilience test coverage (0e0f0ad)
- add production hardening and performance optimizations (a3e96ee)
- add developer experience improvements (22949d8)
- add marketplace server handlers and CLI commands (2f75ad7)
- add agent template marketplace and simplify SDK generator (3873ec4)
- Regional sync, auto curation, and audit store improvements (cae555b)
- Nomic phase improvements, legacy API compat, and UI enhancements (fa09c43)
- Multi-region support, nomic gates, runbooks, and tests (647b9e3)
- enhance RLM factory with mode selection and add memory profiler (86f81dd)
- add explicit column lists and task decomposition (3b5c43a)
- add circuit breaker support to chat connectors and pattern-based agent selection (967c944)
- **admin:** add full CRUD support to persona editor (441e3f2)
- **agents:** update agents, auth, and connectors (4a5faf6)
- **analytics:** add flip detection analytics endpoints (ae8de8e)
- **analytics:** add token usage analytics endpoints (43a27a4)
- **api:** Wire RLM streaming and Knowledge Mound curation endpoints (d83a629)
- **auth:** add login links to sidebar, header, and inbox page (202fa3f)
- **cache:** add Redis backend for export cache (030bb27)
- **chat:** add resilient HTTP request helper to chat connector base (80b682e)
- **cli:** add validate-env command and enhance health endpoint (029537f)
- **connectors:** add Salesforce CRM and Teams enterprise connectors (04a14e0)
- **connectors:** add circuit breaker to Gmail connector (33d878d)
- **connectors:** expand document format support (fc33121)
- **connectors:** add health scoring endpoint (fd33139)
- **control-plane:** Add regional leader election for multi-region deployments (94f4e70)
- **control-plane:** add regional task routing and claim methods (83c2209)
- **control-plane:** centralize distributed state checking (2d5686d)
- **core:** enhance memory coordination and debate subsystems (f6ec501)
- **db:** add PostgreSQL schema and improve Gmail analyzers (ae3eeea)
- **debate:** add pattern selection telemetry and cross-cycle learning (a25e252)
- **deploy:** add Helm charts and systemd configuration (7f6312d)
- **deploy:** add multi-region deployment configuration (93783bf)
- **deploy:** enhance PostgreSQL and multi-instance deployment (2567a74)
- **durability:** add multi-instance requirements for marketplace store (066e85b)
- **embeddings:** add exception hierarchy and circuit breaker support (4269351)
- **export:** add batch export with SSE progress streaming (e118fb6)
- **handlers:** graduate 11 handlers to STABLE status (47a5653)
- **handlers:** graduate Phase A handlers to stable (5a2a320)
- **hardening:** add resilience documentation and failure path tests (#18) (ab1a96b)
- **http:** Add async timeout wrappers to aiohttp sessions (33078fa)
- **ide:** add IDE integrations (8bc6945)
- **inbox:** add intelligent inbox feature with email detail modal (968d807)
- **infra:** update integrations, storage, ranking, and core modules (6b36060)
- **integrations:** add platform resilience and observability (6192a67)
- **km:** enhance bidirectional adapters and operations (09d263f)
- **km:** add production hardening with input validation and resource limits (fa8f93c)
- **km:** implement Phase 3 store adapters for dedup/prune ops (f7c6c82)
- **knowledge-mound:** integrate Phase A2 mixins into facade (afc2efb)
- **knowledge-mound:** implement Phase A2 operations (c037a27)
- **modules:** update MCP, ML, workflow, and supporting modules (2138714)
- **mound:** add Phase A2 HTTP handlers for Knowledge Mound (e472fdf)
- **nomic:** add task decomposition integration tests and gmail handlers (e6d753f)
- **oauth:** add Microsoft, Apple, and OIDC providers (1b0c149)
- **observability:** wire up circuit breaker metrics to prometheus (59bb54a)
- **observability:** add tracing to workflow engine and consolidate debate logging (34e2179)
- **observability:** add structured logging to control plane (cd3c5ad)
- **ops:** Add deployment validation tooling (04d7ccf)
- **perf:** integrate DebatePerformanceMonitor with round tracking (e23d627)
- **platform:** add platform health endpoint and helper functions (1b59ec7)
- **queue:** add DLQ management and job cleanup endpoints (20e5268)
- **resilience:** emit metrics on circuit breaker state transitions (033e940)
- **rlm:** prioritize TRUE RLM over compression fallback (7548c82)
- **rlm:** add production hardening with resource limits and timeouts (2f6df4a)
- **routing:** wire channel handlers through DecisionRouter (4a5c1f2)
- **scripts:** add Gmail Takeout analyzer for AP users (ddcccb0)
- **sdk:** update TypeScript SDK and packages (605b0c1)
- **security:** add SOC2 compliance schedulers and anomaly detection (208045d)
- **security:** add SecuritySettings for SOC 2 compliance (0d0b51c)
- **security:** wire RBAC middleware into request flow (74f9f6d)
- **server:** update handlers and middleware (d2a2ad5)
- **server:** Add API versioning migration script (bea1439)
- **slack:** add reactions, channel/user discovery, modals, and pinned messages (147f038)
- **slo:** extend SLOs for RLM, workflow, control plane, and bots (364bcce)
- **soc2:** add comprehensive SOC 2 compliance modules (6c2db11)
- **storage:** Add PostgreSQL backend support for storage stores (031ccfd)
- **teams:** add rate limiting to Teams bot handler (c901a7b)
- **telegram:** add rich media and inline query support (03bd91f)
- **test:** add comprehensive test extra dependencies (b05fc80)
- **tests:** add control plane E2E tests and fix observability signatures (7e660bc)
- **tracing:** add distributed trace propagation to HTTP clients (f727d74)
- **typing:** add strict mypy to core workflow modules (7952a61)
- **ui:** update components and pages (5bcec25)
- **ui:** add SSR-safe theme system with context provider (e378c1e)
- **ui:** add security admin panel and enterprise tests (004940b)
- **ui:** add Nomic loop admin control panel (a2ec35f)
- **ui:** expose Belief Network visualization to standard users (dff9400)
- **workflow:** harden engine with timeouts, LRU cache, and auto-recovery (f535635)

### Bug Fixes

- add missing validate_string function to validation module (ff9f917)
- correct type ignore codes for sqlite row access (665e310)
- thread-safe config read and type annotations (5de09af)
- add thread-safety to email handlers and expand TypeScript API (01d277f)
- add type ignores and improve k8s graceful shutdown (5f6171c)
- cleanup pending changes across codebase (bdb68c0)
- Add missing columns to SELECT explicit column lists (d9c95a2)
- Replace SELECT * with explicit columns in UsageRepository (0fc7f27)
- Add logging to silent exception handlers (454449c)
- mock aiohttp in status command test (4ccd9e9)
- **a11y:** add ARIA attributes to UI components (9e1c600)
- **benchmarks:** correct mock configurations for 1000x speedup (e15131f)
- **billing:** use timezone-aware datetime defaults in Organization (b1ae46b)
- **cleanup:** ensure embedding cache cleaned up on all exit paths (5f76504)
- **core:** add security check for OIDC and type annotations (1ca478f)
- **distributed:** add distributed state checks to middleware (ea7c1ba)
- **distributed:** improve distributed state error handling (6c732ba)
- **email:** add thread-safety to remove_vip handler (f3ec725)
- **gauntlet:** properly encode JSON body in RFC 7807 error responses (a12800b)
- **oauth:** Enable Google OAuth with Next.js API rewrites (be7c8af)
- **scripts:** handle string message IDs in Gmail analyzer (92a4d30)
- **sdk:** correct repository URL to match GitHub org (31de13b)
- **security:** extend SAML env check to staging and improve validation (873c910)
- **security:** enforce encryption in production and add RBAC to notifications (e168792)
- **test:** skip Redis revocation test when redis not installed (54efaac)
- **tests:** update Slack connector and debate rounds tests (f4fe7b1)
- **tests:** skip entire calibration database test module (7329951)
- **tests:** skip FetchAll tests - sqlite3.Row comparison issue (942ba4e)
- **tests:** skip FetchOne tests - sqlite3.Row comparison issue (cb724b3)
- **tests:** skip calibration database transaction tests - Row comparison issue (a62ee99)
- **tests:** skip audio engine integration tests - fail in CI (7a416f4)
- **tests:** skip EdgeTTS tests - fail in CI environment (1ec951d)
- **tests:** skip billing URL encoding test - @ vs %40 difference (748d0b4)
- **tests:** skip AutonomicExecutor critique tests - mock issue in CI (a183946)
- **tests:** skip SAML production test - error message format changed (31a22be)
- **tests:** skip AuditStore event logging tests - empty results in CI (07b64d9)
- **tests:** skip LegalAuditor test class - API changed (aa8cb81)
- **tests:** skip arena builder tracking test with mock issue (061dd55)
- **tests:** skip postgres pool resilience tests on Python < 3.11 (30c46f8)
- **tests:** skip arena builder event hooks test (0be6542)
- **tests:** unskip 3 tests with outdated skip reasons (1b9a7e8)
- **tests:** skip OpenRouter test with changed default role (33a422c)
- **tests:** skip ML search test that fails in CI (e4dfd89)
- **tests:** skip ML embed test that fails in CI (6887a32)
- **tests:** skip false positive SQL injection test (091da9d)
- **tests:** mock Redis store in mark_result_sent test (90b7ccd)
- **tests:** skip flaky RLM logging test (b53bb45)
- **tests:** skip rate limit test with missing export (a31c5a3)
- **tests:** improve test stability and fix flaky tests (7babd9f)
- **tests:** skip migration test for unimplemented --alembic flag (039d9b2)
- **tests:** use temp directory for marketplace test and add --alembic flag (a7747f9)
- **tests:** update route count and skip unimplemented multi-tenant tests (96affce)
- **tests:** update analytics dashboard routes count assertion (fcef5a8)
- **tests:** enable Discord connector tests with correct httpx mocking (9cb7887)
- **tests:** skip discord test module + regenerate API docs (f45fdb5)
- **tests:** update Teams connector tests for _http_request refactor (7296939)
- **tests:** fix Discord connector tests by using correct mock methods (513570c)
- **tests:** fix 3 of 4 skipped TODO tests and add audit documentation (bdd6d8f)
- **tests:** skip entire Discord send message test class (4b2d5a9)
- **tests:** skip discord mock test with AsyncMock comparison issue (2a65e1e)
- **tests:** skip entire SSO test module due to API changes (590cd77)
- **tests:** fix enterprise SSO tests with proper config (f05dcd4)
- **tests:** skip learning efficiency test with negative result (559ac75)
- **tests:** skip SSO tests with config issue (139a2da)
- **tests:** skip entire stress test class on CI (803ae75)
- **tests:** skip flaky performance test on CI (e534cdc)
- **tests:** skip pruning test with mock issue (63e696b)
- **tests:** skip e2e debate test with Arena env issue (3fb5ea6)
- **tests:** skip another flaky visibility test (07078e6)
- **tests:** skip control plane workflow tests when redis unavailable (923ec80)
- **tests:** skip flaky grant_access_with_expiry test (fd72bf7)
- **tests:** skip all tfidf tests when scikit-learn unavailable (47dc3f0)
- **tests:** Fix regional sync tests for mock state store requirement (ad6aae4)
- **tests:** update RLM limiter tests for new default (250df9d)
- **tests:** Update gauntlet stress tests for correct config params (b7d05af)
- **tests:** skip tfidf test when scikit-learn unavailable (734b9b6)
- **tests:** update durability test to expect DistributedStateError (c6db555)
- **tests:** handle timezone-naive datetimes in DR test (e1ac85a)
- **tests:** correct import path in test_auth_v2.py (6a5f7a9)
- **tests:** correct import path for User/Workspace classes (89c5e68)
- **tests:** handle missing google-auth library in CI (fe4b958)
- **tests:** add tolerance to flaky RPO timing test (2d6014f)
- **tests:** use unique circuit breaker names in degradation test (22fab1b)
- **types:** add missing properties to ApiCloudFile interface (2a443eb)
- **types:** resolve all @typescript-eslint/no-explicit-any errors (da6d070)
- **types:** add type: ignore comments for mixin method calls (30b0ea6)
- **types:** add type ignores for dict access in connectors handler (390be23)
- **types:** add type ignores for table attribute access in document connector (9c6c7f5)
- **types:** add type ignores for lazy-loaded optional attributes (747923f)
- **types:** add type ignores for override and attr-defined errors (98c22fc)
- **types:** add type ignores for conditional type assignments (bfba8a5)
- **types:** replace callable with Callable[..., Any] (2f150aa)
- **types:** use enum values instead of strings for typed lists (62e94a3)
- **types:** add type annotations for untyped variables (5510299)
- **types:** add type ignore comments for lazy imports (ee51728)
- **types:** add missing methods to EncryptionService and JobQueue (fdde836)
- **types:** correct all status_code= to status= in cross_pollination (6d62137)
- **types:** correct error_response parameter and remove unused import (78d2ec0)
- **types:** resolve mypy errors in 5 modules (6ab5107)
- **ui:** resolve ESLint warnings across components, hooks, and tests (154b42e)
- **ui:** correct UploadFile property access in FileUploader (8fd677c)
- **whatsapp:** correct respond_to_interaction return type (4d6c5f9)

### Performance Improvements

- **ci:** parallelize test suite with xdist and category splits (5dfbf4c)

### Code Refactoring

- replace deprecated datetime.utcnow() with datetime.now(timezone.utc) (a5e85a9)
- rename auth_v2.py to user_auth.py for clarity (5f0c9b6)
- **client:** modularize SDK with separate API classes (f90dd91)
- **discord:** use HTTP helper for update_message (63b210c)
- **discord:** use shared HTTP request helper (2c4cab1)
- **events:** Extract handler mixins from cross_subscribers (0a48bbe)
- **storage:** Enhance share_store with backend abstraction (65ec77f)
- **storage:** Complete decision_result_store backend support (0a33f04)
- **storage:** Improve decision_result_store parameter handling (5d3308a)
- **teams:** use shared HTTP request helper (fd3736e)

### Documentation

- add documentation site and integration guides (4dc1a30)
- add ADR 016 for marketplace architecture (98c4c24)
- add marketplace documentation and ADR (0f2454a)
- add SOC2 compliance documentation (75ddf71)
- regenerate API docs (2f926d6)
- Add ops module to architecture documentation (dc94116)
- add incident runbooks and demo seeding script (5f2a5e8)
- Update skipped test reasons to reference actual implementations (2b7fc4b)
- add updated enterprise control plane feasibility study (b457e25)
- Update architecture with extracted modules and PostgreSQL stores (fb201f4)
- add channel production readiness audit results (5597868)
- add security env vars to ENVIRONMENT.md (2473b78)
- **about:** update platform stats to current values (8df6854)
- **observability:** add platform integration metrics documentation (d0b537a)
- **security:** add penetration testing requirements documentation (27f112b)

### Tests

- fix Teams connector tests for replies and search (b519e99)
- update gsheets and replay handler tests (e7c65c7)
- update Salesforce and debate rounds tests (2d210bf)
- add load testing scenarios and connector tests (77465e3)
- update protocol tests for new 8-round defaults (926502b)
- skip TestCalibrationWeighting (weight returns 1.0 vs expected >1.0) (fc5cfa3)
- add comprehensive tests for RLM and Genesis modules (4d4c1a3)
- fix multi-tenant tests to match actual API (acc7db9)
- add comprehensive tests for marketplace module (6ad2936)
- remove outdated skip decorators from working tests (d26f1b9)
- add Debate Engine E2E tests (af13feb)
- add cross-feature integration tests for nomic loop (22d5cd8)
- improve benchmark test performance and add embedding service tests (d898dfc)
- add comprehensive E2E security tests (4a1a2a8)
- **chaos:** add comprehensive chaos testing suite (1a4dc4e)
- **control-plane:** Add tests for regional leader election (99dac08)
- **e2e:** enable debate lifecycle tests for implemented features (8ef34a1)
- **email:** add comprehensive email handler unit tests (c5acf2e)
- **gauntlet:** Add stress tests for adversarial validation (eef9959)
- **handlers:** add tests for critique, routing, and explainability handlers (0c994c5)
- **knowledge:** add comprehensive Phase A2 mound ops tests (35cc7ba)
- **ml:** add ML router integration tests (f62dc84)
- **queue:** add DLQ endpoint tests (54576d5)
- **resilience:** add comprehensive end-to-end resilience integration tests (041b174)
- **rlm:** add comprehensive training pipeline integration tests (ec0efc8)

### Maintenance

- Fix mypy type errors in marketplace, parser, and scheduler (d5c3288)
- fix imports and mock patterns (44038e9)
- fix type annotations and remove unused prop (2105128)
- remove CORS debug logging (43692d9)
- change CORS logging to INFO level for production visibility (feac627)
- add CORS logging to diagnose missing headers (a4a138f)
- docs/test: add ML router integration tests and pentest docs (e5d63ee)
- SDK refactor and knowledge mound test mock fixes (8a89294)
- Add dynamic port selection for Gmail OAuth callback (9bdd400)
- type ignores and landing page copy updates (16d5814)
- Fix StructuredLogger calls in orchestrator.py (cb23a3d)
- Add AWS Secrets Manager support for Gmail OAuth credentials (087fd04)
- Add checkpoint/resume integration tests (e2d073a)
- Add regional sync tests and final decision store cleanup (8242244)
- minor updates to nomic debate phase and postgres store (d12275c)
- minor updates to webhook registry and e2e tests (11f75ab)
- Add PostgresEloDatabase integration tests and update docs (e2bd9be)
- remove duplicate test_auth_v2.py (1736636)
- Extract reusable components from debate_rounds.py (13a713b)
- Extract reusable components from debate_rounds.py (29b30b0)
- Add PostgresContinuumMemory integration tests (62f7a93)
- bump version to 2.1.10 (2d11107)
- **deps:** Bump testing group (pytest, coverage, etc.) (119bbb5)
- **deps:** Update websockets to <17.0 (252f3a4)
- **deps:** Update elevenlabs to <3.0 (ca53e7a)
- **deps:** Update redis to <8.0 (6d3c058)
- **deps:** Update black to <26.0 (c143e1f)
- **deps:** Update pytest-asyncio to <2.0 (914e772)
- **eslint:** migrate to flat config for ESLint 9 compatibility (83817c9)
- **frontend:** fix remaining workflow builder imports (7eb52df)
- **frontend:** prefix unused parameter with underscore (1424cf7)
- **frontend:** fix remaining unused imports in workflow components (32baf82)
- **frontend:** remove unused imports from React components (620b416)
- **frontend:** fix linting issues in TypeScript tests and pages (7f1754b)
- **observability:** Export memory profiling utilities in __all__ (b41a3e4)
- **types:** fix type annotations and unused imports (59974a2)
- **types:** add type: ignore for cross-pollination handler (e679b0b)
- **types:** add type: ignore comments for integration handlers (3215cc0)
- **types:** add type: ignore comments for handlers and adapters (2e6f5b9)
- **types:** add type: ignore comments for dynamic method calls (a745f12)
- **types:** continue fixing mypy Module import errors (3d4dfb9)
- **types:** fix more mypy Module import errors (4989b55)
- **types:** continue reducing mypy Module errors (7e782fc)
- **types:** continue batch fixing Module import errors (313a188)
- **types:** fix more mypy Module import errors (0f16541)
- **types:** continue batch fixing mypy Module import errors (a665386)
- **types:** batch fix more mypy Module import errors (3f04eef)
- **types:** continue reducing mypy Module import errors (eba066a)
- **types:** continue reducing mypy Module import errors (b50ac66)
- **types:** batch fix module import mypy errors (adfec66)
- **types:** continue mypy error reduction in connectors and ML (3b042fb)
- **types:** fix federation.py mixin attribute access errors (40415e3)
- **types:** continue mypy error reduction (c89dc91)
- **types:** reduce mypy errors with type annotations and ignores (4e3968f)

### CI/CD

- add Python SDK and VS Code extension publish workflows (4820f4e)
- add deployment workflows (3aa0abc)
- increase test job timeout to 40 minutes (75d317e)

### Code Style

- apply ruff formatting and fix syntax error (f1793ed)
- format job_queue_store.py (83f5dfe)

### Contributors

- an0mium
- dependabot[bot]

All notable changes to Aragora will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.4] - 2026-01-21

### Added

- **Unified Audit Module** - Centralized audit logging:
  - Consistent audit trail format across all operations
  - Structured event types with metadata
  - Integration with immutable log for compliance
  - 678 lines of audit infrastructure

- **Security Migration Utilities** - Credential rotation support:
  - API key rotation workflows
  - Secret migration between providers
  - Rollback capabilities for failed migrations
  - Audit trail for all credential changes

- **Checkpoint Edge Case Tests** - Enhanced checkpoint reliability:
  - Compression roundtrip verification
  - Concurrent checkpoint creation handling
  - Large message content handling
  - Expiration detection tests

- **Handler Integration Tests** - Comprehensive handler coverage:
  - Secure handler with RBAC tests (811 lines)
  - External integrations handler tests (389 lines)
  - Connector tests (Google Chat, Voice Bridge, HackerNews)

- **Encryption Performance Benchmarks** - Security performance validation:
  - Field encryption throughput tests
  - Key derivation benchmarks
  - Envelope encryption performance

### Changed

- **AdminHandler** - Enhanced with RBAC permission checks
- **Shutdown Sequence** - Improved graceful cleanup
- **Startup** - Enhanced initialization with validation

### Fixed

- **Circuit Breaker Tests** - Fixed flaky test with UUID-based service names
- **Checkpoint Resume Tests** - Fixed SQLite fallback issue
- **Import Errors** - Fixed BaseHandler import in admin module

## [2.1.3] - 2026-01-21

### Added

- **Approval Gate Middleware** - Human-in-the-loop approval for sensitive operations:
  - Risk level classification (low, medium, high, critical)
  - Customizable approval checklists
  - Integration with GovernanceStore for persistence
  - Decorator and middleware usage patterns

- **Secure Handler Base** - Security-enhanced HTTP handler:
  - Automatic JWT verification
  - Built-in RBAC permission enforcement
  - Audit trail logging for security events
  - Security metrics emission

- **Webhook Delivery Manager** - Reliable webhook delivery:
  - Delivery status tracking (pending, delivered, failed, dead-lettered)
  - Retry queue with exponential backoff
  - Dead-letter queue for consistently failing webhooks
  - Delivery SLA metrics

- **DecisionHandler Tests** - Comprehensive test coverage for `/api/decisions`:
  - Route matching tests
  - GET/POST operation tests
  - Result caching tests

- **Cache Invalidation** - Enhanced decision routing middleware:
  - Tagged entries for selective invalidation
  - Workspace-scoped invalidation
  - Policy version tracking
  - Cache statistics and monitoring

### Changed

- **Redis now optional** for initial production deployment (with warning)
- **RBAC enforcement** added to connectors handler

### Fixed

- **Migration script metrics** - Added tracking for migration outcomes
- **ENCRYPTED_FIELDS export** - Now properly exported from gmail_token_store

## [2.1.2] - 2026-01-21

### Added

- **Cloud KMS Provider** - Multi-cloud key management integration:
  - AWS KMS support via boto3
  - Azure Key Vault support via azure-identity
  - GCP Cloud KMS support via google-cloud-kms
  - Auto-detection of cloud platform from environment
  - Envelope encryption with data key decrypt

- **Encrypted Fields** - Field-level encryption for sensitive data:
  - Automatic encryption of OAuth tokens, API keys, secrets
  - Platform-specific credential encryption (Slack, Discord, Telegram, etc.)
  - Transparent encrypt/decrypt on storage operations

- **Decision Routing Middleware** - Smart request routing:
  - `aragora/server/middleware/decision_routing.py` - Request routing based on decision context
  - RBAC-aware routing decisions

- **Re-enabled Integration Tests** - 47 previously skipped tests now passing:
  - TestArenaRun (7 tests)
  - TestRoundExecutionFlow (5 tests)
  - TestPhaseTransitions (5 tests)
  - TestEarlyTerminationOnConvergence (5 tests)
  - TestConsensusDetection (5 tests)
  - TestErrorHandling (5 tests)
  - TestMemoryIntegration (5 tests)
  - TestFullDebateFlow (7 tests)
  - TestAgentFailureHandling (3 tests)
  - Debate performance benchmarks re-enabled

- **Production Deployment Documentation**:
  - `docs/PRODUCTION_DEPLOYMENT.md` - Comprehensive ops guide
  - `docs/SUPABASE_SETUP.md` - Hosted PostgreSQL setup

- **Migration Configuration Tests** - 7 new tests verifying Alembic setup:
  - `test_alembic_config_exists` - Validates alembic.ini and directory structure
  - `test_initial_schema_exists` - Verifies schema SQL file
  - `test_initial_schema_has_required_tables` - Checks all 11 required tables
  - `test_init_postgres_script_exists` - Validates initialization script
  - `test_migration_env_uses_asyncpg` - Confirms async support
  - `test_migration_version_exists` - Verifies migration versions

- **Architecture Documentation** - Added Storage Architecture section:
  - PostgreSQL store implementations table (13 stores)
  - Database migration commands
  - Transaction safety documentation

### Fixed

- **Circuit Breaker Test Isolation** - Fixed flaky `test_get_metrics_provides_summary`:
  - Uses UUID-based service names to avoid cross-test interference
  - Added specific assertion for created breaker in metrics

### Changed

- **Documentation Updates**:
  - `docs/ENVIRONMENT.md` - Added Alembic migration commands
  - `docs/ARCHITECTURE.md` - Added Storage Architecture section with PostgreSQL details
  - Updated performance metrics (38,000+ tests, 250+ strict modules, 468 storage tests)

## [2.1.1] - 2026-01-20

### Added

- **Twilio Voice Integration** - Bidirectional voice for phone-triggered debates:
  - Inbound call handling with speech-to-text transcription
  - TwiML response generation for interactive prompts
  - Outbound calls with TTS for debate results
  - Call session tracking and management
  - Webhook signature verification
  - New endpoints: `/api/voice/inbound`, `/api/voice/status`, `/api/voice/gather`

- **Enhanced Observability** - Comprehensive metrics and health monitoring:
  - Circuit breaker state tracking
  - Debate throughput metrics
  - Memory usage monitoring
  - Readiness and liveness probe support

- **PostgreSQL Backends** - Full horizontal scaling support for all 11 storage modules:
  - `PostgresWebhookConfigStore` - Webhook configuration persistence
  - `PostgresIntegrationStore` - Chat platform integrations
  - `PostgresGmailTokenStore` - OAuth token storage
  - `PostgresFindingWorkflowStore` - Audit workflow state
  - `PostgresGauntletRunStore` - In-flight gauntlet runs
  - `PostgresApprovalRequestStore` - Human approval requests
  - `PostgresJobQueueStore` - Background job queue
  - `PostgresMarketplaceStore` - Template marketplace
  - `PostgresTokenBlacklistStore` - JWT revocation
  - `PostgresFederationRegistryStore` - Multi-region federation
  - `PostgresGovernanceStore` - Decision governance artifacts
  - Unified schema in `migrations/sql/001_initial_schema.sql` (383 lines)
  - Alembic migration framework with async asyncpg support
  - Atomic transaction handling for multi-table operations
  - Factory functions support `ARAGORA_DB_BACKEND=postgres` environment variable

### Changed

- **Migrations Restructure** - Moved schema to `migrations/sql/001_initial_schema.sql`
- **Operations Documentation** - Updated with monitoring and alerting guidance
- **Transaction Safety** - Added explicit transactions to:
  - `PostgresGovernanceStore.cleanup_old_records_async()` - Atomic multi-table cleanup
  - `PostgresFederationRegistryStore.update_sync_status()` - Atomic counter increments

## [2.1.0] - 2026-01-20

### Added

- **JWT Webhook Verification** - Proper cryptographic verification for chat platform webhooks:
  - Microsoft Teams: JWT validation against Azure AD public keys
  - Google Chat: JWT validation against Google's JWKS endpoint
  - Graceful fallback when PyJWT not installed (with security warning)
  - JWKS client caching with hourly refresh

- **AgentSpec Test Suite** - Comprehensive tests for unified agent specification:
  - Creation with explicit fields
  - Deprecated string parsing with warnings
  - Team creation from dicts
  - String serialization and equality

- **Chat Webhook Router Tests** - Platform detection and routing tests:
  - Slack, Discord, Telegram, WhatsApp detection
  - Connector caching behavior
  - Signature format verification

### Changed

- **rlm_backend Deprecation** - Improved deprecation handling:
  - Now uses sentinel value to detect ANY explicit use
  - Warns for all uses (not just non-default values)
  - Documented removal planned for v3.0

### Security

- **Webhook Signature Verification** - Teams and Google Chat webhooks now properly validate JWT signatures instead of just checking for Bearer token presence

## [2.0.8] - 2026-01-20

### Added

- **Cross-Pollination Health Endpoint** - `/api/health/cross-pollination` for monitoring feature integrations:
  - ELO weighting status
  - Calibration tracking health
  - Evidence quality scoring
  - RLM hierarchy caching metrics
  - Knowledge Mound operations
  - Pulse trending topics

- **Cross-Pollination CLI Flags** - Control features via CLI:
  - `--no-elo-weighting` - Disable ELO-based vote weights
  - `--no-calibration` - Disable calibration tracking
  - `--no-evidence-weighting` - Disable evidence quality scoring
  - `--no-trending` - Disable Pulse trending topics

- **Cross-Pollination Grafana Dashboard** - `deploy/grafana/dashboards/cross-pollination.json`:
  - RLM cache hit rate gauge
  - Calibration error (ECE) gauge
  - Voting accuracy rate
  - ELO weight adjustments
  - Calibration adjustments by agent
  - Evidence quality bonuses
  - Knowledge Mound operations

- **CultureAdapter** - Bridges Culture Accumulator to Knowledge Mound:
  - Culture pattern storage after debates
  - Pattern retrieval for protocol configuration
  - Cross-workspace culture promotion

- **MultiInboxManager** - Unified Gmail account management:
  - Multi-account authentication
  - Cross-account sender intelligence
  - Unified prioritization

- **Template Marketplace** - Community workflow template sharing:
  - SQLite-backed storage
  - Rating and review system
  - Category browsing

- **GauntletRunStore** - Persistent storage for in-flight gauntlet runs:
  - InMemory, SQLite, and Redis backends
  - Status tracking (pending/running/completed/failed/cancelled)
  - Template and workspace filtering
  - Active run listing with Redis index support

- **ApprovalRequestStore** - Persistent storage for human approval requests:
  - InMemory, SQLite, and Redis backends
  - Workflow and step tracking
  - Expiration management
  - Response recording with responder tracking
  - Priority-based ordering

### Fixed

- **EmailHandler Interface** - Added missing `can_handle` and `handle` methods required by BaseHandler

### Changed

- **Cross-Pollination Enabled by Default** - All features now enabled out of the box
- **Quick Start Documentation** - Added to CROSS_POLLINATION.md
- **Strict Type Checking Expansion** - Added 19 modules to strict mypy (Phase 27):
  - Workflow templates: `__init__`, `package`, `patterns`, `legal`, `healthcare`, `accounting`, `ai_ml`, `code`, `devops`, `product`
  - Misc modules: `server.stream.events`, `client.resources.leaderboard`, `debate.safety`, `replay.schema`, `modes.builtin.orchestrator`, `server.handlers.knowledge`, `broadcast.mixer`
  - Continuum extractions: `continuum_glacial`, `continuum_snapshot`

- **Continuum Memory Refactoring** - Reduced `continuum.py` (1,995 → 1,612 lines):
  - Extracted `ContinuumGlacialMixin` to `continuum_glacial.py` (222 lines)
  - Extracted `ContinuumSnapshotMixin` to `continuum_snapshot.py` (267 lines)
  - `ContinuumMemory` now inherits from mixins for cleaner separation

## [2.0.7] - 2026-01-20

### Added

- **Batch Explainability Panel** - UI component for multi-debate analysis
- **Culture Integration Tests** - Tests for debate culture profile processing
- **Mode Handoff Tests** - Tests for transition contexts between modes

### Fixed

- **BeliefNetwork API Mismatch** - Fixed `WinnerSelector.analyze_belief_network()` to use correct `add_claim()` signature and `CruxDetector` for crux identification
- **MockDebateResult Test Fixture** - Added missing attributes (`consensus_reached`, `proposals`, `participants`, etc.)
- **Knowledge Mound Query Pagination** - Added `offset` parameter to `QueryOperationsMixin.query()` for proper pagination support
- **Knowledge Bridge Tests** - Fixed `MockKnowledgeMound` missing `workspace_id` attribute
- **Checkpoint Restore** - Graceful handling of corrupted checkpoint files with proper error messages
- **Checkpoint Test Timing** - Changed `duration_ms > 0` assertion to `>= 0` for fast operations
- **Analytics Handler** - Fixed `get_knowledge_mound()` being incorrectly awaited (it's synchronous)
- **Federation Tests** - Added proper mocking of persistent store to isolate tests from SQLite data

### Changed

- **Knowledge Mound Federation** - Methods now fall back to class-level cache when persistent store unavailable
- **Test Isolation** - Federation tests now properly isolated from persistent SQLite data

## [2.0.6] - 2026-01-20

### Added

- **Notification Delivery Metrics** - Prometheus metrics for notification tracking:
  - `aragora_notification_sent_total` - Counts by channel/severity/priority/status
  - `aragora_notification_latency_seconds` - Delivery latency histogram by channel
  - `aragora_notification_errors_total` - Error counts by channel and error type
  - `aragora_notification_queue_size` - Gauge for queue size by channel
  - Integrated into Slack, Email, and Webhook providers

- **Redis Cluster Support** - High-availability Redis for multi-instance deployments:
  - `RedisClusterClient` with automatic cluster/standalone detection
  - `get_redis_client()` utility for unified Redis access
  - Connection pooling with health monitoring
  - Graceful failover and automatic reconnection
  - Read replica support for scaling reads
  - Hash tag support for slot affinity

- **Enhanced Consensus Ingestion Metrics** - Track dissent and evolution:
  - `aragora_consensus_dissent_ingested_total` - Dissenting views captured
  - `aragora_consensus_evolution_tracked_total` - Supersession relationships
  - `aragora_consensus_evidence_linked_total` - Evidence linking counts
  - `aragora_consensus_agreement_ratio` - Agreement ratio distribution

- **Database Migration** - `v20260120000000_channel_governance_stores.py`:
  - `integration_configs` - Chat platform configurations
  - `gmail_tokens` - Gmail OAuth token storage
  - `gmail_sync_jobs` - Gmail sync job state
  - `finding_workflows` - Audit finding workflow state
  - `federation_registry` - Multi-region federation config

### Fixed

- **ELO System Tests** - Fixed tests to properly persist ratings to database
- **Metrics Package Import** - Fixed missing submodules in metrics package refactoring:
  - Created `aragora/observability/metrics/bridge.py` for cross-pollination metrics
  - Created `aragora/observability/metrics/km.py` for Knowledge Mound metrics
  - Created `aragora/observability/metrics/notification.py` for notification metrics
  - Added backward compatibility shims for `_init_metrics` and `_init_noop_metrics`
- **Workflow Templates Schema** - Removed pattern templates from `WORKFLOW_TEMPLATES` registry
  as they use a different schema (factory patterns vs fixed step workflows)

### Changed

- **Belief Module Refactoring** - Reduced `belief.py` (1,593 → 1,001 lines):
  - Extracted `CruxDetector`, `CruxClaim`, `CruxAnalysisResult` to `crux_detector.py`
  - Extracted `BeliefPropagationAnalyzer` to `crux_detector.py`
  - Backward compatible re-exports maintained

- **Strict Type Checking Expansion** - Added 21 modules to strict mypy (Phase 25-26):
  - Phase 25: `crux_detector`, `metrics/bridge`, `metrics/km`, `metrics/notification`
  - Phase 25: `streaming_mixin`, `resources/gauntlet`, `resources/graph_debates`
  - Phase 25: `resources/matrix_debates`, `resources/replay`
  - Phase 26: `resources/agents`, `resources/memory`, `resources/verification`
  - Phase 26: `modes/tool_groups`, `modes/builtin/*` (architect, coder, debugger, reviewer)
  - Phase 26: `ranking/verification`, `billing/jwt_auth`, `spectate/events`, `mcp/tools_module/gauntlet`

### Documentation

- Updated `docs/ENVIRONMENT.md` with Redis cluster configuration variables
- Added pluggable storage backend documentation
- Updated `docs/ARCHITECTURE.md` with RLM and client module structure
- Updated architecture metrics (35,784 tests, 38 strict modules, 495K LOC)

### Testing

- Added integration tests for notification metrics (14 tests)
- Added integration tests for Redis clustering (16 tests)
- Added consensus dissent tracking tests (400+ lines)
- Audited skipped tests: 158 conditional (optional deps) + 17 unconditional (E2E/future API)

## [2.0.5] - 2026-01-20

### Changed

- **RLM Bridge Refactoring** - Further reduced `bridge.py` (979 → 691 lines):
  - Extracted streaming methods to `streaming_mixin.py` (330 lines)
  - `RLMStreamingMixin` provides `query_stream()`, `query_with_refinement_stream()`, `compress_stream()`
  - `AragoraRLM` now inherits from `RLMStreamingMixin` for cleaner separation of concerns

- **Client Module Refactoring** - Reduced `client.py` (1,101 → 694 lines):
  - Extracted `GauntletAPI` to `resources/gauntlet.py`
  - Extracted `GraphDebatesAPI` to `resources/graph_debates.py`
  - Extracted `MatrixDebatesAPI` to `resources/matrix_debates.py`
  - Extracted `ReplayAPI` to `resources/replay.py`

### Added

- **New Prometheus Metrics** for observability:
  - TTS metrics: `aragora_tts_synthesis_total`, `aragora_tts_latency_seconds`
  - Convergence metrics: `aragora_convergence_check_total`, `aragora_convergence_blocked_total`
  - RLM metrics: `aragora_rlm_ready_quorum_total`
  - Vote bonus metrics: `aragora_evidence_citation_bonus_total`, `aragora_process_evaluation_bonus_total`

- **Integration Tests** for new features (19 tests):
  - TTS integration: initialization, event bus registration, agent message handling, rate limiting
  - Convergence tracker: initialization, reset, convergence check, novelty tracking
  - Vote bonus calculator: evidence citation bonuses, quality weighting
  - RLM streaming mixin: event sequence, error handling, node examination
  - Cross-feature integration: singleton patterns, metrics recording

### Technical

- Metrics wired in: `tts_integration.py`, `convergence_tracker.py`, `vote_bonus_calculator.py`
- Type ignore audit: 208 total (mostly legitimate decorator/mixin/optional-import patterns)

## [2.0.4] - 2026-01-20

### Changed

- **Phase 24: Module Extractions** - Reduced large file sizes for maintainability:
  - `prometheus.py` (1,460 → 994 lines): Extracted to `prometheus_nomic.py`, `prometheus_control_plane.py`, `prometheus_rlm.py`, `prometheus_knowledge.py`
  - `feedback_phase.py` (1,628 → 1,191 lines): Extracted to `feedback_elo.py`, `feedback_persona.py`, `feedback_evolution.py`
  - `bridge.py` (1,701 → 979 lines): Extracted to `debate_adapter.py`, `knowledge_adapter.py`, `hierarchy_cache.py`

- **Strict Type Checking** - Expanded mypy strict mode to 29 modules (from 19):
  - Added: `prometheus_nomic`, `prometheus_control_plane`, `prometheus_rlm`
  - Added: `feedback_elo`, `feedback_persona`, `feedback_evolution`
  - Added: `debate_adapter`, `knowledge_adapter`, `hierarchy_cache`, `rlm/types`

### Fixed

- Fixed undefined name errors (`AgentSpec`, `KnowledgeItem`, `DB_KNOWLEDGE_PATH`, `asyncio`)
- Fixed circular imports in prometheus module re-exports
- Fixed duplicate imports in `openai_compatible.py`
- Fixed ambiguous variable name `l` → `label` in `email_priority.py`
- Removed unused local variables in `backup/manager.py`
- Updated import paths for metrics functions to use extracted submodules

### Documentation

- Updated `.github/workflows/lint.yml` to include 29 strict-checked modules
- Added comments documenting intentional broad exception handlers with `# noqa: BLE001`

## [2.0.3] - 2026-01-20

### Added

- **Cross-Functional Integration** - 7 major features now fully wired:
  - `KnowledgeBridgeHub` - Unified access to MetaLearner, Evidence, and Pattern bridges
  - `MemoryCoordinator` - Atomic writes across multiple memory systems
  - `SelectionFeedbackLoop` - Performance-based agent selection weights
  - `CrossDebateMemory` - Institutional knowledge injection from past debates
  - `EvidenceBridge` - Persist collected evidence in KnowledgeMound
  - `CultureAccumulator` - Extract organizational patterns from debates
  - Post-debate workflow triggers for automated refinement

- **New Prometheus Metrics** (7 metrics for cross-functional features):
  - `aragora_knowledge_cache_hits_total` / `aragora_knowledge_cache_misses_total`
  - `aragora_memory_coordinator_writes_total`
  - `aragora_selection_feedback_adjustments_total`
  - `aragora_workflow_triggers_total`
  - `aragora_evidence_stored_total`
  - `aragora_culture_patterns_total`

- **Documentation**:
  - `docs/CROSS_FUNCTIONAL_FEATURES.md` - Comprehensive usage guide
  - Updated `docs/STATUS.md` with 88 fully integrated features

- **Tests**:
  - Knowledge mound ops handler tests (793 LOC)
  - Trickster calibrator tests
  - Cross-pollination integration tests
  - Modes module tests (base, deep_audit, redteam, tool_groups)

### Changed

- `AgentSpec` now always assigns a default role of "proposer" when not specified
- Legacy colon format (`claude:critic`) sets persona, not role (pipe format for explicit roles)
- Updated CLI `parse_agents` tests to match new AgentSpec behavior

### Fixed

- CLI test failures for `parse_agents` function
- Arena.from_config `enable_adaptive_rounds` NameError

## [2.0.2] - 2026-01-19

### Added

- UI Enhancement Release with improved connectors and uncertainty pages
- Inbox components for notifications
- Knowledge Mound federation operations and visibility controls
- Snapshot/restore for checkpoint integration
- Calibration and learning feedback loops

### Fixed

- Agent spec parsing 3-part spec bug
- Usage sync persistence watermarks
- Context gatherer cache task-hash keying
- React side effect in setLastAllConnected
- Cross-debate memory snapshot race condition

## [2.0.1] - 2026-01-18

### Added

- Feature Integration & Consolidation Release
- OAuth endpoints (Google, GitHub)
- Workflow API endpoints
- Workspace management endpoints
- Leader election for distributed coordination

## [2.0.0] - 2026-01-17

### Added

- Enterprise & Production Hardening Release
- Graph and Matrix debate APIs
- Breakpoint API for human-in-the-loop
- Billing and subscription endpoints
- Memory analytics endpoints
- A/B testing for agent evolution

## [1.5.x] - 2026-01-15

### Added

- E2E Testing & SOC 2 Compliance
- OAuth, SDK Probes & Performance improvements
- Admin UI & Governance features

---

For detailed feature status, see [docs/STATUS.md](docs/STATUS.md).
