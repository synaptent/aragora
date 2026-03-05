# RBAC - Role-Based Access Control

Enterprise-grade access control with role hierarchy, ABAC conditions, delegation, and audit logging.

## Quick Start

```python
from aragora.rbac import AuthorizationContext, check_permission

# Create context
context = AuthorizationContext(
    user_id="user-123",
    org_id="org-456",
    roles={"member"}
)

# Check permission
decision = check_permission(context, "debates.create")
if decision.allowed:
    # Proceed with action
    pass
```

## Key Components

| Component | File | Purpose |
|-----------|------|---------|
| `PermissionChecker` | `checker.py` | Core authorization engine |
| `@require_permission` | `decorators.py` | Route decorator |
| `RBACMiddleware` | `middleware.py` | HTTP middleware |
| `AuditEvent` | `audit.py` | Authorization logging |
| `DelegationManager` | `delegation.py` | Permission delegation |

## Architecture

```
rbac/
├── models.py            # Core types (Permission, Role, etc.)
├── checker.py           # PermissionChecker engine
├── decorators.py        # @require_permission, @require_role
├── middleware.py        # HTTP route protection
├── cache.py             # Distributed Redis cache
├── audit.py             # HMAC-signed audit logs
├── delegation.py        # Permission delegation
├── conditions.py        # ABAC condition evaluation
├── hierarchy.py         # Resource hierarchy
├── profiles.py          # Lite/Standard/Enterprise
├── approvals.py         # Access request workflows
├── emergency.py         # Break-glass access
├── quotas.py            # Rate limits
└── defaults/
    ├── permissions.py   # 360+ permission definitions
    └── roles.py         # System role configurations
```

## Decorators

```python
from aragora.rbac import require_permission, require_role

@require_permission("debates.create")
async def create_debate(context, ...):
    pass

@require_role("admin")
async def admin_only(context, ...):
    pass
```

## Permission Format

```python
# Standard format
"resource.action"  # e.g., "debates.create"

# Also supports
"resource:action"  # Converted internally

# Wildcards
"debates.*"        # All debate actions
"*"                # All permissions
```

## System Roles (Hierarchical)

```
owner → admin → debate_creator → team_lead → compliance_officer → member → analyst → viewer
```

## Profiles

| Profile | Roles | Use Case |
|---------|-------|----------|
| Lite | 3 (owner, admin, member) | Simple workspaces |
| Standard | 5 | Growing teams |
| Enterprise | 8 | Full governance |

## Advanced Features

### Permission Delegation

```python
from aragora.rbac import delegate_permission

delegation = delegate_permission(
    delegator_id="manager-123",
    delegatee_id="assistant-456",
    permission_id="debates.create",
    org_id="org-789",
    expires_at=datetime.now() + timedelta(days=7)
)
```

### ABAC Conditions

```python
decision = checker.check_resource_access(
    context=context,
    resource_type=ResourceType.DEBATE,
    action=Action.UPDATE,
    resource_id="debate-789",
    resource_attrs={"owner_id": "user-123"}  # ABAC
)
```

### Audit Logging

```python
from aragora.rbac.audit import AuthorizationAuditor

auditor = AuthorizationAuditor(signing_key="secret")
auditor.log_decision(context, permission, decision)
# HMAC-SHA256 signed for integrity
```

## Middleware

```python
from aragora.rbac import get_middleware

middleware = get_middleware()
# 90+ pre-configured route permissions
```

## Resource Types (50+)

- Debates, Agents, Users, Organizations
- Knowledge, Workflows, Analytics
- Training, Documents, Connectors
- Policies, Compliance, Audit logs
- Tenancy, Billing, Backups

## Caching

```python
# Local in-memory + distributed Redis
# O(1) invalidation via versioning
from aragora.rbac import RBACDistributedCache

cache = RBACDistributedCache(redis_url)
```

## Enterprise Compliance

- SOC2 Type II audit trails
- HMAC-SHA256 event signing
- Multi-tenant isolation
- Break-glass emergency access
- Approval workflows

## Related

- [CLAUDE.md](../../CLAUDE.md) - Project overview
- [Auth](../auth/README.md) - Authentication
- [Tenancy](../tenancy/README.md) - Multi-tenancy
