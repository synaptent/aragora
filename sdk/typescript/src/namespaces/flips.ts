/**
 * Flips Namespace API
 *
 * Provides access to recent and summary flip analytics.
 */

export interface FlipSummary {
  total_flips: number;
  by_agent?: Record<string, number>;
  by_topic?: Record<string, number>;
  period?: string;
}

export interface FlipEntry {
  flip_id: string;
  agent: string;
  topic?: string;
  previous_position?: string;
  new_position?: string;
  timestamp: string;
}

interface FlipsClientInterface {
  get<T>(path: string): Promise<T>;
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown> }
  ): Promise<T>;
}

export class FlipsAPI {
  constructor(private client: FlipsClientInterface) {}

  async getRecent(params?: { limit?: number; offset?: number }): Promise<{ flips: FlipEntry[]; total?: number }> {
    return this.client.request('GET', '/api/v1/flips/recent', { params: params as Record<string, unknown> });
  }

  async getSummary(params?: { period?: string }): Promise<FlipSummary> {
    return this.client.request('GET', '/api/v1/flips/summary', { params: params as Record<string, unknown> });
  }

  /** Get a specific flip by ID. */
  async get(flipId: string): Promise<FlipEntry> {
    return this.client.request('GET', `/api/v1/flips/${encodeURIComponent(flipId)}`);
  }
}
