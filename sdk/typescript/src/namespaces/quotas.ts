/**
 * Quotas Namespace API
 *
 * Provides endpoints for managing resource quotas including
 * usage limits, quota policies, and usage tracking.
 */

import type { AragoraClient } from '../client';

/** Quota resource type */
export type QuotaResource = 'debates' | 'agents' | 'storage' | 'api_calls' | 'workflows';

/** Quota definition */
export interface Quota {
  id: string;
  resource: QuotaResource;
  limit: number;
  used: number;
  remaining: number;
  period: 'hourly' | 'daily' | 'monthly';
  resets_at: string;
}

/** Quota policy */
export interface QuotaPolicy {
  id: string;
  name: string;
  description?: string;
  limits: Record<string, number>;
  applies_to: string;
  created_at: string;
}

/** Quota usage history entry */
export interface QuotaUsageEntry {
  timestamp: string;
  resource: string;
  used: number;
  limit: number;
}

/**
 * Quotas namespace for resource limit management.
 *
 * @example
 * ```typescript
 * const quotas = await client.quotas.list();
 * const debateQuota = quotas.find(q => q.resource === 'debates');
 * console.log(`${debateQuota.remaining} debates remaining`);
 * ```
 */
export class QuotasNamespace {
  constructor(private client: AragoraClient) {}

  /** List all quotas for the current workspace. */
  async list(): Promise<Quota[]> {
    const response = await this.client.request<{ quotas: Quota[] }>(
      'GET',
      '/api/v1/quotas'
    );
    return response.quotas;
  }

  /** Get a specific quota by resource. */
  async get(resource: string): Promise<Quota> {
    return this.client.request<Quota>(
      'GET',
      `/api/quotas/${encodeURIComponent(resource)}`
    );
  }

  /** Get quota usage history. */
  async getUsageHistory(options?: {
    resource?: string;
    period?: string;
    limit?: number;
  }): Promise<QuotaUsageEntry[]> {
    const response = await this.client.request<{ usage: QuotaUsageEntry[] }>(
      'GET',
      '/api/quotas/usage',
      { params: options }
    );
    return response.usage;
  }

  /** Update a quota limit (admin only). */
  async updateLimit(resource: string, limit: number): Promise<Quota> {
    return this.client.request<Quota>(
      'PUT',
      `/api/v1/quotas/${encodeURIComponent(resource)}`,
      { body: { limit } }
    );
  }

  /**
   * Request a quota increase for a resource.
   *
   * Submits a request for a higher quota limit. Requests are reviewed
   * and typically processed within 1-2 business days.
   *
   * @param resource - Resource type to increase (e.g. 'debates', 'api_calls')
   * @param requestedLimit - Desired new limit value
   * @param reason - Business justification for the increase
   *
   * @example
   * ```typescript
   * const req = await client.quotas.requestIncrease('debates', 500, 'Running enterprise evaluation');
   * console.log(`Request ${req.request_id}: ${req.status}`);
   * ```
   */
  async requestIncrease(
    resource: string,
    requestedLimit: number,
    reason?: string
  ): Promise<{ request_id: string; status: string; resource: string; requested_limit: number }> {
    return this.client.request(
      'POST',
      '/api/v1/quotas/request-increase',
      { body: { resource, requested_limit: requestedLimit, reason } }
    );
  }
}
