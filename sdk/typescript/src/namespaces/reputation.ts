/**
 * Reputation Namespace API
 *
 * Provides access to agent reputation scores and profiles.
 */

export interface ReputationEntry {
  agent: string;
  reputation: number | null;
  trustworthiness?: number;
  expertise?: Record<string, number>;
  community_standing?: number;
  debate_count?: number;
  updated_at?: string;
}

export interface AgentReputation {
  agent: string;
  overall_reputation: number;
  trustworthiness: number;
  expertise: Record<string, number>;
  community_standing: number;
  history?: Array<{
    timestamp: string;
    reputation: number;
    event?: string;
  }>;
}

interface ReputationClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown> }
  ): Promise<T>;
}

export class ReputationAPI {
  constructor(private client: ReputationClientInterface) {}

  /**
   * List all agent reputations.
   */
  async listAll(params?: {
    limit?: number;
    sort_by?: string;
  }): Promise<{ reputations: ReputationEntry[]; count?: number }> {
    return this.client.request('GET', '/api/v1/reputation/all', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Get reputation for a specific agent by canonical path.
   *
   * @param agentName - Agent identifier
   *
   * @example
   * ```typescript
   * const rep = await client.reputation.get('claude-3-5-sonnet');
   * console.log(`Reputation: ${rep.overall_reputation}`);
   * ```
   */
  async get(agentName: string): Promise<AgentReputation> {
    return this.client.request('GET', `/api/v1/reputation/${encodeURIComponent(agentName)}`);
  }

  /**
   * Get reputation for a specific agent via agent endpoint.
   *
   * @param agentName - Agent identifier
   */
  async getAgent(agentName: string): Promise<AgentReputation> {
    return this.client.request('GET', `/api/v1/agent/${agentName}/reputation`);
  }

  /**
   * Get reputation history with optional date range filter.
   */
  async getHistory(params?: {
    start_date?: string;
    end_date?: string;
    agent?: string;
    limit?: number;
  }): Promise<{ history: Array<{ timestamp: string; agent: string; reputation: number; event?: string }> }> {
    return this.client.request('GET', '/api/v1/reputation/history', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Get reputation scores filtered by domain.
   */
  async getByDomain(domain: string): Promise<{ domain: string; reputations: ReputationEntry[] }> {
    return this.client.request('GET', '/api/v1/reputation/domain', {
      params: { domain },
    });
  }
}
