/**
 * Admin API
 *
 * Handles admin-level operations including revenue analytics,
 * system statistics, and organization management.
 */

import { BaseAPI, HttpClient } from './base';

// =============================================================================
// Types
// =============================================================================

export interface TierRevenue {
  count: number;
  mrr_cents: number;
}

export interface RevenueData {
  mrr_dollars: number;
  arr_dollars: number;
  mrr_cents: number;
  paying_organizations: number;
  total_organizations: number;
  tier_breakdown: Record<string, TierRevenue>;
}

export interface RevenueResponse {
  revenue: RevenueData;
}

export interface AdminStats {
  total_users: number;
  users_active_24h: number;
  new_users_7d: number;
  total_debates_this_month: number;
  total_organizations?: number;
  debates_today?: number;
}

export interface AdminStatsResponse {
  stats: AdminStats;
}

export interface Organization {
  id: string;
  name: string;
  tier: string;
  created_at: string;
  user_count: number;
  debate_count: number;
  is_active: boolean;
}

export interface OrganizationsResponse {
  organizations: Organization[];
  total: number;
}

export interface User {
  id: string;
  email: string;
  name: string;
  organization_id?: string;
  role: string;
  created_at: string;
  last_login?: string;
  is_active: boolean;
}

export interface UsersResponse {
  users: User[];
  total: number;
  page: number;
  per_page: number;
}

export interface SystemHealth {
  status: string;
  components: Record<string, { status: string; latency_ms?: number; error?: string }>;
  uptime_seconds: number;
  version: string;
}

// =============================================================================
// Admin API Class
// =============================================================================

export class AdminAPI extends BaseAPI {
  constructor(http: HttpClient) {
    super(http);
  }

  /**
   * Get revenue analytics
   */
  async revenue(): Promise<RevenueResponse> {
    return this.http.get('/api/v1/admin/revenue');
  }

  /**
   * Get admin dashboard statistics
   */
  async stats(): Promise<AdminStatsResponse> {
    return this.http.get('/api/v1/admin/stats');
  }

  /**
   * List all organizations
   */
  async organizations(options?: {
    page?: number;
    per_page?: number;
    tier?: string;
    search?: string;
  }): Promise<OrganizationsResponse> {
    const params = new URLSearchParams();
    if (options?.page) params.set('page', options.page.toString());
    if (options?.per_page) params.set('per_page', options.per_page.toString());
    if (options?.tier) params.set('tier', options.tier);
    if (options?.search) params.set('search', options.search);

    const query = params.toString();
    return this.http.get(`/api/v1/admin/organizations${query ? `?${query}` : ''}`);
  }

  /**
   * Get organization by ID
   */
  async organization(id: string): Promise<{ organization: Organization }> {
    return this.http.get(`/api/v1/admin/organizations/${id}`);
  }

  /**
   * List all users (paginated)
   */
  async users(options?: {
    page?: number;
    per_page?: number;
    organization_id?: string;
    role?: string;
    search?: string;
  }): Promise<UsersResponse> {
    const params = new URLSearchParams();
    if (options?.page) params.set('page', options.page.toString());
    if (options?.per_page) params.set('per_page', options.per_page.toString());
    if (options?.organization_id) params.set('organization_id', options.organization_id);
    if (options?.role) params.set('role', options.role);
    if (options?.search) params.set('search', options.search);

    const query = params.toString();
    return this.http.get(`/api/v1/admin/users${query ? `?${query}` : ''}`);
  }

  /**
   * Get user by ID
   */
  async user(id: string): Promise<{ user: User }> {
    return this.http.get(`/api/v1/admin/users/${id}`);
  }

  /**
   * Get system health status
   */
  async health(): Promise<SystemHealth> {
    return this.http.get('/api/v1/admin/health');
  }

  /**
   * Get security overview
   */
  async security(): Promise<{
    threats_detected: number;
    blocked_requests: number;
    active_sessions: number;
    mfa_adoption_rate: number;
  }> {
    return this.http.get('/api/v1/admin/security/overview');
  }
}
