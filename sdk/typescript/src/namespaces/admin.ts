/**
 * Admin Namespace API
 *
 * Provides a namespaced interface for platform administration.
 * Requires admin role for all operations.
 */

import type { PaginationParams } from '../types';

// Admin-specific types
export interface Organization {
  id: string;
  name: string;
  created_at: string;
  status: 'active' | 'suspended' | 'pending';
  plan: string;
  user_count: number;
}

export interface OrganizationList {
  organizations: Organization[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminUser {
  id: string;
  email: string;
  name: string;
  org_id: string;
  role: string;
  created_at: string;
  last_login?: string;
  status: 'active' | 'suspended' | 'pending';
}

export interface AdminUserList {
  users: AdminUser[];
  total: number;
  limit: number;
  offset: number;
}

export interface PlatformStats {
  total_organizations: number;
  total_users: number;
  active_debates: number;
  debates_today: number;
  debates_this_week: number;
  total_debates: number;
  agent_calls_today: number;
  consensus_rate: number;
}

export interface RevenueData {
  mrr: number;
  arr: number;
  revenue_this_month: number;
  revenue_last_month: number;
  growth_rate: number;
  churn_rate: number;
  active_subscriptions: number;
  trial_conversions: number;
}

export interface NomicStatus {
  running: boolean;
  current_phase: string | null;
  current_cycle: number;
  total_cycles: number;
  last_run: string | null;
  next_scheduled: string | null;
  health: 'healthy' | 'degraded' | 'unhealthy';
}

export interface SecurityStatus {
  encryption_enabled: boolean;
  mfa_enforcement: 'none' | 'optional' | 'required';
  audit_logging: boolean;
  key_rotation_due: boolean;
  last_security_scan: string | null;
  vulnerabilities_found: number;
}

export interface SecurityKey {
  id: string;
  type: string;
  created_at: string;
  expires_at?: string;
  last_rotated?: string;
  status: 'active' | 'rotating' | 'expired';
}

/**
 * Interface for the internal client methods used by AdminAPI.
 */
interface AdminClientInterface {
  request<T = unknown>(method: string, path: string, options?: Record<string, unknown>): Promise<T>;
  listOrganizations(params?: PaginationParams): Promise<OrganizationList>;
  listAdminUsers(params?: PaginationParams): Promise<AdminUserList>;
  getAdminStats(): Promise<PlatformStats>;
  getRevenue(): Promise<RevenueData>;
  getAdminNomicStatus(): Promise<NomicStatus>;
  resetNomic(): Promise<{ success: boolean }>;
  pauseNomic(): Promise<{ success: boolean }>;
  resumeNomic(): Promise<{ success: boolean }>;
  getCreditAccount(orgId: string): Promise<Record<string, unknown>>;
  listCreditTransactions(orgId: string, params?: Record<string, unknown>): Promise<Record<string, unknown>>;
  adjustCreditBalance(orgId: string, data: { amount: number; reason: string }): Promise<Record<string, unknown>>;
  getExpiringCredits(orgId: string): Promise<Record<string, unknown>>;
  getAdminSecurityStatus(): Promise<SecurityStatus>;
  rotateSecurityKey(keyType: string): Promise<Record<string, unknown>>;
  getAdminSecurityHealth(): Promise<{ healthy: boolean; checks: Record<string, boolean> }>;
  listSecurityKeys(): Promise<{ keys: SecurityKey[] }>;
}

/**
 * Admin API namespace.
 *
 * Provides methods for platform administration:
 * - Organization and user listing
 * - Platform statistics
 * - Revenue analytics
 * - Nomic loop control
 * - Security operations
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai', apiKey: 'admin-key' });
 *
 * // View platform stats
 * const stats = await client.admin.getStats();
 * console.log(`${stats.total_organizations} organizations, ${stats.active_debates} active debates`);
 *
 * // Control Nomic loop
 * await client.admin.pauseNomic();
 * const status = await client.admin.getNomicStatus();
 * console.log(`Nomic running: ${status.running}`);
 * ```
 */
export class AdminAPI {
  constructor(private client: AdminClientInterface) {}

  // ===========================================================================
  // Organizations and Users
  // ===========================================================================

  /**
   * List all organizations with pagination.
   */
  async listOrganizations(params?: PaginationParams): Promise<OrganizationList> {
    return this.client.listOrganizations(params);
  }

  /**
   * Get an organization by ID.
   */
  async getOrganization(orgId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/admin/organizations/${orgId}`);
  }

  /**
   * Update an organization.
   */
  async updateOrganization(orgId: string, updates: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('PUT', `/api/v1/admin/organizations/${orgId}`, { json: updates });
  }

  // ===========================================================================
  // Users
  // ===========================================================================

  /**
   * List all users with pagination.
   */
  async listUsers(params?: PaginationParams): Promise<AdminUserList> {
    return this.client.listAdminUsers(params);
  }

  /**
   * Get a user by ID.
   */
  async getUser(userId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/admin/users/${userId}`);
  }

  /**
   * Suspend a user.
   */
  async suspendUser(userId: string, reason: string): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/admin/users/${userId}/suspend`, { json: { reason } });
  }

  /**
   * Activate a user.
   */
  async activateUser(userId: string): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/admin/users/${userId}/activate`);
  }

  /**
   * Impersonate a user.
   */
  async impersonateUser(userId: string): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/admin/users/${userId}/impersonate`);
  }

  // ===========================================================================
  // Platform Statistics
  // ===========================================================================

  /**
   * Get platform-wide statistics.
   */
  async getStats(): Promise<PlatformStats> {
    return this.client.getAdminStats();
  }

  /**
   * Get system metrics (CPU, memory, disk, etc.).
   */
  async getSystemMetrics(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/admin/system/metrics');
  }

  /**
   * Get revenue analytics.
   */
  async getRevenue(): Promise<RevenueData> {
    return this.client.getRevenue();
  }

  // ===========================================================================
  // Nomic Loop Control
  // ===========================================================================

  /**
   * Get the current Nomic loop status.
   */
  async getNomicStatus(): Promise<NomicStatus> {
    return this.client.getAdminNomicStatus();
  }

  /**
   * Reset the Nomic loop to initial state.
   */
  async resetNomic(): Promise<{ success: boolean }> {
    return this.client.resetNomic();
  }

  /**
   * Pause the Nomic loop.
   */
  async pauseNomic(): Promise<{ success: boolean }> {
    return this.client.pauseNomic();
  }

  /**
   * Resume a paused Nomic loop.
   */
  async resumeNomic(): Promise<{ success: boolean }> {
    return this.client.resumeNomic();
  }

  /**
   * Get circuit breaker states.
   */
  async getCircuitBreakers(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/admin/circuit-breakers');
  }

  /**
   * Reset all circuit breakers.
   */
  async resetCircuitBreakers(): Promise<Record<string, unknown>> {
    return this.client.request('POST', '/api/v1/admin/circuit-breakers/reset');
  }

  // ===========================================================================
  // Credit Management
  // ===========================================================================

  /**
   * Issue credits to an organization.
   */
  async issueCredits(orgId: string, amount: number, reason: string, expiresAt?: string): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/admin/organizations/${orgId}/credits`, {
      json: { amount, reason, expires_at: expiresAt },
    });
  }

  /**
   * Get credit account for an organization.
   */
  async getCreditAccount(orgId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/admin/organizations/${orgId}/credits`);
  }

  /**
   * List credit transactions for an organization.
   */
  async listCreditTransactions(orgId: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/admin/organizations/${orgId}/credits/transactions`, { params });
  }

  /**
   * Adjust credit balance for an organization.
   */
  async adjustCredits(orgId: string, amount: number, reason: string): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/admin/organizations/${orgId}/credits`, { body: { amount, reason } });
  }

  /**
   * Get expiring credits for an organization.
   */
  async getExpiringCredits(orgId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/admin/organizations/${orgId}/credits/expiring`);
  }

  // ===========================================================================
  // Security Operations
  // ===========================================================================

  /**
   * Get security status overview.
   */
  async getSecurityStatus(): Promise<SecurityStatus> {
    return this.client.getAdminSecurityStatus();
  }

  /**
   * Rotate a security key.
   */
  async rotateSecurityKey(keyType: string): Promise<Record<string, unknown>> {
    return this.client.rotateSecurityKey(keyType);
  }

  /**
   * Get security health check results.
   */
  async getSecurityHealth(): Promise<{ healthy: boolean; checks: Record<string, boolean> }> {
    return this.client.getAdminSecurityHealth();
  }

  /**
   * List all security keys.
   */
  async listSecurityKeys(): Promise<{ keys: SecurityKey[] }> {
    return this.client.listSecurityKeys();
  }

  /**
   * Get handler diagnostics.
   */
  async getHandlerDiagnostics(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('POST', '/api/v1/diagnostics/handlers', { params }) as Promise<Record<string, unknown>>;
  }

  // --- Emergency Access ---

  /** Activate emergency (break-glass) access. */
  async activateEmergency(data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('POST', '/api/v1/admin/emergency/activate', { body: data });
  }

  /** Deactivate emergency access. */
  async deactivateEmergency(data?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('POST', '/api/v1/admin/emergency/deactivate', { body: data });
  }

  /** Get emergency access status. */
  async getEmergencyStatus(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/admin/emergency/status');
  }

  /** Update feature flags. */
  async updateFeatureFlags(data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('PUT', '/api/v1/admin/feature-flags', { body: data });
  }

  /** Get a specific feature flag by name. */
  async getFeatureFlag(name: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/admin/feature-flags/${encodeURIComponent(name)}`);
  }

  /** Set a specific feature flag value. */
  async setFeatureFlag(name: string, value: unknown): Promise<Record<string, unknown>> {
    return this.client.request('PUT', `/api/v1/admin/feature-flags/${encodeURIComponent(name)}`, {
      body: { value },
    });
  }

  // ===========================================================================
  // Security Keys & Scans
  // ===========================================================================

  /** Get a specific security key by ID. */
  async getSecurityKey(keyId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/admin/security/keys/${encodeURIComponent(keyId)}`);
  }

  /** Revoke a specific security key. */
  async revokeSecurityKey(keyId: string): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/admin/security/keys/${encodeURIComponent(keyId)}/revoke`);
  }

  /** Run a security scan. */
  async runSecurityScan(): Promise<Record<string, unknown>> {
    return this.client.request('POST', '/api/v1/admin/security/scan');
  }

  /** Get a specific security scan result. */
  async getSecurityScan(scanId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/admin/security/scan/${encodeURIComponent(scanId)}`);
  }

  /** Resolve a security threat. */
  async resolveSecurityThreat(threatId: string, data?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/admin/security/threats/${encodeURIComponent(threatId)}/resolve`, {
      body: data,
    });
  }

  /** List detected security threats. */
  async listSecurityThreats(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/admin/security/threats');
  }

  /** Get security audit report. */
  async getSecurityAudit(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/admin/security/audit');
  }

  /** Get security compliance status. */
  async getSecurityCompliance(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/admin/security/compliance');
  }

  /** Get key rotation status. */
  async getRotationStatus(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/admin/security/rotation-status');
  }

  // ===========================================================================
  // System Health
  // ===========================================================================

  /** Get system health overview. */
  async getSystemHealth(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/admin/system-health');
  }

  /** Get health status for a specific component. */
  async getSystemHealthComponent(component: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/admin/system-health/${encodeURIComponent(component)}`);
  }

  /** Get MFA compliance status. */
  async getMfaCompliance(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/admin/mfa-compliance');
  }

  // ===========================================================================
  // User Management (additional)
  // ===========================================================================

  /** Deactivate a user. */
  async deactivateUser(userId: string): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/admin/users/${encodeURIComponent(userId)}/deactivate`);
  }

  /** Unlock a locked user account. */
  async unlockUser(userId: string): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/admin/users/${encodeURIComponent(userId)}/unlock`);
  }
}

// Re-export types for convenience
export type { PaginationParams };
