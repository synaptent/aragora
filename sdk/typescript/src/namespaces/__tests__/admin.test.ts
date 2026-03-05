/**
 * Admin Namespace Tests
 *
 * Comprehensive tests for the admin namespace API including:
 * - Organization and user management
 * - Platform statistics and system metrics
 * - Revenue analytics
 * - Nomic loop control
 * - Credit management
 * - Security operations
 */

import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import { AdminAPI } from '../admin';

interface MockClient {
  request: Mock;
  listOrganizations: Mock;
  getAdminOrganization: Mock;
  updateAdminOrganization: Mock;
  listAdminUsers: Mock;
  getAdminUser: Mock;
  suspendAdminUser: Mock;
  activateAdminUser: Mock;
  getAdminStats: Mock;
  getAdminSystemMetrics: Mock;
  getRevenue: Mock;
  impersonateUser: Mock;
  getAdminNomicStatus: Mock;
  getAdminCircuitBreakers: Mock;
  resetNomic: Mock;
  pauseNomic: Mock;
  resumeNomic: Mock;
  resetAdminCircuitBreakers: Mock;
  issueCredits: Mock;
  getCreditAccount: Mock;
  listCreditTransactions: Mock;
  adjustCreditBalance: Mock;
  getExpiringCredits: Mock;
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
      getAdminOrganization: vi.fn(),
      updateAdminOrganization: vi.fn(),
      listAdminUsers: vi.fn(),
      getAdminUser: vi.fn(),
      suspendAdminUser: vi.fn(),
      activateAdminUser: vi.fn(),
      getAdminStats: vi.fn(),
      getAdminSystemMetrics: vi.fn(),
      getRevenue: vi.fn(),
      impersonateUser: vi.fn(),
      getAdminNomicStatus: vi.fn(),
      getAdminCircuitBreakers: vi.fn(),
      resetNomic: vi.fn(),
      pauseNomic: vi.fn(),
      resumeNomic: vi.fn(),
      resetAdminCircuitBreakers: vi.fn(),
      issueCredits: vi.fn(),
      getCreditAccount: vi.fn(),
      listCreditTransactions: vi.fn(),
      adjustCreditBalance: vi.fn(),
      getExpiringCredits: vi.fn(),
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

    it('should get organization by ID', async () => {
      const mockOrg = {
        id: 'org1',
        name: 'Acme Corp',
        created_at: '2024-01-01',
        status: 'active',
        plan: 'enterprise',
        user_count: 250,
      };
      mockClient.request.mockResolvedValue(mockOrg);

      const result = await api.getOrganization('org1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/admin/organizations/org1');
      expect(result.name).toBe('Acme Corp');
    });

    it('should update organization', async () => {
      const mockUpdated = {
        id: 'org1',
        name: 'Acme Corporation',
        status: 'active',
        plan: 'enterprise',
      };
      mockClient.request.mockResolvedValue(mockUpdated);

      const result = await api.updateOrganization('org1', { name: 'Acme Corporation' });

      expect(mockClient.request).toHaveBeenCalledWith('PUT', '/api/v1/admin/organizations/org1', {
        json: { name: 'Acme Corporation' },
      });
      expect(result.name).toBe('Acme Corporation');
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

    it('should get user by ID', async () => {
      const mockUser = {
        id: 'u1',
        email: 'admin@acme.com',
        name: 'Admin User',
        org_id: 'org1',
        role: 'admin',
        created_at: '2024-01-01',
        last_login: '2024-01-20T10:00:00Z',
        status: 'active',
      };
      mockClient.request.mockResolvedValue(mockUser);

      const result = await api.getUser('u1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/admin/users/u1');
      expect(result.email).toBe('admin@acme.com');
    });

    it('should suspend user', async () => {
      const mockAction = {
        success: true,
        user_id: 'u2',
        status: 'suspended',
        message: 'User suspended due to policy violation',
      };
      mockClient.request.mockResolvedValue(mockAction);

      const result = await api.suspendUser('u2', 'Policy violation');

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/admin/users/u2/suspend', {
        json: { reason: 'Policy violation' },
      });
      expect(result.status).toBe('suspended');
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

    it('should impersonate user', async () => {
      const mockToken = {
        token: 'impersonation_token_123',
        expires_at: '2024-01-20T11:00:00Z',
        user_id: 'u2',
        user_email: 'user@acme.com',
      };
      mockClient.request.mockResolvedValue(mockToken);

      const result = await api.impersonateUser('u2');

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/admin/users/u2/impersonate');
      expect(result.token).toBe('impersonation_token_123');
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
  // Credit Management
  // ===========================================================================

  describe('Credit Management', () => {
    it('should issue credits', async () => {
      const mockAccount = {
        org_id: 'org1',
        balance: 1000,
        lifetime_issued: 1000,
        lifetime_used: 0,
        expires_at: '2024-12-31',
      };
      mockClient.request.mockResolvedValue(mockAccount);

      const result = await api.issueCredits('org1', 1000, 'Welcome bonus', '2024-12-31');

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/admin/organizations/org1/credits', {
        json: {
          amount: 1000,
          reason: 'Welcome bonus',
          expires_at: '2024-12-31',
        },
      });
      expect(result.balance).toBe(1000);
    });

    it('should get credit account', async () => {
      const mockAccount = {
        org_id: 'org1',
        balance: 750,
        lifetime_issued: 1000,
        lifetime_used: 250,
      };
      mockClient.request.mockResolvedValue(mockAccount);

      const result = await api.getCreditAccount('org1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/admin/organizations/org1/credits');
      expect(result.balance).toBe(750);
    });

    it('should list credit transactions', async () => {
      const mockTransactions = {
        transactions: [
          { id: 't1', org_id: 'org1', amount: 1000, type: 'issue', reason: 'Welcome bonus' },
          { id: 't2', org_id: 'org1', amount: -50, type: 'use', reason: 'Debate usage' },
        ],
        total: 2,
      };
      mockClient.request.mockResolvedValue(mockTransactions);

      const result = await api.listCreditTransactions('org1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/admin/organizations/org1/credits/transactions', { params: undefined });
      expect(result.transactions).toHaveLength(2);
    });

    it('should adjust credit balance', async () => {
      const mockAccount = {
        org_id: 'org1',
        balance: 500,
        lifetime_issued: 1000,
        lifetime_used: 500,
      };
      mockClient.request.mockResolvedValue(mockAccount);

      const result = await api.adjustCredits('org1', -250, 'Refund adjustment');

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/admin/organizations/org1/credits', {
        body: { amount: -250, reason: 'Refund adjustment' },
      });
      expect(result.balance).toBe(500);
    });

    it('should get expiring credits', async () => {
      const mockExpiring = {
        credits: [
          { amount: 200, expires_at: '2024-01-31' },
          { amount: 300, expires_at: '2024-02-28' },
        ],
      };
      mockClient.request.mockResolvedValue(mockExpiring);

      const result = await api.getExpiringCredits('org1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/admin/organizations/org1/credits/expiring');
      expect(result.credits).toHaveLength(2);
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
