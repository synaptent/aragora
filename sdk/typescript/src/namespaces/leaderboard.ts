/**
 * Leaderboard Namespace API
 *
 * Provides access to agent rankings, ELO scores, and performance comparisons.
 */

/**
 * Agent ranking entry
 */
export interface RankingEntry {
  rank: number;
  agent_name: string;
  elo: number;
  wins: number;
  losses: number;
  draws: number;
  total_debates: number;
  win_rate: number;
  streak: number;
  streak_type: 'win' | 'loss' | 'none';
  last_debate?: string;
  specialties?: string[];
}

/**
 * Agent performance metrics
 */
export interface AgentPerformance {
  agent_name: string;
  elo: number;
  elo_history: Array<{ date: string; elo: number }>;
  debates_by_domain: Record<string, number>;
  win_rate_by_domain: Record<string, number>;
  average_proposal_quality: number;
  critique_effectiveness: number;
  consensus_contribution: number;
  total_tokens_used: number;
  average_response_time_ms: number;
}

/**
 * Head-to-head comparison
 */
export interface HeadToHead {
  agent_a: string;
  agent_b: string;
  agent_a_wins: number;
  agent_b_wins: number;
  draws: number;
  total_matchups: number;
  last_matchup?: string;
  domains: string[];
}

/**
 * Domain leaderboard
 */
export interface DomainLeaderboard {
  domain: string;
  rankings: RankingEntry[];
  total_debates: number;
  last_updated: string;
}

/**
 * Leaderboard summary view
 */
export interface LeaderboardView {
  global: RankingEntry[];
  by_domain: DomainLeaderboard[];
  recent_movers: Array<{
    agent_name: string;
    elo_change: number;
    new_rank: number;
    old_rank: number;
  }>;
  updated_at: string;
}

/**
 * Interface for the internal client used by LeaderboardAPI.
 */
interface LeaderboardClientInterface {
  request<T>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Leaderboard API namespace.
 *
 * Provides methods for viewing agent rankings and performance:
 * - View global and domain-specific leaderboards
 * - Compare agent performance
 * - Track ELO changes over time
 * - Analyze head-to-head matchups
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai', apiKey: 'your-key' });
 *
 * // Get global leaderboard
 * const { rankings } = await client.leaderboard.getRankings();
 *
 * // Compare two agents
 * const comparison = await client.leaderboard.compareAgents('claude', 'gpt4');
 * ```
 */
export class LeaderboardAPI {
  constructor(private client: LeaderboardClientInterface) {}

  /**
   * Get global agent rankings.
   */
  async getRankings(options?: {
    limit?: number;
    offset?: number;
    min_debates?: number;
  }): Promise<{ rankings: RankingEntry[]; total: number }> {
    return this.client.request('GET', '/api/leaderboard', { params: options });
  }

  /**
   * Get full leaderboard view with global and domain rankings.
   */
  async getView(): Promise<LeaderboardView> {
    return this.client.request('GET', '/api/leaderboard-view');
  }

  /**
   * Compare two agents head-to-head.
   */
  async compareAgents(agentA: string, agentB: string): Promise<HeadToHead> {
    return this.client.request('GET', '/api/leaderboard/compare', {
      params: { agent_a: agentA, agent_b: agentB },
    });
  }

  /**
   * Get agents that have moved the most in rankings recently.
   */
  async getMovers(options?: {
    period?: '24h' | '7d' | '30d';
    direction?: 'up' | 'down' | 'both';
    limit?: number;
  }): Promise<{
    movers: Array<{
      agent_name: string;
      elo_change: number;
      rank_change: number;
      debates_count: number;
    }>;
  }> {
    return this.client.request('GET', '/api/leaderboard/movers', { params: options });
  }

  /**
   * Get list of domains with active leaderboards.
   */
  async getDomains(): Promise<{
    domains: Array<{ name: string; debate_count: number; agent_count: number }>;
  }> {
    return this.client.request('GET', '/api/leaderboard/domains');
  }
}
