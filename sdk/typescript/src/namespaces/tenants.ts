/**
 * Tenants Namespace API
 *
 * Provides a namespaced interface for multi-tenancy operations.
 */

interface TenantsClientInterface {
  listTenants(params?: { limit?: number; offset?: number }): Promise<any>;
  createTenant(body: CreateTenantRequest): Promise<any>;
  addTenantMember(tenantId: string, body: { email: string; role?: string }): Promise<any>;
  removeTenantMember(tenantId: string, userId: string): Promise<void>;
}

/**
 * Tenant object.
 */
export interface Tenant {
  id: string;
  name: string;
  plan?: string;
  status: 'active' | 'suspended';
  created_at: string;
  updated_at?: string;
}

/**
 * Create tenant request.
 */
export interface CreateTenantRequest {
  name: string;
  plan?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Tenant member.
 */
export interface TenantMember {
  user_id: string;
  email: string;
  role: string;
  joined_at: string;
}

/**
 * Tenants API namespace.
 *
 * Provides methods for multi-tenancy management:
 * - Listing and creating tenants
 * - Member management
 */
export class TenantsAPI {
  constructor(private client: TenantsClientInterface) {}

  /**
   * List all tenants.
   * @route GET /api/v1/tenants
   */
  async list(params?: { limit?: number; offset?: number }): Promise<{ tenants: Tenant[] }> {
    return this.client.listTenants(params);
  }

  /**
   * Create a new tenant.
   * @route POST /api/v1/tenants
   */
  async create(body: CreateTenantRequest): Promise<Tenant> {
    return this.client.createTenant(body);
  }

  /**
   * Add a member to a tenant.
   * Compatibility alias for the flat client method.
   */
  async addMember(tenantId: string, body: { email: string; role?: string }): Promise<TenantMember> {
    return this.client.addTenantMember(tenantId, body);
  }

  /**
   * Remove a member from a tenant.
   * Compatibility alias for the flat client method.
   */
  async removeMember(tenantId: string, userId: string): Promise<void> {
    return this.client.removeTenantMember(tenantId, userId);
  }
}
