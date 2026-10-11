# Gastown + OpenClaw Parity Backlog

This backlog tracks parity work for the Gastown (developer orchestration) and
OpenClaw (consumer assistant) extension layers. It focuses on gaps between
existing Aragora implementations and parity targets, and provides acceptance
criteria for each item.

For SDK cross-language parity debt scheduling, see the 2026-02-25 plan
`SDK_CROSS_PARITY_DEBT_PLAN_2026-02-25.md` (archived dated snapshot); the live
debt baseline is `scripts/baselines/cross_sdk_parity.json`.

Status legend:
- implemented: present and usable in the codebase
- partial: scaffolding exists, but lacks production wiring or protocol parity
- missing: no implementation yet

## Parity Matrix Snapshot (Code-Backed)

### Gastown (Developer Orchestration)

| Capability | Status | Code refs | Notes |
| --- | --- | --- | --- |
| Workspace + rig management | partial | `aragora/extensions/gastown/workspace.py`, `aragora/workspace/manager.py` | Two parallel managers; needs unification |
| Convoy lifecycle | partial | `aragora/extensions/gastown/convoy.py`, `aragora/workspace/convoy.py`, `aragora/nomic/convoys.py` | Three implementations |
| Beads (atomic work units) | partial | `aragora/workspace/bead.py`, `aragora/nomic/beads.py` | Two stores + schema mismatch; canonical store now persists by default |
| Hooks + worktree persistence | partial | `aragora/extensions/gastown/hooks.py`, `aragora/nomic/hook_queue.py` | Hooks + GUPP queue exist, need wiring |
| Mayor/Witness roles | partial | `aragora/nomic/agent_roles.py`, `aragora/nomic/mayor_coordinator.py`, `aragora/nomic/witness_behavior.py` | Core logic exists, needs runtime integration |
| CLI workflows | partial | `aragora/cli/gt.py` | CLI uses nomic convoys/beads |
| Dashboard endpoints | partial | `aragora/server/handlers/gastown_dashboard.py` | Mostly stubs |

### OpenClaw (Consumer Assistant)

| Capability | Status | Code refs | Notes |
| --- | --- | --- | --- |
| Local Gateway server | partial | `aragora/gateway/server.py`, `aragora/gateway/router.py` | OpenClaw WS adapter partial (connect/presence); routing commands pending; canonical runtime default and registry mirrored |
| Unified inbox | partial | `aragora/gateway/inbox.py`, `aragora/extensions/moltbot/inbox.py`, `aragora/storage/unified_inbox_store.py` | Multiple inbox layers |
| Device registry + pairing | partial | `aragora/gateway/device_registry.py`, `aragora/server/handlers/devices.py`, `aragora/onboarding/wizard.py` | No device runtime clients |
| Capability routing | partial | `aragora/gateway/capability_router.py`, `aragora/extensions/moltbot/capabilities.py` | Needs device node telemetry |
| Voice wake + voice sessions | partial | `aragora/extensions/moltbot/voice_wake.py`, `aragora/extensions/moltbot/voice.py`, `aragora/server/stream/voice_stream.py` | Wake engines mocked |
| Canvas / A2UI | partial | `aragora/extensions/moltbot/canvas.py`, `aragora/canvas/manager.py`, `aragora/server/stream/canvas_stream.py` | Protocol parity missing |
| Browser control | partial | `aragora/mcp/tools_module/browser.py`, `aragora/workflow/nodes/browser.py` | Needs device-level policy gates |
| Channel coverage | partial | `aragora/connectors/`, `aragora/integrations/` | Consumer channels incomplete |

## Priority Backlog (Best Order)

### P0: Unify duplicated primitives (foundation)
1. **Unify bead storage and status mapping** (in progress)
   - Acceptance: single storage backend for beads (Nomic BeadStore), workspace APIs preserved, consistent status mapping
   - Current: workspace and gastown adapters exist; remaining call sites still split across legacy stores
2. **Unify convoy storage and IDs** (in progress)
   - Acceptance: convoys share the same store backend, workspace status preserved via metadata, IDs stable across adapters
   - Current: adapters exist; convoy routing still split across workspace/gastown/nomic layers
3. **Canonical ownership of Gastown primitives** (in progress)
   - Acceptance: clear "source of truth" module for beads/convoys/workspaces and compatibility shims for legacy APIs
   - Current: `aragora.nomic.stores` provides the canonical surface; continue migrating callers

### P1: Protocol compatibility & device runtime
4. **Gateway WS protocol adapter (OpenClaw-compatible)**
   - Acceptance: sessions/presence/config endpoints mapped to gateway server; test fixture for compatibility
5. **Device node runtime reference client**
   - Acceptance: local device node can pair, heartbeat, and report capabilities; end-to-end test with DeviceRegistry
6. **Voice wake engine integration**
   - Acceptance: real wake engine binding (Porcupine/Vosk), device mic integration, integration test
7. **Canvas A2UI contract**
   - Acceptance: push/reset/snapshot messages handled; compatibility test suite

### P2: Expansion & hardening
8. **Consumer channel expansion (Signal/iMessage/Matrix/Zalo/Google Chat)**
   - Acceptance: connector + inbox routing + RBAC gate for each channel
9. **Policy + approval unification**
   - Acceptance: device + computer-use actions use the same approval and audit flow
10. **Agent Fabric MVP**
   - Acceptance: scheduler + isolation + budgets + telemetry for 50–100 concurrent agents

## Milestone Checklist (Owners + Test Hooks)

Owners are suggested teams/areas to align work; adjust as needed.

### M0 (P0 foundation)

| Item | Suggested owner | Acceptance summary | Test hooks |
| --- | --- | --- | --- |
| Unify bead storage and status mapping | Workspace | Nomic BeadStore is authoritative; workspace APIs preserved; status mapping stable | `tests/workspace/test_workspace_nomic.py`, `tests/workspace/test_workspace.py` |
| Unify convoy storage and IDs | Workspace | Convoys share Nomic backend; workspace/gastown metadata preserved | `tests/workspace/test_workspace_nomic.py`, `tests/extensions/test_gastown.py` |
| Canonical ownership of Gastown primitives | Extensions | Single source of truth module + compatibility adapters | `tests/extensions/test_gastown.py` |

### M1 (Protocol + device parity)

| Item | Suggested owner | Acceptance summary | Test hooks |
| --- | --- | --- | --- |
| Gateway WS protocol adapter | Gateway | Sessions + presence + config endpoints mapped to gateway | `tests/gateway/test_protocol_adapter.py` |
| Device node runtime reference | Gateway | Pairing + heartbeat + capability reports working | `tests/gateway/test_device_node_runtime.py`, `tests/gateway/test_gateway.py` |
| Voice wake engine integration | Extensions | Wake engine wired to device mic + session handoff | `tests/extensions/moltbot/test_voice_wake.py` |
| Canvas A2UI contract | Extensions | push/reset/snapshot handled end-to-end | `tests/extensions/moltbot/test_canvas.py` |

### M2 (Expansion + hardening)

| Item | Suggested owner | Acceptance summary | Test hooks |
| --- | --- | --- | --- |
| Consumer channel expansion | Integrations | Each channel wired with routing + RBAC | `tests/extensions/moltbot/test_capabilities.py` |
| Policy + approval unification | Security | Device + computer-use share approvals + audit | `tests/extensions/moltbot/test_capabilities.py` |
| Agent Fabric MVP | Platform | Scheduler + isolation + budgets + telemetry at scale | `tests/extensions/test_gastown.py` |

## Implementation Notes
- Avoid SDK regeneration until endpoint stability improves.
- Prefer adapters over invasive rewrites; keep enterprise core stable.
- Add acceptance tests alongside each parity item to lock behavior.
