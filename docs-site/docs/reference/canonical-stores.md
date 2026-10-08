---
title: Canonical Stores
description: Canonical Stores
---

# Canonical Stores

Aragora has a single source of truth for work‑tracking (convoys/beads)
and gateway/inbox persistence. This document describes the canonical
store interfaces and how to use them.

## Convoys / Beads / Workspaces

Canonical stores live under `aragora.nomic.stores`. Use the canonical
helpers rather than constructing store instances directly:

```python
from aragora.stores import get_canonical_workspace_stores

stores = get_canonical_workspace_stores()
bead_store = await stores.bead_store()
convoy_manager = await stores.convoy_manager()
```

These helpers wrap `create_bead_store()` and `get_convoy_manager()`
from `aragora.nomic.beads` and `aragora.nomic.convoys`.

## Gateway / Inbox

Canonical gateway persistence is managed by `GatewayStore` and the
unified inbox store. Use the canonical helper:

```python
from aragora.stores import get_canonical_gateway_stores

stores = get_canonical_gateway_stores()
gateway_store = stores.gateway_store()
inbox_store = stores.inbox_store()
```

Gateway stores respect `ARAGORA_GATEWAY_*` environment overrides
(backend/path/redis). For routing and inbox operations, prefer
`GatewayRuntime` in `aragora.gateway.canonical_api`.

## Guidance

- Do not instantiate ad‑hoc stores in production paths.
- Legacy store modules should only be accessed via adapters.
- Prefer canonical accessors in new code and tests.
