/**
 * Admin Namespace Tests
 *
 * Comprehensive tests for the admin namespace API including:
 * - Organization and user management
 * - Platform statistics and system metrics
 * - Revenue analytics
 * - Nomic loop control
 * - Security operations
 */

import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import { AdminAPI } from '../admin';

interface MockClient {
  request: Mock;
  listOrganizations: Mock;
  listAdminUsers: Mock;
  activateAdminUser: Mock;
  getAdminStats: Mock;
  getAdminSystemMetrics: Mock;
  getRevenue: Mock;
  getAdminNomicStatus: Mock;
  getAdminCircuitBreakers: Mock;
  resetNomic: Mock;
  pauseNomic: Mock;
  resumeNomic: Mock;
  getAdminSecurityStatus: Mock;
  rotateSecurityKey: Mock;
  getAdminSecurityHealth: Mock;
  listSecurityKeys: Mock;
}

describe('AdminAPI Namespace', () => {
  let api: AdminAPI;
  let mockClient: MockClient;

  beforeEach(() => {
    mockClient = {
      request: vi.fn(),
      listOrganizations: vi.fn(),
      listAdminUsers: vi.fn(),
      activateAdminUser: vi.fn(),
      getAdminStats: vi.fn(),
      getAdminSystemMetrics: vi.fn(),
      getRevenue: vi.fn(),
      getAdminNomicStatus: vi.fn(),
      getAdminCircuitBreakers: vi.fn(),
      resetNomic: vi.fn(),
      pauseNomic: vi.fn(),
      resumeNomic: vi.fn(),
      getAdminSecurityStatus: vi.fn(),
      rotateSecurityKey: vi.fn(),
      getAdminSecurityHealth: vi.fn(),
      listSecurityKeys: vi.fn(),
    };
    api = new AdminAPI(mockClient as any);
  });

  // ===========================================================================
  // Organizations
  // ===========================================================================

  describe('Organizations', () => {
    it('should list organizations', async () => {
      const mockOrgs = {
        organizations: [
          { id: 'org1', name: 'Acme Corp', status: 'active', plan: 'pro', user_count: 50 },
          { id: 'org2', name: 'TechStart', status: 'active', plan: 'starter', user_count: 5 },
        ],
        total: 2,
        limit: 20,
        offset: 0,
      };
      mockClient.listOrganizations.mockResolvedValue(mockOrgs);

      const result = await api.listOrganizations();

      expect(mockClient.listOrganizations).toHaveBeenCalled();
      expect(result.organizations).toHaveLength(2);
    });

    it('should list organizations with pagination', async () => {
      const mockOrgs = {
        organizations: [{ id: 'org3' }],
        total: 100,
        limit: 1,
        offset: 50,
      };
      mockClient.listOrganizations.mockResolvedValue(mockOrgs);

      const result = await api.listOrganizations({ limit: 1, offset: 50 });

      expect(mockClient.listOrganizations).toHaveBeenCalledWith({ limit: 1, offset: 50 });
      expect(result.total).toBe(100);
    });
  });

  // ===========================================================================
  // Users
  // ===========================================================================

  describe('Users', () => {
    it('should list users', async () => {
      const mockUsers = {
        users: [
          { id: 'u1', email: 'admin@acme.com', name: 'Admin', role: 'admin', status: 'active' },
          { id: 'u2', email: 'user@acme.com', name: 'User', role: 'member', status: 'active' },
        ],
        total: 2,
        limit: 20,
        offset: 0,
      };
      mockClient.listAdminUsers.mockResolvedValue(mockUsers);

      const result = await api.listUsers();

      expect(mockClient.listAdminUsers).toHaveBeenCalled();
      expect(result.users).toHaveLength(2);
    });

    it('should activate user', async () => {
      const mockAction = {
        success: true,
        user_id: 'u2',
        status: 'active',
      };
      mockClient.request.mockResolvedValue(mockAction);

      const result = await api.activateUser('u2');

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/admin/users/u2/activate');
      expect(result.status).toBe('active');
    });
  });

  // ===========================================================================
  // Platform Statistics
  // ===========================================================================

  describe('Platform Statistics', () => {
    it('should get platform stats', async () => {
      const mockStats = {
        total_organizations: 500,
        total_users: 5000,
        active_debates: 150,
        debates_today: 45,
        debates_this_week: 312,
        total_debates: 125000,
        agent_calls_today: 15000,
        consensus_rate: 0.87,
      };
      mockClient.getAdminStats.mockResolvedValue(mockStats);

      const result = await api.getStats();

      expect(mockClient.getAdminStats).toHaveBeenCalled();
      expect(result.total_organizations).toBe(500);
      expect(result.consensus_rate).toBe(0.87);
    });

    it('should get system metrics', async () => {
      const mockMetrics = {
        cpu_usage: 45.5,
        memory_usage: 62.3,
        disk_usage: 38.1,
        active_connections: 1250,
        request_rate: 450.5,
        error_rate: 0.02,
        avg_latency_ms: 85,
        uptime_seconds: 864000,
      };
      mockClient.request.mockResolvedValue(mockMetrics);

      const result = await api.getSystemMetrics();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/admin/system/metrics');
      expect(result.cpu_usage).toBe(45.5);
      expect(result.error_rate).toBe(0.02);
    });

    it('should get revenue analytics', async () => {
      const mockRevenue = {
        mrr: 125000,
        arr: 1500000,
        revenue_this_month: 128000,
        revenue_last_month: 122000,
        growth_rate: 0.049,
        churn_rate: 0.02,
        active_subscriptions: 450,
        trial_conversions: 35,
      };
      mockClient.getRevenue.mockResolvedValue(mockRevenue);

      const result = await api.getRevenue();

      expect(mockClient.getRevenue).toHaveBeenCalled();
      expect(result.mrr).toBe(125000);
      expect(result.growth_rate).toBe(0.049);
    });
  });

  // ===========================================================================
  // Nomic Loop Control
  // ===========================================================================

  describe('Nomic Loop Control', () => {
    it('should get Nomic status', async () => {
      const mockStatus = {
        running: true,
        current_phase: 'implement',
        current_cycle: 5,
        total_cycles: 10,
        last_run: '2024-01-20T09:00:00Z',
        next_scheduled: '2024-01-20T12:00:00Z',
        health: 'healthy',
      };
      mockClient.getAdminNomicStatus.mockResolvedValue(mockStatus);

      const result = await api.getNomicStatus();

      expect(mockClient.getAdminNomicStatus).toHaveBeenCalled();
      expect(result.running).toBe(true);
      expect(result.current_phase).toBe('implement');
    });

    it('should get circuit breakers', async () => {
      const mockBreakers = {
        circuit_breakers: [
          {
            name: 'anthropic',
            state: 'closed',
            failure_count: 2,
            success_count: 1500,
            threshold: 5,
            timeout_seconds: 60,
          },
          {
            name: 'openai',
            state: 'half_open',
            failure_count: 4,
            success_count: 1200,
            threshold: 5,
            timeout_seconds: 60,
          },
        ],
      };
      mockClient.request.mockResolvedValue(mockBreakers);

      const result = await api.getCircuitBreakers();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/admin/circuit-breakers');
      expect(result.circuit_breakers).toHaveLength(2);
    });

    it('should reset Nomic loop', async () => {
      mockClient.resetNomic.mockResolvedValue({ success: true });

      const result = await api.resetNomic();

      expect(mockClient.resetNomic).toHaveBeenCalled();
      expect(result.success).toBe(true);
    });

    it('should pause Nomic loop', async () => {
      mockClient.pauseNomic.mockResolvedValue({ success: true });

      const result = await api.pauseNomic();

      expect(mockClient.pauseNomic).toHaveBeenCalled();
      expect(result.success).toBe(true);
    });

    it('should resume Nomic loop', async () => {
      mockClient.resumeNomic.mockResolvedValue({ success: true });

      const result = await api.resumeNomic();

      expect(mockClient.resumeNomic).toHaveBeenCalled();
      expect(result.success).toBe(true);
    });

    it('should reset circuit breakers', async () => {
      mockClient.request.mockResolvedValue({ success: true, reset_count: 3 });

      const result = await api.resetCircuitBreakers();

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/admin/circuit-breakers/reset');
      expect(result.reset_count).toBe(3);
    });
  });

  // ===========================================================================
  // Feature Flags
  // ===========================================================================

  describe('Feature Flags', () => {
    it('should list feature flags', async () => {
      const mockFlags = { flags: [{ name: 'enable_checkpointing', value: true }] };
      mockClient.request.mockResolvedValue(mockFlags);

      const result = await api.listFeatureFlags();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/admin/feature-flags');
      expect(result).toEqual(mockFlags);
    });

    it('should update feature flags through the detail route', async () => {
      mockClient.request
        .mockResolvedValueOnce({ name: 'enable_checkpointing', value: false })
        .mockResolvedValueOnce({ name: 'enable_checkpointing', updated: true })
        .mockResolvedValueOnce({ name: 'max_agent_retries', value: 3 })
        .mockResolvedValueOnce({ name: 'max_agent_retries', updated: true });

      const result = await api.updateFeatureFlags({
        enable_checkpointing: true,
        max_agent_retries: 7,
      });

      expect(mockClient.request).toHaveBeenNthCalledWith(
        1,
        'GET',
        '/api/v1/admin/feature-flags/enable_checkpointing',
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(
        2,
        'PUT',
        '/api/v1/admin/feature-flags/enable_checkpointing',
        { body: { value: true } },
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(
        3,
        'GET',
        '/api/v1/admin/feature-flags/max_agent_retries',
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(
        4,
        'PUT',
        '/api/v1/admin/feature-flags/max_agent_retries',
        { body: { value: 7 } },
      );
      expect(result).toEqual({
        enable_checkpointing: { name: 'enable_checkpointing', updated: true },
        max_agent_retries: { name: 'max_agent_retries', updated: true },
      });
    });

    it('should roll back applied feature flags when a later update fails', async () => {
      mockClient.request
        .mockResolvedValueOnce({ name: 'enable_checkpointing', value: false })
        .mockResolvedValueOnce({ name: 'enable_checkpointing', updated: true })
        .mockResolvedValueOnce({ name: 'max_agent_retries', value: 3 })
        .mockRejectedValueOnce(new Error('simulated second write failure'))
        .mockResolvedValueOnce({ name: 'enable_checkpointing', updated: true });

      await expect(
        api.updateFeatureFlags({
          enable_checkpointing: true,
          max_agent_retries: 7,
        }),
      ).rejects.toThrow('simulated second write failure');

      expect(mockClient.request).toHaveBeenNthCalledWith(
        1,
        'GET',
        '/api/v1/admin/feature-flags/enable_checkpointing',
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(
        2,
        'PUT',
        '/api/v1/admin/feature-flags/enable_checkpointing',
        { body: { value: true } },
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(
        3,
        'GET',
        '/api/v1/admin/feature-flags/max_agent_retries',
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(
        4,
        'PUT',
        '/api/v1/admin/feature-flags/max_agent_retries',
        { body: { value: 7 } },
      );
      expect(mockClient.request).toHaveBeenNthCalledWith(
        5,
        'PUT',
        '/api/v1/admin/feature-flags/enable_checkpointing',
        { body: { value: false } },
      );
    });

    it('should surface rollback failures explicitly', async () => {
      mockClient.request
        .mockResolvedValueOnce({ name: 'enable_checkpointing', value: false })
        .mockResolvedValueOnce({ name: 'enable_checkpointing', updated: true })
        .mockResolvedValueOnce({ name: 'max_agent_retries', value: 3 })
        .mockRejectedValueOnce(new Error('simulated second write failure'))
        .mockRejectedValueOnce(new Error('simulated rollback failure'));

      await expect(
        api.updateFeatureFlags({
          enable_checkpointing: true,
          max_agent_retries: 7,
        }),
      ).rejects.toThrow(
        'Bulk feature flag update failed and rollback did not restore all prior values: enable_checkpointing: simulated rollback failure',
      );
    });

    it('should get a feature flag by name', async () => {
      mockClient.request.mockResolvedValue({ name: 'enable_checkpointing', value: true });

      const result = await api.getFeatureFlag('enable_checkpointing');

      expect(mockClient.request).toHaveBeenCalledWith(
        'GET',
        '/api/v1/admin/feature-flags/enable_checkpointing',
      );
      expect(result.value).toBe(true);
    });

    it('should set a feature flag by name', async () => {
      mockClient.request.mockResolvedValue({ name: 'enable_checkpointing', updated: true });

      const result = await api.setFeatureFlag('enable_checkpointing', false);

      expect(mockClient.request).toHaveBeenCalledWith(
        'PUT',
        '/api/v1/admin/feature-flags/enable_checkpointing',
        { body: { value: false } },
      );
      expect(result.updated).toBe(true);
    });
  });

  // ===========================================================================
  // Security Operations
  // ===========================================================================

  describe('Security Operations', () => {
    it('should get security status', async () => {
      const mockStatus = {
        encryption_enabled: true,
        mfa_enforcement: 'required',
        audit_logging: true,
        key_rotation_due: false,
        last_security_scan: '2024-01-15T10:00:00Z',
        vulnerabilities_found: 0,
      };
      mockClient.getAdminSecurityStatus.mockResolvedValue(mockStatus);

      const result = await api.getSecurityStatus();

      expect(mockClient.getAdminSecurityStatus).toHaveBeenCalled();
      expect(result.encryption_enabled).toBe(true);
      expect(result.mfa_enforcement).toBe('required');
    });

    it('should get MFA compliance from the runtime-supported route', async () => {
      const mockCompliance = {
        total_admins: 2,
        mfa_enabled_count: 1,
        mfa_disabled_count: 1,
        compliance_pct: 50,
      };
      mockClient.request.mockResolvedValue(mockCompliance);

      const result = await api.getMfaCompliance();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/admin/mfa/compliance');
      expect(result.compliance_pct).toBe(50);
    });

    it.each([
      ['getSystemHealthCircuitBreakers', '/api/v1/admin/system-health/circuit-breakers'],
      ['getSystemHealthSlos', '/api/v1/admin/system-health/slos'],
      ['getSystemHealthAdapters', '/api/v1/admin/system-health/adapters'],
      ['getSystemHealthAgents', '/api/v1/admin/system-health/agents'],
      ['getSystemHealthBudget', '/api/v1/admin/system-health/budget'],
    ] as const)('should use runtime route for %s', async (methodName, expectedPath) => {
      mockClient.request.mockResolvedValue({ ok: true });

      const result = await (api as any)[methodName]();

      expect(mockClient.request).toHaveBeenCalledWith('GET', expectedPath);
      expect(result.ok).toBe(true);
    });

    it('should dispatch component lookups to documented system-health routes', async () => {
      mockClient.request.mockResolvedValue({ component: 'circuit-breakers' });

      const result = await api.getSystemHealthComponent('circuit_breakers');

      expect(mockClient.request).toHaveBeenCalledWith(
        'GET',
        '/api/v1/admin/system-health/circuit-breakers'
      );
      expect(result.component).toBe('circuit-breakers');
    });

    it('should reject unsupported system-health components', async () => {
      await expect(api.getSystemHealthComponent('overview')).rejects.toThrow(
        'Unsupported system health component: overview'
      );
      expect(mockClient.request).not.toHaveBeenCalled();
    });

    it('should rotate security key', async () => {
      const mockResult = { success: true, new_key_id: 'key_new_123' };
      mockClient.rotateSecurityKey.mockResolvedValue(mockResult);

      const result = await api.rotateSecurityKey('encryption');

      expect(mockClient.rotateSecurityKey).toHaveBeenCalledWith('encryption');
      expect(result.new_key_id).toBe('key_new_123');
    });

    it('should get security health', async () => {
      const mockHealth = {
        healthy: true,
        checks: {
          encryption: true,
          key_rotation: true,
          audit_logging: true,
          mfa: true,
          rate_limiting: true,
        },
      };
      mockClient.getAdminSecurityHealth.mockResolvedValue(mockHealth);

      const result = await api.getSecurityHealth();

      expect(mockClient.getAdminSecurityHealth).toHaveBeenCalled();
      expect(result.healthy).toBe(true);
    });

    it('should list security keys', async () => {
      const mockKeys = {
        keys: [
          { id: 'k1', type: 'encryption', status: 'active', created_at: '2024-01-01' },
          { id: 'k2', type: 'signing', status: 'active', created_at: '2024-01-01' },
        ],
      };
      mockClient.listSecurityKeys.mockResolvedValue(mockKeys);

      const result = await api.listSecurityKeys();

      expect(mockClient.listSecurityKeys).toHaveBeenCalled();
      expect(result.keys).toHaveLength(2);
    });
  });
});
