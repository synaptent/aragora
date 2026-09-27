/**
 * Organizations Namespace API
 *
 * Provides a namespaced interface for organization management operations.
 * This wraps the flat client methods for a more intuitive API.
 */

import type {
  Organization,
  OrganizationMember,
  OrganizationInvitation,
  UserOrganization,
  PaginationParams,
} from '../types';

/**
 * Interface for the internal client methods used by OrganizationsAPI.
 */
interface OrganizationsClientInterface {
  request<T = unknown>(method: string, path: string, options?: Record<string, unknown>): Promise<T>;
  getOrganization(orgId: string): Promise<Organization>;
  updateOrganization(orgId: string, body: { name?: string; settings?: Record<string, unknown> }): Promise<Organization>;
  listOrganizationMembers(orgId: string, params?: PaginationParams): Promise<{ members: OrganizationMember[] }>;
  inviteToOrganization(orgId: string, body: { email: string; role?: 'admin' | 'member' }): Promise<OrganizationInvitation>;
  listOrganizationInvitations(orgId: string, params?: PaginationParams): Promise<{ invitations: OrganizationInvitation[] }>;
  revokeOrganizationInvitation(orgId: string, invitationId: string): Promise<void>;
  removeOrganizationMember(orgId: string, userId: string): Promise<void>;
  updateOrganizationMemberRole(orgId: string, userId: string, role: 'admin' | 'member'): Promise<OrganizationMember>;
  listUserOrganizations(): Promise<{ organizations: UserOrganization[] }>;
  switchOrganization(orgId: string): Promise<{ organization_id: string }>;
  setDefaultOrganization(orgId: string): Promise<{ organization_id: string }>;
  leaveOrganization(orgId: string): Promise<void>;
  listPendingInvitations(): Promise<{ invitations: OrganizationInvitation[] }>;
  acceptInvitation(token: string): Promise<{ organization_id: string; role: string }>;
}

/**
 * Organizations API namespace.
 *
 * Provides methods for organization management:
 * - Managing organization settings
 * - Member management and invitations
 * - Organization switching for users
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // Get current organization
 * const org = await client.organizations.get(orgId);
 *
 * // Invite a member
 * await client.organizations.invite(orgId, {
 *   email: 'newuser@example.com',
 *   role: 'member',
 * });
 *
 * // List user's organizations
 * const { organizations } = await client.organizations.listMine();
 *
 * // Switch active organization
 * await client.organizations.switch(orgId);
 * ```
 */
export class OrganizationsAPI {
  constructor(private client: OrganizationsClientInterface) {}

  /**
   * Get an organization by ID.
   */
  async get(orgId: string): Promise<Organization> {
    return this.client.getOrganization(orgId);
  }

  /**
   * Update an organization.
   */
  async update(
    orgId: string,
    body: { name?: string; settings?: Record<string, unknown> }
  ): Promise<Organization> {
    return this.client.updateOrganization(orgId, body);
  }

  /**
   * List organization members.
   */
  async listMembers(
    orgId: string,
    params?: PaginationParams
  ): Promise<{ members: OrganizationMember[] }> {
    return this.client.listOrganizationMembers(orgId, params);
  }

  /**
   * Invite a user to the organization.
   */
  async invite(
    orgId: string,
    body: { email: string; role?: 'admin' | 'member' }
  ): Promise<OrganizationInvitation> {
    return this.client.inviteToOrganization(orgId, body);
  }

  /**
   * List pending invitations for an organization.
   */
  async listInvitations(
    orgId: string,
    params?: PaginationParams
  ): Promise<{ invitations: OrganizationInvitation[] }> {
    return this.client.listOrganizationInvitations(orgId, params);
  }

  /**
   * Revoke an invitation.
   */
  async revokeInvitation(orgId: string, invitationId: string): Promise<void> {
    return this.client.revokeOrganizationInvitation(orgId, invitationId);
  }

  /**
   * Remove a member from the organization.
   */
  async removeMember(orgId: string, userId: string): Promise<void> {
    return this.client.removeOrganizationMember(orgId, userId);
  }

  /**
   * Update a member's role.
   */
  async updateMemberRole(
    orgId: string,
    userId: string,
    role: 'admin' | 'member'
  ): Promise<OrganizationMember> {
    return this.client.updateOrganizationMemberRole(orgId, userId, role);
  }

  /**
   * List the current user's organizations.
   */
  async listMine(): Promise<{ organizations: UserOrganization[] }> {
    return this.client.listUserOrganizations();
  }

  /**
   * Switch to a different organization.
   */
  async switch(orgId: string): Promise<{ organization_id: string }> {
    return this.client.switchOrganization(orgId);
  }

  /**
   * Set the default organization for the current user.
   */
  async setDefault(orgId: string): Promise<{ organization_id: string }> {
    return this.client.setDefaultOrganization(orgId);
  }

  /**
   * Leave an organization.
   */
  async leave(orgId: string): Promise<void> {
    return this.client.leaveOrganization(orgId);
  }

  /**
   * List pending invitations for the current user.
   */
  async listMyInvitations(): Promise<{ invitations: OrganizationInvitation[] }> {
    return this.client.listPendingInvitations();
  }

  /**
   * Accept an organization invitation.
   */
  async acceptInvitation(token: string): Promise<{ organization_id: string; role: string }> {
    return this.client.acceptInvitation(token);
  }

  /**
   * Invite member to org.
   */
  async inviteMember(orgId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/org/${orgId}/invite`) as Promise<Record<string, unknown>>;
  }

  /**
   * Get pending invitations.
   */
  async getPendingInvitations(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/invitations/pending', { params }) as Promise<Record<string, unknown>>;
  }

  /**
   * List user organizations.
   */
  async listUserOrganizations(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/user/organizations', { params }) as Promise<Record<string, unknown>>;
  }

  /**
   * Get default organization.
   */
  async getDefaultOrganization(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/user/organizations/default', { params }) as Promise<Record<string, unknown>>;
  }

  /**
   * Switch active organization.
   */
  async switchOrganization(data?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/user/organizations/switch', { json: data }) as Promise<Record<string, unknown>>;
  }

  /**
   * List organization invitations.
   */
  async getOrgInvitations(orgId: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/org/${orgId}/invitations`, { params }) as Promise<Record<string, unknown>>;
  }

  /**
   * Get organization members.
   */
  async getOrgMembers(orgId: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/org/${orgId}/members`, { params }) as Promise<Record<string, unknown>>;
  }

  /**
   * Update a member's role in an organization.
   */
  async setMemberRole(orgId: string, memberId: string, data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/org/${orgId}/members/${memberId}/role`, { json: data }) as Promise<Record<string, unknown>>;
  }

  /**
   * Accept an invitation.
   */
  async acceptInvite(invitationId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/invitations/${invitationId}/accept`) as Promise<Record<string, unknown>>;
  }

  /**
   * Get an organization by ID (request-based).
   *
   * @param orgId - Organization ID
   */
  async getOrg(orgId: string): Promise<Organization> {
    return this.client.request('GET', `/api/v1/org/${orgId}`);
  }

  /**
   * Remove a member from an organization (request-based).
   *
   * @param orgId - Organization ID
   * @param userId - User ID to remove
   */
  async removeMemberDirect(orgId: string, userId: string): Promise<void> {
    return this.client.request('GET', `/api/v1/org/${orgId}/members/${userId}`);
  }

  /**
   * Revoke an invitation (request-based).
   *
   * @param orgId - Organization ID
   * @param invitationId - Invitation ID to revoke
   */
  async revokeInvitationDirect(orgId: string, invitationId: string): Promise<void> {
    return this.client.request('GET', `/api/v1/org/${orgId}/invitations/${invitationId}`);
  }

  /**
   * List all organizations.
   *
   * @route GET /api/v1/org
   */
  async listOrgs(params?: { limit?: number; offset?: number }): Promise<{ organizations: Organization[]; total: number }> {
    return this.client.request('GET', '/api/v1/org', { params: params as Record<string, unknown> });
  }

  /**
   * List all tenants.
   *
   * @route GET /api/v1/tenants
   */
  async listTenants(params?: { limit?: number; offset?: number }): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/tenants', { params: params as Record<string, unknown> });
  }

}
