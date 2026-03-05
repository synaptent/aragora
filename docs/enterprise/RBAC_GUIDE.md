# Aragora RBAC Guide

Aragora implements a comprehensive Role-Based Access Control (RBAC) system with support for fine-grained permissions, resource-level access control, permission delegation, and ABAC conditions.

## Overview

| Component | Description |
|-----------|-------------|
| **Permissions** | 360+ granular permissions across 20+ resource types |
| **Roles** | 8 system roles with hierarchical inheritance |
| **Resource Permissions** | Per-resource access grants beyond role-based access |
| **Delegation** | Temporary permission delegation with expiration |
| **ABAC Conditions** | Attribute-based conditions (time, IP, resource attributes) |
| **Audit** | Comprehensive authorization audit trail |

## System Roles

Aragora provides 8 built-in roles with hierarchical permission inheritance:

| Role | Description | Key Permissions |
|------|-------------|-----------------|
| **Owner** | Full organization control | All permissions |
| **Admin** | Administrative access | User management, organization settings, billing |
| **Compliance Officer** | Regulatory and audit access | Compliance policies, audit logs, PII handling |
| **Debate Creator** | Create and manage debates | Debate CRUD, agent access, workflow creation |
| **Team Lead** | Team management | Team CRUD, member management, resource sharing |
| **Analyst** | Data and analytics access | Analytics, memory, evidence read access |
| **Viewer** | Read-only access | View debates, results, analytics |
| **Member** | Basic workspace access | Read workspace resources, participate in debates |

### Role Hierarchy

Roles inherit permissions from lower-tier roles:

```
Owner
  └── Admin
       ├── Compliance Officer
       └── Debate Creator
            └── Team Lead
                 └── Analyst
                      └── Viewer
                           └── Member
```

## Permission Categories

### Debate Permissions
- `debate.create` - Create new debates
- `debate.read` - View debate details and history
- `debate.update` - Modify debate settings
- `debate.delete` - Delete debates permanently
- `debate.run` - Start and execute debates
- `debate.stop` - Stop running debates
- `debate.fork` - Create branches from existing debates

### Agent Permissions
- `agent.create` - Create custom agent configurations
- `agent.read` - View agent details and statistics
- `agent.update` - Modify agent configurations
- `agent.delete` - Remove agent configurations
- `agent.deploy` - Deploy agents to production

### Gauntlet Permissions
- `gauntlet.run` - Execute adversarial stress-tests
- `gauntlet.read` - View gauntlet results and receipts
- `gauntlet.sign` - Cryptographically sign decision receipts
- `gauntlet.compare` - Compare gauntlet run results
- `gauntlet.export_data` - Export gauntlet reports

### Organization Permissions
- `organization.read` - View organization settings
- `organization.update` - Modify organization settings
- `organization.manage_billing` - Manage billing and subscriptions
- `organization.view_audit` - Access organization audit trail
- `organization.export_data` - Export organization data

### User Management Permissions
- `user.read` - View user profiles
- `user.invite` - Invite new users
- `user.remove` - Remove users
- `user.change_role` - Modify user role assignments
- `user.impersonate` - Act on behalf of other users

### Compliance Permissions
- `compliance.read` - View compliance status
- `compliance.update` - Update violation status
- `compliance.check` - Run compliance validation
- `compliance_policy.read` - View compliance rules (SOC2, GDPR, HIPAA)
- `compliance_policy.enforce` - Force resolution of findings

### Workspace Permissions
- `workspace.create` - Create new workspaces
- `workspace.read` - View workspace details
- `workspace.update` - Modify workspace settings
- `workspace.delete` - Remove workspaces
- `workspace_member.add_member` - Invite users to workspaces
- `workspace_member.remove_member` - Remove users from workspaces

## Permission Key Formats

Aragora supports two permission key formats for compatibility:

| Format | Example | Usage |
|--------|---------|-------|
| Dot notation | `debate.create` | Preferred, matches system conventions |
| Colon notation | `debate:create` | Legacy, still supported |

Both formats are interchangeable. The system automatically converts between them:

```python
# These are equivalent:
ctx.has_permission("debate.create")  # dot format
ctx.has_permission("debate:create")  # colon format

# Wildcards work with both formats:
ctx.has_permission("debate.*")   # grants all debate permissions
ctx.has_permission("debate:*")   # equivalent wildcard
```

When defining new permissions, prefer dot notation for consistency with the codebase.

## Using RBAC in Code

### Permission Decorators

The simplest way to protect endpoints:

```python
from aragora.rbac.decorators import require_permission, require_role

@require_permission("debate.create")
async def create_debate(request):
    """Only users with debate.create permission can access."""
    ...

@require_role("admin")
async def admin_action(request):
    """Only admins and above can access."""
    ...

@require_permission("gauntlet.sign")
async def sign_receipt(request):
    """Only users who can sign receipts."""
    ...
```

### Multiple Permission Requirements

```python
from aragora.rbac.decorators import require_any_permission, require_all_permissions

@require_any_permission(["debate.read", "analytics.read"])
async def view_results(request):
    """Users with either permission can access."""
    ...

@require_all_permissions(["compliance.read", "audit_log.read"])
async def compliance_audit(request):
    """Both permissions required."""
    ...
```

### Resource-Level Permissions

For per-resource access beyond role-based permissions:

```python
from aragora.rbac.resource_permissions import (
    grant_resource_permission,
    revoke_resource_permission,
    check_resource_permission,
)

# Grant access to specific debate
grant_resource_permission(
    user_id="user-123",
    resource_type="debate",
    resource_id="debate-456",
    permission="debate.update",
    granted_by="admin-user",
    expires_at=datetime.utcnow() + timedelta(days=7),  # Optional
)

# Check access
has_access = check_resource_permission(
    user_id="user-123",
    resource_type="debate",
    resource_id="debate-456",
    permission="debate.update",
)

# Revoke access
revoke_resource_permission(
    user_id="user-123",
    resource_type="debate",
    resource_id="debate-456",
    permission="debate.update",
)
```

### Permission Delegation

Allow users to temporarily delegate their permissions:

```python
from aragora.rbac.delegation import (
    DelegationManager,
    PermissionDelegation,
)

manager = DelegationManager()

# Create delegation
delegation = manager.create_delegation(
    delegator_id="manager-user",
    delegate_id="team-member",
    permissions=["debate.create", "debate.run"],
    expires_at=datetime.utcnow() + timedelta(hours=4),
    reason="Covering during vacation",
)

# Check if delegation is active
is_valid = manager.is_delegation_valid(delegation.id)

# Revoke delegation
manager.revoke_delegation(delegation.id, revoked_by="manager-user")
```

### ABAC Conditions

Add attribute-based conditions to permissions:

```python
from aragora.rbac.conditions import (
    TimeCondition,
    IPCondition,
    ResourceAttributeCondition,
)

# Time-based access (business hours only)
time_condition = TimeCondition(
    start_hour=9,
    end_hour=17,
    days_of_week=[0, 1, 2, 3, 4],  # Mon-Fri
    timezone="America/New_York",
)

# IP-based access (office network only)
ip_condition = IPCondition(
    allowed_ranges=["10.0.0.0/8", "192.168.1.0/24"],
)

# Resource attribute condition
resource_condition = ResourceAttributeCondition(
    attribute="status",
    operator="equals",
    value="published",
)
```

### Permission Checker

Programmatic permission checking:

```python
from aragora.rbac.checker import PermissionChecker

checker = PermissionChecker()

# Check permission for user
allowed = await checker.has_permission(
    user_id="user-123",
    permission="debate.create",
    organization_id="org-456",  # Optional scope
)

# Check with authorization context
from aragora.rbac.models import AuthorizationContext

context = AuthorizationContext(
    user_id="user-123",
    organization_id="org-456",
    roles=["debate_creator"],
    ip_address="10.0.0.50",
)

decision = await checker.authorize(context, "debate.create")
if decision.allowed:
    print(f"Access granted via: {decision.grant_reason}")
else:
    print(f"Access denied: {decision.deny_reason}")
```

## Middleware Protection

Protect HTTP routes automatically:

```python
from aragora.rbac.middleware import RBACMiddleware

# In your server setup
app.middleware.append(
    RBACMiddleware(
        protected_routes={
            "/api/debates": ["debate.read"],
            "/api/debates/create": ["debate.create"],
            "/api/admin/*": ["admin.all"],
        }
    )
)
```

## Audit Trail

All authorization decisions are logged:

```python
from aragora.rbac.audit import AuthorizationAuditor

auditor = AuthorizationAuditor()

# Events are automatically logged, but you can also query them
events = await auditor.get_events(
    user_id="user-123",
    action="debate.create",
    start_time=datetime.utcnow() - timedelta(days=7),
)

for event in events:
    print(f"{event.timestamp}: {event.action} - {'allowed' if event.allowed else 'denied'}")
```

## Best Practices

### 1. Use Decorators for Route Protection
```python
# Good: Declarative and clear
@require_permission("debate.create")
async def create_debate(request):
    ...

# Avoid: Manual checking in every route
async def create_debate(request):
    if not await check_permission(request.user, "debate.create"):
        raise PermissionDenied()
    ...
```

### 2. Prefer Role Assignment Over Direct Permissions
```python
# Good: Assign role
assign_role(user_id, "debate_creator")

# Avoid: Granting individual permissions
grant_permission(user_id, "debate.create")
grant_permission(user_id, "debate.read")
grant_permission(user_id, "debate.update")
# ... many more
```

### 3. Use Resource Permissions for Collaboration
```python
# Good: Grant access to specific resource
grant_resource_permission(
    user_id="collaborator",
    resource_type="debate",
    resource_id="shared-debate",
    permission="debate.update",
)

# Avoid: Elevating user's global role
```

### 4. Set Expiration on Delegations
```python
# Good: Temporary delegation with expiration
manager.create_delegation(
    delegator_id="manager",
    delegate_id="backup",
    permissions=["debate.run"],
    expires_at=datetime.utcnow() + timedelta(hours=8),
)

# Avoid: Permanent delegations
```

### 5. Use ABAC for Sensitive Operations
```python
# Good: Add conditions for sensitive permissions
grant_resource_permission(
    user_id="user",
    resource_type="compliance",
    resource_id="pii-data",
    permission="pii.read",
    conditions=[
        TimeCondition(start_hour=9, end_hour=17),
        IPCondition(allowed_ranges=["10.0.0.0/8"]),
    ],
)
```

## Testing

Run the RBAC test suite:

```bash
# All RBAC tests
pytest tests/rbac/ -v

# Specific component
pytest tests/rbac/test_checker.py -v
pytest tests/rbac/test_delegation.py -v
pytest tests/rbac/test_resource_permissions.py -v
```

## Related Documentation

- [Environment Variables](../reference/ENVIRONMENT.md) - RBAC-related configuration
- [API Reference](../api/API_REFERENCE.md) - RBAC API endpoints
- [Enterprise Features](ENTERPRISE_FEATURES.md) - Advanced RBAC capabilities
