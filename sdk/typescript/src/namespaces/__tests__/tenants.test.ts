/**
 * Tenants Namespace Tests
 *
 * Comprehensive tests for the tenants namespace API including:
 * - Tenant listing and creation
 * - Member management
 */

import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import { TenantsAPI } from '../tenants';

interface MockClient {
  listTenants: Mock;
  createTenant: Mock;
  addTenantMember: Mock;
  removeTenantMember: Mock;
}

describe('TenantsAPI Namespace', () => {
  let api: TenantsAPI;
  let mockClient: MockClient;

  beforeEach(() => {
    mockClient = {
      listTenants: vi.fn(),
      createTenant: vi.fn(),
      addTenantMember: vi.fn(),
      removeTenantMember: vi.fn(),
    };
    api = new TenantsAPI(mockClient as any);
  });

  // ===========================================================================
  // Tenant listing and creation
  // ===========================================================================

  describe('Tenant listing and creation', () => {
    it('should list tenants', async () => {
      const mockTenants = {
        tenants: [
          { id: 't1', name: 'Acme Corp', plan: 'enterprise', status: 'active' },
          { id: 't2', name: 'TechStart', plan: 'starter', status: 'active' },
        ],
        total: 2,
      };
      mockClient.listTenants.mockResolvedValue(mockTenants);

      const result = await api.list();

      expect(mockClient.listTenants).toHaveBeenCalled();
      expect(result.tenants).toHaveLength(2);
    });

    it('should list tenants with pagination', async () => {
      const mockTenants = { tenants: [{ id: 't3' }], total: 10 };
      mockClient.listTenants.mockResolvedValue(mockTenants);

      await api.list({ limit: 10, offset: 20 });

      expect(mockClient.listTenants).toHaveBeenCalledWith({ limit: 10, offset: 20 });
    });

    it('should create tenant', async () => {
      const mockTenant = {
        id: 't_new',
        name: 'New Tenant',
        plan: 'pro',
        status: 'active',
      };
      mockClient.createTenant.mockResolvedValue(mockTenant);

      const result = await api.create({ name: 'New Tenant', plan: 'pro' });

      expect(mockClient.createTenant).toHaveBeenCalledWith({ name: 'New Tenant', plan: 'pro' });
      expect(result.id).toBe('t_new');
    });
  });

  // ===========================================================================
  // Member Management
  // ===========================================================================

  describe('Member Management', () => {
    it('should add tenant member', async () => {
      const mockMember = {
        id: 'u_new',
        email: 'newuser@acme.com',
        role: 'member',
        joined_at: '2024-01-20T10:00:00Z',
      };
      mockClient.addTenantMember.mockResolvedValue(mockMember);

      const result = await api.addMember('t1', { email: 'newuser@acme.com', role: 'member' });

      expect(mockClient.addTenantMember).toHaveBeenCalledWith('t1', {
        email: 'newuser@acme.com',
        role: 'member',
      });
      expect(result.email).toBe('newuser@acme.com');
    });

    it('should remove tenant member', async () => {
      mockClient.removeTenantMember.mockResolvedValue(undefined);

      await api.removeMember('t1', 'u2');

      expect(mockClient.removeTenantMember).toHaveBeenCalledWith('t1', 'u2');
    });
  });
});
