# Next Steps - Q1 2026

> Legacy planning snapshot. Canonical priorities live in `docs/status/NEXT_STEPS_CANONICAL.md`.

Strategic roadmap to reach 100% enterprise readiness.

**Current Status:** 85% production ready | 6-8 weeks to enterprise GA

## Priority 1: Immediate (Week 1-2)

### 1.1 Audit Test Skip Markers
**Effort:** 2-3 days | **Impact:** Improves CI reliability

~194 tests are skipped/xfailed (reduced from 422). Status:
- Target achieved: <200 intentional skips
- Categories: waiting for external dependencies, permanent architectural skips
- CI check implemented to warn on skip count increase
- Next: Continue monitoring and documenting skip reasons

```bash
# Find all skip markers
grep -r "@pytest.mark.skip" tests/ | wc -l
grep -r "@pytest.mark.xfail" tests/ | wc -l
```

### 1.2 Start Penetration Testing (External)
**Effort:** 4-6 weeks | **Impact:** Enterprise blocker

- Engage external security firm immediately
- Scope: API endpoints, authentication, data handling
- Deliverable: SOC 2 compliance evidence

### 1.3 Commit Pending Work
**Effort:** 1 day | **Impact:** Clean baseline

14 modified files pending commit:
- OAuth wizard improvements
- Healthcare connector fixes (Epic, Cerner)
- E2E smoke tests

## Priority 2: Core Gaps (Week 2-4)

### 2.1 OpenAPI 3.1 Specification
**Effort:** 1-2 weeks | **Impact:** Enables SDK generation

Create auto-generation pipeline:
1. Extract routes from Flask/FastAPI handlers
2. Generate OpenAPI 3.1 spec
3. Validate in CI/CD
4. Publish to docs site

**Files to create:**
- `scripts/generate_openapi.py`
- `.github/workflows/openapi-validate.yml`

### 2.2 TypeScript SDK Parity
**Effort:** 3-4 weeks | **Impact:** JS/TS developer adoption

Current gaps:
- WebSocket streaming incomplete
- 25-30% of types missing
- Error handling differs from Python SDK

**Action plan:**
1. Audit Python SDK methods vs TypeScript
2. Generate types from OpenAPI spec
3. Implement missing WebSocket client
4. Add comprehensive tests

**Target:** 95%+ parity with Python SDK

### 2.3 RBAC v2 Enhancement
**Effort:** 2-3 weeks | **Impact:** Enterprise security requirement

Current state: 360+ permissions, 69% test coverage

**Gaps to address:**
- 15-20% of endpoints lack permission checks
- No hierarchical role inheritance
- Resource-level policies incomplete

**Implementation:**
```python
# Add to all sensitive handlers
@require_permission("resource.action", resource_id_param="id")
async def handler(context: AuthorizationContext, ...):
    ...
```

## Priority 3: SME Features (Week 4-6)

### 3.1 Complete Slack/Teams Integration
**Effort:** 2 weeks | **Impact:** SME adoption

- Finish OAuth setup wizards
- Add slash command handlers
- Implement thread-based debate UI
- Write integration tests

### 3.2 Finalize Decision Receipts v1
**Effort:** 1 week | **Impact:** Audit compliance

- Complete PDF export functionality
- Implement 7-year retention enforcement
- Add receipt search/query API

### 3.3 Self-Hosted Deployment
**Effort:** 2 weeks | **Impact:** On-prem customers

Deliverables:
- Single `docker-compose up` experience
- Complete `.env.example` with all variables
- Backup/restore CLI tools
- TLS configuration guide
- Guided setup CLI (`aragora setup`)

## Priority 4: Enterprise Polish (Week 6-8)

### 4.1 Admin Dashboard
**Effort:** 2-3 weeks | **Impact:** Workspace management

Missing features:
- Workspace member management UI
- Role assignment interface
- Usage/cost dashboard
- Audit log viewer

### 4.2 Documentation Completion
**Effort:** 1-2 weeks | **Impact:** Customer success

- Enterprise deployment guide
- SLA documentation (exists, needs update)
- Support escalation procedures
- Runbooks for common issues

### 4.3 Performance Optimization
**Effort:** 1 week | **Impact:** Scale readiness

- Database query optimization
- Connection pool tuning
- Cache hit rate improvement
- Load test with 100+ concurrent debates

## Technical Debt Reduction

### High Priority
| Item | Location | Effort |
|------|----------|--------|
| 102 mypy errors | Various | 3-4 days |
| 13 NotImplementedError in chat base | `connectors/chat/base.py` | 1 week |
| Glacial memory tier stub | `memory/continuum_glacial.py` | 1-2 weeks |

### Medium Priority
| Item | Location | Effort |
|------|----------|--------|
| 100+ TODO/FIXME markers | 49 files | 2 weeks |
| Deprecated API cleanup | Various handlers | 1 week |
| Test organization | `tests/` root (20K+ tests) | 1 week |

## Success Metrics

### Week 2 Checkpoint
- [ ] Test skip audit complete
- [ ] Pen test vendor engaged
- [ ] OpenAPI generation started

### Week 4 Checkpoint
- [ ] OpenAPI spec published
- [ ] TypeScript SDK at 85% parity
- [ ] RBAC v2 core complete

### Week 6 Checkpoint
- [ ] Slack/Teams integrations complete
- [ ] Self-hosted deployment ready
- [ ] Decision receipts v1 complete

### Week 8 Checkpoint (GA Ready)
- [ ] 95%+ TypeScript SDK parity
- [ ] RBAC v2 fully tested
- [ ] Pen test findings addressed
- [ ] Admin dashboard MVP
- [ ] Documentation complete

## Resource Allocation

| Track | Engineers | Duration |
|-------|-----------|----------|
| SDK & OpenAPI | 2 | 4 weeks |
| RBAC & Security | 1-2 | 3 weeks |
| Integrations | 1 | 3 weeks |
| Self-Hosted & Ops | 1 | 2 weeks |
| Documentation | 0.5 | Ongoing |

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Pen test delays | Start immediately, have backup vendor |
| SDK complexity | Auto-generate from OpenAPI where possible |
| RBAC scope creep | Define MVP permissions, iterate |
| Integration testing | Create mock providers for offline CI |

## Dependencies

```
OpenAPI Spec ──────┬──► TypeScript SDK
                   │
                   └──► SDK Code Generation

RBAC v2 ───────────┬──► Admin Dashboard
                   │
                   └──► Audit Logging

Self-Hosted ───────┬──► Customer Onboarding
                   │
                   └──► Support Documentation
```

## Quick Wins (Can Start Today)

1. **Commit pending 14 files** - Clean baseline
2. **Run skip audit script** - Identify test debt
3. **Contact pen test vendors** - Start 4-6 week clock
4. **Create OpenAPI generation issue** - Track progress
5. **Review RBAC handler coverage** - Identify gaps

---

*Created: January 2026*
*Target: Enterprise GA Q1 2026*
