# Route Burn-Down Playbook

This playbook is the mechanical disposition standard for the contract-drift
program anchored at [issue #9378](https://github.com/synaptent/aragora/issues/9378).
The canonical work list is
`scripts/baselines/contract_drift_inventory.json`; generated packet membership
is never hand-edited.

## Preconditions

1. Start from current `origin/main` in an isolated worktree.
2. Read operator steering, claim the issue or PR lane, and acquire a work lease
   for the exact files before editing.
3. Confirm the inventory is internally consistent:

   ```bash
   python scripts/generate_contract_drift_inventory.py --check
   ```

4. Generate a fresh packet snapshot into an empty temporary directory:

   ```bash
   python scripts/route_burndown_batches.py \
     --output-dir /tmp/aragora-route-burndown \
     --batch-size 25 \
     --json
   ```

Record the inventory commit, open-entry count, packet ID, and entry digest in
the PR body. A packet is a snapshot, not a new source of truth.

## Disposition Rules

Probe real behavior before choosing a disposition. `ROUTES` membership alone
does not prove a route is served: require a matching `can_handle` result and a
real dispatch branch, with a focused handler test where practical.

| Disposition | Use when | Required result |
|---|---|---|
| `DOCUMENT` | The server really serves the route, but the public spec omits it. | Add it through `scripts/generate_openapi.py` and the handler metadata used by the generator. Never hand-edit generated OpenAPI files. |
| `WIRE` | An SDK or documented operation is not dispatched, but the capability should exist. | Implement the handler dispatch, document the operation, and add focused server and SDK contract tests. |
| `REMOVE` | The operation is dead surface and should not exist. | Remove the handler, spec, and SDK surface together. Public SDK removal requires an explicit operator-reviewed compatibility decision; a Tier 0-2 worker may classify and escalate it but must not perform an unauthorized removal. |
| `DEPRECATE+PARALLEL` | Public compatibility prevents immediate removal and a contract-correct replacement can ship alongside it. | Deprecate the old method and add the replacement using the #9366/#9367/#9371 pattern. This is staged migration, not closure: the old route must later be wired or removed before its drift entry can resolve. |

**Deprecation alone never closes an entry.** A closing PR must make the
operation contract-correct or remove the invoking surface under the required
public-API authority.

## Per-Entry Procedure

1. Locate the inventory ID in its source baseline and in the Python/TypeScript
   SDK, OpenAPI generator metadata, handler registry, and dispatch code.
2. Record concrete served/unserved evidence. For a served claim, cite the
   handler and focused dispatch test. For an unserved claim, cite the missing or
   rejecting branch.
3. Apply exactly one disposition. Do not combine unrelated cleanup with the
   packet.
4. Update generated specs and SDK artifacts only through their generators.
5. Remove baseline entries only when the regenerated validator output proves
   the violation is gone. Never lower a budget or delete inventory history.
6. Regenerate the inventory. Resolved records remain append-only with
   `status: resolved` and `resolved_on`; new unexplained records must fail
   closed rather than be absorbed into the batch.

If a packet mixes independent owners or dispositions, ship one coherent slice
and leave the remaining IDs unchecked. A partial batch is valid only when its
PR names the exact completed IDs and the next packet snapshot is regenerated
after merge.

## Closing Evidence Contract

A burn-down PR is ready for exact-head review only when all of the following
are true:

1. **Manifest delta:** the diff in
   `scripts/baselines/contract_drift_inventory.json` contains only the intended
   open-to-resolved transitions. Baseline removals match validator output.
2. **Focused behavior:** relevant handler, SDK, and generator tests pass. A
   route is not credited from metadata-only evidence.
3. **No regression:** both route and SDK validators pass against their
   baselines:

   ```bash
   python scripts/validate_openapi_routes.py \
     --spec docs/api/openapi_generated.json \
     --baseline scripts/baselines/validate_openapi_routes.json \
     --fail-on-missing
   python scripts/verify_sdk_contracts.py \
     --strict \
     --baseline scripts/baselines/verify_sdk_contracts.json
   ```

4. **Spec and inventory fixed point:** regenerate the OpenAPI artifacts, then
   regenerate and check the inventory. A second check must produce no diff:

   ```bash
   python scripts/generate_openapi.py --output docs/api/openapi_generated.json
   python scripts/generate_openapi.py \
     --output docs/api/openapi_generated.yaml \
     --format yaml
   python scripts/generate_contract_drift_inventory.py
   python scripts/generate_contract_drift_inventory.py --check
   git diff --check
   ```

5. **Ratchet:** the PR-mode contract-drift gate is non-worsening and the packet
   reports the exact source-bucket reduction:

   ```bash
   python scripts/check_contract_drift_ratchet.py \
     --mode pr \
     --base-ref origin/main \
     --strict \
     --json
   ```

6. **Review last:** commit and push the final head, run normal checks, then
   collect exact-head model evidence. Any later edit invalidates that evidence
   and requires a new collection. P0/P1 or blocking dissent stops the batch.

## Worker Boundaries

- One coherent packet slice per PR; use draft first, then ready through normal
  gates.
- Ordinary Tier 0-2 workers may document served routes, wire bounded behavior,
  add compatible parallel methods, and prepare decision evidence.
- Do not edit `.github/workflows`, branch protection, release controls,
  protected governance files, or other Tier 3/4 surfaces in this lane.
- Do not remove a public SDK operation without the required operator decision.
- Do not use `--admin`, force-push, weaken checks, skip tests, or treat a
  cancelled optional job as evidence that a required gate passed.
- Collect evidence after implementation and validation, never as a substitute
  for them.

## Handoff

After a batch merges, regenerate into a new empty directory and select the
lowest numbered packet with unchecked entries. The successor should run:

```bash
git fetch origin main
python scripts/generate_contract_drift_inventory.py --check
python scripts/route_burndown_batches.py \
  --output-dir /tmp/aragora-route-burndown-next \
  --batch-size 25 \
  --json
```

Post the new open count, packet digest, merged PR, and source-bucket delta to
issue #9378. Escalate wire-or-remove decisions as one bounded list rather than
one operator interruption per entry.
