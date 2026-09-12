# Aragora Canonical Metrics

> **This doc is auto-generated.** Do not edit by hand — edits will be overwritten by the next run of `scripts/regenerate_metrics.py`. If a number here disagrees with another doc, this doc wins. Every metric below is reproducible by running the command in its row.

> **No timestamp or git SHA is embedded in this doc by design.** Embedding either would cause two branches that both regenerated the doc to always conflict on merge, turning an honesty mechanism into a merge-conflict factory. The authoritative timestamp and SHA for any regeneration are available via `--json`.

- **Regenerate:** `python scripts/regenerate_metrics.py`
- **Verify (drift check):** `python scripts/regenerate_metrics.py --check`
- **Timestamped JSON snapshot:** `python scripts/regenerate_metrics.py --json`

## Canonical numbers

| Metric | Value | Source | Command |
|---|---|---|---|
| Python files under aragora/ | `4310` | `aragora/` | `git ls-files aragora \| grep -E '\.py$' \| wc -l` |
| Python lines of code under aragora/ | `1994979` | `aragora/` | `python3 -c "from pathlib import Path; import subprocess; files = subprocess.check_output(['git', 'ls-files', 'aragora'], text=True).splitlines(); print(sum(sum(1 for _ in Path(p).open(encoding='utf-8', errors='replace')) for p in files if p.endswith('.py')))"` |
| Top-level modules under aragora/ | `145` | `aragora/` | `git ls-files aragora \| awk -F/ 'NF>2 {print $2}' \| sort -u \| wc -l` |
| Test files (test_*.py under tests/) | `5551` | `tests/` | `git ls-files tests \| grep -E '(^\|/)test_[^/]*\.py$' \| wc -l` |
| Test functions (class + module level) | `226053` | `tests/` | `git grep -E '^[[:space:]]*(async )?def test_' -- tests \| wc -l` |
| @pytest.mark.parametrize decorators | `1064` | `tests/` | `git grep -E '@pytest\.mark\.parametrize' -- tests \| wc -l` |
| CLI top-level command modules | `86` | `aragora/cli/commands/` | `git ls-files aragora/cli/commands \| grep -E '/[^/]*\.py$' \| grep -v '/__' \| wc -l` |
| OpenAPI paths | `2912` | `docs/api/openapi.json` | `python -c "import json; print(len(json.load(open('docs/api/openapi.json'))['paths']))"` |
| OpenAPI operations (HTTP verbs) | `3205` | `docs/api/openapi.json` | `python -c "import json; spec=json.load(open('docs/api/openapi.json')); print(sum(1 for p in spec['paths'].values() for m in p if m.lower() in {'get','post','put','delete','patch','head','options'}))"` |
| @require_permission decorator calls | `1364` | `aragora/` | `git grep -E '@require_permission\(' -- 'aragora/*.py' \| wc -l` |
| Unique permission strings | `423` | `aragora/` | `git grep -h -o -E "@require_permission\(['\"][^'\"]+['\"]\)" -- aragora \| sed -E "s/.*['\"]([^'\"]+)['\"].*/\1/" \| sort -u \| wc -l` |
| Python SDK modules | `198` | `sdk/python/` | `git ls-files sdk/python/aragora_sdk \| grep -E '\.py$' \| grep -v '/__' \| awk -F/ 'NF<=5' \| wc -l` |
| TypeScript SDK modules | `216` | `sdk/typescript/` | `git ls-files sdk/typescript/src \| grep -E '\.ts$' \| awk -F/ 'NF<=5' \| wc -l` |
| Allowlisted agent types | `35` | `aragora/config/settings.py` | `grep -A 50 'ALLOWED_AGENT_TYPES' aragora/config/settings.py \| grep -oE "'[a-z-]+'" \| sort -u \| wc -l` |
| Knowledge Mound adapter specs | `41` | `aragora/knowledge/mound/adapters/factory.py` | `git grep -E '"\.[a-z_]+_adapter"' -- aragora/knowledge/mound/adapters/factory.py \| wc -l` |
| Knowledge Mound adapter files | `46` | `aragora/knowledge/mound/adapters/` | `git ls-files aragora/knowledge/mound/adapters \| grep -E '/[^/]+_adapter\.py$' \| wc -l` |
| Markdown files under docs/ | `1119` | `docs/` | `git ls-files docs \| grep -E '\.md$' \| wc -l` |
| GitHub Actions workflows | `97` | `.github/workflows/` | `git ls-files .github/workflows \| grep -E '\.yml$' \| wc -l` |
| Mypy baseline errors (grandfathered) | `3115` | `.mypy-baseline` | `wc -l .mypy-baseline` |

## Notes on counting methodology

- **Python lines of code under aragora/:** Uses git-tracked files + direct line count to avoid xargs/wc batching and ignored-file pollution.
- **Test functions (class + module level):** Counts both module-level and class-nested test methods.
- **@pytest.mark.parametrize decorators:** Each decorator expands into N test cases during collection.
- **Knowledge Mound adapter specs:** Counts adapter module entries in the factory spec tuple list.

## Why this doc exists

Aragora's thesis (Commitment 4: respect the limits) requires that the product not claim capability it does not have. The same discipline applies to numeric claims. Before this doc existed, different docs cited different numbers for the same metric (e.g. test-count claims ranged from 129K to 210K+ depending on regex used). This doc is the single source of truth.

All other docs that cite a metric should link here rather than hard-code the number, or explicitly snapshot the number with a date so staleness is visible.

## Drift threshold

The `--check` mode fails if any metric moved by more than 0.5% from the committed doc. This threshold is a trade-off: lower values (e.g. 0.1%) would trigger on small absolute moves in small-denominator metrics (e.g. adapter count changing by one), forcing doc churn on normal development. Higher values (e.g. 5%) would let meaningful drift accumulate silently. 0.5% was picked as the default; it is a constant in `scripts/regenerate_metrics.py` (`DRIFT_THRESHOLD`) and can be tuned if specific metrics prove too noisy.

New metrics (present in the script but not in the committed doc) are reported as `NEW:` in the check output and force a refresh regardless of threshold.

## Related automation

- `.github/workflows/metrics-drift.yml` runs this script on every PR that touches counted surfaces (`aragora/`, `tests/`, `sdk/`, `docs/api/openapi.json`, `.mypy-baseline`), and on a weekly Monday schedule. It invokes `--check` and fails the job if drift exceeds the threshold. On PR runs the check also snapshots the metrics at the merge commit's mainline parent (`--base-json`/`--base-doc`) so drift that pre-exists on `main` is reported as `INHERITED:` and does not fail the PR — only drift the PR itself introduces blocks. The weekly scheduled run stays strict and polices accumulated main-side staleness. The job does **not** auto-open a refresh PR; it fails loud and a human or follow-up automation decides whether to regenerate.
- `tests/scripts/test_regenerate_metrics.py` holds external invariants (e.g. test count > 100K, python file count > 1K) so the bootstrap is not fully self-referential: even if the committed doc were wrong, the invariant tests would catch a gross break.
- `scripts/reconcile_status.py` cross-references feature claims across CAPABILITY_MATRIX, GA_CHECKLIST, STATUS, ROADMAP.
- `scripts/validate_openapi_routes.py` verifies OpenAPI paths against actual handler implementations.
