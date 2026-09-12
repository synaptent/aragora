/**
 * Replays Namespace API
 *
 * Provides access to debate replays, event timelines, and replay visualization.
 */

/**
 * Replay event types
 */
export type ReplayEventType =
  | 'debate_start'
  | 'round_start'
  | 'round_end'
  | 'proposal'
  | 'critique'
  | 'revision'
  | 'vote'
  | 'consensus_check'
  | 'consensus_reached'
  | 'debate_end'
  | 'user_action'
  | 'system_event';

/**
 * Replay summary for listing
 */
export interface ReplaySummary {
  id: string;
  debate_id: string;
  task: string;
  agents: string[];
  total_rounds: number;
  total_events: number;
  duration_ms: number;
  result: 'consensus' | 'no_consensus' | 'timeout' | 'error';
  consensus_type?: string;
  created_at: string;
  size_bytes: number;
  has_video?: boolean;
}

/**
 * Replay event
 */
export interface ReplayEvent {
  id: string;
  type: ReplayEventType;
  timestamp: number;
  round?: number;
  agent?: string;
  content?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Full replay with events
 */
export interface Replay {
  id: string;
  debate_id: string;
  task: string;
  environment: Record<string, unknown>;
  protocol: Record<string, unknown>;
  agents: string[];
  events: ReplayEvent[];
  result: 'consensus' | 'no_consensus' | 'timeout' | 'error';
  consensus_proposal?: string;
  consensus_type?: string;
  total_tokens: number;
  total_cost?: number;
  created_at: string;
  metadata?: Record<string, unknown>;
}

/**
 * Evolution data showing how the debate progressed
 */
export interface EvolutionEntry {
  round: number;
  timestamp: number;
  proposals: Array<{
    agent: string;
    content: string;
    critique_count: number;
    revision_count: number;
    votes: number;
  }>;
  convergence_score: number;
  active_agents: string[];
}

/**
 * Replay fork for branching debates
 */
export interface ReplayFork {
  id: string;
  parent_replay_id: string;
  fork_point: number;
  fork_round: number;
  task_modification?: string;
  new_debate_id?: string;
  created_at: string;
}

/**
 * Interface for the internal client used by ReplaysAPI.
 */
interface ReplaysClientInterface {
  request<T>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Replays API namespace.
 *
 * Provides methods for accessing and analyzing debate replays:
 * - List and retrieve debate replays
 * - View event timelines
 * - Analyze debate evolution
 * - Fork debates from specific points
 * - Export replay visualizations
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai', apiKey: 'your-key' });
 *
 * // List recent replays
 * const { replays } = await client.replays.list({ limit: 10 });
 *
 * // Get a specific replay with all events
 * const replay = await client.replays.get('replay-id');
 *
 * // Get evolution data
 * const evolution = await client.replays.getEvolution('replay-id');
 * ```
 */
export class ReplaysAPI {
  constructor(private client: ReplaysClientInterface) {}

  /**
   * List available debate replays.
   */
  async list(options?: {
    agent?: string;
    result?: 'consensus' | 'no_consensus' | 'timeout' | 'error';
    since?: string;
    until?: string;
    limit?: number;
    offset?: number;
  }): Promise<{ replays: ReplaySummary[]; total: number }> {
    return this.client.request('GET', '/api/replays', { params: options });
  }

  /**
   * Get a specific replay with all events.
   */
  async get(replayId: string): Promise<Replay> {
    return this.client.request('GET', `/api/replays/${replayId}`);
  }

  /**
   * Get just the events for a replay (lighter than full replay).
   */
  async getEvents(
    replayId: string,
    options?: {
      type?: ReplayEventType;
      agent?: string;
      round?: number;
      limit?: number;
      offset?: number;
    }
  ): Promise<{ events: ReplayEvent[]; total: number }> {
    return this.client.request('GET', `/api/replays/${replayId}/events`, { params: options });
  }

  /**
   * Get evolution data showing how the debate progressed.
   */
  async getEvolution(replayId: string): Promise<{ evolution: EvolutionEntry[] }> {
    return this.client.request('GET', `/api/replays/${replayId}/evolution`);
  }

  /**
   * Get HTML visualization of the replay.
   */
  async getHtml(replayId: string): Promise<string> {
    return this.client.request('GET', `/api/replays/${replayId}/html`);
  }

  /**
   * Fork a debate from a specific point to explore alternatives.
   */
  async fork(
    replayId: string,
    options: {
      fork_round?: number;
      fork_event_id?: string;
      task_modification?: string;
      new_agents?: string[];
    }
  ): Promise<ReplayFork> {
    return this.client.request('POST', `/api/replays/${replayId}/fork`, { json: options });
  }

  /**
   * List forks created from a replay.
   */
  async listForks(replayId: string): Promise<{ forks: ReplayFork[] }> {
    return this.client.request('GET', `/api/replays/${replayId}/forks`);
  }

  /**
   * Delete a replay (admin only).
   */
  async delete(replayId: string): Promise<{ success: boolean }> {
    return this.client.request('DELETE', `/api/replays/${replayId}`);
  }

  /**
   * Compare two replays to analyze differences.
   */
  async compare(
    replayId1: string,
    replayId2: string
  ): Promise<{
    replay_1: { id: string; task: string; result: string };
    replay_2: { id: string; task: string; result: string };
    similarities: string[];
    differences: string[];
    agent_overlap: string[];
    convergence_comparison: { replay_1: number; replay_2: number };
  }> {
    return this.client.request('GET', '/api/replays/compare', {
      params: { replay_id_1: replayId1, replay_id_2: replayId2 },
    });
  }

  /**
   * Get replay statistics.
   */
  async getStats(options?: {
    period?: '7d' | '30d' | '90d' | 'all';
  }): Promise<{
    total_replays: number;
    total_events: number;
    average_duration_ms: number;
    consensus_rate: number;
    average_rounds: number;
    by_result: Record<string, number>;
  }> {
    return this.client.request('GET', '/api/replays/stats', { params: options });
  }

  /**
   * Search replays by content.
   */
  async search(
    query: string,
    options?: {
      in_proposals?: boolean;
      in_critiques?: boolean;
      agent?: string;
      limit?: number;
    }
  ): Promise<{
    results: Array<{
      replay_id: string;
      task: string;
      matches: Array<{ event_id: string; content: string; highlight: string }>;
    }>;
  }> {
    return this.client.request('GET', '/api/replays/search', {
      params: { q: query, ...options },
    });
  }
}
