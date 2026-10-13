/**
 * Agents Namespace API
 *
 * Provides a namespaced interface for agent-related operations.
 */

import type {
  Agent,
  AgentCalibration,
  AgentComparison,
  AgentConsistency,
  AgentFlip,
  AgentMoment,
  AgentNetwork,
  AgentPerformance,
  AgentPosition,
  AgentProfile,
  AgentRelationship,
  DomainRating,
  HeadToHeadStats,
  OpponentBriefing,
  PaginationParams,
  TeamSelection,
  TeamSelectionRequest,
} from '../types';

// =============================================================================
// Agent-specific Types (matching Python SDK)
// =============================================================================

/**
 * Agent persona configuration.
 */
export interface AgentPersona {
  agent_name: string;
  description?: string;
  traits?: string[];
  expertise?: string[];
  model?: string;
  temperature?: number;
  created_at?: string;
  updated_at?: string;
}

/**
 * Grounded persona with performance metrics.
 */
export interface GroundedPersona {
  agent_name: string;
  elo: number;
  domain_elos: Record<string, number>;
  win_rate: number;
  calibration_score: number;
  position_accuracy: number;
  debates_count: number;
  last_active?: string;
}

/**
 * Identity prompt response.
 */
export interface IdentityPrompt {
  agent_name: string;
  prompt: string;
  sections_included?: string[];
  token_count?: number;
}

/**
 * Agent accuracy metrics.
 */
export interface AgentAccuracy {
  agent_name: string;
  total_positions: number;
  verified_positions: number;
  correct_positions: number;
  accuracy_rate: number;
  by_domain?: Record<string, {
    total: number;
    correct: number;
    accuracy: number;
  }>;
}

/**
 * Interface for the internal client methods used by AgentsAPI.
 */
export interface AgentsClientInterface {
  // Core listing methods
  listAgents(): Promise<{ agents: Agent[] }>;
  listAgentsAvailability(): Promise<{ available: string[]; missing?: string[] }>;
  listAgentsHealth(): Promise<Record<string, unknown>>;
  listLocalAgents(): Promise<Record<string, unknown>>;
  getLocalAgentsStatus(): Promise<Record<string, unknown>>;

  // Basic agent info
  getAgent(name: string): Promise<Agent>;
  getAgentProfile(name: string): Promise<AgentProfile>;
  getAgentHistory(name: string, params?: Record<string, unknown>): Promise<{ matches: unknown[] }>;

  // Calibration
  getAgentCalibration(name: string): Promise<AgentCalibration>;
  getAgentCalibrationCurve(name: string): Promise<Record<string, unknown>>;
  getAgentCalibrationSummary(name: string): Promise<Record<string, unknown>>;

  // Performance
  getAgentPerformance(name: string): Promise<AgentPerformance>;
  getAgentHeadToHead(name: string, opponent: string): Promise<HeadToHeadStats>;
  getAgentOpponentBriefing(name: string, opponent: string): Promise<OpponentBriefing>;
  getAgentConsistency(name: string): Promise<AgentConsistency>;

  // Flips and positions
  getAgentFlips(name: string, params?: { limit?: number } & PaginationParams): Promise<{ flips: AgentFlip[] }>;
  getAgentPositions(name: string, params?: { topic?: string; limit?: number } & PaginationParams): Promise<{ positions: AgentPosition[] }>;

  // Network and relationships
  getAgentNetwork(name: string): Promise<AgentNetwork>;
  getAgentAllies(name: string): Promise<{ allies: AgentRelationship[] }>;
  getAgentRivals(name: string): Promise<{ rivals: AgentRelationship[] }>;
  getAgentRelationship(agentA: string, agentB: string): Promise<AgentRelationship>;

  // Other metrics
  getAgentReputation(name: string): Promise<{ reputation: number | null }>;
  getAgentMoments(name: string, params?: { type?: string; limit?: number } & PaginationParams): Promise<{ moments: AgentMoment[] }>;
  getAgentDomains(name: string): Promise<{ domains: DomainRating[] }>;
  getAgentElo(name: string): Promise<{ agent: string; elo: number; history: Array<{ date: string; elo: number }> }>;

  // Comparison and leaderboards
  getLeaderboard(): Promise<{ agents: Agent[] }>;
  compareAgents(agents: string[]): Promise<AgentComparison>;
  getAgentMetadata(name: string): Promise<Record<string, unknown>>;
  getAgentIntrospection(name: string): Promise<Record<string, unknown>>;
  getLeaderboardView(): Promise<Record<string, unknown>>;
  getRecentMatches(params?: { limit?: number }): Promise<{ matches: unknown[] }>;
  getRecentFlips(params?: { limit?: number }): Promise<{ flips: unknown[] }>;
  getFlipsSummary(): Promise<Record<string, unknown>>;
  getCalibrationLeaderboard(): Promise<{ agents: Array<{ name: string; score: number }> }>;

  // Team selection
  selectTeam(params: TeamSelectionRequest): Promise<TeamSelection>;

  // Generic request method (for persona/identity/accuracy endpoints)
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; body?: unknown }
  ): Promise<T>;
}

/**
 * Agents API namespace.
 *
 * Provides methods for managing and analyzing AI agents:
 * - Listing and retrieving agents
 * - Viewing agent profiles and performance
 * - Analyzing head-to-head matchups
 * - Tracking ELO ratings and calibration
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // List all agents
 * const { agents } = await client.agents.list();
 *
 * // Get agent profile
 * const profile = await client.agents.getProfile('claude');
 *
 * // Get head-to-head stats
 * const h2h = await client.agents.getHeadToHead('claude', 'gpt-4');
 * ```
 */
export class AgentsAPI {
  constructor(private client: AgentsClientInterface) {}

  /**
   * List all available agents.
   */
  async list(): Promise<{ agents: Agent[] }> {
    return this.client.listAgents();
  }

  /**
   * Get a specific agent by name.
   */
  async get(name: string): Promise<Agent> {
    return this.client.getAgent(name);
  }

  /**
   * Get availability information for configured agents.
   */
  async getAvailability(): Promise<{ available: string[]; missing?: string[] }> {
    return this.client.listAgentsAvailability();
  }

  /**
   * Get health status for configured agents.
   */
  async getHealth(): Promise<Record<string, unknown>> {
    return this.client.listAgentsHealth();
  }

  /**
   * List local agents on the current host.
   */
  async listLocal(): Promise<Record<string, unknown>> {
    return this.client.listLocalAgents();
  }

  /**
   * Get local agent status.
   */
  async getLocalStatus(): Promise<Record<string, unknown>> {
    return this.client.getLocalAgentsStatus();
  }

  /**
   * Get an agent's detailed profile.
   */
  async getProfile(name: string): Promise<AgentProfile> {
    return this.client.getAgentProfile(name);
  }

  /**
   * Get an agent's calibration curve data.
   */
  async getCalibrationCurve(name: string): Promise<Record<string, unknown>> {
    return this.client.getAgentCalibrationCurve(name);
  }

  /**
   * Get an agent's calibration summary data.
   */
  async getCalibrationSummary(name: string): Promise<Record<string, unknown>> {
    return this.client.getAgentCalibrationSummary(name);
  }

  /**
   * Get an agent's auditable calibration report (per-domain accuracy,
   * Brier/calibration-curve summary, sample sizes, data window). Agents with
   * no calibration data return an explicit `{ status: 'absent', reason }`.
   */
  async getCalibrationReport(name: string, params?: { domain?: string }): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>(
      'GET',
      `/api/v1/agents/${encodeURIComponent(name)}/calibration-report`,
      { params }
    );
  }

  /**
   * Get head-to-head statistics against another agent.
   */
  async getHeadToHead(name: string, opponent: string): Promise<HeadToHeadStats> {
    return this.client.getAgentHeadToHead(name, opponent);
  }

  /**
   * Get a briefing on an opponent agent.
   */
  async getOpponentBriefing(name: string, opponent: string): Promise<OpponentBriefing> {
    return this.client.getAgentOpponentBriefing(name, opponent);
  }

  /**
   * Get an agent's consistency metrics.
   */
  async getConsistency(name: string): Promise<AgentConsistency> {
    return this.client.getAgentConsistency(name);
  }

  /**
   * Get an agent's position flips (changes in stance).
   */
  async getFlips(name: string, params?: { limit?: number } & PaginationParams): Promise<{ flips: AgentFlip[] }> {
    return this.client.getAgentFlips(name, params);
  }

  /**
   * Get an agent's network of relationships.
   */
  async getNetwork(name: string): Promise<AgentNetwork> {
    return this.client.getAgentNetwork(name);
  }

  /**
   * Get an agent's allies.
   */
  async getAllies(name: string): Promise<{ allies: AgentRelationship[] }> {
    return this.client.getAgentAllies(name);
  }

  /**
   * Get an agent's rivals.
   */
  async getRivals(name: string): Promise<{ rivals: AgentRelationship[] }> {
    return this.client.getAgentRivals(name);
  }

  /**
   * Get notable moments from an agent's history.
   */
  async getMoments(name: string, params?: { type?: string; limit?: number } & PaginationParams): Promise<{ moments: AgentMoment[] }> {
    return this.client.getAgentMoments(name, params);
  }

  /**
   * Get an agent's positions on various topics.
   */
  async getPositions(name: string, params?: { topic?: string; limit?: number } & PaginationParams): Promise<{ positions: AgentPosition[] }> {
    return this.client.getAgentPositions(name, params);
  }

  /**
   * Get an agent's domain expertise ratings.
   */
  async getDomains(name: string): Promise<{ domains: DomainRating[] }> {
    return this.client.getAgentDomains(name);
  }

  /**
   * Get agent rankings leaderboard.
   */
  async getLeaderboard(): Promise<{ agents: Agent[] }> {
    return this.client.getLeaderboard();
  }

  /**
   * Get agent recommendations using the compatibility route.
   */
  async getAgentRecommendations(params?: {
    domain?: string;
    limit?: number;
  }): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/agents/recommend', { params });
  }

  /**
   * Get agent leaderboard using the compatibility route.
   */
  async getAgentLeaderboard(params?: {
    domain?: string;
    limit?: number;
  }): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/agents/leaderboard', { params });
  }

  /**
   * Compare two agents' performance.
   *
   * @param agent1 - First agent name
   * @param agent2 - Second agent name
   * @returns Comparison data
   */
  async compareAgents(agent1: string, agent2: string): Promise<AgentComparison> {
    return this.client.compareAgents([agent1, agent2]);
  }

  /**
   * Get agent metadata (model info, capabilities).
   */
  async getMetadata(name: string): Promise<Record<string, unknown>> {
    return this.client.getAgentMetadata(name);
  }

  /**
   * Get agent introspection data (self-awareness metrics).
   */
  async getIntrospection(name: string): Promise<Record<string, unknown>> {
    return this.client.getAgentIntrospection(name);
  }

  /**
   * Get consolidated leaderboard view with all tabs.
   */
  async getLeaderboardView(): Promise<Record<string, unknown>> {
    return this.client.getLeaderboardView();
  }

  /**
   * Get recent matches across all agents.
   */
  async getRecentMatches(params?: { limit?: number }): Promise<{ matches: unknown[] }> {
    return this.client.getRecentMatches(params);
  }

  /**
   * Get recent position flips across all agents.
   */
  async getRecentFlips(params?: { limit?: number }): Promise<{ flips: unknown[] }> {
    return this.client.getRecentFlips(params);
  }

  /**
   * Get flip summary data for dashboard display.
   */
  async getFlipsSummary(): Promise<Record<string, unknown>> {
    return this.client.getFlipsSummary();
  }

  /**
   * Get agents ranked by calibration score.
   */
  async getCalibrationLeaderboard(): Promise<{ agents: Array<{ name: string; score: number }> }> {
    return this.client.getCalibrationLeaderboard();
  }

  // ===========================================================================
  // Agent Profile & Identity (matching Python SDK)
  // ===========================================================================

  /**
   * Get agent's persona configuration.
   *
   * @param name - Agent name
   * @returns Persona configuration
   */
  async getPersona(name: string): Promise<AgentPersona> {
    return this.client.request<AgentPersona>(
      'GET',
      `/api/agent/${encodeURIComponent(name)}/persona`
    );
  }

  /**
   * Delete agent's custom persona.
   *
   * @param name - Agent name
   * @returns Deletion result
   */
  async deletePersona(name: string): Promise<{ success: boolean; message: string }> {
    return this.client.request<{ success: boolean; message: string }>(
      'DELETE',
      `/api/agent/${encodeURIComponent(name)}/persona`
    );
  }

  /**
   * Get agent's grounded (evidence-based) persona with performance metrics.
   *
   * @param name - Agent name
   * @returns Grounded persona with ELO and performance data
   */
  async getGroundedPersona(name: string): Promise<GroundedPersona> {
    return this.client.request<GroundedPersona>(
      'GET',
      `/api/agent/${encodeURIComponent(name)}/grounded-persona`
    );
  }

  /**
   * Get agent's identity prompt.
   *
   * @param name - Agent name
   * @returns Identity prompt for the agent
   */
  async getIdentityPrompt(name: string): Promise<IdentityPrompt> {
    return this.client.request<IdentityPrompt>(
      'GET',
      `/api/agent/${encodeURIComponent(name)}/identity-prompt`
    );
  }

  // ===========================================================================
  // Agent Analytics (matching Python SDK)
  // ===========================================================================

  /**
   * Get agent's accuracy metrics.
   *
   * @param name - Agent name
   * @returns Accuracy metrics including position accuracy by domain
   */
  async getAccuracy(name: string): Promise<AgentAccuracy> {
    return this.client.request<AgentAccuracy>(
      'GET',
      `/api/agent/${encodeURIComponent(name)}/accuracy`
    );
  }

  // ===========================================================================
  // Agent Rankings
  // ===========================================================================

  /**
   * Get agent rankings.
   *
   * @param options - Ranking filter options
   * @returns List of agent rankings
   */
  async getRankings(options: {
    limit?: number;
    offset?: number;
    domain?: string;
    minDebates?: number;
    sortBy?: 'elo' | 'wins' | 'win_rate' | 'recent_activity';
    order?: 'asc' | 'desc';
  } = {}): Promise<{ rankings: Array<{ agent: string; elo: number; rank: number }> }> {
    const params: Record<string, unknown> = {
      limit: options.limit ?? 50,
      offset: options.offset ?? 0,
      sort_by: options.sortBy ?? 'elo',
      order: options.order ?? 'desc',
    };
    if (options.domain) {
      params.domain = options.domain;
    }
    if (options.minDebates !== undefined) {
      params.min_debates = options.minDebates;
    }
    return this.client.request<{ rankings: Array<{ agent: string; elo: number; rank: number }> }>(
      'GET',
      '/api/v1/rankings',
      { params }
    );
  }

  /**
   * Get head-to-head comparison between two agents.
   */
  async getHeadToHeadStats(agentId: string, opponentId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/agent/${agentId}/head-to-head/${opponentId}`) as Promise<Record<string, unknown>>;
  }

  /**
   * Get opponent briefing for an agent matchup.
   */
  async getOpponentBriefingReport(agentId: string, opponentId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/agent/${agentId}/opponent-briefing/${opponentId}`) as Promise<Record<string, unknown>>;
  }

  // ===========================================================================
  // Agent History and Performance
  // ===========================================================================

  /**
   * Get an agent's match history with optional pagination.
   */
  async getHistory(name: string, params?: Record<string, unknown>): Promise<{ matches: unknown[] }> {
    return this.client.getAgentHistory(name, params);
  }

  /**
   * Get an agent's performance metrics.
   */
  async getPerformance(name: string): Promise<AgentPerformance> {
    return this.client.getAgentPerformance(name);
  }

  /**
   * Get an agent's calibration data.
   */
  async getCalibration(name: string): Promise<AgentCalibration> {
    return this.client.getAgentCalibration(name);
  }

  // ===========================================================================
  // ELO and Rankings (extended)
  // ===========================================================================

  /**
   * Get an agent's ELO rating and history.
   */
  async getElo(name: string): Promise<{ agent: string; elo: number; history: Array<{ date: string; elo: number }> }> {
    return this.client.getAgentElo(name);
  }

  /**
   * Update an agent's ELO rating.
   *
   * @param name - Agent name
   * @param eloChange - Amount to change ELO by
   * @param options - Additional metadata
   */
  async updateElo(name: string, eloChange: number, options?: {
    debateId?: string;
    reason?: string;
  }): Promise<Record<string, unknown>> {
    return this.client.request(
      'POST',
      `/api/v1/agents/${encodeURIComponent(name)}/elo`,
      {
        body: {
          elo_change: eloChange,
          debate_id: options?.debateId,
          reason: options?.reason,
        },
      }
    );
  }

  /**
   * Compare multiple agents' performance.
   *
   * @param agents - Array of agent names to compare
   */
  async compare(agents: string[]): Promise<AgentComparison> {
    return this.client.compareAgents(agents);
  }

  // ===========================================================================
  // Team Selection
  // ===========================================================================

  /**
   * Select a team of agents for a task.
   *
   * @param taskType - Description of the task
   * @param teamSize - Number of agents to select
   * @param strategy - Selection strategy
   */
  async selectTeam(
    taskType: string,
    teamSize: number,
    strategy: 'balanced' | 'diverse' | 'competitive' | 'specialized' = 'balanced'
  ): Promise<TeamSelection> {
    const weights: Record<string, { diversity: number; quality: number }> = {
      balanced: { diversity: 0.5, quality: 0.5 },
      diverse: { diversity: 0.8, quality: 0.2 },
      competitive: { diversity: 0.2, quality: 0.8 },
      specialized: { diversity: 0.0, quality: 1.0 },
    };
    const w = weights[strategy] ?? weights.balanced;
    return this.client.selectTeam({
      task_type: taskType,
      team_size: teamSize,
      diversity_weight: w.diversity,
      quality_weight: w.quality,
    });
  }

  // ===========================================================================
  // Relationships (extended)
  // ===========================================================================

  /**
   * Get an agent's relationships (alias for getNetwork).
   */
  async getRelationships(name: string): Promise<AgentNetwork> {
    return this.client.getAgentNetwork(name);
  }

  /**
   * Get the relationship between two specific agents.
   */
  async getRelationship(agentA: string, agentB: string): Promise<AgentRelationship> {
    return this.client.getAgentRelationship(agentA, agentB);
  }

  /**
   * Get an agent's reputation score.
   */
  async getReputation(name: string): Promise<{ reputation: number | null }> {
    return this.client.getAgentReputation(name);
  }

  // ===========================================================================
  // Registration and Lifecycle
  // ===========================================================================

  /**
   * Register a new agent.
   *
   * @param agentId - Unique agent identifier
   * @param options - Registration options
   */
  async register(agentId: string, options?: {
    capabilities?: string[];
    model?: string;
    provider?: string;
    metadata?: Record<string, unknown>;
  }): Promise<Record<string, unknown>> {
    return this.client.request(
      'POST',
      '/api/v1/control-plane/agents',
      {
        body: {
          agent_id: agentId,
          capabilities: options?.capabilities,
          model: options?.model,
          provider: options?.provider,
          metadata: options?.metadata ?? {},
        },
      }
    );
  }

  /**
   * Unregister an agent.
   */
  async unregister(agentId: string): Promise<Record<string, unknown>> {
    return this.client.request(
      'DELETE',
      `/api/v1/control-plane/agents/${encodeURIComponent(agentId)}`
    );
  }

  /**
   * Send a heartbeat for an agent.
   */
  async heartbeat(agentId: string, status: string): Promise<Record<string, unknown>> {
    return this.client.request(
      'POST',
      `/api/v1/control-plane/agents/${encodeURIComponent(agentId)}/heartbeat`,
      { body: { status } }
    );
  }

  // ===========================================================================
  // Agent Configurations (YAML-based)
  // ===========================================================================

  /**
   * List available YAML agent configurations.
   *
   * @param options - Optional filters
   * @param options.priority - Filter by priority (low, normal, high, critical)
   * @param options.role - Filter by role (proposer, critic, synthesizer, judge)
   */
  async listConfigs(options?: { priority?: string; role?: string }): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/agents/configs', { params: options });
  }

  /**
   * Get a specific agent configuration by name.
   *
   * @param configName - Name of the agent configuration
   */
  async getConfig(configName: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/agents/configs/${encodeURIComponent(configName)}`);
  }

  /**
   * Search agent configurations by expertise, capability, or tag.
   *
   * @param options - Search filters
   */
  async searchConfigs(options?: { q?: string; expertise?: string; capability?: string; tag?: string }): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/agents/configs/search', { params: options });
  }

  /**
   * Create an agent from a named YAML configuration.
   *
   * @param configName - Name of the configuration to instantiate
   */
  async createFromConfig(configName: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/agents/configs/${encodeURIComponent(configName)}/create`);
  }

  /**
   * Reload all agent configurations from disk. Requires admin role.
   */
  async reloadConfigs(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/agents/configs/reload');
  }
}
