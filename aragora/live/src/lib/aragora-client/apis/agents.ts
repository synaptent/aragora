/**
 * Agents API
 *
 * Handles agent management, profiles, and leaderboard operations.
 */

import { BaseAPI, HttpClient } from './base';

// =============================================================================
// Types
// =============================================================================

export interface AgentProfile {
  agent_id: string;
  name: string;
  provider: string;
  elo_rating?: number;
  wins?: number;
  losses?: number;
  draws?: number;
  specializations?: string[];
  description?: string;
  avatar_url?: string;
  capabilities?: string[];
  model_version?: string;
}

export interface AgentCreateRequest {
  name: string;
  provider: string;
  description?: string;
  capabilities?: string[];
  config?: Record<string, unknown>;
}

export interface LeaderboardEntry {
  agent_id: string;
  elo_rating: number;
  rank: number;
  wins?: number;
  losses?: number;
  win_rate?: number;
  total_debates?: number;
}

export interface LeaderboardResponse {
  leaderboard: LeaderboardEntry[];
  total: number;
  updated_at: string;
}

export interface AgentStatsResponse {
  agent_id: string;
  total_debates: number;
  wins: number;
  losses: number;
  draws: number;
  win_rate: number;
  avg_consensus_contribution: number;
  avg_response_time_ms: number;
  specialization_scores: Record<string, number>;
  recent_debates: Array<{
    debate_id: string;
    task: string;
    result: 'win' | 'loss' | 'draw';
    date: string;
  }>;
}

// =============================================================================
// Agents API Class
// =============================================================================

export class AgentsAPI extends BaseAPI {
  constructor(http: HttpClient) {
    super(http);
  }

  /**
   * List all available agents
   */
  async list(): Promise<{ agents: AgentProfile[] }> {
    return this.http.get('/api/agents');
  }

  /**
   * Get a specific agent by ID
   */
  async get(agentId: string): Promise<{ agent: AgentProfile }> {
    return this.http.get(`/api/agents/${agentId}`);
  }

  /**
   * Create a custom agent
   */
  async create(request: AgentCreateRequest): Promise<{ agent: AgentProfile }> {
    return this.http.post('/api/agents', request);
  }

  /**
   * Update an agent's configuration
   */
  async update(
    agentId: string,
    updates: Partial<AgentCreateRequest>,
  ): Promise<{ agent: AgentProfile }> {
    return this.http.patch(`/api/agents/${agentId}`, updates);
  }

  /**
   * Delete a custom agent
   */
  async delete(agentId: string): Promise<{ message: string }> {
    return this.http.delete(`/api/agents/${agentId}`);
  }

  /**
   * Get agent statistics
   */
  async stats(agentId: string): Promise<AgentStatsResponse> {
    return this.http.get(`/api/agents/${agentId}/stats`);
  }

  /**
   * Get agent leaderboard
   */
  async leaderboard(limit = 50, category?: string): Promise<LeaderboardResponse> {
    const params = new URLSearchParams();
    params.set('limit', String(limit));
    if (category) params.set('category', category);
    return this.http.get(`/api/leaderboard?${params}`);
  }

  /**
   * Get agent's debate history
   */
  async debates(
    agentId: string,
    limit = 10,
  ): Promise<{
    debates: Array<{ debate_id: string; task: string; result: string; date: string }>;
  }> {
    return this.http.get(`/api/agents/${agentId}/debates?limit=${limit}`);
  }

  /**
   * Get recommended agents for a task
   */
  async recommend(task: string, count = 3): Promise<{ agents: AgentProfile[] }> {
    return this.http.post('/api/agents/recommend', { task, count });
  }
}
