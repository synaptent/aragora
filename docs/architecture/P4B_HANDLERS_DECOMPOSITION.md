# P4B: `aragora/server/handlers` flat-root decomposition

Status: design, binding for the four `p4b-handlers-batch-*` features and
`p4b-cycles-and-counts`. Measured on `origin/main` at `1ad1162d59`
(2026-09-05). Every count below was produced by a command in this document
or in `scripts/`, never estimated.

Batch status: batch 1 is PR #10000 (Tier 3, settlement-batched per §7):
the 45 files of §5 (42 moves + 3 retirements), the shim machinery
(`MOVED_MODULES`, `_MovedModuleFinder`, the `__getattr__` branch),
`scripts/ci/check_moved_handler_shim.py`, and the §8 readiness fix; flat
root 186 -> 141 at its head. Batches 2 to 4 pending.

Goal (VAL-P4B-001): `git ls-files ':(glob)aragora/server/handlers/*.py' | grep -v '__init__\.py$' | wc -l`
drops from **186** to **< 20** without losing a single registered handler
(VAL-P4B-005/006) and with every moved module still importable from its old
path under a `DeprecationWarning` that names the handler basename
(VAL-P4B-007).

## 1. Summary of the plan

| Bucket | Files | What happens |
|---|---|---|
| Keep flat (infrastructure) | 13 | untouched; they are the package's shared base (`base`, `secure`, ...) |
| Move into an existing subdir | 156 | `git mv` + rewrite relative imports + registry pointer update + shim entry |
| Move into a new subdir | 12 | same, into `finance/` (5) and `catalog/` (7), both justified in §4.3 |
| Retire (delete outright) | 5 | shadowed or pure-alias duplicates of a subdir twin; shim entry still added |
| Total | 186 | |

End state: 13 flat modules + `__init__.py` = 14 files at the root, leaving
5 of headroom under the < 20 ratchet for future infrastructure.

Four batches of 41 to 45 files (19 to 34 kLOC each), one Tier-3 PR per
batch, grouped so that each PR's test surface is a small set of
`tests/handlers/<dir>/` and `tests/server/handlers/<dir>/` trees (§6).

## 2. Registration and discovery mechanism (traced in code)

There is no filesystem discovery. Handlers reach the server through two
string-keyed tables, and a move is safe exactly when both tables still
resolve to the same class object.

### 2.1 The two tables

**Table A: `HANDLER_MODULES`** in `aragora/server/handlers/_lazy_imports.py`
maps a handler class name to the dotted module that defines it:

```python
HANDLER_MODULES: dict[str, str] = {
    "CheckpointHandler": "aragora.server.handlers.checkpoints",
    "StatusPageHandler": "aragora.server.handlers.public",
    ...
}
```

`aragora/server/handlers/__init__.py` exposes every key lazily through a
module-level `__getattr__` (`__init__.py:455-495`):
`getattr(aragora.server.handlers, "CheckpointHandler")` calls
`_lazy_import(name)`, which does `importlib.import_module(HANDLER_MODULES[name])`
then `getattr(module, name)`, and caches the result in `_handler_cache`.
`ALL_HANDLERS` is built by iterating the same table and silently skipping
any name whose import raises `ImportError`/`AttributeError`.

**Table B: the registry** in `aragora/server/handler_registry/`. Each of
`admin.py`, `agents.py`, `analytics.py`, `debates.py`, `memory.py`,
`social.py` builds a list of `(attr_name, _DeferredImport)` pairs via
`_safe_import(module_path, class_name)` (`core.py:386-395`), and
`handler_registry/__init__.py:98-104` concatenates them into
`HANDLER_REGISTRY`. The `module_path` strings come in two forms:

- the package root, e.g. `_safe_import("aragora.server.handlers", "CheckpointHandler")`
  (97 entries: admin 39, debates 22, memory 13, analytics 10, social 8, agents 5).
  These go through Table A, so they follow whatever `HANDLER_MODULES` says.
- a direct module, e.g. `_safe_import("aragora.server.handlers.public.status_page", "StatusPageHandler")`
  (`features` 14, `cross_pollination` 9, `gauntlet_v1` 8, `workflow_templates` 5,
  `template_marketplace` 2, and roughly 55 more at one entry each).
  These bypass Table A and must be edited by hand when the module moves.

### 2.2 Resolution at boot

`aragora/server/unified_server.py:129` imports `HandlerRegistryMixin` from
`aragora.server.handler_registry`, which resolves to
`handler_registry/__init__.py` (the sibling file
`aragora/server/handler_registry.py` is shadowed by the package and never
imported; same mechanism as `connectors.py` in §4.4), and
`unified_server.py:1281` calls `UnifiedHandler._init_handlers()` eagerly at
startup. `_init_handlers` (`handler_registry/__init__.py:168-240`) runs
`filter_registry_by_tier(HANDLER_REGISTRY, active_tiers)` and then, for each
surviving pair, `handler_ref.resolve()`.

`_DeferredImport.resolve()` (`core.py:342-357`) is the single point of
failure:

```python
try:
    mod = importlib.import_module(self._module_path)
    self._resolved = getattr(mod, self._class_name)
except (ImportError, AttributeError, TypeError) as e:
    logger.warning("Failed to import %s from %s: %s", ...)
    self._resolved = None
```

A stale module path does **not** crash the server. It logs one warning and
the handler silently disappears from routing. That is the failure mode every
batch must guard against, and it is why the boot probe in §6 greps for
`Failed to import` instead of only checking the exit code.

Two other consumers read the same tables and inherit the same failure mode:

- `scripts/check_sdk_parity.py:222-240` builds its route inventory from
  `ALL_HANDLER_NAMES`/`HANDLER_MODULES` and SKIPs any name that fails to
  import, so a broken move shows up as a silent drop in the parity baseline.
- `scripts/validate_openapi_routes.py` AST-walks handler files and imports
  `HANDLER_REGISTRY` (line 1315).

Everything else keyed by handler is keyed by **class name**, not path, and is
move-invariant: `HANDLER_TIERS` and `HANDLER_STABILITY` in `core.py`,
`ALL_HANDLER_NAMES`, `module_tiers.yaml` (package granularity), and
`.importlinter` (one edge, `aragora.exceptions -> aragora.server.handlers.exceptions`,
on a keep-flat file).

### 2.3 The preservation invariant

> After every batch, for every key `K` in `HANDLER_MODULES` and for every
> `_safe_import(M, C)` in `handler_registry/*.py`:
> `importlib.import_module(HANDLER_MODULES[K])` has attribute `K`, and
> `importlib.import_module(M)` has attribute `C`, and both resolve to the
> **same class object** they resolved to before the batch.

Operationally (this is the first line of the per-batch recipe in §6):

```bash
AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true \
python3 - <<'EOF'
import importlib, logging, sys
logging.basicConfig(level=logging.WARNING)
from aragora.server.handlers._lazy_imports import HANDLER_MODULES
from aragora.server.handler_registry import HANDLER_REGISTRY
bad = []
for name, mod in HANDLER_MODULES.items():
    try:
        getattr(importlib.import_module(mod), name)
    except Exception as e:
        bad.append((name, mod, repr(e)))
for attr, ref in HANDLER_REGISTRY:
    if ref.resolve() is None:
        bad.append((attr, repr(ref), "resolve() -> None"))
print("registry entries:", len(HANDLER_REGISTRY), "HANDLER_MODULES:", len(HANDLER_MODULES))
for b in bad: print("BROKEN", *b)
sys.exit(1 if bad else 0)
EOF
```

The counts printed on the first line must not change across a batch
(record them in the PR body before and after).

## 3. Shim pattern for moved handlers

### 3.1 Why the shim cannot be a stub file at the old path

`scripts/ci/measure_import_graph.py:141-144` counts the flat root as
`sum(1 for _ in handlers_dir.glob("*.py"))`, and VAL-P4B-001 counts
`git ls-files ':(glob)aragora/server/handlers/*.py'`. A stub module left at
`aragora/server/handlers/<name>.py` counts as a flat file under both, so
168 stubs would leave the root at 181 and the ratchet red. The shim must
live inside the package without adding files to the root. VAL-P4B-007's
probe explicitly accepts this: it tries
`importlib.import_module("aragora.server.handlers." + name)`, catches
`ModuleNotFoundError`, and falls back to
`getattr(importlib.import_module("aragora.server.handlers"), name)`.

### 3.2 Why a package-level `__getattr__` alone is not enough

A `__getattr__` on `aragora/server/handlers/__init__.py` serves
`from aragora.server.handlers import routing` and
`getattr(handlers, "routing")`, but the statement form
`import aragora.server.handlers.routing` and the dotted form
`from aragora.server.handlers.routing import X` go through the import
system, which consults `sys.modules` and then `sys.meta_path` and never
calls the parent package's `__getattr__`. Runtime code uses those forms
on modules that move (measured over `aragora/` and `scripts/`, excluding the
two registration tables):

| form | B1 | B2 | B3 | B4 | runtime examples |
|---|---|---|---|---|---|
| `import aragora.server.handlers.<f>` | 0 | 1 | 0 | 5 | `orchestration/handler.py:1045` (`routing`); `workspace/{crud,policies,settings,members,invites}.py:34-38` (`workspace_module`, executed per request) |
| `from aragora.server.handlers.<f> import` | 9 | 4 | 11 | 18 | `stream/servers_route_registration.py:42` (`accounting`, inside `try/except ImportError` that silently disables the routes) |
| dotted string (`importlib`/`sys.modules.get`) | 1 | 0 | 13 | 1 | `workspace/__init__.py:96`; `shared_inbox/handler.py:65-92` (`sys.modules.get("..._shared_inbox_handler")`); `_oauth/utils.py:198` |
| `from aragora.server.handlers import <f>` (bare form, served by `__getattr__`) | 6 | 1 | 7 | 3 | `compliance/{gdpr,legal_hold,audit_verify}.py` (`compliance_handler`, six function-local sites, five of them `try/except`-guarded); `ops/enterprise_validator.py:180` (`auditing`); `blockchain/handler.py:85-200` (`erc8004`, seven per-request sites); `review_queue.py:51`, `webhooks/__init__.py:9` (`webhook_management`), `connectors/legacy.py:136` (the `connectors` retiree, already served by the package, §4.4) |

Tests use the same forms far more (statement form 19/98/53/32 per batch;
dotted `patch(...)` strings 1117/2573/2070/1719). Rewriting all of them is
out of the per-PR LOC bound, so the shim has to make every form resolve to
the live module.

### 3.3 The pattern: one `sys.meta_path` finder plus `__getattr__`

One new table in `aragora/server/handlers/_lazy_imports.py` (kept flat; it
already owns `HANDLER_MODULES`), appended to by every batch:

```python
# Old flat basename -> new dotted module.  Read by the MovedModuleFinder in
# handlers/__init__.py so every import form of the old path resolves to the
# moved module (with a DeprecationWarning) until callers are migrated.
MOVED_MODULES: dict[str, str] = {
    "routing": "aragora.server.handlers.agents.routing",
    ...
}
```

And in `aragora/server/handlers/__init__.py`, a finder registered once at
package import and a `__getattr__` branch that delegates to it:

```python
class _MovedModuleLoader(importlib.abc.Loader):
    def __init__(self, target: ModuleType) -> None:
        self._target = target
        self._spec = target.__spec__

    def create_module(self, spec: ModuleSpec) -> ModuleType:
        return self._target

    def exec_module(self, module: ModuleType) -> None:
        # module_from_spec always overwrites __spec__; give the real module its own back.
        module.__spec__ = self._spec


class _MovedModuleFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        prefix = __name__ + "."
        if not fullname.startswith(prefix):
            return None
        basename = fullname[len(prefix):]
        new = MOVED_MODULES.get(basename)
        if new is None:
            return None
        warnings.warn(
            f"{fullname} moved to {new}; import {new} instead (handler basename: {basename})",
            DeprecationWarning,
            stacklevel=2,
        )
        return importlib.util.spec_from_loader(fullname, _MovedModuleLoader(importlib.import_module(new)))


if not any(isinstance(f, _MovedModuleFinder) for f in sys.meta_path):
    sys.meta_path.append(_MovedModuleFinder())


def __getattr__(name: str) -> Any:
    ...
    if name in HANDLER_MODULES:
        return _lazy_import(name)
    if name in MOVED_MODULES:
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(...)
```

The finder is appended, not prepended, so it only runs after the normal
path finder has failed to find a real file, which means it can never
shadow a module that still exists. Because `create_module` returns the
already-imported real module, `sys.modules["aragora.server.handlers.routing"]`
and `sys.modules["aragora.server.handlers.agents.routing"]` are the **same
object**, and the real module keeps its own `__name__` and `__spec__`.

Verified in a throwaway package on Python 3.11.11 (this machine's
interpreter; an independent re-test on 3.13 during review agreed), one
fresh interpreter per case:

| # | form | result |
|---|---|---|
| 1 | `import pkg.old` | imports; one `DeprecationWarning` whose text contains `old`; `pkg.old is pkg.sub.real` |
| 2 | `from pkg.old import f` | works, warns |
| 3 | `from pkg import old` | works, warns, identity holds |
| 4 | `getattr(pkg, "old")` | works, warns, identity holds |
| 5 | `mock.patch("pkg.old.helper", ...)` | patches the live module: the real implementation sees the patched value inside the context and the original after |
| 6 | `__name__`/`__spec__` of the real module after aliasing | unchanged (`pkg.sub.real`), both `sys.modules` keys point at it |
| 7 | `from ..old import f` from a sibling module | works, warns |
| 8 | `importlib.import_module("pkg.old")` | works, returns the real module |
| 9 | the VAL-P4B-007 probe script verbatim | `PASS old` |
| 10 | second and third imports of the old name | no further warnings (`sys.modules` short-circuits the finder) |

Negative control with the `__getattr__`-only variant: forms 1 and 2 raise
`ModuleNotFoundError` on first use, which is exactly what the runtime
consumers in §3.2 would hit.

Row 9 is reproducible against the live tree: batch 1 (PR #10000) commits
the contract's probe verbatim as `scripts/ci/check_moved_handler_shim.py`,
so `python3 scripts/ci/check_moved_handler_shim.py <basename>` (one
basename per process) must print `PASS <basename>` for every
`MOVED_MODULES` key.

Item 10 has a consequence for VAL-P4B-007: the warning fires once per
process per module. The contract's probe runs one `python3` per sampled
name, so it always sees the warning. Any in-process test that asserts the
warning must run first for that name or clear `sys.modules` entries for both
the old and new keys (only the old key is needed to re-trigger the finder,
but clearing both avoids a half-initialised state).

### 3.4 Migration of runtime consumers

The shim keeps runtime consumers working, but each batch still rewrites
the runtime consumers of its own files in the same PR (§6 step 5), because
a `DeprecationWarning` on a per-request path (`workspace/*.py:34-38`) is
noise in production logs. Test consumers may stay on the old path; a
follow-up per directory can migrate them once the batch has settled.

`connectors.py` is the one basename that is also a package name
(`connectors/`). It is retired, not shimmed: the package already shadows
it, so there is no old-path behaviour to preserve. This is also why the two
new subdirs are named `finance/` and `catalog/` rather than `accounting/`
and `marketplace/` (§4.3): a package named after a moved basename would win
the import-system lookup before the finder ran, and `MOVED_MODULES["accounting"]`
would be dead code.

### 3.5 Shim ledger

Every batch appends one bullet per moved module to
`$MISSION/library/shims.md` in the normative form
`- aragora.server.handlers.<flat> -> aragora.server.handlers.<dir>.<name> (PR #N)`.
The retired files (§4.4) get the same bullet pointing at the surviving
twin, since the finder resolves them too.

### 3.6 Not chosen, and why

- **Stub file per moved module** (the `analytics_metrics.py`, `slack.py`,
  `compliance_handler.py` precedent). Rejected: counts against the ratchet
  (§3.1). Those three existing stubs are retired in this plan for the same
  reason.
- **Package `__getattr__` with a `sys.modules` alias, no finder.** The first
  draft of this design. Rejected after the negative control above: the
  statement and dotted forms fail until some earlier attribute access has
  populated the alias, and §3.2 shows six runtime call sites that use those
  forms on modules that move.
- **Rewriting all 4,643 patch strings.** Rejected for the move PRs: it would
  blow the 800-LOC bound many times over. The finder makes the rewrite
  optional; a follow-up cycle can do it per directory.

## 4. Mapping rules

### 4.1 Keep flat (13)

These are imported eagerly by `handlers/__init__.py` or are the package's
shared machinery; every subdir depends on them through `from ..base import`.
Their outside-`handlers` consumer counts (from `rg -l` over `aragora/`) are
the reason they stay: `base` 517, `secure` 110, `openapi_decorator` 65,
`types` 62, `exceptions` 20 (also the only `.importlinter` handler edge),
plus `api_decorators`, `mixins`, `typed_handlers`, `interface`,
`utilities`, `_lazy_imports`, `_registry`, `_stability`.

### 4.2 Placement rule

A file goes to the subdir whose `__init__.py` already re-exports its
neighbours, matched in this order: (1) the registry file that lists it
(`handler_registry/<area>.py`), (2) the URL prefix of its first `ROUTES`
entry, (3) the domain package it imports from (`aragora/<domain>/`). Ties
were broken toward the subdir with the fewer files so no subdir grows past
~35 modules. Where the docstring said "compatibility shim" or "alias", the
file was checked for a live twin and retired instead (§4.4).

### 4.3 New subdirs (2, justified)

- **`finance/`** (5 files, 5,501 LOC): `accounting`, `ap_automation`,
  `ar_automation`, `expenses`, `invoices`. All five serve
  `/api/v1/accounting/...` and import from `aragora/accounting/`. No existing
  subdir owns that prefix; `billing/` and `payments/` are Stripe and
  subscription plumbing, and mixing QuickBooks/Gusto flows into them would
  invert the domain boundary the P4a layering work drew.
- **`catalog/`** (7 files, 3,936 LOC): `marketplace`,
  `marketplace_browse`, `marketplace_pilot`, `template_marketplace`,
  `template_discovery`, `skill_marketplace`, `skills`. All serve
  `/api/v1/marketplace/...` or `/api/v1/templates` and import from
  `aragora/marketplace/` or `aragora/skills/`. There is no marketplace
  subdir today and no closer fit (`features/` is the vertical-feature grab
  bag and is path-frozen by PR #9989).

Neither new subdir may be named after a file it receives. A package
`aragora.server.handlers.accounting` would satisfy
`from aragora.server.handlers.accounting import register_accounting_routes`
(`stream/servers_route_registration.py:42`) with the package's `__init__`
instead of the moved module, and the finder in §3.3 would never run for
that basename because the path finder ahead of it finds the directory
first. The same applies to `marketplace` (29 `patch("aragora.server.handlers.marketplace...")`
strings in `tests/server/handlers/test_marketplace_handler.py`). A batch
that wants to add a subdir must check its name against every basename in
`MOVED_MODULES`.

### 4.4 Retired outright (5)

| flat file | LOC | surviving twin | evidence |
|---|---|---|---|
| `connectors.py` | 952 | `connectors/legacy.py` | the `connectors/` package shadows the flat module on import; nothing can import the flat file today. `legacy.py` differs by 62 diff lines and is the live copy |
| `status_page.py` | 110 | `public/status_page.py` | `HANDLER_MODULES["StatusPageHandler"]` (`_lazy_imports.py:162`) points at the `public` package, which re-exports `.status_page` (`public/__init__.py:8-13`), and `handler_registry/admin.py:204` points at `public.status_page` directly; the flat class is unreachable from the registry |
| `slack.py` | 20 | `bots/slack.py` | pure re-export alias of `bots.slack` |
| `analytics_metrics.py` | 14 | `analytics/_analytics_metrics_impl.py` (the flat `_analytics_metrics_impl.py` after its own move in the same batch) | pure re-export of `AnalyticsMetricsHandler` |
| `compliance_handler.py` | 18 | `compliance/handler.py` | star re-export plus five store getters (`get_receipt_store` 31 test patch strings, `get_audit_store` 52, `get_legal_hold_manager` 35, `get_deletion_scheduler` 15, `get_deletion_coordinator` 15); `compliance/handler.py` defines none of them today, so the batch imports all five into its namespace before deleting the flat file |

Each retirement except `connectors` is listed in `MOVED_MODULES` pointing at
the twin, so old imports keep working and VAL-P4B-007 samples pass if one of
these lands at the first/median/last position. `connectors` cannot be
shimmed (the package of the same name wins the import lookup, §3.4) and has
no old-path behaviour to preserve; if VAL-P4B-007 samples it, the PR body
records the deletion and the validator substitutes the next alphabetical
entry as the contract allows.

### 4.5 Renames on landing (1)

- `feature_flags.py` -> `admin/feature_flags_read.py`. `admin/feature_flags.py`
  already exists (`FeatureFlagAdminHandler`); the flat file is the read-only
  `/api/v1/feature-flags` handler. Shim key stays `feature_flags`.

`checkpoints.py` lands as `memory/checkpoints.py`, not `debates/`, because
`debates/checkpoints.py` already exists (a different `CheckpointHandler`
serving `/api/v1/debates/{id}/checkpoint/*`) and the flat file's registry
home is `handler_registry/memory.py:22`.

### 4.6 Subdir modules that already reach up to a flat file (4 lines, all batch 1)

Measured with `rg "^\s*from \.\.[A-Za-z_0-9]+ import" aragora/server/handlers/*/`
filtered to basenames that move: `analytics/core.py:21` (`.._analytics_impl`),
`analytics/core.py:27` (`.._analytics_metrics_impl`), `oauth/__init__.py:83`
and `oauth/handler.py:9` (`.._oauth_impl`). Batches 2 to 4 have none. In
each case the flat file lands in the same subdir as the importer, so the
batch rewrites `from ..X import` to `from .X import` in the importer; the
finder does not cover relative imports of a moved sibling (it only sees the
absolute `aragora.server.handlers.X` name after resolution, which it does
serve, but a per-import `DeprecationWarning` inside the package itself is
not acceptable). Step 5 in §6 lists this rewrite explicitly.

## 5. Full mapping (186 files)

Column key. **registration**: `HM n` = referenced `n` times from
`HANDLER_MODULES`; `reg n` = `n` direct `_safe_import` module strings in
`handler_registry/*.py`; `none` = reached only through another module or
not registered. **`aragora/` refs**: lines in `aragora/` outside the two
tables that name the flat path. **test refs**: test files that name the
flat path (import or `patch` string). Targets are relative to
`aragora/server/handlers/`.

### Batch 1 (45 files, 19170 LOC)

| flat file | LOC | registration | `aragora/` refs | test refs | target |
|---|---|---|---|---|---|
| `api_docs.py` | 233 | HM 1 + reg 1 | 0 | 2 | `admin/api_docs.py` |
| `backup_handler.py` | 567 | HM 1 + reg 1 | 2 | 5 | `admin/backup_handler.py` |
| `backup_offsite_handler.py` | 167 | reg 1 | 0 | 2 | `admin/backup_offsite_handler.py` |
| `docs.py` | 244 | HM 1 | 1 | 5 | `admin/docs.py` |
| `dr_handler.py` | 620 | HM 1 + reg 1 | 2 | 3 | `admin/dr_handler.py` |
| `feature_flags.py` | 121 | HM 1 + reg 1 | 2 | 2 | `admin/feature_flags_read.py` |
| `system_health.py` | 429 | HM 1 + reg 2 | 1 | 3 | `admin/system_health.py` |
| `system_intelligence.py` | 810 | HM 1 + reg 1 | 0 | 2 | `admin/system_intelligence.py` |
| `_analytics_impl.py` | 642 | HM 1 | 2 | 3 | `analytics/_analytics_impl.py` |
| `_analytics_metrics_agents.py` | 444 | none | 1 | 0 | `analytics/_analytics_metrics_agents.py` |
| `_analytics_metrics_common.py` | 86 | none | 4 | 4 | `analytics/_analytics_metrics_common.py` |
| `_analytics_metrics_debates.py` | 601 | none | 1 | 0 | `analytics/_analytics_metrics_debates.py` |
| `_analytics_metrics_impl.py` | 405 | HM 1 | 3 | 3 | `analytics/_analytics_metrics_impl.py` |
| `_analytics_metrics_usage.py` | 369 | none | 1 | 1 | `analytics/_analytics_metrics_usage.py` |
| `analytics_performance.py` | 862 | HM 1 | 0 | 2 | `analytics/analytics_performance.py` |
| `decision_analytics.py` | 474 | HM 1 + reg 1 | 0 | 3 | `analytics/decision_analytics.py` |
| `moderation_analytics.py` | 151 | HM 1 + reg 1 | 1 | 2 | `analytics/moderation_analytics.py` |
| `outcome_analytics.py` | 259 | HM 1 | 2 | 1 | `analytics/outcome_analytics.py` |
| `spend_analytics.py` | 258 | HM 1 + reg 1 | 0 | 0 | `analytics/spend_analytics.py` |
| `agent_evolution_dashboard.py` | 473 | HM 1 + reg 1 | 0 | 2 | `analytics_dashboard/agent_evolution_dashboard.py` |
| `dashboard.py` | 684 | none | 4 | 3 | `analytics_dashboard/dashboard.py` |
| `differentiation.py` | 362 | HM 1 + reg 1 | 1 | 1 | `analytics_dashboard/differentiation.py` |
| `outcome_dashboard.py` | 517 | HM 1 + reg 1 | 0 | 2 | `analytics_dashboard/outcome_dashboard.py` |
| `spend_analytics_dashboard.py` | 604 | reg 1 | 0 | 1 | `analytics_dashboard/spend_analytics_dashboard.py` |
| `rbac.py` | 634 | HM 1 + reg 1 | 1 | 2 | `auth/rbac.py` |
| `scim_handler.py` | 374 | HM 1 + reg 1 | 1 | 2 | `auth/scim_handler.py` |
| `sso.py` | 865 | HM 1 + reg 1 | 4 | 6 | `auth/sso.py` |
| `audit_export.py` | 310 | none | 1 | 4 | `compliance/audit_export.py` |
| `audit_trail.py` | 553 | HM 1 + reg 1 | 2 | 5 | `compliance/audit_trail.py` |
| `compliance_eu_ai_act.py` | 225 | reg 1 | 0 | 1 | `compliance/compliance_eu_ai_act.py` |
| `compliance_reports.py` | 218 | HM 1 + reg 1 | 1 | 2 | `compliance/compliance_reports.py` |
| `data_classification_handler.py` | 286 | reg 1 | 0 | 1 | `compliance/data_classification_handler.py` |
| `gdpr_deletion.py` | 190 | HM 1 + reg 1 | 1 | 2 | `compliance/gdpr_deletion.py` |
| `privacy.py` | 600 | HM 1 + reg 1 | 1 | 5 | `compliance/privacy.py` |
| `metrics_endpoint.py` | 681 | HM 1 + reg 1 | 1 | 4 | `metrics/metrics_endpoint.py` |
| `_oauth_impl.py` | 195 | none | 3 | 21 | `oauth/_oauth_impl.py` |
| `oauth_wizard.py` | 1266 | HM 1 + reg 1 | 1 | 2 | `oauth/oauth_wizard.py` |
| `endpoint_analytics.py` | 504 | HM 1 | 2 | 2 | `observability/endpoint_analytics.py` |
| `slo.py` | 531 | HM 1 | 1 | 4 | `observability/slo.py` |
| `gallery.py` | 338 | HM 1 | 1 | 3 | `public/gallery.py` |
| `security_debate.py` | 316 | HM 1 + reg 1 | 1 | 3 | `security/security_debate.py` |
| `threat_intel.py` | 560 | HM 1 + reg 1 | 2 | 3 | `security/threat_intel.py` |
| `analytics_metrics.py` | 14 | none | 0 | 1 | retire -> `analytics/_analytics_metrics_impl.py` |
| `compliance_handler.py` | 18 | HM 1 + reg 1 | 0 | 5 | retire -> `compliance/handler.py` |
| `status_page.py` | 110 | none | 1 | 0 | retire -> `public/status_page.py` |

### Batch 2 (41 files, 21276 LOC)

| flat file | LOC | registration | `aragora/` refs | test refs | target |
|---|---|---|---|---|---|
| `agent_bridge.py` | 741 | HM 1 | 0 | 1 | `agents/agent_bridge.py` |
| `external_agents.py` | 565 | HM 1 + reg 1 | 1 | 3 | `agents/external_agents.py` |
| `feedback_hub.py` | 99 | HM 1 + reg 1 | 0 | 3 | `agents/feedback_hub.py` |
| `harnesses.py` | 351 | reg 1 | 2 | 0 | `agents/harnesses.py` |
| `introspection.py` | 319 | HM 1 | 1 | 5 | `agents/introspection.py` |
| `laboratory.py` | 240 | HM 1 | 1 | 3 | `agents/laboratory.py` |
| `persona.py` | 554 | HM 1 | 1 | 3 | `agents/persona.py` |
| `routing.py` | 296 | HM 1 | 6 | 6 | `agents/routing.py` |
| `selection.py` | 531 | HM 1 + reg 1 | 1 | 5 | `agents/selection.py` |
| `verticals.py` | 908 | HM 1 | 2 | 3 | `agents/verticals.py` |
| `audience_suggestions.py` | 155 | HM 1 + reg 1 | 1 | 2 | `debates/audience_suggestions.py` |
| `auditing.py` | 990 | HM 1 | 2 | 6 | `debates/auditing.py` |
| `belief.py` | 870 | HM 1 | 2 | 8 | `debates/belief.py` |
| `breakpoints.py` | 370 | HM 1 | 1 | 4 | `debates/breakpoints.py` |
| `composite.py` | 567 | HM 1 + reg 1 | 1 | 4 | `debates/composite.py` |
| `context_budget.py` | 141 | HM 1 + reg 1 | 1 | 2 | `debates/context_budget.py` |
| `critique.py` | 357 | HM 1 | 1 | 6 | `debates/critique.py` |
| `debate_intervention.py` | 346 | HM 1 | 1 | 0 | `debates/debate_intervention.py` |
| `debate_stats.py` | 130 | HM 1 + reg 1 | 1 | 3 | `debates/debate_stats.py` |
| `deliberations.py` | 373 | HM 1 | 1 | 2 | `debates/deliberations.py` |
| `hybrid_debate_handler.py` | 348 | HM 1 + reg 1 | 1 | 4 | `debates/hybrid_debate_handler.py` |
| `moments.py` | 404 | HM 1 | 1 | 4 | `debates/moments.py` |
| `tournaments.py` | 561 | HM 1 | 2 | 4 | `debates/tournaments.py` |
| `uncertainty.py` | 366 | HM 1 | 1 | 2 | `debates/uncertainty.py` |
| `visualization.py` | 248 | HM 1 | 1 | 0 | `debates/visualization.py` |
| `decision.py` | 574 | HM 1 | 2 | 3 | `decisions/decision.py` |
| `explainability.py` | 1059 | HM 1 | 3 | 8 | `decisions/explainability.py` |
| `explainability_store.py` | 568 | none | 1 | 5 | `decisions/explainability_store.py` |
| `plans.py` | 587 | HM 1 + reg 1 | 3 | 5 | `decisions/plans.py` |
| `receipt_export.py` | 117 | HM 1 + reg 1 | 1 | 3 | `decisions/receipt_export.py` |
| `receipts.py` | 2041 | HM 1 + reg 1 | 4 | 9 | `decisions/receipts.py` |
| `cross_pollination.py` | 678 | HM 9 + reg 9 | 2 | 3 | `evolution/cross_pollination.py` |
| `genesis.py` | 689 | HM 1 | 1 | 7 | `evolution/genesis.py` |
| `replays.py` | 524 | HM 1 | 1 | 4 | `evolution/replays.py` |
| `training.py` | 1072 | HM 1 | 1 | 6 | `evolution/training.py` |
| `checkpoints.py` | 555 | HM 1 | 3 | 3 | `memory/checkpoints.py` |
| `consensus.py` | 866 | HM 1 | 2 | 9 | `memory/consensus.py` |
| `memory_unified.py` | 393 | reg 1 | 0 | 1 | `memory/memory_unified.py` |
| `sandbox.py` | 280 | HM 1 | 5 | 0 | `tasks/sandbox.py` |
| `benchmarking.py` | 146 | HM 1 + reg 1 | 2 | 2 | `verification/benchmarking.py` |
| `evaluation.py` | 297 | HM 1 | 1 | 3 | `verification/evaluation.py` |

### Batch 3 (45 files, 30292 LOC)

| flat file | LOC | registration | `aragora/` refs | test refs | target |
|---|---|---|---|---|---|
| `action_canvas.py` | 795 | HM 1 + reg 1 | 1 | 2 | `canvas/action_canvas.py` |
| `canvas_pipeline.py` | 2600 | HM 1 + reg 1 | 2 | 11 | `canvas/canvas_pipeline.py` |
| `goal_canvas.py` | 739 | HM 1 + reg 1 | 1 | 3 | `canvas/goal_canvas.py` |
| `idea_canvas.py` | 707 | HM 1 + reg 1 | 1 | 3 | `canvas/idea_canvas.py` |
| `orchestration_canvas.py` | 701 | HM 1 + reg 1 | 1 | 3 | `canvas/orchestration_canvas.py` |
| `marketplace.py` | 716 | none | 4 | 5 | `catalog/marketplace.py` |
| `marketplace_browse.py` | 217 | HM 1 + reg 1 | 1 | 1 | `catalog/marketplace_browse.py` |
| `marketplace_pilot.py` | 395 | HM 1 + reg 1 | 1 | 3 | `catalog/marketplace_pilot.py` |
| `skill_marketplace.py` | 626 | HM 1 + reg 1 | 1 | 4 | `catalog/skill_marketplace.py` |
| `skills.py` | 411 | HM 1 + reg 1 | 1 | 4 | `catalog/skills.py` |
| `template_discovery.py` | 162 | HM 1 + reg 1 | 1 | 1 | `catalog/template_discovery.py` |
| `template_marketplace.py` | 1229 | HM 1 + reg 2 | 2 | 7 | `catalog/template_marketplace.py` |
| `email_debate.py` | 343 | HM 1 + reg 1 | 1 | 3 | `email/email_debate.py` |
| `email_services.py` | 1097 | HM 1 | 2 | 4 | `email/email_services.py` |
| `email_triage.py` | 219 | HM 1 + reg 1 | 1 | 2 | `email/email_triage.py` |
| `accounting.py` | 1467 | none | 1 | 2 | `finance/accounting.py` |
| `ap_automation.py` | 736 | HM 1 + reg 1 | 1 | 2 | `finance/ap_automation.py` |
| `ar_automation.py` | 724 | HM 1 + reg 1 | 1 | 2 | `finance/ar_automation.py` |
| `expenses.py` | 1318 | HM 1 + reg 1 | 1 | 4 | `finance/expenses.py` |
| `invoices.py` | 1156 | HM 1 + reg 1 | 1 | 3 | `finance/invoices.py` |
| `a2a.py` | 654 | HM 1 | 1 | 3 | `gateway/a2a.py` |
| `gateway_agents_handler.py` | 385 | HM 1 + reg 1 | 1 | 3 | `gateway/gateway_agents_handler.py` |
| `gateway_config_handler.py` | 214 | HM 1 + reg 1 | 1 | 2 | `gateway/gateway_config_handler.py` |
| `gateway_credentials_handler.py` | 516 | HM 1 + reg 1 | 1 | 3 | `gateway/gateway_credentials_handler.py` |
| `gateway_handler.py` | 596 | HM 1 + reg 1 | 1 | 2 | `gateway/gateway_handler.py` |
| `gateway_health_handler.py` | 307 | HM 1 + reg 1 | 1 | 3 | `gateway/gateway_health_handler.py` |
| `inbox_actions.py` | 358 | none | 1 | 2 | `inbox/inbox_actions.py` |
| `inbox_command.py` | 926 | HM 1 + reg 1 | 4 | 7 | `inbox/inbox_command.py` |
| `inbox_services.py` | 522 | none | 1 | 1 | `inbox/inbox_services.py` |
| `bindings.py` | 533 | HM 1 + reg 1 | 1 | 3 | `integrations/bindings.py` |
| `cloud_storage.py` | 1274 | none | 1 | 2 | `integrations/cloud_storage.py` |
| `computer_use_handler.py` | 697 | HM 1 + reg 1 | 1 | 3 | `integrations/computer_use_handler.py` |
| `erc8004.py` | 755 | HM 1 + reg 1 | 2 | 3 | `integrations/erc8004.py` |
| `extensions.py` | 460 | none | 0 | 3 | `integrations/extensions.py` |
| `external_integrations.py` | 1441 | HM 1 + reg 1 | 1 | 3 | `integrations/external_integrations.py` |
| `integration_management.py` | 925 | HM 1 + reg 1 | 2 | 5 | `integrations/integration_management.py` |
| `mcp_tools_handler.py` | 123 | HM 1 + reg 1 | 1 | 2 | `integrations/mcp_tools_handler.py` |
| `partner.py` | 503 | HM 1 + reg 1 | 1 | 3 | `integrations/partner.py` |
| `openclaw_gateway.py` | 105 | HM 1 + reg 1 | 4 | 6 | `openclaw/openclaw_gateway.py` |
| `dag_operations.py` | 257 | HM 1 + reg 1 | 0 | 1 | `pipeline/dag_operations.py` |
| `pipeline_graph.py` | 589 | HM 1 + reg 1 | 1 | 1 | `pipeline/pipeline_graph.py` |
| `pipeline_telemetry.py` | 134 | none | 0 | 1 | `pipeline/pipeline_telemetry.py` |
| `_shared_inbox_handler.py` | 173 | none | 3 | 3 | `shared_inbox/_shared_inbox_handler.py` |
| `playbooks.py` | 217 | HM 1 + reg 1 | 1 | 1 | `workflows/playbooks.py` |
| `workflow_templates.py` | 1270 | HM 6 + reg 5 | 1 | 3 | `workflows/workflow_templates.py` |

### Batch 4 (42 files, 33760 LOC)

| flat file | LOC | registration | `aragora/` refs | test refs | target |
|---|---|---|---|---|---|
| `platform_config.py` | 196 | reg 1 | 0 | 2 | `admin/platform_config.py` |
| `autonomous_learning.py` | 1294 | HM 1 + reg 1 | 0 | 2 | `autonomous/autonomous_learning.py` |
| `gastown_dashboard.py` | 687 | HM 1 + reg 1 | 1 | 3 | `autonomous/gastown_dashboard.py` |
| `nomic.py` | 1333 | HM 1 | 2 | 5 | `autonomous/nomic.py` |
| `ralph_dashboard.py` | 174 | HM 1 + reg 1 | 0 | 3 | `autonomous/ralph_dashboard.py` |
| `self_improve.py` | 1362 | HM 1 + reg 1 | 1 | 5 | `autonomous/self_improve.py` |
| `self_improve_details.py` | 802 | HM 1 + reg 1 | 0 | 3 | `autonomous/self_improve_details.py` |
| `budgets.py` | 1234 | HM 1 | 1 | 3 | `billing/budgets.py` |
| `usage_metering.py` | 808 | HM 1 + reg 1 | 1 | 3 | `billing/usage_metering.py` |
| `code_review.py` | 448 | HM 1 + reg 1 | 1 | 3 | `codebase/code_review.py` |
| `dependency_analysis.py` | 541 | HM 1 + reg 1 | 1 | 2 | `codebase/dependency_analysis.py` |
| `repository.py` | 586 | HM 1 + reg 1 | 1 | 3 | `codebase/repository.py` |
| `reviews.py` | 132 | HM 1 | 1 | 4 | `codebase/reviews.py` |
| `operator_intervention.py` | 337 | none | 0 | 1 | `control_plane/operator_intervention.py` |
| `queue.py` | 1037 | HM 1 | 1 | 3 | `control_plane/queue.py` |
| `playground.py` | 4256 | HM 1 + reg 1 | 4 | 18 | `demo/playground.py` |
| `gauntlet_v1.py` | 863 | HM 8 + reg 8 | 1 | 2 | `gauntlet/gauntlet_v1.py` |
| `approvals_inbox.py` | 76 | HM 1 + reg 1 | 1 | 2 | `governance/approvals_inbox.py` |
| `moderation.py` | 133 | HM 1 + reg 1 | 1 | 2 | `governance/moderation.py` |
| `policy.py` | 786 | HM 1 | 8 | 4 | `governance/policy.py` |
| `review_queue.py` | 882 | HM 1 | 3 | 2 | `governance/review_queue.py` |
| `review_queue_brief.py` | 552 | none | 0 | 0 | `governance/review_queue_brief.py` |
| `runs.py` | 246 | reg 1 | 1 | 2 | `governance/runs.py` |
| `settlements.py` | 454 | HM 1 + reg 1 | 0 | 2 | `governance/settlements.py` |
| `knowledge_chat.py` | 625 | HM 1 | 1 | 5 | `knowledge/knowledge_chat.py` |
| `knowledge_flow.py` | 363 | reg 1 | 0 | 1 | `knowledge/knowledge_flow.py` |
| `ml.py` | 737 | HM 1 + reg 1 | 1 | 2 | `knowledge/ml.py` |
| `rlm.py` | 1281 | HM 1 | 2 | 6 | `knowledge/rlm.py` |
| `devices.py` | 943 | HM 1 | 1 | 2 | `notifications/devices.py` |
| `coordination.py` | 657 | HM 1 + reg 1 | 1 | 2 | `orchestration/coordination.py` |
| `feedback.py` | 476 | HM 1 + reg 1 | 3 | 3 | `sme/feedback.py` |
| `onboarding.py` | 1707 | HM 9 + reg 1 | 7 | 7 | `sme/onboarding.py` |
| `readiness_check.py` | 201 | HM 1 + reg 1 | 1 | 1 | `sme/readiness_check.py` |
| `sme_success_dashboard.py` | 904 | HM 1 + reg 1 | 1 | 3 | `sme/sme_success_dashboard.py` |
| `sme_usage_dashboard.py` | 953 | HM 1 + reg 1 | 1 | 2 | `sme/sme_usage_dashboard.py` |
| `spectate_ws.py` | 680 | HM 1 + reg 1 | 0 | 2 | `streaming/spectate_ws.py` |
| `transcription.py` | 952 | HM 1 | 2 | 6 | `voice/transcription.py` |
| `webhook_management.py` | 1235 | HM 1 | 3 | 10 | `webhooks/webhook_management.py` |
| `organizations.py` | 1085 | HM 1 | 3 | 4 | `workspace/organizations.py` |
| `workspace_module.py` | 770 | none | 7 | 4 | `workspace/workspace_module.py` |
| `connectors.py` | 952 | reg 1 | 2 | 11 | retire -> `connectors/legacy.py` |
| `slack.py` | 20 | none | 3 | 1 | retire -> `bots/slack.py` |

## 6. Per-batch verification recipe

Run in the batch's worktree, in this order, and paste the tail lines of each
into the PR body. `$ENV` below means
`AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true`
(VAL-P4B-006 machine quirk: without it botocore prompts for MFA at import).

1. **Red first (rule c), on the pre-move commit.** For each file in the
   batch, `python3 scripts/ci/check_moved_handler_shim.py <basename>` (the
   VAL-P4B-007 probe script, verbatim from the contract, committed by
   batch 1 in PR #10000; `/tmp/p4val/t7.py` until that lands)
   must FAIL with an `AssertionError` listing no DeprecationWarning
   because the old path still imports cleanly. Capture the failure once per
   batch, not per file, if the output is long.
2. **Move.** `git mv aragora/server/handlers/<f>.py aragora/server/handlers/<dir>/<f>.py`.
   Rewrite `from .base import` -> `from ..base import` (and the other
   single-dot relatives) in the moved file. Batch relative-import line counts
   measured today: B1 70, B2 60, B3 30, B4 72. Update the target
   `<dir>/__init__.py` only if it enumerates its modules (debates 21,
   email 9, pipeline 7, compliance 7, agents 7, knowledge 6, memory 5,
   costs 4, inbox 4 do; admin and security do not).
3. **Repoint the tables.** Edit `HANDLER_MODULES` values and every direct
   `_safe_import("aragora.server.handlers.<f>", ...)` string in
   `handler_registry/*.py` to the new dotted path. Append the
   `MOVED_MODULES` entries. Run the §2.3 invariant script; the two counts on
   its first line must match the pre-move run and it must print no `BROKEN`.
   Also rewrite this batch's relative imports inside the
   `if TYPE_CHECKING:` block of `handlers/__init__.py` (`from .<f> import
   ...` -> `from .<dir>.<f> import ...`). That block is type-only and never
   executes, so the step-5 `rg` (which matches dotted absolute paths) never
   lists it, nothing at runtime exercises it, and it goes stale silently.
   Verify with `rg -n "^\s+from \.(<f1>|<f2>|...) import" aragora/server/handlers/__init__.py`
   printing nothing. That `rg` is the only check for the rewrite: mypy with
   the CI gate's `--ignore-missing-imports` reports "no issues" on a
   type-only import of a module that no longer exists (verified on a
   throwaway package), and
   `python3 -c 'import typing; typing.TYPE_CHECKING=True; import aragora.server.handlers'`
   fails on today's tree before reaching the block with a pydantic circular
   import, `cannot import name 'BaseModel' from partially initialized module
   'pydantic'`, identically on `origin/main`.
4. **Boot probe (VAL-P4B-006).**
   `$ENV python3 -c "from aragora.server.unified_server import run_unified_server; print('ok')" </dev/null; echo "exit=$?"`
   must print `ok` and `exit=0`. Then
   `$ENV python3 -c "import logging; logging.basicConfig(level=logging.WARNING); from aragora.server.unified_server import UnifiedHandler; UnifiedHandler._init_handlers()" 2>&1 | grep -c 'Failed to import'`
   must print `0`.
5. **Rewrite runtime consumers of the old path.**
   `rg -nU "aragora\.server\.handlers\.(<f1>|<f2>|...)\b|from aragora\.server\.handlers import (\([^)]*)?\b(<f1>|<f2>|...)\b" aragora/ scripts/ | rg -v "handlers/(_lazy_imports|__init__)\.py|handler_registry/"`
   lists every runtime import, `importlib` string and `sys.modules.get`
   key for the batch's files. The second alternation catches the bare
   package form, which the dotted pattern alone misses: today
   `aragora/server/handlers/review_queue.py:51` does
   `from aragora.server.handlers import review_queue_brief` (a batch-4
   mover) and would go through the package `__getattr__` shim on every
   request without it. `-U` plus the optional `(\([^)]*)?` group make the
   bare form match a parenthesised multi-line import list as well as a
   single line (verified on a synthetic file with both forms). Today's
   bare-form sites per batch are the last row of the §3.2 table (6/1/7/3,
   all single-line). Rewrite each to the new dotted path in the
   same PR (the finder keeps them working, §3.3, but a per-request
   `DeprecationWarning` is log noise). Also rewrite the `from ..X import`
   lines in §4.6 for the batch's files. Then run
   `$ENV python3 -W "error:aragora.server.handlers.:DeprecationWarning" -c "from aragora.server.unified_server import UnifiedHandler; UnifiedHandler._init_handlers(); print('boot ok')"`
   and confirm `boot ok`, exit 0. The filter is scoped to the finder's
   message prefix on purpose: an unscoped `-W error::DeprecationWarning`
   exits 1 on today's tree at `aragora/server/errors.py:7` before any
   handler import (verified), so it would fail every batch. Under the
   scoped filter, any surviving old-path import on the boot path raises,
   including one wrapped in `try/except ImportError` (the warning is not
   an `ImportError`, so `stream/servers_route_registration.py:41-46` would
   crash boot rather than silently disable its routes; verified on the
   prototype). Test consumers (`import`, `from ... import`, `patch(...)`
   strings) may stay on the old path.
6. **Green shim probe (VAL-P4B-007).** `python3 scripts/ci/check_moved_handler_shim.py <basename>`
   must print `PASS <basename>` for every file in the batch, including
   retired ones other than `connectors`. Then for every basename that is
   also a directory name after the move,
   `ls aragora/server/handlers/ | sed 's/\.py$//' | sort | uniq -d`
   must print only `connectors` (the pre-existing flat/package pair from
   §4.4, retired in batch 4); any other line names a `MOVED_MODULES` key
   that a same-named package shadows, i.e. a dead shim entry (§3.4). The
   `sed` is what makes the check fire: without stripping `.py`, a file and
   a directory never compare equal and the list is always empty.
7. **Handler-specific tests.** For every target dir touched:
   `set -o pipefail; python3 -m pytest tests/handlers/<dir> tests/server/handlers/<dir> -q -p no:cacheprovider --timeout=120 </dev/null 2>&1 | tail -3`
   plus every test file named in the batch's "test refs" column that lives
   outside those two trees (find them with
   `rg -l "handlers\.(<f1>|<f2>|...)\b" tests/ | rg -v "tests/(server/)?handlers/<dir>/"`).
   Every run must end `N passed` with no `failed`/`error`.
8. **Smoke tier (VAL-P4B-005).**
   `$ENV PYTEST_BIN="python3 -m pytest" bash scripts/test_tiers.sh smoke </dev/null; echo "exit=$?"`
   must end `exit=0`.
9. **Ratchets.** `python3 scripts/ci/measure_import_graph.py` must report the
   flat-root count equal to `git ls-files ':(glob)aragora/server/handlers/*.py' | grep -v '__init__\.py$' | wc -l`
   within 1 (VAL-P4B-008); `python3 scripts/check_sdk_parity.py --strict`
   must stay rc=0 with `missing_from_both 0/0` (a handler that fails to
   import is SKIPped by the parity script, which is a silent regression, so
   compare the parity route count against the pre-move run too).
10. **Standard gates (rule d).** `make lint`, `ruff format --check aragora/ tests/ scripts/`,
    `bash scripts/preflight_mypy.sh --diff-base origin/main` after committing,
    `bash scripts/automation_pr_preflight.sh origin/main HEAD`.

### 6.1 Known per-batch costs, measured

- **mypy changed-file gate.** The required CI `typecheck` check runs
  `mypy --ignore-missing-imports --follow-imports=skip` over every touched
  `aragora/**.py` with no baseline (`library/environment.md` L21-23). Moving
  a file touches it, so pre-existing errors in moved files must be fixed in
  the same PR, behaviour-preservingly. Measured per batch with exactly that
  command over the batch's files: **B1 25, B2 27, B3 15, B4 22** errors.
  `.mypy-baseline` (376 of its 3,115 lines are keyed `aragora/server/handlers/<flat>.py`) is
  consumed only by the advisory `mypy-baseline-ratchet.yml` line-count delta
  and by `scripts/ci/mypy_with_baseline.py`; a move changes the path key so
  those entries become "unexpectedly fixed" (allowed by `--allow-unsynced`)
  and the new-path errors count as new. Fix them rather than `--sync`.
- **`scripts/baselines/file_size_baseline.json`** is path-keyed, shrink-only
  and fail-on-new, but `scripts/ci/check_file_sizes.py` is not wired into any
  workflow or Makefile target (ambient, currently rc=1 on main for unrelated
  files). Batches that move `canvas_pipeline.py` (2600) and `playground.py`
  (4256) should carry their baseline rows to the new path in the same PR so
  the checker stays honest, but this is not a merge gate.
- **`scripts/baselines/bandit_medium_high_confidence.json`** has one flat
  entry (`playground.py:1653`); carry it with the file in batch 4.
- **LOC bound.** Rule (5)'s <= 800 changed LOC per PR is measured with
  `git diff --numstat`, which counts a pure rename as 0 when git detects it
  (>= 50 % similarity). The relative-import rewrites, table edits, shim
  entries and mypy fixes are the real diff; the per-batch relative-import
  counts above put every batch inside the bound with margin. If a batch's
  measured diff exceeds 800, split it at a subdir boundary and open a second
  Tier-3 PR in the same settlement round rather than trimming the shim.

## 7. Batch plan (Tier 3, settlement-batched)

Every handlers PR is Tier 3 (`aragora/server/handlers/` is in
`TIER_3_PREFIXES`, `aragora/cli/commands/review_queue.py:246`), so each batch
parks as one draft PR with a settlement packet and the phase merge train
settles them. The grouping below is chosen so that one operator sitting can
settle a batch by reading one packet whose test evidence is a handful of
directory-scoped pytest tails.

| Batch | Files | LOC | Target dirs | Theme | Settlement note |
|---|---|---|---|---|---|
| 1 | 45 | 19,170 | admin, analytics, analytics_dashboard, auth, compliance, metrics, oauth, observability, public, security | ops, health, compliance, auth | Owns `admin/health/`, so it carries the k8s readiness fix (§8). Includes the three batch-1 retirements from §4.4 (`analytics_metrics`, `compliance_handler`, `status_page`); `slack` and `connectors` retire with batch 4 (§5). |
| 2 | 41 | 21,276 | agents, debates, decisions, evolution, memory, tasks, verification | core debate loop | Highest test density (debates alone has 16 movers); `debates/__init__.py` enumerates 21 modules and must be edited. |
| 3 | 45 | 30,292 | canvas, catalog (new), email, finance (new), gateway, inbox, integrations, openclaw, pipeline, shared_inbox, workflows | pipeline, integrations, SME verticals | Creates the two new subdirs; rewrites `stream/servers_route_registration.py:42` (`accounting`); `canvas_pipeline.py` (2600 LOC) carries its size-baseline row. |
| 4 | 42 | 33,760 | autonomous, billing, codebase, control_plane, demo, gauntlet, governance, knowledge, notifications, orchestration, sme, streaming, voice, webhooks, workspace | governance, autonomy, remaining verticals | Holds the two path-frozen files (`platform_config.py` PR #9989, `webhook_management.py` PR #9853) and `connectors.py`; re-census before opening. Rewrites the six `workspace_module` runtime imports (§3.2). `playground.py` (4256 LOC) carries its size and bandit baseline rows. |

Ordering rationale: batch 1 first because it is the smallest by LOC, has
the fewest relative imports to rewrite after batch 3, and lands the shim
machinery (`MOVED_MODULES`, the finder, the `__getattr__` branch, the
ledger format) that batches 2 to 4 only append to. Batch 4 last because its
frozen files need the foreign PRs to merge or the census to be redone.

The k8s readiness fix (§8) rides batch 1 because that batch owns `admin/`;
if the operator prefers a separately revertable change, it can be split
out as its own small Tier-3 PR ahead of batch 1 with no change to the rest
of this plan. Either way it is one settlement decision in the same phase.

Path-freeze census at design time (open PRs touching handler files, from a
paginated `gh pr list --json files`): flat files frozen are
`platform_config.py` (#9989) and `webhook_management.py` (#9853). Subdir
files touched by open PRs, which the batches must not edit:
`agents/agents.py`, `agents/recommendations.py`, `costs/handler.py`,
`debates/cost_estimation.py`, `debates/diagnostics.py` (#9989);
`payments/billing.py`, `payments/stripe.py` (#9116); `tasks/execution.py`
(#9057); `inbox/email_actions.py` (#9033); `sme/teams_workspace.py` (#8939).
None of these collide with a landing path in §5. Re-run the census before
each batch opens (rule b).

## 8. Folded-in bug: k8s readiness probe never sees the Redis pool

`aragora/server/handlers/admin/health/kubernetes.py:178` does

```python
from aragora.cache.redis_cache import get_redis_pool
```

inside `except (ImportError, RuntimeError)`. `aragora/cache.py` is a module,
not a package, so `aragora.cache.redis_cache` never resolves, the
`ImportError` is swallowed, and `checks["redis_pool"]` reads
`"not_configured"` even when `REDIS_URL` is set. The real function is
`aragora/utils/redis_config.py:85` (`def get_redis_pool() -> Any | None`).

Batch 1 owns `admin/` and therefore this fix:

- repoint the import to `from aragora.utils.redis_config import get_redis_pool`;
- add `test_readiness_fast_reports_redis_pool_when_url_set` to
  `tests/server/handlers/admin/health/test_kubernetes.py` next to the
  existing `test_readiness_fast_*` cases (the `redis_pool` check lives in
  `readiness_probe_fast`, lines 174-183; `readiness_dependencies` writes a
  different key, `checks["redis"]`): set `REDIS_URL` via `monkeypatch`,
  `patch("aragora.utils.redis_config.get_redis_pool", return_value=object())`,
  call `readiness_probe_fast`, assert `checks["redis_pool"] is True`; and
  the negative twin with `return_value=None` asserting `False` (not
  `"not_configured"`). Red-first: both fail today because the import never
  reaches the patched name.

This is a behaviour change on a readiness path, which is exactly why it
rides a Tier-3 PR rather than a doc-tier one.

## 9. Acceptance mapping

| Assertion | Where this design satisfies it |
|---|---|
| VAL-P4B-001 (< 20 flat) | §1: 14 remain; §3.1 forbids stub files |
| VAL-P4B-005 (smoke green) | §6 step 8, every batch |
| VAL-P4B-006 (entrypoint imports) | §6 step 4, every batch |
| VAL-P4B-007 (old path + DeprecationWarning with basename) | §3.3 finder (prototype row 9 runs the contract's probe verbatim); §6 steps 1 and 6 |
| VAL-P4B-008 (tool count == ls-files count) | §6 step 9 |
| VAL-P4B-002/003/004/009 | owned by `p4b-cycles-and-counts` after the four batches; the batches must not regress them, which §6 step 9's `measure_import_graph.py` run checks |

## 10. Reproduction

The census columns in §5 come from a one-off script over `origin/main` at
`1ad1162d59`: for each flat basename, counts of matches for
`handlers\.<name>\b|handlers import <name>\b` in `_lazy_imports.py`,
`handler_registry/*.py`, `handlers/__init__.py`, `unified_server.py`, the
rest of `aragora/`, `tests/`, and `scripts/`. Re-run before each batch; the
numbers only need to be right for the files in that batch. The regex
over-counts a basename that is also a prefix of a subdir module path
(`connectors.py` shows `reg 1` from `handler_registry/admin.py:432`, which
names `connectors.management`); anchor with `handlers\.<name>(\.|\b)` and
exclude `<name>\.` when re-measuring a name that collides with a package.

The VAL-P4B-007 probe (`/tmp/p4val/t7.py`) is defined verbatim in the
validation contract and is machine-local by design. Batch 1 (PR #10000)
commits it as `scripts/ci/check_moved_handler_shim.py` so §6 steps 1 and 6
are reproducible in CI. The probe body is verbatim; the committed file adds
a shebang, a module docstring, and splits the `import` statement across
three lines for ruff E401 (plus the blank lines around them). It keeps the contract's
`warnings.simplefilter("always")`, which is what makes the finder's warning
visible when the import happens inside a helper rather than `__main__`.
