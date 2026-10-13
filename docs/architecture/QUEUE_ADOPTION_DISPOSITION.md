# Queue Adoption Disposition

**Decision:** Adopt `aragora/queue` as Aragora's canonical public API and
transport authority for durable server-side jobs.

**Scope:** This resolves only the `aragora/queue` primitive in #8851 acceptance
item 3. It does not unpark the other six primitive dispositions and introduces
no runtime migration.

## Live Evidence

`aragora.queue` is not dormant:

- `scripts/queue_worker.py` runs the Redis Streams debate worker.
- `aragora/server/handlers/queue.py` exposes queue operations and constructs
  jobs through `aragora.queue`.
- Slack, Telegram, WhatsApp, and Teams handlers enqueue debate jobs through
  the same package.
- `aragora/integrations/email_reply_loop.py` uses the Redis queue for routed
  email work.
- The focused `tests/queue/` suite covers job contracts, Redis streams,
  retries, status tracking, tracing, and workers.

The earlier ARCH-015 note inaccurately cited the default-on GauntletWorker as
proof that `aragora.queue` was the sole implementation. GauntletWorker and
several related workers have instead used
`aragora/storage/job_queue_store.py` directly. The startup wiring remains live
in `aragora/server/startup/workers.py`, but it proves a backend split, not a
single implementation.

## Authority Boundary

`aragora.queue` owns the public durable-job contract, enqueue/dequeue transport,
status, retry, and worker-facing API. New durable server-job producers and job
types enter through this package.

`aragora/storage/job_queue_store.py` is a bounded current persistence backend,
not a second public authority. Its existing static importers, dynamic module
references, and per-file backend call counts are baselined by the conformance
test. Consumer and call-site removals are allowed, but a new consumer file or an
added backend call fails the test. Existing consumers may remain until a
separately reviewed migration places the backend behind `aragora.queue`.

The following concerns remain distinct:

- `aragora.missions` defines synchronous mission dispatch.
- `aragora.workflow` defines product DAG execution.
- `aragora.swarm` and `aragora.nomic.dev_coordination` define fleet scheduling,
  ownership, and leases.
- Operational cron belongs to `aragora.scheduler`.

None of those packages may grow a rival durable server-job transport. This
decision also does not revive the removed `aragora.queue:create_default_executor`
re-export recorded by CHR-P4A-004.

## Verification

`tests/docs/test_queue_authority.py` pins the machine-readable ARCH-015 state,
the decision-record link, the live entrypoints, the allowed static-import and
dynamic-reference consumer files, and each consumer's direct backend call
inventory. It resolves absolute and relative imports, ignores vendored and cache
trees, allows consumer or call-site removal, and fails on authority drift or new
backend use; it never mutates the charter or baseline. ARCH-015's
`binding_in_draft` authority is enforced by this focused test, not by
`scripts/check_charter_compliance.py`, whose draft-binding logic applies only to
`CHR-*` registry entries.

## Provenance

- [#8851 operator ruling](https://github.com/synaptent/aragora/issues/8851#issuecomment-4899964631),
  2026-07-06: adopt `aragora/queue`.
- [Operator authorization receipt](https://github.com/synaptent/aragora/issues/8851#issuecomment-5330909322),
  2026-08-18: unpark acceptance item 3 for this bounded disposition only.
- Current-main audit base: `07942c3dda14303ad49ef58d5154bbbb154d6277`.
