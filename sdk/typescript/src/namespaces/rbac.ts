/**
 * RBAC Namespace API
 *
 * Provides a namespaced interface for role-based access control operations.
 * This wraps the flat client methods for a more intuitive API.
 */

import type {
  Role,
  Permission,
  AssignmentList,
  BulkAssignRequest,
  BulkAssignResponse,
  PaginationParams,
} from '../types';

/**
 * Request for creating a new role.
 */
export interface CreateRoleRequest {
  /** Role name */
  name: string;
  /** Role description */
  description?: string;
  /** Permission IDs to include */
  permissions: string[];
  /** Parent role ID for inheritance */
  parent_role_id?: string;
}

/**
 * Request for updating a role.
 */
export interface UpdateRoleRequest {
  /** Updated name */
  name?: string;
  /** Updated description */
  description?: string;
  /** Updated permissions */
  permissions?: string[];
}

/**
 * Interface for the internal client methods used by RBACAPI.
 */
interface RBACClientInterface {
  // Generic request method for extended endpoints
  request<T = unknown>(method: string, path: string, options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }): Promise<T>;

  // Core RBAC methods
  listRoles(params?: PaginationParams): Promise<{ roles: Role[] }>;
  getRole(roleId: string): Promise<Role>;
  createRole(request: CreateRoleRequest): Promise<Role>;
  updateRole(roleId: string, updates: UpdateRoleRequest): Promise<Role>;
  deleteRole(roleId: string): Promise<{ deleted: boolean }>;
  listPermissions(params?: PaginationParams): Promise<{ permissions: Permission[] }>;
  assignRole(userId: string, roleId: string): Promise<{ assigned: boolean }>;
  revokeRole(userId: string, roleId: string): Promise<void>;
  getUserRoles(userId: string): Promise<{ roles: Role[] }>;
  checkPermission(userId: string, permission: string): Promise<{ allowed: boolean }>;
  listRoleAssignments(roleId: string, params?: PaginationParams): Promise<AssignmentList>;
  bulkAssignRoles(body: BulkAssignRequest): Promise<BulkAssignResponse>;
}

/**
 * RBAC API namespace.
 *
 * Provides methods for role-based access control:
 * - Managing roles and permissions
 * - Assigning and revoking roles
 * - Checking user permissions
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // List all roles
 * const { roles } = await client.rbac.listRoles();
 *
 * // Create a new role
 * const role = await client.rbac.createRole({
 *   name: 'Analyst',
 *   permissions: ['debates:read', 'analytics:read'],
 * });
 *
 * // Assign role to user
 * await client.rbac.assignRole(userId, role.id);
 *
 * // Check permission
 * const { allowed } = await client.rbac.checkPermission(userId, 'debates:create');
 * ```
 */
export class RBACAPI {
  constructor(private client: RBACClientInterface) {}

  /**
   * List available roles.
   *
   * @param params - Optional pagination and filter parameters
   * @param params.include_system - Include system roles (admin, viewer, etc.) (default: true)
   * @param params.limit - Maximum results (default: 50)
   * @param params.offset - Pagination offset (default: 0)
   * @returns List of roles with permissions
   */
  async listRoles(params?: PaginationParams & { include_system?: boolean }): Promise<{ roles: Role[] }> {
    return this.client.listRoles(params);
  }

  /**
   * Get a role by ID.
   *
   * @param roleId - Role ID
   * @returns Role details with permissions
   */
  async getRole(roleId: string): Promise<Role> {
    return this.client.getRole(roleId);
  }

  /**
   * Create a custom role.
   *
   * @param request - Role creation request
   * @param request.name - Role name
   * @param request.permissions - List of permission keys
   * @param request.description - Role description
   * @param request.parent_role_id - Parent role to inherit from
   * @returns Created role
   */
  async createRole(request: CreateRoleRequest): Promise<Role> {
    return this.client.createRole(request);
  }

  /**
   * Update a role.
   *
   * @param roleId - Role ID
   * @param updates - Updates to apply
   * @param updates.permissions - New permissions list
   * @param updates.description - New description
   * @returns Updated role
   */
  async updateRole(roleId: string, updates: UpdateRoleRequest): Promise<Role> {
    return this.client.updateRole(roleId, updates);
  }

  /**
   * Delete a custom role.
   *
   * System roles cannot be deleted.
   *
   * @param roleId - Role ID
   * @returns Deletion result
   */
  async deleteRole(roleId: string): Promise<{ deleted: boolean }> {
    return this.client.deleteRole(roleId);
  }

  /**
   * List all permissions with optional pagination.
   *
   * @param params - Optional pagination and filter parameters
   * @param params.resource_type - Filter by resource type (e.g., "debates", "workspaces")
   * @param params.limit - Maximum results (default: 100)
   * @param params.offset - Pagination offset (default: 0)
   * @returns List of permissions with descriptions
   */
  async listPermissions(params?: PaginationParams & { resource_type?: string }): Promise<{ permissions: Permission[] }> {
    return this.client.listPermissions(params);
  }

  /**
   * Get a permission by key.
   *
   * @param permissionKey - Permission key (e.g., "debates:create")
   * @returns Permission details
   */
  async getPermission(permissionKey: string): Promise<Permission> {
    return this.client.request('GET', `/api/v1/rbac/permissions/${permissionKey}`);
  }

  /**
   * Assign a role to a user.
   *
   * @param userId - User ID
   * @param roleId - Role ID to assign
   * @param scope - Optional scope (org, workspace, etc.)
   * @returns Role assignment result
   */
  async assignRole(userId: string, roleId: string, scope?: string): Promise<{ assigned: boolean }> {
    if (scope) {
      return this.client.request('GET', '/api/v1/rbac/assignments', {
        json: { user_id: userId, role_id: roleId, scope }
      });
    }
    await this.client.assignRole(userId, roleId);
    return { assigned: true };
  }

  /**
   * Revoke a role from a user.
   *
   * @param userId - User ID
   * @param roleId - Role ID to revoke
   * @returns Revocation result
   */
  async revokeRole(userId: string, roleId: string): Promise<void> {
    return this.client.revokeRole(userId, roleId);
  }

  /**
   * Get roles assigned to a user.
   *
   * @param userId - User ID
   * @returns User's role assignments
   */
  async getUserRoles(userId: string): Promise<{ roles: Role[] }> {
    return this.client.getUserRoles(userId);
  }

  /**
   * Check if a user has a specific permission.
   *
   * @param userId - User ID
   * @param permission - Permission key to check
   * @param resourceId - Optional specific resource ID
   * @returns Permission check result with allowed status
   */
  async checkPermission(userId: string, permission: string, resourceId?: string): Promise<{ allowed: boolean }> {
    if (resourceId) {
      return this.client.request('GET', '/api/v1/rbac/check', {
        json: { user_id: userId, permission, resource_id: resourceId }
      });
    }
    return this.client.checkPermission(userId, permission);
  }

  /**
   * List all assignments for a role.
   *
   * @param roleId - Role ID
   * @param params - Optional pagination parameters
   * @returns List of role assignments
   */
  async listAssignments(
    roleId: string,
    params?: PaginationParams
  ): Promise<AssignmentList> {
    return this.client.listRoleAssignments(roleId, params);
  }

  /**
   * Bulk assign roles to multiple users.
   *
   * @param body - Bulk assignment request
   * @param body.assignments - List of {user_id: string, role_id: string, scope?: string}
   * @returns Bulk assignment results
   */
  async bulkAssign(body: BulkAssignRequest): Promise<BulkAssignResponse> {
    return this.client.bulkAssignRoles(body);
  }

  // =========================================================================
  // User Management
  // =========================================================================

  /**
   * List users in organization.
   *
   * @param params - Optional pagination parameters
   * @param params.limit - Maximum results (default: 100)
   * @param params.offset - Pagination offset (default: 0)
   * @returns List of users
   */
  async listUsers(params?: PaginationParams): Promise<{ users: unknown[]; total: number }> {
    return this.client.request('GET', '/api/users', { params });
  }

  // =========================================================================
  // Workspace Roles
  // =========================================================================

  /**
   * Get available roles for a workspace based on RBAC profile.
   *
   * @param workspaceId - Workspace ID
   * @returns Available roles and the workspace's RBAC profile
   */
  async getWorkspaceRoles(workspaceId: string): Promise<{ roles: unknown[]; profile: string }> {
    return this.client.request('GET', `/api/v1/workspaces/${workspaceId}/roles`);
  }

  /**
   * Update member's role in workspace.
   *
   * @param workspaceId - Workspace ID
   * @param userId - User ID
   * @param role - New role to assign
   * @returns Update result
   */
  async updateMemberRole(workspaceId: string, userId: string, role: string): Promise<{ updated: boolean }> {
    return this.client.request('PUT', `/api/v1/workspaces/${workspaceId}/members/${userId}/role`, { json: { role } });
  }

  /**
   * Add member to workspace.
   *
   * @param workspaceId - Workspace ID
   * @param userId - User ID to add
   * @param role - Optional role to assign
   * @returns Addition result
   */
  async addWorkspaceMember(workspaceId: string, userId: string, role?: string): Promise<{ added: boolean }> {
    return this.client.request('POST', `/api/v1/workspaces/${workspaceId}/members`, { json: { user_id: userId, role } });
  }

  /**
   * Remove member from workspace.
   *
   * @param workspaceId - Workspace ID
   * @param userId - User ID to remove
   * @returns Removal result
   */
  async removeWorkspaceMember(workspaceId: string, userId: string): Promise<{ removed: boolean }> {
    return this.client.request('DELETE', `/api/v1/workspaces/${workspaceId}/members/${userId}`);
  }

  /**
   * List available RBAC profiles (lite, standard, enterprise).
   *
   * @returns Available RBAC profiles
   */
  async listProfiles(): Promise<{ profiles: unknown[] }> {
    return this.client.request('GET', '/api/v1/workspaces/profiles');
  }

  // =========================================================================
  // Audit
  // =========================================================================

  /**
   * Query audit log entries.
   *
   * @param options - Query options
   * @param options.action - Filter by action type
   * @param options.user_id - Filter by user ID
   * @param options.since - Filter entries since this timestamp
   * @param options.limit - Maximum results (default: 50)
   * @param options.offset - Pagination offset (default: 0)
   * @returns Audit entries
   */
  async queryAudit(options?: { action?: string; user_id?: string; since?: string; limit?: number; offset?: number }): Promise<{ entries: unknown[]; total: number }> {
    return this.client.request('GET', '/api/v1/audit/entries', { params: options });
  }

  /**
   * Generate compliance audit report.
   *
   * @param options - Report options
   * @param options.framework - Compliance framework (e.g., "SOC2", "GDPR")
   * @param options.since - Start date for the report period
   * @returns Compliance audit report
   */
  async getAuditReport(options?: { framework?: string; since?: string }): Promise<unknown> {
    return this.client.request('GET', '/api/v1/audit/report', { params: options });
  }

  /**
   * Verify audit log integrity.
   *
   * Checks the hash chain integrity of audit logs to detect tampering.
   *
   * @returns Verification result with any detected issues
   */
  async verifyAuditIntegrity(): Promise<{ valid: boolean; issues: unknown[] }> {
    return this.client.request('GET', '/api/v1/audit/verify');
  }

  /**
   * Get user activity history.
   *
   * @param userId - User ID
   * @param options - Pagination options
   * @param options.limit - Maximum results (default: 50)
   * @param options.offset - Pagination offset (default: 0)
   * @returns User's activity history
   */
  async getUserActivityHistory(userId: string, options?: PaginationParams): Promise<{ activities: unknown[]; total: number }> {
    return this.client.request('GET', `/api/v1/audit/actor/${userId}/history`, { params: options });
  }

  /**
   * Get resource access history.
   *
   * @param resourceType - Resource type (e.g., "debate", "workspace")
   * @param resourceId - Resource ID
   * @param options - Pagination options
   * @param options.limit - Maximum results (default: 50)
   * @param options.offset - Pagination offset (default: 0)
   * @returns Resource access history
   */
  async getResourceHistory(resourceType: string, resourceId: string, options?: PaginationParams): Promise<{ accesses: unknown[]; total: number }> {
    return this.client.request('GET', `/api/v1/audit/resource/${resourceType}/${resourceId}/history`, { params: options });
  }

  /**
   * Get denied access attempts.
   *
   * @param options - Pagination options
   * @param options.limit - Maximum results (default: 50)
   * @param options.offset - Pagination offset (default: 0)
   * @returns Denied access attempts
   */
  async getDeniedAccess(options?: PaginationParams): Promise<{ denied: unknown[]; total: number }> {
    return this.client.request('GET', '/api/v1/audit/denied', { params: options });
  }

  // =========================================================================
  // API Keys
  // =========================================================================

  /**
   * Generate a new API key.
   *
   * @param name - Descriptive name for the key
   * @param permissions - Optional list of permission keys to grant
   * @param expires_at - Optional expiration timestamp (ISO 8601)
   * @returns The new API key (only shown once) and its ID
   */
  async generateApiKey(name: string, permissions?: string[], expires_at?: string): Promise<{ key: string; key_id: string }> {
    return this.client.request('POST', '/api/auth/api-key', { json: { name, permissions, expires_at } });
  }

  /**
   * List API keys for current user.
   *
   * @returns List of API keys (secrets are redacted)
   */
  async listApiKeys(): Promise<{ keys: unknown[] }> {
    return this.client.request('GET', '/api/keys');
  }

  /**
   * Revoke an API key.
   *
   * @param keyId - API key ID to revoke
   * @returns Revocation result
   */
  async revokeApiKey(keyId: string): Promise<{ revoked: boolean }> {
    return this.client.request('GET', `/api/keys/${keyId}`);
  }

  // =========================================================================
  // Sessions
  // =========================================================================

  /**
   * List active sessions for current user.
   *
   * @returns List of active sessions with device info
   */
  async listSessions(): Promise<{ sessions: unknown[] }> {
    return this.client.request('GET', '/api/auth/sessions');
  }

  /**
   * Revoke a specific session.
   *
   * @param sessionId - Session ID to revoke
   * @returns Revocation result
   */
  async revokeSession(sessionId: string): Promise<{ revoked: boolean }> {
    return this.client.request('DELETE', `/api/auth/sessions/${sessionId}`);
  }

  /**
   * Logout from all devices.
   *
   * Revokes all active sessions except the current one.
   *
   * @returns Logout result
   */
  async logoutAll(): Promise<{ logged_out: boolean }> {
    return this.client.request('POST', '/api/auth/logout-all');
  }

  // =========================================================================
  // MFA
  // =========================================================================

  /**
   * Setup MFA - generate secret and QR code.
   *
   * Call this to start MFA enrollment. The returned secret should be
   * added to an authenticator app, then confirmed with enableMfa().
   *
   * @returns MFA setup data including secret and QR code URL
   */
  async setupMfa(): Promise<{ secret: string; qr_code: string }> {
    return this.client.request('POST', '/api/auth/mfa/setup');
  }

  /**
   * Enable MFA by verifying setup code.
   *
   * After calling setupMfa(), verify the setup by providing a code
   * from the authenticator app.
   *
   * @param code - TOTP code from authenticator app
   * @returns MFA status and backup codes (save these securely)
   */
  async enableMfa(code: string): Promise<{ enabled: boolean; backup_codes: string[] }> {
    return this.client.request('POST', '/api/auth/mfa/enable', { json: { code } });
  }

  /**
   * Disable MFA.
   *
   * Requires a valid MFA code to confirm the action.
   *
   * @param code - TOTP code from authenticator app
   * @returns Disable result
   */
  async disableMfa(code: string): Promise<{ disabled: boolean }> {
    return this.client.request('POST', '/api/auth/mfa/disable', { json: { code } });
  }

  /**
   * Verify MFA code during login.
   *
   * Called after initial login when MFA is required.
   *
   * @param code - TOTP code from authenticator app or backup code
   * @returns Verification result with session token
   */
  async verifyMfa(code: string): Promise<{ verified: boolean; token?: string }> {
    return this.client.request('POST', '/api/auth/mfa/verify', { json: { code } });
  }

  /**
   * Regenerate MFA backup codes.
   *
   * Invalidates all previous backup codes and generates new ones.
   * Requires a valid MFA code to confirm the action.
   *
   * @param code - TOTP code from authenticator app
   * @returns New backup codes (save these securely)
   */
  async regenerateBackupCodes(code: string): Promise<{ backup_codes: string[] }> {
    return this.client.request('POST', '/api/auth/mfa/backup-codes', { json: { code } });
  }

  /**
   * List all available permissions.
   */
  async getAllPermissions(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/rbac/permissions', { params }) as Promise<Record<string, unknown>>;
  }

  /**
   * List all available roles.
   */
  async getAllRoles(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/rbac/roles', { params }) as Promise<Record<string, unknown>>;
  }

  /**
   * Get a role by name (request-based).
   *
   * @param roleName - Role name
   * @returns Role details with permissions
   */
  async getRoleByName(roleName: string): Promise<Role> {
    return this.client.request('GET', `/api/v1/rbac/roles/${encodeURIComponent(roleName)}`);
  }

  /**
   * Delete a role assignment by ID.
   *
   * @param assignmentId - Assignment ID to delete
   * @returns Deletion result
   */
  async deleteAssignment(assignmentId: string): Promise<{ deleted: boolean }> {
    return this.client.request('GET', `/api/v1/rbac/assignments/${encodeURIComponent(assignmentId)}`);
  }

}
